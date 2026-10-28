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

## Sky patches and rays per patch (`rays_per_patch`)

The four weighted modes divide the sky into the 145 Tregenza patches, give each patch a weight, and trace rays from
every test point toward the patches its surface faces. A voxel's score is the weight of the rays that cross it.

With `rays_per_patch: 1` each point sends one ray to each patch centre. The centres are 12° apart in altitude (12° to
60° in azimuth), so the rays of one point reach a voxel layer at distance d about 0.21 × d apart. Rays from the other
points of a test surface fill the space between them only up to the surface's own extent. Beyond about five times
the height of the test surfaces, voxels between the rows of rays get no ray at all and score 0, and the scores show
horizontal and diagonal bands. On the Allatini example (facades 8 to 24 m high, maximum volumes 30 to 190 m away),
38 % of the maximum volume's voxels scored 0 and the tallest tower column scored 0 over four bands 4 to 12 m high.

`rays_per_patch` 4 (the default), 9 or 16 trace that many rays per patch. The patch is cut into 2 × 2, 3 × 3 or
4 × 4 cells of equal solid angle, and each ray points at a place in its cell drawn from a hash of the test point, the
patch and the cell, carrying that share of the patch weight. Neighbouring points draw different places, so their
rays no longer line up into rows. The places depend on nothing else, so a run gives the same scores every time and
for any batch size; CPU and GPU agree to float32 rounding (their sine and cosine can differ in the last bit, so a ray
grazing a voxel edge may cross the neighbour). Rays that the surface does not face are skipped, so a patch its plane cuts counts the part
in front of it: a wall sees exactly half of the overcast sky.

Measured in daylight mode on an RTX 3060. Allatini (19,193 test points), against 64 rays per patch; District of many
buildings (527,000 test points, test surfaces beside the volumes, so little banding at 1 ray):

| `rays_per_patch` | Allatini: voxels scoring 0 | Allatini: keep or carve decisions at 70 % that differ | Allatini: preprocessing | District: preprocessing |
|---|---|---|---|---|
| 1 | 38 % | 30 % | 1.15 s | 12.3 s |
| 4 | 6 % | 6.4 % | 1.18 s | 13.9 s |
| 9 | 5.5 % | 4.7 % | 1.20 s | 15.2 s |
| 16 | 5 % | 3.8 % | 1.33 s | 17.0 s |

The remaining zeros are voxels that no test point sees (behind context, or behind the surfaces). The sub-rays are
generated inside the tracing kernels, so memory does not grow with them. The rays are ordered by patch, so the GPU
threads that run together trace the same direction from neighbouring points and find the voxels they visit in its
cache; this is what keeps the extra rays cheap.
`rays_per_patch: 1` reproduces the scores of earlier versions. Time-based mode traces sun positions and `tilted_plane`
its planes, so neither reads this setting.

## Context and terrain

Two optional meshes describe what is around (or inside) the site and stays whatever is built: `context_path` for
existing buildings and large trees, `terrain_path` for the ground. Both are opaque. Balconies, external shading
devices and billboards are not context. Without them a run is the same as before.

**Context** does two things, in every mode:

- **Whole columns go.** Where the context lies in a voxel column of the maximum volume (a voxel of the grid counts
  when its centre lies inside the context, not on its surface), the whole column is removed from the buildable mass,
  above and below the context. Nothing is built on top of kept buildings, under tree crowns or beside a chimney within
  its columns. To build on or over an existing building, remove it from the context. A context face shared with the
  maximum volume (a party wall) takes no voxel of the site. Only the context bodies that reach the voxel grid count
  here, so a large city model around the site costs little and its distant parts cannot disturb the result.
- **Rays that hit it are dropped** (ray-based modes: `time-based`, `irradiance`, `benefit`, `daylight`,
  `radiative_cooling`). Each ray from a test point is tested against the context mesh before scoring; a ray that hits
  it within `ray_length` adds nothing to any voxel, because that sun or sky is lost whatever is carved. The test is
  against the mesh, not the voxel grid, so context far outside the grid still blocks. Weights are not renormalised:
  a test point whose sky is half hidden keeps half its weight in play.

