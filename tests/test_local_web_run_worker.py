"""The run worker of the local web service: one run at a time, events for late readers, cancel and failures."""
import threading

import pytest

from local_web_test_support import (
    ALL_CURRENT, ALL_MISSING, FakeEngine, WaitsForCancel, change_settings, has_vertex_normals, make_worker, run_and_wait,
    wait_until_finished, write_joined_test_surfaces_without_normals,
)
from urbansolarcarver.errors import ConfigError, ConfigFieldError, InputError, StageChainError
from urbansolarcarver.local_web_service import run_worker as run_worker_module
from urbansolarcarver.local_web_service.projects import ProjectStore
from urbansolarcarver.local_web_service.run_worker import MissingInputs, RunConflict, RunWorker
from urbansolarcarver.local_web_service.stage_records import choose_stages, stage_status
from urbansolarcarver.stage_settings import PIPELINE_STAGES
from urbansolarcarver.run_context import report_issue, run_context, stage_context


def start_blocked_run(worker, name, produce):
    handler = worker._handle_request
    reply = worker.start(name, produce)
    assert handler.started.wait(10)
    return reply


def test_interrupted_run_makes_the_next_run_complete(project_with_inputs):
    store, name = project_with_inputs
    worker = make_worker(store)
    run_and_wait(worker, name, ["thresholding"])
    change_settings(store, name, voxel_size=2.0)
    blocked_worker = make_worker(store, handle_request=WaitsForCancel())
    reply = start_blocked_run(blocked_worker, name, ["thresholding"])
    # as after a service stopped mid-run: the stages being run have no record
    assert store.read_project_json(name).stage_records == {}
    assert stage_status(store, name) == ALL_MISSING
    assert blocked_worker.cancel(reply.run_id)
    wait_until_finished(blocked_worker, reply.run_id)
    assert choose_stages(store, name, ["thresholding"]).stages == ["preprocessing", "thresholding"]


def test_a_run_rebuilds_a_joined_test_surface_file_written_without_normals_and_runs_the_analysis_again(project_with_inputs):
    store, name = project_with_inputs
    worker = make_worker(store)
    run_and_wait(worker, name, ["thresholding"])
    joined_path = write_joined_test_surfaces_without_normals(store, name)
    assert worker.start(name, ["thresholding"]).stages == ["preprocessing", "thresholding"]
    assert has_vertex_normals(joined_path)


def test_second_start_while_running_is_a_conflict(project_with_inputs):
    store, name = project_with_inputs
    worker = make_worker(store, handle_request=WaitsForCancel())
    reply = start_blocked_run(worker, name, ["thresholding"])
    assert worker.active_project() == name
    with pytest.raises(RunConflict) as conflict:
        worker.start(name, ["thresholding"])
    assert conflict.value.status_code == 409
    worker.cancel(reply.run_id)
    wait_until_finished(worker, reply.run_id)
    assert worker.active_project() is None


def test_a_conflict_is_reported_before_missing_inputs_of_another_project(project_with_inputs):
    store, name = project_with_inputs
    store.create("empty", "daylight")
    worker = make_worker(store, handle_request=WaitsForCancel())
    reply = start_blocked_run(worker, name, ["thresholding"])
    with pytest.raises(RunConflict):
        worker.start("empty", ["thresholding"])
    worker.cancel(reply.run_id)
    wait_until_finished(worker, reply.run_id)


