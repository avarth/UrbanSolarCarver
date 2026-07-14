# Quick Start

## Python API

Run the full pipeline in one call:

```python
from urbansolarcarver import load_config, run_pipeline

cfg = load_config("config.yaml")
result = run_pipeline(cfg, out_dir="./outputs")
print(f"Carved mesh: {result.export_path}")
```

Or run stages individually for finer control:

```python
from urbansolarcarver import load_config, preprocessing, thresholding, exporting
from pathlib import Path

cfg = load_config("config.yaml")

# Stage 1: compute per-voxel carving scores
pre = preprocessing(cfg, Path("outputs/preprocessing"))

# Stage 2: apply threshold to create binary mask
thr = thresholding(pre, cfg, Path("outputs/thresholding"))

# Stage 3: reconstruct mesh from mask
exp = exporting(thr, cfg, Path("outputs/exporting"))
```

The decomposed workflow lets you re-run thresholding with different parameters without recomputing scores.

## CLI

```bash
# Run stages sequentially
urbansolarcarver preprocessing -c config.yaml
urbansolarcarver thresholding -c config.yaml -f outputs/preprocessing/manifest.json
urbansolarcarver exporting -c config.yaml -f outputs/thresholding/manifest.json

# Override config values on the fly
urbansolarcarver preprocessing -c config.yaml -o voxel_size=0.5 -o mode=irradiance

# View all config options
urbansolarcarver schema
```

## Jupyter Notebooks

Tutorial notebooks are in `examples/`:

1. **Quick start** -- basic pipeline walkthrough
2. **Solar envelope** -- time-based solar envelope
3. **Tilted plane & daylight** -- geometric and CIE overcast envelopes
4. **Advanced** -- chaining modes, post-processing, decomposed pipeline
5. **Benefit with simulated weights** -- building-simulation-driven hour weighting (ISO 13790 5R1C)

## Input Requirements

- **Max volume mesh**: watertight PLY representing the theoretical maximum buildable volume.
- **Test surface mesh**: PLY of planar faces whose solar/daylight access is to be protected.
- **EPW weather file**: hourly climate data for the site location (required for all modes except `tilted_plane`).
- All meshes must share the same coordinate system and units (meters recommended).
