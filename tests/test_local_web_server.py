"""The HTTP service of the local web app: security checks, routes, run events, files and the device warm-up state.

The engine is replaced by the fake of local_web_test_support.py, so a run writes the files of a finished run
without computing anything. Requests go through ``TestClient`` with the Host the service expects.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import warnings
import zipfile
from pathlib import Path

import pytest
import send2trash
import yaml
from starlette.websockets import WebSocketDisconnect

with warnings.catch_warnings():     # newer Starlette versions announce that TestClient will need httpx2; the project pins httpx
    warnings.filterwarnings("ignore", message=".*httpx.*testclient|.*testclient.*httpx", category=Warning)
    from starlette.testclient import TestClient

from local_web_test_support import (
    GOLDEN_EPW, FakeRecycleBin, WaitsForCancel, box_bytes, has_vertex_normals, make_link_to_folder, make_worker, write_fake_finished_run_with_envelope,
    write_fake_run, write_joined_test_surfaces_without_normals,
)
from urbansolarcarver import __version__
from urbansolarcarver.local_web_service import create_app
from urbansolarcarver.local_web_service import folder_picker, folder_picker_child, user_preferences
from urbansolarcarver.local_web_service.folder_picker import FolderPickerUnavailable
from urbansolarcarver.local_web_service.gpu_warm_up import GpuWarmUp
from urbansolarcarver.local_web_service.projects import ProjectStore
from urbansolarcarver.local_web_service.server import (
    WEBSOCKET_CLOSE_FORBIDDEN, WEBSOCKET_CLOSE_UNAUTHORIZED, WEBSOCKET_CLOSE_UNKNOWN_RUN, openapi_document,
)
from urbansolarcarver.mode_registry import MODES
from urbansolarcarver.stage_settings import PIPELINE_STAGES

TOKEN = "a" * 64
PORT = 8770
AUTH = {"X-USC-Token": TOKEN}
LAST_EVENT_TYPES = ("run_finished", "run_failed", "run_cancelled")
VOLUME = ("volume.ply", box_bytes([0, 0, 5]))
SURFACE = ("surface.ply", box_bytes([0, 0, 0], extents=(6, 6, 0.1)))


def build_client(projects_folder, handle_request=None, authorized=True, warm_up=None, static_folder=None,
                 projects_folder_source="default", choose_folder_function=None, open_folder_function=None):
    """A client for a service whose worker uses *handle_request* (the fake engine by default); the client and the worker."""
    worker = make_worker(ProjectStore(projects_folder), handle_request=handle_request)
    extra_arguments = {}
    if choose_folder_function is not None:
        extra_arguments["choose_folder_function"] = choose_folder_function
    if open_folder_function is not None:
        extra_arguments["open_folder_function"] = open_folder_function
    app = create_app(projects_folder, TOKEN, PORT, worker=worker, warm_up=warm_up, static_folder=static_folder,
                     projects_folder_source=projects_folder_source, **extra_arguments)
    client = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", headers=AUTH if authorized else None)
    return client, worker


def upload(client, name, role, file):
    file_name, data = file
    return client.post(f"/api/projects/{name}/inputs/{role}", files={"file": (file_name, data, "application/octet-stream")})


def create_project(client, name="p", mode="daylight"):
    reply = client.post("/api/projects", json={"name": name, "mode": mode})
    assert reply.status_code == 200, reply.text
    return reply.json()


def create_project_with_inputs(client, name="p", mode="daylight"):
    create_project(client, name, mode)
    assert upload(client, name, "max_volume", VOLUME).status_code == 200
    assert upload(client, name, "test_surfaces", SURFACE).status_code == 200


def events_url(run_id, query=f"?token={TOKEN}"):
    """The WebSocket address of a run (TestClient takes the Host from an absolute URL)."""
    return f"ws://127.0.0.1:{PORT}/api/runs/{run_id}/events{query}"


def read_events(client, run_id):
    """Every event the WebSocket sends for a run, up to the server closing it."""
    events = []
    with client.websocket_connect(events_url(run_id)) as websocket:
        while True:
            events.append(websocket.receive_json())
            if events[-1]["type"] in LAST_EVENT_TYPES:
                break
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()        # the server closes after the last event
    return events


def start_run(client, name="p", produce=("exporting", "massing")):
    reply = client.post(f"/api/projects/{name}/runs", json={"produce": list(produce)})
    assert reply.status_code == 200, reply.text
    return reply.json()


@pytest.fixture
def projects_folder(tmp_path):
    return tmp_path / "projects"


@pytest.fixture
def client(projects_folder):
    return build_client(projects_folder)[0]


@pytest.fixture
def client_with_inputs(client):
    create_project_with_inputs(client)
    return client


@pytest.fixture
def client_after_fake_run(client_with_inputs):
    run_id = start_run(client_with_inputs)["run_id"]
    assert read_events(client_with_inputs, run_id)[-1]["type"] == "run_finished"
    return client_with_inputs


@pytest.fixture
def client_with_blocking_run(projects_folder):
    """A project 'p' whose run has started and waits until it is cancelled; yields the client and the run id."""
    handler = WaitsForCancel()
    client, worker = build_client(projects_folder, handle_request=handler)
    create_project_with_inputs(client)
    run_id = start_run(client)["run_id"]
    assert handler.started.wait(10)
    yield client, run_id
    worker.cancel(run_id)
    worker.run_state(run_id).wait_for_events(10 ** 9, 10)     # returns when the run has ended


# ---- Security ----

def test_token_and_host_are_checked(projects_folder):
    bare_client = build_client(projects_folder, authorized=False)[0]
    assert bare_client.get("/api/health").status_code == 401
    assert bare_client.get("/api/health", headers={"X-USC-Token": "wrong"}).status_code == 401
    assert bare_client.get("/api/health", headers={"X-USC-Token": TOKEN, "Host": "evil.example:8770"}).status_code == 403
    assert bare_client.get("/api/health", headers={"X-USC-Token": TOKEN, "Host": "127.0.0.1:9999"}).status_code == 403
    assert bare_client.get("/api/health", headers={"Host": "evil.example:8770"}).status_code == 403   # the Host check comes first
    assert bare_client.get("/api/modes", headers=AUTH).status_code == 200
    assert bare_client.get("/api/modes", headers={**AUTH, "Host": f"localhost:{PORT}"}).status_code == 200
    assert bare_client.get("/api/health", headers={"X-USC-Token": ("é" * 64).encode("latin-1")}).status_code == 401   # not ASCII: refused, not an error


@pytest.fixture
def static_folder(tmp_path):
    folder = tmp_path / "ui_static"
    folder.mkdir()
    (folder / "index.html").write_text("<title>front end</title>", encoding="utf-8")
    return folder


def test_static_index_needs_no_token_but_the_host_is_checked(projects_folder, static_folder):
    bare_client = build_client(projects_folder, authorized=False, static_folder=static_folder)[0]
    index = bare_client.get("/")
    assert index.status_code == 200 and "front end" in index.text
    assert bare_client.get("/", headers={"Host": "evil.example:8770"}).status_code == 403
    assert bare_client.get("/api/health").status_code == 401      # the front end being served does not open the API


def test_without_a_built_front_end_the_api_is_still_served(projects_folder, tmp_path):
    client = build_client(projects_folder, static_folder=tmp_path / "missing")[0]
    assert client.get("/").status_code == 404
    assert client.get("/api/health").status_code == 200


def receive_close_code(client, url, **options):
    """The close code the server answers a WebSocket connection with, when it sends no event first."""
    with client.websocket_connect(url, **options) as websocket:
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()
    return closed.value.code


def test_websocket_without_token_is_refused(client):
    assert receive_close_code(client, events_url("anything", "")) == WEBSOCKET_CLOSE_UNAUTHORIZED
    assert receive_close_code(client, events_url("anything", "?token=wrong")) == WEBSOCKET_CLOSE_UNAUTHORIZED
    assert receive_close_code(client, events_url("anything"), headers={"Host": "evil.example:8770"}) == WEBSOCKET_CLOSE_FORBIDDEN
    assert (WEBSOCKET_CLOSE_UNAUTHORIZED, WEBSOCKET_CLOSE_FORBIDDEN, WEBSOCKET_CLOSE_UNKNOWN_RUN) == (4401, 4403, 4404)


def test_websocket_of_an_unknown_run_is_closed(client):
    assert receive_close_code(client, events_url("unknown")) == WEBSOCKET_CLOSE_UNKNOWN_RUN


@pytest.mark.slow
def test_a_real_server_gives_the_browser_the_refusal_codes(projects_folder):
    """Through uvicorn and a WebSocket client, as a browser connects: a close before the accept would arrive as code 1006."""
    import socket
    import uvicorn
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app = create_app(projects_folder, TOKEN, port, worker=make_worker(ProjectStore(projects_folder)))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started:
            assert time.monotonic() < deadline and server_thread.is_alive(), "the server did not start"
            time.sleep(0.02)

        def close_code(query, host="127.0.0.1"):
            # the socket goes to the server whatever the address in the URL, so the URL sets the Host header
            with connect(f"ws://{host}:{port}/api/runs/anything/events{query}",
                         sock=socket.create_connection(("127.0.0.1", port))) as websocket:
                with pytest.raises(ConnectionClosed) as closed:
                    websocket.recv(timeout=10)
            return closed.value.rcvd.code

        assert close_code("?token=wrong") == WEBSOCKET_CLOSE_UNAUTHORIZED
        assert close_code(f"?token={TOKEN}", host="evil.example") == WEBSOCKET_CLOSE_FORBIDDEN
        assert close_code(f"?token={TOKEN}") == WEBSOCKET_CLOSE_UNKNOWN_RUN
    finally:
        server.should_exit = True
        server_thread.join(timeout=20)


# ---- Basics ----

def test_health_reports_the_warm_up_state(projects_folder):
    client = build_client(projects_folder)[0]
    health = client.get("/api/health").json()
    assert health == {"version": __version__,
                      "warm_up": {"state": "not_started", "device_name": None, "problem": None, "cuda_available": None}}
    warm_up = GpuWarmUp("auto", warm_up_function=lambda device: "Test GPU")
    warm_up.start()
    client = build_client(projects_folder, warm_up=warm_up)[0]
    wait_for_warm_up(warm_up)
    assert client.get("/api/health").json()["warm_up"] == {
        "state": "ready", "device_name": "Test GPU", "problem": None, "cuda_available": True}


def test_schema_and_modes(client):
    assert "voxel_size" in client.get("/api/schema").json()["properties"]
    modes = client.get("/api/modes").json()
    assert [mode["name"] for mode in modes] == list(MODES)
    time_based = modes[0]
    assert set(time_based) == {"name", "description", "needs_epw", "needs_period", "experimental", "score_kind", "weight_unit",
                               "starting_values"}
    assert time_based["needs_epw"] is True and time_based["starting_values"]["start_month"] == 12
    assert next(mode for mode in modes if mode["name"] == "radiative_cooling")["experimental"] is True


def test_the_openapi_document_describes_the_routes():
    document = openapi_document()
    assert "/api/health" in document["paths"] and "/api/projects/{name}/runs" in document["paths"]
    assert {"WarmUpState", "StageStatusReply", "ConfigErrorReply", "ProjectDetail"} <= set(document["components"]["schemas"])


@pytest.mark.slow
def test_importing_the_service_does_not_load_torch():
    code = "import sys; import urbansolarcarver.local_web_service.server; print('torch' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"


# ---- Projects, inputs, settings and runs ----

def test_project_inputs_config_run_and_files(client):
    created = create_project(client, "p", "tilted_plane")
    assert created["settings"]["mode"] == "tilted_plane" and created["inputs"] == {"max_volume": [], "test_surfaces": [], "weather": []}
    assert created["stage_status"]["stages"] == {stage: "missing" for stage in PIPELINE_STAGES}
    uploaded = upload(client, "p", "max_volume", VOLUME).json()
    assert uploaded["files"] == [{"name": "volume.ply", "triangle_count": 12}] and uploaded["joined_bounds"] is not None
    assert upload(client, "p", "test_surfaces", SURFACE).status_code == 200
    saved = client.put("/api/projects/p/config", json={"values": {"mode": "tilted_plane", "voxel_size": 2.0}})
    assert saved.status_code == 200 and saved.json()["grid_plan"]["voxel_size"] == 2.0
    started = start_run(client)
    assert started["status"] == "started" and started["stages"] == list(PIPELINE_STAGES)
    events = read_events(client, started["run_id"])
    assert events[0] == {"type": "stage_progress", "stage": "preprocessing", "done": 0, "total": 1}
    assert events[-1]["type"] == "run_finished" and "run_report.md" in events[-1]["files"]
    assert read_events(client, started["run_id"]) == events                  # a later connection gets them all again
    assert client.get("/api/projects/p/run/files/run_report.md").text == "report"
    assert client.get("/api/projects/p/run/files/massing/plates.json").status_code == 200
    opened = client.get("/api/projects/p").json()
    assert opened["settings"]["voxel_size"] == 2.0 and opened["inputs"]["max_volume"][0]["name"] == "volume.ply"
    assert opened["stage_status"]["stages"] == {stage: "current" for stage in PIPELINE_STAGES}
    assert [row["name"] for row in client.get("/api/projects").json()] == ["p"]
    assert start_run(client)["status"] == "up_to_date"


def test_an_opened_project_carries_the_grid_of_its_stored_settings_without_changing_it(client, projects_folder):
    assert create_project(client, "p", "daylight")["grid_plan"] is None          # no max volume yet
    assert upload(client, "p", "max_volume", VOLUME).status_code == 200
    saved = client.put("/api/projects/p/config", json={"values": {"mode": "daylight", "voxel_size": 2.0}}).json()
    config_path = projects_folder / "p" / "config.yaml"
    config_before = config_path.read_bytes()
    first, second = client.get("/api/projects/p").json(), client.get("/api/projects/p").json()
    assert first["grid_plan"] == saved["grid_plan"]
    assert second["modified"] == first["modified"] and config_path.read_bytes() == config_before


def test_an_opened_project_over_the_voxel_budget_still_gets_its_grid(client):
    create_project(client, "p", "daylight")
    assert upload(client, "p", "max_volume", VOLUME).status_code == 200
    assert client.put("/api/projects/p/config", json={"values": {"mode": "daylight", "voxel_size": 1.0}}).status_code == 200
    larger_volume = ("volume.ply", box_bytes([0, 0, 5], extents=(10_000, 10_000, 10)))     # replaces the first upload
    assert upload(client, "p", "max_volume", larger_volume).status_code == 200
    grid_plan = client.get("/api/projects/p").json()["grid_plan"]
    assert grid_plan["voxel_size"] == 1.0 and grid_plan["total_voxels"] > grid_plan["budget_voxels"]


@pytest.mark.parametrize("edit_config", [
    lambda config: {**config, "voxel_size": -1},    # a setting the engine refuses
    lambda config: None,                            # an empty file
    lambda config: ["not", "a", "mapping"],
])
def test_a_project_whose_config_yaml_does_not_validate_still_opens(client_after_fake_run, projects_folder, edit_config):
    client = client_after_fake_run
    config_path = projects_folder / "p" / "config.yaml"
    edited = edit_config(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    config_path.write_text("" if edited is None else yaml.safe_dump(edited), encoding="utf-8")
    opened = client.get("/api/projects/p")
    assert opened.status_code == 200, opened.text
    assert opened.json()["stage_status"]["stages"] == {stage: "out_of_date" for stage in PIPELINE_STAGES}
    assert opened.json()["grid_plan"] is None
    assert client.get("/api/projects/p/stage-status").json()["stages"] == {stage: "out_of_date" for stage in PIPELINE_STAGES}
    refused_run = client.post("/api/projects/p/runs", json={"produce": ["thresholding"]})
    assert refused_run.status_code == 422 and refused_run.json()["field_errors"]
    saved = client.put("/api/projects/p/config", json={"values": {"mode": "daylight", "voxel_size": 2.0}})
    assert saved.status_code == 200 and client.get("/api/projects/p").json()["grid_plan"]["voxel_size"] == 2.0


def test_a_project_whose_config_yaml_has_a_yaml_syntax_error_opens_with_empty_settings(client_with_inputs, projects_folder):
    client = client_with_inputs
    assert read_events(client, start_run(client, produce=["thresholding"])["run_id"])[-1]["type"] == "run_finished"
    (projects_folder / "p" / "config.yaml").write_text("mode: daylight\nvoxel_size: [1.0\n", encoding="utf-8")
    assert [row["name"] for row in client.get("/api/projects").json()] == ["p"]
    opened = client.get("/api/projects/p")
    assert opened.status_code == 200, opened.text
    assert opened.json()["settings"] == {} and opened.json()["grid_plan"] is None
    assert opened.json()["stage_status"]["stages"] == {
        "preprocessing": "out_of_date", "thresholding": "out_of_date", "exporting": "missing", "massing": "missing"}
    saved = client.put("/api/projects/p/config", json={"values": {"mode": "daylight", "voxel_size": 2.0}})
    assert saved.status_code == 200, saved.text
    repaired = client.get("/api/projects/p").json()
    assert repaired["settings"]["mode"] == "daylight" and repaired["grid_plan"]["voxel_size"] == 2.0


def test_a_project_file_that_is_not_utf8_hides_only_its_own_project(client, projects_folder):
    for name in ("bad json", "bad config", "good"):
        create_project(client, name)
    (projects_folder / "bad json" / "project.json").write_bytes('{"name": "bad json", "created": "café"}'.encode("cp1252"))
    (projects_folder / "bad config" / "config.yaml").write_bytes("# café, saved in a legacy code page\nmode: daylight\n".encode("cp1252"))
    listed = client.get("/api/projects")
    assert listed.status_code == 200 and [row["name"] for row in listed.json()] == ["good"]
    assert client.get("/api/projects/bad json").status_code == 422


def test_opening_a_project_rebuilds_a_joined_test_surface_file_written_without_normals(client_after_fake_run, projects_folder):
    store = ProjectStore(projects_folder)
    assert set(client_after_fake_run.get("/api/projects/p").json()["stage_status"]["stages"].values()) == {"current"}
    joined_path = write_joined_test_surfaces_without_normals(store, "p")
    stages = client_after_fake_run.get("/api/projects/p").json()["stage_status"]["stages"]
    assert has_vertex_normals(joined_path) and set(stages.values()) == {"out_of_date"}


def test_a_project_whose_old_joined_file_cannot_be_rebuilt_still_opens(client_with_inputs, projects_folder):
    """An uploaded file missing on disk: the project opens with its old joined file, and the file can be removed."""
    store = ProjectStore(projects_folder)
    write_joined_test_surfaces_without_normals(store, "p")
    (projects_folder / "p" / "inputs" / "test_surfaces" / "surface.ply").unlink()
    assert client_with_inputs.get("/api/projects/p").status_code == 200
    assert client_with_inputs.delete("/api/projects/p/inputs/test_surfaces/surface.ply").status_code == 200


def test_the_examples_are_listed_with_a_description(client):
    examples = client.get("/api/examples").json()
    assert [example["name"] for example in examples] == ["basic_perimeter_block", "new_building", "multiple_buildings"]
    assert all(set(example) == {"name", "title", "description", "project"} and example["title"] and example["description"] for example in examples)


def test_example_project_joins_two_test_surface_files(client):
    created = client.post("/api/projects/nb/examples/new_building")
    assert created.status_code == 200, created.text
    detail = created.json()
    assert [file["name"] for file in detail["inputs"]["max_volume"]] == ["max_volume.ply"]
    assert [file["name"] for file in detail["inputs"]["test_surfaces"]] == ["neighbor_roofs.ply", "neighbor_windows.ply"]
    assert [file["name"] for file in detail["inputs"]["weather"]] == ["weather.epw"]
    assert detail["settings"]["mode"] == "irradiance" and detail["joined_bounds"] is not None and detail["weather_location"]
    triangle_counts = [file["triangle_count"] for file in detail["inputs"]["test_surfaces"]]
    assert all(triangle_counts) and client.get("/api/projects/nb/inputs/test_surfaces").json() == detail["inputs"]["test_surfaces"]
    assert [row["name"] for row in client.get("/api/projects").json()] == ["nb"]


def test_every_example_creates_a_project_with_the_files_it_lists(client):
    for example in client.get("/api/examples").json():
        detail = client.post(f"/api/projects/{example['name']}/examples/{example['name']}").json()
        assert detail["inputs"]["max_volume"] and detail["inputs"]["test_surfaces"] and detail["inputs"]["weather"]
        assert detail["settings"]["mode"] in MODES


def test_an_example_cannot_replace_a_project_or_use_a_bad_name(client):
    create_project(client, "p")
    assert client.post("/api/projects/p/examples/new_building").status_code == 409
    assert client.post("/api/projects/not.a.name/examples/new_building").status_code == 422
    assert client.post("/api/projects/q/examples/no_such_example").status_code == 404
    assert [row["name"] for row in client.get("/api/projects").json()] == ["p"]      # no folder left behind


def test_input_files_can_be_listed_fetched_and_removed(client_with_inputs):
    client = client_with_inputs
    assert client.get("/api/projects/p/inputs/max_volume").json() == [{"name": "volume.ply", "triangle_count": 12}]
    assert client.get("/api/projects/p/inputs/max_volume/volume.ply").content.startswith(b"ply")
    assert client.get("/api/projects/p/inputs/max_volume/other.ply").status_code == 404
    assert client.get("/api/projects/p/inputs/nonsense").status_code == 422
    removed = client.delete("/api/projects/p/inputs/max_volume/volume.ply")
    assert removed.status_code == 200 and removed.json()["files"] == [] and removed.json()["joined_bounds"] is None
    assert upload(client, "p", "max_volume", ("model.txt", b"not a mesh")).status_code == 422


def test_creating_a_project_reports_bad_names_modes_and_duplicates(client):
    create_project(client, "p")
    assert client.post("/api/projects", json={"name": "p", "mode": "daylight"}).status_code == 409
    assert client.post("/api/projects", json={"name": "../escape", "mode": "daylight"}).status_code == 422
    unknown_mode = client.post("/api/projects", json={"name": "q", "mode": "no-such-mode"})
    assert unknown_mode.status_code == 422 and unknown_mode.json()["field_errors"][0]["field"] == "mode"
    assert [row["name"] for row in client.get("/api/projects").json()] == ["p"]      # no folder left behind
    assert client.get("/api/projects/missing").status_code == 404


def test_invalid_setting_is_422_with_the_field(client_with_inputs):
    reply = client_with_inputs.put("/api/projects/p/config", json={"values": {"mode": "daylight", "voxel_size": 0.0}})
    assert reply.status_code == 422
    assert reply.json()["field_errors"][0]["field"] == "voxel_size" and reply.json()["grid_plan"] is None
    assert client_with_inputs.get("/api/projects/p").json()["settings"].get("voxel_size") != 0.0   # nothing was stored


def test_grid_over_budget_reply_carries_the_plan(client_with_inputs):
    reply = client_with_inputs.put("/api/projects/p/config", json={"values": {"mode": "daylight", "voxel_size": 0.0125, "grid_step": 0.0125}})
    assert reply.status_code == 422
    assert reply.json()["field_errors"][0]["field"] == "voxel_size"
    assert reply.json()["grid_plan"]["budget_voxels"] == 500_000_000 and reply.json()["grid_plan"]["total_voxels"] > 500_000_000


def test_missing_inputs_are_422_with_their_roles(client):
    create_project(client, "p", "time-based")
    reply = client.post("/api/projects/p/runs", json={"produce": ["thresholding"]})
    assert reply.status_code == 422 and reply.json()["missing_inputs"] == ["max_volume", "test_surfaces", "weather"]
    assert "max_volume" in reply.json()["detail"]


def test_unknown_stages_in_produce_are_422(client_with_inputs):
    for produce in (["thresholding", "polishing"], []):
        reply = client_with_inputs.post("/api/projects/p/runs", json={"produce": produce})
        assert reply.status_code == 422 and "produce" in reply.json()["detail"]


def test_a_run_without_produce_builds(client_with_inputs):
    reply = client_with_inputs.post("/api/projects/p/runs", json={})
    assert reply.json()["stages"] == list(PIPELINE_STAGES)


# ---- A run in progress ----

def test_changes_during_a_run_are_409(client_with_blocking_run):
    client, run_id = client_with_blocking_run
    assert upload(client, "p", "max_volume", VOLUME).status_code == 409
    assert client.delete("/api/projects/p/inputs/max_volume/volume.ply").status_code == 409
    assert client.put("/api/projects/p/config", json={"values": {"mode": "daylight"}}).status_code == 409
    assert "p" in client.put("/api/projects/p/config", json={"values": {"mode": "daylight"}}).json()["detail"]
    create_project_with_inputs(client, "other")         # another project is free to change
    assert client.put("/api/projects/other/config", json={"values": {"mode": "daylight"}}).status_code == 200


def test_second_run_is_409(client_with_blocking_run):
    client, run_id = client_with_blocking_run
    assert client.post("/api/projects/p/runs", json={"produce": ["thresholding"]}).status_code == 409
    create_project_with_inputs(client, "other")
    assert client.post("/api/projects/other/runs", json={"produce": ["thresholding"]}).status_code == 409


def test_cancel_ends_the_event_stream_with_run_cancelled(client_with_blocking_run):
    client, run_id = client_with_blocking_run
    assert client.post("/api/runs/unknown/cancel").status_code == 404
    events = []
    with client.websocket_connect(events_url(run_id)) as websocket:
        threading.Timer(0.3, lambda: client.post(f"/api/runs/{run_id}/cancel")).start()     # while the socket waits for events
        while not events or events[-1]["type"] not in LAST_EVENT_TYPES:
            events.append(websocket.receive_json())
    assert events[-1] == {"type": "run_cancelled"}
    assert client.post(f"/api/runs/{run_id}/cancel").json() == {"cancelled": False}      # the run has ended
    assert client.put("/api/projects/p/config", json={"values": {"mode": "daylight"}}).status_code == 200   # and frees the project


# ---- Results ----

def test_files_outside_the_run_folder_are_404(client_after_fake_run):
    client = client_after_fake_run
    assert client.get("/api/projects/p/run/files/run_report.md").status_code == 200
    for path in ("..%2Fproject.json", "..%2Fconfig.yaml", "%2E%2E%2F%2E%2E%2Fp%2Fproject.json", "C:%5CWindows%5Cwin.ini",
                 "%2Fetc%2Fpasswd", "massing", "nothing.txt"):
        assert client.get(f"/api/projects/p/run/files/{path}").status_code == 404, path


def test_stage_status_summary_and_sky_dome_routes(projects_folder):
    client = build_client(projects_folder)[0]
    create_project_with_inputs(client, "p", "tilted_plane")
    assert client.get("/api/projects/p/stage-status").json() == {"stages": {stage: "missing" for stage in PIPELINE_STAGES}}
    events = read_events(client, start_run(client)["run_id"])
    assert events[-1]["type"] == "run_finished"
    assert client.get("/api/projects/p/stage-status").json() == {"stages": {stage: "current" for stage in PIPELINE_STAGES}}
    summary = client.get("/api/projects/p/run/summary")
    assert summary.status_code == 200 and "carving" in summary.json() and "massing" in summary.json()
    assert client.get("/api/projects/p/run/sky-patches").status_code == 404
    assert client.get("/api/projects/p/run/score-points").status_code == 404


def test_results_of_a_finished_run_are_served(client_with_inputs, tmp_path):
    client = client_with_inputs
    project_run_folder = ProjectStore(tmp_path / "projects").open("p") / "run"
    shutil.copytree(write_fake_finished_run_with_envelope(tmp_path / "scratch", obstruction_fraction_carved=0.35), project_run_folder,
                    dirs_exist_ok=True)
    summary = client.get("/api/projects/p/run/summary").json()
    assert summary["carving"]["voxels_kept"] == 61 and summary["carving"]["obstruction_fraction_carved"] == 0.35
    assert summary["massing"]["total_floor_area_m2"] == 200.0
    # No run of this project recorded exporting, so the envelope's voxel size is the stored one.
    voxel_size = ProjectStore(tmp_path / "projects").load_project_config("p").voxel_size
    assert summary["envelope"]["envelope_volume_m3"] == pytest.approx(50 * voxel_size ** 3)
    score_points = client.get("/api/projects/p/run/score-points")
    assert score_points.status_code == 200 and score_points.headers["content-type"] == "application/octet-stream"
    assert len(score_points.content) > 4


def test_sky_dome_of_a_weighted_run(client_with_inputs, tmp_path):
    client = client_with_inputs
    shutil.copytree(write_fake_run(tmp_path / "scratch", with_patch_weights=True),
                    ProjectStore(tmp_path / "projects").open("p") / "run", dirs_exist_ok=True)
    dome = client.get("/api/projects/p/run/sky-patches")
    assert dome.status_code == 200
    assert len(dome.json()["directions"]) == len(dome.json()["weights"]) == len(dome.json()["solid_angles"]) == 145


def test_sun_path_is_empty_without_weather(client):
    create_project(client, "p", "time-based")
    assert client.get("/api/projects/p/sun-path").json() == {"days": []}
    create_project(client, "q", "daylight")
    assert client.get("/api/projects/q/sun-path").json() == {"days": []}


@pytest.mark.skipif(not GOLDEN_EPW.is_file(), reason="the bundled weather file is missing")
def test_sun_path_follows_the_uploaded_weather_file(client):
    create_project(client, "p", "time-based")
    uploaded = upload(client, "p", "weather", ("golden.epw", GOLDEN_EPW.read_bytes())).json()
    assert uploaded["weather_location"] is not None
    sun_path = client.get("/api/projects/p/sun-path").json()
    assert [day["date"] for day in sun_path["days"]] == ["12-21"]
    assert [marker["hour"] for marker in sun_path["days"][0]["markers"]] == [10, 12, 14]


def test_the_project_downloads_as_a_zip(client_after_fake_run):
    reply = client_after_fake_run.get("/api/projects/p/download")
    assert reply.status_code == 200 and reply.headers["content-type"] == "application/zip"
    assert "p.zip" in reply.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(reply.content)).namelist()
    assert {"p/project.json", "p/config.yaml", "p/run/run_report.md", "p/inputs/max_volume/volume.ply"} <= set(names)
    assert client_after_fake_run.get("/api/projects/missing/download").status_code == 404


def test_the_settings_download_as_config_yaml(client_with_inputs, projects_folder):
    reply = client_with_inputs.get("/api/projects/p/config.yaml")
    assert reply.status_code == 200 and "config.yaml" in reply.headers["content-disposition"]
    assert yaml.safe_load(reply.text)["mode"] == "daylight"
    assert client_with_inputs.get("/api/projects/missing/config.yaml").status_code == 404
    (projects_folder / "p" / "config.yaml").unlink()
    assert client_with_inputs.get("/api/projects/p/config.yaml").status_code == 404


# ---- The projects folder ----

@pytest.fixture
def home_folder(tmp_path, monkeypatch):
    """A home folder of its own, so the preference file of the user is never read or written."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    assert Path.home() == home
    return home


