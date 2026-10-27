"""Running the studies of the Simulate workspace: their settings and engine requests, their state, and the values the 3D view draws.

A simulation is a job of the run worker (``RunWorker.start_simulation``) of one stage, ``simulate``, outside the pipeline's stages:
it sends one ``check`` request per study that can run and never reads or writes a stage record. A study's result is in
``simulate/<id>`` (``check_points.npz``, ``check_values.npz`` and, written last, ``check_summary.json``); the summary records the
files and settings it was computed from (``solar_check.simulate_study``), which ``study_state`` compares with the files now.
This module reads the result files itself: importing ``solar_check`` imports torch, which the service does not import until a run.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import numpy as np

from ..check_settings import CHECK_METRICS, CheckSettings, build_check_settings
from ..engine_requests import CheckRequest
from ..errors import ConfigError
from ..pydantic_schemas import UserConfig, resolve_grid_step
from ..stage_settings import stage_folder
from .api_models import StudyEntry, StudyState
from .criteria import OPTIONAL_SERVICE_PATHS, SERVICE_PATHS
from .projects import RUN_FOLDER, ProjectStore
from .stage_records import envelope_voxel_size
from .studies import joined_study_surfaces_path, study_folder

SIMULATE_STAGE = "simulate"     # the one stage of a simulation, not one of PIPELINE_STAGES
# The result files as solar_check names them (a test compares them).
POINTS_FILE = "check_points.npz"
VALUES_FILE = "check_values.npz"
SUMMARY_FILE = "check_summary.json"
OPEN_COLUMN = "open"            # the column without any geometry; the others are geometries
HEADER_ALIGNMENT_BYTES = 4      # the values header is padded so the float32 arrays after it start aligned
# The settings of the check that come from the project's settings, not the study's: the shared ones and, for those a criterion
# holds (time_basis, min_altitude, rays_per_patch), the first criterion's.
PROJECT_SETTING_KEYS = ("north_deg", "time_basis", "min_altitude", "ray_length", "rays_per_patch")
# The geometries a run builds and the stage folder whose manifest names each one's mesh, as solar_check.run_geometries reads them.
BUILT_GEOMETRY_STAGES = (("envelope", "exporting"), ("massing", "massing"))
ADD_TEST_SURFACES = "Add test surfaces"
ADD_MAX_VOLUME = "Add a maximum volume"
ADD_WEATHER_FILE = "Add a weather file"
NO_STUDY = "Add a study to run."


def study_settings(store: ProjectStore, name: str, study: StudyEntry) -> CheckSettings:
    """The check settings of a study: the project's (PROJECT_SETTING_KEYS, and the test point spacing of the carving), the
    study's metric and settings, and the weather file when the metric reads one and the project has it.

    Raises ConfigError, naming the fields, when they are not valid (a metric that needs the weather file and has none among them).
    """
    project_settings = store.read_settings(name)
    voxel_size = float(project_settings.get("voxel_size") or UserConfig.model_fields["voxel_size"].default)
    values = {key: project_settings[key] for key in PROJECT_SETTING_KEYS if project_settings.get(key) is not None}
    spec = CHECK_METRICS.get(study.metric)
    if study.metric != "sun_hours":
        values.pop("time_basis", None)      # the other metrics read the weather file's hours, in local standard time
    weather_path = store.weather_file_path(name)
    if spec is not None and spec.needs_epw and weather_path is not None:
        values["epw_path"] = str(weather_path)
    values.update(study.settings, metric=study.metric,
                  sample_spacing=resolve_grid_step(project_settings.get("grid_step"), voxel_size))
    return build_check_settings(values)


def tracing_voxel_size(store: ProjectStore, name: str) -> float:
    """The surface tolerance of the envelope and the massing: the voxel size the envelope on disk was built with, the project's
    voxel size when that is not known."""
    built = envelope_voxel_size(store, name)
    if built is not None:
        return float(built)
    return float(store.read_settings(name).get("voxel_size") or UserConfig.model_fields["voxel_size"].default)


def refusal_of(store: ProjectStore, name: str, study: StudyEntry) -> str | None:
    """Why the study cannot run, as the label the app shows; None when it can."""
    project_folder = store.open(name)
    if not study.test_surface_files or not (project_folder / joined_study_surfaces_path(study.id)).is_file():
        return ADD_TEST_SURFACES
    if not (project_folder / SERVICE_PATHS["max_volume_path"]).is_file():
        return ADD_MAX_VOLUME
    spec = CHECK_METRICS.get(study.metric)
    if spec is not None and spec.needs_epw and store.weather_file_path(name) is None:
        return ADD_WEATHER_FILE
    try:
        study_settings(store, name, study)
    except ConfigError as error:
        return error.errors[0].message if error.errors else str(error)
    return None


def study_request(store: ProjectStore, name: str, study: StudyEntry, device: str = "auto") -> CheckRequest:
    """The engine request that runs the study into simulate/<id>: its joined test surface file, the joined maximum volume, the run
    folder (whose envelope and massing are traced when built, current in Design or not), the context and terrain when they exist.

    Raises ConfigError when the study's settings are not valid (refusal_of says so first).
    """
    project_folder = store.open(name)
    optional_paths = {key: str(project_folder / path) for key, path in OPTIONAL_SERVICE_PATHS.values() if (project_folder / path).is_file()}
    return CheckRequest(
        cmd="check", test_surface_path=str(project_folder / joined_study_surfaces_path(study.id)),
        out_dir=str(study_folder(project_folder, study.id)), settings=study_settings(store, name, study).model_dump(),
        max_volume_path=str(project_folder / SERVICE_PATHS["max_volume_path"]), run_folder=str(project_folder / RUN_FOLDER),
        voxel_size=tracing_voxel_size(store, name), device=device, **optional_paths)


def study_state(store: ProjectStore, name: str, study: StudyEntry) -> tuple[StudyState, str | None]:
    """The state of a study and, when it is refused, why (refusal_of).

    ``not_run`` without a result; ``out_of_date`` when a file the result was computed from changed (its size or time), appeared or
    went (the envelope or the massing built or removed), when its settings changed, or when the envelope's voxel size did; else
    ``current``.
    """
    reason = refusal_of(store, name, study)
    if reason is not None:
        return "refused", reason
    summary = read_summary(study_folder(store.open(name), study.id))
    if summary is None:
        return "not_run", None
    return ("out_of_date" if _is_out_of_date(summary, study_request(store, name, study)) else "current"), None


def result_geometries(store: ProjectStore, name: str, study_id: str) -> list[str]:
    """The geometries of the study's last result in its column order (max_volume, then envelope and massing when they were built);
    none without a result."""
    summary = read_summary(study_folder(store.open(name), study_id))
    if summary is None:
        return []
    return [column for column in summary.get("columns", {}) if column != OPEN_COLUMN]


def read_summary(folder: Path) -> dict | None:
    """The summary of the result in *folder*; None when one of its three files is missing or the summary cannot be read."""
    if not all((folder / file_name).is_file() for file_name in (POINTS_FILE, VALUES_FILE, SUMMARY_FILE)):
        return None
    try:
        summary = json.loads((folder / SUMMARY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return summary if isinstance(summary, dict) else None


def _file_state(path: str | Path | None) -> tuple[int, int] | None:
    """The size and modification time of a file, None when there is no path or no file."""
    if path is None:
        return None
    try:
        status = Path(path).stat()
    except OSError:
        return None
    return status.st_size, status.st_mtime_ns


def _recorded_state(fingerprint) -> tuple[int, int] | None:
    """The size and time a summary recorded for a file (solar_check.file_fingerprint), None for none."""
    if not isinstance(fingerprint, dict):
        return None
    return fingerprint.get("size"), fingerprint.get("modified_ns")


def _built_geometry_paths(run_folder: Path) -> dict[str, Path]:
    """The meshes of the envelope and the massing that the run folder has now, by geometry name, as run_geometries finds them."""
    paths = {}
    for geometry, stage in BUILT_GEOMETRY_STAGES:
        folder = stage_folder(run_folder, stage)
        try:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        mesh_name = manifest.get("mesh_path") if isinstance(manifest, dict) else None
        if isinstance(mesh_name, str) and (folder / mesh_name).is_file():
            paths[geometry] = folder / mesh_name
    return paths


def _is_out_of_date(summary: dict, request: CheckRequest) -> bool:
    """Whether the result of *summary* differs from what *request* would compute now."""
    fingerprints = summary.get("fingerprints")
    if not isinstance(fingerprints, dict):
        return True
    settings = CheckSettings(**request.settings)
    digest = hashlib.sha256(json.dumps(settings.model_dump(), sort_keys=True).encode("utf-8")).hexdigest()
    if fingerprints.get("settings_digest") != digest:
        return True
    files_now = {"test_surface": request.test_surface_path, "max_volume": request.max_volume_path,
                 "weather": settings.epw_path if settings.spec.needs_epw else None,
                 "context": request.context_path, "terrain": request.terrain_path}
    if any(_recorded_state(fingerprints.get(key)) != _file_state(path) for key, path in files_now.items()):
        return True
    recorded_geometries = fingerprints.get("geometries")
    built = _built_geometry_paths(Path(request.run_folder))
    if not isinstance(recorded_geometries, dict) or set(recorded_geometries) != set(built):
        return True
    if any(_recorded_state(recorded_geometries[geometry]) != _file_state(path) for geometry, path in built.items()):
        return True
    columns = summary.get("columns", {})
    return any(columns.get(geometry, {}).get("surface_tolerance_m") != request.voxel_size for geometry in built)


def study_values(folder: Path) -> bytes | None:
    """The patches and values of the result in *folder* for the 3D view, all numbers little-endian; None without a result.

    * ``uint32`` length n of the header in bytes;
    * the header as UTF-8 JSON (``frame``: world coordinates the corners are relative to, ``point_count``, ``columns``: the column
      names in the order of the value arrays, ``unit``), padded with spaces to a multiple of 4;
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
            columns = [column for column in summary.get("columns", {}) if column in values.files]
            arrays = [values[column].astype("<f4") for column in columns]
    except (OSError, ValueError, KeyError):
        return None
    header = {"frame": frame, "point_count": int(len(quads)), "columns": columns, "unit": summary.get("unit")}
    header_bytes = json.dumps(header).encode("utf-8")
    header_bytes += b" " * (-len(header_bytes) % HEADER_ALIGNMENT_BYTES)
    return b"".join([struct.pack("<I", len(header_bytes)), header_bytes, quads.tobytes(), *(array.tobytes() for array in arrays)])


def no_study_can_run_message(refusals: list[tuple[StudyEntry, str]]) -> str:
    """The refusal of a simulation that has no study that can run: each study's name and reason, or that there is none."""
    if not refusals:
        return NO_STUDY
    return "No study can run. " + " ".join(f"{study.name}: {reason}." for study, reason in refusals)
