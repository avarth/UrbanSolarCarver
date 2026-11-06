"""The units of the voxel scores: each sample point stands for grid_step² of protected surface, so a weighted score is the
sky-patch weight a voxel blocks times that area (kWh for Solar energy and Solar heating, m² of weighted sky for Daylight and
Night cooling), as the time-based score is shaded area times duration (m²·h).

The scene: a horizontal test square of side grid_step, or of a side given (at most 0.5 m), at z = 0, centred under a max
volume box of 0.9 m 10 m above it, which is one 1 m voxel. Every sample point's zenith ray crosses that voxel and no other ray
does (the next Tregenza ring is 6° off the zenith, over 1 m to the side at that height), so the voxel's score is the number of
sample points (with edge taper, the sum of their taper weights) times the zenith patch's weight times grid_step².
"""
import numpy as np
import pytest
import torch
import trimesh

from urbansolarcarver import preprocessing
from urbansolarcarver.load_config import user_config
from urbansolarcarver.mode_registry import MODES
from urbansolarcarver.pydantic_schemas import PreprocessingManifest
from urbansolarcarver.sky_patches import fetch_tregenza_patch_directions

VOXEL_HEIGHT_ABOVE_THE_SQUARE = 10.0


def _write_test_square_under_one_voxel(folder, side):
    """The scene of the module description, with a square of *side* (at most 0.5 m); returns the max volume and test surface
    paths."""
    max_volume = trimesh.creation.box(bounds=[[0.05, 0.05, VOXEL_HEIGHT_ABOVE_THE_SQUARE], [0.95, 0.95, VOXEL_HEIGHT_ABOVE_THE_SQUARE + 0.9]])
    corner = 0.5 - side / 2
    square = trimesh.Trimesh(
        vertices=[[corner, corner, 0.0], [corner + side, corner, 0.0],
                  [corner + side, corner + side, 0.0], [corner, corner + side, 0.0]],
        faces=[[0, 1, 2], [0, 2, 3]])
    max_volume_path, test_surface_path = folder / "max_volume.ply", folder / "test_surface.ply"
    max_volume.export(str(max_volume_path))
    square.export(str(test_surface_path))
    return max_volume_path, test_surface_path


def _occupied_voxel_score_and_zenith_weight(tmp_path, mode, sample_spacing, square_side=None, **settings):
    """The occupied voxel's score, the zenith weight its sample points block (count times the zenith patch's weight) and the
    manifest; the square's side is the sample spacing unless given."""
    # One ray per patch centre: the voxel straight above the square takes exactly the zenith patch's ray.
    settings.setdefault("rays_per_patch", 1)
    folder = tmp_path / f"{mode}_{sample_spacing}"
    folder.mkdir()
    max_volume_path, test_surface_path = _write_test_square_under_one_voxel(folder, square_side or sample_spacing)
    config = user_config(max_volume_path=str(max_volume_path), test_surface_path=str(test_surface_path), out_dir=str(folder / "out"),
                         mode=mode, voxel_size=1.0, grid_step=sample_spacing, device="cpu", **settings)
    result = preprocessing(config, folder / "out")
    manifest = PreprocessingManifest.model_validate_json(result.manifest_path.read_text(encoding="utf-8"))
    occupied = np.load(result.out_dir / manifest.voxel_grid_path).ravel().astype(bool)
    assert occupied.sum() == 1
    scores = np.load(result.out_dir / manifest.scores_path).ravel()
    patch_weights = np.load(result.out_dir / manifest.patch_weights_path)
    zenith = int(torch.argmax(fetch_tregenza_patch_directions(torch.device("cpu"))[:, 2]))
    return float(scores[occupied][0]), manifest.sample_point_count * float(patch_weights[zenith]), manifest


@pytest.mark.parametrize("sample_spacing", [0.5, 0.25])
def test_a_daylight_score_is_the_weighted_sky_it_blocks_times_the_area_of_the_sample_points(tmp_path, sample_spacing):
    score, blocked_weight, manifest = _occupied_voxel_score_and_zenith_weight(tmp_path, "daylight", sample_spacing)
    assert score == pytest.approx(blocked_weight * sample_spacing ** 2, rel=1e-5)
    assert manifest.score_unit == MODES["daylight"].score_unit == "m²"


@pytest.mark.slow
def test_a_solar_energy_score_is_the_kwh_it_blocks(tmp_path, example_epw_path):
    """The zenith patch's weight is the kWh/m² it sends over the period; times the 0.25 m² of each sample point, the kWh blocked."""
    whole_year = dict(start_month=1, start_day=1, start_hour=0, end_month=12, end_day=31, end_hour=23)
    score, blocked_kwh_per_square_metre, manifest = _occupied_voxel_score_and_zenith_weight(
        tmp_path, "irradiance", 0.5, epw_path=str(example_epw_path), **whole_year)
    assert blocked_kwh_per_square_metre > 1.0
    assert score == pytest.approx(blocked_kwh_per_square_metre * 0.25, rel=1e-5)
    assert manifest.score_unit == MODES["irradiance"].score_unit == "kWh"


def test_an_edge_tapered_score_is_the_taper_weight_of_each_sample_point_times_its_area(tmp_path):
    """Edge taper weights each sample point's rays, and the area a point stands for multiplies the result: the voxel's score is
    the sum of the points' taper weights times the zenith patch's weight times grid_step².

    A 0.5 m square sampled every 0.125 m with a 0.2 m taper gives 18 points whose weights run from 0 to 1 (sum 7.25, sum of
    squares 4.4375), so a score without the taper, without the area or with the weight applied twice differs.
    """
    side, spacing, taper = 0.5, 0.125, 0.2
    score, zenith_weight_of_all_points, manifest = _occupied_voxel_score_and_zenith_weight(
        tmp_path, "daylight", spacing, square_side=side, edge_taper=taper)
    zenith_weight = zenith_weight_of_all_points / manifest.sample_point_count
    # The taper weights from the saved points, by their distance to the square's outline (the module's square is centred on
    # x = y = 0.5).
    points = np.load(tmp_path / f"daylight_{spacing}" / "out" / "test_points.npy")
    low, high = 0.5 - side / 2, 0.5 + side / 2
    distance_to_outline = np.minimum.reduce([points[:, 0] - low, high - points[:, 0], points[:, 1] - low, high - points[:, 1]])
    taper_weights = np.clip(distance_to_outline / taper, 0.0, 1.0)
    assert 0.0 < taper_weights.sum() < manifest.sample_point_count     # the taper does lower some points
    assert score == pytest.approx(taper_weights.sum() * zenith_weight * spacing ** 2, rel=1e-5)


def test_every_mode_names_the_unit_of_its_scores():
    assert {name: spec.score_unit for name, spec in MODES.items()} == {
        "time-based": "m²·h", "irradiance": "kWh", "benefit": "kWh", "daylight": "m²", "radiative_cooling": "m²",
        "tilted_plane": "rays",
    }


def test_a_night_cooling_score_is_the_weighted_sky_it_blocks_times_the_area_of_the_sample_points(tmp_path):
    score, blocked_weight, manifest = _occupied_voxel_score_and_zenith_weight(tmp_path, "radiative_cooling", 0.5)
    assert score == pytest.approx(blocked_weight * 0.5 ** 2, rel=1e-5)
    assert manifest.score_unit == "m²"
