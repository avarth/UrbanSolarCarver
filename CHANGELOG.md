# Changelog

All notable changes to Urban Solar Carver are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Removed

- **protect_share and recovered_sky.** Thresholding offers
  `carve_fraction` (the default of the weighted modes), `headtail` and a
  numeric cutoff, with score smoothing, carve_above and the slope limit
  (below). Configs that set `protect_share` or `threshold: protect_share`
  are rejected.

### Changed (weighted modes; results change)

- **carve_fraction counts what carve_above removes.** The cutoff was
  computed on the voxels it picked, and carve_above then removed the
  voxels above them uncounted: carve_fraction 0.4 removed 50-62% of the
  obstruction score in the ReSBE test blocks (33 m, 0.5 m voxels), 0.6
  removed 64-73%. Each voxel now gets the cutoff at which carve_above
  would remove it (`carving.carve_above_scores`, which reproduces
  `carve_above_columns` exactly), and the cutoff is found on those values
  while counting each voxel's own score, so the removed share is the value
  set, up to one group of tied voxels. The same carve_fraction now keeps
  more volume than before (0.4: 72-75% kept instead of 56-68%); to get a
  result like before, raise it (0.4 before is about 0.55 now). The shapes
  for a given removed share are unchanged.
- **Slope limit after carve_above (`max_slope_deg`, back).** Each column
  is decided by its highest-scoring voxel, and scores in a column rise and
  fall with height, so neighbouring columns whose peaks fall just above
  and below the cutoff end 10-15 m apart, and score noise leaves spires.
  The resolution study (ReSBE blocks at 33 m, voxel sizes 0.5-2 m,
  sample spacing 0.25-2 m) showed that finer sampling reduces spikes only
  modestly (0-37% fewer with 4x the rays), so they come from the column
  rule rather than from rays missing voxels. Thresholding again caps each
  column at a maximum rise above a 5 x 5 median-filtered height map of its
  neighbours (`carving.limit_column_slope`): it only removes voxels and
  keeps the slider nested. Default: 75 degrees for the weighted modes, off
  for time-based and tilted_plane; `90` turns it off. In the ReSBE blocks
  at 0.5 m voxels it cut the spike area from 26-186 m2 to 0-25 m2 and
  the share of column pairs 2 m apart that differ by 9 m or more from
  3-14% to 0.1-1.7%, for 0-10% of extra obstruction score
  (`obstruction_fraction_carved_by_slope_limit`; most at low
  carve_fraction). At 1 m voxels it is weaker (its median window and
  allowance are counted in voxels). Diagnostics, the run report,
  USC_ThresholdStage and USC_Threshold (input `max_slope`) report or set
  it.
- **A voxel obstructs a test surface only if it lies entirely in front of
  it.** Before, a voxel counted when its centre was in front of the
  surface's plane, so the voxels a facade's own plane passes through (its
  skin) counted as obstructions of that facade. That mattered where test
  panels lie inside a curved mass (faceted facades of a round or freeform
  building): in the ReSBE freeform block, edge columns were carved to the
  ground for nothing. Flat facades aligned with the grid are unaffected.
  Applies to every mode (Warp kernels, the fixed-step fallback and the
  test reference).

### Fixed (tilted_plane; results change)

- **The tilted plane rotates around convex corners of the test surfaces.**
  Each sample point cast one ray along its own normal, so where two facade
  panels meet at an outside corner or a convex kink the two panels' rays
  diverged, and columns between them were crossed by no ray and stayed at
  full height: one-voxel spires at convex corners and vertical strips
  beyond kinks (a 6.7 degree kink left strips from about 8 m out; a 90
  degree corner left the whole outside wedge uncarved). Present since
  0.9.0. Neighbouring sample points whose normals turn convexly now also
  cast rays at headings swept between the two normals, so the wedge is
  capped by the plane rotated around the corner (at 45 degrees: height =
  distance from the corner). Concave corners are unchanged. In the
  full_blocks example at 1 m voxels the 45 degree envelope keeps 3.0% less
  volume (octant table: 3.5% less) and tilted-plane carving takes about
  0.7 s instead of 0.1 s on the CPU. No new parameter.

### Added

