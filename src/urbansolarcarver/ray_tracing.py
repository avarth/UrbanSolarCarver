"""
UrbanSolarCarver: ray generation and voxel grid traversal
=========================================================

This module builds rays (sample point to sky patch, or sample point to sun,
keeping only directions the surface faces) and traces them through the
voxel grid for the carving pipeline.

Rays are traced with the DDA (digital differential analyzer, Amanatides &
Woo 1987) Warp kernels of :mod:`warp_kernels`, launched here, on CUDA or on
Warp's CPU backend.  The fused wrappers (:func:`trace_and_score_dda`,
:func:`trace_and_count_dda`) add each ray's weight or a count of 1
directly into a per-voxel volume, so no list of hits is stored;
:func:`trace_point_access_dda` adds each ray's weight to its test point when
it reaches no occupied voxel.  :func:`mesh_blocks_rays` tests rays against the
context and terrain meshes (a Warp BVH) instead of the grid.  In the sky-patch
modes the wrappers can take a :class:`SkySubRays`: each ray then stands for
several jittered sub-rays over its patch, whose directions the kernels compute,
so the sub-rays are never stored (:func:`mesh_blocks_sky_sub_rays` is their
context test).  There is
no other tracer: when Warp cannot run, the carvers raise
``WarpBackendUnavailableError`` (see :func:`warp_kernels.require_dda_backend`).

The coordinate conventions are those of :mod:`warp_kernels`.
"""

import logging
from typing import NamedTuple, Optional, Tuple

import numpy as np
import torch

from .compute_device import warp_device_name
from .warp_kernels import _warp_available

