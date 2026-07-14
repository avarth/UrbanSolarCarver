# Configuration

USC uses YAML configuration files. Mode-specific templates are in `configs/`.

## Minimal configs by mode

Required parameters vary by mode. Every config needs at minimum `max_volume_path`, `test_surface_path`, `mode`, and `out_dir`. Weather-dependent modes also require `epw_path` and an analysis period.

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
    start_month: 1
    start_day: 1
    start_hour: 8
    end_month: 12
    end_day: 31
    end_hour: 18
    threshold: "carve_fraction"
    carve_fraction: 0.7
    ```

=== "radiative_cooling"

    ```yaml
    max_volume_path: "path/to/maxVolume.ply"
    test_surface_path: "path/to/testSurfaces.ply"
    epw_path: "path/to/weather.epw"
    out_dir: "outputs"
    mode: "radiative_cooling"
    voxel_size: 1.0
    start_month: 6
    start_day: 1
    start_hour: 20
    end_month: 8
    end_day: 31
    end_hour: 6
    dew_point_celsius: 15.0
    bliss_k: 1.22
    threshold: "carve_fraction"
    carve_fraction: 0.6
    ```

## Key parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | -- | Carving mode (see [Modes](../modes.md)) |
| `voxel_size` | 1.0 | Grid resolution in meters (0.01 -- 100) |
| `grid_step` | 1.0 | Surface sampling spacing in meters (must be <= voxel_size) |
| `ray_length` | 300.0 | Maximum ray cast distance in meters |
| `min_altitude` | 5.0 | Minimum sun altitude in degrees |
| `threshold` | `"carve_fraction"` | See [Thresholding strategies](#thresholding-strategies) below |
| `carve_fraction` | 0.7 | Solar protection slider: 0.7 = aggressive (remove 70% obstruction), 0.3 = conservative |
| `carve_above` | false | Carve all occupied voxels above the lowest carved region in each column |
| `carve_above_min_consecutive` | 1 | Min consecutive carved voxels to trigger carve_above (2-3 recommended) |
| `apply_smoothing` | false | SDF smoothing + marching cubes instead of cubic mesh |
| `min_voxels` | 300 | Remove connected components smaller than this |
| `device` | `"auto"` | `"auto"`, `"cpu"`, or `"cuda"` |
| `diagnostics` | true | Write score histograms and diagnostic JSON |

## Mode-specific parameters

| Parameter | Modes | Description |
|-----------|-------|-------------|
| `epw_path` | all except `tilted_plane`, `daylight` | Path to EPW weather file |
| `start_month` .. `end_hour` | all except `tilted_plane`, `daylight` | Analysis period |
| `balance_temperature` | `benefit` | Free-running balance-point temperature (C); unused when `usefulness_path` is set |
| `balance_offset` | `benefit` | Dead-band offset (C); unused when `usefulness_path` is set |
| `usefulness_path` | `benefit` | Path to a `solar_usefulness.json` artifact (`usc usefulness`): simulated hourly weights replace the balance-point rule ([details](../modes.md#simulated-weights)) |
| `include_harm` | `benefit` | Experimental: subtract summer-overheating contributions per sky patch |
| `tilted_plane_angle_deg` | `tilted_plane` | Cut angle in degrees (float or list of 8 for octants) |
| `dew_point_celsius` | `radiative_cooling` | Night-time dew point (C) |
| `bliss_k` | `radiative_cooling` | Bliss angular-attenuation constant |

## Thresholding strategies

After preprocessing computes per-voxel obstruction scores, thresholding decides which voxels to remove. This is the primary design lever -- it controls the trade-off between solar protection and buildable volume.

!!! note "Mode-specific threshold semantics"
    The strategies below apply to the **weighted modes** (`irradiance`, `benefit`, `daylight`, `radiative_cooling`) whose scores are continuous values.

    **`tilted_plane`** is strictly binary -- a voxel either protrudes above the cut plane (removed) or it does not (kept). Do not set `threshold`; leave it unset (`None`). Setting a string method or a value > 0 raises a validation error.

    **`time-based`** scores are **integer violation counts** (how many sun-position time steps the voxel shadows a test surface). Use a non-negative integer: `threshold: 0` removes any voxel that shadows even once (strict, default); `threshold: 1` allows one time step of shadowing; and so on. See [Modes -- violation-count thresholds](../modes.md#for-violation-count-modes-time-based-tilted_plane) for details.

**`carve_fraction`** (recommended for weighted modes)
:   Removes a percentage of total obstruction weight. Set `carve_fraction: 0.7` to remove 70% of obstruction (aggressive -- taller, slimmer result with better solar access). Set `carve_fraction: 0.3` for a conservative result (bulkier volume, more floor area). This is the most intuitive option: a **solar protection slider**.

**`headtail`**
:   Jiang (2013) head/tail breaks: iteratively splits the distribution at the mean. Designed for heavy-tailed score distributions where most voxels have low scores and a few have very high scores. Biased toward removing only the worst obstructors.

**Numeric value** (e.g., `threshold: 0.35`)
:   Manual threshold on normalized scores. Carves all voxels scoring above this value. Enable `diagnostics: true` to inspect the score histogram and pick a value by eye. For `time-based`, use an integer (e.g., `threshold: 2` = allow up to 2 shadow steps).

!!! tip
    The **decomposed pipeline** is designed for threshold exploration. Compute scores once (`preprocessing`), then re-run `thresholding` with different parameters -- it's nearly instant since the expensive ray tracing is already done.

## CLI overrides

Any config value can be overridden from the command line:

```bash
urbansolarcarver preprocessing -c config.yaml \
    -o voxel_size=0.5 \
    -o mode=irradiance \
    -o threshold=carve_fraction
```

## Output structure

```
outputs/
  preprocessing/
    scores.npy, voxel_grid.npy, manifest.json, diagnostics/
  thresholding/
    mask.npy, manifest.json, diagnostics/
  exporting/
    carved_mesh.ply, manifest.json, diagnostics/
```

## Full reference

See `configs/REFERENCE_all_options.yaml` for every parameter with descriptions, or run:

```bash
urbansolarcarver schema
```
