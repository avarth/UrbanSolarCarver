# Local Web UI (milestone 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `usc ui` starts a local web service and opens a browser app in which a user imports a maximum volume and test surfaces, chooses a mode and settings, runs the pipeline with progress, reviews the result in 3D and exports it.

**Architecture:** A FastAPI service in `src/urbansolarcarver/local_web_service/` turns HTTP requests into calls to the existing engine (`engine_requests.handle_engine_request`, `load_config`, `stage_settings`, `grid_planning`), keeps one project folder per project and runs one pipeline at a time on a worker thread. A React + three.js app in `app/` talks to it only over HTTP and a WebSocket; its production build is committed in `src/urbansolarcarver/ui_static/`.

**Tech Stack:** Python 3.10, FastAPI, uvicorn, python-multipart, trimesh, numpy, pytest with FastAPI `TestClient` (httpx); TypeScript, Vite, React 18, three.js, openapi-typescript (dev), Vitest; Node 24 for front-end work only.

**Spec:** `docs/superpowers/specs/2026-10-16-local-web-ui-design.md`

## Global Constraints

- Binds to `127.0.0.1` only. Random token of 32 bytes (hex) per launch, sent as `X-USC-Token` header (WebSocket: `token` query parameter). Missing or wrong token: 401. `Host` must be `127.0.0.1:PORT` or `localhost:PORT`, otherwise 403. Static files are served without the token.
- The service never takes a file path from the browser; files arrive by upload. The service sets `max_volume_path`, `test_surface_path`, `epw_path`, `out_dir` and `device` itself and ignores values the browser sends for them.
- One run at a time per service process. While a project's run is active, uploads, removals and `PUT config` for that project reply 409.
- Importing `urbansolarcarver.local_web_service` must not import torch; the first run (or `GET health`) does.
- FastAPI, uvicorn and python-multipart live in the optional `ui` extra; `httpx` joins the `dev` extra.
- The built front-end in `src/urbansolarcarver/ui_static/` is committed; `ui_static/build_info.json` holds the hash of the front-end sources.
- Score layer: at most 1,000,000 voxels, evenly thinned above that.
- The essential/advanced split and the form sections live only in `app/`.
- Grasshopper and the pickle daemon are unchanged.
- Writing rules (code comments, docs, UI copy): long descriptive names, no em dashes, no cliché labels, they/them for people.
- Tests that take seconds get the `slow` marker; there is no CI, tests run locally.

## Review Focus

1. A project name with path parts or odd characters (`../x`, `a/b`, empty, 200 characters): 422, and nothing is written outside the projects folder. Test in Task 1.
2. A corrupt mesh or an unsupported extension uploaded into a role that already has files: 422, the earlier files and the joined file stay as they were. Test in Task 2.
3. A browser that connects to the run events after the run has finished (slow page, reconnect, second tab): it still receives every event of that run, ending with the final one. Test in Task 5.
4. A service stopped during a run and started again: the next run of that project is complete (starts at preprocessing), because `last_completed_run_config.yaml` was deleted when the run started. Test in Task 5.
5. A georeferenced model (coordinates in the millions) or a model drawn in millimetres: the 3D view stays precise after the local-origin shift, and the size warning appears for a longest side over 10 km or under 1 m. Test in Task 10.

---

## File Structure

