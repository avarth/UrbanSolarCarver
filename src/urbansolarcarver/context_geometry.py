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
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .voxelization import voxelize_solid_warp
from .warp_kernels import require_dda_backend


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
