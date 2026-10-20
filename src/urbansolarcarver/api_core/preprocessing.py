from __future__ import annotations
import json, logging, time
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, Union
import numpy as np
from ..load_config import user_config
from ._util import _resolve_cfg, dump_config_snapshot, ensure_diag, device_summary
from ..compute_device import resolve_compute_device
from ._stage_io import begin_stage, commit_manifest, new_run_id, stored_path
from ._diagnostics import (
    PreprocessingPlotInputs, score_statistics, warn_score_anomalies,
    write_preprocessing_diagnostics,
)
from .. import floor_plates
from ..pydantic_schemas import PreprocessingManifest
from ..errors import InputError
from ..run_context import Issue, RunContext, report_issue, stage_context
from ..stage_settings import PreprocessingSettings, RunOptions
from ..carving import carve_with_sky_patch_rays, carve_with_sun_rays, carve_with_planes
from ..io import load_meshes, validate_inputs
from ..sun import sample_period
from ..voxelization import voxelize
from ..surface_sampling import sample_surface
from ..mode_registry import MODES, MODES_NEEDING_PERIOD

log = logging.getLogger(__name__)

# Everything preprocessing writes into its folder, besides manifest.json.
_PREPROCESSING_OUTPUTS = (
    "scores.npy", "voxel_grid.npy", "patch_weights.npy", "test_points.npy",
    "test_normals.npy", "analysis_mesh.json", "footprint.json",
    "diagnostics/diagnostic.json", "diagnostics/config_snapshot.json",
    "diagnostics/score_histogram.png", "diagnostics/sky_patch_weights.png",
    "diagnostics/sky_patch_weights_intensity.png", "diagnostics/sky_patch_comparison.png",
)

@dataclass(frozen=True)
class PreprocessingResult:
    """Immutable record returned by :func:`preprocessing`.

    Carries paths to persisted artifacts and grid metadata so that downstream
    stages (thresholding, exporting) can locate them without re-computation.
    ``volume_path`` is the ``scores.npy`` file. The ``manifest_path``
    property points to the JSON manifest that the next stage reads; the
    object also implements ``__fspath__`` (returning that manifest path) so
    it can be passed directly as a path-like to :func:`thresholding`.
    """
    out_dir: Path
    volume_path: Path
    volume_shape: Tuple[int, int, int]
    dtype: str
    run_id: str
    device_info: str = ""
    issues: tuple[Issue, ...] = ()
    @property
    def manifest_path(self) -> Path:
       return self.out_dir / "manifest.json"
    def __fspath__(self) -> str:
        return str(self.manifest_path)

def _check_radiative_cooling_surface(norms: np.ndarray) -> None:
    """Raise InputError unless the test surfaces face mostly upward.

    The radiative_cooling view-factor weighting (cos θ / π) is only valid for
    surfaces facing the sky, so reject test surfaces whose mean normal is
    more than about 45° from vertical.
    """
    mean_normal = norms.mean(axis=0)
    mean_normal /= (np.linalg.norm(mean_normal) + 1e-12)
    z_component = float(mean_normal[2])
    if z_component < 0.7:  # cos(45.6°) = 0.7
        raise InputError(
            f"radiative_cooling mode requires a horizontal, upward-facing test surface "
            f"(mean normal Z-component = {z_component:.2f}, expected > 0.7). "
            f"This mode's view-factor weighting (cos θ / π) is only valid for "
            f"surfaces facing the sky. For vertical facades, use a different mode."
        )


def _max_volume_footprint(max_volume_mesh) -> list:
    """The plan projection of the max volume (world xy), for massing.

    Returns an empty list, and reports ``footprint_unreadable``, when the
    projection fails or covers no area; massing then uses the voxel footprint.
    """
    try:
        polygons = floor_plates.footprint_polygons(max_volume_mesh, (0.0, 0.0))
    except Exception as exc:  # a broken mesh must not fail the scoring run
        log.warning("preprocessing: could not project the maximum volume: %s", exc)
        polygons = []
    if not polygons:
        report_issue(
            "footprint_unreadable",
            "preprocessing: the maximum volume's footprint could not be computed; "
            "massing will use the voxel footprint",
        )
    return polygons


