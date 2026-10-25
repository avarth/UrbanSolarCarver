# Criteria: chained carvings

A designer often protects different things with different criteria: the daylight of the neighbours' windows, the
winter sun on a school yard, the PV potential of roofs. Each has its own test surfaces, its own sky or sun model and its
own threshold. A **chain** carves them one after the other on one voxel grid, from a single config file.

!!! note "Where this works today"
    Chains run from the CLI (`usc run`), the Python API (`run_chain`) and the daemon. The browser app and the
    Grasshopper components follow in later phases. Until then the app keeps **Carve further** in its Export step, which
    makes the exported envelope the maximum volume of a new project (see [Browser UI](ui.md)).

## What a chain is

A chain is an ordered list of **criteria**. Each criterion is one carving pass with its own mode, test surfaces,
mode settings and carving rule (`carve_fraction`, `threshold`, smoothing, `carve_above`, `max_slope_deg`).

- **The maximum volume stays as drawn.** Every criterion traces its rays over the same voxel grid, built once from the
  maximum volume, context and terrain. No mesh is made between criteria, so nothing is voxelized twice.
- **Each criterion decides among what the one before it kept.** Its carve amount refers to the voxels still there when
  it starts: `carve_fraction: 0.8` in the second criterion removes 80 % of the score over the voxels the first one
  kept, not 80 % of the whole volume. Its histogram, `carve_above` and slope limit act on those voxels too, and it
  never brings back a voxel an earlier criterion removed. The order therefore matters.
- **Exporting and massing build once, from the last criterion.** Massing measures its floor plates against the
  maximum volume as drawn and its saved footprint, so the facades follow the drawn outline instead of the voxel
  staircase of the envelope.

A voxel's score is the weight of the rays that cross it, and it does not depend on which other voxels remain. So a
criterion's scores are the same as in a run of its settings alone on the drawn maximum volume. Only thresholding
depends on the criterion before it.

## The config file

Settings shared by the whole chain are at the top level, and the criteria are listed under `criteria:`:

```yaml
# Shared by the whole chain
max_volume_path: "site/maxVolume.ply"
context_path: "site/surroundings.ply"
epw_path: "weather/athens.epw"
voxel_size: 1.0
out_dir: "outputs"

criteria:
  - id: daylight
    name: Daylight on neighbours' windows
    mode: daylight
    test_surface_path: "protect/windows.ply"
    carve_fraction: 0.7
  - id: winter-sun
    name: Winter sun on the yard
    mode: benefit
    test_surface_path: "protect/yard.ply"
    start_month: 11
    start_day: 1
    start_hour: 8
    end_month: 2
    end_day: 28
    end_hour: 16
    carve_fraction: 0.8
```

Relative paths are resolved against the folder of the YAML file, as in any config. A file with a `criteria:` list
is a chain file, and `load_config` refuses it: use `load_chain`, or let `usc run` choose.

### Shared settings and criterion settings

| Belongs to | Settings |
|---|---|
| **Each criterion** | `id`, `name`, `mode`, `test_surface_path`; the carving rule (`threshold`, `carve_fraction`, `score_smoothing`, `carve_above`, `carve_above_min_consecutive`, `max_slope_deg`); the mode's own settings (the analysis period `start_month` .. `end_hour` or an `analysis_period:` mapping, `sun_steps_per_hour`, `min_altitude`, `time_basis`, `balance_temperature`, `balance_offset`, `simulated_weights_path`, `include_harm`, `tilted_plane_angle_deg`, `dew_point_celsius`, `bliss_k`, `min_sky_elevation_deg`); `rays_per_patch` and `edge_taper` |
| **Shared by the chain** | `max_volume_path`, `context_path`, `terrain_path`, `context_blocks_rays`, `voxel_size`, `grid_step`, `ray_length`, `device`, `epw_path`, `out_dir`, and the exporting and massing settings (`min_voxels`, `apply_smoothing`, `final_mesh_format`, `ground_floor_height`, `floor_height`, `min_plate_dimension`, `plate_tolerance`, `plate_stacking`, `diagnostics`, `diagnostic_plots`) |

