# Carving

The carving module implements the three geometric strategies used to remove voxels from the maximum buildable volume:

- **Sun-ray carving** (`carve_with_sun_rays`): traces rays along actual sun vectors at specific dates/times. Used by the `time-based` mode.
- **Sky-patch carving** (`carve_with_sky_patch_rays`): traces rays toward Tregenza sky patches weighted by irradiance, heating benefit, daylight luminance, or radiative cooling potential. Used by the `irradiance`, `benefit`, `daylight`, and `radiative_cooling` modes.
- **Plane carving** (`carve_with_planes`): removes voxels above a tilted cut plane at a fixed angle from each test surface. Used by the `tilted_plane` mode.

All three take a voxel grid and surface sample points with normals. Sky-patch carving returns per-voxel weighted scores; sun-ray and plane carving return a carved grid and, on request, per-voxel hit counts. The preprocessing stage stores these as `scores.npy` (for `time-based`, the counts are converted to m²·h), and the thresholding stage turns them into a binary carving mask.

`sun_ray_set` and `sky_patch_ray_set` build the rays (and, for the sky patches, the patch and edge_taper weights) that the carvers trace, so the access evaluation below traces the same ones.

::: urbansolarcarver.carving

## Test point access evaluation

`test_point_access_evaluation` (in `access_evaluation.py`) tells how much sun or sky each test point still receives through an occupancy grid: the uncarved max volume or a carved envelope on the same grid. It traces the mode's preprocessing rays until the first occupied voxel, under the same front-face and skin rules as scoring, and returns per test point `test_point_accessible_weight` (rays that reach no occupied voxel) and `test_point_blocked_weight` (the others). The weights are in the mode's patch weight unit (kWh/m² for `irradiance` and `benefit`, a share of the sky for `daylight` and `radiative_cooling`, so a horizontal point in the open has about 1), or hours of sun for `time-based`. `tilted_plane` has no rays toward the sky and is refused. For a carved envelope, pass the max volume as `max_volume`: the skin rule reads it, as in scoring, so a facade voxel left standing in front of carved mass still counts as the test point's own wall. It is a Python function only for now, with no CLI command or stage.

::: urbansolarcarver.access_evaluation

## Column post-processing

`column_postprocessing.py` holds the column rules thresholding applies after the score threshold: `carve_above_columns` (the `carve_above` setting), `carve_above_scores` (for each voxel, the score cutoff below which carve_above removes it; thresholding uses it so that `carve_fraction` counts what carve_above removes) and `limit_column_slope` (the slope limit, `max_slope_deg`).

::: urbansolarcarver.column_postprocessing
