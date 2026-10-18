# Local Web UI, round 2: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved round-2 changes of the browser UI: project management, the 3D view's ground aids, mode tiles, sliders and the analysis period control, and the envelope and massing as two builds.

**Architecture:** Service changes in `src/urbansolarcarver/local_web_service/` (projects folder preference and picker, project rename, delete and reset with guardrails, example links); front-end changes in `app/src/` against those routes. The engine is not touched.

**Tech Stack:** as the milestone 1 plan (`docs/superpowers/plans/2026-10-16-local-web-ui.md`), plus `send2trash` in the `ui` extra and Python's `tkinter` for the folder picker.

**Spec:** `docs/superpowers/specs/2026-10-18-local-web-ui-round-2-design.md` (approved 2026-10-18; "R2 n" below), amending `docs/superpowers/specs/2026-10-17-local-web-ui-ux-design.md` ("UX n").

## Global Constraints

- All milestone 1 global constraints hold (127.0.0.1 only, token, one run at a time, copy only in `app/src/messages.ts`, colours only in `app/src/theme/tokens.css`, writing rules: long descriptive names, no em dashes, no cliché labels, sentence case in the interface).
- The browser never sends a file path; the service shows the folder picker on this computer (R2 7.1).
- Deleting or resetting a project removes nothing but that one project folder, and moves it to the recycle bin or trash (R2 7.3).
- Rename, delete, reset and changing the projects folder are refused while a run is active (409).
- The engine is off limits in this plan.
- Python runs as `PYTHONPATH=src "D:/RESEARCH_CENTER/ACTIVE_PROJECTS/RSBenvelope_generation/urbanSolarCarver/.venv/Scripts/python.exe"` from the worktree root; every task touching `app/` ends with `npm test`, `npm run typecheck`, `npm run build` and the committed `ui_static/`.

## Review Focus

1. A project folder that holds a symbolic link or junction to a folder outside the projects folder: delete and reset refuse and nothing outside is touched. Test in Task 2.
2. A project renamed to a name differing only in letter case, or to an existing project's name: refused with 409, nothing moved. Test in Task 2.
3. The folder picker closed without a choice, or unavailable (no display): the old folder stays, the start screen says why. Test in Task 1.
4. An analysis period across the new year or across midnight, typed or dragged: the engine receives start after end and the words read correctly. Test in Task 7.
5. Build massing while the envelope is out of date (or the reverse): only the asked part runs, the other keeps its out-of-date mark. Test in Task 8.

---

## File Structure

```
src/urbansolarcarver/local_web_service/
  user_preferences.py    read and write ~/.urbansolarcarver/ui.json (projects folder)
  folder_picker.py       choose_folder() with tkinter; open_in_file_manager()
  project_removal.py     guardrail checks and move to the recycle bin (send2trash)
  projects.py            + rename_project, reset_project_to_example, example link in project.json
  server.py              + projects-folder routes, rename, delete, reset, open-folder; examples report their project
pyproject.toml           ui extra + send2trash
src/urbansolarcarver/carver_cli.py   usc ui reads the projects folder preference
app/src/steps/StartScreen.tsx, ProjectMenu.tsx (new), dialogs in ProjectDialogs.tsx (new)
app/src/viewer/ground_grid.ts, compass.ts, compass_ring.ts (new), scene.ts, sky_dome.ts, sun_path.ts
app/src/viewer_overlays/AxisGizmo.tsx, ViewToolbar.tsx, ViewerPane.tsx
app/src/steps/ModeStep.tsx, ModeTileSymbols.tsx, mode_tiles.json
app/src/settings_form/setting_presentation.json, presentation.ts, SettingField.tsx, widgets/RangeSlider.tsx (new),
  widgets/BalanceTemperatureSlider.tsx (new), widgets/AnalysisPeriod.tsx (rewritten), form_state.ts
app/src/steps/EnvelopeAndMassingStep.tsx, result_steps.tsx, step_summaries.ts, ExportStep.tsx
docs/ui.md, CHANGELOG.md
```

---

### Task 1: Projects folder preference and picker (service)

