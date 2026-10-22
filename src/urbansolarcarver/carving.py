"""
UrbanSolarCarver: carving utilities
===================================

Purpose
-------
Convert point/normal samples on analysis surfaces into ray sets, trace those
through a voxelized envelope, and count or score the voxels they visit.
Supports:

• Time-based solar carving (sun vectors from the EPW for specific datetimes):
  every visited voxel is removed.
• Sky-patch-weighted carving (Tregenza patches + mode-specific weights):
  returns per-voxel scores; the threshold is applied later, in
  api_core/thresholding.py.
• Tilted-plane daylight carving (single or per-octant plane angle): every
  voxel at or above a visited voxel in its column is removed; extra rays
  rotate the plane around convex turns of the test-surface outline.

Raytracing contract
-------------------
Rays are traced by the fused DDA kernels of warp_kernels.py (launched from
ray_tracing.py), which visit every voxel a ray crosses exactly once and
accumulate counts or scores in place; without Warp the carvers raise
WarpBackendUnavailableError.  The kernels count voxels that lie entirely
in front of the surface a ray starts from, plus the surface's skin voxels
(crossed by its plane) that are occupied and have nothing of the max
volume behind them.  Occupied skin voxels with max volume behind them are
the surface's own skin: not counted, but raised to the value of the voxel
behind them once tracing is done (`_follow_mass_behind_skin`), so they
never outlast the mass behind them.

Coordinate/scale conventions
----------------------------
`grid_origin` is the world-space min corner for grid index [0,0,0].
`grid_extent` is the physical cube size (meters). `grid_resolution` is D, the
number of voxels per side, so one voxel is `grid_extent / D` meters wide.
The tracers receive `scale = grid_extent`.

Determinism and batching
------------------------
Given a fixed config, hit counts are deterministic. Float scores are summed
with atomic adds on the GPU, so the order of additions, and therefore the last
bits of a score, can differ between runs. Rays are processed in batches of
the `ray_batch_size` run option (0 = sized from free GPU memory) on the device of the
input voxel grid.
"""

import os
import queue
import threading
import torch
import numpy as np

from .scoring import get_weights
from .stage_settings import PreprocessingSettings
from .sky_patches import fetch_tregenza_patch_directions
from .sun import get_sun_vectors
from .run_context import active_context, report_issue, report_progress
from .ray_tracing import (
    generate_sun_rays, generate_sky_patch_rays, trace_and_count_dda, trace_and_score_dda,
    follow_mass_behind_skin_dda, auto_batch_size,
)
from .warp_kernels import require_dda_backend
from typing import NamedTuple, Sequence


class SkyPatchCarvingResult(NamedTuple):
    """Return type for :func:`carve_with_sky_patch_rays`.

    ``ray_origins`` / ``ray_directions`` are None unless the carver was
    called with ``return_rays=True``: copying the full ray set to host
    memory costs hundreds of MB at typical ray counts.
    """
    ray_origins: "np.ndarray | None"      # (N, 3) ray start points, or None
    ray_directions: "np.ndarray | None"   # (N, 3) ray unit vectors, or None
    raw_voxel_scores: np.ndarray          # (X*Y*Z,) float32 per-voxel weighted scores
    patch_weights: np.ndarray             # (P,) weight per Tregenza sky patch


def _resolve_batch_size(device, *, ray_batch_size: int) -> int:
    """Return the effective ray batch size, auto-tuning if requested.

    If *ray_batch_size* is 0 the batch size is computed from free GPU
    memory via :func:`auto_batch_size` (a fixed default on CPU).
    """
    if ray_batch_size > 0:
        return int(ray_batch_size)
    return auto_batch_size(device)


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

      
#--- Ray tracing and carving -----------------------------------------------------------------------------------

def _follow_mass_behind_skin(values, min_corner, scale, res,
                             origins, directions, point_ids, surface_normals,
                             occupancy, ray_length):
    """Raise every own-skin voxel to the value of the voxel behind it.

    A voxel the source surface's plane passes through, with occupied max
    volume behind it, is the surface's own skin: the surface's rays do not
    count it, but it must not outlast the mass behind it.  *values* are the
    finished flat counts or scores.  Runs the Warp pass over the rays and
    returns a new tensor.
    """
    return follow_mass_behind_skin_dda(
        min_corner, scale, res, origins, directions, point_ids,
        surface_normals, occupancy, values, ray_length,
    )


_CPU_BUFFER_BUDGET_BYTES = 1 << 30  # 1 GiB cap on the per-thread accumulation buffers


