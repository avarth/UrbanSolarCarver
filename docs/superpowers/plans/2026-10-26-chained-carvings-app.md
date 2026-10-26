# Chained carvings, phase 3 (app) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The browser app works with criteria: Inputs holds the site only, a Site and grid step holds the shared settings, and a Criteria step holds an ordered list of criterion cards (mode, settings, test surfaces, carving rule each), with progress per card, a 3D layer showing which criterion removed each voxel, and no Carve further; plus the service additions the phase 2 review found the app needs.

**Order:** Tasks 1 to 3 change the service and engine only (the current app keeps working). From Task 4 on the app changes; after every task `npm test`, `npm run typecheck` and the Python not-slow tier pass, and the one-criterion flow works end to end in the browser. Nothing is merged or pushed before Task 11 (user, 2026-10-25: push only when phases 2 and 3 work together).

**Architecture:** The app keeps its shape (React 19, state in hooks passed as props, `fetch` to the local service). Settings split by the service's criterion keys (`GET /api/criterion-keys`): keys outside it are shared and saved through a new `PUT /projects/{name}/shared-settings`; keys inside it belong to the selected criterion and are saved through `PATCH /projects/{name}/criteria/{id}` (`values`). A `useCriteria` hook holds the criteria list, the selected id and the criteria calls; results (score points, sky patches, summary entry) follow the selected criterion. Run state is keyed by criterion and stage.

