# Local web UI for UrbanSolarCarver: design (milestone 1)

- Date: 2026-10-16
- Implementation: not started (the UI work belongs to the main development session)
- Engine baseline: `main` at `f2947fd` (stage contract restructure, request core, module split, one device rule, cached sky weights)
- Status: reviewed and amended on 2026-10-16 (front-end delivery, several input files per role, changes during a run, score layer cap, packaged examples, missing results, tiers note); awaiting approval

## 1. Goal and scope

UrbanSolarCarver (USC) is used today through Grasshopper, notebooks and the `usc` CLI. Designers and planners who use none of these cannot use it, and the number of settings is hard for new users. The long-term goal is a traditional desktop app that installs easily and has a clean interface, with limited drawing tools for maximum volumes and test surfaces.

This spec covers **milestone 1**: a browser UI started with `usc ui`, running on the user's machine and GPU. The flow is: import inputs, choose a mode and settings, run, review the result in 3D, export.

In scope:

1. Two small engine changes the service needs (section 4).
2. A local HTTP engine service in the USC package (section 5).
3. A browser app in `app/` (sections 6 to 8).

Out of scope, each with its own later spec:

- Drawing tools for maximum volumes and test surfaces (milestone 2).
- The desktop window (Tauri or Electron) and a first-run installer.
- A live Rhino bridge.
- A remote GPU server. The design keeps it possible: the browser talks to the service only over HTTP, and files reach the service only by upload.
- Run history and side-by-side comparison, context buildings, and 3DM or GeoJSON import.

Platform: machines with an NVIDIA GPU (Windows or Linux) run at full speed. Other machines, including Macs, run in CPU mode and are slower.

## 2. Decisions

| Topic | Decision |
|---|---|
| Where it runs | Fully local. No hosted service. |
| Order | Browser UI first; the desktop window and installer wrap the same front-end later. |
| Repository | Same repo. The front-end lives in `app/`; the service lives in `src/urbansolarcarver/`. The front-end uses only the HTTP API and never reads Python files. |
| Service framework | FastAPI and uvicorn, in an optional `ui` extra, so CLI and Grasshopper users do not install them. |
| Files | Inputs are uploaded into a project folder; the service never takes paths from the browser. The maximum volume and the test surfaces may each come as several files, which the service joins (section 5.3). |
| Front-end delivery | The built front-end is committed in the repository (section 8), so a `git clone` install has it, offline and always matching the code of that commit. Node is needed only to change the front-end. |
| Concurrency | One run at a time per service process. |
| Settings tiers | The essential/advanced split lives only in `app/`. |
| Mode starting values | Taken from the engine (`ModeSpec.starting_values`), not duplicated in `app/`. |
| Front-end stack | TypeScript, Vite and React for panels; plain three.js for the 3D view in its own module. |
| Grasshopper | Unchanged. The pickle daemon stays as it is. |

## 3. Architecture

```
Browser app (app/, built into src/urbansolarcarver/ui_static/)
        |  HTTP + WebSocket on 127.0.0.1, token per launch
        v
Local web service (src/urbansolarcarver/local_web_service/)
        |  Python calls
        v
Engine API
  engine_requests.handle_engine_request (-> api.run_pipeline), RunContext,
  build_config_from_mode_starting_values, stages_to_rerun, stages_needed_for,
  grid_planning, mode_registry, io.load_mesh
```

The service holds no carving logic. It turns HTTP requests into engine calls, stores project files, runs one pipeline at a time on a worker thread, and turns engine events and errors into JSON.

## 4. Engine changes before the service

Done, and on `main` since `830a1f0`:

- **`engine_requests`**: the request core every transport uses. `parse_engine_request` validates a message into a typed request (`RunRequest`, `StageRequest`, `RunPipelineRequest`, `SimulateWeightsRequest`, `PingRequest`); `config_for_engine_request` builds its config from a YAML path or from the mode's starting values plus overrides; `handle_engine_request(request, session, context=None)` runs it inside a given `RunContext` and returns a typed reply (`RunReply`, `StageReply`...); `error_reply_for(exc)` builds an `ErrorReply` with `error_type` and `config_errors`. The pickle daemon is now a transport over it. The local web service is a second transport: it calls `handle_engine_request` with its own `RunContext` (progress, issues, cancel) instead of reimplementing request handling.
- **`load_config.build_config_from_mode_starting_values(values, base_folder=None)`**: public; fills the mode's starting values under the given values.
- **`load_mesh` raises `InputError`** for a missing file, a file without triangles and a file trimesh cannot parse.

