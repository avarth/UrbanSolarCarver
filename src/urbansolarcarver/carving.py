"""
UrbanSolarCarver — Carving utilities
====================================

Purpose
-------
Convert point/normal samples on analysis surfaces into ray sets, march those
through a voxelized envelope, and remove the voxels they visit. Supports:

• Time-based solar carving (sun vectors from EPW for specific datetimes)
• Sky-patch-weighted carving (Tregenza patches + mode-specific weights)
• Tilted-plane daylight carving (single or per-octant plane angle)
• Simple directional carving (global vector, per-point normals, or +Z)

Raytracing contract
-------------------
All carving is executed via `trace_multi_hit_grid`, which guarantees each
(ray, voxel) pair is reported at most once.  The Warp DDA backend traverses
voxels exactly; the PyTorch fallback samples at cell centers
(distances = (0.5 + k) * voxel_size) and maps world → grid with floor(),
not round(), to avoid lattice aliasing (especially for the plane method).

Coordinate/scale conventions
----------------------------
`grid_origin` is the world-space min corner for grid index [0,0,0].
`grid_extent` is the physical cube size (meters). `grid_resolution` is D.
The tracer receives `scale = grid_extent` and a per-ray step of `voxel_size`.

Determinism and batching
------------------------
Given a fixed config, carving is deterministic. Rays are processed in batches
(`config.ray_batch_size`) on the device of the input voxel grid.
"""

import warnings
import torch
import numpy as np
from numba import njit

from .scoring import (
    get_weights,
    headtail_threshold,
)
from .load_config import user_config
from .mode_registry import ALL_MODE_NAMES, MODES_NEEDING_EPW
from .sky_patches import fetch_tregenza_patch_directions
from urbansolarcarver.session import get_active_session
import hashlib
import json
from .sun import get_sun_vectors
from .raytracer import (
    generate_sun_rays, generate_sky_patch_rays, trace_multi_hit_grid,
    auto_batch_size, dda_backend_available,
)
# Fused kernel import (conditional -- only available when Warp is installed)
try:
    from .raytracer import trace_and_score_dda as _fused_dda
except ImportError:
    _fused_dda = None
from typing import NamedTuple, Sequence, Literal, Tuple


class SkyPatchCarvingResult(NamedTuple):
    """Return type for :func:`carve_with_sky_patch_rays`."""
    ray_origins: np.ndarray      # (N, 3) ray start points
    ray_directions: np.ndarray   # (N, 3) ray unit vectors
    raw_voxel_scores: np.ndarray # (X*Y*Z,) per-voxel weighted scores
    patch_weights: np.ndarray    # (P,) weight per Tregenza sky patch

# High-level helpers migrated from api_core
import os
from ladybug.analysisperiod import AnalysisPeriod
from .io import load_mesh

def _resolve_batch_size(config, resolution: int, device) -> int:
    """Return the effective ray batch size, auto-tuning if requested.

    If ``config.ray_batch_size`` is 0 the batch size is computed from
    available GPU memory via :func:`auto_batch_size`.
    """
    bs = getattr(config, "ray_batch_size", 0)
    if bs and bs > 0:
        return int(bs)
    return auto_batch_size(resolution, device)


def validate_inputs(config: user_config):
    """
    Validate file paths and supported modes.

    Raises
    ------
    FileNotFoundError
        If any required input file is missing.
    ValueError
        If `config.mode` is not one of:
        {'time-based','irradiance','benefit','daylight','radiative_cooling','tilted_plane'}.
    """
    for filepath, name in [
        (config.max_volume_path, 'max_volume'),
        (config.test_surface_path,    'test_surface'),
    ]:
        if not filepath or not os.path.isfile(filepath):
            raise FileNotFoundError(f"{name} file missing: {filepath!r}")
    # EPW is required for modes that use weather data
    if config.mode in MODES_NEEDING_EPW:
        if not config.epw_path or not os.path.isfile(config.epw_path):
            raise FileNotFoundError(f"EPW file missing: {config.epw_path!r}")
    if config.mode not in ALL_MODE_NAMES:
        raise ValueError(f"Unsupported mode: {config.mode!r}")

