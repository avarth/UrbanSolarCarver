"""The sun and shade check (solar_check, check_settings): sky directions and sub-rays, analytic
values of unobstructed and half-obstructed surfaces, sun hours against an
independent ray-box test, test surfaces on and in a mesh, clipping by the
maximum volume, the check of a run, context and terrain, and Ladybug's
incident radiation."""
import json
import math

import numpy as np
import pytest
import torch
import trimesh

from _epw import resolve_epw
from urbansolarcarver.warp_kernels import dda_backend_available

REQUIRES_WARP_CPU = pytest.mark.skipif(not dda_backend_available(torch.device("cpu")),
                                       reason="Warp CPU unavailable")
EPW = resolve_epw()
REQUIRES_EPW = pytest.mark.skipif(not EPW, reason="no EPW file")

UP, EAST = [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]


def _settings(metric, **values):
    from urbansolarcarver.check_settings import CheckSettings
    return CheckSettings(metric=metric, **values)


def _evaluate(metric_or_settings, points, normals, mesh=None, clip_mesh=None, tolerance=0.5, **settings):
    from urbansolarcarver.solar_check import check_directions, evaluate_test_points
    s = metric_or_settings if not isinstance(metric_or_settings, str) else _settings(metric_or_settings, **settings)
    return evaluate_test_points(np.asarray(points, float), np.asarray(normals, float), check_directions(s),
                                mesh, clip_mesh=clip_mesh, surface_tolerance=tolerance, device="cpu")


def _box(lower, upper):
    lower, upper = np.asarray(lower, float), np.asarray(upper, float)
    box = trimesh.creation.box(extents=upper - lower)
    box.apply_translation((lower + upper) / 2.0)
    return box


# --- sky directions and sub-rays -------------------------------------------------------------------------------

@pytest.mark.parametrize("rays", [1, 4, 16])
def test_sky_directions_are_ladybugs_patches_and_each_sub_ray_carries_a_share_of_its_patch(rays):
    from ladybug.viewsphere import ViewSphere, view_sphere
    from urbansolarcarver.solar_check import check_directions
    side = math.isqrt(rays)
    centres = np.array([[v.x, v.y, v.z] for v in view_sphere.tregenza_dome_vectors])
    solid_angles = np.repeat(ViewSphere.TREGENZA_COEFFICIENTS, list(ViewSphere.TREGENZA_PATCHES_PER_ROW) + [1])
    directions = check_directions(_settings("sky_view", rays_per_patch=rays))
    assert directions.sub_side == side
    np.testing.assert_array_equal(directions.patch_ids, np.repeat(np.arange(145), rays))
    np.testing.assert_allclose(directions.directions, np.repeat(centres, rays, axis=0), atol=1e-7)
    # Ladybug rounds its solid angles to 10 digits; the sub-rays of a patch share its value equally.
    np.testing.assert_allclose(directions.values * math.pi * rays, np.repeat(solid_angles, rays), rtol=1e-8)


@REQUIRES_WARP_CPU
def test_sub_rays_of_the_check_are_the_carvings_jittered_directions():
    """A box 2 mm wide 100 m out along one of the carving's sub-rays (sky_patches.sub_ray_directions) takes
    exactly that sub-ray's value from the test point whose index the hash was given: the kernel traced it to
    within 1e-5 rad."""
    from urbansolarcarver.sky_patches import sub_ray_directions, tregenza_patch_cells
    from urbansolarcarver.solar_check import check_directions, evaluate_test_points
    directions = check_directions(_settings("sky_view", rays_per_patch=4))
    # Four test points at one place, so only the point id tells their sub-rays apart; the last is checked.
    points, normals = np.zeros((4, 3)), np.tile(UP, (4, 1))
    point_id = 3
    expected = sub_ray_directions([point_id] * 145, np.arange(145), 2, tregenza_patch_cells())
    assert len(expected) == len(directions.directions) == 580
    origin = np.array([0.0, 0.0, 0.01])           # the default origin offset along the normal
    free = evaluate_test_points(points, normals, directions, device="cpu")
    for slot in (3, 77, 301, 452, 577):           # the lowest row, middle rows and the zenith cap
        box = trimesh.creation.box(extents=[2e-3] * 3)
        box.apply_translation(origin + 100.0 * expected[slot])
        shaded = evaluate_test_points(points, normals, directions, box, device="cpu")
        drop = free[point_id] - shaded[point_id]
        assert drop == pytest.approx(directions.values[slot] * expected[slot, 2] * directions.scale, rel=1e-4)


def _overcast_vertical_share():
    """CIE overcast illuminance on an unobstructed vertical surface over that on a horizontal one:
    (2/3)(pi/4 + 2/3) / (7 pi / 9), the 39.6 % of the vertical sky component."""
    return (2.0 / 3.0) * (math.pi / 4.0 + 2.0 / 3.0) / (7.0 * math.pi / 9.0)


