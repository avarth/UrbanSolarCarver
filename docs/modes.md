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

## Thresholding strategies

USC supports three threshold strategies. The right choice depends on the mode.

### For weighted modes (irradiance, benefit, daylight, radiative_cooling)

Scores are continuous **weighted sums**: the total sky-patch weight obstructed by each voxel. Their absolute magnitude depends on the mode, weather file, and number of sample points, so they are not directly interpretable as physical quantities.

| Strategy | How it works | When to use |
|----------|---|---|
| `carve_fraction` (default) | Ranks the building's voxels by score and removes the highest-scoring ones until the target fraction of the building's total obstruction weight is removed. `0.7` = aggressive (tall, slim volumes). `0.3` = conservative (bulky volumes). | **Recommended.** Works as a slider; no knowledge of the score distribution needed. |
| `headtail` | Jiang (2013) head/tail breaks: splits the scores at their mean, then splits the part above the mean again, for as long as that part holds at most 40% of the values. Suited to heavy-tailed distributions. | When you want an automatic, data-driven split without choosing a fraction. |
| Numeric value | Manual cutoff on raw scores. Voxels scoring above this value are carved. | **Advanced.** Only useful after inspecting the score histogram in `diagnostics/`. The value is mode- and dataset-specific and does not carry over to other runs. |

All three strategies, the score smoothing and the reported retention consider **occupied voxels only**. Rays also cross the empty cells of streets, courtyards and the grid margin, and those cells typically hold 60-80% of the total score mass; including them would make the result depend on how much air the grid contains.

### For violation-count modes (time-based, tilted_plane)

`time-based` scores measure **how much protected surface a voxel shades, and for how long**, in m²·h: the shaded test-surface area times the duration, summed over the analysis period. Each sample point stands for about `grid_step`² m² of surface and each sun position for 1/`sun_steps_per_hour` h, so the score does not depend on the sampling density.

| Threshold value | Meaning |
|---|---|
| `0` (default) | **Strict**: remove any voxel that shades any protected surface at any sampled moment |
| `5` | Tolerate a voxel that shades up to 5 m²·h, e.g. 5 m² of facade for one hour, or 1 m² for five hours |
| `None` | Uses the default (0 = strict) |

String strategies (`carve_fraction`, `headtail`) do **not apply** to violation counts and raise an error. `tilted_plane` is strictly binary (see below).

!!! tip "Physically interpretable thresholds"
    Unlike weighted modes, the time-based threshold has a direct meaning: `threshold: 0` means zero shadow tolerance during the analysis period; `threshold: 5` lets each voxel cast up to 5 m²·h of shadow on the protected surfaces.

## time-based

Casts rays from test surfaces along actual sun vectors for specific dates and times. Each voxel's score is the shading it causes (m²·h, see above); with the default `threshold: 0`, a voxel is carved if **any** sun ray passes through it. There is no sky-patch weighting.

The sun is sampled `sun_steps_per_hour` times per hour (default 12, i.e. every 5 minutes). The sun moves about 15° of azimuth per hour, so hourly sampling leaves gaps between the ray sheets of consecutive hours in which mass survives while still shading the protected surface between samples; at 1 m voxels, 5-minute sampling closes them for obstructions up to ~40 m away. Ray count grows linearly with this value.

**Use case**: protect direct sunlight during specific hours (e.g., winter solstice 10:00-14:00).

**Threshold semantics**: see [violation-count thresholds](#for-violation-count-modes-time-based-tilted_plane) above.

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