- **Floor-plate massing (stage 4, `massing`).** Turns the carved envelope into
  stacked floor plates: a ground floor (`ground_floor_height`, 5 m), then
  floors of `floor_height` (3 m). The footprint (the maximum volume's plan projection) is
  split into faces, one per facade (corners squared to the longer facade), and
  each face into bays of `min_plate_dimension` (3 m) cut perpendicular to its
  facade. A bay is built on a floor when it stays in the maximum volume, at
  most `plate_tolerance` (0.2) of its volume lies outside the envelope, and,
  with `plate_stacking: supported`, it is built on the floor below; parts
  narrower than `min_plate_dimension` are dropped. Writes `plates.json` (world
  outlines, floor areas) and `plates.obj` (one closed prism per plate) and adds
  a Massing section to the run report. `usc massing`, a daemon command, and the
  Grasshopper components USC_Massing and USC_MassingSettings. Geometry in
  `urbansolarcarver.floor_plates`.

- **Simulated-weights generator (benefit mode)**: `usc simulate-weights` and the
  `urbansolarcarver.simulated_weights` module: an ISO 13790 Annex C simple hourly
  ("5R1C") thermal model plus batched central-difference perturbation,
  producing the hourly *marginal* benefit/harm of solar gain, `benefit[t]` (fraction of
  a marginal joule of solar gain that offsets heating over the year) and
  `harm[t]` (fraction that becomes cooling load), written to a
  `simulated_weights.json` artifact with full provenance metadata. Inputs:
  one EPW plus ~10 archetype parameters (`configs/archetype_example.yaml`;
  neutral values, no national defaults). The engine is validated against
  ETH's RC_BuildingSimulator on three archetypes under the bundled Golden
  TMY3 weather (annual demands and hourly node states; driving arrays
  stored verbatim in `tests/data/`), plus steady-state closure against an
  independent network reduction. Design, tier ladder, and declared
  limitations: `design/simulated-weights.md`.
- **`simulated_weights_path`** (benefit mode): consume a simulated-weights artifact
  in place of the balance-point hour filter: each hour's DNI/DHI is scaled
  by `benefit[t]` before the cumulative sky matrix (the balance filter is
  the binary special case of this mechanism), and `include_harm: true`
  subtracts the `harm[t]`-scaled matrix clipped at zero. Analysis-period
  hours outside the period are zero-weighted. `balance_temperature`/
  `balance_offset` are unused (warns if customized); artifact provenance is
  recorded in preprocessing diagnostics (the artifact is read again on every
  preprocessing run, so edits to it take effect). Occupancy: archetypes accept a flat internal-gains
  value or a 24-value daily profile.
- **Shoebox archetype shorthand**: instead of explicit areas, an archetype
  may give `width`/`length`/`height` plus per-facade `wwr` (window-to-wall
  ratio), `g_value`, and optional `orientation`; floor area, volume,
  per-facade window areas, `area_window`, and `area_opaque` (opaque walls +
  roof) are derived. `configs/archetype_example.yaml` shows both forms.
- **Weights preview**: `usc simulate-weights` / `generate_simulated_weights` write a
  `.png` companion next to the artifact (benefit and harm as day x hour
  heatmaps), so the schedule can be inspected without writing code.
- **Sky-weight comparison in diagnostics**: a benefit run that consumes a
  simulated-weights artifact (with `diagnostic_plots: true`) also records a
  difference dome versus the simple balance-point rule for the same config
  (`sky_patch_comparison_image` + redistribution stats in
  `diagnostic.json`).
- **Tutorial 5** (`examples/5_benefit_5r1c.ipynb`): simulated benefit
  weights end-to-end: archetype, weights generation and inspection,
  simple-vs-simulated carve comparison, harm channel, provenance.
- The sample Golden CO TMY3 EPW is now actually committed
  (`.gitignore` exception), so the tutorials and EPW-dependent tests run
  out of the box as documented.
- **`usc archetype`**: builds a shoebox archetype YAML from defaults or an
  existing file (`--from`), with `-s key=value` overrides (`wwr_south=0.4`
  style for the per-facade ratios). The file is validated through the
  generator's own code path before writing, and the derived floor area,
  volume, and per-facade window areas are printed, so mistakes surface here
  and not inside a simulation.
- **`usc validate` checks the weights artifact**: when
  `simulated_weights_path` is set, the artifact itself is read and
  validated (existence, schema, 8760 bounded values) at validate time
  instead of failing mid-preprocessing.
- **Daemon `simulate_weights` RPC**: the persistent daemon generates
  weights artifacts on request (archetype as inline mapping or YAML path),
  so Grasshopper avoids a cold Python start per generation.
- **Grasshopper components for simulated weights**: new `USC_Archetype`
  assembles a typical building from five Honeybee-style family feeders
  (`USC_ZoneGeometry`, `USC_ZoneFabric`, `USC_ZoneVentilation`,
  `USC_ZoneOperation`, `USC_ZoneShading`; one wire per family, all
  optional with neutral defaults), and `USC_SimulateWeights` runs the
  simulation through the daemon (outputs the artifact path and the
  heatmap preview).
  `USC_BenefitParams` gains `simulated_weights_path` and `include_harm`
  inputs (with an on-canvas remark when balance settings are wired but
  unused), and `USC_Preprocess` surfaces the sky-weight comparison dome
  and redistribution stats in its diagnostics outputs.
- `generate_simulated_weights` reads internal gains from the archetype's
  `internal_gains_w_m2` / `internal_gains_profile_w_m2` keys when the
  argument is omitted, so CLI, daemon, and Grasshopper pass archetypes
  through unmodified.
- **Shading coefficients** (archetype keys, declared multipliers; no
  device geometry): `shading_permanent` (year-round transmission factor
  for fins/context) and `shading_hot` (additional factor deployed during
  the user-declared `hot_months`; awnings, tents, seasonal vegetation).
  Each accepts a scalar or a per-facade mapping (windows bin to their
  nearest cardinal). The attribution is attenuated by the same effective
  hourly transmission, preserving the artifact's exterior-joule semantics,
  and declared values land in the artifact provenance. Declaring seasonal
  shading makes the `harm` channel a defensible estimate instead of a
  conservative worst case. Supported in `usc archetype` (-s overrides)
  and on the USC_Archetype Grasshopper component (scalars).
- **`grasshopper/build_ghuser.py`**: builds the `.ghuser` user objects
  from the component sources (port names/descriptions from each GH UI
  block, port order and type hints from the numpydoc docstring, ribbon
  placement and stable GUIDs from `grasshopper/components.json`), using
  Grasshopper's `GH_IO.dll` without running Rhino. Byte-reproducible;
  `--check` flags stale files. `pip install -e .[ghbuild]` adds pythonnet.
  `tests/test_gh_components.py` keeps sources and docstrings in sync.
  Serialization adapted from the MIT-licensed GHPython Componentizer.
- **USC_SyncCanvas Grasshopper component**: updates the USC components
  on an open canvas to the installed versions. Unchanged inputs/outputs:
  replaced in place with wires, internalised values, data mappings,
  enabled/preview state and group membership kept. Changed inputs/outputs:
  the new version is placed beside the old one in a red group naming the
  new/removed ports, for manual rewiring. Report-only unless `update` is
  True; one undo step; a failed update rolls back.
- **End-to-end carving tests on urban typologies** (`tests/typologies.py`,
  `tests/oracle.py`, `tests/test_typologies.py`): eight procedural block
  types (courtyard, towers, rows, freeform, L-block, podium, random
  polygon, ground-floor passage) run through the full pipeline and
  checked against an independent CPU reference marcher, plus invariants
  (no floating mass, empty-cell independence, carve_fraction nesting,
  georeferenced translation, CPU/CUDA parity, cross-stage diagnostics).
  `tests/montecarlo.py` draws random scenes and settings from a seed and
  runs the same checks; any failing case is reproducible from its seed.

### Changed

- **All Grasshopper `.ghuser` files rebuilt from source.** The packaged
  files had drifted from `grasshopper/components/` (e.g. the USC_Session
  `python_path.txt` lookup and the PLY-loader hang fix were never
  packaged); the seven simulated-weights components (USC_Archetype, the
  five USC_Zone* feeders, USC_SimulateWeights) are packaged for the first
  time, in a new `3::Weights` ribbon group, with icons. Inputs now carry
  the type hints their docstrings declare (`bool`, `float`, `int`, `str`
  instead of untyped), so text panels convert as expected (e.g. `"False"`
  into a `run` or `include_harm` input is false, not a truthy string).

- **Benefit mode now implements its documented formula exactly (by
  default)**: patch weights are a plain cumulative irradiance matrix over
  the hours below `balance_temperature − balance_offset` (Heaviside filter
  on EPW dry-bulb). Previously the weights were always Ladybug's signed
  benefit−harm net clipped at zero, which silently let hot-hour radiation
  erode winter weights and made results depend on whether the analysis
  period included summer. A full-year analysis period is now safe and
  natural: the balance filter selects the beneficial hours by itself.
  The composite remains available as a declared, opt-in experiment:
  `include_harm: true` subtracts hot-hour radiation per patch (clipped at
  zero, dead-band hours count for neither side), with its period-dependence
  documented. Shading value is deliberately never a carving force: with
  signed retention, every voxel along a hot-hour ray earns shade credit, so
  the "optimal" envelope keeps whole sun-path prisms (cave-like volumes).
- `balance_temperature` default changed from 20 to **15 °C** (Ladybug's
  default; typical range ~12 commercial to ~18 residential, higher for
  older poorly insulated stock). Derive project-specific values via the
  Honeybee/E+ balance-point workflow.
- `balance_offset` now validates `>= 0` (a negative offset silently inverted
  the dead-band, so the cold-hour and hot-hour ranges overlapped).
- User-facing terminology for the two benefit weightings: "simple weights"
  (balance-point rule) vs "simulated weights" (5R1C hourly simulation);
  the internal "Tier 1.5" label no longer appears in docs, CLI, or configs.
  The module and all public names use the `simulated_weights` family
  (`generate_simulated_weights`, `simulated_weights_path`,
  `usc simulate-weights`, `simulated_weights.json`); no aliases are kept
  since the feature is unreleased.
- Benefit mode warns loudly and returns all-zero weights when the analysis
  period contains no beneficial hours (previously this fell through toward a
  degenerate carve with only a generic downstream warning; an empty hour
  list must also never reach Ladybug, which treats it as "whole year").

### Removed

- **`ground_reflectance` config field**. It never affected results: Ladybug
  SkyMatrix only stores it as metadata for RadiationStudy, which USC does
  not run, and USC's ray casting targets sky patches only. Configs carrying
  the key now fail validation with a clear message; remove the line. The
  USC_RaySettings Grasshopper component no longer emits it (old canvases
  keep the input; it is ignored).

### Fixed (code review)

- **CPU runs lost score updates.** Warp's CPU `atomic_add` is a plain
  read-modify-write, and CPU batches ran from a thread pool on one shared
  buffer: about 6e-5 of the score mass was lost per run, by a different
  amount each time. Each thread now accumulates into its own buffer.
- **The daemon could be stopped by a client.** A wrong authkey, a client
  that disconnected before its reply, or an unreadable message ended the
  server loop. Each connection is now handled in isolation; errors reply
  with the exception type, and GPU memory is released after every run.
  The unusable `--authkey` option is removed.
- **`carve_above` from the Grasshopper Threshold component had no
  effect.** It was applied in exporting, which never received the
  threshold overrides. It now runs in thresholding, so `mask.npy` and
  the reported retention describe the exported envelope.
- **USC_Mode could not be wired to anything that worked.** It now outputs
  `mode_name` for USC_Config's `mode` input.
- **`headtail` used the inverted stop rule** and returned the plain mean
  on heavy-tailed scores. It now follows Jiang (2013): keep splitting
  while the head is a minority, return the deepest such break.
- **Irradiance and benefit scores were labelled Wh/m²**; Ladybug returns
  kWh/m².
- **Relative paths in a YAML config now resolve against the YAML's own
  folder** (they resolved against whatever directory the CLI, daemon or
  Rhino happened to run in, so one config found its files in one place and
  not the other). The CLI sends the daemon absolute paths, and USC_Config
  resolves relative paths against the saved `.gh` file.
- **Period overrides no longer clash with an `analysis_period:` block**:
  flat `start_*`/`end_*` overrides (what USC_AnalysisPeriod sends) win.
- **`radiative_cooling` no longer requires an EPW or analysis period** (it
  never read them), and irradiance/benefit no longer list `min_altitude`
  (unused). Setting a field the chosen mode ignores now warns.
- **Thresholding refuses scores from a run in another mode** instead of
  applying that mode's default threshold rule to them.
- **The session cache returned tensors on the wrong device** (a CPU run
  inside the CUDA daemon failed in the Warp launch) and keyed voxel grids
  on trimesh's rotation-invariant mesh identifier. Keys now include the
  device, voxel grids are keyed on mesh contents, and leaving a
  `with CarverSession()` block closes the session.
- **CLI `--daemon`**: `--dry-run` stays local, manifests are auto-detected
  before sending, daemon errors exit 1 with a readable message, and
  `daemon start` refuses to start a second daemon, reports a crashed one,
  and logs to `~/.urbansolarcarver/daemon.log`. `daemon status` exits 1
  when no daemon runs.
- **A stage that fails midway can no longer leave the previous run's
  manifest** pointing at half-overwritten arrays; the run report goes into
  the run folder (not the export folder's parent) and an old one is
  removed before regenerating.
- **Silent fallbacks now warn.** Skipped test-surface panels (non-planar,
  degenerate, unsampled) are reported by component index; the Warp to
  trimesh voxelizer fallback and a Warp installation that fails to
  initialise are reported; tilted-plane samples on horizontal surfaces
  are reported; score smoothing clipped to 0.5-8 voxels says so.
  `smooth_iters` is validated to 0-6 instead of being clamped silently.
- **One zero-area face no longer drops a whole test-surface panel**, and
  edge samples no longer depend on vertex numbering (inward side chosen by
  ring order, not shapely object identity) or on which panel edge is
  "first" (both edges sampled alike).
- **Smoothed export:** the Taubin polish shrank the mesh (wrong sign of
  its inflating step; -10% volume at 6 passes), and an empty grid produced
  a box around the whole domain. `cleanup_mesh` kept every fragment when
  none reached `min_face_count`; it now keeps the largest and warns.
- **An EPW replaced on disk is re-read** by a running daemon (the parse
  cache now keys on modification time and size).
- **Grasshopper components share one helper module**
  (`grasshopper/usc_gh.py`) instead of keeping 2-5 drifting copies of the
  daemon call, PLY reader/writer, mesh conversion and override parsing
  (Preprocess, Threshold Stage, Export and Run Pipeline went from 1,343 to
  528 lines). Daemon calls time out instead of freezing Rhino on a hung
  daemon, errors show as red runtime messages everywhere, a missing result
  file is an error instead of an empty output, test points are read
  without numpy, and USC_Session checks the daemon with a ping (not
  "a key file exists and the port is open"), logs a detached daemon to
  `~/.urbansolarcarver/daemon.log` and reports a daemon that crashed on
  start. USC_RunPipeline's subprocess fallback is removed (it broke on
  quotes in paths and on Warp's start-up banner); it needs the daemon like
  the other stages. Brep inputs now reach the components unconverted, so
  the fine Brep meshing applies instead of Grasshopper's coarse default.
  USC_Archetype reports a connected family input that delivered nothing
  (a failed USC_Zone* component) instead of silently using defaults.
- **Exporting** meshed with the config's `voxel_size` instead of the
  preprocessing run's, and counted retained voxels before the small-
  fragment cleanup (now reported as `voxels_removed_by_cleanup`).
- **Smaller fixes from the comment and docstring review**:
  - Re-voxelizing a run whose `voxel_grid.npy` is missing now uses the
    preprocessing run's voxel size, not the one in the config passed later.
  - A planar test surface too small for the sampling grid gets its single
    sample at a point inside the polygon (the vertex centroid can fall
    outside an L-shaped or ring-shaped surface).
  - Sample normals and analysis-quad winding follow the area-weighted face
    normal instead of the first face's, which is zero for a zero-area face.
  - The iso-level helper of the smoothed mesher had its two edge cases
    swapped (all cells inside / no cell inside).
  - Hour-of-year indices are validated as 0 to 8759 (EPW files hold 8760
    hours; 8760 to 8783 used to pass and were dropped silently).
  - An archetype with `wwr`, `g_value` or `orientation` but no
    width/length/height now fails with "shoebox archetype is missing ..."
    instead of a later TypeError.
  - The fixed-step tracer (no Warp) sized its chunks for 24 bytes per
    sample; it holds 49, so it could use about twice its memory budget.
  - The daemon authkey file is created with owner-only permissions on
    Linux and macOS from the start, and two processes starting at once
    no longer write different keys. A CLI call with a mismatched key
    prints a message instead of a traceback.
  - Carving looked up the Tregenza patch directions with a keyword
    argument, which bypassed the session cache.
  - USC_Config resolves relative `epw_path` / `simulated_weights_path`
    from USC_EPW and USC_BenefitParams against the .gh file, as it does
    for its own inputs. USC_Threshold warns about an unknown `method`
    instead of ignoring it.
  - `load_mesh` turns closed bodies stored inside out so their normals
    point outward (before, only open meshes had their winding fixed).
  - Tregenza solid angles are built from Ladybug's per-band constants:
    its `ViewSphere.tregenza_solid_angles` property returns the 577
    Reinhart values once `reinhart_solid_angles` has been read.
  - The sky-patch diagnostic plot drew the Tregenza band edges at the band
    centres (6°, 18°, ...); they are now at 0°, 12°, ..., 84°.
  - The thresholding diagnostic `normalized_score_stats` is renamed
    `occupied_score_stats`: the scores are not normalized, they are the
    occupied-voxel scores the threshold was compared with.
  - Automatic ray batch size with Warp assumed 320 bytes per ray for hit
    lists the fused kernels no longer keep; it now assumes 96, so GPUs
    with little free memory get larger batches.
  - USC_SimulateWeights without `out_path` on an unsaved .gh file writes
    to `~/.urbansolarcarver/simulated_weights.json` instead of failing.
  - The Grasshopper PLY reader reads x, y, z from any column position in
    ASCII files, accepts any face list count and index types, and splits
    faces with more than four corners into triangles (they were cut to
    quads).
- **Session cache kept between daemon commands**: the daemon cleared its
  cache after every command, so re-running preprocessing on unchanged
  geometry voxelized again. The cache now persists, capped at 1 GiB
  (`CarverSession(max_cache_bytes=...)`) with least-recently-used
  eviction; after each command the daemon only returns unused GPU memory.
- **Docs and comments**: docstrings, comments, CLI help, config field
  descriptions, Grasshopper port descriptions and the docs pages were
  checked against the code and corrected where they disagreed (removed
  functions, wrong defaults, units, file names, mode requirements).
- **Tests**: tests that only checked hand-written values (`hashlib`, a
  literal manifest dict, a copied mode table) now run the real stages or
  read the mode registry; a new exporting test checks that a model at UTM
  coordinates keeps its voxel lattice to 1e-6 m end to end.

### Removed (code review)

- Unused code: the buffered Warp DDA tracer (replaced by the fused
  kernels), the point-cloud and diagnostic exporters in `io.py`,
  `sun.warm_up`, unused `AnalysisMesh` methods, the never-read
  `suggested_threshold` manifest field, and the report's fallback to the
  old `summary.json` / `timings.json` files.

### Fixed (carving correctness; results change)

Found with a new end-to-end harness (procedural urban typologies checked
against an independent CPU reference marcher, plus Monte Carlo runs).

- **Protected surfaces obstructed themselves.** Rays started inside the
  boundary voxels of the mass a test surface belongs to, and those voxels
  were counted as obstructions: protected lower floors lost a voxel-thick
  skin on roughly half their facades (every facade on curved footprints),
  and with `carve_above` the whole column above went with it. Weighted modes
  gave those voxels the highest scores. The DDA kernels now skip voxels
  whose centre lies behind the ray's source surface (exact rule, per-ray
  surface normal; no origin offset, which would shift rays sideways).
- **`tilted_plane` carved a band, not the half-space above the plane.** Only
  voxels crossed by each sample's ray were removed, so mass above the band
  swept by a facade survived as floating slabs. Every voxel at or above a
  ray in its column is now removed.
- **Thresholds were resolved over empty cells.** `carve_fraction`,
  `headtail`, score smoothing and the reported retention used every grid
  cell; streets, courtyards and the grid margin hold 60-80% of the score
  mass, so `carve_fraction: 0.8` removed 79-86% of the building's own
  obstruction depending on the scene, and results changed with
  `margin_frac`. Everything now uses occupied voxels only (smoothing is a
  normalized convolution over the building); the mask is False on empty
  cells.
- **`carve_above` treated empty cells as carved mass.** Air the mask marked
  False (a passage under a bridge, the margin) could trigger removal of
  everything above it. Runs are now made of carved occupied voxels only.
- **Time-based sampled the sun hourly.** The sun moves ~15° of azimuth per
  hour; mass between consecutive hourly ray sheets survived while shading
  the protected surface between samples (58-322 voxels per scene at 1 m).
  New `sun_steps_per_hour` (default 12 = every 5 min). Violation scores
  are now shaded area x duration in **m²·h** (they were raw ray counts,
  which grew with both the sun sampling and the surface sampling density),
  so a numeric threshold means the same at any `grid_step` and
  `sun_steps_per_hour`.
- **Georeferenced coordinates lost precision.** Voxelization, sampling and
  tracing ran in float32 world coordinates (~0.5 m resolution at UTM
  northings). Preprocessing now works in a local frame (coordinates rounded
  to 1 µm, so the same scene placed anywhere samples and carves
  bit-identically) and persists world coordinates in float64; surface
  sampling no longer drops or keeps a panel's edge row at random when the
  sampling lattice coincides with that edge. The exported mesh is placed in float64 and PLY
  exports switch to double-precision vertices when float32 would round by
  more than 1 mm. A warning names float32 PLY inputs whose coordinates are
  already rounded on disk by more than 1% of a voxel. The Grasshopper
  components now write their input geometry with double-precision vertices
  (previously float32: a Brep box at UTM coordinates reached USC 0.21 m off;
  verified exact in Rhino 8.35), and their PLY readers accept
  double-precision files and build double-precision Rhino meshes.
- **`carve_above` defaults to `true`** (was `false`). Time-based and
  weighted carving otherwise return mass floating above carved zones
  (8k-24k voxels on the ReSBE demo scenes): physically it casts no
  violating shadow, but the classical solar envelope is a height field and
  floating mass cannot be built. Set `carve_above: false` to keep it.
- **`carve_above` no longer refills short carved runs.** Runs shorter than
  `carve_above_min_consecutive` were patched back to kept, reinstating
  voxels the solar constraint had removed (up to ~100 per scene). They now
  stay carved and simply do not trigger; carve_above only ever removes.
- **Diagnostics.** Exporting reported the retained voxel count as
  `voxels_carved`; it is now `voxels_retained`, with `voxels_removed`
  added. Thresholding reports `voxels_occupied` (replacing `voxels_total`,
  which counted the whole grid) and retention over occupied voxels, so both
  stages report the same retention.

### Added

- **`edge_taper` design constraint** (all weighted sky-patch modes): sample
  points within `edge_taper` meters of their test-surface component's
  boundary count proportionally less (linear ramp), so perimeter/corner
  points no longer force carving of directly adjacent volume. This replaces the
  manual practice of offsetting test-surface edges. Distances are exact 2D
  distances to the welded component outline (exterior and holes), so
  exploded-but-coincident panels (e.g. street networks) have no phantom
  seams. Zero-weight rays are dropped before tracing. Components narrower
  than ~2× the taper warn loudly and per-component stats are recorded in the
  preprocessing diagnostics, so the taper never silently excludes geometry.
  Ignored (with a warning) by the binary violation-count modes.
- **`min_sky_elevation_deg` protection cone** (radiative_cooling): sky
  patches below the declared elevation are excluded from the cooling weights
  (renormalized): a declared design constraint analogous to
  obstruction-angle daylight rules, controlling how steeply the envelope may
  rise around protected surfaces. Default 0 keeps the pure physical model.
- The radiative-cooling template now documents both constraints and ships a
  mode-appropriate `carve_fraction: 0.35` default (cooling scores are
  diffuse; the 0.7 used by solar modes over-carves drastically).

- **Canonical `ThresholdSpec`**: `threshold` now normalizes every accepted
  spelling (bare number, `headtail`, `carve_fraction`, or the canonical
  mapping `{method: ..., value: ...}`) into one validated object at config
  load. Methods: `carve_fraction`, `headtail`, `cutoff`. Mode defaults are
  resolved at load time (weighted modes → `carve_fraction`, count modes →
  `cutoff 0`), and the method is cross-checked against the mode's score
  kind; misuse fails at load with a precise message. All previous config
  spellings keep working.
- **`analysis_period` mapping**: the analysis period can be given as one
  mapping using Ladybug's `AnalysisPeriod.to_dict()` keys (`st_month` …
  `end_hour`; `start_*` spellings also accepted; LB's `type`/`timestep`/
  `is_leap_year` extras are ignored). The six flat fields remain valid.
