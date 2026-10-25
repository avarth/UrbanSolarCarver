"""grasshopper/usc_gh.py: the parts that run without Rhino, plus loader checks.

The Rhino-side paths (meshes, PLY, daemon calls from components) are
exercised inside Rhino; see docs/grasshopper.md.
"""
import ast
import importlib.util
import re
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


@pytest.mark.slow
def test_call_daemon_against_a_real_daemon(gh, tmp_path):
    from _daemon_home import isolated_home_env
    from urbansolarcarver.daemon_client import resolve_daemon_authkey
    # A temporary home keeps the test away from the real ~/.urbansolarcarver/.daemon_authkey.
    authkey = resolve_daemon_authkey(tmp_path / ".urbansolarcarver" / ".daemon_authkey")
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "urbansolarcarver.daemon", "--port", str(port),
                             "--device", "cpu"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env=isolated_home_env(tmp_path))
    session = types.SimpleNamespace(authkey=authkey, host="localhost", port=port)
    try:
        for _ in range(240):
            if gh.ping(session, timeout=1):
                break
            time.sleep(0.5)
        else:
            pytest.fail("daemon did not start")
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


def test_read_plates(tmp_path, gh):
    import json
    path = tmp_path / "plates.json"
    path.write_text(json.dumps({"plates": [{"floor": 0, "plate": 0, "z_bottom": 0.0, "z_top": 5.0,
                                            "outline": [[0, 0], [1, 0], [1, 1], [0, 0]], "holes": []}],
                                "floor_area_m2_per_floor": [0.5], "total_floor_area_m2": 0.5}))
    plates = gh.read_plates(path)
    assert len(plates) == 1 and plates[0]["z_top"] == 5.0


REPO_ROOT = GH_DIR.parent


def test_engine_module_loads_the_mode_registry_by_path(gh):
    registry = gh.engine_module(REPO_ROOT, "mode_registry")
    assert list(registry.MODES) == ["time-based", "irradiance", "benefit", "daylight",
                                    "radiative_cooling", "tilted_plane"]
    assert registry.canonical_mode_name(" Tilted-Plane ") == "tilted_plane"
    assert gh.engine_module(REPO_ROOT, "mode_registry") is registry


def test_engine_module_loads_the_archetype_defaults_by_path(gh):
    defaults = gh.engine_module(REPO_ROOT, "archetype_defaults")
    assert defaults.WINDOW_TO_WALL_DEFAULTS["south"] == 0.35
    assert defaults.ARCHETYPE_DEFAULTS["mass_class"] == "medium"


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


@pytest.mark.parametrize("name", ["USC_Preprocess.py", "USC_RunPipeline.py"])
def test_preprocessing_components_write_and_pass_the_context_and_terrain(name):
    text = (GH_DIR / "components" / name).read_text(encoding="utf-8")
    assert "gh.write_optional_geometry(" in text
    for key in ('"context_path"', '"terrain_path"'):
        assert key in text, f"{name} does not pass {key}"


def test_config_resolves_context_and_terrain_paths_against_the_gh_file():
    text = (GH_DIR / "components" / "USC_Config.py").read_text(encoding="utf-8")
    resolved = re.search(r"for key in \(([^)]*)\):\s*\n\s*if overrides_dict.get\(key\)", text).group(1)
    assert '"context_path"' in resolved and '"terrain_path"' in resolved


def test_write_optional_geometry_without_input_writes_nothing(gh, tmp_path):
    assert gh.write_optional_geometry(None, tmp_path, "context") is None
    assert gh.write_optional_geometry([], tmp_path, "context") is None
    assert not any(tmp_path.iterdir())
