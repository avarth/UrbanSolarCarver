"""
UrbanSolarCarver: ray generation and voxel grid traversal
=========================================================

This module builds rays (sample point to sky patch, or sample point to sun,
keeping only directions the surface faces) and traces them through the
voxel grid for the carving pipeline.

Two traversal backends are available:

* DDA (digital differential analyzer, Amanatides & Woo 1987): the Warp
  kernels of :mod:`warp_kernels`, launched here.  The fused wrappers
  (:func:`trace_and_score_dda`, :func:`trace_and_count_dda`) add each
  ray's weight or a count of 1 directly into a per-voxel volume, so no
  list of hits is stored.  Used whenever Warp can run on the device
  (CUDA or Warp's CPU backend).

* Fixed-step fallback (:func:`trace_multi_hit_grid`): pure PyTorch, used
  only when Warp is unavailable.  It samples each ray at regular
  distances and returns the list of (ray, voxel) pairs.  It is
  approximate: an oblique ray can cross a voxel corner between two
  samples, so that voxel is missed.

The coordinate conventions are those of :mod:`warp_kernels`.
"""

import logging
import math
from typing import Tuple

import numpy as np
import torch

from .warp_kernels import _warp_available

if _warp_available:
    import warp as wp
    from .warp_kernels import (
        _dda_fused_count_kernel, _dda_fused_score_kernel, _dda_fused_score_pw_kernel,
        _skin_follows_mass_behind_kernel,
    )

log = logging.getLogger(__name__)


def _surface_args(num_rays, point_ids, surface_normals, occupancy, device_str, who):
    """Warp inputs for the behind-surface voxel filter and the skin rule.

    Returns ``(point_ids, normals, front_test, skin_rule, occupancy)``.
    Without *surface_normals* the normals are a 1-element placeholder and
    ``front_test`` is 0, so the kernels skip the filter; missing
    *point_ids* become zeros.  Without *occupancy* the grid is a 1-element
    placeholder and ``skin_rule`` is 0, so skin voxels are never counted.
    """
    if surface_normals is not None and point_ids is None:
        raise ValueError(f"{who}: surface_normals and point_ids must be provided together")
    if occupancy is not None and surface_normals is None:
        raise ValueError(f"{who}: occupancy requires surface_normals and point_ids")
    ids = (wp.from_torch(point_ids.contiguous().int()) if point_ids is not None
           else wp.zeros(num_rays, dtype=int, device=device_str))
    if occupancy is None:
        occ, skin_rule = wp.zeros(1, dtype=wp.uint8, device=device_str), 0
    else:
        occ, skin_rule = _occupancy_array(occupancy), 1
    if surface_normals is None:
        return ids, wp.zeros(1, dtype=wp.vec3, device=device_str), 0, skin_rule, occ
    return (ids, wp.from_torch(surface_normals.contiguous().float(), dtype=wp.vec3), 1,
            skin_rule, occ)


def _occupancy_array(occupancy: torch.Tensor):
    """Flat uint8 Warp view of a max volume occupancy grid (any dtype, nonzero = occupied)."""
    flat = occupancy.reshape(-1)
    if flat.dtype != torch.uint8:
        flat = (flat != 0).to(torch.uint8)
    return wp.from_torch(flat.contiguous(), dtype=wp.uint8)


