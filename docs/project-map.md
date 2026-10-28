# Project Map

Overview of the files and directories in the repository.

## Repository root

```
UrbanSolarCarver/
├── src/urbansolarcarver/   Core Python package
├── app/                    Source of the browser UI front-end (React, three.js)
├── configs/                YAML config templates (one per mode + reference + archetype example)
├── examples/               Example data, weather file, and Jupyter notebook tutorials
├── tests/                  Pytest suite
├── grasshopper/            Rhino Grasshopper plugin
├── docs/                   MkDocs documentation source
│   └── publications/       The ReSBE 2026 paper (PDF, CC BY-NC-ND 4.0)
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
| `api.py` | Public facade. Defines `run_pipeline(config, out_dir, produce, start_from, context, after)`, the sequencer (`after` is the previous criterion's thresholding, passed to the thresholding stage): it runs the stages needed for `produce`, each writing into `<out_dir>/<stage>`, and returns a `PipelineResult` (one Result per stage that ran, plus the run's issues). Also re-exports `run_chain()` and `ChainResult` (chained carvings, `api_core/chain.py`), `stages_to_rerun()`, `preprocessing()`, `thresholding()`, `exporting()`, `massing()`, their result types, `load_config()` and `build_config()`. |
| `api_core/__init__.py` | Collects the three stage modules and their result types into one importable sub-package. |
| `api_core/preprocessing.py` | **Stage 1.** Voxelizes the max-volume mesh into a dense 3D grid, samples test surfaces into evenly spaced points with outward normals, generates rays toward sky patches (or sun positions, or the tilted-plane direction, depending on mode), traces them through the grid with the DDA kernel, and writes the per-voxel obstruction scores to `scores.npy`. Also writes `voxel_grid.npy`, `footprint.json` (the plan projection of the voxelized mesh, which massing reads), the sample points and normals, the manifest, and diagnostics (JSON always; plots with `diagnostic_plots: true`). |
| `api_core/thresholding.py` | **Stage 2.** Loads `scores.npy` from Stage 1, optionally applies Gaussian score smoothing (weighted modes), applies the selected thresholding strategy (`carve_fraction`, `headtail`, or a numeric cutoff) to the raw scores of the occupied voxels together with `carve_above` (`column_postprocessing.carve_above_scores`, so `carve_fraction` counts what carve_above removes), applies the slope limit (`column_postprocessing.limit_column_slope`; 75 degrees by default for the weighted modes), and writes the binary mask `mask.npy` and `scores_compared_with_cutoff.npy` (the values the cutoff was applied to, which the browser UI draws its histogram from). Can be re-run with different threshold parameters without re-computing scores. With the optional `after` input (the previous criterion's thresholding result, folder or manifest) it decides only among the voxels that criterion kept: the manifest records `after_manifest` and `after_run_id`, the diagnostics `voxels_at_start`, and an empty start gives the issue `nothing_left_to_carve`. |
| `api_core/chain.py` | **Chained carvings.** `run_chain(chain, out_dir, produce, start_from, context, trace, threshold_from)` runs preprocessing and thresholding of each criterion of a chain in order into `<out_dir>/criteria/<id>/<stage>` (each thresholding gets the previous one as its `after` input), writes `criteria/chain.json`, then exporting and massing from the last criterion. `trace` limits the criteria that trace their rays again, and `threshold_from` starts thresholding at an earlier criterion than the first traced one, or, with `start_from="thresholding"`, at that criterion instead of the first. Returns a `ChainResult`. See [Criteria](criteria.md). |
| `api_core/massing.py` | **Stage 4.** Reads the thresholding chain, builds floor plates with `floor_plates.py`, writes `plates.json` (world outlines), `plates.obj` (one closed prism per plate), the manifest, diagnostics and the run report with a Massing section. |
| `floor_plates.py` | Floor-plate massing geometry: base outline and facades split at corners, faces by nearest facade with squared corners, faces cut into square modules (along the facade and in depth), floor-by-floor module selection (tolerance, maximum volume, stacking, minimum width), plate outlines and closed prisms. |
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
| `context_geometry.py` | Context and terrain on the max volume's lattice. **`context_occupancy`**: voxels whose centre lies inside the context (parity voxelizer, centre rule only, rays spanning the context's bounds). **`remove_context_columns`**: the column rule. **`ground_heights`** / **`remove_below_ground`**: the voxels below the terrain. **`build_blocking_mesh`** / **`drop_blocked_rays`**: one Warp BVH of context and terrain, and the rays that hit it (dropped before scoring). **`drop_blocked_sky_sub_rays`**: the same per jittered sky sub-ray, as a skip mask. **`subtract_columns`**: the footprint without the removed columns, for massing. |
| `meshing.py` | Mesh reconstruction. Removes small disconnected voxel clusters with `scipy.ndimage.label` and converts carved voxel masks back to triangle meshes, either as cubic voxel faces or through signed-distance-field smoothing, marching cubes, and Taubin polishing. **`finalize_mesh`** is the exporting entry point. |
| `io.py` | Mesh file I/O. **`load_mesh`**: reads a mesh through Trimesh (PLY, OBJ, STL...), rejects files without triangles, and runs `fix_normals` on meshes that are not watertight. **`save_mesh`**: writes a mesh; PLY files switch to double-precision vertices when float32 would round the coordinates, GLB files (**`save_glb`**) carry a whole-metre offset in their nodes, and STL files, float32 only, report a `float32_coordinates` issue when that rounds them by more than 1 mm. **`validate_inputs`** checks that the files a preprocessing run needs exist; **`load_meshes`** loads the maximum volume and the test surfaces and reports coordinates a float32 PLY file has rounded. |

### Carving engines

| File | Purpose |
|------|---------|
| `carving.py` | The three carving strategies. **`carve_with_sun_rays`** (`time-based`): traces rays from test-surface points toward the sun positions of the analysis period and returns the carved grid and per-voxel hit counts. **`carve_with_sky_patch_rays`** (`irradiance`, `benefit`, `daylight`, `radiative_cooling`): traces rays toward the 145 Tregenza sky patches (`rays_per_patch` per patch: the centre, or jittered sub-rays spread over the patch), weights each ray by its share of its patch's mode-specific value, and returns the accumulated per-voxel scores. **`carve_with_planes`** (`tilted_plane`): traces one ray per sample point at the plane angle (per-octant angles supported) and removes every voxel at or above it in its column. |
| `column_postprocessing.py` | The column rules thresholding applies after the score threshold: `carve_above_columns()` and `carve_above_scores()` (the `carve_above` setting) and `limit_column_slope()` (`max_slope_deg`), as numba kernels. |
| `ray_tracing.py` | Ray generation and voxel traversal. **`trace_and_score_dda`** / **`trace_and_count_dda`**: launch the Digital Differential Analyzer (DDA) kernels that step each ray through the voxel grid cell by cell and add the ray's weight (or a count of 1) to every voxel it crosses; they run on CUDA or on Warp's CPU backend, and there is no other tracer. **`follow_mass_behind_skin_dda`**: the skin rule. **`SkySubRays`**: passed to the wrappers, has the kernels trace each sky-patch ray as `side²` jittered sub-rays whose directions they compute themselves (no sub-ray arrays are stored); **`mesh_blocks_sky_sub_rays`** tests them against context and terrain, **`sky_sub_ray_directions`** returns them. **`generate_sky_patch_rays`** / **`generate_sun_rays`**: expand sample points × directions into flat ray arrays, keeping only directions the surface faces. **`auto_batch_size`**: picks a ray batch size from the free GPU memory. |
| `warp_kernels.py` | Warp setup and every Warp kernel of the package (DDA traversal, jittered sky sub-ray directions, skin rule, parity voxelizer, ground heights, mesh any-hit test), kept in one module so Warp compiles and caches them as one unit. **`dda_backend_available`**: whether the DDA backend can run on a device; **`require_dda_backend`** raises `WarpBackendUnavailableError` with the reason when it cannot. **`warmup_kernels`**: precompiles the kernels. |

### Sky and sun models

| File | Purpose |
|------|---------|
| `sky_patches.py` | Tregenza hemisphere subdivision (145 patches) used by the weighted carving modes. **`fetch_tregenza_patch_directions`**: the 145 unit direction vectors. **`fetch_tregenza_patch_solid_angles`**: the solid angle (sr) of each patch. **`tregenza_patch_cells`**: each patch's band of altitude and share of azimuth. **`sub_ray_directions`**: the NumPy definition of the jittered sub-ray directions the kernels compute (a hash of point, patch and cell picks a place in each cell of equal solid angle); **`patch_facing_margin`**: how far behind a surface a patch centre can lie while the surface still faces part of the patch. **`compute_EPW_based_weights`**: for `irradiance` and `benefit`, builds a Ladybug `SkyMatrix` (Perez all-weather model) from the EPW's direct-normal and diffuse-horizontal irradiance over the analysis period, each computation in a temporary folder of its own; benefit keeps only the hours below the balance point, or scales each hour by simulated weights. For `daylight`, returns the CIE standard overcast luminance distribution (brightest at the zenith, no EPW). **`compute_radiative_cooling_weights`**: long-wave cooling potential per patch from the Martin-Berdahl clear-sky emissivity with Bliss angular attenuation, for a horizontal surface; patches near the zenith get higher weights than those near the horizon. |
| `sun.py` | Solar position vectors. **`get_sun_vectors`**: uses Ladybug's `Sunpath` with the location from the EPW header to return unit vectors toward the sun for each sampled date-time of the analysis period (`sun_steps_per_hour` per hour), dropping positions below `min_altitude` and rotating by `north_deg`; `time_basis` says whether the date-times are local standard time, daylight saving time (one hour ahead) or true solar time. **`sample_period`** builds the analysis date/time list with Ladybug's `AnalysisPeriod`. |
| `weather_file.py` | **`read_weather_file`**: parses an EPW file with Ladybug once per path, modification time and size, and returns a `ParsedWeatherFile` that hands out copies (the location, the hourly dry-bulb temperatures, a Wea of the solar irradiance), so one caller's change cannot reach another. Used by the sun vectors, sky weights, cold period, simulated weights and the service's sun path. |
| `scoring.py` | Sky-patch weight dispatch and threshold selection. **`get_weights`**: calls the weighting function for the selected mode (Perez irradiance, heating benefit, CIE daylight, or radiative cooling). **`carve_fraction_threshold`**: the score cutoff above which the voxels hold a given fraction of the total score mass (two-pass weighted histogram, O(N)). **`headtail_threshold`**: Jiang (2013) head/tail breaks for heavy-tailed score distributions. Inside a `CarverSession`, `get_weights` is cached, keyed by every argument and by the contents of the EPW and simulated-weights files. |
| `simulated_weights.py` | Simulated benefit weights (opt-in via `simulated_weights_path`). Implements the ISO 13790 Annex C hourly thermal model ("5R1C": five conductances, one lumped mass capacitance, one zone) in NumPy, and derives the hourly *marginal* benefit/harm of solar gain by perturbation: for each hour of the year, one watt of solar gain is added and removed and the change in annual heating and cooling demand is attributed to that hour (`benefit[t]` / `harm[t]`, both in [0, 1]; all 17,521 year-simulations, the base run plus two per hour, march as one vectorized batch). **`generate_simulated_weights`**: EPW + archetype → `simulated_weights.json` artifact with provenance metadata plus a `.png` heatmap preview. **`ZoneParams.from_archetype`** builds the thermal network from about 10 physical inputs; **`expand_shoebox`** derives all areas from a width/length/height + per-facade window-to-wall ratio shorthand. Validated against ETH's RC_BuildingSimulator (`tests/data/oracle_5r1c_reference.json`). Design note: `design/simulated-weights.md`. |

### Sun and sky check (Simulate)

| File | Purpose |
|------|---------|
| `check_settings.py` | The metrics of the check (`CHECK_METRICS`: sun hours, solar energy, useful solar gains (key `useful_solar_energy`), overcast sky component, cooling sky, sky view factor, each with its unit, whether it reads the weather file and which mode's starting period it takes), the metric each carving mode starts with (`DEFAULT_CHECK_METRIC`), `CheckSettings` (period, time basis, lowest sun altitude, rays per patch, sample spacing, ...) with `for_config`, `settings_digest` (sha256 of the settings without the weather file's path) and `build_check_settings`. Standard library and Pydantic only, so the service lists the metrics without importing torch. |
| `solar_check.py` | The check itself. **`check_directions`**: the sun positions of the period (one an hour), or Tregenza's 145 sky patches traced with the carving's jittered sub-rays, each with its value. **`evaluate_test_points`**: traces the directions of every test point against a closed mesh with Warp's BVH ray queries, an envelope or massing clipped by the maximum volume, the context and terrain blocking in every geometry. **`solar_check`** and **`simulate_study`**: sample the test points at the carving's spacing (at most `MAX_CHECK_POINTS`, 2 million), trace every geometry and write `check_points.npz`, `check_values.npz` and `check_summary.json` with the fingerprints of what the result came from. Behind the engine request `check`. |
| `check_files.py` | The files of the sun and sky check without torch: the result file names, `file_fingerprint`, and `run_geometry_files` (the envelope and massing a run folder has built, with the surface tolerance from their manifests), which `solar_check.run_geometries` and the service both use. |

### Configuration

| File | Purpose |
|------|---------|
| `mode_registry.py` | One `ModeSpec` per carving mode, in Grasshopper's menu order: whether it needs an EPW and an analysis period, its score kind (`weighted_sum` or `violation_count`), its weight unit, the mode-specific settings it reads, its description and its starting values (what differs from the schema defaults: analysis period, tilted-plane angle, carve fraction). Also `MODE_ALIASES` and `canonical_mode_name()`. Validation, the CLI `schema` command, the stages and the Grasshopper components read their mode facts from here. Standard library only. |
| `archetype_defaults.py` | The shoebox archetype defaults (`ARCHETYPE_DEFAULTS`, `WINDOW_TO_WALL_DEFAULTS`, `ARCHETYPE_OPTIONAL_KEYS`) read by `usc archetype`, `simulated_weights.py` and the USC_Archetype component. Standard library only. |
| `errors.py` | `UrbanSolarCarverError` and its subclasses `ConfigError` (with `ConfigFieldError`), `InputError`, `StageChainError`, `MalformedEngineRequest` and `RunCancelled`, plus `UrbanSolarCarverWarning`. Standard library only. |
| `run_context.py` | `RunContext` (issues, progress callback, cancel flag), `Issue`, `report_issue()`, `report_progress()` and `run_context()` / `stage_context()`. Standard library only. |
| `stage_settings.py` | The per-stage settings models (`PreprocessingSettings`, `ThresholdingSettings`, `ExportingSettings`, `MassingSettings`, `RunOptions`), `stages_to_rerun()` and `stage_folder()` (the one definition of the `<run_folder>/<stage>` layout). Does not import torch. |
| `load_config.py` | Reads a YAML configuration file and returns a validated `UserConfig` object. **`load_config`**: loads the YAML, expands an `analysis_period:` mapping, resolves relative paths against the YAML's folder, applies flat `key=value` overrides, and validates with Pydantic (all errors reported in one message). **`build_config`**: validates typed values (what a client holds) into a `UserConfig` and raises `ConfigError` with a `ConfigFieldError` per problem; `load_config` calls it. **`parse_override_value`**: converts override strings into Python values (booleans, None, JSON lists and objects, numbers). |
| `chain_config.py` | The `criteria:` form of a config. **`load_chain`** validates a chain file into a `ChainConfig`: one `Criterion` (id, name, validated config) per criterion, built from the shared top-level settings plus the criterion's own. **`CRITERION_KEYS`** lists the per-criterion settings; every other key is shared. **`is_chain_file`** tells a chain file from an ordinary config; `load_config` refuses a chain file. See [Criteria](criteria.md). |
| `pydantic_schemas.py` | Data schemas. **`UserConfig`**: the Pydantic v2 model defining every pipeline parameter with types, defaults and value ranges (e.g. `voxel_size` must be 0.01-100); unknown keys are rejected. It normalizes `threshold` into a **`ThresholdSpec`**, checks mode requirements, and emits `UrbanSolarCarverWarning` for settings the mode ignores and when `ray_batch_size` is clamped. **`PreprocessingManifest`** / **`ThresholdingManifest`**: schemas for the JSON manifests written by the first two stages, so a later stage can be re-run from an earlier run's output. |

### Infrastructure

| File | Purpose |
|------|---------|
| `compute_device.py` | The one rule for choosing the compute device. **`resolve_compute_device`**: `auto`/None picks CUDA when available, else the CPU; `cpu`, `cuda`, `cuda:N` and a `torch.device` are taken as given, and a CUDA choice without CUDA raises. **`warp_device_name`**: the Warp name of a torch device. Used by the stages, the session, the daemon, the weights, voxelization and the kernel launches. |
| `session.py` | Compute-session lifecycle. **`CarverSession`**: a long-lived object that keeps the CUDA context alive across pipeline calls and holds a value cache (voxelized grids, Tregenza patch directions and solid angles, and the sky-patch weights of the weighted modes). Keys cover the geometry, settings and device, so entries stay valid across runs; the cache holds at most 1 GiB (`max_cache_bytes`) and drops the least recently used entries beyond that. The daemon opens one session and keeps its cache between commands, returning only unused GPU memory after each; the Python API and CLI run without a session unless you open one (`with CarverSession():`). Compiled Warp kernels are cached by Warp itself, on disk. **`get_active_session`**: returns the session registered for a device, or `None`. **`session_cache`**: a decorator that stores a function's return value in the active session's cache under a key built from its arguments. |
| `engine_requests.py` | The request core every transport uses. **`parse_engine_request`** validates a message into a typed request (`run`, the stage commands, `run_pipeline`, `simulate_weights`, `check`, `ping`); **`config_for_engine_request`** builds its config from a YAML path or from the mode's starting values plus overrides. The `check` request runs one Simulate study (see [Engine requests](api/engine-requests.md)). A `run` request also carries `trace_criteria` and `threshold_from_criterion` (chain files) and `after` (one criterion, started at thresholding), and the `ping` reply lists the engine's `features` (`run_after`). **`handle_engine_request`** runs it in a run context and returns a typed reply with the run's `issues`; **`answer_engine_message`** does all of this for dict transports and turns any failure into an error reply with `error_type` and, for config errors, `config_errors`. Does not import torch until a request runs. |
| `daemon.py` | Persistent background process for Grasshopper and the CLI's `--daemon` flag, a transport over `engine_requests`. **`serve`**: listens on `127.0.0.1` (localhost only) with Python's `multiprocessing.connection`, authenticated with a random key stored in `~/.urbansolarcarver/.daemon_authkey`. Creates a `CarverSession` on startup and keeps it for the daemon's lifetime; each request goes to `answer_engine_message`, and only `shutdown` is handled by the daemon itself. Started and stopped with the CLI (`urbansolarcarver daemon start/stop`) or from Grasshopper with the `USC_Session` component. |
| `daemon_client.py` | The client side of the daemon, standard library only: the authkey file (`resolve_daemon_authkey`), the default host and port, and `send_daemon_request`. The CLI's daemon commands use it, so they do not load torch; the daemon reads its key through it too. |
| `carver_cli.py` | Command-line interface built with Typer, registered in `pyproject.toml` as both `urbansolarcarver` and `usc`. Commands: `run` (the sequencer, with `--produce` and `--start-from`; it runs a chain file's criteria in order), `preprocessing`, `thresholding` (with `--after` for one step of a chain), `exporting`, `massing` (each with a config file `-c`, overrides `-o`, and optional `--daemon`), `validate` (lists a chain's criteria), `schema` (prints the config parameter table, filterable by `--mode` or `--search`), `warmup`, `simulate-weights`, `archetype`, `ui` (the browser interface) and `daemon start/stop/status`. |

### Browser UI

| File | Purpose |
|------|---------|
| `local_web_service/server.py` | The FastAPI application behind `usc ui`. `create_app` builds it; `SecurityMiddleware` refuses a `Host` header that is not the service's address and an API call or WebSocket without the launch token. Routes for projects, input files, settings, criteria, modes, examples, stage status, run summaries, result files, downloads and run events (see the routes below); serves the built front-end. Does not import torch. |
| `local_web_service/api_models.py` | The Pydantic models of the requests and replies; the front-end's types are generated from them. `ProjectJson` holds the project's `criteria` (`CriterionEntry`), `next_criterion_id` and the stage records, with the records of each criterion's preprocessing and thresholding in `criterion_records`. |
| `local_web_service/projects.py` | Project folders: name validation, the folder layout, `project.json`, uploads (several mesh files of a role are joined into one), the methods for criteria (add, update, delete, duplicate, reorder), `config.yaml` built from the settings the browser sends on top of the mode's starting values, and the voxel grid check. Every change that writes `config.yaml` checks it with `load_chain` first and writes nothing when the check fails. |
| `local_web_service/criteria.py` | The criterion model helpers: the colour palette, `config.yaml` generated from `project.json` (shared settings, then the criteria that are on), and the split of the app's settings into shared and criterion keys (`split_settings`). `engine_settings` gives an energy-weighted Solar usefulness criterion (`CriterionEntry.energy_weighted`) `simulated_weights_path: inputs/typical_building/weights.json` and leaves out its `balance_temperature` and `balance_offset`, which `project.json` keeps; `ProjectStore.read_stored_config` reads the engine's form, `read_settings` (the browser's) the stored one. |
| `local_web_service/typical_building.py` | The project's typical building (`ProjectJson.typical_building`, `TypicalBuildingEntry`), shared by its energy-weighted criteria: the three types to start from (`PRESETS`), `validate` (each value's type and range, then the engine's `expand_shoebox`, `ZoneParams.from_archetype` and `_shading_factors`, an error at each field), `archetype_of` (the shoebox archetype, gains by day 8:00 to 20:00 and by night as a 24-value profile), `weights_key` (sha256 of the values and the weather file) and `calculate` (`generate_simulated_weights` into a new folder, then the file, its heatmap and `calculated_key` put in place together under the project lock). |
| `local_web_service/test_surfaces.py` | Test surface files stored once in `inputs/test_surfaces/` and compared by content, the joined file of each criterion (`inputs/joined/test_surfaces_<id>.ply`) and of each study that lists files (`inputs/joined/study_surfaces_<id>.ply`), `users_of` (the criteria and studies that list a file; a stored file goes to the recycle bin when none does), and the fingerprint of a joined file that the stage records use. |
| `local_web_service/stored_files.py` | Input files replaced in the project folder from outside the app: the record of each stored file in `project.json` (`stored_files`: size, modification time, sha256), `refresh_changed_inputs` (a changed file builds again the joined files that use it; a joined file that comes out different replaces the old one, dates what was built on it and leaves a notice in `changed_files`), `input_changes` for the stage status, and the refusal of a run while a recorded file is missing. |
| `local_web_service/studies.py` | The studies of the Simulate workspace (`StudyEntry`, kept in `project.json` under `studies` beside the criteria): default names ("Sun hours, 21 Dec"), the settings a metric starts with and accepts (`STUDY_SETTING_KEYS`), a study like a criterion, and the results folder `simulate/<id>`. The store methods (`add_study`, `update_study`, `delete_study`, `reorder_studies`, `use_study_test_surface`, `remove_study_test_surface`) write `project.json` and the study's joined test surface file only, never `config.yaml`, `inputs_revision` or a stage record. |
| `local_web_service/simulation.py` | Running the studies: a study's check settings (north, ray length and carving spacing from the shared settings, rays per patch of the first criterion that is on, the study's metric, period, time basis and mode settings), its `check` engine request, why it cannot run (`refusal_of`), the engine's refusal of a study kept in `simulate/<id>/refusal.json` until its inputs change, its state (`study_state`: current, out of date when a file, setting or surface tolerance it was computed from changed, not run, refused) and the binary of its patches and values for the 3D view. Reads the result files through `check_files.py`, so it does not import torch. |
| `local_web_service/inspection.py` | The Inspect workspace's view of the input mesh files. **`inspect_file`** reads a stored file with `load_mesh` (the maximum volume and test surfaces with `fix_normals`) and keeps the result until its size or modification time changes; a surface is the triangles joined by shared edges, and a test surface file closed as a whole is not flippable. **`project_inspection`**: the summary of each mesh file (triangles, area, bounds, closed bodies, surfaces), a file that cannot be read listed with its problem. **`inspection_geometry`**: the triangles of a test surface file with a surface number per triangle, as one binary. **`save_turned_surfaces`**: turns whole surfaces, writes the file in its own format (OBJ at 10 decimals, PLY float64, GLB and STL float32), reads it back with `load_mesh`, saves nothing when the turns or corners did not hold, keeps the original in `inputs/originals/test_surfaces/` before the first save and builds the joined files of the criteria and studies that list the file as an upload does. **`restore_original`** puts the kept original back. |
| `local_web_service/migration.py` | `migrate_to_criteria`: a project of an earlier version becomes a chain of one criterion with its results kept (run folders moved to `run/criteria/1/`, manifests that name them rewritten, records moved). It runs when a project opens, when a run starts and at a first settings save, and undoes its steps when one fails. |
| `local_web_service/stage_records.py` | Which stages of a project are current, out of date or missing, for each criterion (`criterion_status`) and summed up (`stage_status`), and which stages a run has to execute: `choose_stages` returns the criteria to trace (`trace_criteria`), the criterion to threshold from and what the run does for each criterion. The preprocessing record of an energy-weighted criterion keeps the typical building's key (`StageRecord.weights_key`); another key now dates that preprocessing. |
| `local_web_service/run_worker.py` | Runs a project in a background thread in two phases (analysis, then envelope and massing), publishes progress events that name their criterion, refuses a run without test surfaces in a criterion that is on, and handles cancel. When it preprocesses an energy-weighted criterion and the weights are missing or for another key, it calculates them first (progress events of stage `typical_building`, criterion `null`, 0 then 1 of 1). Runs a simulation of the studies (`start_simulation`, stage `simulate`) as the same kind of job: one job at a time, the same events and cancel, no stage record touched. |
| `local_web_service/run_summary.py`, `score_points.py` | What the app shows of a run: the numbers of the carving and massing for each criterion and for the chain, the sun path and sky dome, the scored voxels of a criterion, and which criterion carved each voxel. |
| `local_web_service/carve_further.py` | **Carve further** for a project with one criterion; refused with several. The browser app no longer offers it; the route stays for other clients. |
| `local_web_service/gpu_warm_up.py` | Compiles the GPU kernels in the background at launch and reports the device or why the CPU is used. |
| `example_projects/` | The three packaged examples (`examples.json`, mesh files and one weather file). |
| `ui_static/` | The built front-end, committed. `build_info.json` holds a hash of the sources in `app/`. |

**Routes for studies** (Simulate; all under `/api`; the writes hold the project's lock and answer 409 while a run of the project is active; an unknown study id is a 404 that names the id):

| Route | What it does |
|-------|--------------|
| `GET /projects/{name}/studies` | The studies in order, each with its `state` (`current`, `out_of_date`, `not_run`, `refused` with its `reason`) and the geometries its last result has, and the metrics with their availability, unit and default settings |
| `POST /projects/{name}/studies` | Add a study; body `metric` (its default period, no files) or `from_criterion` (the criterion's metric, period, mode settings and file names). Neither or both is a 422. Returns the `StudyEntry` |
| `PATCH /projects/{name}/studies/{id}` | Change `name`, `metric`, `values` (the study's settings) or `target` (`null` removes it). A new metric resets the settings to its defaults and keeps the values both metrics have |
| `DELETE /projects/{name}/studies/{id}` | Delete a study (204), move its results folder to the recycle bin and the stored test surface files no criterion or study lists |
| `PUT /projects/{name}/studies/order` | Reorder; body `ids`, every id once |
| `POST /projects/{name}/studies/{id}/test-surfaces` | Upload a test surface file to a study (multipart `file`) |
| `PUT /projects/{name}/studies/{id}/test-surfaces/{file}` | Use a file the project stores |
| `DELETE /projects/{name}/studies/{id}/test-surfaces/{file}` | Remove a file from a study |
| `POST /projects/{name}/simulate` | Run every study that can run as one job of the run worker (stage `simulate`, outside the pipeline's stages); events are read as a run's. 409 while any run or simulation is active, 422 when no study can run (the message names each study and why) |
| `GET /projects/{name}/studies/{id}/values` | The test point patches of the last result and the values of each geometry as one binary (layout in `simulation.study_values`); 404 without a result |

None of these changes `inputs_revision`, `config.yaml` or a stage record.

**Routes for Inspect** (all under `/api`; the two writes hold the project's lock and answer 409 while a run of the project is active):

| Route | What it does |
|-------|--------------|
| `GET /projects/{name}/inspect` | The `InspectReply`: the summary of each mesh file by role, allowed while a run is active |
| `GET /projects/{name}/inspect/test_surfaces/{file}/geometry` | The triangles of a test surface file with a surface number per triangle, as one binary (layout in `inspection.inspection_geometry`) |
| `POST /projects/{name}/inspect/test_surfaces/{file}/turn` | Body `surfaces`: turn those surfaces and save the file. 422 for a file closed as a whole, an unreadable file or a surface that does not exist, 500 when the written file does not read as turned (nothing is saved) |
| `POST /projects/{name}/inspect/test_surfaces/{file}/restore` | Put the kept original back; 404 when none is kept |

**Routes for criteria** (all under `/api`; the writes hold the project's lock and answer 409 while a run of the project is active; an unknown criterion id is a 404 that names the id):

| Route | What it does |
|-------|--------------|
| `GET /criterion-keys` | The settings that belong to a criterion (`CRITERION_KEYS`); every other setting is shared |
| `POST /projects/{name}/criteria` | Add a criterion at the end; body `mode` and optional `name`. Returns the `CriterionEntry` |
| `PATCH /projects/{name}/criteria/{id}` | Change `name`, `colour`, `bypassed`, `energy_weighted` (Solar usefulness: count the hours by the typical building) or `values` (the criterion's own settings; shared keys in `values` are ignored and belong to `PUT /projects/{name}/shared-settings`) |
| `DELETE /projects/{name}/criteria/{id}` | Delete a criterion (204) and the stored test surface files no other criterion uses |
| `POST /projects/{name}/criteria/{id}/duplicate` | Copy the settings and the test surface files into a new criterion at the end |
| `PUT /projects/{name}/criteria/order` | Reorder; body `ids`, every id once. A bad list is a 422 and changes nothing |
| `POST /projects/{name}/criteria/{id}/test-surfaces` | Upload a test surface file to a criterion (multipart `file`) |
| `PUT /projects/{name}/criteria/{id}/test-surfaces/{file}` | Use a stored file of another criterion |
| `DELETE /projects/{name}/criteria/{id}/test-surfaces/{file}` | Remove a file from a criterion |
| `GET /projects/{name}`, `PUT /projects/{name}/config` | Take an optional `criterion` (default: the first for a read, the only one for a save; a save with several criteria and none named is a 422). `ProjectDetail` gains `criteria` and `criterion_status` |
| `PUT /projects/{name}/shared-settings` | Save the settings the criteria share (body `values`, no mode); a criterion's own key is a 422 that names it, and so is a value that makes a criterion that is on invalid. Returns the shared settings as stored and the `grid_plan` |
| `GET /projects/{name}/criteria/{id}/settings` | The settings of one criterion with the shared ones (`criterion_id`, `settings`), read without looking at the test surface files |
| `GET /projects/{name}/sun-path` | Takes an optional `criterion` (default: the first criterion that is on) |
| `GET /projects/{name}/run/score-points`, `.../run/sky-patches` | Take an optional `criterion` (default: the last criterion that is on) |
| `GET /projects/{name}/run/carved-by-criterion` | One byte per voxel: the criterion that removed it (format in [Browser UI](ui.md#criteria-in-a-project)) |

`POST /projects/{name}/runs` answers with `criterion_stages` besides `stages`, and refuses with a 422 (`missing_inputs`) when no criterion is on or a criterion that is on has no test surfaces.

**Routes for the typical building** (all under `/api`; the save and Calculate answer 409 while a run of the project is active):

| Route | What it does |
|-------|--------------|
| `GET /typical-building-presets` | The types to start from by key (`office`, `heavy_home`, `light_home`): `label` and `values` |
| `GET /projects/{name}/typical-building` | The `TypicalBuildingReply`: `values`, `start_from`, `state` (`current`, `out_of_date`, `missing`) and, from the weights file, `heating_kwh_m2`, `cooling_kwh_m2` and `counted_hours` (benefit above 0.01). Before a save: the office type |
| `PUT /projects/{name}/typical-building` | Body `values`, `start_from`; a bad value is a 422 `ConfigErrorReply` at its field (`wwr.<side>` for a window share) |
| `POST /projects/{name}/typical-building/calculate` | Calculate the weights of the stored building into `inputs/typical_building/weights.json` (about 9 s); 404 without a weather file |
| `GET /projects/{name}/typical-building/weights` | `benefit` and `harm`, 8,760 values each to 3 decimals; 404 before a calculation |

`app/` holds the front-end source (`src/inspect/` the Inspect workspace: `InspectView.tsx`, what it puts over the 3D view, `FilesPanel.tsx`, the Files panel with a file's summary, Flip mode, Save, Discard and Restore original, `use_inspection.ts`, the summaries, the selected file and the staged turns, `UnsavedTurnsDialog.tsx`, the Save, Discard or Stay question when leaving Inspect, and `inspect_geometry_decoder.ts`, the reader of the geometry binary; `src/simulate/` the Simulate workspace: `SimulateView.tsx`, what it puts over the 3D view, `StudiesPanel.tsx` and `AddStudyMenu.tsx`, the Studies panel and its Add study menu, `StudyPopover.tsx`, a study's settings, `GeometrySwitch.tsx` and `ResultCard.tsx`, the geometry switch with Change and the result card, `use_studies.ts` and `use_study_view.ts`, the studies and the study on the view (geometry, Change, target, legend, card), and `study_values.ts` with `study_values_decoder.ts`, the statistics and the reader of the values binary; `src/viewer_overlays/TargetLegend.tsx` is its legend with the draggable target; `src/steps/` the five steps: `InputsStep.tsx`, `SiteAndGridStep.tsx`, the result steps and the export, with `ActionMenu.tsx`, the menu of a project and of a criterion row, `menu_popup.ts`, the placement and keys of a popup menu that `ActionMenu.tsx` and the mode menu share, and `CriteriaRunBar.tsx`, the Run analysis and Build buttons pinned under the Criteria step; `src/criteria/` the criteria hook and its helpers (`use_criteria.ts`, `criteria_state.ts`), the Criteria step, the criterion list and its rows (`CriterionList.tsx`, `CriterionCard.tsx`) and their dialogs, `ModeMenu.tsx`, the short menu of modes behind Add criterion, the criterion panel with `PanelSection.tsx`, its folded sections, and `section_summaries.ts`, the one-line summary of each section, and its Test surfaces box, with `TypicalBuildingSheet.tsx` and `use_typical_building.ts`, the typical building's box in a Solar usefulness criterion's Settings, its sheet beside the panel (the values in six folded groups, Calculate, the day-by-hour chart of the weights) and the project's building as read, saved and calculated; `src/settings_form/` the settings, with `two_forms.ts` for the shared and the criterion settings held side by side; `src/viewer/` and `src/viewer_overlays/` the 3D view, with `carved_by_criterion_decoder.ts` for the carved-by-criterion layer; `src/api_client/` the typed client). See [Browser UI](ui.md#rebuilding-the-front-end-after-changing-app) for building it.

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
├── _chain_scene.py          A box with two facades to protect, the smallest scene on which two criteria decide about different voxels, for the chain tests
├── montecarlo.py            Random scenes x random settings from a seed, checked against oracle.py (single criteria and chains: `run_chain_case`)
├── data/                    5R1C oracle reference data and its capture script
├── test_chain_config.py     load_chain: shared and criterion keys, ids, defaults, the weather file rule, errors
├── test_chained_thresholding.py  thresholding with `after`: the base of the second criterion, manifest links, stale chains, empty start
├── test_run_chain.py        run_chain: folders, chain.json, start_from, issues, the report's Criteria section
├── test_carve_above.py      carve_above_columns, carve_above_scores, limit_column_slope
├── test_cli.py              CLI commands and the schema table
├── test_compute_device.py   The device rule: auto, explicit choices, CUDA missing, Warp device names
├── test_context_*.py        Context and terrain: config keys, voxels on the lattice and the column rule, ground heights, the ray mask, preprocessing, typology scenes
├── test_daemon.py           Daemon survives misbehaving clients and failing requests
├── test_engine_requests.py  Request parsing, configs from starting values, replies and real runs through the request core
├── test_exporting.py        Exporting stage: mesh placement, diagnostics, run report
├── test_local_web_*.py      The browser UI service: packaging and build hash, projects, criteria, test surfaces, studies, simulations, stage records, run worker, earlier-project migration, run summaries, score points, HTTP routes and security
├── test_floor_plates.py     Floor-plate geometry: facades, faces, bays, floors, outlines, prisms
├── test_massing_stage.py    Massing stage end to end on synthetic scenes
├── test_meshing.py          Cubic and smoothed meshing, pruning, diffusion, Taubin polish, cleanup
├── test_gh_components.py    Grasshopper sources stay buildable into .ghuser files
├── test_modes.py            End-to-end smoke tests per mode, benefit weight formula
├── test_montecarlo.py       Fixed Monte Carlo seeds in the regular suite
├── test_north.py            north_deg convention (clockwise from +Y) at every Ladybug boundary
├── test_package_imports.py  Every public name resolves; importing the package and `usc daemon status` do not load torch
├── test_pipeline.py         Full runs, stage-boundary validation, overrides, simulated weights
├── test_preprocessing.py    Preprocessing helpers and manifest keys
├── test_ray_tracing.py      Warp DDA kernel launches, ray generation, batch size
├── test_schemas.py          Config schema validation, grid resolution cap, overrides, relative paths
├── test_run_context.py      RunContext: issues, progress, cancel, and the error classes
├── test_scoring.py          Head/tail and carve-fraction thresholds
├── test_sequencer.py        run_pipeline: produce, start_from, collected issues, progress, cancel
├── test_setup_env.py        setup_env.py: choosing the PyTorch wheel index for the driver
├── test_session.py          CarverSession caching and the session_cache decorator
├── test_solar_check.py      The sun and sky check: sub-ray directions, unobstructed values, the infinite wall, sun hours against a ray-box test, a mesh's own facades, clipping by the maximum volume, context and terrain blocking, the check's settings, files and fingerprints, too many points, solar energy against Ladybug's radiation
├── test_sky_matrix_folder.py  Sky matrices in their own temporary folder: concurrent runs, nothing left behind
├── test_simulated_weights.py  5R1C engine: oracle regression vs RC_BuildingSimulator,
│                            steady-state closure, attribution, shoebox expansion, artifact I/O
├── test_stage_chain.py      Run IDs, upstream checks, relative manifest paths
├── test_stage_outputs.py    Outputs cleared before a stage, manifest written last, run report sections
├── test_stage_settings.py   Per-stage settings models and stages_to_rerun
├── test_surface_sampling.py  Test-surface sampling: coplanarity, boundary samples, edge taper, degenerate faces
├── test_typologies.py       End-to-end carving checks on procedural urban typologies
├── test_usc_gh.py           grasshopper/usc_gh.py parts that run without Rhino (engine_module, show_issues, run_stages, PLY, daemon calls)
├── test_util.py             Diagnostics helpers and the grid memory estimate
├── test_version.py          The version in pyproject.toml, the package, the CLI and CITATION.cff
├── test_voxelization.py     Voxelization: invariants, Warp parity voxelizer, grid budget, cavity filling
├── test_warp_kernels.py     Warp availability, the error when Warp cannot run, kernel warmup
└── test_weather_file.py     The cached EPW reader: re-read on a changed file, copies for each caller
```
