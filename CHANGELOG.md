# Changelog

All notable changes to Urban Solar Carver are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Windows with an altitude** in an explicit archetype: a window may carry the altitude of its normal (90 for a
  skylight). The weights file is now schema version 2 (version 1 is still read; 0.10.0 refuses version 2).
- **Progress of Calculate** in the typical building window: a bar under the button fills as the weights are calculated
  (`GET /projects/{name}/typical-building/progress`; `generate_simulated_weights` takes a `progress` callback). A run
  that calculates the weights first reports the same progress, in percent.
- **Import rules and drawn maps** for developers: the Python package's seven layers are written in
  `pyproject.toml` and checked by import-linter in the tests, the app's folders in eleven layers and its other rules by
  dependency-cruiser in `npm test`, and `python tools/draw_maps.py` draws both as SVG. The Project Map page explains
  them in place of its file list; each file's description is its own docstring or header comment.
- **The model of the simulated weights in the docs**: the Simulated Weights page now gives the 5R1C equations, the
  archetype rules, the attribution, the weights file's format and how benefit mode uses it, which were in a design
  note of the repository; the note is no longer published.
- **ESLint for the app**, run by `npm test`: typescript-eslint and the React hooks rules (effect dependencies, refs and
  state during render). The 153 findings were cleared without changing what the app does; one line sets a rule aside,
  with its reason.

- **Developer checks.** `tools/check_references.py` reports routes, files and names in the docs that no longer exist
  (`tests/test_docs_references.py` runs it). Ruff runs in `tests/test_architecture.py`, with mistakes as its rules and no
  formatting. `tools/repo_state.py` prints where the repository stands, asking GitHub rather than the local tracking refs.

### Changed

- **`npm run api-types`** finds the project's environment itself, also from a git worktree. pytest no longer prints the 15
  slowest tests on every run; add `--durations=15` to ask for them.
- **The simulated weights take about 4 s instead of 7 s, with the same numbers.** The attribution computes a run perturbed
  at hour t only from hour t on, starting from the base run's state, and takes the base run from its first row; the sun is
  placed once for all the windows. Calculate in the Typical building window takes about 5 s, and the tests that calculate
  weights about half as long.
- **The 3D view's layers come from one list** in the app: each layer's object, whether the layers menu lists it, and
  whether it is shown and dimmed are one entry, which one hook gives the scene (30 effects in the view pane down to
  12). What a layer offers the scene (theme colours, its summary, recolouring, picking) is typed (`layer_hooks.ts`).
  A study shown on another geometry is now recoloured in place instead of being built again.
- **The open project's plumbing in the app**: the token, the project's name and the handler of failed requests come
  from one context (`api_client/project_session.ts`) instead of being handed to 16 hooks and panels;
  `reportServiceProblem` replaces 24 copies of the same check, `configErrorOf` four readers of a refused save's field
  errors. Three small hooks in a new `hooks/` folder (`useChangedDuringRender`, `useLatest`, `useKeyedValue`) replace
  about 20 hand-written copies. Nothing the app does changes.
- **The daemon's key file is found when it is asked for**: `daemon_client.daemon_authkey_path()` replaces the constant
  `DAEMON_AUTHKEY_PATH`, which was fixed when the module was imported and so ignored a home folder set later.
- **Tests keep out of the user's folders on their own**: every test gets a home folder of its own, and Warp's kernel cache
  stays in its usual folder (no more `NVIDIA` folder in the checkout after a test run). The smallest shared test scene
  has its test surface under the cube, as described, not inside it; its end-to-end tests now check that part of the cube
  is carved. `pytest` collects from `tests/` only. The app's fake service checks its main replies against the service's
  types, and the fake 3D scene against the real one's methods. `docs/testing.md` lists the shared scenes and fakes.
- **The tests were reviewed one by one** for the mistake each catches. About 90 duplicate or trivial tests were deleted
  and about 40 merged into the ones kept; tests tied to markup, CSS text or private functions now check behaviour; 30
  weak assertions now fail on the mistake they aim at. A small plot, street and neighbour scene (`tests/_plot_scene.py`)
  checks which side each mode carves. Tests wait on events instead of the clock, and the app tests' `settle` waits until
  no reply is outstanding. The app tests read the service's schema and modes from a snapshot that a test keeps current
  (`tools/write_app_test_service_data.py`), and each shared helper is written once (see `docs/testing.md`).
