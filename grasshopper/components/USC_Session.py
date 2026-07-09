"""USC Session — Establish connection to UrbanSolarCarver backend.

Sets up the Python environment and optionally starts the CUDA daemon
for persistent GPU sessions (essential for Grasshopper workflows).

Inputs
------
carver_root : str
    Path to the UrbanSolarCarver repository root. The backend Python is
    located automatically: .venv/ or venv/ inside the root, or the path
    written in an optional <root>/python_path.txt override file (one line,
    full path to the python executable — useful when the venv lives
    elsewhere on the machine).
start_daemon : bool, optional
    True (default) = start daemon if not running. False = report only.
verbose : bool, optional
    True = show daemon console window for debugging.

Outputs
-------
session : dict
    Opaque session handle passed to all other USC components.
    Contains: root, python_path, authkey, host, port, daemon_pid.
status : str
    "ready" | "starting" | "no_daemon" | "error: ..."
"""

import os
import socket
import subprocess
import time
from pathlib import Path

# -- Session handle (non-iterable so GH treats it as a single item) ---------
class USCSession:
    """Opaque session handle. Not iterable — GH won't unpack it into a list."""
    __slots__ = ("root", "python_path", "authkey", "host", "port", "daemon_running")

    def __init__(self, root, python_path, authkey, host, port, daemon_running):
        self.root = root
        self.python_path = python_path
        self.authkey = authkey
        self.host = host
        self.port = port
        self.daemon_running = daemon_running

    def __repr__(self):
        state = "connected" if self.daemon_running else "no daemon"
        return "USCSession({}, {})".format(self.host + ":" + str(self.port), state)


# -- Constants ---------------------------------------------------------------
HOST = "localhost"
PORT = 6000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010

# -- GH UI rollovers --------------------------------------------------------
try:
    ghenv.Component.Name = "USC Session"
    ghenv.Component.NickName = "USC_Session"
    ghenv.Component.Description = "Connects to the UrbanSolarCarver computation daemon. The daemon keeps the GPU context alive between runs for fast iteration. Place this component once and wire 'session' to USC_Config."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "carver_root", "Path to the UrbanSolarCarver folder on your computer (the folder containing the 'src' subfolder). The Python environment is found automatically in '.venv' or 'venv' inside it; if your venv lives elsewhere, create a text file 'python_path.txt' in this folder containing the full path to python.exe. Right-click > Set One String, then paste the full path."
    ii[1].Name, ii[1].Description = "start_daemon", "Wire a Boolean True to launch the background computation server (daemon). If left unconnected (None) or False the daemon is NOT started — status will be 'no_daemon'. The daemon keeps the GPU warm between runs for fast iteration."
    if len(ii) > 2:
        ii[2].Name, ii[2].Description = "verbose", "Set to True to open a visible console window showing daemon activity. Useful for debugging if things go wrong. Leave False for normal use."
    oo[0].Name, oo[0].Description = "session", "Connection handle passed to the USC_Config component. Contains the daemon address and authentication. Do not modify."
    oo[1].Name, oo[1].Description = "status", "Current daemon state: 'ready' means the daemon is running and accepting jobs. 'starting' means it is loading. 'error:...' means something went wrong -- read the message."
except Exception:
    pass

# -- Helpers -----------------------------------------------------------------

def _venv_python(root):
    """Locate the backend Python interpreter.

    Search order:
      1. <root>/python_path.txt — a one-line text file containing the full
         path to a python executable.  Machine-specific override for venvs
         that live outside the repo (the file is gitignored).
      2. <root>/.venv  (Windows then POSIX layout — setup_env.py default)
      3. <root>/venv
    """
    root = Path(root)
    override = root / "python_path.txt"
    if override.is_file():
        try:
            cand = Path(override.read_text(encoding="utf-8").strip().strip('"'))
            if cand.is_file():
                return cand
        except Exception:
            pass
    for rel in (
        (".venv", "Scripts", "python.exe"),
        ("venv", "Scripts", "python.exe"),
        (".venv", "bin", "python"),
        ("venv", "bin", "python"),
    ):
        p = root.joinpath(*rel)
        if p.exists():
            return p
    return None