def trace_and_score_dda(
    min_corner: Tuple[float, float, float],
    scale: float,
    resolution: int,
    origins: torch.Tensor,
    ray_dirs: torch.Tensor,
    patch_ids: torch.Tensor,
    patch_weights: torch.Tensor,
    scores: torch.Tensor,
    ray_length: float,
    point_ids: "torch.Tensor | None" = None,
    point_weights: "torch.Tensor | None" = None,
    surface_normals: "torch.Tensor | None" = None,
    occupancy: "torch.Tensor | None" = None,
) -> None:
    """Trace rays with the Warp DDA kernel and add each ray's weight to every
    voxel it visits, directly into ``scores``.

    Runs on CUDA or the Warp CPU backend.  On CPU, do not let parallel
    calls write into the same ``scores`` tensor (see the note above
    ``_DDAState``).

    Parameters
    ----------
    min_corner : tuple of float
        World-space (x, y, z) of the grid's lower corner.
    scale : float
        Edge length of the cubic grid in meters.
    resolution : int
        Voxels per axis.
    origins, ray_dirs : torch.Tensor, shape (R, 3)
        Ray start points and unit directions.
    patch_ids : torch.Tensor, shape (R,)
        Sky patch index per ray.
    patch_weights : torch.Tensor, shape (P,)
        Weight per sky patch.
    scores : torch.Tensor, shape (resolution**3,)
        Flat contiguous float32 score volume, modified in place.
    ray_length : float
        Maximum distance traced along each ray, in meters (directions must
        be unit length for this to be a distance).
    point_ids : torch.Tensor, shape (R,), optional
        Sample-point index per ray; required by ``point_weights`` and
        ``surface_normals``.
    point_weights : torch.Tensor, shape (num_points,), optional
        Weight per sample point in [0, 1] (per-ray weight =
        patch_weight × point_weight; edge_taper design constraint).
    surface_normals : torch.Tensor, shape (num_points, 3), optional
        Normal of each ray's source surface.  When given, only voxels that
        lie entirely in front of that surface are scored; voxels behind it
        or crossed by its plane (the surface's own mass and skin) are not.
    occupancy : torch.Tensor, shape (resolution**3,) or (res, res, res), optional
        Max volume occupancy (nonzero = occupied); requires
        ``surface_normals``.  When given, a voxel crossed by the source
        surface's plane is scored too if the voxel behind it (see
        :func:`follow_mass_behind_skin_dda`) is empty or outside the grid:
        the surface's building is then not part of the max volume, so the
        voxel is not its skin.

    Raises
    ------
    ValueError
        If ``scores`` is not a contiguous float32 tensor (Warp would then
        write into a copy), if ``point_ids`` is given with neither
        ``point_weights`` nor ``surface_normals``, or if either of those
        is given without ``point_ids``, or if ``occupancy`` is given
        without ``surface_normals``.
    """
    num_rays = origins.shape[0]
    if num_rays == 0:
        return
    if point_ids is not None and point_weights is None and surface_normals is None:
        raise ValueError(
            "trace_and_score_dda: point_ids must be provided together with "
            "point_weights or surface_normals"
        )
    if point_weights is not None and point_ids is None:
        raise ValueError(
            "trace_and_score_dda: point_ids and point_weights must be "
            "provided together"
        )
    # Warp requires explicit device index (e.g. "cuda:0", not just "cuda")
    device_str = f"cuda:{origins.device.index or 0}" if origins.is_cuda else "cpu"
    cell_size = scale / resolution

    if not scores.is_contiguous() or scores.dtype != torch.float32:
        raise ValueError(
            "trace_and_score_dda: scores must be a contiguous float32 tensor "
            "(in-place update would silently fail on a copy)"
        )
    wp_origins = wp.from_torch(origins.contiguous().float(), dtype=wp.vec3)
    wp_dirs = wp.from_torch(ray_dirs.contiguous().float(), dtype=wp.vec3)
    wp_patch_ids = wp.from_torch(patch_ids.contiguous().int())
    wp_scores = wp.from_torch(scores)
    wp_weights = wp.from_torch(patch_weights.contiguous().float())
    grid_origin_wp = wp.vec3(float(min_corner[0]), float(min_corner[1]), float(min_corner[2]))
    wp_point_ids, wp_normals, front, skin_rule, wp_occ = _surface_args(
        num_rays, point_ids, surface_normals, occupancy, device_str, "trace_and_score_dda")

    if point_weights is not None:
        wp_point_weights = wp.from_torch(point_weights.contiguous().float())
        wp.launch(
            _dda_fused_score_pw_kernel,
            dim=num_rays,
            inputs=[
                wp_origins, wp_dirs, wp_patch_ids, wp_point_ids, wp_normals, front,
                skin_rule, wp_occ,
                grid_origin_wp, float(cell_size), int(resolution), float(ray_length),
                wp_scores, wp_weights, wp_point_weights,
            ],
            device=device_str,
        )
        return

    wp.launch(
        _dda_fused_score_kernel,
        dim=num_rays,
        inputs=[
            wp_origins, wp_dirs, wp_patch_ids, wp_point_ids, wp_normals, front,
            skin_rule, wp_occ, grid_origin_wp, float(cell_size), int(resolution), float(ray_length),
            wp_scores, wp_weights,
        ],
        device=device_str,
    )


