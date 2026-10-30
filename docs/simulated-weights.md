# Simulated Benefit Weights

Benefit mode's optional simulated weighting runs a small building simulation inside USC. A simulation brings physical assumptions that the geometric parts of USC do not have, so this page documents the engine, its origin, how it was validated, what the user supplies, and where its limits are.

## The engine

USC implements the **ISO 13790 Annex C simple hourly method**, commonly called the **5R1C model**: a single thermal zone represented by five conductances and one lumped thermal-mass capacitance.

- Nodes: outdoor air, supply air, indoor air, an internal surface node, and the thermal mass.
- Conductances: ventilation, air-surface coupling, glazing, surface-mass coupling, and the opaque-envelope remainder, all derived per the standard (coupling coefficients `h_is = 3.45 W/m²K`, `h_ms = 9.1 W/m²K`, `Λ_at = 4.5`; thermal mass per ISO 13790 Table 12 mass classes).
- Time stepping: Crank-Nicolson on the mass node, one hour per step, with the standard's three-step heating/cooling demand calculation (free-float, 10 W/m² test load, exact linear interpolation to the setpoint).

On top of the simulation sits **perturbation attribution**: for every hour of the year, the transmitted solar gain of that hour is perturbed by ±1 W and the change in *annual* heating and cooling demand is attributed to that hour (central differences). This yields two hourly series in [0, 1]:

| Series | Meaning |
|--------|---------|
| `benefit[t]` | fraction of a marginal joule of solar gain at hour *t* that offsets heating over the year |
| `harm[t]` | fraction that becomes cooling load |

Attributing against the annual totals captures **thermal lag**: a noon gain stored in the mass and released into the cold evening still earns heating credit. All 17,521 year-simulations (the base run plus two per hour) run as one vectorized NumPy batch, in seconds.

## Origin and validation

The engine is an **independent implementation**, written directly from the ISO 13790 Annex C equation set in NumPy (`urbansolarcarver/simulated_weights.py`). It is **not** a fork, port, or adaptation of an existing simulator.

