# Project Map

Overview of the files and directories in the repository.

## Repository root

```
UrbanSolarCarver/
├── src/urbansolarcarver/   Core Python package
├── configs/                YAML config templates (one per mode + reference + archetype example)
├── examples/               Example data, weather file, and Jupyter notebook tutorials
├── tests/                  Pytest suite
├── grasshopper/            Rhino Grasshopper plugin
├── docs/                   MkDocs documentation source
├── design/                 Design notes (simulated benefit weights)
├── pyproject.toml          Package metadata and dependencies
├── setup_env.py            Automated environment setup (GPU detection)
├── mkdocs.yml              Documentation site configuration
├── CHANGELOG.md            Release history
├── CITATION.cff            Citation metadata
├── CONTRIBUTING.md         Contribution guidelines
├── LICENSE                 AGPL-3.0
└── README.md               Project landing page
```

## Source code (`src/urbansolarcarver/`)

### Pipeline orchestration

| File | Purpose |
|------|---------|
| `__init__.py` | Package entry point. `load_config`, `build_config` and `user_config` are imported directly; `run_pipeline`, `PipelineResult`, `stages_to_rerun`, the four stage functions and their result types are loaded from `api.py` on first access, so `import urbansolarcarver` and light CLI commands do not import torch or Warp. |
| `api.py` | Public facade. Defines `run_pipeline(config, out_dir, produce, start_from, context)`, the sequencer: it runs the stages needed for `produce`, each writing into `<out_dir>/<stage>`, and returns a `PipelineResult` (one Result per stage that ran, plus the run's issues). Re-exports `stages_to_rerun()`, `preprocessing()`, `thresholding()`, `exporting()`, `massing()`, their result types, `load_config()` and `build_config()`. |
| `api_core/__init__.py` | Collects the three stage modules and their result types into one importable sub-package. |
| `api_core/preprocessing.py` | **Stage 1.** Voxelizes the max-volume mesh into a dense 3D grid, samples test surfaces into evenly spaced points with outward normals, generates rays toward sky patches (or sun positions, or the tilted-plane direction, depending on mode), traces them through the grid with the DDA kernel, and writes the per-voxel obstruction scores to `scores.npy`. Also writes `voxel_grid.npy`, `footprint.json` (the plan projection of the voxelized mesh, which massing reads), the sample points and normals, the manifest, and diagnostics (JSON always; plots with `diagnostic_plots: true`). |
| `api_core/thresholding.py` | **Stage 2.** Loads `scores.npy` from Stage 1, optionally applies Gaussian score smoothing (weighted modes), applies the selected thresholding strategy (`carve_fraction`, `headtail`, or a numeric cutoff) to the raw scores of the occupied voxels together with `carve_above` (`carving.carve_above_scores`, so `carve_fraction` counts what carve_above removes), applies the slope limit (`carving.limit_column_slope`; 75 degrees by default for the weighted modes), and writes the binary mask `mask.npy`. Can be re-run with different threshold parameters without re-computing scores. |
| `api_core/massing.py` | **Stage 4.** Reads the thresholding chain, builds floor plates with `floor_plates.py`, writes `plates.json` (world outlines), `plates.obj` (one closed prism per plate), the manifest, diagnostics and the run report with a Massing section. |
| `floor_plates.py` | Floor-plate massing geometry: base outline and facades split at corners, faces by nearest facade with squared corners, bays cut perpendicular to the facades, floor-by-floor bay selection (tolerance, maximum volume, stacking, minimum width), plate outlines and closed prisms. |
| `api_core/exporting.py` | **Stage 3.** Loads the binary mask from Stage 2, removes small disconnected voxel clusters, reconstructs a triangle mesh (cubic voxel faces, or SDF-smoothed marching cubes with Taubin polishing), writes `export.<format>`, and writes `run_report.md` for the whole run. |
| `api_core/_stage_io.py` | The start and end of a stage (`begin_stage`, `commit_manifest`), manifest paths relative to the manifest's folder (`stored_path`) and reading an upstream manifest with its run ID check (`load_upstream`). |
| `api_core/_util.py` | Helpers shared by the stages: config resolution, device resolution (`"auto"` → `"cuda"` or `"cpu"`), JSON writing, reloading the occupancy grid, config snapshots. |
| `api_core/_diagnostics.py` | Writes each stage's `diagnostic.json` and, with `diagnostic_plots`, its plots (`write_preprocessing_diagnostics`, `write_thresholding_diagnostics`) after the stage's compute; score histograms, sky-patch hemisphere plots, the simple-vs-simulated weight comparison dome, score statistics, NaN/Inf issues. matplotlib loads when a plot is drawn. |
| `api_core/_reporting.py` | `run_report.md` generation. |

### Geometry

| File | Purpose |
|------|---------|
| `surface_sampling.py` | Test-surface sampling. Discretizes each planar test-surface component into a regular grid of points with outward normals, projecting each face into its local 2D plane and using Shapely `contains_xy` for the in-polygon test; also computes the `edge_taper` weights and the analysis-mesh quads (`AnalysisMesh`). **`sample_surface`** is the preprocessing entry point. |
| `voxelization.py` | Converts a watertight mesh into a dense cubic boolean grid at the configured `voxel_size`, using the Warp parity voxelizer (`voxelize_solid_warp`, kernel in `warp_kernels.py`) (trimesh's rasterize-and-fill when Warp cannot run on the device) and filling enclosed cavities; the grid is cached in the active `CarverSession`. **`voxelize`** is the preprocessing entry point. |
| `meshing.py` | Mesh reconstruction. Removes small disconnected voxel clusters with `scipy.ndimage.label` and converts carved voxel masks back to triangle meshes, either as cubic voxel faces or through signed-distance-field smoothing, marching cubes, and Taubin polishing. **`finalize_mesh`** is the exporting entry point. |
| `io.py` | Mesh file I/O. **`load_mesh`**: reads a mesh through Trimesh (PLY, OBJ, STL...), rejects files without triangles, and runs `fix_normals` on meshes that are not watertight. **`save_mesh`**: writes a mesh; PLY files switch to double-precision vertices when float32 would round the coordinates. |

### Carving engines

| File | Purpose |
|------|---------|
| `carving.py` | The three carving strategies. **`carve_with_sun_rays`** (`time-based`): traces rays from test-surface points toward the sun positions of the analysis period and returns the carved grid and per-voxel hit counts. **`carve_with_sky_patch_rays`** (`irradiance`, `benefit`, `daylight`, `radiative_cooling`): traces rays toward the 145 Tregenza sky patches, weights each ray by its patch's mode-specific value, and returns the accumulated per-voxel scores. **`carve_with_planes`** (`tilted_plane`): traces one ray per sample point at the plane angle (per-octant angles supported) and removes every voxel at or above it in its column. Also `carve_above_columns()` (the `carve_above` post-processing), `validate_inputs()` (checks that input files exist), `load_meshes()` (loads max volume + test surfaces), and `sample_period()` (builds the analysis date/time list with Ladybug's `AnalysisPeriod`). |
| `ray_tracing.py` | Ray generation and voxel traversal. **`trace_and_score_dda`** / **`trace_and_count_dda`**: launch the Digital Differential Analyzer (DDA) kernels that step each ray through the voxel grid cell by cell and add the ray's weight (or a count of 1) to every voxel it crosses; they run on CUDA or on Warp's CPU backend, and without Warp a fixed-step PyTorch marcher (`trace_multi_hit_grid`, approximate) is used. **`follow_mass_behind_skin_dda`**: the skin rule. **`generate_sky_patch_rays`** / **`generate_sun_rays`**: expand sample points × directions into flat ray arrays, keeping only directions the surface faces. **`auto_batch_size`**: picks a ray batch size from the free GPU memory. |
| `warp_kernels.py` | Warp setup and every Warp kernel of the package (DDA traversal, skin rule, parity voxelizer), kept in one module so Warp compiles and caches them as one unit. **`dda_backend_available`**: whether the exact DDA backend can run on a device. **`warmup_kernels`**: precompiles the kernels. |

### Sky and sun models

| File | Purpose |
|------|---------|
| `sky_patches.py` | Tregenza hemisphere subdivision (145 patches) used by the weighted carving modes. **`fetch_tregenza_patch_directions`**: the 145 unit direction vectors. **`fetch_tregenza_patch_solid_angles`**: the solid angle (sr) of each patch. **`compute_EPW_based_weights`**: for `irradiance` and `benefit`, builds a Ladybug `SkyMatrix` (Perez all-weather model) from the EPW's direct-normal and diffuse-horizontal irradiance over the analysis period; benefit keeps only the hours below the balance point, or scales each hour by simulated weights. For `daylight`, returns the CIE standard overcast luminance distribution (brightest at the zenith, no EPW). **`compute_radiative_cooling_weights`**: long-wave cooling potential per patch from the Martin-Berdahl clear-sky emissivity with Bliss angular attenuation, for a horizontal surface; patches near the zenith get higher weights than those near the horizon. |
| `sun.py` | Solar position vectors. **`get_sun_vectors`**: uses Ladybug's `Sunpath` with the location from the EPW header to return unit vectors toward the sun for each sampled date-time of the analysis period (`sun_steps_per_hour` per hour), dropping positions below `min_altitude` and rotating by `north_deg`. |
| `scoring.py` | Sky-patch weight dispatch and threshold selection. **`get_weights`**: calls the weighting function for the selected mode (Perez irradiance, heating benefit, CIE daylight, or radiative cooling). **`carve_fraction_threshold`**: the score cutoff above which the voxels hold a given fraction of the total score mass (two-pass weighted histogram, O(N)). **`headtail_threshold`**: Jiang (2013) head/tail breaks for heavy-tailed score distributions. |
| `simulated_weights.py` | Simulated benefit weights (opt-in via `simulated_weights_path`). Implements the ISO 13790 Annex C hourly thermal model ("5R1C": five conductances, one lumped mass capacitance, one zone) in NumPy, and derives the hourly *marginal* benefit/harm of solar gain by perturbation: for each hour of the year, one watt of solar gain is added and removed and the change in annual heating and cooling demand is attributed to that hour (`benefit[t]` / `harm[t]`, both in [0, 1]; all 17,521 year-simulations, the base run plus two per hour, march as one vectorized batch). **`generate_simulated_weights`**: EPW + archetype → `simulated_weights.json` artifact with provenance metadata plus a `.png` heatmap preview. **`ZoneParams.from_archetype`** builds the thermal network from about 10 physical inputs; **`expand_shoebox`** derives all areas from a width/length/height + per-facade window-to-wall ratio shorthand. Validated against ETH's RC_BuildingSimulator (`tests/data/oracle_5r1c_reference.json`). Design note: `design/simulated-weights.md`. |

### Configuration

| File | Purpose |
|------|---------|
| `mode_registry.py` | One `ModeSpec` per carving mode, in Grasshopper's menu order: whether it needs an EPW and an analysis period, its score kind (`weighted_sum` or `violation_count`), its weight unit, the mode-specific settings it reads, its description and its starting values (what differs from the schema defaults: analysis period, tilted-plane angle, carve fraction). Also `MODE_ALIASES` and `canonical_mode_name()`. Validation, the CLI `schema` command, the stages and the Grasshopper components read their mode facts from here. Standard library only. |
| `archetype_defaults.py` | The shoebox archetype defaults (`ARCHETYPE_DEFAULTS`, `WINDOW_TO_WALL_DEFAULTS`, `ARCHETYPE_OPTIONAL_KEYS`) read by `usc archetype`, `simulated_weights.py` and the USC_Archetype component. Standard library only. |
| `errors.py` | `UrbanSolarCarverError` and its subclasses `ConfigError` (with `ConfigFieldError`), `InputError`, `StageChainError`, `MalformedEngineRequest` and `RunCancelled`, plus `UrbanSolarCarverWarning`. Standard library only. |
| `run_context.py` | `RunContext` (issues, progress callback, cancel flag), `Issue`, `report_issue()`, `report_progress()` and `run_context()` / `stage_context()`. Standard library only. |
| `stage_settings.py` | The per-stage settings models (`PreprocessingSettings`, `ThresholdingSettings`, `ExportingSettings`, `MassingSettings`, `RunOptions`), `stages_to_rerun()` and `stage_folder()` (the one definition of the `<run_folder>/<stage>` layout). Does not import torch. |
| `load_config.py` | Reads a YAML configuration file and returns a validated `UserConfig` object. **`load_config`**: loads the YAML, expands an `analysis_period:` mapping, resolves relative paths against the YAML's folder, applies flat `key=value` overrides, and validates with Pydantic (all errors reported in one message). **`build_config`**: validates typed values (what a client holds) into a `UserConfig` and raises `ConfigError` with a `ConfigFieldError` per problem; `load_config` calls it. **`parse_override_value`**: converts override strings into Python values (booleans, None, JSON lists and objects, numbers). |
| `pydantic_schemas.py` | Data schemas. **`UserConfig`**: the Pydantic v2 model defining every pipeline parameter with types, defaults and value ranges (e.g. `voxel_size` must be 0.01-100); unknown keys are rejected. It normalizes `threshold` into a **`ThresholdSpec`**, checks mode requirements, and emits `UrbanSolarCarverWarning` for settings the mode ignores and when `ray_batch_size` is clamped. **`PreprocessingManifest`** / **`ThresholdingManifest`**: schemas for the JSON manifests written by the first two stages, so a later stage can be re-run from an earlier run's output. |

### Infrastructure

| File | Purpose |
|------|---------|
| `session.py` | Compute-session lifecycle. **`CarverSession`**: a long-lived object that keeps the CUDA context alive across pipeline calls and holds a value cache (voxelized grids, Tregenza patch directions and solid angles). Keys cover the geometry, settings and device, so entries stay valid across runs; the cache holds at most 1 GiB (`max_cache_bytes`) and drops the least recently used entries beyond that. The daemon opens one session and keeps its cache between commands, returning only unused GPU memory after each; the Python API and CLI run without a session unless you open one (`with CarverSession():`). Compiled Warp kernels are cached by Warp itself, on disk. **`get_active_session`**: returns the session registered for a device, or `None`. **`session_cache`**: a decorator that stores a function's return value in the active session's cache under a key built from its arguments. |
| `engine_requests.py` | The request core every transport uses. **`parse_engine_request`** validates a message into a typed request (`run`, the stage commands, `run_pipeline`, `simulate_weights`, `ping`); **`config_for_engine_request`** builds its config from a YAML path or from the mode's starting values plus overrides; **`handle_engine_request`** runs it in a run context and returns a typed reply with the run's `issues`; **`answer_engine_message`** does all of this for dict transports and turns any failure into an error reply with `error_type` and, for config errors, `config_errors`. Does not import torch until a request runs. |
| `daemon.py` | Persistent background process for Grasshopper and the CLI's `--daemon` flag, a transport over `engine_requests`. **`serve`**: listens on `127.0.0.1` (localhost only) with Python's `multiprocessing.connection`, authenticated with a random key stored in `~/.urbansolarcarver/.daemon_authkey`. Creates a `CarverSession` on startup and keeps it for the daemon's lifetime; each request goes to `answer_engine_message`, and only `shutdown` is handled by the daemon itself. Started and stopped with the CLI (`urbansolarcarver daemon start/stop`) or from Grasshopper with the `USC_Session` component. |
| `carver_cli.py` | Command-line interface built with Typer, registered in `pyproject.toml` as both `urbansolarcarver` and `usc`. Commands: `run` (the sequencer, with `--produce` and `--start-from`), `preprocessing`, `thresholding`, `exporting`, `massing` (each with a config file `-c`, overrides `-o`, and optional `--daemon`), `validate`, `schema` (prints the config parameter table, filterable by `--mode` or `--search`), `warmup`, `simulate-weights`, `archetype`, and `daemon start/stop/status`. |

## Grasshopper plugin (`grasshopper/`)

```
grasshopper/
├── USC_GHplugin/       27 .ghuser components (copy into the GH User Objects folder)
├── components/         Python source for each component
├── icons/              24×24 component icons
├── components.json     Ribbon group and stable GUID per component
├── usc_gh.py           Helpers shared by the components, loaded at run time
└── build_ghuser.py     Builds the .ghuser files from components/ (see the Grasshopper page)
```

## Configuration templates (`configs/`)

One YAML template per mode, plus a reference file documenting every parameter and an archetype example for simulated weights:

```
configs/
├── REFERENCE_all_options.yaml   Every parameter with descriptions
├── archetype_example.yaml       Building archetype for `usc simulate-weights`
├── config_benefit.yaml          Heating-benefit mode (balance temperature, analysis period)
├── config_daylight.yaml         CIE overcast daylight mode
├── config_irradiance.yaml       Perez all-weather irradiance mode
├── config_radiative_cooling.yaml  Nighttime radiative cooling (experimental)
├── config_tilted_plane.yaml     Fixed-angle geometric envelope
└── config_time_based.yaml       Solar envelope (actual sun paths)
```

Start from the template matching your mode and fill in the paths; each
template lists only the parameters relevant to that mode, with commonly
tuned defaults commented at the bottom.

## Tests (`tests/`)

```
tests/
├── conftest.py              Shared fixtures (temporary directories, small meshes and configs)
├── _stage_scene.py          A 10 m cube scene in daylight mode on the CPU: the smallest scene that runs every stage
├── _epw.py                  EPW lookup for tests: USC_EPW_PATH, else the bundled file
├── typologies.py            Procedural urban-block scenes for end-to-end checks
├── oracle.py                Independent CPU reference implementation of the carving
├── cases.py                 Runs USC end-to-end on a typology scene and loads the results
├── montecarlo.py            Random scenes x random settings from a seed, checked against oracle.py
├── data/                    5R1C oracle reference data and its capture script
├── test_carve_above.py      carve_above_columns, carve_above_scores, limit_column_slope
├── test_cli.py              CLI commands and the schema table
├── test_daemon.py           Daemon survives misbehaving clients and failing requests
├── test_engine_requests.py  Request parsing, configs from starting values, replies and real runs through the request core
├── test_exporting.py        Exporting stage: mesh placement, diagnostics, run report
├── test_floor_plates.py     Floor-plate geometry: facades, faces, bays, floors, outlines, prisms
├── test_massing_stage.py    Massing stage end to end on synthetic scenes
├── test_meshing.py          Cubic and smoothed meshing, pruning, diffusion, Taubin polish, cleanup
├── test_gh_components.py    Grasshopper sources stay buildable into .ghuser files
├── test_modes.py            End-to-end smoke tests per mode, benefit weight formula
├── test_montecarlo.py       Fixed Monte Carlo seeds in the regular suite
├── test_north.py            north_deg convention (clockwise from +Y) at every Ladybug boundary
├── test_pipeline.py         Full runs, stage-boundary validation, overrides, simulated weights
├── test_preprocessing.py    Preprocessing helpers and manifest keys
├── test_ray_tracing.py      Fixed-step marcher, Warp DDA kernel launches, ray generation, batch size
├── test_schemas.py          Config schema validation, grid resolution cap, overrides, relative paths
├── test_run_context.py      RunContext: issues, progress, cancel, and the error classes
├── test_scoring.py          Head/tail and carve-fraction thresholds
├── test_sequencer.py        run_pipeline: produce, start_from, collected issues, progress, cancel
├── test_session.py          CarverSession caching and the session_cache decorator
├── test_simulated_weights.py  5R1C engine: oracle regression vs RC_BuildingSimulator,
│                            steady-state closure, attribution, shoebox expansion, artifact I/O
├── test_stage_chain.py      Run IDs, upstream checks, relative manifest paths
├── test_stage_outputs.py    Outputs cleared before a stage, manifest written last, run report sections
├── test_stage_settings.py   Per-stage settings models and stages_to_rerun
├── test_sun.py              Sun and weather input: the EPW cache
├── test_surface_sampling.py  Test-surface sampling: coplanarity, boundary samples, edge taper, degenerate faces
├── test_typologies.py       End-to-end carving checks on procedural urban typologies
├── test_usc_gh.py           grasshopper/usc_gh.py parts that run without Rhino (engine_module, show_issues, run_stages, PLY, daemon calls)
├── test_util.py             Diagnostics helpers and the grid memory estimate
├── test_voxelization.py     Voxelization: invariants, Warp parity voxelizer, grid budget, cavity filling
└── test_warp_kernels.py     Warp availability and kernel warmup
```