**Tech Stack:** TypeScript, React 19, three.js, Vite, vitest (jsdom, `renderForTest`, `fetch` stubbed with a `FakeService`); Python 3.10, FastAPI, pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-25-chained-carvings-design.md` (sections 7, 7.1 to 7.5, 9, 11 "App", 12 step 3). Phase 2 plan for the service names: `docs/superpowers/plans/2026-10-25-chained-carvings-service.md`. Current app routes and service behaviour: `docs/ui.md` "Criteria in a project".

## Global Constraints

- A one-criterion project looks and behaves as today: no list chrome, no extra clicks, no new vocabulary until the user adds a second criterion (spec 4, 7.1, 11: "one criterion shows no list chrome"). The only new element in that state is a quiet **Add another criterion** link at the end of the Criteria step.
- Steps (spec 7.1): Inputs (maximum volume, context, terrain, weather file), Site and grid, Criteria, Envelope and massing, Export. `StepName` becomes `"inputs" | "site_and_grid" | "criteria" | "envelope_and_massing" | "export"`.
- Shared versus criterion settings come from `GET /api/criterion-keys`, never from a list in the app. Site and grid shows the `settings`-step settings that are not criterion keys (today: `north_deg`, `context_blocks_rays`, `voxel_size`, `ray_batch_size`, `diagnostics`); the criterion panel shows the `settings`-step settings that are criterion keys and the `carving`-step settings.
- Card lines (spec 7.2): colour swatch (the criterion's `colour`), name, mode symbol (`ModeTileSymbol`); result "{p} % of the score carved, {v} m³ removed" (weighted modes, `obstruction_fraction_carved`) or "{p} % of the volume carved, {v} m³ removed" (otherwise); status: current (the result line), "Out of date", "Updates from {name}", "Running", "Bypassed", "Add test surfaces", "Not run yet".
- Card actions: drag handle (and ArrowUp / ArrowDown on the focused handle), bypass toggle, menu with Rename, Duplicate, Delete. **Add criterion** under the last card opens the mode tiles. Delete is disabled on the only criterion with the reason "A project needs at least one criterion.".
- All user-facing strings live in `app/src/messages.ts` (plain labels, units beside values, no em dash, no "plate"; function messages accept numeric arguments, `messages.test.ts` calls them with `(1, 2, 3, 4)`).
- Criterion colours come from the service (`CriterionEntry.colour`); they stay distinct from the score colour map (cividis) and the carved colour token.
- Generated types are refreshed with `npm run api-types` (in a worktree: venv `Scripts` first on PATH and `PYTHONPATH` to the worktree's `src`); `client.ts` re-exports every schema the app uses as `export type X = Schemas["X"]`.
- A commit that changes `app/` also commits the rebuilt `src/urbansolarcarver/ui_static` (`tests/test_local_web_packaging.py`).
- Writes the service refuses during a run stay refused in the app as today (buttons disabled with the run's reason).

## Review Focus

- An earlier-version project (one criterion, results current) opened in the new app: its test surfaces show in the criterion's Protects box, every step reads current, no card list. Pinned in Task 6.
- Deleting or bypassing the selected criterion: the selection moves to the next card (else the previous one), and settings, histogram and 3D show that criterion, with no stale data and no error. Pinned in Task 7.
- Typing in one criterion's settings and selecting another card before the debounced save fires: the pending save goes to the criterion it was typed in. Pinned in Task 7.
- A run refused because criterion 2 protects nothing or has an invalid setting: the app selects criterion 2's card, shows the message there and marks the field. Pinned in Task 8.
- Moving criterion 1's cutoff with "Update when I change the threshold" on while criterion 2 exists: one run, criterion 2's card shows "Updates from {criterion 1}" until it finishes, criterion 1's histogram keeps its own scores. Pinned in Task 8.

---

## File structure

- Service: `src/urbansolarcarver/local_web_service/{server.py,projects.py,api_models.py,run_summary.py,run_worker.py,stage_records.py}`; engine `src/urbansolarcarver/api_core/chain.py`, `src/urbansolarcarver/_reporting.py` (Tasks 1 to 3).
- `app/src/api_client/client.ts`, `events.ts`, `generated_types.ts` (Task 4).
- `app/src/criteria/criteria_state.ts` (new: pure helpers), `app/src/criteria/use_criteria.ts` (new: the hook) (Task 4).
- `app/src/settings_form/form_state.ts` (saver with a send function; two forms) (Task 5).
- `app/src/steps/SiteAndGridStep.tsx` (new, replaces `SettingsStep.tsx`'s step role), `app/src/criteria/CriteriaStep.tsx`, `CriterionPanel.tsx`, `ProtectsBox.tsx` (new), `InputsStep.tsx`, `step_summaries.ts`, `ProjectWorkspace.tsx`, `result_steps.tsx` (Task 6).
- `app/src/criteria/CriterionCard.tsx`, `CriterionList.tsx` (new), `app/src/steps/ActionMenu.tsx` (generalised from `ProjectMenu.tsx`), `app/src/criteria/CriterionDialogs.tsx` (new) (Task 7).
- `app/src/steps/run_state.ts`, `RunProgress.tsx`, `result_steps.tsx`, `run_results.ts` (Task 8).
- `app/src/viewer/carved_by_criterion_decoder.ts` (new), `layers.ts`, `app/src/viewer_overlays/{ViewerPane.tsx,LayersMenu.tsx,Legend.tsx}`, `app/src/steps/input_meshes.ts` (Task 9).
- Removed: `app/src/steps/CarveFurther.tsx` and its test, `carveFurther` in `client.ts`, its messages and CSS (Task 10).
- Docs: `docs/ui.md`, `docs/criteria.md`, `CHANGELOG.md` (Task 11).

---

### Task 1: Service: the settings and summary routes the app needs

**Files:**
- Modify: `src/urbansolarcarver/local_web_service/server.py`, `projects.py`, `api_models.py`, `run_summary.py`, `run_worker.py`
- Test: `tests/test_local_web_server.py`, `tests/test_local_web_criteria.py`, `tests/test_local_web_run_summary.py`, `tests/test_local_web_run_worker.py`

**Interfaces:**
- Produces: `PUT /api/projects/{name}/shared-settings` body `{values}` -> `ConfigReply` (settings = the shared settings as stored, `grid_plan`); `ProjectStore.write_shared_settings(name, values) -> ConfigReply`: keys that are criterion keys are refused (422 `ConfigErrorReply` naming them), service-owned keys dropped as in `write_config_from_values`; validated by building every active criterion's config with the new shared settings (and the chain with `load_chain`); the grid plan checked as today (`GridOverBudget`). No mode needed. Writes hold the project lock and refuse while running (`writable_project`).
- Produces: `GET /api/projects/{name}/criteria/{criterion_id}/settings` -> `CriterionSettingsReply {criterion_id, settings}` (`settings` = `read_settings(name, criterion_id)`: shared plus that criterion's, without service paths); no test surface digests.
- Produces: `GET /api/projects/{name}/sun-path?criterion=<id>` (default: the first active criterion).
- Produces: `ProjectSummary.mode` from the first active criterion (the first criterion when none is on).
- Produces: `CriterionCarvingSummary.volume_removed_m3: Optional[float]` (= (voxels_at_start - voxels_kept) x voxel size³; None when either is unknown).
- Produces: `ConfigErrorReply.criterion: Optional[str] = None`, set when a run-start refusal or a `PATCH /criteria/{id}` rejection comes from one criterion's settings.

- [ ] **Step 1: Write the failing tests**: `test_shared_settings_save_without_a_mode` (voxel size 2.0 saved, every criterion's settings unchanged, grid plan in the reply), `test_shared_settings_refuse_criterion_keys` (422 naming `threshold`, nothing written), `test_a_shared_setting_that_breaks_a_criterion_is_refused` (choose a shared value that makes an active criterion's config invalid; 422, nothing written), `test_criterion_settings_read_does_not_digest_test_surfaces` (monkeypatched `fingerprint` not called), `test_sun_path_of_a_chosen_criterion`, `test_the_project_list_shows_the_first_active_criterions_mode`, `test_the_summary_gives_the_volume_each_criterion_removed`, `test_a_run_refused_for_a_criterions_settings_names_it` (`criterion == "2"` in the 422 reply).
- [ ] **Step 2: Run them to verify they fail** (`python -m pytest tests/test_local_web_server.py tests/test_local_web_criteria.py tests/test_local_web_run_summary.py tests/test_local_web_run_worker.py -m "not slow" -k "shared_settings or criterion_settings or sun_path_of or first_active or volume_each or names_it"`).
- [ ] **Step 3: Implement.** Regenerate the app types (`npm run api-types` in `app/`); `npm test` and `npm run typecheck` pass unchanged.
- [ ] **Step 4: Run** the four test files and the not-slow tier: PASS.
- [ ] **Step 5: Commit** `feat(service): shared settings save, criterion settings read, criterion on sun path and refusals, removed volume per criterion` (with the regenerated `generated_types.ts`).

---

### Task 2: Engine and service: rethreshold from one criterion

**Files:**
- Modify: `src/urbansolarcarver/api_core/chain.py`, `src/urbansolarcarver/engine_requests.py` (docstring only), `src/urbansolarcarver/local_web_service/stage_records.py` (`choose_stages`, `_criterion_stages`), `tests/local_web_test_support.py` (fake engine)
- Test: `tests/test_run_chain.py`, `tests/test_local_web_stage_records.py`, `tests/test_local_web_run_worker.py`

**Interfaces:**
- Produces: `run_chain(..., start_from="thresholding", threshold_from="<id>")` thresholds from that criterion on, reading the earlier criteria's existing thresholding folders (a missing one raises `StageChainError` naming it); `threshold_from=None` keeps "every criterion". `RunRequest.threshold_from_criterion` is now honoured for `start_from="thresholding"` too.
- Produces: `choose_stages` sets `threshold_from` to the first active criterion whose thresholding is not current whenever thresholding runs (with or without tracing; None when that is the first active criterion); `criterion_stages` and `record_stages` follow it.

- [ ] **Step 1: Write the failing tests**: `test_rethresholding_from_the_second_criterion_keeps_the_first` (real chain of two, slow: criterion 1's thresholding run id unchanged, criterion 2 rethresholded with `after_run_id` = criterion 1's run id), `test_choose_stages_rethresholds_from_the_changed_criterion` (criterion 2 of 3 threshold changed: `start_from == "thresholding"`, `threshold_from == "2"`, `criterion_stages == {"1": [], "2": ["thresholding"], "3": ["thresholding"]}`), `test_a_threshold_change_reruns_only_that_criterion_and_the_ones_after` (fake engine run; criterion 1's records untouched).
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement**; update `docs/api/engine-requests.md` and `docs/api/pipeline.md` for the wider `threshold_from`.
- [ ] **Step 4: Run** the three test files with `-m "slow or not slow"`: PASS.
- [ ] **Step 5: Commit** `feat(chain): rethreshold from one criterion without the ones before it`.

---

### Task 3: Engine: the run report's chain summary

**Files:**
- Modify: `src/urbansolarcarver/_reporting.py`, `src/urbansolarcarver/api_core/chain.py` (what it passes to the report)
- Test: `tests/test_run_chain.py` (or the report test file that covers the Criteria section)

**Interfaces:**
- Produces (spec 7.5): after the Criteria table, a "Chain" section: one row per criterion with the volume after it (m³) and the share of the maximum volume kept after the last one; "Total time" covers every criterion's stages plus exporting and massing. The Criteria table's Threshold column shows the method and the resolved cutoff as separate columns ("Rule", "Cutoff") instead of "carve_fraction 278.1".

- [ ] **Step 1: Write the failing tests**: `test_the_run_report_ends_the_criteria_with_the_chain_summary` (two criteria: both volumes and the kept share appear with units), `test_the_run_report_total_time_covers_the_chain`, `test_the_criteria_table_separates_rule_and_cutoff`.
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the report tests: PASS.
- [ ] **Step 5: Commit** `feat(report): chain summary and total time over the chain`.

---

### Task 4: App: criteria in the client and a criteria hook

**Files:**
- Modify: `app/src/api_client/client.ts`, `app/src/api_client/events.ts`, `app/src/App.tsx` (setup loads criterion keys)
- Create: `app/src/criteria/criteria_state.ts`, `app/src/criteria/use_criteria.ts`, `app/src/criteria/criteria_state.test.ts`, `app/src/criteria/use_criteria.test.tsx`
- Test: `app/src/api_client/client.test.ts`

**Interfaces:**
- Produces in `client.ts`: types `CriterionEntry`, `CriterionCarvingSummary`, `ChainSummary`, `CriterionSettingsReply`; calls `getCriterionKeys(token)`, `addCriterion(token, project, mode, name?)`, `updateCriterion(token, project, id, {name?, colour?, bypassed?, values?})`, `deleteCriterion`, `duplicateCriterion`, `reorderCriteria(token, project, ids)`, `addCriterionTestSurface(token, project, id, file)`, `reuseTestSurface(token, project, id, fileName)` (no `use` prefix: it is not a React hook), `removeCriterionTestSurface(token, project, id, fileName)`, `putSharedSettings(token, project, values)`, `getCriterionSettings(token, project, id)`, `getCarvedByCriterion(token, project) -> ArrayBuffer`; `getScorePoints`, `getSkyPatches`, `getSunPath` gain an optional `criterion` argument (query `criterion=`).
- Produces in `events.ts`: `stage_progress` and `issue` events carry `criterion: string | null`.
- Produces in `criteria_state.ts` (pure): `activeCriteria(criteria)`, `criterionStatus(entry, criteria, stagesByCriterion, runningId) -> CardStatus` (`{kind: "current" | "out_of_date" | "updates_from" | "running" | "bypassed" | "no_test_surfaces" | "not_run", from?: string}`; "updates_from" when its preprocessing is current, its thresholding is not, and an earlier active criterion is not current: `from` = the first such criterion's name), `cardResultLine(summary: CriterionCarvingSummary) -> string | null`, `selectionAfterRemoving(criteria, removedId, selectedId) -> string` (next card, else previous).
- Produces in `use_criteria.ts`: `useCriteria(token, project: ProjectDetail) -> {criteria, selectedId, select(id), add(mode), rename(id, name), setBypassed(id, on), duplicate(id), remove(id), reorder(ids), addTestSurfaces(id, files), reuseFile(id, fileName), removeFile(id, fileName), applyReply(entry)}`; each call updates `criteria` from the reply (list calls from the returned list, single-entry calls by id) and returns a promise the workspace awaits; errors surface as `ApiError` like the input calls.
- `App.tsx`: the one-time setup loads `getCriterionKeys` beside schema and modes and passes `criterionKeys: ReadonlySet<string>` down.

- [ ] **Step 1: Write the failing tests**: client tests for every new call's method, path and query (`criterion=2` on score points, sky patches, sun path); `criteria_state.test.ts`: `criterionStatus` for each kind (including "updates_from" naming the first out-of-date earlier criterion, and bypassed criteria skipped when looking back), `cardResultLine` for a weighted and an unweighted mode (`"70 % of the score carved, 18 400 m³ removed"` with the app's number formatting), `selectionAfterRemoving` (middle, last, only); `use_criteria.test.tsx`: add, rename, reorder and remove update the list from the replies.
- [ ] **Step 2: Run them to verify they fail** (`npx vitest run src/criteria src/api_client/client.test.ts`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run typecheck`: PASS.
- [ ] **Step 5: Commit** `feat(app): criteria calls and the criteria hook` (with rebuilt `ui_static`).

