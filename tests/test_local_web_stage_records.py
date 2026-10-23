"""Stage records of the local web service: stage status, the choice of stages to run, and the records a run leaves.

The engine is replaced by the fake of local_web_test_support.py, which writes a manifest with a new run_id (and the current
upstream run_id) for each stage it runs, as the real stages do. The fixture project_with_inputs is in conftest.py.
"""
import json

import pytest

from local_web_test_support import (
    ALL_CURRENT, ALL_MISSING, GOLDEN_EPW, box_bytes, change_settings, make_worker, run_and_wait, write_fake_stage_output,
)
from urbansolarcarver.stage_settings import PIPELINE_STAGES
from urbansolarcarver.local_web_service.projects import ProjectStore
from urbansolarcarver.local_web_service.stage_records import (
    choose_stages, envelope_voxel_size, forget_stages, missing_inputs, record_stages, stage_status,
)

@pytest.fixture
def built_project(project_with_inputs):
    """The project after an analysis and a build: every stage current. Returns the store, the name and the worker."""
    store, name = project_with_inputs
    worker = make_worker(store)
    run_and_wait(worker, name, ["exporting", "massing"])
    assert stage_status(store, name) == ALL_CURRENT
    return store, name, worker


# ---- Stage choice across runs ----

def test_analysis_then_build_runs_only_the_missing_stages(project_with_inputs):
    store, name = project_with_inputs
    worker = make_worker(store)
    assert run_and_wait(worker, name, ["thresholding"]).stages == ["preprocessing", "thresholding"]
    assert worker.start(name, ["thresholding"]).status == "up_to_date"
    assert stage_status(store, name) == {
        "preprocessing": "current", "thresholding": "current", "exporting": "missing", "massing": "missing"}
    assert run_and_wait(worker, name, ["exporting", "massing"]).stages == ["exporting", "massing"]
    assert stage_status(store, name) == ALL_CURRENT


def test_threshold_change_after_a_build_marks_envelope_and_massing_out_of_date(built_project):
    store, name, worker = built_project
    change_settings(store, name, carve_fraction=0.3)
    assert stage_status(store, name) == {
        "preprocessing": "current", "thresholding": "out_of_date", "exporting": "out_of_date", "massing": "out_of_date"}
    assert run_and_wait(worker, name, ["thresholding"]).stages == ["thresholding"]
    # exporting and massing keep the output of the old thresholding run, which their manifests name as upstream
    assert stage_status(store, name) == {
        "preprocessing": "current", "thresholding": "current", "exporting": "out_of_date", "massing": "out_of_date"}
    assert run_and_wait(worker, name, ["exporting", "massing"]).stages == ["exporting", "massing"]
    assert stage_status(store, name) == ALL_CURRENT


def _record_runs_with_grid_step(store, name, grid_step):
    """Rewrites every stage record as if the runs had used config.yaml with *grid_step* set (an earlier version stored one)."""
    project_json = store.read_project_json(name)
    for record in project_json.stage_records.values():
        record.config["grid_step"] = grid_step
    store.write_project_json(name, project_json)


def test_a_run_with_a_stored_grid_step_is_out_of_date_only_when_its_spacing_was_not_half_the_voxel_size(built_project):
    """The service drops a stored grid_step, so the engine samples at half the voxel size; a run made with a spacing of half
    the voxel size stays current, one made with another spacing is out of date once."""
    store, name, _worker = built_project
    voxel_size = store.load_project_config(name).voxel_size
    _record_runs_with_grid_step(store, name, voxel_size / 2)
    assert stage_status(store, name) == ALL_CURRENT
    _record_runs_with_grid_step(store, name, voxel_size)
    assert stage_status(store, name) == {
        "preprocessing": "out_of_date", "thresholding": "out_of_date", "exporting": "out_of_date", "massing": "out_of_date"}


def test_floor_height_change_reruns_massing_only(built_project):
    store, name, worker = built_project
    change_settings(store, name, floor_height=4.0)
    assert stage_status(store, name)["massing"] == "out_of_date"
    assert run_and_wait(worker, name, ["exporting", "massing"]).stages == ["massing"]
    assert stage_status(store, name) == ALL_CURRENT


