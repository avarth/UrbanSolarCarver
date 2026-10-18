# Browser UI

`usc ui` opens UrbanSolarCarver in your browser. You add the maximum volume and the test surfaces, choose a mode, run the analysis, adjust how much to carve while watching the result in 3D, build the envelope and building massing, and download the files. It runs the same engine as the CLI and the Python API; everything stays on your computer.

## Starting the interface

In the UrbanSolarCarver folder, double-click `start-urbansolarcarver.bat` on Windows, or run `./start-urbansolarcarver.sh` in a terminal on Linux and macOS. The first time, the launcher installs UrbanSolarCarver with `setup_env.py` (this takes several minutes and needs Python 3.10 or newer); after that it starts the interface at once. A window stays open while the interface runs: close it (Windows) or press Ctrl+C (Linux, macOS) to stop UrbanSolarCarver. The launcher passes its arguments on to `usc ui`, so `start-urbansolarcarver.bat --port 8780` works too. It uses the environment in `.venv` in the folder, or `~/.usc-venv` when `setup_env.py` had to put it there; for an environment made with `setup_env.py --venv-dir`, set `USC_VENV` to that folder.

From a terminal with the environment active, the same command is:

```bash
usc ui
```

The command prints the address to open and opens it in your default browser once the service is listening. When another program already uses the port, the command says so and stops without opening the browser; choose a free port with `--port`. The address carries a token that is new on every launch, so keep using the page it opened (or the printed address) and not a bookmark from an earlier launch. Press Ctrl+C in the terminal to stop the service.

| Option | Default | Meaning |
|--------|---------|---------|
| `--port` | `8770` | Port on `127.0.0.1` |
| `--projects-folder` | `~/UrbanSolarCarver/projects` | Folder that holds one subfolder per project; it is created when missing |
| `--no-browser` | off | Print the address without opening the browser |
| `--device`, `-d` | `auto` | Compute device: `auto`, `cpu` or `cuda` |

