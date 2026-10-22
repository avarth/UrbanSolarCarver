# Ray Tracing

Ray generation and voxel traversal for the carving pipeline, in two modules. The main kernels use a DDA (Digital Differential Analyzer) that steps each ray through the voxel grid and adds to a per-voxel volume in a single pass.

`ray_tracing.py` builds and traces the rays:

- **`trace_and_score_dda`**: traces a batch of rays and adds each ray's weight to every voxel it crosses (weighted modes). Runs on CUDA or on Warp's CPU backend.
- **`trace_and_count_dda`**: the same traversal, adding a count of 1 per ray (`time-based` and `tilted_plane`).
- **`trace_point_access_dda`**: stops each ray at the first occupied voxel and adds its weight to its test point's accessible or blocked weight (`test_point_access_evaluation`).
- **`follow_mass_behind_skin_dda`**: the skin rule, which keeps a test surface's skin voxels with the mass behind them.
- **`generate_sky_patch_rays`** / **`generate_sun_rays`**: expand sample points × directions into flat ray arrays (origins + directions), keeping only directions the surface faces.
- **`auto_batch_size`**: picks a ray batch size from the free GPU memory, to avoid out-of-memory errors on large scenes.

`warp_kernels.py` sets up Warp and holds every Warp kernel of the package (the DDA kernels above and the parity voxelizer that `voxelization.voxelize_solid_warp` launches), so Warp compiles and caches them as one module:

- **`dda_backend_available`**: whether the Warp DDA backend can run on a device.
- **`require_dda_backend`**: raises `WarpBackendUnavailableError`, naming the reason, when it cannot. Ray tracing has no other backend; every carver calls this first.
- **`warmup_kernels`**: precompiles the Warp kernels (`urbansolarcarver warmup`).

Rays are processed in batches. With `ray_batch_size: 0` (the default) the batch size comes from `auto_batch_size`; set a positive value to fix it.

::: urbansolarcarver.ray_tracing

::: urbansolarcarver.warp_kernels
