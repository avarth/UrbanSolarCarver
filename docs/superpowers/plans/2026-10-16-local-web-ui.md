# Local Web UI (milestone 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `usc ui` starts a local web service and opens a browser app in which a user imports a maximum volume and test surfaces, picks a mode, runs the analysis, adjusts the threshold on the voxel result, then builds the envelope and the building massing and exports them.

**Architecture:** A FastAPI service in `src/urbansolarcarver/local_web_service/` turns HTTP requests into calls to the existing engine (`engine_requests.handle_engine_request`, `load_config`, `stage_settings`, `grid_planning`, `sun`, `sky_patches`), keeps one project folder per project with a record per completed stage, and runs one pipeline at a time on a worker thread. A React + three.js app in `app/` talks to it only over HTTP and a WebSocket; its production build is committed in `src/urbansolarcarver/ui_static/`. The app is an accordion of steps (Inputs, Mode, Settings, Carving, Envelope and massing, Export) beside an always-visible 3D view, and runs in two phases: the analysis (preprocessing and thresholding), then the envelope and building massing (exporting and massing).

**Tech Stack:** Python 3.10, FastAPI, uvicorn, python-multipart, trimesh, numpy, pytest with FastAPI `TestClient` (httpx); TypeScript, Vite, React 18, three.js, openapi-typescript (dev), Vitest; Atkinson Hyperlegible Next (bundled woff2, SIL Open Font License); Node 24 for front-end work only.

**Specs:**
- Technical: `docs/superpowers/specs/2026-10-16-local-web-ui-design.md`, as amended on 2026-10-17 by the UX spec's section 14.
- UX: `docs/superpowers/specs/2026-10-17-local-web-ui-ux-design.md` (approved 2026-10-17, high-fidelity screens accepted the same day, UX 17). It replaces the technical spec's section 7 and the screen parts of its section 6. Section numbers below prefixed "UX" refer to it. The Claude Design canvas of UX 17 shows every front-end task's target screens; the UX spec stays the source of truth where they differ.

## Global Constraints

- Binds to `127.0.0.1` only. Random token of 32 bytes (hex) per launch, sent as `X-USC-Token` header (WebSocket: `token` query parameter). Missing or wrong token: 401. `Host` must be `127.0.0.1:PORT` or `localhost:PORT`, otherwise 403. Static files are served without the token.
- The service never takes a file path from the browser; files arrive by upload. The service sets `max_volume_path`, `test_surface_path`, `epw_path`, `out_dir` and `device` itself and ignores values the browser sends for them.
- One run at a time per service process. While a project's run is active, uploads, removals and `PUT config` for that project reply 409.
- Importing `urbansolarcarver.local_web_service` must not import torch; the warm-up thread started by `usc ui`, a run, or a sun-path request does.
- FastAPI, uvicorn and python-multipart live in the optional `ui` extra; `httpx` joins the `dev` extra.
- The built front-end in `src/urbansolarcarver/ui_static/` is committed; `ui_static/build_info.json` holds the hash of the front-end sources.
- Score layer: at most 1,000,000 voxels, evenly thinned above that.
- Two run phases (UX 6.2): "Run analysis" and threshold updates send `produce: ["thresholding"]`; "Build envelope and massing" sends `produce: ["exporting", "massing"]`; an export format change sends `produce: ["exporting"]`. The service decides which stages actually run from the stage records (Task 5).
- Labels, units, help texts, step and group placement and essential flags of the settings live only in `app/src/settings_form/setting_presentation.json` (UX 7).
- Interface copy follows UX 13: stage names "Sun analysis", "Carving", "Envelope mesh", "Building massing"; per-floor values are "per storey"; the words "floor plates" and "plates" never appear in interface text (file names such as `plates.obj` are shown as "Building massing (OBJ)"). Without a usable GPU the text is exactly "No CUDA-enabled GPU found. USC runs on the CPU, which is slower." (no brand names).
- Colours, type and spacing are the UX 10 tokens, defined once in `app/src/theme/tokens.css`; state messages of UX 11 are defined once in `app/src/messages.ts`, so the Claude Design pass (UX 17) changes values there only.
- Grasshopper and the pickle daemon are unchanged.
- Writing rules (code comments, docs, UI copy): long descriptive names, no em dashes, no cliché labels, they/them for people, sentence case in the interface.
- Tests that take seconds get the `slow` marker; there is no CI, tests run locally.

## Execution Guardrails

**The engine is off limits, except for Task 0.** Implementers may create or change only these paths:

- `src/urbansolarcarver/local_web_service/**`, `src/urbansolarcarver/example_projects/**`, `src/urbansolarcarver/ui_static/**`
- `app/**`
- `tests/test_local_web_*.py`, and in `tests/test_cli.py` only tests for the `ui` command
- `src/urbansolarcarver/carver_cli.py`: only the new `ui` command and its helpers, nothing in existing commands
- `pyproject.toml`: only the `ui` extra, `httpx` in `dev`, and `[tool.setuptools.package-data]`
- `setup_env.py`: only installing the `ui` extra and the `--no-ui` flag
- `.gitignore`, `docs/ui.md`, `docs/getting-started/installation.md`, `docs/project-map.md`, `mkdocs.yml`, `README.md`, `CHANGELOG.md`
- **Task 0 only** (engine change approved by the user on 2026-10-17, UX 14 item 10): `src/urbansolarcarver/api_core/thresholding.py`, `src/urbansolarcarver/pydantic_schemas.py` (the `ThresholdingManifest` field only), `tests/test_stage_outputs.py`, `docs/api/pipeline.md`.

Every other file under `src/urbansolarcarver/` is engine code. An implementer who finds that a task needs an engine change (a missing function, a wrong signature, a bug) **stops**, reports `NEEDS_ENGINE_CHANGE` with the file, the change and the reason, and does not work around it in service code. The controller passes that report to the user and waits for their decision. After every task the controller compares `git diff --name-only BASE..HEAD` with the list above and treats any other path as a stop.

**Models.** Implementers of Tasks 0 to 8 and 14: Sonnet. One combined review per task (spec compliance and code quality): Opus. Tasks 9 to 13 (front-end): Opus.

**Order.** Task 0 first, then Tasks 1 to 8, then 9 to 14. The UX spec is approved, so the front-end is no longer blocked. The Claude Design pass (UX 17) is done and its changes are in the UX spec and in the tasks below; later value changes still go into the UX spec first and reach the code through `tokens.css` and `messages.ts`.

## Review Focus

1. A project name with path parts or odd characters (`../x`, `a/b`, empty, 200 characters): 422, and nothing is written outside the projects folder. Test in Task 1.
2. A corrupt mesh or an unsupported extension uploaded into a role that already has files: 422, the earlier files and the joined file stay as they were. Test in Task 2.
3. A browser that connects to the run events after the run has finished (slow page, reconnect, second tab): it still receives every event of that run, ending with the final one. Test in Task 5.
4. A service stopped during a run and started again: the next run of that project reruns every stage that run had started, because their stage records were removed when it started. Test in Task 5.
5. The threshold moved several times while a carving run is in progress: exactly one more run follows, with the last value, and the panel never shows a result for a value the user has already left. Test in Task 13.

---

## File Structure

```
src/urbansolarcarver/api_core/thresholding.py     (Task 0) + scores_compared_with_cutoff.npy
src/urbansolarcarver/pydantic_schemas.py          (Task 0) + ThresholdingManifest.scores_compared_with_cutoff_path
src/urbansolarcarver/local_web_service/
  __init__.py          create_app re-export only (no torch)
  api_models.py        pydantic request, reply and event models
  projects.py          project folders, names, uploads, joining, project.json, config.yaml
  score_points.py      binary score layer data with the cap, raw and compared scores
  run_summary.py       carving and massing numbers, sky dome data, sun path
  stage_records.py     per-stage records, stage status, stage choice
  run_worker.py        RunWorker thread, run events, error mapping
  gpu_warm_up.py       background warm-up started by usc ui, its state for GET health
  server.py            FastAPI app factory, security checks, routes, WebSocket, static files
src/urbansolarcarver/example_projects/      copies of three examples and the Golden EPW
src/urbansolarcarver/ui_static/             committed front-end build (+ build_info.json)
src/urbansolarcarver/carver_cli.py          + `usc ui`
pyproject.toml                              ui extra, httpx in dev, package-data
setup_env.py                                installs the ui extra (unless --no-ui)
app/
  package.json, package-lock.json, vite.config.ts, tsconfig.json, index.html
  scripts/write_build_info.mjs
  src/main.tsx, src/App.tsx, src/messages.ts
  src/theme/           tokens.css, fonts/ (Atkinson Hyperlegible Next woff2 + OFL.txt)
  src/api_client/      client.ts, generated_types.ts, events.ts
  src/viewer/          scene.ts, local_origin.ts, loaders.ts, layers.ts, score_points_decoder.ts, size_check.ts,
                       ground_grid.ts, compass.ts, scale_bar.ts, sky_dome.ts, sun_path.ts, colour_scales.ts
  src/settings_form/   setting_presentation.json, presentation.ts, SettingField.tsx, SettingGroup.tsx, SettingTooltip.tsx,
                       widgets/{AnalysisPeriod, TiltedPlaneAngles, SunStepsPerHour, MeshFormat, PercentSlider}.tsx
  src/steps/           StartScreen.tsx, StepAccordion.tsx, InputsStep.tsx, ModeStep.tsx, SettingsStep.tsx,
                       CarvingStep.tsx, ScoreHistogram.tsx, EnvelopeAndMassingStep.tsx, ExportStep.tsx,
                       run_state.ts, threshold_queue.ts, step_summaries.ts, mode_tiles.ts
tests/
  test_stage_outputs.py (Task 0), test_local_web_projects.py, test_local_web_score_points.py,
  test_local_web_run_summary.py, test_local_web_stage_records.py, test_local_web_run_worker.py,
  test_local_web_server.py, test_local_web_packaging.py, test_cli.py (+ usc ui)
docs/ui.md, docs/api/pipeline.md, mkdocs.yml, README.md, CHANGELOG.md, docs/getting-started/installation.md
```

---

### Task 0: Engine: thresholding saves the scores it compares with the cutoff

Approved by the user on 2026-10-17 (UX 14 item 10). The only engine change in this plan.

