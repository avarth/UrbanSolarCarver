# Project Map

Overview of every file and directory in the repository.

## Repository root

```
UrbanSolarCarver/
├── src/urbansolarcarver/   Core Python package
├── configs/                YAML config templates (one per mode + reference)
├── examples/               Example data, configs, and Jupyter notebook tutorials
├── tests/                  Pytest suite
├── benchmarks/             Performance benchmarking scripts
├── grasshopper/            Rhino Grasshopper plugin
├── docs/                   MkDocs documentation source
├── pyproject.toml          Package metadata and dependencies
├── setup_env.py            Automated environment setup (GPU detection)
├── mkdocs.yml              Documentation site configuration
├── CHANGELOG.md            Release history
├── CONTRIBUTING.md         Contribution guidelines
├── LICENSE                 AGPL-3.0
└── README.md               Project landing page
```

## Source code (`src/urbansolarcarver/`)

### Pipeline orchestration

| File | Purpose |
|------|---------|
| `__init__.py` | Package entry point. Re-exports the public API from `api.py` so that `from urbansolarcarver import run_pipeline, load_config` works. |
| `api.py` | Public facade. Defines `run_pipeline()` (one-shot full pipeline) and re-exports `preprocessing()`, `thresholding()`, `exporting()`, and `load_config()`. All user-facing imports resolve here. |
| `api_core/__init__.py` | Wires up the three stage modules and their result types into a single importable sub-package. |
| `api_core/preprocessing.py` | **Stage 1.** Voxelizes the max-volume mesh into a dense 3D boolean grid, samples test surfaces into evenly-spaced points with outward normals, generates rays toward sky patches (or sun vectors depending on mode), traces them through the grid via the DDA kernel, and writes the resulting per-voxel obstruction scores to `scores.npy`. Also exports diagnostic artefacts (histograms, sky-patch weight plots, timing JSON) when enabled. |
| `api_core/thresholding.py` | **Stage 2.** Loads `scores.npy` from Stage 1, optionally applies Gaussian score smoothing, then applies the selected thresholding strategy (head-tail breaks, carve_fraction, or a numeric value) on the raw scores to produce a binary carving mask, and writes `mask.npy`. Can be re-run with different threshold parameters without re-computing scores. |
| `api_core/exporting.py` | **Stage 3.** Loads the binary mask from Stage 2, prunes small disconnected voxel clusters, reconstructs a triangle mesh (either cubic voxel faces or SDF-smoothed marching cubes with Taubin polishing), and writes the final `export.<format>` mesh. |
| `api_core/_util.py` | Internal helpers shared across stages: device resolution (`"auto"` → `"cuda"` or `"cpu"`), output-directory creation, diagnostic file writing (JSON, histograms, sky-patch plots), config hashing for cache invalidation, and score statistics. |

### Geometry

| File | Purpose |
|------|---------|
| `grid.py` | Core geometry operations. **Voxelization**: converts a watertight mesh into a dense 3D boolean array at the configured `voxel_size` using Trimesh's voxelization with surface-normal ray tests. **Surface sampling**: discretizes each planar test-surface face into a regular grid of points with outward-facing normals, projecting from 3D into the face's local 2D plane and using Shapely `contains_xy` for in-polygon testing. **Pruning**: removes small disconnected voxel clusters via `scipy.ndimage.label` connected-component analysis. **Mesh reconstruction**: converts carved voxel masks back to triangle meshes -- either as raw cubic voxel faces or via signed-distance-field smoothing, marching cubes, and Taubin iterative polishing. |
| `io.py` | All file I/O. **Mesh loading**: reads PLY files via Trimesh, ensures consistent face-normal orientation with `trimesh.repair.fix_normals`. **Mesh saving**: writes PLY. **Diagnostic exports**: sun direction vectors as OBJ line segments for visual inspection, arbitrary ray bundles as OBJ, surface sample points with normal vectors as PLY + OBJ, and axis-aligned bounding-box meshes for both the input mesh and the voxel grid. These diagnostic files can be opened in Rhino or any 3D viewer to visually verify the pipeline's intermediate results. |