class FakeFolderPicker:
    """Stands in for the operating system's folder picker: answers with *answer* (a folder, None, or an exception to raise)."""

    def __init__(self, answer):
        self.answer = answer
        self.initial_folders = []

    def __call__(self, initial_folder):
        self.initial_folders.append(initial_folder)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_the_preference_file_is_in_the_home_folder(home_folder):
    assert user_preferences.preferences_file() == home_folder / ".urbansolarcarver" / "ui.json"


def test_the_projects_folder_preference_round_trips_and_creates_the_folder(home_folder, tmp_path):
    assert user_preferences.read_projects_folder_preference() is None
    chosen = tmp_path / "elsewhere" / "projects"
    user_preferences.write_projects_folder_preference(chosen)
    assert chosen.is_dir()
    assert user_preferences.read_projects_folder_preference() == chosen
    other = tmp_path / "other"
    user_preferences.write_projects_folder_preference(other)
    assert user_preferences.read_projects_folder_preference() == other
    assert [path.name for path in user_preferences.preferences_file().parent.iterdir()] == ["ui.json"]     # no temporary file is left


def test_writing_the_projects_folder_keeps_the_other_preferences(home_folder, tmp_path):
    user_preferences.preferences_file().parent.mkdir(parents=True)
    user_preferences.preferences_file().write_text(json.dumps({"something_else": 3}), encoding="utf-8")
    user_preferences.write_projects_folder_preference(tmp_path / "projects")
    stored = json.loads(user_preferences.preferences_file().read_text(encoding="utf-8"))
    assert stored == {"something_else": 3, "projects_folder": str(tmp_path / "projects")}


