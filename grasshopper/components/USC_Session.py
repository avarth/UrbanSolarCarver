"""USC Session: connect to the UrbanSolarCarver backend.

Finds the backend Python environment, checks whether the daemon is
running and optionally starts it. The daemon is a background Python
process on localhost:6000 that runs the pipeline stages for the other
components and keeps the GPU context and compiled kernels loaded between
runs. All stage components need it.

Inputs
------
carver_root : str
    Path to the UrbanSolarCarver repository root. The backend Python is
    located automatically: the path written in an optional
    <root>/python_path.txt file (one line, full path to the python
    executable; useful when the venv lives elsewhere on the machine),
    otherwise .venv/ or venv/ inside the root.
start_daemon : bool, optional
    True = start the daemon if it is not running. Unconnected or False =
    only report whether one is running.
verbose : bool, optional
    True = show the daemon's console window (for debugging). Otherwise its
    output goes to ~/.urbansolarcarver/daemon.log.

Outputs
-------
session : USCSession
    Handle passed to USC_Config: carver root, Python path, daemon address
    and key.
status : str
    "ready" | "no_daemon" | "error: ..."; session is None only when
    carver_root is missing or invalid.
"""

import time
from pathlib import Path

# -- Session handle ----------------------------------------------------------
class USCSession:
    """Opaque session handle. Not iterable, so Grasshopper passes it as a single item."""
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
STARTUP_TIMEOUT_S = 60  # generous because the first start compiles the Warp kernels

# -- GH UI rollovers --------------------------------------------------------
try:
    ghenv.Component.Name = "USC Session"
    ghenv.Component.NickName = "USC_Session"
    ghenv.Component.Description = "Connects to the UrbanSolarCarver computation daemon, which runs the pipeline for the other components and keeps the GPU context alive between runs for fast iteration. Place this component once and wire 'session' to USC_Config."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "carver_root", "Path to the UrbanSolarCarver folder on your computer (the folder containing the 'src' and 'grasshopper' subfolders). The Python environment is found automatically in '.venv' or 'venv' inside it; if your venv lives elsewhere, create a text file 'python_path.txt' in this folder containing the full path to python.exe (it takes precedence). Right-click > Set One String, then paste the full path."
    ii[1].Name, ii[1].Description = "start_daemon", "Wire a Boolean True to launch the background computation server (daemon). If left unconnected or False, no daemon is started and status is 'no_daemon' unless one is already running. The daemon keeps the GPU warm between runs for fast iteration."
    ii[2].Name, ii[2].Description = "verbose", "Set to True to open a visible console window showing daemon activity. Useful for debugging if things go wrong. Leave False for normal use (output then goes to ~/.urbansolarcarver/daemon.log)."
    oo[0].Name, oo[0].Description = "session", "Connection handle passed to the USC_Config component. Contains the daemon address and authentication. Do not modify."
    oo[1].Name, oo[1].Description = "status", "Current daemon state: 'ready' means the daemon is running and accepting jobs. 'no_daemon' means none is running. 'error:...' means something went wrong; read the message."
except Exception:
    pass

# -- Helpers -----------------------------------------------------------------

def _venv_python(root):
    """Locate the backend Python interpreter.

    Search order:
      1. <root>/python_path.txt: a one-line text file containing the full
         path to a python executable.  Machine-specific override for venvs
         that live outside the repo (the file is gitignored).  Ignored if
         the path it names does not exist.
      2. <root>/.venv, then <root>/venv (Windows layout first, then POSIX;
         .venv is what setup_env.py creates)
    Returns None if nothing is found.
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


def _read_authkey():
    """The daemon's key from ~/.urbansolarcarver/.daemon_authkey (None if absent)."""
    kf = Path.home() / ".urbansolarcarver" / ".daemon_authkey"
    if not kf.is_file():
        return None
    return kf.read_bytes().strip() or None


def _usc_gh(root):
    """Shared helpers from <carver_root>/grasshopper/usc_gh.py, reloaded when that file changes."""
    import importlib.util
    import sys
    path = Path(root) / "grasshopper" / "usc_gh.py"
    stamp = (str(path), path.stat().st_mtime)
    mod = sys.modules.get("usc_gh")
    if mod is None or getattr(mod, "_source", None) != stamp:
        spec = importlib.util.spec_from_file_location("usc_gh", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod._source = stamp
        sys.modules["usc_gh"] = mod
    return mod


# -- Main logic --------------------------------------------------------------

session = None
if carver_root is None:
    status = "error: carver_root is required"
else:
    root = Path(str(carver_root)).resolve()
    py = _venv_python(root)
    if py is None:
        status = (
            "error: no Python interpreter found under " + str(root) + "; "
            "run setup_env.py to create .venv/, or write the full path to "
            "your python executable into <carver_root>/python_path.txt"
        )
    elif not (root / "grasshopper" / "usc_gh.py").is_file():
        status = "error: " + str(root) + " is not an UrbanSolarCarver folder (no grasshopper/usc_gh.py)"
    else:
        gh = _usc_gh(root)
        session = USCSession(root=str(root), python_path=str(py), authkey=_read_authkey(),
                             host=HOST, port=PORT, daemon_running=False)
        session.daemon_running = gh.ping(session)
        status = None

        if not session.daemon_running and start_daemon:
            proc = gh.start_daemon(py, root, HOST, PORT, visible_console=bool(verbose))
            deadline = time.time() + STARTUP_TIMEOUT_S
            while time.time() < deadline and proc.poll() is None:
                time.sleep(0.5)
                session.authkey = _read_authkey()
                if gh.ping(session, timeout=2):
                    session.daemon_running = True
                    break
            if not session.daemon_running:
                where = "its console" if verbose else str(gh.daemon_log_path())
                state = ("exited with code {}".format(proc.returncode) if proc.poll() is not None
                         else "did not answer within {} s".format(STARTUP_TIMEOUT_S))
                status = "error: the daemon {}; see {}".format(state, where)

        if session.daemon_running:
            status = "ready"
        elif status is None:
            status = "no_daemon"
