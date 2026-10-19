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
| `--projects-folder` | the folder chosen in the app, else `~/UrbanSolarCarver/projects` | Folder that holds one subfolder per project; it is created when missing. It wins over the folder chosen in the app for that launch |
| `--no-browser` | off | Print the address without opening the browser |
| `--device`, `-d` | `auto` | Compute device: `auto`, `cpu` or `cuda` |

The browser interface is an optional extra of the package. `setup_env.py` installs it unless you pass `--no-ui`; to add it to an existing environment run `python -m pip install -e ".[ui]"` (see [Installation](getting-started/installation.md#browser-ui)). Without the extra, `usc ui` prints that command and exits, and every other command is unaffected.

When the service starts it compiles the GPU kernels in the background. The start screen shows "Preparing the GPU" until that ends; you can open a project and add files meanwhile, and the run buttons wait for the GPU.

## The start screen

The start screen shows the version, the device (the GPU's name, or that the CPU is used) and three cards:

- **New project**: type a name (up to 64 letters, numbers, spaces, hyphens or underscores) and create the project.
- **Open a project**: the projects folder, with **Change folder**, and the projects in it, newest first. Each project has a menu (see [Managing a project](#managing-a-project)).
- **Try an example**: three projects with their files already in place, so you can run an analysis without preparing any input. *Perimeter block* (a perimeter block 126 by 92 m, mode Solar time-based) is the smallest, *New building among neighbors* (a plot of about 18 by 17 m among existing buildings, mode Solar energy) is the middle one, and *District of many buildings* (about 208 by 227 m, mode Solar energy) is the largest. The first time you choose an example, it makes a copy as a new project, so the example itself never changes. After that, choosing it opens that project again. A project records which example it came from, so it is found after a rename. To start from a fresh copy, use **Reset to the example** in the project's menu.

### The projects folder

**Change folder** opens the operating system's folder picker on this computer. The browser never sends a path: the service shows the picker and reads the folder you choose. The folder is remembered in `~/.urbansolarcarver/ui.json` and used at the next launch. The projects already in the old folder stay there, and the list shows the projects of the new folder.

- **Change folder** is offered on the start screen only, with no run active. While a run is active the start screen says the folder can be changed once the run has ended.
- When the folder was given with `--projects-folder`, it wins for that launch and the start screen offers no Change folder. Start `usc ui` without the option to change it there.
- When the folder picker cannot open (no display, or tkinter missing), the start screen says so and the old folder stays. The way that always works is to start with `usc ui --projects-folder <folder>`.

### Managing a project

Each project in the list, and the project name in the top bar, has a menu:

- **Open folder** opens the project's folder in Explorer (Finder, or the file manager on Linux) on this computer. It works during a run.
- **Rename** asks for a new name, checked by the same rule as a new project's name, and renames the folder.
- **Delete** names the project and its folder and asks you to type the project name to confirm.
- **Reset to the example** (projects made from an example) replaces the project's inputs, settings and results with a fresh copy of the example, after a confirmation. The project keeps its name.

Rename, delete and reset wait while the project's run is active.

Delete and Reset send the project folder to the recycle bin (Windows) or trash (macOS, Linux), so a mistake can be undone; UrbanSolarCarver does not delete it for good. They remove only that one project folder, and refuse when the folder is not a direct child of the projects folder, has no `project.json` of that project, or is or holds a symbolic link or junction. On Windows they work only for a folder on a fixed disk of this computer: on a network, removable or other drive they are refused, and you can delete the folder in the file manager. A folder larger than the recycle bin's size limit may be deleted for good by Windows, and the app cannot check this beforehand.

## The steps

A project opens as a list of six steps on the left, with the 3D view on the right. Each step shows a one-line summary when it is closed.

1. **Inputs.** Drop or choose the maximum volume (the largest building you would allow), the test surfaces (the surfaces whose sun or sky the carving protects) and, for the modes that need one, a weather file (`.epw`). Meshes may be PLY, OBJ, STL or GLB; several files for one role are joined into one. The step lists each file with its triangle count and the size of all inputs together, and warns when the model looks as if it is not in meters.
2. **Mode.** Six tiles in a grid of three by two, each with a coloured symbol and a plain name. The tile's tooltip holds a one-line description, what the mode needs and the engine name, for people who use the CLI.

    | Tile | Engine name | What it does |
    |------|-------------|-------|
    | Angle rule | `tilted_plane` | Removes everything above a plane at a fixed angle from each facade |
    | Solar time-based | `time-based` | Keeps direct sun on the test surfaces during the hours you choose |
    | Solar energy | `irradiance` | Keeps sun and sky energy over the period |
    | Solar usefulness | `benefit` | Keeps sun in the hours that need heating |
    | Daylight | `daylight` | Keeps the view of an overcast sky |
    | Night cooling | `radiative_cooling` | Keeps a flat roof's view of the cold night sky. Experimental, and it assumes horizontal test surfaces |

    Choosing a mode fills its starting values in Settings. [Carving Modes](modes.md) explains the methods.
3. **Settings.** The analysis settings with plain labels, units and a help text for each: the analysis period, the mode's own settings and the detail (voxel size, sampling and, at the end of the detail settings, the rays per batch and the detailed statistics, which only change the run report). The step shows the size of the voxel grid and refuses a grid larger than the analysis can handle, naming the smallest voxel size that fits. **Run analysis** is in this step. See [Entering values](#entering-values).
4. **Carving.** How much to carve, with a histogram of the scores of the voxels (a log or linear scale), and the numbers of the last carving. Solar time-based has a *Shadow tolerated* slider in m²·h; the weighted modes have a *Carve amount* slider in percent; the Angle rule has no threshold. The other carving settings (the carving rule, score smoothing, the cut above a carved voxel, the steepest step between columns) are folded under the slider.
5. **Envelope and massing.** Two parts that are built on their own, since the massing reads the carving and not the envelope.
    - **Envelope**: its settings (smooth surface, smoothing passes, the smallest pieces and fragments kept), **Build envelope**, and its result, the envelope volume (counted on the kept voxels the mesh was built from, after small pieces are dropped, not on the smoothed surface).
    - **Building massing**: its settings (ground floor and upper floor heights, grid module, permitted volume exceedance, whether floors rest on the floors below), **Build massing**, and its results: the gross floor area, the number of storeys and a table with the bottom, top and floor area of each storey.

    Each part has its own out-of-date mark, "Out of date for the current settings". The step's summary says what exists, for example "Envelope built, massing not built". A link at the bottom opens the run report. The *grid module* is the square module the storeys are built from and the narrowest piece of floor allowed. The *permitted volume exceedance* is the share of a module on a storey that may lie outside the carved envelope; the massing never leaves the maximum volume. [Floor-plate massing](massing.md) describes the method.
6. **Export.** The mesh format of the carved envelope and the building massing, and the downloads: the carved envelope, the building massing, the building massing data (JSON), the settings (`config.yaml`) and the whole project as a zip. Each file is offered once it exists. The envelope and the massing are the files that were built, in the format they were built in. A change of format rebuilds the parts that exist (the envelope, the massing or both); while Carving is locked (see below), the format is stored without a build, Export says so, and the next build of each part writes the chosen format.

## Entering values

A number with a range is entered with a slider and a number field side by side. The number field takes any value the engine accepts; the slider covers the range people normally use (for example 0.1 to 5 m for the voxel size).

- **Balance temperature** (Solar usefulness) is one track from 10 to 30 °C with two handles, the two ends of the dead band: "Counts below" (sun counts in hours colder than this) and "Too warm above" (with harm counted, hours warmer than this count against the sun). Each end moves on its own and both can be typed; the app sends the engine the middle as `balance_temperature` and half the width as `balance_offset`, the dead band the engine reads on both sides of the balance temperature. Without harm counted the upper end does nothing, so it is muted with the note "(only with harm counted)". The lower handle comes first for Tab, as on the track; where the two handles lie on one spot, an arrow key toward the other end moves the focus to that end's handle and steps it, and Home or End takes the lower or the upper end to the end of the track.
- **Sample spacing** on test surfaces must not exceed the voxel size. When the voxel size goes below the sample spacing, the sample spacing is lowered to the voxel size and the settings say so under Voxel size ("Sample spacing lowered to 0.5 m to match the voxel size."). Raising the voxel size later does not raise it back. A sample spacing you type above the voxel size is not changed; it shows as an error on its own field.
- **Analysis period** is one control with two strips.
    - The year strip has twelve months and two handles for the start and the end date. A period across the new year (start after end, as in October to April) is drawn wrapped.
    - The hour strip has two handles for the first and the last hour. The last hour is inclusive, so 10 to 14 h samples 10:00 through 14:00. A range across midnight is drawn wrapped.
    - Presets set the dates and keep the hours: 21 December, 21 June, Heating season and Whole year. The heating season follows the hemisphere of the weather file's latitude: 1 April to 31 October south of the Tropic of Capricorn (23.44 degrees), 1 October to 30 April elsewhere, within the tropics and without a weather file.
    - In Solar usefulness a fifth preset, **Cold period from the weather file**, sets the dates of the site's cold period: the longest run of days whose mean temperature over the month around them is below the balance temperature minus the dead band. The line under the presets says what it found ("Cold period of the weather file, where the mean of the month around each day is below 13 °C: 30 Sep to 15 May."). It needs the weather file. Changing the balance temperature later updates that line but not the dates already set; press the preset again to use the new ones. Solar usefulness already counts only the hours colder than that threshold, so the cold period mostly leaves out cold hours outside the heating season, such as cool summer mornings; it changes more when the experimental "include harm" option is on, whose warm hours depend on the period.
    - The period in words below the strips ("21 Dec, 10 to 14 h") opens fields where you type exact dates and hours.
    - When you add or replace the weather file (not when a project opens with one), Settings shows one notice about the new file, with two buttons; either button closes it, and a later weather file replaces it. In Solar usefulness it offers the cold period of the new file when its dates differ from the period's, keeping the hours ("The new weather file (Brisbane, AUS) has its cold period from 3 May to 20 Sep; the analysis period is 30 Sep to 15 May.", **Use the cold period** or **Keep**); it waits for the cold period and shows nothing when the file has none. In Solar time-based and Solar energy it appears only when the new file is in the other hemisphere from the one before (a project without one counts as northern, as the starting values are), and offers the same dates six months on: the month plus six, the day held to the month's length, the last day of a month staying the last day (30 Apr gives 31 Oct). For example "The new weather file (Brisbane, AUS) is in the southern hemisphere: winter there is June to August. Shift the analysis period by six months, to 21 Jun, 10 to 14 h?", **Shift by six months** or **Keep**. A period that covers the whole year covers the same days six months on, so it gets no offer. A file within the tropics, or one whose latitude cannot be read, brings no offer, and the hemisphere of the file before it still counts for the next one. The offer is saved as any change of the period is; while a run is in progress the buttons are disabled, as the settings are. Either button moves the focus to the analysis period's start date. Once the period changes, by the button or by hand, the notice is gone and stays gone if the period is set back; choosing a mode without an analysis period (Angle rule, Daylight, Night cooling) dismisses it too. Screen readers announce the notice as it appears.
    - Each handle takes the keyboard: the arrow keys move it by one day or one hour, Page Up and Page Down by a month or six hours, Home and End to the first or last day or hour.
    - When the hours cross midnight on a single date, the end date moves to the next day ("21 to 22 Dec, 22 to 2 h"). A period stored earlier with one date and hours across midnight reads "Every day, 22 to 2 h", because the engine runs it on every day of the year.

## Running: two phases

A run has two phases, so that the part that takes time happens once and the part you adjust is quick.

1. **Run analysis** runs the sun analysis and the carving (the preprocessing and thresholding stages). The 3D view then shows the voxels, kept voxels coloured by score and carved voxels in a separate layer. The progress shows the stages, the ray batches and the elapsed time, with a Cancel button.
2. **Build envelope** and **Build massing** (in Envelope and massing) run on the voxel result you settled on in the Carving step: the exporting stage and the massing stage. **Build envelope and massing** in Carving builds both.

Between the two you change the threshold. Moving the slider (or typing a value) changes the cutoff line in the histogram; **Update carving** applies it, which thresholds the scores again without repeating the analysis. Switching on **Update when I change the threshold** applies each change as you let go of the slider or leave the field. The choice is remembered per project in the browser.

The interface keeps track of what each result was built from. When you change a setting or an input after a result exists, that result stays visible, dimmed and labelled out of date, and the step that needs a run says so. Running again replaces it. A run only starts the stages whose results are missing or out of date.

While the mode or the analysis settings in the form differ from the stored ones, Carving is locked, because a build would have to run the analysis first. The two builds then wait with a message to run the analysis again, and a mesh format change is stored and written by the next build of each part.

## The 3D view

The view has a compass, an axis gizmo (the three lettered axes, drawn straight on the viewport) and a legend for the coloured layers. The **Layers** menu switches the maximum volume, the test surfaces, the kept and carved voxels, the sun path, the sky dome, the carved envelope and the building massing. Buttons frame the whole model, show the top view and switch between a light and a dark viewport (remembered in the browser).

The ground aid button cycles through three states: off, a ground grid with a scale bar, and a compass ring on the ground around the scene (ticks every 10 degrees, the letters N, E, S and W every 90 degrees, rotated by the north direction). The button names the aid it switches to, and the choice is remembered in the browser. The compass ring, the sun path and the sky dome are centred on, and sized to, everything loaded (the maximum volume and the test surfaces together).

## Where projects are kept

Each project is a folder in the projects folder:

```
<projects folder>/<project name>/
├── inputs/        The files you added (max_volume/, test_surfaces/, weather.epw)
│                  and the joined meshes the engine reads (joined/)
├── config.yaml    The settings, a normal USC configuration file
├── project.json   The project's record: the files you added with their triangle counts, the input revision,
│                  the example it came from (if any)
│                  and one record per completed stage (with the settings that stage ran with)
└── run/           The engine's output: preprocessing/, thresholding/, exporting/ and massing/
```

`config.yaml` works outside the interface: its paths are relative to the project folder, so `usc run -c <project folder>/config.yaml` runs the same analysis from the command line. Thresholding also writes `scores_compared_with_cutoff.npy` in its folder (the values the cutoff is applied to, which the histogram draws). To delete a project, use Delete in its menu (see [Managing a project](#managing-a-project)), or delete its folder in the file manager.

## Security

The service listens on `127.0.0.1` only and checks the `Host` header of every request, which stops a web page on another site from reaching it. Every request to the API needs the token of the launch, which only the printed and opened address carries, and the service takes no file path from the browser: it derives every folder from a validated project name, and the folder picker is shown by the service on this computer.

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