---

### Task 5: App: two settings forms, the same screen

**Files:**
- Modify: `app/src/settings_form/form_state.ts`, `app/src/steps/ProjectWorkspace.tsx`, `app/src/steps/SettingsStep.tsx`, `app/src/steps/CarvingStep.tsx`, `app/src/steps/result_steps.tsx`, `app/src/steps/project_workspace_for_test.tsx` (fake service learns `/shared-settings`, `/criteria/...`, `criterion_status`, `criteria`)
- Test: `app/src/settings_form/form_state.test.ts`, `app/src/steps/ProjectWorkspace.saves_and_runs.test.tsx`

**Interfaces:**
- Consumes (Task 4): `putSharedSettings`, `updateCriterion`, `getCriterionSettings`, `criterionKeys`.
- Produces: `createConfigSaver(send: (values) => Promise<SaveReply>, ...)` where `SaveReply = {settings, grid_plan?}`; `useSettingsForm(token, project, start, send)`. Two forms in `ProjectWorkspace`: `sharedForm` (keys outside `criterionKeys`, saved with `putSharedSettings`, owns `gridPlan`) and `criterionForm` (mode plus criterion keys of the selected criterion, saved with `updateCriterion(..., {values})`; its reply's `settings` are the criterion's stored settings). `shownValue` reads the form that owns the key. A 422 `field_errors` reply goes to the form that sent it, as `save_rejected` today.
- The screen does not change in this task: Mode, Settings and Carving steps show the same fields, each field wired to the form that owns it. `analysisDiffersFromStored` is true when either form differs.