def _run_batches(batch_ranges, launch, out, device, parallel: bool) -> None:
    """Call ``launch(start, end, buffer)`` for every batch, accumulating into *out*.

    On CPU, Warp kernel launches release the GIL, so a few threads can run
    batches on separate cores. Warp's CPU ``atomic_add`` is a plain
    read-modify-write, not atomic across threads, so each thread writes its
    own buffer and the buffers are summed at the end. The first batch runs
    alone because it triggers Warp's one-time module compile.

    The active run context is checked for cancellation before each batch and
    told how many batches are done after each one.  Context variables do not
    reach worker threads, so the context is read here, on the calling thread,
    and handed to the workers; progress is reported from the calling thread.
    """
    context = active_context()
    total = len(batch_ranges)

    def run_in_order(ranges, buffer, done):
        for start, end in ranges:
            if context is not None:
                context.raise_if_cancelled()
            launch(start, end, buffer)
            done += 1
            report_progress(done, total)
        return done

    if not parallel or device.type != "cpu" or total < 2:
        run_in_order(batch_ranges, out, 0)
        return

    done = run_in_order(batch_ranges[:1], out, 0)
    rest = batch_ranges[1:]
    buffer_bytes = out.numel() * out.element_size()
    n_workers = min(4, os.cpu_count() or 1, len(rest),
                    max(1, _CPU_BUFFER_BUDGET_BYTES // max(buffer_bytes, 1)))
    if n_workers < 2:
        run_in_order(rest, out, done)
        return

    from concurrent.futures import ThreadPoolExecutor
    buffers = [torch.zeros_like(out) for _ in range(n_workers)]
    chunks = [rest[i::n_workers] for i in range(n_workers)]
    finished_batches = queue.Queue()
    stop_workers = threading.Event()

    def _work(i):
        try:
            for start, end in chunks[i]:
                if stop_workers.is_set():
                    return
                if context is not None:
                    context.raise_if_cancelled()
                launch(start, end, buffers[i])
                finished_batches.put(1)
        except BaseException:
            stop_workers.set()  # cancelled or failed: the other workers stop at their next batch
            raise

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = [pool.submit(_work, i) for i in range(n_workers)]
        try:
            while done < total:
                try:
                    finished_batches.get(timeout=0.05)
                except queue.Empty:
                    if all(future.done() for future in futures):
                        break  # a worker stopped early: cancelled or failed
                    continue
                done += 1
                report_progress(done, total)
        except BaseException:
            stop_workers.set()  # a failing progress callback must not leave the pool running
            raise
        # The loop can end on an empty queue just before the last batches of
        # finished workers arrive in it; report those too.
        while True:
            try:
                finished_batches.get_nowait()
            except queue.Empty:
                break
            done += 1
            report_progress(done, total)
    for future in futures:
        future.result()  # re-raises the first worker exception, RunCancelled included
    for buf in buffers:
        out += buf


def _count_ray_hits(voxel_grid, min_corner, scale, res, origins, directions,
                    settings: PreprocessingSettings, point_ids, surface_normals, occupancy,
                    *, ray_batch_size: int):
    """Count how many rays visit each voxel with the fused Warp count kernel.

    Each (ray, voxel) pair counts at most once.  Voxels behind the ray's
    source surface (*point_ids* maps rays to rows of *surface_normals*) and
    its own skin (crossed by its plane, with max volume behind it;
    *occupancy* is the flat uint8 grid) are skipped.  Returns a flat int32
    tensor.  The carvers check first that Warp can run on the grid's device.
    """
    device = voxel_grid.device
    counts = torch.zeros(voxel_grid.numel(), dtype=torch.int32, device=device)
    batch_size = _resolve_batch_size(device, ray_batch_size=ray_batch_size)
    batch_ranges = [
        (start, min(start + batch_size, origins.shape[0]))
        for start in range(0, origins.shape[0], batch_size)
    ]

    def _count_batch(start, end, buf):
        trace_and_count_dda(
            min_corner, scale, res,
            origins[start:end], directions[start:end],
            buf, float(settings.ray_length),
            point_ids=point_ids[start:end], surface_normals=surface_normals,
            occupancy=occupancy,
        )

    _run_batches(batch_ranges, _count_batch, counts, device, parallel=True)
    # Warp launches run on Warp's own CUDA stream; the counts buffer is
    # shared zero-copy with torch, so synchronize before torch reads it.
    if device.type == "cuda":
        torch.cuda.synchronize()
    return counts

def _occupancy_flat(voxel_grid) -> torch.Tensor:
    """Flat contiguous uint8 copy of the max volume occupancy (1 = occupied)."""
    return (voxel_grid.reshape(-1) != 0).to(torch.uint8).contiguous()


def _carve_by_counts(voxel_grid, counts) -> torch.Tensor:
    """Remove every voxel visited by at least one ray."""
    keep = counts.view_as(voxel_grid) == 0
    return (voxel_grid.bool() & keep).to(voxel_grid.dtype)


class SunRaySet(NamedTuple):
    """Rays from the sample points toward the sun (:func:`sun_ray_set`)."""
    origins: torch.Tensor          # (N, 3) ray start points
    directions: torch.Tensor       # (N, 3) unit vectors toward the sun
    point_ids: torch.Tensor        # (N,) source sample point per ray
    surface_normals: torch.Tensor  # (P, 3) float32 normal per sample point


def sun_ray_set(device, sample_points, sample_normals, settings: PreprocessingSettings,
                datetimes) -> "SunRaySet | None":
    """The rays of time-based carving: from each sample point toward the sun
    at each of *datetimes* that it faces, on *device*.

    Uses ``epw_path``, ``min_altitude``, ``north_deg`` and ``time_basis``
    of *settings*.  Returns None when no sun position is above
    ``min_altitude``.
    """
    # Sun directions in model coordinates (rotated by north_deg).
    sun_dirs = get_sun_vectors(
        settings.epw_path, datetimes, settings.min_altitude,
        north_deg=settings.north_deg, time_basis=settings.time_basis,
    )
    if isinstance(sun_dirs, torch.Tensor):
        sun_arr = sun_dirs.clone().detach().to(device)
    else:
        sun_arr = torch.as_tensor(sun_dirs, dtype=torch.float32, device=device)
    if sun_arr.numel() == 0:
        return None
    # The 1e-9 guards against division by zero for a zero-length vector. It is
    # far below float32 precision (~1.2e-7), so unit vectors are unchanged.
    sun_arr = sun_arr / (sun_arr.norm(dim=1, keepdim=True) + 1e-9)

    normals_np = (sample_normals.detach().cpu().numpy()
                  if isinstance(sample_normals, torch.Tensor) else np.asarray(sample_normals))
    points_np = (sample_points.detach().cpu().numpy()
                 if isinstance(sample_points, torch.Tensor) else np.asarray(sample_points))
    origins, directions, point_idx = generate_sun_rays(
        points_np, normals_np, sun_arr.cpu().numpy(), device,
        return_point_idx=True,
    )
    surface_normals = torch.as_tensor(normals_np, dtype=torch.float32, device=device)
    return SunRaySet(origins, directions, point_idx, surface_normals)


class SkyPatchRaySet(NamedTuple):
    """Rays and weights of the sky-patch modes (:func:`sky_patch_ray_set`)."""
    origins: torch.Tensor                    # (N, 3) ray start points
    directions: torch.Tensor                 # (N, 3) unit vectors to patch centres
    patch_ids: torch.Tensor                  # (N,) sky patch per ray
    point_ids: torch.Tensor                  # (N,) int32 source sample point per ray
    surface_normals: torch.Tensor            # (P, 3) float32 normal per sample point
    point_weights: "torch.Tensor | None"     # (P,) edge_taper weight per sample point, or None
    patch_weights: torch.Tensor              # (145,) weight per sky patch for the mode


def sky_patch_ray_set(device, sample_points, sample_normals, settings: PreprocessingSettings,
                      hoys, point_weights=None) -> SkyPatchRaySet:
    """The rays and weights of the sky-patch modes, on *device*.

    One ray from each sample point toward every Tregenza patch on the
    outward side of its normal; rays of points whose *point_weights*
    (edge_taper) entry is 0 are dropped.  The patch weights are those of
    ``settings.mode`` over the hours *hoys*.

    Raises
    ------
    ValueError
        If *point_weights* does not have one entry per sample point.
    """
    # --- 1) Sky patch directions ------------------------------------------
    sky_dirs = fetch_tregenza_patch_directions(device)  # (P, 3) unit vectors to patch centres

    # --- 2) Ray generation ------------------------------------------------
    # point_idx maps each ray back to its source sample point, for the
    # behind-surface test and the per-point design weights (edge_taper).
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

    # --- 3) Patch weights: one value per sky patch for the chosen mode -----
    patch_weights = get_weights(
        mode=settings.mode,
        device=device,
        epw_file=settings.epw_path,
        hoys=hoys,
        dew_point_celsius=settings.dew_point_celsius,
        bliss_k=settings.bliss_k,
        balance_temperature=settings.balance_temperature,
        balance_offset=settings.balance_offset,
        north_deg=settings.north_deg,
        min_sky_elevation_deg=settings.min_sky_elevation_deg,
        include_harm=settings.include_harm,
        simulated_weights_path=settings.simulated_weights_path,
    )
    return SkyPatchRaySet(ray_origins, ray_directions, patch_ids, point_idx.to(torch.int32),
                          surface_normals, pw_t, patch_weights)


def carve_with_sun_rays(
    voxel_grid,
    grid_origin,
    grid_extent,
    grid_resolution,
    sample_points,
    sample_normals,
    settings: PreprocessingSettings,
    datetimes,
    return_counts: bool = False,
    return_rays: bool = False,
    *,
    ray_batch_size: int,
):
    """
    Time-based carving of a voxel grid with sun vectors for explicit datetimes.

    This builds a classical solar envelope by tracing rays toward the sun
    positions computed from the EPW location for the given datetimes. No
    scoring, normalization, or thresholding is applied here: any voxel
    visited by any ray is removed from the returned grid.

    Core procedure
      1. Compute sun vectors for the provided datetimes from the EPW file and
         drop those below ``settings.min_altitude``.
      2. For each surface sample point, build rays toward the sun directions
         on the outward side of its normal (dot product > 0).
      3. Trace each ray through the grid (exact Warp DDA when available),
         counting hits per voxel and skipping voxels behind the source surface.
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
    settings : PreprocessingSettings
        Settings used:
          - epw_path: path to EPW file used for sun positions.
          - min_altitude: degrees above horizon for filtering sun vectors.
          - north_deg: model north, degrees clockwise from +Y.
          - time_basis: "standard", "daylight_saving" or "solar", the clock
            *datetimes* are in.
          - ray_length: maximum traced distance along each ray.
    datetimes : Sequence[datetime.datetime]
        Timestamps for which sun vectors are generated, in local standard
        time, daylight saving time or true solar time (``settings.time_basis``).
    return_counts : bool, default False
        If True, return a 4th element: per-voxel hit counts (int32 array).
    return_rays : bool, default False
        If True, return the full ray set as host numpy arrays.  Off by
        default: at millions of rays this is hundreds of MB of
        device-to-host transfer that the pipeline never uses.
    ray_batch_size : int
        Rays processed per batch (0 = automatic); keyword only.

    Returns
    -------
    carved_grid : torch.Tensor, shape (X, Y, Z)
        Voxel grid after removing all cells intersected by any traced ray.
    ray_origins : np.ndarray, shape (N, 3), or None
        World-space ray start points (None unless *return_rays* is True).
    ray_directions : np.ndarray, shape (N, 3), or None
        Unit ray directions (None unless *return_rays* is True).
    counts : np.ndarray, shape (X*Y*Z,), int32, optional
        Per-voxel hit counts (flat).  Only returned when *return_counts* is True.
    """
    require_dda_backend(voxel_grid.device)
    _validate_cubic_resolution(grid_resolution, "carve_with_sun_rays")
    res = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])

    rays = sun_ray_set(voxel_grid.device, sample_points, sample_normals, settings, datetimes)
    if rays is None:
        report_issue(
            "no_sun_vectors",
            "carve_with_sun_rays: no sun vectors above min_altitude; "
            "the grid is returned unmodified.",
        )
        empty = np.empty((0, 3), dtype=np.float32) if return_rays else None
        if return_counts:
            return voxel_grid.clone(), empty, empty, np.zeros(voxel_grid.numel(), dtype=np.int32)
        return voxel_grid.clone(), empty, empty
    origins, directions, point_idx, surface_normals = rays
    ray_origins = origins.cpu().numpy() if return_rays else None
    ray_directions = directions.cpu().numpy() if return_rays else None

    # scale is the cubic grid extent in world units (meters), not per-voxel size
    min_corner = (float(grid_origin[0]), float(grid_origin[1]), float(grid_origin[2]))
    occupancy = _occupancy_flat(voxel_grid)
    counts = _count_ray_hits(
        voxel_grid, min_corner, float(grid_extent), res, origins, directions, settings,
        point_idx, surface_normals, occupancy, ray_batch_size=ray_batch_size,
    )
    counts = _follow_mass_behind_skin(
        counts, min_corner, float(grid_extent), res, origins, directions,
        point_idx, surface_normals, occupancy, float(settings.ray_length))
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
    settings: PreprocessingSettings,
    hoys: Sequence[int],
    return_rays: bool = False,
    point_weights: "np.ndarray | None" = None,
    *,
    ray_batch_size: int,
):
    """
    Score each voxel by the sky-patch weight of the rays that cross it.

    Each Tregenza sky patch gets a weight according to ``settings.mode``:
      • irradiance: cumulative direct + diffuse irradiance per patch (kWh/m²)
        from the EPW over the analysis hours (Ladybug sky matrix).
      • benefit: the same, counted only in hours cold enough for solar gains
        to offset heating (kWh/m²), optionally minus hot-hour irradiance
        (``include_harm``).
      • daylight: relative luminance of the CIE standard overcast sky times
        the patch solid angle.
      • radiative_cooling: long-wave cooling potential from the dew point and
        the Bliss angular law, normalized to sum to 1.

    Procedure:
      1. Take the 145 Tregenza patch directions.
      2. Cast a ray from each sample point toward every patch on the outward
         side of its normal.
      3. Trace the rays through the voxel volume and add each ray's patch
         weight (times its point weight, if given) to every voxel it visits
         in front of its source surface.

    No voxel is removed here: thresholding the scores into a keep/carve mask
    happens in ``api_core.thresholding``.

    Parameters
    ----------
    voxel_grid : torch.Tensor, shape (X, Y, Z)
        Occupancy grid; only its shape and device are used.
    grid_origin : array_like, shape (3,)
        Minimum corner of the voxel volume in world coordinates.
    grid_extent : float
        Physical span of the cubic grid (meters).
    grid_resolution : int or (3,)
        Number of voxels along each axis (must represent a cube).
    sample_points : np.ndarray, shape (R, 3)
        Coordinates of R surface evaluation points.
    sample_normals : np.ndarray, shape (R, 3)
        Outward-facing unit normals at each sample point.
    settings : PreprocessingSettings
        Settings used:
          - mode: weight mode selector.
          - epw_path: EPW file (irradiance and benefit).
          - dew_point_celsius, bliss_k, min_sky_elevation_deg: radiative_cooling.
          - balance_temperature, balance_offset, include_harm,
            simulated_weights_path: benefit.
          - north_deg: model north, degrees clockwise from +Y.
          - ray_length: maximum ray length.
    hoys : Sequence[int]
        Hour-of-year indices (0..8759) of the analysis period, used by the
        EPW-based modes.
    return_rays : bool, default False
        If True, include the full ray set (host numpy arrays) in the
        result.  Off by default: at millions of rays this is hundreds of
        MB of device-to-host transfer that the pipeline never uses.
    point_weights : np.ndarray (R,), optional
        Per-sample-point design weights in [0, 1] (edge_taper): each ray's
        contribution is patch_weight × point_weight, and zero-weight rays
        are dropped before tracing.  None (default) = all points count
        fully.
    ray_batch_size : int
        Rays processed per batch (0 = automatic); keyword only.

    Returns
    -------
    SkyPatchCarvingResult
        NamedTuple with fields:
        - ray_origins (N, 3): ray start points, or None unless return_rays.
        - ray_directions (N, 3): unit ray vectors, or None unless return_rays.
        - raw_voxel_scores (X*Y*Z,): accumulated weights per voxel (float32).
        - patch_weights (P,): weight per Tregenza sky patch.

    Raises
    ------
    ValueError
        If *point_weights* does not have one entry per sample point.
    """

    # --- 0) Setup ----------------------------------------------------------
    device = voxel_grid.device
    require_dda_backend(device)
    _validate_cubic_resolution(grid_resolution, 'carve_with_sky_patch_rays')

    # --- 1-3) Rays, per-point design weights and patch weights ------------
    rays = sky_patch_ray_set(device, sample_points, sample_normals, settings, hoys, point_weights)
    ray_origins, ray_directions, patch_ids, ray_point_ids = (
        rays.origins, rays.directions, rays.patch_ids, rays.point_ids)
    surface_normals, pw_t, patch_weights = rays.surface_normals, rays.point_weights, rays.patch_weights
    occupancy = _occupancy_flat(voxel_grid)
    total_rays = ray_origins.size(0)  # after facing and zero-weight filtering

    # --- 4) Initialize score accumulation ---------------------------------
    num_voxels = voxel_grid.numel()
    scores = torch.zeros(num_voxels, device=device)  # float32, flat X*Y*Z
    grid_extent_m = float(grid_extent)

    # --- 5) Batch ray tracing & weighting ----------------------------------
    res = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])
    batch_size = _resolve_batch_size(device, ray_batch_size=ray_batch_size)

    def _score_batch(start: int, end: int, buf) -> None:
        # Trace and accumulate in one Warp kernel, writing into buf.
        trace_and_score_dda(
            grid_origin, float(grid_extent_m), res,
            ray_origins[start:end], ray_directions[start:end], patch_ids[start:end],
            patch_weights, buf, settings.ray_length,
            point_ids=ray_point_ids[start:end],
            point_weights=pw_t,
            surface_normals=surface_normals,
            occupancy=occupancy,
        )

    batch_ranges = [
        (start, min(start + batch_size, total_rays))
        for start in range(0, total_rays, batch_size)
    ]
    with torch.no_grad():
        _run_batches(batch_ranges, _score_batch, scores, device, parallel=True)

    # Warp launches run on Warp's own CUDA stream; wait for them before
    # torch reads the shared scores buffer.
    if device.type == "cuda":
        torch.cuda.synchronize()

    # Own skin scores at least as much as the mass behind it, so it is
    # never kept once that mass is carved.
    with torch.no_grad():
        scores = _follow_mass_behind_skin(
            scores, grid_origin, grid_extent_m, res, ray_origins,
            ray_directions, ray_point_ids, surface_normals, occupancy,
            float(settings.ray_length))

    raw_voxel_scores = scores.cpu().numpy()

    # Thresholding lives in api_core.thresholding, so users can re-threshold
    # without re-tracing rays.
    return SkyPatchCarvingResult(
        ray_origins=ray_origins.cpu().numpy() if return_rays else None,
        ray_directions=ray_directions.cpu().numpy() if return_rays else None,
        raw_voxel_scores=raw_voxel_scores,
        patch_weights=patch_weights.cpu().numpy(),
    )