- **Bundled example weather file**: a public-domain NREL TMY3 EPW (Golden,
  Colorado) ships under `examples/weather/`, so the tutorial notebooks and
  the EPW-dependent tests run out of the box. `USC_EPW_PATH` still overrides
  it for the test suite.
- **`setup_env.py` long-path preflight**: on Windows, the installer now
  predicts the 260-character path failure that torch's wheel triggers under
  deep repo paths, and falls back to a short per-user venv (`~/.usc-venv`)
  with clear instructions, instead of dying mid-install with WinError 206.
  A `--venv-dir` option overrides the location.

### Removed

- The monolithic `configs/user_config.yaml` starter (superseded by the
  per-mode templates).
- Dead nested/dotted-key override machinery in `load_config`: the schema is
  flat and the advertised `a.b=c` form never validated. Overrides are plain
  `key=value` (JSON lists/objects are parsed as values).

### Changed

- The thresholding stage hash now derives from `{threshold_method,
  threshold_value, score_smoothing}`. Previously it could embed a
  score-dependent resolved cutoff (making identical configs hash
  differently) and an irrelevant `carve_fraction` for non-fraction methods.
  Stage hashes change once across this version boundary.
- `threshold_method` in diagnostics reports `cutoff` where it previously
  reported `numeric`.

