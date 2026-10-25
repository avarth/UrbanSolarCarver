# API Reference

Generated from the source docstrings: each documented public function and class is shown with its signature, parameters, return type, and description.

## Pipeline

The main entry points for running USC, in one call or stage by stage. Several criteria carved in sequence (`run_chain`, `thresholding(..., after=)`, `load_chain`) are described in [Criteria: chained carvings](../criteria.md).

| Module | Contents |
|--------|----------|
| [Pipeline](pipeline.md) | `run_pipeline()` (`produce`, `start_from`, `context`), `PipelineResult`, `run_chain()`, `ChainResult`, `stages_to_rerun()`, `preprocessing()`, `thresholding()`, `exporting()`, `massing()`, result dataclasses, `RunContext` and issues, the error classes |

## Geometry & Ray Tracing

Voxelization, surface sampling, ray casting, and mesh reconstruction.

| Module | Contents |
|--------|----------|
| [Carving](carving.md) | `carve_with_sun_rays()`, `carve_with_sky_patch_rays()`, `carve_with_planes()` (carving); `carve_above_columns()`, `carve_above_scores()`, `limit_column_slope()` (column_postprocessing) |
| [Ray Tracing](ray-tracing.md) | `trace_and_score_dda()` / `trace_and_count_dda()` (DDA kernels), `generate_sky_patch_rays()`, `generate_sun_rays()`, `auto_batch_size()` (ray_tracing); `dda_backend_available()`, `warmup_kernels()` (warp_kernels) |
| [Geometry](geometry.md) | `sample_surface()` (surface_sampling), `voxelize()` (voxelization), `finalize_mesh()`, `prune_voxels()`, `mesh_from_voxels()`, `mesh_from_voxels_smoothed()`, `polish_mesh_taubin()` (meshing) |
| [I/O](io.md) | `load_mesh()`, `save_mesh()`, `validate_inputs()`, `load_meshes()` |

## Sky & Sun Models

Sky hemisphere weighting and solar position computation.

| Module | Contents |
|--------|----------|
| [Sky Patches](sky-patches.md) | Tregenza 145-patch geometry, `compute_EPW_based_weights()` (Perez / benefit / CIE), `compute_radiative_cooling_weights()` (Martin-Berdahl) |
| [Sun Vectors](sun.md) | `get_sun_vectors()`: solar positions from the EPW location via Ladybug's sunpath, altitude filtering |
| [Scoring](scoring.md) | `get_weights()` (mode dispatch), `carve_fraction_threshold()`, `headtail_threshold()` |
| [Simulated Weights](simulated-weights.md) | Simulated benefit weights: `generate_simulated_weights()`, `ZoneParams`, `attribute_solar_gains()` (5R1C + perturbation), `expand_shoebox()`, artifact I/O |

## Configuration

YAML loading, validation, and schema definitions.

| Module | Contents |
|--------|----------|
| [Configuration](config.md) | `load_config()`, `build_config()`, `parse_override_value()`, `load_chain()`, `ChainConfig`, `Criterion`, `is_chain_file()`, `UserConfig` (Pydantic model), `ThresholdSpec`, manifest schemas, mode starting values |

## Infrastructure

Compute sessions, the Grasshopper daemon, and the CLI.

| Module | Contents |
|--------|----------|
| [Session](session.md) | `CarverSession` (CUDA context and value cache), `session_cache` decorator |
| [Daemon](daemon.md) | Persistent localhost server for Grasshopper requests, authkey authentication, the `run` command |
| [CLI](cli.md) | `urbansolarcarver` / `usc` command: `run` (`--produce`, `--start-from`), `preprocessing`, `thresholding`, `exporting`, `validate`, `schema`, `warmup`, `simulate-weights`, `archetype`, `daemon start/stop/status` |
