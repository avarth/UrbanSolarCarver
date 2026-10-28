# Energy-weighted solar usefulness in the app

Date: 2026-10-28, revised the same day after the user's review of the first build. Status: design, waiting for the
user's approval.

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

- 5R1C does not appear in the app. Help text may say "a simple hourly model of one room (ISO 13790)".
- In a Solar usefulness criterion: **Which hours count**, **Cold hours** (default) or **Energy-weighted**.
- The building is the **Typical building**, edited in a sheet opened by **Edit building**.

## Decisions by the user

1. One typical building per project (uses per context volume later).
2. Calculated in the sheet (**Calculate**) and again by Run analysis when the building or the weather file changed.
3. A **library** of typical buildings, independent of projects, replaces "Start from". It ships read-only examples; the
   user saves their own and reuses them in any project.
4. Examples: an apartment and an office for each of the four Greek climate zones (KENAK), plus the ASHRAE 140 test boxes.
   All KENAK values are those of the **reference building** of ΤΟΤΕΕ 20701-1/2017.
5. The default room is a statistical middle case: a room turned 45° with the same window share on all four sides, 40 %.
   Floor and ceiling are adiabatic; an exposed roof or floor, with its own U, is an advanced setting.
6. Geometry and window shares are advanced settings, not basic ones.
7. Keep it simple before a full energy-simulation interface: schedules are a choice among a few typical cases, not an
   editor; summer shading is one factor and a period.
8. Thermal mass: the ISO 13790 classes stay; the ΤΟΤΕΕ categories (table 3.14) are offered as the other way to give it.

## The building model

A single zone, the ISO 13790 hourly model, with these inputs:

| Group | Values |
|-------|--------|
| Use | the schedule (a typical case), set points, internal gains while in use (W/m²), fresh air while in use (m³/h per m² of floor), heat recovery |
| Fabric | U of the walls and of the windows; thermal mass (an ISO class or a ΤΟΤΕΕ category); whole-window g |
| Room (advanced) | storey height, depth of the room from its facades, window share per side (NE, SE, SW, NW for the default room), turn |
| Roof and floor (advanced) | roof exposed (yes/no) with its U; floor exposed (yes/no) with its U; adiabatic by default |
| Air (advanced) | infiltration, m³/h per m² of window |
| Summer shading | one factor for the windows during a period of dates; none outside it |

- **The room.** The weights do not depend on the size of the room, only on ratios. The default room is a square plan
  turned 45° with all four walls exposed and the same window share on each; its side is four times the room depth, so it
  has the facade per m² of floor of a room that deep with one facade (6 m deep: a 24 × 24 m square, 3 m storey). Its
  windows face NE, SE, SW and NW, so no direction is favoured.
- **Schedules (typical cases):** "Apartment: 6:00 to 24:00 every day" (18 h, 7 days, ΤΟΤΕΕ table 2.1), "Office: 8:00 to
  18:00 Monday to Friday" (10 h, 5 days, table 2.1), "Always" (for the ASHRAE boxes). ΤΟΤΕΕ gives the number of hours,
  not which hours; the hours of day are my call. Internal gains and fresh air apply in the hours of the schedule;
  infiltration applies always. The weekday of 1 January comes from the weather file's header (Monday when it gives none).
- **Thermal mass:** either an ISO 13790 class (very light 80, light 110, medium 165, heavy 260, very heavy 370 kJ/m²K)
  or a ΤΟΤΕΕ category (1: 80, 2: 110, 3: 165, 4: 230, 5: 280, 6: 300 kJ/m²K, with the table's construction descriptions).
  A ΤΟΤΕΕ category takes the effective mass area of the ISO class nearest in capacity.

## Library examples

### KENAK reference building, ΤΟΤΕΕ 20701-1/2017

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
| Schedule | Apartment (18 h, every day) | Office (10 h, weekdays) | 2.1 |
| Set points | 20 / 26 °C | 20 / 26 °C | 2.2 |
| Fresh air while in use | 0.75 m³/h per m² | 3.0 m³/h per m² | 2.3 |
| Heat recovery | none (natural ventilation) | 0.5 | §4.4.1, reference ventilation |
| People | 4 W/m² | 8 W/m² | 2.7 |
| Equipment × diversity | 4 × 0.5 = 2 W/m² | 15 × 0.3 = 4.5 W/m² | 2.8 |
| Lighting | none (not counted for homes) | 16 W/m² (500 lx, reference building) | 2.4, 2.4α |
| Internal gains while in use | 6 W/m² | 28.5 W/m² | sum |
| Thermal mass | ΤΟΤΕΕ category 5: concrete frame, hollow clay bricks, 280 kJ/m²K | category 3: concrete frame, light infill, suspended ceilings, 165 kJ/m²K | 3.14 (my choice of category) |

The same for all KENAK examples:

- Whole-window g 0.55: glass 0.76 at normal incidence, × 0.9 mean, × 0.8 for a 20 % frame (§4.2.7, reference building).
- Infiltration 5.5 m³/h per m² of window (§4.4.1, reference building).
- Summer shading of the windows (reference building, §4.3.1): S 0.70, SE and SW 0.73, E and W 0.75, NE and NW 0.80,
  N 1.00. For the default room (NE, SE, SW, NW): their mean, 0.77. No shading outside the period.
- Room: 6 m deep, 3 m storey, 40 % window share on each side, roof and floor adiabatic.

The office lighting gain counts the reference building's full installed power in every hour of use; daylight would
reduce it. The docs say so.

### ASHRAE Standard 140, cases 600 and 900

A free-standing box 8 × 6 × 2.7 m, walls and roof exposed, 12 m² of glass on the south wall only, floor insulated. Case 600
is lightweight, case 900 heavyweight. Constant internal gains, infiltration only, set points of the test case. Its values
are taken from a published description of the test and checked there before use; the library entry names its source. Its
room fields are the explicit box (it is not the default room).

## The library

- Stored apart from projects: one YAML file per building in the user's app folder (next to the user preferences), so it
  serves every project folder.
- Examples ship with the app, read-only, grouped as Apartment, Office and Test boxes; the zone is part of the name
  ("Apartment, zone Β").
- A project keeps its own copy of the building and the name of the library entry it came from. Changes in the library do
  not change a project; the sheet says "Changed from Apartment, zone Β" once the copy differs.
- In the sheet: the library list (choose one: the project's copy is replaced), **Save to library** (overwrite the entry it
  came from, when it is the user's own), **Save as new** (asks a name). Deleting and renaming own entries is in the list.
- A new project uses "Apartment, zone Β" (my call; the user changes it once and the project keeps it).

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
- Docs: `docs/simulated-weights.md` (the room convention, the adiabatic default, the ΤΟΤΕΕ sources table by table, ISO
  13790 replaced by EN ISO 52016-1, the facade-independent weights as a limit), `docs/ui.md`, `docs/modes.md`, CHANGELOG.
