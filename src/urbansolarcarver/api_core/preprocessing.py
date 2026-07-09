from __future__ import annotations
import json, time, hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, Union
import numpy as np
from ..load_config import user_config
from ._util import _resolve_cfg, _ensure_out_dir, ensure_diag, write_json, resolve_device, device_summary, dump_config_snapshot
from ._diagnostics import save_sky_patch_weights, save_histogram, score_statistics
from ..pydantic_schemas import PreprocessingManifest, schema_to_json
from ..carving import (
    carve_with_sky_patch_rays, carve_with_sun_rays, carve_with_planes,
    load_meshes, sample_period, validate_inputs,
)
from ..grid import voxelize, sample_surface
from ..mode_registry import MODES, MODES_NEEDING_PERIOD

@dataclass(frozen=True)
class PreprocessingResult:
    """Immutable record returned by :func:`preprocessing`.

    Carries paths to persisted artifacts and grid metadata so that downstream
    stages (thresholding, exporting) can locate them without re-computation.
    The ``manifest_path`` property points to the JSON manifest that fully
    describes this preprocessing run; the object also implements
    ``__fspath__`` so it can be passed directly as a path-like to
    :func:`thresholding`.
    """
    out_dir: Path
    volume_path: Path
    volume_shape: Tuple[int, int, int]
    dtype: str
    hash: str
    device_info: str = ""
    @property
    def manifest_path(self) -> Path:
       return self.out_dir / "manifest.json"
    def __fspath__(self) -> str:
        return str(self.manifest_path)

