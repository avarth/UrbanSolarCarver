# Energy-weighted solar usefulness in the app

Date: 2026-10-28, revised the same day after the user's review of the first build, and again on 2026-10-29: the app is for
international use, so the Greek regulation is only the source of some library examples, never part of the model, the value keys,
the form, the help texts or the defaults (user, 2026-10-29). Status: design, waiting for the user's approval.

## Intent

Benefit mode ("Solar usefulness" in the app) counts the sun of the hours colder than the balance temperature. The engine can
instead weight every hour by what its sun saves a typical building in heating over the year (`simulated_weights.py`, the
ISO 13790 hourly model, validated against RC_BuildingSimulator). The app gets this as a form where a typical building is
described, after which the app calculates the hourly weights (user, 2026-10-28). Uploading a ready weights file is off the
table.

The first build (`c975f93`, `2fc976e`) worked but its building was a poor model (user review, 2026-10-28): a box with
width, length and orientation, one U for walls and roof, an unshaded summer, presets that mixed age with construction, and
a "Start from" list. This revision replaces the building model and the presets; the switch in the criterion, the
calculation, the run step and the out-of-date rules of the first build stay.

## Names in the app

- 5R1C does not appear in the app. Help text says "a simple hourly model of one room" and names no standard.
- In a Solar usefulness criterion: **Which hours count**, **Cold hours** (default) or **Energy-weighted**.
- The building is the **Typical building**, edited in a sheet opened by **Edit building**.

## Decisions by the user

1. One typical building per project (uses per context volume later).
2. Calculated in the sheet (**Calculate**) and again by Run analysis when the building or the weather file changed.
3. A **library** of typical buildings, independent of projects, replaces "Start from". It ships read-only examples; the
   user saves their own and reuses them in any project.
4. Examples: an apartment and an office for each of the four Greek climate zones (KENAK), plus the ASHRAE 140 test boxes.
   All KENAK values are those of the **reference building** of ΤΟΤΕΕ 20701-1/2017. The regulation is named only in the
   examples' group and source text and in the docs' section on the examples.
5. The default room is a statistical middle case: a room turned 45° with the same window share on all four sides.
   Floor and ceiling are adiabatic; an exposed roof or floor, with its own U, is an advanced setting.
6. Geometry and window shares are advanced settings, not basic ones.
7. Keep it simple before a full energy-simulation interface: schedules are a choice among three example cases with plain
   descriptions of their hours, not an editor; summer shading is one factor and a period.
8. Thermal mass is one number, the thermal capacity in kJ/m²K of floor. The form offers no lists of standard values (no
   ISO classes, no categories of a national table): values come from the library's examples or from the user (user,
   2026-10-29).
9. A new project has no typical building until one is chosen from the library; a run with an energy-weighted criterion
   that is on is refused without one, as a missing input (user, 2026-10-29).
10. Help texts say what a value means and its unit; they cite no standard or table.

## The building model

A single zone, the ISO 13790 hourly model, with these inputs:

| Group | Values |
|-------|--------|
| Use | the schedule (a typical case), set points, internal gains while in use (W/m²), fresh air while in use (m³/h per m² of floor), heat recovery |
| Fabric | U of the walls and of the windows; thermal capacity, kJ/m²K of floor; whole-window g |
| Room (advanced) | storey height, depth of the room from its facades, window share per side (NE, SE, SW, NW for the default room), turn |
| Roof and floor (advanced) | roof exposed (yes/no) with its U; floor exposed (yes/no) with its U; adiabatic by default |
| Air (advanced) | infiltration, air changes per hour |
| Summer shading | one factor for the windows during a period of dates; none outside it |

- **The room.** The weights do not depend on the size of the room, only on ratios. The default room is a square plan
  turned 45° with all four walls exposed and the same window share on each; its side is four times the room depth, so it
  has the facade per m² of floor of a room that deep with one facade (6 m deep: a 24 × 24 m square, 3 m storey). Its
  windows face NE, SE, SW and NW, so no direction is favoured.
- **Schedules (example cases):** "Residential: 6:00 to 24:00 every day", "Office: 8:00 to 18:00, Monday to Friday" and
  "Always" (keys `residential`, `office`, `always`). Internal gains and fresh air apply in the hours of the schedule;
  infiltration applies always. The weekday of 1 January comes from the weather file's header (Monday when it gives none).
