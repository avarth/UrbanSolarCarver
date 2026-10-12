# API Reference

Generated from the source docstrings: each documented public function and class is shown with its signature, parameters, return type, and description.

## Pipeline

The main entry points for running USC, in one call or stage by stage.

| Module | Contents |
|--------|----------|
| [Pipeline](pipeline.md) | `run_pipeline()`, `preprocessing()`, `thresholding()`, `exporting()`, result dataclasses |

## Geometry & Ray Tracing

Voxelization, surface sampling, ray casting, and mesh reconstruction.

| Module | Contents |
|--------|----------|
| [Carving](carving.md) | `carve_with_sun_rays()`, `carve_with_sky_patch_rays()`, `carve_with_planes()`, `carve_above_columns()`, `validate_inputs()`, `load_meshes()`, `sample_period()` |
| [Ray Tracer](raytracer.md) | `trace_and_score_dda()` / `trace_and_count_dda()` (DDA kernels), `generate_sky_patch_rays()`, `generate_sun_rays()`, `voxelize_solid_warp()`, `auto_batch_size()`, `warmup_kernels()` |
| [Grid Operations](grid.md) | `voxelize()`, `sample_surface()`, `prune_voxels()`, `mesh_from_voxels()`, `mesh_from_voxels_smoothed()`, `polish_mesh_taubin()` |
| [I/O](io.md) | `load_mesh()`, `save_mesh()` |

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
| [Configuration](config.md) | `load_config()`, `parse_override_value()`, `UserConfig` (Pydantic model), `ThresholdSpec`, manifest schemas |

## Infrastructure

Compute sessions, the Grasshopper daemon, and the CLI.

| Module | Contents |
|--------|----------|
| [Session](session.md) | `CarverSession` (CUDA context and value cache), `session_cache` decorator |
| [Daemon](daemon.md) | Persistent localhost server for Grasshopper requests, authkey authentication |
| [CLI](cli.md) | `urbansolarcarver` / `usc` command: `run`, `preprocessing`, `thresholding`, `exporting`, `validate`, `schema`, `warmup`, `simulate-weights`, `archetype`, `daemon start/stop/status` |
