# Carving Modes

USC supports six carving modes, each using a different strategy to determine which voxels to remove from the maximum buildable volume.

## Mode overview

| Mode | Type | Weight Source | Requirements |
|------|------|---|---|
| `time-based` | Violation count | Sun vectors from EPW | EPW + analysis period |
| `irradiance` | Weighted | Perez all-weather sky | EPW + analysis period |
| `benefit` | Weighted | Heating-benefit sky | EPW + analysis period (+ balance temperature or a simulated-weights file) |
| `daylight` | Weighted | CIE overcast luminance | None (no EPW, no analysis period) |
| `tilted_plane` | Binary | Geometric fixed angle | Angle specification only |
| `radiative_cooling` | Weighted | Martin-Berdahl + Bliss | Dew point temperature (no EPW) |

## How much to carve

Each mode has one main setting that decides how much is carved:

| Mode | Setting | Meaning |
|---|---|---|
| `irradiance`, `benefit`, `daylight`, `radiative_cooling` (sky modes) | `recovered_sky` (0-1, default 0.5) | Share of the sky blocked by the maximum volume that the test surfaces get back |
| `time-based` | `threshold` (m²·h, default 0) | Shading a voxel may cause before it is carved; 0 = none |
| `tilted_plane` | `tilted_plane_angle_deg` | Angle of the plane above which everything is carved |

### Sky modes: `recovered_sky`

```yaml
recovered_sky: 0.4   # the test surfaces get back 40% of the sky the maximum volume blocks
```

**What it means.** The maximum volume blocks part of the sky from the test surfaces. `recovered_sky: 0.4` carves the volume so that the surfaces get 40% of that blocked sky back. USC removes first the parts of the volume that block the most sky per cubic metre, so as much volume as possible is kept for that share.

**What "sky" means in each mode.** The sky is divided into the 145 Tregenza patches, and each patch has a weight for the mode. A test point's view of a patch counts with the patch weight times the cosine of the angle between the patch direction and the surface normal, so the totals are what the surfaces receive:

| Mode | The recovered share is a share of |
|---|---|
| `irradiance` | solar energy (kWh/m²) reaching the test surfaces over the analysis period |
| `benefit` | solar energy reaching the test surfaces in the hours when it offsets heating |
| `daylight` | overcast-sky daylight reaching the test surfaces |
| `radiative_cooling` | the surfaces' long-wave cooling potential to the sky (the patch weights already contain the view factor, so no extra cosine) |

**The baseline is the maximum volume.** Neighbouring buildings are not modelled: 0.4 means 40% of what the maximum volume blocks, not 40% of the open sky. Sky that the maximum volume does not block (for example above a low part of it) is not counted either way.

**The value is exact.** The thresholding stage finds the smallest cut that recovers at least the requested share and reports the share actually recovered (`recovered_sky_actual` in `diagnostics/diagnostic.json`, also in the run report and the Grasshopper USC_ThresholdStage summary). It is above the request only by rays that clear together at the same cut, usually by less than 0.1 percentage points. The share is measured on the voxel model, before the mesh export removes small fragments.

**How it works.** USC treats each pair of a test point and a sky patch as a ray. A ray is obstructed if it crosses the maximum volume in front of its surface. Each obstructed ray gets:

