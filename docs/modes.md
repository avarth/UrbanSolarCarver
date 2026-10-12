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
| `irradiance`, `benefit`, `daylight`, `radiative_cooling` (sky modes) | `carve_fraction` (0-1, default 0.7) | Fraction of the building's obstruction score to remove |
| `time-based` | `threshold` (m²·h, default 0) | Shading a voxel may cause before it is carved; 0 = none |
| `tilted_plane` | `tilted_plane_angle_deg` | Angle of the plane above which everything is carved |

### Sky modes: `carve_fraction`

```yaml
carve_fraction: 0.4   # remove the voxels holding 40% of the obstruction score
```

Each voxel's **score** is the sky weight it blocks: the sum, over every ray from a test point to a sky patch that passes through the voxel, of that patch's weight (for example its heating-season irradiance in `benefit` mode). Scores are compared within the building only (occupied voxels). `carve_fraction` sorts these voxels from highest to lowest score and removes the top ones until they hold the given fraction of the building's total score. `0.7` is aggressive (tall, slim volumes, more sky), `0.3` conservative (bulky volumes, more floor area). Because a few voxels hold much of the score, 0.7 removes far fewer than 70% of the voxels.

Before the cutoff, the scores are blurred with a small Gaussian (`score_smoothing`, default 1.1 x `voxel_size`) to reduce noise from the sampling. After it, `carve_above` removes everything above a carved voxel in its column, so the result has no floating mass.

**Slope limit (`max_slope_deg`, default 75 degrees).** With `carve_above`, each column is decided by its single highest-scoring voxel. Scores in a column are near zero at the base and peak partway up, so two neighbouring columns whose peaks fall just above and just below the cutoff can end up 15-30 m apart in height, and score noise leaves one-voxel spires. The slope limit removes this: after `carve_above`, each column may rise at most `tan(max_slope_deg)` above its neighbours, measured against a median-filtered height map, and anything higher is cut off. Cliffs become ramps and spires end at most one step above their surroundings. The limit only ever removes voxels, and carving more before it never keeps more after it, so the slider stays consistent. The median ignores features one or two columns wide (a stub at a curved edge, a narrow slot); wider height differences, including next to areas carved to the ground, become ramps. On the ReSBE test blocks (0.5 m voxels, `benefit`) at `carve_fraction: 0.4`, it removed all spires (31-182 per scene before) at a cost of 1-6 percentage points of kept volume (9 points in the curved "freeform" block). Lower angles give gentler ramps and remove more; `90` turns the limit off. The thresholding diagnostics report `max_slope_deg` and `slope_limit_extra_voxels_removed`.

**What `carve_fraction` does not tell you.** The score adds up the sky weight of every ray through a voxel, but blocking does not add up: a ray that crosses ten voxels stays blocked until all ten are removed. Removing the voxels that hold 40% of the score therefore does not return 40% of the sky to the test surfaces; how much it returns depends on the geometry. Treat the value as a design slider and judge the result, for example with a daylight or radiation study of the exported envelope. A ray-based version that removes this gap is planned (see below).

### Sky modes: other methods

Set `threshold` to choose one of these instead of `carve_fraction`:

| Method | How it works |
|---|---|
| `protect_share` (with `protect_share`, 0-1) | Ray-based. The highest-weight sky patches holding this share of the total weight are protected: every voxel on a ray from a test point towards a protected patch's centre is carved. This is the solar-envelope operation of `time-based`, with patch centres chosen by weather-weighted value in place of clock-time sun positions. Setting only the `protect_share` key also selects it. |
| `headtail` | Jiang (2013) head/tail breaks: splits the scores at their mean, then splits the part above the mean again while it holds at most 40% of the values. |
| a number | Carves voxels scoring above it. The value depends on the mode, weather file and sampling, so it does not carry over between runs. |

**More on `protect_share`.** It gives a firm statement: every protected surface keeps unobstructed lines of sight towards the centres of the patches that together carry at least the given share of the sky weight (rays towards the rest of a 12° x 12° patch can still be partly blocked). Its limits: patches are protected whole, so nearby values can give the same result (the share actually protected is reported as `protected_weight_share`); the same patches are protected for every test point, so the most demanding point (low in a courtyard, say) drives the carving; and small values already carve a lot (on the ReSBE blocks, 0.1 kept 33-74% of the volume, 0.2 kept 22-41%). It needs no slope limit or score smoothing. To keep re-thresholding instant, preprocessing of the sky modes also stores for each voxel the rank of the highest-weight patch it blocks (`patch_rank.npy`), which makes preprocessing somewhat slower (about 2.0 s to 2.2-2.5 s in the test scenes). Setting both `carve_fraction` and `protect_share` without `threshold` is an error.

### Time-based: tolerated shading

`time-based` scores measure **how much protected surface a voxel shades, and for how long**, in m²·h: the shaded test-surface area times the duration, summed over the analysis period. Each sample point stands for about `grid_step`² m² of surface and each sun position for 1/`sun_steps_per_hour` h, so the score does not depend on the sampling density.

| `threshold` | Meaning |
|---|---|
| `0` (default) | **Strict**: remove any voxel that shades any protected surface at any sampled moment |
| `5` | Tolerate a voxel that shades up to 5 m²·h, e.g. 5 m² of facade for one hour, or 1 m² for five hours |

`tilted_plane` is strictly binary (see below) and takes no threshold. Neither mode applies the slope limit unless `max_slope_deg` is set: their envelopes follow the rays exactly.

### Planned: a ray-based carve fraction

The aim is to keep the `carve_fraction` slider but give it a physical meaning: *clear the given fraction of the obstructed sky weight, removing as little volume as possible*. Each ray from a test point gets a weight (its patch weight) and a cost (the volume that clearing it removes, including what `carve_above` removes above it), and the rays that clear the most weight per cubic metre are cleared first. This counts rays instead of adding up voxel scores, and it clears expensive rays, such as those from low courtyard points, last. It needs new tracing kernels and a prototype on the test scenes before it can replace the score-based version.

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
