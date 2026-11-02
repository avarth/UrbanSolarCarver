"""Irradiance and benefit rays count their patch weight times cos θ to their test surface's normal.

The patch weights are radiation per m² facing the patch (Ladybug's sky matrix), so with the cosine a ray carries the
radiation its surface receives from that direction, as Simulate's solar energy counts it.
"""
import numpy as np
import pytest
import torch

from _epw import BUNDLED_EPW
from urbansolarcarver.mode_registry import MODES
from urbansolarcarver.warp_kernels import dda_backend_available

REQUIRES_WARP_CPU = pytest.mark.skipif(not dda_backend_available(torch.device("cpu")), reason="Warp CPU unavailable")
RES, EXTENT = 20, 40.0          # 2 m voxels
CPU = torch.device("cpu")


def _settings(mode="irradiance", **overrides):
    from urbansolarcarver.load_config import user_config
    from urbansolarcarver.stage_settings import PreprocessingSettings
    values = dict(max_volume_path="unused", test_surface_path="unused", out_dir="unused", mode=mode,
                  voxel_size=2.0, grid_step=2.0, ray_length=200.0, device="cpu")
    if MODES[mode].needs_epw:
        values.update(epw_path=str(BUNDLED_EPW), start_month=1, start_day=1, start_hour=0,
                      end_month=12, end_day=31, end_hour=23)
    values.update(overrides)
    return PreprocessingSettings.from_config(user_config(**values))


def _hoys(settings):
    from urbansolarcarver.sun import sample_period
    return sample_period(settings, steps_per_hour=1)[1] if MODES[settings.mode].needs_period else []


def _cosine_totals(points, normals, settings):
    """Each point's total ray weight by the definition: patch weight / sub-rays x cos θ, over the sub-rays it faces."""
    from urbansolarcarver.carving import sky_patch_ray_set
    from urbansolarcarver.ray_tracing import sky_sub_ray_directions
    rays = sky_patch_ray_set(CPU, np.asarray(points, np.float32), np.asarray(normals, np.float32), settings,
                             _hoys(settings))
    point_ids, w, directions = rays.point_ids.long(), rays.patch_weights[rays.patch_ids].double(), rays.directions
    if rays.sub_rays is not None:
        count = rays.sub_rays.count
        directions = sky_sub_ray_directions(rays.point_ids, rays.patch_ids, rays.sub_rays)
        point_ids, w = point_ids.repeat_interleave(count), w.repeat_interleave(count) / count
    cos = (directions.double() * rays.surface_normals.double()[point_ids]).sum(1).clamp_min(0.0)
    return np.bincount(point_ids.numpy(), weights=(w * cos).numpy(), minlength=len(points))


def _evaluate(occ, points, normals, settings):
    from urbansolarcarver.access_evaluation import test_point_access_evaluation as evaluate
    return evaluate(torch.from_numpy(occ), (0.0, 0.0, 0.0), EXTENT, RES, np.asarray(points, np.float32),
                    np.asarray(normals, np.float32), settings, None, device="cpu")


def test_the_energy_modes_take_the_incidence_term():
    assert {name for name, spec in MODES.items() if spec.incidence} == {"irradiance", "benefit"}


@REQUIRES_WARP_CPU
def test_a_ray_counts_its_weight_times_the_cosine():
    from urbansolarcarver.ray_tracing import trace_and_score_dda
    origin = torch.tensor([[1.0, 20.0, 1.0]])
    direction = torch.tensor([[0.5, 0.0, np.sqrt(3.0) / 2.0]])     # 60° from the facade's normal +x
    normals = torch.tensor([[1.0, 0.0, 0.0]])
    weights = torch.tensor([2.0])

    def total(incidence):
        scores = torch.zeros(RES ** 3, dtype=torch.float32)
        trace_and_score_dda((0.0, 0.0, 0.0), EXTENT, RES, origin, direction, torch.zeros(1, dtype=torch.int32),
                            weights, scores, 200.0, point_ids=torch.zeros(1, dtype=torch.int32),
                            surface_normals=normals, incidence=incidence)
        return scores

    plain, with_cosine = total(False), total(True)
    assert plain.max() == pytest.approx(2.0) and with_cosine.max() == pytest.approx(1.0, rel=1e-6)
    assert torch.equal(plain > 0, with_cosine > 0)


