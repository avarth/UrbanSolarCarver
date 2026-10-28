# Energy-weighted solar usefulness: implementation plan

**Goal:** a Solar usefulness criterion can count hours by a simulated typical building (Energy-weighted) instead of the cold
hours rule; the project holds one typical building, edited in a sheet that calculates and shows the weights.

**Spec:** `docs/superpowers/specs/2026-10-28-energy-weighted-benefit-design.md` (the authority; this plan fixes interfaces).

**Branch:** `feature/energy-weighted-benefit`.

## Global constraints

- No "5R1C" in app text. Names: "Which hours count", "Cold hours", "Energy-weighted", "Typical building", "Edit building",
  "Calculate", "Start from".
- Style of text and comments: plain words with numbers, no em dashes, no pompous labels; match the surrounding code's
  comment density and naming.
- Test tiers from `docs/testing.md` / CLAUDE.md. Commit tier before each commit: `npm test && npm run build` (when `app/`
  changed), then `python -m pytest -m "not sweep" -n 8`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never `git stash`; leave
  `examples/test_inputs/Real_world_examples/` out of commits.

## Task 1: engine and service

**Files:** `src/urbansolarcarver/simulated_weights.py`; `local_web_service/` new `typical_building.py`, `api_models.py`,
`projects.py`, `criteria.py`, `stage_records.py`, `run_worker.py`, `server.py`; tests in `tests/`.

1. `generate_simulated_weights` writes `meta["heating_kwh_m2"]` and `meta["cooling_kwh_m2"]`: the base run
   (`simulate()` with the shaded solar gains and the internal gains it already builds) divided by the floor area, in kWh.
   Test: they equal `simulate()` of the same inputs.
2. `typical_building.py`:
   - `PRESETS: dict[str, Preset]` with keys `office`, `heavy_home`, `light_home`, each a label ("Office, medium mass",
     "Older home, heavy masonry", "Light, well-insulated home") and its values, from the spec's table.
   - The values are the shoebox archetype keys the form edits: `width, length, height, orientation, wwr {north, east,
     south, west}, g_value, u_opaque, u_window, mass_class, ach_vent, ach_infiltration, heat_recovery, t_set_heating,
     t_set_cooling, gains_day_w_m2, gains_night_w_m2, shading_permanent (float | None), shading_hot (float | None),
     hot_months (list[int])`. `archetype_of(values) -> dict` turns them into the engine's archetype (gains into
     `internal_gains_profile_w_m2`, day 8:00 to 20:00, or `internal_gains_w_m2` when equal; zero shares left out).
   - `validate(values)` raises `ConfigError` with an error per field (loc = the field name), using the engine's own checks
     (`expand_shoebox`, `ZoneParams.from_archetype`, `_shading_factors`) plus ranges (shares 0 to 0.9, factors 0 to 1,
     months 1 to 12).
   - `WEIGHTS_PATH = "inputs/typical_building/weights.json"`; `weights_key(values, weather_path) -> str` (sha256 of the
     sorted JSON of the values and the weather file's bytes or its stored fingerprint); `calculate(project_folder, values)`
     runs `generate_simulated_weights` into `WEIGHTS_PATH` and stores the key.
3. `api_models.py`: `TypicalBuildingEntry {values: dict, start_from: str | None, calculated_key: str | None}`;
   `ProjectJson.typical_building: TypicalBuildingEntry | None = None` (None reads as the office preset);
   `CriterionEntry.energy_weighted: bool = False`; `StageRecord.weights_key: str | None = None`;
   `TypicalBuildingReply {values, start_from, state: "current" | "out_of_date" | "missing", heating_kwh_m2: float | None,
   cooling_kwh_m2: float | None, counted_hours: int | None}` (numbers from the weights file when it exists; counted hours
   = benefit > 0.01); `TypicalBuildingWeightsReply {benefit: list[float], harm: list[float]}` (3 decimals);
   `TypicalBuildingPreset {label, values}`.
4. Routes (`server.py`):
   - `GET /typical-building-presets` -> `dict[str, TypicalBuildingPreset]`.
   - `GET /projects/{name}/typical-building` -> `TypicalBuildingReply`.
   - `PUT /projects/{name}/typical-building` body `{values, start_from}` -> `TypicalBuildingReply`; 422 `ConfigErrorReply`.
   - `POST /projects/{name}/typical-building/calculate` -> `TypicalBuildingReply`; 404 with `sun_study.NO_WEATHER_FILE_MESSAGE`
     without a weather file; 409 while a run of the project is active.
   - `GET /projects/{name}/typical-building/weights` -> `TypicalBuildingWeightsReply`; 404 when not calculated.
   - `PATCH /projects/{name}/criteria/{id}` also takes `energy_weighted: bool`.
5. Config: for a benefit criterion with `energy_weighted`, the generated `config.yaml` and the flat settings
   (`read_stored_config`) get `simulated_weights_path: inputs/typical_building/weights.json` and lose `balance_temperature`
   and `balance_offset`; the stored balance values stay in `CriterionEntry.settings`. Other modes ignore the flag.
6. Stage records: the preprocessing record of an energy-weighted benefit criterion keeps `weights_key` (the key at run
   start); its preprocessing is `out_of_date` when that differs from the current key.
7. Run: when a criterion that is on is benefit and energy-weighted and the weights are missing or stale, the run thread
   calculates them before the engine, emitting `stage_progress` with `stage: "typical_building"`, `criterion: null`,
   done 0 then 1 of 1. A calculation error ends the run with the usual failure event.

Tests (new `tests/test_local_web_typical_building.py`, plus additions where the existing tests live): presets validate;
one bad value per group gives its field error; save and read back; calculate writes the file and answers the numbers;
calculate without weather is 404; config.yaml of an energy-weighted criterion has the path and no balance values and
switching back restores them; a changed building dates only energy-weighted criteria; a run with stale weights calculates
them first (mark slow if it runs the 5R1C, about 9 s).

## Task 2: app and docs

**Files:** `app/src/api_client/client.ts` (and regenerated `generated_types.ts` by the project's own script), new
`app/src/criteria/TypicalBuildingSheet.tsx` (+ test), `use_typical_building.ts`, `CriterionPanel.tsx`, the Settings
step (`steps/SettingsStep.tsx`) for hiding the balance temperature, the run progress labels, `messages.ts`, css; docs.

1. Settings section of a benefit criterion: a two-way switch "Which hours count" (Cold hours, Energy-weighted) at the top,
   saved through `PATCH criteria/{id}` `energy_weighted`. Energy-weighted hides the balance temperature widget and shows a
   "Typical building" box: the start type's label (or "Custom" once a value differs), the state, and "Edit building".
2. `TypicalBuildingSheet`: opened by Edit building beside the criterion panel (as `simulate/StudyPopover.tsx` sits beside
   its list); Start from (the presets route); folded groups Shape, Windows, Walls and glass, Air, Use, Summer shading with a
   one-line summary each; every change saved by `PUT typical-building`, a 422 shown at its field; Calculate (busy state
   while it runs); a day-by-hour chart of benefit (viridis, 0 to 1) and of harm when the criterion counts harm; heating,
   cooling (kWh/m² a year) and hours that count; dimmed with "Calculate again" when `state` is `out_of_date`.
3. Run progress shows the `typical_building` stage as "Typical building".
4. With Energy-weighted, the cold period preset's help says it describes the cold hours rule.
5. Tests per spec. Docs: `docs/ui.md`, `docs/simulated-weights.md` (section "In the app"), `docs/modes.md`, CHANGELOG.