@pytest.mark.parametrize("content", [b"", b"{not json", b"\xff\xfe", b"[1, 2]", b'{"projects_folder": 7}', b'{"projects_folder": ""}', b"{}"])
def test_an_unreadable_preference_file_means_no_preference(home_folder, content):
    user_preferences.preferences_file().parent.mkdir(parents=True)
    user_preferences.preferences_file().write_bytes(content)
    assert user_preferences.read_projects_folder_preference() is None


def test_a_damaged_preference_file_is_replaced_by_the_next_write(home_folder, tmp_path):
    user_preferences.preferences_file().parent.mkdir(parents=True)
    user_preferences.preferences_file().write_bytes(b"{not json")
    user_preferences.write_projects_folder_preference(tmp_path / "projects")
    assert user_preferences.read_projects_folder_preference() == tmp_path / "projects"


@pytest.mark.parametrize("source, can_change", [("default", True), ("preference", True), ("command_line", False)])
def test_the_projects_folder_is_reported_with_its_source(projects_folder, source, can_change):
    client, _ = build_client(projects_folder, projects_folder_source=source)
    reply = client.get("/api/projects-folder")
    assert reply.status_code == 200
    assert reply.json() == {"path": str(projects_folder), "source": source, "can_change": can_change}


def test_the_projects_folder_cannot_be_changed_during_a_run(client_with_blocking_run):
    client, _ = client_with_blocking_run
    assert client.get("/api/projects-folder").json()["can_change"] is False


