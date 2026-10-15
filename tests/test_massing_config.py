"""Massing settings in UserConfig."""
import pytest

from urbansolarcarver.load_config import user_config

BASE = dict(max_volume_path="v.ply", test_surface_path="s.ply", out_dir="out",
            mode="tilted_plane", tilted_plane_angle_deg=45.0, voxel_size=1.0, grid_step=1.0)


def test_defaults():
    cfg = user_config(**BASE)
    assert cfg.ground_floor_height == 5.0
    assert cfg.floor_height == 3.0
    assert cfg.min_plate_dimension == 3.0
    assert cfg.plate_tolerance == 0.2
    assert cfg.plate_stacking == "supported"


def test_coarse_voxels_stay_valid_without_massing():
    # Massing sizes are checked against the preprocessing run's voxel size by
    # the massing stage, so a coarse grid that never runs massing stays valid.
    assert user_config(**dict(BASE, voxel_size=10.0, grid_step=10.0)).voxel_size == 10.0


@pytest.mark.parametrize("name", ["ground_floor_height", "floor_height", "min_plate_dimension"])
def test_sizes_must_be_positive(name):
    with pytest.raises(ValueError, match=name):
        user_config(**dict(BASE, **{name: 0.0}))


@pytest.mark.parametrize("value", [-0.1, 1.5])
def test_tolerance_outside_0_1_is_rejected(value):
    with pytest.raises(ValueError):
        user_config(**dict(BASE, plate_tolerance=value))


def test_stacking_accepts_free_only_besides_supported():
    assert user_config(**dict(BASE, plate_stacking="free")).plate_stacking == "free"
    with pytest.raises(ValueError):
        user_config(**dict(BASE, plate_stacking="stacked"))