def sample_period(config: user_config):
    """
    Build analysis datetimes and HOYs via Ladybug's AnalysisPeriod.

    Returns
    -------
    datetimes : list[datetime.datetime]
        Start→end at 1-hour steps using config start/end.
    hoys : list[int]
        Hour-of-year indices (1..8760) aligned to `datetimes`.
    """
    ap = AnalysisPeriod(
        st_month=config.start_month, st_day=config.start_day, st_hour=config.start_hour,
        end_month=config.end_month,   end_day=config.end_day,   end_hour=config.end_hour,
        timestep=1
    )
    return ap.datetimes, ap.hoys_int

def load_meshes(config: user_config):
    """
    Load the maximum envelope mesh and the insolation sampling surface.

    Returns
    -------
    envelope_mesh : trimesh.Trimesh
    insolation_mesh : trimesh.Trimesh
    """
    envelope_mesh = load_mesh(config.max_volume_path)
    insolation_mesh = load_mesh(config.test_surface_path)
    return envelope_mesh, insolation_mesh

def _validate_cubic_resolution(grid_resolution, func_name: str):
    """
    Validate that `grid_resolution` encodes a cubic grid.

    Parameters
    ----------
    grid_resolution : int | tuple[int, int, int] | list[int]
        Either a single side length D, or a 3-tuple/list with all
        entries equal to D.
    func_name : str
        Name of the caller for error context.

    Raises
    ------
    ValueError
        If the value does not represent a cube.
    """
    if isinstance(grid_resolution, int):
        return
    if (
        isinstance(grid_resolution, (tuple, list))
        and len(grid_resolution) == 3
        and grid_resolution[0] == grid_resolution[1] == grid_resolution[2]
    ):
        return
    raise ValueError(
        f"{func_name}: expected cubic grid_resolution (int or 3-tuple of equal ints), "
        f"got {grid_resolution}"
    )

      
#--- Defs for time-based or weighted carving -------------------------------------------------------------------