def test_choosing_a_folder_switches_the_projects_and_remembers_the_folder(projects_folder, tmp_path, home_folder):
    new_folder = tmp_path / "new projects"
    picker = FakeFolderPicker(new_folder)
    client, _ = build_client(projects_folder, projects_folder_source="default", choose_folder_function=picker)
    create_project(client, "old")
    ProjectStore(new_folder).create("in-new", "daylight")

    reply = client.post("/api/projects-folder/choose")

    assert reply.status_code == 200
    assert reply.json() == {"status": "changed", "path": str(new_folder), "problem": None}
    assert picker.initial_folders == [projects_folder]
    assert [project["name"] for project in client.get("/api/projects").json()] == ["in-new"]
    assert client.get("/api/projects-folder").json() == {"path": str(new_folder), "source": "preference", "can_change": True}
    assert user_preferences.read_projects_folder_preference() == new_folder
    assert (projects_folder / "old").is_dir()       # existing projects are not moved


def test_after_choosing_a_folder_new_projects_and_runs_use_it(projects_folder, tmp_path, home_folder):
    new_folder = tmp_path / "new projects"
    client, _ = build_client(projects_folder, choose_folder_function=FakeFolderPicker(new_folder))
    assert client.post("/api/projects-folder/choose").json()["status"] == "changed"
    create_project_with_inputs(client, "fresh")
    assert (new_folder / "fresh" / "project.json").is_file()
    assert not (projects_folder / "fresh").exists()
    run_id = start_run(client, "fresh")["run_id"]
    assert read_events(client, run_id)[-1]["type"] == "run_finished"
    assert (new_folder / "fresh" / "run").is_dir()


