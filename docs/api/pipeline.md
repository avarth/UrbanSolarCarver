# Pipeline

USC runs in three stages: preprocessing, thresholding, exporting. Preprocessing and thresholding each write a manifest that the next stage reads, so you can re-run thresholding with different parameters without recomputing scores.

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

Voxelizes the max volume, samples the test surfaces, generates rays toward sky patches (or sun positions, or the tilted-plane direction), traces them through the voxel grid, and writes per-voxel obstruction scores to `scores.npy`. Weighted modes also trace the rays one sky patch at a time and write `patch_rank.npy` (per voxel, the rank of the highest-weight patch it blocks), referenced by the manifest field `patch_rank_path`; this makes their preprocessing somewhat slower.

::: urbansolarcarver.api_core.preprocessing
    options:
      members: [preprocessing, PreprocessingResult]

## Thresholding

Converts the preprocessing output into a binary carving mask, then applies `carve_above`, and writes `mask.npy`. With `protect_share` (the default for weighted modes), the share is turned into a number of protected sky patches and every voxel whose patch rank is below it is carved; the scores are not used, so re-thresholding stays instant and score smoothing does not apply. The diagnostics record `protected_patch_count`, `protected_patches` and `protected_weight_share`. With `carve_fraction`, head/tail breaks, or a numeric cutoff, optional score smoothing is applied and the cutoff is taken over the occupied voxels.

::: urbansolarcarver.api_core.thresholding
    options:
      members: [thresholding, ThresholdingResult]

## Exporting

Reconstructs a triangle mesh from the binary mask, either as cubic voxel faces or as SDF-smoothed marching cubes with Taubin polishing. Writes `export.<format>` (`ply` by default, set by `final_mesh_format`) and the run's `run_report.md`.

::: urbansolarcarver.api_core.exporting
    options:
      members: [exporting, ExportingResult]