def trace_and_count_dda(
    min_corner: Tuple[float, float, float],
    scale: float,
    resolution: int,
    origins: torch.Tensor,
    ray_dirs: torch.Tensor,
    counts: torch.Tensor,
    ray_length: float,
    point_ids: "torch.Tensor | None" = None,
    surface_normals: "torch.Tensor | None" = None,
    occupancy: "torch.Tensor | None" = None,
) -> None:
    """Trace rays with the Warp DDA kernel and add 1 to ``counts`` for every
    voxel each ray visits, in place.

    The grid and ray arguments are the same as in
    :func:`trace_and_score_dda`, including the note on parallel CPU calls.

    Parameters
    ----------
    counts : torch.Tensor, shape (resolution**3,)
        Flat contiguous int32 hit-count volume, modified in place.
    point_ids, surface_normals : optional
        Per-ray sample-point index and per-point surface normal; when both
        are given, voxels behind the ray's source surface are not counted.
        ``point_ids`` alone is accepted and ignored.
    occupancy : torch.Tensor, optional
        Max volume occupancy; skin voxels with nothing behind them are
        counted, as in :func:`trace_and_score_dda`.

    Raises
    ------
    ValueError
        If ``counts`` is not a contiguous int32 tensor, or
        ``surface_normals`` is given without ``point_ids``, or ``occupancy``
        without ``surface_normals``.
    """
    num_rays = origins.shape[0]
    if num_rays == 0:
        return
    device_str = f"cuda:{origins.device.index or 0}" if origins.is_cuda else "cpu"
    cell_size = scale / resolution

    if not counts.is_contiguous() or counts.dtype != torch.int32:
        raise ValueError(
            "trace_and_count_dda: counts must be a contiguous int32 tensor "
            "(in-place update would silently fail on a copy)"
        )
    wp_origins = wp.from_torch(origins.contiguous().float(), dtype=wp.vec3)
    wp_dirs = wp.from_torch(ray_dirs.contiguous().float(), dtype=wp.vec3)
    wp_counts = wp.from_torch(counts)
    grid_origin_wp = wp.vec3(float(min_corner[0]), float(min_corner[1]), float(min_corner[2]))
    wp_point_ids, wp_normals, front, skin_rule, wp_occ = _surface_args(
        num_rays, point_ids, surface_normals, occupancy, device_str, "trace_and_count_dda")

    wp.launch(
        _dda_fused_count_kernel,
        dim=num_rays,
        inputs=[
            wp_origins, wp_dirs, wp_point_ids, wp_normals, front,
            skin_rule, wp_occ, grid_origin_wp, float(cell_size), int(resolution), float(ray_length),
            wp_counts,
        ],
        device=device_str,
    )