def test_choosing_the_same_folder_again_keeps_the_projects(projects_folder, home_folder):
    client, _ = build_client(projects_folder, choose_folder_function=FakeFolderPicker(projects_folder))
    create_project(client, "kept")
    assert client.post("/api/projects-folder/choose").json()["status"] == "changed"
    assert [project["name"] for project in client.get("/api/projects").json()] == ["kept"]


def test_cancelling_the_folder_picker_changes_nothing(projects_folder, home_folder):
    client, _ = build_client(projects_folder, choose_folder_function=FakeFolderPicker(None))
    create_project(client, "p")
    reply = client.post("/api/projects-folder/choose")
    assert reply.status_code == 200
    assert reply.json() == {"status": "cancelled", "path": str(projects_folder), "problem": None}
    assert [project["name"] for project in client.get("/api/projects").json()] == ["p"]
    assert client.get("/api/projects-folder").json()["source"] == "default"
    assert not user_preferences.preferences_file().exists()


def test_an_unavailable_folder_picker_names_the_problem_and_changes_nothing(projects_folder, home_folder):
    picker = FakeFolderPicker(FolderPickerUnavailable("There is no display to show the folder picker on."))
    client, _ = build_client(projects_folder, choose_folder_function=picker)
    create_project(client, "p")
    reply = client.post("/api/projects-folder/choose")
    assert reply.status_code == 200
    assert reply.json() == {"status": "unavailable", "path": str(projects_folder), "problem": "There is no display to show the folder picker on."}
    assert [project["name"] for project in client.get("/api/projects").json()] == ["p"]
    assert not user_preferences.preferences_file().exists()


def test_choosing_a_folder_during_a_run_is_409_and_does_not_open_the_picker(projects_folder, tmp_path, home_folder):
    handler = WaitsForCancel()
    picker = FakeFolderPicker(tmp_path / "new")
    client, worker = build_client(projects_folder, handle_request=handler, choose_folder_function=picker)
    create_project_with_inputs(client)
    run_id = start_run(client)["run_id"]
    assert handler.started.wait(10)
    try:
        reply = client.post("/api/projects-folder/choose")
        assert reply.status_code == 409
        assert "run" in reply.json()["detail"]
        assert picker.initial_folders == []
        assert not user_preferences.preferences_file().exists()
    finally:
        worker.cancel(run_id)
        worker.run_state(run_id).wait_for_events(10 ** 9, 10)


def test_a_run_that_starts_while_the_picker_is_open_blocks_the_change(projects_folder, tmp_path, home_folder):
    handler = WaitsForCancel()
    holder = {}

    def picker_while_a_run_starts(initial_folder):
        holder["run_id"] = start_run(holder["client"])["run_id"]
        assert handler.started.wait(10)
        return tmp_path / "new"

    client, worker = build_client(projects_folder, handle_request=handler, choose_folder_function=picker_while_a_run_starts)
    holder["client"] = client
    create_project_with_inputs(client)
    try:
        assert client.post("/api/projects-folder/choose").status_code == 409
        assert client.get("/api/projects-folder").json()["path"] == str(projects_folder)
        assert not user_preferences.preferences_file().exists()
    finally:
        worker.cancel(holder["run_id"])
        worker.run_state(holder["run_id"]).wait_for_events(10 ** 9, 10)


def test_a_second_choose_while_the_picker_is_open_is_409_and_the_first_still_completes(projects_folder, tmp_path, home_folder):
    picker_open = threading.Event()
    release_picker = threading.Event()
    new_folder = tmp_path / "new"

    def blocking_picker(initial_folder):
        picker_open.set()
        assert release_picker.wait(10)
        return new_folder

    client, _ = build_client(projects_folder, choose_folder_function=blocking_picker)
    first_reply = {}
    first_request = threading.Thread(target=lambda: first_reply.update(response=client.post("/api/projects-folder/choose")))
    first_request.start()
    try:
        assert picker_open.wait(10)
        second = client.post("/api/projects-folder/choose")
        assert second.status_code == 409
        assert "already open" in second.json()["detail"]
    finally:
        release_picker.set()
        first_request.join(10)
    assert first_reply["response"].json() == {"status": "changed", "path": str(new_folder), "problem": None}


def test_an_unknown_projects_folder_source_fails_at_startup(projects_folder):
    with pytest.raises(ValueError, match="projects_folder_source"):
        create_app(projects_folder, TOKEN, PORT, projects_folder_source="comand_line")


def test_a_folder_given_on_the_command_line_cannot_be_changed(projects_folder, tmp_path, home_folder):
    picker = FakeFolderPicker(tmp_path / "new")
    client, _ = build_client(projects_folder, projects_folder_source="command_line", choose_folder_function=picker)
    reply = client.post("/api/projects-folder/choose")
    assert reply.status_code == 409
    assert "--projects-folder" in reply.json()["detail"]
    assert picker.initial_folders == []
    assert not user_preferences.preferences_file().exists()


def test_a_folder_that_cannot_be_remembered_is_not_switched_to(projects_folder, tmp_path, home_folder, monkeypatch):
    def refuse(folder):
        raise OSError("disk is read-only")

    monkeypatch.setattr(user_preferences, "write_projects_folder_preference", refuse)
    client, _ = build_client(projects_folder, choose_folder_function=FakeFolderPicker(tmp_path / "new"))
    reply = client.post("/api/projects-folder/choose")
    assert reply.status_code == 422
    assert "disk is read-only" in reply.json()["detail"]
    assert client.get("/api/projects-folder").json()["path"] == str(projects_folder)


def test_the_folder_routes_need_the_token(projects_folder):
    client, _ = build_client(projects_folder, authorized=False)
    assert client.get("/api/projects-folder").status_code == 401
    assert client.post("/api/projects-folder/choose").status_code == 401


def test_the_openapi_document_describes_the_folder_routes():
    document = openapi_document()
    assert "ProjectsFolderReply" in document["components"]["schemas"]
    assert "ProjectsFolderChoiceReply" in document["components"]["schemas"]
    assert "/api/projects-folder" in document["paths"] and "/api/projects-folder/choose" in document["paths"]


# ---- The folder picker and the file manager ----

class FakeTkinter:
    """Stands in for the tkinter module and its filedialog: the Tk root records what was done to it."""

    TclError = type("TclError", (Exception,), {})

    def __init__(self, dialog_answer, no_display=False):
        self.log = []
        fake = self

        class Tk:
            def __init__(self):
                if no_display:
                    raise fake.TclError("no display name and no $DISPLAY environment variable")
                fake.log.append("root")

            def withdraw(self):
                fake.log.append("withdraw")

            def attributes(self, name, value):
                fake.log.append((name, value))

            def destroy(self):
                fake.log.append("destroy")

        def ask_directory(**options):
            fake.log.append(("ask", options["initialdir"]))
            return dialog_answer

        self.Tk = Tk
        self.filedialog = type("filedialog", (), {"askdirectory": staticmethod(ask_directory)})

    def install(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "tkinter", self)


def test_the_dialog_program_shows_a_hidden_topmost_dialog_and_destroys_it_afterwards(monkeypatch, tmp_path):
    fake = FakeTkinter(str(tmp_path / "chosen"))
    fake.install(monkeypatch)
    assert folder_picker_child.choose_folder_in_this_process(str(tmp_path)) == str(tmp_path / "chosen")
    assert fake.log == ["root", "withdraw", ("-topmost", True), ("ask", str(tmp_path)), "destroy"]


