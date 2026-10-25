"""test_point_access_evaluation: per test point, the weight of its rays that
reach no occupied voxel (accessible) and of the others (blocked)."""
import math

import numpy as np
import pytest
import torch

from urbansolarcarver.warp_kernels import dda_backend_available

REQUIRES_WARP_CPU = pytest.mark.skipif(not dda_backend_available(torch.device("cpu")),
                                       reason="Warp CPU unavailable")
RES, EXTENT = 20, 40.0          # 2 m voxels


def _settings(**overrides):
    from urbansolarcarver.load_config import user_config
    from urbansolarcarver.stage_settings import PreprocessingSettings
    values = dict(max_volume_path="unused", test_surface_path="unused", out_dir="unused",
                  mode="daylight", voxel_size=2.0, grid_step=2.0, ray_length=200.0, device="cpu")
    values.update(overrides)
    return PreprocessingSettings.from_config(user_config(**values))


def _evaluate(occ, points, normals, settings=None, point_weights=None):
    from urbansolarcarver.access_evaluation import test_point_access_evaluation as evaluate
    return evaluate(torch.from_numpy(occ), (0.0, 0.0, 0.0), EXTENT, RES,
                    np.asarray(points, np.float32), np.asarray(normals, np.float32),
                    settings or _settings(), point_weights, device="cpu")


def _total_weights(points, normals, settings=None, point_weights=None):
    """Each point's total ray weight, from the rays preprocessing would trace (its sky sub-rays the surface faces)."""
    from urbansolarcarver.carving import sky_patch_ray_set
    from urbansolarcarver.ray_tracing import sky_sub_ray_directions
    rays = sky_patch_ray_set(torch.device("cpu"), np.asarray(points, np.float32),
                             np.asarray(normals, np.float32), settings or _settings(), [], point_weights)
    point_ids, w = rays.point_ids.long(), rays.patch_weights[rays.patch_ids]
    if rays.sub_rays is not None:
        count = rays.sub_rays.count
        directions = sky_sub_ray_directions(rays.point_ids, rays.patch_ids, rays.sub_rays)
        point_ids, w = point_ids.repeat_interleave(count), w.repeat_interleave(count) / count
        w = w * ((directions * rays.surface_normals[point_ids]).sum(1) > 0)
    if point_weights is not None:
        w = w * rays.point_weights[point_ids]
    return np.bincount(point_ids.numpy(), weights=w.numpy(), minlength=len(points))


POINTS = [[20.0, 20.0, 0.0], [5.0, 31.0, 0.0], [39.0, 10.0, 12.0]]
NORMALS = [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [-1.0, 0.0, 0.0]]


@REQUIRES_WARP_CPU
def test_empty_grid_leaves_the_total_weight_accessible():
    result = _evaluate(np.zeros((RES,) * 3, bool), POINTS, NORMALS)
    np.testing.assert_allclose(result.test_point_accessible_weight, _total_weights(POINTS, NORMALS), rtol=1e-5)
    assert not result.test_point_blocked_weight.any()
    # A horizontal point faces the half of the daylight sky that sums to about 1, a facade about half of it.
    assert result.test_point_accessible_weight[0] == pytest.approx(1.0, abs=0.02)
    assert result.weight_unit.startswith("share of the CIE overcast sky")


@REQUIRES_WARP_CPU
def test_a_slab_over_a_point_blocks_it_fully():
    occ = np.zeros((RES,) * 3, bool)
    occ[:, :, 1] = True               # 2-4 m above the ground, over the whole grid
    # Walls 0-4 m high around the grid's edge: rays under 6° pass below the slab's edge.
    occ[[0, -1], :, :2] = True
    occ[:, [0, -1], :2] = True
    result = _evaluate(occ, POINTS[:1], NORMALS[:1])
    assert result.test_point_accessible_weight[0] == 0.0
    assert result.test_point_blocked_weight[0] == pytest.approx(_total_weights(POINTS[:1], NORMALS[:1])[0], rel=1e-5)


