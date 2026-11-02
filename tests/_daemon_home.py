"""A daemon subprocess for tests: its environment, which must not touch the real home folder, and its start-up."""
import os
import socket
import subprocess
import sys
import time

import pytest


def isolated_home_env(home):
    """The environment of the current process with the home folder set to *home*.

    The daemon takes its authkey from ``~/.urbansolarcarver``; with a temporary
    home, a test cannot read or create the real key.  Warp puts its kernel cache
    under the home folder when it is not told otherwise, so it is pinned to the
    cache of this process (no recompiling, and no cache folder in the working
    directory).
    """
    env = {**os.environ, "USERPROFILE": str(home), "HOME": str(home)}
    try:
        import warp
        warp.init()
        env.setdefault("WARP_CACHE_PATH", str(warp.config.kernel_cache_dir))
    except Exception:
        pass
    return env


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def start_daemon(home, answers):
    """Start a daemon on the CPU, with its home folder at *home* (isolated_home_env), on a free port; return (process, port)
    once the daemon says it listens and ``answers(port)`` is true. The log is ``home / "daemon.log"``.

    The daemon takes a port number, not a socket, so the port is free when chosen and another test worker can take it before
    the daemon binds it. The daemon then stops at once saying the port is in use, and another free port is tried."""
    log = home / "daemon.log"
    for _ in range(3):
        port = _free_port()
        with open(log, "wb") as output:
            proc = subprocess.Popen([sys.executable, "-m", "urbansolarcarver.daemon", "--port", str(port), "--device", "cpu"],
                                    stdout=output, stderr=subprocess.STDOUT, env=isolated_home_env(home))
        for _ in range(240):
            if proc.poll() is not None:
                break
            # Try the daemon only once it says it bound the port: until then the port can be another program's.
            if "[daemon] listening on" in log.read_text(encoding="utf-8", errors="replace") and answers(port):
                return proc, port
            time.sleep(0.5)
        else:
            proc.kill()
            pytest.fail("daemon did not become ready")
        said = log.read_text(encoding="utf-8", errors="replace")
        if "already in use" not in said:
            pytest.fail("daemon exited during startup:\n" + said)
    pytest.fail("three free ports were taken before the daemon could bind them")