def test_missing_inputs_are_named(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("p", "time-based")
    worker = make_worker(store)
    with pytest.raises(MissingInputs) as missing:
        worker.start("p", ["thresholding"])
    assert missing.value.roles == ["max_volume", "test_surfaces:1", "weather"]
    assert missing.value.status_code == 422
    assert worker.active_project() is None
    assert store.read_project_json("p").stage_records == {}


def test_the_engine_is_asked_for_the_chosen_stages_with_the_device_of_the_worker(project_with_inputs):
    store, name = project_with_inputs
    engine = FakeEngine()
    worker = make_worker(store, handle_request=engine, device="cpu")
    assert store.read_stored_config(name)["device"] == "auto"     # the device stored at the last save is not the run's
    run_and_wait(worker, name, ["thresholding"])
    change_settings(store, name, floor_height=4.0)
    run_and_wait(worker, name, ["exporting", "massing"])
    first, second = engine.requests
    assert (first.cmd, first.produce, first.start_from, first.overrides) == ("run", ["thresholding"], "preprocessing", {"device": "cpu"})
    assert (second.produce, second.start_from) == (["exporting", "massing"], "exporting")
    assert first.config == str(store.open(name) / "config.yaml")
    assert first.run_folder == str(store.open(name) / "run")


def test_events_reach_a_late_reader_in_order(project_with_inputs):
    store, name = project_with_inputs
    worker = make_worker(store)
    reply = run_and_wait(worker, name, ["thresholding"])
    state = worker.run_state(reply.run_id)
    assert state.finished and (state.run_id, state.project, state.stages) == (reply.run_id, name, ["preprocessing", "thresholding"])
    events = state.wait_for_events(0, 0)
    assert events == [
        {"type": "stage_progress", "stage": "preprocessing", "done": 0, "total": 1},
        {"type": "issue", "stage": "preprocessing", "code": "fake_issue", "message": "preprocessing noticed something"},
        {"type": "stage_progress", "stage": "preprocessing", "done": 1, "total": 1},
        {"type": "stage_progress", "stage": "thresholding", "done": 0, "total": 1},
        {"type": "stage_progress", "stage": "thresholding", "done": 1, "total": 1},
        {"type": "run_finished", "stages": ["preprocessing", "thresholding"], "files": []},
    ]
    assert state.wait_for_events(3, 0) == events[3:]        # a reader that saw three events gets the rest
    assert state.wait_for_events(len(events), 0) == []      # and nothing once it has seen them all


def test_a_reader_blocks_until_the_next_event(project_with_inputs):
    store, name = project_with_inputs
    worker = make_worker(store, handle_request=WaitsForCancel())
    reply = start_blocked_run(worker, name, ["thresholding"])
    state = worker.run_state(reply.run_id)
    assert state.wait_for_events(0, 0.05) == [] and not state.finished      # the timeout passes with nothing new
    reader_result = []
    reader = threading.Thread(target=lambda: reader_result.extend(state.wait_for_events(0, 10)))
    reader.start()
    worker.cancel(reply.run_id)
    reader.join(10)
    assert reader_result == [{"type": "run_cancelled"}]


def test_a_finished_run_lists_the_result_files_that_exist(project_with_inputs):
    store, name = project_with_inputs
    worker = make_worker(store)
    run_and_wait(worker, name, ["thresholding"])
    reply = run_and_wait(worker, name, ["exporting", "massing"])
    final_event = worker.run_state(reply.run_id).events[-1]
    assert final_event == {"type": "run_finished", "stages": ["exporting", "massing"], "files": [
        "exporting/export.ply", "massing/plates.json", "massing/plates.obj", "run_report.md"]}


def test_the_result_files_include_the_plates_in_the_chosen_format(tmp_path):
    massing_folder = tmp_path / "massing"
    massing_folder.mkdir()
    for file_name in ("plates.json", "plates.obj", "plates.glb"):
        (massing_folder / file_name).write_text("", encoding="utf-8")
    assert run_worker_module._result_files(tmp_path) == ["massing/plates.glb", "massing/plates.json", "massing/plates.obj"]


class CountingSession:
    """A session that counts its releases; ``instances`` collects every one created."""

    def __init__(self, instances):
        self.released = 0
        instances.append(self)

    def release_memory(self):
        self.released += 1


def test_cancel_gives_run_cancelled_and_leaves_the_stages_missing(project_with_inputs):
    store, name = project_with_inputs
    released_sessions = []
    worker = RunWorker(store, "cpu", handle_request=WaitsForCancel(),
                       session_factory=lambda device: CountingSession(released_sessions))
    reply = start_blocked_run(worker, name, ["thresholding"])
    assert worker.cancel(reply.run_id)
    events = wait_until_finished(worker, reply.run_id)
    assert events[-1] == {"type": "run_cancelled"}
    assert stage_status(store, name) == ALL_MISSING
    assert released_sessions[0].released == 1


def test_cancel_of_an_unknown_or_finished_run_is_false(project_with_inputs):
    store, name = project_with_inputs
    worker = make_worker(store)
    assert not worker.cancel("nothing")
    reply = run_and_wait(worker, name, ["thresholding"])
    assert not worker.cancel(reply.run_id)
    assert worker.run_state("nothing") is None


def test_the_session_is_created_once_and_released_after_every_run(project_with_inputs):
    store, name = project_with_inputs
    created_devices = []
    released = []

    class CountingSession:
        def __init__(self, device):
            created_devices.append(device)

        def release_memory(self):
            released.append(True)

    worker = RunWorker(store, "cpu", handle_request=FakeEngine(), session_factory=CountingSession)
    run_and_wait(worker, name, ["thresholding"])
    change_settings(store, name, carve_fraction=0.3)
    run_and_wait(worker, name, ["thresholding"])
    assert created_devices == ["cpu"] and len(released) == 2


@pytest.mark.parametrize("error, error_type", [
    (ConfigError("m", [ConfigFieldError("voxel_size", "too small")]), "ConfigError"),
    (InputError("broken mesh"), "InputError"),
    (StageChainError("rerun preprocessing"), "StageChainError"),
    (RuntimeError("boom"), "RuntimeError"),
])
def test_failures_become_run_failed_events(project_with_inputs, error, error_type):
    store, name = project_with_inputs
    run_and_wait(make_worker(store), name, ["thresholding"])
    change_settings(store, name, carve_fraction=0.3)

    def failing_engine(request, session, context):
        raise error

    worker = make_worker(store, handle_request=failing_engine)
    reply = run_and_wait(worker, name, ["thresholding"])
    last_event = worker.run_state(reply.run_id).events[-1]
    assert last_event["type"] == "run_failed" and last_event["error_type"] == error_type
    if isinstance(error, ConfigError):
        assert last_event["field_errors"] == [{"field": "voxel_size", "message": "too small"}]
        assert last_event["message"] == "m"
    else:
        assert last_event["field_errors"] == []
    if isinstance(error, StageChainError):
        assert last_event["message"] == "Results are out of date; run again from the start."
        assert stage_status(store, name) == ALL_MISSING
    else:
        assert last_event["message"] == str(error)
        assert stage_status(store, name)["thresholding"] == "missing" and stage_status(store, name)["preprocessing"] == "current"
    assert worker.active_project() is None
    next_run = worker.start(name, ["thresholding"])      # a failed run does not block the next one
    assert next_run.status == "started"
    wait_until_finished(worker, next_run.run_id)


def test_a_failing_release_of_memory_does_not_block_the_worker(project_with_inputs):
    store, name = project_with_inputs

    class SessionThatFailsToRelease:
        def release_memory(self):
            raise RuntimeError("CUDA error")

    worker = RunWorker(store, "cpu", handle_request=FakeEngine(), session_factory=lambda device: SessionThatFailsToRelease())
    reply = run_and_wait(worker, name, ["thresholding"])
    assert worker.run_state(reply.run_id).events[-1]["type"] == "run_finished"     # the run itself succeeded
    assert worker.active_project() is None
    assert run_and_wait(worker, name, ["exporting"]).status == "started"


def test_a_failure_while_finishing_still_ends_the_run_and_frees_the_worker(project_with_inputs, monkeypatch):
    store, name = project_with_inputs
    run_and_wait(make_worker(store), name, ["thresholding"])
    change_settings(store, name, carve_fraction=0.3)

    def engine_with_broken_chain(request, session, context):
        raise StageChainError("rerun preprocessing")

    forget_all_stages = run_worker_module.forget_stages

    def forget_stages_failing_for_the_whole_pipeline(store_, name_, stages):
        if len(stages) == len(PIPELINE_STAGES):
            raise OSError("disk error")
        forget_all_stages(store_, name_, stages)

    monkeypatch.setattr(run_worker_module, "forget_stages", forget_stages_failing_for_the_whole_pipeline)
    worker = make_worker(store, handle_request=engine_with_broken_chain)
    reply = run_and_wait(worker, name, ["thresholding"])
    last_event = worker.run_state(reply.run_id).events[-1]
    assert (last_event["type"], last_event["error_type"], last_event["message"]) == ("run_failed", "OSError", "disk error")
    assert worker.active_project() is None
    next_run = worker.start(name, ["thresholding"])
    assert next_run.status == "started"
    wait_until_finished(worker, next_run.run_id)


def test_issues_reported_before_a_failure_are_sent_before_run_failed(project_with_inputs):
    store, name = project_with_inputs
    def failing_after_an_issue(request, session, context):
        with run_context(context), stage_context("preprocessing"):
            report_issue("grid_coarse", "The grid is coarse.")
            raise RuntimeError("boom")

    worker = make_worker(store, handle_request=failing_after_an_issue)
    reply = run_and_wait(worker, name, ["thresholding"])
    assert [event["type"] for event in worker.run_state(reply.run_id).events] == ["issue", "run_failed"]


def test_an_engine_that_returns_without_manifests_is_not_recorded_as_current(project_with_inputs):
    store, name = project_with_inputs
    worker = make_worker(store, handle_request=lambda request, session, context: None)
    reply = run_and_wait(worker, name, ["thresholding"])
    assert worker.run_state(reply.run_id).events[-1]["type"] == "run_failed"
    assert stage_status(store, name) == ALL_MISSING


@pytest.mark.slow
def test_real_two_phase_run_on_the_basic_perimeter_block(tmp_path):
    from pathlib import Path
    example_folder = Path(__file__).resolve().parent.parent / "examples" / "test_inputs" / "basic_perimeter_block"
    store = ProjectStore(tmp_path / "projects", device="cpu")
    store.create("block", "tilted_plane")
    store.add_input("block", "max_volume", "maxVolume.ply", (example_folder / "maxVolume.ply").read_bytes())
    store.add_input("block", "test_surfaces", "testSrfs.ply", (example_folder / "testSrfs.ply").read_bytes())
    change_settings(store, "block", voxel_size=2.0)
    worker = RunWorker(store, "cpu")
    run_folder = store.open("block") / "run"

    analysis = worker.start("block", ["thresholding"])
    analysis_events = wait_until_finished(worker, analysis.run_id)
    assert analysis_events[-1]["type"] == "run_finished", analysis_events[-1]
    first_progress = next(event for event in analysis_events if event["type"] == "stage_progress")
    assert first_progress["stage"] == "preprocessing"

    build = worker.start("block", ["exporting", "massing"])
    assert build.stages == ["exporting", "massing"]
    build_events = wait_until_finished(worker, build.run_id)
    assert build_events[-1]["type"] == "run_finished", build_events[-1]
    assert "massing/plates.json" in build_events[-1]["files"]
    assert stage_status(store, "block") == ALL_CURRENT

    change_settings(store, "block", carve_above_min_consecutive=2)
    rerun = worker.start("block", ["thresholding"])
    assert rerun.stages == ["thresholding"]
    assert wait_until_finished(worker, rerun.run_id)[-1]["type"] == "run_finished"
    assert (run_folder / "exporting" / "manifest.json").is_file() and (run_folder / "massing" / "plates.json").is_file()
    assert stage_status(store, "block") == {
        "preprocessing": "current", "thresholding": "current", "exporting": "out_of_date", "massing": "out_of_date"}
