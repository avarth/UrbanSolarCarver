# Energy-weighted solar usefulness in the app

Date: 2026-10-28. Status: design, waiting for the user's approval.

## Intent

Benefit mode ("Solar usefulness" in the app) counts the sun of the hours colder than the balance temperature. The engine can
instead weight every hour by what its sun saves a typical building in heating over the year (`simulated_weights.py`, the
ISO 13790 hourly model, validated against RC_BuildingSimulator). The app has never offered this: the service never sets
`simulated_weights_path`. The user wants it in the app as a form where a typical building is described, after which the app
calculates the hourly weights (user, 2026-10-28: "a submenu to calculate simulated weights after the user fill an archetype
form"). Uploading a ready `simulated_weights.json` is off the table.

## Names in the app

- The model's name, 5R1C, does not appear in the app (user). Help text may say "a simple hourly model of one room
  (ISO 13790)".
- In a Solar usefulness criterion, a two-way switch **Which hours count**: **Cold hours** (the balance temperature rule,
  as today, the default) or **Energy-weighted** (the typical building).
- The building is the **Typical building**; its form opens from an **Edit building** button under the switch.

## Decisions by the user

1. One typical building per project, shared by every energy-weighted criterion. Later, uses may be assigned to context
   volumes; not now.
2. The weights are calculated in the form (a **Calculate** button, with a chart and numbers) and again by Run analysis on
   its own when the building or the weather file changed since, so a run never uses old weights.
3. **Start from** offers three plain types based on the three cases the engine was validated on.

## The form

A sheet beside the criterion panel, in the way the Simulate study popover sits beside its list. Folded groups with a
one-line summary each, as in the criterion panel:

| Group | Values (archetype keys) |
|-------|-------------------------|
| Shape | width, length, storey height (m), orientation (degrees clockwise from north) |
| Windows | window share of the wall per side, north / east / south / west (0 to 0.9); glass solar transmittance g |
| Walls and glass | U of the walls and roof, U of the glass (W/m²K); thermal mass (very light, light, medium, heavy, very heavy) |
| Air | ventilation and infiltration (air changes per hour); heat recovery (0 to 1) |
| Use | heating and cooling set points (°C); internal gains by day and by night (W/m²; day is 8:00 to 20:00) |
| Summer shading | permanent shading factor (0 to 1, 1 = none); summer shading factor and its months |

- Only the shoebox form of the archetype. The explicit-area form stays in the CLI and Grasshopper.
- Gains by day and by night are written as the 24-value profile `internal_gains_profile_w_m2`; equal values give a flat
  profile.
- Each value is checked as the engine checks it (`expand_shoebox`, `ZoneParams.from_archetype`, `_shading_factors`); an
  error is shown at its field.
- Below the groups: **Calculate**, then a chart of the weight of each hour (day of the year across, hour of the day down,
  viridis, 0 to 1), a second chart for harm when the criterion counts harm, and three numbers: heating and cooling of the
  typical building in kWh/m² a year, and the hours whose weight is above 0.01.
- While the building differs from the one the weights were calculated for, the chart is dimmed with "Calculate again"
  (the way out-of-date studies are muted in Simulate).

### Start from (my call on the geometry)

The validation cases are given as areas. Their U values, air, mass and set points are kept; their floor area and volume
become a box, and their window areas become window shares:

| Type | Box (m) | Window share | U walls / glass | Air (vent + infiltration), recovery | Mass | Gains day / night (W/m²) |
|------|---------|--------------|-----------------|------------------------------|------|--------------------------|
| Office, medium mass | 5 × 7 × 3 | S 0.27, E 0.10, W 0.10 | 0.5 / 1.8 | 1.2 + 0.3, 0 | medium | 7.1 / 1.7 |
| Older home, heavy masonry | 5 × 8 × 2.75 | S 0.15, E 0.05, W 0.05, N 0.07 | 1.2 / 2.8 | 0.8 + 0.5, 0 | heavy | 5 / 5 |
| Light, well-insulated home | 5 × 6 × 3 | S 0.4, W 0.22 | 0.25 / 1.0 | 1.5 + 0.2, 0.6 | light | 5 / 5 |

Set points 20 / 26 °C and g 0.6 for all three. The validation cases used office gains (250 W by day, 60 W at night) for
all three; the two homes get the engine's default 5 W/m² instead (my call). A new project starts with the office type.

## Service

- `project.json` gets `typical_building`: the archetype values (shoebox keys), the type it started from, and, once
  calculated, the key of the calculation: a hash of the archetype values and the weather file's fingerprint.
- The weights are written to `inputs/typical_building/weights.json` (and the engine's heatmap PNG beside it).
- Routes: read and save the building (validated); `POST .../typical-building/calculate` runs
  `generate_simulated_weights` (about 9 s on the Golden weather file) and answers with the weights (benefit and harm,
  8,760 values each, 3 decimals) and the three numbers. Without a weather file it refuses with the existing "add a
  weather file" message.
- A criterion's Which hours count is stored as a browser setting translated by the service: for Energy-weighted, the
  generated `config.yaml` gets `simulated_weights_path: inputs/typical_building/weights.json` and leaves out
  `balance_temperature` and `balance_offset` (the engine warns when both are given); the stored balance values are kept,
  so switching back restores them.
- Run analysis: when a criterion that is on is energy-weighted and the weights are missing or their key differs, the run
  calculates them first, as a step of the run's progress ("Typical building").
- Out of date: a criterion's preprocessing record keeps the key of the weights it ran with; another key dates its
  preprocessing (and through it what follows, as today). Switching Which hours count changes `simulated_weights_path`,
  which the engine's own settings comparison already catches. A weather change already dates everything.

## Engine (small change)

`generate_simulated_weights` also records the base run's annual heating and cooling demand in the file's `meta`
(`heating_kwh_m2`, `cooling_kwh_m2`), so the service reads the numbers from the file instead of simulating again.

## Unchanged

- Analysis period and Count harm work as today; with Energy-weighted, Count harm subtracts the building's cooling share.
- The cold period preset still describes the cold hours rule; its help says so when the criterion is energy-weighted.
- CLI, Grasshopper and config files.

## Not now

Uses per context volume; national presets (TABULA); the explicit-area form; uploading a weights file; a cold period from
the simulation.

## Tests

- Service: save and validate the building (one bad value per group); calculate writes the file and answers the numbers;
  calculate without weather refuses; config.yaml of an energy-weighted criterion has the path and no balance values;
  a run with stale weights recalculates them first; a changed building dates only the energy-weighted criteria.
- Engine: the meta numbers match `simulate()` of the base run.
- App: the switch hides the balance temperature; Edit building opens the sheet; Start from fills the values; a field error
  shows at its field; Calculate shows the chart and numbers; a change after Calculate dims the chart.
- Docs: `docs/ui.md`, `docs/simulated-weights.md` (a section on the app), `docs/modes.md`, CHANGELOG.
