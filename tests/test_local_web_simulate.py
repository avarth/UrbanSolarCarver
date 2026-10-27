"""Running the studies of the Simulate workspace: one job at a time with the pipeline runs, results and state per study.

The engine is the real ``handle_engine_request`` with the ray tracing replaced (every test point gets 1 per direction set), so the
check samples the test surfaces, lists the geometries of the run folder and writes its files and fingerprints as it does for real.
"""
import json
import shutil
import struct
import warnings

import numpy as np
import pytest
import trimesh

from local_web_test_support import (
    GOLDEN_EPW, WaitsForCancel, box_bytes, change_settings, wait_until_finished, write_envelope_as_exported, write_fake_chain_run,
    write_earlier_version_project, write_fake_stage_output,
)
from test_local_web_server import build_client, create_project_with_inputs, read_events, start_run, upload
from urbansolarcarver import solar_check
from urbansolarcarver.engine_requests import handle_engine_request
from urbansolarcarver.local_web_service import simulation
from urbansolarcarver.local_web_service.projects import ProjectStore
from urbansolarcarver.local_web_service.run_worker import RunConflict
from urbansolarcarver.local_web_service.stage_records import stage_status_reply


@pytest.fixture(autouse=True)
def tracing_gives_ones(monkeypatch):
    """Every test point sees 1 in every column; the rest of the check runs as it does."""
    def evaluate_test_points(points, normals, directions, mesh, *, progress=None, **_keywords):
        if progress is not None:
            progress(1)
        return np.ones(len(points))
    monkeypatch.setattr(solar_check, "evaluate_test_points", evaluate_test_points)


class CheckEngine:
    """The real engine handler; keeps the requests it received."""

    def __init__(self):
        self.requests = []

    def __call__(self, request, session, context):
        self.requests.append(request)
        return handle_engine_request(request, session, context)


def plane_bytes(z=0.5, size=6.0) -> bytes:
    """A flat square test surface facing up (the test surface of add_project_with_inputs is a thin box, which the check skips)."""
    half = size / 2
    plane = trimesh.Trimesh(vertices=[[-half, -half, z], [half, -half, z], [half, half, z], [-half, half, z]], faces=[[0, 1, 2], [0, 2, 3]])
    return plane.export(file_type="ply")


def add_study(store, name, metric="sky_view", files=("plane.ply",), **values):
    study = store.add_study(name, metric=metric)
    for file_name in files:
        store.use_study_test_surface(name, study.id, file_name)
    if values:
        store.update_study(name, study.id, values=values)
    return study.id


def simulate_and_wait(worker, name="p") -> list[dict]:
    state = worker.start_simulation(name)
    return wait_until_finished(worker, state.run_id)


def state_of(store, name, study_id):
    return simulation.study_state(store, name, next(study for study in store.studies(name) if study.id == study_id))


def write_massing_as_built(project_folder):
    """Put a real massing mesh where the fake massing stage left its empty plates.obj (the file its manifest names)."""
    massing = trimesh.creation.box(extents=(4, 4, 3))
    massing.apply_translation([0, 0, 1.5])
    massing.export(project_folder / "run" / "massing" / "plates.obj")


@pytest.fixture
def service(tmp_path):
    """A client and worker with the check engine, and a daylight project 'p' with a max volume and the test surfaces surface.ply
    (criterion 1's) and plane.ply."""
    engine = CheckEngine()
    client, worker = build_client(tmp_path / "projects", handle_request=engine)
    create_project_with_inputs(client)
    worker.store.add_input("p", "test_surfaces", "plane.ply", plane_bytes())
    return client, worker, engine