@REQUIRES_WARP_CPU
@pytest.mark.parametrize("rays", [1, 4, 16])
def test_more_sub_rays_keep_the_unobstructed_values(rays):
    points, normals = [[0, 0, 0], [5, 0, 0]], [UP, EAST]
    sky_view = _evaluate("sky_view", points, normals, rays_per_patch=rays)
    overcast = _evaluate("sky_component", points, normals, rays_per_patch=rays)
    cooling = _evaluate("cooling_sky", points, normals, rays_per_patch=rays)
    # Patch centres sum to the normaliser exactly; jittered sub-rays to it on average.
    exact = 1e-4 if rays == 1 else 0.5
    assert sky_view[0] == pytest.approx(100.0, abs=exact)
    assert overcast[0] == pytest.approx(100.0, abs=exact)
    assert cooling[0] == pytest.approx(100.0, abs=exact)
    # Tregenza's patches are 12 degrees apart: a wall's value is within 0.5 of the analytic one at any ray count.
    assert sky_view[1] == pytest.approx(50.0, abs=0.5)
    assert overcast[1] == pytest.approx(100.0 * _overcast_vertical_share(), abs=0.5)
    # The cooling sky is brightest at the zenith, so a wall sees well under half of it.
    assert 10.0 < cooling[1] < 40.0


@REQUIRES_WARP_CPU
def test_sub_rays_see_a_thin_mast_that_patch_centres_miss():
    """A mast 0.3 m wide, 40 m from the point at azimuth 4°: 4° or more from every patch centre's azimuth
    (0, 12, 15, 20, 30 and 60° apart in the rows it rises through), so no centre ray meets it."""
    azimuth = math.radians(4.0)
    centre = 40.0 * np.array([math.sin(azimuth), math.cos(azimuth)])
    mast = _box([centre[0] - 0.15, centre[1] - 0.15, -1.0], [centre[0] + 0.15, centre[1] + 0.15, 100.0])
    blocked = {}
    for rays in (1, 16):
        free = _evaluate("sky_view", [[0, 0, 0]], [UP], rays_per_patch=rays)[0]
        blocked[rays] = 1.0 - _evaluate("sky_view", [[0, 0, 0]], [UP], mast, rays_per_patch=rays)[0] / free
    assert blocked[1] == 0.0
    assert blocked[16] > 0.0


@REQUIRES_WARP_CPU
@pytest.mark.parametrize("height", [5.0, 10.0, 20.0])
def test_sky_view_factor_beside_an_infinite_wall(height):
    """A long wall 10 m away, of height h, rises to an elevation beta = atan(h / 10) from the point.
    Horizontal surface: (1 + cos beta) / 2.  Facade facing the wall: (1 - sin beta) / 2."""
    wall = _box([10.0, -5000.0, 0.0], [12.0, 5000.0, height])
    beta = math.atan2(height, 10.0)
    values = _evaluate("sky_view", [[0, 0, 0], [0, 0, 0]], [UP, EAST], wall, rays_per_patch=9)
    assert values[0] == pytest.approx(100.0 * (1.0 + math.cos(beta)) / 2.0, abs=0.5)
    assert values[1] == pytest.approx(100.0 * (1.0 - math.sin(beta)) / 2.0, abs=0.5)


@REQUIRES_WARP_CPU
def test_a_roof_over_a_point_blocks_its_whole_sky():
    roof = _box([-1000.0, -1000.0, 3.0], [1000.0, 1000.0, 4.0])
    # Patch centres: jittered sub-rays reach down to the horizon and some pass under the roof's edge, 0.17° up.
    assert _evaluate("sky_view", [[0, 0, 0]], [UP], roof, rays_per_patch=1)[0] == 0.0
    assert _evaluate("sky_view", [[0, 0, 0]], [UP], roof, rays_per_patch=4)[0] < 0.01


def _ray_hits_box(origin, directions, lower, upper):
    """Slab test, independent of Warp: which rays from *origin* hit the box."""
    with np.errstate(divide="ignore", invalid="ignore"):
        t1 = (np.asarray(lower) - origin) / directions
        t2 = (np.asarray(upper) - origin) / directions
    t_near = np.nanmax(np.minimum(t1, t2), axis=1)
    t_far = np.nanmin(np.maximum(t1, t2), axis=1)
    return (t_far >= np.maximum(t_near, 0.0)) & (t_far > 0)


@REQUIRES_WARP_CPU
@REQUIRES_EPW
def test_sun_hours_past_a_box_match_an_independent_ray_box_test():
    from urbansolarcarver.solar_check import check_directions
    settings = _settings("sun_hours", epw_path=EPW, start_month=12, start_day=21, start_hour=8,
                         end_month=12, end_day=21, end_hour=16, sun_steps_per_hour=12)
    lower, upper = [-6.0, -20.0, 0.0], [6.0, -8.0, 9.0]          # a block south of the points
    points = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [0.0, -4.0, 2.0]])
    normals = np.array([UP, UP, [0.0, -1.0, 0.0]])
    values = _evaluate(settings, points, normals, _box(lower, upper))
    directions = check_directions(settings)
    suns = directions.directions.astype(float)
    expected = []
    for point, normal in zip(points, normals):
        origin = point + 0.01 * normal
        faces = suns @ normal > 0
        expected.append(np.sum(faces & ~_ray_hits_box(origin, suns, lower, upper)) / 12.0)
    np.testing.assert_allclose(values, expected, atol=1e-9)
    assert 0.0 < values[0] < values[1]     # the block shades the point behind it for part of the day


