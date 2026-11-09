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
├── tools/                  Developer scripts (the maps below, repository state, reference check, lockfile, app test data, Grasshopper smoke test)
├── benchmarks/             Timing scripts
├── pyproject.toml          Package metadata, dependencies and the Python import rules
├── setup_env.py            Automated environment setup (GPU detection)
├── requirements-lock.txt   The exact versions the tests last passed on, which setup_env.py installs
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
| 5. Stages and checks | `api_core/` (preprocessing, thresholding, exporting, massing, chains), `solar_check` (Simulate), `access_evaluation`, `sites` (the volume of a site, built by the service) |
| 6. Engine | voxels, test points, rays and kernels, sky and sun weights, scoring, meshing, floor plates, file reading; under it `outlines` (the closed polylines of DXF and OBJ files and the faces of DXF files, read with ezdxf) |
| 7. Settings and basics | config models and loading, the mode registry, errors, run context, the compute device, the weather file reader |

The exact list of modules in each layer is the `[tool.importlinter]` section of `pyproject.toml`. A second rule there
keeps the settings modules free of torch, Warp and the web server, so the CLI and the service can read configs without
starting the GPU stack.

`tests/test_architecture.py` runs these rules with every test run (`lint-imports` from the repository gives the same
report). A new module must be added to a layer, or the test fails. An exception would be listed with
`ignore_imports` and a comment saying why; there is none today.

## The app

The app (`app/src/`) is organised in folders, in layers like the Python package. A file may import from its own folder
and from the layers below, not from a layer above and not from another folder of its own layer. Top first:

| Layer | Folders | What they hold |
|---|---|---|
| 1. Page | `App.tsx`, `main.tsx` | the top bar with the device status, then the start screen or the open project |
| 2. Workspace | `workspace/` | the start screen, the open project with its top bar and step list, the project dialogs, the result steps that put the screens together |
| 3. Screens | `steps/`, `criteria/`, `simulate/`, `inspect/` | the Design steps other than Criteria; the Criteria step (list, panel, mode, settings, carving rule, typical building); Simulate; Inspect |
| 4. Shared parts | `common/` | what several screens use: the dialog frame, menus, the input box, the run's state and progress, the test-surfaces box |
| 5. Settings | `settings_form/` | the settings fields and their state, the analysis settings (SettingsStep), the cold period |
| 6. Over the 3D view | `viewer_overlays/` | the view pane, legends, compass, layers menu |
| 7. Theme | `theme/` | colours and sizes (`tokens.css`), the panels' stylesheet (`panels.css`), light and dark |
| 8. 3D scene | `viewer/` | the three.js scene, its loaders and decoders |
| 9. Service client | `api_client/` | the typed client of the service, and the open project's session (token, project, failure handler) |
| 10. React helpers | `hooks/` | small hooks that import nothing of the app: a value kept while its key holds, the latest value for callbacks, state adjusted when a value changes |
| 11. Basics | `messages.ts`, `format_numbers.ts`, `modes.ts`, `stages.ts` | every text of the interface, numbers as it writes them, the modes' names, the steps' and stages' names |

`app/.dependency-cruiser.cjs` holds these layers (`LAYERS`) and the other rules, checked by `npm test` (the `deps`
script):

- no import cycles between files;
- no source file that nothing imports (helpers named `*_for_test` are for tests);
- source does not import test files, and the built app uses only the packages under `dependencies`;
- `api_client/` imports only itself and `messages.ts`;
- `viewer/` imports no React component.

Tests may import across the layers. A new folder must be added to `LAYERS`, or nothing checks it.

## Drawing the maps

```bash
python tools/draw_maps.py
```

writes into `build/maps/` (not kept in git):

- `python_layers.svg`: the seven layers with their modules and the number of imports between them;
- `app_folders.svg`: the app's folders with the number of imports between them; two folders that import each other
  would be joined in red.

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