### Fixed

- **`setup_env.py` on current NVIDIA drivers**: the CUDA-to-wheel map ended
  at 12.x, so drivers reporting CUDA 13.x silently fell back to CPU-only
  PyTorch; CUDA >= 13 now maps to cu128 wheels. The script also installs
  the package editable (`pip install -e .[dev]`) as its docs always claimed,
  instead of a static site-packages copy that ignored source edits.
- **Session cache on CUDA machines with CPU sessions**: `get_active_session()`
  with no device preferred cuda-when-available, so a `device: cpu` run on a
  GPU machine silently lost all session caching; a single active session now
  wins regardless of device.
- **Matplotlib backend hijack**: `api_core._diagnostics` forced the Agg
  backend at import time, breaking inline plotting in any notebook that
  imports USC; Agg is now only the fallback when no backend was chosen yet.
- The Warp voxelizer parity test crashed on CUDA machines (`.numpy()` on a
  cuda tensor) before asserting anything; it is now device-aware and
  parametrized over both cpu and cuda, so the parity guarantee is actually
  exercised on GPUs.
- **CPU ray tracing accuracy and speed**: the CPU path now runs the same exact
  Warp DDA kernel as CUDA. The previous fixed-step marcher skipped up to ~37 %
  of the voxels traversed by oblique rays, systematically under-counting
  obstruction on CPU-only machines. Measured on the `full_blocks` example
  (daylight mode): preprocessing 101 s → 5.8 s (~17×), obstruction score mass
  +61 %. The fixed-step marcher remains as a fallback when Warp is missing and
  now warns that it is approximate.