def _read_authkey(root):
    """Read daemon authkey from the shared keyfile.

    The daemon writes to ~/.urbansolarcarver/.daemon_authkey (user-specific,
    cross-platform).  Falls back to <repo_root>/.daemon_authkey for
    backward compatibility with older daemon versions.
    """
    # Primary: user-specific location (matches daemon.py _DEFAULT_KEYFILE)
    kf = Path.home() / ".urbansolarcarver" / ".daemon_authkey"
    if kf.is_file():
        return kf.read_bytes().strip()
    # Fallback: legacy repo-root location
    kf_legacy = Path(root).resolve() / ".daemon_authkey"
    if kf_legacy.is_file():
        return kf_legacy.read_bytes().strip()
    return None


def _port_open(host=HOST, port=PORT, timeout=0.3):
    """Check if the daemon port is listening."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


def _ping_daemon(authkey, host=HOST, port=PORT):
    """Verify daemon responds to RPC ping."""
    if authkey is None:
        return False
    try:
        from multiprocessing.connection import Client as MPClient
        c = MPClient((host, port), authkey=authkey)
        c.send({"cmd": "ping"})
        resp = c.recv()
        c.close()
        # daemon sends {"status": "ok", "pid": ...}
        return resp.get("status") == "ok" if isinstance(resp, dict) else False
    except Exception:
        return False


def _start_daemon(root, verbose=False):
    """Launch the daemon subprocess with proper PYTHONPATH."""
    py = _venv_python(root)
    if py is None:
        return None

    # Use -m to invoke the daemon module (requires PYTHONPATH)
    cmd = [str(py), "-m", "urbansolarcarver.daemon",
           "--host", HOST, "--port", str(PORT)]

    # Set PYTHONPATH so the daemon can import urbansolarcarver
    env = os.environ.copy()
    src_dir = str(Path(root) / "src")
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")

    if verbose:
        # Keep console open so user can see init messages and errors
        flags = CREATE_NEW_CONSOLE
        out, err = None, None
    else:
        flags = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
        out, err = subprocess.DEVNULL, subprocess.DEVNULL

    popen_kwargs = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = flags  # Windows-only argument
    proc = subprocess.Popen(
        cmd, env=env, cwd=str(root),
        stdout=out, stderr=err,
        **popen_kwargs,
    )
    return proc.pid


# -- Main logic --------------------------------------------------------------

# Defaults
if carver_root is None:
    session = None
    status = "error: carver_root is required"
else:
    root = Path(str(carver_root)).resolve()
    py = _venv_python(root)

    if py is None:
        session = None
        status = (
            "error: no Python interpreter found under " + str(root) + " — "
            "run setup_env.py to create .venv/, or write the full path to "
            "your python executable into <carver_root>/python_path.txt"
        )
    else:
        authkey = _read_authkey(root)
        port_open_now = _port_open()
        daemon_running = authkey is not None and port_open_now

        if not daemon_running and start_daemon:
            # Only launch if the port is not already open — prevents spawning a
            # second daemon when one is starting up but hasn't written the keyfile yet.
            pid = _start_daemon(root, verbose=bool(verbose)) if not port_open_now else None
            # Wait for daemon to become ready (CUDA+Warp init can take 15-25s)
            for attempt in range(60):  # 60 × 0.5s = 30s max
                time.sleep(0.5)
                authkey = _read_authkey(root)
                if authkey and _port_open() and _ping_daemon(authkey):
                    daemon_running = True
                    break

            if daemon_running:
                status = "ready"
            else:
                status = "starting (pid={})".format(pid) if pid else "error: daemon failed to launch"
        elif daemon_running:
            status = "ready"
        else:
            status = "no_daemon"

        session = USCSession(
            root=str(root),
            python_path=str(py),
            authkey=authkey,
            host=HOST,
            port=PORT,
            daemon_running=daemon_running,
        )