def follow_mass_behind_skin_dda(
    min_corner: Tuple[float, float, float],
    scale: float,
    resolution: int,
    origins: torch.Tensor,
    ray_dirs: torch.Tensor,
    point_ids: torch.Tensor,
    surface_normals: torch.Tensor,
    occupancy: torch.Tensor,
    values: torch.Tensor,
    ray_length: float,
) -> torch.Tensor:
    """Return *values* with every own-skin voxel raised to the value of the
    voxel behind it.

    A voxel the source surface's plane passes through is that surface's
    skin.  When the skin voxel and the voxel behind it are both occupied,
    the skin belongs to the mass behind the surface: its own rays do not count it, but it must not
    outlast that mass.  So each skin voxel a ray visits takes the maximum
    of its value and the value of the voxel behind it (counts: removed when
    the mass behind is removed; scores: never below the mass behind).

    The voxel behind a skin voxel is found by stepping from the skin
    voxel's centre one cell length at a time against the surface normal,
    up to three steps, until the voxel containing the stepped point lies
    wholly behind the plane.

    Parameters
    ----------
    min_corner, scale, resolution, origins, ray_dirs, ray_length :
        As in :func:`trace_and_count_dda`; pass the same rays.
    point_ids : torch.Tensor, shape (R,)
        Sample-point index per ray.
    surface_normals : torch.Tensor, shape (num_points, 3)
        Unit normal of each sample point's surface.
    occupancy : torch.Tensor
        Max volume occupancy, resolution**3 voxels (nonzero = occupied).
    values : torch.Tensor, shape (resolution**3,)
        Finished int32 counts or float32 scores; not modified.

    Returns
    -------
    torch.Tensor
        A new flat tensor like *values*.

    Raises
    ------
    ValueError
        If *values* is not int32 or float32.
    """
    if values.dtype not in (torch.int32, torch.float32):
        raise ValueError("follow_mass_behind_skin_dda: values must be int32 or float32")
    values_in = values.reshape(-1).contiguous()
    values_out = values_in.clone()
    num_rays = origins.shape[0]
    if num_rays == 0:
        return values_out
    device_str = f"cuda:{origins.device.index or 0}" if origins.is_cuda else "cpu"
    wp_dtype = wp.int32 if values.dtype == torch.int32 else wp.float32
    wp.launch(
        _skin_follows_mass_behind_kernel,
        dim=num_rays,
        inputs=[
            wp.from_torch(origins.contiguous().float(), dtype=wp.vec3),
            wp.from_torch(ray_dirs.contiguous().float(), dtype=wp.vec3),
            wp.from_torch(point_ids.contiguous().int()),
            wp.from_torch(surface_normals.contiguous().float(), dtype=wp.vec3),
            wp.vec3(float(min_corner[0]), float(min_corner[1]), float(min_corner[2])),
            float(scale / resolution), int(resolution), float(ray_length),
            _occupancy_array(occupancy),
            wp.from_torch(values_in, dtype=wp_dtype),
            wp.from_torch(values_out, dtype=wp_dtype),
        ],
        device=device_str,
    )
    # Warp launches run on Warp's own CUDA stream; wait before torch reads.
    if origins.is_cuda:
        torch.cuda.synchronize()
    return values_out

