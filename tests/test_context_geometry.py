"""Context and terrain on the max volume's lattice (context_geometry.py): the context voxels, the column rule and the
voxels below the ground."""
import hashlib

import numpy as np
import pytest
import torch
import trimesh

from urbansolarcarver.context_geometry import (
    context_occupancy, ground_heights, remove_below_ground, remove_context_columns,
)
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


# ---- Terrain: ground heights and the voxels below the ground ----

def _sheet(x0, x1, y0, y1, z_of):
    """An open terrain sheet of two triangles over [x0, x1] x [y0, y1], its corners at the heights z_of(x, y)."""
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    vertices = np.array([(x, y, z_of(x, y)) for x, y in corners], dtype=float)
    return trimesh.Trimesh(vertices=vertices, faces=[[0, 1, 2], [0, 2, 3]], process=False)


def _below_ground(cube_grid, terrain):
    occupancy, origin, resolution = cube_grid
    heights = ground_heights(terrain.vertices, terrain.faces, origin, VOXEL, resolution, DEVICE)
    return heights, remove_below_ground(occupancy, heights, origin, VOXEL)


def _centres(origin, resolution, axis):
    return origin[axis] + (np.arange(resolution) + 0.5) * VOXEL


def test_flat_terrain_at_three_metres_removes_three_layers(cube_grid):
    occupancy, origin, resolution = cube_grid
    heights, (reduced, removed) = _below_ground(cube_grid, _sheet(-50, 50, -50, 50, lambda x, y: 3.0))
    np.testing.assert_allclose(heights, 3.0, atol=1e-5)
    expected = occupancy.copy()
    expected[:, :, _centres(origin, resolution, 2) < 3.0] = 0
    np.testing.assert_array_equal(reduced, expected)
    assert removed == 3 * 100
    assert reduced.dtype == np.uint8


def test_sloping_terrain_keeps_columns_above_ground(cube_grid):
    """A plane rising from z = 0 at x = 0 to z = 6 at x = 10: each column loses only what lies below it."""
    occupancy, origin, resolution = cube_grid
    heights, (reduced, removed) = _below_ground(cube_grid, _sheet(-20, 30, -20, 30, lambda x, y: 0.6 * x))
    cx = _centres(origin, resolution, 0)
    np.testing.assert_allclose(heights, np.broadcast_to(0.6 * cx[:, None], heights.shape), atol=1e-4)
    cz = _centres(origin, resolution, 2)
    expected = occupancy.copy()
    expected[cz[None, None, :] < 0.6 * cx[:, None, None] + np.zeros((1, resolution, 1))] = 0
    np.testing.assert_array_equal(reduced, expected)
    assert removed == int(occupancy.sum() - expected.sum()) > 0
    columns = occupancy.any(axis=2)
    assert (reduced.any(axis=2) == columns).all()  # every column of the cube keeps voxels above the ground


def test_terrain_not_covering_a_column_leaves_it(cube_grid):
    occupancy, origin, resolution = cube_grid
    heights, (reduced, removed) = _below_ground(cube_grid, _sheet(-20, 5, -20, 30, lambda x, y: 4.0))
    cx = _centres(origin, resolution, 0)
    assert np.isnan(heights[cx > 5]).all()
    assert not np.isnan(heights[cx < 5]).any()
    np.testing.assert_array_equal(reduced[cx > 5], occupancy[cx > 5])
    assert removed == 5 * 10 * 4


def test_terrain_far_larger_than_the_grid(cube_grid):
    small = _below_ground(cube_grid, _sheet(-50, 50, -50, 50, lambda x, y: 2.0))
    large = _below_ground(cube_grid, _sheet(-2500, 2500, -2500, 2500, lambda x, y: 2.0))
    np.testing.assert_allclose(small[0], large[0], atol=1e-4)
    np.testing.assert_array_equal(small[1][0], large[1][0])
    assert small[1][1] == large[1][1] == 2 * 100


def test_terrain_takes_the_highest_crossing(cube_grid):
    """Two sheets over each other (an overhang): the ground is the upper one."""
    lower = _sheet(-50, 50, -50, 50, lambda x, y: 1.0)
    upper = _sheet(-50, 50, -50, 50, lambda x, y: 4.0)
    both = trimesh.util.concatenate([lower, upper])
    heights, (_, removed) = _below_ground(cube_grid, both)
    np.testing.assert_allclose(heights, 4.0, atol=1e-5)
    assert removed == 4 * 100