def preprocessing(
    cfg: Union[user_config, str, Path],
    out_dir: Union[str, Path]
) -> PreprocessingResult:
    """First stage of the 3-stage envelope pipeline: per-voxel obstruction scoring.

    Converts a maximum-volume mesh and a set of insolation test surfaces into
    a 3-D scalar field where each voxel carries a score indicating how much it
    obstructs the surrounding context.  The pipeline steps are:

    1. Voxelization -- the maximum-volume envelope mesh is discretised into
       a regular Boolean grid at the resolution specified by ``cfg.voxel_size``.
    2. Surface sampling -- insolation test surfaces are point-sampled
       (density controlled by ``cfg.grid_step``), yielding test points
       with associated outward normals.  The test surface PLY file may
       contain multiple disjoint mesh components (e.g. separate facade
       panels, a ground plane and a courtyard, or a PV array).  All
       components are sampled and their ray contributions aggregated into
       a single score grid.
    3. Ray casting -- for every test point, rays are cast through the voxel
       grid according to the configured mode.  Each voxel that blocks a ray
       accumulates a weight that depends on the mode:

       * ``time-based``: sun-position rays for the configured analysis period;
         scores are integer *violation counts* (number of sun-hours blocked).
       * ``tilted_plane``: geometric plane-intersection test; scores are also
         violation counts.
       * sky-patch modes (``irradiance``, ``benefit``, ``daylight``,
         ``radiative_cooling``): rays are
         sampled from a discretised sky hemisphere weighted by radiance or
         irradiance; scores are *weighted sums* reflecting the total sky
         contribution obstructed by the voxel.

    Parameters
    ----------
    cfg : user_config | str | Path
        A validated ``user_config`` instance, or a filesystem path to a YAML /
        JSON configuration file that will be loaded and validated.
    out_dir : str | Path
        Root output directory.  All stage artifacts are written directly
        into this directory (no subdirectory is created).

    Returns
    -------
    PreprocessingResult
        Frozen dataclass with paths and metadata for the completed stage.

    Persisted artifacts
    -------------------
    ``scores.npy``
        3-D ``float32`` array (same shape as the voxel grid) with raw
        obstruction scores.
    ``voxel_grid.npy``
        Boolean occupancy grid so downstream stages can skip re-voxelization.
    ``manifest.json``
        Machine-readable manifest (``PreprocessingManifest``) recording grid
        origin, extent, voxel size, score semantics, and file paths.
    ``diagnostics/``
        Per-stage diagnostics: score histogram, sky-patch weight visualisation
        (if applicable), summary statistics, and wall/CPU timings.
    """
    # Begin timing here. Keep diagnostics local.
    _t0_wall = time.perf_counter()
    _t0_cpu = time.process_time()
    _step_times = {}
    def _mark(label):
        _step_times[label] = time.perf_counter() - _t0_wall

    conf = _resolve_cfg(cfg)
    validate_inputs(conf)  # fail fast on missing mesh/EPW files
    out_path = _ensure_out_dir(out_dir, "preprocessing")

    full_cfg = conf.model_dump()
    stage_hash = hashlib.sha256(json.dumps(full_cfg, sort_keys=True).encode()).hexdigest()[:8]

    resolved_device = resolve_device(getattr(conf, "device", "auto"))
    device_info = device_summary(resolved_device)
    _mark("config_and_device")

    mesh_env, mesh_insol = load_meshes(conf)
    _mark("load_meshes")

    voxel_grid, origin, extent, resolution = voxelize(mesh_env, conf, device=resolved_device)
    _mark("voxelize")
    total_voxels = int(np.prod(voxel_grid.shape))
    if total_voxels > 500_000_000:
        raise ValueError(
            f"Voxel grid has {total_voxels:,} voxels — this would exhaust memory. "
            f"Increase voxel_size (currently {conf.voxel_size}m) or reduce geometry extent."
        )
    pts, norms, analysis_mesh = sample_surface(mesh_insol, conf)
    _mark("sample_surface")
    if pts.shape[0] == 0:
        raise ValueError(
            "No sample points were generated from the test surface. "
            "Check that test_surface_path contains valid geometry and that "
            "grid_step is not larger than the surface extent."
        )

    mode = conf.mode

    # Guard: radiative_cooling assumes horizontal, upward-facing test surfaces.
    # Check that the mean normal of the test surface is predominantly vertical.
    if mode == "radiative_cooling":
        mean_normal = norms.mean(axis=0)
        mean_normal /= (np.linalg.norm(mean_normal) + 1e-12)
        z_component = float(mean_normal[2])
        if z_component < 0.7:  # ~45° from vertical
            raise ValueError(
                f"radiative_cooling mode requires a horizontal, upward-facing test surface "
                f"(mean normal Z-component = {z_component:.2f}, expected > 0.7). "
                f"This mode's view-factor weighting (cos θ / π) is only valid for "
                f"surfaces facing the sky. For vertical facades, use a different mode."
            )

    patch_weights = None
    suggested_threshold = None

    if mode in MODES_NEEDING_PERIOD:
        datetimes, hoys = sample_period(conf)
    else:
        datetimes, hoys = [], []

    if mode == "time-based":
        _carved, _ro, _rd, counts = carve_with_sun_rays(
            voxel_grid, origin, extent, resolution, pts, norms, conf, datetimes, return_counts=True
        )
        raw_scores = counts.astype(np.float32)
        scores_kind = "violation_count"
        suggested_threshold = 0.0
    elif mode == "tilted_plane":
        _carved, _ro, _rd, counts = carve_with_planes(
            voxel_grid, origin, extent, resolution, pts, norms, conf, return_counts=True
        )
        raw_scores = counts.astype(np.float32)
        scores_kind = "violation_count"
        suggested_threshold = 0.0
    else:
        carve_out = carve_with_sky_patch_rays(
            voxel_grid, origin, extent, resolution, pts, norms, conf, hoys
        )
        raw_scores = carve_out.raw_voxel_scores
        patch_weights = carve_out.patch_weights
        scores_kind = "weighted_sum"
        # Threshold is now computed exclusively in thresholding stage
        suggested_threshold = None

    _mark("ray_tracing")

    scores_path = out_path / "scores.npy"
    np.save(scores_path, raw_scores, allow_pickle=False)

    # Persist patch weights for downstream performance reporting
    if patch_weights is not None:
        pw_path = out_path / "patch_weights.npy"
        pw_np = patch_weights.cpu().numpy() if hasattr(patch_weights, 'cpu') else np.asarray(patch_weights)
        np.save(pw_path, pw_np, allow_pickle=False)
    else:
        pw_path = None

    # Persist test points and normals for diagnostics and GH visualization
    test_points_path = out_path / "test_points.npy"
    test_normals_path = out_path / "test_normals.npy"
    np.save(test_points_path, pts, allow_pickle=False)
    np.save(test_normals_path, norms, allow_pickle=False)

    # Persist voxel grid so exporting can reuse it without re-voxelizing
    import torch
    voxel_grid_path = out_path / "voxel_grid.npy"
    np.save(voxel_grid_path, voxel_grid.cpu().numpy() if isinstance(voxel_grid, torch.Tensor) else voxel_grid, allow_pickle=False)

    # Persist analysis mesh for downstream visualization and diagnostics
    if analysis_mesh is not None:
        analysis_mesh_path = out_path / "analysis_mesh.json"
        analysis_mesh_path.write_text(
            json.dumps(analysis_mesh.to_dict()), encoding="utf-8"
        )
    else:
        analysis_mesh_path = None
    _mark("save_npy_and_mesh")

    pm = PreprocessingManifest(
        hash=stage_hash,
        scores_path=str(scores_path),
        scores_kind=scores_kind,
        shape=tuple(voxel_grid.shape),
        origin=tuple(map(float, origin)),
        suggested_threshold=suggested_threshold,
        voxel_grid_path=str(voxel_grid_path),
        voxel_size=float(conf.voxel_size),
        mode=mode,
        patch_weights_path=str(pw_path) if pw_path else None,
        sample_point_count=int(pts.shape[0]),
    )

    # Per-stage diagnostics (write alongside stage artifacts)
    diag_dir = ensure_diag(out_path)
    dump_config_snapshot(conf, diag_dir)
    rs = np.asarray(raw_scores)
    summary = {
        "mode": mode,
        "scores_kind": scores_kind,
        "voxel_size": float(conf.voxel_size),
        "grid_shape": [int(x) for x in voxel_grid.shape],
        "grid_origin": [float(o) for o in origin],
        "grid_extent": float(extent),
        "grid_resolution": int(resolution),
        "voxels_total": int(np.prod(voxel_grid.shape)),
        "voxels_filled": int(voxel_grid.sum().item() if hasattr(voxel_grid, 'sum') else np.sum(voxel_grid)),
        "test_surface_points": int(pts.shape[0]),
        "test_points_path": str(test_points_path),
        "test_normals_path": str(test_normals_path),
        "scores_path": str(scores_path),
        "score_stats": score_statistics(rs, detailed=conf.diagnostics),
    }
    summary["device"] = device_info
    _mark("build_summary")
    xlabel = MODES[mode].weight_unit if mode in MODES else "Score"

    # Diagnostic plots: gated behind the diagnostic_plots flag so the
    # matplotlib overhead is only paid when explicitly requested.
    if getattr(conf, "diagnostic_plots", False):
        if patch_weights is not None and hasattr(patch_weights, 'size') and patch_weights.size > 0:
            summary["sky_patch_images"] = [
                str(diag_dir / "sky_patch_weights.png"),
                str(diag_dir / "sky_patch_weights_intensity.png"),
            ]
            save_sky_patch_weights(patch_weights, diag_dir, weight_unit=xlabel)
        summary["score_histogram"] = str(diag_dir / "score_histogram.png")
        save_histogram(rs, diag_dir, "score_histogram.png",
                       title=f"Raw Scores ({mode})", xlabel=xlabel)
    _mark("diagnostic_plots_done")
    # Consolidated diagnostic — one file per stage.
    # Step timings are cumulative (elapsed since t0) — subtract consecutive
    # pairs to get per-step durations.
    summary["timings"] = {
        "wall_seconds": float(time.perf_counter() - _t0_wall),
        "cpu_seconds": float(time.process_time() - _t0_cpu),
        "steps": {k: round(v, 3) for k, v in _step_times.items()},
    }
    write_json(diag_dir, "diagnostic.json", summary)
    # Write manifest directly.
    (out_path / "manifest.json").write_text(schema_to_json(pm), encoding="utf-8")

    return PreprocessingResult(
        out_dir=out_path,
        volume_path=scores_path,
        volume_shape=tuple(voxel_grid.shape),
        dtype=str(raw_scores.dtype),
        hash=stage_hash,
        device_info=device_info,
    )