"""Run summary, sky dome and sun path of the local web service."""
import json
import math
import shutil
import struct
import warnings

import pytest

from local_web_test_support import (
    GOLDEN_EPW, thresholding_diagnostic, write_diagnostic, write_fake_finished_run, write_fake_finished_run_with_envelope, write_fake_run,
)
from urbansolarcarver.load_config import build_config_from_mode_starting_values
from urbansolarcarver.local_web_service.project_names import ProjectError
from urbansolarcarver.local_web_service.run_summary import (
    build_run_summary, build_sky_dome, sun_marker_hours, sun_path_for_config,
)
from urbansolarcarver.local_web_service.score_points import build_score_points

VOXEL_SIZE = 2.0        # of the fake runs


def score_points_header(blob):
    return json.loads(blob[4:4 + struct.unpack("<I", blob[:4])[0]])


def write_chain_of_two_with_results(store, name):
    """Criterion "1" (100 voxels to decide about, 60 kept) and a new criterion "2" (those 60, 30 kept) after a fake run; the run folder."""
    store.add_criterion(name, "daylight")
    run = write_fake_run(store.open(name))
    write_diagnostic(run / "criteria" / "1" / "thresholding", thresholding_diagnostic(voxels_at_start=100, voxels_kept=60))
    write_fake_run(store.open(name), criterion_id="2", after_criterion_id="1")
    write_diagnostic(run / "criteria" / "2" / "thresholding", thresholding_diagnostic(voxels_at_start=60, voxels_kept=30))
    return run


def test_summary_reads_carving_and_massing_numbers(project_with_inputs):
    store, name = project_with_inputs
    write_fake_finished_run(store.open(name))
    summary = build_run_summary(store, name)
    assert summary.carving.retention_pct == 61.0 and summary.carving.obstruction_fraction_carved is None
    assert (summary.carving.threshold_value, summary.carving.voxels_occupied, summary.carving.voxels_kept,
            summary.carving.voxels_removed) == (3.5, 100, 61, 39)
    assert (summary.carving.carve_above_extra_voxels_removed, summary.carving.slope_limit_extra_voxels_removed) == (4, 2)
    assert summary.massing.floor_area_m2_per_storey == [120.0, 80.0] and summary.massing.total_floor_area_m2 == 200.0
    assert summary.massing.storeys_built == 2 and "envelope_volume_m3" not in summary.massing.model_dump()


def test_summary_carries_the_obstruction_fraction_of_weighted_modes(project_with_inputs):
    store, name = project_with_inputs
    write_fake_finished_run(store.open(name), obstruction_fraction_carved=0.35)
    assert build_run_summary(store, name).carving.obstruction_fraction_carved == 0.35


def test_summary_parts_are_none_without_their_stage(project_with_inputs):
    store, name = project_with_inputs
    summary = build_run_summary(store, name)
    assert summary.carving is None and summary.envelope is None and summary.massing is None and summary.chain is None
    [criterion] = summary.criteria      # the criterion is listed so the app can say it has not run yet
    assert criterion.id == "1" and criterion.carving is None and criterion.voxels_at_start is None and criterion.volume_kept_m3 is None


def test_the_summary_lists_each_criterion_and_the_chain(project_with_inputs):
    store, name = project_with_inputs
    write_chain_of_two_with_results(store, name)
    summary = build_run_summary(store, name)
    first, second = summary.criteria
    entries = store.criteria(name)
    assert [(c.id, c.name, c.colour, c.mode) for c in (first, second)] == [(e.id, e.name, e.colour, "daylight") for e in entries]
    assert (first.voxels_at_start, first.carving.voxels_kept, first.volume_kept_m3) == (100, 60, 60 * VOXEL_SIZE ** 3)
    assert (second.voxels_at_start, second.carving.voxels_kept, second.volume_kept_m3) == (60, 30, 30 * VOXEL_SIZE ** 3)
    assert summary.carving == second.carving        # the carving screen's numbers are those of the last criterion
    assert summary.chain.volume_after_each_m3 == [480.0, 240.0]
    assert summary.chain.share_of_max_volume_kept == pytest.approx(240.0 / (100 * VOXEL_SIZE ** 3))