@REQUIRES_WARP_CPU
@REQUIRES_EPW
@pytest.mark.slow     # a year of sky matrix
def test_solar_energy_on_an_unobstructed_horizontal_surface_is_the_sky_matrix_cosine_sum():
    from urbansolarcarver.sky_patches import compute_EPW_based_weights
    from urbansolarcarver.sun import sample_period
    settings = _settings("solar_energy", epw_path=EPW, start_month=1, start_day=1, start_hour=0,
                         end_month=12, end_day=31, end_hour=23, rays_per_patch=1)
    _datetimes, hoys = sample_period(settings, steps_per_hour=1)
    patch_values = compute_EPW_based_weights("irradiance", EPW, hoys, device=torch.device("cpu")).numpy()
    from ladybug.viewsphere import view_sphere
    z = np.array([v.z for v in view_sphere.tregenza_dome_vectors])
    value = _evaluate(settings, [[0, 0, 0]], [UP])[0]
    assert value == pytest.approx(float(np.sum(patch_values * z)), rel=1e-5)
    # Golden, Colorado gets about 1,800 kWh/m² a year on the horizontal.
    assert 1500.0 < value < 2100.0


# --- test surfaces on and in a mesh, and the clip by the maximum volume ---------------------------------------

@REQUIRES_WARP_CPU
def test_a_facade_of_the_mesh_itself_is_not_shaded_by_it():
    box = _box([0, 0, 0], [10, 10, 10])
    points = [[10.0, 5.0, 5.0], [5.0, 5.0, 10.0]]       # on the east facade and on the roof
    values = _evaluate("sky_view", points, [EAST, UP], box)
    np.testing.assert_allclose(values, _evaluate("sky_view", points, [EAST, UP]), atol=1e-9)


@REQUIRES_WARP_CPU
def test_ground_under_a_mesh_is_shaded_although_it_lies_on_the_mesh():
    """The skin tolerance is for a test surface that faces the way the mesh's surface does, not into the solid."""
    box = _box([0, 0, 0], [10, 10, 10])
    assert _evaluate("sky_view", [[5.0, 5.0, 0.0], [0.3, 5.0, 0.0]], [UP, UP], box, tolerance=1.0).max() == 0.0


@REQUIRES_WARP_CPU
def test_a_mesh_a_little_outside_its_facade_does_not_shade_it_but_a_buried_surface_stays_shaded():
    """A smoothed or voxel envelope lies up to about a voxel outside the facades it was carved around."""
    bulging = _box([0, 0, 0], [10.3, 10, 10])
    facade, buried = [[10.0, 5.0, 5.0]], [[5.0, 5.0, 5.0]]
    open_sky = _evaluate("sky_view", facade, [EAST], rays_per_patch=9)[0]
    # Rays that run inside the 0.3 m skin for more than ten tolerances (cos < 0.3 / 5) stay blocked: at most
    # (0.3 / 5)^2 of the cosine-weighted sky, 0.18 of the facade's 50 %.
    within_skin = _evaluate("sky_view", facade, [EAST], bulging, tolerance=0.5, rays_per_patch=9)[0]
    assert open_sky - 0.18 - 0.02 <= within_skin <= open_sky + 1e-6
    # With no tolerance, the point is inside the mesh and the wall shades it.
    assert _evaluate("sky_view", facade, [EAST], bulging, tolerance=0.0)[0] < 1.0
    assert _evaluate("sky_view", buried, [EAST], bulging, tolerance=0.5)[0] == 0.0


@REQUIRES_WARP_CPU
def test_a_result_mesh_blocks_only_inside_the_maximum_volume():
    max_volume = _box([0, 0, 0], [10, 10, 10])
    beyond = _box([0, 0, 0], [10, 10, 30])      # a result mesh that reaches 20 m above the maximum volume
    point, normal = [[20.0, 5.0, 0.0]], [UP]
    clipped = _evaluate("sky_view", point, normal, beyond, clip_mesh=max_volume)[0]
    assert clipped == pytest.approx(_evaluate("sky_view", point, normal, max_volume)[0], abs=1e-9)
    assert _evaluate("sky_view", point, normal, beyond)[0] < clipped