```
src/urbansolarcarver/local_web_service/
  __init__.py          create_app re-export only (no torch)
  api_models.py        pydantic request, reply and event models
  projects.py          project folders, names, uploads, joining, project.json, config.yaml
  score_points.py      binary score layer data with the cap
  run_worker.py        stage choice, RunWorker thread, run events, error mapping
  server.py            FastAPI app factory, security checks, routes, WebSocket, static files
src/urbansolarcarver/example_projects/      copies of three examples and the Golden EPW
src/urbansolarcarver/ui_static/             committed front-end build (+ build_info.json)
src/urbansolarcarver/carver_cli.py          + `usc ui`
pyproject.toml                              ui extra, httpx in dev, package-data
setup_env.py                                installs the ui extra (unless --no-ui)
app/
  package.json, package-lock.json, vite.config.ts, tsconfig.json, index.html
  scripts/write_build_info.mjs
  src/main.tsx, src/App.tsx
  src/api_client/      client.ts, generated_types.ts, events.ts
  src/viewer/          scene.ts, local_origin.ts, loaders.ts, layers.ts, score_points_decoder.ts, size_check.ts
  src/settings_form/   setting_tiers.json, setting_sections.json, SettingsForm.tsx, widgets/*.tsx
  src/steps/           ProjectStep.tsx, InputsStep.tsx, SettingsStep.tsx, RunStep.tsx, ReviewStep.tsx, ExportStep.tsx
tests/
  test_local_web_projects.py, test_local_web_score_points.py, test_local_web_run_worker.py,
  test_local_web_server.py, test_local_web_packaging.py, test_cli.py (+ usc ui)
docs/ui.md, mkdocs.yml, README.md, CHANGELOG.md, docs/getting-started/installation.md
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
  - `api_models.ProjectJson(BaseModel)`: `name: str`, `created: str` (ISO 8601 UTC), `inputs_changed_since_last_run: bool = True`.
  - `api_models.ProjectSummary(BaseModel)`: `name: str`, `created: str`, `mode: str`.
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
    assert data.name == "Block 7" and data.inputs_changed_since_last_run is True

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
  - `ProjectStore.add_input(name, role, file_name, data: bytes) -> InputFilesReply`: for a mesh role, writes to a temporary file in the role folder, checks it with `load_mesh` (an `InputError` or an extension outside `MESH_EXTENSIONS` gives `ProjectError(422)` with the engine message, the temporary file removed), then moves it into place (same name replaced) and rebuilds the joined file. For `role == "weather"`: extension `.epw`, stored as `inputs/weather.epw`. Sets `inputs_changed_since_last_run = True`.
  - `ProjectStore.remove_input(name, role, file_name) -> InputFilesReply` (404 if absent), rebuilds the joined file (removes it when the role is empty), sets the flag.
  - `ProjectStore.input_files(name, role) -> list[str]` (sorted), `ProjectStore.input_file_path(name, role, file_name) -> Path`.
  - `ProjectStore.joined_bounds(name) -> list[list[float]] | None`: `[[xmin,ymin,zmin],[xmax,ymax,zmax]]` of `inputs/joined/max_volume.ply`, None if absent.
  - `api_models.InputFilesReply`: `role: str`, `files: list[str]`, `joined_bounds: list[list[float]] | None` (always the max volume's).
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
    assert reply.files == ["a.ply", "b.ply"]
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
    assert store.input_files("p", "max_volume") == ["a.ply"]
    assert (tmp_path / "p/inputs/joined/max_volume.ply").read_bytes() == before

@pytest.mark.parametrize("raw, clean", [("../../evil.ply", "evil.ply"), ("C:\\x\\my model.obj", "mymodel.obj"), ("bü ro.stl", "bro.stl")])
def test_file_names_are_sanitized(raw, clean):
    assert sanitize_file_name(raw) == clean

def test_upload_sets_the_inputs_changed_flag(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    data = store.read_project_json("p"); data.inputs_changed_since_last_run = False; store.write_project_json("p", data)
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    assert store.read_project_json("p").inputs_changed_since_last_run is True
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
  - `api_models.GridPlanReply`: `resolution: int`, `voxel_size: float`, `total_voxels: int`, `extent: float`.
  - `api_models.ConfigReply`: `settings: dict`, `grid_plan: GridPlanReply | None`.
  - `api_models.FieldErrorReply`: `field: str | None`, `message: str`; `api_models.ConfigErrorReply`: `field_errors: list[FieldErrorReply]`.

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

### Task 4: Score layer data

**Files:**
- Create: `src/urbansolarcarver/local_web_service/score_points.py`
- Test: `tests/test_local_web_score_points.py`

**Interfaces:**
- Consumes: `run/preprocessing/manifest.json` (`PreprocessingManifest`: `scores_path`, `scores_kind`, `shape`, `origin`, `voxel_size`, `voxel_grid_path`, `mode`; paths relative to the manifest's folder), `run/thresholding/manifest.json` (`ThresholdingManifest.mask_path`), `mode_registry.MODES[mode].weight_unit`.
- Produces:
  - `SCORE_POINTS_CAP = 1_000_000`.
  - `build_score_points(run_folder: Path, cap: int = SCORE_POINTS_CAP) -> bytes | None` (None when there is no preprocessing output).
  - Binary layout (little-endian): `uint32` header length in bytes; header JSON (UTF-8) padded with spaces to a multiple of 4; `uint32` flat indices (C order of `shape`); `float32` scores; `uint8` kept (1) or carved (0), present only when `has_mask`.
  - Header keys: `origin`, `shape`, `voxel_size`, `scores_kind`, `weight_unit`, `score_min`, `score_max`, `occupied_count`, `point_count`, `thinning_step`, `has_mask`.
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
    return header, idx, scores, kept

def test_arrays_match_the_header_and_the_occupied_voxels(tmp_path):
    run = _fake_run(tmp_path)
    header, idx, scores, kept = _decode(build_score_points(run))
    assert header["occupied_count"] == header["point_count"] == 18 and header["thinning_step"] == 1
    assert len(idx) == len(scores) == len(kept) == 18 and (np.diff(idx) > 0).all()

def test_above_the_cap_every_kth_voxel_is_kept(tmp_path):
    run = _fake_run(tmp_path)
    header, idx, _, _ = _decode(build_score_points(run, cap=5))
    assert header["thinning_step"] == 4 and header["point_count"] == 5      # ceil(18 / 5) = 4, ceil(18 / 4) = 5
    occupied = np.flatnonzero(np.load(run / "preprocessing" / "voxel_grid.npy").ravel())
    assert (idx == occupied[::4]).all()

def test_without_thresholding_the_kept_array_is_absent(tmp_path):
    header, idx, _, kept = _decode(build_score_points(_fake_run(tmp_path, with_mask=False)))
    assert header["has_mask"] is False and kept is None

def test_without_preprocessing_there_is_no_data(tmp_path):
    assert build_score_points(tmp_path / "run") is None
```