def test_massing_alone_runs_while_the_envelope_is_out_of_date_and_the_envelope_keeps_its_mark(built_project):
    """Review Focus 5 (R2 5): Build massing and Build envelope each run their own stage; the other part keeps its out-of-date mark."""
    store, name, worker = built_project
    change_settings(store, name, carve_fraction=0.3)
    assert run_and_wait(worker, name, ["thresholding"]).stages == ["thresholding"]
    assert run_and_wait(worker, name, ["massing"]).stages == ["massing"]
    assert stage_status(store, name) == {**ALL_CURRENT, "exporting": "out_of_date"}
    change_settings(store, name, floor_height=4.0)
    assert run_and_wait(worker, name, ["exporting"]).stages == ["exporting"]
    assert stage_status(store, name) == {**ALL_CURRENT, "massing": "out_of_date"}


def write_voxel_size_into_preprocessing_manifest(store, name, voxel_size):
    """The fake engine writes no voxel size; the real preprocessing manifest has the one it ran with."""
    manifest_path = store.open(name) / "run" / "preprocessing" / "manifest.json"
    manifest_path.write_text(json.dumps({**json.loads(manifest_path.read_text()), "voxel_size": voxel_size}), encoding="utf-8")


def test_the_envelope_voxel_size_is_the_one_exporting_last_completed_with(built_project):
    store, name, _worker = built_project
    built_voxel_size = store.load_project_config(name).voxel_size
    change_settings(store, name, voxel_size=built_voxel_size * 2)      # not built yet: the envelope on disk has the old voxels
    assert envelope_voxel_size(store, name) == built_voxel_size


def test_without_its_record_the_envelope_voxel_size_comes_from_the_manifest_chain(built_project):
    """A run removes the record of a stage it redoes; meanwhile the envelope on disk is the one its manifests name."""
    store, name, _worker = built_project
    write_voxel_size_into_preprocessing_manifest(store, name, 0.5)
    change_settings(store, name, voxel_size=2.0)
    forget_stages(store, name, ["exporting"])
    assert envelope_voxel_size(store, name) == 0.5


def test_mid_run_with_a_new_voxel_size_the_old_envelope_has_no_voxel_size(built_project):
    """A run with a new voxel size has redone preprocessing and thresholding, not yet exporting: the envelope on disk was built
    on grids that are gone, so its voxel size is not known and its volume is not given."""
    store, name, _worker = built_project
    change_settings(store, name, voxel_size=2.0)
    forget_stages(store, name, PIPELINE_STAGES)
    run_folder = store.open(name) / "run"
    for stage in ("preprocessing", "thresholding"):
        write_fake_stage_output(run_folder, stage)
    write_voxel_size_into_preprocessing_manifest(store, name, 2.0)
    assert envelope_voxel_size(store, name) is None
    write_fake_stage_output(run_folder, "exporting")                 # the run's exporting is done: the chain holds again
    assert envelope_voxel_size(store, name) == 2.0


def test_a_broken_manifest_chain_gives_no_envelope_voxel_size(built_project):
    store, name, _worker = built_project
    write_voxel_size_into_preprocessing_manifest(store, name, 0.5)
    forget_stages(store, name, ["exporting"])
    manifest_path = store.open(name) / "run" / "thresholding" / "manifest.json"
    manifest_path.write_text(json.dumps({**json.loads(manifest_path.read_text()), "upstream_run_id": "another"}), encoding="utf-8")
    assert envelope_voxel_size(store, name) is None


def test_mesh_format_change_marks_the_envelope_and_the_massing_out_of_date_and_each_build_reruns_its_own(built_project):
    """Both write a mesh in the chosen format; the analysis and the carving do not read it."""
    store, name, worker = built_project
    change_settings(store, name, final_mesh_format="obj")
    assert stage_status(store, name) == {**ALL_CURRENT, "exporting": "out_of_date", "massing": "out_of_date"}
    assert run_and_wait(worker, name, ["exporting"]).stages == ["exporting"]
    assert stage_status(store, name) == {**ALL_CURRENT, "massing": "out_of_date"}
    assert run_and_wait(worker, name, ["massing"]).stages == ["massing"]
    assert stage_status(store, name) == ALL_CURRENT


