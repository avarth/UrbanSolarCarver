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
from multiprocessing import AuthenticationError
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

# Keys each command must carry (besides "cmd").
_REQUIRED_KEYS = {
    "preprocessing": ("config",),
    "thresholding": ("config", "from"),
    "exporting": ("config", "from"),
    "run_pipeline": ("config",),
    "simulate_weights": ("epw", "archetype", "out"),
    "ping": (),
    "shutdown": (),
}


def _error_reply(exc: BaseException) -> dict:
    return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def _reply(conn, obj) -> None:
    """Send *obj* and close; a client that already left must not stop the server."""
    try:
        conn.send(obj)
    except Exception as exc:
        print(f"[daemon] could not send reply ({type(exc).__name__}: {exc})", flush=True)
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _handle_stage_command(cmd, msg, sess):
    """Run one pipeline command and build the reply dict. Raises on failure."""
    from urbansolarcarver import api

    cfg = load_config(msg["config"], msg.get("overrides", []))
    if cmd in ("preprocessing", "run_pipeline"):
        # A new run: drop tensors cached from the previous one.
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
    result = api.exporting(msg["from"], cfg, out_dir)
    return {"status": "ok", "export_path": str(result.export_path)}


def _simulate_weights(msg):
    """Generate a simulated-weights artifact (no config or GPU session needed)."""
    from urbansolarcarver.simulated_weights import generate_simulated_weights

    arch = msg["archetype"]
    if isinstance(arch, str):  # a YAML path instead of an inline mapping
        import yaml
        arch = yaml.safe_load(Path(arch).read_text(encoding="utf-8"))
        if not isinstance(arch, dict):
            raise ValueError(f"archetype file {msg['archetype']!r} does not contain a mapping")
    path = Path(generate_simulated_weights(
        msg["epw"], arch, msg["out"],
        internal_gains_w_m2=msg.get("internal_gains_w_m2"),
        eps=msg.get("eps", 1.0),
    ))
    preview = path.with_suffix(".png")
    return {"status": "ok", "artifact": str(path),
            "preview": str(preview) if preview.is_file() else None}


def _dispatch(msg, sess) -> dict:
    """Validate a request and run it. Raises on failure."""
    if not isinstance(msg, dict):
        return {"status": "error", "error": "Expected a dict message"}
    cmd = msg.get("cmd")
    if cmd not in _REQUIRED_KEYS:
        return {"status": "error", "error": f"Unknown command: {cmd!r}"}
    missing = [k for k in _REQUIRED_KEYS[cmd] if k not in msg]
    if missing:
        return {"status": "error", "error": f"Missing required keys for {cmd!r}: {missing}"}
    if cmd == "ping":
        return {"status": "ok", "pid": os.getpid()}
    if cmd == "simulate_weights":
        return _simulate_weights(msg)
    try:
        return _handle_stage_command(cmd, msg, sess)
    finally:
        # Return GPU memory after every run, successful or not, so the next
        # run (and the Rhino viewport) does not start from a full allocator.
        sess.bump(flush=True)


def serve(address, authkey, device_arg="auto"):
    """Serve pipeline requests from Grasshopper and the CLI until "shutdown".

    Keeps one CarverSession (CUDA context and compiled Warp kernels) alive
    across requests. Commands: preprocessing, thresholding, exporting,
    run_pipeline, simulate_weights, ping, shutdown. Requests are handled one
    at a time; a failing request becomes an error reply and the server keeps
    running.
    """
    device = _pick_device(device_arg)
    with CarverSession(device) as sess:
        # Bind before the (possibly slow) kernel warmup: clients polling for
        # readiness can connect at once, and their ping waits for the accept
        # loop instead of timing out on a cold kernel cache.
        listener = Listener(address, authkey=authkey)
        print(f"[daemon] listening on {address[0]}:{address[1]} "
              f"(device={device}, pid={os.getpid()}), warming up...", flush=True)
        try:
            from urbansolarcarver.raytracer import warmup_kernels
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
                    _reply(conn, _error_reply(exc))
                    continue
                if isinstance(msg, dict) and msg.get("cmd") == "shutdown":
                    _reply(conn, {"status": "ok"})
                    break
                try:
                    reply = _dispatch(msg, sess)
                except Exception as exc:
                    traceback.print_exc()
                    reply = _error_reply(exc)
                _reply(conn, reply)
        finally:
            listener.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=6000)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()
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
