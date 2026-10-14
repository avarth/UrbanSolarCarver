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
    recovered_sky: 0.5
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
    recovered_sky: 0.5
    ```

=== "daylight"

    ```yaml
    max_volume_path: "path/to/maxVolume.ply"
    test_surface_path: "path/to/testSurfaces.ply"
    out_dir: "outputs"
    mode: "daylight"
    voxel_size: 1.0
    recovered_sky: 0.5
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
    recovered_sky: 0.5
    ```

## Key parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mode` | `"time-based"` | Carving mode (see [Modes](../modes.md)) |
| `voxel_size` | 1.0 | Voxel edge length in meters (0.01-100) |
| `grid_step` | 1.0 | Surface sampling spacing in meters (must be <= voxel_size) |
| `ray_length` | 300.0 | Maximum ray cast distance in meters |
| `recovered_sky` | 0.5 | Sky modes (the default method): share (0-1) of the sky blocked by the maximum volume that the test surfaces get back. See [How much to carve](#how-much-to-carve) |
| `threshold` | 0 | `time-based`: tolerated shading in m²·h (0 = none). Sky modes: unset uses `recovered_sky` (or `carve_fraction` / `protect_share` when only that key is set); set it to choose [another method](../modes.md#sky-modes-other-methods) |
| `carve_fraction` | 0.7 | Sky modes, other method (score-based, the default before `recovered_sky`): fraction (0-1) of the building's obstruction score to remove |
| `protect_share` | 0.1 | Sky modes, other method: share (0-1) of the sky weight whose patch directions stay clear from every test point |
| `max_slope_deg` | `null` | Steepest rise (degrees) allowed between neighbouring columns after `carve_above`; taller columns are cut into ramps. `null` = 75 for the score-cutoff methods of the sky modes (`carve_fraction`, `headtail`, numeric cutoff), off otherwise; 90 = off; a set value applies to any method |
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

**Sky modes** (`irradiance`, `benefit`, `daylight`, `radiative_cooling`): `recovered_sky` (0-1, default 0.5)
:   The share of the sky blocked by the maximum volume that the test surfaces get back, with the sky weighted as the mode weights it (patch weight times incidence cosine; for `radiative_cooling` the patch weights already contain the view factor). USC removes first the parts of the volume that block the most sky per cubic metre, so as much volume as possible is kept for that share. The value is exact: thresholding picks the smallest cut that reaches it and reports the share actually recovered (`recovered_sky_actual` in `diagnostics/diagnostic.json`, with `rays_obstructed`, `rays_recovered` and `recovery_cut`). No slope limit or score smoothing is applied.

**`time-based`**: `threshold` in m²·h (default 0)
:   The shading a voxel may cause on the protected surfaces (area x duration) before it is carved. `0` removes any voxel that shades at any sampled moment; `5` tolerates up to 5 m²·h.

**`tilted_plane`**: `tilted_plane_angle_deg`
:   Everything above the plane is carved; do not set `threshold`.

**Other methods for the sky modes**
:   `threshold: carve_fraction` (with `carve_fraction`) removes the highest-scoring voxels until they hold this fraction of the building's obstruction score; it was the default before `recovered_sky`, and configs that set it give the same results as before. `threshold: headtail` splits the scores automatically; a numeric `threshold` is a raw-score cutoff. These score-cutoff methods use score smoothing and, after `carve_above`, a slope limit (`max_slope_deg`, 75° by default) that cuts columns rising too steeply above their neighbours into ramps. `threshold: protect_share` (with `protect_share`) keeps the rays from every test point to the highest-weight sky patches clear, like a solar envelope over those directions. Setting only the `carve_fraction` or `protect_share` key also selects that method; setting more than one of `recovered_sky`, `carve_fraction` and `protect_share` without `threshold` is an error. See [Carving Modes](../modes.md#sky-modes-other-methods).

!!! tip
    The **decomposed pipeline** is designed for exploring this setting. Compute once (`preprocessing`), then re-run `thresholding` with other values; it takes seconds because the ray tracing is already done. Preprocessing stores the ranked rays for `recovered_sky` in `recovery_rays.npz` and the per-voxel patch ranks for `protect_share` in `patch_rank.npy`; `recovered_sky` thresholding traces the obstructed rays once more, which takes about 0.5 s on a GPU on the ReSBE test blocks at 0.5 m voxels.

## CLI overrides

Any config value can be overridden from the command line:

```bash
urbansolarcarver preprocessing -c config.yaml     -o voxel_size=0.5     -o mode=irradiance     -o recovered_sky=0.3
```

Relative paths given in overrides are resolved against the current directory, not the YAML's folder.

## Output structure

With the default output folders (`<out_dir>/preprocessing`, `<out_dir>/thresholding`, `<out_dir>/exporting`):

```
outputs/
  preprocessing/
    scores.npy, voxel_grid.npy, test_points.npy, test_normals.npy, manifest.json, diagnostics/
    patch_weights.npy, recovery_rays.npz, patch_rank.npy   (sky modes)
  thresholding/
    mask.npy, manifest.json, diagnostics/
  exporting/
    export.ply (or .obj/.stl/.glb), diagnostics/
  run_report.md
```

In the weighted (sky) modes, preprocessing also writes `patch_weights.npy`, `recovery_rays.npz` (the obstructed rays in clearing order, the per-voxel ray ranks and the traced points and normals; used by `recovered_sky`) and `patch_rank.npy` (for each voxel, the rank of the highest-weight sky patch it blocks; used by `protect_share`).

## Full reference

See `configs/REFERENCE_all_options.yaml` for every parameter with descriptions, or run:

```bash
urbansolarcarver schema
```
