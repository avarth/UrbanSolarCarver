"""One-voxel fins along test surfaces that lie on or inside the max volume.

Every ray skips the voxels its source panel's plane passes through (the
panel's skin). The voxelizer marks every voxel the max volume's surface
passes through as occupied, so a panel lying on the max volume's face, or
inside the max volume, sits in occupied skin voxels. Before the skin rule
only other panels' rays could remove them, and where none reached them
they stood as a one-voxel fin above carved neighbours.

The skin rule: a skin voxel with nothing of the max volume behind it
obstructs the panel like any voxel in front of it; a skin voxel with mass
behind it is the panel's own skin and goes whenever that mass goes.
"""
import numpy as np
import pytest
import torch
import trimesh

from urbansolarcarver.warp_kernels import dda_backend_available
from urbansolarcarver.stage_settings import PreprocessingSettings

WARP_CPU = dda_backend_available(torch.device("cpu"))
BACKENDS = [
    pytest.param("warp", marks=pytest.mark.skipif(not WARP_CPU, reason="Warp CPU unavailable")),
    "fixed_step",
]


def _use_backend(monkeypatch, backend):
    if backend == "fixed_step":
        import urbansolarcarver.carving as carving
        monkeypatch.setattr(carving, "dda_backend_available", lambda device: False)
        monkeypatch.setattr(carving, "_fused_dda", None)


def _vertical_panel_along_x(x_start, x_end, y, facing_positive_y, height=20.0):
    """A vertical quad at the given y, from x_start to x_end, standing on
    z = 0, with its normal along +y or -y."""
    vertices = np.array([
        [x_start, y, 0.0], [x_end, y, 0.0], [x_end, y, height], [x_start, y, height],
    ])
    faces = [[0, 2, 1], [0, 3, 2]] if facing_positive_y else [[0, 1, 2], [0, 2, 3]]
    return trimesh.Trimesh(vertices, faces, process=False)


def _box_grid_and_samples(panels, box_min_y, box_max_y, **config):
    """A 20 x (box_max_y - box_min_y) x 20 m box (x from 0 to 20), 1 m
    voxels, CPU: its grid, the panels' sample points and the config."""
    from urbansolarcarver.load_config import user_config
    from urbansolarcarver.voxelization import voxelize
    from urbansolarcarver.surface_sampling import sample_surface

    max_volume = trimesh.creation.box(extents=(20.0, box_max_y - box_min_y, 20.0))
    max_volume.apply_translation([10.0, (box_min_y + box_max_y) / 2.0, 10.0])
    cfg = user_config(
        max_volume_path="unused", test_surface_path="unused", out_dir="unused",
        voxel_size=1.0, grid_step=1.0, device="cpu", **config,
    )
    settings = PreprocessingSettings.from_config(cfg)
    grid, origin, extent, resolution = voxelize(max_volume, settings, device=torch.device("cpu"))
    points, normals, *_ = sample_surface(trimesh.util.concatenate(panels), settings)
    return grid, origin, extent, resolution, points, normals, cfg


def _row_heights(kept, occupied, origin, cell, x=10.0):
    """{row centre y: kept height above the box base in voxels} for the
    column row through *x*, over the occupied rows."""
    resolution = kept.shape[0]
    i = int(np.floor((x - origin[0]) / cell))
    base_index = int(np.argmax(occupied.any(axis=(0, 1))))
    heights = {}
    for j in np.nonzero(occupied[i].any(axis=1))[0]:
        column = kept[i, j]
        top = resolution - int(np.argmax(column[::-1])) if column.any() else base_index
        heights[round(float(origin[1] + (j + 0.5) * cell), 3)] = top - base_index
    return heights


