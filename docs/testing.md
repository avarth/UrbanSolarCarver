# Running the tests

The Python suite (about 1320 tests in `tests/`) and the front-end suite (about 480 vitest tests in `app/`) run locally:
there is no CI, because the engine runs on the GPU and hosted runners have none. Tests marked `gpu` are skipped
automatically without CUDA.

Install the test dependencies once with `pip install -e .[dev]` (it includes pytest-xdist, which runs tests in
parallel with `-n`). Run the commands below from the repository root with the repository's environment active. In a
git worktree that has no environment of its own, put the worktree's sources first: `PYTHONPATH=src python -m pytest ...`
(in PowerShell, `$env:PYTHONPATH = "src"` once).

## Four tiers

Times are wall times on an 8-core / 16-thread AMD Zen 2 with an RTX 3060, measured 2026-10-19.

| Tier | When | Command | Time |
|---|---|---|---|
| 0 | While editing | `python -m pytest tests/test_floor_plates.py -m "not slow"` | seconds |
| 1 | After every change | `python -m pytest -m "not slow" -n 8` | about 45 s |
| 2 | Before each commit | `python -m pytest -m "not sweep" -n 8` | about 80 s |
| 3 | Before merging | `python -m pytest -n 8` | about 115 s |

When `app/` changed, also run the front-end checks of the same tier (see below): `npm test` takes about 12 s,
`npm run typecheck` 5 s and `npm run build` 7 s.

### Tier 0: the files you are editing

Run the test file of the module you are changing, or one test with `-k`:

```bash
python -m pytest tests/test_floor_plates.py -m "not slow"
python -m pytest tests/test_floor_plates.py -k end_wings
```

`--lf` runs only the tests that failed last time, which is quick after a fix. In `app/`:

```bash
npx vitest run src/steps/ModeStep.test.tsx
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

The whole suite, sweeps included. From time to time, and before a release, run it without `-n` (about 6 minutes): a
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

## Running in parallel

`-n 8` starts 8 worker processes and hands out single tests to them; each worker pays about 8 s of imports and
collection once. Tests must not depend on one another or on a shared file: each uses its own `tmp_path`. The engine computes each
sky matrix in a temporary folder of its own, so workers computing sky matrices at the same time do not share
Ladybug's weather folder. When another checkout is testing on
the same machine at the same time, `-n 4` leaves it room.