- [ ] **Step 1: Write the failing tests**: `test saving the voxel size sends only shared settings` (fake service sees `PUT /shared-settings` with `{voxel_size: 2}` and no `mode`), `test saving the analysis period sends the criterion's settings` (`PATCH /criteria/1` with `values` holding the period and `mode`), `test a rejected criterion setting marks its field`, `test a mode change starts the criterion from the new mode's values`; every existing `ProjectWorkspace.*.test.tsx`, `form_state.test.ts` and `result_steps.test.tsx` test passes (adapt only the fake service routes).
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run typecheck`: PASS.
- [ ] **Step 5: Commit** `feat(app): shared and criterion settings saved apart` (with rebuilt `ui_static`).

---

### Task 6: App: the new steps for one criterion

**Files:**
- Create: `app/src/steps/SiteAndGridStep.tsx`, `app/src/criteria/CriteriaStep.tsx`, `app/src/criteria/CriterionPanel.tsx`, `app/src/criteria/ProtectsBox.tsx` (+ tests beside them)
- Modify: `app/src/steps/step_summaries.ts`, `app/src/steps/ProjectWorkspace.tsx`, `app/src/steps/InputsStep.tsx`, `app/src/steps/result_steps.tsx`, `app/src/messages.ts`, `app/src/steps/steps.css`; remove the step roles of `ModeStep`/`SettingsStep`/`CarvingStep` (their contents are reused inside `CriterionPanel`)
- Test: `app/src/steps/step_summaries.test.ts`, `ProjectWorkspace.*.test.tsx`, `InputsStep.test.tsx`

**Interfaces:**
- Consumes (Tasks 4, 5): `useCriteria`, the two forms.
- Produces: `STEP_NAMES = ["inputs", "site_and_grid", "criteria", "envelope_and_massing", "export"]`; `messages.stepTitles` "Inputs", "Site and grid", "Criteria", "Envelope and massing", "Export". `InputsStep` without `test_surfaces` (roles `max_volume`, `context`, `terrain`, `weather`). `SiteAndGridStep` renders the `settings` step's groups filtered to shared keys (Global Constraints) plus the grid budget line. `CriteriaStep` with one criterion renders `CriterionPanel` directly: `ProtectsBox` (drop box and file list of the criterion, `addTestSurfaces` / `removeFile`; with no files: "Add test surfaces" and the mode's hint from `mode_tiles.json` `needs`), the mode tiles (`ModeStep`'s tile grid), the criterion's `settings`-step groups (criterion keys), the carving rule (today's `CarvingStep` content) and **Run analysis**; then the link **Add another criterion** (opens the mode tiles in Task 7; in this task it adds a criterion with the selected mode through `useCriteria.add`).
- Step summaries: `site_and_grid` = north and voxel size ("North 10°, 0.5 m voxels"); `criteria` with one criterion = today's Mode and Carving summaries joined: "{mode plain name}, {carving summary}" ("Solar usefulness, 56 % kept"; "Daylight, Out of date"); several criteria in Task 7.
- 3D layers per step: `site_and_grid` as today's `settings`; `criteria` as today's `mode` plus `carving` layers.
- Pinned actions: Site and grid keeps today's pinned **Run analysis** (the Settings pin); Criteria shows **Run analysis** in its panel and pins **Build envelope and massing** when every active criterion's thresholding is current (today's Carving pin).

- [ ] **Step 1: Write the failing tests**: `test one criterion shows no list chrome` (no card list, no drag handle, no bypass toggle, the panel open), `test an earlier project shows its test surfaces in the criterion` (detail with `criteria: [{id: "1", test_surface_files: ["roofs.ply", "windows.ply"]}]` and every stage current: both files listed in Protects, every step mark current), `test inputs hold only the site`, `test site and grid shows only shared settings` (`voxel_size` present, `start_month` absent), `test a criterion without test surfaces says what to add` (daylight: the hint from `needs`), step summary tests for the new names.
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run build`, then check the one-criterion flow in the browser with `usc ui --projects-folder <scratch copy>` (open, change a setting, run, build, export): PASS.
- [ ] **Step 5: Commit** `feat(app): Site and grid and Criteria steps; test surfaces move into the criterion` (with rebuilt `ui_static`).