def carve_with_sun_rays(
    voxel_grid,
    grid_origin,
    grid_extent,
    grid_resolution,
    sample_points,
    sample_normals,
    config: "user_config",
    datetimes,
    return_counts: bool = False,
):
    """
    Perform time-based carving of a voxel grid using time-based sun vectors.

    This function constructs a classical solar envelope (or fan) by tracing rays for a set of
    sun directions derived from weather data and explicit datetimes. No scoring,
    normalization, or thresholding is applied. Any voxel intersected by any ray is
    removed.

    Core procedure
      1. Compute sun vectors for the provided datetimes from the EPW file, then filter
         by minimum altitude.
      2. For each surface sample point with outward normal, build rays toward the sun
         directions that lie in its visible hemisphere (facing-mask from normals).
      3. March points along each ray in fixed steps equal to `voxel_size` up to
         `ray_length`.
      4. Map sampled world positions to grid indices and zero all intersected voxels.
      5. Return the carved grid and the full set of ray origins and directions.

    Parameters
    ----------
    voxel_grid : torch.Tensor, shape (X, Y, Z)
        Input occupancy grid on CPU or GPU.
    grid_origin : array_like, shape (3,)
        Minimum corner of the voxel volume in world coordinates.
    grid_extent : float
        Physical span of the cubic grid (meters).
    grid_resolution : int or (3,)
        Number of voxels along each axis (must represent a cube).
    sample_points : torch.Tensor or np.ndarray, shape (R, 3)
        Coordinates of R surface evaluation points.
    sample_normals : torch.Tensor or np.ndarray, shape (R, 3)
        Outward unit normals at each sample point.
    config : user_config
        Configuration containing:
          - epw_path: path to EPW file used for sun positions.
          - min_altitude: degrees above horizon for filtering sun vectors.
          - voxel_size: step size for the marcher.
          - ray_length: maximum traced distance along each ray.
          - ray_batch_size: rays processed per batch.
    datetimes : Sequence[datetime.datetime]
        Wall-clock timestamps for which sun vectors are generated.
    return_counts : bool, default False
        If True, return a 4th element: per-voxel hit counts (int32 array).

    Returns
    -------
    carved_grid : torch.Tensor, shape (X, Y, Z)
        Voxel grid after removing all cells intersected by any traced ray.
    ray_origins : np.ndarray, shape (N, 3)
        World-space starting points for all emitted rays after facing cull.
    ray_directions : np.ndarray, shape (N, 3)
        Unit direction vectors for the emitted rays.
    counts : np.ndarray, shape (V,), optional
        Per-voxel hit counts (flat).  Only returned when *return_counts* is True.
    """
    _validate_cubic_resolution(grid_resolution, "carve_with_sun_rays")
    res = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])
    res_sq = res * res

    # sun directions on device (rotated to model coordinates via north_deg)
    sun_dirs = get_sun_vectors(
        config.epw_path, datetimes, config.min_altitude,
        north_deg=config.north_deg,
    )
    if isinstance(sun_dirs, torch.Tensor):
        sun_arr = sun_dirs.clone().detach().to(voxel_grid.device)
    else:
        sun_arr = torch.as_tensor(sun_dirs, dtype=torch.float32, device=voxel_grid.device)
    if sun_arr.numel() == 0:
        warnings.warn(
            "carve_with_sun_rays: no sun vectors above min_altitude — "
            "grid will be returned unmodified.",
            stacklevel=2,
        )
        empty = np.empty((0, 3), dtype=np.float32)
        if return_counts:
            return voxel_grid.clone(), empty, empty, np.zeros(voxel_grid.numel(), dtype=np.int32)
        return voxel_grid.clone(), empty, empty
    # 1e-9 epsilon prevents division by zero for degenerate sun vectors
    # (e.g. sun exactly at horizon). Float32 machine epsilon is ~1.2e-7,
    # so 1e-9 is safely below it.
    sun_arr = sun_arr / (sun_arr.norm(dim=1, keepdim=True) + 1e-9)

    # build rays
    origins, directions = generate_sun_rays(
        sample_points, sample_normals, sun_arr.cpu().numpy(), voxel_grid.device
    )
    R = origins.shape[0]
    ray_origins = origins.cpu().numpy()
    ray_directions = directions.cpu().numpy()

    device = voxel_grid.device
    flat = voxel_grid.reshape(-1).clone().to(torch.float32)
    counts = None
    if return_counts:
        counts = torch.zeros_like(flat, dtype=torch.int32)

    # scale is the cubic grid extent in world units (meters), not per-voxel size
    min_corner = (float(grid_origin[0]), float(grid_origin[1]), float(grid_origin[2]))
    scale = float(grid_extent)

    batch_size = _resolve_batch_size(config, res, device)
    for i in range(0, R, batch_size):
        o_batch = origins[i: i + batch_size]
        d_batch = directions[i: i + batch_size]
        if o_batch.numel() == 0:
            break

        # tracer requires per-ray patch ids; unused for carving
        patch_ids_stub = torch.zeros((o_batch.shape[0],), dtype=torch.long, device=device)

        _, _, voxel_idx = trace_multi_hit_grid(
            min_corner=min_corner,
            scale=scale,
            resolution=res,
            origins=o_batch,
            ray_dirs=d_batch,
            sky_patch_ids=patch_ids_stub,
            voxel_size=float(config.voxel_size),
            ray_length=float(config.ray_length),
        )

        if voxel_idx.numel() > 0:
            # 3D → 1D index in row-major (C) order: x*(res²) + y*res + z
            flat_idx = voxel_idx[:, 0] * res_sq + voxel_idx[:, 1] * res + voxel_idx[:, 2]
            valid = (flat_idx >= 0) & (flat_idx < flat.numel())
            flat_idx = flat_idx[valid]
            flat[flat_idx] = 0
            if counts is not None:
                counts.index_add_(0, flat_idx, torch.ones_like(flat_idx, dtype=torch.int32))

    carved_grid = flat.view_as(voxel_grid).to(voxel_grid.dtype)
    if counts is None:
        return carved_grid, ray_origins, ray_directions
    return carved_grid, ray_origins, ray_directions, counts.detach().cpu().numpy()

