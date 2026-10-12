# Configuration

USC uses YAML configuration files. Mode-specific templates are in `configs/`. Relative paths inside a config file (meshes, EPW, `out_dir`, `simulated_weights_path`) are resolved against the folder that contains the YAML file.

## Minimal configs by mode

Required parameters vary by mode. Every config needs `max_volume_path`, `test_surface_path`, and `out_dir`; `mode` defaults to `time-based`. The weather-dependent modes (`time-based`, `irradiance`, `benefit`) also require `epw_path` and an analysis period. `daylight`, `tilted_plane` and `radiative_cooling` need neither, and USC warns if you set settings the chosen mode does not use.

=== "tilted_plane"

    ```yaml
    max_volume_path: "path/to/maxVolume.ply"
    test_surface_path: "path/to/testSurfaces.ply"
    out_dir: "outputs"
    mode: "tilted_plane"
    voxel_size: 1.0
    tilted_plane_angle_deg: 45.0   # single angle, or list of 8 for octants
    ```

=== "time-based"

    ```yaml
    max_volume_path: "path/to/maxVolume.ply"
    test_surface_path: "path/to/testSurfaces.ply"
    epw_path: "path/to/weather.epw"
    out_dir: "outputs"
    mode: "time-based"
    voxel_size: 1.0
    start_month: 12
    start_day: 21
    start_hour: 9
    end_month: 12
    end_day: 21
    end_hour: 15
    ```

=== "irradiance"

    ```yaml
    max_volume_path: "path/to/maxVolume.ply"
    test_surface_path: "path/to/testSurfaces.ply"
    epw_path: "path/to/weather.epw"
    out_dir: "outputs"
    mode: "irradiance"
    voxel_size: 1.0
    start_month: 1
    start_day: 1
    start_hour: 8
    end_month: 12
    end_day: 31
    end_hour: 18
    threshold: "protect_share"
    protect_share: 0.1
    ```

=== "benefit"

    ```yaml
    max_volume_path: "path/to/maxVolume.ply"
    test_surface_path: "path/to/testSurfaces.ply"
    epw_path: "path/to/weather.epw"
    out_dir: "outputs"
    mode: "benefit"
    voxel_size: 1.0
    start_month: 10
    start_day: 1
    start_hour: 8
    end_month: 4
    end_day: 30
    end_hour: 16
    balance_temperature: 18.0
    balance_offset: 2.0
    threshold: "protect_share"
    protect_share: 0.1
    ```

=== "daylight"

    ```yaml
    max_volume_path: "path/to/maxVolume.ply"
    test_surface_path: "path/to/testSurfaces.ply"
    out_dir: "outputs"
    mode: "daylight"
    voxel_size: 1.0
    threshold: "protect_share"
    protect_share: 0.1
    ```

=== "radiative_cooling"

    ```yaml
    max_volume_path: "path/to/maxVolume.ply"
    test_surface_path: "path/to/testSurfaces.ply"
    out_dir: "outputs"
    mode: "radiative_cooling"
    voxel_size: 1.0
    dew_point_celsius: 14.0
    bliss_k: 1.8
    threshold: "protect_share"
    protect_share: 0.1
    # alternative: threshold: "carve_fraction" with carve_fraction: 0.35
    # (cooling scores are diffuse; 0.7 over-carves)
    ```

