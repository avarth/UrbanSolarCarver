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
  voxel at or above a visited voxel in its column is removed.

Raytracing contract
-------------------
With Warp installed, rays are traced by the fused DDA kernels in
raytracer.py, which visit every voxel a ray crosses exactly once and
accumulate counts or scores in place.  Without Warp, `trace_multi_hit_grid`
lists the (ray, voxel) pairs with a fixed-step PyTorch march (each pair at
most once) and the scores are accumulated here with torch; that path is
slower and can miss voxels that oblique rays only clip.  Both paths count
only voxels that lie entirely in front of the surface a ray starts from
(see `_front_of_surface`).

Coordinate/scale conventions
----------------------------
`grid_origin` is the world-space min corner for grid index [0,0,0].
`grid_extent` is the physical cube size (meters). `grid_resolution` is D, the
number of voxels per side, so one voxel is `grid_extent / D` meters wide.
The tracers receive `scale = grid_extent`; the fixed-step fallback also uses
`voxel_size` as its step length.

Determinism and batching
------------------------
Given a fixed config, hit counts are deterministic. Float scores are summed
with atomic adds on the GPU, so the order of additions, and therefore the last
bits of a score, can differ between runs. Rays are processed in batches of
the `ray_batch_size` run option (0 = sized from free GPU memory) on the device of the
input voxel grid.
"""

import queue
import threading
import warnings
import torch
import numpy as np
from numba import njit

from .scoring import get_weights
from .stage_settings import PreprocessingSettings
from .mode_registry import ALL_MODE_NAMES, MODES_NEEDING_EPW
from .sky_patches import fetch_tregenza_patch_directions
from .sun import get_sun_vectors
from .errors import InputError
from .run_context import active_context, report_issue, report_progress
from .raytracer import (
    generate_sun_rays, generate_sky_patch_rays, trace_multi_hit_grid,
    trace_and_count_dda, auto_batch_size, dda_backend_available,
)
# The fused score kernel exists only when Warp is installed.
try:
    from .raytracer import trace_and_score_dda as _fused_dda
except ImportError:
    _fused_dda = None
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

import os
from ladybug.analysisperiod import AnalysisPeriod
from .io import load_mesh

def _resolve_batch_size(resolution: int, device, *, ray_batch_size: int) -> int:
    """Return the effective ray batch size, auto-tuning if requested.

    If *ray_batch_size* is 0 the batch size is computed from free GPU
    memory via :func:`auto_batch_size` (a fixed default on CPU).
    """
    if ray_batch_size > 0:
        return int(ray_batch_size)
    return auto_batch_size(resolution, device)


def validate_inputs(settings: PreprocessingSettings):
    """
    Validate file paths and supported modes.

    Raises
    ------
    InputError
        If the max-volume or test-surface mesh is missing, or the EPW file is
        missing for a mode that needs one.
    ValueError
        If `settings.mode` is not one of:
        {'time-based','irradiance','benefit','daylight','radiative_cooling','tilted_plane'}.
    """
    for filepath, name in [
        (settings.max_volume_path, 'max_volume'),
        (settings.test_surface_path,    'test_surface'),
    ]:
        if not filepath or not os.path.isfile(filepath):
            raise InputError(f"{name} file missing: {filepath!r}")
    # EPW is required for modes that use weather data
    if settings.mode in MODES_NEEDING_EPW:
        if not settings.epw_path or not os.path.isfile(settings.epw_path):
            raise InputError(f"EPW file missing: {settings.epw_path!r}")
    if settings.mode not in ALL_MODE_NAMES:
        raise ValueError(f"Unsupported mode: {settings.mode!r}")

def sample_period(settings: PreprocessingSettings, steps_per_hour: int = 1):
    """
    Build analysis datetimes and HOYs via Ladybug's AnalysisPeriod.

    Returns
    -------
    datetimes : list[datetime.datetime]
        Start to end (inclusive) at ``1/steps_per_hour``-hour steps.
    hoys : list[int]
        Hour-of-year indices (0..8759, 0 = 1 January 00:00) of the period,
        always hourly: they index EPW records, which are hourly.
    """
    def _ap(timestep):
        return AnalysisPeriod(
            st_month=settings.start_month, st_day=settings.start_day, st_hour=settings.start_hour,
            end_month=settings.end_month,   end_day=settings.end_day,   end_hour=settings.end_hour,
            timestep=timestep,
        )
    hourly = _ap(1)
    if steps_per_hour == 1:
        return hourly.datetimes, hourly.hoys_int
    return _ap(steps_per_hour).datetimes, hourly.hoys_int

def load_meshes(settings: PreprocessingSettings):
    """
    Load the maximum envelope mesh and the insolation sampling surface.

    Warns when a PLY file stores large (georeferenced) coordinates as float32,
    because that rounding happened on disk and cannot be undone here.

    Returns
    -------
    envelope_mesh : trimesh.Trimesh
    insolation_mesh : trimesh.Trimesh
    """
    envelope_mesh = load_mesh(settings.max_volume_path)
    insolation_mesh = load_mesh(settings.test_surface_path)
    for path, mesh in ((settings.max_volume_path, envelope_mesh),
                       (settings.test_surface_path, insolation_mesh)):
        _warn_float32_input(path, mesh, settings.voxel_size)
    return envelope_mesh, insolation_mesh


def _stores_float32_vertices(path: str) -> bool:
    """True if *path* is a PLY file whose header declares float32 x coordinates."""
    if not str(path).lower().endswith(".ply"):
        return False
    with open(path, "rb") as fh:
        header = fh.read(4096).split(b"end_header")[0].decode("ascii", errors="replace")
    return any(line.split()[:3] in (["property", "float", "x"], ["property", "float32", "x"])
               for line in header.splitlines())


def _warn_float32_input(path: str, mesh, voxel_size: float) -> None:
    """Warn if the file's float32 vertices are rounded by more than 1 % of a voxel.

    Large (georeferenced) coordinates stored as float32 lose precision when
    the file is written, so the rounding cannot be recovered on load.
    """
    from .io import float32_resolution
    res = float32_resolution(mesh.vertices)
    if res > 0.01 * float(voxel_size) and _stores_float32_vertices(path):
        report_issue(
            "float32_coordinates",
            f"{os.path.basename(path)}: coordinates reach "
            f"{float(np.abs(mesh.vertices).max()):,.0f} m and the file stores "
            f"float32 vertices, so its geometry is rounded to ~{res:.2g} m on disk "
            f"({100 * res / voxel_size:.0f}% of a voxel). Move the model near the "
            f"origin before export, or export PLY with double-precision vertices.",
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

      
#--- Ray tracing and carving -----------------------------------------------------------------------------------

def _front_of_surface(min_corner, cell, voxel_idx, origins, normals) -> torch.Tensor:
    """Mask of hits whose whole voxel lies in front of the ray's source surface.

    A voxel the surface's plane passes through is the building's own skin
    (a test surface on a facade sits inside the boundary voxels of its own
    mass), not an obstruction of it.  Same rule as the Warp kernels'
    ``_in_front``, applied here for the fixed-step fallback.
    """
    corner = torch.tensor(min_corner, dtype=torch.float32, device=voxel_idx.device)
    centre = corner + (voxel_idx.float() + 0.5) * cell
    half_extent = 0.5 * cell * normals.abs().sum(dim=1)
    return ((centre - origins) * normals).sum(dim=1) > half_extent


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
                    settings: PreprocessingSettings, point_ids, surface_normals,
                    *, ray_batch_size: int):
    """Count how many rays visit each voxel; returns a flat int32 tensor.

    Uses the fused Warp count kernel when available; otherwise the
    fixed-step :func:`trace_multi_hit_grid` fallback.  Both count each
    (ray, voxel) pair at most once, and skip voxels behind the ray's source
    surface (*point_ids* maps rays to rows of *surface_normals*).
    """
    device = voxel_grid.device
    counts = torch.zeros(voxel_grid.numel(), dtype=torch.int32, device=device)
    batch_size = _resolve_batch_size(res, device, ray_batch_size=ray_batch_size)
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
                buf, float(settings.ray_length),
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
        # The tracer requires per-ray patch ids; they are unused for counting.
        patch_ids_stub = torch.zeros((o_batch.shape[0],), dtype=torch.long, device=device)
        ray_idx, _, voxel_idx = trace_multi_hit_grid(
            min_corner=min_corner,
            scale=scale,
            resolution=res,
            origins=o_batch,
            ray_dirs=d_batch,
            sky_patch_ids=patch_ids_stub,
            voxel_size=float(settings.voxel_size),
            ray_length=float(settings.ray_length),
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
          - voxel_size: step length of the fixed-step fallback tracer.
          - ray_length: maximum traced distance along each ray.
    datetimes : Sequence[datetime.datetime]
        Wall-clock timestamps for which sun vectors are generated.
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
    _validate_cubic_resolution(grid_resolution, "carve_with_sun_rays")
    res = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])

    # Sun directions in model coordinates (rotated by north_deg).
    sun_dirs = get_sun_vectors(
        settings.epw_path, datetimes, settings.min_altitude,
        north_deg=settings.north_deg,
    )
    if isinstance(sun_dirs, torch.Tensor):
        sun_arr = sun_dirs.clone().detach().to(voxel_grid.device)
    else:
        sun_arr = torch.as_tensor(sun_dirs, dtype=torch.float32, device=voxel_grid.device)
    if sun_arr.numel() == 0:
        report_issue(
            "no_sun_vectors",
            "carve_with_sun_rays: no sun vectors above min_altitude; "
            "the grid is returned unmodified.",
        )
        empty = np.empty((0, 3), dtype=np.float32) if return_rays else None
        if return_counts:
            return voxel_grid.clone(), empty, empty, np.zeros(voxel_grid.numel(), dtype=np.int32)
        return voxel_grid.clone(), empty, empty
    # The 1e-9 guards against division by zero for a zero-length vector. It is
    # far below float32 precision (~1.2e-7), so unit vectors are unchanged.
    sun_arr = sun_arr / (sun_arr.norm(dim=1, keepdim=True) + 1e-9)

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
        voxel_grid, min_corner, float(grid_extent), res, origins, directions, settings,
        point_idx, surface_normals, ray_batch_size=ray_batch_size,
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
          - voxel_size, ray_length: fallback step length and maximum ray length.
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
    _validate_cubic_resolution(grid_resolution, 'carve_with_sky_patch_rays')

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
    ray_point_ids = point_idx.to(torch.int32)

    total_rays = ray_origins.size(0)  # after facing and zero-weight filtering

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

    # --- 4) Initialize score accumulation ---------------------------------
    num_voxels = voxel_grid.numel()
    scores = torch.zeros(num_voxels, device=device)  # float32, flat X*Y*Z
    grid_extent_m = float(grid_extent)

    # --- 5) Batch ray tracing & weighting ----------------------------------
    res = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])
    batch_size = _resolve_batch_size(res, device, ray_batch_size=ray_batch_size)
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
                patch_weights, buf, settings.ray_length,
                point_ids=ray_point_ids[start:end],
                point_weights=pw_t,
                surface_normals=surface_normals,
            )
            return

        # Fallback without Warp: trace, then accumulate with torch.
        hit_ray_ids, hit_patch_ids, hit_voxel_idxs = trace_multi_hit_grid(
            grid_origin, grid_extent_m, res,
            origins_batch, directions_batch, patches_batch,
            settings.voxel_size, settings.ray_length,
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

    # Warp launches run on Warp's own CUDA stream; wait for them before
    # torch reads the shared scores buffer.
    if device.type == "cuda":
        torch.cuda.synchronize()

    raw_voxel_scores = scores.cpu().numpy()

    # Thresholding lives in api_core.thresholding, so users can re-threshold
    # without re-tracing rays.
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
        The sample points (one ray each).
    ray_directions : np.ndarray, shape (R, 3)
    counts : np.ndarray, shape (D*D*D,), int32, optional
        Only returned when *return_counts* is True.

    Raises
    ------
    ValueError
        If ``tilted_plane_angle_deg`` is neither a number nor 8 values.
    """
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
        north_deg = float(settings.north_deg)
        phi = (np.degrees(np.arctan2(n_xy[:, 0], n_xy[:, 1])) - north_deg + 360.0) % 360.0
        # Octant bins are 45° wide (360° / 8). Adding half a bin (22.5°)
        # centres each bin on its direction (N = 0°, NE = 45°, E = 90°, ...),
        # so N covers 337.5° to 22.5°.
        idx = np.floor(((phi + 22.5) % 360.0) / 45.0).astype(np.int64)
        alpha_deg = table[idx]

    alpha_rad = np.radians(alpha_deg).astype(np.float32)

    # Ray direction d = cos(a)*n_xy + sin(a)*z_hat: horizontal and outward
    # at a = 0, vertical at a = 90 deg, a deg above the horizon in between.
    dirs_np = (
        np.cos(alpha_rad)[:, None] * n_xy
        + np.sin(alpha_rad)[:, None] * np.array([[0.0, 0.0, 1.0]], dtype=np.float32)
    )
    dirs_np /= np.maximum(np.linalg.norm(dirs_np, axis=1, keepdims=True), 1e-9)
    dirs_np = dirs_np.astype(np.float32)

    origins_tensor = torch.from_numpy(pts_np).to(device, non_blocking=True)
    dirs_tensor = torch.from_numpy(dirs_np).to(device, non_blocking=True)

    grid_min_corner = (float(grid_origin[0]), float(grid_origin[1]), float(grid_origin[2]))
    counts = _count_ray_hits(
        voxel_grid, grid_min_corner, float(grid_extent), side_len,
        origins_tensor, dirs_tensor, settings,
        torch.arange(pts_np.shape[0], device=device),
        torch.from_numpy(norms_np).to(device),
        ray_batch_size=ray_batch_size,
    )
    # Propagate counts up each (x, y) column (running maximum along z), so
    # every cell at or above a visited cell is carved. Visits to empty cells
    # count too: a ray passing over a low roof still bounds the mass above it.
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
    min_consecutive : int, default 1
        Minimum consecutive carved voxels to trigger carve-above.

    Returns
    -------
    ndarray (D, D, D) bool
        A copy of *mask* with the occupied voxels above qualifying runs
        set to False.
    """
    out = np.ascontiguousarray(mask.astype(bool, copy=True))
    occ = np.ascontiguousarray(voxel_grid.astype(bool, copy=False))
    _carve_above_kernel(out, occ, int(min_consecutive))
    return out


@njit(cache=True)
def _carve_above_kernel(out, voxel_grid, min_consecutive):
    """Numba kernel for :func:`carve_above_columns`; mutates *out* in place.

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
                    # Short run: too small to trigger, but it stays carved;
                    # refilling it would undo the solar constraint.
                else:
                    z += 1

            if trigger_top >= 0:
                for z_above in range(trigger_top + 1, nz):
                    if voxel_grid[x, y, z_above]:
                        out[x, y, z_above] = False