def carve_with_sky_patch_rays(
    voxel_grid,
    grid_origin,
    grid_extent,
    grid_resolution,
    sample_points,
    sample_normals,
    config: user_config,
    hoys : Sequence[int]
    ):
    """
    Perform sky-patch-weighted carving of a voxel grid using mode-specific weight metrics.

    This function assigns a weight to each Tregenza sky patch according to the selected mode. Available
    modes draw weights from:
      • Global horizontal + diffuse irradiance data.
      • Passive solar benefit indices (e.g. from Ladybug).
      • Daylighting metrics under a CIE overcast sky.
      • Radiative cooling potential (Bliss-K anisotropy and dew-point adjustment).

    Core procedure (identical across modes):
      1. Subdivide the hemisphere into angular bins (Tregenza patches).
      2. Cast rays from each sample point p with outward normal n toward each patch center.
      3. Trace rays through the voxel volume, accumulating per-voxel weights based on patch assignments.
      4. Normalize the raw score distribution if requested (linear or percentile scaling).
      5. Select a threshold via fixed value, head/tail breaks, or carve_fraction
      6. Apply binary mask to remove voxels above the threshold, yielding the carved grid.

    Parameters
    ----------
    voxel_grid : torch.Tensor, shape (X, Y, Z)
        Input occupancy or density values for each grid cell.
    grid_origin : array_like, shape (3,)
        Minimum corner of the voxel volume in world coordinates.
    grid_extent : float
        Physical span of each grid axis (meters).
    grid_resolution : int or (3,)
        Number of voxels along each axis (uniform or per-axis).
    sample_points : torch.Tensor, shape (R, 3)
        Coordinates of R surface evaluation points.
    sample_normals : torch.Tensor, shape (R, 3)
        Outward-facing unit normals at each sample point.
    config : user_config
        Configuration containing:
          - mode: weight mode selector.
          - epw_path: EPW file for irradiance/weather.
          - dew_point_celsius: dew-point temperature for cooling mode.
          - bliss_k: anisotropy scaling for cooling.
          - balance_temperature, balance_offset: tuning for energy-balance modes.
          - ray_batch_size: rays processed per batch.
          - voxel_size, ray_length: tracer resolution and extent.
    hoys : Sequence[int]
        Hours-of-year indices mapping to EPW or other time-series input.

    Returns
    -------
    SkyPatchCarvingResult
        NamedTuple with fields:
        - ray_origins (N, 3): world-space ray start points.
        - ray_directions (N, 3): unit ray vectors.
        - raw_voxel_scores (X*Y*Z,): accumulated patch weights per voxel.
        - patch_weights (P,): weight per Tregenza sky patch.
    """

    # --- 0) Setup ----------------------------------------------------------
    device = voxel_grid.device  # Determine compute device (CPU or CUDA)
    _validate_cubic_resolution(grid_resolution, 'carve_with_sky_patch_rays')  # Ensure grid is cubic

    # --- 1) Sky patch directions ------------------------------------------
    sky_dirs = fetch_tregenza_patch_directions(device=device)  # Unit vectors to each patch center

    # --- 2) Ray generation ------------------------------------------------
    # Generate rays: sample_points (R×3), sample_normals (R×3), sky_dirs (P×3)
    # generate_sky_patch_rays also returns normals_per_ray and point_idx,
    # discarded here — point_idx would enable per-sample-point attribution
    # but is not needed by the current pipeline (evaluation is out of scope).
    ray_origins, ray_directions, patch_ids, *_ = generate_sky_patch_rays(
        sample_points,
        sample_normals,
        sky_dirs,
        device=device
    )
    total_rays = ray_origins.size(0)  # Total number of rays (R * P)

    # --- 3) Load patch weights ---------------------------------------------
    # patch_weights: tensor of length P, weight per sky patch for chosen mode
    # --- NEW: cache in CarverSession if one is active ---------------------
    sess = get_active_session(device)

    def _compute_weights():
        return get_weights(
            mode=config.mode,
            device=device,
            epw_file=config.epw_path,
            hoys=hoys,
            dew_point_celsius=config.dew_point_celsius,
            bliss_k=config.bliss_k,
            ground_reflectance=config.ground_reflectance,
            balance_temperature=config.balance_temperature,
            balance_offset=config.balance_offset,
            north_deg=config.north_deg,
        )

    if sess:
        # Build a reproducible key from mode + key parameters
        key_payload = {
            "mode": config.mode,
            "epw": config.epw_path,
            "hoys": list(hoys),
            "dew": config.dew_point_celsius,
            "bliss": config.bliss_k,
            "balance_T": config.balance_temperature,
            "balance_off": config.balance_offset,
            "north": config.north_deg,
            "ground_refl": config.ground_reflectance,
        }
        cache_key = "patch_weights:" + hashlib.md5(
            json.dumps(key_payload, sort_keys=True).encode()
        ).hexdigest()
        patch_weights = sess.get_tensor(cache_key, _compute_weights)
    else:
        patch_weights = _compute_weights()

    # --- 4) Initialize score accumulation ---------------------------------
    num_voxels = voxel_grid.numel()     # Total voxels = X*Y*Z
    scores = torch.zeros(num_voxels, device=device)  # Accumulator for voxel scores
    grid_extent_m = float(grid_extent)  # Full world-space extent of the cubic voxel grid (meters)

    # --- 5) Batch ray tracing & weighting ----------------------------------
    res = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])
    batch_size = _resolve_batch_size(config, res, device)
    use_fused = (_fused_dda is not None and dda_backend_available(device))

    def _score_batch(start: int, end: int) -> None:
        origins_batch = ray_origins[start:end]
        directions_batch = ray_directions[start:end]
        patches_batch = patch_ids[start:end]

        if use_fused:
            # Fused DDA: traverse + score in a single Warp kernel.
            # No output buffer, no post-processing. Modifies scores in-place.
            _fused_dda(
                grid_origin, float(grid_extent_m), grid_resolution,
                origins_batch, directions_batch, patches_batch,
                patch_weights, scores, config.ray_length,
            )
            return

        # Legacy path: trace then accumulate on host
        hit_ray_ids, hit_patch_ids, hit_voxel_idxs = trace_multi_hit_grid(
            grid_origin, grid_extent_m, grid_resolution,
            origins_batch, directions_batch, patches_batch,
            config.voxel_size, config.ray_length,
        )
        if hit_voxel_idxs.numel() == 0:
            return

        idx_flat = (
            hit_voxel_idxs[:, 0] * res * res +
            hit_voxel_idxs[:, 1] * res +
            hit_voxel_idxs[:, 2]
        )

        # Guard: filter out-of-bounds indices
        if (idx_flat < 0).any() or (idx_flat >= num_voxels).any():
            warnings.warn(
                "trace_multi_hit_grid returned out-of-bounds voxel indices.",
                stacklevel=2,
            )
            valid = (idx_flat >= 0) & (idx_flat < num_voxels)
            idx_flat = idx_flat[valid]
            hit_patch_ids = hit_patch_ids[valid]

        if idx_flat.numel() == 0:
            return

        # trace_multi_hit_grid guarantees each (ray, voxel) pair
        # appears at most once, so weights can be accumulated directly.
        weights_for_hits = patch_weights[hit_patch_ids]
        scores.scatter_add_(0, idx_flat, weights_for_hits)

    batch_ranges = [
        (start, min(start + batch_size, total_rays))
        for start in range(0, total_rays, batch_size)
    ]
    with torch.no_grad():
        if use_fused and device.type == "cpu" and len(batch_ranges) > 1:
            # Warp executes CPU kernel launches single-threaded, and the
            # launches release the GIL, so dispatching batches from a small
            # thread pool runs them on multiple cores (~2x measured; gains
            # taper beyond a few workers — the kernel is memory-bound).
            # The shared score buffer stays correct because the kernel
            # accumulates with atomic adds.  Note: like on CUDA, atomic
            # float addition order varies, so scores can differ by
            # float-rounding noise between runs.
            from concurrent.futures import ThreadPoolExecutor
            n_workers = min(4, os.cpu_count() or 1, len(batch_ranges))
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                # list() drains the iterator so worker exceptions propagate
                list(pool.map(lambda rng: _score_batch(*rng), batch_ranges))
        else:
            for start, end in batch_ranges:
                _score_batch(start, end)

    # Synchronize GPU before reading scores
    if device.type == "cuda":
        torch.cuda.synchronize()

    raw_voxel_scores = scores.cpu().numpy()  # Move accumulated scores to CPU NumPy

    # Return raw scores, ray geometry, and patch weights.
    # Thresholding and mask creation are handled exclusively by
    # api_core.thresholding — keeping them separate avoids duplication
    # and lets users re-threshold without re-tracing rays.
    return SkyPatchCarvingResult(
        ray_origins=ray_origins.cpu().numpy(),
        ray_directions=ray_directions.cpu().numpy(),
        raw_voxel_scores=raw_voxel_scores,
        patch_weights=patch_weights.cpu().numpy(),
    )