def _tilt_angles_deg(horizontal_dirs, spec, north_deg) -> np.ndarray:
    """Tilt angle, in degrees above the horizon, for each horizontal unit
    direction (N, 2): the single angle, or the compass-octant entry of an
    8-element table [N, NE, E, SE, S, SW, W, NW].

    Raises
    ------
    ValueError
        If *spec* is neither a number nor 8 values.
    """
    if isinstance(spec, (int, float)) or np.isscalar(spec):
        return np.full((horizontal_dirs.shape[0],), float(spec), dtype=np.float64)
    table = np.asarray(spec, dtype=np.float64)
    if table.shape != (8,):
        raise ValueError(
            "tilted_plane_angle_deg must be a single number or an 8-length list [N, NE, E, SE, S, SW, W, NW]"
        )
    # Compute the model-space azimuth from +Y clockwise toward +X, then
    # subtract north_deg (model north, degrees clockwise from +Y) to get
    # the true compass azimuth of each direction.
    phi = (np.degrees(np.arctan2(horizontal_dirs[:, 0], horizontal_dirs[:, 1])) - float(north_deg) + 360.0) % 360.0
    # Octant bins are 45° wide (360° / 8). Adding half a bin (22.5°)
    # centres each bin on its direction (N = 0°, NE = 45°, E = 90°, ...),
    # so N covers 337.5° to 22.5°.
    idx = np.floor(((phi + 22.5) % 360.0) / 45.0).astype(np.int64)
    return table[idx]


