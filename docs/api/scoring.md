# Scoring

Sky-patch weight dispatch and threshold selection:

- **Weight dispatch** (`get_weights`): calls the sky-patch weighting function for the selected mode (Perez irradiance, heating benefit, CIE daylight luminance, or radiative cooling).
- **Thresholds**, applied by the thresholding stage to the raw scores of the occupied voxels:
    - `carve_fraction_threshold`: the cutoff above which the voxels hold a given fraction of the total score mass.
    - `headtail_threshold`: Jiang (2013) head/tail breaks for heavy-tailed score distributions.
    - A numeric cutoff from the config is used as given.
- **Sky-patch protection order**, used by the `protect_share` threshold (which works on sky patches, not on scores):
    - `protection_order`: indices of the patches with positive weight, highest weight first (ties keep patch order).
    - `protected_patch_count`: the smallest number of top patches whose weights reach a given share of the total positive weight.

::: urbansolarcarver.scoring