- **`PipelineResult` is defined in `urbansolarcarver.api_core.pipeline_result`**, below `api`, since `run_chain` builds
  it too. `from urbansolarcarver import PipelineResult` and `from urbansolarcarver.api import PipelineResult` work as
  before.
- **The typical building runs free**: the energy-weighted Solar usefulness weights now measure passive performance.
  The room has no heating or cooling; its two set points are the limits of a **comfort band**, its windows open for
  natural ventilation (above **Open the windows above**, 25 °C in the examples, when outdoors is cooler, up to **Open
  windows let in at most**, 4 air changes per hour), and each hour's sun counts by the degree-hours below the band it
  removes (benefit) and above it it adds (harm), times the room's heat loss coefficient so the weights stay shares of a
  watt-hour. The window shows the room's degree-hours below and above the band. In the engine this is
  `operation: free_running` with `vent_above` and `vent_ach` (`simulate_free_running`, `attribute_free_running`);
  `conditioned`, the earlier ideal heating and cooling, stays the engine's default (and `usc archetype`'s). Weights
  calculated before are out of date and are calculated again.
- **Grasshopper: USC_Archetype's room runs free** by default, as the app's. USC_ZoneOperation takes `free_running`
  (False for the heated and cooled room), `vent_above` and `vent_ach`, added after its earlier inputs so wires carried
  over by USC_SyncCanvas stay in place; the setpoints are the comfort band of a free-running room. After a sync, a canvas
  that leaves `free_running` unwired gets free-running weights. `OPERATIONS` and `FREE_RUNNING_DEFAULTS` move to
  `archetype_defaults.py` (still importable from `simulated_weights`).
- **Irradiance and benefit rays count the angle of incidence**: each ray (each sub-ray with `rays_per_patch` above 1)
  counts its patch weight times cos θ to its test surface's normal, so a score is the energy the protected surface
  receives, as Simulate's solar energy and useful solar gains count it. Before, a ray counted its patch's radiation as
  if the surface faced the patch. The same weight goes into the context drop figures and `test_point_access_evaluation`.
  On the bundled examples, full year in Golden, carve fraction 0.7: 4.5 to 9.0 % of the voxels are decided differently
  and 0.6 to 1.5 % less volume is kept; scores fall to 58 to 67 % of before, so a numeric threshold of these modes
  carves less. `daylight` and `radiative_cooling` are unchanged. `ModeSpec.incidence` says which modes take the term.