def carve_above_scores(scores, occupancy, min_consecutive: int = 1) -> np.ndarray:
    """For each voxel, the score cutoff below which carve_above removes it.

    Carving the occupied voxels that score above a cutoff t and then running
    :func:`carve_above_columns` removes exactly the occupied voxels whose
    value here is above t: a voxel goes when it scores above t itself, or
    when some run of *min_consecutive* consecutive occupied voxels below it
    in its column all score above t.  So the value is the larger of the
    voxel's own score and, over those runs below it, the smallest score in
    the run.  Empty cells break runs.

    With these values a score-mass cutoff can count everything carve_above
    removes, not only the voxels the cutoff picks itself.  NaN scores count
    as +inf (always carved).

    Parameters
    ----------
    scores : ndarray (X, Y, Z) float
    occupancy : ndarray (X, Y, Z) bool
    min_consecutive : int, default 1

    Returns
    -------
    ndarray (X, Y, Z) float64
        Values on empty cells are their own score and carry no meaning.
    """
    s = np.ascontiguousarray(np.asarray(scores, dtype=np.float64))
    occ = np.ascontiguousarray(np.asarray(occupancy, dtype=bool))
    out = np.empty_like(s)
    _carve_above_scores_kernel(s, occ, int(min_consecutive), out)
    return out


