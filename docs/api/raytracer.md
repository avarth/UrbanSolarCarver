# Ray Tracer

Ray generation and voxel traversal for the carving pipeline. The main kernels use a DDA (Digital Differential Analyzer) that steps each ray through the voxel grid and adds to a per-voxel volume in a single pass.

- **`trace_and_score_dda`**: traces a batch of rays and adds each ray's weight to every voxel it crosses (weighted modes). Runs on CUDA or on Warp's CPU backend.
- **`trace_and_count_dda`**: the same traversal, adding a count of 1 per ray (`time-based` and `tilted_plane`).
- **`trace_ray_costs`** / **`trace_ray_ranks`** / **`trace_ray_clear_times`**: wrappers of three DDA kernels for the `recovered_sky` threshold. Per ray, the voxels that clearing it removes, counting `carve_above`; per voxel, the best rank of the rays crossing it; per ray, the largest removal value along it (the ray is clear for cuts above it). Without Warp, `carving.py` computes the same values, approximately, with the fixed-step marcher.
- **`trace_multi_hit_grid`**: fixed-step PyTorch fallback used only when Warp is unavailable; approximate, since an oblique ray can skip a voxel corner between two samples.
- **`generate_sky_patch_rays`** / **`generate_sun_rays`**: expand sample points × directions into flat ray arrays (origins + directions), keeping only directions the surface faces.
- **`voxelize_solid_warp`**: the Warp parity voxelizer used by `grid.voxelize_mesh`.
- **`auto_batch_size`**: picks a ray batch size from the free GPU memory, to avoid out-of-memory errors on large scenes.
- **`warmup_kernels`**: precompiles the Warp kernels (`urbansolarcarver warmup`).

Rays are processed in batches. With `ray_batch_size: 0` (the default) the batch size comes from `auto_batch_size`; set a positive value to fix it.

::: urbansolarcarver.raytracer
