"""grasshopper/usc_gh.py: the parts that run without Rhino, plus loader checks.

The Rhino-side paths (meshes, PLY, daemon calls from components) are
exercised inside Rhino; see docs/grasshopper.md.
"""
import ast
import importlib.util
import json
import socket
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

GH_DIR = Path(__file__).resolve().parent.parent / "grasshopper"


@pytest.fixture(scope="module")
def gh():
    spec = importlib.util.spec_from_file_location("usc_gh", GH_DIR / "usc_gh.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("value, expected", [
    (None, {}),
    ("a=1;b=2", {"a": "1", "b": "2"}),
    (["a=1", "b=2;c=3"], {"a": "1", "b": "2", "c": "3"}),
    ([["a=1"], ["a=2"]], {"a": "2"}),           # later keys win
    ("path=C:/x=y;flag=true", {"path": "C:/x=y", "flag": "true"}),
    (" junk ; =x ; k = v ", {"k": "v"}),
])
def test_parse_overrides(gh, value, expected):
    assert gh.parse_overrides(value) == expected


def test_components_using_the_loader_import_what_it_needs():
    for src in sorted((GH_DIR / "components").glob("USC_*.py")):
        text = src.read_text(encoding="utf-8")
        if "def _usc_gh(" in text:
            tree = ast.parse(text)
            names = {a.asname or a.name for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
                     for a in n.names}
            assert "Path" in names, f"{src.name} uses _usc_gh but does not import Path"


def test_no_component_keeps_its_own_daemon_or_ply_code():
    for src in sorted((GH_DIR / "components").glob("USC_*.py")):
        text = src.read_text(encoding="utf-8")
        for name in ("def _rpc_call", "def _load_ply_to_rhino", "def _export_mesh_to_ply", "MPClient("):
            assert name not in text, f"{src.name} has its own copy of {name}; use usc_gh"


def _free_port():
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def _start_daemon(gh, home, authkey):
    """Start a daemon on a free port and wait until it answers a ping; (process, session).

    The daemon takes a port number, not a socket, so the port is free when chosen and another test worker can take it before
    the daemon binds it. The daemon then stops at once saying the port is in use, and another free port is tried."""
    from _daemon_home import isolated_home_env
    log = home / "daemon.log"
    for _ in range(3):
        port = _free_port()
        with open(log, "wb") as output:
            proc = subprocess.Popen([sys.executable, "-m", "urbansolarcarver.daemon", "--port", str(port), "--device", "cpu"],
                                    stdout=output, stderr=subprocess.STDOUT, env=isolated_home_env(home))
        session = types.SimpleNamespace(authkey=authkey, host="localhost", port=port)
        for _ in range(240):
            if proc.poll() is not None:
                break
            # Ping only once the daemon says it bound the port: until then the port can be another program's.
            if "[daemon] listening on" in log.read_text(encoding="utf-8", errors="replace") and gh.ping(session, timeout=1):
                return proc, session
            time.sleep(0.5)
        else:
            proc.kill()
            pytest.fail("daemon did not start")
        said = log.read_text(encoding="utf-8", errors="replace")
        if "already in use" not in said:
            pytest.fail("daemon exited during startup:\n" + said)
    pytest.fail("three free ports were taken before the daemon could bind them")


@pytest.mark.slow
def test_call_daemon_against_a_real_daemon(gh, tmp_path):
    from urbansolarcarver.daemon_client import resolve_daemon_authkey
    # A temporary home keeps the test away from the real ~/.urbansolarcarver/.daemon_authkey.
    authkey = resolve_daemon_authkey(tmp_path / ".urbansolarcarver" / ".daemon_authkey")
    proc, session = _start_daemon(gh, tmp_path, authkey)
    try:
        with pytest.raises(gh.DaemonError, match="FileNotFoundError"):
            gh.call_daemon(session, "preprocessing", {"config": "missing.yaml"})
    finally:
        try:
            gh.call_daemon(session, "shutdown", timeout=10)
        except gh.DaemonError:
            proc.kill()
        proc.wait(timeout=20)
    with pytest.raises(gh.DaemonError, match="not reachable"):
        gh.call_daemon(session, "ping", timeout=1)


_PENTAGON = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 1.5, 0.0), (1.0, 3.0, 0.0), (-1.0, 1.5, 0.0)]


