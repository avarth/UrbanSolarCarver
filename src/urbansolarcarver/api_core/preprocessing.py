from __future__ import annotations
import json, time, hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, Union
import numpy as np
from ..load_config import user_config
from ._util import _resolve_cfg, _ensure_out_dir, ensure_diag, write_json, resolve_device, device_summary, dump_config_snapshot
from ._diagnostics import (
    save_sky_patch_weights, save_sky_patch_comparison, save_histogram,
    score_statistics, warn_score_anomalies,
)
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
    ``volume_path`` is the ``scores.npy`` file. The ``manifest_path``
    property points to the JSON manifest that the next stage reads; the
    object also implements ``__fspath__`` (returning that manifest path) so
    it can be passed directly as a path-like to :func:`thresholding`.
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

def _check_radiative_cooling_surface(norms: np.ndarray) -> None:
    """Raise ValueError unless the test surfaces face mostly upward.

    The radiative_cooling view-factor weighting (cos θ / π) is only valid for
    surfaces facing the sky, so reject test surfaces whose mean normal is
    more than about 45° from vertical.
    """
    mean_normal = norms.mean(axis=0)
    mean_normal /= (np.linalg.norm(mean_normal) + 1e-12)
    z_component = float(mean_normal[2])
    if z_component < 0.7:  # cos(45.6°) = 0.7
        raise ValueError(
            f"radiative_cooling mode requires a horizontal, upward-facing test surface "
            f"(mean normal Z-component = {z_component:.2f}, expected > 0.7). "
            f"This mode's view-factor weighting (cos θ / π) is only valid for "
            f"surfaces facing the sky. For vertical facades, use a different mode."
        )