if _warp_available:
    import warp as wp
    from .warp_kernels import (
        _dda_first_hit_access_kernel, _dda_fused_count_kernel, _dda_fused_score_kernel,
        _dda_fused_score_pw_kernel, _mesh_any_hit_kernel, _mesh_any_hit_sky_kernel,
        _skin_follows_mass_behind_kernel, _sky_sub_ray_directions_kernel,
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


class SkySubRays(NamedTuple):
    """How the kernels split each sky-patch ray into jittered sub-rays.

    Ray ``r`` becomes the ``side**2`` threads ``r * side**2 + k``, each
    tracing the direction :func:`sky_patches.sub_ray_directions` gives and
    carrying ``1 / side**2`` of the patch weight; the sub-rays the surface
    does not face are skipped.  Pass None instead to trace each ray's own
    direction (the patch centre).
    """
    side: int                    # sub-rays per patch = side**2, at least 2 x 2
    patch_cells: torch.Tensor    # (P, 4) float32 extent of each patch (sky_patches.tregenza_patch_cells)

    @property
    def count(self) -> int:
        return self.side * self.side


def _sub_ray_args(sub_rays: Optional[SkySubRays], skip, num_rays: int, surface_normals, device_str, who):
    """Warp inputs for the sky sub-rays: ``(launch_dim, side, cells, use_skip, skip)``.

    Without *sub_rays* the side is 0 (each thread traces its ray's own
    direction) and the cells a 1-element placeholder.  *skip* (uint8, one
    entry per thread, nonzero = do not trace) is optional either way.
    """
    if sub_rays is None:
        side, cells, dim = 0, wp.zeros(1, dtype=wp.vec4, device=device_str), num_rays
    else:
        if sub_rays.side < 2:
            raise ValueError(f"{who}: sub_rays.side must be at least 2, got {sub_rays.side}")
        if surface_normals is None:
            raise ValueError(f"{who}: sub_rays require surface_normals (sub-rays facing away are skipped)")
        side, dim = int(sub_rays.side), num_rays * sub_rays.count
        cells = wp.from_torch(sub_rays.patch_cells.contiguous().float(), dtype=wp.vec4)
    if skip is None:
        return dim, side, cells, 0, wp.zeros(1, dtype=wp.uint8, device=device_str)
    if skip.dtype != torch.uint8 or skip.numel() != dim:
        raise ValueError(f"{who}: skip must be a uint8 tensor of {dim} entries, one per traced ray")
    return dim, side, cells, 1, wp.from_torch(skip.contiguous(), dtype=wp.uint8)


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
    sub_rays: "SkySubRays | None" = None,
    skip: "torch.Tensor | None" = None,
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
    sub_rays : SkySubRays, optional
        Trace ``sub_rays.count`` jittered sub-rays per ray instead of its
        direction, each with that share of the patch weight; requires
        ``surface_normals``.  None (default) traces ``ray_dirs``.
    skip : torch.Tensor, optional
        uint8, one entry per traced ray (R, or R * sub_rays.count): rays
        whose entry is nonzero are not traced (the context blocks them).

    Raises
    ------
    ValueError
        If ``scores`` is not a contiguous float32 tensor (Warp would then
        write into a copy), if ``point_ids`` is given with neither
        ``point_weights`` nor ``surface_normals``, or if either of those
        is given without ``point_ids``, or if ``occupancy`` is given
        without ``surface_normals``, or *sub_rays* without
        ``surface_normals``, or *skip* of another length.
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
    device_str = warp_device_name(origins.device)
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
    dim, side, cells, use_skip, wp_skip = _sub_ray_args(
        sub_rays, skip, num_rays, surface_normals, device_str, "trace_and_score_dda")

    if point_weights is not None:
        wp_point_weights = wp.from_torch(point_weights.contiguous().float())
        wp.launch(
            _dda_fused_score_pw_kernel,
            dim=dim,
            inputs=[
                wp_origins, wp_dirs, wp_patch_ids, wp_point_ids, wp_normals, front,
                skin_rule, wp_occ, side, cells, use_skip, wp_skip,
                grid_origin_wp, float(cell_size), int(resolution), float(ray_length),
                wp_scores, wp_weights, wp_point_weights,
            ],
            device=device_str,
        )
        return

    wp.launch(
        _dda_fused_score_kernel,
        dim=dim,
        inputs=[
            wp_origins, wp_dirs, wp_patch_ids, wp_point_ids, wp_normals, front,
            skin_rule, wp_occ, side, cells, use_skip, wp_skip,
            grid_origin_wp, float(cell_size), int(resolution), float(ray_length),
            wp_scores, wp_weights,
        ],
        device=device_str,
    )


def trace_point_access_dda(
    min_corner: Tuple[float, float, float],
    scale: float,
    resolution: int,
    origins: torch.Tensor,
    ray_dirs: torch.Tensor,
    patch_ids: torch.Tensor,
    patch_weights: torch.Tensor,
    access: torch.Tensor,
    ray_length: float,
    occupancy: torch.Tensor,
    point_ids: torch.Tensor,
    point_weights: "torch.Tensor | None" = None,
    surface_normals: "torch.Tensor | None" = None,
    skin_occupancy: "torch.Tensor | None" = None,
    sub_rays: "SkySubRays | None" = None,
) -> None:
    """Trace rays until the first occupied voxel and add each ray's weight
    to its sample point's accessible or blocked weight in ``access``.

    The grid and ray arguments are those of :func:`trace_and_score_dda`,
    including the note on parallel CPU calls; voxels count under the same
    front-face and skin rules.

    Parameters
    ----------
    access : torch.Tensor, shape (2 * num_points,)
        Flat contiguous float64, modified in place: the accessible weight
        of each sample point, then the blocked weight of each.
    occupancy : torch.Tensor, shape (resolution**3,) or (res, res, res)
        The occupancy grid to evaluate (nonzero = occupied).
    point_ids : torch.Tensor, shape (R,)
        Sample-point index per ray, below ``access.numel() // 2``.
    skin_occupancy : torch.Tensor, optional
        The max volume the skin rule reads (whether a skin voxel has mass
        behind it), as in scoring; default *occupancy*.  Pass the max volume
        when *occupancy* is a carved envelope.
    sub_rays : SkySubRays, optional
        As in :func:`trace_and_score_dda`: a sub-ray the surface does not
        face counts as neither accessible nor blocked.

    Raises
    ------
    ValueError
        If ``access`` is not a contiguous float64 tensor of even length.
    """
    num_rays = origins.shape[0]
    if num_rays == 0:
        return
    if not access.is_contiguous() or access.dtype != torch.float64 or access.numel() % 2:
        raise ValueError(
            "trace_point_access_dda: access must be a contiguous float64 tensor "
            "of 2 * num_points entries"
        )
    device_str = warp_device_name(origins.device)
    wp_point_ids, wp_normals, front, skin_rule, _ = _surface_args(
        num_rays, point_ids, surface_normals,
        occupancy if surface_normals is not None else None,
        device_str, "trace_point_access_dda")
    if point_weights is not None:
        use_pw, wp_point_weights = 1, wp.from_torch(point_weights.contiguous().float())
    else:
        use_pw, wp_point_weights = 0, wp.zeros(1, dtype=float, device=device_str)
    dim, side, cells, _, _ = _sub_ray_args(
        sub_rays, None, num_rays, surface_normals, device_str, "trace_point_access_dda")

    wp.launch(
        _dda_first_hit_access_kernel,
        dim=dim,
        inputs=[
            wp.from_torch(origins.contiguous().float(), dtype=wp.vec3),
            wp.from_torch(ray_dirs.contiguous().float(), dtype=wp.vec3),
            wp.from_torch(patch_ids.contiguous().int()), wp_point_ids, wp_normals, front, skin_rule,
            _occupancy_array(occupancy),
            _occupancy_array(occupancy if skin_occupancy is None else skin_occupancy),
            side, cells,
            wp.vec3(float(min_corner[0]), float(min_corner[1]), float(min_corner[2])),
            float(scale / resolution), int(resolution), float(ray_length),
            wp.from_torch(access, dtype=wp.float64), int(access.numel() // 2),
            wp.from_torch(patch_weights.contiguous().float()), use_pw, wp_point_weights,
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
    device_str = warp_device_name(origins.device)
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
    patch_ids: "torch.Tensor | None" = None,
    sub_rays: "SkySubRays | None" = None,
    skip: "torch.Tensor | None" = None,
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
    patch_ids, sub_rays, skip : optional
        As in :func:`trace_and_score_dda`; pass the ones the scores were
        traced with.  *patch_ids* is required with *sub_rays*.

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
    device_str = warp_device_name(origins.device)
    wp_dtype = wp.int32 if values.dtype == torch.int32 else wp.float32
    if sub_rays is not None and patch_ids is None:
        raise ValueError("follow_mass_behind_skin_dda: sub_rays require patch_ids")
    dim, side, cells, use_skip, wp_skip = _sub_ray_args(
        sub_rays, skip, num_rays, surface_normals, device_str, "follow_mass_behind_skin_dda")
    wp_patch_ids = (wp.from_torch(patch_ids.contiguous().int()) if sub_rays is not None
                    else wp.zeros(1, dtype=int, device=device_str))
    wp.launch(
        _skin_follows_mass_behind_kernel,
        dim=dim,
        inputs=[
            wp.from_torch(origins.contiguous().float(), dtype=wp.vec3),
            wp.from_torch(ray_dirs.contiguous().float(), dtype=wp.vec3),
            wp.from_torch(point_ids.contiguous().int()),
            wp.from_torch(surface_normals.contiguous().float(), dtype=wp.vec3),
            wp_patch_ids, side, cells, use_skip, wp_skip,
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

def mesh_blocks_rays(
    blocking,
    origins: torch.Tensor,
    directions: torch.Tensor,
    point_ids: torch.Tensor,
    surface_normals: torch.Tensor,
    max_t: float,
    origin_offset: float = 0.01,
    min_hit: float = 1e-3,
) -> torch.Tensor:
    """Which rays hit the context or terrain mesh within *max_t*.

    Parameters
    ----------
    blocking : context_geometry.BlockingMesh
        The context and terrain meshes, in the frame of *origins*.
    origins, directions : torch.Tensor, shape (R, 3)
        Ray start points (the test points) and unit directions.
    point_ids : torch.Tensor, shape (R,)
        Test point of each ray, an index into *surface_normals*.
    surface_normals : torch.Tensor, shape (P, 3)
        Outward unit normal of each test point.  Each ray starts
        *origin_offset* off its test surface along it, and hits closer than
        *min_hit* are ignored, so a test surface lying on a context face
        (a neighbour's facade) is not blocked by that face.

    Returns
    -------
    torch.Tensor
        (R,) bool on the device of *origins*, True where the ray is blocked.
    """
    num_rays = origins.shape[0]
    if num_rays == 0:
        return torch.zeros(0, dtype=torch.bool, device=origins.device)
    device_str = warp_device_name(origins.device)
    blocked = torch.zeros(num_rays, dtype=torch.uint8, device=origins.device)
    wp.launch(
        _mesh_any_hit_kernel,
        dim=num_rays,
        inputs=[
            blocking.mesh.id,
            wp.from_torch(origins.contiguous().float(), dtype=wp.vec3),
            wp.from_torch(directions.contiguous().float(), dtype=wp.vec3),
            wp.from_torch(point_ids.contiguous().int()),
            wp.from_torch(surface_normals.contiguous().float(), dtype=wp.vec3),
            float(origin_offset), float(min_hit), float(max_t),
            wp.from_torch(blocked, dtype=wp.uint8),
        ],
        device=device_str,
    )
    wp.synchronize_device(device_str)
    return blocked.bool()


# Sub-rays per launch of the context test, about: keeps each launch well under
# the time limit of a GPU's display watchdog.
_SUB_RAYS_PER_MESH_LAUNCH = 1 << 24


class SkySubRayBlocking(NamedTuple):
    """What the context and terrain block of the sky sub-rays (:func:`mesh_blocks_sky_sub_rays`)."""
    status: torch.Tensor                   # (R * count,) uint8: 0 free, 1 blocked, 2 the surface faces away
    rays_of_point: torch.Tensor            # (P,) int32 sub-rays each point faces
    blocked_of_point: torch.Tensor         # (P,) int32 of them blocked
    weight_of_point: torch.Tensor          # (P,) float64 their weight
    blocked_weight_of_point: torch.Tensor  # (P,) float64 weight of the blocked ones


def mesh_blocks_sky_sub_rays(
    blocking,
    origins: torch.Tensor,
    patch_ids: torch.Tensor,
    point_ids: torch.Tensor,
    surface_normals: torch.Tensor,
    sub_rays: SkySubRays,
    patch_weights: torch.Tensor,
    max_t: float,
    point_weights: "torch.Tensor | None" = None,
    origin_offset: float = 0.01,
    min_hit: float = 1e-3,
) -> SkySubRayBlocking:
    """:func:`mesh_blocks_rays` for the sky sub-rays of *sub_rays*.

    Each ray of *origins*, *patch_ids* and *point_ids* stands for
    ``sub_rays.count`` sub-rays, tested one thread each in launches of
    about 16 million.  Returns each sub-ray's status and, per test point,
    how many sub-rays it faces and their weight (``patch_weights[patch] /
    count``, times *point_weights* when given), and how much of that the
    mesh blocks.
    """
    num_rays = origins.shape[0]
    num_points = int(surface_normals.shape[0])
    device = origins.device
    count = sub_rays.count
    status = torch.zeros(num_rays * count, dtype=torch.uint8, device=device)
    per_point = [torch.zeros(num_points, dtype=dtype, device=device)
                 for dtype in (torch.int32, torch.int32, torch.float64, torch.float64)]
    if num_rays == 0:
        return SkySubRayBlocking(status, *per_point)
    device_str = warp_device_name(device)
    if point_weights is not None:
        use_pw, wp_point_weights = 1, wp.from_torch(point_weights.contiguous().float())
    else:
        use_pw, wp_point_weights = 0, wp.zeros(1, dtype=float, device=device_str)
    normals = wp.from_torch(surface_normals.contiguous().float(), dtype=wp.vec3)
    cells = wp.from_torch(sub_rays.patch_cells.contiguous().float(), dtype=wp.vec4)
    weights = wp.from_torch(patch_weights.contiguous().float())
    outputs = [wp.from_torch(per_point[0], dtype=wp.int32), wp.from_torch(per_point[1], dtype=wp.int32),
               wp.from_torch(per_point[2], dtype=wp.float64), wp.from_torch(per_point[3], dtype=wp.float64)]
    step = max(1, _SUB_RAYS_PER_MESH_LAUNCH // count)
    for start in range(0, num_rays, step):
        end = min(start + step, num_rays)
        wp.launch(
            _mesh_any_hit_sky_kernel,
            dim=(end - start) * count,
            inputs=[
                blocking.mesh.id,
                wp.from_torch(origins[start:end].contiguous().float(), dtype=wp.vec3),
                wp.from_torch(patch_ids[start:end].contiguous().int()),
                wp.from_torch(point_ids[start:end].contiguous().int()),
                normals, int(sub_rays.side), cells, weights, use_pw, wp_point_weights,
                float(origin_offset), float(min_hit), float(max_t),
                wp.from_torch(status[start * count:end * count], dtype=wp.uint8),
                *outputs,
            ],
            device=device_str,
        )
    wp.synchronize_device(device_str)
    return SkySubRayBlocking(status, *per_point)


def sky_sub_ray_directions(point_ids: torch.Tensor, patch_ids: torch.Tensor, sub_rays: SkySubRays) -> torch.Tensor:
    """The (R * count, 3) float32 sub-ray directions the kernels trace for these rays, on their device.

    The same directions as :func:`sky_patches.sub_ray_directions`, computed
    by the kernels' own function (float32).  Includes the sub-rays the
    surface does not face.
    """
    num_rays = point_ids.shape[0]
    directions = torch.zeros((num_rays * sub_rays.count, 3), dtype=torch.float32, device=point_ids.device)
    if num_rays == 0:
        return directions
    device_str = warp_device_name(point_ids.device)
    wp.launch(
        _sky_sub_ray_directions_kernel,
        dim=num_rays * sub_rays.count,
        inputs=[
            wp.from_torch(point_ids.contiguous().int()), wp.from_torch(patch_ids.contiguous().int()),
            int(sub_rays.side), wp.from_torch(sub_rays.patch_cells.contiguous().float(), dtype=wp.vec4),
            wp.from_torch(directions, dtype=wp.vec3),
        ],
        device=device_str,
    )
    wp.synchronize_device(device_str)
    return directions


def generate_sky_patch_rays(
    pts: np.ndarray,
    norms: np.ndarray,
    patch_dirs: torch.Tensor,
    device: torch.device,
    facing_margin: float = 0.0,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """One ray per (sample point, sky patch) pair whose patch the surface faces.

    A ray is kept only where dot(normal, patch direction) > -facing_margin:
    with the default 0, where the surface faces the patch centre; with sky
    sub-rays, :func:`sky_patches.patch_facing_margin` keeps every patch the
    surface faces in part.

    The rays are ordered by patch, then by sample point, so the threads that
    run together trace one direction from neighbouring points and visit
    nearby voxels; on the GPU this keeps the voxel arrays in the cache (on
    the District example, tracing took a quarter of the time it took with
    the rays ordered by point).

    Parameters
    ----------
    pts, norms : np.ndarray (P, 3)
        Sample points and their outward unit normals.
    patch_dirs : torch.Tensor (V, 3)
        Unit directions of the sky patches.
    device : torch.device
        Device for the returned tensors.
    facing_margin : float
        See above; 0 or more.

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

    # (patch, point) pairs in patch-major order: see the docstring.
    patch_ids, point_idx = torch.nonzero(sky_vectors @ normal_vecs.t() > -float(facing_margin), as_tuple=True)
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

def auto_batch_size(
    device: torch.device,
    *,
    vram_fraction: float = 0.6,
    fallback: int = 300_000,
) -> int:
    """Choose a ray batch size from the free GPU memory.

    The budget is ``vram_fraction`` of free VRAM (video memory).  The fused
    DDA kernels accumulate into the voxel grid and keep no hit lists, so a
    batch only adds its slice of the ray inputs: 96 bytes per ray (see the
    comment in the code).  The result is at least 10,000 and at most
    5,000,000 rays.

    Returns ``fallback`` on CPU or if VRAM cannot be queried.

    Parameters
    ----------
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

    # Per ray: origin and direction (2 x 12 bytes), patch id and point id
    # (2 x 8 bytes, int64) = 40 bytes, rounded up to 48; doubled for the
    # copies made when a slice is not contiguous or needs int32 ids.
    bytes_per_ray = 96
    batch = min(max(budget_bytes // bytes_per_ray, 10_000), 5_000_000)

    log.info("auto_batch_size: free=%.0f MB, budget=%.0f MB, batch=%d",
             free / 1e6, budget_bytes / 1e6, batch)
    return batch
