# Running the tests

The Python suite (about 2,080 tests in `tests/`) and the front-end suite (about 1,010 vitest tests in `app/`) run locally:
there is no CI, because the engine runs on the GPU and hosted runners have none. Tests marked `gpu` are skipped
automatically without CUDA.

Install the test dependencies once with `pip install -e .[dev]` (it includes pytest-xdist, which runs tests in
parallel with `-n`). Run the commands below from the repository root with the repository's environment active. In a
git worktree that has no environment of its own, put the worktree's sources first: `PYTHONPATH=src python -m pytest ...`
(in PowerShell, `$env:PYTHONPATH = "src"` once).

## Four tiers

Times are wall times on an 8-core / 16-thread AMD Zen 2 with an RTX 3060, measured 2026-11-02.

| Tier | When | Command | Time |
|---|---|---|---|
| 0 | While editing | `python -m pytest tests/test_floor_plates.py -m "not slow"` | seconds |
| 1 | After every change | `python -m pytest -m "not slow" -n 8` | about 55 s |
| 2 | Before each commit | `python -m pytest -m "not sweep" -n 8` | about 2 min |
| 3 | Before merging | `python -m pytest -n 8` | about 2.5 min |

When `app/` changed, also run the front-end checks of the same tier (see below): `npm test` takes about 32 s (12 s of it ESLint),
`npm run typecheck` 5 s and `npm run build` 7 s.

Every tier also checks the import rules of the [Project Map](project-map.md): `tests/test_architecture.py` for the
Python package (with `npm test`'s `deps` script for the app). `npm test` also runs ESLint (`npm run lint`,
`app/eslint.config.js`): the React hooks rules check effect dependencies and what components do during render, and a
line that sets a rule aside says why.

### Tier 0: the files you are editing

Run the test file of the module you are changing, or one test with `-k`:

```bash
python -m pytest tests/test_floor_plates.py -m "not slow"
python -m pytest tests/test_floor_plates.py -k end_wings
```

`--lf` runs only the tests that failed last time, which is quick after a fix. In `app/`:

```bash
npx vitest run src/criteria/ModeStep.test.tsx
```

### Tier 1: after every change

```bash
python -m pytest -m "not slow" -n 8
```

Leaves out the tests marked `slow`: end-to-end scenes, full-year simulations, sweeps and a real daemon process. When
`app/` changed, in a second terminal at the same time:

```bash
cd app
npm test && npm run typecheck
```

### Tier 2: before each commit

```bash
python -m pytest -m "not sweep" -n 8
```

Everything except the tests marked `sweep` (the 0.5 m floor-plate sweep and the Monte Carlo seeds). When `app/`
changed, rebuild the front end first: the pytest run includes the test that compares `ui_static/build_info.json` with
the sources.

```bash
cd app
npm test && npm run build
```

`npm run build` runs the type check before it writes `src/urbansolarcarver/ui_static/`.

### Tier 3: before merging

```bash
python -m pytest -n 8
```

The whole suite, sweeps included. From time to time, and before a release, run it without `-n` (about 5 minutes): a
serial run catches a test that only passes after another one has run. Also run, when they apply:

- after a change to the engine's numerics, the randomised Monte Carlo sweep: `python tests/montecarlo.py` (see its
  docstring for the options);
- after a change under `grasshopper/components/`, the Rhino smoke test `tools/grasshopper_example_smoke_test.py`
  (see [Grasshopper](grasshopper.md));
- before a release, the suite in a fresh install (see CONTRIBUTING.md, "Checking a fresh install").

## Markers

| Marker | Meaning | Left out by |
|---|---|---|
| `slow` | Takes seconds: end-to-end scenes, simulations, a daemon process | `-m "not slow"` |
| `sweep` | Exhaustive parameter sweeps and Monte Carlo seeds; always also `slow` | `-m "not sweep"` |
| `gpu` | Needs a CUDA GPU; skipped automatically without one | (automatic) |

Mark a new test `slow` when it takes more than about a second, and `sweep` when it repeats a check over many
parameter values that other tests already cover at a few chosen ones. `pyproject.toml` runs pytest with
`--strict-markers` (a misspelt marker is an error) and `--durations=15` (every run ends with its 15 slowest tests).
After the run, `tests/conftest.py` also lists each test outside `slow` that took over 1 s; mark it `slow` or make it
faster. Times grow by about half under `-n 8`, so a test listed only in a parallel run may be fine on its own.

An exact count in a test (panels, sample points, kept voxels of a packaged example) carries a comment on how to take
the new value after a deliberate change of the example files or of the code that produces it.

## Keeping out of the user's folders

`tests/conftest.py` does this for every test, without a fixture to ask for:

- `no_real_home_folder` gives each test a home folder of its own (`HOME` and `USERPROFILE`), so no test reads or writes
  the user's `~/.urbansolarcarver` (the typical building library, the preferences, the daemon key) or
  `~/UrbanSolarCarver/projects`. A test that looks into the home folder asks for it by a `home_folder` fixture.
