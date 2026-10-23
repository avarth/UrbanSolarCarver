"""
UrbanSolarCarver: context and terrain on the maximum volume's lattice

Context (existing buildings, large trees) and terrain are optional meshes that
stay whatever is built on the site. Preprocessing uses them in two ways:

- the voxels: context removes every voxel column of the maximum volume it
  overlaps (a voxel overlaps when its centre lies inside the context), and
  terrain removes the voxels whose centre lies below the ground;
- the rays: a ray from a test point that hits context or terrain is dropped
  before scoring (the blocking mesh, below).

All coordinates are in the run's local frame (the one the max volume was
voxelized in).

Public API
----------
context_occupancy(vertices, faces, grid_origin, voxel_size, resolution, device)
    Cells of the grid whose centre lies inside the context.
remove_context_columns(occupancy, inside) -> ColumnRemoval
    The column rule.
ground_heights(vertices, faces, grid_origin, voxel_size, resolution, device)
    Ground height per column where the terrain crosses its centre line.
remove_below_ground(occupancy, heights, grid_origin, voxel_size)
    Clear the voxels whose centre lies below the ground.
build_blocking_mesh(meshes, device) -> BlockingMesh | None
    One Warp BVH of the context and terrain, for
    :func:`ray_tracing.mesh_blocks_rays`.
drop_blocked_rays(blocking, origins, directions, point_ids, surface_normals, max_t, ray_weights)
    The rays to keep and what the drop removed (RayDrop).
subtract_columns(polygons, removed_columns, grid_origin_world, voxel_size)
    The max volume's footprint without the removed columns, for massing.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
import torch
import trimesh
from shapely.geometry import Polygon, box

from .compute_device import warp_device_name
from .voxelization import voxelize_solid_warp
from .warp_kernels import _warp_available, require_dda_backend

if _warp_available:
    import warp as wp
    from .warp_kernels import _ground_height_kernel


def _warp_mesh(vertices: np.ndarray, faces: np.ndarray, device_str: str,
               bvh_constructor: str | None = None) -> "wp.Mesh":
    """A Warp BVH mesh of the triangles (float32 points, int32 indices)."""
    arrays = dict(
        points=wp.array(np.ascontiguousarray(vertices, dtype=np.float32), dtype=wp.vec3, device=device_str),
        indices=wp.array(np.ascontiguousarray(faces, dtype=np.int32).ravel(), dtype=wp.int32, device=device_str),
    )
    if bvh_constructor is not None:
        try:
            return wp.Mesh(**arrays, bvh_constructor=bvh_constructor)
        except TypeError:   # a Warp without the option
            pass
    return wp.Mesh(**arrays)


def context_occupancy(vertices: np.ndarray, faces: np.ndarray, grid_origin: np.ndarray, voxel_size: float,
                      resolution: int, device) -> np.ndarray:
    """The (R, R, R) bool cells of the grid whose centre lies inside the context mesh.

    The parity voxelizer runs with the centre-inside rule only (no surface
    through the voxel), so a context face shared with the max volume (a party
    wall) takes no voxel of the site. Its rays start and end at the context's
    bounds, so a context far larger than the grid is classified correctly
    inside it. An open context mesh gives an incomplete result there (the
    caller warns).
    """
    require_dda_backend(device)
    vertices = np.asarray(vertices, dtype=np.float64)
    inside = voxelize_solid_warp(vertices, faces, grid_origin, voxel_size, resolution, device, centre_only=True,
                                 span_min=vertices.min(axis=0), span_max=vertices.max(axis=0))
    return inside


@dataclass(frozen=True)
class ColumnRemoval:
    """The max volume's occupancy after the column rule."""
    occupancy: np.ndarray        # uint8 (R, R, R)
    removed_columns: np.ndarray  # bool (R, R): columns that lost all their voxels to context
    voxels_removed: int


def remove_context_columns(occupancy: np.ndarray, inside: np.ndarray) -> ColumnRemoval:
    """Remove every column (i, j) in which a context cell overlaps an occupied voxel, over its full height.

    Nothing is built above, below or beside kept context within its columns.
    """
    occupied = np.asarray(occupancy) != 0
    removed_columns = (np.asarray(inside, dtype=bool) & occupied).any(axis=2)
    reduced = occupied.copy()
    reduced[removed_columns, :] = False
    voxels_removed = int(occupied.sum() - reduced.sum())
    return ColumnRemoval(occupancy=reduced.astype(np.uint8), removed_columns=removed_columns,
                         voxels_removed=voxels_removed)


def ground_heights(vertices: np.ndarray, faces: np.ndarray, grid_origin: np.ndarray, voxel_size: float,
                   resolution: int, device) -> np.ndarray:
    """The (R, R) float64 ground height (local z) of each grid column, NaN where the terrain does not cross it.

    The height is where the terrain crosses the column's vertical centre line,
    the highest crossing if there are several (an overhang). One downward ray
    per column from above the terrain's top; an open sheet works.
    """
    require_dda_backend(device)
    device_str = warp_device_name(device)
    vertices = np.asarray(vertices, dtype=np.float64)
    mesh = _warp_mesh(vertices, faces, device_str)
    top, bottom = float(vertices[:, 2].max()), float(vertices[:, 2].min())
    start_z = top + float(voxel_size)
    heights = wp.zeros(resolution * resolution, dtype=wp.float32, device=device_str)
    wp.launch(_ground_height_kernel, dim=resolution * resolution,
              inputs=[mesh.id, wp.vec3(*(float(value) for value in grid_origin)), float(voxel_size),
                      int(resolution), start_z, start_z - bottom + float(voxel_size), heights],
              device=device_str)
    wp.synchronize()
    return heights.numpy().astype(np.float64).reshape(resolution, resolution)