@REQUIRES_WARP_CPU
def test_a_ground_point_under_a_voxel_overhang_is_shaded_only_by_the_maximum_volume():
    """A voxel envelope reaches up to a voxel past the maximum volume's facade, over the ground beside it."""
    max_volume = _box([0, 0, 0], [10, 10, 20])
    voxel_result = _box([-0.6, -0.6, -0.4], [10.6, 10.6, 20.6])
    point = [[10.3, 5.0, 0.0]]                    # beside the facade, under the overhang
    clipped = _evaluate("sky_view", point, [UP], voxel_result, clip_mesh=max_volume)[0]
    assert clipped == pytest.approx(_evaluate("sky_view", point, [UP], max_volume)[0], abs=0.05)
    assert clipped > 40.0


# --- settings ---------------------------------------------------------------------------------------------------

@pytest.mark.filterwarnings("ignore:mode .* does not use")
def test_check_settings_take_the_modes_metric_and_period_from_a_config():
    from urbansolarcarver.check_settings import CheckSettings, metrics_available
    from urbansolarcarver.load_config import user_config
    common = dict(max_volume_path="unused", test_surface_path="unused", out_dir="unused")
    time_based = user_config(**common, mode="time-based", epw_path="w.epw", start_month=12, start_day=21,
                             start_hour=10, end_month=12, end_day=21, end_hour=14, sun_steps_per_hour=12,
                             rays_per_patch=9)
    settings = CheckSettings.for_config(time_based)
    assert (settings.metric, settings.start_month, settings.end_hour) == ("sun_hours", 12, 14)
    assert time_based.sun_steps_per_hour == 12      # the carving's, left as it is
    assert settings.sun_steps_per_hour == 1
    assert settings.sky_density == "tregenza"
    assert settings.rays_per_patch == 9
    assert CheckSettings.for_config(time_based, sun_steps_per_hour=4).sun_steps_per_hour == 4
    energy = CheckSettings.for_config(time_based, "solar_energy")
    assert energy.time_basis == "standard" and energy.start_month == 12
    daylight = user_config(**common, mode="daylight", epw_path="w.epw")
    assert CheckSettings.for_config(daylight).metric == "sky_component"
    # A daylight project checked for sun hours takes Solar time-based's starting period.
    sun = CheckSettings.for_config(daylight, "sun_hours")
    assert (sun.start_month, sun.start_day, sun.start_hour, sun.end_hour) == (12, 21, 10, 14)
    benefit = user_config(**common, mode="benefit", epw_path="w.epw", start_month=10, start_day=15,
                          start_hour=7, end_month=4, end_day=15, end_hour=19)
    assert CheckSettings.for_config(benefit).metric == "useful_solar_energy"
    assert metrics_available("tilted_plane", has_weather_file=False) == ["sky_view", "sky_component", "cooling_sky"]
    assert metrics_available("irradiance", has_weather_file=True)[0] == "solar_energy"


def test_check_settings_refuse_a_metric_without_its_inputs():
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="weather file"):
        _settings("sun_hours", start_month=1, start_day=1, start_hour=0, end_month=1, end_day=1, end_hour=23)
    with pytest.raises(ValidationError, match="analysis period"):
        _settings("solar_energy", epw_path="w.epw")
    with pytest.raises(ValidationError, match="only valid for sun hours"):
        _settings("solar_energy", epw_path="w.epw", start_month=1, start_day=1, start_hour=0, end_month=1,
                  end_day=1, end_hour=23, time_basis="solar")


# --- a run folder, context and terrain ---------------------------------------------------------------------

@REQUIRES_WARP_CPU
@pytest.mark.slow
def test_check_of_a_run_compares_the_maximum_volume_with_the_envelope_and_the_massing(tmp_path):
    from _stage_scene import daylight_cube_config
    from urbansolarcarver.api import run_pipeline
    from urbansolarcarver.check_settings import CheckSettings
    from urbansolarcarver.solar_check import load_solar_check, simulate_study
    config = daylight_cube_config(tmp_path)
    run_pipeline(config, config.out_dir, produce=("exporting", "massing"))
    result = simulate_study(config.test_surface_path, config.max_volume_path, CheckSettings.for_config(config),
                            run_folder=config.out_dir, out_dir=tmp_path / "run" / "check", voxel_size=config.voxel_size,
                            device="cpu")
    assert list(result.values) == ["open", "max_volume", "envelope", "massing"]
    # The check samples the points the analysis did.
    np.testing.assert_allclose(result.points.points, np.load(tmp_path / "run" / "preprocessing" / "test_points.npy"),
                               atol=1e-6)
    assert result.points.quads.shape == (len(result.points.points), 4, 3)
    # The test surface lies inside the cube: before carving the cube hides its sky, the result opens it.
    assert result.values["max_volume"].max() < result.values["envelope"].mean()
    assert (result.values["envelope"] <= result.values["open"] + 1e-6).all()
    summary = json.loads((tmp_path / "run" / "check" / "check_summary.json").read_text(encoding="utf-8"))
    assert summary["metric"] == "sky_component" and summary["unit"] == "%" and summary["baseline"] == "max_volume"
    envelope = summary["columns"]["envelope"]
    assert envelope["clipped"] and envelope["surface_tolerance_m"] == 1.0 and envelope["mesh"]["size"] > 0
    assert set(envelope["statistics"]) == {"min", "p10", "mean", "max", "mean_change", "share_improved", "share_worse"}
    assert envelope["statistics"]["share_worse"] == 0.0
    assert "mean_change" not in summary["columns"]["max_volume"]["statistics"]
    loaded = load_solar_check(tmp_path / "run" / "check")
    np.testing.assert_allclose(loaded.values["envelope"], result.values["envelope"], rtol=1e-6)
    np.testing.assert_allclose(loaded.points.quads, result.points.quads, atol=1e-4)
    assert set(summary["fingerprints"]["geometries"]) == {"envelope", "massing"}