## 5. Local web service

### 5.1 Package and command

`src/urbansolarcarver/local_web_service/`:

| Module | Responsibility |
|---|---|
| `server.py` | FastAPI app, routes, token and Host checks, static files |
| `projects.py` | Project folder layout, uploads, joining several files per role, stored settings, input-change tracking |
| `run_worker.py` | The worker thread, the run context, event forwarding, cancel |
| `score_points.py` | Builds the score layer data from the preprocessing and thresholding outputs |
| `api_models.py` | Pydantic request, reply and event models (the OpenAPI schema comes from these) |

Command: `usc ui [--port PORT] [--projects-folder PATH] [--no-browser] [--device auto|cpu|cuda]`. It starts uvicorn on `127.0.0.1` and opens the browser at `http://127.0.0.1:PORT/?token=...` unless `--no-browser` is given. The default projects folder is `~/UrbanSolarCarver/projects`. If `ui_static/index.html` is missing (a damaged checkout), `usc ui` stops with a message that names the folder and the rebuild command (section 8). If the `ui` extra is not installed, it stops with the `pip install` command that adds it.

Optional extra `ui` in `pyproject.toml`: `fastapi`, `uvicorn`, `python-multipart` (needed by FastAPI for uploads). Importing the service must not import torch until the first run; `GET health` imports it to report the device.

### 5.2 Security

- Binds to `127.0.0.1` only.
- A random token (32 bytes, hex) is created at each launch. Every HTTP request must carry it in an `X-USC-Token` header; the WebSocket carries it as a query parameter. The browser receives it once in the launch URL and keeps it in memory.
- A request without the right token gets 401.
- The `Host` header must be `127.0.0.1:PORT` or `localhost:PORT`, which blocks DNS rebinding; any other gets 403.
- Static files (the built front-end) are served without the token; they contain no data.

### 5.3 Project folder

```
<projects folder>/<project name>/
  project.json                      name, created, input file names, inputs_changed_since_last_run
  inputs/max_volume/<file>          one or more of ply, obj, stl or glb, as uploaded
  inputs/test_surfaces/<file>       one or more, as uploaded
  inputs/weather.epw                when the mode needs one
  inputs/joined/max_volume.ply      written by the service from the files above
  inputs/joined/test_surfaces.ply
  config.yaml                       the settings as the user set them, paths relative to the project
  last_completed_run_config.yaml    the config of the last run that finished; absent otherwise
  run/                              the run folder: preprocessing/, thresholding/, exporting/, massing/, run_report.md
```

**Joining several files.** After every upload or removal the service rebuilds the joined file of that role, the way the Grasshopper components join several objects: the maximum volume files are concatenated and identical vertices welded, so each closed body stays closed; the test surface files are concatenated without welding, because welding across neighbouring panels averages their normals and can flip panels. The config's `max_volume_path` and `test_surface_path` point to the joined files. File names are kept as uploaded after removing path parts and characters other than letters, digits, `-`, `_` and `.`; a name that already exists in the role is replaced.

`config.yaml` holds the values as set (unresolved "None means auto" fields stay None), so it rebuilds to the same config. It loads with `usc run -c config.yaml --out run --produce exporting --produce massing`.

There is one run folder per project, updated in place: `run_pipeline` writes `run/<stage>` and, with `start_from`, reads the earlier stages from the same folder. A user keeps a result by exporting it.

### 5.4 Requests

All paths are under `/api`. Replies are JSON unless noted.