def remove_below_ground(occupancy: np.ndarray, heights: np.ndarray, grid_origin: np.ndarray,
                        voxel_size: float) -> tuple[np.ndarray, int]:
    """Clear the voxels whose centre z lies below their column's ground height (NaN columns keep all theirs).

    Returns the new uint8 occupancy and the number of voxels removed. The
    column rule does not apply: the column stays buildable above the ground.
    """
    occupied = np.asarray(occupancy) != 0
    resolution = occupied.shape[2]
    centres_z = float(grid_origin[2]) + (np.arange(resolution) + 0.5) * float(voxel_size)
    with np.errstate(invalid="ignore"):
        below = centres_z[None, None, :] < np.asarray(heights, dtype=np.float64)[:, :, None]
    reduced = occupied & ~below
    return reduced.astype(np.uint8), int(occupied.sum() - reduced.sum())


@dataclass
class BlockingMesh:
    """The context and terrain as one Warp BVH, in the run's local frame."""
    mesh: "wp.Mesh"
    device: str
    triangle_count: int


def build_blocking_mesh(meshes: list[trimesh.Trimesh], device) -> BlockingMesh | None:
    """One BVH of *meshes* (already in the local frame) for the ray test; None when there are none.

    A surface-area-heuristic BVH is used where the Warp version offers it
    (faster to trace for large meshes such as terrain).
    """
    meshes = [mesh for mesh in meshes if mesh is not None and len(mesh.faces)]
    if not meshes:
        return None
    require_dda_backend(device)
    device_str = warp_device_name(device)
    combined = meshes[0] if len(meshes) == 1 else trimesh.util.concatenate(meshes)
    mesh = _warp_mesh(combined.vertices, combined.faces, device_str, bvh_constructor="sah")
    return BlockingMesh(mesh=mesh, device=device_str, triangle_count=int(len(combined.faces)))


@dataclass(frozen=True)
class RayDrop:
    """What dropping the rays that hit context or terrain removed, before scoring."""
    rays_total: int
    rays_dropped: int
    weight_total: float              # in the mode's weight unit (one per ray for time-based)
    weight_dropped: float
    test_points_fully_blocked: int   # test points that had rays and lost all of them

    @property
    def weight_dropped_share(self) -> float:
        return self.weight_dropped / self.weight_total if self.weight_total > 0 else 0.0


def drop_blocked_rays(blocking: BlockingMesh, origins: torch.Tensor, directions: torch.Tensor,
                      point_ids: torch.Tensor, surface_normals: torch.Tensor, max_t: float,
                      ray_weights: "torch.Tensor | None" = None) -> tuple[torch.Tensor, RayDrop]:
    """The (R,) bool mask of rays to keep (those that miss the blocking mesh), and the RayDrop.

    *ray_weights* (R,) is each ray's weight; None counts each ray as 1.
    """
    from .ray_tracing import mesh_blocks_rays
    blocked = mesh_blocks_rays(blocking, origins, directions, point_ids, surface_normals, max_t)
    weights = (torch.ones(blocked.shape[0], dtype=torch.float64, device=blocked.device) if ray_weights is None
               else ray_weights.to(torch.float64))
    ids = point_ids.long()
    num_points = int(surface_normals.shape[0])
    rays_of_point = torch.bincount(ids, minlength=num_points)
    blocked_of_point = torch.bincount(ids[blocked], minlength=num_points)
    fully_blocked = int(((rays_of_point > 0) & (blocked_of_point == rays_of_point)).sum())
    drop = RayDrop(rays_total=int(blocked.shape[0]), rays_dropped=int(blocked.sum()),
                   weight_total=float(weights.sum()), weight_dropped=float(weights[blocked].sum()),
                   test_points_fully_blocked=fully_blocked)
    return ~blocked, drop


def subtract_columns(polygons: list[Polygon], removed_columns: np.ndarray, grid_origin_world: np.ndarray,
                     voxel_size: float) -> list[Polygon]:
    """The footprint *polygons* (world xy) minus the plan squares of the removed columns.

    Massing builds plates inside the footprint, so they never stand in a
    column that context took. Returns the polygons of what is left.
    """
    cells = np.argwhere(np.asarray(removed_columns, dtype=bool))
    if not len(cells) or not polygons:
        return list(polygons)
    x0, y0 = float(grid_origin_world[0]), float(grid_origin_world[1])
    size = float(voxel_size)
    squares = shapely.union_all([box(x0 + i * size, y0 + j * size, x0 + (i + 1) * size, y0 + (j + 1) * size)
                                 for i, j in cells])
    left = []
    for polygon in polygons:
        rest = polygon.difference(squares)
        left.extend(part for part in getattr(rest, "geoms", [rest])
                    if isinstance(part, Polygon) and not part.is_empty and part.area > 0)
    return left