In code the first row is `urbansolarcarver.chain_config.CRITERION_KEYS`; every other config key is shared.
Putting a shared setting inside a criterion, or a criterion setting at the top level, is an error that names the
setting, so a file never means two things. `-o` overrides on the command line set shared settings only.

`epw_path` is shared but only reaches the criteria whose mode reads a weather file (`time-based`, `irradiance`,
`benefit`). A `daylight` criterion in the same chain does not receive it, so it raises no warning about an unused
setting.

**Ids.** A criterion's `id` names its output folder, so it is 1 to 40 letters, digits, `_` or `-`, and ids are unique
ignoring case (Windows and macOS ignore case in folder names). Without an `id` the criterion gets its position
(`1`, `2`, ...). Without a `name` the display name is its mode.

Every criterion is validated when the file is loaded, and an error message starts with `criterion <id> (<name>):`.

## Running a chain

```bash
usc validate -c chain.yaml          # lists the criteria and the shared settings
usc run -c chain.yaml               # criteria in order, then exporting
usc run -c chain.yaml --produce massing
```

`usc run` runs preprocessing and thresholding of each criterion in order, then exporting (or massing) from the last.
`--start-from thresholding` reuses every criterion's existing scores and thresholds the chain again.

From Python:

```python
from urbansolarcarver import run_chain

result = run_chain("chain.yaml", out_dir="outputs", produce=("exporting", "massing"))
result.criteria[0].thresholding.retention_pct   # what the first criterion kept
result.exporting.export_path
```

`run_chain(chain, out_dir=None, produce=("exporting",), start_from="preprocessing", context=None)` accepts a path or
a `ChainConfig` from `load_chain`, and returns a `ChainResult`: one `PipelineResult` per criterion, then `exporting`
and `massing` (None when not produced) and the issues of the call. An issue of a criterion's stage is named
`criterion <id> (<stage>)`.

The daemon runs a chain when a `run` request names a chain file; its overrides set shared settings only.

### Output folders

```
outputs/
  criteria/
    daylight/
      preprocessing/   scores.npy, voxel_grid.npy, footprint.json, manifest.json, diagnostics/
      thresholding/    mask.npy, manifest.json, diagnostics/
    winter-sun/
      preprocessing/
      thresholding/
    chain.json         the criteria in order, with the thresholding run of each
  exporting/
  massing/             (when produced)
  run_report.md
```

The run report has a "Criteria" section with one row per criterion (name, mode, threshold, voxels at start, voxels
kept). Its Configuration, Preprocessing and Thresholding sections describe the last criterion.

## One step of a chain

`thresholding` takes the previous criterion's result as an optional input, `after`:

```bash
usc thresholding -c winter_sun.yaml --from outputs/criteria/winter-sun/preprocessing/manifest.json \
    --after outputs/criteria/daylight/thresholding
```

```python
from urbansolarcarver import thresholding

thr2 = thresholding(pre2, cfg2, "outputs/criteria/winter-sun/thresholding", after=thr1)
```

`--after` and `after` take the folder or the `manifest.json` of the previous criterion's thresholding (the Python
function also takes its result). The mask of this run is never True where the previous mask is False.

- The manifest records `after_manifest` and `after_run_id`, and the diagnostics record `voxels_at_start`, the voxels
  this criterion decided about.
- Both criteria must share the grid (maximum volume, context, terrain, voxel size and margin). Otherwise a
  `StageChainError` says which differs.
- When the previous criterion re-runs later, the criteria after it are refused with `StageChainError` until they are
  thresholded again, as for any stage.
- When the previous criterion kept no voxel, the mask is empty and the run reports the issue `nothing_left_to_carve`.

## Changing a criterion is cheap

Scores do not depend on the other criteria, so an earlier criterion's settings change only the thresholding of the
criteria after it, which takes seconds. Only a change to a criterion's own mode settings or test surfaces, or to a
shared setting such as the voxel size, needs its rays traced again. To change the carve amount of the first criterion
and see the effect on the whole chain, edit it and run `usc run -c chain.yaml --start-from thresholding`.
