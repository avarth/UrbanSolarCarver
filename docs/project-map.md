# Project Map

How the code is laid out, which parts may use which, and how to draw the current picture. The rules on this page are
checked by the tests, and the pictures are drawn from the code, so neither depends on this page being kept up to date.
What each file does is written at the top of the file itself.

## Repository root

```
UrbanSolarCarver/
├── src/urbansolarcarver/   Core Python package (the engine, the API, the CLI and the browser UI's service)
├── app/                    Source of the browser UI front-end (React, three.js)
├── configs/                YAML config templates (one per mode, a reference and an archetype example)
├── examples/               Example data, weather file, and Jupyter notebook tutorials
├── tests/                  Pytest suite (see Testing)
├── grasshopper/            Rhino Grasshopper plugin
├── docs/                   MkDocs documentation source
│   └── publications/       The ReSBE 2026 paper (PDF, CC BY-NC-ND 4.0)
├── tools/                  Developer scripts (the maps below, Grasshopper smoke tests)
├── benchmarks/             Timing scripts
├── pyproject.toml          Package metadata, dependencies and the Python import rules
├── setup_env.py            Automated environment setup (GPU detection)
├── mkdocs.yml              Documentation site configuration
├── CHANGELOG.md            Release history
├── CITATION.cff            Citation metadata
├── CONTRIBUTING.md         Contribution guidelines
├── LICENSE                 AGPL-3.0
└── README.md               Project landing page
```

## The Python package in seven layers

Each module of `src/urbansolarcarver/` sits in one layer. A module may import from the layers below it, never from a
layer above. The layers, top first:

| Layer | What it holds |
|---|---|
| 1. Front ends | `carver_cli` (the `usc` command) and `daemon` (the process Grasshopper talks to) |
| 2. Browser UI service | `local_web_service/`: projects, criteria, studies, runs and the HTTP routes the app calls |
| 3. Requests | `engine_requests`: one entry point that runs a stage chain or a simulation for the service and the daemon |
| 4. API | `api`: the public Python API (`run_pipeline`, `run_chain` and the stage functions) |
| 5. Stages and checks | `api_core/` (preprocessing, thresholding, exporting, massing, chains), `solar_check` (Simulate), `access_evaluation` |
| 6. Engine | voxels, test points, rays and kernels, sky and sun weights, scoring, meshing, floor plates, file reading |
| 7. Settings and basics | config models and loading, the mode registry, errors, run context, the compute device, the weather file reader |

The exact list of modules in each layer is the `[tool.importlinter]` section of `pyproject.toml`. A second rule there
keeps the settings modules free of torch, Warp and the web server, so the CLI and the service can read configs without
starting the GPU stack.

`tests/test_architecture.py` runs these rules with every test run (`lint-imports` from the repository gives the same
report). A new module must be added to a layer, or the test fails. Known exceptions are listed with
`ignore_imports` and a comment saying why; there is one today, `api_core.chain` importing `api`.

## The app

The app (`app/src/`) is organised in folders by screen and concern: `steps/` (the five steps and the workspace),
`criteria/`, `simulate/`, `inspect/`, `settings_form/`, `viewer/` (the three.js scene), `viewer_overlays/` (what sits
over the 3D view), `api_client/` (the typed client of the service) and `theme/`, with `App.tsx`, `main.tsx` and
`messages.ts` (every text of the interface) at the top.

`app/.dependency-cruiser.cjs` holds its rules, checked by `npm test` (the `deps` script):

- no import cycles between files;
- no source file that nothing imports (helpers named `*_for_test` are for tests);
- source does not import test files, and the built app uses only the packages under `dependencies`;
- `api_client/` imports only itself and `messages.ts`;
- `viewer/` imports no React component.

The folders themselves still import each other both ways in several places (red in the folder map below).

## Drawing the maps

```bash
python tools/draw_maps.py
```

writes into `build/maps/` (not kept in git):

- `python_layers.svg`: the seven layers with their modules and the number of imports between them;
- `app_folders.svg`: the app's folders with the number of imports between them, pairs that import each other in red.

`--modules` also draws every Python module (`python_modules.svg`, pydeps). It needs Graphviz
(`winget install Graphviz.Graphviz`), the dev extra and `npm install` in `app/`.

## What each file does

- **Python:** the docstring at the top of each module (a test checks that every module has one). The
  [API reference](api/index.md) renders those of the public modules.
- **App:** the comment at the top of each file.
- **The service's HTTP routes:** `app/src/api_client/generated_types.ts`, generated from the service by
  `npm run api-types` (which also writes the OpenAPI document `app/openapi.json`, not kept in git).
- **Tests:** the docstring of each test file; [Testing](testing.md) explains the tiers and the shared scenes.

## Grasshopper plugin (`grasshopper/`)

```
grasshopper/
├── USC_GHplugin/       .ghuser components (copy into the GH User Objects folder)
├── components/         Python source for each component
├── icons/              24×24 component icons
├── components.json     Ribbon group and stable GUID per component
├── usc_gh.py           Helpers shared by the components, loaded at run time
└── build_ghuser.py     Builds the .ghuser files from components/ (see the Grasshopper page)
```

## Configuration templates (`configs/`)

One YAML template per mode (`config_<mode>.yaml`), `REFERENCE_all_options.yaml` with every parameter described, and
`archetype_example.yaml`, a building archetype for `usc simulate-weights`. Start from the template of your mode and fill
in the paths.
