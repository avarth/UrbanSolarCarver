"""Context and terrain on the max volume's lattice (context_geometry.py): the context voxels, the column rule and the
voxels below the ground."""
import hashlib

import numpy as np
import pytest
import torch
import trimesh

from urbansolarcarver.context_geometry import context_occupancy, remove_context_columns
from urbansolarcarver.grid_planning import plan_voxel_grid
from urbansolarcarver.voxelization import voxelize_solid_warp

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
VOXEL = 1.0


def _box(lo, hi):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    box = trimesh.creation.box(extents=hi - lo)
    box.apply_translation((lo + hi) / 2)
    return box


@pytest.fixture
def cube_grid():
    """A 10 m cube from (0, 0, 0) to (10, 10, 10) voxelized at 1 m: (occupancy uint8, origin, resolution)."""
    cube = _box((0, 0, 0), (10, 10, 10))
    plan = plan_voxel_grid(cube.bounds, VOXEL, 0.2)
    grid = voxelize_solid_warp(cube.vertices, cube.faces, plan.origin, VOXEL, plan.resolution, DEVICE)
    return grid.astype(np.uint8), plan.origin, plan.resolution


def _removal(cube_grid, context):
    occupancy, origin, resolution = cube_grid
    inside = context_occupancy(context.vertices, context.faces, origin, VOXEL, resolution, DEVICE)
    return remove_context_columns(occupancy, inside)


def test_default_voxelization_is_unchanged():
    """The counts and bits recorded before the context options were added to the voxelizer."""
    cube = trimesh.creation.box(extents=(10, 10, 10))
    plan = plan_voxel_grid(cube.bounds, VOXEL, 0.2)
    assert voxelize_solid_warp(cube.vertices, cube.faces, plan.origin, VOXEL, plan.resolution, DEVICE).sum() == 1000
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=4.3)
    sphere.apply_translation([0.3, 0.1, -0.2])
    grid = voxelize_solid_warp(sphere.vertices, sphere.faces, plan.origin, VOXEL, plan.resolution, DEVICE)
    assert grid.sum() == 435
    assert hashlib.sha1(np.packbits(grid).tobytes()).hexdigest() == "fc7c26461226bf35fa00da3f4cfb6450479f06ee"


def test_centre_only_ignores_the_surface_through_rule():
    """A thin slab through voxel centres' gaps: the surface passes through voxels whose centres lie outside it."""
    slab = _box((-3, -3, 4.1), (13, 13, 4.4))
    plan = plan_voxel_grid(_box((0, 0, 0), (10, 10, 10)).bounds, VOXEL, 0.2)
    default = voxelize_solid_warp(slab.vertices, slab.faces, plan.origin, VOXEL, plan.resolution, DEVICE)
    centre = voxelize_solid_warp(slab.vertices, slab.faces, plan.origin, VOXEL, plan.resolution, DEVICE,
                                 centre_only=True)
    assert default.sum() > 0
    assert centre.sum() == 0


def test_context_box_inside_removes_its_whole_columns(cube_grid):
    removal = _removal(cube_grid, _box((4, 4, 4), (6, 6, 6)))
    assert removal.voxels_removed == 4 * 10
    assert removal.removed_columns.sum() == 4
    occupancy, origin, _ = cube_grid
    expected = occupancy.copy()
    i0 = int(round((4 - origin[0]) / VOXEL))
    j0 = int(round((4 - origin[1]) / VOXEL))
    expected[i0:i0 + 2, j0:j0 + 2, :] = 0
    np.testing.assert_array_equal(removal.occupancy, expected)
    assert removal.occupancy.dtype == np.uint8


def test_shared_face_removes_no_site_voxel(cube_grid):
    """A neighbour standing against the cube's +x face (a party wall) removes nothing of the site."""
    removal = _removal(cube_grid, _box((10, 2, 0), (14, 8, 10)))
    assert removal.voxels_removed == 0
    assert not removal.removed_columns.any()


def test_context_much_larger_than_the_grid_voxelizes_correctly(cube_grid):
    """A 1 km slab crossing the cube at z = 4-6 m: its parity rays start outside it, so every column is removed."""
    removal = _removal(cube_grid, _box((-500, -500, 4), (500, 500, 6)))
    occupancy = cube_grid[0]
    footprint = occupancy.any(axis=2)
    assert removal.removed_columns[footprint].all()
    assert removal.voxels_removed == int(occupancy.sum())
    assert removal.occupancy.sum() == 0


def test_context_slab_inside_the_grid_marks_only_its_layers(cube_grid):
    occupancy, origin, resolution = cube_grid
    slab = _box((-500, -500, 4), (500, 500, 6))
    inside = context_occupancy(slab.vertices, slab.faces, origin, VOXEL, resolution, DEVICE)
    k = np.arange(resolution)
    centres_z = origin[2] + (k + 0.5) * VOXEL
    layers = (centres_z > 4) & (centres_z < 6)
    assert inside[:, :, layers].all()
    assert not inside[:, :, ~layers].any()


def test_context_outside_the_grid_changes_nothing(cube_grid):
    removal = _removal(cube_grid, _box((100, 100, 0), (110, 110, 10)))
    assert removal.voxels_removed == 0
    np.testing.assert_array_equal(removal.occupancy, cube_grid[0])