def carve_with_planes(
    voxel_grid,
    grid_origin,
    grid_extent,
    grid_resolution,
    sample_points,
    sample_normals,
    config: "user_config",
    return_counts: bool = False,
):
    """
    Tilted-plane daylight carving.

    For each sample:
      1) Project the surface normal to the XY plane → n_xy
      2) Select angle α (single value or per-octant table)
      3) Form d = cos(α)·n_xy + sin(α)·ẑ and march this direction
    Every visited voxel is deleted.

    Parameters
    ----------
    voxel_grid, grid_origin, grid_extent, grid_resolution,
    sample_points, sample_normals :
        See :func:`carve_with_sun_rays` for shared parameter descriptions.
    config : user_config
        Must contain ``tilted_plane_angle_deg`` — a single angle in degrees,
        or an 8-element list [N, NE, E, SE, S, SW, W, NW] for octant lookup.
    return_counts : bool, default False
        If True, return a 4th element: per-voxel hit counts (int32 array).

    Returns
    -------
    carved_grid : torch.Tensor, shape (D, D, D)
    ray_origins : np.ndarray, shape (N, 3)
    ray_directions : np.ndarray, shape (N, 3)
    counts : np.ndarray, shape (V,), optional
        Only returned when *return_counts* is True.

    Notes
    -----
    • The underlying tracer samples at cell centers with floor indexing to
      avoid checkerboarding on regular planar lattices (see
      :func:`~urbansolarcarver.raytracer.trace_multi_hit_grid`).
    """
    _validate_cubic_resolution(grid_resolution, "carve_tilted_plane")
    side_len = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])
    side_len_sq = side_len * side_len

    device = voxel_grid.device

    # sample points
    if isinstance(sample_points, torch.Tensor):
        pts_np = sample_points.detach().cpu().numpy().astype(np.float32)
    else:
        pts_np = np.asarray(sample_points, dtype=np.float32)

    # sample_normals
    if isinstance(sample_normals, torch.Tensor):
        norms_np = sample_normals.detach().cpu().numpy().astype(np.float32)
    else:
        norms_np = np.asarray(sample_normals, dtype=np.float32)

    # Project surface normals onto the XY (horizontal) plane.
    # This gives the outward-facing horizontal direction of each test surface,
    # which determines which octant it faces (N, NE, E, ...).
    # Z is zeroed because the tilt angle is measured FROM horizontal.
    n_xy = norms_np.copy()
    n_xy[:, 2] = 0.0
    lens = np.linalg.norm(n_xy[:, :2], axis=1, keepdims=True)
    np.maximum(lens, 1e-9, out=lens)
    n_xy[:, :2] /= lens

    # Assign a tilt angle to each sample point.
    # Scalar: all surfaces share the same angle.
    # 8-element list: each surface gets an angle based on the compass octant
    # its horizontal normal faces ([N, NE, E, SE, S, SW, W, NW]).
    spec = getattr(config, "tilted_plane_angle_deg", None)
    if isinstance(spec, (int, float)) or np.isscalar(spec):
        alpha_deg = np.full((n_xy.shape[0],), float(spec), dtype=np.float32)
    else:
        table = np.asarray(spec, dtype=np.float32)
        if table.shape != (8,):
            raise ValueError(
                "tilted_plane_angle_deg must be a single number or an 8-length list [N, NE, E, SE, S, SW, W, NW]"
            )
        # Compute the model-space azimuth from +Y clockwise toward +X, then
        # subtract north_deg (model north, degrees clockwise from +Y) to get
        # the true compass azimuth of each surface normal.
        north_deg = float(getattr(config, "north_deg", 0.0) or 0.0)
        phi = (np.degrees(np.arctan2(n_xy[:, 0], n_xy[:, 1])) - north_deg + 360.0) % 360.0
        # 22.5° = 360° / (8 × 2) — half-octant offset so bin centers align with
        # cardinal/intercardinal directions (N=0°, NE=45°, E=90°, ...)
        # 45° = 360° / 8 — angular width of each octant bin
        idx = np.floor(((phi + 22.5) % 360.0) / 45.0).astype(np.int64)
        alpha_deg = table[idx]

    alpha_rad = np.radians(alpha_deg).astype(np.float32)

    # Construct ray direction: d = cos(a)*n_xy + sin(a)*z_hat
    # Interpolates between horizontal (a=0) and vertical (a=90 deg).
    # At a=45 deg the ray tilts 45 deg above the horizon, outward
    # in the direction the surface faces.
    dirs_np = (
        np.cos(alpha_rad)[:, None] * n_xy
        + np.sin(alpha_rad)[:, None] * np.array([[0.0, 0.0, 1.0]], dtype=np.float32)
    )
    dirs_np /= np.maximum(np.linalg.norm(dirs_np, axis=1, keepdims=True), 1e-9)
    dirs_np = dirs_np.astype(np.float32)

    # carve via tracer
    origins_tensor = torch.from_numpy(pts_np).to(device, non_blocking=True)
    dirs_tensor = torch.from_numpy(dirs_np).to(device, non_blocking=True)

    voxel_occupancy_flat = voxel_grid.reshape(-1).clone().float()
    counts = None
    if return_counts:
        counts = torch.zeros_like(voxel_occupancy_flat, dtype=torch.int32)

    grid_min_corner = (float(grid_origin[0]), float(grid_origin[1]), float(grid_origin[2]))
    scale_tensor = float(grid_extent)
    batch_size = _resolve_batch_size(config, side_len, device)

    total_rays = origins_tensor.shape[0]
    for batch_start in range(0, total_rays, batch_size):
        origins_batch = origins_tensor[batch_start: batch_start + batch_size]
        dirs_batch = dirs_tensor[batch_start: batch_start + batch_size]
        if origins_batch.numel() == 0:
            break

        # required by tracer but unused for carving
        patch_ids_placeholder = torch.zeros((origins_batch.shape[0],), dtype=torch.long, device=device)

        _, _, visited_voxel_indices = trace_multi_hit_grid(
            min_corner=grid_min_corner,
            scale=scale_tensor,          # full-box world extent
            resolution=side_len,         # cubic grid
            origins=origins_batch,
            ray_dirs=dirs_batch,
            sky_patch_ids=patch_ids_placeholder,
            voxel_size=float(config.voxel_size),
            ray_length=float(config.ray_length),
        )

        if visited_voxel_indices.numel() > 0:
            flat_indices = (
                visited_voxel_indices[:, 0] * side_len_sq
                + visited_voxel_indices[:, 1] * side_len
                + visited_voxel_indices[:, 2]
            )
            valid = (flat_indices >= 0) & (flat_indices < voxel_occupancy_flat.numel())
            flat_indices = flat_indices[valid]
            voxel_occupancy_flat[flat_indices] = 0
            if counts is not None:
                counts.index_add_(0, flat_indices, torch.ones_like(flat_indices, dtype=torch.int32))

    carved_grid = voxel_occupancy_flat.view_as(voxel_grid).to(voxel_grid.dtype)
    if counts is None:
        return carved_grid, pts_np, dirs_np
    return carved_grid, pts_np, dirs_np, counts.detach().cpu().numpy()