---

### Task 7: App: several criteria as cards

**Files:**
- Create: `app/src/criteria/CriterionCard.tsx`, `app/src/criteria/CriterionList.tsx`, `app/src/criteria/CriterionDialogs.tsx`, `app/src/steps/ActionMenu.tsx` (+ tests)
- Modify: `app/src/steps/ProjectMenu.tsx` (uses `ActionMenu`), `app/src/criteria/CriteriaStep.tsx`, `CriterionPanel.tsx`, `ProtectsBox.tsx`, `app/src/steps/ProjectWorkspace.tsx`, `app/src/steps/run_results.ts`, `app/src/messages.ts`, `app/src/steps/steps.css`

**Interfaces:**
- Consumes (Task 4): `useCriteria`, `criterionStatus`, `cardResultLine`, `selectionAfterRemoving`.
- Produces: `ActionMenu({label, symbol, items: {key, label, disabledReason?}[], onChoose})` (today's `ProjectMenu` behaviour: window placement, arrow keys, Home, End, Escape, Tab, closes on scroll and resize); `ProjectMenu` keeps its props and uses it.
- With two or more criteria `CriteriaStep` renders `CriterionList` (cards in order, selected card marked, `aria-current`), then **Add criterion** (opens the mode tiles; the new card is selected), then the selected criterion's `CriterionPanel`. A card: drag handle (`draggable`; ArrowUp / ArrowDown on the focused handle move it one place; both call `reorder`), swatch, name, `ModeTileSymbol`, result or status line, bypass switch (`aria-label` "Bypass {name}"), `ActionMenu` with Rename, Duplicate, Delete (Delete confirms in `DeleteCriterionDialog`: "Delete {name}? Its settings and results go; test surface files no other criterion uses go to the recycle bin."; Rename in `RenameCriterionDialog`, refusing an empty name with the service's message).
- Selecting a card flushes the pending criterion save first, then loads that criterion's settings (`getCriterionSettings`) into the criterion form and its results (score points, sky patches and the sun path with `criterion=`, its `summary.criteria` entry for the carving numbers and histogram cutoff).
- `ProtectsBox` gains **Use a file from another criterion**: the stored files other criteria use and this one does not, each with a Use button (`reuseFile`).
- The step summary with several criteria reads as a sequence of the active ones: "Daylight on windows 70 %, then Solar usefulness 80 %" (kept shares); bypassed ones left out.