def remove_the_export_mesh_from_the_massing_manifest(store, name):
    """A massing manifest as massing wrote it before it wrote the chosen format: plates.obj only."""
    manifest_path = store.open(name) / "run" / "massing" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["export_mesh_path"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_a_massing_run_from_before_massing_wrote_the_chosen_format_is_out_of_date_for_a_format_other_than_obj(built_project):
    store, name, worker = built_project
    remove_the_export_mesh_from_the_massing_manifest(store, name)
    assert stage_status(store, name) == {**ALL_CURRENT, "massing": "out_of_date"}
    assert choose_stages(store, name, ["exporting", "massing"]).stages == ["massing"]
    change_settings(store, name, final_mesh_format="obj")
    run_and_wait(worker, name, ["exporting", "massing"])
    remove_the_export_mesh_from_the_massing_manifest(store, name)
    assert stage_status(store, name) == ALL_CURRENT                 # its OBJ is the format chosen


def test_upload_after_a_run_starts_again_at_preprocessing(built_project):
    store, name, worker = built_project
    store.add_input(name, "max_volume", "second.ply", box_bytes([30, 0, 5]))
    assert stage_status(store, name) == {stage: "out_of_date" for stage in PIPELINE_STAGES}
    assert run_and_wait(worker, name, ["thresholding"]).stages == ["preprocessing", "thresholding"]
    assert stage_status(store, name) == {
        "preprocessing": "current", "thresholding": "current", "exporting": "out_of_date", "massing": "out_of_date"}


def test_a_voxel_size_change_makes_every_stage_out_of_date(built_project):
    store, name, _worker = built_project
    change_settings(store, name, voxel_size=2.0)
    assert stage_status(store, name) == {stage: "out_of_date" for stage in PIPELINE_STAGES}


def test_a_thresholding_rerun_with_the_same_settings_still_outdates_what_was_built_from_the_old_one(built_project):
    store, name, worker = built_project
    forget_stages(store, name, ["thresholding"])     # e.g. an earlier run of it was cut off
    assert run_and_wait(worker, name, ["thresholding"]).stages == ["thresholding"]
    assert stage_status(store, name) == {
        "preprocessing": "current", "thresholding": "current", "exporting": "out_of_date", "massing": "out_of_date"}


def test_a_build_after_a_threshold_change_reruns_thresholding_and_both_leaves(built_project):
    store, name, worker = built_project
    change_settings(store, name, carve_fraction=0.3)
    assert run_and_wait(worker, name, ["exporting", "massing"]).stages == ["thresholding", "exporting", "massing"]
    assert stage_status(store, name) == ALL_CURRENT


# ---- Status and choice without a run ----

def test_a_new_project_has_every_stage_missing_and_nothing_to_skip(project_with_inputs):
    store, name = project_with_inputs
    assert stage_status(store, name) == ALL_MISSING
    choice = choose_stages(store, name, ["exporting", "massing"])
    assert choice.stages == list(PIPELINE_STAGES)
    assert choice.produce_for_engine == ["exporting", "massing"]
    assert choose_stages(store, name, ["thresholding"]).produce_for_engine == ["thresholding"]


def test_a_stage_without_its_manifest_is_missing_and_its_dependants_out_of_date(built_project):
    store, name, _worker = built_project
    (store.open(name) / "run" / "thresholding" / "manifest.json").unlink()
    assert stage_status(store, name) == {
        "preprocessing": "current", "thresholding": "missing", "exporting": "out_of_date", "massing": "out_of_date"}


def test_a_record_whose_settings_no_longer_build_a_config_is_out_of_date(built_project):
    store, name, _worker = built_project
    project_json = store.read_project_json(name)
    project_json.stage_records["massing"].config["floor_height"] = -3.0     # a value the engine now refuses
    store.write_project_json(name, project_json)
    assert stage_status(store, name) == {**ALL_CURRENT, "massing": "out_of_date"}


def test_a_stage_whose_manifest_is_not_json_is_missing(built_project):
    store, name, _worker = built_project
    (store.open(name) / "run" / "massing" / "manifest.json").write_text("{not json", encoding="utf-8")
    assert stage_status(store, name)["massing"] == "missing"


@pytest.mark.parametrize("field_name", ["max_volume_lowest_z", "max_volume_highest_z"])
def test_a_preprocessing_run_from_before_the_manifest_recorded_the_max_volume_heights_is_out_of_date(built_project, field_name):
    """Massing of such a run starts and ends the floors at the voxel layers, up to a voxel outside the max volume."""
    store, name, _worker = built_project
    manifest_path = store.open(name) / "run" / "preprocessing" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest[field_name]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert stage_status(store, name) == {stage: "out_of_date" for stage in PIPELINE_STAGES}
    assert choose_stages(store, name, ["massing"]).stages == ["preprocessing", "thresholding", "massing"]


def _write_preprocessing_manifest_from_before_it_recorded_the_sample_spacing(store, name):
    """Replaces the preprocessing manifest with one as an earlier version wrote it: every field but grid_step, same run_id.

    It keeps the score unit of today, so that only the sample spacing is compared (a manifest really that old also lacks
    score_unit, which makes a weighted run out of date on its own: see the score unit tests below)."""
    manifest_path = store.open(name) / "run" / "preprocessing" / "manifest.json"
    run_id = json.loads(manifest_path.read_text(encoding="utf-8"))["run_id"]
    old_manifest = {"run_id": run_id, "scores_path": "scores.npy", "scores_kind": "weighted_sum", "shape": [12, 12, 12],
                    "origin": [-6.0, -6.0, -1.0], "voxel_size": 1.0, "mode": "daylight", "voxel_grid_path": "voxel_grid.npy",
                    "patch_weights_path": "patch_weights.npy", "sample_point_count": 36, "footprint_path": "footprint.npy",
                    "max_volume_lowest_z": 0.0, "max_volume_highest_z": 10.0, "score_unit": "m²"}
    manifest_path.write_text(json.dumps(old_manifest), encoding="utf-8")


def _built_at_voxel_size(project_with_inputs, voxel_size):
    store, name = project_with_inputs
    change_settings(store, name, voxel_size=voxel_size)
    worker = make_worker(store)
    run_and_wait(worker, name, ["exporting", "massing"])
    assert stage_status(store, name) == ALL_CURRENT
    return store, name, worker


def test_a_run_from_before_the_manifest_recorded_the_sample_spacing_used_the_old_1_m_default(project_with_inputs):
    """Without grid_step in its config, such a run sampled every 1 m; the next run samples at half the 1 m voxel size, so the
    analysis and everything built on it are out of date once, and the run after brings them back."""
    store, name, worker = _built_at_voxel_size(project_with_inputs, 1.0)
    assert "grid_step" not in store.read_project_json(name).stage_records["preprocessing"].config
    _write_preprocessing_manifest_from_before_it_recorded_the_sample_spacing(store, name)
    assert stage_status(store, name) == {stage: "out_of_date" for stage in PIPELINE_STAGES}
    assert choose_stages(store, name, ["thresholding"]).stages == ["preprocessing", "thresholding"]
    run_and_wait(worker, name, ["exporting", "massing"])
    assert stage_status(store, name) == ALL_CURRENT


def test_a_run_from_before_the_manifest_recorded_the_sample_spacing_stays_current_when_it_used_the_spacing_the_next_run_uses(
        project_with_inputs):
    # At 2 m voxels, half the voxel size is the old 1 m default.
    store, name, _worker = _built_at_voxel_size(project_with_inputs, 2.0)
    _write_preprocessing_manifest_from_before_it_recorded_the_sample_spacing(store, name)
    assert stage_status(store, name) == ALL_CURRENT


def test_a_run_from_before_the_manifest_recorded_the_sample_spacing_with_a_stored_grid_step_compares_that_value(project_with_inputs):
    store, name, _worker = _built_at_voxel_size(project_with_inputs, 1.0)
    _write_preprocessing_manifest_from_before_it_recorded_the_sample_spacing(store, name)
    _record_runs_with_grid_step(store, name, 0.5)          # half the voxel size: what the next run uses
    assert stage_status(store, name) == ALL_CURRENT
    _record_runs_with_grid_step(store, name, 1.0)
    assert stage_status(store, name)["preprocessing"] == "out_of_date"


def test_forgetting_stages_removes_only_their_records(built_project):
    store, name, _worker = built_project
    forget_stages(store, name, ["exporting", "massing"])
    assert sorted(store.read_project_json(name).stage_records) == ["preprocessing", "thresholding"]
    assert stage_status(store, name) == {
        "preprocessing": "current", "thresholding": "current", "exporting": "missing", "massing": "missing"}


def test_recording_stages_stores_settings_revision_and_the_manifest_run_id(project_with_inputs):
    store, name = project_with_inputs
    run_folder = store.open(name) / "run"
    write_fake_stage_output(run_folder, "preprocessing")
    settings = store.read_stored_config(name)
    record_stages(store, name, ["preprocessing"], settings, inputs_revision=7)
    record = store.read_project_json(name).stage_records["preprocessing"]
    assert record.config == settings and record.inputs_revision == 7
    assert record.manifest_run_id == json.loads((run_folder / "preprocessing" / "manifest.json").read_text())["run_id"]


def test_the_status_ignores_a_change_of_device(built_project, tmp_path):
    store, name, _worker = built_project
    other_device_store = ProjectStore(tmp_path / "projects", device="cpu")   # a service on another device saves the settings
    change_settings(other_device_store, name)
    assert store.read_stored_config(name)["device"] == "cpu"
    assert stage_status(store, name) == ALL_CURRENT


# ---- Missing inputs ----

def test_missing_inputs_lists_the_roles_without_a_joined_file(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    assert missing_inputs(store, "p", store.load_project_config("p")) == ["max_volume", "test_surfaces"]
    store.add_input("p", "test_surfaces", "surface.ply", box_bytes([0, 0, 0], extents=(6, 6, 0.1)))
    assert missing_inputs(store, "p", store.load_project_config("p")) == ["max_volume"]


def test_missing_inputs_names_the_weather_file_for_a_mode_that_reads_one(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("p", "time-based")
    assert missing_inputs(store, "p", store.load_project_config("p")) == ["max_volume", "test_surfaces", "weather"]
    store.add_input("p", "weather", "weather.epw", GOLDEN_EPW.read_bytes())
    assert missing_inputs(store, "p", store.load_project_config("p")) == ["max_volume", "test_surfaces"]


def _rewrite_preprocessing_manifest(store, name, **changes):
    """Changes fields of the preprocessing manifest on disk; a value of None removes the field, as an earlier version wrote it."""
    manifest_path = store.open(name) / "run" / "preprocessing" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for field, value in changes.items():
        if value is None:
            manifest.pop(field, None)
        else:
            manifest[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_a_weighted_run_from_before_the_scores_were_scaled_by_the_sample_area_is_out_of_date(built_project):
    """Its scores are sums of patch weights without the area each sample point stands for: a score cutoff on them means another
    thing. Every stage is out of date once; the next run brings them back."""
    store, name, worker = built_project
    _rewrite_preprocessing_manifest(store, name, score_unit=None)
    assert stage_status(store, name) == {stage: "out_of_date" for stage in PIPELINE_STAGES}
    assert choose_stages(store, name, ["thresholding"]).stages == ["preprocessing", "thresholding"]
    run_and_wait(worker, name, ["exporting", "massing"])
    assert stage_status(store, name) == ALL_CURRENT


def test_a_run_whose_scores_are_in_another_unit_than_the_mode_now_writes_is_out_of_date(built_project):
    store, name, _worker = built_project
    _rewrite_preprocessing_manifest(store, name, score_unit="relative")
    assert stage_status(store, name)["preprocessing"] == "out_of_date"


def test_a_time_based_run_from_before_the_score_unit_was_recorded_stays_current(built_project):
    """Time-based scores were in m²·h already."""
    store, name, worker = built_project
    store.add_input(name, "weather", "weather.epw", GOLDEN_EPW.read_bytes())
    change_settings(store, name, mode="time-based", start_month=12, start_day=21, start_hour=10, end_month=12, end_day=21, end_hour=14)
    run_and_wait(worker, name, ["exporting", "massing"])
    assert stage_status(store, name) == ALL_CURRENT
    _rewrite_preprocessing_manifest(store, name, score_unit=None)
    assert stage_status(store, name) == ALL_CURRENT


# ---- The optional context and terrain inputs ----

def test_optional_roles_are_not_missing_inputs(project_with_inputs):
    store, name = project_with_inputs
    assert missing_inputs(store, name, store.load_project_config(name)) == []


def test_removing_the_context_drops_the_path_and_marks_the_run_out_of_date(project_with_inputs):
    store, name = project_with_inputs
    store.add_input(name, "context", "ctx.ply", box_bytes([30, 0, 5]))
    worker = make_worker(store)
    run_and_wait(worker, name, ["preprocessing"])
    assert stage_status(store, name)["preprocessing"] == "current"
    store.remove_input(name, "context", "ctx.ply")
    assert store.load_project_config(name).context_path is None
    assert stage_status(store, name)["preprocessing"] == "out_of_date"
    assert run_and_wait(worker, name, ["preprocessing"]).stages == ["preprocessing"]
    assert stage_status(store, name)["preprocessing"] == "current"