(`_fake_run` builds the manifests with the real `PreprocessingManifest` and `ThresholdingManifest` models so field names stay in step with the engine.)

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_local_web_score_points.py -q -p no:cacheprovider`
Expected: FAIL (`ImportError: build_score_points`).

- [ ] **Step 3: Implement `build_score_points`**

- [ ] **Step 4: Run them to verify they pass** (same command, 4 PASS)

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/local_web_service/score_points.py tests/test_local_web_score_points.py
git commit -m "feat(ui): binary score layer data with an even cap"
```

---

### Task 5: Run worker: stage choice, events, cancel

**Files:**
- Create: `src/urbansolarcarver/local_web_service/run_worker.py`
- Modify: `api_models.py`
- Test: `tests/test_local_web_run_worker.py`

**Interfaces:**
- Consumes: `ProjectStore` (Tasks 1 to 3); `stage_settings.stages_needed_for(produce) -> list[str]`, `stage_settings.stages_to_rerun(previous_config, new_config, produce) -> list[str]`, `stage_settings.PIPELINE_STAGES`; `engine_requests.RunRequest(cmd="run", produce, run_folder, start_from, config)`, `engine_requests.handle_engine_request(request, session, context) -> RunReply`; `run_context.RunContext(on_progress)` with `.issues`, `.cancel()`; errors `ConfigError`, `InputError`, `StageChainError`, `RunCancelled`.
- Produces:
  - `choose_stages(store: ProjectStore, name: str, produce: list[str]) -> list[str]`: spec 5.5 step 2. Reads `last_completed_run_config.yaml` with `load_config` when present.
  - `missing_inputs(store, name, config) -> list[str]`: roles without a joined file, plus `"weather"` when `MODES[config.mode].needs_epw` and `inputs/weather.epw` is absent.
  - `class RunState`: `run_id: str`, `project: str`, `stages: list[str]`, `events: list[dict]`, `finished: bool`; `wait_for_events(after: int, timeout: float) -> list[dict]` (blocks on a `threading.Condition` until events beyond index *after* exist, the run finished, or the timeout passes).
  - `class RunWorker`: `__init__(self, store: ProjectStore, device: str, handle_request=None, session_factory=None)` (defaults: `engine_requests.handle_engine_request` and `lambda device: CarverSession(device)`, both imported lazily so torch loads on the first run); `start(name: str, produce: list[str]) -> StartRunReply`; `cancel(run_id: str) -> bool`; `active_project() -> str | None`; `run_state(run_id) -> RunState | None`. `start` raises `RunConflict` (409) when a run is active and `MissingInputs(roles)` (422) when inputs are missing.
  - Lifecycle in `start` and the thread exactly as spec 5.5: delete `last_completed_run_config.yaml` before the thread starts; on success copy `config.yaml` (as loaded at start, re-dumped) to `last_completed_run_config.yaml` and set `inputs_changed_since_last_run = False`; on `StageChainError` also delete it (it is already absent) and send its message as spec 5.6 says.
  - Events (dicts, `type` first): `stage_progress {stage, done, total}`; `issue {stage, code, message}` (new `context.issues` entries, sent before each progress event and before the final event); `run_finished {stages, files}` (`files`: paths relative to `run/` of `exporting/*` mesh, `massing/plates.json`, `massing/plates.obj`, `run_report.md`, those that exist); `run_failed {error_type, message, field_errors}`; `run_cancelled {}`.
  - `api_models.StartRunReply`: `status: Literal["started", "up_to_date"]`, `run_id: str | None`, `stages: list[str]`.

