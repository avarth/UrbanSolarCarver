"""Run summary, sky dome and sun path of the local web service."""
import math
import shutil
import subprocess
import sys
import warnings

import pytest

from local_web_test_support import GOLDEN_EPW, write_diagnostic, write_fake_finished_run, write_fake_run
from urbansolarcarver.load_config import build_config_from_mode_starting_values
from urbansolarcarver.local_web_service.run_summary import (
    build_run_summary, build_sky_dome, sun_marker_hours, sun_path_for_config,
)

def test_summary_reads_carving_and_massing_numbers(tmp_path):
    summary = build_run_summary(write_fake_finished_run(tmp_path))
    assert summary.carving.retention_pct == 61.0 and summary.carving.obstruction_fraction_carved is None
    assert (summary.carving.threshold_value, summary.carving.voxels_occupied, summary.carving.voxels_kept,
            summary.carving.voxels_removed) == (3.5, 100, 61, 39)
    assert (summary.carving.carve_above_extra_voxels_removed, summary.carving.slope_limit_extra_voxels_removed) == (4, 2)
    assert summary.massing.floor_area_m2_per_storey == [120.0, 80.0] and summary.massing.total_floor_area_m2 == 200.0
    assert summary.massing.storeys_built == 2 and "envelope_volume_m3" not in summary.massing.model_dump()


def test_summary_carries_the_obstruction_fraction_of_weighted_modes(tmp_path):
    summary = build_run_summary(write_fake_finished_run(tmp_path, obstruction_fraction_carved=0.35))
    assert summary.carving.obstruction_fraction_carved == 0.35


def test_summary_parts_are_none_without_their_stage(tmp_path):
    summary = build_run_summary(tmp_path / "run", envelope_voxel_size=2.0)
    assert summary.carving is None and summary.envelope is None and summary.massing is None


def test_summary_envelope_volume_is_the_voxels_the_envelope_was_meshed_from(tmp_path):
    """R2 5: the envelope part shows its own volume, so it needs only exporting: 50 voxels left after the cleanup, 2 m each side."""
    run = write_fake_finished_run(tmp_path)
    write_diagnostic(run / "exporting", {"voxels_original": 100, "voxels_retained": 50, "mesh_volume_m3": None})
    assert build_run_summary(run, envelope_voxel_size=2.0).envelope.envelope_volume_m3 == 400.0
    assert build_run_summary(run, envelope_voxel_size=None).envelope is None       # the voxel size is not known


def test_summary_envelope_without_massing_and_massing_without_envelope(tmp_path):
    run = write_fake_finished_run(tmp_path)
    assert build_run_summary(run, envelope_voxel_size=2.0).envelope is None and build_run_summary(run).massing is not None
    write_diagnostic(run / "exporting", {"voxels_retained": 50})
    shutil.rmtree(run / "massing")
    summary = build_run_summary(run, envelope_voxel_size=2.0)
    assert summary.envelope is not None and summary.massing is None


def test_summary_massing_needs_both_of_its_files(tmp_path):
    run = write_fake_finished_run(tmp_path)
    (run / "massing" / "plates.json").unlink()
    summary = build_run_summary(run)
    assert summary.massing is None and summary.carving is not None


def test_sky_dome_has_145_patches_or_none(tmp_path):
    assert build_sky_dome(write_fake_run(tmp_path)) is None                         # no patch_weights.npy
    dome = build_sky_dome(write_fake_run(tmp_path / "w", with_patch_weights=True))
    assert len(dome.directions) == len(dome.weights) == len(dome.solid_angles) == 145
    assert all(len(direction) == 3 for direction in dome.directions)
    assert dome.weights[0] == 0.0 and dome.weights[-1] == 1.0
    assert sum(dome.solid_angles) == pytest.approx(2 * 3.14159265, rel=1e-6)


def test_sky_dome_without_a_run_is_none(tmp_path):
    assert build_sky_dome(tmp_path / "run") is None


def test_sun_marker_hours_every_two_hours_or_three_for_long_days():
    assert sun_marker_hours(10, 14) == [10, 12, 14]
    assert sun_marker_hours(8, 16) == [8, 10, 12, 14, 16]       # 8 hours is not longer than 8
    assert sun_marker_hours(8, 18) == [8, 11, 14, 17]


def test_sun_marker_hours_of_a_period_over_midnight_follow_the_hours_of_the_period():
    assert sun_marker_hours(20, 4) == [20, 22, 0, 2, 4]         # 8 hours after the start: every 2 hours
    assert sun_marker_hours(18, 4) == [18, 21, 0, 3]            # 10 hours: every 3 hours
    assert sun_marker_hours(10, 10) == [10]


def golden_config(**changes):
    values = {"mode": "time-based", "max_volume_path": "v.ply", "test_surface_path": "s.ply", "out_dir": "run",
              "epw_path": str(GOLDEN_EPW), "start_month": 12, "start_day": 21, "start_hour": 10,
              "end_month": 12, "end_day": 21, "end_hour": 14}
    return build_config_from_mode_starting_values({**values, **changes})