**Terrain** blocks rays exactly like context, but removes only the voxels whose centre lies below the ground (where
the terrain crosses the column's vertical centre line, the highest crossing if there are several). The rest of the
column stays buildable, so a sloping site keeps its volume above the ground. A voxel centre on the ground counts as
above it. An open sheet is fine; a column the
terrain does not cover keeps all its voxels.

**Test surfaces on context buildings.** A neighbour's facade is usually a face of its own context building. Each ray
starts 1 cm off the test surface along its normal and hits closer than 1 mm are ignored, so a test surface lying on
a context face is not blocked by that face; other parts of the same building (a second wing) block normally. A test
surface drawn inside a context mass, below the terrain, or facing into its own building has all its rays blocked:
the run reports a `test_points_blocked` warning with their count (ray-based modes), since those points protect
nothing.

**`tilted_plane`** traces no rays to the sky, so context and terrain only remove voxels there: the planes are the
same as without them.

**Account for context blocking** (`context_blocks_rays`, on by default). Off, the context and the terrain still
remove their voxels and still count as solid mass, but no ray is tested against them: the carving is the one that
ignores what they block, on the same reduced maximum volume, for comparison. The run report says when it is off.
Dropping the rays lowers the scores, so with it on the cutoff usually needs another look.

**Context and ground are solid.** The rule that keeps a facade's own building from counting as its obstruction (a
voxel the facade plane passes through, with mass behind it, is the facade's own skin) treats everything inside the
context and below the terrain as solid mass, like the maximum volume. The space under a tree crown or above a kept
building is not solid: a column removed there is empty, and a sliver of the maximum volume left in front of it counts
as an obstruction like any thin part of the maximum volume.

**Context mesh not closed.** The column rule needs closed (watertight) context bodies to tell inside from outside. An
open context mesh gives a `context_not_closed` warning: where an open body reaches the voxel grid, the columns removed
may be too few or too many. It still blocks rays.

The run report (and `summary["context"]` in the preprocessing diagnostics) gives the voxels removed by the context
columns and below the ground, the volume and share of the maximum volume removed, the rays dropped and their share
of the ray weight, and the test points with every ray blocked. Everything after preprocessing (thresholding,
`carve_above`, the slope limit, export, massing) sees the reduced maximum volume; the massing footprint leaves out
the columns context took.

## Thresholding strategies

USC supports three threshold strategies. The right choice depends on the mode.

### For weighted modes (irradiance, benefit, daylight, radiative_cooling)

Scores are continuous **weighted sums**: the sky-patch weight of every ray a voxel blocks, times the area of protected surface that ray's sample point stands for (about `grid_step`² m², times its `edge_taper` weight when that is set). The score is then a physical quantity that does not change with the sample spacing:

| Mode | Score unit | A voxel's score is |
|---|---|---|
| `irradiance` | kWh | the solar energy (direct and diffuse) it keeps from the protected surfaces over the analysis period |
| `benefit` | kWh | the same for the heating-useful solar energy only (the hours below the balance point, or the simulated weights) |
| `daylight` | m² | the overcast sky it hides from the protected surfaces, weighted by CIE overcast brightness, in m² of fully hidden sky |
| `radiative_cooling` | m² | the night sky's cooling potential it hides, in m² of fully hidden sky |

The patch weights of `irradiance` and `benefit` are kWh/m² per patch (Ladybug's sky matrix), counted on a surface facing the patch: there is no reduction for the angle at which a ray meets its surface, so the kWh are those a surface turned towards each sky patch would receive. The `daylight` and `radiative_cooling` weights are each patch's share of its sky and sum to 1, so 1 m² is the whole sky of 1 m² of open horizontal surface (a vertical facade sees half of it at most). Summed over a set of voxels a score counts what they block more than once when a ray crosses several of them; it compares voxels, it is not an energy balance. Scores written before this unit was introduced (preprocessing manifests without `score_unit`) were sums of patch weights without the area, and changed four times when the sample spacing halved.

| Strategy | How it works | When to use |
|----------|---|---|
| `carve_fraction` (default) | Removes the highest-scoring voxels until the removed part holds the target fraction of the building's total obstruction weight, counting the voxels that `carve_above` removes with them. `0.7` = aggressive (tall, slim volumes). `0.3` = conservative (bulky volumes). | **Recommended.** Works as a slider; no knowledge of the score distribution needed. |
| `headtail` | Jiang (2013) head/tail breaks: splits the scores at their mean, then splits the part above the mean again, for as long as that part holds at most 40% of the values. Suited to heavy-tailed distributions. | When you want an automatic, data-driven split without choosing a fraction. |
| Numeric value | Manual cutoff on the scores, in the score unit above. Voxels scoring above this value are carved. | **Advanced.** Pick it from the score histogram in `diagnostics/` (or the browser UI's). It means the same at any sample spacing, but depends on the weather, the period and the protected surfaces, so it carries over between variants of one project rather than between projects. |

**How carve_fraction and carve_above work together.** With `carve_above` (the default), a column loses everything above its lowest removed voxel. Each voxel therefore goes at the cutoff of the lowest high-scoring voxel below it, and carve_fraction counts the score of everything removed that way: `0.4` removes 40% of the obstruction score. (Before this was counted, carve_above removed extra score on top of the value set, so `0.4` removed 50-62% in the ReSBE test blocks.)

**Slope limit (`max_slope_deg`, default 75 degrees for these modes).** Scores in a column are low near the ground, peak partway up and fall again, and a column is cut at its lowest voxel above the cutoff. Two neighbouring columns whose peaks fall just above and just below the cutoff end 10-15 m apart, and small score differences leave single-column spires. After carve_above, each column may rise at most `tan(max_slope_deg)` above a 5 x 5 median of its neighbours' heights; anything higher is removed. Cliffs become ramps and spires end one step above their surroundings. The limit only removes voxels, and carving more before it never keeps more after it. In the ReSBE test blocks (33 m, 0.5 m voxels) it cut the spike area from 26-186 m² to 0-25 m² for 0-10% of extra obstruction score, reported as `obstruction_fraction_carved_by_slope_limit` (it is not counted in carve_fraction). The median window and the allowed step are counted in voxels, so at 1 m voxels the limit is weaker than at 0.5 m. `90` turns it off. Finer sampling (`grid_step`) reduces spikes only a little; they come from the column rule, not from rays missing voxels.

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
    The time-based threshold has a direct meaning: `threshold: 0` means zero shadow tolerance during the analysis period; `threshold: 5` lets each voxel cast up to 5 m²·h of shadow on the protected surfaces. A numeric threshold of a weighted mode is read the same way in its unit: `threshold: 20` in `irradiance` keeps a voxel that blocks up to 20 kWh over the period.

## time-based

Casts rays from test surfaces along actual sun vectors for specific dates and times. Each voxel's score is the shading it causes (m²·h, see above); with the default `threshold: 0`, a voxel is carved if **any** sun ray passes through it. There is no sky-patch weighting.

The sun is sampled `sun_steps_per_hour` times per hour (default 12, i.e. every 5 minutes). The sun moves about 15° of azimuth per hour, so hourly sampling leaves gaps between the ray sheets of consecutive hours in which mass survives while still shading the protected surface between samples; at 1 m voxels, 5-minute sampling closes them for obstructions up to ~40 m away. Ray count grows linearly with this value.

### Time basis: standard, daylight saving or solar time (`time_basis`)

By default (`time_basis: standard`) the hours of the analysis period are the EPW's local standard time.

With `time_basis: daylight_saving` they are daylight saving (summer) time: standard time plus one hour, on every date of the period, so 13:00 is read as 12:00 standard time. Weather files carry no daylight saving dates (TMY files leave the EPW header's field empty), so USC does not look up when the clocks change: a period that runs past the change of the clocks is one hour off on the days outside summer time. Split such a period, or use standard time.

With `time_basis: solar` they are true solar time: 12:00 is the moment the sun crosses the meridian, due south at a northern mid-latitude site, on every date. Solar-fence rules (Boulder: 21 December, two hours each side of solar noon) and the Japanese shadow regulation define their hours this way.

The two clocks differ by the equation of time (between about −14 and +16 minutes over the year) plus the site's distance from its time-zone meridian (4 minutes per degree of longitude). Solar noon in standard time:

| Site | 11 Feb | 21 Jun | 3 Nov | 21 Dec |
|---|---|---|---|---|
| Golden, CO (bundled EPW, 105.2° W, UTC−7) | 12:15 | 12:03 | 11:44 | 11:59 |
| Athens (23.7° E, UTC+2) | 12:39 | 12:27 | 12:09 | 12:23 |

So a 10:00-14:00 window read in standard time is up to 39 minutes off a 10:00-14:00 solar-time rule in Athens, and the carved envelope shifts with it. Ladybug computes the sun position in either clock (`is_solar_time`).

`time_basis` is read by `time-based` only. `daylight_saving` and `solar` are refused in `irradiance` and `benefit`: their analysis period selects hourly EPW records, which are in standard time, so reading the period in another clock would pair each hour with the wrong weather record. Modes without an analysis period (`daylight`, `tilted_plane`, `radiative_cooling`) ignore it with the usual "does not use" warning. In the browser UI it is **Time** (Standard time / Daylight saving time / Solar time) under "More sun settings"; in Grasshopper it is the `time_basis` text input of USC Analysis Period.

```yaml
mode: time-based
analysis_period: {st_month: 12, st_day: 21, st_hour: 10, end_month: 12, end_day: 21, end_hour: 14}
time_basis: solar   # 10:00-14:00 true solar time
```

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

**Cold period**: `urbansolarcarver.cold_period.cold_period_from_weather_file(epw_path, base_temperature)` gives the start and end dates of the site's cold period, to use as the analysis period: the longest run of days whose 31-day running mean dry-bulb temperature (wrapping across the new year) is below the base, for benefit mode `balance_temperature - balance_offset`. It may wrap across the new year. Hours the EPW marks missing (99.9) are left out. The browser UI offers it as a preset of the analysis period. With `simulated_weights_path` set, the balance values are unused by the mode, so the cold period found from them describes the simple rule, not the simulated building. In climates whose temperature stays near the base all year, the longest run can be short and its dates arbitrary.

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

**In the browser app** the same weights come from the Settings of a Solar usefulness criterion: **Which hours count**, **Energy-weighted**. The project's **typical building** is described in a form (a shoebox: its shape, windows, walls and glass, air, use and summer shading, starting from one of three types) and calculated there or by Run analysis; the app writes `simulated_weights_path` into the criterion's config and leaves out its balance values. See [Browser UI: the typical building](ui.md#the-typical-building).

A full-year `analysis_period` is the natural choice with simulated weights, since the schedule itself selects the useful hours. `balance_temperature` / `balance_offset` are unused (USC warns if you customize them). With `diagnostic_plots: true`, the run's diagnostics include a comparison dome showing how the simulated weights shifted the sky relative to the simple rule.

**Use case**: benefit envelopes that respond to the thermal mass, insulation, and glazing of the building stock being protected.

**Key parameters**: `simulated_weights_path`, `include_harm` (experimental; without declared seasonal shading (`shading_hot` in the archetype) harm is overstated, so treat it as a bracketing scenario).

See [Simulated Benefit Weights](simulated-weights.md) for the engine's documentation (what it implements, how it was validated against RC_BuildingSimulator, the archetype inputs, and the declared limitations) and Tutorial 5 (`examples/5_benefit_5r1c.ipynb`) for an end-to-end walkthrough.

## daylight

Weights sky patches using the CIE standard overcast sky luminance distribution. Direct sun is not considered: each patch's weight is its overcast-sky luminance, which depends on the zenith angle, times its solid angle, scaled so the weights sum to 1. No weather file or analysis period is needed.

**Use case**: protect diffuse daylight access (e.g., for daylighting codes, visual comfort).

## tilted_plane

Traditional geometric solar envelope method. Every voxel above a tilted plane at a fixed angle from each test surface is carved. No weather data is involved. Each sample point casts one ray at the plane angle, outward along the facade's horizontal normal, and every voxel at or above that ray in its (x, y) column is removed: the whole half-space above the plane, not only the band the rays cross. Where two test-surface panels meet at a convex corner or kink, their rays diverge; extra rays from the corner sweep the headings between the two normals, so the plane rotates around the corner (at 45 degrees, a column outside a right-angle corner is capped at its distance from the corner). Concave corners need no extra rays: the two planes already meet there.

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
