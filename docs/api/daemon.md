# Daemon

A persistent background process that keeps a `CarverSession` (and with it the CUDA context and the compiled Warp kernels) alive for low-latency calls from Grasshopper or other clients. It communicates via Python's `multiprocessing.connection` over localhost; clients authenticate with a random key stored in `~/.urbansolarcarver/.daemon_authkey`.

The daemon is started and stopped via the CLI (`urbansolarcarver daemon start/stop`, `daemon status` to check it) or from within Grasshopper using the `USC_Session` component. It binds to `127.0.0.1` only and is not reachable from the network.

## A transport over the engine requests

The daemon only carries messages. Each request is a dict with a `cmd` key; the daemon passes it to `engine_requests.answer_engine_message`, which runs it and returns the reply dict, with `status` `"ok"` or `"error"`. The commands, their keys and their replies are described in [Engine requests](engine-requests.md). The daemon itself handles one more command, **`shutdown`**, which stops it.

Clients reach it through `daemon_client.py`, which uses only the standard library: `resolve_daemon_authkey` reads (or creates) the key and `send_daemon_request` sends one request, so asking the daemon something does not load torch. Grasshopper keeps its own copy of the key reading in `usc_gh.py`, because Rhino's Python does not import this package.

A message the daemon cannot unpickle gets an error reply too, and the daemon keeps running. Failed requests are logged with their traceback in the daemon's console or log file.

::: urbansolarcarver.daemon
