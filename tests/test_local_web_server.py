"""The HTTP service of the local web app: security checks, routes, run events, files and the device warm-up state.

The engine is replaced by the fake of local_web_test_support.py, so a run writes the files of a finished run
without computing anything. Requests go through ``TestClient`` with the Host the service expects.
"""
import io
import shutil
import subprocess
import sys
import threading
import time
import warnings
import zipfile

import pytest
import yaml
from starlette.websockets import WebSocketDisconnect

with warnings.catch_warnings():     # newer Starlette versions announce that TestClient will need httpx2; the project pins httpx
    warnings.filterwarnings("ignore", message=".*httpx.*testclient|.*testclient.*httpx", category=Warning)
    from starlette.testclient import TestClient

from local_web_test_support import GOLDEN_EPW, WaitsForCancel, box_bytes, make_worker, write_fake_finished_run, write_fake_run
from urbansolarcarver import __version__
from urbansolarcarver.local_web_service import create_app
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


def build_client(projects_folder, handle_request=None, authorized=True, warm_up=None, static_folder=None):
    """A client for a service whose worker uses *handle_request* (the fake engine by default); the client and the worker."""
    worker = make_worker(ProjectStore(projects_folder), handle_request=handle_request)
    app = create_app(projects_folder, TOKEN, PORT, worker=worker, warm_up=warm_up, static_folder=static_folder)
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


def test_the_examples_are_listed_with_a_description(client):
    examples = client.get("/api/examples").json()
    assert [example["name"] for example in examples] == ["basic_perimeter_block", "new_building", "multiple_buildings"]
    assert all(set(example) == {"name", "title", "description"} and example["title"] and example["description"] for example in examples)


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
    shutil.copytree(write_fake_finished_run(tmp_path / "scratch", obstruction_fraction_carved=0.35), project_run_folder,
                    dirs_exist_ok=True)
    summary = client.get("/api/projects/p/run/summary").json()
    assert summary["carving"]["voxels_kept"] == 61 and summary["carving"]["obstruction_fraction_carved"] == 0.35
    assert summary["massing"]["total_floor_area_m2"] == 200.0
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