- `pytest_configure` pins Warp's kernel cache (`WARP_CACHE_PATH`) to its usual folder first: with the home folder
  moved, Warp would otherwise make a new cache in the working folder (an `NVIDIA` folder in the checkout) and compile
  every kernel again. A daemon started by a test gets the same environment (`tests/_daemon_home.py`).
- `no_real_recycle_bin` removes what the local web service would send to the recycle bin.

`tests/test_isolation.py` checks the first two.

## Shared scenes and fakes

Before writing a scene or a fake of your own, use these.

| Where | What |
|---|---|
| `tests/conftest.py` | `tiny_cube_mesh` (a 10 m cube, z -5 to 5), `tiny_surface_mesh` (a 6 m quad 1 m under it, facing up), `tmp_mesh_files`, `example_epw_path`, `project_with_inputs`, `example_project_templates` |
| `tests/_stage_scene.py` | `cube_volume`, `surface_under_cube`, `cube_config` and `daylight_cube_config`: the same cube and surface as a validated daylight config on the CPU, the smallest scene that runs every stage; for stage plumbing, not for which voxels a mode carves (the surface looks straight up through the cube from any side) |
| `tests/_plot_scene.py` | `plot_scene`: a 12 x 12 x 18 m plot, a 10 m street and a 12 m neighbour whose south facade is the test surface and whose mass is the context, optionally turned by `north_deg`; `PlotScene.config(folder, mode, epw_path)` (1 m voxels, CPU) and `PlotScene.voxels` with `assert_carves_the_north_side`: which side a mode or stage carves, in about a second |
| `tests/_chain_scene.py` | a box with two facades, on which two chained criteria decide about different voxels |
| `tests/cases.py`, `tests/oracle.py`, `tests/montecarlo.py` | the typology scenes run end to end, an independent reference implementation, and the randomised sweep |
| `tests/local_web_test_support.py` | projects for the local web service (`add_project_with_inputs`, `box_bytes`), `FakeEngine` (writes run_chain's folders without computing), `FakeRecycleBin` |
| `tests/_geometry.py` | `box_between(lo, hi)`: a box mesh from two corners |
| `tests/_epw.py`, `tests/_daemon_home.py` | `BUNDLED_EPW` and `resolve_epw` (a test that needs a weather file asks for `example_epw_path`, which skips without one); `isolated_home_env` and `start_daemon(home, answers)`, a real daemon subprocess with a home folder of its own, started on a free port |
| `app/src/workspace/project_workspace_for_test.tsx` | `FakeService`, the service an open project talks to; `json<Reply>(body)` checks a reply against the service's type when given it |
| `app/src/workspace/chain_service_for_test.tsx`, `simulate_service_for_test.tsx` | the same for several criteria, and for Simulate |
| `app/src/viewer/fake_scene_for_test.ts` | `FakeViewerScene`, typed against `ViewerScene`'s public methods; it records what the pane asked it to draw |
| `app/src/api_client/project_session_for_test.tsx` | `inProjectSession(element)`: a hook or panel of an open project rendered without the workspace |
| `app/src/api_client/fake_websocket_for_test.ts` | a run's events |
| `app/src/viewer_overlays/render_for_test.tsx` | rendering with React's `act`; `click`, `press`, `type`, `typeAndLeave`, `byRole`, `accessibleName`; `settle()`, which waits until no reply is outstanding and nothing changed for two rounds (it throws, naming the unanswered requests, after 50 rounds; a reply a fake holds on purpose goes through `holdReply`); `addStyleSheetForTest` for computed styles |
| `app/src/api_client/service_data_for_test.ts` | the service's settings schema, modes and criterion keys as the app gets them (`SERVICE_SCHEMA`, `SERVICE_MODES`, `SERVICE_CRITERION_KEYS`, `serviceSchemaWith`, `serviceModes`), from a JSON snapshot written by `python tools/write_app_test_service_data.py`; `tests/test_local_web_api_types.py` fails when the snapshot or `generated_types.ts` no longer matches the service |

## Running in parallel

`-n 8` starts 8 worker processes and hands out tests to them; each worker pays about 10 s of imports and collection
once. `pyproject.toml` adds `--dist worksteal`: a worker that runs out of tests takes some from another's queue. With
the default scheduling, tests given out in a block (the eight Monte Carlo cases, 15 to 38 s each) kept one worker
busy for 210 s while the others had stopped at about 110 to 160 s; the whole suite took 235 s, with worksteal 188 s.
A test that runs over about 40 s still ends up alone at the end of the run: split it with `parametrize` so two workers
share it. Tests must not depend on one another or on a shared file: each uses its own `tmp_path`. The engine computes each
sky matrix in a temporary folder of its own, so workers computing sky matrices at the same time do not share
Ladybug's weather folder. When another checkout is testing on
the same machine at the same time, `-n 4` leaves it room.