- a *weight*: the patch weight times the incidence cosine (times the point's `edge_taper` weight, if set);
- a *cost*: the number of voxels that clearing it removes, counting what `carve_above` removes above it (in each column the ray crosses, the voxels at and above the lowest one on the ray).

The rays are ranked by weight per voxel of cost, and clearing the first *n* rays means removing every voxel those rays cross, then applying `carve_above`. Preprocessing traces the rays to compute this ranking and stores it with the rays (`recovery_rays.npz`). Thresholding traces the obstructed rays once more to find, for each, the cut from which it is clear, and picks the smallest cut that reaches the share. On the ReSBE test blocks (0.5 m voxels) the extra tracing adds about 0.5 s to preprocessing, and thresholding takes about 0.5 s on a GPU (at 1 m voxels, 0.5 s on a CPU as well).

**Shapes.** Because whole rays are cleared, the envelope is made of ray fans and ramps, like a time-based solar envelope; there are no one-voxel spires, and no slope limit or score smoothing is applied. The order is a greedy one (each ray's cost is counted as if it were cleared alone), so it is not guaranteed to keep the very largest volume possible for a share, but on the test blocks it kept as much or more volume than `carve_fraction` for the same recovered sky: for example 9-11 percentage points more sky at about 60% kept volume in the courtyard block.

**Resolution.** The result depends on the voxel size, the sampling step (`grid_step`) and the 145-patch sky: a ray that only clips a voxel corner counts as obstructed. Compare designs at the same settings.

### Sky modes: other methods

Set `threshold` to choose one of these instead (setting only the `carve_fraction` or `protect_share` key also selects that method; setting more than one of the three keys without `threshold` is an error):

| Method | How it works |
|---|---|
| `carve_fraction` (with `carve_fraction`, 0-1) | Score-based, the default before `recovered_sky`. Each voxel's score is the sky weight of all rays through it; the highest-scoring voxels are removed until they hold the given fraction of the building's total score. Scores add up the rays through a voxel, but a ray stays blocked until every voxel on it is gone, so the value does not say how much sky comes back. With `carve_above` each column is decided by its highest-scoring voxel, which can leave cliffs and one-voxel spires; a slope limit (`max_slope_deg`, 75 degrees by default for the score-based methods) cuts columns that rise too steeply above their neighbours into ramps. |
| `protect_share` (with `protect_share`, 0-1) | Ray-based. The highest-weight sky patches holding this share of the total weight are protected: every voxel on a ray from a test point towards a protected patch's centre is carved. This is the `time-based` solar-envelope operation with patch centres chosen by weight in place of sun positions. Patches are protected whole and for every test point, so small values already carve a lot. |
| `headtail` | Jiang (2013) head/tail breaks on the scores: splits them at their mean, then splits the part above the mean again while it holds at most 40% of the values. Uses the slope limit like `carve_fraction`. |
| a number | Carves voxels scoring above it. The value depends on the mode, weather file and sampling, so it does not carry over between runs. Uses the slope limit like `carve_fraction`. |

The score-based methods consider **occupied voxels only** (rays also cross streets, courtyards and the grid margin, which can hold 60-80% of the score mass) and blur the scores slightly before the cutoff (`score_smoothing`, default 1.1 x `voxel_size`).

**Slope limit (`max_slope_deg`).** After `carve_above`, each column may rise at most `tan(max_slope_deg)` above its neighbours, measured against a 5 x 5 median-filtered height map, and anything higher is cut off. Features one or two columns wide (an edge stub, a narrow slot) are ignored by the median. The limit only removes voxels, and carving more before it never keeps more after it. On the ReSBE blocks at `carve_fraction: 0.4` it removed every spire (31-182 per scene before) for 1-9 percentage points of kept volume. `90` turns it off; setting a value applies it to any method.

### Time-based: tolerated shading

`time-based` scores measure **how much protected surface a voxel shades, and for how long**, in m²·h: the shaded test-surface area times the duration, summed over the analysis period. Each sample point stands for about `grid_step`² m² of surface and each sun position for 1/`sun_steps_per_hour` h, so the score does not depend on the sampling density.

| `threshold` | Meaning |
|---|---|
| `0` (default) | **Strict**: remove any voxel that shades any protected surface at any sampled moment |
| `5` | Tolerate a voxel that shades up to 5 m²·h, e.g. 5 m² of facade for one hour, or 1 m² for five hours |

`tilted_plane` is strictly binary (see below) and takes no threshold. Neither mode applies the slope limit unless `max_slope_deg` is set: their envelopes follow the rays exactly.

## time-based

Casts rays from test surfaces along actual sun vectors for specific dates and times. Each voxel's score is the shading it causes (m²·h, see above); with the default `threshold: 0`, a voxel is carved if **any** sun ray passes through it. There is no sky-patch weighting.

The sun is sampled `sun_steps_per_hour` times per hour (default 12, i.e. every 5 minutes). The sun moves about 15° of azimuth per hour, so hourly sampling leaves gaps between the ray sheets of consecutive hours in which mass survives while still shading the protected surface between samples; at 1 m voxels, 5-minute sampling closes them for obstructions up to ~40 m away. Ray count grows linearly with this value.

**Use case**: protect direct sunlight during specific hours (e.g., winter solstice 10:00-14:00).

**Threshold semantics**: see [tolerated shading](#time-based-tolerated-shading) above.

## irradiance

Weights each Tregenza sky patch by its cumulative direct + diffuse irradiance over the analysis period, using the Perez all-weather sky model. Voxels blocking high-irradiance patches receive higher scores.

**Use case**: climate-based solar resource assessment over an entire heating or cooling season.

## benefit

Similar to irradiance, but weights hours by a heating-benefit criterion. Two weightings are available:

**Simple weights (default)**: only hours when the outdoor temperature is below `balance_temperature - balance_offset` contribute to patch weights. This protects solar access in the hours when it is useful for passive heating.

**Use case**: maximize passive solar heating potential during the heating season.

**Key parameters**: `balance_temperature` (free-running balance point; default 15 °C, typically about 12 °C for commercial to 18 °C for residential buildings), `balance_offset` (dead-band width, default 2 °C).

### Simulated weights

Instead of the binary cold-hour rule, benefit mode can consume hourly weights derived from a thermal simulation of a typical building (the compact 5R1C hourly model from ISO 13790). For every hour of the year the simulation answers: *if one extra watt of sun arrived in this hour, how much less heating, and how much more cooling, would the building need over the whole year?* This captures thermal lag (a noon gain stored in the mass and released into the cold evening still earns credit), diurnal mass state, and gain saturation, none of which the binary rule can express. The simple rule is the special case where the weights are 0 or 1.

Generate the weights once from an EPW and a building **archetype** (roughly ten numbers describing a typical building; the easiest form is a shoebox with per-facade window-to-wall ratios, see `configs/archetype_example.yaml`):

```bash
urbansolarcarver simulate-weights -e weather.epw -a configs/archetype_example.yaml
```

This writes `simulated_weights.json` (the weights plus full provenance) and a `.png` preview of the weights next to it. Then point a benefit config at the artifact:

```yaml
mode: benefit
simulated_weights_path: simulated_weights.json
# include_harm: true   # experimental: also subtract summer-overheating contributions
```

A full-year `analysis_period` is the natural choice with simulated weights, since the schedule itself selects the useful hours. `balance_temperature` / `balance_offset` are unused (USC warns if you customize them). With `diagnostic_plots: true`, the run's diagnostics include a comparison dome showing how the simulated weights shifted the sky relative to the simple rule.

**Use case**: benefit envelopes that respond to the thermal mass, insulation, and glazing of the building stock being protected.

**Key parameters**: `simulated_weights_path`, `include_harm` (experimental; without declared seasonal shading (`shading_hot` in the archetype) harm is overstated, so treat it as a bracketing scenario).

See [Simulated Benefit Weights](simulated-weights.md) for the engine's documentation (what it implements, how it was validated against RC_BuildingSimulator, the archetype inputs, and the declared limitations) and Tutorial 5 (`examples/5_benefit_5r1c.ipynb`) for an end-to-end walkthrough.

## daylight

Weights sky patches using the CIE standard overcast sky luminance distribution. Direct sun is not considered: each patch's weight is its overcast-sky luminance, which depends on the zenith angle, times its solid angle. No weather file or analysis period is needed.

**Use case**: protect diffuse daylight access (e.g., for daylighting codes, visual comfort).

## tilted_plane

Traditional geometric solar envelope method. Every voxel above a tilted plane at a fixed angle from each test surface is carved. No weather data is involved. Each sample point casts one ray at the plane angle, outward along the facade's horizontal normal, and every voxel at or above that ray in its (x, y) column is removed: the whole half-space above the plane, not only the band the rays cross.

The angle can be a single float (applied uniformly) or a list of 8 floats (one per compass octant N, NE, E, SE, S, SW, W, NW, chosen by the direction each facade faces).

**Use case**: quick regulatory envelopes, traditional Knowles-style solar access planes.

**Key parameter**: `tilted_plane_angle_deg`

**Threshold semantics**: this mode is strictly binary: a voxel either protrudes above the cut plane or it does not. Do not set `threshold`; leave it unset (the default `None`). Setting any string method or a numeric value > 0 raises a validation error.

## radiative_cooling (experimental)

Weights sky patches by their radiative cooling potential, using the Martin-Berdahl atmospheric emissivity model and a Bliss angular attenuation factor. The aim is to keep access to the cold sky dome for passive nighttime cooling. The model uses one representative night-time dew point and reads no weather file.

**Use case**: hot-arid climates where nighttime radiative cooling is a significant design strategy.

**Key parameters**: `dew_point_celsius`, `bliss_k`, `min_sky_elevation_deg` (optional: ignore sky patches below this elevation and renormalize the rest)

!!! warning
    This mode is experimental. The clear-sky assumption may not hold in humid or cloudy climates.

!!! note "Horizontal surface assumption"
    The current implementation assumes a **horizontal analysis surface** (flat roof). The angular view-factor weighting (cos&theta;/&pi;) is only valid for upward-facing surfaces. Applying these weights to tilted or vertical test surfaces will over-weight the zenith and under-weight low-altitude sky patches, producing inaccurate cooling envelopes.
