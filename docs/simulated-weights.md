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

In the browser app a Solar usefulness criterion offers the weights as **Which hours count**: **Energy-weighted** (the other choice, **Cold hours**, is the balance temperature rule). The app describes the model as a simple hourly model of one room (ISO 13790) and does not use the name 5R1C, which stays the engine's. A project has one **typical building**, the archetype of every energy-weighted criterion, edited in a sheet beside the criterion's panel ([Browser UI: the typical building](ui.md#the-typical-building)).

The sheet edits the shoebox form only, in six groups: Shape (`width`, `length`, `height`, `orientation`), Windows (`wwr` of each side, 0 to 0.9, and `g_value`), Walls and glass (`u_opaque`, `u_window`, `mass_class`), Air (`ach_vent`, `ach_infiltration`, `heat_recovery`), Use (`t_set_heating`, `t_set_cooling`, and internal gains by day and by night, written as the 24-value `internal_gains_profile_w_m2` with the day value from 8:00 to 20:00, or a flat `internal_gains_w_m2` when the two are equal) and Summer shading (`shading_permanent`, `shading_hot` and `hot_months`, each factor one value for all facades). Each value is checked as the engine checks it (`expand_shoebox`, `ZoneParams.from_archetype`, the shading factors), and an error is shown at its field. The explicit-area form, per-facade shading factors and uploading a ready weights file stay in the CLI and Grasshopper.

**Start from** offers three types based on the validation scenarios. Their U values, air, mass and set points are the scenarios'; their floor area and volume became a box, and their window areas window shares:

| Type | Box (m) | Window share | U walls / glass (W/m²K) | Air (vent + infiltration, 1/h), recovery | Mass | Gains day / night (W/m²) |
|------|---------|--------------|-------------------------|------------------------------------------|------|--------------------------|
| Office, medium mass | 5 × 7 × 3 | S 0.27, E 0.10, W 0.10 | 0.5 / 1.8 | 1.2 + 0.3, 0 | medium | 7.1 / 1.7 |
| Older home, heavy masonry | 5 × 8 × 2.75 | S 0.15, E 0.05, W 0.05, N 0.07 | 1.2 / 2.8 | 0.8 + 0.5, 0 | heavy | 5 / 5 |
| Light, well-insulated home | 5 × 6 × 3 | S 0.4, W 0.22 | 0.25 / 1.0 | 1.5 + 0.2, 0.6 | light | 5 / 5 |

All three have set points of 20 and 26 °C, g = 0.6, orientation 0 and no shading. The scenarios used office gains (250 W by day, 60 W at night on 35 m²) for all three; the two homes take the engine's default 5 W/m² instead. On the bundled Golden, CO weather file their base runs need 189.5, 314.8 and 58.8 kWh/m² of heating and 26.9, 6.8 and 91.9 kWh/m² of cooling a year, and 7,082, 7,501 and 5,591 hours have a benefit weight above 0.01.

**Calculate** in the sheet runs `generate_simulated_weights` with the project's weather file into `inputs/typical_building/weights.json` (with `weights.png`) and shows the benefit weights of each hour as a day-by-hour chart, the harm weights too when the criterion has `include_harm`, and the base run's annual heating and cooling demand, which the generator records in the artifact's `meta` (`heating_kwh_m2`, `cooling_kwh_m2`). The calculation is keyed by a hash of the values and of the weather file: a change of either marks the weights out of date, and Run analysis calculates them again before it analyses an energy-weighted criterion, so a run never uses old weights. The generated `config.yaml` of such a criterion has `simulated_weights_path` and no `balance_temperature` or `balance_offset`.

## Limitations

The weights are a *marginal, single-zone, schedule-free* physical signal. They capture effects the binary balance-point rule cannot (thermal lag, mass state, gain saturation), but the model makes the following simplifications on purpose:

- **Single zone, lumped mass**: the weights are facade-independent within an hour; time-of-day carries the directional signal. Perimeter-zone effects are out of scope for a massing tool.
- **Ideal, unlimited conditioning** at the air node; continuous operation, no setback or occupancy schedules.
- **Fixed air-change rates**: no night flushing, and no *adaptive* shading control. Without a declared `shading_hot` coefficient the `harm` channel is **overstated**, since real buildings have cheap defenses against summer sun that they lack for missing winter sun; declaring seasonal shading in the archetype makes harm a defensible estimate instead of a worst case. `include_harm` remains opt-in.
- **Flat internal gains, or one 24-hour profile repeated every day.**
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