def carve_directional(
    voxel_grid,
    grid_origin,
    grid_extent,
    grid_resolution,
    sample_points,
    sample_normals,
    config: "user_config",
    mode: Literal["vector", "normals", "positive_z"] = "vector",
    direction: Tuple[float, float, float] | None = None,
):
    """
    Simple directional carving primitive (geometry-only, no scoring).

    March rays from `sample_points` and delete all visited voxels.
    Unlike :func:`carve_with_sun_rays` and :func:`carve_with_planes`,
    ``return_counts`` is not supported here because this mode produces
    a binary mask without score accumulation.

    Direction can be:
      • "vector"     — one global world-space vector for all points
      • "normals"    — the per-point surface normal
      • "positive_z" — +Z for all points (vertical clearance)

    Parameters
    ----------
    mode : Literal["vector","normals","positive_z"]
        Direction policy.
    direction : tuple[float, float, float] | None
        Required when `mode=="vector"`. Ignored otherwise.

    Returns
    -------
    carved_grid : torch.Tensor, shape (D, D, D)
    ray_origins : np.ndarray, shape (N, 3)
    ray_directions : np.ndarray, shape (N, 3)

    Notes
    -----
    • This is geometry-only; it ignores EPW and weights.
    • Useful for vertical setbacks ("positive_z") or view corridors
      along a fixed vector.
    """
    _validate_cubic_resolution(grid_resolution, "carve_directional")
    side = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])
    side_sq = side * side

    # Inputs to numpy
    pts_np = sample_points.detach().cpu().numpy().astype(np.float32) if isinstance(sample_points, torch.Tensor) else np.asarray(sample_points, dtype=np.float32)
    if mode == "normals":
        norms_np = sample_normals.detach().cpu().numpy().astype(np.float32) if isinstance(sample_normals, torch.Tensor) else np.asarray(sample_normals, dtype=np.float32)
        dirs_np = norms_np
    elif mode == "positive_z":
        dirs_np = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (pts_np.shape[0], 1))
    else:
        if direction is None:
            raise ValueError("carve_directional(mode='vector') requires `direction=(x,y,z)`")
        d = np.asarray(direction, dtype=np.float32)
        n = np.linalg.norm(d)
        if n < 1e-9:
            raise ValueError("direction must be non-zero")
        d /= n
        dirs_np = np.tile(d, (pts_np.shape[0], 1))

    # Normalize directions
    nrm = np.linalg.norm(dirs_np, axis=1, keepdims=True)
    np.maximum(nrm, 1e-9, out=nrm)
    dirs_np = dirs_np / nrm

    device = voxel_grid.device
    origins_tensor = torch.from_numpy(pts_np).to(device, non_blocking=True)
    dirs_tensor    = torch.from_numpy(dirs_np).to(device, non_blocking=True)
    voxel_flat     = voxel_grid.reshape(-1).clone().float()

    min_corner = (float(grid_origin[0]), float(grid_origin[1]), float(grid_origin[2]))
    scale      = float(grid_extent)
    res = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])
    batch_size = _resolve_batch_size(config, res, device)

    for i in range(0, origins_tensor.shape[0], batch_size):
        o = origins_tensor[i:i+batch_size]
        d = dirs_tensor[i:i+batch_size]
        if o.numel() == 0:
           break
        dummy = torch.zeros((o.shape[0],), dtype=torch.long, device=device)
        _, _, vox_idx = trace_multi_hit_grid(
            min_corner=min_corner,
            scale=scale,
            resolution=side,
            origins=o,
            ray_dirs=d,
           sky_patch_ids=dummy,
            voxel_size=float(config.voxel_size),
            ray_length=float(config.ray_length),
        )
        if vox_idx.numel():
            flat_idx = vox_idx[:,0]*side_sq + vox_idx[:,1]*side + vox_idx[:,2]
            valid = (flat_idx >= 0) & (flat_idx < voxel_flat.numel())
            flat_idx = flat_idx[valid]
            voxel_flat[flat_idx] = 0

    carved = voxel_flat.view_as(voxel_grid).to(voxel_grid.dtype)
    return carved, pts_np, dirs_np


