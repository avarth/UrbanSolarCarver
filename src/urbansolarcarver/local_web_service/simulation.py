"""Running the studies of the Simulate workspace: their settings and engine requests, their state, and the values the 3D view draws.

A simulation is a job of the run worker (``RunWorker.start_simulation``) of one stage, ``simulate``, outside the pipeline's stages:
it sends one ``check`` request per study that can run and never reads or writes a stage record. A study's result is in
``simulate/<id>`` (``check_points.npz``, ``check_values.npz`` and, written last, ``check_summary.json``); the summary records the
files and settings it was computed from (``solar_check.simulate_study``), which ``study_state`` compares with the files now. A study
the engine refused leaves ``refusal.json`` there instead, with the message and the same record of what it was given.
The file names and the lookup of a run's geometries are ``check_files``'s, which the engine uses too; this module does not import
``solar_check``, which imports torch.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

from ..check_files import POINTS_FILE, SKY_FILE, SUMMARY_FILE, VALUES_FILE, run_geometry_files
from ..check_settings import CHECK_METRICS, CheckSettings, build_check_settings, settings_digest
from ..engine_requests import CheckRequest
from ..errors import ConfigError
from ..pydantic_schemas import UserConfig, resolve_grid_step
from .api_models import SkyDome, StudyEntry, StudyState
from .criteria import OPTIONAL_SERVICE_PATHS, SERVICE_PATHS, active_criteria
from .projects import RUN_FOLDER, ProjectStore
from .stage_records import envelope_voxel_size
from .studies import GEOMETRY, SAMPLE_GEOMETRY, SURFACES_FROM, joined_study_surfaces_path, study_folder

SIMULATE_STAGE = "simulate"     # the one stage of a simulation, not one of PIPELINE_STAGES
REFUSAL_FILE = "refusal.json"   # in simulate/<id>: the engine refused the study with these inputs
OPEN_COLUMN = "open"            # the column without any geometry; the others are geometries
HEADER_ALIGNMENT_BYTES = 4      # the values header is padded so the float32 arrays after it start aligned
# The check settings that come from the project's shared settings; the spacing comes from voxel_size and grid_step.
SHARED_SETTING_KEYS = ("north_deg", "ray_length")
# The rays per sky patch when the project has no criterion to take them from.
DEFAULT_RAYS_PER_PATCH = CheckSettings.model_fields["rays_per_patch"].default
# The input files a result records by key (fingerprints in the summary), besides the geometries of the run.
RECORDED_FILE_KEYS = ("test_surface", "max_volume", "weather", "context", "terrain")
ADD_STUDY_SURFACES = "Add study surfaces"
ADD_MAX_VOLUME = "Add a maximum volume"
# A study that samples the surroundings or the terrain (its settings' surfaces_from) waits for the project's file of that role.
ADD_SOURCE_FILE = {"context": "Add surroundings", "terrain": "Add a terrain"}
ADD_WEATHER_FILE = "Add a weather file"
# A study on the envelope or the massing waits until Carve has built it.
BUILD_ENVELOPE = "Build the envelope in Carve"
BUILD_MASSING = "Build the massing in Carve"
BUILD_GEOMETRY = {"envelope": BUILD_ENVELOPE, "massing": BUILD_MASSING}
# The share of the scene's longer plan side that is the radius of the compass ring and the ground disc (app: viewer/sky_dome.ts,
# HEMISPHERE_RADIUS_SHARE); the radius is at least the scene's height.
SCENE_RADIUS_SHARE = 0.75
TEST_SURFACES_ROLE = "test_surfaces"
NO_STUDY = "Add a study to run."


def _rays_criterion(store: ProjectStore, name: str) -> str | None:
    """The criterion whose rays_per_patch the studies trace with: the first that is on, the first when none is, None without one."""
    criteria = store.criteria(name)
    chosen = (active_criteria(criteria) or criteria or [None])[0]
    return chosen.id if chosen is not None else None


def study_settings(store: ProjectStore, name: str, study: StudyEntry) -> CheckSettings:
    """The check settings of a study: north and ray length from the shared settings, the test point spacing of the carving,
    rays_per_patch of the first criterion that is on (the first criterion when none is, 4 without one), the study's metric and
    settings (the period, its time basis, the mode settings), and the weather file when the metric reads one and the project has
    it. The lowest sun altitude is CheckSettings' default.

    Raises ConfigError, naming the fields, when they are not valid (a metric that needs the weather file and has none among them).
    """
    criterion_id = _rays_criterion(store, name)
    project_settings = store.read_settings(name, criterion_id)
    voxel_size = float(project_settings.get("voxel_size") or UserConfig.model_fields["voxel_size"].default)
    values = {key: project_settings[key] for key in SHARED_SETTING_KEYS if project_settings.get(key) is not None}
    values["rays_per_patch"] = (project_settings.get("rays_per_patch") if criterion_id is not None else None) or DEFAULT_RAYS_PER_PATCH
    values["sample_spacing"] = resolve_grid_step(project_settings.get("grid_step"), voxel_size)     # unless the study has its own
    spec = CHECK_METRICS.get(study.metric)
    weather_path = store.weather_file_path(name)
    if spec is not None and spec.needs_epw and weather_path is not None:
        values["epw_path"] = str(weather_path)
    values.update(study.settings, metric=study.metric)
    return build_check_settings(values)


# The bounds of each file input_bounds read, by its path, size and time: the list of studies asks for the circle of every study that
# samples the ground at each read, and the files rarely change.
_FILE_BOUNDS: dict[tuple[str, int, int], np.ndarray | None] = {}


def _file_bounds(path: Path) -> np.ndarray | None:
    """The bounds of the mesh file at *path*, None when it cannot be read or has no vertices; read again only when it changed."""
    import trimesh
    state = _file_state(path)
    if state is None:
        return None
    key = (str(path), state[0], state[1])
    if key not in _FILE_BOUNDS:
        try:
            mesh = trimesh.load(str(path), force="mesh")
            _FILE_BOUNDS[key] = np.asarray(mesh.bounds, dtype=float) if len(getattr(mesh, "vertices", ())) else None
        except Exception:           # unreadable: the view does not draw it either
            _FILE_BOUNDS[key] = None
    return _FILE_BOUNDS[key]


def input_bounds(store: ProjectStore, name: str) -> list[list[float]] | None:
    """The bounds of the maximum volume and every file of the test surfaces role together, as the 3D view loads them for its compass
    ring (app: ProjectWorkspace.tsx, boundsOf([maxVolume, testSurfaces])); None without a maximum volume. A file that cannot be read
    is left out, as the view leaves out a file it cannot draw. Each file is read once while it does not change (_file_bounds)."""
    max_volume = _file_bounds(store.open(name) / SERVICE_PATHS["max_volume_path"])
    if max_volume is None:
        return None
    bounds = max_volume
    for info in store.input_files(name, TEST_SURFACES_ROLE):
        found = _file_bounds(store.input_file_path(name, TEST_SURFACES_ROLE, info.name))
        if found is not None:
            bounds = np.array([np.minimum(bounds[0], found[0]), np.maximum(bounds[1], found[1])])
    return bounds.tolist()


def scene_circle(store: ProjectStore, name: str) -> tuple[float, float, float] | None:
    """The centre (x, y) and radius of the compass ring, which the ground disc of a study follows: the middle of the plan of
    input_bounds, and SCENE_RADIUS_SHARE times their longer plan side, at least their height (app: viewer/sky_dome.ts,
    sceneHemisphere). None without a maximum volume."""
    bounds = input_bounds(store, name)
    if bounds is None:
        return None
    (x0, y0, z0), (x1, y1, z1) = bounds
    radius = max(SCENE_RADIUS_SHARE * max(x1 - x0, y1 - y0), z1 - z0)
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0, float(radius))


def tracing_voxel_size(store: ProjectStore, name: str) -> float:
    """The surface tolerance of the envelope and the massing when the run folder's manifests do not tell it: the voxel size the
    envelope on disk was built with, the project's voxel size when that is not known."""
    built = envelope_voxel_size(store, name)
    if built is not None:
        return float(built)
    return float(store.read_settings(name).get("voxel_size") or UserConfig.model_fields["voxel_size"].default)


