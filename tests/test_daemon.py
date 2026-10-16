"""The daemon must survive misbehaving clients and failing requests."""
import socket
import subprocess
import sys
import time
from pathlib import Path
from multiprocessing.connection import Client

import pytest

from urbansolarcarver.daemon import _resolve_authkey


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def daemon():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "urbansolarcarver.daemon", "--port", str(port), "--device", "cpu"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    addr, key = ("localhost", port), _resolve_authkey()
    try:
        for _ in range(240):
            if proc.poll() is not None:
                pytest.fail("daemon exited during startup")
            try:
                with Client(addr, authkey=key) as c:
                    c.send({"cmd": "ping"})
                    c.recv()
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("daemon did not become ready")
        yield addr, key, proc
    finally:
        try:
            with Client(addr, authkey=key) as c:
                c.send({"cmd": "shutdown"})
                c.recv()
            proc.wait(timeout=20)
        except Exception:
            proc.kill()


def _call(addr, key, msg):
    with Client(addr, authkey=key) as c:
        c.send(msg)
        return c.recv()


def _alive(addr, key, proc):
    assert proc.poll() is None
    assert _call(addr, key, {"cmd": "ping"})["status"] == "ok"


def test_wrong_authkey_does_not_stop_server(daemon):
    addr, key, proc = daemon
    with pytest.raises(Exception):
        Client(addr, authkey=b"wrong key")
    _alive(addr, key, proc)


def test_unpicklable_message_gets_error_reply(daemon):
    addr, key, proc = daemon
    with Client(addr, authkey=key) as c:
        c.send_bytes(b"not a pickle")
        reply = c.recv()
    assert reply["status"] == "error" and "UnpicklingError" in reply["error"]
    _alive(addr, key, proc)


def test_client_leaving_before_reply(daemon):
    addr, key, proc = daemon
    c = Client(addr, authkey=key)
    c.send({"cmd": "preprocessing", "config": "does_not_exist.yaml"})
    c.close()
    _alive(addr, key, proc)


@pytest.mark.parametrize("msg, fragment", [
    ({"cmd": "nope"}, "Unknown command"),
    ({"cmd": "thresholding", "config": "x.yaml"}, "Missing required keys"),
    (["not", "a", "dict"], "Expected a dict"),
    ({"cmd": "preprocessing", "config": "does_not_exist.yaml"}, "FileNotFoundError"),
])
def test_bad_requests_get_error_replies(daemon, msg, fragment):
    addr, key, proc = daemon
    reply = _call(addr, key, msg)
    assert reply["status"] == "error" and fragment in reply["error"]
    _alive(addr, key, proc)


def test_authkey_created_once_and_reused(tmp_path):
    keyfile = tmp_path / "sub" / ".daemon_authkey"
    key = _resolve_authkey(keyfile)
    assert len(key) == 64 and keyfile.read_bytes() == key
    assert _resolve_authkey(keyfile) == key
    if sys.platform != "win32":
        assert keyfile.stat().st_mode & 0o077 == 0


def test_voxel_grid_cache_survives_between_commands(tmp_path, tmp_mesh_files):
    """A second preprocessing command on the same geometry reuses the cached
    voxel grid and produces the same scores."""
    import numpy as np
    import yaml
    from urbansolarcarver.daemon import _dispatch
    from urbansolarcarver.session import CarverSession

    vol_path, srf_path = tmp_mesh_files
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "max_volume_path": str(vol_path), "test_surface_path": str(srf_path),
        "out_dir": str(tmp_path / "out"), "mode": "daylight",
        "voxel_size": 2.0, "grid_step": 2.0, "ray_length": 50.0, "device": "cpu",
    }))
    with CarverSession(device="cpu") as sess:
        first = _dispatch({"cmd": "preprocessing", "config": str(cfg_path),
                           "out_dir": str(tmp_path / "a")}, sess)
        cached = [k for k in sess.tensors if k.startswith("voxelize_mesh:")]
        assert first["status"] == "ok" and len(cached) == 1
        grid = sess.tensors[cached[0]]
        second = _dispatch({"cmd": "preprocessing", "config": str(cfg_path),
                            "out_dir": str(tmp_path / "b")}, sess)
        assert sess.tensors[cached[0]] is grid  # reused, not rebuilt
    np.testing.assert_array_equal(np.load(tmp_path / "a" / "scores.npy"),
                                  np.load(tmp_path / "b" / "scores.npy"))
    assert second["status"] == "ok"


def test_massing_command_runs_after_thresholding(tmp_path, tmp_mesh_files):
    import yaml
    from urbansolarcarver.daemon import _dispatch
    from urbansolarcarver.session import CarverSession

    vol_path, srf_path = tmp_mesh_files
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "max_volume_path": str(vol_path), "test_surface_path": str(srf_path),
        "out_dir": str(tmp_path / "out"), "mode": "daylight",
        "voxel_size": 2.0, "grid_step": 2.0, "ray_length": 50.0, "device": "cpu",
    }))
    with CarverSession(device="cpu") as sess:
        pre = _dispatch({"cmd": "preprocessing", "config": str(cfg_path)}, sess)
        thr = _dispatch({"cmd": "thresholding", "config": str(cfg_path), "from": pre["manifest"]}, sess)
        reply = _dispatch({"cmd": "massing", "config": str(cfg_path), "from": thr["manifest"]}, sess)
    assert reply["status"] == "ok", reply
    assert (tmp_path / "out" / "massing" / "plates.json").is_file()
    assert reply["plates_path"].endswith("plates.json")


