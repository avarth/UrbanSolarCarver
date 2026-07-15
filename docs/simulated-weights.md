# Simulated Benefit Weights

Benefit mode's optional simulated weighting embeds a small building-simulation engine inside USC. Because a simulation engine carries physics assumptions that a geometric tool otherwise would not, this page documents the engine, its origin, how it was validated, what the user supplies, and where its limits are.

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

Attributing against the annual totals is what captures **thermal lag**: a noon gain stored in the mass and released into the cold evening still earns heating credit. All 17,521 perturbed year-simulations run as one vectorized NumPy batch, in seconds.

## Origin and validation

The engine is an **independent implementation**, written directly from the ISO 13790 Annex C equation set in pure NumPy (`urbansolarcarver/simulated_weights.py`, ~450 lines). It is **not** a fork, port, or adaptation of an existing simulator.

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

**Both forms** additionally take: `u_opaque`, `u_window` (W/m²K), `ach_vent`, `ach_infiltration` (1/h), `heat_recovery` (0-1), `mass_class` (`very_light` … `very_heavy`, ISO 13790 Table 12), `t_set_heating`, `t_set_cooling` (°C), and internal gains as either a flat `internal_gains_w_m2` or a 24-value daily profile.

The shipped example values are deliberately **neutral, with no national defaults**. For real projects, source values from [TABULA](https://episcope.eu/building-typology/) (EU building-stock typologies), DOE prototype buildings (US), or your national code tables.

## Limitations

The weights are a *marginal, single-zone, schedule-free* physics signal. That is a large step past the binary balance-point rule (thermal lag, mass state, gain saturation), but the following simplifications are declared and deliberate:

- **Single zone, lumped mass**: the weights are facade-independent within an hour; time-of-day carries the directional signal. Perimeter-zone effects are out of scope for a massing tool.
- **Ideal, unlimited conditioning** at the air node; continuous operation, no setback or occupancy schedules.
- **Fixed air-change rates**: no night flushing and no operable shading. Consequently the `harm` channel is **overstated**, since real buildings have cheap defenses against summer sun that they lack for missing winter sun. This is why `include_harm` is opt-in and marked experimental.
- **Flat (or simple daily-profile) internal gains.**
- **Marginal linearization**: the weights describe one *extra* watt at the archetype's operating point; window sizes and g-values in the archetype set where gains saturate, and are recorded in the artifact's provenance metadata.
- **Unshaded derivation**: the weights are computed for an unshaded archetype while the carve itself creates shading context; a first-order acceptable inconsistency for massing studies.
- **TMY weather**; the ISO coupling coefficients carry the standard's residential-European calibration provenance.

!!! warning "Treat `include_harm` as a bracketing scenario"
    Because harm is conservatively overstated (no shading, no night ventilation), the benefit-only weighting is the recommended default; enable the harm subtraction to bracket overheating-critical projects, not as the standard mode.

## Traceability

Every artifact records its full provenance (`meta`: method, EPW, the complete expanded archetype, perturbation size, timestamp), and every carve that consumes one records that provenance in its preprocessing diagnostics. The sky-weight cache keys on the artifact's *content*, so regenerating it with a different archetype can never yield stale results. With `diagnostic_plots: true`, the run also writes a comparison dome quantifying how the simulated weights shifted the sky relative to the simple rule under the same configuration.

## See also

- [Carving Modes -- benefit](modes.md#simulated-weights) for the user-level workflow
- Tutorial 5 (`examples/5_benefit_5r1c.ipynb`) for an end-to-end walkthrough
- [API reference](api/simulated-weights.md) for `generate_simulated_weights()`, `ZoneParams`, and the artifact I/O