@njit(cache=True)
def _carve_above_scores_kernel(scores, occ, k, out):
    """Column scan for :func:`carve_above_scores`.

    Walking up a column, ``trigger`` is the largest cutoff at which some run
    of k consecutive occupied voxels below the current voxel is entirely
    carved (the smallest score in that run).
    """
    nx, ny, nz = occ.shape
    for x in range(nx):
        for y in range(ny):
            trigger = -np.inf
            run = 0
            for z in range(nz):
                value = scores[x, y, z]
                if value != value:          # NaN: always carved
                    value = np.inf
                if not occ[x, y, z]:
                    out[x, y, z] = value
                    run = 0
                    continue
                out[x, y, z] = max(value, trigger)
                run += 1
                if run >= k:
                    window = value
                    for zz in range(z - k + 1, z):
                        below = scores[x, y, zz]
                        if below != below:
                            below = np.inf
                        window = min(window, below)
                    trigger = max(trigger, window)


def limit_column_slope(mask, occupancy, max_slope_deg: float, median_size: int = 5):
    """Lower columns that rise too steeply above their neighbours.

    Each building column's kept height (one above its highest kept voxel,
    0 if nothing is kept) is capped so that it rises at most
    ``tan(max_slope_deg)`` voxels per voxel of horizontal distance above a
    reference height map, counting the reference at the column itself as
    one voxel away; every kept voxel above the cap is removed.  The result
    only ever removes voxels.

    The reference is the kept height map after a ``median_size`` x
    ``median_size`` median filter over the building's columns, so features
    one or two columns wide are ignored: a single tall column (a spire) is
    measured against its surroundings and ends at most one slope step above
    them, and a single low column (a stub left at a curved edge) or a
    narrow slot does not pull its neighbours down.  Wider differences in
    height, including next to areas carved to the ground, become ramps of
    the given slope, cut from the taller side.  Columns outside the
    building (no occupied voxel) take no part.

    The cap never rises when the input loses voxels, so carving more before
    this step never keeps more after it (a carve_fraction slider stays
    nested).

    Parameters
    ----------
    mask : ndarray (X, Y, Z) bool
        Kept voxels (True), normally after carve_above.  Not mutated.
    occupancy : ndarray (X, Y, Z) bool
        The building's voxels before carving; decides which columns count.
    max_slope_deg : float
        Steepest allowed rise between neighbouring columns, in degrees
        above horizontal (0 < angle < 90; voxels are cubes, so the slope is
        the same in metres).
    median_size : int, default 5
        Width in voxels of the median filter that builds the reference.

    Returns
    -------
    ndarray (X, Y, Z) bool
        A copy of *mask* with the voxels above each column's cap removed.
    """
    from numpy.lib.stride_tricks import sliding_window_view
    if not 0.0 < max_slope_deg < 90.0:
        raise ValueError(f"max_slope_deg must be between 0 and 90, got {max_slope_deg}")
    z = np.arange(mask.shape[2])
    building = np.asarray(occupancy, dtype=bool).any(axis=2)
    top = np.where(mask.any(axis=2), (mask * (z + 1)).max(axis=2), 0).astype(np.float64)
    half = median_size // 2
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # windows with no building column
        windows = sliding_window_view(
            np.pad(np.where(building, top, np.nan), half, constant_values=np.nan),
            (median_size, median_size))
        reference = np.where(building, np.nanmedian(windows, axis=(-2, -1)), 0.0)
    rise = float(np.tan(np.radians(max_slope_deg)))
    cap = _slope_envelope(np.ascontiguousarray(reference), building, rise, rise * np.sqrt(2.0))
    cap = np.minimum(top, cap + rise)
    return mask & (z[None, None, :] < np.floor(cap + 1e-9)[:, :, None])