- [ ] **Step 1: Write the failing tests** (fast: `handle_request` is a fake that records the request and calls `context.on_progress`; `session_factory` returns an object with `release_memory`)

```python
def test_first_run_starts_at_preprocessing_and_unchanged_settings_are_up_to_date(project_with_inputs):
    store, name = project_with_inputs
    worker = RunWorker(store, "cpu", handle_request=fake_success, session_factory=FakeSession)
    reply = worker.start(name, ["exporting", "massing"])
    assert reply.stages == ["preprocessing", "thresholding", "exporting", "massing"]
    worker.run_state(reply.run_id).wait_for_events(0, 5); join(worker)
    assert worker.start(name, ["exporting", "massing"]).status == "up_to_date"

def test_carve_fraction_change_starts_at_thresholding(project_with_inputs): ...
    # after a successful run, write_config_from_values with another carve_fraction -> stages[0] == "thresholding"

def test_upload_after_a_run_starts_again_at_preprocessing(project_with_inputs): ...

def test_interrupted_run_makes_the_next_run_complete(project_with_inputs):
    # after one successful run, start a second whose fake handler blocks on a threading.Event:
    # while it runs, last_completed_run_config.yaml does not exist (as after a service stopped mid-run);
    # cancel it, then choose_stages(store, name, ["exporting", "massing"])[0] == "preprocessing"

def test_second_start_while_running_is_a_conflict(project_with_inputs): ...   # RunConflict

def test_missing_inputs_are_named(tmp_path): ...    # MissingInputs.roles == ["max_volume", "test_surfaces", "weather"] for time-based

def test_events_reach_a_late_reader_in_order(project_with_inputs):
    # after the run finished, wait_for_events(0, 0) returns stage_progress ... issue ... run_finished, finished is True

def test_cancel_gives_run_cancelled(project_with_inputs): ...   # fake raises RunCancelled when context.cancel_event is set

@pytest.mark.parametrize("exc, error_type", [(ConfigError("m", [ConfigFieldError("voxel_size", "too small")]), "ConfigError"),
                                             (InputError("broken mesh"), "InputError"),
                                             (StageChainError("rerun preprocessing"), "StageChainError"),
                                             (RuntimeError("boom"), "RuntimeError")])
def test_failures_become_run_failed_events(project_with_inputs, exc, error_type): ...
    # last event == {"type": "run_failed", "error_type": error_type, ...}; ConfigError carries field_errors [{"field": "voxel_size", ...}]
```

Write each `...` body with the assertions in its comment.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_local_web_run_worker.py -q -p no:cacheprovider`
Expected: FAIL (`ImportError: RunWorker`).

- [ ] **Step 3: Implement `run_worker.py`**

The event buffer with a `threading.Condition` replaces the spec's `loop.call_soon_threadsafe` forwarding: the WebSocket handler (Task 6) reads with `await asyncio.to_thread(state.wait_for_events, index, 1.0)`, which also serves late and repeated readers (Review Focus 3).

- [ ] **Step 4: Run them to verify they pass** (same command, all PASS)

- [ ] **Step 5: Add one slow end-to-end test with the real engine on CPU**

```python
@pytest.mark.slow
def test_real_run_on_the_basic_perimeter_block(tmp_path):
    # project from examples/test_inputs/basic_perimeter_block (maxVolume.ply, testSrfs.ply), mode "tilted_plane",
    # voxel_size 2.0, device "cpu"; start(["exporting", "massing"]); wait until finished;
    # last event type == "run_finished"; files include "massing/plates.json"; a progress event with stage "preprocessing" came first
```

Run: `.venv/Scripts/python -m pytest tests/test_local_web_run_worker.py -q -p no:cacheprovider -m slow`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/urbansolarcarver/local_web_service tests/test_local_web_run_worker.py
git commit -m "feat(ui): run worker with stage choice, buffered events, cancel and error events"
```

---

### Task 6: HTTP service

**Files:**
- Create: `src/urbansolarcarver/local_web_service/server.py`; `__init__.py` re-exports `create_app`
- Test: `tests/test_local_web_server.py`