def _error_or_reply(msg, sess):
    """Call ``_dispatch`` the way ``serve`` does: a raised exception becomes an error reply."""
    from urbansolarcarver import daemon
    try:
        return daemon._dispatch(msg, sess)
    except Exception as exc:
        return daemon._error_reply(exc)


def _write_daylight_yaml(tmp_path, vol_path, srf_path):
    import yaml
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "max_volume_path": str(vol_path), "test_surface_path": str(srf_path),
        "out_dir": str(tmp_path / "out"), "mode": "daylight",
        "voxel_size": 2.0, "grid_step": 2.0, "ray_length": 50.0, "device": "cpu",
    }))
    return cfg_path


def test_run_builds_the_config_from_starting_values_without_a_yaml(tmp_path, tmp_mesh_files):
    from urbansolarcarver.daemon import _dispatch
    from urbansolarcarver.session import CarverSession

    vol_path, srf_path = tmp_mesh_files
    overrides = ["mode=daylight", f"max_volume_path={vol_path}", f"test_surface_path={srf_path}",
                 f"out_dir={tmp_path / 'run'}", "device=cpu", "voxel_size=2.0", "grid_step=2.0",
                 "ray_length=50.0"]
    with CarverSession(device="cpu") as sess:
        reply = _dispatch({"cmd": "run", "produce": ["thresholding"],
                           "run_folder": str(tmp_path / "run"), "overrides": overrides}, sess)
    assert reply["status"] == "ok"
    assert set(reply["stage_folders"]) == {"preprocessing", "thresholding"}
    assert reply["manifest"].endswith("manifest.json")
    assert (tmp_path / "run" / "thresholding" / "manifest.json").is_file()
    assert isinstance(reply["issues"], list)


def test_run_starting_values_sit_under_the_overrides(tmp_path, tmp_mesh_files):
    from urbansolarcarver.daemon import _build_request_config

    vol_path, srf_path = tmp_mesh_files
    base = {"mode": "tilted-plane", "max_volume_path": str(vol_path),
            "test_surface_path": str(srf_path), "out_dir": str(tmp_path / "run")}
    assert _build_request_config({"overrides": base}).tilted_plane_angle_deg == 45.0
    changed = _build_request_config({"overrides": {**base, "tilted_plane_angle_deg": 30.0}})
    assert changed.tilted_plane_angle_deg == 30.0


def test_run_reply_carries_the_produced_paths(tmp_path, tmp_mesh_files):
    from urbansolarcarver.daemon import _dispatch
    from urbansolarcarver.session import CarverSession

    vol_path, srf_path = tmp_mesh_files
    cfg_path = _write_daylight_yaml(tmp_path, vol_path, srf_path)
    with CarverSession(device="cpu") as sess:
        reply = _dispatch({"cmd": "run", "produce": ["exporting", "massing"], "config": str(cfg_path),
                           "run_folder": str(tmp_path / "run")}, sess)
    assert reply["status"] == "ok", reply
    assert set(reply["stage_folders"]) == {"preprocessing", "thresholding", "exporting", "massing"}
    assert Path(reply["export_path"]).is_file()
    assert reply["plates_path"].endswith("plates.json")
    assert "mesh_path" in reply


def test_run_without_yaml_requires_mode(tmp_path):
    from urbansolarcarver.session import CarverSession

    with CarverSession(device="cpu") as sess:
        reply = _error_or_reply({"cmd": "run", "produce": ["preprocessing"],
                                 "run_folder": str(tmp_path)}, sess)
    assert reply["status"] == "error"
    assert reply["error_type"] == "ConfigError"
    assert [e["field"] for e in reply["config_errors"]] == ["mode"]


def test_error_reply_keeps_the_text_and_adds_the_type():
    from urbansolarcarver.daemon import _error_reply
    reply = _error_reply(FileNotFoundError("gone"))
    assert reply == {"status": "error", "error": "FileNotFoundError: gone",
                     "error_type": "FileNotFoundError"}


def test_run_requires_produce_and_run_folder(tmp_path):
    from urbansolarcarver.daemon import _dispatch
    reply = _dispatch({"cmd": "run", "produce": ["exporting"]}, None)
    assert reply["status"] == "error" and "run_folder" in reply["error"]


def test_stage_reply_carries_issues(tmp_path, tmp_mesh_files):
    from urbansolarcarver.daemon import _dispatch
    from urbansolarcarver.session import CarverSession

    vol_path, srf_path = tmp_mesh_files
    cfg_path = _write_daylight_yaml(tmp_path, vol_path, srf_path)
    with CarverSession(device="cpu") as sess:
        pre = _dispatch({"cmd": "preprocessing", "config": str(cfg_path)}, sess)
        assert pre["issues"] == []
        reply = _dispatch({"cmd": "thresholding", "config": str(cfg_path), "from": pre["manifest"],
                           "overrides": ["threshold=1e9"]}, sess)
    assert [i["code"] for i in reply["issues"]] == ["nothing_carved"]
    assert reply["issues"][0]["stage"] == "thresholding"
    assert set(reply["issues"][0]) == {"stage", "code", "message"}