def _tilted_directions(horizontal_dirs, alpha_deg) -> np.ndarray:
    """d = cos(a)*h + sin(a)*z_hat for horizontal unit directions h (N, 2):
    horizontal at a = 0, vertical at a = 90 deg."""
    alpha_rad = np.radians(alpha_deg)
    dirs = np.empty((horizontal_dirs.shape[0], 3), dtype=np.float64)
    dirs[:, :2] = np.cos(alpha_rad)[:, None] * horizontal_dirs
    dirs[:, 2] = np.sin(alpha_rad)
    return dirs


# Sample points closer than this many grid steps (in plan, on the same row)
# are neighbours on the test-surface outline; a pair whose normals differ is
# a turn of the outline.
_CORNER_NEIGHBOUR_STEPS = 1.5
# Neighbours closer than this many grid steps lie on the same corner edge
# (both panels seed sample points along their shared edge).
_CORNER_SAME_EDGE_STEPS = 0.25
# Normals this close to opposite (back-to-back faces of a thin wall) have no
# corner to rotate around.
_CORNER_MAX_TURN_DEG = 179.0


def _corner_fan_rays(points, horizontal_normals, usable, spec, north_deg,
                     grid_step, cell_size, grid_top_z, grid_extent, ray_length):
    """Extra rays that rotate the tilted plane around convex turns of the
    test-surface outline.

    One ray per sample point along its own normal leaves a wedge between
    the rays of two panels that meet at a convex turn: the rays diverge,
    and columns between them are crossed by none. For every pair of
    neighbouring sample points (same row, at most 1.5 grid steps apart in
    plan) whose horizontal normals turn convexly, this casts rays at headings
    swept from the first point's normal to its neighbour's, spaced so that
    neighbouring rays are at most 0.9 voxels apart where they leave the
    grid. Rays in the first half of the sweep start at the first point, the
    rest at its neighbour, and each skips the voxels its source facade's
    plane passes through (the same own-skin rule as the sample points' own
    rays). Each ray takes the tilt angle of its own heading. Concave
    turns (rays converge) are skipped, except for neighbours on the same
    corner edge, whose offset cannot tell the two apart: on a concave
    corner their swept rays lie above the two planes and carve nothing more.
    A swept ray from point p caps a column at distance t at
    z_p + tan(angle) * t, never lower than the same angle measured from the
    nearest sample point.

    Parameters
    ----------
    points : (N, 3) float64
    horizontal_normals : (N, 2) float64
        Unit horizontal normals.
    usable : (N,) bool
        False for (nearly) horizontal surfaces, which have no facing direction.

    Returns
    -------
    directions : (F, 3) float64
    source_ids : (F,) int64
        Sample point each ray starts from (its origin and its facade plane).
    """
    from scipy.spatial import cKDTree

    empty = (np.zeros((0, 3), dtype=np.float64), np.zeros(0, dtype=np.int64))
    candidate_ids = np.nonzero(usable)[0]
    if candidate_ids.size < 2:
        return empty
    tree = cKDTree(points[candidate_ids, :2])
    pairs = tree.query_pairs(_CORNER_NEIGHBOUR_STEPS * grid_step, output_type="ndarray")
    if pairs.size == 0:
        return empty
    first, second = candidate_ids[pairs[:, 0]], candidate_ids[pairs[:, 1]]
    same_row = np.abs(points[first, 2] - points[second, 2]) <= 0.5 * grid_step
    first, second = first[same_row], second[same_row]

    heading = np.arctan2(horizontal_normals[:, 1], horizontal_normals[:, 0])
    turn = (heading[second] - heading[first] + np.pi) % (2.0 * np.pi) - np.pi
    offset = points[second, :2] - points[first, :2]
    same_edge = np.linalg.norm(offset, axis=1) <= _CORNER_SAME_EDGE_STEPS * grid_step
    # Convex: the two rays move apart, i.e. the normals turn toward the side
    # the neighbour lies on.
    diverging = ((horizontal_normals[second] - horizontal_normals[first]) * offset).sum(axis=1) > 0.0

    # Horizontal reach of a ray before it leaves the grid (its top, its
    # plan diagonal, or ray_length), at the lowest tilt angle in use; the
    # angular step keeps rays within 0.9 voxels of each other out to that
    # reach.
    alpha_min = float(np.min(np.atleast_1d(np.asarray(spec, dtype=np.float64))))
    tan_min = np.tan(np.radians(alpha_min))
    reach = np.full(first.shape, min(float(ray_length) * np.cos(np.radians(alpha_min)),
                                     np.sqrt(2.0) * grid_extent))
    if tan_min > 1e-6:
        reach = np.minimum(reach, (grid_top_z - points[first, 2]) / tan_min)
    angular_step = 0.9 * cell_size / np.maximum(reach, 1e-9)

    keep = ((same_edge | diverging)
            & (np.abs(turn) < np.radians(_CORNER_MAX_TURN_DEG))
            & (np.abs(turn) > angular_step)
            & (reach > 0.0))
    first, second = first[keep], second[keep]
    turn, angular_step = turn[keep], angular_step[keep]
    if first.size == 0:
        return empty

    # Interior headings only: m = 1 .. k-1 of k equal steps (the end
    # headings are the two points' own rays).
    steps = np.ceil(np.abs(turn) / angular_step).astype(np.int64)
    rays_per_pair = steps - 1
    pair_of_ray = np.repeat(np.arange(first.size), rays_per_pair)
    starts = np.cumsum(rays_per_pair) - rays_per_pair
    m = np.arange(pair_of_ray.size) - starts[pair_of_ray] + 1
    fraction = m / steps[pair_of_ray]
    fan_heading = heading[first][pair_of_ray] + turn[pair_of_ray] * fraction
    fan_horizontal = np.stack([np.cos(fan_heading), np.sin(fan_heading)], axis=1)

    # The first half of the sweep starts at the first point, the second half
    # at its neighbour: every ray is within half the turn of its source
    # point's normal and leaves from in front of that point's facade.
    source_ids = np.where(fraction <= 0.5, first[pair_of_ray], second[pair_of_ray])
    directions = _tilted_directions(fan_horizontal, _tilt_angles_deg(fan_horizontal, spec, north_deg))
    return directions, source_ids