def generate_sky_patch_rays(
    pts: np.ndarray,
    norms: np.ndarray,
    patch_dirs: torch.Tensor,
    device: torch.device,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """One ray per (sample point, sky patch) pair whose patch the surface faces.

    A ray is kept only where dot(normal, patch direction) > 0.

    Parameters
    ----------
    pts, norms : np.ndarray (P, 3)
        Sample points and their outward unit normals.
    patch_dirs : torch.Tensor (V, 3)
        Unit directions of the sky patches.
    device : torch.device
        Device for the returned tensors.

    Returns
    -------
    origins : (R, 3)      ray start points (the sample points)
    ray_dirs : (R, 3)     unit ray directions
    patch_ids : (R,)      sky patch index of each ray
    point_idx : (R,)      sample point index of each ray
    """
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(f"pts must be Nx3, got {pts.shape}")
    if norms.shape != pts.shape:
        raise ValueError(f"norms shape {norms.shape} must match pts shape {pts.shape}")

    point_coords = torch.from_numpy(pts.astype(np.float32)).to(device)
    normal_vecs = torch.from_numpy(norms.astype(np.float32)).to(device)
    sky_vectors = patch_dirs.to(dtype=torch.float32, device=device)

    point_idx, patch_ids = torch.nonzero(normal_vecs @ sky_vectors.t() > 0, as_tuple=True)
    return point_coords[point_idx], sky_vectors[patch_ids], patch_ids, point_idx

def generate_sun_rays(
    points_3d: np.ndarray,
    point_normals: np.ndarray,
    sun_directions: np.ndarray,
    device: torch.device,
    return_point_idx: bool = False,
):
    """
    Build one ray per (sample point, sun direction) pair that the surface
    faces, i.e. where dot(normal, sun direction) > 0.

    Args:
      points_3d:    (P,3) NumPy array of sample points on the surface.
      point_normals:(P,3) NumPy array of normals at each sample point.
      sun_directions:(S,3) NumPy array of unit vectors pointing toward the
                     sun.  They are used as ray directions unchanged, so
                     they must be unit length for ray_length to be a distance.
      device:       Torch device for the returned tensors.
      return_point_idx: also return the source sample-point index per ray.

    Returns:
      ray_origins:   (R,3) float32 tensor of ray start points.
      ray_directions:(R,3) float32 tensor of ray direction vectors.
      point_idx:     (R,) int64 source sample-point index per ray, only when
                     return_point_idx is True.

    Raises:
      ValueError: if the arrays are not (N,3) or the normals do not match
                  the points.
    """
    if points_3d.ndim != 2 or points_3d.shape[1] != 3:
        raise ValueError(f"points_3d must be Nx3, got {points_3d.shape}")
    if point_normals.shape != points_3d.shape:
        raise ValueError(f"point_normals shape {point_normals.shape} must match points_3d shape {points_3d.shape}")
    if sun_directions.ndim != 2 or sun_directions.shape[1] != 3:
        raise ValueError(f"sun_directions must be Sx3, got {sun_directions.shape}")
    pts_tensor   = torch.from_numpy(points_3d.astype(np.float32)).to(device)
    norms_tensor = torch.from_numpy(point_normals.astype(np.float32)).to(device)
    suns_tensor  = torch.from_numpy(sun_directions.astype(np.float32)).to(device)

    dot_ps = norms_tensor @ suns_tensor.t()  # (P, S)

    facing_mask = dot_ps > 0.0

    idx_pts, idx_suns = torch.nonzero(facing_mask, as_tuple=True)

    ray_origins    = pts_tensor[idx_pts]    # (R,3)
    ray_directions = suns_tensor[idx_suns]  # (R,3)

    if return_point_idx:
        return ray_origins, ray_directions, idx_pts
    return ray_origins, ray_directions

def trace_multi_hit_grid(
    min_corner: Tuple[float, float, float],
    scale: float,
    resolution: int,
    origins: torch.Tensor,
    ray_dirs: torch.Tensor,
    sky_patch_ids: torch.Tensor,
    voxel_size: float,
    ray_length: float,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Fallback tracer for when Warp cannot run: list the voxels each ray visits.

    Fixed-step PyTorch marching (see :func:`_trace_fixed_step` for the
    parameters); when Warp is available the pipeline uses the exact fused
    DDA kernels instead.  Each (ray, voxel) pair appears at most once.
    Every call with at least one ray emits a UserWarning.

    Returns
    -------
    ray_ids : (H,)        index of the ray that made each hit
    patch_ids : (H,)      sky patch of that ray
    voxel_indices : (H, 3) grid index of each visited voxel
    """
    if origins.shape[0] == 0:
        empty1 = torch.empty((0,), dtype=torch.long, device=origins.device)
        return empty1, empty1, torch.empty((0, 3), dtype=torch.long, device=origins.device)
    log.warning(
        "Warp is not available: using the fixed-step ray marcher, which is "
        "slower and can miss voxels that oblique rays only clip."
    )
    return _trace_fixed_step(min_corner, float(scale), resolution, origins, ray_dirs,
                             sky_patch_ids, voxel_size, ray_length)


# Memory budget that sets how many rays _trace_fixed_step processes per
# chunk (R rays x S steps per chunk).  Tests lower it by assigning to this
# module attribute.
_FIXED_STEP_BUDGET_BYTES: int = 512 * 1024 * 1024


def _trace_fixed_step(
    min_corner, scale, resolution,
    origins, ray_dirs, sky_patch_ids,
    voxel_size, ray_length,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Fixed-step ray marcher in pure PyTorch (runs on any torch device).

    Samples each ray at distances ``(k + 0.5) * voxel_size`` for
    ``k = 0 .. ceil(ray_length / voxel_size) - 1`` and records the voxel
    containing each in-bounds sample.  Each (ray, voxel) pair is reported
    at most once, as with the DDA kernels.  Used only when Warp is not
    installed or cannot run on the device.

    With a step of one voxel, an oblique ray can cross a voxel corner
    between two samples and miss that voxel; the Warp DDA kernels do not
    have this problem.

    Rays are processed in chunks sized from ``_FIXED_STEP_BUDGET_BYTES``
    (512 MB by default) so the ``(R, S, 3)`` sample tensor never covers
    all rays at once.  The output is identical for any chunk size.

    Parameters
    ----------
    min_corner : tuple of float
        World-space (x, y, z) of the grid's lower corner.
    scale : float
        Edge length of the cubic grid in meters.
    resolution : int
        Number of voxels per axis.
    origins : (R, 3) torch.Tensor
        Ray start positions.
    ray_dirs : (R, 3) torch.Tensor
        Unit direction vectors.
    sky_patch_ids : (R,) torch.Tensor
        Sky-patch index per ray.
    voxel_size : float
        Step length along the ray (meters); callers pass the voxel edge
        length.  Must be positive.
    ray_length : float
        Maximum march distance (meters).

    Returns
    -------
    ray_ids : (H,) torch.Tensor
        Which ray produced each hit (indices into the *full* input batch).
    patch_ids : (H,) torch.Tensor
        Sky-patch index for each hit.
    voxel_indices : (H, 3) torch.Tensor
        3-D grid coordinates of each visited voxel.

    Raises
    ------
    ValueError
        If ``voxel_size`` is not positive.
    """
    device = origins.device
    num_rays = origins.shape[0]

    if voxel_size <= 0:
        raise ValueError(
            f"_trace_fixed_step: voxel_size must be positive, got {voxel_size}"
        )
    num_steps = math.ceil(ray_length / voxel_size)
    if num_steps <= 0 or num_rays == 0:
        empty1 = torch.empty((0,), dtype=torch.long, device=device)
        empty3 = torch.empty((0, 3), dtype=torch.long, device=device)
        return empty1, empty1, empty3

    # Chunk size from the tensors held per sample: sample_pts and voxel_rel
    # (3 x float32 each, 24 bytes), voxel_idxs (3 x int64, 24 bytes) and
    # in_bounds (1 byte) make 49 bytes; 64 leaves room for the selections.
    bytes_per_ray = num_steps * 64
    budget = _FIXED_STEP_BUDGET_BYTES
    chunk_size = max(budget // max(bytes_per_ray, 1), 1)

    distances = (
        (torch.arange(num_steps, dtype=torch.float32, device=device) + 0.5)
        * voxel_size
    )
    grid_origin = torch.tensor(min_corner, dtype=torch.float32, device=device)

    all_ray_ids = []
    all_patch_ids = []
    all_voxel_indices = []

    for start in range(0, num_rays, chunk_size):
        end = min(start + chunk_size, num_rays)
        o = origins[start:end]             # (C, 3)
        d = ray_dirs[start:end]            # (C, 3)
        c = end - start

        sample_pts = o[:, None, :] + d[:, None, :] * distances[None, :, None]
        voxel_rel = (sample_pts - grid_origin) / scale * resolution
        voxel_idxs = torch.floor(voxel_rel).long()

        in_bounds = (
            (voxel_idxs[..., 0] >= 0) & (voxel_idxs[..., 0] < resolution) &
            (voxel_idxs[..., 1] >= 0) & (voxel_idxs[..., 1] < resolution) &
            (voxel_idxs[..., 2] >= 0) & (voxel_idxs[..., 2] < resolution)
        )

        ray_indices = torch.arange(c, device=device)[:, None].expand_as(in_bounds)
        chunk_ray_ids = ray_indices[in_bounds] + start  # offset to global index
        chunk_voxels = voxel_idxs[in_bounds]

        if chunk_ray_ids.numel() > 0:
            # Deduplicate (ray, voxel) pairs: two samples of one ray can fall
            # in the same voxel, which would count that ray twice for the
            # voxel.  Duplicates only arise within a single ray, and a ray
            # is never split across chunks, so per-chunk deduplication is
            # exact.  torch.unique sorts the keys, so the output order is
            # deterministic and independent of chunk size.
            res_sq = resolution * resolution
            n_vox = res_sq * resolution
            flat_vox = (
                chunk_voxels[:, 0] * res_sq
                + chunk_voxels[:, 1] * resolution
                + chunk_voxels[:, 2]
            )
            ukey = torch.unique(chunk_ray_ids * n_vox + flat_vox)
            uray = ukey // n_vox
            uflat = ukey - uray * n_vox
            uvox = torch.stack(
                (uflat // res_sq, (uflat % res_sq) // resolution, uflat % resolution),
                dim=1,
            )
            all_ray_ids.append(uray)
            all_patch_ids.append(sky_patch_ids[uray])
            all_voxel_indices.append(uvox)

        # Free this chunk's tensors before the next chunk allocates its own.
        del sample_pts, voxel_rel, voxel_idxs, in_bounds

    if not all_ray_ids:
        empty1 = torch.empty((0,), dtype=torch.long, device=device)
        empty3 = torch.empty((0, 3), dtype=torch.long, device=device)
        return empty1, empty1, empty3

    return (
        torch.cat(all_ray_ids),
        torch.cat(all_patch_ids),
        torch.cat(all_voxel_indices),
    )


def auto_batch_size(
    resolution: int,
    device: torch.device,
    *,
    vram_fraction: float = 0.6,
    fallback: int = 300_000,
) -> int:
    """Choose a ray batch size from the free GPU memory.

    The budget is ``vram_fraction`` of free VRAM (video memory).  With Warp,
    the fused DDA kernels accumulate into the voxel grid and keep no hit
    lists, so a batch only adds its slice of the ray inputs: 96 bytes per
    ray (see the comment in the code).  Without Warp, the fixed-step tracer
    returns one hit record of 40 bytes per visited voxel, estimated as
    ``max(resolution, 50)`` per ray; its sample points are already limited
    by ``_FIXED_STEP_BUDGET_BYTES``.  The result is at least 10,000 and at
    most 5,000,000 rays.

    Returns ``fallback`` on CPU or if VRAM cannot be queried.

    Parameters
    ----------
    resolution : int
        Voxel grid resolution (used only for the no-Warp step estimate).
    device : torch.device
        Target compute device.
    vram_fraction : float
        Fraction of free VRAM to budget for ray tracing (default 0.6).
    fallback : int
        Batch size when VRAM cannot be queried (default 300K).

    Returns
    -------
    int
        Recommended ray batch size.
    """
    if device.type != "cuda":
        return fallback

    try:
        free, total = torch.cuda.mem_get_info(device)
    except Exception:
        return fallback

    budget_bytes = int(free * vram_fraction)

    if _warp_available:
        # Per ray: origin and direction (2 x 12 bytes), patch id and point
        # id (2 x 8 bytes, int64) = 40 bytes, rounded up to 48; doubled for
        # the copies made when a slice is not contiguous or needs int32 ids.
        bytes_per_ray = 96
        batch = max(budget_bytes // bytes_per_ray, 10_000)
    else:
        # Hit records: ray id, patch id (int64) and voxel index (3 x int64)
        # = 40 bytes per visited voxel.
        num_steps = max(resolution, 50)  # rough estimate of voxels per ray
        bytes_per_ray = num_steps * 40
        batch = max(budget_bytes // bytes_per_ray, 10_000)

    batch = min(batch, 5_000_000)

    log.info("auto_batch_size: free=%.0f MB, budget=%.0f MB, batch=%d",
             free / 1e6, budget_bytes / 1e6, batch)
    return batch