def _compute_raw_scores(voxel_grid, origin, extent, resolution, pts, norms,
                        settings: PreprocessingSettings, options: RunOptions,
                        point_weights=None):
    """Run the carver for ``settings.mode`` and return the per-voxel scores.

    Parameters
    ----------
    point_weights : np.ndarray (N,) | None
        Per-sample-point design weights (edge_taper); weighted modes only.

    Returns
    -------
    raw_scores : np.ndarray, float32, shape (X*Y*Z,)
        Flat scores in the grid's C order, in ``MODES[mode].score_unit``:
        time-based in m²·h, the weighted modes in patch-weight units times
        m² (kWh for irradiance and benefit, m² of fully hidden sky for
        daylight and radiative_cooling).
    scores_kind : {"violation_count", "weighted_sum"}
    patch_weights : np.ndarray | torch.Tensor | None
        Per-sky-patch weights (weighted modes only).
    """
    mode = settings.mode
    spec = MODES.get(mode)
    if spec is None:
        raise ValueError(
            f"Unknown mode '{mode}': not registered in mode_registry.MODES"
        )
    if mode in MODES_NEEDING_PERIOD:
        steps = settings.sun_steps_per_hour if mode == "time-based" else 1
        datetimes, hoys = sample_period(settings, steps_per_hour=steps)
    else:
        datetimes, hoys = [], []

    # Route by the registry's score_kind so that a new violation-count mode
    # without a carver raises here instead of falling through to the
    # weighted sky-patch carver.
    if spec.score_kind == "violation_count":
        if mode == "time-based":
            _carved, _ro, _rd, counts = carve_with_sun_rays(
                voxel_grid, origin, extent, resolution, pts, norms, settings,
                datetimes, return_counts=True, ray_batch_size=options.ray_batch_size,
            )
            # Each count is one (sample point, sun position) ray the voxel
            # blocks. A sample point stands for ~grid_step² of protected
            # surface and a sun position for 1/sun_steps_per_hour h, so the
            # score is shaded area x duration (m²·h): a numeric threshold
            # then means the same at any sampling density.
            counts = counts * (float(settings.grid_step) ** 2 / float(settings.sun_steps_per_hour))
        elif mode == "tilted_plane":
            _carved, _ro, _rd, counts = carve_with_planes(
                voxel_grid, origin, extent, resolution, pts, norms, settings,
                return_counts=True, ray_batch_size=options.ray_batch_size,
            )
        else:
            raise NotImplementedError(
                f"mode '{mode}' declares score_kind='violation_count' but has "
                f"no carver wired in _compute_raw_scores"
            )
        return counts.astype(np.float32), spec.score_kind, None

    # weighted_sum: all sky-patch modes share one carver.
    carve_out = carve_with_sky_patch_rays(
        voxel_grid, origin, extent, resolution, pts, norms, settings, hoys,
        point_weights=point_weights, ray_batch_size=options.ray_batch_size,
    )
    # Each blocked ray adds its patch weight (times its point's edge_taper
    # weight) per m² of protected surface; a sample point stands for
    # ~grid_step² of it, as in time-based above. The score is then the
    # weighted quantity the voxel blocks (kWh, or m² of fully hidden sky),
    # which does not change with the sample spacing.
    sample_area = float(settings.grid_step) ** 2
    raw_scores = np.asarray(carve_out.raw_voxel_scores, dtype=np.float32) * np.float32(sample_area)
    return raw_scores, spec.score_kind, carve_out.patch_weights