## Key parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | `"time-based"` | Carving mode (see [Modes](../modes.md)) |
| `voxel_size` | 1.0 | Voxel edge length in meters (0.01-100) |
| `grid_step` | 1.0 | Surface sampling spacing in meters (must be <= voxel_size) |
| `ray_length` | 300.0 | Maximum ray cast distance in meters |
| `threshold` | mode default | `protect_share` for weighted modes (`carve_fraction` if only the `carve_fraction` key is set), `0` for `time-based`, unset for `tilted_plane`. See [Thresholding strategies](#thresholding-strategies) below |
| `protect_share` | 0.1 | Share (0-1) of the total sky-patch weight to keep visible from every test point: the highest-weight patches holding this share are protected. Small values already carve a lot |
| `carve_fraction` | 0.7 | Used with `threshold: carve_fraction`: 0.7 = aggressive (remove 70% of the obstruction weight), 0.3 = conservative |
| `score_smoothing` | `null` | Gaussian blur radius (m) on the scores before thresholding; `null` = 1.1 x voxel_size, 0 = off. Weighted modes only; not used by `protect_share` |
| `carve_above` | true | Carve all occupied voxels above the lowest carved region in each column, so the result is a buildable height field without floating mass (empty cells such as a ground-floor passage never trigger it). `false` keeps mass that floats above carved zones but casts no violating shadow |
| `carve_above_min_consecutive` | 1 | Min consecutive carved voxels to trigger carve_above (2-3 avoid column removal from stray single voxels; shorter runs stay carved) |
| `apply_smoothing` | false | SDF smoothing + marching cubes instead of cubic mesh |
| `min_voxels` | 300 | Remove connected voxel clusters smaller than this |
| `final_mesh_format` | `"ply"` | Exported mesh format: `ply`, `obj`, `stl`, or `glb` |
| `device` | `"auto"` | `"auto"`, `"cpu"`, or `"cuda"` |
| `diagnostics` | false | Add detailed score statistics (median, std, percentiles) to the diagnostics JSON. Basic statistics and timings are always written |
| `diagnostic_plots` | false | Write plot images (score histograms, sky-patch weight plots, threshold histogram) |

## Mode-specific parameters

| Parameter | Modes | Description |
|-----------|-------|-------------|
| `epw_path` | `time-based`, `irradiance`, `benefit` | Path to EPW weather file |
| `start_month` .. `end_hour` | `time-based`, `irradiance`, `benefit` | Analysis period (or one `analysis_period:` mapping with Ladybug `AnalysisPeriod.to_dict()` keys) |
| `sun_steps_per_hour` | `time-based` | Sun positions per hour (default 12 = every 5 min; Ladybug timesteps 1-60) |
| `min_altitude` | `time-based` | Ignore sun positions below this altitude in degrees (default 5.0) |
| `balance_temperature` | `benefit` | Free-running balance-point temperature (°C, default 15); unused when `simulated_weights_path` is set |
| `balance_offset` | `benefit` | Dead-band below the balance point (°C, default 2); unused when `simulated_weights_path` is set |
| `simulated_weights_path` | `benefit` | Path to a `simulated_weights.json` artifact (`usc simulate-weights`): simulated hourly weights replace the balance-point rule ([details](../modes.md#simulated-weights)) |
| `include_harm` | `benefit` | Experimental: subtract summer-overheating contributions per sky patch |
| `tilted_plane_angle_deg` | `tilted_plane` | Cut angle in degrees (float or list of 8 for octants) |
| `dew_point_celsius` | `radiative_cooling` | Night-time dew point (°C, default 14) |
| `bliss_k` | `radiative_cooling` | Bliss angular-attenuation constant (default 1.8) |
| `min_sky_elevation_deg` | `radiative_cooling` | Ignore sky patches below this elevation in degrees (default 0 = full hemisphere) |
| `edge_taper` | weighted modes | Sample points closer than this (m) to their surface's edge count proportionally less (default 0 = off). Does not apply to `protect_share`, except that points with taper weight 0 cast no rays |

## Thresholding strategies

After preprocessing computes per-voxel obstruction scores, thresholding decides which voxels to remove. This is the main design control: it sets the trade-off between solar protection and buildable volume.

!!! note "Mode-specific threshold semantics"
    The strategies below apply to the **weighted modes** (`irradiance`, `benefit`, `daylight`, `radiative_cooling`) whose scores are continuous values.

    **`tilted_plane`** is strictly binary: a voxel either protrudes above the cut plane (removed) or it does not (kept). Do not set `threshold`; leave it unset (`None`). Setting a string method or a value > 0 raises a validation error.

    **`time-based`** scores are **shaded area x duration in m²·h** (how much protected surface the voxel shades, and for how long, during the period). Use a non-negative number: `threshold: 0` removes any voxel that shadows at any sampled moment (strict, default); `threshold: 5` tolerates up to 5 m²·h; and so on. See [Modes: violation-count thresholds](../modes.md#for-violation-count-modes-time-based-tilted_plane) for details.

**`protect_share`** (default and recommended for weighted modes)
:   Protects a share of the sky. The 145 Tregenza sky patches are ranked by weight (highest first; zero-weight patches are never protected), and the smallest top set holding `protect_share` of the total weight is kept visible: every voxel that blocks one of those patches from any test point is carved. Whole rays are cleared, so the envelope varies continuously, as in time-based carving; `carve_above` still applies afterwards. Small values already carve a lot: on the ReSBE test blocks (0.5 m voxels, benefit, Thessaloniki heating season), `protect_share: 0.1` kept 33-74% of the volume and `0.2` kept 22-41%. Patches are whole, so the share actually protected can exceed the requested value; the thresholding `diagnostics/diagnostic.json` reports `protected_patch_count`, `protected_patches` (Tregenza indices) and `protected_weight_share`. The method does not use the scores, so `score_smoothing` does not apply.

**`carve_fraction`**
:   Removes a fraction of the total obstruction weight of the building's voxels. Set `carve_fraction: 0.7` to remove 70% of the obstruction (aggressive: taller, slimmer result with better solar access). Set `carve_fraction: 0.3` for a conservative result (bulkier volume, more floor area). Selected by `threshold: carve_fraction`, or by setting only the `carve_fraction` key without `threshold` (setting both `carve_fraction` and `protect_share` without `threshold` is an error). With `carve_above`, each column is decided by its highest-scoring voxel, so neighbouring columns can differ sharply in height and score noise can leave single-voxel spires; see [Modes](../modes.md#for-weighted-modes-irradiance-benefit-daylight-radiative_cooling).

**`headtail`**
:   Jiang (2013) head/tail breaks: splits the scores at their mean and keeps splitting the upper part while it holds at most 40% of the values. Designed for heavy-tailed score distributions where most voxels have low scores and a few have very high scores. Biased toward removing only the worst obstructors.

**Numeric value** (e.g., `threshold: 0.35`)
:   Manual cutoff on the raw scores. Carves all voxels scoring above this value. Set `diagnostic_plots: true` to get the score histogram and pick a value from it. For `time-based`, the value is the tolerated shading in m²·h (see above).

!!! tip
    The **decomposed pipeline** is designed for threshold exploration. Compute scores once (`preprocessing`), then re-run `thresholding` with different parameters; it takes seconds because the ray tracing is already done. This includes `protect_share`: preprocessing of weighted modes stores the per-voxel patch ranks (`patch_rank.npy`) it needs.

## CLI overrides

Any config value can be overridden from the command line:

```bash
urbansolarcarver preprocessing -c config.yaml     -o voxel_size=0.5     -o mode=irradiance     -o threshold=protect_share     -o protect_share=0.2
```

Relative paths given in overrides are resolved against the current directory, not the YAML's folder.

## Output structure

With the default output folders (`<out_dir>/preprocessing`, `<out_dir>/thresholding`, `<out_dir>/exporting`):

```
outputs/
  preprocessing/
    scores.npy, voxel_grid.npy, test_points.npy, test_normals.npy, manifest.json, diagnostics/
  thresholding/
    mask.npy, manifest.json, diagnostics/
  exporting/
    export.ply (or .obj/.stl/.glb), diagnostics/
  run_report.md
```

Weighted modes also write `preprocessing/patch_weights.npy` and `preprocessing/patch_rank.npy` (for each voxel, the rank of the highest-weight sky patch it blocks; used by `protect_share`).

## Full reference

See `configs/REFERENCE_all_options.yaml` for every parameter with descriptions, or run:

```bash
urbansolarcarver schema
```