@REQUIRES_WARP_CPU
def test_accessible_plus_blocked_is_the_total_with_edge_taper_weights():
    occ = np.zeros((RES,) * 3, bool)
    occ[8:14, 12:18, 0:9] = True
    occ[2:4, 0:12, 0:4] = True        # a wall from y = 0 to 24 m, short of the second point
    point_weights = np.array([1.0, 0.5, 0.25], np.float32)
    result = _evaluate(occ, POINTS, NORMALS, point_weights=point_weights)
    total = result.test_point_accessible_weight + result.test_point_blocked_weight
    np.testing.assert_allclose(total, _total_weights(POINTS, NORMALS, point_weights=point_weights), rtol=1e-5)
    assert (result.test_point_blocked_weight > 0).all() and (result.test_point_accessible_weight > 0).all()


@REQUIRES_WARP_CPU
def test_a_point_is_not_blocked_by_its_own_surface():
    """A facade point on the face of a box, facing out: its own skin and
    the box behind it block nothing."""
    occ = np.zeros((RES,) * 3, bool)
    occ[5:10, 5:15, 0:10] = True      # box from x = 10 to 20 m
    points, normals = [[19.4, 20.0, 9.0], [10.6, 20.0, 9.0]], [[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]]
    result = _evaluate(occ, points, normals)
    assert not result.test_point_blocked_weight.any()


@REQUIRES_WARP_CPU
def test_on_a_carved_grid_the_skin_rule_reads_the_max_volume():
    """A facade voxel left standing in front of carved mass is the point's
    own wall: given the max volume it blocks nothing, while judged on the
    carved grid alone it has nothing behind it and blocks the point."""
    from urbansolarcarver.access_evaluation import test_point_access_evaluation as evaluate
    max_volume = np.zeros((RES,) * 3, bool)
    max_volume[5:10, 5:15, 0:10] = True
    carved = max_volume.copy()
    carved[5:9] = False               # only the one-voxel facade fin at x = 18-20 m stays
    points, normals = np.array([[19.4, 20.0, 9.0]], np.float32), np.array([[1.0, 0.0, 0.0]], np.float32)
    with_max_volume = evaluate(carved, (0.0, 0.0, 0.0), EXTENT, RES, points, normals, _settings(),
                               max_volume=max_volume, device="cpu")
    assert with_max_volume.test_point_blocked_weight[0] == 0.0
    assert _evaluate(carved, points, normals).test_point_blocked_weight[0] > 0.0


@REQUIRES_WARP_CPU
def test_time_based_weights_are_hours_of_sun():
    from _epw import BUNDLED_EPW
    from urbansolarcarver.carving import sun_ray_set
    from urbansolarcarver.sun import sample_period
    settings = _settings(mode="time-based", epw_path=str(BUNDLED_EPW), start_month=12, start_day=21,
                         start_hour=9, end_month=12, end_day=21, end_hour=15, sun_steps_per_hour=4)
    result = _evaluate(np.zeros((RES,) * 3, bool), POINTS[:1], NORMALS[:1], settings)
    rays = sun_ray_set(torch.device("cpu"), np.asarray(POINTS[:1], np.float32),
                       np.asarray(NORMALS[:1], np.float32), settings, sample_period(settings, 4)[0])
    assert result.weight_unit == "h"
    assert result.test_point_accessible_weight[0] == pytest.approx(rays.origins.shape[0] / 4)
    assert 5.0 < result.test_point_accessible_weight[0] <= 6.25


def test_tilted_plane_is_refused():
    from urbansolarcarver.access_evaluation import test_point_access_evaluation as evaluate
    with pytest.raises(ValueError, match="tilted_plane"):
        evaluate(np.zeros((RES,) * 3, bool), (0, 0, 0), EXTENT, RES, np.zeros((1, 3)), np.zeros((1, 3)),
                 _settings(mode="tilted_plane", tilted_plane_angle_deg=45.0))


# ---------------------------------------------------------------------------
# 2D street section: a block 24 m deep and 36 m tall in 3 m voxels, a 40 m
# street with 20 ground receivers every 2 m and an 18 m building across it.
# Rays run in one y slice of the grid (dy = 0), one per degree, weighted for
# the sky view factor of a horizontal receiver in 2D: cos(theta) / 2 per
# radian. The building across the street is not in the grid: its rays are
# left out.
# ---------------------------------------------------------------------------

CELL, BLOCK_DEPTH, BLOCK_HEIGHT, STREET, OPPOSITE_HEIGHT = 3.0, 24.0, 36.0, 40.0, 18.0
SECTION_RES = 12                     # a 36 m cube: the block plus 12 m of street
SECTION_Y = 6                        # the y slice the rays run in


