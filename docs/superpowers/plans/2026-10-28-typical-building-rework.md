# Typical building rework: implementation plan

**Goal:** replace the first build's typical building (box, one U, "Start from") with the revised design: a library apart
from projects, KENAK reference-building examples for zones Α to Δ and the ASHRAE 140 boxes, the 45° default room, typical
schedules, and one diverging chart.

**Spec:** `docs/superpowers/specs/2026-10-28-energy-weighted-benefit-design.md` (revised; the authority). The first build's
plan, `2026-10-28-energy-weighted-benefit.md`, describes what stays (criterion switch, Calculate, run step, out-of-date).

**Branch:** `feature/energy-weighted-benefit`. Source of the KENAK values: ΤΟΤΕΕ 20701-1/2017 (ΦΕΚ Β' 4003/17.11.2017),
https://web.tee.gr/wp-content/uploads/%CE%95%CE%93%CE%9A%CE%A1%CE%99%CE%A3%CE%97-TOTEE-1.pdf ; the spec's tables give
every value with its table number.

## Global constraints

As in the first plan: no "5R1C" in app text; plain words with numbers, no em dashes, no pompous labels; match the
surrounding code; test tiers of CLAUDE.md; commit trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
never `git stash`; leave `examples/test_inputs/Real_world_examples/` out; CRLF files are not edited with `sed -i`.
The branch is not merged, so the first build's project.json shape and routes may change freely (no migration).

## Task 1: engine and service

### Engine (`simulated_weights.py`, `archetype_defaults.py`); old keys keep their meaning (CLI, Grasshopper, tests)

1. `internal_gains_w_m2` also takes 8,760 values; `ach_vent` also takes 8,760 values (the ventilation conductance becomes
   hourly in `_hourly_constants` / `_march`; `ach_infiltration` stays one value; heat recovery applies to the ventilation
   part of each hour). A constant series gives the same result as the flat value (test).
2. Shoebox keys `u_wall`, `u_roof`, `u_floor`, `roof_exposed` (default true for the old shoebox, which counted the roof),
   `floor_exposed` (default false). With `u_wall` given, H_op = u_wall × walls + u_roof × roof (if exposed) + u_floor ×
   floor (if exposed); `u_opaque` keeps the old meaning (walls and roof at one U). Giving both is an error.
3. `mass_capacity_kj_m2k` as the alternative to `mass_class`: C_m = value × 1000 × floor area; A_m from the ISO class
   nearest in capacity. Both given is an error.
4. `shading_hot_period: [first_day, last_day]` (day of year 1 to 365, inclusive, may wrap the new year) as the
   alternative to `hot_months`.
5. `meta["sun_up"]`: 8,760 values 0/1, the hours with the sun above the horizon at the EPW site (ladybug Sunpath at the
   middle of each hour, as `transmitted_solar_from_epw` places the hour).

### Service (`local_web_service/typical_building.py` and its routes; replace the first build's values and presets)

6. The values the app edits (stored per project and per library entry):
   `schedule` ("apartment" | "office" | "always"), `t_set_heating`, `t_set_cooling`, `gains_w_m2` (while in use),
   `fresh_air_m3h_m2` (while in use), `heat_recovery`, `u_wall`, `u_window`, `g_value`, `mass_kind` ("iso" | "totee"),
   `mass_class` (ISO name) or `totee_category` (1 to 6), `shading_factor` (null = none), `shading_start` and
   `shading_end` ("MM-DD"), `room` ("average" | "box"), `height`, `depth` (average room), `width`, `length`,
   `orientation` (box), `wwr` (average: `ne, se, sw, nw`; box: `north, east, south, west`), `roof_exposed`, `u_roof`,
   `floor_exposed`, `u_floor`, `infiltration_m3h_m2_window`. `archetype_of(values, epw_path)` builds the engine archetype:
   the average room is a square of side 4 × depth turned 45° with all four walls; fresh air m³/h per m² over the storey
   height gives ach; infiltration m³/h per m² of window × window area / volume gives ach; the schedule gives the hourly
   gains and fresh air (hours of use: apartment 6:00 to 24:00 every day, office 8:00 to 18:00 Monday to Friday, always:
   every hour); the weekday of 1 January comes from the EPW header (DATA PERIODS start day; Monday when absent).
7. Library: one YAML file per own entry in a `typical_buildings` folder beside the user preferences file
   (`user_preferences.py`); tests point it at a temporary folder. Examples are built in (not files), read-only:
   ids `kenak-apartment-a` ... `kenak-office-d`, `ashrae140-600`, `ashrae140-900`; names "Apartment, zone Α" ...,
   "ASHRAE 140 case 600 (light)" / "... 900 (heavy)"; group "apartment" | "office" | "test" | "own"; each example carries
   `source` (e.g. "ΤΟΤΕΕ 20701-1/2017, reference building, zone Α").
   - KENAK values: the spec's tables (U from 3.4α; shading 0.77 over the zone's cooling period; room average, 6 m deep,
     3 m storey, 40 % on each side, roof and floor not exposed, with u_roof / u_floor set to the zone's 3.4α values so
     turning them on gives KENAK values; infiltration 5.5; g 0.55).
   - ASHRAE 140: find a published description of cases 600 and 900 (for example NREL's BESTEST reports or the test
     descriptions shipped with EnergyPlus) and take the values from it; name it in `source`. Starting values to verify,
     not to trust: box 8 × 6 × 2.7 m, 12 m² of south glass, U wall 0.514, roof 0.318, floor 0.039, window 3.0, glass
     SHGC 0.787, 200 W constant gains, 0.5 ach infiltration, 20 / 27 °C; case 900 heavyweight. The ISO mass class or
     capacity for each case is your call from the published constructions; say so in the report.
