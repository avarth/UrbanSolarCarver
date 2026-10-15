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
    threshold: "carve_fraction"
    carve_fraction: 0.7
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
    threshold: "carve_fraction"
    carve_fraction: 0.7
    ```

=== "daylight"

    ```yaml
    max_volume_path: "path/to/maxVolume.ply"
    test_surface_path: "path/to/testSurfaces.ply"
    out_dir: "outputs"
    mode: "daylight"
    voxel_size: 1.0
    threshold: "carve_fraction"
    carve_fraction: 0.7
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
    threshold: "carve_fraction"
    carve_fraction: 0.35   # cooling scores are diffuse; 0.7 over-carves
    ```

## Key parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | `"time-based"` | Carving mode (see [Modes](../modes.md)) |
| `voxel_size` | 1.0 | Voxel edge length in meters (0.01-100) |
| `grid_step` | 1.0 | Surface sampling spacing in meters (must be <= voxel_size) |
| `ray_length` | 300.0 | Maximum ray cast distance in meters |
| `threshold` | mode default | `carve_fraction` for weighted modes, `0` for `time-based`, unset for `tilted_plane`. See [Thresholding strategies](#thresholding-strategies) below |
| `carve_fraction` | 0.7 | Solar protection slider: 0.7 = aggressive (remove 70% of the obstruction weight, including what `carve_above` removes), 0.3 = conservative |
| `score_smoothing` | `null` | Gaussian blur radius (m) on the scores before thresholding; `null` = 1.1 x voxel_size, 0 = off. Weighted modes only |
| `carve_above` | true | Carve all occupied voxels above the lowest carved region in each column, so the result is a buildable height field without floating mass (empty cells such as a ground-floor passage never trigger it). `false` keeps mass that floats above carved zones but casts no violating shadow |
| `carve_above_min_consecutive` | 1 | Min consecutive carved voxels to trigger carve_above (2-3 avoid column removal from stray single voxels; shorter runs stay carved) |
| `max_slope_deg` | 75 (weighted modes), off otherwise | Steepest rise (degrees) allowed between neighbouring columns after carve_above; taller columns are cut into ramps, which removes cliffs and spires. `90` = off. The extra score it removes is reported, not counted in `carve_fraction` |
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
| `edge_taper` | weighted modes | Sample points closer than this (m) to their surface's edge count proportionally less (default 0 = off) |

## Thresholding strategies

After preprocessing computes per-voxel obstruction scores, thresholding decides which voxels to remove. This is the main design control: it sets the trade-off between solar protection and buildable volume.

!!! note "Mode-specific threshold semantics"
    The strategies below apply to the **weighted modes** (`irradiance`, `benefit`, `daylight`, `radiative_cooling`) whose scores are continuous values.

    **`tilted_plane`** is strictly binary: a voxel either protrudes above the cut plane (removed) or it does not (kept). Do not set `threshold`; leave it unset (`None`). Setting a string method or a value > 0 raises a validation error.

    **`time-based`** scores are **shaded area x duration in m²·h** (how much protected surface the voxel shades, and for how long, during the period). Use a non-negative number: `threshold: 0` removes any voxel that shadows at any sampled moment (strict, default); `threshold: 5` tolerates up to 5 m²·h; and so on. See [Modes: violation-count thresholds](../modes.md#for-violation-count-modes-time-based-tilted_plane) for details.

**`carve_fraction`** (recommended for weighted modes)
:   Removes a fraction of the total obstruction weight of the building's voxels, counting what `carve_above` removes. Set `carve_fraction: 0.7` to remove 70% of the obstruction (aggressive: taller, slimmer result with better solar access). Set `carve_fraction: 0.3` for a conservative result (bulkier volume, more floor area). It works as a **solar protection slider**.

**`headtail`**
:   Jiang (2013) head/tail breaks: splits the scores at their mean and keeps splitting the upper part while it holds at most 40% of the values. Designed for heavy-tailed score distributions where most voxels have low scores and a few have very high scores. Biased toward removing only the worst obstructors.

**Numeric value** (e.g., `threshold: 0.35`)
:   Manual cutoff on the raw scores. Carves all voxels scoring above this value. Set `diagnostic_plots: true` to get the score histogram and pick a value from it. For `time-based`, the value is the tolerated shading in m²·h (see above).

!!! tip
    The **decomposed pipeline** is designed for threshold exploration. Compute scores once (`preprocessing`), then re-run `thresholding` with different parameters; it takes seconds because the ray tracing is already done.

## CLI overrides

Any config value can be overridden from the command line:

```bash
urbansolarcarver preprocessing -c config.yaml     -o voxel_size=0.5     -o mode=irradiance     -o threshold=carve_fraction
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

Weighted modes also write `preprocessing/patch_weights.npy`.

## Full reference

See `configs/REFERENCE_all_options.yaml` for every parameter with descriptions, or run:

```bash
urbansolarcarver schema
```