def test_simulate_runs_every_study_that_can_run_and_names_the_ones_that_cannot(service):
    client, worker, engine = service
    store = worker.store
    ready = add_study(store, "p")
    without_files = add_study(store, "p", files=())
    reply = client.post("/api/projects/p/simulate")
    assert reply.status_code == 200, reply.text
    started = reply.json()
    assert (started["status"], started["stages"], started["criterion_stages"]) == ("started", ["simulate"], {})
    events = read_events(client, started["run_id"])
    assert events[-1] == {"type": "run_finished", "stages": ["simulate"], "files": []}
    progress = [event for event in events if event["type"] == "stage_progress"]
    assert progress and all(event["stage"] == "simulate" and event["study"] == ready for event in progress)
    assert len(engine.requests) == 1
    request = engine.requests[0]
    project_folder = store.open("p")
    assert request.cmd == "check" and request.out_dir == str(project_folder / "simulate" / ready)
    assert request.test_surface_path == str(project_folder / "inputs" / "joined" / f"study_surfaces_{ready}.ply")
    assert request.max_volume_path == str(project_folder / "inputs" / "joined" / "max_volume.ply")
    assert request.run_folder == str(project_folder / "run") and request.device == "cpu"
    assert request.settings["sample_spacing"] == 0.5        # half the voxel size of 1 m, as the carving samples
    studies = {study["entry"]["id"]: study for study in client.get("/api/projects/p/studies").json()["studies"]}
    assert (studies[ready]["state"], studies[ready]["reason"], studies[ready]["geometries"]) == ("current", None, ["max_volume"])
    assert (studies[without_files]["state"], studies[without_files]["reason"]) == ("refused", "Add test surfaces")
    assert studies[without_files]["geometries"] == []


def test_a_study_whose_metric_needs_the_missing_weather_file_is_refused(service):
    _client, worker, _engine = service
    store = worker.store
    sun_hours = add_study(store, "p", metric="sun_hours")
    assert state_of(store, "p", sun_hours) == ("refused", "Add a weather file")
    store.add_input("p", "weather", "golden.epw", GOLDEN_EPW.read_bytes())
    assert state_of(store, "p", sun_hours) == ("not_run", None)


def test_a_study_the_engine_refuses_stays_refused_until_its_inputs_change_and_the_others_still_run(service, monkeypatch):
    client, worker, _engine = service
    store = worker.store
    store.add_input("p", "test_surfaces", "small.ply", plane_bytes(size=2.0))
    large, small = add_study(store, "p"), add_study(store, "p", files=("small.ply",))
    monkeypatch.setattr(solar_check, "MAX_CHECK_POINTS", 50)     # the 6 m plane has 144 points at 0.5 m, the 2 m plane 16
    events = simulate_and_wait(worker)
    assert events[-1]["type"] == "run_finished"
    issues = [event for event in events if event["type"] == "issue"]
    assert [(issue["stage"], issue["study"], issue["code"]) for issue in issues] == [("simulate", large, "InputError")]
    state, reason = state_of(store, "p", large)
    assert state == "refused" and reason == issues[0]["message"] and "A spacing of" in reason
    assert state_of(store, "p", small) == ("current", None)
    listed = {study["entry"]["id"]: study for study in client.get("/api/projects/p/studies").json()["studies"]}
    assert (listed[large]["state"], listed[large]["reason"]) == ("refused", reason)
    assert simulation.study_state(ProjectStore(store.projects_folder), "p", store.studies("p")[0]) == ("refused", reason)  # read from disk

    store.write_shared_settings("p", {"voxel_size": 2.0})     # a spacing of 1 m: 36 points
    assert state_of(store, "p", large) == ("not_run", None)
    assert state_of(store, "p", small) == ("out_of_date", None)
    assert simulate_and_wait(worker)[-1]["type"] == "run_finished"
    assert state_of(store, "p", large) == ("current", None)
    assert not (store.open("p") / "simulate" / large / "refusal.json").exists()


def test_deleting_a_refused_study_removes_its_refusal(service, monkeypatch):
    _client, worker, _engine = service
    store = worker.store
    study = add_study(store, "p")
    monkeypatch.setattr(solar_check, "MAX_CHECK_POINTS", 50)
    simulate_and_wait(worker)
    assert (store.open("p") / "simulate" / study / "refusal.json").is_file()
    store.delete_study("p", study)
    assert not (store.open("p") / "simulate" / study).exists()