It is **cross-validated against [RC_BuildingSimulator](https://github.com/architecture-building-systems/RC_BuildingSimulator)**, the ETH Zurich Architecture & Building Systems group's MIT-licensed implementation of the same annex (Jayathissa et al., "Optimising building net energy demand with dynamic BIPV shading", *Applied Energy* 202, 2017). The validation setup:

- **Three archetype scenarios**: medium office, heavy masonry, light insulated.
- **Weather**: the bundled Golden, CO TMY3 EPW (dry-bulb direct; transmitted solar from Ladybug's directional irradiance on each scenario's glazing, g = 0.6).
- **Compared quantities**: annual heating and cooling demand totals (agreement to roughly 1 Wh/year, relative tolerance 1e-6), mean annual air temperature, and hourly air-temperature, mass-temperature, and heating/cooling-demand values at sampled hours across the year.
- **Method**: the oracle's own derived conductances are fed into USC's engine directly, so the comparison isolates the hourly recurrence itself rather than parameter-derivation conventions (the two implementations intentionally differ on one of those: RC_BuildingSimulator uses `U·A` directly for the opaque-envelope conductance, USC applies the standard's serial split).
- **Artifacts**: the oracle's driving arrays and reference outputs are committed verbatim in `tests/data/oracle_5r1c_reference.json`; the regression runs in the test suite on every change (`tests/test_simulated_weights.py`), deterministically, with no weather generation at test time.

Beyond the oracle comparison, the engine is checked for **steady-state energy-balance closure** against an independent hand-derived network reduction (constant outdoor temperature, no gains: demand converges to conductance × ΔT with the air node held at setpoint), and for the physical property that heavier mass classes flatten hour-to-hour mass-temperature variation.

Full derivation notes and the coefficient provenance live in the repository at `design/simulated-weights.md`.

## What you supply: the archetype

The archetype describes a *typical* building in about ten numbers. Two equivalent forms are accepted (`configs/archetype_example.yaml` shows both):

**Shoebox form** (areas derived for you):

| Key | Meaning |
|-----|---------|
| `width`, `length`, `height` | zone dimensions (m); floor area, volume, facade areas derived |
| `wwr` | window-to-wall ratio per facade, keyed `north`/`east`/`south`/`west` |
| `g_value` | glazing solar transmittance (applies to all windows) |
| `orientation` | optional rotation of the whole box, degrees clockwise from north |

**Explicit form**: `floor_area`, `volume`, `area_opaque`, `area_window`, and a `windows` list of `[azimuth_deg, area_m2, g_value]`.

**Both forms** additionally take: `u_opaque`, `u_window` (W/m²K), `ach_vent`, `ach_infiltration` (1/h), `heat_recovery` (0-1), `mass_class` (`very_light` … `very_heavy`, ISO 13790 Table 12), `t_set_heating`, `t_set_cooling` (°C), and internal gains as either a flat `internal_gains_w_m2` (W/m², default 5) or a 24-value daily profile `internal_gains_profile_w_m2`.

The shoebox form may instead give `u_wall` with `u_roof` and `u_floor` (W/m²K) and the switches `roof_exposed` (default true) and `floor_exposed` (default false): the walls, and the roof and floor when exposed, each at its own U; `u_opaque` keeps its meaning (walls and roof at one U). The thermal mass may be `mass_capacity_kj_m2k` (kJ/m²K of floor) instead of `mass_class`; `internal_gains_w_m2` and `ach_vent` also take 8,760 hourly values (a schedule), and the summer shading may run over `shading_hot_period: [first_day, last_day]` (days of the year, wrapping the new year when the first is later) instead of `hot_months`. The repository's `design/simulated-weights.md` §3 gives the details.

**Shading coefficients** (optional, declared multipliers; no device geometry is modelled):

| Key | Meaning |
|-----|---------|
| `shading_permanent` | year-round solar transmission multiplier in [0, 1] (fins, context obstructions); 1 = no shading |
| `shading_hot` | additional multiplier applied only during `hot_months` (awnings, tents, seasonal vegetation); stacks with the permanent factor |
| `hot_months` | calendar months (1-12) when `shading_hot` is deployed, e.g. `[6, 7, 8, 9]` |

Each coefficient accepts a scalar (all facades) or a per-facade mapping (`{south: 0.8, west: 0.9}`); windows are assigned to their nearest cardinal facade. The perturbation attribution is attenuated by the same factors, so the weights describe a marginal joule of *exterior* solar: a July joule arriving while the awning is out counts for little. The declared coefficients are recorded in the artifact's provenance. Note that a fixed overhang's blocking is concentrated in high-sun hours, so its effect is usually best expressed through `shading_hot` rather than `shading_permanent`.

The shipped example values are deliberately **neutral, with no national defaults**. For real projects, source values from [TABULA](https://episcope.eu/building-typology/) (EU building-stock typologies), DOE prototype buildings (US), or your national code tables.

The `usc archetype` command builds and validates the file for you, printing the derived floor area, volume, and per-facade window areas so mistakes surface before any simulation runs:

```bash
usc archetype -o my_building.yaml -s width=12 -s wwr_south=0.4 -s mass_class=heavy
usc archetype --from my_building.yaml -o variant.yaml -s mass_class=light   # derive a variant
```

In Grasshopper, **USC_Archetype** assembles the archetype from five family feeder components (USC_ZoneGeometry / Fabric / Ventilation / Operation / Shading, one wire each), feeding **USC_SimulateWeights**, whose output path wires into **USC_BenefitParams**.

## In the app

In the browser app a Solar usefulness criterion offers the weights as **Which hours count**: **Energy-weighted** (the other choice, **Cold hours**, is the balance temperature rule). The app describes the model as a simple hourly model of one room, names no standard in its labels and help, and does not use the name 5R1C, which stays the engine's. A project has one **typical building**, the archetype of every energy-weighted criterion, chosen from a library and edited in a window that opens over the app ([Browser UI: the typical building](ui.md#the-typical-building)).

ISO 13790:2008 has been withdrawn and replaced by EN ISO 52016-1:2017, whose hourly method gives each building element several nodes instead of one lumped mass. The engine keeps the 13790 method, the one validated against RC_BuildingSimulator.

### The values of the sheet

The sheet's values (`local_web_service/typical_building.py`, `archetype_of`) become a shoebox archetype:

| Sheet | Archetype |
|-------|-----------|
| Hours in use: Residential (6:00 to 24:00 every day), Office (8:00 to 18:00, Monday to Friday) or Always | the hours in which the internal gains and the fresh air apply, as 8,760-value `internal_gains_w_m2` and `ach_vent` (0 outside them); Always gives one value each. The weekday of 1 January is the weather file's (its DATA PERIODS line; Monday when it gives none) |
| Set points, heat recovery | `t_set_heating`, `t_set_cooling`, `heat_recovery` |
| Internal gains while in use, W/m² | `internal_gains_w_m2` in the hours in use |
| Fresh air while in use, m³/h per m² of floor | `ach_vent` = fresh air / storey height in the hours in use |
| Infiltration, air changes per hour | `ach_infiltration`, in every hour |
| U of the walls, of the windows; whole-window g | `u_wall`, `u_window`, `g_value` |
| Thermal capacity, kJ/m²K of floor | `mass_capacity_kj_m2k`; the effective mass area is that of the ISO 13790 class nearest in capacity |
| Summer shading: one factor and a period of dates | `shading_hot` with `shading_hot_period` (days of the year); none outside it |
| Room | the shoebox `width`, `length`, `height`, `orientation`, `wwr` |
| Roof and floor, exposed or not, each with its U | `roof_exposed`, `u_roof`, `floor_exposed`, `u_floor` |

The three cases of use are examples of hours, not an editor: gains and fresh air are on in the hours of the case and off outside them, with no holidays. The project's values (project.json, the library's YAML files) use the keys of `typical_building.VALUE_KEYS`: `schedule` (`residential`, `office`, `always`), `t_set_heating`, `t_set_cooling`, `gains_w_m2`, `fresh_air_m3h_m2`, `heat_recovery`, `u_wall`, `u_window`, `g_value`, `mass_capacity_kj_m2k`, `shading_factor` (null for none), `shading_start`, `shading_end` ("MM-DD"), `room` (`average` with `depth`, or `box` with `width`, `length`, `orientation`), `height`, `wwr`, `roof_exposed`, `u_roof`, `floor_exposed`, `u_floor`, `ach_infiltration`.

**The default room.** The weights do not depend on the size of the room, only on its ratios: facade and window per m² of floor, volume per m² of floor. The default room ("average") is a square plan turned 45° with all four walls exposed and the same window share on each, so its windows face NE, SE, SW and NW and no direction is favoured. Its side is four times the room depth, which gives it the facade per m² of floor of a room that deep with one facade: 6 m deep is a 24 × 24 m square. An average room of depth d is the box of width and length 4d at orientation 45° whose north, east, south and west shares are the NE, SE, SW and NW ones. The explicit box (width, length, orientation, a share per wall) is the other kind of room.

**Roof and floor are adiabatic by default**: the room stands for a storey between others, and no heat passes through its ceiling and floor. A top storey or a floor over pilotis is turned on under Advanced, Roof and floor, with its own U.

The weights describe one room with the mean exposure of the building's facades. They are the same for every facade of the carved volume within an hour (the time of day carries the direction of the sun): a south facade and a north facade of the same building get the same weight in the same hour. Weights per facade direction (one room per orientation) are not in the app.

### The library

The library is apart from projects: the built-in examples, read-only, and the user's own entries, one YAML file each in `~/.urbansolarcarver/typical_buildings/` (beside the user preferences file), so an own entry serves every projects folder. A project keeps its own copy of the values and the name of the entry it came from; changing or deleting the entry does not change the project, and the sheet says "Changed from" the entry once the copy differs.

A new project has **no typical building** until one is chosen from the library: the box in the criterion's Settings says "None chosen", and a run with an energy-weighted criterion that is on is refused as a missing input (`missing_inputs` names `typical_building`) until one is chosen. A building stored with the keys of an earlier form of the values (before 2026-10-29) reads as none chosen, and an own entry with such keys is left out of the library.

The examples are grouped by the source of their values; the values come only from these examples, and the form offers no lists of standard values.

### The library examples

**Greece, KENAK reference building.** The eight examples "Apartment, zone Α" to "Office, zone Δ" take every value from the reference building of ΤΟΤΕΕ 20701-1/2017 (ΦΕΚ Β' 4003/17.11.2017, [PDF](https://web.tee.gr/wp-content/uploads/%CE%95%CE%93%CE%9A%CE%A1%CE%99%CE%A3%CE%97-TOTEE-1.pdf)); each example's source text names the tables:

| Value | Zone Α | Zone Β | Zone Γ | Zone Δ | ΤΟΤΕΕ 20701-1/2017 |
|-------|--------|--------|--------|--------|--------------------|
| U walls, W/m²K | 0.60 | 0.50 | 0.45 | 0.40 | table 3.4α (reference building, §4.2.1) |
| U roof, and floor over pilotis, W/m²K (when exposed) | 0.50 | 0.45 | 0.40 | 0.35 | table 3.4α |
| U windows, W/m²K | 3.20 | 3.00 | 2.80 | 2.60 | table 3.4α |
| Summer shading period (the cooling period) | 15 May to 15 Sep | 15 May to 15 Sep | 1 Jun to 31 Aug | 1 Jun to 31 Aug | §2.4.2 |

| Value | Apartment | Office | ΤΟΤΕΕ 20701-1/2017 |
|-------|-----------|--------|--------------------|
| Hours in use | Residential, 18 h every day (6:00 to 24:00) | Office, 10 h on weekdays (8:00 to 18:00) | table 2.1 (hours a day and days a week; which hours is the app's choice) |
| Set points | 20 / 26 °C | 20 / 26 °C | table 2.2 |
| Fresh air while in use | 0.75 m³/h per m² | 3.0 m³/h per m² | table 2.3 |
| Heat recovery | none (natural ventilation) | 0.5 | §4.4.1, reference ventilation |
| People | 4 W/m² | 8 W/m² | table 2.7 |
| Equipment × diversity | 4 × 0.5 = 2 W/m² | 15 × 0.3 = 4.5 W/m² | table 2.8 |
| Lighting | none (not counted for homes) | 16 W/m² (500 lx) | tables 2.4 and 2.4α |
| Internal gains while in use | 6 W/m² | 28.5 W/m² | the sum |
| Thermal capacity | 250 kJ/m²K | 250 kJ/m²K | §4.2.4 (ΚΕΝΑΚ article 9) |

The same for all eight: whole-window g 0.55 (glass 0.76 at normal incidence, × 0.9 for the mean over the angles, × 0.8 for a 20 % frame, §4.2.7); infiltration 5.5 m³/h per m² of window (§4.4.1), which in the examples' room is 115.2 m² of window × 5.5 / 1,728 m³ = 0.37 air changes per hour (the value the examples carry, to 2 decimals; a room of another depth or window share has another value); summer shading 0.77, the mean of the reference building's factors for NE, SE, SW and NW windows (0.80, 0.73, 0.73, 0.80, §4.3.1), over the zone's cooling period and none outside it; the average room 6 m deep with a 3 m storey, 40 % window share on each side, roof and floor adiabatic (their U values are the zone's, so turning them on gives the KENAK values). The 250 kJ/m²K takes the effective mass area of the ISO 13790 class nearest in capacity (heavy, 260).

The office lighting gain counts the reference building's full installed power, 16 W/m², in every hour of use. Daylight would lower it in a real office, so the office examples overstate the internal gains of sunny hours, and so the cooling and the harm.

On the bundled Golden, CO weather file the examples give (heating and cooling of the base run, and the hours with the sun up whose benefit weight is above 0.01, of 4,438):

| Example | Heating, kWh/m² a year | Cooling, kWh/m² a year | Hours that count |
|---------|-----------------------:|-----------------------:|-----------------:|
| Apartment, zone Α | 49.1 | 22.6 | 2,459 |
| Apartment, zone Β | 44.0 | 24.1 | 2,395 |
| Apartment, zone Γ | 40.0 | 27.3 | 2,258 |
| Apartment, zone Δ | 36.0 | 28.7 | 2,236 |
| Office, zone Α | 33.4 | 40.1 | 2,028 |
| Office, zone Β | 28.9 | 42.5 | 1,954 |
| Office, zone Γ | 25.5 | 46.6 | 1,899 |
| Office, zone Δ | 22.2 | 48.9 | 1,791 |

### Calculate

**Calculate** in the window runs `generate_simulated_weights` with the project's weather file into `inputs/typical_building/weights.json` (with `weights.png`) and shows **Effect of sunlight, by hour**: a day-by-hour chart of benefit minus harm when the criterion has `include_harm` (red where the sun offsets heating, blue where it adds to cooling), of benefit alone otherwise, with the hours that have the sun down (`meta["sun_up"]`) in grey; then the base run's annual heating and cooling demand, which the generator records in the artifact's `meta` (`heating_kwh_m2`, `cooling_kwh_m2`), and the hours that count. The calculation is keyed by a hash of the values and of the weather file: a change of either marks the weights out of date, and Run analysis calculates them again before it analyses an energy-weighted criterion, so a run never uses old weights. The generated `config.yaml` of such a criterion has `simulated_weights_path` and no `balance_temperature` or `balance_offset`. The explicit-area form, per-facade shading factors and uploading a ready weights file stay in the CLI and Grasshopper.

## Limitations

The weights are a *marginal, single-zone, schedule-free* physical signal. They capture effects the binary balance-point rule cannot (thermal lag, mass state, gain saturation), but the model makes the following simplifications on purpose:

- **Single zone, lumped mass**: the weights are facade-independent within an hour; time-of-day carries the directional signal. One room stands for the whole building (the app's average room has the mean exposure of its facades), not a room per facade direction. Perimeter-zone effects are out of scope for a massing tool.
- **Ideal, unlimited conditioning** at the air node, at constant set points: no setback. Internal gains and ventilation may follow an hourly schedule (the app's three example cases of use); infiltration and the set points do not.
- **Fixed air-change rates**: no night flushing, and no *adaptive* shading control. Without a declared `shading_hot` coefficient the `harm` channel is **overstated**, since real buildings have cheap defenses against summer sun that they lack for missing winter sun; declaring seasonal shading in the archetype makes harm a defensible estimate instead of a worst case. `include_harm` remains opt-in.
- **Schedules without holidays**: the app's example cases of use repeat every week of the year; the office lighting counts its full installed power in every hour of use, with no daylight.
- **Marginal linearization**: the weights describe one *extra* watt at the archetype's operating point; window sizes and g-values in the archetype set where gains saturate, and are recorded in the artifact's provenance metadata.
- **Unshaded derivation**: the weights are computed for an unshaded archetype while the carve itself creates shading context; a first-order acceptable inconsistency for massing studies.
- **TMY weather**; the ISO coupling coefficients carry the standard's residential-European calibration provenance.

!!! warning "Treat `include_harm` as a bracketing scenario"
    Without declared seasonal shading, harm is conservatively overstated (no night ventilation is modelled either), so the benefit-only weighting is the recommended default. Declaring `shading_hot` + `hot_months` in the archetype makes the harm channel a defensible estimate; even then, enable the subtraction deliberately for overheating-critical projects rather than as the standard mode.

## Traceability

Every artifact records its full provenance (`meta`: method, EPW, the complete expanded archetype, perturbation size, timestamp), and every carve that consumes one records that provenance in its preprocessing diagnostics. The artifact file is read again on every preprocessing run, so a regenerated artifact takes effect on the next run. With `diagnostic_plots: true`, the run also writes a comparison dome quantifying how the simulated weights shifted the sky relative to the simple rule under the same configuration.

## See also

- [Carving Modes: benefit](modes.md#simulated-weights) for the user-level workflow
- Tutorial 5 (`examples/5_benefit_5r1c.ipynb`) for an end-to-end walkthrough
- [API reference](api/simulated-weights.md) for `generate_simulated_weights()`, `ZoneParams`, and the artifact I/O