@REQUIRES_WARP_CPU
def test_context_and_terrain_shade_every_column():
    from urbansolarcarver.check_settings import CheckSettings
    from urbansolarcarver.solar_check import CheckGeometry, solar_check
    ground = trimesh.Trimesh(vertices=[[0, 0, 0], [4, 0, 0], [4, 4, 0], [0, 4, 0]], faces=[[0, 1, 2], [0, 2, 3]])
    box = _box([10, -50, 0], [20, 50, 30])
    building = _box([-20, -50, 0], [-10, 50, 10])
    settings = CheckSettings(metric="sky_view", sample_spacing=1.0)
    alone = solar_check(ground, [CheckGeometry("max_volume", "Building", building)], settings, device="cpu")
    among = solar_check(ground, [CheckGeometry("max_volume", "Building", building)], settings, blocking=[box],
                        device="cpu")
    assert among.values["open"].mean() < alone.values["open"].mean() - 5.0
    np.testing.assert_allclose(among.values["open"] - among.values["max_volume"],
                               alone.values["open"] - alone.values["max_volume"], atol=0.5)
    assert among.summary["blocking_triangles"] == 12


@REQUIRES_WARP_CPU
def test_a_list_of_context_and_terrain_files_is_joined_and_both_block(tmp_path):
    from urbansolarcarver.check_settings import CheckSettings
    from urbansolarcarver.io import save_mesh
    from urbansolarcarver.solar_check import CheckGeometry, solar_check
    point = trimesh.Trimesh(vertices=[[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]], faces=[[0, 1, 2], [0, 2, 3]])
    roof_over_it = _box([-1000, -1000, 30], [1000, 1000, 31])      # terrain-like cover, far above
    wall_east = _box([10, -50, 0], [20, 50, 30])                   # a neighbour
    save_mesh(roof_over_it, str(tmp_path / "terrain.obj"))
    save_mesh(wall_east, str(tmp_path / "context.obj"))
    building = [CheckGeometry("max_volume", "Building", _box([-20, -50, -5], [-10, 50, -1]))]
    # Patch centres, which all meet the cover; jittered sub-rays within 1.7° of the horizon pass under its edge.
    settings = CheckSettings(metric="sky_view", sample_spacing=1.0, rays_per_patch=1)
    free = solar_check(point, building, settings, device="cpu").values["open"]
    context_only = solar_check(point, building, settings, blocking=[tmp_path / "context.obj"], device="cpu")
    both = solar_check(point, building, settings, blocking=[str(tmp_path / "context.obj"), tmp_path / "terrain.obj"],
                       device="cpu")
    assert context_only.values["open"].mean() < free.mean() - 5.0
    assert both.values["open"].max() == 0.0                         # the cover over the point blocks the whole sky
    assert both.summary["blocking_triangles"] == 24
    assert len(both.summary["inputs"]["blocking"]) == 2


# --- one study of Simulate ---------------------------------------------------------------------------------

def _study_files(tmp_path):
    """A 10 m cube as the maximum volume, a wall panel 1 m east of it as the test surface (facing east), a block
    beside that as the context."""
    from urbansolarcarver.io import save_mesh
    save_mesh(_box([0, 0, 0], [10, 10, 10]), str(tmp_path / "max_volume.ply"))
    wall = trimesh.Trimesh(vertices=[[11, 0, 0], [11, 6, 0], [11, 6, 6], [11, 0, 6]], faces=[[0, 1, 2], [0, 2, 3]])
    save_mesh(wall, str(tmp_path / "test_surface.ply"))
    save_mesh(_box([20, -5, 0], [25, 15, 30]), str(tmp_path / "context.ply"))
    return tmp_path / "test_surface.ply", tmp_path / "max_volume.ply", tmp_path / "context.ply"


@pytest.mark.parametrize("rays", [1, 4])
def test_each_sky_patch_carries_the_sum_of_its_slots(rays):
    from urbansolarcarver.sky_patches import tregenza_solid_angles
    from urbansolarcarver.solar_check import check_directions, sky_patch_values
    patch_values = sky_patch_values(check_directions(_settings("sky_view", rays_per_patch=rays)))
    assert np.allclose(patch_values, tregenza_solid_angles() / np.pi)      # sky view: each patch's solid angle over pi


SUN_PERIOD = dict(start_month=12, start_day=21, start_hour=8, end_month=12, end_day=21, end_hour=16)