**Interfaces:**
- Consumes: Tasks 1 to 5; `urbansolarcarver.__version__`; `user_config.model_json_schema()`; `mode_registry.MODES`; `warp_kernels.require_dda_backend(device)` (raises `WarpBackendUnavailableError`) and `compute_device.resolve_compute_device`, imported inside `health` only.
- Produces:
  - `create_app(projects_folder: Path, token: str, port: int, device: str = "auto", static_folder: Path | None = None, worker: RunWorker | None = None) -> FastAPI`.
  - `openapi_document() -> dict`: `create_app(Path("."), "x", 0).openapi()`, used by the front-end type generation (Task 9).
  - Routes exactly as spec 5.4, with the input routes as amended (`POST`/`DELETE`/`GET` under `inputs/{role}`) and these replies: `GET health` `{version, device, cuda_available, warp_problem: str | None}`; `GET modes` list of `{name, description, needs_epw, needs_period, experimental, score_kind, weight_unit, starting_values}`; `GET projects/{name}` `{name, created, settings, inputs: {role: [files]}, joined_bounds, inputs_changed_since_last_run, has_results: {stage: bool}}`; `PUT config` body `{"values": {...}}`, reply `ConfigReply` or 422 `ConfigErrorReply`; `POST runs` body `{"produce": [...]}` (default `["exporting", "massing"]`) reply `StartRunReply`, 409 `{detail}`, 422 `{detail, missing_inputs}`; `GET run/score-points` `application/octet-stream` or 404; `GET run/files/{path}` (404 for paths outside `run/`); `GET download` zip of the project folder.
  - `ProjectError`, `RunConflict`, `MissingInputs`, `ConfigError` map to their status codes in exception handlers; 409 for input and config changes while `worker.active_project() == name`.
  - Security middleware for every request: Host check (403), then for paths under `/api` the token check (401); the WebSocket `api/runs/{run_id}/events?token=...` checks both before accepting and closes with code 4401 or 4403. `hmac.compare_digest` for the token.
  - Static files from `static_folder` (default `ui_static/` next to the package) at `/`, without the token; `index.html` for `/`.
  - The WebSocket sends every buffered event from index 0, then new ones, and closes after `run_finished`, `run_failed` or `run_cancelled`.

- [ ] **Step 1: Write the failing tests** (fake worker handle as in Task 5; `TestClient(create_app(tmp_path, TOKEN, 8765), base_url="http://127.0.0.1:8765")`)

```python
def test_token_and_host_are_checked(client):
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/health", headers={"X-USC-Token": "wrong"}).status_code == 401
    assert client.get("/api/health", headers={"X-USC-Token": TOKEN, "Host": "evil.example:8765"}).status_code == 403
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
git commit -m "feat(ui): local HTTP service with token and Host checks, run events over WebSocket"
```

---

### Task 7: Packaged example projects

**Files:**
- Create: `src/urbansolarcarver/example_projects/{basic_perimeter_block,new_building,multiple_buildings}/...`, `src/urbansolarcarver/example_projects/weather/USA_CO_Golden-NREL.724666_TMY3.epw`, `src/urbansolarcarver/example_projects/examples.json`
- Modify: `server.py` (route `POST projects/{name}/examples/{example}`), `pyproject.toml` (`[tool.setuptools.package-data] urbansolarcarver = ["ui_static/**/*", "example_projects/**/*"]`)
- Test: `tests/test_local_web_packaging.py`, `tests/test_local_web_server.py`

