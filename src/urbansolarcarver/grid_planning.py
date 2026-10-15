"""Voxel grid planning: grid size from the mesh bounds, before any allocation.

``plan_voxel_grid`` computes the cubic grid that
:func:`urbansolarcarver.grid.voxelize_mesh` builds, from the bounding box
alone, and ``check_voxel_grid_budget`` rejects a grid that is too large to
score.  Both are pure and need only numpy, so a client can validate a
request without importing torch or Warp.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Largest grid preprocessing accepts.  The Warp voxelizer alone holds 8 bytes
# per voxel on the device (two int32 counters), and scoring adds a float32
# score per voxel, so 500 million voxels is about 4 GB before scoring starts.
MAX_GRID_VOXELS = 500_000_000


@dataclass(frozen=True)
class VoxelGridPlan:
    """The cubic voxel grid built for a mesh: *resolution* voxels per side
    of *voxel_size* meters, with its minimum corner at *origin*."""
    resolution: int
    voxel_size: float
    origin: np.ndarray
    extent: float

    @property
    def total_voxels(self) -> int:
        return self.resolution ** 3


def plan_voxel_grid(bounds, voxel_size: float, margin_frac: float) -> VoxelGridPlan:
    """Plan the grid for a mesh with axis-aligned *bounds* ``[min, max]``.

    The grid is cubic: its side is the longest side of the bounding box plus
    *margin_frac* of it on each side, rounded up to whole voxels, and it is
    centred on the bounding box.

    Raises ValueError if voxel_size <= 0 or margin_frac < 0.
    """
    if voxel_size <= 0 or margin_frac < 0:
        raise ValueError("plan_voxel_grid: invalid voxel_size or margin_frac")
    bounds_min, bounds_max = np.asarray(bounds, dtype=np.float64)
    longest_side = float(np.max(bounds_max - bounds_min))
    side = longest_side + 2 * longest_side * margin_frac
    resolution = int(np.ceil(side / voxel_size))
    extent = resolution * voxel_size
    origin = (bounds_min + bounds_max) / 2.0 - extent / 2.0
    return VoxelGridPlan(resolution=resolution, voxel_size=float(voxel_size),
                         origin=origin, extent=extent)


def check_voxel_grid_budget(plan: VoxelGridPlan) -> None:
    """Raise ValueError if *plan* has more than MAX_GRID_VOXELS voxels."""
    if plan.total_voxels > MAX_GRID_VOXELS:
        raise ValueError(
            f"The voxel grid would have {plan.resolution}^3 = {plan.total_voxels:,} "
            f"voxels, more than the {MAX_GRID_VOXELS:,} preprocessing can score. "
            f"Increase voxel_size (currently {plan.voxel_size:g} m) or reduce the "
            f"maximum volume's extent."
        )
