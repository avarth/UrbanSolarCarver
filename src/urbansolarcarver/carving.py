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

from .scoring import get_weights
from .load_config import user_config
from .mode_registry import ALL_MODE_NAMES, MODES_NEEDING_EPW
from .sky_patches import fetch_tregenza_patch_directions
from .sun import get_sun_vectors
from .raytracer import (
    generate_sun_rays, generate_sky_patch_rays, trace_multi_hit_grid,
    trace_and_count_dda, auto_batch_size, dda_backend_available,
)
# Fused kernel import (conditional -- only available when Warp is installed)
try:
    from .raytracer import trace_and_score_dda as _fused_dda
except ImportError:
    _fused_dda = None
from typing import NamedTuple, Sequence


class SkyPatchCarvingResult(NamedTuple):
    """Return type for :func:`carve_with_sky_patch_rays`.

    ``ray_origins`` / ``ray_directions`` are None unless the carver was
    called with ``return_rays=True`` — transferring the full ray set to
    host memory costs hundreds of MB at typical ray counts.
    """
    ray_origins: "np.ndarray | None"      # (N, 3) ray start points, or None
    ray_directions: "np.ndarray | None"   # (N, 3) ray unit vectors, or None
    raw_voxel_scores: np.ndarray          # (X*Y*Z,) per-voxel weighted scores
    patch_weights: np.ndarray             # (P,) weight per Tregenza sky patch

# High-level helpers migrated from api_core
import os
from ladybug.analysisperiod import AnalysisPeriod
from .io import load_mesh

def _resolve_batch_size(config, resolution: int, device) -> int:
    """Return the effective ray batch size, auto-tuning if requested.

    If ``config.ray_batch_size`` is 0 the batch size is computed from
    available GPU memory via :func:`auto_batch_size`.
    """
    if config.ray_batch_size > 0:
        return int(config.ray_batch_size)
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

def sample_period(config: user_config, steps_per_hour: int = 1):
    """
    Build analysis datetimes and HOYs via Ladybug's AnalysisPeriod.

    Returns
    -------
    datetimes : list[datetime.datetime]
        Start→end (inclusive) at ``1/steps_per_hour``-hour steps.
    hoys : list[int]
        Hour-of-year indices (1..8760) of the period, always hourly: they
        index EPW records, which are hourly.
    """
    def _ap(timestep):
        return AnalysisPeriod(
            st_month=config.start_month, st_day=config.start_day, st_hour=config.start_hour,
            end_month=config.end_month,   end_day=config.end_day,   end_hour=config.end_hour,
            timestep=timestep,
        )
    hourly = _ap(1)
    if steps_per_hour == 1:
        return hourly.datetimes, hourly.hoys_int
    return _ap(steps_per_hour).datetimes, hourly.hoys_int

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
    for path, mesh in ((config.max_volume_path, envelope_mesh),
                       (config.test_surface_path, insolation_mesh)):
        _warn_float32_input(path, mesh, config.voxel_size)
    return envelope_mesh, insolation_mesh


def _stores_float32_vertices(path: str) -> bool:
    if not str(path).lower().endswith(".ply"):
        return False
    with open(path, "rb") as fh:
        header = fh.read(4096).split(b"end_header")[0].decode("ascii", errors="replace")
    return any(line.split()[:3] in (["property", "float", "x"], ["property", "float32", "x"])
               for line in header.splitlines())


def _warn_float32_input(path: str, mesh, voxel_size: float) -> None:
    """Georeferenced coordinates in a float32 PLY are already rounded on disk."""
    from .io import float32_resolution
    res = float32_resolution(mesh.vertices)
    if res > 0.01 * float(voxel_size) and _stores_float32_vertices(path):
        warnings.warn(
            f"{os.path.basename(path)}: coordinates reach "
            f"{float(np.abs(mesh.vertices).max()):,.0f} m and the file stores "
            f"float32 vertices, so its geometry is rounded to ~{res:.2g} m on disk "
            f"({100 * res / voxel_size:.0f}% of a voxel). Move the model near the "
            f"origin before export, or export PLY with double-precision vertices.",
            stacklevel=3,
        )

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

def _front_of_surface(min_corner, cell, voxel_idx, origins, normals) -> torch.Tensor:
    """Mask of hits whose voxel centre lies in front of the ray's source surface.

    A test surface sits inside the boundary voxels of its own mass; those
    voxels are the building, not an obstruction of it.  Same rule as the
    Warp kernels' ``_in_front``, for the buffered / fixed-step fallbacks.
    """
    corner = torch.tensor(min_corner, dtype=torch.float32, device=voxel_idx.device)
    centre = corner + (voxel_idx.float() + 0.5) * cell
    return ((centre - origins) * normals).sum(dim=1) > 0.0