def test_sun_path_needs_time_based_mode_weather_and_period():
    golden = golden_config()
    path = sun_path_for_config(golden)
    assert len(path.days) == 1 and path.days[0].date == "12-21"
    day = path.days[0]
    assert [m.hour for m in day.markers] == [10, 12, 14] and all(m.vector[2] > 0 for m in day.markers)
    assert len(day.day_path) > len(day.period_path) >= 48 and all(v[2] > 0 for v in day.day_path[1:-1])
    assert day.day_path[0][2] == day.day_path[-1][2] == 0.0                     # both ends on the horizon
    season = golden.model_copy(update={"start_month": 11, "start_day": 1, "end_month": 2, "end_day": 28})
    assert [d.date for d in sun_path_for_config(season).days] == ["11-01", "02-28"]
    assert sun_path_for_config(golden.model_copy(update={"mode": "daylight"})).days == []


def test_sun_path_is_empty_without_a_weather_file_or_period(tmp_path):
    golden = golden_config()
    assert sun_path_for_config(golden.model_copy(update={"epw_path": None})).days == []
    assert sun_path_for_config(golden.model_copy(update={"epw_path": str(tmp_path / "missing.epw")})).days == []
    assert sun_path_for_config(golden.model_copy(update={"start_hour": None})).days == []


def test_sun_path_curves_are_unit_vectors_from_the_east_to_the_west():
    day = sun_path_for_config(golden_config()).days[0]
    for vector in day.day_path + day.period_path + [marker.vector for marker in day.markers]:
        assert sum(component ** 2 for component in vector) == pytest.approx(1.0, abs=1e-5)
    assert day.day_path[0][0] > 0 > day.day_path[-1][0]                 # sunrise in the east (+x), sunset in the west
    assert day.day_path[0][1] < 0 and day.day_path[-1][1] < 0           # the winter sun stays on the south side
    assert day.period_path[0] != day.period_path[-1]


def test_the_stored_north_rotates_the_sun_path():
    unrotated = sun_path_for_config(golden_config()).days[0].markers[1].vector     # 12 h, sun due south
    rotated = sun_path_for_config(golden_config(north_deg=90.0)).days[0].markers[1].vector
    assert unrotated[1] < -0.5 and abs(unrotated[0]) < 0.1
    assert abs(rotated[1]) < 0.1 and abs(rotated[0]) > 0.5


def test_markers_below_the_minimum_altitude_are_left_out():
    day = sun_path_for_config(golden_config(start_hour=2, end_hour=12, min_altitude=10.0)).days[0]
    marker_hours = [marker.hour for marker in day.markers]          # a long day: 2, 5, 8, 11 h
    assert 2 not in marker_hours and 11 in marker_hours
    assert all(marker.vector[2] > 0 for marker in day.markers)


def test_computing_a_sun_path_raises_no_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        sun_path_for_config(golden_config(start_hour=2, end_hour=12, min_altitude=10.0))


def test_importing_the_service_modules_does_not_load_torch():
    code = ("import sys; import urbansolarcarver.local_web_service.score_points, urbansolarcarver.local_web_service.run_summary; "
            "print('torch' in sys.modules)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"


@pytest.fixture
def arctic_epw(tmp_path):
    """The Golden weather file moved to 66 N, 25 E (time zone +2): on 18 June the sun sets just after midnight."""
    lines = GOLDEN_EPW.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    location_fields = lines[0].split(",")
    location_fields[6:9] = ["66.0", "25.0", "2.0"]
    lines[0] = ",".join(location_fields)
    arctic_path = tmp_path / "arctic.epw"
    arctic_path.write_text("".join(lines), encoding="utf-8")
    return arctic_path


def azimuth_degrees(vector):
    return math.degrees(math.atan2(vector[0], vector[1]))      # clockwise from +y, which is north here


def test_a_sunset_after_midnight_still_gives_a_path_from_sunrise_to_sunset(arctic_epw):
    config = golden_config(epw_path=str(arctic_epw), start_month=6, start_day=18, end_month=6, end_day=18)
    day = sun_path_for_config(config).days[0]
    assert day.day_path[0][2] == day.day_path[-1][2] == 0.0 and all(v[2] > 0 for v in day.day_path[1:-1])
    azimuths = [azimuth_degrees(vector) % 360 for vector in day.day_path]
    steps = [(later - earlier) % 360 for earlier, later in zip(azimuths, azimuths[1:])]
    assert all(0 <= step < 10 for step in steps)                               # always clockwise, never back to an earlier sun
    assert sum(steps) < 360                                                      # the path is one turn at most, not a closed loop
    assert azimuths[0] < 10 and azimuths[-1] > 350                             # starts and ends near north, having gone round by the south
    assert [m.hour for m in day.markers] == [10, 12, 14]


def test_analysis_hours_over_midnight_are_the_engines(arctic_epw):
    config = golden_config(epw_path=str(arctic_epw), start_month=6, start_day=18, end_month=6, end_day=18,
                           start_hour=20, end_hour=4, min_altitude=0.0)
    day = sun_path_for_config(config).days[0]
    assert [marker.hour for marker in day.markers] == [20, 22, 0, 2, 4]
    assert len(day.period_path) > 48 and all(vector[2] > 0 for vector in day.period_path)
    first_azimuth, last_azimuth = azimuth_degrees(day.period_path[0]), azimuth_degrees(day.period_path[-1])
    assert abs(first_azimuth - last_azimuth) > 30       # the early morning hours come first, then the evening ones
