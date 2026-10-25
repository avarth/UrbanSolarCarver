# Chained carvings, phase 2 (service) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The browser app's local service holds an ordered list of criteria per project, stores each criterion's test surfaces, runs the chain (tracing only the criteria that changed), tracks what is out of date per criterion, serves results per criterion, and opens existing projects as a chain of one, while every route the current app uses keeps working.

**Order:** the suite stays green after every task, but the app works end to end with the real engine again only from Task 5 (runs) on, and earlier projects open correctly from Task 6 (migration) on. Nothing is merged before Task 10.

**Architecture:** `project.json` gains `criteria` (id, name, colour, bypassed, test surface files, settings) and per-criterion stage records; `config.yaml` keeps the shared settings and a `criteria:` list generated from the criteria that are on, so the project folder is a valid `usc run` input and the existing `RunRequest` path runs the chain. Stage status and stage choice become per criterion (thresholding of criterion *k* depends on its preprocessing and on the previous active criterion's thresholding). Old routes address the single criterion (or the last active one for results), so the current app works unchanged until phase 3 switches it to the criteria interface.

**Tech Stack:** Python 3.10, FastAPI, pydantic v2, pytest with the service's fake engine; the app's generated TypeScript types (`npm run api-types`).

**Spec:** `docs/superpowers/specs/2026-10-25-chained-carvings-design.md` (sections 7.2 Protects and file sharing, 7.3 running, 8, 9, 10, 11 service tests, 12 step 2).

## Global Constraints

- Phase 1 engine names: `load_chain`, `ChainConfig`, `Criterion`, `is_chain_file`, `CRITERION_KEYS` (`src/urbansolarcarver/chain_config.py`); `run_chain`, `ChainResult` (`src/urbansolarcarver/api_core/chain.py`); run layout `run/criteria/<id>/{preprocessing,thresholding}`, `run/criteria/chain.json`, `run/exporting`, `run/massing`.
- Every route and reply field the current app uses keeps its meaning for a project with one criterion; new data is added beside it, never in place of it. The current app's tests (`npm test`) and typecheck pass after `npm run api-types` (spec 12: one branch changes the service and app at a time; the app is switched in phase 3).
- Criterion ids are service-assigned, stable across reordering, never reused in a project: `"1"`, `"2"`, ... from `ProjectJson.next_criterion_id`. Folders and joined files are named by id (spec 8).
- Test surface files are stored once in `inputs/test_surfaces/`, named as uploaded; an upload with the same content as a stored file reuses it; an upload with a stored name and other content replaces it in every criterion that uses it; a stored file no criterion uses is deleted (spec 8).
- What goes out of date (spec 8): maximum volume, context, terrain, weather file or a shared setting: everything (today's `inputs_revision` and settings comparison); a criterion's test surfaces (fingerprint of its joined file) or its own settings: its preprocessing, then the thresholding of every active criterion from it on; order, bypass, delete: the thresholding of every active criterion from the first changed position on.
- A run refuses to start while no criterion is on, or while a criterion that is on protects nothing ("Add test surfaces to <name>").
- All project writes hold `store.project_lock(name)` and refuse while a run is active, as today.
- Tests: a test over about 1 s goes under `@pytest.mark.slow`. Messages: plain words, no em dashes.

## Review Focus

- A project from an earlier version (single criterion, results current) opened after the upgrade: its results stay current and its test surfaces show under criterion 1. Pinned in Task 6.
- A project carved further with an earlier version (Allatini form): opens and runs as a chain of one; its `carving_chain` and earlier files untouched. Pinned in Task 6.
- Deleting the criterion whose results the 3D view shows (the last active one): status and summary fall back to the new last active criterion, no 500 error. Pinned in Task 7.
- Uploading a test surface file whose name exists with other content while two criteria use it: both criteria go out of date, nothing else does. Pinned in Task 3.
- The current app's settings save (`PUT /config` with shared and criterion keys mixed) on a one-criterion project: stored exactly as before from the app's point of view (same `read_settings` result). Pinned in Task 2.

---

## File structure

- `src/urbansolarcarver/api_core/chain.py`, `src/urbansolarcarver/engine_requests.py`: `run_chain(trace=...)`, `RunRequest.trace_criteria` (Task 1).
- `src/urbansolarcarver/local_web_service/criteria.py` (new): criterion model helpers, colour palette, `config.yaml` generation from `project.json`, legacy split of mixed settings (Task 2).
- `src/urbansolarcarver/local_web_service/test_surfaces.py` (new): content-addressed store, per-criterion joined files, fingerprints (Task 3).
- `src/urbansolarcarver/local_web_service/migration.py` (new): chain-of-one migration of earlier projects (Task 6).
- `src/urbansolarcarver/local_web_service/api_models.py`, `projects.py`, `stage_records.py`, `run_worker.py`, `run_summary.py`, `score_points.py`, `carve_further.py`, `server.py`: per-criterion behaviour (Tasks 2-8).
- `tests/local_web_test_support.py`: fake engine writes the chain layout (Task 5).
- Tests: `tests/test_local_web_criteria.py`, `tests/test_local_web_test_surfaces.py`, `tests/test_local_web_migration.py` (new), additions to the existing `tests/test_local_web_*.py`.
- `app/src/api_client/generated_types.ts` regenerated; no other app change (Task 8).

---

### Task 1: Engine: trace only some criteria

**Files:**
- Modify: `src/urbansolarcarver/api_core/chain.py` (`run_chain`), `src/urbansolarcarver/engine_requests.py` (`RunRequest`, the chain branch of the run handler)
- Test: `tests/test_run_chain.py`, `tests/test_engine_requests.py`

**Interfaces:**
- Produces: `run_chain(..., trace: Optional[Collection[str]] = None)`. With `start_from="preprocessing"` and `trace` given, only the criteria whose id is in `trace` run preprocessing; the others read their existing `criteria/<id>/preprocessing` folder (a missing one raises `StageChainError` naming it). Every criterion is thresholded from the first traced one on (earlier untraced criteria are not re-thresholded). `trace=None` keeps today's behaviour.
- Produces: `RunRequest.trace_criteria: Optional[List[str]] = None`, passed to `run_chain` as `trace`; ignored for a config without `criteria:`.

- [ ] **Step 1: Write the failing tests**: `test_tracing_one_criterion_reuses_the_rays_of_the_others` (chain of two; rerun with `trace={"2"}`: `criteria/1/preprocessing/scores.npy` mtime and criterion 1's thresholding run id unchanged, criterion 2's preprocessing and thresholding re-run, exporting re-run) and `test_tracing_the_first_rethresholds_the_ones_after` (`trace={"1"}`: criterion 2's preprocessing untouched, its thresholding re-run with `after_run_id` = criterion 1's new run id); in `tests/test_engine_requests.py`, `test_a_chain_run_request_passes_trace_criteria` (monkeypatched `api.run_chain` receives `trace=["2"]`).
- [ ] **Step 2: Run them to verify they fail** (`python -m pytest tests/test_run_chain.py -m slow -k trac -v`; expected: `TypeError: run_chain() got an unexpected keyword argument 'trace'`).
- [ ] **Step 3: Implement** the parameter in `run_chain` (decide per criterion whether to run preprocessing: `start_from == "preprocessing" and (trace is None or id in trace)`; thresholding runs for criterion *k* when `start_from in ("preprocessing", "thresholding")` and *k* is at or after the first criterion that ran preprocessing, or always when `start_from == "thresholding"`) and the request field.
- [ ] **Step 4: Run the tests** (`python -m pytest tests/test_run_chain.py tests/test_engine_requests.py -m "slow or not slow" -v`): PASS.
- [ ] **Step 5: Commit** `feat(chain): trace only some criteria (run_chain trace=, RunRequest.trace_criteria)`.

---

### Task 2: Criteria in the project model and config.yaml

**Files:**
- Create: `src/urbansolarcarver/local_web_service/criteria.py`, `tests/test_local_web_criteria.py`
- Modify: `src/urbansolarcarver/local_web_service/api_models.py` (`ProjectJson`, new `CriterionEntry`), `src/urbansolarcarver/local_web_service/projects.py` (`write_config_from_values`, `read_settings`, `load_project_config`, `config_from_settings`, `create`)

**Interfaces:**
- Produces in `api_models.py`: `class CriterionEntry(BaseModel): id: str; name: str; named_by_user: bool = False; colour: str; bypassed: bool = False; test_surface_files: list[str] = []; settings: dict = {}` (settings hold criterion keys only, as stored, without service paths). `ProjectJson.criteria: list[CriterionEntry] = []`, `ProjectJson.next_criterion_id: int = 1`, `ProjectJson.criterion_records: dict[str, dict[str, StageRecord]] = {}` (criterion id -> `preprocessing`/`thresholding` -> record; filled from Task 4 on), `StageRecord.test_surfaces_fingerprint: Optional[str] = None`.
- Default names (spec 7.2): a new criterion is named after its mode (plain mode name); while `named_by_user` is False, adding its first test surface file renames it "<Mode> on <file name without extension>" and a mode change renames it after the new mode; `update_criterion(name=...)` sets `named_by_user`.
- Produces in `criteria.py`: `CRITERION_COLOURS = ("#7F77DD", "#D85A30", "#1D9E75", "#D4537E", "#BA7517", "#378ADD", "#639922", "#888780")` (assigned in order, cycling); `split_settings(values: Mapping) -> tuple[dict, dict]` (shared keys, criterion keys by `CRITERION_KEYS`; `name`/`id` never come from the browser); `chain_config_document(shared: dict, criteria: list[CriterionEntry], project_folder: Path) -> dict` (the `config.yaml` mapping: shared settings and service paths at the top, `criteria:` with one entry per criterion that is on: `id`, `name`, its settings, `test_surface_path: inputs/joined/test_surfaces_<id>.ply`, and `epw_path` left at the top).
- Produces on `ProjectStore`: `criteria(name) -> list[CriterionEntry]`; `add_criterion(name, mode, criterion_name=None) -> CriterionEntry` (settings = the mode's starting values restricted to criterion keys; name defaults to the plain mode name; colour from the palette); `update_criterion(name, criterion_id, *, name=None, colour=None, bypassed=None, values=None) -> CriterionEntry` (`values` are criterion settings from the browser, validated as in `write_config_from_values`; a mode change starts from the new mode's starting values); `delete_criterion(name, criterion_id)` (removes its run folder `run/criteria/<id>/` and joined file); `duplicate_criterion(name, criterion_id) -> CriterionEntry` (settings and test surfaces copied, name "<name> copy"); `reorder_criteria(name, ids: list[str])` (must be a permutation). Each write regenerates `config.yaml` and validates it with `load_chain`; an invalid result raises `ConfigError` and changes nothing. The generated file starts with the comment line `# Written by the UrbanSolarCarver app from project.json; change settings in the app.` (user, 2026-10-25: `config.yaml` is an engine format and a record, not an editing surface).
- Compatibility: `write_config_from_values(name, values, criterion_id=None)`: shared keys go to the top of `config.yaml`; criterion keys go to `criterion_id`, or to the only criterion when there is one (with several and no id: `ProjectError(422, "Say which criterion these settings belong to")`). `read_settings(name, criterion_id=None)` returns shared plus that criterion's settings (default: the first criterion), the same mapping the current app reads today. `load_project_config(name, criterion_id=None)` returns that criterion's merged `UserConfig` (from `load_chain`). `create(name, mode)` creates criterion `"1"` in that mode. Until Task 4 makes stage records per criterion, `record_stages` and `_settings_changed` keep recording and comparing a single-criterion config: the first criterion's merged settings (the mapping `read_settings` returns plus the service paths), so the existing stage-status tests stay green.

- [ ] **Step 1: Write the failing tests** in `tests/test_local_web_criteria.py`: `test_a_new_project_has_one_criterion_and_a_chain_config` (`config.yaml` is a chain file whose only criterion has id "1"), `test_the_apps_settings_save_reads_back_unchanged` (mixed `PUT /config` values on a one-criterion project: `read_settings` returns exactly what the same save returned before this change; pin the values with an existing example project), `test_criteria_can_be_added_renamed_reordered_bypassed_duplicated_and_deleted` (ids "1","2","3" never reused after delete; `config.yaml` lists only those that are on, in order), `test_mixed_settings_need_a_criterion_when_there_are_several` (422), `test_an_invalid_criterion_setting_changes_nothing` (ConfigError; `project.json` and `config.yaml` byte-identical), `test_the_config_yaml_says_it_is_written_by_the_app` (first line is the comment; `usc validate` style `load_chain` still reads the file).
- [ ] **Step 2: Run them to verify they fail** (`python -m pytest tests/test_local_web_criteria.py -v`).
- [ ] **Step 3: Implement** the model, `criteria.py` and the store methods.
- [ ] **Step 4: Run** `tests/test_local_web_criteria.py` and the existing `tests/test_local_web_projects.py` and `tests/test_local_web_server.py`: PASS (existing tests pass unchanged; adapt only fixtures that create projects by writing `config.yaml` by hand, and say so in the report).
- [ ] **Step 5: Commit** `feat(service): criteria in project.json; config.yaml lists the active criteria`.

---

### Task 3: Test surfaces per criterion

**Files:**
- Create: `src/urbansolarcarver/local_web_service/test_surfaces.py`, `tests/test_local_web_test_surfaces.py`
- Modify: `src/urbansolarcarver/local_web_service/projects.py` (`add_input`, `remove_input` for role `test_surfaces`, `REQUIRED_MESH_ROLES`, `rebuild_joined_test_surfaces_without_normals`), `src/urbansolarcarver/local_web_service/stage_records.py` (`missing_inputs`)

**Interfaces:**
- Produces in `test_surfaces.py`: `content_digest(path) -> str` (sha256 hex of the file bytes); `joined_path(project_folder, criterion_id) -> Path` (`inputs/joined/test_surfaces_<id>.ply`); `fingerprint(project_folder, criterion_id) -> Optional[str]` (sha256 of the joined file, None without one).
- Produces on `ProjectStore`: `add_criterion_test_surface(name, criterion_id, file_name, data) -> CriterionEntry` (stores or reuses by content, as the Global Constraints say, adds the name to the criterion, rebuilds the joined file of every criterion using that stored name); `use_test_surface(name, criterion_id, file_name)` (adds an already stored file); `remove_criterion_test_surface(name, criterion_id, file_name)` (removes it from that criterion; deletes the stored file when no criterion uses it). The joined file is written as today (`_write_ply_with_vertex_normals`). None of these raise `inputs_revision`.
- Compatibility: `add_input(name, "test_surfaces", ...)` and `remove_input(name, "test_surfaces", ...)` act on the only criterion (with several: 422 as in Task 2); `input_files(name, "test_surfaces")` lists every stored file. `missing_inputs` reports a criterion that is on and protects nothing as `test_surfaces:<id>` (the reply names the criterion), and no criterion on as `criteria`.

- [ ] **Step 1: Write the failing tests**: `test_the_same_file_in_two_criteria_is_stored_once`, `test_a_new_file_with_a_stored_name_replaces_it_for_every_criterion` (both joined files change; a third criterion not using it keeps its fingerprint), `test_removing_a_file_from_one_criterion_keeps_it_for_the_other`, `test_a_file_no_criterion_uses_is_deleted`, `test_test_surface_changes_do_not_raise_inputs_revision`, `test_a_run_needs_test_surfaces_in_every_active_criterion` (missing_inputs names it), `test_the_apps_test_surface_upload_goes_to_the_only_criterion`.
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new tests and `tests/test_local_web_projects.py`: PASS.
- [ ] **Step 5: Commit** `feat(service): test surfaces stored once and protected per criterion`.

---

### Task 4: Stage status and stage choice per criterion

**Files:**
- Modify: `src/urbansolarcarver/local_web_service/api_models.py` (`StageRecord`, `ProjectJson`, `StageStatusReply`), `src/urbansolarcarver/local_web_service/stage_records.py` (`stage_status`, `_settings_changed`, `choose_stages`, `record_stages`, `forget_stages`, `envelope_voxel_size`, manifest helpers)
- Test: `tests/test_local_web_stage_records.py`

**Interfaces:**
- Consumes (Task 2): `ProjectJson.criterion_records`, `StageRecord.test_surfaces_fingerprint`. `stage_records` keeps `exporting` and `massing`, whose record config becomes the last active criterion's merged config.
- Produces: `criterion_status(store, name) -> dict[str, dict[str, StageState]]` (per active criterion id: `preprocessing`, `thresholding`; a bypassed criterion is not listed). Preprocessing of *k* is current when its record and manifest exist, `inputs_revision` and the fingerprint match, and `stages_to_rerun` on *k*'s merged config does not include preprocessing (plus today's manifest checks). Thresholding of *k* is current when its preprocessing is current, the manifest's `upstream_run_id` equals the preprocessing record's run id, its settings did not change, and its `after_run_id` equals the previous active criterion's thresholding run id (None for the first), with that thresholding current.
- `stage_status(store, name)` keeps returning the flat `dict[str, StageState]` the app reads: `preprocessing`/`thresholding` aggregate the active criteria (missing if any missing, else out of date if any out of date, else current); `exporting`/`massing` depend on the last active criterion's thresholding.
- `StageStatusReply` gains `criteria: dict[str, dict[str, StageState]]`.
- Produces: `choose_stages(store, name, produce) -> StageChoice` with new fields `trace_criteria: list[str]` (active criteria whose preprocessing is not current) and `start_from` (`"preprocessing"` when any must be traced, else `"thresholding"` when any thresholding is not current, else the first non-current later stage). `record_stages` writes per-criterion records (with fingerprints) for the criteria that ran and the exporting/massing records.

- [ ] **Step 1: Write the failing tests** (with a helper `write_fake_chain_run(store, name, criterion_ids)` added to `tests/local_web_test_support.py` that writes per-criterion manifests and records with consistent run ids and `after_run_id` links; Task 5 makes the fake engine use it): `test_changing_a_criterions_settings_dates_it_and_the_ones_after` (criterion 2 of 3: 1 current, 2 preprocessing out of date, 3 thresholding out of date), `test_reordering_dates_thresholding_from_the_first_moved_position`, `test_bypassing_a_criterion_dates_the_thresholding_after_it`, `test_deleting_the_last_criterion_makes_the_new_last_feed_the_envelope` (exporting out of date, no error), `test_a_test_surface_change_dates_only_the_criteria_using_it`, `test_a_shared_setting_dates_everything`, `test_the_flat_status_aggregates_the_criteria`, `test_choose_stages_traces_only_the_changed_criteria`.
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_local_web_stage_records.py` and `tests/test_local_web_run_worker.py`: PASS.
- [ ] **Step 5: Commit** `feat(service): stage status and stage choice per criterion`.

---

### Task 5: Runs of a chain

**Files:**
- Modify: `src/urbansolarcarver/local_web_service/run_worker.py` (`start`, `_call_engine`, `_IssuesForwarder`, `_final_event_of_run`, `_result_files`), `src/urbansolarcarver/local_web_service/api_models.py` (`StartRunReply`, run event models), `tests/local_web_test_support.py` (`FakeEngine`, `write_fake_stage_output`, `write_fake_run`, `write_fake_finished_run*`, `add_project_with_inputs`)
- Test: `tests/test_local_web_run_worker.py`

**Interfaces:**
- Consumes: `choose_stages` -> `StageChoice.start_from`, `StageChoice.trace_criteria`, per-criterion `record_stages` (Task 4); `RunRequest.trace_criteria` (Task 1); `missing_inputs` per criterion (Task 3).
- `_call_engine` sends the existing `RunRequest` with `config=<project>/config.yaml` (now a chain file), `start_from=choice.start_from` and `trace_criteria=choice.trace_criteria`.
- `StartRunReply.stages` keeps the plain stage names that will run (union over criteria, in pipeline order); new `criterion_stages: dict[str, list[str]]`.
- Progress and issue events gain `criterion: Optional[str] = None`. Engine progress whose stage is `criterion <id>` sets the current criterion and is not forwarded; following stage events carry that id; issues labelled `criterion <id> (<stage>)` are forwarded as `stage=<stage>, criterion=<id>`. Existing event fields keep their meaning.
- The fake engine writes the chain layout for chain configs (per-criterion folders, `after_run_id` links, `chain.json`), honouring `start_from` and `trace_criteria` like `run_chain`; `add_project_with_inputs` creates criterion "1" with the test surface.

- [ ] **Step 1: Write the failing tests**: `test_a_run_of_two_criteria_records_both_and_builds_from_the_last`, `test_a_second_run_traces_only_the_changed_criterion` (fake engine receives `trace_criteria == ["2"]`), `test_progress_events_name_the_criterion`, `test_a_run_refuses_without_test_surfaces_in_an_active_criterion`, `test_a_run_refuses_with_no_criterion_on`.
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement**, including the fake engine.
- [ ] **Step 4: Run** every `tests/test_local_web_*.py`: PASS.
- [ ] **Step 5: Commit** `feat(service): run the chain, record per criterion, events name the criterion`.

---

### Task 6: Earlier projects open as a chain of one

**Files:**
- Create: `src/urbansolarcarver/local_web_service/migration.py`, `tests/test_local_web_migration.py`
- Modify: `src/urbansolarcarver/local_web_service/server.py` (`open_project`), `src/urbansolarcarver/local_web_service/run_worker.py` (`start`), both next to the existing `rebuild_joined_test_surfaces_without_normals` and `add_missing_chain_footprint`-style repairs

**Interfaces:**
- Consumes: `CriterionEntry`, `chain_config_document` (Task 2); `joined_path`, `fingerprint` (Task 3); `criterion_records` and per-criterion `stage_status` (Task 4).
- Produces: `ProjectStore.migrate_to_criteria(name) -> bool` (no-op returning False when `project.json` already has criteria). It creates criterion `"1"`: settings = the criterion keys of the stored `config.yaml`, name = plain mode name, colour = first palette colour, test surface files = the stored test surface files; rewrites `config.yaml` as a chain file; moves `run/preprocessing` and `run/thresholding` (when present) to `run/criteria/1/`, rewrites the `upstream_manifest` path in `run/exporting/manifest.json` and `run/massing/manifest.json` to point at the moved thresholding manifest (run ids unchanged), writes `run/criteria/chain.json`, and moves the `preprocessing` and `thresholding` stage records to `criterion_records["1"]`, adding the test surface fingerprint of criterion 1's joined file (the file built from the same uploads, so the fingerprint matches). Everything else (`carving_chain`, `inputs/earlier_max_volumes/`, other run files) is left as it is.

- [ ] **Step 1: Write the failing tests** (build an earlier-version project: `project.json` without criteria, a single-criterion `config.yaml`, and the single-criterion run layout written by a helper `write_earlier_version_project` added to `tests/local_web_test_support.py`, copied from the pre-chain `write_fake_finished_run`): `test_an_earlier_project_keeps_its_results_current` (stage status of every stage `current` before and after; exporting manifest's `upstream_manifest` resolves to `run/criteria/1/thresholding/manifest.json`), `test_its_test_surfaces_belong_to_criterion_1`, `test_a_project_carved_further_opens_as_a_chain_of_one` (carving_chain and earlier files byte-identical), `test_migration_runs_once` (second call returns False), `test_opening_a_project_migrates_it` (GET `/api/projects/<name>` on an earlier project).
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement**; call it in `open_project` (errors swallowed like the existing repairs, so the project still opens) and in `RunWorker.start`.
- [ ] **Step 4: Run** the new tests and the example-project tests in `tests/test_local_web_projects.py`: PASS.
- [ ] **Step 5: Commit** `feat(service): earlier projects open as a chain of one, results kept`.

---

### Task 7: Results per criterion

**Files:**
- Modify: `src/urbansolarcarver/local_web_service/run_summary.py`, `src/urbansolarcarver/local_web_service/score_points.py`, `src/urbansolarcarver/local_web_service/carve_further.py`, `src/urbansolarcarver/local_web_service/api_models.py` (`RunSummary`, `CarvingSummary`)
- Test: `tests/test_local_web_run_summary.py`, `tests/test_local_web_score_points.py`, `tests/test_local_web_carve_further.py`

**Interfaces:**
- Consumes: chain run layout and per-criterion records (Tasks 4 and 5).
- `build_run_summary(store, name)`: `RunSummary.carving` keeps describing the last active criterion; new `RunSummary.criteria: list[CriterionCarvingSummary]` (`id`, `name`, `colour`, `mode`, `carving: CarvingSummary`, `voxels_at_start`, `volume_kept_m3`) in chain order, and `RunSummary.chain: Optional[ChainSummary]` (`volume_after_each_m3: list[float]`, `share_of_max_volume_kept: float`) (spec 7.5).
- `build_score_points(store, name, criterion_id=None)` and `build_sky_dome(store, name, criterion_id=None)`: read `run/criteria/<id>/...`; default: the last active criterion. Routes take an optional `criterion` query parameter (Task 8).
- New `build_carved_by_criterion(store, name) -> bytes`: one uint8 per voxel of the grid (C order), 0 = kept by the last active criterion or empty, *k* = removed by the *k*-th active criterion (1-based, in chain order); with a small JSON header in the same style as `build_score_points` naming the grid shape and the criterion ids in order.
- `carve_further` keeps working: it reads `run/exporting` and the exporting record (last active criterion's config) as before (removed with the app in phase 3).

- [ ] **Step 1: Write the failing tests**: `test_the_summary_lists_each_criterion_and_the_chain`, `test_score_points_default_to_the_last_active_criterion`, `test_score_points_of_a_chosen_criterion`, `test_carved_by_criterion_names_who_removed_each_voxel` (two criteria with known masks), `test_after_deleting_the_last_criterion_results_fall_back_without_error`, `test_carve_further_still_works_on_a_chain_of_one`.
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the three test files: PASS.
- [ ] **Step 5: Commit** `feat(service): results per criterion, chain summary, carved-by-criterion data`.

---

### Task 8: Routes and the app's generated types

**Files:**
- Modify: `src/urbansolarcarver/local_web_service/server.py`, `src/urbansolarcarver/local_web_service/api_models.py` (`ProjectDetail`, request models), `app/src/api_client/generated_types.ts` (regenerated)
- Test: `tests/test_local_web_server.py`

**Interfaces (all under `/api`, writes under the project lock and refused while running):**
- `GET /criterion-keys` -> `list[str]` (sorted `CRITERION_KEYS`).
- `POST /projects/{name}/criteria` body `{mode, name?}` -> `CriterionEntry`; `PATCH /projects/{name}/criteria/{id}` body `{name?, colour?, bypassed?, values?}` -> `CriterionEntry` (422 `ConfigErrorReply` on invalid values); `DELETE /projects/{name}/criteria/{id}` -> 204; `POST /projects/{name}/criteria/{id}/duplicate` -> `CriterionEntry`; `PUT /projects/{name}/criteria/order` body `{ids}` -> `list[CriterionEntry]`.
- `POST /projects/{name}/criteria/{id}/test-surfaces` (multipart, as the inputs upload) -> `CriterionEntry`; `PUT /projects/{name}/criteria/{id}/test-surfaces/{file_name}` (use a stored file) -> `CriterionEntry`; `DELETE /projects/{name}/criteria/{id}/test-surfaces/{file_name}` -> `CriterionEntry`.
- `PUT /projects/{name}/config` and `GET /projects/{name}` accept an optional `criterion` query parameter (Task 2 compatibility). `ProjectDetail` gains `criteria: list[CriterionEntry]` and `criterion_status`.
- `GET /projects/{name}/run/score-points` and `/run/sky-patches` accept `criterion`; new `GET /projects/{name}/run/carved-by-criterion` (octet-stream).
- Unknown criterion id: 404 with the id in the message.

- [ ] **Step 1: Write the failing tests** in `tests/test_local_web_server.py` through the FastAPI test client: one test per route family (create/patch/delete/duplicate/order; test surface upload/use/remove; `criterion` parameters; 404 on an unknown id; a write while running is refused with 409).
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement** the routes, then regenerate the app's types: in `app/`, `npm run api-types`.
- [ ] **Step 4: Run** `tests/test_local_web_*.py`, then in `app/` `npm test` and `npm run typecheck` and `npm run build` (the current app must still build and pass its tests unchanged; `tests/test_local_web_packaging.py` checks `ui_static` matches the build).
- [ ] **Step 5: Commit** `feat(service): criteria and per-criterion test surface routes; regenerated app types`.

---

### Task 9: Grasshopper: threshold after a previous criterion

**Files:**
- Modify: `src/urbansolarcarver/engine_requests.py` (`RunRequest.after`), `grasshopper/usc_gh.py` (`run_stages`), `grasshopper/components/USC_ThresholdStage.py`, rebuilt `grasshopper/USC_GHplugin/USC Threshold Stage.ghuser`, `docs/grasshopper.md`
- Test: `tests/test_engine_requests.py`, `tests/test_usc_gh.py`

**Interfaces:**
- `RunRequest.after: Optional[str] = None`: passed as `thresholding(..., after=)` when the run starts at thresholding of a config without `criteria:`; refused (`ConfigError` reply) otherwise.
- `USC_ThresholdStage` gains a last input `after` (the previous `USC_ThresholdStage`'s `thr_result`); `run_stages` sends it.

- [ ] **Step 1: Write the failing tests**: `test_a_run_request_thresholds_after_a_previous_run` (engine request test with monkeypatched `api.thresholding`), `test_threshold_stage_passes_after` (`tests/test_usc_gh.py` style: run the component with `after=...` and a stub `run_stages`).
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement**; rebuild the user objects with `python grasshopper/build_ghuser.py` and check with `--check`.
- [ ] **Step 4: Run** the two test files: PASS.
- [ ] **Step 5: Commit** `feat(grasshopper): USC_ThresholdStage after input for chained criteria`.

---

### Task 10: Docs, the current app end to end, and the merge tier

**Files:**
- Modify: `docs/ui.md` (a note that projects now hold criteria; the app shows one until phase 3), `docs/project-map.md` (new service modules, routes), `docs/criteria.md` (the service and Grasshopper part), `CHANGELOG.md` (`### Added (chained carvings, service)`)

- [ ] **Step 1: Write the docs.** Build them: `mkdocs build --strict -d <scratch>` (no warnings).
- [ ] **Step 2: Check the current app end to end** with the real engine on a scratch copy of an example project and of an earlier project (use the `usc ui --projects-folder <scratch>` preview): open, change a setting, run the analysis, build envelope and massing, see the results and the run report. Record what was checked and a screenshot in the report.
- [ ] **Step 3: Run the merge tier once**: `python -m pytest -n 8`; in `app/`, `npm test && npm run build`.
- [ ] **Step 4: Commit** `docs: chained carvings in the service and Grasshopper`.

---

## Not in this phase

- The app's criteria interface (cards, Protects box, 3D layer, report section, removing Carve further): phase 3.
- Layered input files: later (spec 3).