**Interfaces:**
- Produces: `examples.json`, one entry per example: `{"name", "title", "mode", "max_volume": [files], "test_surfaces": [files], "weather": bool}`. The roles follow the example folders (for `new_building`: max volume `max_volume.ply`, test surfaces `neighbor_roofs.ply` and `neighbor_windows.ply`; for `basic_perimeter_block`: `maxVolume.ply` and `testSrfs.ply`; `multiple_buildings` as its folder holds). The route creates the project with the example's mode and adds its files through `ProjectStore.add_input`.

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
    # POST /api/projects/nb/examples/new_building -> inputs["test_surfaces"] == ["neighbor_roofs.ply", "neighbor_windows.ply"]
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
- Consumes: `create_app` (Task 6).
- Produces: `usc ui [--port 8765] [--projects-folder ~/UrbanSolarCarver/projects] [--no-browser] [--device auto]`. Steps: (1) import `fastapi` and `uvicorn`; on `ImportError` print `The browser UI needs the ui extra: <python> -m pip install -e "<repo>[ui]"` (the repository folder when the package is an editable install, `urbansolarcarver[ui]` otherwise) and exit 1; (2) if `ui_static/index.html` is missing, print the folder and `cd app && npm install && npm run build` and exit 1; (3) token `secrets.token_hex(32)`; (4) open `http://127.0.0.1:PORT/?token=...` with `webbrowser.open` unless `--no-browser` (and print it either way); (5) `uvicorn.run(app, host="127.0.0.1", port=port)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_ui_without_the_extra_names_the_install_command(monkeypatch): ...
    # monkeypatch builtins.__import__ to fail for "fastapi"; CliRunner().invoke(app, ["ui", "--no-browser"]) -> exit 1, "[ui]" in output

def test_ui_without_the_front_end_names_the_build_command(monkeypatch, tmp_path): ...
    # monkeypatch the static folder lookup to tmp_path; exit 1; "npm run build" in output

def test_ui_starts_uvicorn_on_localhost_with_a_token(monkeypatch): ...
    # monkeypatch uvicorn.run to record host/port and webbrowser.open to record the URL;
    # host == "127.0.0.1", URL starts with "http://127.0.0.1:8765/?token=" followed by 64 hex characters
```

- [ ] **Step 2: Run them to verify they fail.** Run: `.venv/Scripts/python -m pytest tests/test_cli.py -q -p no:cacheprovider -k ui`. Expected: FAIL (`No such command 'ui'`).

- [ ] **Step 3: Implement the command and the installer change**

- [ ] **Step 4: Run them to verify they pass** (same command), then `python setup_env.py --dry-run` and check that the printed install line contains `[ui]`.

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/carver_cli.py setup_env.py docs/getting-started/installation.md tests/test_cli.py
git commit -m "feat(ui): usc ui command; the installer adds the ui extra"
```

---

### Task 9: Front-end scaffold, API client and build hash

**Files:**
- Create: `app/package.json`, `app/package-lock.json`, `app/vite.config.ts`, `app/tsconfig.json`, `app/index.html`, `app/src/main.tsx`, `app/src/App.tsx`, `app/src/api_client/client.ts`, `app/src/api_client/generated_types.ts`, `app/src/api_client/events.ts`, `app/scripts/write_build_info.mjs`, `src/urbansolarcarver/ui_static/` (first build)
- Modify: `.gitignore` (`app/node_modules/`)
- Test: `tests/test_local_web_packaging.py` (build hash), `app/src/api_client/client.test.ts`

**Interfaces:**
- Produces:
  - npm scripts: `dev` (Vite, proxy `/api` with `ws: true` to `http://127.0.0.1:8765`), `api-types` (`python -c "import json; from urbansolarcarver.local_web_service.server import openapi_document; print(json.dumps(openapi_document()))" > openapi.json && openapi-typescript openapi.json -o src/api_client/generated_types.ts`), `build` (`vite build --outDir ../src/urbansolarcarver/ui_static --emptyOutDir && node scripts/write_build_info.mjs`), `test` (`vitest run`).
  - `client.ts`: `readTokenFromLaunchUrl(): string` (reads `?token=`, then removes it from the address bar with `history.replaceState`), and one typed function per route, each sending `X-USC-Token`; non-2xx replies throw `ApiError {status, body}`.
  - `events.ts`: `subscribeToRunEvents(runId, token, onEvent): () => void` over `ws://<host>/api/runs/<id>/events?token=`.
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
```

- [ ] **Step 2: Run them to verify they fail.** Run: `.venv/Scripts/python -m pytest tests/test_local_web_packaging.py -q -p no:cacheprovider -k build` and `cd app && npm test`. Expected: FAIL (no `build_info.json`; no `client.ts`).

- [ ] **Step 3: Scaffold the app with a minimal `App.tsx` (shows `GET health`), implement the client, events and build script; run `npm install`, `npm run api-types`, `npm run build`**

- [ ] **Step 4: Run both again; both PASS.** Then `usc ui` and open the printed URL: the page shows the version and device.

- [ ] **Step 5: Commit**

```bash
git add .gitignore app src/urbansolarcarver/ui_static tests/test_local_web_packaging.py
git commit -m "feat(ui): front-end scaffold, typed API client and committed build with source hash"
```

---

### Task 10: 3D viewer

**Files:**
- Create: `app/src/viewer/scene.ts`, `local_origin.ts`, `loaders.ts`, `layers.ts`, `score_points_decoder.ts`, `size_check.ts` and their `*.test.ts`
- Test: Vitest

**Interfaces:**
- Produces:
  - `localOrigin(bounds: [[number,number,number],[number,number,number]]): [number,number,number]` (the minimum corner) and `toLocal(point, origin)` in float64 before any `Float32Array` is filled.
  - `decodeScorePoints(buffer: ArrayBuffer): {header, indices: Uint32Array, scores: Float32Array, kept: Uint8Array | null}` (layout of Task 4) and `voxelCentres(header, indices, origin): Float32Array` (centre = header.origin + (ijk + 0.5) * voxel_size, minus the local origin).
  - `sizeWarning(bounds): string | null`: longest side over 10,000 m gives "This model is more than 10 km across. Is it in meters?"; under 1 m gives "This model is less than 1 m across. Is it in meters?".
  - `class ViewerScene`: `constructor(container: HTMLElement)`, Z up, `setNorth(deg: number)`, `setLayer(name: LayerName, object: THREE.Object3D | null)`, `setLayerVisible(name, visible)`, `frameAll()`; `LayerName = "max_volume" | "test_surfaces" | "envelope" | "plates" | "scores"`. Maximum volume drawn transparent; scores as `THREE.Points` coloured by score, carved voxels marked.
  - `loadMesh(url, token, extension): Promise<THREE.BufferGeometry>` with three.js `PLYLoader`, `OBJLoader`, `STLLoader`, `GLTFLoader`.

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
test("score points decode to the header's counts", () => { /* build a buffer with the Task 4 layout, 3 points, has_mask true; lengths 3 */ });
```