**Files:**
- Modify: `src/urbansolarcarver/api_core/thresholding.py` (save the array, list it in the stage's outputs tuple, record it in the manifest), `src/urbansolarcarver/pydantic_schemas.py` (`ThresholdingManifest`), `docs/api/pipeline.md` (the thresholding outputs list)
- Test: `tests/test_stage_outputs.py`

**Interfaces:**
- Produces:
  - `run/thresholding/scores_compared_with_cutoff.npy`: float32, the grid shape, the values the cutoff is applied to: `removal_scores` when `carve_above` is on, otherwise the scores after `score_smoothing` (for time-based and tilted_plane these are the raw scores).
  - `ThresholdingManifest.scores_compared_with_cutoff_path: Optional[str] = None` (relative to the manifest's folder, through `stored_path`; optional so manifests written before this change still load).
  - The file is added to the tuple of thresholding outputs (`"mask.npy", ...`) so `begin_stage` clears it before a rerun.

- [ ] **Step 1: Write the failing tests** (in `tests/test_stage_outputs.py`, with its `thresholded_run` fixture; occupancy is preprocessing's `voxel_grid.npy`; `threshold_value` and `slope_limit_extra_voxels_removed` come from `thresholding/diagnostics/diagnostic.json`)

```python
def test_thresholding_saves_the_scores_it_compares_with_the_cutoff(thresholded_run):
    folder = <thresholding folder of thresholded_run>
    manifest = ThresholdingManifest.model_validate_json((folder / "manifest.json").read_text())
    compared = np.load(folder / manifest.scores_compared_with_cutoff_path)
    mask = np.load(folder / manifest.mask_path)
    occupied = np.load(<preprocessing folder> / "voxel_grid.npy").astype(bool)
    summary = json.loads((folder / "diagnostics" / "diagnostic.json").read_text())
    kept_before_slope_limit = occupied & (compared <= summary["threshold_value"])
    assert compared.dtype == np.float32 and compared.shape == mask.shape
    assert not (mask & ~kept_before_slope_limit).any()
    assert int(kept_before_slope_limit.sum()) - int(mask.sum()) == summary["slope_limit_extra_voxels_removed"]

def test_without_carve_above_time_based_compares_the_raw_scores(tmp_path):
    # the fixture's own run helper with mode "time-based" and carve_above False:
    # scores_compared_with_cutoff.npy equals preprocessing's scores.npy on the occupied voxels
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_stage_outputs.py -q -p no:cacheprovider -k compare`
Expected: FAIL (`scores_compared_with_cutoff_path` is not a field).

- [ ] **Step 3: Implement.** Save the array right after `removal_scores` and `scores` are final, before the slope limit, with `np.save(..., allow_pickle=False)`; add the manifest field.

- [ ] **Step 4: Run the stage tests and the whole fast suite**

Run: `.venv/Scripts/python -m pytest tests -q -p no:cacheprovider -m "not slow"`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/api_core/thresholding.py src/urbansolarcarver/pydantic_schemas.py docs/api/pipeline.md tests/test_stage_outputs.py
git commit -m "feat(thresholding): save the scores compared with the cutoff for the UI histogram"
```

---

### Task 1: Projects, names and project.json

**Files:**
- Create: `src/urbansolarcarver/local_web_service/__init__.py` (empty for now), `src/urbansolarcarver/local_web_service/api_models.py`, `src/urbansolarcarver/local_web_service/projects.py`
- Modify: `pyproject.toml` (extras `ui = ["fastapi>=0.110", "uvicorn>=0.29", "python-multipart>=0.0.9"]`; add `"httpx>=0.27"` to `dev`)
- Test: `tests/test_local_web_projects.py`

**Interfaces:**
- Produces:
  - `class ProjectError(Exception)` with `status_code: int` (404 unknown project, 409 exists, 422 invalid name or file).
  - `validate_project_name(name: str) -> str`: accepts `^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$` after stripping spaces at both ends, else `ProjectError(422)`.
  - `class ProjectStore` with `__init__(self, projects_folder: Path)`, `create(name: str, mode: str) -> Path`, `open(name: str) -> Path` (404 if missing), `list() -> list[ProjectSummary]`, `read_project_json(name) -> ProjectJson`, `write_project_json(name, data: ProjectJson) -> None`.
  - `api_models.StageRecord(BaseModel)`: `config: dict` (the `config.yaml` content the stage ran with), `inputs_revision: int`, `manifest_run_id: str` (the `run_id` of the manifest the stage wrote). Written by Task 5.
  - `api_models.ProjectJson(BaseModel)`: `name: str`, `created: str` (ISO 8601 UTC), `inputs_revision: int = 1` (raised by every upload and removal, Task 2), `input_files: dict[str, dict[str, int]] = {}` (role to file name to triangle count, Task 2), `stage_records: dict[str, StageRecord] = {}`. This replaces the technical spec's `inputs_changed_since_last_run` flag and `last_completed_run_config.yaml` (UX 14 item 1).
  - `api_models.ProjectSummary(BaseModel)`: `name: str`, `created: str`, `modified: str` (ISO 8601 UTC, the newest modification time of `project.json` and `config.yaml`; the start screen lists it), `mode: str`.
  - Folder layout as the spec section 5.3, created by `create`: `inputs/max_volume/`, `inputs/test_surfaces/`, `inputs/joined/`, `run/`.
  - `create` writes the first `config.yaml` through Task 3's `write_config_from_values` once Task 3 exists; in this task it writes `project.json` and the folders only, and records the mode in a minimal `config.yaml` (`mode: <mode>`).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("bad", ["", "   ", "../x", "a/b", "a\\b", ".hidden", "x" * 65, "naïve"])
def test_invalid_project_names_are_rejected_without_writing(tmp_path, bad):
    store = ProjectStore(tmp_path / "projects")
    with pytest.raises(ProjectError) as err:
        store.create(bad, "time-based")
    assert err.value.status_code == 422
    assert not any(p for p in tmp_path.rglob("*") if p.is_file())

def test_create_makes_the_folder_layout_and_project_json(tmp_path):
    store = ProjectStore(tmp_path)
    folder = store.create("Block 7", "time-based")
    for sub in ("inputs/max_volume", "inputs/test_surfaces", "inputs/joined", "run"):
        assert (folder / sub).is_dir()
    data = store.read_project_json("Block 7")
    assert data.name == "Block 7" and data.inputs_revision == 1 and data.stage_records == {}

def test_create_twice_is_a_conflict_and_open_unknown_is_not_found(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("a", "time-based")
    with pytest.raises(ProjectError) as err:
        store.create("a", "time-based")
    assert err.value.status_code == 409
    with pytest.raises(ProjectError) as err:
        store.open("b")
    assert err.value.status_code == 404

def test_list_returns_projects_sorted_by_name(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("b", "time-based"); store.create("a", "daylight")
    assert [p.name for p in store.list()] == ["a", "b"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_local_web_projects.py -q -p no:cacheprovider`
Expected: FAIL (`ModuleNotFoundError: urbansolarcarver.local_web_service`)

- [ ] **Step 3: Implement `api_models.py` (the two models above) and `projects.py`**

`ProjectStore` resolves every project folder with `(projects_folder / name).resolve()` and checks it is a direct child of `projects_folder.resolve()` before writing. `project.json` is written with `model_dump_json(indent=1)`.

- [ ] **Step 4: Run them to verify they pass**

Run: same command. Expected: 4 test functions PASS.

- [ ] **Step 5: Install the extra and commit**

```bash
.venv/Scripts/python -m pip install "fastapi>=0.110" "uvicorn>=0.29" "python-multipart>=0.0.9" "httpx>=0.27"
git add pyproject.toml src/urbansolarcarver/local_web_service tests/test_local_web_projects.py
git commit -m "feat(ui): project folders, names and project.json for the local web service"
```

---

### Task 2: Input files and joining

**Files:**
- Modify: `src/urbansolarcarver/local_web_service/projects.py`, `api_models.py`
- Test: `tests/test_local_web_projects.py`

**Interfaces:**
- Consumes: `ProjectStore`, `ProjectError` (Task 1); `urbansolarcarver.io.load_mesh(path) -> trimesh.Trimesh` (raises `InputError`), `urbansolarcarver.io.save_mesh(mesh, path) -> str`.
- Produces:
  - `MESH_ROLES = ("max_volume", "test_surfaces")`, `MESH_EXTENSIONS = (".ply", ".obj", ".stl", ".glb")`.
  - `sanitize_file_name(name: str) -> str`: last path part only; characters other than letters, digits, `-`, `_`, `.` removed; `ProjectError(422)` if the result is empty or starts with `.`.
  - `ProjectStore.add_input(name, role, file_name, data: bytes) -> InputFilesReply`: for a mesh role, writes to a temporary file in the role folder, checks it with `load_mesh` (an `InputError` or an extension outside `MESH_EXTENSIONS` gives `ProjectError(422)` with the engine message, the temporary file removed), then moves it into place (same name replaced), records its triangle count (`len(mesh.faces)`) in `ProjectJson.input_files[role]`, and rebuilds the joined file. For `role == "weather"`: extension `.epw`, stored as `inputs/weather.epw`. Raises `ProjectJson.inputs_revision` by 1.
  - `ProjectStore.remove_input(name, role, file_name) -> InputFilesReply` (404 if absent), rebuilds the joined file (removes it when the role is empty), drops its triangle count, raises `inputs_revision` by 1.
  - `ProjectStore.input_files(name, role) -> list[InputFileInfo]` (sorted by name, from `ProjectJson.input_files`), `ProjectStore.input_file_path(name, role, file_name) -> Path`.
  - `ProjectStore.joined_bounds(name) -> list[list[float]] | None`: `[[xmin,ymin,zmin],[xmax,ymax,zmax]]` of `inputs/joined/max_volume.ply`, None if absent.
  - `ProjectStore.weather_location(name) -> str | None`: from the EPW's first line (`LOCATION,<city>,<state>,<country>,...`), `"<city>, <country>"` with runs of spaces collapsed to one; None without a weather file.
  - `api_models.InputFileInfo`: `name: str`, `triangle_count: int`.
  - `api_models.InputFilesReply`: `role: str`, `files: list[InputFileInfo]`, `joined_bounds: list[list[float]] | None` (always the max volume's), `weather_location: str | None`.
  - Joining (spec 5.3): max volume = `trimesh.util.concatenate(meshes)` then `merge_vertices()`; test surfaces = `trimesh.util.concatenate(meshes)` without merging; written with `save_mesh` to `inputs/joined/max_volume.ply` and `inputs/joined/test_surfaces.ply`.

- [ ] **Step 1: Write the failing tests**

```python
def _box_bytes(center, ext=".ply"):
    m = trimesh.creation.box(extents=[10, 10, 10]); m.apply_translation(center)
    return m.export(file_type=ext.lstrip("."))

def test_two_test_surface_files_join_and_removal_rebuilds(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    a = trimesh.creation.box(extents=[4, 4, 4]); b = trimesh.creation.box(extents=[2, 2, 2])
    store.add_input("p", "test_surfaces", "a.ply", a.export(file_type="ply"))
    reply = store.add_input("p", "test_surfaces", "b.ply", b.export(file_type="ply"))
    assert [(f.name, f.triangle_count) for f in reply.files] == [("a.ply", len(a.faces)), ("b.ply", len(b.faces))]
    joined = trimesh.load(tmp_path / "p/inputs/joined/test_surfaces.ply", force="mesh")
    assert len(joined.faces) == len(a.faces) + len(b.faces)
    store.remove_input("p", "test_surfaces", "a.ply")
    joined = trimesh.load(tmp_path / "p/inputs/joined/test_surfaces.ply", force="mesh")
    assert len(joined.faces) == len(b.faces)

def test_two_closed_max_volume_files_stay_two_closed_bodies(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    reply = store.add_input("p", "max_volume", "b.obj", _box_bytes([30, 0, 5], ".obj"))
    joined = trimesh.load(tmp_path / "p/inputs/joined/max_volume.ply", force="mesh")
    bodies = joined.split(only_watertight=False)
    assert len(bodies) == 2 and all(b.is_watertight for b in bodies)
    assert reply.joined_bounds == [[-5.0, -5.0, 0.0], [35.0, 5.0, 10.0]]

@pytest.mark.parametrize("file_name, data", [("bad.ply", b"not a mesh"), ("model.3dm", b"x")])
def test_rejected_upload_keeps_earlier_files_and_joined_file(tmp_path, file_name, data):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    before = (tmp_path / "p/inputs/joined/max_volume.ply").read_bytes()
    with pytest.raises(ProjectError) as err:
        store.add_input("p", "max_volume", file_name, data)
    assert err.value.status_code == 422
    assert [f.name for f in store.input_files("p", "max_volume")] == ["a.ply"]
    assert (tmp_path / "p/inputs/joined/max_volume.ply").read_bytes() == before

@pytest.mark.parametrize("raw, clean", [("../../evil.ply", "evil.ply"), ("C:\\x\\my model.obj", "mymodel.obj"), ("bü ro.stl", "bro.stl")])
def test_file_names_are_sanitized(raw, clean):
    assert sanitize_file_name(raw) == clean

def test_upload_and_removal_raise_the_inputs_revision(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    assert store.read_project_json("p").inputs_revision == 2
    store.remove_input("p", "max_volume", "a.ply")
    assert store.read_project_json("p").inputs_revision == 3

def test_weather_location_comes_from_the_epw_header(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    reply = store.add_input("p", "weather", "golden.epw", GOLDEN_EPW.read_bytes())   # examples/weather/USA_CO_Golden-NREL.724666_TMY3.epw
    assert reply.weather_location == "Denver Centennial Golden Nr, USA"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_local_web_projects.py -q -p no:cacheprovider`
Expected: the new tests FAIL with `AttributeError` (`add_input`, `sanitize_file_name`).

- [ ] **Step 3: Implement the interfaces above in `projects.py`**

- [ ] **Step 4: Run them to verify they pass**

Run: same command. Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/local_web_service tests/test_local_web_projects.py
git commit -m "feat(ui): several input files per role, joined like the Grasshopper components"
```

---

### Task 3: Settings: config.yaml and the grid plan

**Files:**
- Modify: `src/urbansolarcarver/local_web_service/projects.py`, `api_models.py`
- Test: `tests/test_local_web_projects.py`

**Interfaces:**
- Consumes: `load_config.build_config_from_mode_starting_values(values, base_folder) -> UserConfig` (raises `ConfigError` with `.errors: list[ConfigFieldError(field, message)]`), `load_config.load_config(path) -> UserConfig`, `grid_planning.plan_voxel_grid(bounds, voxel_size, margin_frac) -> VoxelGridPlan`, `grid_planning.check_voxel_grid_budget(plan)` (raises `ConfigError` on field `voxel_size`).
- Produces:
  - `SERVICE_OWNED_SETTINGS = ("max_volume_path", "test_surface_path", "epw_path", "out_dir", "device")`.
  - `SERVICE_PATHS = {"max_volume_path": "inputs/joined/max_volume.ply", "test_surface_path": "inputs/joined/test_surfaces.ply", "epw_path": "inputs/weather.epw", "out_dir": "run"}` (relative to the project folder).
  - `ProjectStore.__init__(self, projects_folder: Path, device: str = "auto")`.
  - `ProjectStore.write_config_from_values(name, values: dict) -> ConfigReply`: drops `SERVICE_OWNED_SETTINGS` from *values*, adds `SERVICE_PATHS` and `device`, builds with `build_config_from_mode_starting_values(values, base_folder=project_folder)`, computes the grid plan when the joined max volume exists (an over-budget grid raises the `ConfigError` on `voxel_size` and nothing is stored), then writes `config.yaml` as `config.model_dump(mode="json")` with the four path fields replaced by the relative `SERVICE_PATHS` values. `ConfigError` propagates.
  - `ProjectStore.read_settings(name) -> dict`: `config.yaml` without `SERVICE_OWNED_SETTINGS`.
  - `ProjectStore.load_project_config(name) -> UserConfig`: `load_config(str(project_folder / "config.yaml"))`.
  - `ProjectStore.create(name, mode)` now writes the first `config.yaml` with `write_config_from_values(name, {"mode": mode})`.
  - `api_models.GridPlanReply`: `resolution: int`, `voxel_size: float`, `total_voxels: int`, `extent: float`, `budget_voxels: int` (`grid_planning.MAX_GRID_VOXELS`).
  - `api_models.ConfigReply`: `settings: dict`, `grid_plan: GridPlanReply | None`.
  - `api_models.FieldErrorReply`: `field: str | None`, `message: str`; `api_models.ConfigErrorReply`: `field_errors: list[FieldErrorReply]`, `grid_plan: GridPlanReply | None` (the rejected plan when the error is the budget, so the app can name the smallest voxel size that fits, UX 11).
  - `class GridOverBudget(ConfigError)` raised by `write_config_from_values` with the plan attached as `.grid_plan: GridPlanReply`; the plan is computed before `check_voxel_grid_budget` is called.

- [ ] **Step 1: Write the failing tests**

```python
def test_config_yaml_round_trips_through_load_config(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "daylight")
    reply = store.write_config_from_values("p", {"mode": "daylight", "voxel_size": 2.0, "carve_fraction": 0.3})
    loaded = store.load_project_config("p")
    assert loaded.voxel_size == 2.0 and loaded.carve_fraction == 0.3
    assert Path(loaded.max_volume_path) == (tmp_path / "p/inputs/joined/max_volume.ply").resolve()
    assert "max_volume_path" not in reply.settings and reply.settings["mode"] == "daylight"

def test_browser_paths_and_device_are_ignored(tmp_path):
    store = ProjectStore(tmp_path, device="cpu"); store.create("p", "daylight")
    store.write_config_from_values("p", {"mode": "daylight", "out_dir": "C:/elsewhere", "max_volume_path": "/etc/x", "device": "cuda"})
    loaded = store.load_project_config("p")
    assert Path(loaded.out_dir) == (tmp_path / "p/run").resolve() and loaded.device == "cpu"

def test_invalid_setting_raises_config_error_on_its_field(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "daylight")
    with pytest.raises(ConfigError) as err:
        store.write_config_from_values("p", {"mode": "daylight", "voxel_size": -1})
    assert [e.field for e in err.value.errors] == ["voxel_size"]

def test_grid_plan_and_budget_use_the_joined_max_volume(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "daylight")
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    reply = store.write_config_from_values("p", {"mode": "daylight", "voxel_size": 1.0})
    assert reply.grid_plan.resolution == 11            # 10 m side + 1% margin each side, rounded up
    with pytest.raises(ConfigError) as err:
        store.write_config_from_values("p", {"mode": "daylight", "voxel_size": 0.0125})
    assert err.value.errors[0].field == "voxel_size"
    assert err.value.grid_plan.total_voxels > err.value.grid_plan.budget_voxels == 500_000_000
    assert store.load_project_config("p").voxel_size == 1.0   # the rejected value was not stored
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_local_web_projects.py -q -p no:cacheprovider`
Expected: the new tests FAIL with `AttributeError: write_config_from_values`.

- [ ] **Step 3: Implement the interfaces above**

- [ ] **Step 4: Run them to verify they pass** (same command, all PASS)

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/local_web_service tests/test_local_web_projects.py
git commit -m "feat(ui): settings stored as config.yaml with service-owned paths, grid plan and budget"
```

---

### Task 4: Score layer data, run summary, sky dome and sun path

**Files:**
- Create: `src/urbansolarcarver/local_web_service/score_points.py`, `src/urbansolarcarver/local_web_service/run_summary.py`
- Test: `tests/test_local_web_score_points.py`, `tests/test_local_web_run_summary.py`

**Interfaces:**
- Consumes: `run/preprocessing/manifest.json` (`PreprocessingManifest`: `scores_path`, `scores_kind`, `shape`, `origin`, `voxel_size`, `voxel_grid_path`, `mode`; paths relative to the manifest's folder), `run/preprocessing/patch_weights.npy`, `run/thresholding/manifest.json` (`ThresholdingManifest.mask_path`, `.scores_compared_with_cutoff_path` from Task 0), `run/thresholding/diagnostics/diagnostic.json` (flat keys `threshold_value`, `voxels_occupied`, `voxels_kept`, `voxels_removed`, `retention_pct`, `obstruction_fraction_carved` (weighted modes only), `carve_above_extra_voxels_removed`, `slope_limit_extra_voxels_removed`), `run/massing/plates.json` (`floor_area_m2_per_floor`, `total_floor_area_m2`), `run/massing/diagnostics/diagnostic.json` (`floors_built`, `envelope_volume_m3`), `mode_registry.MODES[mode].weight_unit`; `sky_patches.fetch_tregenza_patch_directions(device)`, `sky_patches.tregenza_solid_angles()`; `sun.sample_period(PreprocessingSettings, steps_per_hour)`, `sun.get_sun_vectors(epw_file, date_list, min_altitude, device, north_deg)`; `stage_settings.PreprocessingSettings.from_config(config)`.
- Produces:
  - `SCORE_POINTS_CAP = 1_000_000`.
  - `build_score_points(run_folder: Path, cap: int = SCORE_POINTS_CAP) -> bytes | None` (None when there is no preprocessing output).
  - Binary layout (little-endian): `uint32` header length in bytes; header JSON (UTF-8) padded with spaces to a multiple of 4; `uint32` flat indices (C order of `shape`); `float32` raw scores; `uint8` kept (1) or carved (0), present only when `has_mask`; `float32` compared scores (Task 0's array at the same indices), present only when `has_compared_scores`.
  - Header keys: `origin`, `shape`, `voxel_size`, `scores_kind`, `weight_unit`, `score_min`, `score_max`, `occupied_count`, `point_count`, `thinning_step`, `has_mask`, `has_compared_scores`.
  - `run_summary.build_run_summary(run_folder: Path) -> RunSummary`: `RunSummary.carving: CarvingSummary | None` (the eight diagnostic keys above, `obstruction_fraction_carved` None when absent) and `RunSummary.massing: MassingSummary | None` (`floor_area_m2_per_storey: list[float]`, `total_floor_area_m2: float`, `storeys_built: int`, `envelope_volume_m3: float`); each None when its stage output is missing. Models in `api_models.py`.
  - `run_summary.build_sky_dome(run_folder: Path) -> SkyDome | None`: `directions: list[list[float]]` (145), `solid_angles: list[float]`, `weights: list[float]`; None when `patch_weights.npy` is absent (time-based and tilted_plane). Torch is imported inside the function.
  - `run_summary.sun_marker_hours(start_hour: int, end_hour: int) -> list[int]`: `range(start_hour, end_hour + 1, step)` with `step = 3` when `end_hour - start_hour > 8`, else `2` (UX 8.2).
  - `run_summary.sun_path_for_config(config: UserConfig) -> SunPath` (UX 8.2, UX 14 item 4): `SunPath.days: list[SunPathDay]`, one for the first and one for the last day of the stored period (one when they are the same day); `SunPathDay`: `date: str` (`"12-21"`, month and day), `day_path: list[list[float]]` (unit vectors from sunrise to sunset every 10 minutes, `get_sun_vectors(..., min_altitude=0, ...)`, with a first and a last point at sunrise and sunset from Ladybug's `Sunpath.calculate_sunrise_sunset(month, day)`, their z set to 0 and renormalised, so the curve meets the ground, UX 8.2), `period_path: list[list[float]]` (from `start_hour` to `end_hour` every 5 minutes with the stored `min_altitude`), `markers: list[SunMarker]` (`hour: int`, `vector: list[float]`, one `get_sun_vectors` call per hour of `sun_marker_hours`, an hour whose sun is below `min_altitude` left out). Dates are Ladybug `DateTime(month, day, hour, minute)`; every call passes `torch.device("cpu")` and the stored `north_deg`. `days` is empty when the mode is not time-based or the weather file or period is missing. Torch is imported inside the function. Models in `api_models.py`.
  - Thinning: `thinning_step = max(1, ceil(occupied_count / cap))`; the kept voxels are the occupied flat indices in increasing order, sliced `[::thinning_step]`.

- [ ] **Step 1: Write the failing tests**

```python
def _fake_run(tmp_path, shape=(4, 3, 2), with_mask=True):
    # writes run/preprocessing/{manifest.json, scores.npy, voxel_grid.npy}
    # and, with_mask, run/thresholding/{manifest.json, mask.npy}; occupied = every voxel with i < 3
    ...

def _decode(blob):
    n = struct.unpack("<I", blob[:4])[0]; header = json.loads(blob[4:4 + n])
    body = blob[4 + n:]; c = header["point_count"]
    idx = np.frombuffer(body[:4 * c], "<u4"); scores = np.frombuffer(body[4 * c:8 * c], "<f4")
    kept = np.frombuffer(body[8 * c:9 * c], "u1") if header["has_mask"] else None
    start = 9 * c if header["has_mask"] else 8 * c
    compared = np.frombuffer(body[start:start + 4 * c], "<f4") if header["has_compared_scores"] else None
    return header, idx, scores, kept, compared

def test_arrays_match_the_header_and_the_occupied_voxels(tmp_path):
    run = _fake_run(tmp_path)
    header, idx, scores, kept, _ = _decode(build_score_points(run))
    assert header["occupied_count"] == header["point_count"] == 18 and header["thinning_step"] == 1
    assert len(idx) == len(scores) == len(kept) == 18 and (np.diff(idx) > 0).all()

def test_above_the_cap_every_kth_voxel_is_kept(tmp_path):
    run = _fake_run(tmp_path)
    header, idx, _, _, _ = _decode(build_score_points(run, cap=5))
    assert header["thinning_step"] == 4 and header["point_count"] == 5      # ceil(18 / 5) = 4, ceil(18 / 4) = 5
    occupied = np.flatnonzero(np.load(run / "preprocessing" / "voxel_grid.npy").ravel())
    assert (idx == occupied[::4]).all()

def test_without_thresholding_the_kept_array_is_absent(tmp_path):
    header, idx, _, kept, _ = _decode(build_score_points(_fake_run(tmp_path, with_mask=False)))
    assert header["has_mask"] is False and kept is None

def test_without_preprocessing_there_is_no_data(tmp_path):
    assert build_score_points(tmp_path / "run") is None

def test_compared_scores_follow_the_same_indices(tmp_path):
    run = _fake_run(tmp_path, with_compared_scores=True)   # compared = raw scores + 100
    header, idx, scores, kept, compared = _decode(build_score_points(run, cap=5))
    assert header["has_compared_scores"] is True and np.allclose(compared, scores + 100)
```

(`_fake_run` builds the manifests with the real `PreprocessingManifest` and `ThresholdingManifest` models so field names stay in step with the engine.)

```python
def test_summary_reads_carving_and_massing_numbers(tmp_path):
    run = _fake_finished_run(tmp_path)   # thresholding and massing diagnostics, plates.json with [120.0, 80.0]
    summary = build_run_summary(run)
    assert summary.carving.retention_pct == 61.0 and summary.carving.obstruction_fraction_carved is None
    assert summary.massing.floor_area_m2_per_storey == [120.0, 80.0] and summary.massing.total_floor_area_m2 == 200.0

def test_summary_parts_are_none_without_their_stage(tmp_path):
    summary = build_run_summary(tmp_path / "run")
    assert summary.carving is None and summary.massing is None

def test_sky_dome_has_145_patches_or_none(tmp_path):
    assert build_sky_dome(_fake_run(tmp_path)) is None                         # no patch_weights.npy
    dome = build_sky_dome(_fake_run(tmp_path / "w", with_patch_weights=True))
    assert len(dome.directions) == len(dome.weights) == len(dome.solid_angles) == 145

def test_sun_marker_hours_every_two_hours_or_three_for_long_days():
    assert sun_marker_hours(10, 14) == [10, 12, 14]
    assert sun_marker_hours(8, 18) == [8, 11, 14, 17]

def test_sun_path_needs_time_based_mode_weather_and_period():
    golden = UserConfig(..., mode="time-based", epw_path=GOLDEN_EPW, start_month=12, start_day=21, start_hour=10,
                        end_month=12, end_day=21, end_hour=14)
    path = sun_path_for_config(golden)
    assert len(path.days) == 1 and path.days[0].date == "12-21"
    day = path.days[0]
    assert [m.hour for m in day.markers] == [10, 12, 14] and all(m.vector[2] > 0 for m in day.markers)
    assert len(day.day_path) > len(day.period_path) >= 48 and all(v[2] > 0 for v in day.day_path[1:-1])
    assert day.day_path[0][2] == day.day_path[-1][2] == 0.0                     # both ends on the horizon
    season = golden.model_copy(update={"start_month": 11, "start_day": 1, "end_month": 2, "end_day": 28})
    assert [d.date for d in sun_path_for_config(season).days] == ["11-01", "02-28"]
    assert sun_path_for_config(golden.model_copy(update={"mode": "daylight"})).days == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_local_web_score_points.py tests/test_local_web_run_summary.py -q -p no:cacheprovider`
Expected: FAIL (`ImportError: build_score_points`, `build_run_summary`).

- [ ] **Step 3: Implement `build_score_points` and `run_summary.py`**

- [ ] **Step 4: Run them to verify they pass** (same command, all PASS)

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/local_web_service tests/test_local_web_score_points.py tests/test_local_web_run_summary.py
git commit -m "feat(ui): score layer with compared scores, run summary, sky dome and sun path"
```

---

### Task 5: Stage records and the run worker: stage choice, events, cancel

**Files:**
- Create: `src/urbansolarcarver/local_web_service/stage_records.py`, `src/urbansolarcarver/local_web_service/run_worker.py`
- Modify: `api_models.py`, `projects.py` (`config_from_settings`)
- Test: `tests/test_local_web_stage_records.py`, `tests/test_local_web_run_worker.py`

**Interfaces:**
- Consumes: `ProjectStore`, `ProjectJson`, `StageRecord` (Tasks 1 to 3); `stage_settings.stages_needed_for(produce) -> list[str]`, `stage_settings.stages_to_rerun(previous_config, new_config, produce) -> list[str]`, `stage_settings.PIPELINE_STAGES`; every stage manifest's `run_id` and, for thresholding, exporting and massing, `upstream_run_id` (`run/<stage>/manifest.json`); `engine_requests.RunRequest(cmd="run", produce, run_folder, start_from, config)`, `engine_requests.handle_engine_request(request, session, context) -> RunReply`; `run_context.RunContext(on_progress)` with `.issues`, `.cancel()`; errors `ConfigError`, `InputError`, `StageChainError`, `RunCancelled`.
- Produces:
  - `ProjectStore.config_from_settings(name, settings: dict) -> UserConfig`: what `load_project_config` does, from a settings dict (`load_project_config` now calls it with the content of `config.yaml`).
  - `stage_records.UPSTREAM_STAGE = {"thresholding": "preprocessing", "exporting": "thresholding", "massing": "thresholding"}`.
  - `stage_records.stage_status(store, name) -> dict[str, Literal["current", "out_of_date", "missing"]]`, for every stage of `PIPELINE_STAGES`, in pipeline order:
    - `missing`: no `StageRecord`, or `run/<stage>/manifest.json` is absent;
    - `out_of_date`: the record's `inputs_revision` differs from the project's; or `stage in stages_to_rerun(config_from_settings(record.config), current config, [stage])`; or the stage has an upstream stage whose status is not `current`, or whose record's `manifest_run_id` differs from this stage's manifest `upstream_run_id`;
    - `current` otherwise.
  - `stage_records.choose_stages(store, name, produce: list[str]) -> StageChoice` with `StageChoice.stages: list[str]` (pipeline order, empty when up to date) and `StageChoice.produce_for_engine: list[str]`. Rule: among `stages_needed_for(produce)`, if preprocessing or thresholding is not `current`, run from the first of them through thresholding, plus every stage of *produce* after it; otherwise run each stage of *produce* that is not `current`. `produce_for_engine` = the chosen stages that are in *produce*.
  - `stage_records.forget_stages(store, name, stages)` and `stage_records.record_stages(store, name, stages, settings: dict, inputs_revision: int)` (reads each stage's new `run_id` from its manifest).
  - `missing_inputs(store, name, config) -> list[str]`: roles without a joined file, plus `"weather"` when `MODES[config.mode].needs_epw` and `inputs/weather.epw` is absent.
  - `class RunState`: `run_id: str`, `project: str`, `stages: list[str]`, `events: list[dict]`, `finished: bool`; `wait_for_events(after: int, timeout: float) -> list[dict]` (blocks on a `threading.Condition` until events beyond index *after* exist, the run finished, or the timeout passes).
  - `class RunWorker`: `__init__(self, store: ProjectStore, device: str, handle_request=None, session_factory=None)` (defaults: `engine_requests.handle_engine_request` and `lambda device: CarverSession(device)`, both imported lazily so torch loads on the first run); `start(name: str, produce: list[str]) -> StartRunReply`; `cancel(run_id: str) -> bool`; `active_project() -> str | None`; `run_state(run_id) -> RunState | None`. `start` raises `RunConflict` (409) when a run is active and `MissingInputs(roles)` (422) when inputs are missing.
  - Lifecycle: `start` calls `choose_stages`; with no stages it replies `up_to_date`. Otherwise it calls `forget_stages` for the chosen stages **before** the thread starts (so a run stopped by a crash leaves them `missing`), then runs `RunRequest(produce=produce_for_engine, start_from=stages[0], ...)`. On success it calls `record_stages` with the settings and `inputs_revision` read at start. On failure or cancel the chosen stages stay forgotten. On `StageChainError` it forgets every stage and sends its message as technical spec 5.6 says. After every run it calls `release_memory()` on the session.
  - Events (dicts, `type` first): `stage_progress {stage, done, total}`; `issue {stage, code, message}` (new `context.issues` entries, sent before each progress event and before the final event); `run_finished {stages, files}` (`files`: paths relative to `run/` of `exporting/*` mesh, `massing/plates.json`, `massing/plates.obj`, `run_report.md`, those that exist); `run_failed {error_type, message, field_errors}`; `run_cancelled {}`.
  - `api_models.StartRunReply`: `status: Literal["started", "up_to_date"]`, `run_id: str | None`, `stages: list[str]`; `api_models.StageStatusReply`: `stages: dict[str, Literal["current", "out_of_date", "missing"]]`.

- [ ] **Step 1: Write the failing tests** (fast: `handle_request` is a fake that writes `run/<stage>/manifest.json` with a new `run_id` and the current upstream `run_id` for each stage it runs, and calls `context.on_progress`; `session_factory` returns an object with `release_memory`; `run_and_wait(worker, name, produce)` starts and joins)

```python
def test_analysis_then_build_runs_only_the_missing_stages(project_with_inputs):
    store, name = project_with_inputs
    worker = RunWorker(store, "cpu", handle_request=fake_success, session_factory=FakeSession)
    assert run_and_wait(worker, name, ["thresholding"]).stages == ["preprocessing", "thresholding"]
    assert worker.start(name, ["thresholding"]).status == "up_to_date"
    assert stage_status(store, name) == {"preprocessing": "current", "thresholding": "current", "exporting": "missing", "massing": "missing"}
    assert run_and_wait(worker, name, ["exporting", "massing"]).stages == ["exporting", "massing"]

def test_threshold_change_after_a_build_marks_envelope_and_massing_out_of_date(built_project): ...
    # write_config_from_values with another carve_fraction -> status: thresholding, exporting, massing "out_of_date";
    # run ["thresholding"] -> stages == ["thresholding"]; then thresholding "current", exporting and massing "out_of_date"
    # (their manifests' upstream_run_id is the old thresholding run_id); run ["exporting", "massing"] -> ["exporting", "massing"]

def test_floor_height_change_reruns_massing_only(built_project): ...        # stages == ["massing"]
def test_mesh_format_change_reruns_exporting_only(built_project): ...      # run ["exporting"] -> stages == ["exporting"]
def test_upload_after_a_run_starts_again_at_preprocessing(built_project): ...  # every stage "out_of_date"; run ["thresholding"] -> ["preprocessing", "thresholding"]

def test_interrupted_run_makes_the_next_run_complete(built_project):
    # start ["thresholding"] after a voxel_size change with a fake handler that blocks on a threading.Event:
    # while it runs, stage_records has no "preprocessing" or "thresholding" (as after a service stopped mid-run);
    # cancel it, then choose_stages(store, name, ["thresholding"]).stages == ["preprocessing", "thresholding"]

def test_second_start_while_running_is_a_conflict(project_with_inputs): ...   # RunConflict
def test_missing_inputs_are_named(tmp_path): ...    # MissingInputs.roles == ["max_volume", "test_surfaces", "weather"] for time-based
def test_events_reach_a_late_reader_in_order(project_with_inputs): ...
    # after the run finished, wait_for_events(0, 0) returns stage_progress ... issue ... run_finished, finished is True
def test_cancel_gives_run_cancelled(project_with_inputs): ...   # fake raises RunCancelled when context.cancel_event is set

@pytest.mark.parametrize("exc, error_type", [(ConfigError("m", [ConfigFieldError("voxel_size", "too small")]), "ConfigError"),
                                             (InputError("broken mesh"), "InputError"),
                                             (StageChainError("rerun preprocessing"), "StageChainError"),
                                             (RuntimeError("boom"), "RuntimeError")])
def test_failures_become_run_failed_events(project_with_inputs, exc, error_type): ...
    # last event == {"type": "run_failed", "error_type": error_type, ...}; ConfigError carries field_errors [{"field": "voxel_size", ...}];
    # after StageChainError every stage is "missing"
```

Write each `...` body with the assertions in its comment. The stage-record tests go in `tests/test_local_web_stage_records.py`, the worker tests in `tests/test_local_web_run_worker.py`.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_local_web_stage_records.py tests/test_local_web_run_worker.py -q -p no:cacheprovider`
Expected: FAIL (`ImportError: stage_status`, `RunWorker`).

- [ ] **Step 3: Implement `stage_records.py` and `run_worker.py`**

The event buffer with a `threading.Condition` replaces the technical spec's `loop.call_soon_threadsafe` forwarding: the WebSocket handler (Task 6) reads with `await asyncio.to_thread(state.wait_for_events, index, 1.0)`, which also serves late and repeated readers (Review Focus 3).

- [ ] **Step 4: Run them to verify they pass** (same command, all PASS)

- [ ] **Step 5: Add one slow end-to-end test with the real engine on CPU**

```python
@pytest.mark.slow
def test_real_two_phase_run_on_the_basic_perimeter_block(tmp_path):
    # project from examples/test_inputs/basic_perimeter_block (maxVolume.ply, testSrfs.ply), mode "tilted_plane",
    # voxel_size 2.0, device "cpu"; run ["thresholding"] (a progress event with stage "preprocessing" comes first),
    # then ["exporting", "massing"] (files include "massing/plates.json");
    # then set carve_above_min_consecutive to 2 and run ["thresholding"]:
    # run/exporting/manifest.json and run/massing/plates.json still exist, and stage_status gives
    # exporting and massing "out_of_date" (UX 14 item 2)
```

Run: `.venv/Scripts/python -m pytest tests/test_local_web_run_worker.py -q -p no:cacheprovider -m slow`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/urbansolarcarver/local_web_service tests/test_local_web_stage_records.py tests/test_local_web_run_worker.py
git commit -m "feat(ui): stage records with stage status, run worker with two-phase runs, events and cancel"
```

---

### Task 6: HTTP service

**Files:**
- Create: `src/urbansolarcarver/local_web_service/server.py`, `src/urbansolarcarver/local_web_service/gpu_warm_up.py`; `__init__.py` re-exports `create_app`
- Test: `tests/test_local_web_server.py`

**Interfaces:**
- Consumes: Tasks 1 to 5; `urbansolarcarver.__version__`; `user_config.model_json_schema()`; `mode_registry.MODES`; `warp_kernels.warmup_kernels(device) -> bool` (raises `WarpBackendUnavailableError` when Warp cannot run) and `compute_device.resolve_compute_device`, imported inside the warm-up thread only.
- Produces:
  - `class GpuWarmUp` in `gpu_warm_up.py`: `__init__(self, device: str, warm_up_function=None)` (default: resolve the device, then `warmup_kernels` on it, imported lazily); `start()` runs it on a daemon thread; `state() -> WarmUpState` with `state: Literal["not_started", "running", "ready", "cpu", "failed"]` (`cpu` when no CUDA device is available), `device_name: str | None` (as `torch.cuda.get_device_name` reports it), `problem: str | None` (the `WarpBackendUnavailableError` or other message on failure). Runs never wait for it in the service; the browser keeps the run buttons disabled while it is `running` (UX 5.1).
  - `create_app(projects_folder: Path, token: str, port: int, device: str = "auto", static_folder: Path | None = None, worker: RunWorker | None = None, warm_up: GpuWarmUp | None = None) -> FastAPI` (without *warm_up*, a `GpuWarmUp` that is never started, state `not_started`).
  - `openapi_document() -> dict`: `create_app(Path("."), "x", 0).openapi()`, used by the front-end type generation (Task 9).
  - Routes exactly as spec 5.4, with the input routes as amended (`POST`/`DELETE`/`GET` under `inputs/{role}`) and these replies: `GET health` `{version, warm_up: WarmUpState}`; `GET modes` list of `{name, description, needs_epw, needs_period, experimental, score_kind, weight_unit, starting_values}`; `GET projects/{name}` `{name, created, modified, settings, inputs: {role: [InputFileInfo]}, joined_bounds, weather_location, stage_status}`; `GET projects/{name}/stage-status` `StageStatusReply`; `GET projects/{name}/sun-path` `SunPath` from `sun_path_for_config` on the stored config (`days` empty when not applicable); `GET projects/{name}/run/summary` `RunSummary`; `GET projects/{name}/run/sky-patches` `SkyDome` or 404; `PUT config` body `{"values": {...}}`, reply `ConfigReply` or 422 `ConfigErrorReply` (with `grid_plan` for `GridOverBudget`); `POST runs` body `{"produce": [...]}` (default `["exporting", "massing"]`) reply `StartRunReply`, 409 `{detail}`, 422 `{detail, missing_inputs}`; `GET run/score-points` `application/octet-stream` or 404; `GET run/files/{path}` (404 for paths outside `run/`); `GET download` zip of the project folder.
  - `ProjectError`, `RunConflict`, `MissingInputs`, `ConfigError` map to their status codes in exception handlers; 409 for input and config changes while `worker.active_project() == name`.
  - Security middleware for every request: Host check (403), then for paths under `/api` the token check (401); the WebSocket `api/runs/{run_id}/events?token=...` checks both before accepting and closes with code 4401 or 4403. `hmac.compare_digest` for the token.
  - Static files from `static_folder` (default `ui_static/` next to the package) at `/`, without the token; `index.html` for `/`.
  - The WebSocket sends every buffered event from index 0, then new ones, and closes after `run_finished`, `run_failed` or `run_cancelled`.

- [ ] **Step 1: Write the failing tests** (fake worker handle as in Task 5; `TestClient(create_app(tmp_path, TOKEN, 8770), base_url="http://127.0.0.1:8770")`)

```python
def test_token_and_host_are_checked(client):
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/health", headers={"X-USC-Token": "wrong"}).status_code == 401
    assert client.get("/api/health", headers={"X-USC-Token": TOKEN, "Host": "evil.example:8770"}).status_code == 403
    assert client.get("/api/modes", headers=AUTH).status_code == 200

def test_static_index_needs_no_token(client_with_static):
    assert client_with_static.get("/").status_code == 200

def test_project_inputs_config_run_and_files(client): ...
    # POST /api/projects {"name": "p", "mode": "tilted_plane"} -> 200; POST inputs/max_volume and inputs/test_surfaces (multipart "file");
    # PUT config {"values": {"mode": "tilted_plane", "voxel_size": 2.0}} -> grid_plan present; POST runs -> started;
    # websocket events end with run_finished; GET run/files/run_report.md -> 200 (fake handler writes it)

def test_invalid_setting_is_422_with_the_field(client): ...          # field_errors[0]["field"] == "voxel_size"
def test_changes_during_a_run_are_409(client_with_blocking_run): ...   # POST inputs, DELETE inputs, PUT config -> 409
def test_second_run_is_409(client_with_blocking_run): ...
def test_websocket_without_token_is_refused(client): ...                # close code 4401
def test_files_outside_the_run_folder_are_404(client): ...              # GET run/files/..%2Fproject.json -> 404
def test_missing_inputs_are_422_with_their_roles(client): ...
def test_health_reports_the_warm_up_state(client): ...               # warm_up.state == "not_started"; with a GpuWarmUp whose fake function returns at once: "ready"
def test_stage_status_summary_and_sky_dome_routes(client_after_fake_run): ...
    # stage-status has the four stages; run/summary -> 200 with "carving"; run/sky-patches -> 404 for tilted_plane
def test_sun_path_is_empty_without_weather(client): ...             # time-based project without weather -> {"days": []}
def test_grid_over_budget_reply_carries_the_plan(client_with_inputs): ...   # PUT voxel_size 0.0125 -> 422, grid_plan.budget_voxels == 500_000_000
```

Write each `...` body with the assertions in its comment.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_local_web_server.py -q -p no:cacheprovider`
Expected: FAIL (`ImportError: create_app`).

- [ ] **Step 3: Implement `server.py`**

- [ ] **Step 4: Run them to verify they pass** (same command, all PASS), then check that the import stays light:

Run: `.venv/Scripts/python -c "import sys, urbansolarcarver.local_web_service.server; print('torch' in sys.modules)"`
Expected: `False`

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/local_web_service tests/test_local_web_server.py
git commit -m "feat(ui): local HTTP service with token and Host checks, stage status, summaries, warm-up state and run events"
```

---

### Task 7: Packaged example projects

**Files:**
- Create: `src/urbansolarcarver/example_projects/{basic_perimeter_block,new_building,multiple_buildings}/...`, `src/urbansolarcarver/example_projects/weather/USA_CO_Golden-NREL.724666_TMY3.epw`, `src/urbansolarcarver/example_projects/examples.json`
- Modify: `server.py` (routes `GET examples` and `POST projects/{name}/examples/{example}`), `pyproject.toml` (`[tool.setuptools.package-data] urbansolarcarver = ["ui_static/**/*", "example_projects/**/*"]`)
- Test: `tests/test_local_web_packaging.py`, `tests/test_local_web_server.py`

**Interfaces:**
- Produces: `examples.json`, one entry per example: `{"name", "title", "description", "mode", "max_volume": [files], "test_surfaces": [files], "weather": bool}`; `description` is one plain sentence for the start screen (UX 5.1),, written from what each example's folder and its README describe. `GET examples` replies `[{name, title, description}]`. The roles follow the example folders (for `new_building`: max volume `max_volume.ply`, test surfaces `neighbor_roofs.ply` and `neighbor_windows.ply`; for `basic_perimeter_block`: `maxVolume.ply` and `testSrfs.ply`; `multiple_buildings` as its folder holds). The route creates the project with the example's mode and adds its files through `ProjectStore.add_input`.

- [ ] **Step 1: Write the failing tests**

```python
def test_packaged_examples_match_the_examples_folder():
    for packaged in (PKG / "example_projects").rglob("*"):
        if packaged.is_file() and packaged.name != "examples.json":
            source = _source_of(packaged)
            assert packaged.read_bytes() == source.read_bytes(), f"{packaged} differs from {source}: copy it again"

def test_packaged_examples_are_under_two_megabytes():
    assert sum(p.stat().st_size for p in (PKG / "example_projects").rglob("*") if p.is_file()) < 2_000_000

def test_example_project_joins_two_test_surface_files(client): ...
    # POST /api/projects/nb/examples/new_building -> [f["name"] for f in inputs["test_surfaces"]] == ["neighbor_roofs.ply", "neighbor_windows.ply"];
    # GET /api/examples lists three entries, each with a non-empty description
```

(`_source_of(packaged)` maps `example_projects/weather/<f>` to `examples/weather/<f>` and `example_projects/<example>/<f>` to `examples/test_inputs/<example>/<f>`.)

- [ ] **Step 2: Run them to verify they fail.** Run: `.venv/Scripts/python -m pytest tests/test_local_web_packaging.py tests/test_local_web_server.py -q -p no:cacheprovider`. Expected: FAIL (no `example_projects`).

- [ ] **Step 3: Copy the files, write `examples.json`, add the route and the package-data entry**

- [ ] **Step 4: Run them to verify they pass** (same command)

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/example_projects src/urbansolarcarver/local_web_service pyproject.toml tests/test_local_web_packaging.py tests/test_local_web_server.py
git commit -m "feat(ui): example projects packaged with the service"
```

---

### Task 8: `usc ui` and installation

**Files:**
- Modify: `src/urbansolarcarver/carver_cli.py` (command `ui`), `setup_env.py` (installs `.[ui]`; `--no-ui` installs without it), `docs/getting-started/installation.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `create_app`, `GpuWarmUp` (Task 6).
- Produces: `usc ui [--port 8770] [--projects-folder ~/UrbanSolarCarver/projects] [--no-browser] [--device auto]`. Steps: (1) import `fastapi` and `uvicorn`; on `ImportError` print `The browser UI needs the ui extra: <python> -m pip install -e "<repo>[ui]"` (the repository folder when the package is an editable install, `urbansolarcarver[ui]` otherwise) and exit 1; (2) if `ui_static/index.html` is missing, print the folder and `cd app && npm install && npm run build` and exit 1; (3) token `secrets.token_hex(32)`; (3b) `warm_up = GpuWarmUp(device); warm_up.start()` and pass it to `create_app` (UX 6.1); (4) open `http://127.0.0.1:PORT/?token=...` with `webbrowser.open` unless `--no-browser` (and print it either way); (5) `uvicorn.run(app, host="127.0.0.1", port=port)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_ui_without_the_extra_names_the_install_command(monkeypatch): ...
    # monkeypatch builtins.__import__ to fail for "fastapi"; CliRunner().invoke(app, ["ui", "--no-browser"]) -> exit 1, "[ui]" in output

def test_ui_without_the_front_end_names_the_build_command(monkeypatch, tmp_path): ...
    # monkeypatch the static folder lookup to tmp_path; exit 1; "npm run build" in output

def test_ui_starts_uvicorn_on_localhost_with_a_token(monkeypatch): ...
    # monkeypatch uvicorn.run to record host/port and webbrowser.open to record the URL;
    # host == "127.0.0.1", URL starts with "http://127.0.0.1:8770/?token=" followed by 64 hex characters;
    # GpuWarmUp.start (monkeypatched to record) was called before uvicorn.run
```

- [ ] **Step 2: Run them to verify they fail.** Run: `.venv/Scripts/python -m pytest tests/test_cli.py -q -p no:cacheprovider -k ui`. Expected: FAIL (`No such command 'ui'`).

- [ ] **Step 3: Implement the command and the installer change**

- [ ] **Step 4: Run them to verify they pass** (same command), then `python setup_env.py --dry-run` and check that the printed install line contains `[ui]`.

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/carver_cli.py setup_env.py docs/getting-started/installation.md tests/test_cli.py
git commit -m "feat(ui): usc ui command with GPU warm-up at launch; the installer adds the ui extra"
```

---

### Task 9: Front-end scaffold, API client, theme tokens and build hash

**Files:**
- Create: `app/package.json`, `app/package-lock.json`, `app/vite.config.ts`, `app/tsconfig.json`, `app/index.html`, `app/src/main.tsx`, `app/src/App.tsx`, `app/src/messages.ts`, `app/src/theme/tokens.css`, `app/src/theme/fonts/` (Atkinson Hyperlegible Next woff2 for weights 400, 600, 700 and `OFL.txt`), `app/src/api_client/client.ts`, `app/src/api_client/generated_types.ts`, `app/src/api_client/events.ts`, `app/scripts/write_build_info.mjs`, `src/urbansolarcarver/ui_static/` (first build)
- Modify: `.gitignore` (`app/node_modules/`)
- Test: `tests/test_local_web_packaging.py` (build hash), `app/src/api_client/client.test.ts`, `app/src/theme/tokens.test.ts`, `app/src/messages.test.ts`

**Interfaces:**
- Produces:
  - npm scripts: `dev` (Vite, proxy `/api` with `ws: true` to `http://127.0.0.1:8770`), `api-types` (`python -c "import json; from urbansolarcarver.local_web_service.server import openapi_document; print(json.dumps(openapi_document()))" > openapi.json && openapi-typescript openapi.json -o src/api_client/generated_types.ts`), `build` (`vite build --outDir ../src/urbansolarcarver/ui_static --emptyOutDir && node scripts/write_build_info.mjs`), `test` (`vitest run`).
  - `client.ts`: `readTokenFromLaunchUrl(): string` (reads `?token=`, then removes it from the address bar with `history.replaceState`), and one typed function per route, each sending `X-USC-Token`, named `getHealth`, `getModes`, `getSchema`, `getExamples`, `listProjects`, `createProject`, `getProject`, `createProjectFromExample`, `addInput`, `removeInput`, `putConfig`, `getStageStatus`, `getSunPath`, `startRun`, `cancelRun`, `getRunSummary`, `getSkyPatches`, `getScorePoints`, plus `runFileUrl(project, path)` and `projectDownloadUrl(project)`; non-2xx replies throw `ApiError {status, body}`.
  - `events.ts`: `subscribeToRunEvents(runId, token, onEvent): () => void` over `ws://<host>/api/runs/<id>/events?token=`.
  - `tokens.css`: CSS custom properties on `:root` with the UX 10.1 values, named `--colour-chrome`, `--colour-panel`, `--colour-ink`, `--colour-muted`, `--colour-line`, `--colour-accent`, `--colour-accent-soft`, `--colour-sun`, `--colour-carved`, `--colour-ready`, `--colour-error`, `--colour-viewport-light`, `--colour-viewport-dark`, `--colour-grid-minor-light`, `--colour-grid-major-light`, `--colour-grid-minor-dark`, `--colour-grid-major-dark`, and the rows added with the screens (UX 17): `--colour-overlay-on-dark: #2b3a45`, `--colour-ink-on-dark: #e6ecee`, `--colour-muted-on-dark: #a9b6bc`, `--colour-line-on-dark: #3b4b56`, `--colour-test-surface-on-dark: #6fa0c4`, `--colour-axis-x: #b0603a`, `--colour-axis-y: #4f8a5b`, `--colour-axis-z: #3b6ea5`; type `--text-body: 14px`, `--text-secondary: 12px`, `--text-step-title: 16px`, `--text-key-number: 20px`, `--line-height: 1.4`; `--space-unit: 4px`; `--radius-large: 6px`, `--radius-small: 4px`; a 2 px `--colour-accent` outline on `:focus-visible` (UX 12); the `@font-face` rules for the bundled font; `font-variant-numeric: tabular-nums` on `body` when the font has tabular figures (check with a quick render of "1111" against "8888"; if the widths differ, bundle IBM Plex Sans for numbers and say so in the commit message).
  - `messages.ts`: `export const messages` with one entry per state of UX 11 and the device lines of UX 5.1 and 6.1, copied verbatim from the UX spec (functions where the text takes values, e.g. `gridOverBudget(voxelsPerSide, totalVoxels, budgetVoxels, smallestVoxelSize)` giving "This grid would have 884 voxels per side, 690 807 104 in total. The analysis can handle up to 500 000 000." and "Use 0.07 m or more.", and `fixSettingToRun(label)` giving "Fix the voxel size to run the analysis."), plus the warm-up line of UX 5.1 ("You can open a project and add files now. The run buttons wait until the GPU is ready.").
  - Build hash (both sides identical): files = `app/package.json`, `app/package-lock.json` and every file under `app/src`, sorted by their path relative to `app/` written with `/`; for each, update SHA-256 with `relative_path + "\n"` then the file bytes with every `\r\n` replaced by `\n`; `build_info.json` = `{"app_source_sha256": "<hex>"}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_front_end_build_matches_its_sources():
    recorded = json.loads((PKG / "ui_static" / "build_info.json").read_text())["app_source_sha256"]
    assert recorded == app_source_sha256(REPO / "app"), "app/ changed without a rebuild: run `cd app && npm run build` and commit ui_static/"
```

```ts
test("readTokenFromLaunchUrl takes the token and clears it from the address", () => {
  window.history.replaceState(null, "", "/?token=abc");
  expect(readTokenFromLaunchUrl()).toBe("abc");
  expect(window.location.search).toBe("");
});
test("tokens hold the UX spec colours", () => {
  const css = readFileSync("src/theme/tokens.css", "utf8");
  for (const [name, hex] of [["--colour-accent", "#2f5d7c"], ["--colour-sun", "#f2b632"], ["--colour-carved", "#c8553d"],
                              ["--colour-viewport-light", "#e3e8e7"], ["--colour-viewport-dark", "#22303a"],
                              ["--colour-overlay-on-dark", "#2b3a45"], ["--colour-test-surface-on-dark", "#6fa0c4"]])
    expect(css).toMatch(new RegExp(`${name}:\\s*${hex}`, "i"));
});
test("interface messages follow the copy rules", () => {
  const text = JSON.stringify(Object.values(messages).map(m => typeof m === "function" ? m(1, 2, 3, 4) : m));
  expect(text).not.toMatch(/plates?\b|floor plate|\u2014|NVIDIA/i);
  expect(text).toContain("No CUDA-enabled GPU found. USC runs on the CPU, which is slower.");
  expect(messages.fixSettingToRun("Voxel size")).toBe("Fix the voxel size to run the analysis.");
});
```

- [ ] **Step 2: Run them to verify they fail.** Run: `.venv/Scripts/python -m pytest tests/test_local_web_packaging.py -q -p no:cacheprovider -k build` and `cd app && npm test`. Expected: FAIL (no `build_info.json`; no `client.ts`, `tokens.css`, `messages.ts`).

- [ ] **Step 3: Scaffold the app with a minimal `App.tsx` (shows `GET health` in the body font), implement the client, events, tokens, messages and build script; run `npm install`, `npm run api-types`, `npm run build`**

- [ ] **Step 4: Run both again; both PASS.** Then `usc ui` and open the printed URL: the page shows the version and the warm-up state in Atkinson Hyperlegible Next.

- [ ] **Step 5: Commit**

```bash
git add .gitignore app src/urbansolarcarver/ui_static tests/test_local_web_packaging.py
git commit -m "feat(ui): front-end scaffold, typed API client, theme tokens and committed build with source hash"
```

---

### Task 10: 3D viewer with scale, orientation and the mode layers

**Files:**
- Create: `app/src/viewer/scene.ts`, `local_origin.ts`, `loaders.ts`, `layers.ts`, `score_points_decoder.ts`, `size_check.ts`, `ground_grid.ts`, `compass.ts`, `scale_bar.ts`, `sky_dome.ts`, `sun_path.ts`, `colour_scales.ts` and their `*.test.ts`; `app/src/viewer_overlays/Compass.tsx`, `AxisGizmo.tsx`, `ScaleBar.tsx`, `Legend.tsx`, `LayersMenu.tsx`, `ViewToolbar.tsx`
- Test: Vitest

**Interfaces:**
- Consumes: Task 9 client (`getScorePoints`, `getSkyPatches`, `getSunPath`, `runFileUrl`).
- Produces:
  - `localOrigin(bounds: [[number,number,number],[number,number,number]]): [number,number,number]` (the minimum corner) and `toLocal(point, origin)` in float64 before any `Float32Array` is filled.
  - `decodeScorePoints(buffer: ArrayBuffer): {header, indices: Uint32Array, scores: Float32Array, kept: Uint8Array | null, comparedScores: Float32Array | null}` (layout of Task 4) and `voxelCentres(header, indices, origin): Float32Array` (centre = header.origin + (ijk + 0.5) * voxel_size, minus the local origin).
  - `sizeWarning(bounds): string | null`: longest side over 10,000 m gives "This model is more than 10 km across. Is it in meters?"; under 1 m gives "This model is less than 1 m across. Is it in meters?".
  - `groundGridSpacing(longestSideMetres: number): {minorMetres: number, majorMetres: [number, number], extentMetres: number}`: `{10, [50, 100], 1000}`; under 30 m `{1, [10, 50], 1000}` (UX 8.1).
  - `scaleBarLength(metresPerPixel: number): {metres: number, pixels: number}`: the smallest value of the 1, 2, 5 × 10ⁿ series whose length is at least 100 px (so at most 250 px).
  - `northNeedleScreenAngle(cameraYawDegrees: number, northDegrees: number): number`: `northDegrees - cameraYawDegrees` normalised to [0, 360); camera yaw is the clockwise turn of the view about Z from the top view with +Y up the screen.
  - `hemisphere(maxVolumeBounds): {centre: [number,number,number], radius: number}`: centre at the footprint centre on the lowest z, radius 1.5 × the larger horizontal side (UX 8.2).
  - `cividis(t: number): string` (matplotlib's cividis, 0 → `#00224e`, 1 → `#fee838`), `sunRamp(t, viewportTheme): string` (viewport background to `--colour-sun`), `storeyColour(storeyIndex, storeyCount): string` (`#dfe6ea` to `#2f5d7c`).
  - `class ViewerScene`: `constructor(container: HTMLElement)`, Z up, `setNorth(deg)`, `setLayer(name: LayerName, object: THREE.Object3D | null)`, `setLayerVisible(name, visible)`, `setLayerDimmed(name, dimmed)` (out of date: 35 % opacity, desaturated), `setSkyDomeOpacity(opacity: number)`, `setViewportTheme(theme: "light" | "dark")`, `frameAll()`, `viewTop()` (north up), `onCameraChange(listener: (camera: {yawDegrees: number, metresPerPixel: number}) => void)`, `describe(): string` (accessible name, UX 12). `LayerName = "max_volume" | "test_surfaces" | "kept_voxels" | "carved_voxels" | "sun_path" | "sky_dome" | "envelope" | "building_massing"`. Orbit with the left button, pan with the right, zoom with the wheel; camera moves animate 400 ms, instant under `prefers-reduced-motion`.
  - Drawing as UX 8.2: maximum volume light solid (ghost in later steps), test surfaces solid accent (`--colour-test-surface-on-dark` on the dark viewport), kept voxels coloured by raw score with `cividis` over 0 to the cutoff (`keptScoreRange(thresholdValue): [0, thresholdValue]`), carved voxels in `--colour-carved` at 10 % opacity plus the maximum volume's top edges and front vertical edges above the kept voxels at 60 %, the sun path from `getSunPath` (`sunPathObjects(sunPath, hemisphere)` in `sun_path.ts`: per day a dashed `--colour-sun` line for `day_path`, a solid 3 px line for `period_path`, a sun disc and an "<hour> h" label sprite per marker), the 145 sky patches on the hemisphere coloured with `sunRamp`, envelope light solid, or translucent white (about 30 %, `--colour-ink` edges at about 20 %) while the building massing layer is on, building massing coloured with `storeyColour`. Ground grid and north arrow on z = 0 of the local origin, fading with distance.
  - `loadMesh(url, token, extension): Promise<THREE.BufferGeometry>` with three.js `PLYLoader`, `OBJLoader`, `STLLoader`, `GLTFLoader`.
  - Overlays (React, outside `viewer/`): compass top left (click: `viewTop()`), layers menu top right (only the layers that exist; the sky dome entry has the opacity slider; a missing layer shows the missing-result message), axis gizmo bottom left (lettered X, Y, Z in `--colour-axis-x/-y/-z`), scale bar bottom centre ("0 to 20 m"), legend bottom right (colouring on screen and unit; for kept voxels the 0-to-cutoff ramp with "Kept voxels. Carved voxels score above <cutoff>."; for the sun path "Sun path, 21 Dec; sun at 10, 12 and 14 h"; for the massing "Building massing, by storey" with a numbered swatch per storey; "Showing 1 of every k voxels" when thinned), toolbar at the top right left of the layers menu (three 40 px icon buttons: frame all, top view, light or dark viewport, with accessible names; remembered in `localStorage` under `usc.viewportTheme`, light by default). On the dark viewport every overlay uses the `*-on-dark` tokens (UX 8.1, 10.1).

- [ ] **Step 1: Write the failing tests**

```ts
test("georeferenced coordinates keep millimetre precision after the shift", () => {
  const origin = localOrigin([[500000.25, 4200000.5, 10], [500100.25, 4200050.5, 40]]);
  const local = Float32Array.from(toLocal([500012.345, 4200007.891, 12.5], origin));
  expect(local[0]).toBeCloseTo(12.095, 3); expect(local[1]).toBeCloseTo(7.391, 3);
});
test("size warning for kilometres and millimetres only", () => {
  expect(sizeWarning([[0, 0, 0], [12000, 10, 10]])).toMatch("10 km");
  expect(sizeWarning([[0, 0, 0], [0.5, 0.2, 0.1]])).toMatch("1 m");
  expect(sizeWarning([[0, 0, 0], [80, 60, 33]])).toBeNull();
});
test("score points decode to the header's counts, compared scores included", () => { /* Task 4 layout, 3 points, has_mask and has_compared_scores true; all four arrays length 3 */ });
test("ground grid is 10 m with 50 and 100 m lines, 1 m for small models", () => {
  expect(groundGridSpacing(80)).toEqual({minorMetres: 10, majorMetres: [50, 100], extentMetres: 1000});
  expect(groundGridSpacing(12)).toEqual({minorMetres: 1, majorMetres: [10, 50], extentMetres: 1000});
});
test("scale bar picks 1, 2, 5 steps at least 100 px long", () => {
  expect(scaleBarLength(0.1)).toEqual({metres: 10, pixels: 100});
  expect(scaleBarLength(0.13)).toEqual({metres: 20, pixels: 20 / 0.13});
});
test("north needle turns against the camera", () => {
  expect(northNeedleScreenAngle(0, 20)).toBe(20); expect(northNeedleScreenAngle(30, 20)).toBe(350);
});
test("hemisphere is 1.5 times the larger horizontal side", () => {
  expect(hemisphere([[0, 0, 2], [40, 30, 35]])).toEqual({centre: [20, 15, 2], radius: 60});
});
test("cividis endpoints", () => { expect(cividis(0)).toBe("#00224e"); expect(cividis(1)).toBe("#fee838"); });
test("kept voxels are coloured over 0 to the cutoff", () => { expect(keptScoreRange(1.5)).toEqual([0, 1.5]); });
test("sun path objects: two lines per day and one sun per marker", () => {
  const day = {date: "12-21", day_path: [[1, 0, 0.1], [0, -1, 0.4], [-1, 0, 0.1]], period_path: [[0.3, -1, 0.4], [-0.3, -1, 0.4]],
               markers: [{hour: 10, vector: [0.3, -1, 0.4]}, {hour: 12, vector: [0, -1, 0.45]}]};
  const objects = sunPathObjects({days: [day]}, {centre: [0, 0, 0], radius: 54});
  expect(objects.lines).toHaveLength(2); expect(objects.markers.map(m => m.label)).toEqual(["10 h", "12 h"]);
});
```

- [ ] **Step 2: Run them to verify they fail.** Run: `cd app && npm test`. Expected: FAIL (modules missing).

- [ ] **Step 3: Implement the viewer modules and the overlays**

- [ ] **Step 4: Run them to verify they pass** (`npm test`), then look at the `basic_perimeter_block` example in the browser preview in both viewport themes.

- [ ] **Step 5: Commit**

```bash
git add app/src/viewer app/src/viewer_overlays
git commit -m "feat(ui): three.js viewer with grid, compass, scale bar, sun path, mode layers and light or dark viewport"
```

---

### Task 11: Settings form with labels, units and help

**Files:**
- Create: `app/src/settings_form/setting_presentation.json`, `presentation.ts`, `SettingField.tsx`, `SettingGroup.tsx`, `SettingTooltip.tsx`, `widgets/AnalysisPeriod.tsx`, `widgets/TiltedPlaneAngles.tsx`, `widgets/SunStepsPerHour.tsx`, `widgets/MeshFormat.tsx`, `widgets/PercentSlider.tsx`, `presentation.test.ts`, `form_state.ts`, `form_state.test.ts`
- Test: `tests/test_local_web_packaging.py` (names and stages against the engine), Vitest

**Interfaces:**
- Consumes: `GET schema`, `GET modes`, `PUT config` (Task 9 client).
- Produces:
  - `setting_presentation.json`: `{"steps": {"settings": [group titles], "carving": [...], "envelope_and_massing": [...], "export": [...]}, "settings": {"<UserConfig field>": {"label", "unit", "help", "step", "group", "essential": "all" | [modes] | false, "modes": [modes] (absent = every mode), "display": "percent" (optional), "widget": (optional), "label_for_modes": {mode: label} (optional)}}}`. Content: the UX 7 table verbatim (labels, units, help, step, group, essential). Groups in order: settings `["When", "Mode specific", "Detail", "Computer"]`; carving `["How much to carve"]`; envelope_and_massing `["Envelope", "Building massing"]`; export `["Export"]`. The six period fields share `"widget": "analysis_period"` and the form draws one widget labelled by the `start_month` entry. `threshold` has `"widget": "threshold"` and `"label_for_modes": {"time-based": "Shadow tolerated"}` (label "Carving rule" otherwise); `carve_fraction` and `plate_tolerance` have `"display": "percent"`. `modes`: period fields `["time-based", "irradiance", "benefit"]`; `sun_steps_per_hour`, `min_altitude` `["time-based"]`; `balance_temperature`, `balance_offset`, `include_harm` `["benefit"]`; `tilted_plane_angle_deg` `["tilted_plane"]`; `dew_point_celsius`, `min_sky_elevation_deg`, `bliss_k` `["radiative_cooling"]`; `edge_taper`, `score_smoothing`, `carve_fraction` the four weighted modes; `threshold` every mode except `tilted_plane`.
  - `settingsForStep(step: StepName, mode: string): SettingGroupView[]` (the six period fields appear as one `SettingView` named `start_month`) with `SettingGroupView = {title, essential: SettingView[], folded: SettingView[], foldLabel: string}`; empty groups are left out. `foldLabel` follows UX 5.4: "More sun settings" (When), "More mode settings" (Mode specific), "More detail settings" (Detail), "More carving settings", "More envelope settings", "More massing settings"; a group with no essential settings (Computer) is one fold titled with the group name. `SettingGroup` draws the title as a 12 px, 600, muted header and the fold as a link-styled button under the essential settings. Building massing's three essential fields sit side by side (UX 5.6).
  - `toDisplayValue(name, value)` and `fromDisplayValue(name, shown)` (percent: × 100 and ÷ 100).
  - `SettingTooltip`: help text, then "Config name: `<name>`, default <value> <unit>" in 12 px muted with the name in monospace, opening on hover, focus and click, closing with Escape, pointing at its "i" (whose background turns `--colour-accent-soft` while open, UX 7); the voxel size tooltip adds the grid from the last `PUT config` reply ("62 voxels per side, 238 328 in total").
  - `form_state.ts`: `formReducer` (values, field errors, grid plan, pending save); a mode choice fills `starting_values` from `GET modes` and keeps the shared settings the user set; every change sends `PUT config` debounced 400 ms; a 422 puts each field error under its field.

- [ ] **Step 1: Write the failing tests**

```python
STEP_STAGES = {"settings": {*PreprocessingSettings.model_fields, *RunOptions.model_fields},
               "carving": set(ThresholdingSettings.model_fields),
               "envelope_and_massing": {*ExportingSettings.model_fields, *MassingSettings.model_fields} - {"final_mesh_format"},
               "export": {"final_mesh_format"}}
OWNED = {"max_volume_path", "test_surface_path", "epw_path", "out_dir", "device", "mode", "diagnostic_plots", "simulated_weights_path"}

def _presentation():
    return json.loads((REPO / "app/src/settings_form/setting_presentation.json").read_text(encoding="utf-8"))["settings"]

def test_every_shown_setting_is_presented_exactly_once():
    assert set(_presentation()) == set(UserConfig.model_fields) - OWNED

def test_each_step_holds_only_settings_of_its_stage():
    for name, entry in _presentation().items():
        assert name in STEP_STAGES[entry["step"]], (name, entry["step"])

def test_mode_lists_name_engine_modes():
    for entry in _presentation().values():
        for key in ("modes", "essential"):
            if isinstance(entry.get(key), list):
                assert set(entry[key]) <= set(MODES)
```

```ts
test("essential settings of the Settings step per mode", () => {
  const names = (mode: string) => settingsForStep("settings", mode).flatMap(g => g.essential.map(s => s.name));
  expect(names("time-based")).toEqual(["start_month", "north_deg", "voxel_size"]);
  expect(names("benefit")).toContain("balance_temperature");
  expect(names("tilted_plane")).toEqual(["north_deg", "tilted_plane_angle_deg", "voxel_size"]);
});
test("time-based carving folds the cut-above and slope settings", () => {
  const [group] = settingsForStep("carving", "time-based");
  expect(group.essential.map(s => s.name)).toEqual(["threshold"]);
  expect(group.folded.map(s => s.name)).toEqual(["carve_above", "carve_above_min_consecutive", "max_slope_deg"]);
  expect(group.foldLabel).toBe("More carving settings");
});
test("percent settings convert both ways", () => {
  expect(toDisplayValue("carve_fraction", 0.3)).toBe(30); expect(fromDisplayValue("plate_tolerance", 20)).toBe(0.2);
});
test("choosing a mode fills its starting values and keeps the shared ones the user set", () => { /* formReducer */ });
```

- [ ] **Step 2: Run them to verify they fail.** Run: `.venv/Scripts/python -m pytest tests/test_local_web_packaging.py -q -p no:cacheprovider -k "presented or stage or mode_lists"` and `cd app && npm test`. Expected: FAIL (files missing).

- [ ] **Step 3: Write the presentation file and the form modules**

- [ ] **Step 4: Run them to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add app/src/settings_form tests/test_local_web_packaging.py
git commit -m "feat(ui): settings with plain labels, units and tooltips, placed by pipeline stage"
```

---

### Task 12: Start screen, step accordion, Inputs, Mode and Settings

**Files:**
- Create: `app/src/steps/StartScreen.tsx`, `StepAccordion.tsx`, `InputsStep.tsx`, `ModeStep.tsx`, `SettingsStep.tsx`, `mode_tiles.json`, `ModeTileSymbols.tsx`, `step_summaries.ts`, `format_numbers.ts`, `grid_budget.ts` (+ `*.test.ts`)
- Modify: `app/src/App.tsx` (top bar, start screen or the accordion beside the viewer)
- Test: Vitest; `tests/test_local_web_packaging.py` (tile names against the engine)

**Interfaces:**
- Consumes: client (Task 9), `ViewerScene` and overlays (Task 10), `settingsForStep`, `SettingGroup`, `formReducer` (Task 11); `GET health`, `GET examples`, `GET projects/{name}/stage-status`, `GET projects/{name}/sun-path` (Tasks 6 and 7).
- Produces:
  - `App` layout (UX 4): top bar (product name, project name, "Projects" link, device status dot and text; on the start screen only the product name and the device status), left panel 340 px wide with its own scroll and the open step's run button pinned under the step list with its disabled reason, the viewer filling the rest; minimum window 1280 × 720; below 1100 px wide the panel overlays the view.
  - `StartScreen` (UX 5.1): version, device card from `GET health` polled every second while `warm_up == "running"` (spinner, "Preparing the GPU" and the warm-up line of `messages`), three cards side by side: New project ("Project name" field with the hint "Up to 64 letters, numbers, spaces, hyphens or underscores.", **Create project** sends `createProject(name, "time-based")`), Open a project (name and last modified date and time, newest first), Try an example (title and one-line description from `GET examples`). Choosing one opens the accordion with Inputs open.
  - `StepAccordion`: one step open at a time; each closed step shows `stepSummary(step, state)`; steps never lock; a step that cannot be used yet explains why when opened (UX 4.1). Each row starts with its state mark (tick on `--colour-ready`, "!" on `--colour-error` with the summary in `--colour-error` and 600, empty ring, accent ring on the open step); the "1 setting to fix" summary stays visible while the step is open.
  - `stepSummary(step: StepName, state: ProjectViewState): string`, giving exactly the UX 4.1 texts, e.g. `"1 volume, 2 test surfaces, weather"`, `"Test surfaces missing"`, `"21 Dec, 10 to 14 h; 1 m voxels"`, `"1 setting to fix"`, `"61 % kept"`, `"Not run yet"`, `"4 820 m², 7 storeys"`, `"Out of date"`, `"Not built yet"`, `"Ready"`, `"Build the envelope first"`.
  - `formatNumber(value: number, unit?: string, decimals = 0): string`: thousands separated by U+202F (narrow no-break space), unit after U+00A0; `formatPercent` rounds to whole numbers.
  - `InputsStep` (UX 5.2): boxes Maximum volume, Test surfaces, Weather file (optional), each with "Add files" (picker and drag and drop) and the file list (name, triangle count, remove); the empty and filled box texts of UX 5.2 ("Required", the one-line hints, "or drop them here", **Replace** in a filled weather box, "Remove <file name>" as the remove button's name); the weather box shows the location and which modes need it; "Size of all inputs together" with the joined size in metres, and `sizeWarning`; meshes drawn on arrival and framed; add and remove disabled during a run with the reason.
  - `mode_tiles.json`: the six tiles of UX 5.3 (`engine_name`, `plain_name`, `one_line`, `tooltip`, `needs` as the tooltip sentence, e.g. "Needs a weather file and an analysis period.", `symbol`, `experimental`). `ModeStep`: a 3 × 2 radio group (arrow keys move, Space or Enter selects), tile states of UX 5.3 (chosen: 2 px accent border on accent soft; hovered: muted border), tooltip on hover, focus and the tile's "i" (plain name, tooltip, needs, "Engine name: `<engine_name>`"), the line "Choosing a mode fills its starting values in Settings." under the tiles, and a weather drop zone under the tiles when the chosen mode needs one and none is uploaded.
  - `SettingsStep` (UX 5.4): the groups from `settingsForStep("settings", mode)`, the grid line under Voxel size, the over-budget message from `messages.gridOverBudget` with `smallestVoxelSizeWithinBudget(voxelSize: number, totalVoxels: number, budgetVoxels: number): number` (in `grid_budget.ts`) = `voxelSize * cbrt(totalVoxels / budgetVoxels)` rounded up to 0.01 m below 1 m and to 0.1 m from 1 m up (UX 11), from the `grid_plan` and `budget_voxels` of the 422 reply (Task 3), with the field outline 2 px `--colour-error` and the message under it with a warning icon, and **Run analysis** pinned to the panel bottom (disabled with its reason while inputs, weather, a field or the warm-up block it; for a field, `messages.fixSettingToRun(label)`). The sun path layer (`getSunPath`) is requested whenever the mode is time-based and the weather file and period are set, before any run. During a run of this project the fields are disabled with "A run is in progress" (the service replies 409 to `PUT config` then).

- [ ] **Step 1: Write the failing tests**

```python
def test_mode_tiles_name_every_engine_mode_once():
    tiles = json.loads((REPO / "app/src/steps/mode_tiles.json").read_text(encoding="utf-8"))
    assert sorted(t["engine_name"] for t in tiles) == sorted(MODES)
```

```ts
test("closed steps summarise their state in the UX spec's words", () => {
  expect(stepSummary("inputs", stateWith({maxVolume: 1, testSurfaces: 2, weather: true}))).toBe("1 volume, 2 test surfaces, weather");
  expect(stepSummary("inputs", stateWith({maxVolume: 1, testSurfaces: 0}))).toBe("Test surfaces missing");
  expect(stepSummary("envelope_and_massing", stateWith({totalFloorArea: 4820, storeys: 7, stages: {massing: "current"}}))).toBe("4 820 m², 7 storeys");
  expect(stepSummary("envelope_and_massing", stateWith({stages: {massing: "out_of_date"}}))).toBe("Out of date");
});
test("numbers use narrow no-break spaces", () => { expect(formatNumber(31400, "m³")).toBe("31 400 m³"); });
test("smallest voxel size that fits the budget", () => {
  expect(smallestVoxelSizeWithinBudget(1.0, 1_500_000_000, 500_000_000)).toBe(1.5);
  expect(smallestVoxelSizeWithinBudget(0.06, 690_807_104, 500_000_000)).toBe(0.07);   // 0.0668, to 0.01 m below 1 m
  expect(smallestVoxelSizeWithinBudget(1.0, 600_000_000, 500_000_000)).toBe(1.1);     // 1.0627, to 0.1 m from 1 m up
});
test("a new project's Mode summary names its starting mode", () => {
  expect(stepSummary("mode", stateWith({mode: "time-based"}))).toBe("Sun at set hours");
});
```

- [ ] **Step 2: Run them to verify they fail.** Run: `cd app && npm test` and `.venv/Scripts/python -m pytest tests/test_local_web_packaging.py -q -p no:cacheprovider -k tiles`. Expected: FAIL.

- [ ] **Step 3: Implement the layout, start screen, accordion and the three steps**

- [ ] **Step 4: Run the tests (PASS), rebuild (`npm run build`), and check by hand** in the browser preview against `usc ui --no-browser`: the start screen during warm-up, a new project, the `new_building` example (two test surface files), a mode needing weather without one (drop zone, Run disabled with reason), a voxel size over the budget, keyboard-only use of the mode tiles.

- [ ] **Step 5: Commit**

```bash
git add app src/urbansolarcarver/ui_static tests/test_local_web_packaging.py
git commit -m "feat(ui): start screen, step accordion, inputs, mode tiles and analysis settings"
```

---

### Task 13: Carving, Envelope and massing, Export, and the run loop

**Files:**
- Create: `app/src/steps/CarvingStep.tsx`, `ScoreHistogram.tsx`, `score_histogram.ts`, `EnvelopeAndMassingStep.tsx`, `RunReportPanel.tsx`, `ExportStep.tsx`, `RunProgress.tsx`, `run_state.ts`, `threshold_queue.ts` (+ `*.test.ts`)
- Modify: `app/src/App.tsx`, `StepAccordion.tsx`, `SettingsStep.tsx` (Run analysis wired to the run loop)
- Test: Vitest

**Interfaces:**
- Consumes: Tasks 9 to 12; `POST runs`, run events, `GET run/summary`, `GET run/score-points`, `GET run/sky-patches`, `GET stage-status`, `GET run/files/...`.
- Produces:
  - `runReducer(state, event)` in `run_state.ts`: per-stage `waiting | running | done`, `done/total` during ray tracing, issues, final `finished | failed | cancelled`, elapsed time; stage display names "Sun analysis", "Carving", "Envelope mesh", "Building massing".
  - `RunProgress`: the stage list with states, elapsed time, Cancel, under the button that started the run; every other run button disabled with "A run is in progress" (UX 6.4); the progress bar along the top of the viewer; "Results are up to date" for three seconds when `POST runs` replies so. Layers update stage by stage; until new data arrives the previous layer stays, dimmed.
  - `createThresholdUpdateQueue(applyAndRun: (value: number) => Promise<void>): {submit(value: number): void, busy(): boolean}`: at most one `applyAndRun` at a time; values submitted while one runs replace each other, and exactly one more call follows with the last value (Review Focus 5). `applyAndRun` = `PUT config` with the value, then `POST runs {"produce": ["thresholding"]}`, resolving at the run's final event.
  - `histogramBins(compared: Float32Array, kept: Uint8Array, binCount: number): {lower, upper, keptCount, carvedCount}[]` over the occupied voxels sent; `stackedBarHeights(keptCount, carvedCount, scale: "log" | "linear", plotHeight, decades): {kept, carved}` (log: kept from the axis to log(kept), carved from log(kept) to log(kept + carved), UX 5.5); `ScoreHistogram`: titled "Scores of the voxels", split bars (kept `--colour-accent`, carved `--colour-carved`), cutoff as a dashed `--colour-ink` line at the summary's `threshold_value` with its value on an ink label, log y axis by default with a **Log** / **Linear** switch at the title's right, the "Kept" / "Carved" key under the chart, hover reading "0.9 to 1.2 m²·h" and "880 kept, 92 carved", axis title "Shadow tolerated at which a voxel is carved, m²·h" (time-based) or "Score compared with the cutoff (relative)" (weighted), and the slope-limit note "The slope limit removed N voxels below the cutoff." when `slope_limit_extra_voxels_removed > 0`. No histogram for `tilted_plane`.
  - `CarvingStep` (UX 5.5): threshold control per mode (Shadow tolerated number and slider, the slider ends labelled "0" and "<maximum>, the highest score", with "More carving settings" folding the cut-above and slope settings; Carve amount percent slider and number, with the folded thresholding settings; the angle rule's message), the histogram, the numbers as tiles two per row (Volume kept, Volume carved, Kept volume, Obstruction removed for weighted modes, "Last analysis took"), the "Update when I change the threshold" switch (on by default, stored in `localStorage` under `usc.autoUpdate.<project>`; off shows **Update carving**), and **Build envelope and massing** pinned to the bottom. When `stage-status` reports preprocessing not `current`: the carving dimmed, the control and switch disabled, the UX 5.5 message, and a Run analysis button.
  - `EnvelopeAndMassingStep` (UX 5.6): the envelope and building massing groups, **Build envelope and massing** (`produce: ["exporting", "massing"]`), results (Gross floor area, Storeys, Envelope volume as tiles in one row; the table captioned "Floor area per storey" with columns "Storey", "Bottom, m", "Top, m", "Area, m²", storeys numbered from 1 with the first row "1, ground", a swatch of `storeyColour` per row, heights to one decimal, a bold "Total" row), "Open the run report" opening `RunReportPanel` over the viewer (the report as preformatted text in milestone 1), and the out-of-date state (results greyed with "Out of date for the current carving", layers dimmed) when exporting or massing is `out_of_date`.
  - `ExportStep` (UX 5.7): links for the envelope mesh, "Building massing (OBJ)", "Building massing data (JSON)", `config.yaml`, the project zip; the mesh format choice (`produce: ["exporting"]` on change); out-of-date files labelled and still downloadable.
  - Every state of UX 11 shown with its `messages` entry; run failures with a "Details" fold and a link to the named field; the full overlay when the engine is not reachable (WebSocket or fetch failure).

- [ ] **Step 1: Write the failing tests**

```ts
test("run events build per-stage progress, issues and the final state", () => {
  let s = initialRunState(["preprocessing", "thresholding"]);
  s = runReducer(s, {type: "stage_progress", stage: "preprocessing", done: 3, total: 10});
  s = runReducer(s, {type: "issue", stage: "preprocessing", code: "W1", message: "m"});
  s = runReducer(s, {type: "run_failed", error_type: "InputError", message: "broken", field_errors: []});
  expect(s.stages.preprocessing).toMatchObject({done: 3, total: 10});
  expect(s.issues).toHaveLength(1); expect(s.final).toBe("failed");
});
test("threshold moves during a run give exactly one more run, with the last value", async () => {
  const calls: number[] = []; let finish!: () => void;
  const queue = createThresholdUpdateQueue(v => { calls.push(v); return new Promise(r => { finish = r; }); });
  queue.submit(1); queue.submit(2); queue.submit(3); queue.submit(4);
  finish(); await flush(); finish(); await flush();
  expect(calls).toEqual([1, 4]); expect(queue.busy()).toBe(false);
});
test("histogram bins split kept and carved and count every voxel", () => {
  const bins = histogramBins(Float32Array.from([0, 0, 1, 5, 9]), Uint8Array.from([1, 1, 1, 0, 0]), 3);
  expect(bins.reduce((n, b) => n + b.keptCount + b.carvedCount, 0)).toBe(5);
  expect(bins[0]).toMatchObject({keptCount: 3, carvedCount: 0}); expect(bins[2]).toMatchObject({keptCount: 0, carvedCount: 1});
});
test("on the log scale the carved part sits on top of the kept part", () => {
  const h = stackedBarHeights(100, 900, "log", 100, 4);       // log10(100) = 2, log10(1000) = 3, of 4 decades
  expect(h.kept).toBeCloseTo(50); expect(h.carved).toBeCloseTo(25);
});
```

- [ ] **Step 2: Run them to verify they fail.** Run: `cd app && npm test`. Expected: FAIL.

- [ ] **Step 3: Implement the steps, the histogram, the queue and the run progress**

- [ ] **Step 4: Run the tests (PASS), rebuild (`npm run build`), and check the whole flow by hand** in the browser preview against `usc ui --no-browser`, noting and fixing anything that fails before the commit:
  - the `basic_perimeter_block` example in time-based mode: Run analysis, then Carving opens with the voxels, the sun path with its hour suns and the histogram with its cutoff line, matching the screens of UX 17;
  - the threshold moved quickly several times with auto-update on (one queued run, last value shown), then with it off (Update carving);
  - a weighted mode: the sky dome with its opacity slider, the Carve amount control, the cutoff line;
  - Build envelope and massing after an analysis-only run (it runs, it is not "up to date"); then a threshold change: envelope and massing dimmed and "Out of date";
  - a voxel size change after a run: Carving locked with the message and its Run analysis button;
  - Cancel during the sun analysis; an invalid setting from a failed run linking to its field;
  - light and dark viewport; a keyboard-only pass through all steps; the page at 200 % browser zoom; the export downloads.

- [ ] **Step 5: Commit**

```bash
git add app src/urbansolarcarver/ui_static
git commit -m "feat(ui): carving with histogram and threshold loop, envelope and massing, export"
```

---

### Task 14: Documentation and full check

**Files:**
- Create: `docs/ui.md`
- Modify: `mkdocs.yml` (nav entry "Browser UI"), `README.md` (feature line and `usc ui`), `CHANGELOG.md` (Unreleased > Added, including the new thresholding output), `docs/project-map.md` (the new modules and `app/`)

- [ ] **Step 1: Write the docs.** `docs/ui.md`: starting `usc ui`, the start screen, the six steps and the two phases (Run analysis, then Build envelope and massing), the threshold loop, where projects are kept, the security model in two sentences, CPU mode on machines without a CUDA-enabled GPU, and how to rebuild the front-end after changing `app/`.

- [ ] **Step 2: Run the whole suite and the front-end tests**

Run: `.venv/Scripts/python -m pytest tests -q -p no:cacheprovider` and `cd app && npm test`
Expected: all pass (the slow tests included).

- [ ] **Step 3: Commit**

```bash
git add docs mkdocs.yml README.md CHANGELOG.md
git commit -m "docs(ui): browser UI page, README, changelog and project map"
```
