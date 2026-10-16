# Stage contract restructure: design

Status: approved section by section in conversation on 2026-10-16; this
document awaits review as a whole.
Branch: `claude/backend-correctness-and-stage-contract-3612b2`, on top of the
phase 1 commits (A1 to A6, see the CHANGELOG "Fixed (stage chain)" entries).

## 1. Goal and constraints

The stage layer (preprocessing, thresholding, exporting, massing) should be a
contract that a local HTTP engine service and a browser UI can use without
copying engine logic, the way the CLI, the daemon and Grasshopper use it
today.

Constraints:

- The flat YAML format, `load_config`, CLI overrides and the Grasshopper
  inputs stay as they are for users.
- The future HTTP service runs in its own process and calls the engine in
  process, like the daemon. The daemon stays Grasshopper's engine process.
  Progress, issues and cancel are therefore plain Python objects that either
  process forwards.
- Each piece of this design is either asked for in the brief or follows from
  a decision recorded below. Hashes, schema versions, atomic writes,
  redesigned result classes and automatic reuse were considered and left out
  because nothing would read them yet.

Out of scope: splitting `grid.py`, `raytracer.py` and `carving.py` by
responsibility; a cached sky-weights step; removing the torch tracer
fallback; the typed daemon protocol; test markers, CI and packaging; a
config workflow built around run folders (see section 10).

## 2. Decisions

| # | Question | Decision |
|---|---|---|
| D1 | How does the HTTP service call the engine? | In process, in its own process. The daemon stays for Grasshopper. |
| D2 | Should the engine notice an input file edited in place? | No content hashing. A random run ID per stage run checks chain consistency, and massing reads a footprint that preprocessing saved, so no stage reads an input file after preprocessing. |
| D3 | How does a caller say what to run? | `produce` (the stages wanted) and `start_from`, not a linear `last_stage`. |
| D4 | How do user-facing issues relate to Python warnings? | A per-run collector first; without one, issues become `warnings.warn` as today. |
| D5 | How does Grasshopper get engine facts it cannot import? | It loads standard-library-only engine modules by file path, as it loads `usc_gh.py`. |
| D6 | How do per-stage settings relate to the flat config? | Typed per-stage models projected from `UserConfig`. |
| D7 | Stage hashes? | None. Run IDs answer "is the chain consistent", and comparing settings models answers "what must rerun". |
| D8 | Mode starting values (per-mode period, angle, carve fraction)? | They fill a new config only (Grasshopper's Config through the daemon). Schema defaults and validation do not change. |
| D9 | YAML configs? | Unchanged. "The config lives with the run" is recorded as future work. |

## 3. Settings models and rerun decisions

New module `src/urbansolarcarver/stage_settings.py`. Five frozen pydantic
models, each built with `from_config(config: UserConfig)`:

| Model | Fields |
|---|---|
| `PreprocessingSettings` | `max_volume_path`, `test_surface_path`, `epw_path`, the six period fields, `mode`, `voxel_size`, `grid_step`, `margin_frac`, `edge_taper`, `ray_length`, `min_altitude`, `sun_steps_per_hour`, `north_deg`, `dew_point_celsius`, `bliss_k`, `min_sky_elevation_deg`, `balance_temperature`, `balance_offset`, `simulated_weights_path`, `include_harm`, `tilted_plane_angle_deg` |
| `ThresholdingSettings` | `threshold`, `carve_fraction`, `score_smoothing`, `carve_above`, `carve_above_min_consecutive`, `max_slope_deg` |
| `ExportingSettings` | `final_mesh_format`, `apply_smoothing`, `min_voxels`, `min_face_count`, `smooth_iters` |
| `MassingSettings` | `ground_floor_height`, `floor_height`, `min_plate_dimension`, `plate_tolerance`, `plate_stacking` |
| `RunOptions` | `out_dir`, `device`, `ray_batch_size`, `diagnostics`, `diagnostic_plots` |

A test checks that every `UserConfig` field belongs to exactly one model.

Stage internals receive their own settings model, the `RunOptions`, and the
upstream manifest. The public functions keep their signatures
(`thresholding(config, upstream, out_dir)` and so on) and project the config
themselves, so existing callers and tests do not change.

**Effective values.** Each settings model has `effective_values(...)`, a
mapping of what the stage will apply, used for comparisons:

- Preprocessing leaves out the mode-specific fields its mode does not read
  (`mode_registry.MODES[mode].extra_params`).
- Thresholding takes `mode` and `voxel_size` and returns the resolved
  threshold (`resolve_threshold`), the applied smoothing radius in meters
  (after the 0.5 to 8 voxel clip) and the resolved slope limit, so unset and
  explicit defaults compare equal. The stage takes `mode` and `voxel_size`
  from the preprocessing manifest; comparisons between configs take them from
  the configs.
- Exporting leaves out `smooth_iters` when `apply_smoothing` is off.
- `RunOptions` is never compared: `device` (CPU and CUDA can differ in the
  last float bits) and `ray_batch_size` (no effect on results) are recorded in
  diagnostics instead.

**Rerun decision.** `stages_to_rerun(previous_config, new_config, produce)
-> list[str]`, in `stage_settings.py`, returns the stages to run in pipeline
order:

- preprocessing effective values differ: preprocessing, thresholding and the
  produced leaves;
- else thresholding differs: thresholding and the produced leaves;
- else each produced leaf whose own effective values differ.

`previous_config=None` returns every stage needed for `produce`. The function
compares settings only; whether an input file changed, or whether a leaf was
ever run, is the caller's knowledge.

## 4. Manifests, stage folders, results

**Manifests** (`pydantic_schemas.py`). Every manifest has `run_id`
(`uuid4().hex`, new on every run of that stage). Downstream manifests add
`upstream_manifest` and `upstream_run_id`. Fields are required unless absent
by nature. The `hash` and `upstream_hash` fields go.

| Manifest | Facts |
|---|---|
| `PreprocessingManifest` | `scores_path`, `scores_kind`, `shape`, `origin`, `voxel_size`, `mode`, `voxel_grid_path`, `patch_weights_path` (absent in violation-count modes), `sample_point_count`, `footprint_path` |
| `ThresholdingManifest` | `mask_path`, `resolved_threshold`, `score_smoothing_m`, `max_slope_deg` |
| `ExportingManifest` | `mesh_path` |
| `MassingManifest` | `plates_path`, `mesh_path` |

`PreprocessingManifest.max_volume_path` (added in A4) is removed: massing no
longer reads the mesh.

**Paths** are stored relative to the manifest's own folder (`scores.npy`,
`../preprocessing/manifest.json`), so a run folder can be copied or moved and
its manifests still point inside it. When no relative path exists (another
drive on Windows), the absolute path is stored.

