# Pipeline

USC runs in three stages: preprocessing, thresholding, exporting, with massing as an optional fourth that reads the thresholding output like exporting. Each stage writes a manifest, last, after all its other outputs; the next stage reads it, so you can re-run thresholding with different parameters without recomputing scores. Every manifest after preprocessing records the hash of the manifest it was built from (`upstream_hash`), and a stage refuses an upstream that has changed since (`UpstreamMismatchError`). A stage first deletes the manifest and the outputs of its previous run in its folder, so a failed run leaves no manifest.

`run_pipeline()` chains all three stages in one call. For finer control, call each stage individually.

```python
from urbansolarcarver import load_config, run_pipeline

# One-shot
result = run_pipeline(load_config("config.yaml"), out_dir="outputs")

# Decomposed
from urbansolarcarver import preprocessing, thresholding, exporting
from pathlib import Path

cfg = load_config("config.yaml")
pre  = preprocessing(cfg, Path("outputs/preprocessing"))
thr  = thresholding(pre, cfg, Path("outputs/thresholding"))
exp  = exporting(thr, cfg, Path("outputs/exporting"))
```

## run_pipeline

::: urbansolarcarver.api
    options:
      members: [run_pipeline]

## Preprocessing

Voxelizes the max volume, samples the test surfaces, generates rays toward sky patches (or sun positions, or the tilted-plane direction), traces them through the voxel grid, and writes per-voxel obstruction scores to `scores.npy`.

::: urbansolarcarver.api_core.preprocessing
    options:
      members: [preprocessing, PreprocessingResult]

## Thresholding

Converts the score array into a binary carving mask: optional score smoothing, then `carve_fraction`, head/tail breaks, or a numeric cutoff over the occupied voxels, with `carve_above` applied through `carving.carve_above_scores` (the cutoff at which carve_above removes each voxel, so that `carve_fraction` counts what carve_above removes), then the slope limit (`max_slope_deg`, 75 degrees for the weighted modes; `carving.limit_column_slope`). Writes `mask.npy`; the diagnostics record `max_slope_deg`, `slope_limit_extra_voxels_removed` and `obstruction_fraction_carved_by_slope_limit`.

::: urbansolarcarver.api_core.thresholding
    options:
      members: [thresholding, ThresholdingResult]

## Exporting

Reconstructs a triangle mesh from the binary mask, either as cubic voxel faces or as SDF-smoothed marching cubes with Taubin polishing. Writes `export.<format>` (`ply` by default, set by `final_mesh_format`), `manifest.json` and diagnostics, and the run's `run_report.md`. The report has a Massing section too when the run's massing folder was built from the same thresholding run.

::: urbansolarcarver.api_core.exporting
    options:
      members: [exporting, ExportingResult]

## Massing

Builds stacked floor plates that follow the footprint from the carving mask (see [Floor-plate massing](../massing.md)). Writes `plates.json`, `plates.obj`, `manifest.json` and diagnostics, and adds a Massing section to the run report. Returns a `MassingResult` with the paths, the floor areas per floor and in total, and the number of plates. The geometry is in `urbansolarcarver.floor_plates`.

::: urbansolarcarver.api_core.massing
    options:
      members: [massing, MassingResult]