def test_a_moved_project_keeps_its_weather_study_current(service):
    _client, worker, _engine = service
    store = worker.store
    store.add_input("p", "weather", "golden.epw", GOLDEN_EPW.read_bytes())
    study = add_study(store, "p", metric="sun_hours")
    simulate_and_wait(worker)
    assert state_of(store, "p", study) == ("current", None)
    store.rename_project("p", "moved")
    assert state_of(store, "moved", study) == ("current", None)


def test_the_rays_per_patch_are_those_of_the_first_criterion_that_is_on(service):
    _client, worker, _engine = service
    store = worker.store
    study = store.add_study("p", metric="sky_view")
    first = store.criteria("p")[0]
    store.update_criterion("p", first.id, values={**first.settings, "rays_per_patch": 1})
    second = store.add_criterion("p", "daylight")
    store.update_criterion("p", second.id, values={**second.settings, "rays_per_patch": 9})
    assert simulation.study_settings(store, "p", study).rays_per_patch == 1        # the first is on
    store.update_criterion("p", first.id, bypassed=True)
    settings = simulation.study_settings(store, "p", study)
    assert settings.rays_per_patch == 9 and settings.min_altitude == 5.0
    store.update_criterion("p", second.id, bypassed=True)
    assert simulation.study_settings(store, "p", study).rays_per_patch == 1        # none is on: the first
    with store.project_lock("p"):
        project_json = store.read_project_json("p")
        project_json.criteria = []
        store.write_project_json("p", project_json)
    assert simulation.study_settings(store, "p", study).rays_per_patch == 4        # no criterion


def test_a_study_takes_its_time_basis_from_its_own_settings(service):
    _client, worker, _engine = service
    store = worker.store
    store.add_input("p", "weather", "golden.epw", GOLDEN_EPW.read_bytes())
    study = store.add_study("p", metric="sun_hours")
    assert simulation.study_settings(store, "p", study).time_basis == "standard"
    store.update_study("p", study.id, values={"time_basis": "solar"})
    assert simulation.study_settings(store, "p", store.studies("p")[0]).time_basis == "solar"
    with store.project_lock("p"):       # as a study stored before time_basis was a study setting
        project_json = store.read_project_json("p")
        project_json.studies[0].settings.pop("time_basis")
        store.write_project_json("p", project_json)
    assert simulation.study_settings(store, "p", store.studies("p")[0]).time_basis == "standard"


def test_a_project_of_an_earlier_version_is_migrated_before_a_simulation(tmp_path):
    client, worker = build_client(tmp_path / "projects", handle_request=CheckEngine())
    write_earlier_version_project(worker.store, "old", stages=())
    assert worker.store.read_project_json("old").criteria == []
    reply = client.post("/api/projects/old/simulate")
    assert reply.status_code == 422 and reply.json()["detail"] == "Add a study to run."
    assert [criterion.id for criterion in worker.store.criteria("old")] == ["1"]


def test_an_unreadable_envelope_manifest_leaves_the_envelope_out_with_an_issue(service):
    _client, worker, _engine = service
    store = worker.store
    project_folder = store.open("p")
    write_fake_chain_run(store, "p", ["1"])
    write_envelope_as_exported(project_folder)
    shutil.rmtree(project_folder / "run" / "massing")
    manifest_path = project_folder / "run" / "exporting" / "manifest.json"
    manifest_path.write_text("{not json", encoding="utf-8")
    study = add_study(store, "p")
    events = simulate_and_wait(worker)
    assert events[-1]["type"] == "run_finished"
    issues = [event for event in events if event["type"] == "issue" and event["code"] == "geometry_manifest_unusable"]
    assert len(issues) == 1 and issues[0]["study"] == study
    assert "Carved envelope" in issues[0]["message"] and str(manifest_path) in issues[0]["message"]
    assert simulation.result_geometries(store, "p", study) == ["max_volume"]
    with warnings.catch_warnings():
        warnings.simplefilter("error")      # the state of a study reports nothing and raises nothing
        assert state_of(store, "p", study) == ("current", None)