def test_the_summary_gives_the_volume_each_criterion_removed(project_with_inputs):
    store, name = project_with_inputs
    run = write_chain_of_two_with_results(store, name)
    first, second = build_run_summary(store, name).criteria
    assert first.volume_removed_m3 == (100 - 60) * VOXEL_SIZE ** 3 == 320.0
    assert second.volume_removed_m3 == (60 - 30) * VOXEL_SIZE ** 3 == 240.0
    # unknown without the size of a voxel (no preprocessing manifest) and without thresholding output
    shutil.rmtree(run / "criteria" / "1" / "preprocessing")
    shutil.rmtree(run / "criteria" / "2" / "thresholding")
    first, second = build_run_summary(store, name).criteria
    assert first.volume_removed_m3 is None and first.volume_kept_m3 is None
    assert second.volume_removed_m3 is None and second.voxels_at_start is None


def test_a_bypassed_criterion_is_left_out_of_the_summary(project_with_inputs):
    store, name = project_with_inputs
    write_chain_of_two_with_results(store, name)
    store.update_criterion(name, "2", bypassed=True)
    summary = build_run_summary(store, name)
    assert [criterion.id for criterion in summary.criteria] == ["1"]
    assert summary.carving.voxels_kept == 60 and summary.chain.volume_after_each_m3 == [480.0]


def test_with_every_criterion_bypassed_the_summary_has_no_criteria(project_with_inputs):
    store, name = project_with_inputs
    write_chain_of_two_with_results(store, name)
    store.update_criterion(name, "1", bypassed=True)
    store.update_criterion(name, "2", bypassed=True)
    summary = build_run_summary(store, name)
    assert summary.criteria == [] and summary.carving is None and summary.chain is None


def test_the_share_of_the_max_volume_is_none_when_it_has_no_filled_voxel(project_with_inputs):
    store, name = project_with_inputs
    run = write_fake_run(store.open(name))
    write_diagnostic(run / "criteria" / "1" / "thresholding", {
        **thresholding_diagnostic(voxels_at_start=100, voxels_kept=0), "voxels_at_start": 0, "voxels_occupied": 0,
        "voxels_removed": 0, "retention_pct": 0.0})
    chain = build_run_summary(store, name).chain
    assert chain.volume_after_each_m3 == [0.0] and chain.share_of_max_volume_kept is None


def test_a_criterion_without_results_is_listed_and_the_chain_waits_for_it(project_with_inputs):
    store, name = project_with_inputs
    run = write_chain_of_two_with_results(store, name)
    shutil.rmtree(run / "criteria" / "2")
    summary = build_run_summary(store, name)
    first, second = summary.criteria
    assert first.carving.voxels_kept == 60
    assert second.carving is None and second.voxels_at_start is None and second.volume_kept_m3 is None
    assert summary.carving is None and summary.chain is None        # the last criterion has no results


def test_after_deleting_the_last_criterion_results_fall_back_without_error(project_with_inputs):
    store, name = project_with_inputs
    write_chain_of_two_with_results(store, name)
    store.delete_criterion(name, "2")
    summary = build_run_summary(store, name)
    assert [criterion.id for criterion in summary.criteria] == ["1"]
    assert summary.carving.voxels_kept == 60 and summary.chain.volume_after_each_m3 == [480.0]
    assert score_points_header(build_score_points(store, name))["has_mask"] is True     # the new last criterion's
    # a criterion added since has no results: the summary says what it can, the score layer is not available
    store.add_criterion(name, "daylight")
    summary = build_run_summary(store, name)
    assert [criterion.id for criterion in summary.criteria] == ["1", "3"]
    assert summary.criteria[0].carving is not None and summary.criteria[1].carving is None
    assert summary.carving is None and summary.chain is None
    for build in (build_score_points, build_sky_dome):
        with pytest.raises(ProjectError) as error:
            build(store, name)
        assert error.value.status_code == 404


def test_summary_envelope_volume_is_the_voxels_the_envelope_was_meshed_from(project_with_inputs):
    """R2 5: the envelope part shows its own volume, so it needs only exporting: 50 voxels left after the cleanup, 2 m each side."""
    store, name = project_with_inputs
    run = write_fake_finished_run_with_envelope(store.open(name))
    assert build_run_summary(store, name).envelope.envelope_volume_m3 == 400.0
    (run / "criteria" / "1" / "preprocessing" / "manifest.json").unlink()      # the voxel size the envelope was built with is not known
    assert build_run_summary(store, name).envelope.envelope_volume_m3 is None


