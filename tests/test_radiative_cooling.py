"""Night cooling (radiative_cooling): the sky model against values worked out by hand, and a run from test surface to envelope.

Hand values, for dew point T and k = 1.8: x = T / 100, eps = 0.758 + 0.521 x + 0.625 x², deficit = (1 - eps) ^ (1 / (k cos zenith)).
"""
import numpy as np
import pytest
import torch
import trimesh

from urbansolarcarver import exporting, preprocessing, thresholding
from urbansolarcarver.errors import InputError
from urbansolarcarver.load_config import user_config
from urbansolarcarver.sky_patches import (
    compute_radiative_cooling_weights, fetch_tregenza_patch_directions, fetch_tregenza_patch_solid_angles, sky_emissivity_deficit,
)


@pytest.mark.parametrize("dew_point, cos_zenith, deficit", [
    (10.0, 1.0, 0.39004),       # eps 0.81635
    (10.0, 0.5, 0.15213),       # the same sky at 60 degrees from the zenith: twice the path
    (-15.0, 1.0, 0.51803),      # eps 0.69391, the dry end of the fit
    (25.0, 1.0, 0.23307),       # eps 0.92731, the humid end
])
def test_the_emissivity_deficit_at_hand_values(dew_point, cos_zenith, deficit):
    assert float(sky_emissivity_deficit(dew_point, 1.8, cos_zenith)) == pytest.approx(deficit, abs=1e-5)


def test_the_deficit_clamps_the_emissivity_and_the_horizon():
    assert float(sky_emissivity_deficit(60.0, 1.8, 1.0)) == pytest.approx(0.02154, abs=1e-5)    # eps 1.2956 taken as 0.999
    assert float(sky_emissivity_deficit(10.0, 1.8, 0.0)) == 0.0                                  # cos zenith taken as 1e-3


def test_the_patch_weights_are_view_factor_times_deficit_summing_to_one():
    device = torch.device("cpu")
    weights = compute_radiative_cooling_weights(10.0, 1.8, device).numpy().astype(np.float64)
    cos_zenith = fetch_tregenza_patch_directions(device)[:, 2].numpy().astype(np.float64)
    solid_angles = fetch_tregenza_patch_solid_angles(device).numpy().astype(np.float64)
    expected = cos_zenith * solid_angles * sky_emissivity_deficit(10.0, 1.8, cos_zenith)
    np.testing.assert_allclose(weights, expected / expected.sum(), rtol=1e-4)


ROOF = [[-4, -4, 0], [4, -4, 0], [4, 4, 0], [-4, 4, 0]]
WALL = [[-4, -8, 0], [-4, -8, 2], [4, -8, 2], [4, -8, 0]]


def _config_with_test_surface(folder, corners):
    """Night cooling on a 6 m cube of maximum volume 3 m above the ground, with the test surface *corners*."""
    max_volume_path, surface_path = folder / "max_volume.ply", folder / "surface.ply"
    trimesh.creation.box(bounds=[[-3, -3, 3], [3, 3, 9]]).export(str(max_volume_path))
    trimesh.Trimesh(vertices=corners, faces=[[0, 1, 2], [0, 2, 3]], process=False).export(str(surface_path))
    return user_config(max_volume_path=str(max_volume_path), test_surface_path=str(surface_path), out_dir=str(folder / "out"),
                       mode="radiative_cooling", voxel_size=1.0, grid_step=1.0, ray_length=80.0, device="cpu", min_voxels=1,
                       min_face_count=0, dew_point_celsius=10.0, carve_fraction=0.5, carve_above=False)


def _mean_distance_off_the_axis(cells, centre_x, centre_y):
    i, j, _ = np.nonzero(cells)
    return float(np.hypot(i - centre_x, j - centre_y).mean())


@pytest.mark.slow
def test_a_run_carves_the_sky_straight_above_the_roof_first_and_builds_an_envelope(tmp_path):
    config = _config_with_test_surface(tmp_path, ROOF)
    pre = preprocessing(config, tmp_path / "out" / "preprocessing")
    thr = thresholding(pre, config, tmp_path / "out" / "thresholding")
    exporting(thr, config, tmp_path / "out" / "exporting")
    assert (tmp_path / "out" / "exporting" / "manifest.json").is_file()
    occupied = np.load(pre.out_dir / "voxel_grid.npy").astype(bool)
    kept = np.load(thr.mask_path).astype(bool) & occupied
    carved = occupied & ~kept
    assert kept.any() and carved.any()
    i, j, _ = np.nonzero(occupied)
    centre_x, centre_y = i.mean(), j.mean()
    # The zenith counts most, so the voxels over the middle of the roof go first.
    assert _mean_distance_off_the_axis(carved, centre_x, centre_y) < _mean_distance_off_the_axis(kept, centre_x, centre_y)


def test_a_vertical_test_surface_is_refused(tmp_path):
    config = _config_with_test_surface(tmp_path, WALL)
    with pytest.raises(InputError, match="requires a horizontal, upward-facing test surface"):
        preprocessing(config, tmp_path / "out" / "preprocessing")