def carve_above_columns(
    mask: "np.ndarray",
    voxel_grid: "np.ndarray",
    min_consecutive: int = 1,
) -> "np.ndarray":
    """Carve occupied voxels above the lowest sufficiently-carved run per column.

    For each (x, y) column, scans bottom-to-top (z=0 upward) for runs of
    consecutive carved (False) voxels:

    * Runs with length >= *min_consecutive* **trigger** carve-above: all
      occupied voxels above the run are carved.  The first (lowest)
      qualifying run triggers; scanning stops for that column.
    * Runs with length < *min_consecutive* are treated as noise and
      **patched** back to kept (True).

    Parameters
    ----------
    mask : ndarray (D, D, D) bool
        Thresholding mask.  True = keep, False = carved.  Not mutated.
    voxel_grid : ndarray (D, D, D) bool
        Original envelope occupancy.  True = occupied.
    min_consecutive : int
        Minimum consecutive carved voxels to trigger carve-above.
        Shorter runs are patched (filled back in).

    Returns
    -------
    ndarray (D, D, D) bool
        Modified mask with short runs patched and voxels above qualifying
        runs carved.
    """
    out = np.ascontiguousarray(mask.astype(bool, copy=True))
    occ = np.ascontiguousarray(voxel_grid.astype(bool, copy=False))
    _carve_above_kernel(out, occ, int(min_consecutive))
    return out


@njit(cache=True)
def _carve_above_kernel(out, voxel_grid, min_consecutive):
    """Numba kernel for :func:`carve_above_columns` — mutates *out* in place.

    Scans each column bottom-to-top: short carved runs are patched back to
    kept; the first run of >= min_consecutive carved voxels triggers
    carve-above for all occupied voxels higher in that column.
    """
    nx, ny, nz = out.shape
    for x in range(nx):
        for y in range(ny):
            trigger_top = -1
            z = 0
            while z < nz:
                if not out[x, y, z]:  # carved voxel — start of a run
                    run_start = z
                    while z < nz and not out[x, y, z]:
                        z += 1
                    if z - run_start >= min_consecutive:
                        trigger_top = z - 1
                        break
                    # Short run — noise: patch carved voxels back to kept.
                    for zz in range(run_start, z):
                        out[x, y, zz] = True
                else:
                    z += 1

            if trigger_top >= 0:
                for z_above in range(trigger_top + 1, nz):
                    if voxel_grid[x, y, z_above]:
                        out[x, y, z_above] = False
