# Changelog

All notable changes to Urban Solar Carver are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Solar-usefulness generator (simulated benefit weights)** — `usc usefulness` and the
  `urbansolarcarver.usefulness` module: an ISO 13790 Annex C simple hourly
  ("5R1C") thermal model plus batched central-difference perturbation,
  producing hourly *marginal* solar usefulness — `benefit[t]` (fraction of
  a marginal joule of solar gain that offsets heating over the year) and
  `harm[t]` (fraction that becomes cooling load) — written to a
  `solar_usefulness.json` artifact with full provenance metadata. Inputs:
  one EPW plus ~10 archetype parameters (`configs/archetype_example.yaml`;
  neutral values, no national defaults). The engine is validated against
  ETH's RC_BuildingSimulator on three archetypes under the bundled Golden
  TMY3 weather (annual demands and hourly node states; driving arrays
  stored verbatim in `tests/data/`), plus steady-state closure against an
  independent network reduction. Design, tier ladder, and declared
  limitations: `design/solar-usefulness.md`.
- **`usefulness_path`** (benefit mode): consume a solar-usefulness artifact
  in place of the balance-point hour filter — each hour's DNI/DHI is scaled
  by `benefit[t]` before the cumulative sky matrix (the balance filter is
  the binary special case of this mechanism), and `include_harm: true`
  subtracts the `harm[t]`-scaled matrix clipped at zero. Analysis-period
  hours outside the period are zero-weighted. `balance_temperature`/
  `balance_offset` are unused (warns if customized); artifact provenance is
  recorded in preprocessing diagnostics and the patch-weight cache keys on
  artifact content. Occupancy: archetypes accept a flat internal-gains
  value or a 24-value daily profile.
- **Shoebox archetype shorthand**: instead of explicit areas, an archetype
  may give `width`/`length`/`height` plus per-facade `wwr` (window-to-wall
  ratio), `g_value`, and optional `orientation` — floor area, volume,
  per-facade window areas, `area_window`, and `area_opaque` (opaque walls +
  roof) are derived. `configs/archetype_example.yaml` shows both forms.
- **Weights preview**: `usc usefulness` / `generate_usefulness` write a
  `.png` companion next to the artifact — benefit and harm as day x hour
  heatmaps — so the schedule can be inspected without writing code.
- **Sky-weight comparison in diagnostics**: a benefit run that consumes a
  usefulness artifact (with `diagnostic_plots: true`) also records a
  difference dome versus the simple balance-point rule for the same config
  (`sky_patch_comparison_image` + redistribution stats in
  `diagnostic.json`).
- **Tutorial 5** (`examples/5_benefit_5r1c.ipynb`): simulated benefit
  weights end-to-end — archetype, weights generation and inspection,
  simple-vs-simulated carve comparison, harm channel, provenance.
- The sample Golden CO TMY3 EPW is now actually committed
  (`.gitignore` exception) — the tutorials and EPW-dependent tests run
  out of the box as documented.

### Changed

- **Benefit mode now implements its documented formula exactly (by
  default)**: patch weights are a plain cumulative irradiance matrix over
  the hours below `balance_temperature − balance_offset` (Heaviside filter
  on EPW dry-bulb). Previously the weights were always Ladybug's signed
  benefit−harm net clipped at zero, which silently let hot-hour radiation
  erode winter weights and made results depend on whether the analysis
  period included summer. A full-year analysis period is now safe and
  natural — the balance filter selects the beneficial hours by itself.
  The composite remains available as a declared, opt-in experiment:
  `include_harm: true` subtracts hot-hour radiation per patch (clipped at
  zero, dead-band hours count for neither side), with its period-dependence
  documented. Shading value is deliberately never a carving force — with
  signed retention, every voxel along a hot-hour ray earns shade credit, so
  the "optimal" envelope keeps whole sun-path prisms (cave-like volumes).
- `balance_temperature` default changed from 20 to **15 °C** (Ladybug's
  default; typical range ~12 commercial to ~18 residential, higher for
  older poorly insulated stock). Derive project-specific values via the
  Honeybee/E+ balance-point workflow.
- `balance_offset` now validates `>= 0` (a negative offset silently inverted
  the dead-band into inverted hour classification).
- User-facing terminology for the two benefit weightings: "simple weights"
  (balance-point rule) vs "simulated weights" (5R1C hourly simulation);
  the internal "Tier 1.5" label no longer appears in docs, CLI, or configs.
  `generate_tier15` is renamed `generate_usefulness` (old name kept as a
  compatible alias).
- Benefit mode warns loudly and returns all-zero weights when the analysis
  period contains no beneficial hours (previously this fell through toward a
  degenerate carve with only a generic downstream warning; an empty hour
  list must also never reach Ladybug, which treats it as "whole year").

### Removed

- **`ground_reflectance` config field** — it never affected results: Ladybug
  SkyMatrix only stores it as metadata for RadiationStudy, which USC does
  not run, and USC's ray casting targets sky patches only. Configs carrying
  the key now fail validation with a clear message; remove the line. The
  USC_RaySettings Grasshopper component no longer emits it (old canvases
  keep the input; it is ignored).

### Added

- **`edge_taper` design constraint** (all weighted sky-patch modes): sample
  points within `edge_taper` meters of their test-surface component's
  boundary count proportionally less (linear ramp), so perimeter/corner
  points no longer force carving of directly adjacent volume — replacing the
  manual practice of offsetting test-surface edges. Distances are exact 2D
  distances to the welded component outline (exterior and holes), so
  exploded-but-coincident panels (e.g. street networks) have no phantom
  seams. Zero-weight rays are dropped before tracing. Components narrower
  than ~2× the taper warn loudly and per-component stats are recorded in the
  preprocessing diagnostics — the taper never silently excludes geometry.
  Ignored (with a warning) by the binary violation-count modes.
- **`min_sky_elevation_deg` protection cone** (radiative_cooling): sky
  patches below the declared elevation are excluded from the cooling weights
  (renormalized) — a declared design constraint analogous to
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
  kind — misuse fails at load with a precise message. All previous config
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
  with clear instructions — instead of dying mid-install with WinError 206.
  A `--venv-dir` option overrides the location.

### Removed

- The monolithic `configs/user_config.yaml` starter (superseded by the
  per-mode templates).
- Dead nested/dotted-key override machinery in `load_config` — the schema is
  flat and the advertised `a.b=c` form never validated. Overrides are plain
  `key=value` (JSON lists/objects are parsed as values).

### Changed

- The thresholding stage hash now derives from `{threshold_method,
  threshold_value, score_smoothing}` — previously it could embed a
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

- **Voxelization**: new Warp parity voxelizer — one BVH ray per grid
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
  accumulates in float64 — the old float32 cumulative sum drifted
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
  (an (R, 3) tensor nobody consumes — hundreds of MB of VRAM);
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