@pytest.mark.parametrize("cancelled_answer", ["", ()])
def test_a_cancelled_dialog_gives_none(monkeypatch, tmp_path, cancelled_answer):
    fake = FakeTkinter(cancelled_answer)
    fake.install(monkeypatch)
    assert folder_picker_child.choose_folder_in_this_process(str(tmp_path)) is None
    assert fake.log[-1] == "destroy"


def test_a_computer_without_a_display_makes_the_dialog_program_unavailable(monkeypatch, tmp_path):
    FakeTkinter("", no_display=True).install(monkeypatch)
    with pytest.raises(folder_picker_child.PickerUnavailable, match="display"):
        folder_picker_child.choose_folder_in_this_process(str(tmp_path))


def test_a_python_without_tkinter_makes_the_dialog_program_unavailable(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "tkinter", None)       # an import of a module set to None raises ImportError
    with pytest.raises(folder_picker_child.PickerUnavailable, match="tkinter"):
        folder_picker_child.choose_folder_in_this_process(str(tmp_path))


def test_the_dialog_program_answers_with_exit_codes_and_json(monkeypatch, tmp_path, capsys):
    greek_folder = tmp_path / "Έργα"
    FakeTkinter(str(greek_folder)).install(monkeypatch)
    assert folder_picker_child.main([str(tmp_path)]) == folder_picker_child.EXIT_CHOSEN
    assert json.loads(capsys.readouterr().out) == {"folder": str(greek_folder)}
    FakeTkinter("").install(monkeypatch)
    assert folder_picker_child.main([str(tmp_path)]) == folder_picker_child.EXIT_CANCELLED
    FakeTkinter("", no_display=True).install(monkeypatch)
    assert folder_picker_child.main([str(tmp_path)]) == folder_picker_child.EXIT_UNAVAILABLE
    assert "display" in capsys.readouterr().err


def test_an_unexpected_error_in_the_dialog_program_is_one_readable_line(monkeypatch, tmp_path, capsys):
    def dialog_that_breaks(initial_folder):
        raise RuntimeError("bad window path name")
    monkeypatch.setattr(folder_picker_child, "choose_folder_in_this_process", dialog_that_breaks)
    assert folder_picker_child.main([str(tmp_path)]) == folder_picker_child.EXIT_UNAVAILABLE
    assert capsys.readouterr().err == "The folder picker failed: bad window path name"


def test_the_dialog_program_ships_with_the_package():
    assert folder_picker.CHILD_SCRIPT.is_file() and folder_picker.CHILD_SCRIPT.parent == Path(folder_picker.__file__).parent


def use_fake_dialog_program(monkeypatch, tmp_path, source):
    """Replaces the dialog program by a script written for the test; choose_folder still starts it as a separate process."""
    script = tmp_path / "fake_dialog_program.py"
    script.write_text(source, encoding="utf-8")
    monkeypatch.setattr(folder_picker, "CHILD_SCRIPT", script)


def test_choose_folder_gives_the_folder_the_dialog_program_prints_even_with_greek_letters(monkeypatch, tmp_path):
    use_fake_dialog_program(monkeypatch, tmp_path, "import json, sys\nsys.stdout.write(json.dumps({'folder': sys.argv[1] + '/Έργα'}))\n")
    assert folder_picker.choose_folder(tmp_path / "αρχή") == Path(str(tmp_path / "αρχή") + "/Έργα")


def test_choose_folder_gives_none_when_the_dialog_program_reports_a_cancel(monkeypatch, tmp_path):
    use_fake_dialog_program(monkeypatch, tmp_path, f"import sys\nsys.exit({folder_picker_child.EXIT_CANCELLED})\n")
    assert folder_picker.choose_folder(tmp_path) is None


def test_choose_folder_is_unavailable_with_the_reason_the_dialog_program_gives(monkeypatch, tmp_path):
    use_fake_dialog_program(monkeypatch, tmp_path, f"import sys\nsys.stderr.write('There is no display.')\nsys.exit({folder_picker_child.EXIT_UNAVAILABLE})\n")
    with pytest.raises(FolderPickerUnavailable, match="There is no display."):
        folder_picker.choose_folder(tmp_path)


def test_the_reason_the_dialog_program_gives_keeps_its_greek_letters(monkeypatch, tmp_path):
    use_fake_dialog_program(monkeypatch, tmp_path, f"import sys\nsys.stderr.write('Δεν υπάρχει οθόνη.')\nsys.exit({folder_picker_child.EXIT_UNAVAILABLE})\n")
    with pytest.raises(FolderPickerUnavailable, match="Δεν υπάρχει οθόνη."):
        folder_picker.choose_folder(tmp_path)


def test_choose_folder_is_unavailable_when_the_dialog_program_crashes(monkeypatch, tmp_path):
    use_fake_dialog_program(monkeypatch, tmp_path, "raise RuntimeError('the dialog broke')\n")
    with pytest.raises(FolderPickerUnavailable, match="the dialog broke"):
        folder_picker.choose_folder(tmp_path)


def test_choose_folder_is_unavailable_when_the_dialog_program_stops_without_a_message(monkeypatch, tmp_path):
    use_fake_dialog_program(monkeypatch, tmp_path, "import os\nos._exit(3)\n")
    with pytest.raises(FolderPickerUnavailable, match="exit code 3"):
        folder_picker.choose_folder(tmp_path)


def test_choose_folder_is_unavailable_when_the_answer_cannot_be_read(monkeypatch, tmp_path):
    use_fake_dialog_program(monkeypatch, tmp_path, "print('not json')\n")
    with pytest.raises(FolderPickerUnavailable, match="cannot be read"):
        folder_picker.choose_folder(tmp_path)


def test_the_service_process_never_loads_tkinter_to_choose_a_folder(monkeypatch, tmp_path):
    monkeypatch.delitem(sys.modules, "tkinter", raising=False)
    use_fake_dialog_program(monkeypatch, tmp_path, "import json, sys\nsys.stdout.write(json.dumps({'folder': 'x'}))\n")
    folder_picker.choose_folder(tmp_path)
    assert "tkinter" not in sys.modules


@pytest.mark.parametrize("platform, expected_command", [("darwin", ["open"]), ("linux", ["xdg-open"])])
def test_the_folder_opens_in_the_file_manager_of_the_platform(monkeypatch, tmp_path, platform, expected_command):
    started = []
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(subprocess, "Popen", lambda command, *args, **kwargs: started.append(command))
    folder_picker.open_in_file_manager(tmp_path)
    assert started == [[*expected_command, str(tmp_path)]]