def _compute_raw_scores(voxel_grid, origin, extent, resolution, pts, norms, conf,
                        point_weights=None):
    """Run the carver for ``conf.mode`` and return the per-voxel scores.

    Parameters
    ----------
    point_weights : np.ndarray (N,) | None
        Per-sample-point design weights (edge_taper); weighted modes only.

    Returns
    -------
    raw_scores : np.ndarray, float32, shape (X*Y*Z,)
        Flat scores in the grid's C order. time-based scores are in m²·h.
    scores_kind : {"violation_count", "weighted_sum"}
    patch_weights : np.ndarray | torch.Tensor | None
        Per-sky-patch weights (weighted modes only).
    patch_rank : np.ndarray | None
        Per-voxel rank of the highest-weight patch blocked, for the
        protect_share threshold (weighted modes only; see
        ``carving.rank_blocked_patches``).
    recovery : carving.RecoveryRays | None
        Obstructed rays in clearing order and per-voxel ray ranks, for the
        recovered_sky threshold (weighted modes only).
    """
    mode = conf.mode
    spec = MODES.get(mode)
    if spec is None:
        raise ValueError(
            f"Unknown mode '{mode}': not registered in mode_registry.MODES"
        )
    if mode in MODES_NEEDING_PERIOD:
        steps = conf.sun_steps_per_hour if mode == "time-based" else 1
        datetimes, hoys = sample_period(conf, steps_per_hour=steps)
    else:
        datetimes, hoys = [], []

    # Route by the registry's score_kind so that a new violation-count mode
    # without a carver raises here instead of falling through to the
    # weighted sky-patch carver.
    if spec.score_kind == "violation_count":
        if mode == "time-based":
            _carved, _ro, _rd, counts = carve_with_sun_rays(
                voxel_grid, origin, extent, resolution, pts, norms, conf,
                datetimes, return_counts=True,
            )
            # Each count is one (sample point, sun position) ray the voxel
            # blocks. A sample point stands for ~grid_step² of protected
            # surface and a sun position for 1/sun_steps_per_hour h, so the
            # score is shaded area x duration (m²·h): a numeric threshold
            # then means the same at any sampling density.
            counts = counts * (float(conf.grid_step) ** 2 / float(conf.sun_steps_per_hour))
        elif mode == "tilted_plane":
            _carved, _ro, _rd, counts = carve_with_planes(
                voxel_grid, origin, extent, resolution, pts, norms, conf,
                return_counts=True,
            )
        else:
            raise NotImplementedError(
                f"mode '{mode}' declares score_kind='violation_count' but has "
                f"no carver wired in _compute_raw_scores"
            )
        return counts.astype(np.float32), spec.score_kind, None, None, None

    # weighted_sum: all sky-patch modes share one carver.
    carve_out = carve_with_sky_patch_rays(
        voxel_grid, origin, extent, resolution, pts, norms, conf, hoys,
        point_weights=point_weights, return_patch_rank=True, return_recovery=True,
    )
    return (carve_out.raw_voxel_scores, spec.score_kind, carve_out.patch_weights,
            carve_out.patch_rank, carve_out.recovery)


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
         of the weights of the rays it blocks.

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
    FileNotFoundError
        If the mesh or required EPW file is missing.
    ValueError
        If the grid is too large (more than 4096 voxels per side or
        500,000,000 in total) or, in radiative_cooling mode, the test
        surfaces do not face up.
    RuntimeError
        If the voxel grid is empty or no test-surface points are sampled.

    Persisted artifacts
    -------------------
    ``scores.npy``
        Flat ``float32`` array of length X*Y*Z (C order of the voxel grid)
        with raw obstruction scores; thresholding reshapes it.
    ``voxel_grid.npy``
        Occupancy grid (uint8, 1 = inside the max volume) so downstream
        stages can skip re-voxelization.
    ``test_points.npy``, ``test_normals.npy``, ``analysis_mesh.json``
        Sample points (world coordinates), their normals, and the analysis
        mesh, for diagnostics and Grasshopper display.
    ``patch_weights.npy``
        Per-sky-patch weights (sky-patch modes only).
    ``patch_rank.npy``
        Flat ``int32`` array, per voxel the rank of the highest-weight sky
        patch it blocks from some test point (sky-patch modes only); read
        by the protect_share threshold.
    ``recovery_rays.npz``
        The obstructed rays in clearing order (sample point, sky patch,
        weight), the per-voxel ray ranks and the traced points and normals
        (sky-patch modes only); read by the recovered_sky threshold.
    ``manifest.json``
        Machine-readable manifest (``PreprocessingManifest``) recording grid
        shape, world origin, voxel size, mode, score kind, and file paths.
        Written last, so a failed run leaves no manifest.
    ``diagnostics/``
        ``diagnostic.json`` (summary statistics and wall/CPU timings),
        ``config_snapshot.json``, and, with ``cfg.diagnostic_plots``, the
        score histogram and sky-patch weight plots.
    """
    _t0_wall = time.perf_counter()
    _t0_cpu = time.process_time()
    _step_times = {}
    def _mark(label):
        _step_times[label] = time.perf_counter() - _t0_wall

    conf = _resolve_cfg(cfg)
    validate_inputs(conf)  # fail fast on missing mesh/EPW files
    out_path = _ensure_out_dir(out_dir, "preprocessing")
    # A run that fails midway must not leave the previous manifest pointing
    # at half-overwritten arrays: the manifest is written last.
    (out_path / "manifest.json").unlink(missing_ok=True)

    full_cfg = conf.model_dump()
    stage_hash = hashlib.sha256(json.dumps(full_cfg, sort_keys=True).encode()).hexdigest()[:8]

    resolved_device = resolve_device(conf.device)
    device_info = device_summary(resolved_device)
    _mark("config_and_device")

    mesh_env, mesh_insol = load_meshes(conf)
    # Work in a local frame anchored at the max volume's min corner.  Rays,
    # voxelization and sampling run in float32; georeferenced coordinates
    # (UTM northings ~4.5e6 m) leave float32 a resolution of ~0.5 m.  Every
    # persisted coordinate is shifted back to world space below.
    # Local coordinates are rounded to 1 µm: subtracting a large frame leaves
    # ~1e-9 m of rounding noise, enough to flip sampling decisions for points
    # that lie exactly on panel edges, so the same scene placed elsewhere
    # would sample (and carve) slightly differently.
    frame = np.asarray(mesh_env.bounds[0], dtype=np.float64)
    mesh_env = mesh_env.copy()
    mesh_env.vertices = np.round(mesh_env.vertices - frame, 6)
    mesh_insol = mesh_insol.copy()
    mesh_insol.vertices = np.round(mesh_insol.vertices - frame, 6)
    _mark("load_meshes")

    voxel_grid, origin, extent, resolution = voxelize(mesh_env, conf, device=resolved_device)
    _mark("voxelize")
    total_voxels = int(np.prod(voxel_grid.shape))
    if total_voxels > 500_000_000:
        raise ValueError(
            f"Voxel grid has {total_voxels:,} voxels, too many to score in memory. "
            f"Increase voxel_size (currently {conf.voxel_size}m) or reduce geometry extent."
        )
    pts, norms, analysis_mesh, sample_weights, taper_stats = sample_surface(mesh_insol, conf)
    _mark("sample_surface")
    if pts.shape[0] == 0:
        raise ValueError(
            "No sample points were generated from the test surface. "
            "Check that test_surface_path contains valid geometry and that "
            "grid_step is not larger than the surface extent."
        )

    mode = conf.mode
    if mode == "radiative_cooling":
        _check_radiative_cooling_surface(norms)

    # edge_taper weights each sample point's contribution to the scores. The
    # violation-count modes count rays without weights, so there it is
    # ignored with a warning.
    point_weights = None
    if conf.edge_taper > 0.0:
        if MODES[mode].score_kind == "violation_count":
            import warnings
            warnings.warn(
                f"edge_taper={conf.edge_taper:g} m is ignored by mode "
                f"'{mode}': violation-count carving is binary per ray and "
                f"has no per-point weighting.",
                stacklevel=2,
            )
        else:
            point_weights = sample_weights

    raw_scores, scores_kind, patch_weights, patch_rank, recovery = _compute_raw_scores(
        voxel_grid, origin, extent, resolution, pts, norms, conf,
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
    rank_path = out_path / "patch_rank.npy"
    if patch_rank is not None:
        np.save(rank_path, patch_rank, allow_pickle=False)
    else:
        rank_path.unlink(missing_ok=True)  # from an earlier run in a weighted mode
        rank_path = None
    recovery_path = out_path / "recovery_rays.npz"
    if recovery is not None:
        np.savez(recovery_path, **recovery._asdict())
    else:
        recovery_path.unlink(missing_ok=True)
        recovery_path = None

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
    _mark("save_npy_and_mesh")

    pm = PreprocessingManifest(
        hash=stage_hash,
        scores_path=str(scores_path),
        scores_kind=scores_kind,
        shape=tuple(voxel_grid.shape),
        origin=tuple(map(float, world_origin)),
        voxel_grid_path=str(voxel_grid_path),
        voxel_size=float(conf.voxel_size),
        mode=mode,
        patch_weights_path=str(pw_path) if pw_path else None,
        patch_rank_path=str(rank_path) if rank_path else None,
        recovery_rays_path=str(recovery_path) if recovery_path else None,
        sample_point_count=int(pts.shape[0]),
    )

    # Per-stage diagnostics
    diag_dir = ensure_diag(out_path)
    dump_config_snapshot(conf, diag_dir)
    rs = np.asarray(raw_scores)
    summary = {
        "mode": mode,
        "scores_kind": scores_kind,
        "voxel_size": float(conf.voxel_size),
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
        "score_stats": score_statistics(rs, detailed=conf.diagnostics),
    }
    if conf.edge_taper > 0.0:
        # Taper transparency: record what the design constraint excluded.
        sw = np.asarray(sample_weights)
        summary["edge_taper"] = {
            "meters": float(conf.edge_taper),
            "applied": point_weights is not None,
            "mean_weight": round(float(sw.mean()), 4) if sw.size else None,
            "near_zero_fraction": round(float((sw < 0.1).mean()), 4) if sw.size else None,
            "components": taper_stats,
        }
    if conf.mode == "radiative_cooling" and conf.min_sky_elevation_deg > 0.0:
        summary["min_sky_elevation_deg"] = float(conf.min_sky_elevation_deg)
    if conf.mode == "benefit" and conf.simulated_weights_path:
        # Provenance: which physics-derived schedule weighted this carve.
        from ..simulated_weights import read_simulated_weights
        _b, _h, u_meta = read_simulated_weights(conf.simulated_weights_path)
        summary["simulated_weights"] = {
            "path": str(conf.simulated_weights_path),
            "method": u_meta.get("method"),
            "generated": u_meta.get("generated"),
            "archetype": u_meta.get("archetype"),
        }
    summary["device"] = device_info
    _mark("build_summary")
    xlabel = MODES[mode].weight_unit if mode in MODES else "Score"

    # Diagnostic plots only when diagnostic_plots is set, so matplotlib is
    # not loaded otherwise.
    if conf.diagnostic_plots:
        if patch_weights is not None and hasattr(patch_weights, 'size') and patch_weights.size > 0:
            summary["sky_patch_images"] = [
                str(diag_dir / "sky_patch_weights.png"),
                str(diag_dir / "sky_patch_weights_intensity.png"),
            ]
            save_sky_patch_weights(patch_weights, diag_dir, weight_unit=xlabel)
            if conf.mode == "benefit" and conf.simulated_weights_path:
                # How the simulated weights shifted the sky relative to the
                # simple balance-point rule under the same config.
                import torch
                from ..scoring import get_weights
                _, cf_hoys = sample_period(conf)
                simple = get_weights(
                    "benefit", device=torch.device("cpu"),
                    epw_file=conf.epw_path, hoys=cf_hoys,
                    balance_temperature=conf.balance_temperature,
                    balance_offset=conf.balance_offset,
                    north_deg=conf.north_deg,
                    include_harm=conf.include_harm,
                ).cpu().numpy()
                comparison = save_sky_patch_comparison(
                    simple, np.asarray(patch_weights, dtype=float), diag_dir,
                    labels=("simple (balance point)", "simulated"),
                )
                if comparison is not None:
                    cmp_path, cmp_stats = comparison
                    summary["sky_patch_comparison_image"] = str(cmp_path)
                    summary["sky_patch_comparison_stats"] = cmp_stats
        summary["score_histogram"] = str(diag_dir / "score_histogram.png")
        save_histogram(rs, diag_dir, "score_histogram.png",
                       title=f"Raw Scores ({mode})", xlabel=xlabel)
    _mark("diagnostic_plots_done")
    # One diagnostic file per stage. Step timings are cumulative (seconds
    # since the stage started); subtract consecutive entries to get the
    # duration of each step.
    summary["timings"] = {
        "wall_seconds": float(time.perf_counter() - _t0_wall),
        "cpu_seconds": float(time.process_time() - _t0_cpu),
        "steps": {k: round(v, 3) for k, v in _step_times.items()},
    }
    write_json(diag_dir, "diagnostic.json", summary)
    # Manifest last (see the unlink at the start of this function).
    (out_path / "manifest.json").write_text(schema_to_json(pm), encoding="utf-8")

    return PreprocessingResult(
        out_dir=out_path,
        volume_path=scores_path,
        volume_shape=tuple(voxel_grid.shape),
        dtype=str(raw_scores.dtype),
        hash=stage_hash,
        device_info=device_info,
    )