- [ ] **Step 1: Write the failing tests**: `test two criteria show cards in order`, `test reordering with the keyboard sends the new order`, `test bypassing a card greys it and reads Bypassed`, `test deleting the selected criterion selects the next one` (and the last one selects the previous; settings and histogram show the newly selected criterion), `test the only criterion cannot be deleted` (menu item disabled with the reason), `test a pending save goes to the criterion it was typed in` (type a period in criterion 1, select criterion 2 before the save delay: `PATCH /criteria/1` carries the value, `PATCH /criteria/2` does not), `test a file added to two criteria is stored once and replacing it dates both` (fake service: one stored file, both cards "Out of date" after the replace), `test use a file from another criterion`, `test project menu still works` (existing `ProjectMenu.test.tsx` passes).
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run build`: PASS.
- [ ] **Step 5: Commit** `feat(app): criterion cards: add, select, reorder, bypass, rename, duplicate, delete` (with rebuilt `ui_static`).

---

### Task 8: App: runs with several criteria

**Files:**
- Modify: `app/src/steps/run_state.ts`, `app/src/steps/RunProgress.tsx`, `app/src/steps/result_steps.tsx`, `app/src/steps/run_results.ts`, `app/src/criteria/CriterionCard.tsx`, `app/src/criteria/CriteriaStep.tsx`, `app/src/messages.ts`
- Test: `app/src/steps/run_loop.test.ts`, `app/src/steps/result_steps.test.tsx`, `app/src/criteria/CriterionCard.test.tsx`, `ProjectWorkspace.saves_and_runs.test.tsx`

**Interfaces:**
- Consumes: `RunEvent.criterion` (Task 4), `StartRunReply.criterion_stages`, `ConfigErrorReply.criterion` (Task 1), `threshold_from` behaviour (Task 2).
- Produces: `RunState` progress keyed by `progressKey(criterion, stage)` (`"exporting"` for stages without a criterion); `RunState.order` from `criterion_stages` in chain order then exporting and massing; `RunProgress` labels criterion rows "{criterion name}: {stage display name}"; `runningCriterion(state) -> string | null` for the cards.
- Card status while a run is active: "Running" on the criterion being traced or thresholded, "Updates from {name}" on later ones until their thresholding finishes.
- A run refused with `criterion` set: that card is selected, the message shows in its panel, the field is marked (`save_rejected` on the criterion form); a `MissingInputs` refusal naming `test_surfaces:<id>` selects that card and shows "Add test surfaces to {name}." there.
- Carving controls of the selected criterion are locked while its preprocessing is not current (today's `carvingLocked`, per criterion). Moving the cutoff with "Update when I change the threshold" on saves the selected criterion and starts one thresholding run (the service thresholds from that criterion on); results reload for the selected criterion only.

- [ ] **Step 1: Write the failing tests**: `test progress of two criteria is kept apart` (events for criterion 1 and 2 preprocessing do not overwrite each other), `test the running criterion's card says Running`, `test a later criterion says it updates from the changed one` (until its `thresholding` stage finishes), `test a run refused for criterion 2 selects it and marks the field`, `test a run refused for missing test surfaces selects that criterion`, `test moving an earlier cutoff with auto update runs once and keeps that criterion's histogram`.
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run build`: PASS.
- [ ] **Step 5: Commit** `feat(app): progress, refusals and live rethreshold per criterion` (with rebuilt `ui_static`).

