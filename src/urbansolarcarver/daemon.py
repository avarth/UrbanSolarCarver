"""CUDA/Warp session persistence server for IPC (Grasshopper, Revit).

Keeps the GPU context alive across multiple calls from external
applications.  Starts a single CarverSession and listens for JSON-like
RPC messages over a multiprocessing Connection, dispatching each request
to the appropriate pipeline entry point and returning serialised results.

Security assumptions
--------------------
- **Localhost only** — the daemon binds exclusively to the loopback
  interface. Non-loopback addresses are rejected at startup.
- **Authkey** — a random 32-byte token is generated on first start and
  stored in ``.daemon_authkey``. Clients must present this key.
- **Pickle IPC** — ``multiprocessing.connection`` uses pickle internally.
  Any process that holds the authkey can execute arbitrary code in the
  daemon's context.  This is acceptable because both endpoints run on the
  same machine under the same user account.
- **Not designed for multi-tenant or server deployment.** Do not expose
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
from multiprocessing.connection import Listener
import traceback

log = logging.getLogger(__name__)
from urbansolarcarver.session import CarverSession
from urbansolarcarver.load_config import load_config

# Key file location: user-specific directory (cross-platform).
# Generated randomly on first daemon start; clients must read this file.
_DEFAULT_KEYFILE = Path.home() / ".urbansolarcarver" / ".daemon_authkey"


def _resolve_authkey(keyfile: Path = _DEFAULT_KEYFILE) -> bytes:
    """Read or generate a per-install random authkey.

    On first daemon start the key is generated with 32 bytes of
    cryptographic randomness and persisted to *keyfile*.  Subsequent
    starts and all clients reuse the same key.  The file is created
    with owner-only permissions where the OS supports it.
    """
    if keyfile.is_file():
        return keyfile.read_bytes().strip()
    key = secrets.token_hex(32).encode()
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    keyfile.write_bytes(key)
    # Restrict authkey file to current user only.
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["icacls", str(keyfile), "/inheritance:r",
                 "/grant:r", f"{os.getlogin()}:(R,W)"],
                capture_output=True, check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            log.warning("Could not restrict authkey file permissions (Windows): %s", exc)
    else:
        try:
            keyfile.chmod(0o600)
        except OSError as exc:
            log.warning("Could not restrict authkey file permissions: %s", exc)
    return key


_LOOPBACK = frozenset({"127.0.0.1", "::1"})

def _validate_localhost(host: str) -> None:
    """Reject non-loopback bind addresses to prevent network exposure."""
    # Accept bare IPv6 loopback before any DNS lookup.
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


def _pick_device(arg: str) -> str:
    """Select the best available compute device.

    Returns 'cuda' if a CUDA GPU is available and PyTorch is installed,
    otherwise 'cpu'.
    """
    if arg == "cpu":
        return "cpu"
    if arg == "cuda":
        return "cuda"
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except (ImportError, RuntimeError):
        return "cpu"

def _handle_stage_command(cmd, msg, sess):
    """Dispatch a pipeline RPC command and build the reply dict.

    Raises on failure — the caller converts exceptions into error replies.
    """
    from urbansolarcarver import api

    cfg = load_config(msg["config"], msg.get("overrides", []))
    if cmd in ("preprocessing", "run_pipeline"):
        # New run: invalidate cached tensors (kernel caches persist on disk).
        sess.bump(flush=False)

    if cmd == "run_pipeline":
        result = api.run_pipeline(cfg, msg.get("out_dir") or cfg.out_dir)
        return {"status": "ok", "export_path": str(result.export_path)}

    out_dir = msg.get("out_dir") or (Path(cfg.out_dir) / cmd)
    if cmd == "preprocessing":
        result = api.preprocessing(cfg, out_dir)
        return {"status": "ok", "manifest": str(result.out_dir / "manifest.json")}
    if cmd == "thresholding":
        result = api.thresholding(msg["from"], cfg, out_dir)
        return {"status": "ok", "manifest": str(result.out_dir / "manifest.json")}
    if cmd == "exporting":
        result = api.exporting(msg["from"], cfg, out_dir)
        return {"status": "ok", "export_path": str(result.export_path)}
    raise ValueError(f"Unknown command: {cmd!r}")


def serve(address, authkey, device_arg="auto"):
    """Start the persistent RPC listener for CUDA/Warp session reuse.

    Binds a multiprocessing.connection Listener on (host, port) and dispatches
    incoming commands to the 3-stage pipeline (preprocessing, thresholding,
    exporting) or to session management (shutdown). Each pipeline command
    runs within a CarverSession context that keeps the CUDA context and
    compiled Warp kernels alive across calls, avoiding the ~5s GPU startup
    penalty on each invocation from Grasshopper or Revit.

    The session's tensor cache is invalidated between runs (bump()) but
    kernels persist for the lifetime of the daemon process.
    """
    from multiprocessing.connection import Listener
    device = _pick_device(device_arg)
    with CarverSession(device) as sess:
        listener = Listener(address, authkey=authkey)
        print(f"[daemon] READY — listening on {address[0]}:{address[1]} (device={device}, pid={os.getpid()})", flush=True)
        try:
            while True:
                try:
                    conn = listener.accept()
                except (ConnectionAbortedError, ConnectionResetError, EOFError, OSError):
                    # stray or half-open client; ignore and continue
                    time.sleep(0.05)
                    continue
                try:
                    msg = conn.recv()
                except (EOFError, OSError):
                    conn.close()
                    continue
                if not isinstance(msg, dict):
                    try:
                        conn.send({"status": "error", "error": "Expected dict message"})
                    finally:
                        conn.close()
                    continue
                cmd = msg.get("cmd")
                _REQUIRED_KEYS = {
                    "preprocessing": ("config",),
                    "thresholding": ("config", "from"),
                    "exporting": ("config", "from"),
                    "run_pipeline": ("config",),
                    "ping": (),
                    "shutdown": (),
                }
                expected = _REQUIRED_KEYS.get(cmd)
                if expected is None and cmd not in _REQUIRED_KEYS:
                    try:
                        conn.send({"status": "error", "error": f"Unknown command: {cmd!r}"})
                    finally:
                        conn.close()
                    continue
                missing = [k for k in (expected or ()) if k not in msg]
                if missing:
                    try:
                        conn.send({"status": "error", "error": f"Missing required keys for '{cmd}': {missing}"})
                    finally:
                        conn.close()
                    continue

                if cmd == "ping":
                    conn.send({"status": "ok", "pid": os.getpid()})
                    conn.close()
                    continue

                if cmd == "shutdown":
                    conn.send({"status": "ok"})
                    conn.close()
                    break

                # Pipeline commands share one handler; failures become
                # error replies (full traceback stays server-side only).
                try:
                    reply = _handle_stage_command(cmd, msg, sess)
                except Exception as e:
                    traceback.print_exc()
                    reply = {"status": "error", "error": str(e)}
                try:
                    conn.send(reply)
                finally:
                    conn.close()
        finally:
            listener.close()



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=6000)
    parser.add_argument("--authkey", default=None,
                        help="Auth key string. If omitted, a random key is "
                             "generated/read from .daemon_authkey")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()
    if args.authkey:
        key = args.authkey.encode()
    else:
        key = _resolve_authkey()
    _validate_localhost(args.host)
    print(f"[daemon] authkey file: {_DEFAULT_KEYFILE}", flush=True)
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