def test_the_folder_opens_in_explorer_on_windows(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(folder_picker.os, "startfile", lambda folder: opened.append(folder), raising=False)
    folder_picker.open_in_file_manager(tmp_path)
    assert opened == [tmp_path]


# ---- Rename, delete, reset, open folder and example links ----

@pytest.fixture
def recycle_bin(monkeypatch):
    bin_stub = FakeRecycleBin()
    monkeypatch.setattr(send2trash, "send2trash", bin_stub)
    return bin_stub


class RecordsOpenedFolders:
    def __init__(self):
        self.folders = []

    def __call__(self, folder):
        self.folders.append(folder)


def project_names(client):
    return [row["name"] for row in client.get("/api/projects").json()]


def test_rename_changes_the_name_and_returns_the_project(client_with_inputs, projects_folder):
    reply = client_with_inputs.post("/api/projects/p/rename", json={"new_name": "Block 2"})
    assert reply.status_code == 200, reply.text
    detail = reply.json()
    assert detail["name"] == "Block 2" and [file["name"] for file in detail["inputs"]["max_volume"]] == ["volume.ply"]
    assert detail["joined_bounds"] is not None and project_names(client_with_inputs) == ["Block 2"]
    assert not (projects_folder / "p").exists()
    assert client_with_inputs.get("/api/projects/p").status_code == 404


def test_rename_to_a_bad_name_is_422_and_to_an_existing_name_is_409_whatever_the_letter_case(client):
    create_project(client, "Block")
    create_project(client, "other")
    assert client.post("/api/projects/Block/rename", json={"new_name": "not.a.name"}).status_code == 422
    assert client.post("/api/projects/Block/rename", json={"new_name": "  "}).status_code == 422
    for existing in ("other", "OTHER", "block", "Block"):
        reply = client.post("/api/projects/Block/rename", json={"new_name": existing})
        assert reply.status_code == 409 and "letter case" in reply.json()["detail"], existing
    assert client.post("/api/projects/nothing/rename", json={"new_name": "fresh"}).status_code == 404
    assert client.post("/api/projects/Block/rename", json={}).status_code == 422
    assert project_names(client) == ["Block", "other"]


def test_delete_moves_the_project_folder_to_the_recycle_bin(client, projects_folder, recycle_bin):
    create_project(client, "gone")
    create_project(client, "kept")
    reply = client.delete("/api/projects/gone", params={"confirm_name": "gone"})
    assert reply.status_code == 204 and reply.content == b""
    assert recycle_bin.folders == [(projects_folder / "gone").resolve()]
    assert project_names(client) == ["kept"]


@pytest.mark.skipif(sys.platform != "win32", reason="folder names ignore letter case on Windows only")
def test_delete_compares_the_confirmation_with_the_stored_name_not_the_one_in_the_address(client, recycle_bin):
    create_project(client, "gone")
    assert client.delete("/api/projects/GONE", params={"confirm_name": "GONE"}).status_code == 422
    assert recycle_bin.folders == []
    assert client.delete("/api/projects/GONE", params={"confirm_name": "gone"}).status_code == 204
    assert len(recycle_bin.folders) == 1


def test_delete_needs_the_project_name_typed_exactly(client, recycle_bin):
    create_project(client, "gone")
    for wrong in ("Gone", "gon", "", "gone "):
        reply = client.delete("/api/projects/gone", params={"confirm_name": wrong})
        assert reply.status_code == 422, wrong
    assert client.delete("/api/projects/gone").status_code == 422       # no confirm_name at all
    assert recycle_bin.folders == [] and project_names(client) == ["gone"]


def test_delete_of_an_unknown_project_is_404_and_of_a_bad_name_is_422(client, recycle_bin):
    assert client.delete("/api/projects/nothing", params={"confirm_name": "nothing"}).status_code == 404
    assert client.delete("/api/projects/not.a.name", params={"confirm_name": "not.a.name"}).status_code == 422
    assert recycle_bin.folders == []


def test_delete_with_a_link_inside_is_422_and_the_folder_it_leads_to_is_untouched(client, projects_folder, tmp_path, recycle_bin):
    create_project(client, "p")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "precious.txt").write_text("keep", encoding="utf-8")
    make_link_to_folder(projects_folder / "p" / "inputs" / "linked", tmp_path / "outside", "junction" if sys.platform == "win32" else "symlink")
    reply = client.delete("/api/projects/p", params={"confirm_name": "p"})
    assert reply.status_code == 422 and "linked" in reply.json()["detail"]
    assert recycle_bin.folders == [] and (tmp_path / "outside" / "precious.txt").is_file() and (projects_folder / "p").is_dir()


def test_delete_when_the_recycle_bin_fails_is_422_with_the_reason(client, monkeypatch):
    monkeypatch.setattr(send2trash, "send2trash", FakeRecycleBin(error=OSError("the recycle bin is full")))
    create_project(client, "p")
    reply = client.delete("/api/projects/p", params={"confirm_name": "p"})
    assert reply.status_code == 422 and "the recycle bin is full" in reply.json()["detail"] and project_names(client) == ["p"]


def test_reset_to_the_example_gives_the_example_inputs_and_no_results(client, recycle_bin):
    assert client.post("/api/projects/mine/examples/new_building").status_code == 200
    assert client.put("/api/projects/mine/config", json={"values": {"mode": "daylight"}}).status_code == 200
    assert client.delete("/api/projects/mine/inputs/test_surfaces/neighbor_windows.ply").status_code == 200
    run_id = start_run(client, "mine")["run_id"]
    assert read_events(client, run_id)[-1]["type"] == "run_finished"
    reply = client.post("/api/projects/mine/reset-to-example")
    assert reply.status_code == 200, reply.text
    detail = reply.json()
    assert detail["name"] == "mine" and detail["settings"]["mode"] == "irradiance"
    assert [file["name"] for file in detail["inputs"]["test_surfaces"]] == ["neighbor_roofs.ply", "neighbor_windows.ply"]
    assert set(detail["stage_status"]["stages"].values()) == {"missing"}
    assert len(recycle_bin.folders) == 1 and project_names(client) == ["mine"]


def test_reset_is_422_for_a_project_that_is_not_from_an_example(client, recycle_bin):
    create_project(client, "plain")
    reply = client.post("/api/projects/plain/reset-to-example")
    assert reply.status_code == 422 and "example" in reply.json()["detail"]
    assert client.post("/api/projects/nothing/reset-to-example").status_code == 404
    assert recycle_bin.folders == []


def test_reset_finds_the_example_of_a_renamed_project(client, recycle_bin):
    assert client.post("/api/projects/first/examples/basic_perimeter_block").status_code == 200
    assert client.post("/api/projects/first/rename", json={"new_name": "Renamed"}).status_code == 200
    assert client.post("/api/projects/Renamed/reset-to-example").status_code == 200 and project_names(client) == ["Renamed"]


def test_reset_with_a_link_inside_is_422_and_changes_nothing(client, projects_folder, tmp_path, recycle_bin):
    assert client.post("/api/projects/mine/examples/new_building").status_code == 200
    (tmp_path / "outside").mkdir()
    make_link_to_folder(projects_folder / "mine" / "run" / "linked", tmp_path / "outside", "junction" if sys.platform == "win32" else "symlink")
    assert client.post("/api/projects/mine/reset-to-example").status_code == 422
    assert recycle_bin.folders == [] and client.get("/api/projects/mine").json()["inputs"]["max_volume"]


def test_open_folder_gives_the_opener_the_project_folder_only(projects_folder):
    opener = RecordsOpenedFolders()
    client, _ = build_client(projects_folder, open_folder_function=opener)
    create_project(client, "p")
    reply = client.post("/api/projects/p/open-folder")
    assert reply.status_code == 204 and reply.content == b""
    assert opener.folders == [(projects_folder / "p").resolve()]
    assert client.post("/api/projects/nothing/open-folder").status_code == 404
    assert client.post("/api/projects/not.a.name/open-folder").status_code == 422
    assert len(opener.folders) == 1


def test_open_folder_that_cannot_open_is_422_with_the_reason(projects_folder):
    def cannot_open(folder):
        raise OSError("no file manager is installed")

    client, _ = build_client(projects_folder, open_folder_function=cannot_open)
    create_project(client, "p")
    reply = client.post("/api/projects/p/open-folder")
    assert reply.status_code == 422 and "no file manager is installed" in reply.json()["detail"]


def test_rename_delete_and_reset_are_409_and_open_folder_is_not_during_a_run_of_the_project(projects_folder, recycle_bin):
    handler = WaitsForCancel()
    opener = RecordsOpenedFolders()
    client, worker = build_client(projects_folder, handle_request=handler, open_folder_function=opener)
    assert client.post("/api/projects/p/examples/new_building").status_code == 200
    run_id = start_run(client, "p")["run_id"]
    assert handler.started.wait(10)
    try:
        assert client.post("/api/projects/p/rename", json={"new_name": "q"}).status_code == 409
        assert client.post("/api/projects/P/rename", json={"new_name": "q"}).status_code == 409      # the name in another letter case
        assert client.delete("/api/projects/p", params={"confirm_name": "p"}).status_code == 409
        assert client.post("/api/projects/p/reset-to-example").status_code == 409
        assert recycle_bin.folders == [] and project_names(client) == ["p"]
        assert client.post("/api/projects/p/open-folder").status_code == 204        # R2 7.2 refuses only rename, delete and reset
        assert opener.folders == [(projects_folder / "p").resolve()]
    finally:
        worker.cancel(run_id)
        worker.run_state(run_id).wait_for_events(10 ** 9, 10)