def test_a_result_traced_with_the_voxel_size_its_manifests_record_stays_current(service):
    _client, worker, _engine = service
    store = worker.store
    project_folder = store.open("p")
    run_folder = project_folder / "run"
    write_fake_chain_run(store, "p", ["1"])
    write_envelope_as_exported(project_folder)
    shutil.rmtree(run_folder / "massing")
    upstream = json.loads((run_folder / "exporting" / "manifest.json").read_text(encoding="utf-8"))["upstream_run_id"]
    (run_folder / "thresholding").mkdir()      # the single-run layout, whose preprocessing records a voxel size of 2 m
    (run_folder / "thresholding" / "manifest.json").write_text(json.dumps({"run_id": upstream, "upstream_run_id": "pre"}), encoding="utf-8")
    (run_folder / "preprocessing").mkdir()
    (run_folder / "preprocessing" / "manifest.json").write_text(json.dumps({"run_id": "pre", "voxel_size": 2.0}), encoding="utf-8")
    study = add_study(store, "p")
    simulate_and_wait(worker)
    summary = json.loads((project_folder / "simulate" / study / "check_summary.json").read_text(encoding="utf-8"))
    assert summary["columns"]["envelope"]["surface_tolerance_m"] == 2.0 and simulation.tracing_voxel_size(store, "p") == 1.0
    assert state_of(store, "p", study) == ("current", None)


def test_simulate_is_refused_while_a_pipeline_run_is_active_and_the_reverse(tmp_path):
    handler = WaitsForCancel()
    client, worker = build_client(tmp_path / "projects", handle_request=handler)
    create_project_with_inputs(client)
    create_project_with_inputs(client, "q")
    add_study(worker.store, "p", files=("surface.ply",))
    add_study(worker.store, "q", files=("surface.ply",))
    run_id = start_run(client)["run_id"]
    assert handler.started.wait(10)
    assert client.post("/api/projects/p/simulate").status_code == 409
    assert client.post("/api/projects/q/simulate").status_code == 409      # one job at a time, whatever the project
    worker.cancel(run_id)
    wait_until_finished(worker, run_id)

    handler.started.clear()
    simulation_reply = client.post("/api/projects/p/simulate")
    assert simulation_reply.status_code == 200, simulation_reply.text
    assert handler.started.wait(10)
    for project in ("p", "q"):
        refused = client.post(f"/api/projects/{project}/runs", json={"produce": ["exporting"]})
        assert refused.status_code == 409 and "'p'" in refused.json()["detail"]
    with pytest.raises(RunConflict):
        worker.start_simulation("q")
    simulation_id = simulation_reply.json()["run_id"]
    worker.cancel(simulation_id)
    wait_until_finished(worker, simulation_id)


def test_edits_are_refused_during_a_simulation(tmp_path):
    handler = WaitsForCancel()
    client, worker = build_client(tmp_path / "projects", handle_request=handler)
    create_project_with_inputs(client)
    study = add_study(worker.store, "p", files=("surface.ply",))
    run_id = client.post("/api/projects/p/simulate").json()["run_id"]
    assert handler.started.wait(10)
    assert client.patch(f"/api/projects/p/studies/{study}", json={"name": "Roofs"}).status_code == 409
    assert client.patch("/api/projects/p/criteria/1", json={"name": "Courtyard"}).status_code == 409
    assert upload(client, "p", "context", ("context.ply", box_bytes([30, 0, 5]))).status_code == 409
    assert client.get("/api/projects/p/studies").status_code == 200        # reading goes on
    worker.cancel(run_id)
    wait_until_finished(worker, run_id)
    assert client.patch(f"/api/projects/p/studies/{study}", json={"name": "Roofs"}).status_code == 200


