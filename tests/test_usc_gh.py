"""grasshopper/usc_gh.py: the parts that run without Rhino, plus loader checks.

The Rhino-side paths (meshes, PLY, daemon calls from components) are
exercised inside Rhino; see docs/grasshopper.md.
"""
import ast
import importlib.util
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


def test_call_daemon_against_a_real_daemon(gh):
    from urbansolarcarver.daemon import _resolve_authkey
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "urbansolarcarver.daemon", "--port", str(port),
                             "--device", "cpu"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session = types.SimpleNamespace(authkey=_resolve_authkey(), host="localhost", port=port)
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
    assert payload["overrides"] == ["mode=irradiance", "start_month=3"]


def test_components_no_longer_use_the_replaced_helpers_or_stage_commands():
    for src in sorted((GH_DIR / "components").glob("USC_*.py")):
        text = src.read_text(encoding="utf-8")
        assert "_mode_default_yaml" not in text and "_mode_canonical" not in text, src.name
        for command in ("preprocessing", "thresholding", "exporting", "massing", "run_pipeline"):
            assert f'call_daemon(config.session, "{command}"' not in text, f"{src.name} still sends {command}"