def test_read_ply_ascii_with_normals_before_xyz(gh, tmp_path):
    lines = ["ply", "format ascii 1.0", "element vertex 5",
             "property float nx", "property float ny", "property float nz",
             "property double x", "property double y", "property double z",
             "element face 1", "property list uchar int vertex_indices", "end_header"]
    lines += ["0 0 1 {} {} {}".format(*v) for v in _PENTAGON]
    lines += ["5 0 1 2 3 4"]
    path = tmp_path / "a.ply"
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    verts, faces = gh.read_ply(str(path))
    assert verts == _PENTAGON
    assert faces == [(0, 1, 2, 3, 4)]


def test_read_ply_binary_other_list_types(gh, tmp_path):
    import struct
    header = ("ply\nformat binary_little_endian 1.0\nelement vertex 5\n"
              "property float x\nproperty float y\nproperty float z\nproperty uchar red\n"
              "element face 1\nproperty list int uint vertex_indices\nend_header\n").encode()
    body = b"".join(struct.pack("<fffB", *v, 7) for v in _PENTAGON)
    body += struct.pack("<i5I", 5, 0, 1, 2, 3, 4)
    path = tmp_path / "b.ply"
    path.write_bytes(header + body)
    verts, faces = gh.read_ply(str(path))
    assert verts == _PENTAGON
    assert faces == [(0, 1, 2, 3, 4)]


def test_read_ply_matches_usc_double_writer(gh, tmp_path):
    import numpy as np
    import trimesh
    from urbansolarcarver.io import save_mesh
    box = trimesh.creation.box(extents=(1, 1, 1))
    box.apply_translation((500_000.37, 4_200_000.81, 10.0))
    save_mesh(box, str(tmp_path / "box.ply"))
    verts, faces = gh.read_ply(str(tmp_path / "box.ply"))
    np.testing.assert_array_equal(np.array(verts), box.vertices)
    np.testing.assert_array_equal(np.array(faces), box.faces)


@pytest.mark.slow
def test_read_plates(tmp_path, gh):
    """read_plates reads the plates.json the massing stage writes, with the keys USC_Massing builds its Breps from
    (z_bottom, z_top, outline and holes as rings of world x, y): a change of the writer's format fails here.

    The scene is the cube of _stage_scene (x and y -5 to 5 m, z -5 to 5 m) carved above its test surface, with 3 m floors.
    """
    import warnings
    from _stage_scene import daylight_cube_config
    from urbansolarcarver import massing, preprocessing, thresholding
    config = daylight_cube_config(tmp_path)
    run = tmp_path / "run"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = preprocessing(config, run / "preprocessing")
        result = massing(thresholding(pre, config, run / "thresholding"), config, run / "massing")
    plates = gh.read_plates(result.plates_path)
    assert len(plates) == result.n_plates > 0
    for plate in plates:
        assert -5.0 <= plate["z_bottom"] < plate["z_top"] <= 5.0
        for ring in [plate["outline"]] + plate["holes"]:
            assert len(ring) >= 4 and ring[0] == ring[-1]       # closed, as rg.PolylineCurve needs it
            assert all(len(point) == 2 and -5.0 <= point[0] <= 5.0 and -5.0 <= point[1] <= 5.0 for point in ring)


REPO_ROOT = GH_DIR.parent


def test_engine_module_loads_the_mode_registry_by_path(gh):
    registry = gh.engine_module(REPO_ROOT, "mode_registry")
    assert list(registry.MODES) == ["time-based", "irradiance", "benefit", "daylight",
                                    "radiative_cooling", "tilted_plane"]
    assert registry.canonical_mode_name(" Tilted-Plane ") == "tilted_plane"
    assert gh.engine_module(REPO_ROOT, "mode_registry") is registry


def _engine_source(root, name, text):
    engine_dir = root / "src" / "urbansolarcarver"
    engine_dir.mkdir(parents=True, exist_ok=True)
    source = engine_dir / f"{name}.py"
    source.write_text(text, encoding="utf-8")
    return source


def test_engine_module_registers_the_module_before_running_it(gh, tmp_path):
    # A dataclass looks its module up in sys.modules while the class is built.
    _engine_source(tmp_path, "probe_module", (
        "from dataclasses import dataclass\n\n"
        "@dataclass(frozen=True)\n"
        "class Probe:\n"
        "    value: int = 1\n\n"
        "VALUE = Probe().value\n"))
    module = gh.engine_module(tmp_path, "probe_module")
    assert module.VALUE == 1
    assert sys.modules["usc_engine_probe_module"] is module