_CPU_BUFFER_BUDGET_BYTES = 1 << 30  # extra per-thread accumulation buffers


def _run_batches(batch_ranges, launch, out, device, parallel: bool) -> None:
    """Call ``launch(start, end, buffer)`` for every batch, accumulating into *out*.

    On CPU, Warp kernel launches release the GIL, so a few threads can run
    batches on separate cores. Warp's CPU ``atomic_add`` is a plain
    read-modify-write, not atomic across threads, so each thread writes its
    own buffer and the buffers are summed at the end. The first batch runs
    alone because it triggers Warp's one-time module compile.
    """
    if not parallel or device.type != "cpu" or len(batch_ranges) < 2:
        for start, end in batch_ranges:
            launch(start, end, out)
        return

    launch(*batch_ranges[0], out)
    rest = batch_ranges[1:]
    buffer_bytes = out.numel() * out.element_size()
    n_workers = min(4, os.cpu_count() or 1, len(rest),
                    max(1, _CPU_BUFFER_BUDGET_BYTES // max(buffer_bytes, 1)))
    if n_workers < 2:
        for start, end in rest:
            launch(start, end, out)
        return

    from concurrent.futures import ThreadPoolExecutor
    buffers = [torch.zeros_like(out) for _ in range(n_workers)]
    chunks = [rest[i::n_workers] for i in range(n_workers)]

    def _work(i):
        for start, end in chunks[i]:
            launch(start, end, buffers[i])

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        list(pool.map(_work, range(n_workers)))  # list() re-raises worker exceptions
    for buf in buffers:
        out += buf


def _count_ray_hits(voxel_grid, min_corner, scale, res, origins, directions, config,
                    point_ids, surface_normals):
    """Count how many rays visit each voxel; returns a flat int32 tensor.

    Uses the fused Warp count kernel when available (no hit buffers, no
    overflow-retry re-tracing); otherwise falls back to the buffered
    :func:`trace_multi_hit_grid` path.  Both count each (ray, voxel) pair
    at most once, and skip voxels behind the ray's source surface
    (*point_ids* maps rays to rows of *surface_normals*).
    """
    device = voxel_grid.device
    counts = torch.zeros(voxel_grid.numel(), dtype=torch.int32, device=device)
    batch_size = _resolve_batch_size(config, res, device)
    res_sq = res * res

    if dda_backend_available(device):
        batch_ranges = [
            (start, min(start + batch_size, origins.shape[0]))
            for start in range(0, origins.shape[0], batch_size)
        ]

        def _count_batch(start, end, buf):
            trace_and_count_dda(
                min_corner, scale, res,
                origins[start:end], directions[start:end],
                buf, float(config.ray_length),
                point_ids=point_ids[start:end], surface_normals=surface_normals,
            )

        _run_batches(batch_ranges, _count_batch, counts, device, parallel=True)
        # Warp launches run on Warp's own CUDA stream; the counts buffer is
        # shared zero-copy with torch, so synchronize before torch reads it.
        if device.type == "cuda":
            torch.cuda.synchronize()
        return counts

    for i in range(0, origins.shape[0], batch_size):
        o_batch = origins[i: i + batch_size]
        d_batch = directions[i: i + batch_size]
        # tracer requires per-ray patch ids; unused for counting
        patch_ids_stub = torch.zeros((o_batch.shape[0],), dtype=torch.long, device=device)
        ray_idx, _, voxel_idx = trace_multi_hit_grid(
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
            front = _front_of_surface(min_corner, scale / res, voxel_idx, o_batch[ray_idx],
                                      surface_normals[point_ids[i: i + batch_size][ray_idx]])
            voxel_idx = voxel_idx[front]
        if voxel_idx.numel() > 0:
            # 3D → 1D index in row-major (C) order: x*(res²) + y*res + z
            flat_idx = voxel_idx[:, 0] * res_sq + voxel_idx[:, 1] * res + voxel_idx[:, 2]
            counts.index_add_(0, flat_idx, torch.ones_like(flat_idx, dtype=torch.int32))
    return counts


def _carve_by_counts(voxel_grid, counts) -> torch.Tensor:
    """Remove every voxel visited by at least one ray."""
    keep = counts.view_as(voxel_grid) == 0
    return (voxel_grid.bool() & keep).to(voxel_grid.dtype)


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
    return_rays: bool = False,
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
      3. Trace each ray through the grid (exact Warp DDA when available),
         counting hits per voxel.
      4. Remove every voxel visited by at least one ray.

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
    return_rays : bool, default False
        If True, return the full ray set as host numpy arrays.  Off by
        default: at millions of rays this is hundreds of MB of
        device→host transfer that the pipeline never uses.

    Returns
    -------
    carved_grid : torch.Tensor, shape (X, Y, Z)
        Voxel grid after removing all cells intersected by any traced ray.
    ray_origins : np.ndarray, shape (N, 3), or None
        World-space ray start points (None unless *return_rays* is True).
    ray_directions : np.ndarray, shape (N, 3), or None
        Unit ray directions (None unless *return_rays* is True).
    counts : np.ndarray, shape (V,), optional
        Per-voxel hit counts (flat).  Only returned when *return_counts* is True.
    """
    _validate_cubic_resolution(grid_resolution, "carve_with_sun_rays")
    res = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])

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
        empty = np.empty((0, 3), dtype=np.float32) if return_rays else None
        if return_counts:
            return voxel_grid.clone(), empty, empty, np.zeros(voxel_grid.numel(), dtype=np.int32)
        return voxel_grid.clone(), empty, empty
    # 1e-9 epsilon prevents division by zero for degenerate sun vectors
    # (e.g. sun exactly at horizon). Float32 machine epsilon is ~1.2e-7,
    # so 1e-9 is safely below it.
    sun_arr = sun_arr / (sun_arr.norm(dim=1, keepdim=True) + 1e-9)

    # build rays
    normals_np = (sample_normals.detach().cpu().numpy()
                  if isinstance(sample_normals, torch.Tensor) else np.asarray(sample_normals))
    points_np = (sample_points.detach().cpu().numpy()
                 if isinstance(sample_points, torch.Tensor) else np.asarray(sample_points))
    origins, directions, point_idx = generate_sun_rays(
        points_np, normals_np, sun_arr.cpu().numpy(), voxel_grid.device,
        return_point_idx=True,
    )
    surface_normals = torch.as_tensor(normals_np, dtype=torch.float32, device=voxel_grid.device)
    ray_origins = origins.cpu().numpy() if return_rays else None
    ray_directions = directions.cpu().numpy() if return_rays else None

    # scale is the cubic grid extent in world units (meters), not per-voxel size
    min_corner = (float(grid_origin[0]), float(grid_origin[1]), float(grid_origin[2]))
    counts = _count_ray_hits(
        voxel_grid, min_corner, float(grid_extent), res, origins, directions, config,
        point_idx, surface_normals,
    )
    carved_grid = _carve_by_counts(voxel_grid, counts)

    if not return_counts:
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
    hoys: Sequence[int],
    return_rays: bool = False,
    point_weights: "np.ndarray | None" = None,
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
    return_rays : bool, default False
        If True, include the full ray set (host numpy arrays) in the
        result.  Off by default: at millions of rays this is hundreds of
        MB of device→host transfer that the pipeline never uses.
    point_weights : np.ndarray (R,), optional
        Per-sample-point design weights in [0, 1] (edge_taper): each ray's
        contribution is patch_weight × point_weight, and zero-weight rays
        are dropped before tracing.  None (default) = all points count
        fully.

    Returns
    -------
    SkyPatchCarvingResult
        NamedTuple with fields:
        - ray_origins (N, 3): ray start points, or None unless return_rays.
        - ray_directions (N, 3): unit ray vectors, or None unless return_rays.
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
    # point_idx maps each ray back to its source sample point — needed when
    # per-point design weights (edge_taper) are active.
    ray_origins, ray_directions, patch_ids, point_idx = (
        generate_sky_patch_rays(
            sample_points,
            sample_normals,
            sky_dirs,
            device=device
        )
    )
    surface_normals = torch.as_tensor(sample_normals, dtype=torch.float32, device=device)

    # --- 2b) Per-point design weights (edge_taper) -------------------------
    # Fold sample-point weights into per-ray weighting; rays from
    # zero-weight points contribute nothing, so drop them before tracing.
    pw_t = None
    if point_weights is not None:
        pw_t = torch.as_tensor(point_weights, dtype=torch.float32, device=device)
        n_pts = sample_points.shape[0]
        if pw_t.numel() != n_pts:
            raise ValueError(
                f"carve_with_sky_patch_rays: point_weights length "
                f"{pw_t.numel()} does not match sample_points ({n_pts})"
            )
        keep = pw_t[point_idx] > 0.0
        if not bool(keep.all()):
            ray_origins = ray_origins[keep]
            ray_directions = ray_directions[keep]
            patch_ids = patch_ids[keep]
            point_idx = point_idx[keep]
    ray_point_ids = point_idx.to(torch.int32)

    total_rays = ray_origins.size(0)  # after facing and zero-weight filtering

    # --- 3) Patch weights: one value per sky patch for the chosen mode -----
    patch_weights = get_weights(
        mode=config.mode,
        device=device,
        epw_file=config.epw_path,
        hoys=hoys,
        dew_point_celsius=config.dew_point_celsius,
        bliss_k=config.bliss_k,
        balance_temperature=config.balance_temperature,
        balance_offset=config.balance_offset,
        north_deg=config.north_deg,
        min_sky_elevation_deg=config.min_sky_elevation_deg,
        include_harm=config.include_harm,
        simulated_weights_path=config.simulated_weights_path,
    )

    # --- 4) Initialize score accumulation ---------------------------------
    num_voxels = voxel_grid.numel()     # Total voxels = X*Y*Z
    scores = torch.zeros(num_voxels, device=device)  # Accumulator for voxel scores
    grid_extent_m = float(grid_extent)  # Full world-space extent of the cubic voxel grid (meters)

    # --- 5) Batch ray tracing & weighting ----------------------------------
    res = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])
    batch_size = _resolve_batch_size(config, res, device)
    use_fused = (_fused_dda is not None and dda_backend_available(device))

    def _score_batch(start: int, end: int, buf) -> None:
        origins_batch = ray_origins[start:end]
        directions_batch = ray_directions[start:end]
        patches_batch = patch_ids[start:end]

        if use_fused:
            # Trace and accumulate in one Warp kernel, writing into buf.
            _fused_dda(
                grid_origin, float(grid_extent_m), res,
                origins_batch, directions_batch, patches_batch,
                patch_weights, buf, config.ray_length,
                point_ids=ray_point_ids[start:end],
                point_weights=pw_t,
                surface_normals=surface_normals,
            )
            return

        # Fallback without Warp: trace, then accumulate with torch.
        hit_ray_ids, hit_patch_ids, hit_voxel_idxs = trace_multi_hit_grid(
            grid_origin, grid_extent_m, res,
            origins_batch, directions_batch, patches_batch,
            config.voxel_size, config.ray_length,
        )
        if hit_voxel_idxs.numel() == 0:
            return
        front = _front_of_surface(
            grid_origin, grid_extent_m / res, hit_voxel_idxs, origins_batch[hit_ray_ids],
            surface_normals[point_idx[start:end][hit_ray_ids]],
        )
        hit_ray_ids, hit_patch_ids, hit_voxel_idxs = (
            hit_ray_ids[front], hit_patch_ids[front], hit_voxel_idxs[front])
        if hit_voxel_idxs.numel() == 0:
            return

        idx_flat = (
            hit_voxel_idxs[:, 0] * res * res +
            hit_voxel_idxs[:, 1] * res +
            hit_voxel_idxs[:, 2]
        )

        # trace_multi_hit_grid guarantees each (ray, voxel) pair
        # appears at most once, so weights can be accumulated directly.
        weights_for_hits = patch_weights[hit_patch_ids]
        if pw_t is not None:
            # hit_ray_ids index into this batch; map back to sample points.
            weights_for_hits = weights_for_hits * pw_t[
                point_idx[start:end][hit_ray_ids]
            ]

        buf.scatter_add_(0, idx_flat, weights_for_hits)

    batch_ranges = [
        (start, min(start + batch_size, total_rays))
        for start in range(0, total_rays, batch_size)
    ]
    with torch.no_grad():
        _run_batches(batch_ranges, _score_batch, scores, device, parallel=use_fused)

    # Synchronize GPU before reading scores
    if device.type == "cuda":
        torch.cuda.synchronize()

    raw_voxel_scores = scores.cpu().numpy()  # Move accumulated scores to CPU NumPy

    # Return raw scores, patch weights, and (only on request) ray geometry.
    # Thresholding and mask creation are handled exclusively by
    # api_core.thresholding — keeping them separate avoids duplication
    # and lets users re-threshold without re-tracing rays.
    return SkyPatchCarvingResult(
        ray_origins=ray_origins.cpu().numpy() if return_rays else None,
        ray_directions=ray_directions.cpu().numpy() if return_rays else None,
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
    Every voxel at or above a visited voxel in its (x, y) column is deleted:
    the ray traces the plane's section through that column, and everything
    above the plane is forbidden, not only the cells the ray crosses.

    Parameters
    ----------
    voxel_grid, grid_origin, grid_extent, grid_resolution,
    sample_points, sample_normals :
        See :func:`carve_with_sun_rays` for shared parameter descriptions.
    config : user_config
        Must contain ``tilted_plane_angle_deg`` — a single angle in degrees,
        or an 8-element list [N, NE, E, SE, S, SW, W, NW] for octant lookup.
    return_counts : bool, default False
        If True, return a 4th element: per-voxel counts, propagated up each
        column (a voxel's count is the largest ray count at or below it).

    Returns
    -------
    carved_grid : torch.Tensor, shape (D, D, D)
    ray_origins : np.ndarray, shape (N, 3)
    ray_directions : np.ndarray, shape (N, 3)
    counts : np.ndarray, shape (V,), optional
        Only returned when *return_counts* is True.
    """
    _validate_cubic_resolution(grid_resolution, "carve_tilted_plane")
    side_len = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])

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
    spec = config.tilted_plane_angle_deg
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
        north_deg = float(config.north_deg)
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

    grid_min_corner = (float(grid_origin[0]), float(grid_origin[1]), float(grid_origin[2]))
    counts = _count_ray_hits(
        voxel_grid, grid_min_corner, float(grid_extent), side_len,
        origins_tensor, dirs_tensor, config,
        torch.arange(pts_np.shape[0], device=device),
        torch.from_numpy(norms_np).to(device),
    )
    # Hits include empty cells: a ray passing over a low roof still bounds
    # the mass above that roof.
    counts = torch.cummax(counts.view(side_len, side_len, side_len), dim=2).values.reshape(-1)
    carved_grid = _carve_by_counts(voxel_grid, counts)

    if not return_counts:
        return carved_grid, pts_np, dirs_np
    return carved_grid, pts_np, dirs_np, counts.detach().cpu().numpy()


def carve_above_columns(
    mask: "np.ndarray",
    voxel_grid: "np.ndarray",
    min_consecutive: int = 1,
) -> "np.ndarray":
    """Carve occupied voxels above the lowest sufficiently-carved run per column.

    For each (x, y) column, scans bottom-to-top (z=0 upward) for runs of
    consecutive carved voxels (occupied in *voxel_grid*, False in *mask*;
    empty cells break a run and never count as carved):

    * Runs with length >= *min_consecutive* **trigger** carve-above: all
      occupied voxels above the run are carved.  The first (lowest)
      qualifying run triggers; scanning stops for that column.
    * Shorter runs do not trigger, but stay carved: the result only ever
      removes voxels, so it never re-violates the carving constraint.

    Parameters
    ----------
    mask : ndarray (D, D, D) bool
        Thresholding mask.  True = keep, False = carved.  Not mutated.
    voxel_grid : ndarray (D, D, D) bool
        Original envelope occupancy.  True = occupied.
    min_consecutive : int
        Minimum consecutive carved voxels to trigger carve-above.

    Returns
    -------
    ndarray (D, D, D) bool
        Modified mask with voxels above qualifying runs carved.
    """
    out = np.ascontiguousarray(mask.astype(bool, copy=True))
    occ = np.ascontiguousarray(voxel_grid.astype(bool, copy=False))
    _carve_above_kernel(out, occ, int(min_consecutive))
    return out


@njit(cache=True)
def _carve_above_kernel(out, voxel_grid, min_consecutive):
    """Numba kernel for :func:`carve_above_columns` — mutates *out* in place.

    Scans each column bottom-to-top: the first run of >= min_consecutive
    carved voxels triggers carve-above for all occupied voxels higher in
    that column; shorter runs are left as they are.
    """
    nx, ny, nz = out.shape
    for x in range(nx):
        for y in range(ny):
            trigger_top = -1
            z = 0
            while z < nz:
                # Only occupied voxels can be carved. Empty cells (pre-existing
                # voids, air under an overhang) neither start nor extend a run,
                # whatever the mask says about them.
                if voxel_grid[x, y, z] and not out[x, y, z]:
                    run_start = z
                    while z < nz and voxel_grid[x, y, z] and not out[x, y, z]:
                        z += 1
                    if z - run_start >= min_consecutive:
                        trigger_top = z - 1
                        break
                    # Short run: too small to trigger, but it stays carved —
                    # refilling would undo the solar constraint.
                else:
                    z += 1

            if trigger_top >= 0:
                for z_above in range(trigger_top + 1, nz):
                    if voxel_grid[x, y, z_above]:
                        out[x, y, z_above] = False
