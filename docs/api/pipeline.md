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

Voxelizes the max volume, samples the test surfaces, generates rays toward sky patches (or sun positions, or the tilted-plane direction), traces them through the voxel grid, and writes per-voxel obstruction scores to `scores.npy`. Weighted modes also rank the obstructed rays by sky weight per removed voxel and write `recovery_rays.npz` (per-voxel ray ranks `voxel_rank`; the obstructed rays in clearing order as `point_idx`, `patch_idx` and `weight`; and the traced `points`, `normals`, `min_corner`, `extent` and `resolution`), referenced by the manifest field `recovery_rays_path` and read by `recovered_sky`. They also trace the rays one sky patch at a time and write `patch_rank.npy` (per voxel, the rank of the highest-weight patch it blocks), referenced by the manifest field `patch_rank_path` and read by `protect_share`. These passes make their preprocessing slower: on the ReSBE test blocks at 0.5 m voxels, the ray ranking for `recovered_sky` raised it from about 2.1 s to 2.6 s.

::: urbansolarcarver.api_core.preprocessing
    options:
      members: [preprocessing, PreprocessingResult]

## Thresholding

Converts the preprocessing output into a binary carving mask, then applies `carve_above` and the slope limit, and writes `mask.npy`. With `recovered_sky` (the default for weighted modes), the voxel ranks in `recovery_rays.npz` give the cut at which each voxel is removed (with `carve_above`), the obstructed rays are traced once more to find the cut from which each one is clear, and the smallest cut that recovers the requested share of the ray weight is kept; the scores are not used, no smoothing or slope limit is applied, and the diagnostics record `recovered_sky_actual`, `rays_obstructed`, `rays_recovered` and `recovery_cut`. This takes about 0.5 s on a GPU on the ReSBE test blocks at 0.5 m voxels. With `carve_fraction`, head/tail breaks, or a numeric cutoff, optional score smoothing is applied and the cutoff is taken over the occupied voxels; the slope limit (`max_slope_deg`, 75 degrees unless set) then cuts columns that rise too steeply above their neighbours, and the diagnostics record `slope_limit_extra_voxels_removed`. With `protect_share`, the share is turned into a number of protected sky patches and every voxel whose patch rank is below it is carved; the scores are not used, and the diagnostics record `protected_patch_count`, `protected_patches` and `protected_weight_share`.

::: urbansolarcarver.api_core.thresholding
    options:
      members: [thresholding, ThresholdingResult]

## Exporting

Reconstructs a triangle mesh from the binary mask, either as cubic voxel faces or as SDF-smoothed marching cubes with Taubin polishing. Writes `export.<format>` (`ply` by default, set by `final_mesh_format`) and the run's `run_report.md`.

::: urbansolarcarver.api_core.exporting
    options:
      members: [exporting, ExportingResult]