def test_engine_module_reloads_when_the_file_changes(gh, tmp_path):
    import os
    source = _engine_source(tmp_path, "reload_probe", "VALUE = 1\n")
    assert gh.engine_module(tmp_path, "reload_probe").VALUE == 1
    source.write_text("VALUE = 2\n", encoding="utf-8")
    os.utime(source, (source.stat().st_atime, source.stat().st_mtime + 5))
    assert gh.engine_module(tmp_path, "reload_probe").VALUE == 2


class _FakeComponent:
    def __init__(self):
        self.messages = []

    def AddRuntimeMessage(self, level, text):
        self.messages.append((level, text))


@pytest.fixture
def fake_grasshopper(monkeypatch):
    levels = types.SimpleNamespace(Error="error", Warning="warning", Remark="remark")
    kernel = types.ModuleType("Grasshopper.Kernel")
    kernel.GH_RuntimeMessageLevel = levels
    package = types.ModuleType("Grasshopper")
    package.Kernel = kernel
    monkeypatch.setitem(sys.modules, "Grasshopper", package)
    monkeypatch.setitem(sys.modules, "Grasshopper.Kernel", kernel)


def test_show_issues_adds_one_warning_per_issue(gh, fake_grasshopper):
    component = _FakeComponent()
    reply = {"status": "ok", "issues": [
        {"stage": "preprocessing", "code": "a", "message": "first problem"},
        {"stage": "thresholding", "code": "b", "message": "second problem"}]}
    lines = gh.show_issues(component, reply)
    assert lines == ["preprocessing: first problem", "thresholding: second problem"]
    assert component.messages == [("warning", "preprocessing: first problem"),
                                  ("warning", "thresholding: second problem")]


def test_show_issues_without_issues_adds_nothing(gh, fake_grasshopper):
    component = _FakeComponent()
    assert gh.show_issues(component, {"status": "ok"}) == []
    assert gh.show_issues(component, {"status": "ok", "issues": []}) == []
    assert component.messages == []


def _config(yaml_path):
    return types.SimpleNamespace(yaml_path=yaml_path, out_dir="C:/runs/one",
                                 overrides={"mode": "irradiance", "start_month": "3"})


def test_run_stages_sends_the_run_command(gh, monkeypatch):
    sent = []

    def fake_call_daemon(session, cmd, payload=None, timeout=None):
        sent.append((session, cmd, payload))
        return {"status": "ok", "stage_folders": {"thresholding": "C:/runs/one/thresholding"}}

    monkeypatch.setattr(gh, "call_daemon", fake_call_daemon)
    reply = gh.run_stages("the-session", _config("C:/base.yaml"), ["thresholding"], "thresholding",
                          {"start_month": "5", "threshold_method": "quantile"})
    assert reply["stage_folders"]["thresholding"] == "C:/runs/one/thresholding"
    ((session, cmd, payload),) = sent
    assert session == "the-session" and cmd == "run"
    assert payload["produce"] == ["thresholding"] and payload["start_from"] == "thresholding"
    assert payload["run_folder"] == "C:/runs/one"
    assert payload["config"] == "C:/base.yaml"
    assert sorted(payload["overrides"]) == ["mode=irradiance", "start_month=5",
                                            "threshold_method=quantile"]


def test_run_stages_omits_config_when_no_yaml_was_given(gh, monkeypatch):
    sent = []
    monkeypatch.setattr(gh, "call_daemon",
                        lambda session, cmd, payload=None, timeout=None: sent.append(payload) or {"status": "ok"})
    gh.run_stages("s", _config(None), ["exporting"], "preprocessing", None)
    (payload,) = sent
    assert "config" not in payload
    incoming = Path("C:/runs/one") / "incoming"
    assert payload["overrides"] == ["mode=irradiance", "start_month=3",
                                    "max_volume_path={}".format(incoming / "max_volume.ply"),
                                    "test_surface_path={}".format(incoming / "test_surfaces.ply")]


