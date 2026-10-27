"""The sun and shade check (solar_check, check_settings): sky cells, analytic
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


# --- sky cells -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("side", [1, 2, 3])
def test_sky_cells_cover_the_hemisphere_in_equal_parts_of_each_patch(side):
    from urbansolarcarver.solar_check import sky_cells
    cells = sky_cells("tregenza", side)
    assert len(cells.directions) == 145 * side * side
    assert cells.solid_angles.sum() == pytest.approx(2 * math.pi, rel=1e-12)
    assert len(cells.patch_solid_angles) == 145
    np.testing.assert_allclose(np.bincount(cells.patch_index, weights=cells.solid_angles), cells.patch_solid_angles,
                               rtol=1e-12)
    np.testing.assert_allclose(np.linalg.norm(cells.directions, axis=1), 1.0, rtol=1e-12)
    assert (cells.directions[:, 2] > 0).all()


def test_one_cell_per_patch_is_ladybugs_patch_and_finer_cells_stay_in_their_patch():
    from ladybug.viewsphere import ViewSphere, view_sphere
    from urbansolarcarver.solar_check import sky_cells
    centres = view_sphere.tregenza_dome_vectors
    rows = ViewSphere.TREGENZA_PATCHES_PER_ROW
    coefficients = ViewSphere.TREGENZA_COEFFICIENTS
    one = sky_cells("tregenza", 1)
    np.testing.assert_allclose(one.directions, [[v.x, v.y, v.z] for v in centres], atol=1e-12)
    np.testing.assert_allclose(one.patch_solid_angles, np.repeat(coefficients, list(rows) + [1]), rtol=1e-8)  # Ladybug rounds them to 10 digits
    # The middle cell of a 3 x 3 split lies within half a degree of Ladybug's patch centre.
    three = sky_cells("tregenza", 3)
    middle = three.directions[4::9]
    angle = np.degrees(np.arccos(np.clip(np.sum(middle * one.directions, axis=1), -1.0, 1.0)))
    assert angle[:-1].max() < 0.6


# --- unobstructed and analytic cases ---------------------------------------------------------------------------

def _overcast_vertical_share():
    """CIE overcast illuminance on an unobstructed vertical surface over that on a horizontal one:
    (2/3)(pi/4 + 2/3) / (7 pi / 9), the 39.6 % of the vertical sky component."""
    return (2.0 / 3.0) * (math.pi / 4.0 + 2.0 / 3.0) / (7.0 * math.pi / 9.0)


@REQUIRES_WARP_CPU
@pytest.mark.parametrize("rays", [1, 4, 9])
def test_unobstructed_horizontal_and_vertical_sky_metrics(rays):
    points, normals = [[0, 0, 0], [5, 0, 0]], [UP, EAST]
    sky_view = _evaluate("sky_view", points, normals, rays_per_patch=rays)
    overcast = _evaluate("sky_component", points, normals, rays_per_patch=rays)
    cooling = _evaluate("cooling_sky", points, normals, rays_per_patch=rays)
    assert sky_view[0] == pytest.approx(100.0, abs=1e-4)   # float32 values
    assert overcast[0] == pytest.approx(100.0, abs=1e-4)
    assert cooling[0] == pytest.approx(100.0, abs=1e-4)
    # Tregenza's patches are 12 degrees apart: a wall's value is within 0.25 of the analytic one at any ray count.
    assert sky_view[1] == pytest.approx(50.0, abs=0.25)
    assert overcast[1] == pytest.approx(100.0 * _overcast_vertical_share(), abs=0.25)
    # The cooling sky is brightest at the zenith, so a wall sees well under half of it.
    assert 10.0 < cooling[1] < 40.0


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
    assert _evaluate("sky_view", [[0, 0, 0]], [UP], roof)[0] == 0.0


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
    from urbansolarcarver.solar_check import load_solar_check, run_geometries, solar_check
    config = daylight_cube_config(tmp_path)
    run_pipeline(config, config.out_dir, produce=("exporting", "massing"))
    geometries = run_geometries(config.max_volume_path, config.out_dir, config.voxel_size)
    result = solar_check(config.test_surface_path, geometries, CheckSettings.for_config(config),
                         sampling_frame=geometries[0].mesh.bounds[0], out_dir=tmp_path / "run" / "check", device="cpu")
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
    settings = CheckSettings(metric="sky_view", sample_spacing=1.0)
    free = solar_check(point, building, settings, device="cpu").values["open"]
    context_only = solar_check(point, building, settings, blocking=[tmp_path / "context.obj"], device="cpu")
    both = solar_check(point, building, settings, blocking=[str(tmp_path / "context.obj"), tmp_path / "terrain.obj"],
                       device="cpu")
    assert context_only.values["open"].mean() < free.mean() - 5.0
    assert both.values["open"].max() == 0.0                         # the cover over the point blocks the whole sky
    assert both.summary["blocking_triangles"] == 24
    assert len(both.summary["inputs"]["blocking"]) == 2


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