def preprocessing(
    cfg: Union[user_config, str, Path],
    out_dir: Union[str, Path]
) -> PreprocessingResult:
    """First stage of the 3-stage envelope pipeline: per-voxel obstruction scoring.

    Converts a maximum-volume mesh and a set of insolation test surfaces into
    a 3-D scalar field where each voxel carries a score indicating how much it
    blocks sun or sky from the test surfaces.  The steps are:

    1. Voxelization: the maximum-volume mesh is rasterized into a cubic
       occupancy grid with edge length ``cfg.voxel_size``.  This and the
       next two steps run in a local frame whose origin is the max volume's
       minimum corner; persisted coordinates are shifted back to world space.
    2. Surface sampling: the test surfaces are point-sampled (spacing
       ``cfg.grid_step``), giving test points with outward normals.  The
       test surface PLY file may contain several disjoint mesh components
       (e.g. separate facade panels, a ground plane and a courtyard, or a
       PV array).  All components are sampled and their ray contributions
       added into a single score grid.
    3. Ray casting: for every test point, rays are cast through the voxel
       grid according to the configured mode.  Each voxel that blocks a ray
       accumulates a weight that depends on the mode:

       * ``time-based``: sun-position rays for the configured analysis period;
         a voxel's score is the protected-surface area it shades times the
         duration, in m²·h (each sample point stands for ~grid_step² m²).
       * ``tilted_plane``: one ray per sample point at the plane angle; a
         non-zero score means the voxel lies on or above at least one plane.
       * sky-patch modes (``irradiance``, ``benefit``, ``daylight``,
         ``radiative_cooling``): rays go toward the sky patches, each
         patch carrying a mode-specific weight; a voxel's score is the sum
         of the weights of the rays it blocks times the area each sample
         point stands for (grid_step²): the solar energy it blocks in kWh
         (irradiance, benefit), or the sky it hides in m² of fully hidden
         sky (daylight, radiative_cooling; their weights sum to 1).

    Parameters
    ----------
    cfg : user_config | str | Path
        A validated ``user_config`` instance, or a filesystem path to a YAML /
        JSON configuration file that will be loaded and validated.
    out_dir : str | Path
        Output directory for this stage; created if it does not exist.
        Artifacts are written directly into it, diagnostics into its
        ``diagnostics/`` subfolder.

    Returns
    -------
    PreprocessingResult
        Frozen dataclass with paths and metadata for the completed stage.

    Raises
    ------
    InputError
        If the mesh or required EPW file is missing, the voxel grid is empty,
        no test-surface points are sampled, or, in radiative_cooling mode,
        the test surfaces do not face up.
    ConfigError
        If the grid is too large (more than
        ``grid_planning.MAX_GRID_VOXELS``, 500,000,000, checked before it is
        allocated).

    Persisted artifacts
    -------------------
    ``scores.npy``
        Flat ``float32`` array of length X*Y*Z (C order of the voxel grid)
        with raw obstruction scores; thresholding reshapes it.
    ``voxel_grid.npy``
        Occupancy grid (uint8, 1 = inside the max volume) so downstream
        stages can skip re-voxelization.
    ``footprint.json``
        The max volume's plan projection in world xy (``{"polygons": [{"exterior":
        [[x, y], ...], "holes": [...]}, ...]}``), which massing reads instead of
        the input mesh.  An empty list when the projection failed; massing then
        uses the voxel footprint.
    ``test_points.npy``, ``test_normals.npy``, ``analysis_mesh.json``
        Sample points (world coordinates), their normals, and the analysis
        mesh, for diagnostics and Grasshopper display.
    ``patch_weights.npy``
        Per-sky-patch weights (sky-patch modes only).
    ``manifest.json``
        Machine-readable manifest (``PreprocessingManifest``) recording a
        random ``run_id`` (new on every run), grid shape, world origin, voxel
        size, mode, score kind and score unit, and file paths relative to the
        manifest's folder.  Written last, so a failed run leaves no manifest.
    ``diagnostics/``
        ``diagnostic.json`` (summary statistics and wall/CPU timings),
        ``config_snapshot.json``, and, with ``cfg.diagnostic_plots``, the
        score histogram and sky-patch weight plots.
    """
    with stage_context("preprocessing") as context:
        conf = _resolve_cfg(cfg)
        settings = PreprocessingSettings.from_config(conf)
        options = RunOptions.from_config(conf)
        validate_inputs(settings)  # fail fast on missing mesh/EPW files
        # A run that fails midway must not leave the previous manifest pointing
        # at half-overwritten arrays: the manifest is written last.
        out_path = begin_stage(out_dir, _PREPROCESSING_OUTPUTS)
        # The snapshot holds the whole config, which the stage itself does not read.
        dump_config_snapshot(conf, ensure_diag(out_path))
        return _run_preprocessing(settings, options, out_path, context)