def refusal_of(store: ProjectStore, name: str, study: StudyEntry) -> str | None:
    """Why the study cannot run, as the label the app shows; None when it can. A study samples its files, the sources of its
    surfaces_from, the faces of its geometry (sample_geometry, not for none), or several: it needs one of them, the project's file
    of each source it names, and its geometry built when that is the envelope or the massing."""
    project_folder = store.open(name)
    sources = study.settings.get(SURFACES_FROM) or []
    geometry = study.settings.get(GEOMETRY, "max_volume")
    samples_geometry = bool(study.settings.get(SAMPLE_GEOMETRY)) and geometry != "none"
    has_files = bool(study.test_surface_files) and (project_folder / joined_study_surfaces_path(study.id)).is_file()
    if (study.test_surface_files and not has_files) or not (has_files or sources or samples_geometry):
        return ADD_STUDY_SURFACES
    for source, label in ADD_SOURCE_FILE.items():
        if source in sources and not (project_folder / OPTIONAL_SERVICE_PATHS[source][1]).is_file():
            return label
    if not (project_folder / SERVICE_PATHS["max_volume_path"]).is_file():
        return ADD_MAX_VOLUME
    if geometry in BUILD_GEOMETRY and not run_geometry_files(project_folder / RUN_FOLDER, only=geometry):
        return BUILD_GEOMETRY[geometry]
    spec = CHECK_METRICS.get(study.metric)
    if spec is not None and spec.needs_epw and store.weather_file_path(name) is None:
        return ADD_WEATHER_FILE
    try:
        study_settings(store, name, study)
    except ConfigError as error:
        return error.errors[0].message if error.errors else str(error)
    return None