- **One averaged room values the sun for every facade**: the rooms per facade direction (archetype key
  `direction_rooms`, the app's **One room per facade direction**, between 0.10.0 and this change) are removed. What
  lies behind a test surface is not known, and with the angle of incidence above a facade counts the absolute gains
  it receives. A typical building stored with `by_direction` reads without it (its weights are calculated again when
  it was on); a weights file that holds `hourly.directions` is read for the room's own series.
- **App: fewer numbers on the carving, the last run's time in the top bar.** The Carving rule no longer has the tiles
  under its histogram (Kept here, Obstruction removed, Last analysis took): the criterion's card says what it removes, now
  without a volume, "Removes 80 % of the obstruction" in the weighted modes and "Removes 39 % of what reached it" in
  the others. The line under two or more criteria reads "After all criteria: kept 61 % of the maximum volume", and is not
  shown without that share. The time of the last run of the open project, a pipeline run or a simulation, is in the top
  bar beside the device status, "Last run 7.0 s", after a run in this page; a narrow window leaves it out.

### Removed

- **The service route `POST /projects/{name}/carve-further`** and the code behind it (`carve_further.py`,
  `ProjectStore.replace_max_volume_with_envelope`). The app dropped Carve further on 2026-10-26 for chained criteria, and
  no other client called the route. A project carved further before still opens: it keeps its `carving_chain` and
  `inputs/earlier_max_volumes/`, and the app still names the modes under its maximum volume file.
- **The service route `PUT /projects/{name}/config`**, which saved the shared and one criterion's settings together. The
  app has saved them with `PUT /projects/{name}/shared-settings` and `PATCH /projects/{name}/criteria/{id}` since
  2026-10-26.
- **Test surfaces as a project input**: an upload or removal through `/projects/{name}/inputs/test_surfaces` (which the
  app before 2026-10-25 used, for the only criterion) is refused with 422; they go to a criterion or a study. Listing them
  there stays.
- **Two settings dropped on read**: `score_rule` (2026-10-22 only, before any release) and a typical building's
  `by_direction` (2026-10-30 to 31). A config that still sets `score_rule` is refused with the field named; a building
  that has `by_direction` is no longer read, so the window asks for a building again.
- `UserConfig.effective_max_slope_deg`, which nothing called.

### Fixed

- **The New building example's roofs no longer have a bottom.** `neighbor_roofs.ply` closed four of its pitched roofs with
  a flat base facing down (965 m², a third of the file's area), so a share of its test points faced the ground: they read 0
  in Simulate and their rays did not steer the carving. The bases are removed (1,809 faces down to 1,293; 43 roof surfaces),
  in the packaged example and in `examples/test_inputs/new_building/`. A project made from the example before keeps its
  copy; make it again from Try an example to get the new file.
- **Simulate's study values no longer break into stripes with the test surfaces shown.** The patches and the test
  surfaces they lie on were pulled forward in depth by the same amount, so with the Test surfaces layer turned on the two
  took turns pixel by pixel, more at grazing angles. The patches are now pulled further forward.
- **A criterion turned back on shows its result again.** The run summary lists only the criteria that are on, and the app
  fetched it at open and after runs only: a criterion turned on after the summary was read had an empty card line, and
  the chain line kept the numbers without it, until the next run or a reload. The app now fetches the summary again
  whenever the criteria that are on change.
- **North now turns the sky of irradiance and benefit.** Ladybug's sky matrix only records its north and runs Radiance's
  gendaymtx without it, so the patch weights of every `north_deg` were those of north 0: a turned site got the sun
  from the model's -Y. The sky is now turned by gendaymtx's `-r` before the sun is binned into the patches, which
  stay in the model's frame. The plot test scene turned a quarter now loses 1,253 voxels against 1,272 unturned
  (1,463 before). This changes the carving, Simulate's solar energy and useful solar energy and the sky dome of
  every project whose North is not 0; results computed before are not marked out of date, so run them again.
  Time-based, daylight and radiative cooling are unchanged.
- **A NaN score no longer carves its neighbours.** The score smoothing before thresholding blurred NaN and Inf scores into
  every voxel the kernel reached, which were then carved too (one NaN voxel in a 20 m cube of 1 m voxels carved 729). A
  non-finite score now adds nothing to its neighbours' blur and is carved on its own, as the warning about it says. Runs
  without non-finite scores are unchanged.
- **A chain run of preprocessing alone that leaves the last criterion out no longer fails.** The engine took the reply's
  folders from the last criterion only, which had none (`IndexError`); it now takes each stage's folder from the last
  criterion that ran it. The app always asks for thresholding too; `POST /projects/{name}/runs` could send such a request.
- **Simulate drew some test points' patches in the wrong place.** On a panel whose sampling plane had to be turned to face outward, each
  point's patch was mirrored through the panel's centre, so it showed another point's value (on the Allatini example about a third
  of the patches; a facade could read darker at the top than at the bottom). The test points, their values and the carving
  did not change. A study run before this fix shows the old patches until it is run again.
- **The legend's two ends can no longer meet.** Dragging the high end onto the low end saved both at one value: the high mark hid
  under the low one and the palette spanned one unit (0 to 1 kWh/m², with nearly everything in the top colour). An end now stays
  1 % of the bar short of the other, and a saved high end at or below the target counts as none.
- **New study settings clear the colour range.** Changing a study's settings (its period, for example) or its metric clears
  the two ends of its colour range, which are in the study's unit and fitted the last result; the next run shows its own range
  (a range set on a year's result no longer applies to a day's).

## [0.10.0] - 2026-10-30

### Highlights

- **Browser app** (`usc ui`): projects with their inputs, a Carve workspace (criteria, carving rule with a histogram,
  envelope and building massing, export), a Simulate workspace (studies of sun hours, irradiance, daylight and useful
  solar gains on any test surfaces, the sky dome, a Sun panel with sun paths, shadows and hours in shade) and an Inspect
  workspace (input files, face normals, turning faces). Light and dark themes.
- **Chained carvings**: several criteria, each with its own test surfaces and mode, carved one after another.
- **Context and terrain**: existing surroundings and the ground block sun and sky in every mode and client.
- **Energy-weighted Solar usefulness**: hours weighted by what their sun saves a typical building in heating, from a
  simple hourly model of one room; a library of typical buildings with example buildings.
- **Building massing** on floor plates, also on sloped ground.
- **Sky sampling**: several jittered rays per sky patch (`rays_per_patch`), removing banding far from the test surfaces.
- **Time basis** for time-based mode: standard, daylight saving or solar time.
- **Test point access evaluation** in the Python API; cold period preset from the weather file; scores in kWh or m².

The full list of changes is in the CHANGELOG at the v0.10.0 tag:
https://github.com/avarth/UrbanSolarCarver/blob/v0.10.0/CHANGELOG.md

### Added

- **Browser app** (`usc ui`; `--port`, `--projects-folder`, `--no-browser`, `--device`), the optional `ui` extra that
  `setup_env.py` installs unless `--no-ui` is given; `start-urbansolarcarver.bat` and `.sh` start it. The service
  listens on `127.0.0.1` with a per-launch token. A project is a folder under `~/UrbanSolarCarver/projects` (by
  default) with `inputs/`, `project.json`, `run/` and a `config.yaml` that `usc run -c` runs. Typical buildings are kept
  in `~/.urbansolarcarver/typical_buildings/`. See [Browser UI](docs/ui.md).
- **Chained carvings.** A config with a `criteria:` list carves criteria one after the other on one grid, each with its
  own mode, test surfaces, mode settings and carving rule; each decides only among the voxels the one before kept.
  - `usc run -c chain.yaml` and `run_chain(chain, out_dir, produce, start_from, context)` write
    `<out>/criteria/<id>/preprocessing` and `.../thresholding`, then `<out>/exporting` and `<out>/massing`.
    `load_config` refuses a chain file; `load_chain` and `ChainConfig` are in `chain_config.py`.
  - One step at a time: `thresholding(..., after=...)`, `usc thresholding --after <folder or manifest>`, and the `after`
    input of USC_ThresholdStage.
- **Context and terrain** (`context_path`, `terrain_path`): context removes the voxel columns it overlaps, terrain the
  voxels below the ground, and rays that hit either are dropped before scoring (`context_blocks_rays`, default on).
  Also on USC_Preprocess, USC_RunPipeline and USC_RaySettings.
- **Floor-plate massing**, stage 4 (`usc massing`, USC_Massing, USC_MassingSettings): floors of square modules
  (`ground_floor_height` 5 m, `floor_height` 3 m, `min_plate_dimension` 3 m, `plate_tolerance` 0.2, `plate_stacking`),
  written as `plates.json`, `plates.obj` and the plates in `final_mesh_format`.
- **Simulated weights for benefit mode.** `usc simulate-weights` and `generate_simulated_weights` run an ISO 13790
  simple hourly (5R1C) model of an archetype (`usc archetype`, `configs/archetype_example.yaml`) and write
  `simulated_weights.json` with hourly `benefit[t]` and `harm[t]`. Benefit mode reads it with `simulated_weights_path`
  in place of the balance rule. Grasshopper: USC_Archetype, five USC_Zone* feeders, USC_SimulateWeights. Tutorial 5.
- **New settings.** `rays_per_patch` (1, 4, 9 or 16) in the weighted modes. `time_basis: standard | daylight_saving |
  solar` for `time-based`. `edge_taper` (weighted modes) and `min_sky_elevation_deg` (`radiative_cooling`). `threshold`
  also takes `{method, value}` (`carve_fraction`, `headtail`, `cutoff`), `analysis_period` one Ladybug mapping.
- **Python API.** `run_pipeline(config, out_dir, produce=("exporting",), start_from="preprocessing", context=None)`
  returns a `PipelineResult`; `build_config(values)`; errors derived from `UrbanSolarCarverError` (`ConfigError`,
  `InputError`, `StageChainError`, `RunCancelled`); a `RunContext` with progress, `cancel()` and issues that replace
  `warnings.warn`; `test_point_access_evaluation`, `urbansolarcarver.cold_period` and `urbansolarcarver.grid_planning`.
- **CLI and daemon.** `usc run --produce` and `--start-from`, `usc warmup [-d cpu|cuda]`, the daemon's `run` and
  `simulate_weights` requests, a session cache kept between daemon commands (1 GiB). Thresholding writes
  `scores_compared_with_cutoff.npy`. A Golden, CO EPW ships in `examples/weather/`; USC_SyncCanvas updates a canvas.

### Changed

- **Weighted-mode scores are in physical units (results change).** `irradiance` and `benefit` in kWh (they were
  labelled Wh/m²), `daylight` and `radiative_cooling` in m² of hidden sky, `time-based` in m²·h (it was a ray count).
  A numeric `threshold` must be chosen again: at 0.5 m spacing an earlier `irradiance` score is 4 times the new one,
  `daylight` about 17 times. `carve_fraction` and `headtail` do not depend on the scale.
- **New defaults (results change).** `grid_step` unset samples at half the voxel size (was 1.0 m; a run takes about
  twice as long). `rays_per_patch` 4 (`1` gives earlier scores). `sun_steps_per_hour` 12 (the sun was sampled hourly).
  `ray_length` 3000 m (was 300 m). `carve_above` `true` (was `false`). `balance_temperature` 15 °C (was 20).
- **Thresholding (results change).** Rules and retention count occupied voxels only (empty cells held 60-80 % of the
  score mass). `carve_fraction` counts what `carve_above` removes: 0.4 before is about 0.55 now. `carve_above` ignores
  empty cells and no longer refills short runs. The new `max_slope_deg` (75 degrees in the weighted modes, `90` off) caps
  each column's rise over its neighbours.
- **Ray rules (results change, all modes).** A voxel obstructs a test surface only when wholly in front of it, and a
  surface no longer counts the boundary voxels of its own mass. `tilted_plane` removes all mass above the plane, not a
  band, and turns the plane around convex corners. On the CPU the same Warp kernel as on CUDA runs (the old marcher
  skipped up to about 37 % of voxels; `full_blocks` daylight 101 s to 5.8 s, score +61 %).
- **Benefit mode (results change).** The weights are the irradiance of the hours below `balance_temperature -
  balance_offset` (they were Ladybug's benefit minus harm, clipped at zero); `include_harm: true` subtracts hot hours.
  `balance_offset` must be `>= 0`.
- **Stage chain.** Manifests carry `run_id` and `upstream_run_id` in place of `hash` and `upstream_hash`; a stage whose
  upstream is missing or from another run raises `StageChainError`. `PreprocessingResult.hash` and
  `ThresholdingResult.hash` are `run_id`, `ThresholdingResult.upstream` is `upstream_run_id`. Manifest paths are
  relative, so run folders can be moved. A stage deletes its old outputs first; a config whose `mode` differs from the
  run's raises `StageChainError`.
- **Errors and modules.** Some `FileNotFoundError` and `RuntimeError` are now `InputError`, `StageChainError` or
  `ConfigError` (`ValueError` subclasses); `load_mesh` raises `InputError`. `grid.py` is split into
  `surface_sampling.py`, `voxelization.py` and `meshing.py`, `raytracer.py` into `warp_kernels.py` and
  `ray_tracing.py`.
- **Diagnostics keys.** `voxels_carved` is `voxels_retained`, `voxels_total` is `voxels_occupied`,
  `normalized_score_stats` is `occupied_score_stats`, `upstream_hash` is `upstream_run_id`; `threshold_method` reports
  `cutoff` for `numeric`. The `diagnostics` flag, unused before, now adds the detailed score statistics (median, standard
  deviation, percentiles).
- **Relative paths** in a YAML resolve against its folder, not the working directory (USC_Config: the `.gh` file).
- **Grasshopper.** Stage components send the daemon's `run` command and read their upstream from `<out_dir>/<stage>`;
  issues show as warnings; daemon calls time out; geometry passes in double precision; all `.ghuser` files are rebuilt.
- **Speed.** Full pipeline on a 306³ grid (daylight, CPU) 112 s to about 34 s; sky weights and EPW files are cached.

### Removed

- `ground_reflectance` (it never affected results; a config with it fails validation), `configs/user_config.yaml` and
  the dotted `a.b=c` override form.
- The `cuda` extra, the daemon's `--authkey` option and USC_RunPipeline's subprocess fallback.
- The fixed-step fallback tracer: without a working Warp the carvers raise `WarpBackendUnavailableError`.

### Fixed

- **Georeferenced coordinates** keep float64 precision through preprocessing, PLY and GLB export (float32 rounded to
  about 0.5 m at UTM northings).
- **`north_deg`** is honoured by `time-based` and `tilted_plane`.
- **Carving and export.** `headtail` follows Jiang (2013) (its stop rule was inverted); `carve_above` set on USC_Threshold
  had no effect; the trimesh voxelizer placed the grid half a voxel off; the smoothed mesher no longer
  binarizes the SDF or shrinks the mesh.
- **Runs.** Two sky matrices of one weather file no longer read each other's file; a client can no longer stop the
  daemon; the grid size limit is checked before allocation; `setup_env.py` maps CUDA 13 drivers to CUDA wheels.

### Upgrading from 0.9.0

- **Re-run every run folder from preprocessing.** 0.9.0 manifests have no `run_id`, and thresholding, exporting and
  massing refuse them with a `StageChainError` naming the stage to re-run.
- **Expect different results** in every mode. Choose numeric thresholds of the weighted modes again; raise
  `carve_fraction` for a result like 0.9.0's. Set `rays_per_patch: 1` to compare scores, `carve_above: false` to keep
  floating mass.
- **Configs:** remove `ground_reflectance` and dotted overrides; check relative paths and `balance_temperature`.
- **Python:** `result.export_path` is `result.exporting.export_path`; `.hash` is `run_id`; imports from
  `urbansolarcarver.grid` and `urbansolarcarver.raytracer` move; rename the diagnostics keys you read.
- **Install:** drop the `cuda` extra; add `ui` for the browser app; refresh an editable install with
  `pip install -e . --no-deps`.
- **Grasshopper:** restart the daemon (an old one answers "Unknown command: 'run'"), then run USC_SyncCanvas.

## [0.9.0] - 2026-04-02

First public beta release.

### Added

- **3-stage pipeline**: preprocessing (voxelise, ray-cast) → thresholding (score ranking, carve fraction) → exporting (mesh reconstruction)
- **6 analysis modes**: time-based, irradiance, benefit (heating/cooling), daylight (CIE overcast), tilted-plane, radiative-cooling (experimental)
- **GPU acceleration**: NVIDIA Warp ray tracer with automatic CPU fallback
- **Thresholding strategies**: `carve_fraction` (direct), `headtail` (automatic heavy-tail detection), numeric threshold
- **Score smoothing**: optional Gaussian smoothing with auto-default sigma (1.1× voxel size)
- **Carve-above column post-processing**: remove structurally implausible floating mass above carved zones, with configurable `min_consecutive` sensitivity threshold
- **Connected-component filtering**: `min_voxels` parameter removes small isolated fragments
- **Multi-format mesh export**: PLY, OBJ, STL, GLB output via trimesh
- **Run report**: automatic `run_report.md` summarising every pipeline run
- **Diagnostic outputs**: score histograms, sky-patch hemisphere plots, config snapshots, step timings
- **CLI** with two entry points (`usc`, `urbansolarcarver`): `run`, `validate`, `info`, `list-modes` commands
- **Python API**: `preprocess()`, `threshold()`, `export()` for decomposed workflows
- **Grasshopper integration**: 17 GHPython components for Rhino 8
- **Configuration**: single YAML file with Pydantic v2 validation (`extra='forbid'`)
- **Memory guard**: rejects grids exceeding 500 million voxels
- **Mode registry**: single source of truth for mode definitions and parameter requirements
- **5 tutorial notebooks**: quick start, mode comparison, threshold tuning, Grasshopper bridge, advanced post-processing
- **Reference YAML**: fully commented `REFERENCE_all_options.yaml` with all configuration fields

### Notes

- `radiative_cooling` mode is marked experimental (clear-sky only, horizontal surfaces)
- GPU (`[cuda]` extra) is recommended for grids above ~100³ but not required
- Requires Python >= 3.9