@REQUIRES_EPW
def test_sun_hours_have_no_sky_patches():
    from urbansolarcarver.solar_check import check_directions, sky_patch_values
    assert sky_patch_values(check_directions(_settings("sun_hours", epw_path=EPW, **SUN_PERIOD))) is None


@REQUIRES_WARP_CPU
def test_simulate_study_without_a_run_has_only_the_maximum_volume(tmp_path):
    from urbansolarcarver.solar_check import SUMMARY_FILE, simulate_study
    surface, max_volume, _context = _study_files(tmp_path)
    result = simulate_study(surface, max_volume, _settings("sky_view", sample_spacing=2.0, rays_per_patch=1),
                            out_dir=tmp_path / "study", device="cpu")
    assert list(result.values) == ["open", "max_volume"]
    assert list(result.summary["columns"]) == ["open", "max_volume"] and result.summary["baseline"] == "max_volume"
    assert result.summary["fingerprints"]["geometries"] == {}
    # The wall faces away from the cube: the cube hides nothing of its sky.
    assert result.values["max_volume"].mean() <= result.values["open"].mean() + 1e-6
    assert (tmp_path / "study" / SUMMARY_FILE).is_file()
    sky = json.loads((tmp_path / "study" / "check_sky.json").read_text(encoding="utf-8"))
    assert len(sky["weights"]) == 145


@REQUIRES_WARP_CPU
@REQUIRES_EPW
def test_a_sun_hours_study_removes_an_earlier_sky_file(tmp_path):
    from urbansolarcarver.solar_check import simulate_study
    surface, max_volume, _context = _study_files(tmp_path)
    (tmp_path / "study").mkdir()
    (tmp_path / "study" / "check_sky.json").write_text('{"weights": []}', encoding="utf-8")
    simulate_study(surface, max_volume, _settings("sun_hours", epw_path=EPW, sample_spacing=2.0, **SUN_PERIOD),
                   out_dir=tmp_path / "study", device="cpu")
    assert not (tmp_path / "study" / "check_sky.json").exists()       # its directions are sun positions


@REQUIRES_WARP_CPU
def test_simulate_study_samples_in_the_maximum_volumes_frame_rounded_to_a_micrometre(tmp_path):
    from urbansolarcarver.solar_check import sample_test_surfaces, simulate_study
    surface, max_volume, _context = _study_files(tmp_path)
    shifted = trimesh.load(str(max_volume))
    shifted.apply_translation([0.1234567, 0.2345674, 0.3])
    shifted.export(str(max_volume))
    settings = _settings("sky_view", sample_spacing=2.0, rays_per_patch=1)
    result = simulate_study(surface, max_volume, settings, out_dir=tmp_path / "study", device="cpu")
    frame = np.round(trimesh.load(str(max_volume)).bounds[0], 6)
    expected = sample_test_surfaces(str(surface), 2.0, frame)
    np.testing.assert_allclose(result.points.points, expected.points, atol=1e-8)


@REQUIRES_WARP_CPU
def test_simulate_study_records_the_fingerprints_and_the_settings_digest(tmp_path):
    import hashlib
    from urbansolarcarver.solar_check import file_fingerprint, simulate_study
    surface, max_volume, context = _study_files(tmp_path)
    settings = _settings("sky_view", sample_spacing=2.0, rays_per_patch=1)
    result = simulate_study(surface, max_volume, settings, context_path=str(context), out_dir=tmp_path / "study",
                            device="cpu")
    saved = json.loads((tmp_path / "study" / "check_summary.json").read_text(encoding="utf-8"))["fingerprints"]
    assert saved == result.summary["fingerprints"]
    assert saved["test_surface"] == file_fingerprint(surface)
    assert saved["max_volume"] == file_fingerprint(max_volume)
    assert saved["context"] == file_fingerprint(context) and saved["context"]["size"] > 0
    assert saved["terrain"] is None and saved["weather"] is None and saved["geometries"] == {}
    # An empty surfaces_from is left out, so the results written before it existed keep their digest.
    assert saved["settings_digest"] == hashlib.sha256(
        json.dumps(settings.model_dump(exclude={"epw_path", "surfaces_from"}), sort_keys=True).encode("utf-8")).hexdigest()
    assert result.summary["inputs"]["blocking"] == [saved["context"]]
    # The digest follows the settings and the context follows the file.
    other = simulate_study(surface, max_volume, _settings("sky_view", sample_spacing=2.0, rays_per_patch=4),
                           out_dir=tmp_path / "other", device="cpu")
    assert other.summary["fingerprints"]["settings_digest"] != saved["settings_digest"]
    assert other.summary["fingerprints"]["context"] is None