def study_request(store: ProjectStore, name: str, study: StudyEntry, device: str = "auto") -> CheckRequest:
    """The engine request that runs the study into simulate/<id>: its joined test surface file (None when it has no files), the
    joined maximum volume, the run folder (whose envelope or massing a study on it traces, current in Carve or not), the context and
    terrain when they exist, and the ground disc (scene_circle) when the study samples the ground.

    Raises ConfigError when the study's settings are not valid (refusal_of says so first).
    """
    project_folder = store.open(name)
    optional_paths = {key: str(project_folder / path) for key, path in OPTIONAL_SERVICE_PATHS.values() if (project_folder / path).is_file()}
    test_surface_path = str(project_folder / joined_study_surfaces_path(study.id)) if study.test_surface_files else None
    settings = study_settings(store, name, study)
    ground_disc = scene_circle(store, name) if "ground" in settings.surfaces_from else None
    return CheckRequest(
        cmd="check", test_surface_path=test_surface_path,
        out_dir=str(study_folder(project_folder, study.id)), settings=settings.model_dump(), ground_disc=ground_disc,
        max_volume_path=str(project_folder / SERVICE_PATHS["max_volume_path"]), run_folder=str(project_folder / RUN_FOLDER),
        voxel_size=tracing_voxel_size(store, name), device=device, **optional_paths)