- **Thermal mass:** the thermal capacity in kJ/m²K of floor (`mass_capacity_kj_m2k`). The model takes the effective mass
  area of the ISO 13790 class nearest in capacity; that is part of the model, not a choice in the form. The engine keeps
  its classes for the CLI and Grasshopper.
- **Infiltration:** in air changes per hour (`ach_infiltration`), in every hour.
- **Value keys:** `schedule`, `t_set_heating`, `t_set_cooling`, `gains_w_m2`, `fresh_air_m3h_m2`, `heat_recovery`,
  `u_wall`, `u_window`, `g_value`, `mass_capacity_kj_m2k`, `shading_factor`, `shading_start`, `shading_end`, `room`
  (`average` with `depth`, `box` with `width`, `length`, `orientation`), `height`, `wwr`, `roof_exposed`, `u_roof`,
  `floor_exposed`, `u_floor`, `ach_infiltration`. A building stored with the keys of an earlier form reads as none chosen.

## Library examples

### Greece, KENAK reference building (ΤΟΤΕΕ 20701-1/2017)

Values that change with the climate zone:

| | Α | Β | Γ | Δ | Source |
|---|---|---|---|---|---|
| U walls, W/m²K | 0.60 | 0.50 | 0.45 | 0.40 | table 3.4α (reference building, §4.2.1) |
| U roof, W/m²K (when exposed) | 0.50 | 0.45 | 0.40 | 0.35 | 3.4α |
| U floor over pilotis, W/m²K (when exposed) | 0.50 | 0.45 | 0.40 | 0.35 | 3.4α |
| U windows, W/m²K | 3.20 | 3.00 | 2.80 | 2.60 | 3.4α |
| Summer shading period (cooling period) | 15 May to 15 Sep | 15 May to 15 Sep | 1 Jun to 31 Aug | 1 Jun to 31 Aug | §2.4.2 |

Values that change with the use:

| | Apartment | Office | Source |
|---|---|---|---|
| Schedule | Residential (18 h, every day) | Office (10 h, weekdays) | 2.1 (hours a day and days a week; which hours is my call) |
| Set points | 20 / 26 °C | 20 / 26 °C | 2.2 |
| Fresh air while in use | 0.75 m³/h per m² | 3.0 m³/h per m² | 2.3 |
| Heat recovery | none (natural ventilation) | 0.5 | §4.4.1, reference ventilation |
| People | 4 W/m² | 8 W/m² | 2.7 |
| Equipment × diversity | 4 × 0.5 = 2 W/m² | 15 × 0.3 = 4.5 W/m² | 2.8 |
| Lighting | none (not counted for homes) | 16 W/m² (500 lx, reference building) | 2.4, 2.4α |
| Internal gains while in use | 6 W/m² | 28.5 W/m² | sum |
| Thermal capacity | 250 kJ/m²K (reference building) | 250 kJ/m²K (reference building) | §4.2.4 (ΚΕΝΑΚ article 9) |

The same for all KENAK examples:

- Whole-window g 0.55: glass 0.76 at normal incidence, × 0.9 mean, × 0.8 for a 20 % frame (§4.2.7, reference building).
- Infiltration 5.5 m³/h per m² of window (§4.4.1, reference building): in the examples' room, 115.2 m² of window × 5.5 /
  1,728 m³ = 0.37 air changes per hour, the value they carry; their source text says so.
- Summer shading of the windows (reference building, §4.3.1): S 0.70, SE and SW 0.73, E and W 0.75, NE and NW 0.80,
  N 1.00. For the default room (NE, SE, SW, NW): their mean, 0.77. No shading outside the period.
- Room: 6 m deep, 3 m storey, 40 % window share on each side, roof and floor adiabatic.

The office lighting gain counts the reference building's full installed power in every hour of use; daylight would
reduce it. The docs say so.

### ASHRAE 140 test cases, 600 and 900

A free-standing box 8 × 6 × 2.7 m, walls and roof exposed, 12 m² of glass on the south wall only, floor insulated. Case 600
is lightweight, case 900 heavyweight. Constant internal gains, infiltration only, set points of the test case. Its values
are taken from a published description of the test and checked there before use; the library entry names its source. Its
room fields are the explicit box (it is not the default room). Infiltration 0.5 air changes per hour; thermal capacity 80
kJ/m²K (case 600) and 260 kJ/m²K (case 900), those of the ISO classes very light and heavy, stated in the source text.