def test_two_renames_in_opposite_directions_at_the_same_time_both_finish(projects_folder):
    """Each rename waits, right after the checks of its own project, for the other: they would deadlock if each held only its own lock then."""
    client, worker = build_client(projects_folder)
    create_project(client, "z")
    create_project(client, "a")
    meeting = threading.Barrier(2, timeout=1.0)

    def active_project_after_meeting_the_other_rename():
        try:
            meeting.wait()
        except threading.BrokenBarrierError:
            pass    # the other rename is waiting for a lock this one holds: it gets through only when both locks were taken together
        return None

    worker.active_project = active_project_after_meeting_the_other_rename
    statuses = {}

    def rename(old_name, new_name):
        statuses[old_name] = client.post(f"/api/projects/{old_name}/rename", json={"new_name": new_name}).status_code

    threads = [threading.Thread(target=rename, args=("z", "a"), daemon=True), threading.Thread(target=rename, args=("a", "z"), daemon=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    assert not any(thread.is_alive() for thread in threads), "the two renames wait for each other"
    assert statuses == {"z": 409, "a": 409}      # each new name is taken by the other project
    assert project_names(client) == ["a", "z"]


def test_a_renamed_project_keeps_the_results_of_its_run_current(client_after_fake_run):
    stages_before = client_after_fake_run.get("/api/projects/p/stage-status").json()["stages"]
    assert "current" in stages_before.values()
    renamed = client_after_fake_run.post("/api/projects/p/rename", json={"new_name": "q"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["stage_status"]["stages"] == stages_before
    assert client_after_fake_run.get("/api/projects/q/run/summary").status_code == 200


def test_another_project_can_be_changed_during_a_run(client_with_blocking_run):
    client, _ = client_with_blocking_run
    create_project(client, "other")
    assert client.post("/api/projects/other/rename", json={"new_name": "renamed"}).status_code == 200


def test_the_examples_report_the_project_made_from_them(client, projects_folder):
    assert [example["project"] for example in client.get("/api/examples").json()] == [None, None, None]
    for name, example in (("mine", "new_building"), ("Perimeter block", "basic_perimeter_block"), ("Perimeter block 2", "basic_perimeter_block")):
        assert client.post(f"/api/projects/{name}/examples/{example}").status_code == 200
    newer_seconds = (projects_folder / "Perimeter block" / "project.json").stat().st_mtime + 100
    os.utime(projects_folder / "Perimeter block 2" / "project.json", (newer_seconds, newer_seconds))
    projects_by_example = {example["name"]: example["project"] for example in client.get("/api/examples").json()}
    assert projects_by_example["new_building"] == "mine" and projects_by_example["multiple_buildings"] is None
    assert projects_by_example["basic_perimeter_block"] == "Perimeter block 2"      # the most recently modified of the two
    assert client.post("/api/projects/mine/rename", json={"new_name": "Renamed"}).status_code == 200
    assert {example["name"]: example["project"] for example in client.get("/api/examples").json()}["new_building"] == "Renamed"


def test_an_old_project_named_like_the_example_title_counts_as_from_the_example(client, projects_folder):
    create_project(client, "Perimeter block")      # no example field, as a project made before the field existed
    create_project(client, "Perimeter block 2")
    assert {example["name"]: example["project"] for example in client.get("/api/examples").json()}["basic_perimeter_block"] == "Perimeter block"


def test_the_project_list_and_the_opened_project_name_the_example_they_came_from(client):
    assert client.post("/api/projects/mine/examples/new_building").status_code == 200
    create_project(client, "plain")
    create_project(client, "Perimeter block")       # no example field, named like the example's title
    create_project(client, "Perimeter block 2")
    assert {row["name"]: row["example"] for row in client.get("/api/projects").json()} == {
        "mine": "new_building", "plain": None, "Perimeter block": "basic_perimeter_block", "Perimeter block 2": None}
    assert client.get("/api/projects/mine").json()["example"] == "new_building"
    assert client.get("/api/projects/plain").json()["example"] is None
    assert client.get("/api/projects/Perimeter block").json()["example"] == "basic_perimeter_block"
    assert client.get("/api/projects/Perimeter block 2").json()["example"] is None
    renamed = client.post("/api/projects/mine/rename", json={"new_name": "Renamed"}).json()
    assert renamed["example"] == "new_building"
    reset = client.post("/api/projects/Renamed/reset-to-example")
    assert reset.status_code == 200 and reset.json()["example"] == "new_building"


def test_the_new_routes_need_the_token(projects_folder):
    bare_client = build_client(projects_folder, authorized=False)[0]
    assert bare_client.post("/api/projects/p/rename", json={"new_name": "q"}).status_code == 401
    assert bare_client.delete("/api/projects/p", params={"confirm_name": "p"}).status_code == 401
    assert bare_client.post("/api/projects/p/reset-to-example").status_code == 401
    assert bare_client.post("/api/projects/p/open-folder").status_code == 401


def test_the_openapi_document_describes_the_project_management_routes():
    paths = openapi_document()["paths"]
    assert {"post"} <= set(paths["/api/projects/{name}/rename"]) and "delete" in paths["/api/projects/{name}"]
    assert "post" in paths["/api/projects/{name}/reset-to-example"] and "post" in paths["/api/projects/{name}/open-folder"]
    assert "204" in paths["/api/projects/{name}"]["delete"]["responses"] and "204" in paths["/api/projects/{name}/open-folder"]["post"]["responses"]
    examples_schema = openapi_document()["components"]["schemas"]["ExampleInfo"]
    assert "project" in examples_schema["properties"]
    assert all("example" in openapi_document()["components"]["schemas"][model]["properties"] for model in ("ProjectSummary", "ProjectDetail"))


# ---- Device warm-up ----

def wait_for_warm_up(warm_up, deadline_seconds=10.0):
    deadline = time.monotonic() + deadline_seconds
    while warm_up.state().state in ("not_started", "running"):
        assert time.monotonic() < deadline, "the warm-up did not end"
        time.sleep(0.01)
    return warm_up.state()


def test_warm_up_is_not_started_until_asked():
    calls = []
    warm_up = GpuWarmUp("auto", warm_up_function=calls.append)
    assert warm_up.state().state == "not_started" and calls == []


def test_warm_up_reports_the_device_name_when_ready():
    warm_up = GpuWarmUp("cuda", warm_up_function=lambda device: f"Test GPU for {device}")
    warm_up.start()
    state = wait_for_warm_up(warm_up)
    assert (state.state, state.device_name, state.problem) == ("ready", "Test GPU for cuda", None)


def test_warm_up_without_a_cuda_device_is_cpu_and_says_no_cuda_device_exists():
    warm_up = GpuWarmUp("auto", warm_up_function=lambda device: None, cuda_available_function=lambda: False)
    warm_up.start()
    state = wait_for_warm_up(warm_up)
    assert (state.state, state.device_name, state.problem, state.cuda_available) == ("cpu", None, None, False)


def test_warm_up_on_the_cpu_chosen_at_launch_says_a_cuda_device_exists():
    warm_up = GpuWarmUp("cpu", warm_up_function=lambda device: None, cuda_available_function=lambda: True)
    warm_up.start()
    state = wait_for_warm_up(warm_up)
    assert (state.state, state.device_name, state.problem, state.cuda_available) == ("cpu", None, None, True)


def test_a_prepared_cpu_stays_cpu_when_asking_torch_for_a_cuda_device_fails():
    def cuda_check_that_fails():
        raise RuntimeError("CUDA driver initialization failed")

    warm_up = GpuWarmUp("cpu", warm_up_function=lambda device: None, cuda_available_function=cuda_check_that_fails)
    warm_up.start()
    state = wait_for_warm_up(warm_up)
    assert (state.state, state.device_name, state.problem, state.cuda_available) == ("cpu", None, None, None)


def test_the_two_cpu_cases_reach_the_app_apart_through_health(projects_folder):
    replies = []
    for cuda_available in (False, True):
        warm_up = GpuWarmUp("cpu", warm_up_function=lambda device: None, cuda_available_function=lambda found=cuda_available: found)
        warm_up.start()
        wait_for_warm_up(warm_up)
        client = build_client(projects_folder, warm_up=warm_up)[0]
        replies.append(client.get("/api/health").json()["warm_up"])
    assert replies == [
        {"state": "cpu", "device_name": None, "problem": None, "cuda_available": False},
        {"state": "cpu", "device_name": None, "problem": None, "cuda_available": True},
    ]


def test_warm_up_failure_keeps_the_message():
    def cannot_run(device):
        raise RuntimeError("Warp cannot run: repair the environment with setup_env.py")

    warm_up = GpuWarmUp("auto", warm_up_function=cannot_run)
    warm_up.start()
    state = wait_for_warm_up(warm_up)
    assert state.state == "failed" and "setup_env.py" in state.problem and state.device_name is None
    assert state.cuda_available is None


def test_warm_up_runs_once_and_shows_running_meanwhile():
    release = threading.Event()
    calls = []

    def slow(device):
        calls.append(device)
        assert release.wait(10)
        return None

    warm_up = GpuWarmUp("auto", warm_up_function=slow)
    warm_up.start()
    warm_up.start()
    assert warm_up.state().state == "running"
    release.set()
    assert wait_for_warm_up(warm_up).state == "cpu" and calls == ["auto"]
    warm_up.start()
    assert calls == ["auto"]


@pytest.mark.slow
def test_default_warm_up_prepares_the_cpu_or_names_why_it_cannot():
    warm_up = GpuWarmUp("cpu")
    warm_up.start()
    state = wait_for_warm_up(warm_up, deadline_seconds=120.0)
    assert state.state in ("cpu", "failed") and state.device_name is None
    assert (state.problem is None) == (state.state == "cpu")
    assert (state.cuda_available is None) == (state.state == "failed")
