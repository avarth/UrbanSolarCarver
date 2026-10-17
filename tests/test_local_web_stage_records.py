"""Stage records of the local web service: stage status, the choice of stages to run, and the records a run leaves.

The engine is replaced by a fake that writes a manifest with a new run_id (and the current upstream run_id)
for each stage it runs, as the real stages do.
"""
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import trimesh

from urbansolarcarver.run_context import report_issue, report_progress, run_context, stage_context
from urbansolarcarver.stage_settings import PIPELINE_STAGES, stages_needed_for
from urbansolarcarver.local_web_service.projects import ProjectStore
from urbansolarcarver.local_web_service.run_worker import RunWorker
from urbansolarcarver.local_web_service.stage_records import (
    UPSTREAM_STAGE, choose_stages, forget_stages, missing_inputs, record_stages, stage_status,
)

GOLDEN_EPW = Path(__file__).resolve().parent.parent / "examples" / "weather" / "USA_CO_Golden-NREL.724666_TMY3.epw"
ALL_CURRENT = {stage: "current" for stage in PIPELINE_STAGES}
ALL_MISSING = {stage: "missing" for stage in PIPELINE_STAGES}


# ---- Fakes and helpers shared with the run worker tests ----

def write_fake_stage_output(run_folder: Path, stage: str) -> None:
    """What a finished stage leaves: a manifest with a new run_id and, for a stage that reads one, the upstream run_id."""
    folder = run_folder / stage
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": uuid.uuid4().hex}
    if stage in UPSTREAM_STAGE:
        manifest["upstream_run_id"] = json.loads((run_folder / UPSTREAM_STAGE[stage] / "manifest.json").read_text())["run_id"]
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if stage == "exporting":
        (folder / "export.ply").write_bytes(b"ply")
    if stage == "massing":
        (folder / "plates.json").write_text("{}", encoding="utf-8")
        (folder / "plates.obj").write_text("", encoding="utf-8")
        (run_folder / "run_report.md").write_text("report", encoding="utf-8")


def stages_the_engine_runs(request) -> list[str]:
    path = stages_needed_for(request.produce)
    return path[path.index(request.start_from):]


class FakeEngine:
    """Stands in for ``handle_engine_request``; keeps the requests it received."""

    def __init__(self):
        self.requests = []

    def __call__(self, request, session, context):
        self.requests.append(request)
        with run_context(context):
            for stage in stages_the_engine_runs(request):
                with stage_context(stage):
                    report_progress(0, 1)
                    context.raise_if_cancelled()
                    if stage == "preprocessing":
                        report_issue("fake_issue", "preprocessing noticed something")
                    write_fake_stage_output(Path(request.run_folder), stage)
                    report_progress(1, 1)


class FakeSession:
    def __init__(self, device="cpu"):
        self.device = device

    def release_memory(self):
        pass


def make_worker(store, handle_request=None, device="cpu") -> RunWorker:
    return RunWorker(store, device, handle_request=handle_request or FakeEngine(), session_factory=FakeSession)


def wait_until_finished(worker: RunWorker, run_id: str, deadline_seconds: float = 20.0) -> list[dict]:
    """All events of a run once it has finished; fails the test when the run does not finish within the deadline."""
    state = worker.run_state(run_id)
    deadline = time.monotonic() + deadline_seconds
    seen = 0
    while not state.finished:
        assert time.monotonic() < deadline, f"the run did not finish within {deadline_seconds} seconds"
        seen += len(state.wait_for_events(seen, 0.2))
    return list(state.events)


def run_and_wait(worker: RunWorker, name: str, produce: list[str]):
    """Start a run and wait for it to end; the start reply."""
    reply = worker.start(name, produce)
    if reply.run_id is not None:
        wait_until_finished(worker, reply.run_id)
    return reply


def change_settings(store: ProjectStore, name: str, **changes) -> None:
    store.write_config_from_values(name, {**store.read_settings(name), **changes})


def box_bytes(center, extents=(10, 10, 10)) -> bytes:
    box = trimesh.creation.box(extents=extents)
    box.apply_translation(center)
    return box.export(file_type="ply")


@pytest.fixture
def project_with_inputs(tmp_path):
    """A daylight project (no weather file needed) with a max volume and a test surface."""
    store = ProjectStore(tmp_path / "projects")
    store.create("p", "daylight")
    store.add_input("p", "max_volume", "volume.ply", box_bytes([0, 0, 5]))
    store.add_input("p", "test_surfaces", "surface.ply", box_bytes([0, 0, 0], extents=(6, 6, 0.1)))
    return store, "p"


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