---

### Task 9: App: the 3D view by criterion

**Files:**
- Create: `app/src/viewer/carved_by_criterion_decoder.ts` (+ test)
- Modify: `app/src/viewer/layers.ts`, `app/src/viewer/scene.ts` (layer name), `app/src/viewer_overlays/ViewerPane.tsx`, `LayersMenu.tsx`, `Legend.tsx`, `app/src/steps/input_meshes.ts`, `app/src/steps/run_results.ts`, `app/src/steps/ProjectWorkspace.tsx`, `app/src/messages.ts`
- Test: `app/src/viewer_overlays/ViewerPane.test.tsx`, `app/src/viewer/layers.test.ts`

**Interfaces:**
- Consumes: `getCarvedByCriterion` (Task 4); the binary from the service: uint32 header length, JSON header `{origin, shape, voxel_size, criterion_ids}` padded to a multiple of 4, then one uint8 per voxel in C order (0 kept or empty, k = removed by the k-th id of `criterion_ids`).
- Produces: `decodeCarvedByCriterion(buffer) -> {origin, shape, voxelSize, criterionIds, carvedBy: Uint8Array}`; layer `carved_by_criterion` (messages.layerNames "Carved voxels, by criterion"), hidden by default, offered in the Criteria step when there are two or more criteria and every active one has run (the route answers 404 otherwise: the layer is then listed as missing); each carved voxel drawn in its criterion's colour; `Legend` lists a swatch and the name per criterion.
- The test surfaces layer draws the selected criterion's files at full strength and the other criteria's files dimmed (`testSurfacesLayer(highlighted, dimmed)`); with one criterion nothing is dimmed.
- Kept and carved voxel layers show the state after the selected criterion (score points with `criterion=`); envelope and massing unchanged.