def carve_with_planes(
    voxel_grid,
    grid_origin,
    grid_extent,
    grid_resolution,
    sample_points,
    sample_normals,
    settings: PreprocessingSettings,
    return_counts: bool = False,
    *,
    ray_batch_size: int,
):
    """
    Tilted-plane daylight carving.

    One ray per sample point:
      1) Project the surface normal onto the XY plane to get n_xy.
      2) Select the tilt angle α (single value or per-octant table).
      3) Form d = cos(α)·n_xy + sin(α)·ẑ and trace a ray along it.
    Every voxel at or above a visited cell in its (x, y) column is deleted:
    the ray traces the plane's section through that column, and everything
    above the plane is forbidden, not only the cells the ray crosses.

    Where the test-surface outline turns convexly (two panels meeting at an
    outside corner or a kink), the rays of the two panels diverge. Extra
    rays from the corner sweep the headings between the two normals, so the
    plane rotates around the corner instead of leaving the columns between
    the diverging rays standing (see :func:`_corner_fan_rays`).

    Parameters
    ----------
    voxel_grid, grid_origin, grid_extent, grid_resolution,
    sample_points, sample_normals :
        See :func:`carve_with_sun_rays` for shared parameter descriptions.
    settings : PreprocessingSettings
        Must contain ``tilted_plane_angle_deg``: a single angle in degrees
        above the horizon, or an 8-element list [N, NE, E, SE, S, SW, W, NW]
        looked up by the compass direction the surface faces (which uses
        ``north_deg``).
    return_counts : bool, default False
        If True, return a 4th element: per-voxel counts, propagated up each
        column (a voxel's count is the largest ray count at or below it).
    ray_batch_size : int
        Rays processed per batch (0 = automatic); keyword only.

    Returns
    -------
    carved_grid : torch.Tensor, shape (D, D, D)
    ray_origins : np.ndarray, shape (R, 3)
        The sample points (one ray each; the corner rays are not included).
    ray_directions : np.ndarray, shape (R, 3)
    counts : np.ndarray, shape (D*D*D,), int32, optional
        Only returned when *return_counts* is True.

    Raises
    ------
    ValueError
        If ``tilted_plane_angle_deg`` is neither a number nor 8 values.
    """
    require_dda_backend(voxel_grid.device)
    _validate_cubic_resolution(grid_resolution, "carve_tilted_plane")
    side_len = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])

    device = voxel_grid.device

    if isinstance(sample_points, torch.Tensor):
        pts_np = sample_points.detach().cpu().numpy().astype(np.float32)
    else:
        pts_np = np.asarray(sample_points, dtype=np.float32)

    if isinstance(sample_normals, torch.Tensor):
        norms_np = sample_normals.detach().cpu().numpy().astype(np.float32)
    else:
        norms_np = np.asarray(sample_normals, dtype=np.float32)

    # Project surface normals onto the XY (horizontal) plane: the result is
    # the horizontal direction each test surface faces, which the tilt angle
    # is measured up from and which selects the octant (N, NE, E, ...).
    n_xy = norms_np.copy()
    n_xy[:, 2] = 0.0
    lens = np.linalg.norm(n_xy[:, :2], axis=1, keepdims=True)
    # A horizontal component below 0.05 means the normal is within about 3°
    # of vertical (roofs, courtyard floors): no usable facade direction.
    flat = lens[:, 0] < 0.05
    if flat.any():
        report_issue(
            "horizontal_test_surfaces",
            f"tilted_plane: {int(flat.sum())} of {len(lens)} sample points lie on "
            f"(nearly) horizontal test surfaces, which have no reliable facing "
            f"direction for a tilted plane. On exactly horizontal surfaces the ray "
            f"goes straight up and protects only the sky directly above; on nearly "
            f"horizontal ones it follows the small horizontal tilt of the normal.",
        )
    np.maximum(lens, 1e-9, out=lens)
    n_xy[:, :2] /= lens

    # Assign a tilt angle to each sample point.
    # Scalar: all surfaces share the same angle.
    # 8-element list: each surface gets an angle based on the compass octant
    # its horizontal normal faces ([N, NE, E, SE, S, SW, W, NW]).
    spec = settings.tilted_plane_angle_deg
    alpha_deg = _tilt_angles_deg(n_xy[:, :2], spec, settings.north_deg).astype(np.float32)

    alpha_rad = np.radians(alpha_deg).astype(np.float32)

    # Ray direction d = cos(a)*n_xy + sin(a)*z_hat: horizontal and outward
    # at a = 0, vertical at a = 90 deg, a deg above the horizon in between.
    dirs_np = (
        np.cos(alpha_rad)[:, None] * n_xy
        + np.sin(alpha_rad)[:, None] * np.array([[0.0, 0.0, 1.0]], dtype=np.float32)
    )
    dirs_np /= np.maximum(np.linalg.norm(dirs_np, axis=1, keepdims=True), 1e-9)
    dirs_np = dirs_np.astype(np.float32)

    # Rotate the plane around convex turns of the outline: without these
    # rays, columns between the diverging rays of two panels stay standing.
    cell_size = float(grid_extent) / side_len
    fan_dirs, fan_source_ids = _corner_fan_rays(
        pts_np.astype(np.float64), n_xy[:, :2].astype(np.float64), ~flat,
        spec, settings.north_deg, float(settings.grid_step), cell_size,
        float(grid_origin[2]) + float(grid_extent), float(grid_extent),
        float(settings.ray_length),
    )
    source_ids = np.concatenate([np.arange(pts_np.shape[0]), fan_source_ids])
    all_dirs = np.concatenate([dirs_np, fan_dirs.astype(np.float32)])

    origins_tensor = torch.from_numpy(pts_np[source_ids]).to(device, non_blocking=True)
    dirs_tensor = torch.from_numpy(all_dirs).to(device, non_blocking=True)

    grid_min_corner = (float(grid_origin[0]), float(grid_origin[1]), float(grid_origin[2]))
    occupancy = _occupancy_flat(voxel_grid)
    # Corner rays use their source sample point's facade plane, for both the
    # in-front test and the own-skin rule.
    ray_point_ids = torch.from_numpy(source_ids).to(device)
    surface_normals = torch.from_numpy(norms_np).to(device)
    counts = _count_ray_hits(
        voxel_grid, grid_min_corner, float(grid_extent), side_len,
        origins_tensor, dirs_tensor, settings,
        ray_point_ids, surface_normals, occupancy,
        ray_batch_size=ray_batch_size,
    )

    # Propagate counts up each (x, y) column (running maximum along z), so
    # every cell at or above a visited cell is carved. Visits to empty cells
    # count too: a ray passing over a low roof still bounds the mass above it.
    def _up_columns(c):
        return torch.cummax(c.view(side_len, side_len, side_len), dim=2).values.reshape(-1)

    counts = _up_columns(counts)
    # Own skin goes with the mass behind it (that mass's final state, so
    # after the column pass), and then takes its own column with it.
    counts = _up_columns(_follow_mass_behind_skin(
        counts, grid_min_corner, float(grid_extent), side_len,
        origins_tensor, dirs_tensor, ray_point_ids, surface_normals, occupancy,
        float(settings.ray_length)))
    carved_grid = _carve_by_counts(voxel_grid, counts)

    if not return_counts:
        return carved_grid, pts_np, dirs_np
    return carved_grid, pts_np, dirs_np, counts.detach().cpu().numpy()