def study_state(store: ProjectStore, name: str, study: StudyEntry) -> tuple[StudyState, str | None]:
    """The state of a study and, when it is refused, why.

    ``refused`` when refusal_of says so, or when the engine refused it with the inputs it would be given now (refusal.json);
    ``not_run`` without a result; ``out_of_date`` when a file the result was computed from changed (its size or time), appeared or
    went (the envelope or the massing built or removed), when its settings changed, or when the surface tolerance of a geometry
    did; else ``current``.
    """
    reason = refusal_of(store, name, study)
    if reason is not None:
        return "refused", reason
    folder = study_folder(store.open(name), study.id)
    inputs_now = _inputs_of_request(study_request(store, name, study))
    refusal = _read_json(folder / REFUSAL_FILE)
    if refusal is not None and refusal.get("inputs") == inputs_now:
        return "refused", str(refusal.get("message", ""))
    summary = read_summary(folder)
    if summary is None:
        return "not_run", None
    return ("out_of_date" if _inputs_of_summary(summary) != inputs_now else "current"), None


def record_refusal(request: CheckRequest, message: str) -> None:
    """Keep the engine's refusal of a study with what it was given, so study_state shows it until one of those changes."""
    folder = Path(request.out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / REFUSAL_FILE).write_text(json.dumps({"message": message, "inputs": _inputs_of_request(request)}), encoding="utf-8")


def forget_refusal(request: CheckRequest) -> None:
    """Remove the refusal of a study the engine has now run."""
    (Path(request.out_dir) / REFUSAL_FILE).unlink(missing_ok=True)


def result_geometries(store: ProjectStore, name: str, study_id: str) -> list[str]:
    """The geometries of the study's last result in its column order (max_volume, then envelope and massing when they were built);
    none without a result."""
    summary = read_summary(study_folder(store.open(name), study_id))
    if summary is None:
        return []
    return [column for column in summary.get("columns", {}) if column != OPEN_COLUMN]


def _read_json(path: Path) -> dict | None:
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return content if isinstance(content, dict) else None


def read_summary(folder: Path) -> dict | None:
    """The summary of the result in *folder*; None when one of its three files is missing or the summary cannot be read."""
    if not all((folder / file_name).is_file() for file_name in (POINTS_FILE, VALUES_FILE, SUMMARY_FILE)):
        return None
    return _read_json(folder / SUMMARY_FILE)


def _file_state(path: str | Path | None) -> list[int] | None:
    """The size and modification time of a file, None when there is no path or no file (a list, as JSON reads it back)."""
    if path is None:
        return None
    try:
        status = Path(path).stat()
    except OSError:
        return None
    return [status.st_size, status.st_mtime_ns]


def _recorded_state(fingerprint) -> list[int] | None:
    """The size and time a summary recorded for a file (check_files.file_fingerprint), None for none. The path is left out, so
    moving the project's folder keeps a result current."""
    if not isinstance(fingerprint, dict):
        return None
    return [fingerprint.get("size"), fingerprint.get("modified_ns")]


def _inputs_of_request(request: CheckRequest) -> dict:
    """What a result of *request* would be computed from, in the form _inputs_of_summary gives (plain JSON values): the settings
    digest, the size and time of each input file, and of each geometry the run folder has built with its surface tolerance, found
    as the engine finds them (check_files.run_geometry_files)."""
    settings = CheckSettings(**request.settings)
    paths = {"test_surface": request.test_surface_path, "max_volume": request.max_volume_path,
             "weather": settings.epw_path if settings.spec.needs_epw else None,
             "context": request.context_path, "terrain": request.terrain_path}
    geometries = (run_geometry_files(request.run_folder, request.voxel_size, only=settings.geometry)
                  if settings.geometry in BUILD_GEOMETRY else [])
    return {"settings_digest": settings_digest(settings),
            "files": {key: _file_state(paths[key]) for key in RECORDED_FILE_KEYS},
            "geometries": {geometry.name: _file_state(geometry.path) for geometry in geometries},
            "surface_tolerances": {geometry.name: float(geometry.surface_tolerance) for geometry in geometries},
            "ground_disc": _rounded_disc(request.ground_disc)}