- **`north_deg` convention**: USC documents `north_deg` as degrees *clockwise*
  from +Y, but Ladybug's `SkyMatrix`/`Sunpath` use *counterclockwise*. The
  angle is now negated at the Ladybug boundary, and `north_deg` is honored by
  the time-based mode (sun vectors) and the tilted-plane per-octant lookup,
  which previously ignored it. Runs with the default `north_deg: 0` are
  unaffected.
- **`apply_smoothing=True` meshing**: marching cubes now contours the
  continuous smoothed SDF (trimesh's `threshold` argument binarized the field,
  silently discarding the SDF smoothing), with correct voxel-center alignment
  (surfaces were previously shifted half a voxel) and outward face winding.
- **Violation counts on the fallback tracer**: `trace_multi_hit_grid` now
  guarantees each (ray, voxel) pair is reported once; the fixed-step marcher
  could report duplicates, inflating time-based / tilted-plane violation
  counts.
- **`--dry-run` grid estimate**: now mirrors the actual cubic grid built by
  `voxelize_mesh` (the estimate used per-axis dimensions and could badly
  under-report memory for elongated sites).
- **`threshold: numeric`** (a Grasshopper-side placeholder) is now rejected
  with a clear message at config load instead of crashing mid-pipeline.
- Missing input files (meshes, EPW) are validated at the start of
  preprocessing for fast, clear errors.

