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

## Citation

USC is described in a paper presented at ReSBE 2026 and published open access. If you use USC, please cite:

> Vartholomaios, A. (2026). Urban Solar Carver: A GPU-Accelerated Framework for Solar-Driven Urban Form Finding. In: Bragança, L., Tsikaloudaki, K., Giarma, C., Mateus, R., Kontoleon, K., Askar, R., Salles, A. & Cervantes, C. (Eds.), *ReShaping the Built Environment through Sustainability and Circularity: Proceedings of ReSBE 2026 International Conference, Volume 1*. Lecture Notes in Civil Engineering, vol. 905. Springer, pp. 600-607. [https://doi.org/10.1007/978-3-032-34930-9_70](https://doi.org/10.1007/978-3-032-34930-9_70)

[Download the paper (PDF)](publications/Vartholomaios_2026_ReSBE_Urban_Solar_Carver.pdf). The paper is licensed under [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/), not under the AGPL-3.0 that covers the code. To cite the software itself, use the [Zenodo DOI](https://doi.org/10.5281/zenodo.19443737); machine-readable metadata is in [`CITATION.cff`](https://github.com/avarth/UrbanSolarCarver/blob/main/CITATION.cff).