def _rounded_disc(disc) -> list[float] | None:
    """A ground disc (centre x, centre y, radius) rounded to a millimetre as the engine records it; None for none."""
    return None if disc is None else [round(float(value), 3) for value in disc]


def _inputs_of_summary(summary: dict) -> dict | None:
    """What the result of *summary* was computed from, as _inputs_of_request gives it; None when the summary does not record it."""
    fingerprints = summary.get("fingerprints")
    columns = summary.get("columns")
    if not isinstance(fingerprints, dict) or not isinstance(fingerprints.get("geometries"), dict) or not isinstance(columns, dict):
        return None
    geometries = fingerprints["geometries"]
    return {"settings_digest": fingerprints.get("settings_digest"),
            "files": {key: _recorded_state(fingerprints.get(key)) for key in RECORDED_FILE_KEYS},
            "geometries": {name: _recorded_state(fingerprint) for name, fingerprint in geometries.items()},
            "surface_tolerances": {name: (columns.get(name) or {}).get("surface_tolerance_m") for name in geometries},
            "ground_disc": fingerprints.get("ground_disc")}


def study_values(folder: Path) -> bytes | None:
    """The patches and values of the result in *folder* for the 3D view, all numbers little-endian; None without a result.

    * ``uint32`` length n of the header in bytes;
    * the header as UTF-8 JSON (``frame``: world coordinates the corners are relative to, ``point_count``, ``columns``: the column
      names in the order of the value arrays, ``unit``, ``geometry``: the geometry the result accounts for ("none" for nothing),
      ``geometry_point_count``: how many of the points, the last ones, are on the faces of that geometry), padded with spaces to a
      multiple of 4;
    * ``float32`` the four corners of each point's patch, x y z each, relative to ``frame``;
    * ``float32`` one value per point for each column.
    """
    summary = read_summary(folder)
    if summary is None:
        return None
    try:
        with np.load(folder / POINTS_FILE) as points, np.load(folder / VALUES_FILE) as values:
            frame = points["frame"].astype(float).tolist()
            quads = points["quads"].astype("<f4")
            geometry_point_count = int(points["geometry_point_count"]) if "geometry_point_count" in points.files else 0
            columns = [column for column in summary.get("columns", {}) if column in values.files]
            arrays = [values[column].astype("<f4") for column in columns]
    except (OSError, ValueError, KeyError):
        return None
    header = {"frame": frame, "point_count": int(len(quads)), "columns": columns, "unit": summary.get("unit"),
              "geometry": summary.get("geometry", "max_volume"), "geometry_point_count": geometry_point_count}
    header_bytes = json.dumps(header).encode("utf-8")
    header_bytes += b" " * (-len(header_bytes) % HEADER_ALIGNMENT_BYTES)
    return b"".join([struct.pack("<I", len(header_bytes)), header_bytes, quads.tobytes(), *(array.tobytes() for array in arrays)])


def study_sky_patches(folder: Path) -> SkyDome | None:
    """The 145 Tregenza patches with the value each carried in the result in *folder* (its check_sky.json), drawn as Design's
    sky dome is; None for a sun hours study."""
    try:
        weights = json.loads((folder / SKY_FILE).read_text(encoding="utf-8"))["weights"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    import torch
    from ..sky_patches import fetch_tregenza_patch_directions, tregenza_solid_angles
    directions = fetch_tregenza_patch_directions(torch.device("cpu")).numpy().tolist()
    if not isinstance(weights, list) or len(weights) != len(directions):
        return None
    return SkyDome(directions=directions, solid_angles=tregenza_solid_angles().tolist(), weights=[float(weight) for weight in weights])


def no_study_can_run_message(refusals: list[tuple[StudyEntry, str]]) -> str:
    """The refusal of a simulation that has no study that can run: each study's name and reason, or that there is none."""
    if not refusals:
        return NO_STUDY
    return "No study can run. " + " ".join(f"{study.name}: {reason}." for study, reason in refusals)