8. Routes (replace `/typical-building-presets`):
   - `GET /typical-building-library` -> list of `{id, name, group, read_only, source: str | null, values}`.
   - `POST /typical-building-library` body `{name, values}` -> the new own entry (save as new); 422 per field, 409 for a
     name in use.
   - `PUT /typical-building-library/{id}` body `{name?, values?}` -> the entry; refused (409) for an example.
   - `DELETE /typical-building-library/{id}` -> 204; refused for an example.
   - `GET /projects/{name}/typical-building` -> `{values, library_id, library_name, changed, state, heating_kwh_m2,
     cooling_kwh_m2, counted_hours}`; `changed` when the copy differs from its library entry (false when the entry is
     gone, with library_name kept); counted_hours counts sun-up hours only.
   - `PUT /projects/{name}/typical-building` body `{values, library_id?}` (choosing an entry sends its values and id).
   - `POST .../calculate` as now. `GET .../weights` -> `{benefit, harm, sun_up}`.
   - A new project's building is a copy of `kenak-apartment-b`.
9. Validation per field as now (field names are the value keys, `wwr.<side>`), plus: shading dates valid, schedule and
   mass kind known, exposure booleans, room kind with its own keys.

Tests: engine items 1 to 5 (equalities named in the spec's Tests); every example validates; every example calculates on the
Golden EPW (slow, one test looping over them, report the numbers); library save / save as new / rename / delete, examples
read-only; a project's copy survives a change and a deletion of its entry; `changed`; field errors. Commit tier before
committing. Docs of the engine keys in `design/simulated-weights.md` and `docs/project-map.md`.

## Task 2: app and docs

1. Sheet: the library list at the top (grouped Apartment, Office, Test boxes, Your buildings; choosing replaces the copy),
   "Changed from <name>" when changed, **Save to library** (own entry), **Save as new** (asks a name), rename and delete of
   own entries; basic groups Use (schedule as a choice of the three typical cases, set points, gains, fresh air, heat
   recovery), Fabric (U walls, U windows, g, thermal mass: ISO class or ΤΟΤΕΕ category with the table's descriptions),
   Summer shading (factor and dates); an **Advanced** fold with Room, Roof and floor, Air. "Start from" goes.
2. Chart: one diverging chart (red offsets heating, white no effect, blue adds to cooling; benefit minus harm; red half only
   with Count harm off), grey where `sun_up` is 0; title "Effect of sunlight, by hour", legend ends "offsets heating" and
   "adds to cooling". "Hours that count" from the service (daytime).
3. The 3D view's "Out of date" banner moves beside the open sheet.
4. The Typical building box in Settings shows the library name and "Changed" when changed.
5. Tests per the spec. Docs: `docs/simulated-weights.md` (the room convention, adiabatic default, ΤΟΤΕΕ sources table by
   table, the library, ISO 13790 replaced by EN ISO 52016-1, the facade-independent weights as a limit, the office
   lighting note), `docs/ui.md`, `docs/modes.md`, CHANGELOG.
