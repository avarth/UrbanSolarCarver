# Engine requests

`urbansolarcarver.engine_requests` turns a request message into an engine call and a reply. Every transport uses it: the [daemon](daemon.md) today, a local HTTP service later. It does not import torch until a request runs.

- `parse_engine_request(message)` validates a dict into one of the request models below, or raises `MalformedEngineRequest` (a `ValueError`) when the message is not a dict, names an unknown command, or lacks or misuses a key.
- `config_for_engine_request(request)` builds the config: from the YAML file in `config` with `overrides` on top, or, without a file, from the starting values of the mode the overrides name (`load_config.build_config_from_mode_starting_values`).
- `handle_engine_request(request, session, context=None)` runs the request inside a run context and returns a reply model; engine errors propagate. A given `RunContext` receives progress, issues and cancellation.
- `answer_engine_message(message, session)` does all of this for transports that carry dicts and never raises: any failure becomes an error reply.

## Commands

**`run`** runs the stages needed to produce `produce`, through the same sequencer as `run_pipeline()`.

| Request key | Meaning |
|-------------|---------|
| `produce` | List of stages to produce: `preprocessing`, `thresholding`, `exporting`, `massing` |
| `run_folder` | The folder that holds one subfolder per stage |
| `start_from` | First stage to run (default `preprocessing`); earlier stages are read from `run_folder` |
| `config` | Optional path of a YAML config |
| `overrides` | Optional list of `key=value` strings, or a mapping |
| `trace_criteria` | Chain files only: list of criterion ids to trace again when starting from `preprocessing`; the others reuse their existing preprocessing. Default: all |
| `threshold_from_criterion` | Chain files only: the id of the criterion thresholding starts at. With `trace_criteria` it applies when that criterion comes before the first traced one (its preprocessing is read as it is); with `start_from: "thresholding"` the criteria before it keep their thresholding folders. Default: thresholding starts at the first traced criterion, or at the first criterion when nothing is traced |
| `after` | Configs without `criteria:` only, with `start_from` `thresholding`: the previous criterion's thresholding folder or `manifest.json`, passed to thresholding as `after`. A chain file, or a run that starts anywhere else, gets a `ConfigError` reply. Default: none |

When `config` is a chain file (a `criteria:` list), `run` runs the chain through `run_chain` and `overrides` set the shared settings only; `run_folder` then holds `criteria/<id>/...`, `exporting` and `massing` (see [Criteria](../criteria.md)). The reply's `stage_folders` and `manifest` point at the last criterion's folders and at the chain's exporting and massing. With `trace_criteria`, every criterion from the first traced one on is thresholded again; the ones before it keep their thresholding, unless `threshold_from_criterion` names an earlier one, from which thresholding then starts. With `start_from: "thresholding"`, every criterion is thresholded again unless `threshold_from_criterion` names one; thresholding then starts there and reads the earlier criteria's thresholding folders (a missing one is a `StageChainError` naming it).

Without `config`, the config is built in memory from the starting values of the mode named in the overrides (`mode` is required) with the overrides on top; no file is written.

The reply holds `stage_folders` (stage name to folder, only for the stages that ran in this call), `manifest` (the manifest of the last of them), `issues`, and `export_path` (exporting), `plates_path`, `mesh_path` (the OBJ) and `export_mesh_path` (the plates in `final_mesh_format`) (massing) for the stages that produced them.

**`preprocessing`, `thresholding`, `exporting`, `massing`** run one stage. They need `config`; every stage but preprocessing also needs `from`, the upstream stage's folder or manifest. `out_dir` defaults to `<config out_dir>/<stage>`. `thresholding` also takes `after`, the previous criterion's thresholding folder or `manifest.json` (`StageRequest.after`): the stage then decides only among the voxels that criterion kept, and `out_dir` may not be that criterion's own folder. The reply has `issues` and `manifest`, `export_path` (exporting) or `plates_path`, `mesh_path` and `export_mesh_path` (massing).

**`run_pipeline`** runs preprocessing, thresholding and exporting into `out_dir` (default: the config's `out_dir`); Grasshopper definitions saved before `run` existed still send it. **`simulate_weights`** writes a simulated-weights file (`epw`, `archetype`, `out`, optional `internal_gains_w_m2` and `eps`) and replies with `artifact` and `preview`. **`ping`** replies with the process id (`pid`) and `features`, a list of what this engine supports beyond the first version (`run_after`: the `after` key of `run`), so a client can tell an older engine.

**`check`** runs one Simulate study: the sun and sky check (`solar_check.simulate_study`) of a test surface file against the project's geometries, written to `out_dir`. It samples the test surface in the maximum volume's local frame (its minimum corner rounded to 1 µm, as preprocessing does) and traces every sun or sky direction against each geometry with Warp, without a carving run.

| Request key | Meaning |
|-------------|---------|
| `test_surface_path` | The mesh file of the test surfaces |
| `max_volume_path` | The mesh file of the maximum volume |
| `out_dir` | Where `check_summary.json`, `check_points.npz` and `check_values.npz` are written |
| `settings` | `CheckSettings` values (`metric`, the period, `sample_spacing`, `rays_per_patch`, ...); an invalid one is a `ConfigError` reply |
| `run_folder` | Optional run folder: its built envelope (`exporting`) and massing are added as columns, found through their manifests and clipped by the maximum volume. A manifest that exists but cannot be read or names no mesh leaves its geometry out, with the issue `geometry_manifest_unusable` naming the geometry and the file |
| `context_path`, `terrain_path` | Optional mesh files that block in every column; a file without triangles is ignored with an issue |
| `voxel_size` | Surface tolerance of the envelope and massing when the run folder does not record the voxel size they were built with (default 1.0) |
| `device` | `auto` (default), `cpu` or `cuda` |

The columns are `open` (no geometry), `max_volume`, then `envelope` and `massing` when built; the summary compares them with `max_volume`. Progress is reported per kernel launch under the stage `check`, and a cancel raises `RunCancelled` between launches. More than 2 million test points (`solar_check.MAX_CHECK_POINTS`, estimated from the test surfaces' area and `sample_spacing`) is an `InputError` naming the spacing that fits. The summary records under `fingerprints` what the result was computed from: `test_surface`, `max_volume`, `geometries` (the envelope's and massing's meshes, only those built), `weather` (only for a metric that reads it), `context` and `terrain` (each `{path, size, modified_ns}`, or null) and `settings_digest` (sha256 of the settings' JSON, sorted keys, without `epw_path`, which `weather` records), so a client can tell that a result is out of date. The reply has `summary_path` and `issues`.

Keys a command does not use are ignored. Reply fields that are None are left out.

## Replies

Every reply to a run or stage command has `issues`, a list of `{stage, code, message}`. An error reply has `error` (the text), `error_type` (the exception class name; `MalformedEngineRequest` for a malformed request) and, for a `ConfigError`, `config_errors`, a list of `{field, message}`.

::: urbansolarcarver.engine_requests