def test_the_cosine_needs_the_surface_normals():
    from urbansolarcarver.ray_tracing import trace_and_score_dda
    with pytest.raises(ValueError, match="incidence needs surface_normals"):
        trace_and_score_dda((0.0, 0.0, 0.0), EXTENT, RES, torch.zeros((1, 3)), torch.tensor([[0.0, 0.0, 1.0]]),
                            torch.zeros(1, dtype=torch.int32), torch.ones(1), torch.zeros(RES ** 3), 200.0,
                            incidence=True)


@pytest.mark.slow
@REQUIRES_WARP_CPU
@pytest.mark.parametrize("rays_per_patch", [1, 4])
def test_accessible_plus_blocked_is_the_cosine_weighted_total(rays_per_patch):
    occ = np.zeros((RES,) * 3, bool)
    occ[8:14, 12:18, 0:9] = True
    points, normals = [[20.0, 10.0, 0.0], [20.0, 10.0, 6.0], [10.0, 30.0, 6.0]], [[0, 0, 1], [0, 1, 0], [1, 0, 0]]
    settings = _settings(rays_per_patch=rays_per_patch)
    result = _evaluate(occ, points, normals, settings)
    total = result.test_point_accessible_weight + result.test_point_blocked_weight
    np.testing.assert_allclose(total, _cosine_totals(points, normals, settings), rtol=1e-5)
    assert (result.test_point_blocked_weight > 0).any()


@REQUIRES_WARP_CPU
def test_daylight_rays_keep_their_patch_weight():
    from urbansolarcarver.carving import sky_patch_ray_set
    rays = sky_patch_ray_set(CPU, np.array([[20.0, 20.0, 0.0]], np.float32), np.array([[0.0, 0.0, 1.0]], np.float32),
                             _settings("daylight"), [])
    assert not rays.incidence


@pytest.mark.slow
@REQUIRES_WARP_CPU
def test_an_open_horizontal_point_receives_the_weather_files_global_radiation():
    """Over a year in Golden, an unobstructed horizontal point's irradiance is within 2 % of the EPW's global
    horizontal radiation (1,620 kWh/m²; the sky matrix gives 1.4 % less). A south facade receives over four times
    a north one."""
    points = [[20.0, 20.0, 0.0], [20.0, 20.0, 10.0], [20.0, 20.0, 10.0]]
    normals = [[0.0, 0.0, 1.0], [0.0, -1.0, 0.0], [0.0, 1.0, 0.0]]   # up, south, north (north is +y)
    result = _evaluate(np.zeros((RES,) * 3, bool), points, normals, _settings())
    up, south, north = result.test_point_accessible_weight
    ghi = sum(float(line.split(",")[13]) for line in BUNDLED_EPW.read_text().splitlines()[8:]) / 1000.0
    assert up == pytest.approx(ghi, rel=0.02)
    assert 4.0 < south / north < 5.0


@pytest.mark.slow
@REQUIRES_WARP_CPU
def test_the_context_test_counts_the_cosine_weighted_total():
    import trimesh
    from urbansolarcarver.carving import sky_patch_ray_set
    from urbansolarcarver.context_geometry import build_blocking_mesh, drop_blocked_sky_sub_rays
    points, normals = np.array([[20.0, 20.0, 0.0], [20.0, 20.0, 6.0]], np.float32), np.array([[0, 0, 1], [0, -1, 0]],
                                                                                             np.float32)
    settings = _settings()
    rays = sky_patch_ray_set(CPU, points, normals, settings, _hoys(settings))
    far_box = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    far_box.apply_translation((900.0, 900.0, 1.0))
    blocking = build_blocking_mesh([far_box], CPU)
    _, drop = drop_blocked_sky_sub_rays(blocking, rays.origins, rays.patch_ids, rays.point_ids, rays.surface_normals,
                                        rays.sub_rays, rays.patch_weights, 200.0, incidence=rays.incidence)
    assert drop.weight_dropped == 0.0
    assert drop.weight_total == pytest.approx(_cosine_totals(points, normals, settings).sum(), rel=1e-5)
