# Carving Modes

USC supports six carving modes, each using a different strategy to determine which voxels to remove from the maximum buildable volume.

## Mode overview

| Mode | Type | Weight Source | Requirements |
|------|------|---|---|
| `time-based` | Binary | Sun vectors from EPW | EPW + analysis period |
| `irradiance` | Weighted | Perez all-weather sky | EPW + analysis period |
| `benefit` | Weighted | Heating-benefit sky | EPW + analysis period + balance temp |
| `daylight` | Weighted | CIE overcast luminance | Analysis period |
| `tilted_plane` | Binary | Geometric fixed angle | Angle specification only |
| `radiative_cooling` | Weighted | Martin-Berdahl + Bliss | Dew point temperature |

## Thresholding strategies

USC supports three threshold strategies. The right choice depends on the mode.

### For weighted modes (irradiance, benefit, daylight, radiative_cooling)

Scores are continuous **weighted sums** -- the total sky-patch weight obstructed by each voxel. Their absolute magnitude depends on the mode, weather file, and number of sample points, so they are not directly interpretable as physical quantities.

| Strategy | How it works | When to use |
|----------|---|---|
| `carve_fraction` (default) | Ranks voxels by score, removes top-scorers until the target fraction of total obstruction weight is eliminated. `0.7` = aggressive (tall, slim volumes). `0.3` = conservative (bulky volumes). | **Recommended.** Intuitive slider; no knowledge of score distribution needed. |
| `headtail` | Jiang (2013) head/tail breaks: iteratively splits the distribution at the mean. Good for heavy-tailed distributions. | When you want an automatic, data-driven split without choosing a fraction. |
| Numeric value | Manual cutoff on raw scores. Voxels scoring above this value are carved. | **Advanced.** Only useful after inspecting the score histogram in `diagnostics/`. The value is mode- and dataset-specific; not portable across runs. |

### For violation-count modes (time-based, tilted_plane)

Scores are **integer violation counts** -- the number of time steps (sun hours) or plane intersections that each voxel causes. These have direct physical meaning:

| Threshold value | Meaning |
|---|---|
| `0` (default) | **Strict** -- remove any voxel that causes even one violation |
| `1` | Allow one hour of shadow (or one plane intersection) |
| `2` | Allow two violations, etc. |
| `None` | Uses the default (0 = strict) |

String strategies (`carve_fraction`, `headtail`) are **not applicable** to integer counts and will raise an error for `tilted_plane`. For `time-based`, the threshold is applied as a simple integer cutoff.

!!! tip "Violation counts are powerful"
    Unlike weighted modes, violation-count thresholds have a clear physical interpretation. `threshold: 0` means "zero shadow tolerance during the analysis period." `threshold: 2` means "allow up to 2 hours of shadow." This makes time-based mode the most transparent and controllable carving strategy.

## time-based

Casts rays from test surfaces along actual sun vectors for specific dates and times. A voxel is carved if **any** sun ray passes through it. Simple binary logic -- no weighting.

**Use case**: protect direct sunlight during specific hours (e.g., winter solstice 10:00--14:00).

**Threshold semantics**: see [violation-count thresholds](#for-violation-count-modes-time-based-tilted_plane) above.

## irradiance

Weights each Tregenza sky patch by its cumulative direct + diffuse irradiance over the analysis period, using the Perez all-weather sky model. Voxels blocking high-irradiance patches receive higher scores.

**Use case**: climate-based solar resource assessment over an entire heating or cooling season.

## benefit

Similar to irradiance, but weights hours by a heating-benefit criterion. Two weightings are available:

**Simple weights (default)**: only hours when the outdoor temperature is below the building's balance-point temperature contribute to patch weights. This focuses carving on protecting solar access when it is most useful for passive heating.

**Use case**: maximize passive solar heating potential during the heating season.

**Key parameters**: `balance_temperature` (free-running balance point, typically 15--20 C), `balance_offset` (dead-band width).

### Simulated weights

Instead of the binary cold-hour rule, benefit mode can consume hourly weights derived from a thermal simulation of a typical building (the compact 5R1C hourly model from ISO 13790). For every hour of the year the simulation answers: *if one extra watt of sun arrived in this hour, how much less heating, and how much more cooling, would the building need over the whole year?* This captures thermal lag (a noon gain stored in the mass and released into the cold evening still earns credit), diurnal mass state, and gain saturation -- everything the binary rule cannot express. The simple rule is the special case where the weights are 0 or 1.

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

**Key parameters**: `simulated_weights_path`, `include_harm` (experimental; without declared seasonal shading (`shading_hot` in the archetype) harm is overstated -- treat it as a bracketing scenario).

See [Simulated Benefit Weights](simulated-weights.md) for the engine's documentation -- what it implements, how it was validated against RC_BuildingSimulator, the archetype inputs, and the declared limitations -- and Tutorial 5 (`examples/5_benefit_5r1c.ipynb`) for an end-to-end walkthrough.

## daylight

Weights sky patches using the CIE standard overcast sky luminance distribution. No direct sun is considered -- only diffuse sky luminance weighted by solid angle and zenith angle.

**Use case**: protect diffuse daylight access (e.g., for daylighting codes, visual comfort).

## tilted_plane

Traditional geometric solar envelope method. Voxels above a tilted plane at a fixed angle from each test surface are carved. No weather data or ray tracing is involved -- purely geometric.

The angle can be a single float (applied uniformly) or a list of 8 floats (one per octant, for directional control).

**Use case**: quick regulatory envelopes, traditional Knowles-style solar access planes.

**Key parameter**: `tilted_plane_angle_deg`

**Threshold semantics**: this mode is strictly binary -- a voxel either protrudes above the cut plane or it does not. Do not set `threshold`; leave it unset (the default `None`). Setting any string method or a numeric value > 0 raises a validation error.

## radiative_cooling (experimental)

Weights sky patches by their radiative cooling potential, using the Martin-Berdahl atmospheric emissivity model and a Bliss angular attenuation factor. Designed to preserve access to the cold sky dome for passive nighttime cooling.

**Use case**: hot-arid climates where nighttime radiative cooling is a significant design strategy.

**Key parameters**: `dew_point_celsius`, `bliss_k`

!!! warning
    This mode is experimental. The clear-sky assumption may not hold in humid or cloudy climates.

!!! note "Horizontal surface assumption"
    The current implementation assumes a **horizontal analysis surface** (flat roof). The angular view-factor weighting (cos&theta;/&pi;) is only valid for upward-facing surfaces. Applying these weights to tilted or vertical test surfaces will over-weight the zenith and under-weight low-altitude sky patches, producing inaccurate cooling envelopes.
