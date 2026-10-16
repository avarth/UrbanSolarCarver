"""Long-running server that keeps a GPU session alive between pipeline calls.

Used by the Grasshopper components and the CLI ``--daemon`` flag.  Starts a
single CarverSession and listens on a ``multiprocessing.connection``
Listener for request dicts such as ``{"cmd": "preprocessing", "config": ...}``.
Each request is dispatched to the matching pipeline entry point and a reply
dict with a ``"status"`` key (``"ok"`` or ``"error"``) is sent back.

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
from urbansolarcarver.errors import ConfigError, ConfigFieldError
from urbansolarcarver.load_config import _parse_overrides, _wrap_value_error, build_config, load_config
from urbansolarcarver.mode_registry import MODES, canonical_mode_name
from urbansolarcarver.pydantic_schemas import expand_analysis_period
from urbansolarcarver.run_context import RunContext, run_context
from urbansolarcarver.session import CarverSession
from urbansolarcarver.stage_settings import PIPELINE_STAGES, stage_folder

# Per-user key file shared by the daemon and its clients.
_DEFAULT_KEYFILE = Path.home() / ".urbansolarcarver" / ".daemon_authkey"


def _resolve_authkey(keyfile: Path = _DEFAULT_KEYFILE) -> bytes:
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


def _pick_device(arg: str) -> str:
    """Turn the ``--device`` argument into ``'cpu'`` or ``'cuda'``.

    ``'cpu'`` and ``'cuda'`` are returned as given.  For ``'auto'``, returns
    ``'cuda'`` if PyTorch is installed and sees a CUDA GPU, otherwise ``'cpu'``.
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
    "massing": ("config", "from"),
    "run_pipeline": ("config",),
    "run": ("produce", "run_folder"),
    "simulate_weights": ("epw", "archetype", "out"),
    "ping": (),
    "shutdown": (),
}


def _error_reply(exc: BaseException) -> dict:
    """The error reply for *exc*: its text, its class name and, for a
    ``ConfigError``, the invalid fields."""
    reply = {"status": "error", "error": f"{type(exc).__name__}: {exc}",
             "error_type": type(exc).__name__}
    if isinstance(exc, ConfigError):
        reply["config_errors"] = [{"field": e.field, "message": e.message} for e in exc.errors]
    return reply


def _issues_of(context: RunContext) -> list:
    """The issues of *context* as reply dicts."""
    return [{"stage": issue.stage, "code": issue.code, "message": issue.message}
            for issue in context.issues]


def _build_request_config(msg):
    """The validated config of a request.

    With ``msg["config"]`` (a YAML path) the file is loaded and the request's
    ``overrides`` are applied.  Without it, the config is built from the
    starting values of the mode named in the overrides, with the overrides
    on top; the overrides must then give ``mode``.  ``overrides`` is a list of
    ``key=value`` strings or a mapping.
    """
    overrides = msg.get("overrides") or []
    if msg.get("config") is not None:
        return load_config(msg["config"], overrides)
    try:
        values = dict(expand_analysis_period(_parse_overrides(overrides)))
    except ValueError as exc:
        raise _wrap_value_error(exc) from exc
    if values.get("mode") is None:
        raise ConfigError(
            "mode: required when no config file is given",
            [ConfigFieldError("mode", "required when no config file is given")])
    mode_name = canonical_mode_name(values["mode"])
    if mode_name not in MODES:
        return build_config(values)  # the schema reports the unknown mode
    return build_config({**MODES[mode_name].starting_values, **values, "mode": mode_name})


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


def _handle_stage_command(cmd, msg, sess):
    """Run one pipeline command and build the reply dict. Raises on failure."""
    from urbansolarcarver import api

    context = RunContext()
    with run_context(context):
        # The config is built inside the run context, so the issues its
        # validators report reach the reply.
        cfg = _build_request_config(msg)

        if cmd == "run":
            result = api.run_pipeline(
                cfg, msg["run_folder"], produce=msg["produce"],
                start_from=msg.get("start_from", PIPELINE_STAGES[0]), context=context)
            return _run_reply(msg["run_folder"], result, context)

        if cmd == "run_pipeline":
            result = api.run_pipeline(cfg, msg.get("out_dir") or cfg.out_dir, context=context)
            return {"status": "ok", "export_path": str(result.exporting.export_path),
                    "issues": _issues_of(context)}

        out_dir = msg.get("out_dir") or (Path(cfg.out_dir) / cmd)
        if cmd == "preprocessing":
            result = api.preprocessing(cfg, out_dir)
            reply = {"status": "ok", "manifest": str(result.out_dir / "manifest.json")}
        elif cmd == "thresholding":
            result = api.thresholding(msg["from"], cfg, out_dir)
            reply = {"status": "ok", "manifest": str(result.out_dir / "manifest.json")}
        elif cmd == "massing":
            result = api.massing(msg["from"], cfg, out_dir)
            reply = {"status": "ok", "manifest": str(result.out_dir / "manifest.json"),
                     "plates_path": str(result.plates_path), "mesh_path": str(result.mesh_path)}
        else:
            result = api.exporting(msg["from"], cfg, out_dir)
            reply = {"status": "ok", "export_path": str(result.export_path)}
        reply["issues"] = _issues_of(context)
        return reply


def _run_reply(run_folder, result, context) -> dict:
    """The reply of a ``run`` command: the folders of the stages that ran, the
    manifest of the last of them, the paths it produced, and the issues."""
    ran = [stage for stage in PIPELINE_STAGES if getattr(result, stage) is not None]
    reply = {
        "status": "ok",
        "stage_folders": {stage: str(stage_folder(run_folder, stage)) for stage in ran},
        "manifest": str(stage_folder(run_folder, ran[-1]) / "manifest.json"),
        "issues": _issues_of(context),
    }
    if result.exporting is not None:
        reply["export_path"] = str(result.exporting.export_path)
    if result.massing is not None:
        reply["plates_path"] = str(result.massing.plates_path)
        reply["mesh_path"] = str(result.massing.mesh_path)
    return reply


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
    """Validate a request and run it.

    Malformed requests (not a dict, unknown command, missing keys) get an
    error reply; exceptions raised while running a command propagate to the
    caller.
    """
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
        # Return unused GPU memory after every command, successful or not, so
        # the Rhino viewport gets it back.  The session cache stays: its keys
        # cover the geometry and settings, and its size is capped.
        sess.release_memory()


def serve(address, authkey, device_arg="auto"):
    """Serve pipeline requests from Grasshopper and the CLI until "shutdown".

    Keeps one CarverSession (CUDA context and compiled Warp kernels) alive
    across requests. Commands: run, preprocessing, thresholding, exporting, massing,
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
