"""The client side of the daemon, standard library only.

Clients (the CLI's ``daemon`` commands and its ``--daemon`` runs) import this
module rather than :mod:`daemon`, which loads torch, so asking the daemon
something stays quick.  The daemon reads its key through the same function.
Grasshopper keeps its own copy of the key reading in ``usc_gh.py``, because
Rhino's Python does not import this package.
"""
import logging
import os
import secrets
import subprocess
import sys
from multiprocessing.connection import Client
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_DAEMON_HOST = "localhost"
DEFAULT_DAEMON_PORT = 6000
# Per-user key file shared by the daemon and its clients.
DAEMON_AUTHKEY_PATH = Path.home() / ".urbansolarcarver" / ".daemon_authkey"


def resolve_daemon_authkey(keyfile: Path = DAEMON_AUTHKEY_PATH) -> bytes:
    """Read the authkey from *keyfile*, creating it if it does not exist.

    Whichever process calls this first (the daemon or a client) generates
    the key: 32 bytes from ``secrets``, hex-encoded to 64 ASCII bytes.  All
    later calls return the same key.  After creating the file, access is
    restricted to the current user: on Linux and macOS the file is created
    with mode 0o600; on Windows ``icacls`` is run afterwards, and if that
    fails a warning is logged and the key is still used.
    """
    if keyfile.is_file():
        return keyfile.read_bytes().strip()
    key = secrets.token_hex(32).encode()
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL: if another process created the file in the meantime, use its key.
    try:
        fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return keyfile.read_bytes().strip()
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["icacls", str(keyfile), "/inheritance:r",
                 "/grant:r", f"{os.getlogin()}:(R,W)"],
                capture_output=True, check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            log.warning("Could not restrict authkey file permissions (Windows): %s", exc)
    return key


def send_daemon_request(payload: dict, host: str = DEFAULT_DAEMON_HOST,
                        port: int = DEFAULT_DAEMON_PORT) -> dict:
    """Send one request to the daemon and return its reply.

    Raises ``ConnectionRefusedError`` if no daemon listens on *host*:*port*
    and ``multiprocessing.AuthenticationError`` if the keys do not match.
    """
    conn = Client((host, port), authkey=resolve_daemon_authkey())
    try:
        conn.send(payload)
        return conn.recv()
    finally:
        conn.close()
