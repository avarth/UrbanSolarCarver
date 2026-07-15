# API Reference

Auto-generated from source docstrings. Every public function and class includes its full signature, parameters, return type, and description.

## Pipeline

The main entry points for running USC -- one-shot or stage-by-stage.

| Module | Contents |
|--------|----------|
| [Pipeline](pipeline.md) | `run_pipeline()`, `preprocessing()`, `thresholding()`, `exporting()`, result dataclasses |

## Geometry & Ray Tracing

Voxelization, surface sampling, ray casting, and mesh reconstruction.

| Module | Contents |
|--------|----------|
| [Carving](carving.md) | `carve_with_sun_rays()`, `carve_with_sky_patch_rays()`, `carve_with_planes()`, `validate_inputs()`, `load_meshes()`, `sample_period()` |
| [Ray Tracer](raytracer.md) | `trace_and_score_dda()` (fused DDA kernel), `generate_sky_patch_rays()`, `generate_sun_rays()`, `auto_batch_size()` |
| [Grid Operations](grid.md) | `voxelize()`, `sample_surface()`, `prune_voxels()`, `mesh_from_voxels()`, `mesh_from_voxels_smoothed()`, `polish_mesh_taubin()` |
| [I/O](io.md) | `load_mesh()`, `save_mesh()`, `save_pointcloud()`, diagnostic exporters (sun vectors, rays, bounding boxes) |

## Sky & Sun Models

Sky hemisphere weighting and solar position computation.

| Module | Contents |
|--------|----------|
| [Sky Patches](sky-patches.md) | Tregenza 145-patch geometry, `compute_EPW_based_weights()` (Perez / benefit / CIE), `compute_radiative_cooling_weights()` (Martin-Berdahl) |
| [Sun Vectors](sun.md) | `get_sun_vectors()` -- solar positions from EPW via Ladybug sunpath, altitude filtering |
| [Scoring](scoring.md) | `get_weights()` (mode dispatch), `normalize_scores()`, `otsu_threshold()`, `headtail_threshold()` |
| [Simulated Weights](simulated-weights.md) | Simulated benefit weights: `generate_simulated_weights()`, `ZoneParams`, `attribute_solar_gains()` (5R1C + perturbation), `expand_shoebox()`, artifact I/O |

## Configuration

YAML loading, validation, and schema definitions.

| Module | Contents |
|--------|----------|
| [Configuration](config.md) | `load_config()`, `parse_override_value()`, `UserConfig` (Pydantic model), manifest schemas |

## Infrastructure

GPU session management, Grasshopper daemon, and CLI.

| Module | Contents |
|--------|----------|
| [Session](session.md) | `CarverSession` -- CUDA context lifecycle, `session_cache` decorator for tensor memoisation |
| [Daemon](daemon.md) | Persistent localhost TCP server for Grasshopper RPC, authkey authentication |
| [CLI](cli.md) | `urbansolarcarver` command: `preprocessing`, `thresholding`, `exporting`, `schema`, `daemon start/stop` |