def test_run_stages_keeps_explicit_geometry_paths_and_adds_no_default_with_a_yaml(gh, monkeypatch):
    sent = []
    monkeypatch.setattr(gh, "call_daemon",
                        lambda session, cmd, payload=None, timeout=None: sent.append(payload) or {"status": "ok"})
    explicit = {"max_volume_path": "D:/in/volume.ply"}
    gh.run_stages("s", _config(None), ["preprocessing"], "preprocessing", explicit)
    gh.run_stages("s", _config("C:/base.yaml"), ["thresholding"], "thresholding", None)
    without_yaml, with_yaml = sent
    assert "max_volume_path=D:/in/volume.ply" in without_yaml["overrides"]
    assert not any(o.startswith("max_volume_path=") and "incoming" in o for o in without_yaml["overrides"])
    assert any(o.startswith("test_surface_path=") and "incoming" in o for o in without_yaml["overrides"])
    assert not any(o.startswith(("max_volume_path=", "test_surface_path=")) for o in with_yaml["overrides"])


def test_show_issues_labels_a_config_issue_without_a_stage(gh, fake_grasshopper):
    component = _FakeComponent()
    reply = {"status": "ok", "issues": [{"stage": None, "code": "c", "message": "mode note"}]}
    assert gh.show_issues(component, reply) == ["config: mode note"]
    assert component.messages == [("warning", "config: mode note")]


def test_stage_folder_mismatch_names_both_paths(gh):
    config = types.SimpleNamespace(out_dir="C:/runs/one")
    assert gh.stage_folder_mismatch(config, "C:/runs/one/preprocessing/manifest.json", "preprocessing") is None
    assert gh.stage_folder_mismatch(config, "C:/runs/one/../one/preprocessing/manifest.json",
                                    "preprocessing") is None
    message = gh.stage_folder_mismatch(config, "C:/runs/other/preprocessing/manifest.json", "preprocessing")
    assert "other" in message and "one" in message
    assert str(Path("C:/runs/other/preprocessing")) in message
    assert str(Path("C:/runs/one/preprocessing")) in message


def test_call_daemon_hints_at_a_restart_for_an_old_daemon(gh, monkeypatch):
    class _OldDaemonConnection:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def send(self, message):
            pass

        def poll(self, timeout):
            return True

        def recv(self):
            return {"status": "error", "error": "Unknown command: 'run'"}

    import multiprocessing.connection
    monkeypatch.setattr(multiprocessing.connection, "Client", _OldDaemonConnection)
    session = types.SimpleNamespace(host="localhost", port=1, authkey=b"key")
    with pytest.raises(gh.DaemonError, match="Restart the daemon from USC_Session"):
        gh.call_daemon(session, "run", {})


def test_components_no_longer_use_the_replaced_helpers_or_stage_commands():
    for src in sorted((GH_DIR / "components").glob("USC_*.py")):
        text = src.read_text(encoding="utf-8")
        assert "_mode_default_yaml" not in text and "_mode_canonical" not in text, src.name
        for command in ("preprocessing", "thresholding", "exporting", "massing", "run_pipeline"):
            assert f'call_daemon(config.session, "{command}"' not in text, f"{src.name} still sends {command}"


def _run_component(name, **inputs):
    """Execute a component script outside Grasshopper (its GH UI block fails quietly without ghenv); return its globals."""
    namespace = dict(inputs)
    exec(compile((GH_DIR / "components" / name).read_text(encoding="utf-8"), name, "exec"), namespace)
    return namespace


@pytest.mark.parametrize("value, expected", [(False, "context_blocks_rays=false"), (True, "context_blocks_rays=true"), (None, None)])
def test_ray_settings_pass_the_context_blocking_switch(value, expected):
    out = _run_component("USC_RaySettings.py", ray_length=None, min_altitude=None, north_deg=None, context_blocks_rays=value,
                         rays_per_patch=None)
    assert out["overrides"] == expected


def test_ray_settings_keep_the_numbers_beside_the_switch():
    out = _run_component("USC_RaySettings.py", ray_length=500, min_altitude=None, north_deg=10, context_blocks_rays=False,
                         rays_per_patch=None)
    assert out["overrides"] == "ray_length=500.0;north_deg=10.0;context_blocks_rays=false"


def test_ray_settings_pass_the_rays_per_patch_as_a_whole_number():
    out = _run_component("USC_RaySettings.py", ray_length=None, min_altitude=None, north_deg=None, context_blocks_rays=None,
                         rays_per_patch=16.0)
    assert out["overrides"] == "rays_per_patch=16"


