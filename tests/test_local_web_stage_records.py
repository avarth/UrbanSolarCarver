"""Stage records of the local web service: stage status, the choice of stages to run, and the records a run leaves.

The engine is replaced by the fake of local_web_test_support.py, which writes a manifest with a new run_id (and the current
upstream run_id) for each stage it runs, as the real stages do. The fixture project_with_inputs is in conftest.py.
"""
import json
import subprocess
import sys

import pytest

from local_web_test_support import (
    ALL_CURRENT, ALL_MISSING, GOLDEN_EPW, box_bytes, change_settings, make_worker, run_and_wait, write_fake_stage_output,
)
from urbansolarcarver.stage_settings import PIPELINE_STAGES
from urbansolarcarver.local_web_service.projects import ProjectStore
from urbansolarcarver.local_web_service.stage_records import choose_stages, forget_stages, missing_inputs, record_stages, stage_status

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


def test_floor_height_change_reruns_massing_only(built_project):
    store, name, worker = built_project
    change_settings(store, name, floor_height=4.0)
    assert stage_status(store, name)["massing"] == "out_of_date"
    assert run_and_wait(worker, name, ["exporting", "massing"]).stages == ["massing"]
    assert stage_status(store, name) == ALL_CURRENT


def test_mesh_format_change_reruns_exporting_only(built_project):
    store, name, worker = built_project
    change_settings(store, name, final_mesh_format="obj")
    assert run_and_wait(worker, name, ["exporting"]).stages == ["exporting"]
    assert stage_status(store, name) == ALL_CURRENT


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


def test_importing_the_stage_records_and_the_worker_does_not_load_torch():
    code = ("import sys; import urbansolarcarver.local_web_service.stage_records, urbansolarcarver.local_web_service.run_worker; "
            "print('torch' in sys.modules)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"