def _street_section():
    """The section's occupancy, its receivers and its rays as (receiver, x, theta, weight)."""
    occ = np.zeros((SECTION_RES,) * 3, dtype=bool)
    occ[:int(BLOCK_DEPTH / CELL), :, :int(BLOCK_HEIGHT / CELL)] = True
    receivers_x = BLOCK_DEPTH + 1.0 + 2.0 * np.arange(20)
    theta = np.radians(np.arange(-89.5, 90.0, 1.0))      # from the zenith, negative toward the block
    weight = np.cos(theta) / 2.0 * np.radians(1.0)
    rays = [(i, x, t, w) for i, x in enumerate(receivers_x) for t, w in zip(theta, weight)
            if not (t > 0 and (BLOCK_DEPTH + STREET - x) / math.tan(t) < OPPOSITE_HEIGHT)]
    return occ, receivers_x, rays


def _section_rays(rays):
    y = (SECTION_Y + 0.5) * CELL
    origins = torch.tensor([[x, y, 0.0] for _, x, _, _ in rays], dtype=torch.float32)
    dirs = torch.tensor([[math.sin(t), 0.0, math.cos(t)] for _, _, t, _ in rays], dtype=torch.float32)
    weights = torch.tensor([w for _, _, _, w in rays], dtype=torch.float32)
    point_ids = torch.tensor([i for i, _, _, _ in rays], dtype=torch.int32)
    return origins, dirs, weights, point_ids


def _summed_section_scores(occ, rays, receivers):
    from urbansolarcarver.ray_tracing import trace_and_score_dda
    origins, dirs, weights, point_ids = _section_rays(rays)
    scores = torch.zeros(SECTION_RES ** 3, dtype=torch.float32)
    trace_and_score_dda((0.0, 0.0, 0.0), SECTION_RES * CELL, SECTION_RES, origins, dirs, torch.arange(len(rays)), weights,
                        scores, 200.0, point_ids=point_ids, surface_normals=torch.tensor([[0.0, 0.0, 1.0]] * receivers),
                        occupancy=torch.from_numpy(occ.reshape(-1).astype(np.uint8)))
    return scores.numpy().reshape((SECTION_RES,) * 3)[:, SECTION_Y, :]


def _carve_share_of_volume(scores, occ, share):
    """Kept section after carving *share* of the occupied voxels, highest
    carve_above cutoff first (ties: higher voxel first)."""
    from urbansolarcarver.column_postprocessing import carve_above_scores
    removal = carve_above_scores(scores[:, None, :], occ[:, None, :])[:, 0, :]
    xs, zs = np.nonzero(occ)
    order = np.lexsort((-zs, -removal[xs, zs]))
    kept = occ.copy()
    n = round(share * len(xs))
    kept[xs[order[:n]], zs[order[:n]]] = False
    return kept


@REQUIRES_WARP_CPU
def test_street_section_sky_view_before_and_after_a_quarter_carved():
    """The mean accessible weight of the receivers is their sky view factor:
    0.546 before carving and 0.619 after carving 25 % of the block's volume
    by summed scores (both from sampling the rays every 5 cm)."""
    from urbansolarcarver.ray_tracing import trace_point_access_dda

    occ3, receivers_x, rays = _street_section()
    occ = occ3[:, SECTION_Y, :]
    origins, dirs, weights, point_ids = _section_rays(rays)

    def mean_sky_view(kept_section):
        grid = np.repeat(kept_section[:, None, :], SECTION_RES, axis=1)
        access = torch.zeros(2 * len(receivers_x), dtype=torch.float64)
        trace_point_access_dda((0.0, 0.0, 0.0), SECTION_RES * CELL, SECTION_RES, origins, dirs, torch.arange(len(rays)),
                               weights, access, 200.0, torch.from_numpy(grid.reshape(-1).astype(np.uint8)), point_ids,
                               surface_normals=torch.tensor([[0.0, 0.0, 1.0]] * len(receivers_x)))
        return float(access[:len(receivers_x)].mean())

    assert mean_sky_view(occ) == pytest.approx(0.5466, abs=0.003)
    kept = _carve_share_of_volume(_summed_section_scores(occ3, rays, len(receivers_x)), occ, 0.25)
    assert mean_sky_view(kept) == pytest.approx(0.6191, abs=0.003)
