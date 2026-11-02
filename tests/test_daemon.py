"""The daemon must survive misbehaving clients and failing requests.

What a request does is tested in test_engine_requests.py; these tests run a
real daemon process and check the transport around the request core."""
import sys
from multiprocessing.connection import Client

import pytest

from _daemon_home import start_daemon
from urbansolarcarver.daemon_client import resolve_daemon_authkey


@pytest.fixture(scope="module")
def daemon(tmp_path_factory):
    # The daemon reads its key from the home folder; a temporary home keeps
    # the tests away from the real ~/.urbansolarcarver/.daemon_authkey.
    home = tmp_path_factory.mktemp("home")
    key = resolve_daemon_authkey(home / ".urbansolarcarver" / ".daemon_authkey")

    def answers_a_ping(port):
        with Client(("localhost", port), authkey=key) as c:     # waits for the accept, after the kernel warm-up
            c.send({"cmd": "ping"})
            c.recv()
        return True

    proc, port = start_daemon(home, answers_a_ping)
    addr = ("localhost", port)
    try:
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


@pytest.mark.slow
def test_wrong_authkey_does_not_stop_server(daemon):
    addr, key, proc = daemon
    with pytest.raises(Exception):
        Client(addr, authkey=b"wrong key")
    _alive(addr, key, proc)


@pytest.mark.slow
def test_unpicklable_message_gets_error_reply(daemon):
    addr, key, proc = daemon
    with Client(addr, authkey=key) as c:
        c.send_bytes(b"not a pickle")
        reply = c.recv()
    assert reply["status"] == "error" and "UnpicklingError" in reply["error"]
    _alive(addr, key, proc)


@pytest.mark.slow
def test_client_leaving_before_reply(daemon):
    addr, key, proc = daemon
    c = Client(addr, authkey=key)
    c.send({"cmd": "preprocessing", "config": "does_not_exist.yaml"})
    c.close()
    _alive(addr, key, proc)


@pytest.mark.parametrize("msg, fragment, error_type", [
    ({"cmd": "nope"}, "Unknown command", "MalformedEngineRequest"),
    ({"cmd": "thresholding", "config": "x.yaml"}, "Missing required keys", "MalformedEngineRequest"),
    (["not", "a", "dict"], "Expected a dict", "MalformedEngineRequest"),
    ({"cmd": "preprocessing", "config": "does_not_exist.yaml"}, "FileNotFoundError",
     "FileNotFoundError"),
])
@pytest.mark.slow
def test_bad_requests_get_error_replies(daemon, msg, fragment, error_type):
    addr, key, proc = daemon
    reply = _call(addr, key, msg)
    assert reply["status"] == "error" and fragment in reply["error"]
    assert reply["error_type"] == error_type
    _alive(addr, key, proc)


def test_authkey_created_once_and_reused(tmp_path):
    keyfile = tmp_path / "sub" / ".daemon_authkey"
    key = resolve_daemon_authkey(keyfile)
    assert len(key) == 64 and keyfile.read_bytes() == key
    assert resolve_daemon_authkey(keyfile) == key
    if sys.platform != "win32":
        assert keyfile.stat().st_mode & 0o077 == 0
