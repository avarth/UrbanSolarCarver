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
