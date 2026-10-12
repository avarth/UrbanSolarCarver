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

Each mode has one setting that decides how much is carved:

| Mode | Setting | Meaning |
|---|---|---|
| `irradiance`, `benefit`, `daylight`, `radiative_cooling` (sky modes) | `protect_share` (0-1, default 0.1) | Share of the sky's weight to protect; the directions to the protected sky patches stay unobstructed from every test point |
| `time-based` | `threshold` (m²·h, default 0) | Shading a voxel may cause before it is carved; 0 = none |
| `tilted_plane` | `tilted_plane_angle_deg` | Angle of the plane above which everything is carved |

### Sky modes: `protect_share`

```yaml
protect_share: 0.1   # keep the sky patches holding 10% of the sky weight visible
```

The sky is divided into the 145 Tregenza patches, and each patch has a weight for the mode (for example the heating-season irradiance it delivers in `benefit` mode). USC ranks the patches by weight and protects the smallest group of top patches whose weights add up to `protect_share` of the total. Every voxel that blocks a protected patch from any test point is carved.

**What this guarantees.** Each patch is represented by one direction, the ray to its centre, as in the scoring. For a protected patch, no voxel of the envelope stands on that ray from any test point. So with `protect_share: 0.1`, every protected surface keeps unobstructed lines of sight towards the centres of the patches that together carry at least 10% of the mode's sky weight. Rays towards the rest of a patch (a Tregenza patch spans about 12° x 12°) can still be partly blocked near the envelope's edges.

**Relation to time-based carving.** This is the same operation as a `time-based` solar envelope: pick a set of sky directions and carve every voxel on a ray from a test point towards one of them. `time-based` uses the sun positions of a period you choose; `protect_share` uses the patch centres that deliver the most weight for the mode (including diffuse sky). In a sunny climate the top patches lie on the winter sun path, so the two give similar shapes. `time-based` also offers a tolerance (`threshold` in m²·h); `protect_share` has none.

**Choosing a value.** Small values already carve a lot, because the top patches are usually low winter-sun patches that cross much of the volume. On the ReSBE test blocks (0.5 m voxels, `benefit`, Thessaloniki heating season), `0.1` kept 33-74% of the volume and `0.2` kept 22-41%. Start at 0.1 and adjust in steps of 0.05.

**Limitations.**

- *Steps, not a smooth slider.* Patches are protected whole, so nearby values can give the same result (in the test blocks, 0.05, 0.1 and 0.15 all protected 2-5 patches). The share actually protected is reported and can exceed the value you set.
- *The most demanding test point decides.* The same patches are protected for every test point, so a point low in a courtyard drives the carving even where its view matters little.
- *A share of the whole sky, not of each surface's view.* 10% means 10% of the total patch weight, not 10% of what each window would receive on an empty plot.
- `score_smoothing` and `edge_taper` do not apply (the method does not use the voxel scores; sample points with taper weight 0 cast no rays).

**Where to see the result.** The thresholding stage's `diagnostics/diagnostic.json` reports `protected_patch_count`, `protected_patches` (Tregenza indices) and `protected_weight_share` (the share actually protected). The run report and the Grasshopper USC_ThresholdStage summary show the same.

**How it is computed.** Preprocessing of the sky modes traces the rays once more, one patch at a time, and stores for each voxel the rank of the highest-weight patch it blocks (`patch_rank.npy`). Thresholding turns the share into a number of patches and carves every voxel whose rank is below it, so trying another value does not trace rays again. The extra tracing makes preprocessing somewhat slower (about 2.0 s to 2.2-2.5 s in the test scenes).

### Time-based: tolerated shading

`time-based` scores measure **how much protected surface a voxel shades, and for how long**, in m²·h: the shaded test-surface area times the duration, summed over the analysis period. Each sample point stands for about `grid_step`² m² of surface and each sun position for 1/`sun_steps_per_hour` h, so the score does not depend on the sampling density.

| `threshold` | Meaning |
|---|---|
| `0` (default) | **Strict**: remove any voxel that shades any protected surface at any sampled moment |
| `5` | Tolerate a voxel that shades up to 5 m²·h, e.g. 5 m² of facade for one hour, or 1 m² for five hours |

`tilted_plane` is strictly binary (see below) and takes no threshold.

### Legacy: score-cutoff methods (sky modes)

Earlier versions decided the sky modes by a cutoff on voxel scores. These methods still work, so existing configs run unchanged, but they are no longer recommended:

```yaml
threshold: carve_fraction   # or: headtail, or a number (raw-score cutoff)
carve_fraction: 0.7
```

| Method | How it works |
|---|---|
| `carve_fraction` | Removes the highest-scoring voxels until they hold the given fraction of the building's total score. Also selected when a config sets only the `carve_fraction` key. |
| `headtail` | Jiang (2013) head/tail breaks: splits the scores at their mean, then splits the part above the mean again while it holds at most 40% of the values. |
| a number | Carves voxels scoring above it. The value depends on the mode, weather file and sampling, so it does not carry over between runs. |

**Why they are legacy.** A voxel's score adds up the sky weight of every ray passing through it. But blocking does not add up: a ray that crosses ten voxels stays blocked until all ten are removed. Removing the voxels that hold 40% of the score therefore does not return 40% of the sky to the test surfaces, and how much it does return cannot be read from the setting. With `carve_above` (the default) each column is also decided by its single highest-scoring voxel; scores in a column are near zero at the base and peak partway up, so neighbouring columns whose peaks fall just above or below the cutoff can end up 15-30 m apart, and score noise leaves one-voxel spires. On the ReSBE test blocks, `carve_fraction: 0.4` left 31-182 spires per scene; `protect_share: 0.1` left none.

These methods consider **occupied voxels only**: rays also cross the empty cells of streets, courtyards and the grid margin, which typically hold 60-80% of the score mass, and including them would make the result depend on how much air the grid contains. `score_smoothing` (a Gaussian blur of the scores before the cutoff) applies only to these methods. Setting both `carve_fraction` and `protect_share` without `threshold` is an error; set `threshold` to choose.

### Planned: a per-surface target

What designers and regulations usually ask for is a per-surface guarantee: *every test point keeps at least X% of the sky weight it would see on an empty plot*, with as little volume removed as possible. That is physically correct and would also remove the steps and the "most demanding point decides" effect above, because each point would protect the patches that matter most to it. Choosing which rays to clear at the least volume cost is an optimisation problem, so it is planned as a separate method; `protect_share` is the simple, conservative version of the same idea.

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
