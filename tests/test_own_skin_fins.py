"""One-voxel fins along test surfaces that lie on or inside the max volume.

Every ray skips the voxels its source panel's plane passes through (the
own-skin rule: `_in_front` in raytracer.py, `_front_of_surface` in
carving.py), so a panel never carves those voxels itself. The voxelizer
marks every voxel the max volume's surface passes through as occupied, so
a panel lying on the max volume's face, or inside the max volume, sits in
occupied voxels that only other panels' rays can remove. Where no other
ray reaches them, they stand as a one-voxel fin above carved neighbours.

Reproduction for the own-skin follow-up; the expected failures are lifted
by the fix once its semantics are agreed.
"""
import numpy as np
import pytest
import torch
import trimesh


def _vertical_panel_along_x(x_start, x_end, y, facing_positive_y, height=20.0):
    """A vertical quad at the given y, from x_start to x_end, standing on
    z = 0, with its normal along +y or -y."""
    vertices = np.array([
        [x_start, y, 0.0], [x_end, y, 0.0], [x_end, y, height], [x_start, y, height],
    ])
    faces = [[0, 2, 1], [0, 3, 2]] if facing_positive_y else [[0, 1, 2], [0, 2, 3]]
    return trimesh.Trimesh(vertices, faces, process=False)


def _tilted_plane_heights_along_y(panels, box_min_y, box_max_y, x=10.0):
    """Carve a 20 x (box_max_y - box_min_y) x 20 m box (x from 0 to 20)
    with the 45 degree tilted plane of the given panels, 1 m voxels, CPU.

    Returns {row centre y: carved height above the box base in voxels} for
    the column row through *x*, over the occupied rows.
    """
    from urbansolarcarver.load_config import user_config
    from urbansolarcarver.grid import voxelize, sample_surface
    from urbansolarcarver.carving import carve_with_planes

    max_volume = trimesh.creation.box(extents=(20.0, box_max_y - box_min_y, 20.0))
    max_volume.apply_translation([10.0, (box_min_y + box_max_y) / 2.0, 10.0])
    cfg = user_config(
        max_volume_path="unused", test_surface_path="unused", out_dir="unused",
        mode="tilted_plane", tilted_plane_angle_deg=45.0,
        voxel_size=1.0, grid_step=1.0, device="cpu",
    )
    grid, origin, extent, resolution = voxelize(max_volume, cfg, device=torch.device("cpu"))
    points, normals, *_ = sample_surface(trimesh.util.concatenate(panels), cfg)
    carved, _, _ = carve_with_planes(grid, origin, extent, resolution, points, normals, cfg)

    occupied = grid.numpy().astype(bool)
    kept = carved.numpy().astype(bool)
    cell = extent / resolution
    i = int(np.floor((x - origin[0]) / cell))
    base_index = int(np.argmax(occupied.any(axis=(0, 1))))
    heights = {}
    for j in np.nonzero(occupied[i].any(axis=1))[0]:
        column = kept[i, j]
        top = resolution - int(np.argmax(column[::-1])) if column.any() else base_index
        heights[round(float(origin[1] + (j + 0.5) * cell), 3)] = top - base_index
    return heights


@pytest.mark.xfail(strict=True, reason="own-skin fins: semantics of the fix pending owner approval")
@pytest.mark.parametrize("facade_y", [0.0, 0.3])
def test_no_fin_in_front_of_a_facade_on_the_max_volume_face(facade_y):
    """A neighbour's facade on the plot line faces into the max volume
    (box from y = facade_y to 20). In front of it the 45 degree plane rises
    one voxel per metre. The row the facade passes through is a surface
    voxel of the max volume, mostly in front of the facade; before the fix
    it stays at the full 20 m."""
    panels = [_vertical_panel_along_x(0.0, 20.0, facade_y, facing_positive_y=True)]
    heights = _tilted_plane_heights_along_y(panels, facade_y, facade_y + 20.0)
    rows = sorted(heights)
    row_through_facade, row_in_front = rows[0], rows[1]
    assert heights[row_in_front] <= 2
    assert heights[row_through_facade] <= heights[row_in_front] + 1, heights


@pytest.mark.xfail(strict=True, reason="own-skin fins: semantics of the fix pending owner approval")
def test_no_fin_in_a_slot_between_two_facing_facades():
    """Two existing buildings inside the max volume face each other across
    a 0.7 m slot (facades at y = 9.6 facing +y and y = 10.3 facing -y). Each
    facade's plane carves the other side to about one voxel near the slot.
    The voxel row holding the slot is crossed by both facade planes, so
    neither facade's rays count it; before the fix it stays at 20 m."""
    panels = [
        _vertical_panel_along_x(0.0, 20.0, 9.6, facing_positive_y=True),
        _vertical_panel_along_x(0.0, 20.0, 10.3, facing_positive_y=False),
    ]
    heights = _tilted_plane_heights_along_y(panels, 0.0, 20.0)
    slot_row = min(heights, key=lambda y: abs(y - 9.95))
    rows = sorted(heights)
    k = rows.index(slot_row)
    neighbour_height = max(heights[rows[k - 1]], heights[rows[k + 1]])
    assert neighbour_height <= 2
    assert heights[slot_row] <= neighbour_height + 1, heights
