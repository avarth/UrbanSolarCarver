# Browser UI

`usc ui` opens UrbanSolarCarver in your browser. You add the maximum volume, add the test surfaces and choose a mode for a criterion (a project can carve with several criteria, one after the other), run the analysis, adjust how much to carve while watching the result in 3D, build the envelope and building massing, and download the files. It runs the same engine as the CLI and the Python API; everything stays on your computer.

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

A project opens as a list of five steps on the left, with the 3D view on the right. Each step shows a one-line summary when it is closed.

1. **Inputs.** The site: drop or choose the maximum volume (the largest building you would allow) and, for the modes that need one, a weather file (`.epw`). The test surfaces belong to each criterion (step 3). Two boxes are optional: **Existing surroundings** (buildings and large trees that stay, `context_path`; not balconies or shading devices) and **Terrain** (the ground, `terrain_path`). Both block sun and sky; nothing is built in the columns the surroundings take, and the site stays buildable above the terrain (see [Context and terrain](modes.md#context-and-terrain)). Removing their files makes the analysis out of date, and the next run goes without them. With either of them, Site and grid shows **Account for context blocking** (on by default; not in the Angle rule, which traces no rays to the sky): off, they still take their voxels but block no sun or sky, to compare the two carvings. Meshes may be PLY, OBJ, STL or GLB; several files for one role are joined into one. The step lists each file with its triangle count and the size of all inputs together, and warns when the model looks as if it is not in meters.
2. **Site and grid.** The analysis settings every criterion shares, with plain labels, units and a help text for each: north, the surroundings switch and the detail (voxel size, then, folded, the rays per batch and the detailed statistics, which only change the run report). The sample spacing on the test surfaces, the grid margin and the ray length have no field: the engine's values apply (see below). The step shows the size of the voxel grid and refuses a grid larger than the analysis can handle, naming the smallest voxel size that fits. **Run analysis** is pinned under the steps while it is open. Its summary reads "North 10°, 0.5 m voxels". See [Entering values](#entering-values).
3. **Criteria.** A criterion is one carving pass with its own test surfaces, mode and carving rule. The step always shows the list of criteria, also with one criterion (a new project starts with one), then the panel of the selected criterion, and keeps **Run analysis** and **Build envelope and massing** pinned under the steps while it is open. In this order (the rows, **Add criterion** and the pinned bar are described under [Several criteria](#several-criteria)):
    - **The list**: one row per criterion in carving order, each with a colour swatch, its name, the symbol of its mode, its result or state, a switch that is on and a menu. **Add criterion**, under the list, opens a short menu of the six modes.
    - **The panel of the selected criterion**, in four sections, each a button with the section's title and, while it is closed, a one-line summary of what it holds. **Test surfaces** and **Carving rule** start open, **Mode** and **Settings** closed; the sections you open or close stay as you left them when you select another criterion.
        - **Test surfaces** (summary: the file name, two file names, "3 files" or "None yet"): the criterion's test surfaces (the surfaces whose sun or sky the carving protects), a drop box like the Inputs boxes. While it has none, the box says **Add test surfaces** with a hint of what its mode may protect (Daylight: windows or facades; Solar energy: roofs or facades), and Run analysis waits for them.
        - **Mode** (summary: the mode's plain name): six tiles in a grid of three by two, each with a coloured symbol and a plain name. The tile's tooltip holds a one-line description, what the mode needs and the engine name, for people who use the CLI.

        | Tile | Engine name | What it does |
        |------|-------------|-------|
        | Angle rule | `tilted_plane` | Removes everything above a plane at a fixed angle from each facade |
        | Solar time-based | `time-based` | Keeps direct sun on the test surfaces during the hours you choose |
        | Solar energy | `irradiance` | Keeps sun and sky energy over the period |
        | Solar usefulness | `benefit` | Keeps sun in the hours that need heating |
        | Daylight | `daylight` | Keeps the view of an overcast sky |
        | Night cooling | `radiative_cooling` | Keeps a flat roof's view of the cold night sky. Experimental, and it assumes horizontal test surfaces |

        Choosing a mode fills its starting values in the Settings section. [Carving Modes](modes.md) explains the methods.
        - **Settings** (summary: the analysis period in words, "21 Dec, 7 to 19 h", in the modes that have one; otherwise "Starting values" or "2 settings changed"): the analysis period, the mode's own settings and, folded, the rays per sky patch in the four sky-patch modes.
        - **Carving rule** (summary: "Carve 70 %", "Cutoff 1.5 m²·h", "Automatic", or "Everything above the planes" in the Angle rule): how much to carve, with a histogram of the scores of the voxels (a log or linear scale) and the numbers of the last carving. In the weighted modes the *Carving rule* comes first: *Manual* (the *Carve amount* slider, in percent of the total score) or *Automatic* (no setting: the cut is found from the spread of the scores, and the step says where it fell). A cutoff on the scores that a config holds (from the command line or an earlier version) shows as Manual, at the carve amount it stands for. Solar time-based has a *Shadow tolerated* slider in m²·h; the Angle rule has no threshold. The histogram follows the control in both rules; the other carving settings (score smoothing, the cut above a carved voxel, the steepest step between columns) are folded at the end. Scores are in physical units: m²·h of shade (Solar time-based), kWh of solar energy or of useful solar heat a voxel blocks (Solar energy, Solar usefulness), and m² of fully hidden sky (Daylight, Night cooling); the histogram axis, the cutoff, the 3D legend and the slider ends say which. Before the first analysis it says to run the analysis.
    - **The pinned bar**: **Run analysis** and **Build envelope and massing** side by side, with the progress of the run and its messages under them, whichever section is open.

    A section with a problem opens by itself and its summary turns to the warning colour, with a warning icon (screen readers hear "Needs attention" in its header): no test surfaces; a weather file the mode needs and the project lacks (Mode, whose summary reads "Daylight, needs a weather file"); settings the last save refused (Settings or Carving rule, where a closed section says "2 settings to fix" in place of its summary). A criterion that is off needs neither test surfaces nor a weather file, and its closed Carving rule reads "Off". A **Go to** *setting* link in a refused run opens the section that holds the setting and focuses the field.

    The step's summary joins the mode and the carving: "Solar usefulness, 56 % kept". With several criteria it lists each one with the share it kept: "Daylight on windows 70 %, then Solar usefulness 80 %". A criterion that is off reads "Solar usefulness, Off", and with every criterion off the summary is "All off".
4. **Envelope and massing.** Two parts that are built on their own, since the massing reads the carving and not the envelope.
    - **Envelope**: its settings (smooth surface, smoothing passes, the smallest pieces and fragments kept), **Build envelope**, and its result, the envelope volume (counted on the kept voxels the mesh was built from, after small pieces are dropped, not on the smoothed surface).
    - **Building massing**: its settings (ground floor and upper floor heights, grid module, permitted volume exceedance, whether floors rest on the floors below), **Build massing**, and its results: the gross floor area, the number of storeys and a table with the bottom, top and floor area of each storey.

    Each part has its own out-of-date mark, "Out of date for the current settings". The step's summary says what exists, for example "Envelope built, massing not built". A link at the bottom opens the run report. The *grid module* is the square module the storeys are built from and the narrowest piece of floor allowed. The *permitted volume exceedance* is the share of a module on a storey that may lie outside the carved envelope; the massing never leaves the maximum volume. [Floor-plate massing](massing.md) describes the method.
5. **Export.** The mesh format of the carved envelope and the building massing, and the downloads: the carved envelope, the building massing, the building massing data (JSON), the settings (`config.yaml`) and the whole project as a zip. Each file is offered once it exists. The envelope and the massing are the files that were built, in the format they were built in. A change of format rebuilds the parts that exist (the envelope, the massing or both); while the carving is locked (see below), the format is stored without a build, Export says so, and the next build of each part writes the chosen format.

## Several criteria

A project can carve with several criteria in turn, for example the daylight of the neighbours' windows first and then the winter sun on a yard. Each criterion has its own test surfaces, mode, mode settings and carving rule, and decides among the voxels the criterion before it kept ([Criteria: chained carvings](criteria.md) explains the method). The Criteria step is built for this from the start: the list is there with one criterion, and **Add criterion** under it starts a chain.

### The list

The list has one row per criterion, in carving order. A row shows:

- a colour swatch, the criterion's colour in the 3D view's by-criterion layer;
- the criterion's name and the symbol of its mode;
- a line: when the criterion is current, what it carved, "70 % of the score carved, 813 m³ removed" in the weighted modes or "62 % of the volume carved, 420 m³ removed" in the others; otherwise its state:

| Line | Meaning |
|------|---------|
| Out of date | Its test surfaces or settings changed after its last run, or a shared setting did |
| Updates from *name* | A criterion before it is out of date or running, so this carving will change when that one finishes |
| Running | The run is tracing or carving it now |
| Off | Switched off: the chain skips it |
| Add test surfaces | It protects nothing yet, and a run waits for its files |
| Not run yet | It has test surfaces and no result |

Pressing a row selects it, and the panel, the histogram, the carving numbers and the 3D view then follow that criterion: the kept voxels are the ones left after it. A row also has:

- a switch that means on, **Use** *name*. It is on by default, and a new criterion is on. Switching it off leaves the criterion out of the chain without deleting it: the row reads "Off" and the panel says "Off: the chain skips this criterion" in place of its carving rule. Switching it on again brings the panel back;
- a menu with **Rename**, **Duplicate** and **Delete**. Duplicate copies the settings and the test surface files into a new criterion at the end and selects it. Delete asks first: the criterion's settings and results go, and the test surface files no other criterion uses go to the recycle bin. The criteria left keep their switches: when the one left is off, it stays off and Run analysis waits with "Turn on a criterion to run". The only criterion cannot be deleted (the item waits with "A project needs at least one criterion.");
- with two or more criteria, a drag handle: drag the row to reorder, or focus the handle and press the up or down arrow key. Reordering puts out of date the carving of the criteria from the first changed position on. A single criterion has no handle.

When the selected criterion is deleted, the selection moves to the next row, or to the previous one when it was the last. Switching the selected criterion off keeps it selected, and its panel says it is off. While a run is active the rows, the switches and the menus wait.

**Add criterion**, under the last row, opens a short menu of the six modes, each with its symbol, its plain name and its one-line description under "Mode of the new criterion". Choosing a mode adds the criterion at the end of the chain, named after its mode, and selects it; its Test surfaces section is open, since it has none yet. The arrow keys, Home and End move in the menu, and Escape closes it and returns to the button. While a run is active **Add criterion** waits; a run that starts while the menu is open makes its items wait, with the reason under them.

Under the list, with two or more criteria on, a line gives what the chain kept: "Kept 480 m³, 48 % of the maximum volume". It is the volume left after the last criterion that is on, against the maximum volume as drawn.

### The panel of a criterion

The panel is the one described under [Criteria](#the-steps), for the selected criterion. With several criteria:

- Under the **Test surfaces** box, **Use a file from another criterion** lists the files the other criteria hold, each with a **Use** button. Using a file adds no copy, and removing a file from one criterion leaves it in the others.
- The carve amount and the histogram of the second criterion on refer to the voxels the criteria before it kept, so 80 % in the second criterion is 80 % of the score of what is left.
- **Update carving** and **Update when I change the threshold** carve again from the selected criterion on, without tracing: moving the cutoff of criterion 1 thresholds criteria 1 and 2 again in one run, criterion 2's row reads "Updates from *name*" (the name of criterion 1) until it finishes, and criterion 1's histogram keeps its own scores. When another criterion has an analysis that is out of date, the change is saved and nothing runs; the step says "Run the analysis for *name* first", and Run analysis traces that criterion first.

### The pinned bar

**Run analysis** and **Build envelope and massing** sit side by side in the bar pinned under the steps while the Criteria step is open, so they are in view with any section of the panel open or closed. The progress of a run, its refusals and the failure of a carving update are under them; the warnings of the last run fold behind one line, "2 warnings", which opens their list, while a failure and "Cancelled." are said in full. When the progress is long and the window short, the bar scrolls within its height and the step above stays reachable. With several criteria a reason names the criterion it is about, the selected one too: "Add test surfaces to Daylight to run the analysis", "Add a weather file to run Daylight", "Fix the analysis period of Daylight to run the analysis". **Build envelope and massing** waits, with its reason under it, while the analysis is missing ("Run the analysis before building"), out of date ("Settings changed: run the analysis again before building"), or current with a carving that is not ("Update the carving before building"), and while a run is active.

### What the criteria share

The maximum volume, the surroundings, the terrain and the weather file are set once in Inputs, and the settings of **Site and grid** (north, voxel size, the surroundings switch and, folded, the rays per batch and the detailed statistics) apply to every criterion. A change to any of them puts every criterion out of date. A setting belongs to a criterion when the service lists it in `GET /api/criterion-keys` (the mode's settings and the carving rule); the app takes the split from there. The weather file reaches only the criteria whose mode reads one.

### Runs

**Run analysis**, in the Criteria step's pinned bar and in Site and grid, traces the rays of the criteria whose test surfaces, mode settings or a shared setting changed, then carves the chain from the first of them on. There is one Run analysis for the whole chain and no button per row. After adding a second criterion to a finished project, the next run traces only the new one. The progress lists the stages of each criterion, "Daylight on windows: Sun analysis" and "Daylight on windows: Carving", then the envelope and the massing; with one criterion the rows keep their plain names.

A refused run points at the criterion that caused it, in the pinned bar:

- A setting of one criterion that the engine refuses selects that criterion's row, says so in the bar with a **Go to** *setting* link, and marks the field. The link opens the section of the panel that holds the setting (Mode, Settings or Carving rule) and focuses the field.
- A criterion that protects nothing selects its row and opens its Test surfaces section; the bar says "Add test surfaces to *name*." **Run analysis** waits with "Add test surfaces to *name* to run the analysis" while any criterion that is on has none.
- With every criterion off, the run waits with "Turn on a criterion to run".

**Build envelope and massing** waits until every criterion that is on is carved, and builds once, from the last criterion.

### The 3D view with several criteria

- The layer **Carved voxels, by criterion** (Layers menu, hidden until you turn it on) draws each carved voxel in the colour of the criterion that removed it, and the legend, "Carved voxels, by the criterion that removed them", names each colour. The layer appears once every criterion that is on has run; the menu says so until then. It is dimmed with the other results while any criterion is out of date. Beyond 1,000,000 carved voxels it draws a regular share of them, and the legend says which ("Showing 1 of every 2 voxels").
- The layer **Test surfaces** draws each criterion's files in the colour of that criterion, all at full strength. With two or more criteria its entry in the Layers menu has a check box and a colour swatch for each criterion, in chain order (a criterion that is switched off reads "name (off)"), all checked until you change them; the **Test surfaces** check box shows or hides the layer as the other layers' do (half checked while some criteria are unchecked) and does not change which criteria are checked. A file that several criteria use is drawn once, in the colour of the selected criterion when it uses the file and is shown, else in the colour of the first shown criterion that uses it. Which criteria are shown stays as you set it when you select another criterion or open another step, and is not saved with the project. The sun path and the sky dome follow the selected criterion.

### The run report

With several criteria the run report's Criteria section has one row per criterion: name, mode, rule, cutoff with its unit, voxels at start and voxels kept. A **Chain** section follows, with the maximum volume (the filled voxels the first criterion started with), the volume left after each criterion in m³ and its share of the maximum volume in %. The total time adds the analysis and carving of every criterion to the exporting and the massing. A report of one criterion has no Chain section. The Configuration, Preprocessing and Thresholding sections describe the last criterion.

### Earlier projects

A project made with an earlier version opens as a chain of one criterion: one row in the list, its results still current, and the test surfaces it protected in the Test surfaces box of its only criterion. A project that was carved further with an earlier version keeps its maximum volume (the last envelope) and the note under it in Inputs, "Carved by Daylight, then Solar time-based. The earlier maximum volumes are kept in the project folder, in inputs/earlier_max_volumes." **Carve further** is no longer in the app: add a criterion to carve what the first one kept, which also leaves no mesh between the criteria to voxelize again.

## Criteria in a project

A project holds an ordered list of **criteria**, the carving passes of a chain (see [Criteria: chained carvings](criteria.md)). Each has its own mode, test surfaces, mode settings and carving rule, and decides among the voxels the criteria before it kept. Every project holds at least one: deleting the only criterion is refused with a 422 (*A project needs at least one criterion.*).

The app asks for a criterion's settings and results by its id. A client that does not name one (the routes keep their meaning for a project with one criterion) gets, for a project with several, the settings of the first criterion and the results of the last one that is on (the score colours, the sky dome and the run summary's top-level carving), while a settings save and a test surface upload or removal through the inputs routes are refused with a 422 that asks which criterion they belong to (*Say which criterion these settings belong to.*, *Say which criterion these test surfaces belong to.*).

**Where a criterion's data lives**

- `project.json` lists the criteria: id, name, colour, whether it is bypassed (the field the app's on switch sets, the other way round), the names of its test surface files and its own settings. A criterion's id is `"1"`, `"2"`, and so on, assigned by the service, kept when the criteria are reordered and never used again in the project. Run folders and joined test surface files are named by id.
- `config.yaml` is generated from `project.json` at every change: the settings shared by the whole chain at the top, then the criteria that are on under `criteria:`. A bypassed criterion is left out, and so is left out of every run. A project folder is still valid input for `usc run -c <folder>/config.yaml`. Change settings in the app, because the next save writes the file again.
- `inputs/test_surfaces/` stores each test surface file once, named as uploaded. `inputs/joined/test_surfaces_<id>.ply` is the joined file the engine reads for criterion `<id>`.
- `run/criteria/<id>/preprocessing` and `run/criteria/<id>/thresholding` hold each criterion's results, with `run/criteria/chain.json` listing them in order. Exporting and massing stay in `run/exporting` and `run/massing` and are built once, from the last criterion that is on.

**Test surface files**

- An upload with the content of a stored file reuses that file. An upload with the name of a stored file and other content replaces it in every criterion that uses it, and puts out of date only those criteria. A file that no criterion uses any more goes to the recycle bin, as a removed project does; on a drive without one (a network share, a USB stick) it is deleted.
- A criterion uses a stored file of another criterion through the *use* route, which adds no copy. Removing a file from one criterion leaves it in the others.
- A new criterion has no test surfaces. A run refuses to start while no criterion is on (the app's Run analysis waits with "Turn on a criterion to run") or while one that is on protects nothing (*Add test surfaces to <name>.*). The checks a run starts with look at the criteria that are on only: the settings of each must validate, and the weather file is needed when one of them reads it. A bypassed criterion needs nothing. A criterion is named after its mode as the app shows it ("Solar time-based", "Daylight", ...) until it is renamed; one that gets its first file and has not been renamed is named "<mode> on <file name>", for example "Daylight on roofs". A project from an earlier version names its criterion 1 the same way.
- The Test surfaces box of a criterion adds, uses and removes its files through the criterion's routes (`POST`, `PUT` and `DELETE` on `/criteria/{id}/test-surfaces`). The inputs routes for test surfaces go to the only criterion; with several they are refused with a 422.

**Settings routes**

- `PUT /api/projects/<name>/shared-settings` saves the settings the criteria share (voxel size, north and the like) from a body `{values}`, with no mode; the values are merged into the stored shared settings. A key that is a criterion's own setting is refused with a 422 that names it, and so is a value that makes any criterion that is on invalid or a grid over the budget. Nothing is stored then. The reply holds the shared settings as stored and the `grid_plan`.
- `GET /api/projects/<name>/criteria/<id>/settings` answers `{criterion_id, settings}`: the criterion's settings with the shared ones, without the paths and device the service owns.
- `GET /api/projects/<name>/sun-path` takes an optional `criterion` (default: the first criterion that is on, the first one when none is).
- A 422 that comes from one criterion's settings (a refused run start, a rejected `PATCH` of a criterion) carries `criterion`, its id, next to `field_errors`.
- The project list's `mode` is the mode of the first criterion that is on. `criteria` in the run summary gain `volume_removed_m3`, the volume a criterion removed (null without results).

**What goes out of date**

| Change | Out of date |
|---|---|
| Maximum volume, context, terrain, weather file or a shared setting | Everything |
| A criterion's test surfaces (a file added, removed or replaced) | Its preprocessing, then the thresholding of every criterion that is on from it on |
| A criterion's own mode settings | The same |
| A criterion's carving rule (carve amount, threshold, smoothing, `carve_above`, slope limit) | Its thresholding, then the thresholding of every criterion after it |
| Order, switching a criterion off or on, or deleting one | The thresholding of every criterion that is on from the first changed position on |

Exporting and massing are compared with the settings of the last criterion that is on and with its thresholding. When the last criterion is deleted, the one before it becomes the last, and exporting and massing are out of date.

`GET /api/projects/<name>/stage-status` answers with `stages`, as before (preprocessing and thresholding sum up the criteria: missing when any is missing, else out of date when any is, else current), and `criteria`, the state of both analysis stages of each criterion that is on, in chain order. The project detail repeats it as `criterion_status`.

**Running**

A run traces the rays only of the criteria whose preprocessing is missing or out of date, then thresholds the chain from the first traced criterion on, or from an earlier criterion whose thresholding is out of date. When no criterion needs tracing and a thresholding is out of date, it thresholds the criteria that are on from the first out-of-date one on; the ones before it keep their results. A criterion that only needs thresholding again does not trace. `StartRunReply.criterion_stages` says what the run does for each criterion that is on, for example `{"1": [], "2": ["preprocessing", "thresholding"]}` after a second criterion was added to a finished project. The service sends the engine `trace_criteria` for this, and `threshold_from_criterion` when thresholding starts at another criterion than the first traced one, or than the first one when nothing is traced (see [Engine requests](api/engine-requests.md)). The progress and issue events of a run carry `criterion`, the id of the criterion the stage belongs to, or null for exporting and massing.

**Results**

- `GET /api/projects/<name>/run/summary` keeps its fields (`carving` describes the last criterion that is on) and adds `criteria`, one entry per criterion that is on with its id, name, colour, mode, carving numbers, voxels at start and kept volume, and `chain`, the volume each criterion kept and the share of the maximum volume the last one kept. A criterion without results is listed with empty numbers, and `chain` is null until every criterion has results.
- `.../run/score-points` and `.../run/sky-patches` take an optional `criterion` and default to the last criterion that is on.
- `.../run/carved-by-criterion` serves which criterion removed each voxel: a 4-byte little-endian header length, a JSON header (`origin`, `shape`, `voxel_size`, `criterion_ids`, padded with spaces to a multiple of 4 bytes), then one byte per voxel of the grid in C order, 0 for a voxel the last criterion kept or one that is empty, and *k* for a voxel removed by the *k*-th criterion that is on. It answers 404 until every criterion that is on has thresholding results on the same grid.
- The run report has a Criteria section with one row per criterion (see [Criteria](criteria.md#output-folders)).

**Earlier projects**

A project made with an earlier version opens as a chain of one criterion, and its results stay current. Opening it moves `inputs/joined/test_surfaces.ply` to `test_surfaces_1.ply`, `run/preprocessing` and `run/thresholding` to `run/criteria/1/`, rewrites the manifests of thresholding, exporting and massing that name a moved folder, writes `criteria/chain.json`, and lists its test surface files under criterion 1, so what they protect does not change. Run ids are not touched. The migration runs once, undoes every step when one fails and leaves the project as it was (the project then opens as before and the error goes to the service's log); `project.json` is written last, and its `criteria` tell that the project is migrated.

A project carved further with an earlier version (its `carving_chain` is set) opens the same way: a chain of one criterion whose maximum volume is the last envelope. `carving_chain` and `inputs/earlier_max_volumes/` stay as they are, as a record. The service's `carve-further` route, which made the built envelope the maximum volume of a project with one criterion, stays for other clients and is refused on a project with several (409, "Carve further works on a project with one criterion.", before anything changes); the app no longer offers it. A project whose test surface files were removed after its last run opens with criterion 1 holding none: its results show as out of date, as they did before, and a run asks for test surfaces.

## Entering values

A number with a range is entered with a slider and a number field side by side. The number field takes any value the engine accepts; the slider covers the range people normally use (for example 0.1 to 5 m for the voxel size). The balance temperature and the analysis period are strips with two handles instead, each handle with its exact value in a bubble over it, always shown; where the two handles are close, their bubbles move apart so they never overlap.

- **Balance temperature** (Solar usefulness) is a strip from 10 to 30 °C, with a tick a degree and a label every 5 °C, and two handles, the two ends of the dead band, with the band between them filled. The lower end (named "Counts below" for a screen reader) is where sun starts to count: in hours colder than this. The upper end ("Too warm above") is where, with harm counted, hours warmer than this count against the sun. Each end moves on its own and cannot pass the other; the app sends the engine the middle as `balance_temperature` and half the width as `balance_offset`, the dead band the engine reads on both sides of the balance temperature. A press on the strip moves the nearer handle there, to the step of 0.5 °C; the arrow keys move a handle by 0.5 °C, Page Up and Page Down by 2 °C, Home and End to the ends of the strip. A value outside 10 to 30 °C (from a hand-edited `config.yaml`) pins its handle at the end of the strip, and its bubble shows the value. The lower handle comes first for Tab, as on the strip; where the two handles lie on one spot, the direction picks the end: a drag to the left or an arrow key toward the lower end moves the lower one, and to the right the upper one, the focus moving to that end's handle. Home or End on one spot take the lower or the upper end to the end of the strip.
- **Sample spacing** on the test surfaces is not set in the browser: the engine samples them at half the voxel size, and a quiet line under Voxel size says so ("Test surfaces sampled every 0.5 m"). On the District example (Solar usefulness, 1 m voxels) half the voxel size differs from a 0.25 m reference in 0.9 % of the kept voxels, against 2.0 % for a spacing of 1 m, at about twice the analysis time (13.9 s against 7.1 s; 0.25 m takes 37 s). A project that stored a sample spacing (an earlier version let you set one) drops it when it opens, so its analysis shows as out of date once if that spacing was not half its voxel size. An analysis made before this change without a stored spacing sampled every 1 m, the old default, so it too shows as out of date once unless its voxel size is 2 m. In `config.yaml`, on the command line and in Grasshopper `grid_step` can still be set.
- **Units.** Every number shows its unit beside the value: counts say what they count (Smoothing passes in passes, Rays per batch in rays, Cut voxels in voxels, Drop mesh fragments in faces), Sun positions per hour reads "12 per hour (every 5 minutes)", and only the Bliss constant, a number without a unit, has none.
- **Drop pieces smaller than** is shown and typed in m³, though the engine stores `min_voxels`, a count of voxels: the form multiplies the count by the volume of a voxel at the voxel size it shows (300 voxels at 0.5 m read 37.5 m³) and turns a volume typed back into whole voxels, at least one. The stored count does not change when the voxel size does, so the volume shown follows the voxel size.
- **Grid margin** (`margin_frac`) is hidden for now; the engine's default (1 % of the longest side) applies, or a value already in `config.yaml`.
- **Ray length** (`ray_length`) has no field: rays stop where they leave the voxel grid, so the engine's default of 3000 m reaches across any grid at no cost. A value already in a project's `config.yaml` is kept and applies.
- **Edge strip with less weight** (`edge_taper`) is shown in Night cooling only, under **More mode settings**: sample points closer than this to the edge of a test surface count less, from 0 at the edge to full at this distance, so a cooling street or courtyard does not clear the mass right beside it. 0 is off. The engine reads it in every weighted mode: a value already in a project's `config.yaml` is kept when the project opens, in any mode, and dropped when you choose a mode that does not show it.
- **Analysis period** is one control with two strips.
    - The year strip has twelve months and two handles for the start and the end date, each with its date in a bubble ("21 Dec"). A period across the new year (start after end, as in October to April) is drawn wrapped.
    - The hour strip has two handles for the first and the last hour, each with its hour in a bubble ("10 h"). The last hour is inclusive, so 10 to 14 h samples 10:00 through 14:00. A range across midnight is drawn wrapped.
    - A drag is sent once, when you let go; a key or a preset is sent at once. A period not set yet says "Not set yet" under the strips.
    - Presets set the dates and keep the hours: 21 December, 21 June, Heating season and Whole year. The heating season follows the hemisphere of the weather file's latitude: 1 April to 31 October south of the Tropic of Capricorn (23.44 degrees), 1 October to 30 April elsewhere, within the tropics and without a weather file.
    - In Solar usefulness a fifth preset, **Cold period from the weather file**, sets the dates of the site's cold period: the longest run of days whose mean temperature over the month around them is below the balance temperature minus the dead band. Its tooltip, shown while the pointer is over the button or the keyboard focus is on it (Escape closes it), says what it found ("Cold period of the weather file, where the mean of the month around each day is below 13 °C: 30 Sep to 15 May."), or why it cannot be used yet: no weather file, no cold period in it, or a failure to read it. A screen reader reads the same text as the button's description. It needs the weather file. Changing the balance temperature later updates that text but not the dates already set; press the preset again to use the new ones. Solar usefulness already counts only the hours colder than that threshold, so the cold period mostly leaves out cold hours outside the heating season, such as cool summer mornings; it changes more when the experimental "include harm" option is on, whose warm hours depend on the period.
    - When you add or replace the weather file (not when a project opens with one), the Criteria step shows one notice about the new file, with two buttons; either button closes it, and a later weather file replaces it. In Solar usefulness it offers the cold period of the new file when its dates differ from the period's, keeping the hours ("The new weather file (Brisbane, AUS) has its cold period from 3 May to 20 Sep; the analysis period is 30 Sep to 15 May.", **Use the cold period** or **Keep**); it waits for the cold period and shows nothing when the file has none. In Solar time-based and Solar energy it appears only when the new file is in the other hemisphere from the one before (a project without one counts as northern, as the starting values are), and offers the same dates six months on: the month plus six, the day held to the month's length, the last day of a month staying the last day (30 Apr gives 31 Oct). For example "The new weather file (Brisbane, AUS) is in the southern hemisphere: winter there is June to August. Shift the analysis period by six months, to 21 Jun, 10 to 14 h?", **Shift by six months** or **Keep**. A period that covers the whole year covers the same days six months on, so it gets no offer. A file within the tropics, or one whose latitude cannot be read, brings no offer, and the hemisphere of the file before it still counts for the next one. The offer is saved as any change of the period is; while a run is in progress the buttons are disabled, as the settings are. Either button moves the focus to the analysis period's start date. Once the period changes, by the button or by hand, the notice is gone and stays gone if the period is set back; choosing a mode without an analysis period (Angle rule, Daylight, Night cooling) dismisses it too. Screen readers announce the notice as it appears.
    - Each handle takes the keyboard: the arrow keys move it by one day or one hour, Page Up and Page Down by a month or six hours, Home and End to the first or last day or hour.
    - When the hours cross midnight on a single date, the end date moves to the next day ("21 to 22 Dec, 22 to 2 h"). A period stored earlier with one date and hours across midnight (an older save or a hand-edited `config.yaml`) is what the engine runs on every day of the year: the year strip is filled whole and a note under the strips says so: "Every day, 22 to 2 h: the hours cross midnight on one date, which the engine runs on every day of the year. The next change makes it one night." The period is not written until you change it.

## Running: two phases

A run has two phases, so that the part that takes time happens once and the part you adjust is quick.

1. **Run analysis** runs the sun analysis and the carving (the preprocessing and thresholding stages). The 3D view then shows the kept voxels coloured by score; the carved voxels are a separate layer, hidden at first, which the Layers menu shows. The progress shows the stages, the ray batches and the elapsed time, with a Cancel button. With several criteria it does this for the criteria that changed (see [Runs](#runs)).
2. **Build envelope** and **Build massing** (in Envelope and massing) run on the voxel result you settled on in the Criteria step: the exporting stage and the massing stage. **Build envelope and massing**, pinned in Criteria, builds both.

Between the two you change the threshold. The cutoff line on the histogram can be dragged in every rule, or moved with the keys of its handle (arrow keys a hundredth of the range, Page Up and Page Down a tenth, Home and End to the ends). While it moves, a line under the histogram previews the share of the volume the cut keeps, worked out in the browser from the voxel scores of the last carving, before the slope limit (the run gives the exact numbers); in the weighted modes it also gives the carve amount the cut stands for, which the slider shows. Letting go sets that carve amount (under Automatic it switches the rule to Manual, and the step says so), or in Solar time-based the cutoff itself, whose slider ends at the highest score the cutoff is compared with (after *Remove everything above a cut*), past which a cutoff carves nothing more. Choosing Manual starts from the amount the cut on the histogram carves. With several criteria the line, the slider and the update belong to the selected criterion (see [Several criteria](#several-criteria)). Moving the slider or typing a value moves the line too. **Update carving** applies the change, which thresholds the scores again without repeating the analysis; until then the line stays where it was set, drawn in the accent colour as a preview. Switching on **Update when I change the threshold** applies each change as you let go of the line or the slider or leave the field. The choice is remembered per project in the browser.

The interface keeps track of what each result was built from. When you change a setting or an input after a result exists, that result stays visible, dimmed and labelled out of date, and the step that needs a run says so. While a dimmed result is shown in the 3D view, an **Out of date** stamp sits at the top of the view (**Updating** while a run replaces it); it has nothing to click and goes once the results are current. Running again replaces it. A run only starts the stages whose results are missing or out of date.

While the mode or the analysis settings in the form differ from the stored ones, the carving is locked, because a build would have to run the analysis first. The two builds then wait with a message to run the analysis again, and a mesh format change is stored and written by the next build of each part.

## The 3D view

The view has a compass, an axis gizmo (the three lettered axes, drawn straight on the viewport) and a legend for the coloured layers. The **Layers** menu switches the maximum volume, the test surfaces, the existing surroundings (neutral grey massing) and the terrain (a ground surface), both shown in every step, the kept and carved voxels (with several criteria also the carved voxels by criterion), the sun path, the sky dome, the carved envelope and the building massing. Buttons frame the whole model, show the top view and switch between a light and a dark viewport (remembered in the browser).

The ground aid button cycles through three states: off, a ground grid with a scale bar, and a compass ring on the ground around the scene (ticks every 10 degrees, the letters N, E, S and W every 90 degrees, rotated by the north direction). The button names the aid it switches to, and the choice is remembered in the browser. The compass ring, the sun path and the sky dome are centred on, and sized to, everything loaded (the maximum volume and the test surfaces together). Framing the model leaves out the surroundings and the terrain, which can reach far beyond the site.

## Simulate

The switch **Design | Simulate** in the header, next to the project name, opens a workspace beside the pipeline that checks how much sun, solar energy or sky reaches the test surfaces once the maximum volume stands and once the carved envelope or the massing stands. [Simulate](simulate.md) explains the metrics and what they block. Simulate changes no criterion, setting or pipeline step, and runs nothing until you press **Run**.

- Simulate hides the five steps and gives the 3D view the whole window. Switching back to Design returns to the step you left, with its folds and scroll position kept.
- The **Studies** panel floats over the top left of the view and collapses to an icon. Each row is a study: a colour swatch, its name and a line (its test surface files, **Out of date**, **Not run yet** or why it cannot run). Pressing a row puts that study on the view; only one is shown at a time. Its settings button opens a popover with the name, the metric, the analysis period, **More settings**, the test surface files and **Delete study**. Changes are saved at once.
- **Add study** lists the criteria as **Like *name*** (the metric of its mode, its period, mode settings and files, copied) and the metrics (a metric that needs a weather file is greyed without one). **Run** runs every study that can run, on the maximum volume and on the envelope and the massing when they are built.
- One job runs at a time. While a Design run is going Run says "A Design run is in progress", and while a simulation is going Design's run buttons say so.
- At the top centre, **Max volume | Envelope | Massing** chooses the geometry the values are shown on (the last two wait until Design has built them), and **Change** colours each point by its change from the maximum volume.
- The legend along the bottom colours the values by the study's unit (the default) or by **% of no-build** (each point's share of its value with nothing built on the plot, the surroundings and terrain still blocking; 0 to 100 % for every geometry). Two marks set the low and high end of the colours (drag them, or use the arrow keys; Delete puts one back): the palette runs between them and values beyond an end take its colour. By value the low end is the study's **target**, and both ends are saved with the study. The palettes are fixed: Magma by value, Viridis by share and for Change. The result card in the bottom right corner gives what the geometry keeps of the no-build value, the mean, the lowest tenth and the share of points at the target, with the maximum volume's value in brackets. When no study is selected the first one with a result is.
- The **Sun** panel under the studies panel (it needs the weather file) draws the year's sun path with a day while it is open, and shows one of two views: the shadows at a moment (a day and a time, each on a strip with one handle) or the hours in shade over a period (the analysis period's control), in viridis or grey, a quick count on the view (a Sun hours study is the precise one). Its clock, at the end, reads the times in local standard, solar or daylight saving time. The **Show** switch beside the studies panel's title hides the selected study from the view.
- The **Sky dome** layer shows the selected study's sky patches, each coloured by the value it carried in the study's last run (none for sun hours); Design's dome is not shown in Simulate.
- A result whose inputs changed stays on the view with the **Out of date** stamp, its colours kept but muted part of the way to grey (other out-of-date layers fade to a grey). Reopening the project shows the last results.

## Inspect

The switch **Design | Simulate | Inspect** in the header also opens Inspect, a workspace beside the pipeline that shows which way the test surfaces face and summarises the input mesh files. [Inspect](inspect.md) explains it in full. It runs no engine step, and only **Save** and **Restore original** change a file.

- Inspect hides the five steps and gives the 3D view the whole window. Switching back returns to the step you left.
- The **Files** panel floats over the top left of the view and collapses to an icon. It lists the maximum volume, test surface, surroundings and terrain files, each with its triangle count and area; pressing a row frames the file, draws the other test surface files faint and opens its bounds and (for test surfaces) surface count. A file the app cannot read is listed with its problem.
- Test surfaces are drawn two-sided: the side the normal points to in the test surface colour, the back side in orange, so a surface the wrong way round shows orange from outside. **Face normals** draws one normal per surface.
- On a test surface file, **Flip mode** turns the whole surface under a click (a second click turns it back) and **Flip all** turns every surface. Turns are staged and shown at once; **Save** writes the file once in its own format, **Discard** drops the turns, and **Restore original** puts back the file as it was before the first save. A file that is closed as a whole cannot be flipped.
- Save and Restore original act like an upload: the criteria and studies that list the file go out of date. They wait while a run of the project is going. If the file was replaced in the project folder since Inspect read it, they write nothing and say so, and its staged turns are dropped.
- Leaving Inspect with turns not saved, or while a save is under way, asks Save, Discard or Stay. A save under way is said in the dialog, and if it is refused the dialog stays open with the reason.

## Where projects are kept

Each project is a folder in the projects folder:

```
<projects folder>/<project name>/
├── inputs/        The files you added (max_volume/, test_surfaces/, context/, terrain/, weather.epw)
│                  and the joined meshes the engine reads (joined/, one test_surfaces_<id>.ply per criterion
│                  and one study_surfaces_<id>.ply per study that lists files), and originals/test_surfaces/,
│                  the test surface files as they were before Inspect first saved a flip of them
├── config.yaml    The settings, a normal USC chain file (shared settings, then the criteria that are on)
├── project.json   The project's record: the files you added with their triangle counts, size, time and digest,
│                  the notices of files replaced in the folder, the input revision,
│                  the example it came from (if any), the criteria with their own settings and test surface files,
│                  the studies of Simulate, and one record per completed stage (with the settings that stage ran with)
├── run/           The engine's output: criteria/<id>/preprocessing and thresholding, criteria/chain.json,
│                  exporting/ and massing/
└── simulate/      The results of the studies, one folder per study (see Simulate)
```

`config.yaml` works outside the interface: its paths are relative to the project folder, so `usc run -c <project folder>/config.yaml` runs the same analysis from the command line (see [Criteria in a project](#criteria-in-a-project)). Thresholding also writes `scores_compared_with_cutoff.npy` in its folder (the values the cutoff is applied to, which the histogram draws). To delete a project, use Delete in its menu (see [Managing a project](#managing-a-project)), or delete its folder in the file manager.

### Replacing a file in the project folder

You can save a new version of an input file over the old one in `inputs/` (an export from Rhino saved over `inputs/test_surfaces/roofs.obj`, say), keeping its name. The app finds the change when the project is opened, when it asks for the stage status (after a save, a change of the inputs or a run, and whenever its window comes back to the front), when it lists the studies, and when a run or a simulation starts. A file that was added in the app is read again only when its size or modification time differs from what `project.json` recorded (`stored_files`); the same content saved again changes nothing.

A file whose content changed is built into the joined files that use it, in place of the old version:

- A test surface file: the joined files of the criteria and studies that list it. Those criteria are out of date, and the criteria after them have to carve again; the studies that list it are out of date.
- The maximum volume, the context or the terrain: the role's joined file. Every stage and every study is out of date.
- The weather file: every stage is out of date, and so are the studies whose metric reads it.

A notice over the steps (and at the top of the Studies panel in Simulate) names each changed file, until you press **OK**. The 3D view loads its meshes again. A joined file that comes out the same (a file saved again with the same surfaces) changes nothing and gives no notice; for the context and the terrain, whose orientation nothing reads, a face turned the other way is the same face. While a run of the project is going, the app waits for it to end before it looks.

A file of a project made before this check has no record. The first look builds its joined files and compares them with those the runs used, so a file replaced earlier is caught too. A weather file without a record is taken as it is.

A file the app cannot read (a broken export, or one still being copied or locked by another program) is not built in and is tried again at the next look; the project still opens, and a run says which file it is. A file deleted from the folder is listed as missing. A run is refused while a file it reads is missing (a test surface file of a criterion that is on, or a file of another role), and a simulation while a file the studies read is missing, until you put it back or remove it in the app. A file added to the folder by hand, under a new name, is not seen: add it in the app.

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