The browser interface is an optional extra of the package. `setup_env.py` installs it unless you pass `--no-ui`; to add it to an existing environment run `python -m pip install -e ".[ui]"` (see [Installation](getting-started/installation.md#browser-ui)). Without the extra, `usc ui` prints that command and exits, and every other command is unaffected.

When the service starts it compiles the GPU kernels in the background. The start screen shows "Preparing the GPU" until that ends; you can open a project and add files meanwhile, and the run buttons wait for the GPU.

## The start screen

The start screen shows the version, the device (the GPU's name, or that the CPU is used) and three cards:

- **New project**: type a name (up to 64 letters, numbers, spaces, hyphens or underscores) and create the project.
- **Open a project**: the projects in the projects folder, newest first.
- **Try an example**: three projects with their files already in place, so you can run an analysis without preparing any input. *Perimeter block* (a perimeter block 126 by 92 m, mode Sun at set hours) is the smallest, *New building among neighbors* (a plot of about 18 by 17 m among existing buildings, mode Solar energy) is the middle one, and *District of many buildings* (about 208 by 227 m, mode Solar energy) is the largest. Choosing an example makes a copy as a new project, so the example itself never changes.

## The steps

A project opens as a list of six steps on the left, with the 3D view on the right. Each step shows a one-line summary when it is closed.

1. **Inputs.** Drop or choose the maximum volume (the largest building you would allow), the test surfaces (the surfaces whose sun or sky the carving protects) and, for the modes that need one, a weather file (`.epw`). Meshes may be PLY, OBJ, STL or GLB; several files for one role are joined into one. The step lists each file with its triangle count and the size of all inputs together, and warns when the model looks as if it is not in meters.
2. **Mode.** Six tiles, each with a plain name and a one-line description. The engine name, for people who use the CLI, is in the tile's tooltip.

    | Tile | Engine name | What it does |
    |------|-------------|-------|
    | Sun at set hours | `time-based` | Keeps direct sun on the test surfaces during the hours you choose |
    | Solar energy | `irradiance` | Keeps sun and sky energy over the period |
    | Solar heat when cold | `benefit` | Keeps sun in the hours that need heating |
    | Daylight | `daylight` | Keeps the view of an overcast sky |
    | Angle rule | `tilted_plane` | Removes everything above a plane at a fixed angle from each facade |
    | Night cooling | `radiative_cooling` | Keeps a flat roof's view of the cold night sky (experimental) |

    Choosing a mode fills its starting values in Settings. [Carving Modes](modes.md) explains the methods.
3. **Settings.** The analysis settings with plain labels, units and a help text for each: the analysis period, the mode's own settings, the detail (voxel size and sampling) and the computer group (rays per batch, detailed statistics). The step shows the size of the voxel grid and refuses a grid larger than the analysis can handle, naming the smallest voxel size that fits. **Run analysis** is in this step.
4. **Carving.** How much to carve, with a histogram of the scores of the voxels (a log or linear scale), and the numbers of the last carving. Sun at set hours has a *Shadow tolerated* slider in m²·h; the weighted modes have a *Carve amount* slider in percent; the Angle rule has no threshold. The other carving settings (the carving rule, score smoothing, the cut above a carved voxel, the steepest step between columns) are folded under the slider.
5. **Envelope and massing.** The envelope settings and the building massing settings (ground floor and upper floor heights, bay width, allowed overhang, whether floors rest on the floors below), then **Build envelope and massing**. The results are the gross floor area, the number of storeys, the envelope volume and a table with the bottom, top and floor area of each storey. A link opens the run report.
6. **Export.** The mesh format of the carved envelope and the downloads: the carved envelope, the building massing (OBJ), the building massing data (JSON), the settings (`config.yaml`) and the whole project as a zip. A change of format rebuilds the envelope mesh only.

## Running: two phases

A run has two phases, so that the part that takes time happens once and the part you adjust is quick.

1. **Run analysis** runs the sun analysis and the carving (the preprocessing and thresholding stages). The 3D view then shows the voxels, kept voxels coloured by score and carved voxels in a separate layer. The progress shows the stages, the ray batches and the elapsed time, with a Cancel button.
2. **Build envelope and massing** runs on the voxel result you settled on in the Carving step (the exporting and massing stages).

Between the two you change the threshold. Moving the slider (or typing a value) changes the cutoff line in the histogram; **Update carving** applies it, which thresholds the scores again without repeating the analysis. Switching on **Update when I change the threshold** applies each change as you let go of the slider or leave the field. The choice is remembered per project in the browser.

The interface keeps track of what each result was built from. When you change a setting or an input after a result exists, that result stays visible, dimmed and labelled out of date, and the step that needs a run says so. Running again replaces it. A run only starts the stages whose results are missing or out of date.

## The 3D view

The view has a compass, a ground grid with a scale bar, an axis gizmo and a legend for the coloured layers. The **Layers** menu switches the maximum volume, the test surfaces, the kept and carved voxels, the sun path, the sky dome, the carved envelope and the building massing. Buttons frame the whole model, show the top view and switch between a light and a dark viewport (remembered in the browser).

## Where projects are kept

Each project is a folder in the projects folder:

```
<projects folder>/<project name>/
├── inputs/        The files you added (max_volume/, test_surfaces/, weather.epw)
│                  and the joined meshes the engine reads (joined/)
├── config.yaml    The settings, a normal USC configuration file
├── project.json   The project's record: the files you added with their triangle counts, the input revision
│                  and one record per completed stage (with the settings that stage ran with)
└── run/           The engine's output: preprocessing/, thresholding/, exporting/ and massing/
```

`config.yaml` works outside the interface: its paths are relative to the project folder, so `usc run -c <project folder>/config.yaml` runs the same analysis from the command line. Thresholding also writes `scores_compared_with_cutoff.npy` in its folder (the values the cutoff is applied to, which the histogram draws). Deleting a project is deleting its folder.

## Security

The service listens on `127.0.0.1` only and checks the `Host` header of every request, which stops a web page on another site from reaching it. Every request to the API needs the token of the launch, which only the printed and opened address carries, and the service takes no file path from the browser: it derives every folder from a validated project name.

## Without a CUDA-enabled GPU

When no CUDA-enabled GPU is found, the start screen says so and the engine runs on the CPU. The results are the same, and an analysis takes noticeably longer, so start with a larger voxel size or with the smallest example. `--device cpu` chooses the CPU even when a GPU is present.

## Rebuilding the front-end after changing `app/`

The interface is a React and three.js application whose source is in `app/`. The package carries its built files in `src/urbansolarcarver/ui_static/`, so using `usc ui` needs no Node.js. After changing `app/`:

```bash
cd app
npm install
npm run typecheck  # tsc --noEmit: the type check alone
npm run build      # runs the type check first, then writes src/urbansolarcarver/ui_static/ and build_info.json
npm test           # the front-end tests
```

A type error stops `npm run build` before anything is written.

Commit the rebuilt `ui_static/` with the source change: a test compares the hash in `build_info.json` with the sources and fails when they differ.

If the service's API changed, regenerate the client types with `npm run api-types`. It runs `python` with the `ui` extra installed, so activate the repository's environment first (in a git worktree without an environment, set `PYTHONPATH=../src` and use a Python that has the extra).