**Footprint.** Preprocessing writes `footprint.json`: the max volume's plan
projection (`floor_plates.footprint_polygons`) in world xy, a list of
polygons with exterior and holes. When the projection fails or covers no
area, the list is empty and preprocessing reports an issue; massing then uses
the voxel footprint with its existing warning. Massing's mismatch check
(`FOOTPRINT_MISMATCH_SHARE`) stays as a guard.

**Stage folder helper**, new module `api_core/_stage_io.py`:

- `stage_folder(run_folder, stage) -> Path`: `<run_folder>/<stage>`, the one
  definition of the layout.
- `begin_stage(out_dir, stage, output_names) -> Path`: creates the folder and
  deletes the previous manifest and the stage's listed outputs
  (`remove_previous_stage_outputs` today). It runs before the upstream is
  validated, so a stage refused for a bad upstream also loses its previous
  outputs, which no longer match what was asked for.
- `commit_manifest(folder, manifest)`: writes `manifest.json`, last.
- `load_upstream(source, expected_stage) -> (manifest, folder)`: `source` is
  a Result, a folder or a `manifest.json` path. It parses the manifest,
  resolves its relative paths, checks the stage, and checks its
  `upstream_run_id` against its own upstream manifest. Any failure raises
  `StageChainError` naming the stage to re-run.

This replaces `load_thresholded_grid`'s loading code and the manifest code in
each stage. Each stage module keeps its tuple of output names (from A5).

**Results** keep today's classes and attributes, with two changes: every
Result gains `issues` (a tuple of `Issue`, section 5), and `hash`/`upstream`
become `run_id`/`upstream_run_id`.