**Files:** Create `local_web_service/user_preferences.py`, `local_web_service/folder_picker.py`; modify `server.py`, `api_models.py`, `carver_cli.py` (ui command only), `pyproject.toml` (ui extra); tests `tests/test_local_web_server.py`, `tests/test_cli.py` (ui tests).

**Interfaces:**
- Produces:
  - `user_preferences.preferences_file() -> Path` = `Path.home() / ".urbansolarcarver" / "ui.json"`; `read_projects_folder_preference() -> Path | None` (None when missing or unreadable); `write_projects_folder_preference(folder: Path) -> None` (atomic write, creates the folder).
  - `folder_picker.FolderPickerUnavailable(Exception)`; `choose_folder(initial_folder: Path) -> Path | None` (None when cancelled; raises FolderPickerUnavailable without tkinter or a display); `open_in_file_manager(folder: Path) -> None` (`os.startfile` on Windows, `open` on macOS, `xdg-open` on Linux).
  - `GET /api/projects-folder` -> `ProjectsFolderReply {path: str, source: "command_line" | "preference" | "default", can_change: bool}` (`can_change` false when given on the command line or a run is active).
  - `POST /api/projects-folder/choose` -> `ProjectsFolderChoiceReply {status: "changed" | "cancelled" | "unavailable", path: str, problem: str | None}`; 409 during a run or when `source == "command_line"`. On "changed" the service swaps to a new `ProjectStore` and `RunWorker` for that folder and writes the preference.
  - `create_app(...)` takes `projects_folder_source: str = "default"` and a `choose_folder_function` parameter (defaults to `folder_picker.choose_folder`) so tests inject a fake.
  - `usc ui`: without `--projects-folder`, uses the preference when present, else `~/UrbanSolarCarver/projects`.