### Performance

Measured on a 306³ grid / 375k sample points (daylight mode, CPU): full
pipeline 112 s → ~34 s.  Except for the CPU trace dispatch, the gains
apply equally to CUDA machines.

- **Voxelization**: new Warp parity voxelizer: one BVH ray per grid
  column along each axis, majority vote across the three parities plus
  surface-hit marking (the same robustness idea as trimesh's
  orthographic fill).  Runs on CUDA or the Warp CPU device: 10–50×
  faster than the trimesh rasterize-and-fill path (6.4 s → 0.6 s at
  306³), which remains as the no-Warp fallback.  The occupancy is
  center-exact; differences vs trimesh are confined to the 1-voxel
  surface shell (regression-tested).
- **Fixed a half-voxel embed bug in the trimesh voxelization path**:
  `vox.transform[:3, 3]` is the CENTER of trimesh's voxel (0,0,0), not a
  grid corner, so the occupancy grid was systematically misplaced by
  half a voxel (rounding to a full voxel at ambiguous alignments) in all
  previous releases.
- **Smoothed exporting**: marching-cubes output is welded
  (`merge_vertices`) and then given the light cleanup instead of the
  full trimesh repair whenever it is watertight (it normally is); the
  full repair remains the fallback.  Welding first matters: MC emits
  zero-area faces where the iso crosses lattice nodes, and dropping
  them before welding would open pinholes.