def _stub_session(tmp_path, monkeypatch, stub_source):
    """A carver root in *tmp_path* whose grasshopper/usc_gh.py is *stub_source*; a component given this session loads it."""
    (tmp_path / "grasshopper").mkdir()
    (tmp_path / "grasshopper" / "usc_gh.py").write_text(stub_source, encoding="utf-8")
    monkeypatch.setitem(sys.modules, "usc_gh", types.ModuleType("usc_gh"))     # restored afterwards; the component loads the stub
    return types.SimpleNamespace(root=str(tmp_path))


_STUB_GH_FOR_GEOMETRY = """
from pathlib import Path
sent = []
def write_input_geometry(max_volume, test_surfaces, folder):
    return str(Path(folder) / "max_volume.ply"), str(Path(folder) / "test_surface.ply")
def write_optional_geometry(items, folder, name):
    return str(Path(folder) / (name + ".ply")) if items else None
def run_stages(session, config, produce, start_from, extra_overrides=None, after=None):
    sent.append(dict(extra_overrides))
    out = Path(config.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text("{}")
    (out / "carved.obj").write_text("")
    return {"stage_folders": {stage: str(out) for stage in ("preprocessing", "thresholding", "exporting")},
            "manifest": str(out / "manifest.json"), "export_path": str(out / "carved.obj")}
def show_issues(component, reply):
    return []
def read_diagnostics(folder):
    return {}
def existing_files(*values):
    return []
def report(component, message, level):
    pass
"""


@pytest.mark.parametrize("name", ["USC_Preprocess.py", "USC_RunPipeline.py"])
@pytest.mark.parametrize("with_surroundings", [True, False], ids=["context and terrain", "neither"])
def test_preprocessing_components_write_and_pass_the_context_and_terrain(tmp_path, monkeypatch, name, with_surroundings):
    """The context and terrain inputs are written beside the other geometry and sent as context_path and terrain_path; left
    unconnected, neither key is sent."""
    session = _stub_session(tmp_path, monkeypatch, _STUB_GH_FOR_GEOMETRY)
    out_dir = tmp_path / "run"
    context, terrain = (["a building"], ["the ground"]) if with_surroundings else (None, None)
    _run_component(name, config=types.SimpleNamespace(session=session, out_dir=str(out_dir)), max_volume=["box"],
                   test_surfaces=["facade"], context=context, terrain=terrain, run=True,
                   ghenv=types.SimpleNamespace(Component=None))
    incoming = out_dir / "incoming"
    expected = {"max_volume_path": str(incoming / "max_volume.ply"), "test_surface_path": str(incoming / "test_surface.ply")}
    if with_surroundings:
        expected.update(context_path=str(incoming / "context.ply"), terrain_path=str(incoming / "terrain.ply"))
    assert sys.modules["usc_gh"].sent == [expected]


_STUB_GH_FOR_CONFIG = """
import types
def engine_module(root, name):
    return types.SimpleNamespace(canonical_mode_name=lambda mode: mode, MODES={"daylight": None})
def resolve_path(component, value):
    return "D:/project/" + value
def parse_overrides(value):
    return dict(item.split("=", 1) for item in value)
"""


def test_config_resolves_the_path_overrides_against_the_gh_file(tmp_path, monkeypatch):
    """Paths from the feeder components arrive relative and are resolved as the component's own inputs are, the context and
    terrain among them; other values pass unchanged."""
    path_keys = ("epw_path", "simulated_weights_path", "max_volume_path", "test_surface_path", "context_path", "terrain_path")
    session = _stub_session(tmp_path, monkeypatch, _STUB_GH_FOR_CONFIG)
    overrides = [f"{key}=inputs/{key}.file" for key in path_keys] + ["voxel_size=2"]
    out = _run_component("USC_Config.py", session=session, mode="daylight", epw_path=None, out_dir="run", config_yaml=None,
                         overrides=overrides, ghenv=types.SimpleNamespace(Component=None))
    sent = out["config"].overrides
    assert {key: sent[key] for key in path_keys} == {key: f"D:/project/inputs/{key}.file" for key in path_keys}
    assert sent["voxel_size"] == "2" and sent["out_dir"] == "D:/project/run"


def test_write_optional_geometry_without_input_writes_nothing(gh, tmp_path):
    assert gh.write_optional_geometry(None, tmp_path, "context") is None
    assert gh.write_optional_geometry([], tmp_path, "context") is None
    assert not any(tmp_path.iterdir())