### Carving engines

| File | Purpose |
|------|---------|
| `carving.py` | Implements the three carving strategies as top-level functions. **`carve_with_sun_rays`**: used by `time-based` mode -- generates rays from test-surface points toward actual sun positions at specific dates/times, traces them through the voxel grid, and marks intersected voxels for removal. **`carve_with_sky_patch_rays`**: used by `irradiance`, `benefit`, `daylight`, and `radiative_cooling` modes -- generates rays toward the 145 Tregenza sky patches, weights each ray by the patch's mode-specific value, and accumulates weighted scores per voxel. **`carve_with_planes`**: used by `tilted_plane` mode -- removes all voxels above a tilted cut plane at a fixed angle from each test surface, with per-octant angle support. Also contains `validate_inputs()` (checks file paths, mode validity), `load_meshes()` (loads max volume + test surfaces), and `sample_period()` (builds the analysis date/time list via Ladybug's `AnalysisPeriod`). |
| `raytracer.py` | The computational core. **`trace_and_score_dda`**: a fused Digital Differential Analyser (DDA) kernel implemented in NVIDIA Warp that marches each ray through the voxel grid cell-by-cell, incrementing each traversed voxel's score by the ray's weight. Runs on GPU (Warp CUDA) or CPU (Warp CPU fallback). **`generate_sky_patch_rays`** / **`generate_sun_rays`**: expand the Cartesian product of sample points × direction vectors into flat arrays of ray origins and directions ready for batch tracing. **`auto_batch_size`**: estimates the largest ray batch that fits in available GPU VRAM given the grid resolution, to prevent out-of-memory errors on large scenes. The batch loop is the primary computational bottleneck. |

### Sky and sun models

| File | Purpose |
|------|---------|
| `sky_patches.py` | Implements the Tregenza hemisphere subdivision (145 patches) used by all weighted carving modes. **`fetch_tregenza_patch_directions`**: returns the 145 unit direction vectors. **`fetch_tregenza_patch_solid_angles`**: returns the solid angle (in steradians) subtended by each patch. **`compute_EPW_based_weights`**: reads hourly direct-normal and diffuse-horizontal irradiance from an EPW file, applies the Perez all-weather sky model to distribute radiation onto each patch, and aggregates over the analysis period. Supports filtering by heating-benefit hours (only hours when outdoor temperature falls below a balance-point temperature contribute) and CIE standard overcast luminance (cosine-weighted zenith-brightest distribution, diffuse only). **`compute_radiative_cooling_weights`**: models the long-wave radiative cooling potential of each sky patch using the Martin-Berdahl clear-sky atmospheric emissivity model combined with Bliss angular attenuation -- patches near the zenith have higher cooling potential than those near the horizon. |
| `sun.py` | Computes solar position vectors for specific dates and times. **`get_sun_vectors`**: uses Ladybug's sunpath model with location data from the EPW header to return unit direction vectors pointing toward the sun for each hour in the analysis period, filtering out hours below the `min_altitude` threshold (when the sun is too low for meaningful contribution). **`warm_up`**: pre-loads EPW weather data and sunpath object into memory, called by the daemon on startup to eliminate first-call latency. |
| `scoring.py` | Bridges between raw per-voxel hit counts and the binary carving decision. **`get_weights`**: dispatches to the correct sky-patch weighting function based on the selected mode (Perez irradiance, heating benefit, CIE daylight, or radiative cooling). **`normalize_scores`**: rescales raw scores to [0, 1] using min-max normalization. **Thresholding algorithms**: `otsu_threshold` (minimizes intra-class variance -- good general default), `headtail_threshold` (iterative head-tail breaks for heavy-tailed distributions where most voxels have low scores), and `carve_fraction` (removes a fixed percentage of the scored volume, controlled by the `carve_fraction` config parameter). |

### Configuration

