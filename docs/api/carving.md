# Carving

The carving module implements the three geometric strategies used to remove voxels from the maximum buildable volume:

- **Sun-ray carving** (`carve_with_sun_rays`): traces rays along actual sun vectors at specific dates/times. Used by the `time-based` mode.
- **Sky-patch carving** (`carve_with_sky_patch_rays`): traces rays toward Tregenza sky patches weighted by irradiance, heating benefit, daylight luminance, or radiative cooling potential. Used by the `irradiance`, `benefit`, `daylight`, and `radiative_cooling` modes.
- **Plane carving** (`carve_with_planes`): removes voxels above a tilted cut plane at a fixed angle from each test surface. Used by the `tilted_plane` mode.

All three take a voxel grid and surface sample points with normals. Sky-patch carving returns per-voxel weighted scores; sun-ray and plane carving return a carved grid and, on request, per-voxel hit counts. The preprocessing stage stores these as `scores.npy` (for `time-based`, the counts are converted to m²·h), and the thresholding stage turns them into a binary carving mask.

With `return_patch_rank=True`, sky-patch carving also returns `patch_rank`, computed by `rank_blocked_patches`: the rays are traced one patch at a time in order of weight, and each voxel gets the rank of the highest-weight patch it blocks from some test point, in front of the test surface (`UNBLOCKED_RANK` where it blocks none). The preprocessing stage stores this as `patch_rank.npy` for the `protect_share` threshold.

With `return_recovery=True`, sky-patch carving also returns a `RecoveryRays` record, computed by `rank_rays_for_recovery`, for the `recovered_sky` threshold. Each ray from a test point to a sky patch the surface faces gets a weight (the patch weight, times the incidence cosine when the mode's `incidence_cosine` flag is set, times the point's `edge_taper` weight) and a cost (the number of voxels that clearing it removes, counting what `carve_above` removes above it). Rays with a cost of 0 are already clear and left out; the others are ranked by weight per voxel of cost, and each voxel gets the best rank of the rays crossing it. The preprocessing stage stores the record as `recovery_rays.npz`. In thresholding, `removal_order` turns the voxel ranks into the cut at which each voxel is removed (with `carve_above`), `ray_clear_times` traces the obstructed rays again to find the cut from which each one is clear, and `recovered_sky_cut` picks the smallest cut that recovers a given share of the ray weight.

The module also holds the column post-processing applied in thresholding: `carve_above_columns` (the `carve_above` setting) and `limit_column_slope` (the `max_slope_deg` setting), which caps each column at a maximum rise above a median-filtered height map of its neighbours.

::: urbansolarcarver.carving