## The library

- Stored apart from projects: one YAML file per building in the user's app folder (next to the user preferences), so it
  serves every project folder.
- Examples ship with the app, read-only, grouped by the source of their values: "Greece, KENAK reference building" (the
  zone is part of the name: "Apartment, zone Β", "Office, zone Β") and "ASHRAE 140 test cases"; then "Your buildings". The
  service names the groups; the app has no list of them.
- A project keeps its own copy of the building and the name of the library entry it came from. Changes in the library do
  not change a project; the sheet says "Changed from Apartment, zone Β" once the copy differs.
- In the sheet: the library list (choose one: the project's copy is replaced), **Save to library** (overwrite the entry it
  came from, when it is the user's own), **Save as new** (asks a name). Deleting and renaming own entries is in the list.
- A new project has no typical building ("None chosen"). The box in the criterion's Settings asks to choose one and opens
  the sheet on the library; the sheet shows only the library until one is chosen, so Calculate is not offered; the
  project's building reply has null values and the state `not_chosen`; a run with an energy-weighted criterion that is on
  is refused as a missing input (`typical_building`), with a message naming the typical building.

## The sheet

- Library list at the top, then the basic groups (Use, Fabric, Summer shading) with one-line summaries, then an
  **Advanced** fold (Room, Roof and floor, Air).
- **Calculate** below, then one chart and three numbers.
- The chart: day of the year across, hour of the day down; one diverging scale, red for the share of the sun that offsets
  heating, white for no effect, blue for the share that adds to cooling (benefit minus harm). With Count harm off, the red
  half only. Hours with the sun below the horizon are grey. Title "Effect of sunlight, by hour"; legend ends "offsets
  heating" and "adds to cooling".
- Numbers: heating and cooling of the typical building, kWh/m² a year, and the hours with the sun up whose weight is above
  0.01 ("Hours that count", daytime only).
- The sheet no longer covers the "Out of date" banner of the 3D view (the banner moves beside the sheet while it is open).

## Engine changes

1. Schedules: hourly internal gains and hourly fresh air (8,760 values each); the zone's ventilation conductance becomes an
   hourly series, infiltration constant. The 24-value profile and the flat value still work (CLI, Grasshopper).
2. Separate U values for walls, roof and floor, with roof and floor exposure switches (the shoebox today counts the roof at
   the wall U and leaves out the floor). The old keys keep their meaning.
3. Thermal capacity in kJ/m²K as the alternative to the mass class.
4. Summer shading by a period of dates (day of year) as the alternative to whole months; one factor for all windows.
5. The meta of the weights file records which hours have the sun up (for the grey hours and the daytime count).

## Service and app changes from the first build

- `typical_building.py`: the new values, the library (read, save, save as new, delete, rename; examples read-only), the
  project's copy with its library name; validation per field as before.
- The sheet as above; the "Start from" list goes.
- Unchanged: the criterion switch, the box in Settings, Calculate and its route, the run step "Typical building", the
  out-of-date rules, the hidden balance temperature.

## Not now

Uses per context volume; per-orientation weights (one room per facade direction, Shoeboxer); a schedule editor; shading
per orientation in the sheet; other countries' tables; the explicit-area form in the app.

## Tests

- Engine: hourly gains and ventilation equal the flat case when constant; roof and floor exposure add their U × area;
  capacity in kJ/m²K equals the matching class; a date period equals the months it spans.
- Service: the library (examples read-only, save, save as new, delete, rename; a project's copy survives a library change);
  every example validates and calculates (slow); field errors per value.
- App: library choice replaces the copy and shows "Changed from"; Advanced fold; the diverging chart with grey night hours;
  the banner beside the open sheet.
- Docs: `docs/simulated-weights.md` (the room convention, the adiabatic default, the facade-independent weights as a
  limit, ISO 13790 replaced by EN ISO 52016-1; the ΤΟΤΕΕ sources table by table only in the section on the library
  examples), `docs/ui.md`, `docs/modes.md`, CHANGELOG.