| File | Purpose |
|------|---------|
| `load_config.py` | Reads a YAML configuration file and returns a validated `UserConfig` object. **`load_config`**: the main entry point -- loads YAML, applies CLI overrides (`-o key=value` parsed via `parse_override_value`), recursively merges nested dictionaries, and passes the result to Pydantic for validation. **`parse_override_value`**: converts CLI override strings into Python types (numbers, booleans, lists). **`assign_override_path`**: sets a nested key in-place using a dot-separated path (e.g., `"threshold"` → `config["threshold"]`). |
| `pydantic_schemas.py` | All data schemas. **`UserConfig`**: the main Pydantic v2 model defining every pipeline parameter with type annotations, default values, value-range validators (e.g., `voxel_size` must be 0.01-100), and informative error messages. Emits `UrbanSolarCarverWarning` when values are auto-clamped. **`PreprocessingManifest`** / **`ThresholdingManifest`** / **`ExportingManifest`**: schemas for the JSON manifests written by each pipeline stage, enabling stage re-entry (e.g., re-run thresholding from a previous preprocessing run). |

### Infrastructure

| File | Purpose |
|------|---------|
| `session.py` | GPU context lifecycle management. **`CarverSession`**: a long-lived object that initialises the CUDA context and Warp runtime once, then keeps them alive across multiple pipeline calls -- avoiding the ~2 s cold-start penalty that would otherwise occur on each invocation. Maintains an internal tensor cache for expensive computations (e.g., Tregenza patch directions, compiled Warp kernels). **`get_active_session`**: retrieves the current session for a given device, or `None` if none exists. **`session_cache`**: a decorator that memoises a function's return value in the active session's tensor cache, keyed by a template string -- so `fetch_tregenza_patch_directions` is computed once and reused across all stages and pipeline runs within the same session. |
| `daemon.py` | Persistent background process for Grasshopper and other external clients. **`serve`**: starts a TCP listener on `127.0.0.1` (localhost only, not network-accessible) using Python's `multiprocessing.connection`, authenticated with a random authkey written to `.daemon_authkey`. Creates a `CarverSession` on startup and keeps it alive for the daemon's lifetime, accepting RPC-style calls from Grasshopper components. Started/stopped via CLI (`urbansolarcarver daemon start/stop`) or from Grasshopper using the `USC_Session` component. |
| `carver_cli.py` | Command-line interface built with Typer. Exposes the three pipeline stages as subcommands (`preprocessing`, `thresholding`, `exporting`), each accepting a config file (`-c`) and optional overrides (`-o`). **`schema`**: prints the full `UserConfig` JSON schema for reference. **`daemon start`** / **`daemon stop`**: manage the background daemon process. The CLI is the entry point registered in `pyproject.toml` as `urbansolarcarver`. |

## Grasshopper plugin (`grasshopper/`)

```
grasshopper/
├── USC_GHplugin/       15 .ghuser components (drag into GH User Objects)
├── components/         Python source for each component
└── icons/              24×24 component icons
```

Build and install scripts (`_build_ghx.py`, `_install_components.py`) are local-only and not included in the repository.

## Configuration templates (`configs/`)

One YAML template per mode, plus a reference file documenting every parameter:

```
configs/
├── REFERENCE_all_options.yaml   Every parameter with descriptions and defaults
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
├── conftest.py         Shared fixtures: temporary directories, minimal YAML configs,
│                       procedurally-generated watertight box meshes, mock test surfaces
├── test_grid.py        Voxelization round-trip, surface sampling point counts,
│                       connected-component pruning, mesh reconstruction
├── test_modes.py       Smoke tests for all 6 carving modes -- verifies each mode
│                       produces non-empty scores and a valid carved mesh
├── test_pipeline.py    End-to-end pipeline execution, stage re-entry from manifests,
│                       run_pipeline convenience wrapper, CLI schema command
├── test_schemas.py     Pydantic validation: required fields, value bounds, type coercion,
│                       env-var fallbacks, auto-clamping warnings
└── test_scoring.py     Head-tail breaks convergence, threshold strategy selection,
│                       min-max normalization bounds, weight dispatch per mode
```