- [ ] **Step 2: Run them to verify they fail.** Run: `cd app && npm test`. Expected: FAIL (modules missing).

- [ ] **Step 3: Implement the viewer modules**

- [ ] **Step 4: Run them to verify they pass** (`npm test`)

- [ ] **Step 5: Commit**

```bash
git add app/src/viewer
git commit -m "feat(ui): three.js viewer with local origin, layers, loaders and score points"
```

---

### Task 11: Settings form with tiers

**Files:**
- Create: `app/src/settings_form/setting_tiers.json`, `setting_sections.json`, `SettingsForm.tsx`, `widgets/ModeSelect.tsx`, `widgets/AnalysisPeriod.tsx`, `widgets/TiltedPlaneAngles.tsx`, `widgets/SunStepsPerHour.tsx`, `widgets/MeshFormat.tsx`
- Test: `tests/test_local_web_packaging.py` (names against the engine), Vitest for the form state

**Interfaces:**
- Produces:
  - `setting_tiers.json`: `{"all": [...], "<mode>": [...]}` with exactly the essential settings of spec section 6 (all modes: `mode`, `north_deg`, `voxel_size`, `apply_smoothing`, `ground_floor_height`, `floor_height`, `min_plate_dimension`; time-based, irradiance, benefit: the six period fields; time-based: `threshold`; irradiance, benefit, daylight, radiative_cooling: `carve_fraction`; benefit: `balance_temperature`; tilted_plane: `tilted_plane_angle_deg`; radiative_cooling: `dew_point_celsius`). Mode keys are the canonical names in `mode_registry.MODES`.
  - `setting_sections.json`: `{"<section title>": [setting names]}`, covering every `UserConfig` field except `max_volume_path`, `test_surface_path`, `epw_path`, `out_dir`, `device`.
  - `SettingsForm`: field types, defaults, limits and descriptions from `GET schema`; mode choice fills `starting_values` from `GET modes`; essential settings first, other settings folded per section; every change sends `PUT config` (debounced 400 ms); field errors from a 422 shown next to their fields; the grid plan (resolution³ and total voxels) shown, and Run disabled while the last reply was a `voxel_size` error.

- [ ] **Step 1: Write the failing tests**

```python
def test_tier_and_section_names_are_engine_settings():
    fields = set(UserConfig.model_fields)
    tiers = json.loads((REPO / "app/src/settings_form/setting_tiers.json").read_text())
    sections = json.loads((REPO / "app/src/settings_form/setting_sections.json").read_text())
    assert set(tiers) - {"all"} <= set(MODES)
    for names in [*tiers.values(), *sections.values()]:
        assert set(names) <= fields, set(names) - fields

def test_every_user_setting_is_in_exactly_one_section():
    sections = json.loads((REPO / "app/src/settings_form/setting_sections.json").read_text())
    listed = [n for names in sections.values() for n in names]
    owned = {"max_volume_path", "test_surface_path", "epw_path", "out_dir", "device"}
    assert sorted(listed) == sorted(set(UserConfig.model_fields) - owned)
```