def test_the_settings_digest_leaves_out_where_the_weather_file_is():
    from urbansolarcarver.check_settings import settings_digest
    period = dict(start_month=12, start_day=21, start_hour=10, end_month=12, end_day=21, end_hour=14)
    here = settings_digest(_settings("sun_hours", epw_path="C:/a/weather.epw", **period))
    assert here == settings_digest(_settings("sun_hours", epw_path="D:/moved/weather.epw", **period))
    assert here != settings_digest(_settings("sun_hours", epw_path="C:/a/weather.epw", **{**period, "end_hour": 13}))
    assert here != settings_digest(_settings("sun_hours", epw_path="C:/a/weather.epw", surfaces_from=["ground"], **period))


def test_the_sources_of_a_study_are_kept_sorted_and_once_and_unknown_ones_are_refused():
    from pydantic import ValidationError
    assert _settings("sky_view", surfaces_from=["terrain", "context", "terrain"]).surfaces_from == ["context", "terrain"]
    with pytest.raises(ValidationError):
        _settings("sky_view", surfaces_from=["roofs"])


def test_simulate_study_refuses_too_many_points_with_the_spacing_that_fits(tmp_path, monkeypatch):
    from urbansolarcarver import solar_check
    from urbansolarcarver.errors import InputError
    surface, max_volume, _context = _study_files(tmp_path)
    monkeypatch.setattr(solar_check, "MAX_CHECK_POINTS", 100)
    # 36 m² at 0.5 m would be 144 points: 0.6 m fits (100 points).
    with pytest.raises(InputError, match=r"0\.6 m or more") as refused:
        solar_check.simulate_study(surface, max_volume, _settings("sky_view", sample_spacing=0.5),
                                   out_dir=tmp_path / "study", device="cpu")
    assert "144" in str(refused.value) and not (tmp_path / "study").exists()


@REQUIRES_WARP_CPU
def test_a_study_that_samples_the_context_has_points_on_it_and_none_without(tmp_path):
    from urbansolarcarver.solar_check import simulate_study
    surface, max_volume, context = _study_files(tmp_path)
    alone = simulate_study(surface, max_volume, _settings("sky_view", sample_spacing=2.0, rays_per_patch=1),
                           context_path=str(context), out_dir=tmp_path / "alone", device="cpu")
    with_context = simulate_study(surface, max_volume,
                                  _settings("sky_view", sample_spacing=2.0, rays_per_patch=1, surfaces_from=["context"]),
                                  context_path=str(context), out_dir=tmp_path / "with_context", device="cpu")
    points, normals = with_context.points.points, with_context.points.normals
    on_context = points[:, 0] >= 20.0 - 1e-6        # the block is 20 to 25 m in x, the wall at 11 m
    assert not (alone.points.points[:, 0] >= 20.0 - 1e-6).any()
    assert on_context.any() and (~on_context).sum() == len(alone.points.points)
    assert alone.summary["surfaces_from"] == [] and with_context.summary["surfaces_from"] == ["context"]
    # The closed block faces out: the points facing east are on its east side, those facing up on its roof, and the roof sees
    # the whole sky past the block.
    east = on_context & (normals[:, 0] > 0.99)
    roof = on_context & (normals[:, 2] > 0.99)
    assert east.any() and np.allclose(points[east, 0], 25.0)
    assert roof.any() and np.allclose(points[roof, 2], 30.0)
    assert with_context.values["open"][roof].min() > 95.0


@REQUIRES_WARP_CPU
def test_a_study_that_samples_the_ground_has_points_at_the_maximum_volumes_foot_and_its_margin(tmp_path):
    from urbansolarcarver.solar_check import simulate_study
    _surface, max_volume, _context = _study_files(tmp_path)
    result = simulate_study(None, max_volume,
                            _settings("sky_view", sample_spacing=2.0, rays_per_patch=1, surfaces_from=["ground"]),
                            out_dir=tmp_path / "study", device="cpu")
    points = result.points.points
    assert np.allclose(points[:, 2], 0.0) and np.allclose(result.points.normals, [0.0, 0.0, 1.0])
    # The cube is 0 to 10 m: a margin of 20 m makes the ground -20 to 30 m both ways.
    assert points[:, :2].min() == pytest.approx(-20.0, abs=1.0) and points[:, :2].max() == pytest.approx(30.0, abs=1.0)
    assert result.summary["inputs"]["test_surfaces"] is None and result.summary["fingerprints"]["test_surface"] is None


def test_the_ground_margin_is_half_the_longer_side_of_a_large_maximum_volume():
    from urbansolarcarver.solar_check import ground_square
    ground = ground_square(_box([0, 0, 2], [100, 40, 30]))
    # Half of 100 m is 50 m, more than 20 m: the square is 200 m wide, centred on (50, 20).
    assert np.allclose(ground.bounds, [[-50, -80, 2], [150, 120, 2]])
    assert np.allclose(ground.face_normals, [0.0, 0.0, 1.0])


