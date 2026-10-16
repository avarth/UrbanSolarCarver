"""Tilted-plane carving where the test-surface outline turns.

Each sample point casts one ray along its own horizontal normal, so where
two facade panels meet at a convex turn the rays of the two panels diverge.
A column between two diverging rays was crossed by neither and stayed at
full height next to columns carved by the plane: the thin spires and
vertical strips seen on complex block footprints. Extra rays from the
corner now rotate the plane around convex turns.
"""
import numpy as np
import pytest
import torch
import trimesh


def _vertical_panel(start_xy, end_xy, height=10.0):
    """A vertical quad from start_xy to end_xy, standing on z = 0. Its normal
    faces to the right of the start-to-end direction (for (0, 0) -> (-15, 0)
    that is +y)."""
    a = np.array([start_xy[0], start_xy[1], 0.0])
    b = np.array([end_xy[0], end_xy[1], 0.0])
    up = np.array([0.0, 0.0, height])
    vertices = np.array([a, b, b + up, a + up])
    return trimesh.Trimesh(vertices, [[0, 1, 2], [0, 2, 3]], process=False)


def _carved_column_heights(panels, box_min_xy, box_max_xy, angle_deg=45.0):
    """Carve a 20 m tall box (z from 0 to 20) with the tilted plane of the
    given facade panels, voxel size and grid step 1 m, on the CPU.

    Returns the carved height of every column above the box base in voxels
    (0 for columns outside the box), and the column centres in x and y.
    """
    from urbansolarcarver.load_config import user_config
    from urbansolarcarver.grid import voxelize, sample_surface
    from urbansolarcarver.carving import carve_with_planes

    size = np.subtract(box_max_xy, box_min_xy)
    max_volume = trimesh.creation.box(extents=(size[0], size[1], 20.0))
    max_volume.apply_translation([*(np.add(box_min_xy, box_max_xy) / 2.0), 10.0])
    cfg = user_config(
        max_volume_path="unused", test_surface_path="unused", out_dir="unused",
        mode="tilted_plane", tilted_plane_angle_deg=angle_deg,
        voxel_size=1.0, grid_step=1.0, device="cpu",
    )
    grid, origin, extent, resolution = voxelize(max_volume, cfg, device=torch.device("cpu"))
    points, normals, *_ = sample_surface(trimesh.util.concatenate(panels), cfg)
    carved, _, _ = carve_with_planes(grid, origin, extent, resolution, points, normals, cfg)

    occupied = grid.numpy().astype(bool)
    kept = carved.numpy().astype(bool)
    base_index = int(np.argmax(occupied.any(axis=(0, 1))))
    top_kept = resolution - np.argmax(kept[:, :, ::-1], axis=2)
    heights = np.where(kept.any(axis=2), top_kept - base_index, 0)
    cell = extent / resolution
    centres_x = origin[0] + (np.arange(resolution) + 0.5) * cell
    centres_y = origin[1] + (np.arange(resolution) + 0.5) * cell
    return heights, centres_x, centres_y


def _largest_step_between_neighbours(heights, region):
    step_along_x = np.abs(np.diff(heights, axis=0))[region[1:] & region[:-1]]
    step_along_y = np.abs(np.diff(heights, axis=1))[region[:, 1:] & region[:, :-1]]
    return max(step_along_x.max(), step_along_y.max())


@pytest.mark.parametrize("turn_deg", [0.0, 10.0, 25.0])
def test_no_uncarved_columns_in_front_of_a_convex_kink(turn_deg):
    """Two panels meet at x = 0 with a convex turn. In front of both, near
    the turn, the 45 degree plane rises one voxel per metre, so neighbouring
    columns differ by about one voxel. A column left at full height between
    carved neighbours breaks that by ten voxels or more."""
    turn = np.radians(turn_deg)
    panels = [
        _vertical_panel((0.0, 0.0), (-15.0, 0.0)),                                # faces +y
        _vertical_panel((15.0 * np.cos(turn), -15.0 * np.sin(turn)), (0.0, 0.0)),  # turned toward +x
    ]
    heights, centres_x, centres_y = _carved_column_heights(panels, (-20.0, 1.5), (20.0, 31.5))
    near_turn = (np.abs(centres_x)[:, None] <= 8.0) & (centres_y[None, :] <= 18.0) & (heights > 0)
    largest_step = _largest_step_between_neighbours(heights, near_turn)
    assert largest_step <= 2, (
        f"turn {turn_deg} deg: neighbouring columns differ by {largest_step} voxels; "
        f"a column between diverging rays was left uncarved"
    )


def test_plane_rotates_around_a_convex_right_angle_corner():
    """Outside a convex 90 degree corner (panels facing +y and +x, meeting at
    the origin) no panel faces the wedge x > 0, y > 0. The plane rotated
    around the corner caps each column there at its distance from the
    corner (45 degrees: one metre of height per metre of distance)."""
    panels = [
        _vertical_panel((0.0, 0.0), (-15.0, 0.0)),   # faces +y
        _vertical_panel((0.0, -15.0), (0.0, 0.0)),   # faces +x
    ]
    heights, centres_x, centres_y = _carved_column_heights(panels, (1.0, 1.0), (21.0, 21.0))
    distance_to_corner = np.hypot(centres_x[:, None], centres_y[None, :])
    wedge = (heights > 0) & (distance_to_corner <= 15.0)
    assert wedge.sum() > 100
    error = heights[wedge] - distance_to_corner[wedge]
    assert np.abs(error).max() <= 1.5, (
        f"column heights in the corner wedge differ from the distance to the "
        f"corner by up to {np.abs(error).max():.1f} voxels"
    )


def test_concave_corner_is_carved_by_the_two_planes_only():
    """Inside a concave 90 degree corner (panels facing +y and +x, the
    envelope in the quadrant between them) the nearer panel's plane sets
    each column: height = min(x, y). Rays swept around the corner lie above
    both planes and must not lower anything."""
    panels = [
        _vertical_panel((15.0, 0.0), (0.0, 0.0)),    # faces +y
        _vertical_panel((0.0, 0.0), (0.0, 15.0)),    # faces +x
    ]
    heights, centres_x, centres_y = _carved_column_heights(panels, (1.0, 1.0), (14.0, 14.0))
    distance_to_nearer_panel = np.minimum(centres_x[:, None], centres_y[None, :])
    inside = heights > 0
    error = heights[inside] - distance_to_nearer_panel[inside]
    assert np.abs(error).max() <= 1.5
