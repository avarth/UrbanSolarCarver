# Urban Solar Carver

GPU-accelerated generation of maximum developable building volumes that protect solar and daylight access in urban environments.

USC works by subtraction: it starts from a theoretical maximum volume, casts rays from the protected surfaces toward the sky, and removes the voxels that obstruct solar or daylight access beyond a configurable threshold.

![USC pipeline overview](assets/explanation.png)

## Overview

- **6 carving modes** covering solar access, passive heating, daylighting, and radiative cooling
- **3-stage pipeline** (preprocessing, thresholding, exporting); each stage can be re-run on its own
- **GPU-accelerated** ray tracing via NVIDIA Warp (DDA kernel), with CPU fallback
- **Grasshopper plugin** (27 components) for Rhino 3D integration
- **Python API**, **CLI**, and **Jupyter notebooks**

## Pipeline

```
Input (PLY meshes, EPW weather, YAML config)
    |
    v
Preprocessing ── scores.npy, voxel_grid.npy
    |
    v
Thresholding ─── mask.npy (binary carving mask)
    |
    v
Exporting ────── export.ply (or .obj/.stl/.glb, set by final_mesh_format)
```

Each stage reads the previous stage's manifest, so you can re-run thresholding with different parameters without re-computing scores.

## Documentation

- **Getting Started**
    - [Installation](getting-started/installation.md): setup via `setup_env.py` or manual install
    - [Quick Start](getting-started/quick-start.md): Python API, CLI, and notebook tutorials
    - [Configuration](getting-started/configuration.md): YAML config reference with per-mode examples
- **[Carving Modes](modes.md)**: the 6 analysis modes (tilted_plane, time-based, irradiance, benefit, daylight, radiative_cooling)
- **[Simulated Weights](simulated-weights.md)**: the building-simulation engine behind benefit mode's simulated weights
- **[Grasshopper Plugin](grasshopper.md)**: Rhino 3D integration, component list, daemon setup
- **[Project Map](project-map.md)**: every file and directory in the repository
- **[API Reference](api/index.md)**: function signatures, parameters, and return types (generated from docstrings)
- **[Changelog](https://github.com/avarth/UrbanSolarCarver/blob/main/CHANGELOG.md)**