- **`carve_fraction` thresholding**: the full `argsort` over the score
  volume (O(N log N); ~5 s at 306³ and minutes at 500³) is replaced by an
  exact two-pass weighted-histogram method (O(N)).  Mass accounting now
  accumulates in float64; the old float32 cumulative sum drifted
  measurably on large grids, so thresholds may shift very slightly (the
  new values are the more accurate ones).
- **Perona–Malik SDF smoothing** (`apply_smoothing=True` exports): the
  serial in-place stencil is now a parallel Jacobi stencil
  (numba `prange`, ~10× on a 306³ grid).  The Jacobi update scheme
  differs from the previous in-place sweep by a fraction of a voxel in
  SDF units; the volume-matched iso compensates globally.  The two
  distance transforms feeding the SDF also run concurrently (~1.9×).
- **CPU ray tracing**: Warp executes CPU launches single-threaded, so
  batches of the fused trace+score kernel are now dispatched from a small
  thread pool when running on CPU (kernels release the GIL; the shared
  score buffer stays correct via atomic adds).  Like on CUDA, atomic
  float addition makes scores reproducible only up to rounding noise.
  CUDA dispatch is unchanged.

### GPU-path efficiency

- The carvers no longer transfer the full ray set to host memory: at
  typical ray counts (~34M rays at 0.5 m sampling) this was ~0.8 GB of
  device→host copying per preprocessing run whose result was immediately
  discarded.  `carve_with_sky_patch_rays` and `carve_with_sun_rays` now
  take `return_rays=False` (opt-in) and return None ray fields otherwise.