- [ ] Tests first: preference round trip and unreadable file; GET reports source; choose with a fake picker returning a folder (changed, list shows that folder's projects, preference written), returning None (cancelled, unchanged), raising FolderPickerUnavailable (unavailable, problem text, unchanged); 409 during a blocking run; 409 with command-line source; `usc ui` reads the preference (monkeypatched home).
- [ ] Run, implement, run (focused tests, then `tests/test_local_web_*.py tests/test_cli.py -m "not slow"`), commit.

### Task 2: Rename, delete, reset, open folder, example links (service)

**Files:** Create `local_web_service/project_removal.py`; modify `projects.py`, `server.py`, `api_models.py`, `pyproject.toml` (`send2trash>=1.8` in `ui`); tests `tests/test_local_web_projects.py`, `tests/test_local_web_server.py`.

**Interfaces:**
- Consumes: Task 1's `open_in_file_manager`.
- Produces:
  - `ProjectJson.example: str | None = None` (the example's name, e.g. `basic_perimeter_block`), set by the examples route; `ProjectStore.project_of_example(example: str, example_title: str) -> str | None` (projects whose `example` matches, or, for projects without the field, whose name equals the example's title exactly; the most recently modified wins).
  - `project_removal.ProjectRemovalRefused(ProjectError)` (422); `check_project_folder_can_be_removed(projects_folder: Path, name: str) -> Path` applying R2 7.3 checks 1 to 4 (name rule; direct child after `resolve()` and not the projects folder; `project.json` reads as a project of that name; no symlink or junction at any depth: `os.path.islink`, and on Windows a reparse point via `os.lstat(...).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT`); `move_to_recycle_bin(folder: Path) -> None` (`send2trash.send2trash`).
  - `ProjectStore.rename_project(name, new_name) -> Path` (under both project locks; 422 bad name, 409 if the new name exists ignoring case, folder rename via `os.replace`, `project.json` name updated).
  - `ProjectStore.reset_project_to_example(name, example_files) -> None`: refuses unless `example` is set (or the backfill rule applies); moves the old folder to the recycle bin through the guardrails, then recreates the project with the same name from the example.
  - Routes: `POST /api/projects/{name}/rename {new_name}` -> ProjectDetail; `DELETE /api/projects/{name}?confirm_name=<name>` -> 204 (422 when confirm_name differs); `POST /api/projects/{name}/reset-to-example` -> ProjectDetail; `POST /api/projects/{name}/open-folder` -> 204; all 409 while that project's run is active. `GET /api/examples` items gain `project: str | None` (the existing project from that example).
- [ ] Tests first, including Review Focus 1 (a junction or symlink inside the project pointing outside: refused, the outside folder's files intact; create the junction with `cmd /c mklink /J` on Windows, `os.symlink` elsewhere) and Review Focus 2 (case-only and existing names: 409, nothing moved); delete with a wrong confirm name; delete moves to the recycle bin (monkeypatch `send2trash.send2trash` to record the path); reset keeps the name and gives the example's inputs and no results; examples report `project` with the backfill rule; open-folder calls the injected opener with the project folder only.
- [ ] Run, implement, run, commit.

### Task 3: Start screen and project menu (front end)

**Files:** Modify `steps/StartScreen.tsx`, `App.tsx`, `api_client/client.ts` (+ regenerated types), `messages.ts`; create `steps/ProjectMenu.tsx`, `steps/ProjectDialogs.tsx`; tests alongside.

**Interfaces:**
- Consumes: Tasks 1 and 2 routes; client functions named `getProjectsFolder`, `chooseProjectsFolder`, `renameProject`, `deleteProject(token, name, confirmName)`, `resetProjectToExample`, `openProjectFolder`.
- Produces: the start screen shows the projects folder with **Change folder** (hidden when `can_change` is false, with the reason); each project row and the top-bar project name open a `ProjectMenu` with Open folder, Rename, Delete, Reset to the example (example projects only); Delete's dialog names the project and folder and enables its button only when the typed name matches; **Try an example** opens `project` when set, else creates it.
- [ ] Tests first (component tests with a fake client): change folder changed / cancelled / unavailable messages; rename dialog refuses an invalid name before sending; delete button disabled until the name matches, then calls `deleteProject` with the confirm name; Try an example opens the existing project and creates none.
- [ ] Implement, `npm test`, typecheck, build, commit with `ui_static`.

### Task 4: 3D view: gizmo, ground aids, scene sizing (front end)

**Files:** Modify `viewer/scene.ts`, `viewer/ground_grid.ts`, `viewer/compass.ts`, `viewer/sky_dome.ts`, `viewer/sun_path.ts`, `viewer_overlays/AxisGizmo.tsx`, `ViewToolbar.tsx`, `ViewerPane.tsx`, `overlays.css`, `messages.ts`; create `viewer/compass_ring.ts`; tests alongside.

**Interfaces:**
- Produces: `type GroundAid = "off" | "grid" | "compass_ring"`; `nextGroundAid(current: GroundAid): GroundAid` (off -> grid -> compass_ring -> off); `ViewerScene.setGroundAid(aid: GroundAid)`; remembered in localStorage `usc.groundAid`, default `"grid"`; `compassRing(sceneBounds, northDegrees)` builds the ring (ticks every 10 degrees, long ticks and N/E/S/W letters every 90 degrees); `sceneHemisphere(sceneBounds)` = R2 2 (radius 1.5 x the larger horizontal side of the bounds of max volume and test surfaces together, centre at their footprint centre, lowest z) replaces `hemisphere(maxVolumeBounds)` for the sun path, sky dome and ring; the ground north arrow is removed; the axis gizmo has no background (letters in `ink` / `ink-on-dark`).
- [ ] Tests first: the cycle order; `sceneHemisphere` for a test surface lying outside the max volume's bounds; the ring rotates with north; no ground north arrow object in the scene; the gizmo's CSS has no background.
- [ ] Implement, test, build, commit.

### Task 5: Mode tiles (front end)

**Files:** Modify `steps/ModeStep.tsx`, `steps/ModeTileSymbols.tsx`, `steps/mode_tiles.json`, `messages.ts`, `step_summaries.ts`, legends that name modes; tests `ModeStep.test.tsx`, packaging test for tile names.

**Interfaces:**
- Produces: tiles in the order and names of R2 3 (Angle rule, Solar time-based, Solar energy, Solar usefulness, Daylight, Night cooling); a tile shows the symbol and the name only; the tooltip keeps the description, needs and engine name; every symbol uses colours from tokens (no all-ink symbol); "Sun at set hours" and "Solar heat when cold" no longer appear anywhere in `app/src` (a test greps `messages.ts` and `mode_tiles.json`).
- [ ] Tests first, implement, test, build, commit.

### Task 6: Sliders, balance temperature, sample spacing, settings groups (front end)

**Files:** Modify `settings_form/setting_presentation.json`, `presentation.ts`, `SettingField.tsx`, `form_state.ts`, `SettingGroup.tsx`, `messages.ts`; create `widgets/RangeSlider.tsx`, `widgets/BalanceTemperatureSlider.tsx`; tests alongside and the packaging test.

**Interfaces:**
- Produces: `setting_presentation.json` entries gain `"slider": {"low": number, "high": number, "step": number}` for every numeric setting with a range (engine limits from the schema, practical ranges otherwise, e.g. voxel size 0.1 to 5 m step 0.1); `RangeSlider` (slider plus number field; the field accepts any engine-valid value outside the slider's range); `BalanceTemperatureSlider` (10 to 30 °C, right handle `balance_temperature`, left handle `balance_temperature - balance_offset`, band labelled "Dead band"); the "Computer" group removed, its two settings appended to "More detail settings"; R2 4.4: lowering voxel size below `grid_step` sets `grid_step` to the new voxel size in the same save and shows `messages.sampleSpacingLoweredToVoxelSize(value)` under Voxel size.
- [ ] Tests first: every numeric setting with a schema range has a slider entry (Python packaging test); dragging the left balance handle changes only `balance_offset`; voxel size 0.5 with grid_step 1 sends both values and shows the note; grid_step typed above voxel size shows a field error and is not clamped.
- [ ] Implement, test, build, commit.

### Task 7: Analysis period control (front end)

**Files:** Rewrite `settings_form/widgets/AnalysisPeriod.tsx`; create `settings_form/analysis_period.ts` (pure functions); modify `messages.ts`, `settings_form.css`; tests alongside.

**Interfaces:**
- Produces: `analysis_period.ts`: `type Period = {startMonth, startDay, startHour, endMonth, endDay, endHour}`; `dayOfYear(month, day)`, `monthDayOf(dayOfYear)` (non-leap year); `periodInWords(period)` ("21 Dec, 10 to 14 h"; "1 Oct to 30 Apr, 0 to 23 h"); `presetPeriod(preset, current)` for "21 December", "21 June", "Heating season, October to April" (1 Oct to 30 Apr), "Whole year" (1 Jan to 31 Dec), keeping the hours; the widget: a twelve-month strip with two date handles and a wrapped draw when start is after end, an hour strip 0 to 23 with two handles (end inclusive, drawn to the end of its hour mark, wrapped across midnight), the preset row, the words (click to type), keyboard as R2 4.3.
- [ ] Tests first (Review Focus 4): across the new year and across midnight, dragged and typed; arrow and Page keys; presets keep hours; 31 February cannot be produced.
- [ ] Implement, test, build, commit.

### Task 8: Envelope and massing as two builds; new names (front end)

**Files:** Modify `steps/EnvelopeAndMassingStep.tsx`, `steps/result_steps.tsx`, `steps/step_summaries.ts`, `steps/ExportStep.tsx`, `settings_form/setting_presentation.json` (labels and help of R2 6), `messages.ts`; tests alongside.

**Interfaces:**
- Produces: two parts with their own settings, button, results and out-of-date state: **Build envelope** (`produce: ["exporting"]`) and **Build massing** (`produce: ["massing"]`); the step summary per R2 5; Export lists each file once its stage exists; "Grid module" and "Permitted volume exceedance" with the R2 6 help.
- [ ] Tests first (Review Focus 5): each button sends only its stage; building one leaves the other's out-of-date mark; Export offers the envelope without massing.
- [ ] Implement, test, build, commit.

### Task 9: Documentation and full check

**Files:** Modify `docs/ui.md` (projects folder, project menu, ground aid, analysis period, two builds, new names), `CHANGELOG.md`.
- [ ] Write the docs; run the full Python suite including slow tests and `npm test`; commit.