| Request | Purpose |
|---|---|
| `GET health` | USC version, device in use, whether CUDA is available |
| `GET schema` | `user_config.model_json_schema()` |
| `GET modes` | For each mode: name, `description`, `needs_epw`, `needs_period`, `experimental`, `score_kind`, `weight_unit`, `starting_values` |
| `GET projects`, `POST projects`, `GET projects/{name}` | List, create, open |
| `POST projects/{name}/examples/{example}` | Create a project from a bundled example (section 7) |
| `POST projects/{name}/inputs/{role}` | Add a file to `max_volume` or `test_surfaces` (checked with `load_mesh`, then the joined file is rebuilt), or set `weather` (replaces the EPW); replies with the role's file list and the joined mesh bounds |
| `DELETE projects/{name}/inputs/{role}/{file_name}` | Remove one file of a role and rebuild the joined file |
| `GET projects/{name}/inputs/{role}` | The role's file list |
| `GET projects/{name}/inputs/{role}/{file_name}` | One stored file, for the 3D view |
| `PUT projects/{name}/config` | Validate with `build_config_from_mode_starting_values`; on success store `config.yaml` and reply with the grid plan; on `ConfigError` reply 422 with its field errors |
| `POST projects/{name}/runs` | Body: `produce` (default `["exporting", "massing"]`). Starts a run or replies that results are up to date (section 5.5) |
| `WS runs/{run_id}/events` | Run events (section 5.5) |
| `POST runs/{run_id}/cancel` | Cancel the run |
| `GET projects/{name}/run/files/{path}` | A file from the run folder (meshes, `plates.json`, `run_report.md`) |
| `GET projects/{name}/run/score-points` | Binary score layer data (section 5.7) |
| `GET projects/{name}/download` | The project folder as a zip |

`build_config_from_mode_starting_values` (section 4) is used in two places: `POST projects` writes the first `config.yaml` from the starting values of the chosen mode (default time-based), and `PUT config` validates the values the browser sends, with the project folder as `base_folder`. The service sets `max_volume_path`, `test_surface_path`, `epw_path` and `out_dir` itself; values the browser sends for them are ignored.

The grid plan in the `PUT config` reply comes from `grid_planning.plan_voxel_grid(bounds, voxel_size, margin_frac)` with the stored mesh bounds; `check_voxel_grid_budget` turns an oversized grid into a field error on `voxel_size`.

### 5.5 Run lifecycle

When `POST runs` arrives:

1. Load `config.yaml` into a config. Check that every input the mode needs is uploaded.
2. Choose the stages:
   - If `inputs_changed_since_last_run` is true, or `last_completed_run_config.yaml` is absent: `stages_needed_for(produce)`, starting from preprocessing.
   - Otherwise: `stages_to_rerun(last_completed_config, config, produce)`.
   - If the list is empty, reply `{"status": "up_to_date"}` and start nothing.
3. If a run is active, reply 409.
4. Otherwise create a run id, delete `last_completed_run_config.yaml`, start the worker and reply `{"status": "started", "run_id": ..., "stages": [...]}`.

The worker thread holds the process's single `CarverSession` and calls `engine_requests.handle_engine_request` with a `RunRequest` built from the project (YAML path `config.yaml`, `run_folder`, `produce`, `start_from`), which in turn calls

```python
api.run_pipeline(config, run_folder, produce=produce, start_from=stages[0], context=context)
```

with `context = RunContext(on_progress=forward_progress)`. `run_pipeline` activates the context in the worker thread; `_run_batches` already hands it to its own worker threads. `forward_progress` runs on the worker thread and passes events to the server's event loop with `loop.call_soon_threadsafe`; with each progress event it also sends any issues added to `context.issues` since the last event. Cancel calls `context.cancel()`, which is thread-safe.

On success the worker writes `last_completed_run_config.yaml` and sets `inputs_changed_since_last_run` to false. On failure or cancel it leaves `last_completed_run_config.yaml` absent, so the next run is complete. After every run it calls `release_memory()` on the session.

While a project's run is active, uploads, removals and `PUT config` for that project reply 409: the files and settings a run reads stay fixed until it ends, and `last_completed_run_config.yaml` is always the config the run actually used.

An upload or removal sets `inputs_changed_since_last_run` to true. The engine compares settings only and does not detect a changed file at an unchanged path, so this flag is how the service knows.

Events, each a JSON object with a `type`:

| Type | Fields | When |
|---|---|---|
| `stage_progress` | `stage`, `done`, `total` | Each stage reports `0/1` at start and `1/1` at end; during preprocessing, ray tracing also reports `done/total` batches |
| `issue` | `stage`, `code`, `message` | Each `Issue` the run records |
| `run_finished` | `stages`, `files` | The pipeline returned |
| `run_failed` | `error_type`, `message`, `field_errors` | An exception other than `RunCancelled` |
| `run_cancelled` | | `RunCancelled` |

### 5.6 Error mapping