def _tilted_plane_heights_along_y(panels, box_min_y, box_max_y):
    from urbansolarcarver.carving import carve_with_planes

    grid, origin, extent, resolution, points, normals, cfg = _box_grid_and_samples(
        panels, box_min_y, box_max_y, mode="tilted_plane", tilted_plane_angle_deg=45.0)
    carved, _, _ = carve_with_planes(grid, origin, extent, resolution, points, normals,
                                     PreprocessingSettings.from_config(cfg),
                                     ray_batch_size=cfg.ray_batch_size)
    return _row_heights(carved.numpy().astype(bool), grid.numpy().astype(bool),
                        origin, extent / resolution)


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("facade_y", [0.0, 0.3])
def test_no_fin_in_front_of_a_facade_on_the_max_volume_face(monkeypatch, backend, facade_y):
    """A neighbour's facade on the plot line faces into the max volume
    (box from y = facade_y to 20). In front of it the 45 degree plane rises
    one voxel per metre. The row the facade passes through is a surface
    voxel of the max volume, mostly in front of the facade, with nothing
    behind it; it used to stay at the full 20 m."""
    _use_backend(monkeypatch, backend)
    panels = [_vertical_panel_along_x(0.0, 20.0, facade_y, facing_positive_y=True)]
    heights = _tilted_plane_heights_along_y(panels, facade_y, facade_y + 20.0)
    rows = sorted(heights)
    row_through_facade, row_in_front = rows[0], rows[1]
    assert heights[row_in_front] <= 2
    assert heights[row_through_facade] <= heights[row_in_front] + 1, heights


@pytest.mark.parametrize("backend", BACKENDS)
def test_no_fin_in_a_slot_between_two_facing_facades(monkeypatch, backend):
    """Two existing buildings inside the max volume face each other across
    a 0.7 m slot (facades at y = 9.6 facing +y and y = 10.3 facing -y). Each
    facade's plane carves the other side to about one voxel near the slot.
    The voxel row holding the slot is skin of both facades with mass behind
    each, so neither counts it; it now goes with that mass instead of
    standing at 20 m."""
    _use_backend(monkeypatch, backend)
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


@pytest.mark.parametrize("backend", BACKENDS)
def test_facade_on_the_max_volume_face_obstructed_in_sky_scores(monkeypatch, backend):
    """Daylight scores: the max volume surface voxels in front of a
    neighbour's facade (nothing of the max volume behind them) obstruct
    that facade, so they score. Before the skin rule nothing counted them
    and they scored 0."""
    from urbansolarcarver.carving import carve_with_sky_patch_rays

    _use_backend(monkeypatch, backend)
    panels = [_vertical_panel_along_x(0.0, 20.0, 0.3, facing_positive_y=True)]
    grid, origin, extent, resolution, points, normals, cfg = _box_grid_and_samples(
        panels, 0.3, 20.3, mode="daylight", ray_length=60.0)
    result = carve_with_sky_patch_rays(grid, origin, extent, resolution, points, normals,
                                       PreprocessingSettings.from_config(cfg), None,
                                       ray_batch_size=cfg.ray_batch_size)
    scores = result.raw_voxel_scores.reshape(grid.shape)
    occupied = grid.numpy().astype(bool)
    cell = extent / resolution
    i = int(np.floor((10.0 - origin[0]) / cell))
    j_facade = int(np.floor((0.3 - origin[1]) / cell))
    for z in np.nonzero(occupied[i, j_facade])[0][1:-1]:
        assert scores[i, j_facade, z] > 0.0


