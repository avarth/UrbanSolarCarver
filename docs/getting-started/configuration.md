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
    carve_fraction: 0.7
    ```

=== "daylight"

    ```yaml
    max_volume_path: "path/to/maxVolume.ply"
    test_surface_path: "path/to/testSurfaces.ply"
    out_dir: "outputs"
    mode: "daylight"
    voxel_size: 1.0
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
    carve_fraction: 0.35   # cooling scores are diffuse; 0.7 over-carves
    ```

## Key parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | `"time-based"` | Carving mode (see [Modes](../modes.md)) |
| `voxel_size` | 1.0 | Voxel edge length in meters (0.01-100) |
| `grid_step` | 1.0 | Surface sampling spacing in meters (must be <= voxel_size) |
| `ray_length` | 300.0 | Maximum ray cast distance in meters |
| `carve_fraction` | 0.7 | Sky modes: fraction (0-1) of the building's obstruction score to remove. See [How much to carve](#how-much-to-carve) |
| `max_slope_deg` | `null` | Steepest rise (degrees) allowed between neighbouring columns after `carve_above`; taller columns are cut into ramps. `null` = 75 for the score-cutoff methods of the sky modes, off otherwise; 90 = off |
| `threshold` | 0 | `time-based`: tolerated shading in m²·h (0 = none). Sky modes: unset uses `carve_fraction`; set it to choose [another method](../modes.md#sky-modes-other-methods) |
| `protect_share` | 0.1 | Sky modes, with `threshold: protect_share`: share (0-1) of the sky weight whose patch directions stay clear from every test point |
| `score_smoothing` | `null` | Score-cutoff methods of the sky modes: Gaussian blur radius (m) on the scores before the cutoff; `null` = 1.1 x voxel_size, 0 = off |
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
| `edge_taper` | weighted modes | Sample points closer than this (m) to their surface's edge count proportionally less (default 0 = off). Does not apply to `protect_share` (points with taper weight 0 cast no rays there) |

## How much to carve

Each mode has one setting for this; it sets the trade-off between solar protection and buildable volume. Details and limitations: [Carving Modes: How much to carve](../modes.md#how-much-to-carve).

**Sky modes** (`irradiance`, `benefit`, `daylight`, `radiative_cooling`): `carve_fraction` (0-1, default 0.7)
:   Removes the voxels that block the most sky weight until they hold this fraction of the building's total obstruction score. 0.7 is aggressive (taller, slimmer result), 0.3 conservative (bulkier volume, more floor area). After `carve_above`, a slope limit (`max_slope_deg`, 75° by default) cuts columns that rise too steeply above their neighbours, so the result has ramps instead of cliffs and one-voxel spires.

**`time-based`**: `threshold` in m²·h (default 0)
:   The shading a voxel may cause on the protected surfaces (area x duration) before it is carved. `0` removes any voxel that shades at any sampled moment; `5` tolerates up to 5 m²·h.

**`tilted_plane`**: `tilted_plane_angle_deg`
:   Everything above the plane is carved; do not set `threshold`.

**Other methods for the sky modes**
:   `threshold: protect_share` (with `protect_share`) keeps the rays from every test point to the highest-weight sky patches clear, like a solar envelope over those directions; `threshold: headtail` splits the scores automatically; a numeric `threshold` is a raw-score cutoff. See [Carving Modes](../modes.md#sky-modes-other-methods).

!!! tip
    The **decomposed pipeline** is designed for exploring this setting. Compute once (`preprocessing`), then re-run `thresholding` with other values; it takes seconds because the ray tracing is already done (for `protect_share`, preprocessing also stores the per-voxel patch ranks in `patch_rank.npy`).

## CLI overrides

Any config value can be overridden from the command line:

```bash
urbansolarcarver preprocessing -c config.yaml     -o voxel_size=0.5     -o mode=irradiance     -o carve_fraction=0.5
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