- [ ] **Step 1: Write the failing tests**: `decodes a carved-by-criterion buffer` (hand-built buffer of shape (2, 2, 1) with ids ["1", "3"]), `test the carved-by-criterion layer colours each voxel by its criterion` (fake scene receives the colours of criteria 1 and 3), `test the legend names each criterion`, `test the other criteria's test surfaces are dimmed`, `test the layer is missing until every active criterion has run`.
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run build`: PASS.
- [ ] **Step 5: Commit** `feat(app): carved voxels by criterion and test surfaces of the selected criterion` (with rebuilt `ui_static`).

---

### Task 10: App: Carve further goes; the chain summary shows

**Files:**
- Delete: `app/src/steps/CarveFurther.tsx`, `app/src/steps/CarveFurther.test.tsx`
- Modify: `app/src/steps/ExportStep.tsx`, `result_steps.tsx`, `ProjectWorkspace.tsx`, `InputsStep.tsx`, `app/src/App.tsx`, `app/src/api_client/client.ts`, `app/src/messages.ts`, `app/src/steps/steps.css`, `app/src/steps/project_workspace_for_test.tsx`, `app/src/criteria/CriteriaStep.tsx`
- Test: `result_steps.test.tsx`, `App.test.tsx`, `app/src/criteria/CriteriaStep.test.tsx`

**Interfaces:**
- Removed: `CarveFurtherSection`, `carveFurther` (client), `onCarveFurther` props, carve-further messages and CSS. Kept: the maximum volume note for projects carved further with an earlier version (`carvedByNote` moves into `InputsStep.tsx`), as a record (spec 9).
- Produces: with two or more criteria, a line under the cards from `RunSummary.chain`: "Kept {v} m³, {p} % of the maximum volume" (hidden while `chain` is null).
- The service route `POST /carve-further` stays (Grasshopper and older clients); the app no longer calls it.

- [ ] **Step 1: Write the failing tests**: `test the export step has no carve further`, `test a project carved further keeps its note on the maximum volume`, `test the chain summary line under the cards`.
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement**; `npm run typecheck` catches every dead import.
- [ ] **Step 4: Run** `npm test && npm run build`: PASS.
- [ ] **Step 5: Commit** `feat(app): carve further removed; chain summary under the criteria` (with rebuilt `ui_static`).

---

### Task 11: Docs, the browser end to end, and the merge tier

**Files:**
- Modify: `docs/ui.md` (steps, the Criteria step, cards, Protects, 3D layer; remove the Carve further section), `docs/criteria.md` (the app part), `CHANGELOG.md` (`### Added (chained carvings, app)` and `### Removed`: Carve further in the app)

- [ ] **Step 1: Write the docs.** `mkdocs build --strict -d <scratch>`: no warnings.
- [ ] **Step 2: Check in the browser** (`usc ui --projects-folder <scratch>` with copies of `~/UrbanSolarCarver/projects/New building among neighbors` and `Allatini`, never the originals): open the earlier project (one criterion, no card list, test surfaces in Protects); add a second criterion with another mode, use a stored file, run (only the new criterion traces), see both cards current, the carved-by-criterion layer and legend, the chain line, the run report's chain section; move criterion 1's cutoff with auto update on (criterion 2 shows "Updates from ..."); bypass and delete criterion 2; build envelope and massing; export. Record what was checked.
- [ ] **Step 3: Run the merge tier once**: `python -m pytest -n 8`; in `app/`, `npm test && npm run build`.
- [ ] **Step 4: Commit** `docs: chained carvings in the app`.

---

## Not in this phase

- Layered test surface files with layer check boxes (spec 3, 7.2 "later").
- Criterion colour picker (the service accepts `colour`; the app uses the assigned colours).
- The Simulate rework from `feature/solar-check` (spec 12 step 4).
- Removing the service's `POST /carve-further` route.
- Parked service items in `vault/features/chained-carvings.md` not listed above (records lost on a failed mid-chain run, status digest cost).