# ------------------------------------------------------------------ kernel level
@pytest.mark.skipif(not WARP_CPU, reason="Warp CPU unavailable")
class TestSkinRuleKernels:
    """A 4 x 4 x 4 grid of 1 m voxels; one ray from a surface at y = 1.3
    facing +y, heading +y along the row x = 1, z = 1. The plane crosses
    voxel y = 1 (skin); the voxel behind it is y = 0."""

    res, scale, ray_length = 4, 4.0, 10.0
    origin = torch.tensor([[1.5, 1.3, 1.5]])
    direction = torch.tensor([[0.0, 1.0, 0.0]])
    normal = torch.tensor([[0.0, 1.0, 0.0]])
    point_ids = torch.zeros(1, dtype=torch.int32)

    def _flat(self, y):
        return 1 * self.res * self.res + y * self.res + 1

    def _counts(self, occupancy):
        from urbansolarcarver.ray_tracing import trace_and_count_dda
        counts = torch.zeros(self.res ** 3, dtype=torch.int32)
        trace_and_count_dda((0.0, 0.0, 0.0), self.scale, self.res, self.origin, self.direction,
                            counts, self.ray_length, point_ids=self.point_ids,
                            surface_normals=self.normal, occupancy=occupancy)
        return counts

    def test_skin_counts_only_when_nothing_is_behind_it(self):
        full = torch.ones(self.res ** 3, dtype=torch.uint8)
        hollow_behind = full.clone()
        hollow_behind[self._flat(0)] = 0
        without_rule = self._counts(None)
        with_mass_behind = self._counts(full)
        without_mass_behind = self._counts(hollow_behind)
        for counts in (without_rule, with_mass_behind, without_mass_behind):
            assert counts[self._flat(2)] == 1 and counts[self._flat(3)] == 1
            assert counts[self._flat(0)] == 0
        assert without_rule[self._flat(1)] == 0
        assert with_mass_behind[self._flat(1)] == 0
        assert without_mass_behind[self._flat(1)] == 1

    @pytest.mark.parametrize("dtype", [torch.int32, torch.float32])
    def test_own_skin_takes_the_value_of_the_voxel_behind(self, dtype):
        from urbansolarcarver.ray_tracing import follow_mass_behind_skin_dda
        values = torch.zeros(self.res ** 3, dtype=dtype)
        values[self._flat(0)] = 7
        values[self._flat(3)] = 5
        out = follow_mass_behind_skin_dda(
            (0.0, 0.0, 0.0), self.scale, self.res, self.origin, self.direction,
            self.point_ids, self.normal, torch.ones(self.res ** 3, dtype=torch.uint8),
            values, self.ray_length)
        expected = values.clone()
        expected[self._flat(1)] = 7
        torch.testing.assert_close(out, expected)
        assert values[self._flat(1)] == 0  # input untouched

    def test_skin_with_empty_voxel_behind_keeps_its_value(self):
        from urbansolarcarver.ray_tracing import follow_mass_behind_skin_dda
        occupancy = torch.ones(self.res ** 3, dtype=torch.uint8)
        occupancy[self._flat(0)] = 0
        values = torch.zeros(self.res ** 3, dtype=torch.int32)
        values[self._flat(0)] = 7
        out = follow_mass_behind_skin_dda(
            (0.0, 0.0, 0.0), self.scale, self.res, self.origin, self.direction,
            self.point_ids, self.normal, occupancy, values, self.ray_length)
        assert out[self._flat(1)] == 0

    def test_fixed_step_fallback_classifies_like_the_kernel(self):
        from urbansolarcarver.carving import _split_hits_at_surface
        occupancy = torch.ones(self.res ** 3, dtype=torch.uint8)
        voxels = torch.tensor([[1, 1, 1], [1, 2, 1]])
        origins = self.origin.expand(2, 3)
        normals = self.normal.expand(2, 3)
        counted, skin_flat, behind_flat = _split_hits_at_surface(
            (0.0, 0.0, 0.0), 1.0, self.res, voxels, origins, normals, occupancy)
        assert counted.tolist() == [False, True]
        assert skin_flat.tolist() == [self._flat(1)] and behind_flat.tolist() == [self._flat(0)]
        occupancy[self._flat(0)] = 0
        counted, skin_flat, _ = _split_hits_at_surface(
            (0.0, 0.0, 0.0), 1.0, self.res, voxels, origins, normals, occupancy)
        assert counted.tolist() == [True, True] and skin_flat.numel() == 0