def test_summary_envelope_volume_needs_the_exporting_diagnostic(project_with_inputs):
    store, name = project_with_inputs
    run = write_fake_finished_run_with_envelope(store.open(name))
    (run / "exporting" / "diagnostics" / "diagnostic.json").unlink()
    assert build_run_summary(store, name).envelope.envelope_volume_m3 is None


def test_summary_envelope_names_the_mesh_file_its_manifest_names(project_with_inputs):
    """The file on disk decides which envelope is offered and drawn, not the format chosen since (a change while Carving is locked
    is stored without rebuilding it)."""
    store, name = project_with_inputs
    run = write_fake_finished_run_with_envelope(store.open(name))
    assert build_run_summary(store, name).envelope.mesh_file == "export.ply"
    manifest_path = run / "exporting" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(json.dumps({**manifest, "mesh_path": str(run / "exporting" / "export.glb")}), encoding="utf-8")
    assert build_run_summary(store, name).envelope.mesh_file == "export.glb"        # an absolute path: the file's name in the folder
    manifest_path.unlink()
    assert build_run_summary(store, name).envelope is None    # no manifest, no envelope


def test_summary_envelope_without_massing_and_massing_without_envelope(project_with_inputs):
    store, name = project_with_inputs
    write_fake_finished_run(store.open(name))
    assert build_run_summary(store, name).envelope is None and build_run_summary(store, name).massing is not None
    store.create("with_envelope", "daylight")
    run = write_fake_finished_run_with_envelope(store.open("with_envelope"))
    shutil.rmtree(run / "massing")
    summary = build_run_summary(store, "with_envelope")
    assert summary.envelope is not None and summary.massing is None


def test_summary_massing_needs_its_files_and_its_manifest(project_with_inputs):
    store, name = project_with_inputs
    run = write_fake_finished_run(store.open(name))
    (run / "massing" / "plates.json").unlink()
    summary = build_run_summary(store, name)
    assert summary.massing is None and summary.carving is not None
    store.create("without_manifest", "daylight")
    run = write_fake_finished_run(store.open("without_manifest"))
    (run / "massing" / "manifest.json").unlink()
    assert build_run_summary(store, "without_manifest").massing is None


def test_summary_massing_names_the_mesh_file_in_the_chosen_format_its_manifest_names(project_with_inputs):
    store, name = project_with_inputs
    run = write_fake_finished_run(store.open(name))
    assert build_run_summary(store, name).massing.export_mesh_file == "plates.stl"
    manifest_path = run / "massing" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["export_mesh_path"]                # a massing run from before massing wrote the chosen format
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert build_run_summary(store, name).massing.export_mesh_file == "plates.obj"


def test_sky_dome_has_145_patches_or_is_not_available(project_with_inputs):
    store, name = project_with_inputs
    write_fake_run(store.open(name))                                    # no patch_weights.npy
    with pytest.raises(ProjectError) as error:
        build_sky_dome(store, name)
    assert error.value.status_code == 404
    store.create("weighted", "daylight")
    write_fake_run(store.open("weighted"), with_patch_weights=True)
    dome = build_sky_dome(store, "weighted")
    assert len(dome.directions) == len(dome.weights) == len(dome.solid_angles) == 145
    assert all(len(direction) == 3 for direction in dome.directions)
    assert dome.weights[0] == 0.0 and dome.weights[-1] == 1.0
    assert sum(dome.solid_angles) == pytest.approx(2 * 3.14159265, rel=1e-6)


def test_the_sky_dome_defaults_to_the_last_active_criterion_and_can_name_another(project_with_inputs):
    store, name = project_with_inputs
    store.add_criterion(name, "daylight")
    write_fake_run(store.open(name), with_patch_weights=True)           # criterion "1" has patch weights, "2" has none
    write_fake_run(store.open(name), criterion_id="2")
    assert len(build_sky_dome(store, name, "1").directions) == 145
    with pytest.raises(ProjectError):
        build_sky_dome(store, name)
    store.update_criterion(name, "2", bypassed=True)
    assert len(build_sky_dome(store, name).directions) == 145


def test_sky_dome_without_a_run_is_not_available(project_with_inputs):
    store, name = project_with_inputs
    with pytest.raises(ProjectError) as error:
        build_sky_dome(store, name)
    assert error.value.status_code == 404


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