def test_a_simulation_leaves_stage_records_and_inputs_revision_alone(service):
    _client, worker, _engine = service
    store = worker.store
    write_fake_chain_run(store, "p", ["1"])
    write_envelope_as_exported(store.open("p"))
    add_study(store, "p")
    project_json_before = store.read_project_json("p")
    config_before = (store.open("p") / "config.yaml").read_text(encoding="utf-8")
    status_before = stage_status_reply(store, "p")
    assert simulate_and_wait(worker)[-1]["type"] == "run_finished"
    project_json_after = store.read_project_json("p")
    assert project_json_after.stage_records == project_json_before.stage_records
    assert project_json_after.criterion_records == project_json_before.criterion_records
    assert project_json_after.inputs_revision == project_json_before.inputs_revision
    assert (store.open("p") / "config.yaml").read_text(encoding="utf-8") == config_before
    assert stage_status_reply(store, "p") == status_before


@pytest.mark.slow
def test_a_study_is_out_of_date_after_its_settings_its_files_the_weather_the_context_or_a_rebuilt_envelope_change(service):
    _client, worker, _engine = service
    store = worker.store
    project_folder = store.open("p")
    store.add_input("p", "weather", "golden.epw", GOLDEN_EPW.read_bytes())
    store.add_input("p", "test_surfaces", "roof.ply", plane_bytes(z=3.0, size=4.0))
    write_fake_chain_run(store, "p", ["1"])
    write_envelope_as_exported(project_folder)
    write_massing_as_built(project_folder)
    study = add_study(store, "p", metric="sun_hours")
    assert state_of(store, "p", study) == ("not_run", None)

    def current_after_a_run():
        assert simulate_and_wait(worker)[-1]["type"] == "run_finished"
        assert state_of(store, "p", study) == ("current", None)

    def changes_make_it_out_of_date(change):
        current_after_a_run()
        change()
        assert state_of(store, "p", study) == ("out_of_date", None), change.__name__

    def its_settings():
        store.update_study("p", study, values={"end_hour": 13})

    def a_shared_setting():
        store.write_shared_settings("p", {"north_deg": 20.0})

    def its_files():
        store.use_study_test_surface("p", study, "roof.ply")

    def the_weather():
        store.add_input("p", "weather", "golden.epw", GOLDEN_EPW.read_bytes())      # the same content written again

    def the_context():
        store.add_input("p", "context", "context.ply", box_bytes([30, 0, 5]))

    def the_terrain():
        store.add_input("p", "terrain", "terrain.ply", box_bytes([0, 0, -1], extents=(80, 80, 0.5)))

    def the_max_volume():
        store.add_input("p", "max_volume", "volume.ply", box_bytes([0, 0, 6]))

    def a_rebuilt_envelope():
        write_envelope_as_exported(project_folder, extents=(7, 7, 5))

    def a_removed_massing():
        shutil.rmtree(project_folder / "run" / "massing")

    def the_voxel_size_the_envelope_was_built_with():
        with store.project_lock("p"):
            project_json = store.read_project_json("p")
            project_json.stage_records["exporting"].config["voxel_size"] = 2.0
            store.write_project_json("p", project_json)

    for change in (its_settings, a_shared_setting, its_files, the_weather, the_context, the_terrain, the_max_volume,
                   a_rebuilt_envelope, a_removed_massing, the_voxel_size_the_envelope_was_built_with):
        changes_make_it_out_of_date(change)
    current_after_a_run()
    write_fake_stage_output(project_folder / "run", "massing")       # the massing built again
    write_massing_as_built(project_folder)
    assert state_of(store, "p", study) == ("out_of_date", None)


