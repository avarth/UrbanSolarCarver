# Scoring

Sky-patch weight dispatch and threshold selection:

- **Weight dispatch** (`get_weights`): calls the sky-patch weighting function for the selected mode (Perez irradiance, heating benefit, CIE daylight luminance, or radiative cooling).
- **Thresholds**, applied by the thresholding stage to the raw scores of the occupied voxels:
    - `carve_fraction_threshold`: the cutoff above which the voxels hold a given fraction of the total score mass.
    - `headtail_threshold`: Jiang (2013) head/tail breaks for heavy-tailed score distributions.
    - A numeric cutoff from the config is used as given.

::: urbansolarcarver.scoring
