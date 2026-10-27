# Changelog

All notable changes to Urban Solar Carver are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added (Inspect)

- **Inspect, a third workspace.** The header switch is now **Design | Simulate | Inspect**. Inspect shows which way every test
  surface faces and lets you turn the ones that face the wrong way, and it summarises each input mesh file. It runs no engine
  step and changes nothing until **Save** or **Restore original** is pressed. See [Inspect](docs/inspect.md).
- **Two-sided test surfaces and arrows.** In Inspect a test surface is drawn in the test surface colour on the side its normal
  points to and in orange on the back, so a surface the wrong way round shows orange from outside. **Arrows** draws one arrow
  per surface along its normal. The **Surface orientation** layer is in the Layers menu.
- **The Files panel.** The maximum volume, test surface, surroundings and terrain files, each with its triangle count and
  area. Selecting a file frames it, draws the other test surface files faint and opens its bounds (with a note for
  georeferenced coordinates), its closed bodies out of its bodies and, for a test surface file, its surfaces. A file that
  cannot be read is listed with its problem.
- **Flipping.** **Flip mode** turns the whole surface under a click (the triangles joined by shared edges, as the engine's
  loader reads the file; a single triangle would be turned back at the next load), **Flip all** turns every surface. A test
  surface file that is closed as a whole cannot be flipped, since the loader turns closed bodies outward. Turns are staged;
  **Save** writes the file once in its own format (OBJ at 10 decimals, PLY float64, GLB and STL float32), reads it back with
  the engine's loader and saves nothing if the turns or coordinates did not hold. OBJ groups, materials and texture
  coordinates and PLY colours are not kept in a saved file. **Discard** drops the turns. Leaving Inspect with turns not saved
  asks Save, Discard or Stay; turns staged on a file that changed meanwhile are dropped with a message.
- **Restore original.** Before the first save the file is kept in `inputs/originals/test_surfaces/`; Restore original puts it
  back byte for byte. An upload of a file with that name, removing the file, or replacing it by hand in the project folder
  drops the kept original.
- **Effects of a save.** Save and Restore original act like an upload: the joined files of the criteria and studies that list
  the file are built again and those criteria and studies go out of date; no "changed in the project folder" notice is given.
  Both are refused (409) while a run of the project is active.
- **Service.** `local_web_service/inspection.py` and the routes `GET /projects/{name}/inspect`,
  `GET /projects/{name}/inspect/test_surfaces/{file}/geometry`, `POST .../turn` and `POST .../restore`. A file is read once and
  kept until its size or modification time changes. No engine function is added.

### Fixed (input files replaced in the project folder)