## 5. Run context and exceptions

**`RunContext`**, new module `src/urbansolarcarver/run_context.py`
(standard library only):

- `Issue(stage, code, message)`: a frozen dataclass. `code` is a short
  stable name (`all_false_mask`, `footprint_mismatch`,
  `carve_fraction_unused`, ...). Issues are warnings; errors are exceptions,
  so there is no severity field.
- `RunContext(on_progress=None)` holds the issues, the current stage name,
  the optional progress callback and a `threading.Event` for cancel.
  Methods: `issues`, `cancel()`, `raise_if_cancelled()`.
- The active context lives in a `contextvars.ContextVar`. `with
  run_context(context):` activates it; module functions
  `report_issue(code, message)` and `report_progress(done, total)` act on the
  active one. Without an active context, `report_issue` calls
  `warnings.warn(message, UrbanSolarCarverWarning)` and `report_progress`
  does nothing.
- A public stage function called without an active context creates one for
  its own call whose issues also go to `warnings.warn`, and returns them in
  the Result. Called by the sequencer, it uses the sequencer's context.

Callers: the 31 `warnings.warn` sites in the engine and the config validators
become `report_issue` calls with a code, except the two internal ones
(`raytracer.py` Warp unavailable, `simulated_weights.py` attribution range),
which become `log.warning`. `UrbanSolarCarverWarning` subclasses
`UserWarning`, so `pytest.warns(UserWarning)` keeps working.

Progress: the sequencer reports each stage's start and end;
`carving._run_batches` reports once per batch. Cancel: the sequencer checks
between stages, `_run_batches` before each batch; worker threads receive the
event captured before they start. Nothing cancels a daemon run yet (the
daemon serves one request at a time); the HTTP service will.

**Exceptions**, new module `src/urbansolarcarver/errors.py` (standard library
only):

| Class | Bases | Raised for |
|---|---|---|
| `UrbanSolarCarverError` | `Exception` | base of the four below |
| `ConfigError` | base, `ValueError` | invalid settings, including a grid over the voxel budget (field `voxel_size`); carries `errors: list[ConfigFieldError]`, where `ConfigFieldError(field: str or None, message: str)` |
| `InputError` | base, `ValueError` | unusable inputs: missing mesh, EPW or weights file, no sample points, empty grid, test surfaces that do not face up in radiative_cooling |
| `StageChainError` | base, `ValueError` | missing, old or mismatched upstream manifest or upstream outputs; replaces phase 1's `UpstreamMismatchError` (unreleased) |
| `RunCancelled` | base | the cancel flag was set |

Only raise sites in the config, input and stage layers convert. The argument
checks in the math modules stay `ValueError`; anything else (CUDA out of
memory, a bug) propagates unchanged. Sites that raise `FileNotFoundError`
today for a missing input or upstream file become `InputError` or
`StageChainError`; the changelog says so.

## 6. Config input

In `load_config.py`:

- `build_config(values: Mapping, base_folder: Path | None = None) ->
  UserConfig`: expands `analysis_period`, resolves relative path fields
  against `base_folder` (left as given when it is None), validates, and
  raises `ConfigError` with one `ConfigFieldError` per pydantic error (`field`
  is None for whole-config checks). The message text is today's multi-line
  text.
- `load_config(path, overrides)`: reads the YAML, merges the overrides
  (`key=value` strings or a mapping), calls `build_config` with the YAML's
  folder. Behavior unchanged; malformed YAML raises `ConfigError`, a missing
  file still `FileNotFoundError`.
- Config warnings come from the validators through `report_issue`, so they
  are Python warnings outside a run and the run's issues inside one.

## 7. Sequencer and clients

**Sequencer** in `api.py`:

```python
run_pipeline(config, out_dir, produce=("exporting",), start_from="preprocessing",
             context=None) -> PipelineResult
```

- `produce` names any stages; the sequencer runs `start_from` and every
  stage on the path to each produced stage, in order. A `start_from` that is
  not on that path raises `ValueError`.
- Starting after preprocessing, it loads the existing upstream manifests in
  `stage_folder(out_dir, ...)` through `load_upstream`.
- `config` is a `UserConfig` or a YAML path, as today. With `context=None` it
  creates one.