| Engine error | HTTP or event | What the browser shows |
|---|---|---|
| `ConfigError` | 422 on `PUT config`; `run_failed` with `field_errors` during a run | Messages next to the fields |
| `InputError` | 422 on upload; `run_failed` during a run | A message on the input |
| `StageChainError` | `run_failed` | "Results are out of date; run again from the start", and the service deletes `last_completed_run_config.yaml` |
| `RunCancelled` | `run_cancelled` | Cancelled state |
| `WarpBackendUnavailableError` | `run_failed` | The message, which names why Warp cannot run and points to `setup_env.py`; `GET health` also reports it before any run |
| Anything else | `run_failed` with the type and message | The message; the traceback goes to the server log |

### 5.7 Score layer data

`GET run/score-points` reads `run/preprocessing/manifest.json` and `run/thresholding/manifest.json` (paths in manifests are relative to the manifest's folder) and returns:

- a JSON header: `origin` (world coordinates, as the manifest records), `shape`, `voxel_size`, `scores_kind`, `weight_unit`, score minimum and maximum, and the counts below;
- then three little-endian arrays for the occupied voxels: flat voxel indices (`uint32`), scores (`float32`), and kept or carved (`uint8`, from `mask.npy`).

The browser rebuilds positions from the index, origin and voxel size. Without a thresholding output the kept/carved array is omitted.

**Cap.** At most 1,000,000 voxels are sent (about 9 MB); a city-scale grid can hold ten times more, which a browser draws slowly. Above the cap the service keeps every k-th occupied voxel in index order, with k the smallest whole number that brings the count under the cap, so the thinning is even across the grid. The header reports `thinning_step` (k, 1 when nothing was thinned) and the total count, and the view states "showing 1 of every k voxels".

## 6. Settings in the browser

- **Form source.** Field types, defaults, limits and descriptions come from `GET schema`. Mode choices, descriptions and starting values come from `GET modes`.
- **Fields the JSON schema does not constrain** get explicit widgets in `app/settings_form/`: `mode` (select from `GET modes`), `final_mesh_format` (ply, obj, stl, glb), `sun_steps_per_hour` (the allowed timesteps), `tilted_plane_angle_deg` (one angle, or eight compass angles), and the analysis period (one date-and-hour range). `device`, `out_dir` and the input paths are not shown in the form: the service sets them.
- **Tiers.** `app/settings_form/setting_tiers.ts` lists the essential settings per mode; everything else is advanced and folded under its form section. Essential settings:

| Shown for | Essential settings |
|---|---|
| All modes | mode, `north_deg`, `voxel_size`, `apply_smoothing`, `ground_floor_height`, `floor_height`, `min_plate_dimension` |
| time-based, irradiance, benefit | analysis period |
| time-based | `threshold` as the tolerated shading in m²·h (default 0) |
| irradiance, benefit, daylight, radiative_cooling | `carve_fraction` |
| benefit | `balance_temperature` |
| tilted_plane | `tilted_plane_angle_deg` |
| radiative_cooling | `dew_point_celsius` |

- **Validation** stays in the engine: the form sends the settings with `PUT config` and shows the field errors it gets back.
- **A front-end test** checks that every setting name in the tier and section lists exists in `GET schema`, so a renamed setting fails a test instead of disappearing from the form.

## 7. Browser app flow

One page: a left panel with the steps and their forms, and a 3D view on the right that is always visible.

1. **Project.** Create, open, or open an example. The examples (`basic_perimeter_block`, `new_building`, `multiple_buildings`, from `examples/test_inputs`, with the Golden EPW from `examples/weather`, under 2 MB in total) are copied into the package as `src/urbansolarcarver/example_projects/`, so a non-editable install has them too; a test checks that the copies match `examples/`. `new_building` has two test surface files and exercises joining.
2. **Inputs.** Add one or more files for the maximum volume and for the test surfaces, and remove them one by one; the EPW appears once the mode needs one. Each mesh is drawn on arrival. The view shows the bounding-box size and warns when it looks wrong for meters (longest side over 10 km or under 1 m).
3. **Mode and settings.** Mode picker with descriptions; choosing a mode fills its starting values. The essential settings, then the folded advanced sections. Each change is sent with `PUT config`; the grid size and the budget check update with it, and a grid over the budget disables Run.
4. **Run.** A progress bar per stage, with batch progress during ray tracing; Cancel; issues listed as they arrive.
5. **Review.** Toggle layers: maximum volume (transparent), carved envelope, floor plates, test surfaces, and scores (voxel points colored by score, carved ones marked). Next to the view: `run_report.md`. A layer whose file is missing (the engine clears a stage's outputs before rerunning it, so a failed or cancelled run leaves some missing) is shown as "no result for this stage: the last run stopped before it", not as an error. Changing a setting and pressing Run again reruns only the stages the change affects; "up to date" is shown when nothing changed.
6. **Export.** Download the carved mesh, `plates.obj` and `plates.json`, `config.yaml`, or the project as a zip. The mesh format is the `final_mesh_format` setting; choosing another format reruns exporting only.

3D view: Z axis up; every object is shifted by one local origin (the maximum volume's minimum corner) so georeferenced models do not lose precision in float32; a north arrow from `north_deg`; three.js loaders for PLY, OBJ, STL and GLB.

## 8. Front-end structure and build

```
app/
  package.json, vite.config.ts, tsconfig.json
  src/
    api_client/       typed client; types generated from the service's OpenAPI schema (openapi-typescript, dev only)
    viewer/           three.js scene, loaders, layers, local origin; no React inside
    settings_form/    tiers, sections, widgets for unconstrained fields
    steps/            the six steps
```

- `npm run build` writes into `src/urbansolarcarver/ui_static/`, which **is committed** and included in the wheel as package data. Installs are `git clone` plus `setup_env.py` (editable), so committing the build is what gives every install a working front-end that matches its own code, without Node and without a download. The minified build is a few megabytes and changes only when `app/` changes.
- The build also writes `ui_static/build_info.json` with a SHA-256 of the files under `app/src`, `package.json` and the lock file. A Python test recomputes it and fails when `app/` changed without a rebuild, naming the command to run.
- In development, the Vite dev server forwards `/api` to a running `usc ui --no-browser`.
- Python users never need Node; only changing the front-end does.

## 9. Testing

**Engine changes (section 4).** Done, with tests in `tests/test_engine_requests.py` and `tests/test_io.py`.

**Service.** pytest with FastAPI's `TestClient` (`httpx` in the dev extra), on CPU, with the `basic_perimeter_block` example:

- Create a project, upload inputs, set config, run `produce=["exporting", "massing"]`; the events arrive in order and the result files can be fetched.
- After a `carve_fraction` change, the run starts at thresholding; with no change, the reply is `up_to_date`; after a new upload, the run starts at preprocessing.
- Cancel during preprocessing gives `run_cancelled`, and the next run is complete.
- A second run while one is active gets 409.
- A missing or wrong token gets 401; a foreign `Host` header gets 403.
- An invalid setting gets 422 with the field name; an oversized grid gets a field error on `voxel_size`.
- `score-points` returns arrays whose lengths match the header; above the cap the step and counts are reported and the thinning is even.
- Two test surface files uploaded to one project give one joined file whose triangle count is the sum, and removing one rebuilds it; two closed maximum volume files stay two closed bodies after joining.
- An upload, a removal or `PUT config` during an active run of that project gets 409.
- The packaged example projects match `examples/`; `ui_static/build_info.json` matches the hash of `app/` (both are fast tests, without the `slow` marker).
- `usc ui` without `ui_static/index.html` stops with the message that names the rebuild command.

The end-to-end service tests take seconds, so they get the `slow` marker (registered in `pyproject.toml`; `pytest -m "not slow"` leaves them out). There is no CI: hosted runners have no GPU, so the tests run locally, and a fresh install is checked from time to time as `CONTRIBUTING.md` describes.

**Front-end.** Vitest for the settings lists check, the score-points decoder and the local-origin shift. The full flow is checked by hand in the browser preview against `usc ui --no-browser` before merging.

## 10. Later work

- Milestone 2: drawing tools (polygon on the ground plane and extrusion for the maximum volume; faces or rectangles for test surfaces), with context import.
- Desktop window and first-run installer, reusing `setup_env.py`.
- Live Rhino bridge, likely through this HTTP service.
- Possibly: Grasshopper moves from the pickle daemon to the HTTP service, and the daemon is retired.
- If the CLI (an `init` wizard) or Grasshopper should show the same essential and advanced settings, the tier lists move from `app/` into the engine (for example as schema metadata), so all clients read one list.
