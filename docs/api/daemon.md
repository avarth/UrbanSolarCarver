# Daemon

A persistent background process that keeps a `CarverSession` (and with it the CUDA context) alive for low-latency calls from Grasshopper or other clients. It communicates via Python's `multiprocessing.connection` over localhost; clients authenticate with a random key stored in `~/.urbansolarcarver/.daemon_authkey`.

The daemon is started and stopped via the CLI (`urbansolarcarver daemon start/stop`, `daemon status` to check it) or from within Grasshopper using the `USC_Session` component. It binds to `127.0.0.1` only and is not reachable from the network.

::: urbansolarcarver.daemon