@njit(cache=True)
def _slope_envelope(h, valid, rise_axis, rise_diag):
    """Lower *h* (in place) to min over neighbours q of h[q] + rise * distance.

    Two raster passes over the 8-neighbourhood (forward, then backward)
    give the chamfer approximation of the Euclidean distance: axis steps
    cost *rise_axis*, diagonal steps *rise_diag*.  Only cells with
    ``valid`` True take part.  Returns *h*.
    """
    nx, ny = h.shape
    for i in range(nx):
        for j in range(ny):
            if not valid[i, j]:
                continue
            for di, dj, r in ((-1, 0, rise_axis), (0, -1, rise_axis),
                              (-1, -1, rise_diag), (-1, 1, rise_diag)):
                a, b = i + di, j + dj
                if 0 <= a < nx and 0 <= b < ny and valid[a, b] and h[a, b] + r < h[i, j]:
                    h[i, j] = h[a, b] + r
    for i in range(nx - 1, -1, -1):
        for j in range(ny - 1, -1, -1):
            if not valid[i, j]:
                continue
            for di, dj, r in ((1, 0, rise_axis), (0, 1, rise_axis),
                              (1, 1, rise_diag), (1, -1, rise_diag)):
                a, b = i + di, j + dj
                if 0 <= a < nx and 0 <= b < ny and valid[a, b] and h[a, b] + r < h[i, j]:
                    h[i, j] = h[a, b] + r
    return h