def test_a_terrain_stored_facing_down_is_sampled_facing_up_on_each_of_its_slopes(tmp_path):
    from urbansolarcarver.io import save_mesh
    from urbansolarcarver.solar_check import sample_test_surfaces, study_surfaces
    # A low pyramid of four slopes, wound to face down: one connected part that is not flat.
    hill = trimesh.Trimesh(vertices=[[0, 0, 0], [20, 0, 0], [20, 20, 0], [0, 20, 0], [10, 10, 3]],
                           faces=[[0, 4, 1], [1, 4, 2], [2, 4, 3], [3, 4, 0]])
    assert hill.face_normals[:, 2].max() < 0.0
    save_mesh(hill, str(tmp_path / "terrain.ply"))
    surfaces = study_surfaces(None, ["terrain"], _box([0, 0, 0], [5, 5, 5]), terrain_path=str(tmp_path / "terrain.ply"))
    sampled = sample_test_surfaces(surfaces, 2.0)
    assert len(sampled.points) > 4 * 30 and sampled.normals[:, 2].min() > 0.0


def test_a_study_refuses_a_source_without_its_file_and_a_study_with_nothing_to_sample(tmp_path):
    from urbansolarcarver.errors import InputError
    from urbansolarcarver.solar_check import simulate_study
    surface, max_volume, _context = _study_files(tmp_path)
    for source, named in (("context", "surroundings"), ("terrain", "terrain")):
        with pytest.raises(InputError, match=f"samples the {named}, but there is no {named} file"):
            simulate_study(surface, max_volume, _settings("sky_view", surfaces_from=[source]), out_dir=tmp_path / "study",
                           device="cpu")
    with pytest.raises(InputError, match="no surface to sample"):
        simulate_study(None, max_volume, _settings("sky_view"), out_dir=tmp_path / "study", device="cpu")
    assert not (tmp_path / "study").exists()


# --- Ladybug's incident radiation ------------------------------------------------------------------------------

def _radiance_available():
    try:
        from ladybug_radiance.config import folders
        return folders.radbin_path is not None
    except Exception:
        return False


@REQUIRES_WARP_CPU
@REQUIRES_EPW
@pytest.mark.slow
@pytest.mark.skipif(not _radiance_available(), reason="Radiance is not installed")
def test_solar_energy_matches_ladybugs_incident_radiation_with_one_ray_per_patch(tmp_path):
    """Ladybug's RadiationStudy on the same Tregenza sky matrix with ground reflectance 0: the cosine of
    each patch centre seen past a box, summed; the check with one ray per patch computes the same."""
    from ladybug.wea import Wea
    from ladybug_geometry.geometry3d import Face3D, Mesh3D, Point3D
    from ladybug_radiance.skymatrix import SkyMatrix
    from ladybug_radiance.study.radiation import RadiationStudy
    from urbansolarcarver.weather_file import read_weather_file

    box = _box([0, 0, 0], [12, 8, 15])
    # Sensors: a strip of ground east and south of the box, and the box's south facade.
    ground = [[x, y, 0.0] for x in np.arange(-4.5, 18, 3.0) for y in (-6.5, -2.5, 2.5)]
    facade = [[x, 0.0, z] for x in (2.0, 6.0, 10.0) for z in (2.0, 8.0, 14.0)]
    points = np.array(ground + facade)
    normals = np.array([UP] * len(ground) + [[0.0, -1.0, 0.0]] * len(facade))

    wea = read_weather_file(EPW).solar_irradiance_wea()
    hoys = list(range(0, 2160))          # January to March
    sky = SkyMatrix.from_components(wea.location, wea.direct_normal_irradiance, wea.diffuse_horizontal_irradiance,
                                    hoys=hoys, high_density=False, ground_reflectance=0.0)
    (tmp_path / "sky").mkdir()
    sky.folder = str(tmp_path / "sky")
    half = 0.05
    faces = []
    for p, n in zip(points, normals):
        u = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        v = np.cross(n, u)
        corners = [p - half * u - half * v, p + half * u - half * v, p + half * u + half * v, p - half * u + half * v]
        faces.append([Point3D(*c) for c in corners])
    vertices, indices = [], []
    for quad in faces:
        indices.append(tuple(range(len(vertices), len(vertices) + 4)))
        vertices.extend(quad)
    study_mesh = Mesh3D(vertices, indices)
    context = [Face3D([Point3D(*box.vertices[i]) for i in tri]) for tri in box.faces]
    study = RadiationStudy(sky, study_mesh, context, offset_distance=0.01, sim_folder=str(tmp_path / "study"))
    ladybug = np.array(study.radiation_values)

    settings = _settings("solar_energy", epw_path=EPW, start_month=1, start_day=1, start_hour=0, end_month=3,
                         end_day=31, end_hour=23, rays_per_patch=1)
    sensors = np.array([[c.x, c.y, c.z] for c in study_mesh.face_centroids])
    sensor_normals = np.array([[n.x, n.y, n.z] for n in study_mesh.face_normals])
    np.testing.assert_allclose(sensor_normals, normals, atol=1e-9)
    ours = _evaluate(settings, sensors, sensor_normals, box)
    # The ground under the box gets nothing in both.
    np.testing.assert_allclose(ours, ladybug, rtol=1e-4, atol=1e-3)