- New fused DDA count kernel (`trace_and_count_dda`) for the binary
  carving modes (time-based, tilted_plane): counts hits atomically
  in-place, replacing the buffered trace path that guessed 20 hits/ray
  and re-traced every batch on overflow (2-3x wasted GPU work on scenes
  with long rays).  The buffered path remains for the no-Warp fallback.
  Equivalence with the buffered counts is regression-tested.
- `generate_sky_patch_rays` no longer materializes per-ray normals
  (an (R, 3) tensor nobody consumes, hundreds of MB of VRAM);
  pass `include_normals=True` to get them.

### Added

- **Kernel warmup**: Warp JIT-compiles kernels on first use (~3-10 s once
  per machine, per device, per code version; cached on disk afterwards).
  That one-time cost is now paid where waiting is expected instead of on
  the first carving run: `setup_env.py` precompiles at the end of
  installation, the daemon precompiles during startup (before READY), and
  a new `usc warmup [-d cpu|cuda]` command covers manual updates.
  Public API: `urbansolarcarver.raytracer.warmup_kernels(device)`.

### Robustness / code quality

- Defensive validation at stage boundaries: thresholding and exporting now
  verify that scores/mask files exist and match the grid shape recorded in
  the manifest, failing with a clear message instead of a cryptic
  numpy/torch error when artifacts from different runs are mixed.
- `load_mesh` rejects files with no triangle geometry at load time (was a
  cryptic empty-grid failure later).
- Preprocessing warns loudly when scores contain NaN/Inf (non-finite voxels
  are always carved, previously without any signal); the test suite now
  exercises the real check instead of a copy of its logic.
- `usc schema` (and any CLI output) no longer crashes with
  UnicodeEncodeError on legacy Windows code pages when piped.
- CLI overrides accept scientific notation (`-o score_smoothing=1e-1`);
  'inf'/'nan' spellings stay strings so validation rejects them clearly.
- `session_cache` warns once when a key template does not match the call
  signature (a silently dead cache was invisible before).
- Direct attribute access on the validated config everywhere (the
  `getattr(conf, "field", default)` pattern silently masked typos).
- Daemon RPC handlers consolidated into one dispatcher (was 4 copies of
  the same try/except/close block).
- Monolith decomposition: threshold resolution and score smoothing
  extracted from `thresholding()`; mode dispatch and the
  radiative-cooling guard extracted from `preprocessing()`; boundary-loop
  chaining extracted from `sample_planar_surface()`.
- Removed dead/speculative API: `carve_directional`, `voxelize_and_clean`,
  `mesh_from_voxels_select`, `CarverSession.get_kernel` (Warp caches its
  own compiled modules), plus unused parameters and unreachable branches.

### Changed

- The `diagnostics` config flag (previously unused) now gates the detailed
  score statistics (median, std, percentiles) in per-stage diagnostics JSON.
  Basic statistics (count, min, max, mean, nonzero counts) and timings are
  always written.
- Grasshopper components: the PLY preview loader no longer hangs Rhino on
  non-PLY export formats (obj/stl/glb are saved to disk with a canvas
  Remark instead); USC_Threshold warns instead of emitting the invalid
  bare `threshold=numeric` placeholder; USC_Session finds the backend
  Python in `.venv`/`venv` (Windows and POSIX layouts) or via an optional
  `python_path.txt` override, and no longer passes Windows-only process
  flags on macOS; USC_RunPipeline errors turn the component red like the
  stage components.
- `carve_above_columns` compiled with numba (was a pure-Python triple loop;
  large grids dropped from minutes to milliseconds).
- Diagnostic plots render synchronously; the previous "background thread" was
  started and immediately joined, adding overhead without concurrency.
- Documentation/docstring corrections (nonexistent config fields, stale
  return signatures, wrong output filename in CLI help).

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
