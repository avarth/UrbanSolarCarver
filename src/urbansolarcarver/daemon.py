"""Long-running server that keeps a GPU session alive between pipeline calls.

Used by the Grasshopper components and the CLI ``--daemon`` flag.  Starts a
single CarverSession and listens on a ``multiprocessing.connection``
Listener for request dicts such as ``{"cmd": "run", "produce": [...], ...}``.
The daemon is a transport: each request goes to
:func:`urbansolarcarver.engine_requests.answer_engine_message`, which runs it
and returns the reply dict (``"status"`` is ``"ok"`` or ``"error"``) that is
sent back.  Only ``shutdown`` is handled here, since it stops the transport.

Security assumptions
--------------------
- **Localhost only**: the daemon binds to the loopback interface.
  Host names that do not resolve to 127.0.0.1 or ::1 are rejected at startup.
- **Authkey**: 32 random bytes, stored as 64 hex characters in
  ``~/.urbansolarcarver/.daemon_authkey``, are generated on first use.
  Clients must present this key.
- **Pickle IPC**: ``multiprocessing.connection`` uses pickle internally.
  Any process that holds the authkey can execute arbitrary code in the
  daemon's context.  This is acceptable because both endpoints run on the
  same machine under the same user account.
- **Not designed for multi-user or server deployment.** Do not expose
  the daemon port to a network.
"""

import logging
import time
import argparse
import os
import secrets
import socket
import subprocess
import sys
from pathlib import Path
from multiprocessing import AuthenticationError
from multiprocessing.connection import Listener
import traceback

log = logging.getLogger(__name__)
from urbansolarcarver.engine_requests import answer_engine_message, error_reply_for
from urbansolarcarver.compute_device import resolve_compute_device
from urbansolarcarver.daemon_client import (
    DAEMON_AUTHKEY_PATH, DEFAULT_DAEMON_PORT, resolve_daemon_authkey,
)
from urbansolarcarver.session import CarverSession

_LOOPBACK = frozenset({"127.0.0.1", "::1"})

def _validate_localhost(host: str) -> None:
    """Raise ValueError unless *host* is or resolves to a loopback address."""
    # gethostbyname only returns IPv4 addresses, so "::1" is accepted here
    # before the lookup.
    if host in _LOOPBACK:
        return
    try:
        resolved = socket.gethostbyname(host)
    except socket.gaierror:
        raise ValueError(f"Cannot resolve daemon host {host!r}")
    if resolved not in _LOOPBACK:
        raise ValueError(
            f"Daemon must bind to localhost for security (pickle IPC). "
            f"Got --host {host!r} which resolves to {resolved}."
        )


def _reply(conn, obj) -> None:
    """Send *obj* and close the connection.

    Send errors are printed, not raised, so a client that has already
    disconnected does not stop the server.
    """
    try:
        conn.send(obj)
    except Exception as exc:
        print(f"[daemon] could not send reply ({type(exc).__name__}: {exc})", flush=True)
    finally:
        try:
            conn.close()
        except OSError:
            pass


def serve(address, authkey, device_arg="auto"):
    """Serve pipeline requests from Grasshopper and the CLI until "shutdown".

    Keeps one CarverSession (CUDA context and compiled Warp kernels) alive
    across requests.  The commands are those of :mod:`engine_requests`, plus
    ``shutdown``.  Requests are handled one at a time; a failing request
    becomes an error reply and the server keeps running.
    """
    device = resolve_compute_device(device_arg)
    with CarverSession(device) as sess:
        # Bind before the (possibly slow) kernel warmup: clients polling for
        # readiness can connect at once, and their ping waits for the accept
        # loop instead of timing out on a cold kernel cache.
        listener = Listener(address, authkey=authkey)
        print(f"[daemon] listening on {address[0]}:{address[1]} "
              f"(device={device}, pid={os.getpid()}), warming up...", flush=True)
        try:
            from urbansolarcarver.warp_kernels import warmup_kernels
            warmed = warmup_kernels(device)
            print(f"[daemon] kernel warmup {'done' if warmed else 'skipped (no Warp backend)'}", flush=True)
        except Exception as exc:
            print(f"[daemon] kernel warmup failed ({exc}); kernels will compile "
                  f"on first use", flush=True)
        print(f"[daemon] READY on {address[0]}:{address[1]} (device={device}, pid={os.getpid()})", flush=True)
        try:
            while True:
                try:
                    conn = listener.accept()
                except AuthenticationError:
                    print("[daemon] rejected a client with a wrong authkey", flush=True)
                    continue
                except (OSError, EOFError):
                    # A client that connected and vanished during the handshake.
                    time.sleep(0.05)
                    continue
                try:
                    msg = conn.recv()
                except Exception as exc:
                    print(f"[daemon] unreadable request ({type(exc).__name__}: {exc})", flush=True)
                    _reply(conn, error_reply_for(exc).model_dump(exclude_none=True))
                    continue
                if isinstance(msg, dict) and msg.get("cmd") == "shutdown":
                    _reply(conn, {"status": "ok"})
                    break
                _reply(conn, answer_engine_message(msg, sess))
        finally:
            listener.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=DEFAULT_DAEMON_PORT)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()
    # Failed requests are logged with their traceback (engine_requests); they
    # go to the daemon's console or log file with the other [daemon] lines.
    logging.basicConfig(level=logging.INFO, format="[daemon] %(levelname)s %(name)s: %(message)s")
    key = resolve_daemon_authkey()
    _validate_localhost(args.host)
    print(f"[daemon] authkey file: {DAEMON_AUTHKEY_PATH}", flush=True)
    print(f"[daemon] starting on {args.host}:{args.port} (device={args.device}) ...", flush=True)
    try:
        serve((args.host, args.port), authkey=key, device_arg=args.device)
    except OSError as e:
        if "address already in use" in str(e).lower() or "10048" in str(e):
            print(f"[daemon] ERROR: port {args.port} already in use. Is another daemon running?", flush=True)
        else:
            print(f"[daemon] ERROR: {e}", flush=True)
        raise SystemExit(1)
    except Exception as e:
        print(f"[daemon] FATAL: {e}", flush=True)
        traceback.print_exc()
        raise SystemExit(1)