- `PipelineResult` holds the Result of each stage that ran (attributes
  `preprocessing`, `thresholding`, `exporting`, `massing`, None when not run)
  and the run's issues. Today's `run_pipeline(config, out_dir)` runs the same
  stages; callers that read `result.export_path` change to
  `result.exporting.export_path` (the daemon, the CLI `run` command, one
  test).

**Daemon** (`daemon.py`):

- A new command `run` with `produce`, `start_from` and `run_folder`. The
  config comes from `config` (a YAML path) and `overrides` (strings or a
  mapping) as today, or, with no `config`, from the mode's starting values
  (section 8) plus the overrides, built in memory with `build_config`. No
  file is written. The overrides must then name `mode`.
- The request runs inside a `RunContext`. The reply adds `issues` (a list of
  `{stage, code, message}`) and `stage_folders` (stage name to folder), and
  on error `error_type` (the `UrbanSolarCarverError` subclass name, or the
  built-in type) and, for `ConfigError`, `config_errors`.
- The existing stage commands and `run_pipeline` stay as aliases mapped onto
  `run`; their `from` and per-stage `out_dir` must match `stage_folder(...)`
  or the request is refused with a message. They are removed with the typed
  daemon protocol.

**Grasshopper:**

- Stage components and RunPipeline send `run` and read folders from
  `stage_folders` instead of computing `<out_dir>/<stage>`.
- `usc_gh.py` gains a function that shows the reply's `issues` as warnings
  on the component; each stage component calls it once.
- Config sends no YAML path when the user gives none, so the daemon starts
  from the mode's starting values; `_mode_default_yaml` and
  `_mode_canonical` go.
- Mode lists, descriptions, spellings and archetype defaults come from the
  engine modules of section 8.
- The edited components' `.ghuser` files are rebuilt
  (`grasshopper/build_ghuser.py`).

**CLI** (`carver_cli.py`):

- Stage commands and `run` call `run_pipeline` with `produce` and
  `start_from`, locally or through the daemon's `run`; `_find_manifest` uses
  `stage_folder`.
- `--dry-run` calls `grid_planning` directly instead of the private
  `_reporting.estimate_grid_memory` (which moves to `grid_planning` as
  `estimate_grid_memory`).
- The archetype command takes its defaults from `archetype_defaults.py`.
- Issues are printed after each command; errors print their message and exit
  1 instead of a traceback for `UrbanSolarCarverError`.

**Run report**: written by exporting and massing at their end, as today
(also when the sequencer calls them). The sibling lookup uses `stage_folder`
and compares run IDs instead of hashes.

## 8. Engine facts for Grasshopper and the per-mode configs

Standard-library-only modules that `usc_gh.py` loads by file path:

- `mode_registry.py` (exists). `ModeSpec` gains `description` (from
  `USC_Mode.py`) and `starting_values` (a mapping). The module gains
  `MODE_ALIASES` (spellings from `USC_Config.py`). `MODES` is reordered to
  Grasshopper's menu order (time-based, irradiance, benefit, daylight,
  radiative_cooling, tilted_plane), so saved Grasshopper value lists keep
  their indices.
- `archetype_defaults.py` (new): the shoebox defaults now in
  `carver_cli.py` (`_ARCHETYPE_DEFAULTS`, `_ARCHETYPE_OPTIONAL`) and
  `USC_Archetype.py` (`_DEFAULTS`, `_WWR_DEFAULTS`). `simulated_weights`
  takes its partial defaults from here.
- `errors.py` and `run_context.py` are standard-library only too, though
  Grasshopper does not need them.

A test imports each of these modules in a subprocess whose path holds only
the standard library and the module's folder.

**Starting values** (D8) move into `ModeSpec.starting_values`, holding only
what differs from the schema defaults in `configs/config_<mode>.yaml` today:
the analysis period (benefit 15 Oct to 15 Apr, irradiance the full year,
time-based 21 Dec 10:00 to 14:00), `tilted_plane_angle_deg: 45`, and
`carve_fraction: 0.35` for radiative_cooling. They fill a new config only:
the daemon uses them when Grasshopper's Config sends no YAML. Schema defaults
and validation do not change: time-based still requires a period, and a CLI
config without `carve_fraction` keeps 0.7 in every mode.