- **A file saved over an input file in the project folder is now used.** Before, the engine went on reading the joined files
  built at upload, and the stages and studies built on the old file stayed current, so a rerun gave the old result. The
  service now records the size, modification time and content digest of each stored file in `project.json`, and compares the
  folder with them when a project opens, on each stage status read, on the studies list and when a run or a simulation
  starts. A changed file is built into the joined files that use it; the criteria, stages and studies built on the old one go
  out of date. A notice names the file until it is dismissed (`DELETE /api/projects/{name}/input-changes`); the stage status
  lists it under `input_changes`. A file missing from the folder is listed too and refuses a run or a simulation that reads it. The app asks
  for the stage status again when its window comes back to the front. A project made before the records is checked once
  against the joined files its runs used. See [Replacing a file in the project folder](docs/ui.md#replacing-a-file-in-the-project-folder).

### Added (Simulate)

- **Simulate, a workspace beside the pipeline.** A **Design | Simulate** switch in the header opens a workspace that shows
  how much sun, solar energy or sky reaches the test surfaces on meshes, before (the maximum volume) and after (the carved
  envelope and the massing, each clipped by the maximum volume). The context and terrain block in every geometry. It changes
  no criterion, setting or pipeline step and runs nothing until **Run** is pressed. See [Simulate](docs/simulate.md).
- **Studies.** A study is a metric, a period and test surface files, kept in `project.json` under `studies` apart from the
  criteria. The metrics are sun hours (h), solar energy and useful solar energy (kWh/m²), overcast sky component, cooling sky
  and sky view factor (%); the sky metrics are a percentage of an unobstructed horizontal surface and ground reflection is
  left out. **Add study** offers **Like *criterion*** shortcuts (the metric, period, mode settings and files are copied, no
  link is kept) and the plain metrics. The time basis (standard, daylight saving or solar time) is a setting of sun hours,
  chosen per study. A study can use a test surface file the project stores already and add files of its
  own; a stored file stays while a criterion or a study lists it.
- **Fixed choices.** One sun position per hour, Tregenza's 145 sky patches traced with the carving's jittered sub-rays at the
  project's rays per patch (the first criterion that is on), test points at the carving's spacing, at most 2 million points
  per study (the message names the spacing that fits), lowest sun altitude 5 degrees.
- **The view.** A Studies panel with a settings popover per study; a geometry switch (Max volume, Envelope, Massing) and a
  **Change** toggle that colours each point by its change from the maximum volume; a legend with a draggable target saved with
  the study (arrow keys move it, Delete clears it), points below it in a muted colour of their own; a result card with the
  mean, the lowest tenth and the share of points at the target, the maximum volume's value in brackets; the **Out of date**
  stamp.
- **Service.** Routes under `/projects/{name}/studies` (list with state, add from a metric or a criterion, update, delete,
  order, test surface files), `POST /projects/{name}/simulate` and `GET /projects/{name}/studies/{id}/values`. A simulation
  is a job of the run worker (stage `simulate`, outside the pipeline's stages), one job at a time with Design runs. A study
  is current, out of date (its settings, files, weather file, context, terrain, maximum volume or a geometry mesh changed),
  not run or refused. Results are in `<project>/simulate/<id>/` (`check_points.npz`, `check_values.npz`,
  `check_summary.json`; `refusal.json` for a refused study) and show again when the project is reopened.
- **Engine.** The engine request `check` runs one study (`solar_check.simulate_study`); the metrics and settings are in
  `check_settings.py`, the files without torch in `check_files.py`. The summary records fingerprints of its inputs, with the
  settings digest left without the weather file's path. An unreadable manifest of the envelope or the massing leaves that
  geometry out with the issue `geometry_manifest_unusable`.
- Not built yet: studies on other designs, snapshots, CSV export, side-by-side views, a command-line command and a
  Grasshopper component.

### Added (chained carvings, engine)

- **Criteria in sequence on one voxel grid.** A config with a `criteria:` list carves several criteria one after the
  other, each with its own mode, test surfaces, mode settings and carving rule, while the maximum volume, context,
  terrain, voxel size and the other fundamentals are set once at the top level. Each criterion traces its rays over
  the drawn maximum volume, so its scores equal those of an unchained run of its settings; its carving rule then
  decides only among the voxels the criterion before it kept, so `carve_fraction` is a share of what is left. No mesh
  is made between criteria. Exporting and massing build once, from the last criterion, and massing measures its floor
  plates against the drawn maximum volume and its footprint instead of the voxel staircase of an earlier envelope.
- `usc run -c chain.yaml` and `run_chain(chain, out_dir, produce, start_from, context)` run a chain into
  `<out>/criteria/<id>/preprocessing` and `<out>/criteria/<id>/thresholding`, then `<out>/exporting` and
  `<out>/massing`; `criteria/chain.json` lists the criteria, and the run report gets a Criteria section (voxels at
  start and kept by each). `usc validate -c chain.yaml` lists the criteria. The daemon runs a chain for a `run`
  request on a chain file.
- **`thresholding(..., after=...)`** and `usc thresholding --after <folder or manifest>` (`StageRequest.after` in the
  daemon): one step of a chain. The manifest records `after_manifest` and `after_run_id`, the diagnostics
  `voxels_at_start`; a criterion whose predecessor was re-run later is refused with `StageChainError`, a predecessor
  on another grid too, and an empty start gives the issue `nothing_left_to_carve`. Changing an earlier criterion
  needs only the thresholding of the later ones again, which takes seconds.
- `load_chain`, `ChainConfig`, `Criterion`, `is_chain_file` and `CRITERION_KEYS` in `chain_config.py`. Criterion ids
  are folder names (letters, digits, `_`, `-`; unique ignoring case; default: the position), and the weather file is
  shared but reaches only the criteria whose mode reads one. `load_config` refuses a chain file.
- Monte Carlo oracle: chained cases (daylight then benefit, time-based then daylight) in `tests/montecarlo.py`.
- The browser app shows the criteria of a project as a list (see Added (chained carvings, app) below). See
  [Chained carvings](docs/criteria.md).

### Added (chained carvings, service)

- **Criteria in projects.** A project of the local service (`usc ui`) holds an ordered list of criteria in
  `project.json` (id, name, colour, bypassed, test surface files, own settings); `config.yaml` is generated from it as a
  chain file, so a project folder runs with `usc run -c`. Criterion ids are `"1"`, `"2"`, ..., assigned by the
  service, stable when criteria are reordered, never reused in a project, and name the run folder
  (`run/criteria/<id>/`) and the joined test surface file (`inputs/joined/test_surfaces_<id>.ply`).
- **Test surfaces per criterion.** Files are stored once in `inputs/test_surfaces/`; an upload with the content of a
  stored file reuses it, an upload with a stored name and other content replaces it in every criterion that uses it,
  and a file no criterion uses is deleted. A run refuses to start while no criterion is on or while one that is on
  protects nothing.
- **Status and runs per criterion.** `stage-status` gains `criteria` (preprocessing and thresholding of each criterion
  that is on; the flat `stages` sums them up, exporting and massing follow the last criterion). A change to a
  criterion's test surfaces or mode settings puts out of date its preprocessing and the thresholding from it on, a
  change to its carving rule the thresholding from it on, and a shared setting everything. A run traces only the
  criteria whose rays changed: `StartRunReply.criterion_stages` says what it does for each criterion, and the engine
  request carries `trace_criteria` and `threshold_from_criterion` (new keys of `RunRequest`, backed by
  `run_chain(trace=, threshold_from=)`). Progress and issue events name their criterion.
- **Earlier projects open as a chain of one criterion.** The first opening moves `run/preprocessing` and
  `run/thresholding` to `run/criteria/1/`, joins the test surfaces as criterion 1's and rewrites the manifests that name
  the moved folders; results that were current stay current. A project carved further keeps its `carving_chain` and
  `inputs/earlier_max_volumes/` untouched. A step that fails is undone and the project opens as it was.
- **Results per criterion.** The run summary gains `criteria` (carving numbers, voxels at start and kept volume of each
  criterion) and `chain` (volume after each criterion, share of the maximum volume kept); `score-points` and
  `sky-patches` take a `criterion`; the new `run/carved-by-criterion` route says which criterion removed each voxel.
  The `carve-further` route is refused on a project with several criteria.
- **Routes** `GET /criterion-keys`, `POST|PATCH|DELETE /projects/{name}/criteria[/{id}]`, `.../duplicate`,
  `PUT .../criteria/order`, and `.../criteria/{id}/test-surfaces[/{file}]` (upload, use a stored file, remove);
  `PUT /config` and `GET /projects/{name}` take an optional `criterion`. The routes the current app uses keep their
  meaning for a project with one criterion.
- **Grasshopper: `after` input on USC_ThresholdStage** (the last input). Wiring the first criterion's `thr_result` into
  it makes the second criterion decide only among the voxels the first one kept (`RunRequest.after`,
  `run_pipeline(after=)`). A request with `after` and a chain file, or a start before thresholding, is refused. The
  `ping` reply lists the engine's `features` (`run_after`), and a definition that chains on an older engine reports
  that the engine must be restarted instead of running the criterion unchained.

### Added (chained carvings, app)

- **Criteria in the browser app.** The steps are now Inputs, Site and grid, Criteria, Envelope and massing, and Export.
  The Criteria step always shows the list of criteria, also with one: a row per criterion (colour swatch, name, mode
  symbol, and either its result, "70 % of the score carved, 813 m³ removed", or its state: Out of date, Updates from
  *name*, Running, Off, Add test surfaces, Not run yet) with a switch that is on by default (off: the chain skips the
  criterion), a menu (Rename, Duplicate, Delete; the only criterion cannot be deleted) and, from two criteria on,
  reordering by dragging or with the arrow keys; **Add criterion** under the list opens a short menu of the modes; and a
  line under the list gives the volume the chain kept and its share of the maximum volume. Switching the selected
  criterion off keeps it selected, and deleting a criterion leaves the switches of the others as they were. Earlier
  projects open as a chain of one criterion; a project carved further keeps its note on the maximum volume.
- **The criterion panel, folded.** The selected criterion's panel has four sections, Test surfaces, Mode, Settings and
  Carving rule, each with a one-line summary while it is closed. Test surfaces and Carving rule start open; a section
  with a problem opens, and **Go to** *setting* in a refused run opens the section of the setting. **Run analysis** and
  **Build envelope and massing** are pinned under the steps while the Criteria step is open, with the progress and the
  messages of the run under them; with several criteria a reason names the criterion it is about, and the warnings of
  the last run fold behind one line ("2 warnings").
- **Site and grid and the criterion panel.** The settings every criterion shares (north, voxel size, the surroundings
  switch, rays per batch, detailed statistics) are in Site and grid and are saved through the shared-settings route; the
  criterion's own settings, its mode and its carving rule are in its panel, split by the service's list of criterion
  keys. The test surfaces belong to the criterion (the **Test surfaces** box, with **Use a file from another
  criterion**), and no longer to the Inputs step.
- **Runs per criterion.** Run analysis traces only the criteria that changed. The progress names the criterion of each
  stage, and a run the service refuses for one criterion (a setting, or no test surfaces) selects that criterion's row
  and shows the message in the pinned bar. Moving a criterion's cutoff with **Update when I change the threshold** on
  carves again from that criterion on in one run, with no ray tracing; the later criteria read "Updates from *name*"
  until it ends. A carving change while another criterion's analysis is out of date is saved and waits for Run
  analysis.
- **3D view.** The layer **Carved voxels, by criterion** draws each carved voxel in the colour of the criterion that
  removed it, with a legend; the kept voxels, the sun path and the sky dome follow the selected criterion.
- **Test surfaces in the colour of their criterion.** The 3D view draws each criterion's test surfaces in its colour, all
  at full strength (they no longer fade when another criterion is selected), and the Layers menu has one check box
  and swatch per criterion under **Test surfaces**. A file several criteria use is drawn once.
- **Service and engine, for the app.** `PUT /projects/{name}/shared-settings` saves the shared settings; `GET
  /projects/{name}/criteria/{id}/settings` reads a criterion's settings; `sun-path` takes a `criterion`; the run
  summary's `criteria` gain `volume_removed_m3`; a refused run carries `criterion` in its 422. A run that starts at
  `thresholding` with `threshold_from_criterion` (`run_chain(start_from="thresholding", threshold_from=)`) thresholds
  from that criterion on and reads the earlier thresholding folders, which is how a changed cutoff reaches the later
  criteria without tracing. The run report of a chain with two or more criteria gets a **Chain** section (the volume
  after each criterion and its share of the maximum volume), a Rule and a Cutoff column in the Criteria table, and a
  total time that covers every criterion.

### Removed

- **Carve further** is no longer in the browser app (Export step). Adding a criterion does the same without voxelizing
  an envelope again. The service route `POST /projects/{name}/carve-further` stays for other clients.

### Fixed (massing)

- A module no longer fails the maximum-volume test because of a voxel column less than half inside the footprint.
  Along a wall the voxels can reach up to a voxel past the footprint (the envelope of an earlier carving, voxelized
  again after **Carve further**, does), and one such column, empty above the lowest floors, dropped the whole module.
  Allatini example after two carve-further steps: 715 of 9,872 columns lay wholly outside the drawn outlines.

### Added (sky sampling)

- **Rays per sky patch** (`rays_per_patch`: 1, 4, 9 or 16; default 4) in the weighted modes (irradiance, benefit,
  daylight, radiative_cooling). One ray per Tregenza patch centre leaves gaps 12° wide between the rays of a test
  point, so far from the test surfaces whole layers of voxels went unscored and the scores showed bands (Allatini
  example, daylight: 38 % of the voxels scored 0). Now each patch is traced as that many rays, one at a hashed place
  in each of its 2 × 2, 3 × 3 or 4 × 4 cells of equal solid angle, each with that share of the patch weight; the
  places depend only on the test point, the patch and the cell, so runs repeat exactly. The tracing kernels compute
  the directions themselves, so memory does not grow. Allatini (daylight, RTX 3060): voxels scoring 0 38 % to 6 %,
  keep or carve decisions that differ from 64 rays per patch 30 % to 6.4 %, preprocessing 1.15 s to 1.18 s; District
  example (527,000 test points): 12.3 s to 13.9 s. A patch a surface's plane cuts counts the part in front of it.
  `rays_per_patch: 1` gives the scores of earlier versions. In the app's Settings step (Detail fold), on
  USC_RaySettings in Grasshopper, and in the test point access evaluation. See
  [Sky patches and rays per patch](docs/modes.md#sky-patches-and-rays-per-patch-rays_per_patch).

### Changed (sky sampling)

- Sky-patch rays are ordered by patch, then by test point, so the GPU threads that run together trace one direction
  from neighbouring points and find their voxels in the cache: tracing the District example with one ray per patch
  takes 0.19 s instead of 0.7 s.
- The default of the weighted modes changes their scores: with 4 rays per patch a voxel's score is the weight it
  blocks over the whole patch area rather than at its centre. Set `rays_per_patch: 1` to compare with runs of
  earlier versions.

### Added (context geometry)

- **Context and terrain as optional inputs** (`context_path`, `terrain_path`): opaque meshes of what stays around or
  inside the site. Context (existing buildings, large trees) removes every voxel column of the maximum volume it
  overlaps; terrain removes only the voxels below the ground. In the ray-based modes, every ray from a test point
  that hits context or terrain is dropped before scoring, so no voxel is blamed for sun or sky that is lost anyway.
  `tilted_plane` loses the voxels only. A test surface lying on a context face is not blocked by it. The run report
  gives the voxels removed, the rays dropped and the test points with every ray blocked; the massing footprint
  leaves out the removed columns; an open context mesh gives a `context_not_closed` warning. See
  [Context and terrain](docs/modes.md#context-and-terrain).
- Context and ground are solid: the rule that keeps a facade's own building from counting as its obstruction treats
  everything inside the context and below the terrain as mass behind the facade, like the maximum volume.
- **Account for context blocking** (`context_blocks_rays`, default on; a switch in the app's Settings step, shown with
  surroundings or terrain): off, context and terrain still remove their voxels and count as solid, but drop no ray.
- Grasshopper: optional `context` and `terrain` inputs (Meshes or Breps) on USC_Preprocess and USC_RunPipeline, and
  `context_blocks_rays` on USC_RaySettings.
- Test points with every ray blocked by context or terrain (inside a context mass, below the terrain, or facing into
  their building) give a `test_points_blocked` warning with their count.
- **`benchmarks/context_sanity.py`**: checks the context path against independent references (trimesh point and ray
  queries, the CPU reference march) on synthetic typology scenes, and the properties the method promises (nothing lost
  at the same cutoff, a taller south neighbour keeps more only on the south side).

### Added (test point access evaluation)

- **`test_point_access_evaluation`** (Python API, `urbansolarcarver.access_evaluation`):
  for an occupancy grid, uncarved or carved, the weight of each test point's
  rays that reach no occupied voxel (`test_point_accessible_weight`) and of
  those that are blocked (`test_point_blocked_weight`). It traces the rays,
  weights, front-face and skin rules of preprocessing (sun rays in hours for
  `time-based`); for a carved envelope, pass the max volume as `max_volume`,
  which the skin rule reads. See [Carving](docs/api/carving.md).
- **`benchmarks/access_baseline.py`**: on the bundled examples, the access
  gained per m³ removed at 5, 10, 25 and 50 % of the max volume, with the
  default post-processing, as a baseline for scoring and thresholding
  changes.

### Added (publication)

- **The ReSBE 2026 paper is published** (Lecture Notes in Civil Engineering,
  vol. 905, pp. 600-607, https://doi.org/10.1007/978-3-032-34930-9_70).
  `CITATION.cff`, the README and the documentation home page cite it with its
  DOI, and the open-access PDF is in `docs/publications/` under its own
  licence, CC BY-NC-ND 4.0.

### Added (solar and daylight saving time)

- **`time_basis: standard | daylight_saving | solar`** (default `standard`):
  `time-based` can read the hours of its analysis period in daylight saving
  time (standard time plus one hour on every date) or in true solar time, in
  which 12:00 is solar noon, as solar-fence rules and the Japanese shadow
  regulation define them. `irradiance` and `benefit` accept `standard` only,
  as their hourly EPW records are in standard time; the modes without a
  period ignore it with a warning. In the browser UI it is "Time" under More
  sun settings, in Grasshopper the `time_basis` input of USC Analysis Period.
  The sun path drawn in the UI and the run report follow it. See
  [Carving modes](docs/modes.md#time-basis-standard-daylight-saving-or-solar-time-time_basis).

### Added (browser UI)

- **Launchers for the browser interface:** `start-urbansolarcarver.bat`
  (Windows, double-click) and `start-urbansolarcarver.sh` (Linux, macOS) in
  the repository. On a fresh clone they install with `setup_env.py`, then
  start `usc ui`; they find `.venv` or `~/.usc-venv`, or the environment named
  by `USC_VENV`, and pass their arguments on to `usc ui`.

- **`usc ui` opens a browser interface** served from this machine
  (`--port`, `--projects-folder`, `--no-browser`, `--device`). It is an
  optional extra (`ui`: fastapi, uvicorn, python-multipart, websockets) that
  `setup_env.py` installs unless `--no-ui` is given; without it the other
  commands work as before and `usc ui` prints the install command. A start
  screen (new project, open a project, three packaged examples) leads to six
  steps: Inputs, Mode, Settings, Carving, Envelope and massing, Export, with
  a 3D view (compass, ground grid, scale bar, axes, legend, layers menu, light
  or dark viewport). A run has two phases: Run analysis (sun analysis and
  carving), then, after adjusting the threshold against the score histogram
  (optionally updating as the slider moves), Build envelope and massing.
  Results that no longer match the settings stay visible, dimmed. See
  [Browser UI](docs/ui.md).
- **`urbansolarcarver.local_web_service`**, the service behind it, and
  `app/`, the front-end source (React and three.js); the built front-end is
  committed in `ui_static/` and a test compares its `build_info.json` with the
  sources. The service listens on `127.0.0.1`, checks the `Host` header and
  needs a per-launch token on every API call. The GPU kernels are compiled in
  the background at launch; without a CUDA-enabled GPU the engine runs on the
  CPU.
- **Projects are folders** under the projects folder
  (`~/UrbanSolarCarver/projects` by default) with `inputs/`, a `config.yaml`
  that `usc run -c` loads, `project.json` (one record per completed stage) and
  `run/`.
- **Thresholding writes `scores_compared_with_cutoff.npy`**, the values the
  cutoff is applied to (float32, the voxel grid's shape), and records its path
  in the thresholding manifest (`scores_compared_with_cutoff_path`, `None` in
  manifests from earlier versions). The browser UI draws its histogram from it.

### Added (browser UI, round 2)

- **Projects folder.** The start screen shows the projects folder with
  **Change folder**, which opens the operating system's folder picker on
  this computer (the browser never sends a path). The folder is remembered
  in `~/.urbansolarcarver/ui.json` and used at the next launch;
  `--projects-folder` wins for that launch. Change folder is offered on the
  start screen only, with no run active. If the picker cannot open, the
  start screen names `usc ui --projects-folder <folder>`.
- **A menu for each project**, in the project list and in the top bar:
  Open folder (also during a run), Rename, Delete (asks for the project name
  to be typed) and, for projects made from an example, Reset to the example.
  Rename, delete and reset wait while the project's run is active. Delete
  and reset send the project folder to the recycle bin or trash with
  `send2trash` (new in the `ui` extra), only for that one project folder, and
  refuse a folder that is not a direct child of the projects folder, has no
  matching `project.json`, or is or holds a link. On Windows they also refuse
  a folder that is not on a fixed disk of this computer; Windows may delete a
  folder larger than the recycle bin's size limit for good, which the app
  cannot check.
- **Try an example opens the project made from that example** if there is
  one, and makes it only the first time. `project.json` records the example
  a project came from.
- **Sliders** beside the number field of every setting with a range, and the
  balance temperature as one track from 10 to 30 degrees C with two handles
  (the balance temperature and, below it, the dead band).
- **The analysis period is one control**: a year strip and an hour strip with
  two handles each, presets that set the dates and keep the hours (21
  December, 21 June, Heating season, Whole year), the value of each handle
  in a bubble over it, and keyboard steps. When the hours cross midnight on a
  single date, the end date moves to the next day.
- **Envelope and massing is two parts built on their own**: Build envelope
  with the envelope settings and the envelope volume, and Build massing with
  the massing settings and results, each with its own out-of-date mark.
  Carving's Build envelope and massing still builds both.
- **A ground aid button** in the 3D view cycles off, ground grid and compass
  ring. The compass ring, the sun path and the sky dome are sized to
  everything loaded, not to the maximum volume alone.

### Changed (browser UI)

- **Units beside every setting.** Rays per batch now says "rays",
  Smoothing passes "passes" (the range 0 to 6 moved to its help), and the
  choices of Sun positions per hour read "12 per hour (every 5 minutes)".
  **Drop pieces smaller than** is shown and typed in m³: the form converts
  the engine's `min_voxels` (a count of voxels, unchanged) with the voxel
  size it shows, and a typed volume back to whole voxels, at least one. The
  Bliss constant is a number without a unit and shows none.
- **An "Out of date" stamp on the 3D view** while a dimmed result is shown,
  so a dimmed result is not taken for a current one; it reads "Updating"
  while a run replaces it. It has nothing to click and goes once the results
  are current.
- **Carving rule: Manual or Automatic.** The weighted modes choose between
  Manual (the Carve amount slider) and Automatic (head/tail breaks); Score
  cutoff is no longer a rule of its own, as the line on the histogram sets
  the cut directly. Letting go of the line sets Manual's carve amount, and
  under Automatic switches to Manual. A cutoff a config holds (from the
  command line or the version before) shows as Manual, at the carve amount
  it stands for, until it is changed. The engine still takes a cutoff.
- **Carved voxels start hidden** in the Carving step; the Layers menu shows
  them.
- **Carving: the rule at the top, a cutoff line to drag, scores in units.**
  In the weighted modes the carving rule (Carve amount, Automatic split,
  Score cutoff) is a three-way choice at the top of the step, with the
  control of the rule under it and the histogram after that in every rule;
  the rule is no longer folded under a disabled Carve amount slider, and the
  other carving settings are folded after the histogram. Score cutoff has a
  slider and field in the unit of the scores, from the cutoff on the
  histogram when it is chosen (it started at 0, which carved everything);
  the slider ends at the highest score the cutoff is compared with (after
  "Remove everything above a cut"), past which a cutoff carves nothing more,
  and the score points of the service give it as `compared_score_max`.
  Carve amount, when chosen, starts from the amount the cut on the
  histogram carves. Automatic split and Score cutoff unset `carve_fraction`,
  which they do not read, so a run no longer warns "carve_fraction=... is
  unused".
  The cutoff line on the histogram can be dragged, or moved with the keys of
  its handle (a slider for screen readers), in every rule: while it moves, a
  line under the histogram previews the share of the volume the cut keeps,
  worked out in the browser from the voxel scores it already has (before the
  slope limit), and under Carve amount the amount it stands for. Letting go
  sets the carve amount, or the cutoff (Score cutoff, Shadow tolerated), or
  switches Automatic split to Score cutoff at that value, which the step
  says; it runs at once with "Update when I change the threshold", else on
  Update carving, and the line stays there as a preview (in the accent
  colour) until then. Moving the slider or typing a value moves the line
  too. The histogram axis, the slider ends, the 3D legend of the kept voxels
  and the sky dome legend give the units ("Solar energy a voxel blocks,
  kWh", "Overcast sky a voxel hides, m²", "Shade a voxel casts, m²·h",
  "Solar energy from each sky patch, kWh/m²") in place of "(relative)". The
  score points of the service name the mode of the analysis.
- **No Sample spacing field.** The engine samples the test surfaces at half
  the voxel size (see "Changed (sample spacing)"), and a quiet line under
  Voxel size says so: "Test surfaces sampled every 0.5 m". The lowering of
  the sample spacing to a smaller voxel size, and its note, are gone. A
  project that stored a `grid_step` drops it when it opens (the service
  leaves it out when it reads and writes `config.yaml`), so the computed
  spacing applies; its analysis shows as out of date once when the stored
  spacing was not half its voxel size. An analysis whose preprocessing
  manifest does not record the spacing, made without a stored `grid_step`,
  used the old 1 m default and is compared as such, so it is out of date
  once unless its voxel size is 2 m.
- **Edge strip with less weight (`edge_taper`) is shown in Night cooling
  only**, under More mode settings, with the help "Sample points closer than
  this to the edge of a test surface count less (from 0 at the edge to full
  at this distance), so a cooling street or courtyard does not clear the
  mass right beside it. 0 = off." The engine still reads it in every
  weighted mode; a stored value is kept when a project opens.
- **Grid margin (`margin_frac`) is hidden for now.** The engine and its
  default are unchanged.
- **Balance temperature is drawn as the analysis period's strips are:** a
  strip of 10 to 30 °C with a tick a degree, labelled every 5 °C, the dead
  band filled between the two handles, and over each handle a bubble with its
  exact value ("14.5 °C"), always shown and kept apart from the other. The
  "Dead band" label and the two number fields ("Counts below", "Too warm
  above") are gone; the handles keep those names for a screen reader. A value
  off the strip (a hand-edited config) pins its handle at the strip's end and
  its bubble says the value. Arrows move an end by 0.5 °C, Page Up and Page
  Down by 2 °C, Home and End to the strip's ends. The two strips share one drawing (`ScaleStrip.tsx`).
- **The cold period line under the presets is now the tooltip** of the
  "Cold period from the weather file" preset, shown on hover and keyboard
  focus as the mode tiles' tooltips are, closed with Escape, and never taking
  a click. It is still the button's description for a screen reader, and so
  are the reasons the preset cannot be used yet.
- **The period in words and its typed fields are removed** (day, month and
  hour of each end). Each handle of the analysis period shows its value in a
  bubble ("21 Dec", "10 h") instead. A period not set yet says so under the
  strips, and a period stored as one date with hours across midnight has a
  note there: "Every day, 22 to 2 h: the hours cross midnight on one date,
  which the engine runs on every day of the year. The next change makes it
  one night." The step summary still reads "Every day, 22 to 2 h".
- **Balance temperature is a range.** Its two handles are the two ends of
  the dead band, "Counts below" and "Too warm above", each moved on its own;
  the app sends the middle as `balance_temperature` and half the
  width as `balance_offset`. The earlier slider drew the band only below the
  balance temperature, although the engine reads it on both sides (cold hours
  below `balance_temperature - balance_offset`, warm hours above
  `balance_temperature + balance_offset`). The lower handle
  comes first for Tab; on one spot an arrow key toward the other end moves
  the focus to that end's handle, which steps, so both ends
  pinned at 10 or 30 °C step back; Home and End pick the lower and the upper
  end the same way. The cold period is asked for at the lower
  end rounded as the slider rounds it (13.2, not 13.200000000000001).
- **A new weather file asks about the analysis period.** Adding or replacing
  the weather file shows one notice in Settings with **Keep** beside the
  offer: in Solar usefulness the cold period of the new file, when its dates
  differ from the period's (the hours kept); in Solar time-based and Solar
  energy, when the new file is in the other hemisphere, the same dates six
  months on (30 Apr gives 31 Oct). Before, a new weather file left the period
  as it was without a word. The project detail and the reply to an input file
  change carry `weather_latitude`, read from the weather file's `LOCATION`
  line.
- **The heating season preset follows the hemisphere** of the weather file:
  1 April to 31 October south of the Tropic of Capricorn, 1 October to 30
  April elsewhere, within the tropics and without a weather file.
- The notice of a new weather file reads "The new weather file (Brisbane,
  AUS) has its cold period from 3 May to 20 Sep; the analysis period is 30
  Sep to 15 May." or "The new weather file (Brisbane, AUS) is in the southern
  hemisphere: ...", also for a file without a location. It offers no six
  month shift for a period that covers the whole year (the same days six
  months on), nor for a file within the tropics; a file whose latitude cannot
  be read keeps the hemisphere of the file before it. The notice sits in a
  live region kept on the page, either button moves the focus to the
  analysis period's start date, and once the period changes the notice does
  not come back when the period is set back.

### Changed (score units)

- **The scores of the weighted modes are in physical units.** Each blocked
  ray's patch weight is multiplied by the area its sample point stands for
  (`grid_step`², as time-based already did for its m²·h), so a score no
  longer changes four times when the sample spacing halves (it follows the
  voxel size now). `irradiance` and `benefit` scores are the solar energy,
  or heating-useful solar energy, a voxel keeps from the protected surfaces
  over the period, in kWh (counted on a surface facing each sky patch, with
  no reduction for the angle of incidence). `daylight` and
  `radiative_cooling` scores are the sky a voxel hides, in m² of fully
  hidden sky: their patch weights are each patch's share of the sky and sum
  to 1 (the `daylight` weights did not; they are now divided by their sum,
  about 4.2). `edge_taper` weights still multiply each ray, and simulated
  benefit weights still scale the hours before the sky matrix is summed.
- **A numeric `threshold` of a weighted mode now means something else**:
  it is compared with the new scores, in kWh or m². A value chosen on
  earlier scores must be chosen again (on 0.5 m sample spacing an earlier
  `irradiance` score is 4 times the new one; `daylight` about 17 times).
  `carve_fraction` and `headtail` do not depend on the scale and carve as
  before. No config in `configs/` sets a numeric threshold for these modes.
- `mode_registry.ModeSpec.score_unit` names the unit of the scores
  (`"kWh"`, `"m²"`, `"m²·h"`, `"rays"` for `tilted_plane`); `weight_unit`
  is the unit of the patch weights. The preprocessing manifest records
  `score_unit`; the score histograms, the thresholding diagnostics
  (`score_unit`) and the run report give it. The browser service treats a
  preprocessing run of a weighted mode without `score_unit` as out of date,
  so its next run rescores it; time-based and angle rule runs stay current.
  `GET /api/modes` and the score points header give `score_unit`.

### Fixed (carving rule)

- A config built from a mode's starting values
  (`build_config_from_mode_starting_values`: the browser UI, the engine
  requests) leaves out the starting `carve_fraction` of `radiative_cooling`
  when its `threshold` does not read it (`headtail`, a cutoff), so that
  config no longer warns about an unused `carve_fraction` it never set.
  `pydantic_schemas.threshold_reads_carve_fraction` tells, for a threshold
  in any spelling, whether it takes its value from `carve_fraction`.

### Changed (ray length)

- **`ray_length` defaults to 3000 m** (it was 300 m). The ray march clips
  each ray to the voxel grid's box, so a length beyond the grid costs
  nothing: on the District example (1 m voxels) the analysis took 12.4 s at
  3000 m against 12.6 s at 300 m in Daylight, and 13.9 s against 13.8 s in
  Solar energy, with the same scores to float rounding. Before, a grid
  wider than about 170 m (space diagonal over 300 m) could cut long rays
  short.
  The browser UI no longer shows the setting; a value stored in a project's
  `config.yaml` is kept and still applies.

### Changed (sample spacing)

- **`grid_step` is unset by default and then samples the test surfaces at
  half the voxel size** (it was 1.0 m whatever the voxel size). Measured on
  the District example (Solar usefulness, 1 m voxels): 1 m differs from a
  0.25 m reference in 2.0 % of the kept voxels (7.1 s analysis), 0.5 m in
  0.9 % (13.9 s); 0.25 m takes 37 s. An explicit value in YAML, on the
  command line or in Grasshopper still wins, and must still be at most
  `voxel_size`. The spacing is resolved in one place
  (`resolve_grid_step`, used by `PreprocessingSettings`), so a run is
  compared on the spacing it uses: an explicit 0.5 m with 1 m voxels and an
  unset one are the same run. The preprocessing manifest records the spacing
  used (`grid_step`, None in manifests written before), and the run report
  gives it. Default configs now sample twice as densely in each direction at
  the default voxel size, so a run takes about twice as long and its result
  can differ slightly from earlier runs.

### Changed (massing)

- **The building massing is written in the mesh format chosen.**
  `final_mesh_format` now applies to massing too: besides `plates.obj`, which
  it keeps writing in every run, massing writes `plates.ply`, `plates.stl` or
  `plates.glb` with the same plates (one mesh in PLY and STL, one named part
  per plate in GLB). Before, the massing was OBJ whatever the format, and the
  Export step of the browser interface offered only the OBJ. The massing
  manifest names the file as `export_mesh_path` (manifests without it still
  read), a format change marks massing out of date as well as the envelope,
  and a format change in the Export step rebuilds the parts that exist (the
  envelope, the massing or both). Export offers the massing file that was
  built under its own format, with a note when a format chosen while Carving
  was locked has not been built yet. A project
  whose massing was built before this change in a format other than OBJ shows
  its massing out of date.

- **Facades whose vertices lie within 1 cm of their chord are straight.**
  Footprints cut from meshes (the District example) carry vertices a few
  micrometres off a straight wall, which made most facades "curved", so their
  modules were drawn from voxel columns as staircases on the upper floors. A
  facade now counts as straight when its vertices lie within 1 cm of its
  chord, or within four float32 steps of the footprint's world coordinates
  when the mesh lies far from the origin, and never more than half a voxel; a
  real bend (6 degrees, 0.39 m over 7.7 m in the District example) stays a
  bend. In the District example, curved facades go from 60 to 3 and modules
  drawn from columns from 520 to 101, with the floor area nearly unchanged
  (74 022 to 74 002 m²).

- **Modules at corners that are not square end on one straight line.** Where
  two facades meet at a corner that is not square, the modules at the ends of
  their faces held voxel columns of the other face inside their rectangle and
  were drawn from their columns, as staircases on the upper floors (101
  modules in 30 of the 66 District buildings). Such a module is now its
  rectangle cut by a line between its columns and those of the other face:
  the bisector of the corner, which the nearest-facade rule draws, a line of
  the two facades' corner squares, or a bisector with a facade that meets one
  of them; failing those, the line across the widest gap between the
  columns, turned to a direction of the two facades or their bisector. A cut
  that leaves an angle under 30 degrees or a piece narrower than a voxel is
  not used: the module is cut without being grown first, or drawn from its
  columns. Plates also lose the spikes and cracks of no width that boolean
  operations left. In the District example modules drawn from columns go
  from 101 to 48 (9 of them on curved facades), plate edges inside the
  footprint at an angle to every facade from 187 to 110 m (49 m of them along
  a corner bisector), plate vertices under 45 degrees away from footprint
  corners from 30 to 8, and the floor area from 74 002 to 74 021 m².

- **Floors are built from square modules.** Each face of the footprint is
  now cut in depth too, into square modules of `min_plate_dimension`, and each
  module is built on a floor on its own. Before, a bay ran from the facade to
  the middle of the footprint, so in a perimeter block whose maximum volume
  covers the courtyard, a wing lost its upper floors as soon as the courtyard
  behind it in the same bay was carved lower (in the Perimeter block example
  the north and south wings stopped at 14 m; the floor area goes from 53 634 to
  65 446 m²). A module at the back of a row shallower than one module joins the
  one in front of it. A plate can now be as shallow as one module behind any
  facade, and such a strip is kept at any angle of the footprint to the voxel
  grid. `plates.json` keeps the key `bays` for the number of modules of a
  plate.

### Changed (massing refinements)

- **Rows of modules are laid from both ends of the building.** Along a
  straight facade, rows of `min_plate_dimension` start at both ends of the
  building's extent and what is left over widens the middle row (or the two
  middle rows). Before, rows were cut from the footprint's centroid, so an
  end row narrower than a module joined its neighbour into a row of 3 to 6 m;
  an end wing shallower than that row could vanish (a 100 x 92 m courtyard
  block with 3.5 m wings lost both 92 m wings above the courtyard: 600 m² on
  the floor from 17 to 20 m, 1116 m² now). The Perimeter block example goes
  from 65 446 to 64 642 m².
- **A floor no longer depends on the angle of the footprint to the voxel
  grid.** A column along a facade not aligned with the grid counts only for
  its share inside the footprint in a module's share outside the envelope
  and in the test for narrow parts (a 60 x 14 m slab sloping from 36 to
  15 m across its depth: 840, 739, 686 and 660 m² on the floor from 14 to
  17 m at 0, 17, 30 and 45 degrees, now 840 m² at each).
- **Columns just outside the footprint join the face next to them.** Such a
  column is assigned from the footprint point nearest to it, so the end of a
  slab whose front rows step back is cut on the same lines as the rest (a
  60 x 14 m slab set back 3 m on both long sides: a 480 m² strip, without the
  0.13 x 1 m notches at its ends).

### Fixed (massing)

- Plates of different modules no longer overlap where modules at a slanted
  end are drawn from their voxel columns, and where two module rectangles
  overlap the overlap belongs to one of them instead of to neither.
- Closing gaps narrower than a voxel no longer fails on a plate with a sharp
  corner, where GEOS's mitre offsets left a self-intersection.
- Georeferenced coordinates are kept in GLB files (the envelope and the
  massing): the vertices, which glTF stores as float32, are written near the
  origin and each node's translation, a double, carries the whole-metre
  offset. Before, coordinates near 4 200 000 m were rounded by up to 0.25 m.
  STL can only hold float32, so writing one far from the origin now reports a
  `float32_coordinates` issue. The engine's massing replies name the plates
  in `final_mesh_format` as `export_mesh_path`, next to `mesh_path`.
- A plate no longer loses whole modules when GEOS's inward mitre offset, used
  to close gaps narrower than a voxel, drops part of the shape (up to 240 m²
  of a parallelogram in a test sweep).

### Added (cold period)

- **Cold period from the weather file:** `urbansolarcarver.cold_period`
  finds the longest run of days whose 31-day running mean dry-bulb
  temperature is below a base temperature (for benefit mode
  `balance_temperature - balance_offset`), wrapping across the new year. The
  service answers it at `GET /api/projects/{name}/cold-period`, and in Solar
  usefulness the analysis period has a preset "Cold period from the weather
  file" that sets those dates and keeps the hours. A source from the 5R1C
  simulation is planned with simulated weights in the interface.

### Changed (browser UI, round 2)

- **Names in the interface.** The modes read Angle rule, Solar time-based
  (was Sun at set hours), Solar energy, Solar usefulness (was Solar heat when
  cold), Daylight and Night cooling, in a grid of three by two, with a
  coloured symbol and the name on each tile and the rest in the tooltip.
  Night cooling is marked experimental and assumes horizontal test surfaces.
  Bay width reads Grid module, and Allowed overhang reads Permitted volume
  exceedance. The engine names and settings are unchanged.
- **The axis gizmo has no background box and the ground has no north
  arrow**; north is shown by the compass overlay and the compass ring.
- **Rays per batch and Detailed statistics** moved to the end of More detail
  settings; the Computer group is gone.
- **Envelope volume is counted on the kept voxels** the envelope mesh was
  built from, after small pieces are dropped.
- **While Carving is locked, the builds wait** and a mesh format change is
  stored and written by the next envelope build; Export offers the envelope
  file that was built.

### Fixed (browser UI, round 2)

- **Test surfaces lost their panel boundaries** when the service joined the
  uploaded files (vertex normals were dropped), so panels sharing corners
  were welded. The joined file keeps the normals, and a project with an older
  joined file recovers when it is opened or a run starts.
- **Settings form:** errors of the whole config are said in the interface's
  words under the settings they name, a setting to fix is counted on the step
  that holds it, a mode change leaves no stale error and a refused mode
  change no longer leaves Carving unlocked, 0 is refused where the engine
  needs more, and the settings that default to automatic say what automatic
  means.
- **Mode tooltips** no longer stay open and swallow clicks.

### Changed (weather files)

- **One cached EPW reader.** The new `weather_file.read_weather_file`
  parses an EPW file once per path, modification time and size (a file
  replaced on disk is read again) and returns a `ParsedWeatherFile`. The
  sun vectors, the irradiance and benefit sky weights, the cold period, the
  simulated weights and the service's sun path read through it; before,
  each parsed the file again (0.2 s each), several times in one run. It
  hands out copies (a new Location, a new numpy array of the dry-bulb
  temperatures, a new Wea of the solar irradiance), because Ladybug's
  objects are mutable and one caller's change would otherwise reach every
  later caller; a copy costs under a millisecond and keeps the Ladybug
  types callers pass on to Ladybug. Results are bit for bit unchanged. The
  check of an uploaded weather file in the service still parses it
  directly: it reads a temporary file that is renamed right after, so a
  cache entry for it would never be read. `sun._load_epw` is removed.
  `pytest -n 8` now loads the hourly data of a weather file 75 times
  instead of 150 (each worker has its own cache; most of the rest are
  service tests, where each project has its own copy of the file, and 12
  are the reader's own tests). Measured on the same
  machine, main then this change: `-m "not sweep" -n 8` 75 s and 66 s,
  `-n 8` 103 s and 100 s, serially 318 s and 308 s; `-m "not slow" -n 8`
  stays at about 45 s. In the service, Run analysis after a change of
  `north_deg` on the `new_building` example went from 2.7-2.8 s to
  2.4-2.65 s on CUDA (one parse less); `multiple_buildings` (about 6 s)
  and the time-based example did not change measurably.

### Fixed (sky matrices)

- **Each sky matrix is computed in a temporary folder of its own.**
  ladybug_radiance writes the Wea file of every sky matrix to
  `<Ladybug weather folder>/sky_matrices/<city>.wea` and runs gendaymtx on
  it, one file per city for every process on the machine. Two irradiance
  or benefit computations for the same weather file at the same time (the
  browser service and a CLI or Grasshopper run, two checkouts testing)
  could read each other's file: two threads computing two analysis periods
  of the Golden EPW got wrong weights in 9 rounds of 10. The engine now
  sets the folder of each `SkyMatrix` to a new temporary folder and removes
  it afterwards; the weights are bit for bit the same. The per-process
  weather folder that `tests/conftest.py` set up for the tests is removed,
  since the engine no longer writes to that folder.

### Added (test markers)

- **`slow` and `gpu` pytest markers**, registered in `pyproject.toml`.
  `pytest -m "not slow"` leaves out the 79 tests that take seconds
  (end-to-end typology and Monte Carlo scenes, 5R1C simulations, tests
  that start a daemon process) and runs in about 40 s instead of 3.5
  minutes. Tests marked `gpu` are skipped by one rule in
  `tests/conftest.py` when torch sees no CUDA, replacing separate
  `skipif` lines.

### Changed (test runs)

- **Tests in parallel and in four tiers** ([Running the tests](docs/testing.md)).
  pytest-xdist joins the `dev` extra; `pytest -m "not slow" -n 8` takes
  about 45 s (157 s serially before), `pytest -m "not sweep" -n 8` before a
  commit about 80 s, and the whole suite with `-n 8` about 115 s (about 6
  minutes serially). The new `sweep` marker holds the 0.5 m floor-plate
  sweep and the Monte Carlo seeds. `--strict-markers` and `--durations=15`
  are on by default, and a run lists the tests outside `slow` that took
  over 1 s.
- **Each test process has its own Ladybug weather folder.** ladybug_radiance
  writes the input of every sky matrix to one fixed file per city, so two
  processes computing sky matrices at once read each other's file; under
  `-n 8` three to five benefit-weight and Monte Carlo tests failed at random.
- **Fewer repeated set-ups:** three full-year 5R1C simulations instead of
  nine, each packaged example made once per session and copied per test,
  one interpreter for the light-import checks instead of seven, and the
  ProjectWorkspace front-end tests on a fake clock (`npm test` 9 s instead
  of 16 s for the same 443 tests), split into a file on saves and runs and one on the 3D view.

### Changed (installation and clients)

- **`setup_env.py` asks the PyTorch wheel indexes which torch they offer**
  and installs from the index with the newest torch the driver can run.
  It sent CUDA 12.6 and 12.8 drivers to the cu124 index, whose newest
  torch is 2.6.0.
- **`urbansolarcarver.__version__`** reads the version from the installed
  metadata, so it is written once, in `pyproject.toml`; the CLI's
  hardcoded fallback is gone, and a test checks that `CITATION.cff` names
  the same version. An editable install keeps the version it was
  installed with: refresh it with `pip install -e . --no-deps`.
- **The `cuda` extra is removed.** It repeated the base `torch` dependency.
- **`daemon_client.py`**, standard library only, holds the daemon's key
  file, default host and port and `send_daemon_request`. The CLI's daemon
  commands use it instead of importing `daemon.py`, so `usc daemon status`
  and `--daemon` runs no longer load torch in the client.
- **One lazy-import mechanism.** The package's `__getattr__` imports
  `api` on first use of a name in `__all__`, and the CLI imports `api`
  inside its commands; the CLI's own `_api()` helper and the package's
  name table are gone. When torch is missing, the error now points to
  `setup_env.py` instead of a fixed CUDA 12.1 index.

### Changed (sky weights cache)

- **Sky-patch weights are cached in the `CarverSession`.** `get_weights`
  is keyed by every argument and by the contents of the EPW and
  simulated-weights files, so a file rewritten at the same path still
  gets new weights. A preprocessing run with unchanged weather settings
  (a Grasshopper re-solve after a geometry edit, a daemon or service
  rerun) skips the sky matrix: on the `multiple_buildings` example at 1 m
  voxels on CUDA, a repeated irradiance preprocessing run went from
  7.1 s to 5.1 s and a benefit run from 6.1 s to 5.3 s. Without a session
  nothing changes.

### Changed (compute device)

- **One rule chooses the compute device.** The new
  `compute_device.resolve_compute_device` replaces eight separate copies of
  "CUDA if available, else CPU" (the stages, `CarverSession`,
  `get_active_session`, the daemon, `scoring.get_weights`, the sky matrix,
  `voxelize_mesh` and `warmup_kernels`), and `warp_device_name` replaces
  five copies of the Warp device name. `api_core._util.resolve_device` and
  the daemon's `_pick_device` are removed. Asking for `"cuda"` on a machine
  without CUDA now raises `RuntimeError` everywhere at once: before, the
  stages raised but `CarverSession("cuda")` and `daemon --device cuda`
  accepted it and failed later. `CarverSession` now also accepts
  `"cuda:N"`.

### Removed (fallback tracer)

- **The fixed-step PyTorch fallback tracer** (`trace_multi_hit_grid`,
  `_trace_fixed_step`) and the torch copies of the surface and skin rules
  in `carving.py`. It ran only when Warp could not run on the device, and
  then gave approximate results (an oblique ray could skip a voxel corner)
  with nothing but a log warning. Warp ships wheels for every platform
  torch runs on, with a CPU backend for machines without an NVIDIA GPU,
  so it only ever ran on a broken installation. Every carver now calls
  `warp_kernels.require_dda_backend` first, which raises the new
  `WarpBackendUnavailableError` (a `RuntimeError`) naming why Warp cannot
  run and pointing to `setup_env.py`. `auto_batch_size` loses its
  `resolution` argument, which only fed the fallback's estimate. The DDA
  count-kernel test keeps its fine-sampling reference as a small helper
  in the test file.

### Added (engine requests)

- **`engine_requests`: one request core for every transport.** Parsing a
  request, building its config, running it and shaping the reply moved out
  of the daemon into `urbansolarcarver.engine_requests`, with typed request
  models (`RunRequest`, `StageRequest`, `RunPipelineRequest`,
  `SimulateWeightsRequest`, `PingRequest`) and reply models. The daemon is
  now a transport over it (`answer_engine_message`); a local HTTP service
  can use the same core. The wire format the daemon accepts and sends is
  unchanged, except below.
- **`load_config.build_config_from_mode_starting_values(values,
  base_folder=None)`** builds a config from the starting values of the mode
  *values* names, with *values* on top. It was private to the daemon.

### Changed (module layout)

- **`grid.py` is split by responsibility** into `surface_sampling.py`
  (test-surface sampling, `sample_surface`, `AnalysisMesh`),
  `voxelization.py` (`voxelize`, `voxelize_mesh`) and `meshing.py`
  (`finalize_mesh`, pruning, the cubic and smoothed meshers, cleanup).
  The code is unchanged; code that imported from `urbansolarcarver.grid`
  imports from the new modules. `test_grid.py` is split the same way, and
  the EPW cache test moved to `test_sun.py`. The API page "Grid Operations"
  is now "Geometry".
- **`raytracer.py` is split** into `warp_kernels.py` (Warp setup,
  `dda_backend_available`, `warmup_kernels` and every Warp kernel, kept in
  one module so Warp compiles and caches them as one unit) and
  `ray_tracing.py` (the kernel launches `trace_and_score_dda`,
  `trace_and_count_dda`, `follow_mass_behind_skin_dda`, ray generation, the
  fixed-step PyTorch fallback and `auto_batch_size`).
  `voxelize_solid_warp` moved to `voxelization.py`, next to its only
  caller. The code is unchanged; `test_raytracer.py` is now
  `test_ray_tracing.py`, with the warmup tests in `test_warp_kernels.py`,
  and the API page "Ray Tracer" is now "Ray Tracing".
- **`carving.py` keeps the ray carving only.** `validate_inputs`,
  `load_meshes` and the float32 input check moved to `io.py`;
  `sample_period` moved to `sun.py`; the column rules thresholding applies
  (`carve_above_columns`, `carve_above_scores`, `limit_column_slope` and
  their numba kernels) moved to the new `column_postprocessing.py`. The
  code is unchanged.

### Changed (engine requests)

- **A malformed daemon request reports `error_type` `MalformedEngineRequest`**
  (a `ValueError`) instead of `ValueError`: an unknown command, a missing
  key, or a message that is not a dict.
- **`load_mesh` raises `InputError`** (a `ValueError`) for a missing file, a
  file without triangles, and a file trimesh cannot parse. A missing file
  raised `FileNotFoundError`, and a corrupt file let trimesh's own
  exception (`IndexError`, `KeyError`...) through.
- **The daemon logs failed requests** with their traceback through
  `logging` instead of printing them.

### Removed

- **protect_share and recovered_sky.** Thresholding offers
  `carve_fraction` (the default of the weighted modes), `headtail` and a
  numeric cutoff, with score smoothing, carve_above and the slope limit
  (below). Configs that set `protect_share` or `threshold: protect_share`
  are rejected.

### Fixed (massing ground and top floor)

- **Massing could build no floor at all on a maximum volume whose facades
  are not aligned with the voxel grid.** The ground floor started at the
  bottom of the lowest occupied voxel layer, which can lie mostly below the
  maximum volume and is filled only where rays hit its base; columns along
  such facades lack it, every ground-floor bay failed the full-column test,
  and with `plate_stacking: supported` nothing was built (the
  `new_building` example). The ground floor now starts at the maximum
  volume's lowest point, as docs/massing.md describes, which preprocessing
  records in its manifest (`max_volume_lowest_z`), and a voxel layer whose
  centre lies below that point does not count against it.
- **The top floor could stand up to one voxel above the maximum volume.**
  Floors ended at or below the top of the highest occupied voxel layer,
  which can lie up to one voxel above the maximum volume's roof (a 19.5 m
  box got a floor from 17 to 20 m). Floors now end at or below the maximum
  volume's highest point, which preprocessing records too
  (`max_volume_highest_z`), and a voxel layer whose centre lies above that
  point does not count against the top floor, as at the base.
- Runs made before these changes keep the old ground and top, up to one
  voxel outside the maximum volume, until the analysis (preprocessing) is
  run again. The browser service marks such runs out of date. It also
  rebuilds a project's joined test surface file when that file was written
  without vertex normals (which welded panels sharing corners), when the
  project is opened or a run starts, and the stages built on it go out of
  date.

### Fixed (stage chain)

- **Exporting and massing could combine outputs of two different
  preprocessing runs.** Re-running preprocessing in place (another EPW or
  analysis period, same grid shape) left the old `mask.npy` beside the new
  occupancy grid, and the only check was the grid shape. Every manifest
  now has a random `run_id`, new on every run of its stage, and every
  downstream manifest records `upstream_run_id`, the `run_id` of the
  manifest it was built from. Thresholding, exporting and massing raise
  `StageChainError` (a `ValueError`) naming the stage to re-run when the
  upstream manifest is missing, unreadable or has another `run_id`. A
  re-run with identical settings is refused too, which a hash of the
  settings could not tell apart. Stage hashes are gone: `hash` and
  `upstream_hash` are removed from the manifests, `PreprocessingResult.hash`
  and `ThresholdingResult.hash` are now `run_id`, and
  `ThresholdingResult.upstream` is now `upstream_run_id`. The CLI prints
  `Run ID` instead of `Hash`.
- **A run folder could not be moved.** Manifests stored absolute paths.
  They now store paths relative to the manifest's own folder, with forward
  slashes (`scores.npy`, `../preprocessing/manifest.json`; the absolute
  path when no relative one exists), so a run folder can be copied or moved
  and still loads. Absolute paths in a manifest still load. The new
  `api_core/_stage_io.py` holds the stage folder layout, the start and end
  of a stage (`begin_stage`, `commit_manifest`) and the reading of an
  upstream (`load_upstream`); `PreprocessingManifest` now requires
  `voxel_size`, `mode`, `voxel_grid_path` and `sample_point_count`, which
  it always held.
- **Migration.** Run folders written before this change have manifests
  without `run_id`. Re-run the stages from preprocessing once for each
  existing run folder; until then thresholding, exporting and massing
  refuse them with a `StageChainError` that names the stage to re-run.
- **A failed Warp voxelization switched to trimesh and was cached.** Any
  exception from the Warp voxelizer (including CUDA out-of-memory) made
  `voxelize_mesh` use trimesh's rasterizer, which classifies boundary
  voxels differently, and the session cache (the daemon keeps one for its
  lifetime) kept that grid for the geometry. The error now propagates;
  trimesh is used only when Warp cannot run on the device at all.
- **The grid size limit was checked after the grid was allocated.**
  `voxelize_mesh` only logged above 500 million voxels and refused more
  than 4096 per side; preprocessing raised at 500 million only after the
  Warp voxelizer had allocated its 8 bytes per voxel. The new
  `urbansolarcarver.grid_planning` module (numpy only) plans the grid from
  the mesh bounds (`plan_voxel_grid`) and checks it
  (`check_voxel_grid_budget`, limit `MAX_GRID_VOXELS`) before anything is
  allocated; `voxelize_mesh` and the `--dry-run` estimate use it, and a
  client can call it to validate a request without importing torch.
- **Stale outputs survived repeated and failed runs.** Exporting wrote no
  manifest and deleted nothing, so changing `final_mesh_format` left the
  old `export.ply` beside the new file; thresholding wrote its manifest
  before its diagnostics; massing kept its old manifest and wrote
  `plates.json` before `plates.obj`; and exporting and massing each
  rewrote `run_report.md` with only their own leaf section, so running
  one dropped the other's. Every stage now deletes its manifest and the
  outputs of its previous run first (`begin_stage`, only the file names
  the stage writes) and writes its manifest last. Exporting writes an
  `ExportingManifest` with `upstream_run_id`. The run report keeps
  the Export and Massing sections whose manifests were built from the
  same thresholding run and leaves out sections of an earlier one.
- **Later stages took facts of the preprocessing run from the current
  config.** Massing projected the footprint from the config's
  `max_volume_path`, so a config naming another mesh changed the plates
  without any warning when the voxel columns fell inside it (a 30 x 12 m
  volume got 594 m² of ground-floor plates from a 36 x 18 m mesh); in
  Grasshopper the massing config does not name the preprocessed geometry
  at all. Preprocessing now saves the plan projection of the mesh it
  voxelized as `footprint.json` (world xy, listed in the manifest as
  `footprint_path`), and massing reads that file, never the input mesh, so
  editing or replacing the mesh afterwards cannot change the plates. When
  the projection fails or covers no area, preprocessing reports a
  `footprint_unreadable` issue, saves an empty list, and massing uses the
  voxel footprint with its existing warning. `load_occupancy` no longer
  re-voxelizes the config's mesh when `voxel_grid.npy` is missing; it
  raises `FileNotFoundError`. The run report's configuration table comes
  from the preprocessing run's `config_snapshot.json` instead of the
  config passed to exporting or massing; smoothing moved to the Export
  section, read from exporting's diagnostics.
- **Each stage reads only its own settings.** Preprocessing, thresholding,
  exporting and massing keep their public signatures; inside, each receives
  its settings model (`PreprocessingSettings`, `ThresholdingSettings`,
  `ExportingSettings`, `MassingSettings`) and `RunOptions`, and the
  carving and grid functions take the settings model in place of the whole
  config (`ray_batch_size` is a keyword of the carvers; `finalize_mesh`
  takes the `voxel_size` of the preprocessing run). Thresholding takes the
  mode and voxel size from the preprocessing manifest, and a config whose
  `mode` differs from the run's raises `StageChainError` (it was a plain
  `ValueError`). Exporting no longer warns when the config's `voxel_size`
  differs from the run's: it never reads it.
- **A dumped config did not load back with the same meaning.** The
  config validator wrote the mode default into `threshold`, so a dumped
  config (`config_snapshot.json`, or one a client keeps) ignored a later
  `carve_fraction` change and failed validation when switched to
  time-based or tilted_plane. `threshold` now keeps what was written (None
  = the mode default); `resolve_threshold` (and
  `UserConfig.resolved_threshold()`) resolves it in one place, and the
  thresholding manifest records the resolved strategy with the score
  smoothing radius and slope limit the run applied
  (`resolved_threshold`, `score_smoothing_m`, `max_slope_deg`). An
  explicit `carve_fraction` that the strategy does not read (headtail, a
  numeric cutoff, time-based, tilted_plane) now gives a warning instead
  of being ignored silently.

### Changed (stage contract)

- **One sequencer.** `run_pipeline(config, out_dir, produce=("exporting",),
  start_from="preprocessing", context=None)` runs `start_from` and every
  later stage on the path to the stages named in `produce` (any of
  `preprocessing`, `thresholding`, `exporting`, `massing`; producing
  exporting and massing thresholds once). A stage before `start_from` is not
  run: the next stage reads its output from `<out_dir>/<stage>`. The
  function returns a `PipelineResult` with one attribute per stage (the
  Result of a stage that ran in this call, None for the others) and
  `issues`. `stage_folder(run_folder, stage)` is the one definition of the
  folder layout, and `stages_to_rerun(previous_config, new_config, produce)`
  lists the stages whose own settings differ between two configs (it
  compares settings only, not input files).
- **Errors.** Errors raised on purpose derive from `UrbanSolarCarverError`:
  `ConfigError` (a `ValueError`; its `errors` list holds a
  `ConfigFieldError(field, message)` per problem), `InputError` (a
  `ValueError`; a mesh or EPW file that is missing or unusable, an empty
  voxel grid, no sample points), `StageChainError` (a `ValueError`; a
  missing, unreadable or stale upstream output, including a missing or
  wrong-shaped `scores.npy`, `voxel_grid.npy` or `mask.npy` and a missing or
  damaged `footprint.json`) and `RunCancelled`. Some
  `FileNotFoundError`, `RuntimeError` and plain `ValueError` raised before
  are now `InputError`, `StageChainError` or `ConfigError`, all `ValueError`
  subclasses: a caller that caught `FileNotFoundError` or `RuntimeError` for
  these cases catches `InputError` or `ValueError` instead.
- **Issues, progress and cancel.** Conditions the engine used to report with
  `warnings.warn` (settings the mode ignores, nothing carved, zero patch
  weights, a footprint that could not be read, ...) are issues with a code:
  `report_issue(code, message)` records an `Issue(stage, code, message)` on
  the active `RunContext`. Every stage Result has `issues`, `PipelineResult`
  has the issues of the whole call, and a direct call without a context
  still emits the warning. A `RunContext` also carries an `on_progress`
  callback (stage, done, total) and `cancel()`, which stops the run at the
  next batch of rays or stage boundary; stages that finished keep their
  output. `errors.py` and `run_context.py` import nothing outside the
  standard library.
- **`build_config(values, base_folder=None)`** validates typed values
  (what a client such as Grasshopper holds) into a `UserConfig`, raising
  `ConfigError` with a `ConfigFieldError` per problem. `load_config` reads
  the YAML and calls it.
- **Mode facts and archetype defaults live in the engine.** `ModeSpec` gains
  `description` and `starting_values`; `MODES` follows Grasshopper's menu
  order (time-based, irradiance, benefit, daylight, radiative_cooling,
  tilted_plane); `MODE_ALIASES` and `canonical_mode_name(name)` hold the
  accepted spellings. The starting values are what differs from the schema
  defaults: the analysis period (benefit 15 Oct 07:00 to 15 Apr 19:00,
  irradiance the full year, time-based 21 Dec 10:00 to 14:00),
  `tilted_plane_angle_deg: 45` and `carve_fraction: 0.35` for
  radiative_cooling. They fill a new config only; schema defaults and
  validation do not change. `configs/config_<mode>.yaml` stay hand-written
  examples for CLI users, a test checks that their values agree with the
  starting values, and the UTF-8 byte order marks of three of them are gone.
  The shoebox defaults moved from `carver_cli.py`, `USC_Archetype.py` and
  `simulated_weights.py` to `archetype_defaults.py` (standard library only,
  like `mode_registry.py`).
- **Diagnostics are written after compute.** Each stage builds its summary
  and ends with one call into `_diagnostics.py`, which writes
  `diagnostic.json` and, with `diagnostic_plots`, the plots. `diagnostic.json` keys keep their names, with one exception:
  thresholding's `upstream_hash` is now `upstream_run_id`. The `timings` in
  `diagnostic.json` now cover compute only: drawing the plots and loading
  the config and the upstream output are not counted. The preprocessing
  step label `diagnostic_plots_done` now marks the end of compute. matplotlib
  is no longer imported with `_diagnostics`; it loads when a plot is drawn.
- **Daemon `run` command.** Request keys: `produce` (list of stages),
  `run_folder`, optional `start_from`, `config` (a YAML path) and
  `overrides` (`key=value` strings or a mapping). Without `config`, the
  daemon builds the config in memory from the starting values of the mode
  named in the overrides (`mode` is required) plus the overrides; no file is
  written. The reply has `stage_folders` (stage to folder, for the stages
  that ran in this call), `manifest` (of the last of them), `issues` (a list
  of `{stage, code, message}`), and `export_path`, `plates_path` and
  `mesh_path` for the stages that produced them. Every stage-command reply
  carries `issues`, and an error reply adds `error_type` (the exception class
  name) and, for a `ConfigError`, `config_errors` (`{field, message}`). The
  older `preprocessing`, `thresholding`, `exporting`, `massing` and
  `run_pipeline` commands remain and keep accepting any `from` and
  `out_dir`; only `run` goes through the sequencer.
- **CLI.** `usc run` takes `--produce` (repeatable, default `exporting`) and
  `--start-from` (default `preprocessing`), locally or through `--daemon`.
  Issues print after each command as `Issues:` with `stage: code: message`.
  An `UrbanSolarCarverError` prints `Error: <message>` and exits with 1,
  without a traceback. `--dry-run` uses `grid_planning.estimate_grid_memory`
  (moved from `_reporting`), and `usc archetype` takes its defaults from
  `archetype_defaults.py`.
- **Grasshopper.** USC_Preprocess, USC_ThresholdStage, USC_Export,
  USC_Massing and USC_RunPipeline send the daemon's `run` command and read
  stage folders from the reply, and each engine issue appears as a warning
  on the component (`<stage>: <message>`; `config: <message>` for a
  configuration check). A stage component reads its upstream stage from
  `<out_dir>/<stage>` of its Config, not from the path on its `pre_result`
  or `thr_result` input (the input still has to be connected); when that
  path is in another folder the component shows an error naming both
  folders. USC_Config sends no YAML path when none is given, so the daemon
  starts from the mode's starting values and Grasshopper no longer reads
  `configs/`; without a YAML the stage components send
  `<out_dir>/incoming/max_volume.ply` and `test_surfaces.ply` (written by
  USC_Preprocess) as `max_volume_path` and `test_surface_path`. Grasshopper
  takes mode spellings from the mode registry. USC_Mode and
  USC_Archetype read the mode list, descriptions and archetype defaults from
  the engine, which they find through the USC helpers that USC_Session
  loads: when they solve before USC_Session (a saved file opened in a new
  Rhino session), they show a message that says so and solve once more
  after the current solution. The `.ghuser` files of USC_Config, USC_Mode, USC_Archetype,
  USC_Preprocess, USC_ThresholdStage, USC_Export, USC_Massing and
  USC_RunPipeline are rebuilt; run USC_SyncCanvas on existing canvases.
  Component inputs and outputs are unchanged.
- **Migration.** Each existing run folder needs one re-run from
  preprocessing (old manifests lack `run_id`; see "Fixed (stage chain)").
  A daemon that was started before this update has to be restarted
  (USC_Session, or `usc daemon stop` and `usc daemon start`): an old daemon
  answers the `run` command with "Unknown command: 'run'", and USC_Session's
  helpers then say to restart it.
  `run_pipeline` returns a `PipelineResult`: `result.export_path` is now
  `result.exporting.export_path`, and the same goes for the other fields of
  the exporting Result (`retention_pct`, `faces`, ...); the quick start and
  the five tutorial notebooks are updated. `PreprocessingResult.hash` and
  `ThresholdingResult.hash` are `run_id`.

### Changed (weighted modes; results change)

- **carve_fraction counts what carve_above removes.** The cutoff was
  computed on the voxels it picked, and carve_above then removed the
  voxels above them uncounted: carve_fraction 0.4 removed 50-62% of the
  obstruction score in the ReSBE test blocks (33 m, 0.5 m voxels), 0.6
  removed 64-73%. Each voxel now gets the cutoff at which carve_above
  would remove it (`carving.carve_above_scores`, which reproduces
  `carve_above_columns` exactly), and the cutoff is found on those values
  while counting each voxel's own score, so the removed share is the value
  set, up to one group of tied voxels. The same carve_fraction now keeps
  more volume than before (0.4: 72-75% kept instead of 56-68%); to get a
  result like before, raise it (0.4 before is about 0.55 now). The shapes
  for a given removed share are unchanged.
- **Slope limit after carve_above (`max_slope_deg`, back).** Each column
  is decided by its highest-scoring voxel, and scores in a column rise and
  fall with height, so neighbouring columns whose peaks fall just above
  and below the cutoff end 10-15 m apart, and score noise leaves spires.
  The resolution study (ReSBE blocks at 33 m, voxel sizes 0.5-2 m,
  sample spacing 0.25-2 m) showed that finer sampling reduces spikes only
  modestly (0-37% fewer with 4x the rays), so they come from the column
  rule rather than from rays missing voxels. Thresholding again caps each
  column at a maximum rise above a 5 x 5 median-filtered height map of its
  neighbours (`carving.limit_column_slope`): it only removes voxels and
  keeps the slider nested. Default: 75 degrees for the weighted modes, off
  for time-based and tilted_plane; `90` turns it off. In the ReSBE blocks
  at 0.5 m voxels it cut the spike area from 26-186 m2 to 0-25 m2 and
  the share of column pairs 2 m apart that differ by 9 m or more from
  3-14% to 0.1-1.7%, for 0-10% of extra obstruction score
  (`obstruction_fraction_carved_by_slope_limit`; most at low
  carve_fraction). At 1 m voxels it is weaker (its median window and
  allowance are counted in voxels). Diagnostics, the run report,
  USC_ThresholdStage and USC_Threshold (input `max_slope`) report or set
  it.
- **A voxel obstructs a test surface only if it lies entirely in front of
  it.** Before, a voxel counted when its centre was in front of the
  surface's plane, so the voxels a facade's own plane passes through (its
  skin) counted as obstructions of that facade. That mattered where test
  panels lie inside a curved mass (faceted facades of a round or freeform
  building): in the ReSBE freeform block, edge columns were carved to the
  ground for nothing. Flat facades aligned with the grid are unaffected.
  Applies to every mode (Warp kernels, the fixed-step fallback and the
  test reference).
- **A test surface's skin goes with the mass behind it (all modes).** The
  voxelizer marks every voxel the max volume's surface passes through as
  occupied, and a surface's own rays skip the voxels its plane passes
  through (its skin). So a test surface on a max volume face, or inside
  the max volume, sat in occupied voxels only other surfaces' rays could
  remove, and where none reached them they stood as one-voxel fins: in
  front of a neighbour's facade on the plot line, in slots narrower than
  a voxel between two facing facades, and at block corners. Now a skin
  occupied skin voxel with nothing of the max volume behind it obstructs
  the surface like any voxel in front of it, and an occupied skin voxel
  with max volume behind it is still not counted by the surface's rays
  but takes the count or score of the voxel behind it, so it is removed
  whenever that mass is. Empty skin voxels are never counted (in
  tilted_plane a count would carve the column above them, such as a
  bridge flush with a protected passage mouth). A lone building
  protecting its own facades is unchanged. full_blocks example,
  tilted_plane 45 degrees, 1 m voxels: 0.35% fewer kept voxels (152,229
  to 151,691), thin columns standing 3 or more voxels above both
  neighbours 52 to 36; the 19 skin fins found there (up to 92 voxels,
  20 to 30 above their neighbours) now stand at most one voxel above a
  neighbour, and most of the remaining thin columns are convex-turn
  gaps. Same rule in the Warp kernels (new
  `follow_mass_behind_skin_dda` pass), the fixed-step fallback and the
  test reference. Rays of zero-weight sample points (edge_taper) are
  dropped before tracing, so their skin does not follow.

### Fixed (tilted_plane; results change)

- **The tilted plane rotates around convex corners of the test surfaces.**
  Each sample point cast one ray along its own normal, so where two facade
  panels meet at an outside corner or a convex kink the two panels' rays
  diverged, and columns between them were crossed by no ray and stayed at
  full height: one-voxel spires at convex corners and vertical strips
  beyond kinks (a 6.7 degree kink left strips from about 8 m out; a 90
  degree corner left the whole outside wedge uncarved). Present since
  0.9.0. Neighbouring sample points whose normals turn convexly now also
  cast rays at headings swept between the two normals, so the wedge is
  capped by the plane rotated around the corner (at 45 degrees: height =
  distance from the corner). Concave corners are unchanged. In the
  full_blocks example at 1 m voxels the 45 degree envelope keeps 3.0% less
  volume (octant table: 3.5% less) and tilted-plane carving takes about
  0.7 s instead of 0.1 s on the CPU. No new parameter.

### Added

- **Floor-plate massing (stage 4, `massing`).** Turns the carved envelope into
  stacked floor plates: a ground floor (`ground_floor_height`, 5 m), then
  floors of `floor_height` (3 m). The footprint (the maximum volume's plan projection) is
  split into faces, one per facade (corners squared to the longer facade), and
  each face into bays of `min_plate_dimension` (3 m) cut perpendicular to its
  facade. A bay is built on a floor when it stays in the maximum volume, at
  most `plate_tolerance` (0.2) of its volume lies outside the envelope, and,
  with `plate_stacking: supported`, it is built on the floor below; parts
  narrower than `min_plate_dimension` are dropped. Writes `plates.json` (world
  outlines, floor areas) and `plates.obj` (one closed prism per plate) and adds
  a Massing section to the run report. `usc massing`, a daemon command, and the
  Grasshopper components USC_Massing and USC_MassingSettings. Geometry in
  `urbansolarcarver.floor_plates`.

- **Simulated-weights generator (benefit mode)**: `usc simulate-weights` and the
  `urbansolarcarver.simulated_weights` module: an ISO 13790 Annex C simple hourly
  ("5R1C") thermal model plus batched central-difference perturbation,
  producing the hourly *marginal* benefit/harm of solar gain, `benefit[t]` (fraction of
  a marginal joule of solar gain that offsets heating over the year) and
  `harm[t]` (fraction that becomes cooling load), written to a
  `simulated_weights.json` artifact with full provenance metadata. Inputs:
  one EPW plus ~10 archetype parameters (`configs/archetype_example.yaml`;
  neutral values, no national defaults). The engine is validated against
  ETH's RC_BuildingSimulator on three archetypes under the bundled Golden
  TMY3 weather (annual demands and hourly node states; driving arrays
  stored verbatim in `tests/data/`), plus steady-state closure against an
  independent network reduction. Design, tier ladder, and declared
  limitations: `design/simulated-weights.md`.
- **`simulated_weights_path`** (benefit mode): consume a simulated-weights artifact
  in place of the balance-point hour filter: each hour's DNI/DHI is scaled
  by `benefit[t]` before the cumulative sky matrix (the balance filter is
  the binary special case of this mechanism), and `include_harm: true`
  subtracts the `harm[t]`-scaled matrix clipped at zero. Analysis-period
  hours outside the period are zero-weighted. `balance_temperature`/
  `balance_offset` are unused (warns if customized); artifact provenance is
  recorded in preprocessing diagnostics (the artifact is read again on every
  preprocessing run, so edits to it take effect). Occupancy: archetypes accept a flat internal-gains
  value or a 24-value daily profile.
- **Shoebox archetype shorthand**: instead of explicit areas, an archetype
  may give `width`/`length`/`height` plus per-facade `wwr` (window-to-wall
  ratio), `g_value`, and optional `orientation`; floor area, volume,
  per-facade window areas, `area_window`, and `area_opaque` (opaque walls +
  roof) are derived. `configs/archetype_example.yaml` shows both forms.
- **Weights preview**: `usc simulate-weights` / `generate_simulated_weights` write a
  `.png` companion next to the artifact (benefit and harm as day x hour
  heatmaps), so the schedule can be inspected without writing code.
- **Sky-weight comparison in diagnostics**: a benefit run that consumes a
  simulated-weights artifact (with `diagnostic_plots: true`) also records a
  difference dome versus the simple balance-point rule for the same config
  (`sky_patch_comparison_image` + redistribution stats in
  `diagnostic.json`).
- **Tutorial 5** (`examples/5_benefit_5r1c.ipynb`): simulated benefit
  weights end-to-end: archetype, weights generation and inspection,
  simple-vs-simulated carve comparison, harm channel, provenance.
- The sample Golden CO TMY3 EPW is now actually committed
  (`.gitignore` exception), so the tutorials and EPW-dependent tests run
  out of the box as documented.
- **`usc archetype`**: builds a shoebox archetype YAML from defaults or an
  existing file (`--from`), with `-s key=value` overrides (`wwr_south=0.4`
  style for the per-facade ratios). The file is validated through the
  generator's own code path before writing, and the derived floor area,
  volume, and per-facade window areas are printed, so mistakes surface here
  and not inside a simulation.
- **`usc validate` checks the weights artifact**: when
  `simulated_weights_path` is set, the artifact itself is read and
  validated (existence, schema, 8760 bounded values) at validate time
  instead of failing mid-preprocessing.
- **Daemon `simulate_weights` RPC**: the persistent daemon generates
  weights artifacts on request (archetype as inline mapping or YAML path),
  so Grasshopper avoids a cold Python start per generation.
- **Grasshopper components for simulated weights**: new `USC_Archetype`
  assembles a typical building from five Honeybee-style family feeders
  (`USC_ZoneGeometry`, `USC_ZoneFabric`, `USC_ZoneVentilation`,
  `USC_ZoneOperation`, `USC_ZoneShading`; one wire per family, all
  optional with neutral defaults), and `USC_SimulateWeights` runs the
  simulation through the daemon (outputs the artifact path and the
  heatmap preview).
  `USC_BenefitParams` gains `simulated_weights_path` and `include_harm`
  inputs (with an on-canvas remark when balance settings are wired but
  unused), and `USC_Preprocess` surfaces the sky-weight comparison dome
  and redistribution stats in its diagnostics outputs.
- `generate_simulated_weights` reads internal gains from the archetype's
  `internal_gains_w_m2` / `internal_gains_profile_w_m2` keys when the
  argument is omitted, so CLI, daemon, and Grasshopper pass archetypes
  through unmodified.
- **Shading coefficients** (archetype keys, declared multipliers; no
  device geometry): `shading_permanent` (year-round transmission factor
  for fins/context) and `shading_hot` (additional factor deployed during
  the user-declared `hot_months`; awnings, tents, seasonal vegetation).
  Each accepts a scalar or a per-facade mapping (windows bin to their
  nearest cardinal). The attribution is attenuated by the same effective
  hourly transmission, preserving the artifact's exterior-joule semantics,
  and declared values land in the artifact provenance. Declaring seasonal
  shading makes the `harm` channel a defensible estimate instead of a
  conservative worst case. Supported in `usc archetype` (-s overrides)
  and on the USC_Archetype Grasshopper component (scalars).
- **`grasshopper/build_ghuser.py`**: builds the `.ghuser` user objects
  from the component sources (port names/descriptions from each GH UI
  block, port order and type hints from the numpydoc docstring, ribbon
  placement and stable GUIDs from `grasshopper/components.json`), using
  Grasshopper's `GH_IO.dll` without running Rhino. Byte-reproducible;
  `--check` flags stale files. `pip install -e .[ghbuild]` adds pythonnet.
  `tests/test_gh_components.py` keeps sources and docstrings in sync.
  Serialization adapted from the MIT-licensed GHPython Componentizer.
- **USC_SyncCanvas Grasshopper component**: updates the USC components
  on an open canvas to the installed versions. Unchanged inputs/outputs:
  replaced in place with wires, internalised values, data mappings,
  enabled/preview state and group membership kept. Changed inputs/outputs:
  the new version is placed beside the old one in a red group naming the
  new/removed ports, for manual rewiring. Report-only unless `update` is
  True; one undo step; a failed update rolls back.
- **End-to-end carving tests on urban typologies** (`tests/typologies.py`,
  `tests/oracle.py`, `tests/test_typologies.py`): eight procedural block
  types (courtyard, towers, rows, freeform, L-block, podium, random
  polygon, ground-floor passage) run through the full pipeline and
  checked against an independent CPU reference marcher, plus invariants
  (no floating mass, empty-cell independence, carve_fraction nesting,
  georeferenced translation, CPU/CUDA parity, cross-stage diagnostics).
  `tests/montecarlo.py` draws random scenes and settings from a seed and
  runs the same checks; any failing case is reproducible from its seed.

### Changed

- **All Grasshopper `.ghuser` files rebuilt from source.** The packaged
  files had drifted from `grasshopper/components/` (e.g. the USC_Session
  `python_path.txt` lookup and the PLY-loader hang fix were never
  packaged); the seven simulated-weights components (USC_Archetype, the
  five USC_Zone* feeders, USC_SimulateWeights) are packaged for the first
  time, in a new `3::Weights` ribbon group, with icons. Inputs now carry
  the type hints their docstrings declare (`bool`, `float`, `int`, `str`
  instead of untyped), so text panels convert as expected (e.g. `"False"`
  into a `run` or `include_harm` input is false, not a truthy string).

- **Benefit mode now implements its documented formula exactly (by
  default)**: patch weights are a plain cumulative irradiance matrix over
  the hours below `balance_temperature − balance_offset` (Heaviside filter
  on EPW dry-bulb). Previously the weights were always Ladybug's signed
  benefit−harm net clipped at zero, which silently let hot-hour radiation
  erode winter weights and made results depend on whether the analysis
  period included summer. A full-year analysis period is now safe and
  natural: the balance filter selects the beneficial hours by itself.
  The composite remains available as a declared, opt-in experiment:
  `include_harm: true` subtracts hot-hour radiation per patch (clipped at
  zero, dead-band hours count for neither side), with its period-dependence
  documented. Shading value is deliberately never a carving force: with
  signed retention, every voxel along a hot-hour ray earns shade credit, so
  the "optimal" envelope keeps whole sun-path prisms (cave-like volumes).
- `balance_temperature` default changed from 20 to **15 °C** (Ladybug's
  default; typical range ~12 commercial to ~18 residential, higher for
  older poorly insulated stock). Derive project-specific values via the
  Honeybee/E+ balance-point workflow.
- `balance_offset` now validates `>= 0` (a negative offset silently inverted
  the dead-band, so the cold-hour and hot-hour ranges overlapped).
- User-facing terminology for the two benefit weightings: "simple weights"
  (balance-point rule) vs "simulated weights" (5R1C hourly simulation);
  the internal "Tier 1.5" label no longer appears in docs, CLI, or configs.
  The module and all public names use the `simulated_weights` family
  (`generate_simulated_weights`, `simulated_weights_path`,
  `usc simulate-weights`, `simulated_weights.json`); no aliases are kept
  since the feature is unreleased.
- Benefit mode warns loudly and returns all-zero weights when the analysis
  period contains no beneficial hours (previously this fell through toward a
  degenerate carve with only a generic downstream warning; an empty hour
  list must also never reach Ladybug, which treats it as "whole year").

### Removed

- **`ground_reflectance` config field**. It never affected results: Ladybug
  SkyMatrix only stores it as metadata for RadiationStudy, which USC does
  not run, and USC's ray casting targets sky patches only. Configs carrying
  the key now fail validation with a clear message; remove the line. The
  USC_RaySettings Grasshopper component no longer emits it (old canvases
  keep the input; it is ignored).

### Fixed (code review)

- **CPU runs lost score updates.** Warp's CPU `atomic_add` is a plain
  read-modify-write, and CPU batches ran from a thread pool on one shared
  buffer: about 6e-5 of the score mass was lost per run, by a different
  amount each time. Each thread now accumulates into its own buffer.
- **The daemon could be stopped by a client.** A wrong authkey, a client
  that disconnected before its reply, or an unreadable message ended the
  server loop. Each connection is now handled in isolation; errors reply
  with the exception type, and GPU memory is released after every run.
  The unusable `--authkey` option is removed.
- **`carve_above` from the Grasshopper Threshold component had no
  effect.** It was applied in exporting, which never received the
  threshold overrides. It now runs in thresholding, so `mask.npy` and
  the reported retention describe the exported envelope.
- **USC_Mode could not be wired to anything that worked.** It now outputs
  `mode_name` for USC_Config's `mode` input.
- **`headtail` used the inverted stop rule** and returned the plain mean
  on heavy-tailed scores. It now follows Jiang (2013): keep splitting
  while the head is a minority, return the deepest such break.
- **Irradiance and benefit scores were labelled Wh/m²**; Ladybug returns
  kWh/m².
- **Relative paths in a YAML config now resolve against the YAML's own
  folder** (they resolved against whatever directory the CLI, daemon or
  Rhino happened to run in, so one config found its files in one place and
  not the other). The CLI sends the daemon absolute paths, and USC_Config
  resolves relative paths against the saved `.gh` file.
- **Period overrides no longer clash with an `analysis_period:` block**:
  flat `start_*`/`end_*` overrides (what USC_AnalysisPeriod sends) win.
- **`radiative_cooling` no longer requires an EPW or analysis period** (it
  never read them), and irradiance/benefit no longer list `min_altitude`
  (unused). Setting a field the chosen mode ignores now warns.
- **Thresholding refuses scores from a run in another mode** instead of
  applying that mode's default threshold rule to them.
- **The session cache returned tensors on the wrong device** (a CPU run
  inside the CUDA daemon failed in the Warp launch) and keyed voxel grids
  on trimesh's rotation-invariant mesh identifier. Keys now include the
  device, voxel grids are keyed on mesh contents, and leaving a
  `with CarverSession()` block closes the session.
- **CLI `--daemon`**: `--dry-run` stays local, manifests are auto-detected
  before sending, daemon errors exit 1 with a readable message, and
  `daemon start` refuses to start a second daemon, reports a crashed one,
  and logs to `~/.urbansolarcarver/daemon.log`. `daemon status` exits 1
  when no daemon runs.
- **A stage that fails midway can no longer leave the previous run's
  manifest** pointing at half-overwritten arrays; the run report goes into
  the run folder (not the export folder's parent) and an old one is
  removed before regenerating.
- **Silent fallbacks now warn.** Skipped test-surface panels (non-planar,
  degenerate, unsampled) are reported by component index; the Warp to
  trimesh voxelizer fallback and a Warp installation that fails to
  initialise are reported; tilted-plane samples on horizontal surfaces
  are reported; score smoothing clipped to 0.5-8 voxels says so.
  `smooth_iters` is validated to 0-6 instead of being clamped silently.
- **One zero-area face no longer drops a whole test-surface panel**, and
  edge samples no longer depend on vertex numbering (inward side chosen by
  ring order, not shapely object identity) or on which panel edge is
  "first" (both edges sampled alike).
- **Smoothed export:** the Taubin polish shrank the mesh (wrong sign of
  its inflating step; -10% volume at 6 passes), and an empty grid produced
  a box around the whole domain. `cleanup_mesh` kept every fragment when
  none reached `min_face_count`; it now keeps the largest and warns.
- **An EPW replaced on disk is re-read** by a running daemon (the parse
  cache now keys on modification time and size).
- **Grasshopper components share one helper module**
  (`grasshopper/usc_gh.py`) instead of keeping 2-5 drifting copies of the
  daemon call, PLY reader/writer, mesh conversion and override parsing
  (Preprocess, Threshold Stage, Export and Run Pipeline went from 1,343 to
  528 lines). Daemon calls time out instead of freezing Rhino on a hung
  daemon, errors show as red runtime messages everywhere, a missing result
  file is an error instead of an empty output, test points are read
  without numpy, and USC_Session checks the daemon with a ping (not
  "a key file exists and the port is open"), logs a detached daemon to
  `~/.urbansolarcarver/daemon.log` and reports a daemon that crashed on
  start. USC_RunPipeline's subprocess fallback is removed (it broke on
  quotes in paths and on Warp's start-up banner); it needs the daemon like
  the other stages. Brep inputs now reach the components unconverted, so
  the fine Brep meshing applies instead of Grasshopper's coarse default.
  USC_Archetype reports a connected family input that delivered nothing
  (a failed USC_Zone* component) instead of silently using defaults.
- **Exporting** meshed with the config's `voxel_size` instead of the
  preprocessing run's, and counted retained voxels before the small-
  fragment cleanup (now reported as `voxels_removed_by_cleanup`).
- **Smaller fixes from the comment and docstring review**:
  - Re-voxelizing a run whose `voxel_grid.npy` is missing now uses the
    preprocessing run's voxel size, not the one in the config passed later.
  - A planar test surface too small for the sampling grid gets its single
    sample at a point inside the polygon (the vertex centroid can fall
    outside an L-shaped or ring-shaped surface).
  - Sample normals and analysis-quad winding follow the area-weighted face
    normal instead of the first face's, which is zero for a zero-area face.
  - The iso-level helper of the smoothed mesher had its two edge cases
    swapped (all cells inside / no cell inside).
  - Hour-of-year indices are validated as 0 to 8759 (EPW files hold 8760
    hours; 8760 to 8783 used to pass and were dropped silently).
  - An archetype with `wwr`, `g_value` or `orientation` but no
    width/length/height now fails with "shoebox archetype is missing ..."
    instead of a later TypeError.
  - The fixed-step tracer (no Warp) sized its chunks for 24 bytes per
    sample; it holds 49, so it could use about twice its memory budget.
  - The daemon authkey file is created with owner-only permissions on
    Linux and macOS from the start, and two processes starting at once
    no longer write different keys. A CLI call with a mismatched key
    prints a message instead of a traceback.
  - Carving looked up the Tregenza patch directions with a keyword
    argument, which bypassed the session cache.
  - USC_Config resolves relative `epw_path` / `simulated_weights_path`
    from USC_EPW and USC_BenefitParams against the .gh file, as it does
    for its own inputs. USC_Threshold warns about an unknown `method`
    instead of ignoring it.
  - `load_mesh` turns closed bodies stored inside out so their normals
    point outward (before, only open meshes had their winding fixed).
  - Tregenza solid angles are built from Ladybug's per-band constants:
    its `ViewSphere.tregenza_solid_angles` property returns the 577
    Reinhart values once `reinhart_solid_angles` has been read.
  - The sky-patch diagnostic plot drew the Tregenza band edges at the band
    centres (6°, 18°, ...); they are now at 0°, 12°, ..., 84°.
  - The thresholding diagnostic `normalized_score_stats` is renamed
    `occupied_score_stats`: the scores are not normalized, they are the
    occupied-voxel scores the threshold was compared with.
  - Automatic ray batch size with Warp assumed 320 bytes per ray for hit
    lists the fused kernels no longer keep; it now assumes 96, so GPUs
    with little free memory get larger batches.
  - USC_SimulateWeights without `out_path` on an unsaved .gh file writes
    to `~/.urbansolarcarver/simulated_weights.json` instead of failing.
  - The Grasshopper PLY reader reads x, y, z from any column position in
    ASCII files, accepts any face list count and index types, and splits
    faces with more than four corners into triangles (they were cut to
    quads).
- **Session cache kept between daemon commands**: the daemon cleared its
  cache after every command, so re-running preprocessing on unchanged
  geometry voxelized again. The cache now persists, capped at 1 GiB
  (`CarverSession(max_cache_bytes=...)`) with least-recently-used
  eviction; after each command the daemon only returns unused GPU memory.
- **Docs and comments**: docstrings, comments, CLI help, config field
  descriptions, Grasshopper port descriptions and the docs pages were
  checked against the code and corrected where they disagreed (removed
  functions, wrong defaults, units, file names, mode requirements).
- **Tests**: tests that only checked hand-written values (`hashlib`, a
  literal manifest dict, a copied mode table) now run the real stages or
  read the mode registry; a new exporting test checks that a model at UTM
  coordinates keeps its voxel lattice to 1e-6 m end to end.

### Removed (code review)

- Unused code: the buffered Warp DDA tracer (replaced by the fused
  kernels), the point-cloud and diagnostic exporters in `io.py`,
  `sun.warm_up`, unused `AnalysisMesh` methods, the never-read
  `suggested_threshold` manifest field, and the report's fallback to the
  old `summary.json` / `timings.json` files.

### Fixed (carving correctness; results change)

Found with a new end-to-end harness (procedural urban typologies checked
against an independent CPU reference marcher, plus Monte Carlo runs).

- **Protected surfaces obstructed themselves.** Rays started inside the
  boundary voxels of the mass a test surface belongs to, and those voxels
  were counted as obstructions: protected lower floors lost a voxel-thick
  skin on roughly half their facades (every facade on curved footprints),
  and with `carve_above` the whole column above went with it. Weighted modes
  gave those voxels the highest scores. The DDA kernels now skip voxels
  whose centre lies behind the ray's source surface (exact rule, per-ray
  surface normal; no origin offset, which would shift rays sideways).
- **`tilted_plane` carved a band, not the half-space above the plane.** Only
  voxels crossed by each sample's ray were removed, so mass above the band
  swept by a facade survived as floating slabs. Every voxel at or above a
  ray in its column is now removed.
- **Thresholds were resolved over empty cells.** `carve_fraction`,
  `headtail`, score smoothing and the reported retention used every grid
  cell; streets, courtyards and the grid margin hold 60-80% of the score
  mass, so `carve_fraction: 0.8` removed 79-86% of the building's own
  obstruction depending on the scene, and results changed with
  `margin_frac`. Everything now uses occupied voxels only (smoothing is a
  normalized convolution over the building); the mask is False on empty
  cells.
- **`carve_above` treated empty cells as carved mass.** Air the mask marked
  False (a passage under a bridge, the margin) could trigger removal of
  everything above it. Runs are now made of carved occupied voxels only.
- **Time-based sampled the sun hourly.** The sun moves ~15° of azimuth per
  hour; mass between consecutive hourly ray sheets survived while shading
  the protected surface between samples (58-322 voxels per scene at 1 m).
  New `sun_steps_per_hour` (default 12 = every 5 min). Violation scores
  are now shaded area x duration in **m²·h** (they were raw ray counts,
  which grew with both the sun sampling and the surface sampling density),
  so a numeric threshold means the same at any `grid_step` and
  `sun_steps_per_hour`.
- **Georeferenced coordinates lost precision.** Voxelization, sampling and
  tracing ran in float32 world coordinates (~0.5 m resolution at UTM
  northings). Preprocessing now works in a local frame (coordinates rounded
  to 1 µm, so the same scene placed anywhere samples and carves
  bit-identically) and persists world coordinates in float64; surface
  sampling no longer drops or keeps a panel's edge row at random when the
  sampling lattice coincides with that edge. The exported mesh is placed in float64 and PLY
  exports switch to double-precision vertices when float32 would round by
  more than 1 mm. A warning names float32 PLY inputs whose coordinates are
  already rounded on disk by more than 1% of a voxel. The Grasshopper
  components now write their input geometry with double-precision vertices
  (previously float32: a Brep box at UTM coordinates reached USC 0.21 m off;
  verified exact in Rhino 8.35), and their PLY readers accept
  double-precision files and build double-precision Rhino meshes.
- **`carve_above` defaults to `true`** (was `false`). Time-based and
  weighted carving otherwise return mass floating above carved zones
  (8k-24k voxels on the ReSBE demo scenes): physically it casts no
  violating shadow, but the classical solar envelope is a height field and
  floating mass cannot be built. Set `carve_above: false` to keep it.
- **`carve_above` no longer refills short carved runs.** Runs shorter than
  `carve_above_min_consecutive` were patched back to kept, reinstating
  voxels the solar constraint had removed (up to ~100 per scene). They now
  stay carved and simply do not trigger; carve_above only ever removes.
- **Diagnostics.** Exporting reported the retained voxel count as
  `voxels_carved`; it is now `voxels_retained`, with `voxels_removed`
  added. Thresholding reports `voxels_occupied` (replacing `voxels_total`,
  which counted the whole grid) and retention over occupied voxels, so both
  stages report the same retention.

### Added

- **`edge_taper` design constraint** (all weighted sky-patch modes): sample
  points within `edge_taper` meters of their test-surface component's
  boundary count proportionally less (linear ramp), so perimeter/corner
  points no longer force carving of directly adjacent volume. This replaces the
  manual practice of offsetting test-surface edges. Distances are exact 2D
  distances to the welded component outline (exterior and holes), so
  exploded-but-coincident panels (e.g. street networks) have no phantom
  seams. Zero-weight rays are dropped before tracing. Components narrower
  than ~2× the taper warn loudly and per-component stats are recorded in the
  preprocessing diagnostics, so the taper never silently excludes geometry.
  Ignored (with a warning) by the binary violation-count modes.
- **`min_sky_elevation_deg` protection cone** (radiative_cooling): sky
  patches below the declared elevation are excluded from the cooling weights
  (renormalized): a declared design constraint analogous to
  obstruction-angle daylight rules, controlling how steeply the envelope may
  rise around protected surfaces. Default 0 keeps the pure physical model.
- The radiative-cooling template now documents both constraints and ships a
  mode-appropriate `carve_fraction: 0.35` default (cooling scores are
  diffuse; the 0.7 used by solar modes over-carves drastically).

- **Canonical `ThresholdSpec`**: `threshold` now normalizes every accepted
  spelling (bare number, `headtail`, `carve_fraction`, or the canonical
  mapping `{method: ..., value: ...}`) into one validated object at config
  load. Methods: `carve_fraction`, `headtail`, `cutoff`. Mode defaults are
  resolved at load time (weighted modes → `carve_fraction`, count modes →
  `cutoff 0`), and the method is cross-checked against the mode's score
  kind; misuse fails at load with a precise message. All previous config
  spellings keep working.
- **`analysis_period` mapping**: the analysis period can be given as one
  mapping using Ladybug's `AnalysisPeriod.to_dict()` keys (`st_month` …
  `end_hour`; `start_*` spellings also accepted; LB's `type`/`timestep`/
  `is_leap_year` extras are ignored). The six flat fields remain valid.
- **Bundled example weather file**: a public-domain NREL TMY3 EPW (Golden,
  Colorado) ships under `examples/weather/`, so the tutorial notebooks and
  the EPW-dependent tests run out of the box. `USC_EPW_PATH` still overrides
  it for the test suite.
- **`setup_env.py` long-path preflight**: on Windows, the installer now
  predicts the 260-character path failure that torch's wheel triggers under
  deep repo paths, and falls back to a short per-user venv (`~/.usc-venv`)
  with clear instructions, instead of dying mid-install with WinError 206.
  A `--venv-dir` option overrides the location.

### Removed

- The monolithic `configs/user_config.yaml` starter (superseded by the
  per-mode templates).
- Dead nested/dotted-key override machinery in `load_config`: the schema is
  flat and the advertised `a.b=c` form never validated. Overrides are plain
  `key=value` (JSON lists/objects are parsed as values).

### Changed

- The thresholding stage hash now derives from `{threshold_method,
  threshold_value, score_smoothing}`. Previously it could embed a
  score-dependent resolved cutoff (making identical configs hash
  differently) and an irrelevant `carve_fraction` for non-fraction methods.
  Stage hashes change once across this version boundary.
- `threshold_method` in diagnostics reports `cutoff` where it previously
  reported `numeric`.

### Fixed

- **`setup_env.py` on current NVIDIA drivers**: the CUDA-to-wheel map ended
  at 12.x, so drivers reporting CUDA 13.x silently fell back to CPU-only
  PyTorch; CUDA >= 13 now maps to cu128 wheels. The script also installs
  the package editable (`pip install -e .[dev]`) as its docs always claimed,
  instead of a static site-packages copy that ignored source edits.
- **Session cache on CUDA machines with CPU sessions**: `get_active_session()`
  with no device preferred cuda-when-available, so a `device: cpu` run on a
  GPU machine silently lost all session caching; a single active session now
  wins regardless of device.
- **Matplotlib backend hijack**: `api_core._diagnostics` forced the Agg
  backend at import time, breaking inline plotting in any notebook that
  imports USC; Agg is now only the fallback when no backend was chosen yet.
- The Warp voxelizer parity test crashed on CUDA machines (`.numpy()` on a
  cuda tensor) before asserting anything; it is now device-aware and
  parametrized over both cpu and cuda, so the parity guarantee is actually
  exercised on GPUs.
- **CPU ray tracing accuracy and speed**: the CPU path now runs the same exact
  Warp DDA kernel as CUDA. The previous fixed-step marcher skipped up to ~37 %
  of the voxels traversed by oblique rays, systematically under-counting
  obstruction on CPU-only machines. Measured on the `full_blocks` example
  (daylight mode): preprocessing 101 s → 5.8 s (~17×), obstruction score mass
  +61 %. The fixed-step marcher remains as a fallback when Warp is missing and
  now warns that it is approximate.
- **`north_deg` convention**: USC documents `north_deg` as degrees *clockwise*
  from +Y, but Ladybug's `SkyMatrix`/`Sunpath` use *counterclockwise*. The
  angle is now negated at the Ladybug boundary, and `north_deg` is honored by
  the time-based mode (sun vectors) and the tilted-plane per-octant lookup,
  which previously ignored it. Runs with the default `north_deg: 0` are
  unaffected.
- **`apply_smoothing=True` meshing**: marching cubes now contours the
  continuous smoothed SDF (trimesh's `threshold` argument binarized the field,
  silently discarding the SDF smoothing), with correct voxel-center alignment
  (surfaces were previously shifted half a voxel) and outward face winding.
- **Violation counts on the fallback tracer**: `trace_multi_hit_grid` now
  guarantees each (ray, voxel) pair is reported once; the fixed-step marcher
  could report duplicates, inflating time-based / tilted-plane violation
  counts.
- **`--dry-run` grid estimate**: now mirrors the actual cubic grid built by
  `voxelize_mesh` (the estimate used per-axis dimensions and could badly
  under-report memory for elongated sites).
- **`threshold: numeric`** (a Grasshopper-side placeholder) is now rejected
  with a clear message at config load instead of crashing mid-pipeline.
- Missing input files (meshes, EPW) are validated at the start of
  preprocessing for fast, clear errors.

### Performance

Measured on a 306³ grid / 375k sample points (daylight mode, CPU): full
pipeline 112 s → ~34 s.  Except for the CPU trace dispatch, the gains
apply equally to CUDA machines.

- **Voxelization**: new Warp parity voxelizer: one BVH ray per grid
  column along each axis, majority vote across the three parities plus
  surface-hit marking (the same robustness idea as trimesh's
  orthographic fill).  Runs on CUDA or the Warp CPU device: 10–50×
  faster than the trimesh rasterize-and-fill path (6.4 s → 0.6 s at
  306³), which remains as the no-Warp fallback.  The occupancy is
  center-exact; differences vs trimesh are confined to the 1-voxel
  surface shell (regression-tested).
- **Fixed a half-voxel embed bug in the trimesh voxelization path**:
  `vox.transform[:3, 3]` is the CENTER of trimesh's voxel (0,0,0), not a
  grid corner, so the occupancy grid was systematically misplaced by
  half a voxel (rounding to a full voxel at ambiguous alignments) in all
  previous releases.
- **Smoothed exporting**: marching-cubes output is welded
  (`merge_vertices`) and then given the light cleanup instead of the
  full trimesh repair whenever it is watertight (it normally is); the
  full repair remains the fallback.  Welding first matters: MC emits
  zero-area faces where the iso crosses lattice nodes, and dropping
  them before welding would open pinholes.

- **`carve_fraction` thresholding**: the full `argsort` over the score
  volume (O(N log N); ~5 s at 306³ and minutes at 500³) is replaced by an
  exact two-pass weighted-histogram method (O(N)).  Mass accounting now
  accumulates in float64; the old float32 cumulative sum drifted
  measurably on large grids, so thresholds may shift very slightly (the
  new values are the more accurate ones).
- **Perona–Malik SDF smoothing** (`apply_smoothing=True` exports): the
  serial in-place stencil is now a parallel Jacobi stencil
  (numba `prange`, ~10× on a 306³ grid).  The Jacobi update scheme
  differs from the previous in-place sweep by a fraction of a voxel in
  SDF units; the volume-matched iso compensates globally.  The two
  distance transforms feeding the SDF also run concurrently (~1.9×).
- **CPU ray tracing**: Warp executes CPU launches single-threaded, so
  batches of the fused trace+score kernel are now dispatched from a small
  thread pool when running on CPU (kernels release the GIL; the shared
  score buffer stays correct via atomic adds).  Like on CUDA, atomic
  float addition makes scores reproducible only up to rounding noise.
  CUDA dispatch is unchanged.

### GPU-path efficiency

- The carvers no longer transfer the full ray set to host memory: at
  typical ray counts (~34M rays at 0.5 m sampling) this was ~0.8 GB of
  device→host copying per preprocessing run whose result was immediately
  discarded.  `carve_with_sky_patch_rays` and `carve_with_sun_rays` now
  take `return_rays=False` (opt-in) and return None ray fields otherwise.
- New fused DDA count kernel (`trace_and_count_dda`) for the binary
  carving modes (time-based, tilted_plane): counts hits atomically
  in-place, replacing the buffered trace path that guessed 20 hits/ray
  and re-traced every batch on overflow (2-3x wasted GPU work on scenes
  with long rays).  The buffered path remains for the no-Warp fallback.
  Equivalence with the buffered counts is regression-tested.
- `generate_sky_patch_rays` no longer materializes per-ray normals
  (an (R, 3) tensor nobody consumes, hundreds of MB of VRAM);
  pass `include_normals=True` to get them.

### Added

- **Kernel warmup**: Warp JIT-compiles kernels on first use (~3-10 s once
  per machine, per device, per code version; cached on disk afterwards).
  That one-time cost is now paid where waiting is expected instead of on
  the first carving run: `setup_env.py` precompiles at the end of
  installation, the daemon precompiles during startup (before READY), and
  a new `usc warmup [-d cpu|cuda]` command covers manual updates.
  Public API: `urbansolarcarver.raytracer.warmup_kernels(device)`.

### Robustness / code quality

- Defensive validation at stage boundaries: thresholding and exporting now
  verify that scores/mask files exist and match the grid shape recorded in
  the manifest, failing with a clear message instead of a cryptic
  numpy/torch error when artifacts from different runs are mixed.
- `load_mesh` rejects files with no triangle geometry at load time (was a
  cryptic empty-grid failure later).
- Preprocessing warns loudly when scores contain NaN/Inf (non-finite voxels
  are always carved, previously without any signal); the test suite now
  exercises the real check instead of a copy of its logic.
- `usc schema` (and any CLI output) no longer crashes with
  UnicodeEncodeError on legacy Windows code pages when piped.
- CLI overrides accept scientific notation (`-o score_smoothing=1e-1`);
  'inf'/'nan' spellings stay strings so validation rejects them clearly.
- `session_cache` warns once when a key template does not match the call
  signature (a silently dead cache was invisible before).
- Direct attribute access on the validated config everywhere (the
  `getattr(conf, "field", default)` pattern silently masked typos).
- Daemon RPC handlers consolidated into one dispatcher (was 4 copies of
  the same try/except/close block).
- Monolith decomposition: threshold resolution and score smoothing
  extracted from `thresholding()`; mode dispatch and the
  radiative-cooling guard extracted from `preprocessing()`; boundary-loop
  chaining extracted from `sample_planar_surface()`.
- Removed dead/speculative API: `carve_directional`, `voxelize_and_clean`,
  `mesh_from_voxels_select`, `CarverSession.get_kernel` (Warp caches its
  own compiled modules), plus unused parameters and unreachable branches.

### Changed

- The `diagnostics` config flag (previously unused) now gates the detailed
  score statistics (median, std, percentiles) in per-stage diagnostics JSON.
  Basic statistics (count, min, max, mean, nonzero counts) and timings are
  always written.
- Grasshopper components: the PLY preview loader no longer hangs Rhino on
  non-PLY export formats (obj/stl/glb are saved to disk with a canvas
  Remark instead); USC_Threshold warns instead of emitting the invalid
  bare `threshold=numeric` placeholder; USC_Session finds the backend
  Python in `.venv`/`venv` (Windows and POSIX layouts) or via an optional
  `python_path.txt` override, and no longer passes Windows-only process
  flags on macOS; USC_RunPipeline errors turn the component red like the
  stage components.
- `carve_above_columns` compiled with numba (was a pure-Python triple loop;
  large grids dropped from minutes to milliseconds).
- Diagnostic plots render synchronously; the previous "background thread" was
  started and immediately joined, adding overhead without concurrency.
- Documentation/docstring corrections (nonexistent config fields, stale
  return signatures, wrong output filename in CLI help).

## [0.9.0] - 2026-04-02

First public beta release.

### Added

- **3-stage pipeline**: preprocessing (voxelise, ray-cast) → thresholding (score ranking, carve fraction) → exporting (mesh reconstruction)
- **6 analysis modes**: time-based, irradiance, benefit (heating/cooling), daylight (CIE overcast), tilted-plane, radiative-cooling (experimental)
- **GPU acceleration**: NVIDIA Warp ray tracer with automatic CPU fallback
- **Thresholding strategies**: `carve_fraction` (direct), `headtail` (automatic heavy-tail detection), numeric threshold
- **Score smoothing**: optional Gaussian smoothing with auto-default sigma (1.1× voxel size)
- **Carve-above column post-processing**: remove structurally implausible floating mass above carved zones, with configurable `min_consecutive` sensitivity threshold
- **Connected-component filtering**: `min_voxels` parameter removes small isolated fragments
- **Multi-format mesh export**: PLY, OBJ, STL, GLB output via trimesh
- **Run report**: automatic `run_report.md` summarising every pipeline run
- **Diagnostic outputs**: score histograms, sky-patch hemisphere plots, config snapshots, step timings
- **CLI** with two entry points (`usc`, `urbansolarcarver`): `run`, `validate`, `info`, `list-modes` commands
- **Python API**: `preprocess()`, `threshold()`, `export()` for decomposed workflows
- **Grasshopper integration**: 17 GHPython components for Rhino 8
- **Configuration**: single YAML file with Pydantic v2 validation (`extra='forbid'`)
- **Memory guard**: rejects grids exceeding 500 million voxels
- **Mode registry**: single source of truth for mode definitions and parameter requirements
- **5 tutorial notebooks**: quick start, mode comparison, threshold tuning, Grasshopper bridge, advanced post-processing
- **Reference YAML**: fully commented `REFERENCE_all_options.yaml` with all configuration fields

### Notes

- `radiative_cooling` mode is marked experimental (clear-sky only, horizontal surfaces)
- GPU (`[cuda]` extra) is recommended for grids above ~100³ but not required
- Requires Python >= 3.9
