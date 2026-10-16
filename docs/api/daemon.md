# Daemon

A persistent background process that keeps a `CarverSession` (and with it the CUDA context) alive for low-latency calls from Grasshopper or other clients. It communicates via Python's `multiprocessing.connection` over localhost; clients authenticate with a random key stored in `~/.urbansolarcarver/.daemon_authkey`.

The daemon is started and stopped via the CLI (`urbansolarcarver daemon start/stop`, `daemon status` to check it) or from within Grasshopper using the `USC_Session` component. It binds to `127.0.0.1` only and is not reachable from the network.

## Commands

Each request is a dict with a `cmd` key; the reply is a dict with `status` (`"ok"` or `"error"`).

**`run`** runs the stages needed to produce `produce`, through the same sequencer as `run_pipeline()`.

| Request key | Meaning |
|-------------|---------|
| `produce` | List of stages to produce: `preprocessing`, `thresholding`, `exporting`, `massing` |
| `run_folder` | The folder that holds one subfolder per stage |
| `start_from` | First stage to run (default `preprocessing`); earlier stages are read from `run_folder` |
| `config` | Optional path of a YAML config |
| `overrides` | Optional list of `key=value` strings, or a mapping |

With `config`, the file is loaded and the overrides applied. Without it, the daemon builds the config in memory from the starting values of the mode named in the overrides (`mode` is required) with the overrides on top; no file is written.

The reply holds `stage_folders` (stage name to folder, only for the stages that ran in this call), `manifest` (the manifest of the last of them), `issues`, and `export_path` (exporting), `plates_path` and `mesh_path` (massing) for the stages that produced them.

Every reply to a stage command has `issues`, a list of `{stage, code, message}`. An error reply has `error` (the text), `error_type` (the exception class name) and, for a `ConfigError`, `config_errors`, a list of `{field, message}`.

**`preprocessing`, `thresholding`, `exporting`, `massing`, `run_pipeline`** run one stage (or the default chain) on the folders given in the request (`from`, `out_dir`) and reply as before, plus `issues`. They remain for clients with their own folder layout. **`simulate_weights`**, **`ping`** and **`shutdown`** are unchanged.

::: urbansolarcarver.daemon