def test_run_stages_sends_after_only_when_given(gh, monkeypatch):
    sent = []
    monkeypatch.setattr(gh, "call_daemon", lambda session, cmd, payload=None, timeout=None: (
        {"status": "ok", "features": ["run_after"]} if cmd == "ping" else sent.append(payload) or {"status": "ok"}))
    gh.run_stages("s", _config("C:/base.yaml"), ["thresholding"], "thresholding", None, after="C:/other/thresholding/manifest.json")
    gh.run_stages("s", _config("C:/base.yaml"), ["thresholding"], "thresholding", None)
    gh.run_stages("s", _config("C:/base.yaml"), ["thresholding"], "thresholding", None, after="")
    with_after, without, empty = sent
    assert with_after["after"] == "C:/other/thresholding/manifest.json"
    assert "after" not in without and "after" not in empty


def _stub_daemon(monkeypatch, gh, ping_reply):
    sent = []

    def fake_call_daemon(session, cmd, payload=None, timeout=None):
        sent.append(cmd)
        return ping_reply if cmd == "ping" else {"status": "ok"}

    monkeypatch.setattr(gh, "call_daemon", fake_call_daemon)
    return sent


def test_run_stages_with_after_refuses_an_engine_without_the_run_after_feature(gh, monkeypatch):
    for ping_reply in ({"status": "ok", "pid": 1}, {"status": "ok", "pid": 1, "features": []}):
        sent = _stub_daemon(monkeypatch, gh, ping_reply)
        with pytest.raises(gh.DaemonError, match="older than this definition and cannot chain criteria. Restart it from USC_Session"):
            gh.run_stages("s", _config("C:/base.yaml"), ["thresholding"], "thresholding", None, after="C:/a/manifest.json")
        assert sent == ["ping"]


def test_run_stages_with_after_proceeds_when_the_engine_lists_run_after(gh, monkeypatch):
    sent = _stub_daemon(monkeypatch, gh, {"status": "ok", "pid": 1, "features": ["run_after"]})
    gh.run_stages("s", _config("C:/base.yaml"), ["thresholding"], "thresholding", None, after="C:/a/manifest.json")
    assert sent == ["ping", "run"]


def test_run_stages_without_after_does_not_ping(gh, monkeypatch):
    sent = _stub_daemon(monkeypatch, gh, {"status": "ok", "pid": 1})
    gh.run_stages("s", _config("C:/base.yaml"), ["thresholding"], "thresholding", None)
    assert sent == ["run"]


_STUB_GH = """
from pathlib import Path
calls = []
def stage_folder_mismatch(config, manifest_path, stage):
    return None
def parse_overrides(value):
    return {}
def run_stages(session, config, produce, start_from, extra_overrides=None, after=None):
    calls.append(after)
    manifest = Path(config.out_dir) / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("{}")
    return {"stage_folders": {"thresholding": str(config.out_dir)}, "manifest": str(manifest)}
def show_issues(component, reply):
    return []
def read_diagnostics(folder):
    return {}
def existing_files(value):
    return []
"""


@pytest.mark.parametrize("after, expected", [("D:/first/thresholding/manifest.json", "D:/first/thresholding/manifest.json"),
                                              (None, None), ("", None)])
def test_threshold_stage_passes_after(tmp_path, monkeypatch, after, expected):
    config = types.SimpleNamespace(session=_stub_session(tmp_path, monkeypatch, _STUB_GH), out_dir=str(tmp_path / "run"))
    out = _run_component("USC_ThresholdStage.py", config=config, pre_result=str(tmp_path / "run" / "preprocessing" / "manifest.json"),
                         threshold_overrides=None, run=True, after=after,
                         ghenv=types.SimpleNamespace(Component=None))
    assert sys.modules["usc_gh"].calls == [expected]
    assert out["thr_result"] == str(tmp_path / "run" / "manifest.json")


def test_threshold_stage_after_is_its_last_input():
    spec = importlib.util.spec_from_file_location("build_ghuser", GH_DIR / "build_ghuser.py")
    build_ghuser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_ghuser)
    manifest = json.loads((GH_DIR / "components.json").read_text(encoding="utf-8"))["components"]
    comp = build_ghuser.describe(GH_DIR / "components" / "USC_ThresholdStage.py", manifest["USC_ThresholdStage.py"])
    assert [port["name"] for port in comp["inputs"]] == ["config", "pre_result", "threshold_overrides", "run", "after"]