# ---- Review fixes: the column rule over the grid, bodies far from the grid, ties at voxel centres ----

def test_context_above_the_max_volume_removes_the_columns_under_it(cube_grid):
    """A tree crown over part of the site, above the max volume: nothing is built under it."""
    removal = _removal(cube_grid, _box((2, 2, 10.2), (4, 4, 11.9)))
    assert removal.removed_columns.sum() == 4
    assert removal.voxels_removed == 4 * 10


def test_context_below_the_max_volume_removes_the_columns_over_it(cube_grid):
    """A kept low building under a max volume drawn on top of it: to build over it, remove it from the context."""
    removal = _removal(cube_grid, _box((6, 6, -1.8), (8, 8, 0)))
    assert removal.removed_columns.sum() == 4
    assert removal.voxels_removed == 4 * 10


def _open_box(lo, hi, axis):
    box = _box(lo, hi)
    box.update_faces(box.face_normals[:, axis] > -0.5)   # the wall facing -axis missing
    return box


def test_open_bodies_far_from_the_grid_do_not_flip_the_parity_inside_it(cube_grid):
    """Open bodies 500 m away and intact ones beyond the site, along the grid's rows: no context near the site."""
    far = [_open_box((-520, -5, -5), (-510, 15, 15), 0), _box((-720, -5, -5), (-710, 15, 15)), _box((700, -5, -5), (710, 15, 15)),
           _open_box((-5, -520, -5), (15, -510, 15), 1), _box((-5, -720, -5), (15, -710, 15)), _box((-5, 700, -5), (15, 710, 15))]
    assert not far[0].is_watertight and not far[3].is_watertight
    removal = _removal(cube_grid, trimesh.util.concatenate(far))
    assert removal.voxels_removed == 0


def test_many_bodies_along_a_row_do_not_hide_context_inside_the_grid(cube_grid):
    """130 closed boxes in a row before the grid along x and along y (more crossings than a parity ray follows) and a chimney
    inside the site."""
    rows = [_box((-1000 + 6 * k, -5, -5), (-997 + 6 * k, 15, 15)) for k in range(130)]
    rows += [_box((-5, -1000 + 6 * k, -5), (15, -997 + 6 * k, 15)) for k in range(130)]
    removal = _removal(cube_grid, trimesh.util.concatenate([*rows, _box((4, 4, 4), (6, 6, 6))]))
    assert removal.voxels_removed == 4 * 10


@pytest.fixture
def cube_grid_default_margin():
    """The 10 m cube at the default grid margin: voxel centres lie on its faces (whole metres)."""
    cube = _box((0, 0, 0), (10, 10, 10))
    plan = plan_voxel_grid(cube.bounds, VOXEL, 0.01)
    grid = voxelize_solid_warp(cube.vertices, cube.faces, plan.origin, VOXEL, plan.resolution, DEVICE)
    assert np.isclose(plan.origin[0] + 0.5 * VOXEL, 0.0)
    return grid.astype(np.uint8), plan.origin, plan.resolution


def test_party_wall_on_voxel_centres_removes_no_site_voxel(cube_grid_default_margin):
    removal = _removal(cube_grid_default_margin, _box((10, 2, 0), (14, 8, 10)))
    assert removal.voxels_removed == 0


@pytest.mark.parametrize("far_height", [13.3, 51.7, 123.456])
def test_flat_ground_on_voxel_centres_with_high_ground_far_away_removes_nothing(cube_grid_default_margin, far_height):
    """Ground at z = 0 (the bottom voxel centres) in one terrain mesh with higher ground outside the grid: the height read
    from above the terrain's top must not land a hair above the voxel centres."""
    ground = _sheet(-100, 100, -100, 100, lambda x, y: 0.0)
    far = _sheet(500, 510, 500, 510, lambda x, y: far_height)
    _heights, (_reduced, removed) = _below_ground(cube_grid_default_margin, trimesh.util.concatenate([ground, far]))
    assert removed == 0