def test_an_envelope_out_of_date_in_design_is_still_traced(service):
    client, worker, engine = service
    store = worker.store
    project_folder = store.open("p")
    write_fake_chain_run(store, "p", ["1"])
    write_envelope_as_exported(project_folder)
    shutil.rmtree(project_folder / "run" / "massing")
    change_settings(store, "p", carve_fraction=0.3)
    assert stage_status_reply(store, "p").stages["exporting"] != "current"
    study = add_study(store, "p")
    assert simulate_and_wait(worker)[-1]["type"] == "run_finished"
    assert engine.requests[-1].run_folder == str(project_folder / "run")
    listed = client.get("/api/projects/p/studies").json()["studies"]
    assert listed[0]["entry"]["id"] == study and listed[0]["geometries"] == ["max_volume", "envelope"]
    summary = json.loads((project_folder / "simulate" / study / "check_summary.json").read_text(encoding="utf-8"))
    assert summary["columns"]["envelope"]["surface_tolerance_m"] == 1.0


def test_values_route_packs_the_header_quads_and_columns(service):
    client, worker, _engine = service
    store = worker.store
    study = add_study(store, "p")
    not_run = add_study(store, "p", files=())
    assert client.get(f"/api/projects/p/studies/{study}/values").status_code == 404
    simulate_and_wait(worker)
    reply = client.get(f"/api/projects/p/studies/{study}/values")
    assert reply.status_code == 200 and reply.headers["content-type"] == "application/octet-stream"
    data = reply.content
    (header_length,) = struct.unpack_from("<I", data, 0)
    assert header_length % 4 == 0
    header = json.loads(data[4:4 + header_length])
    stored = solar_check.load_solar_check(store.open("p") / "simulate" / study)
    point_count = len(stored.points.points)
    assert header["point_count"] == point_count and header["columns"] == ["open", "max_volume"]
    assert header["unit"] == "%" and np.allclose(header["frame"], stored.points.points.min(axis=0), atol=1e-4)
    offset = 4 + header_length
    quads = np.frombuffer(data, "<f4", point_count * 12, offset).reshape(point_count, 4, 3)
    assert np.allclose(quads + np.asarray(header["frame"]), stored.points.quads, atol=1e-3)
    offset += quads.nbytes
    for column in header["columns"]:
        values = np.frombuffer(data, "<f4", point_count, offset)
        assert np.array_equal(values, stored.values[column].astype("<f4"))
        offset += values.nbytes
    assert offset == len(data)
    assert client.get(f"/api/projects/p/studies/{not_run}/values").status_code == 404
    assert client.get("/api/projects/p/studies/99/values").status_code == 404


def test_simulate_with_no_study_that_can_run_is_422(service):
    client, worker, engine = service
    reply = client.post("/api/projects/p/simulate")
    assert reply.status_code == 422 and reply.json()["detail"] == "Add a study to run."
    add_study(worker.store, "p", files=())
    reply = client.post("/api/projects/p/simulate")
    assert reply.status_code == 422 and reply.json()["detail"] == "No study can run. Sky view factor: Add test surfaces."
    assert engine.requests == [] and worker.active_project() is None
    assert client.post("/api/projects/nope/simulate").status_code == 404


def test_cancel_stops_a_simulation(tmp_path):
    handler = WaitsForCancel()
    client, worker = build_client(tmp_path / "projects", handle_request=handler)
    create_project_with_inputs(client)
    add_study(worker.store, "p", files=("surface.ply",))
    add_study(worker.store, "p", files=("surface.ply",))
    run_id = client.post("/api/projects/p/simulate").json()["run_id"]
    assert handler.started.wait(10)
    assert client.post(f"/api/runs/{run_id}/cancel").json() == {"cancelled": True}
    assert read_events(client, run_id)[-1] == {"type": "run_cancelled"}
    assert worker.active_project() is None
    handler.started.clear()
    again = client.post("/api/projects/p/simulate")        # the worker is free again
    assert again.status_code == 200 and handler.started.wait(10)
    worker.cancel(again.json()["run_id"])
    wait_until_finished(worker, again.json()["run_id"])