`configs/config_<mode>.yaml` stay hand-written, commented examples for CLI
users; Grasshopper no longer reads them. A test checks that each file's
values agree with its mode's starting values, so the two cannot drift. The
UTF-8 byte order marks in three of them are removed.

## 9. Diagnostics separated from compute

- Each stage builds its `summary` dict as today and ends with one call into
  `_diagnostics.py` (`write_preprocessing_diagnostics(summary, folder,
  run_options, ...)` and so on), which writes `diagnostic.json`, the config
  snapshot (preprocessing) and, with `diagnostic_plots`, the plots. The plot
  and statistics code in `preprocessing.py` and `thresholding.py` moves there.
- `diagnostic.json` keys stay exactly as they are (the run report and
  Grasshopper read them).
- `_diagnostics.py` stops calling `matplotlib.use("Agg")` at import; plots
  draw on `matplotlib.figure.Figure` with the Agg canvas, as
  `simulated_weights._save_heatmaps` does, and matplotlib loads only when a
  plot is drawn.
- The benefit comparison plot (simple against simulated weights) keeps its
  second EPW parse, now in the diagnostics code and only with
  `diagnostic_plots`; avoiding it needs the cached sky-weights step (out of
  scope).

## 10. Future work (not in this spec)

- **The config lives with the run.** Reuse a run's config with a few
  overrides (`usc run --from-run <folder> -o ...`, and opening a run in the
  browser UI) instead of hand-kept YAML files. Its first step is each stage
  saving its settings model beside its outputs, so a run folder describes
  every stage, not only preprocessing. To be decided with the UI design.
- **Saved, named configs** in the browser UI: a UI feature with its own
  store.
- **Automatic reuse** ("rerun only what changed" without the caller
  deciding): needs stage hashes over effective settings plus input file
  contents, added together with the code that reads them.
- **Cancel from Grasshopper**: needs the typed daemon protocol.

## 11. Migration

- Every existing run folder needs one re-run from preprocessing: old
  manifests lack `run_id` and fail to load with `StageChainError` ("re-run
  preprocessing").
- `run_pipeline` returns `PipelineResult`; `result.export_path` becomes
  `result.exporting.export_path`.
- Results: `hash` becomes `run_id`.
- Some `FileNotFoundError` become `InputError` or `StageChainError`
  (both `ValueError`).
- The `.ghuser` files of the edited components are rebuilt and committed
  with their sources.

All of these go in the CHANGELOG.

## 12. Testing and implementation order

Each step leaves the full suite green (572 tests at the start; the slow
daemon and typology tests included before each commit that touches them).

1. `errors.py` and `run_context.py`; engine `warnings.warn` sites to
   `report_issue`; config validators; `ConfigError` from `load_config`.
   Tests: issues collected per run, repeats included; fallback to warnings;
   `ConfigError.errors` fields.
2. `stage_settings.py` with `effective_values` and `stages_to_rerun`.
   Tests: field coverage; equal effective values for unset and explicit
   defaults; `stages_to_rerun` per stage; mode-irrelevant fields ignored.
3. Manifests with run IDs and relative paths, `_stage_io.py`, footprint in
   preprocessing, massing reading it; stage internals taking settings
   models. Tests: phase 1 tests retargeted to `StageChainError` and
   `run_id`; a moved run folder still runs exporting; massing ignores an
   edited max volume file; mismatched run IDs refused.
4. Diagnostics move. Tests: `diagnostic.json` keys unchanged (the existing
   report and typology tests); importing `urbansolarcarver.api` does not
   import matplotlib.
5. Sequencer and `PipelineResult`. Tests: `produce`/`start_from`
   combinations; invalid `start_from`; cancel between stages and between
   batches; progress callback calls.
6. Clients: daemon `run`, aliases and reply fields; CLI commands,
   dry-run; `mode_registry` and `archetype_defaults` additions; Grasshopper
   `usc_gh.py` and components, `.ghuser` rebuild. Tests: daemon replies with
   issues and error types; the daemon building a config from starting values
   without a YAML; `configs/` agreeing with the starting values; the
   standard-library import check; existing Grasshopper component tests.