```ts
test("choosing a mode fills its starting values and keeps the shared ones the user set", () => { /* form state reducer */ });
```

- [ ] **Step 2: Run them to verify they fail.** Run: `.venv/Scripts/python -m pytest tests/test_local_web_packaging.py -q -p no:cacheprovider -k setting` and `cd app && npm test`. Expected: FAIL (files missing).

- [ ] **Step 3: Write the two JSON lists and the form**

- [ ] **Step 4: Run them to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add app/src/settings_form tests/test_local_web_packaging.py
git commit -m "feat(ui): settings form from the engine schema with essential and advanced settings"
```

---

### Task 12: The six steps

**Files:**
- Create: `app/src/steps/ProjectStep.tsx`, `InputsStep.tsx`, `SettingsStep.tsx`, `RunStep.tsx`, `ReviewStep.tsx`, `ExportStep.tsx`, `app/src/steps/run_state.ts` (+ `run_state.test.ts`)
- Modify: `app/src/App.tsx` (left panel with the steps, the viewer always on the right)

**Interfaces:**
- Consumes: client (Task 9), `ViewerScene` and helpers (Task 10), `SettingsForm` (Task 11).
- Produces (spec section 7, as amended):
  - Project: create (name, mode), open, or open an example from `examples.json` titles.
  - Inputs: several files per mesh role with add and remove; EPW only when the mode `needs_epw`; each upload drawn on arrival; `sizeWarning` shown; uploads disabled while a run of this project is active.
  - Run: `runReducer(state, event)` in `run_state.ts` keeps per-stage progress (`done/total`), issues and the final state (`finished | failed | cancelled`); Cancel; "Results are up to date" when `POST runs` says so; field errors from `run_failed` link back to the settings.
  - Review: layer toggles; a layer whose file is absent shows "No result for this stage: the last run stopped before it."; `run_report.md` beside the view; for thinned scores "Showing 1 of every k voxels".
  - Export: download links for the carved mesh, `plates.obj`, `plates.json`, `config.yaml` and the project zip; changing `final_mesh_format` and pressing Run reruns exporting only (the service decides).

- [ ] **Step 1: Write the failing test**

```ts
test("run events build per-stage progress, issues and the final state", () => {
  let s = initialRunState(["preprocessing", "thresholding"]);
  s = runReducer(s, {type: "stage_progress", stage: "preprocessing", done: 3, total: 10});
  s = runReducer(s, {type: "issue", stage: "preprocessing", code: "W1", message: "m"});
  s = runReducer(s, {type: "run_failed", error_type: "InputError", message: "broken", field_errors: []});
  expect(s.stages.preprocessing).toEqual({done: 3, total: 10});
  expect(s.issues).toHaveLength(1); expect(s.final).toBe("failed");
});
```

- [ ] **Step 2: Run it to verify it fails.** Run: `cd app && npm test`. Expected: FAIL.

- [ ] **Step 3: Implement the steps and the layout**

- [ ] **Step 4: Run the tests (PASS), rebuild (`npm run build`), and check the whole flow by hand** in the browser preview against `usc ui --no-browser`, with each of: the `new_building` example (two test surface files), a fresh project with uploaded files, a settings change that reruns from thresholding, Cancel during preprocessing, a voxel size over the budget (Run disabled), and the export downloads. Note anything that fails and fix it before the commit.

- [ ] **Step 5: Commit**

```bash
git add app src/urbansolarcarver/ui_static
git commit -m "feat(ui): project, inputs, settings, run, review and export steps"
```

---

### Task 13: Documentation and full check

**Files:**
- Create: `docs/ui.md`
- Modify: `mkdocs.yml` (nav entry "Browser UI"), `README.md` (feature line and `usc ui`), `CHANGELOG.md` (Unreleased > Added), `docs/project-map.md` (the new modules and `app/`)

- [ ] **Step 1: Write the docs.** `docs/ui.md`: starting `usc ui`, the six steps, where projects are kept, the security model in two sentences, CPU mode on machines without an NVIDIA GPU, and how to rebuild the front-end after changing `app/`.

- [ ] **Step 2: Run the whole suite and the front-end tests**

Run: `.venv/Scripts/python -m pytest tests -q -p no:cacheprovider` and `cd app && npm test`
Expected: all pass (the slow tests included).

- [ ] **Step 3: Commit**

```bash
git add docs mkdocs.yml README.md CHANGELOG.md
git commit -m "docs(ui): browser UI page, README, changelog and project map"
```