def _run_preprocessing(settings: PreprocessingSettings, options: RunOptions, out_path: Path,
                       context: RunContext) -> PreprocessingResult:
    """The computation of :func:`preprocessing`, from its own settings only.

    *out_path* is the stage folder, already cleared by :func:`begin_stage`.
    """
    _t0_wall = time.perf_counter()
    _t0_cpu = time.process_time()
    _step_times = {}
    def _mark(label):
        _step_times[label] = time.perf_counter() - _t0_wall

    resolved_device = resolve_compute_device(options.device)
    device_info = device_summary(resolved_device)
    _mark("config_and_device")

    mesh_env, mesh_insol = load_meshes(settings)
    # Work in a local frame anchored at the max volume's min corner.  Rays,
    # voxelization and sampling run in float32; georeferenced coordinates
    # (UTM northings ~4.5e6 m) leave float32 a resolution of ~0.5 m.  Every
    # persisted coordinate is shifted back to world space below.
    # Local coordinates are rounded to 1 µm: subtracting a large frame leaves
    # ~1e-9 m of rounding noise, enough to flip sampling decisions for points
    # that lie exactly on panel edges, so the same scene placed elsewhere
    # would sample (and carve) slightly differently.
    frame = np.asarray(mesh_env.bounds[0], dtype=np.float64)
    max_volume_highest_z = float(mesh_env.bounds[1][2])     # world z, for massing
    footprint = _max_volume_footprint(mesh_env)   # world xy, before the shift
    mesh_env = mesh_env.copy()
    mesh_env.vertices = np.round(mesh_env.vertices - frame, 6)
    mesh_insol = mesh_insol.copy()
    mesh_insol.vertices = np.round(mesh_insol.vertices - frame, 6)
    _mark("load_meshes")

    # voxelize checks the grid size against grid_planning.MAX_GRID_VOXELS
    # before allocating anything.
    voxel_grid, origin, extent, resolution = voxelize(mesh_env, settings, device=resolved_device)
    _mark("voxelize")
    pts, norms, analysis_mesh, sample_weights, taper_stats = sample_surface(mesh_insol, settings)
    _mark("sample_surface")
    if pts.shape[0] == 0:
        raise InputError(
            "No sample points were generated from the test surface. "
            "Check that test_surface_path contains valid geometry and that "
            "grid_step is not larger than the surface extent."
        )

    mode = settings.mode
    if mode == "radiative_cooling":
        _check_radiative_cooling_surface(norms)

    # edge_taper weights each sample point's contribution to the scores. The
    # violation-count modes count rays without weights, so there it is
    # ignored with a warning.
    point_weights = None
    if settings.edge_taper > 0.0:
        if MODES[mode].score_kind == "violation_count":
            report_issue(
                "edge_taper_ignored",
                f"edge_taper={settings.edge_taper:g} m is ignored by mode "
                f"'{mode}': violation-count carving is binary per ray and "
                f"has no per-point weighting.",
            )
        else:
            point_weights = sample_weights

    raw_scores, scores_kind, patch_weights = _compute_raw_scores(
        voxel_grid, origin, extent, resolution, pts, norms, settings, options,
        point_weights=point_weights,
    )
    warn_score_anomalies(raw_scores, context="preprocessing")
    _mark("ray_tracing")

    scores_path = out_path / "scores.npy"
    np.save(scores_path, raw_scores, allow_pickle=False)

    # Back to world coordinates for everything persisted.
    world_origin = np.asarray(origin, dtype=np.float64) + frame

    # Persist patch weights for downstream performance reporting
    if patch_weights is not None:
        pw_path = out_path / "patch_weights.npy"
        pw_np = patch_weights.cpu().numpy() if hasattr(patch_weights, 'cpu') else np.asarray(patch_weights)
        np.save(pw_path, pw_np, allow_pickle=False)
    else:
        pw_path = None
        pw_np = None

    # Persist test points and normals for diagnostics and GH visualization
    test_points_path = out_path / "test_points.npy"
    test_normals_path = out_path / "test_normals.npy"
    np.save(test_points_path, pts.astype(np.float64) + frame, allow_pickle=False)
    np.save(test_normals_path, norms, allow_pickle=False)

    # Persist voxel grid so thresholding and exporting can reuse it without
    # re-voxelizing
    import torch
    voxel_grid_path = out_path / "voxel_grid.npy"
    np.save(voxel_grid_path, voxel_grid.cpu().numpy() if isinstance(voxel_grid, torch.Tensor) else voxel_grid, allow_pickle=False)

    # Persist analysis mesh for downstream visualization and diagnostics
    if analysis_mesh is not None:
        analysis_mesh.vertices = analysis_mesh.vertices + frame
        analysis_mesh_path = out_path / "analysis_mesh.json"
        analysis_mesh_path.write_text(
            json.dumps(analysis_mesh.to_dict()), encoding="utf-8"
        )
    else:
        analysis_mesh_path = None
    footprint_path = out_path / "footprint.json"
    footprint_path.write_text(json.dumps(floor_plates.footprint_to_dict(footprint)), encoding="utf-8")
    _mark("save_npy_and_mesh")

    run_id = new_run_id()
    pm = PreprocessingManifest(
        run_id=run_id,
        scores_path=stored_path(scores_path, out_path),
        scores_kind=scores_kind,
        shape=tuple(voxel_grid.shape),
        origin=tuple(map(float, world_origin)),
        voxel_grid_path=stored_path(voxel_grid_path, out_path),
        voxel_size=float(settings.voxel_size),
        mode=mode,
        patch_weights_path=stored_path(pw_path, out_path) if pw_path else None,
        sample_point_count=int(pts.shape[0]),
        grid_step=float(settings.grid_step),
        score_unit=MODES[mode].score_unit,
        footprint_path=stored_path(footprint_path, out_path),
        max_volume_lowest_z=float(frame[2]),
        max_volume_highest_z=max_volume_highest_z,
    )

    # Per-stage diagnostics: the stage builds the summary and the writer puts
    # it (and the plots) on disk. The public preprocessing function writes
    # the config snapshot.
    diag_dir = ensure_diag(out_path)
    rs = np.asarray(raw_scores)
    summary = {
        "mode": mode,
        "scores_kind": scores_kind,
        "voxel_size": float(settings.voxel_size),
        "grid_shape": [int(x) for x in voxel_grid.shape],
        "grid_origin": [float(o) for o in world_origin],
        "grid_extent": float(extent),
        "grid_resolution": int(resolution),
        "voxels_total": int(np.prod(voxel_grid.shape)),
        "voxels_filled": int(voxel_grid.sum().item() if hasattr(voxel_grid, 'sum') else np.sum(voxel_grid)),
        "test_surface_points": int(pts.shape[0]),
        "test_points_path": str(test_points_path),
        "analysis_mesh_path": str(analysis_mesh_path) if analysis_mesh_path else None,
        "test_normals_path": str(test_normals_path),
        "scores_path": str(scores_path),
        "score_stats": score_statistics(rs, detailed=options.diagnostics),
    }
    if settings.edge_taper > 0.0:
        # Taper transparency: record what the design constraint excluded.
        sw = np.asarray(sample_weights)
        summary["edge_taper"] = {
            "meters": float(settings.edge_taper),
            "applied": point_weights is not None,
            "mean_weight": round(float(sw.mean()), 4) if sw.size else None,
            "near_zero_fraction": round(float((sw < 0.1).mean()), 4) if sw.size else None,
            "components": taper_stats,
        }
    if settings.mode == "radiative_cooling" and settings.min_sky_elevation_deg > 0.0:
        summary["min_sky_elevation_deg"] = float(settings.min_sky_elevation_deg)
    if settings.mode == "benefit" and settings.simulated_weights_path:
        # Provenance: which physics-derived schedule weighted this carve.
        from ..simulated_weights import read_simulated_weights
        _b, _h, u_meta = read_simulated_weights(settings.simulated_weights_path)
        summary["simulated_weights"] = {
            "path": str(settings.simulated_weights_path),
            "method": u_meta.get("method"),
            "generated": u_meta.get("generated"),
            "archetype": u_meta.get("archetype"),
        }
    summary["device"] = device_info
    _mark("build_summary")
    weight_unit, score_unit = MODES[mode].weight_unit, MODES[mode].score_unit
    # Plots are drawn by the writer after this point, so the timings below
    # cover the computation; the step label is kept for readers of the report.
    _mark("diagnostic_plots_done")
    # One diagnostic file per stage. Step timings are cumulative (seconds
    # since the stage started); subtract consecutive entries to get the
    # duration of each step.
    summary["timings"] = {
        "wall_seconds": float(time.perf_counter() - _t0_wall),
        "cpu_seconds": float(time.process_time() - _t0_cpu),
        "steps": {k: round(v, 3) for k, v in _step_times.items()},
    }
    write_preprocessing_diagnostics(
        summary, diag_dir, settings, options,
        PreprocessingPlotInputs(raw_scores=rs, patch_weights=pw_np, weight_unit=weight_unit, score_unit=score_unit),
    )
    # Manifest last (see begin_stage at the start).
    commit_manifest(out_path, pm)

    return PreprocessingResult(
        out_dir=out_path,
        volume_path=scores_path,
        volume_shape=tuple(voxel_grid.shape),
        dtype=str(raw_scores.dtype),
        run_id=run_id,
        device_info=device_info,
        issues=context.issues_of("preprocessing"),
    )