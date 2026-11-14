# Changelog

All notable changes to Urban Solar Carver are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Site

- **Draw test surfaces on the ground.** **Draw** in the Test surfaces box draws a flat surface on the ground (a square, a courtyard,
  a street) with the site editor, saved at once as a set; **Edit outline** edits it, with holes, and typing an elevation moves the
  whole surface. A set is still used by nothing until a criterion or study switches it on.
- **Rectangles in the site editor.** While a site, a hole or a context block is drawn, the bar offers **Polygon**, **Rectangle**
  (two opposite corners, sides along x and y) and **Tilted rectangle** (a first side from two clicks, then a click for the width).
  The pointer previews the rectangle with its size; clicks snap as in a polygon, and Shift holds the tilted side to 15° steps.
- **The same words in every box**: Add files is now **Import**, as in the Sites box; the Context box has **Draw** and **Import**, in the Sites box's order; the
  Test surfaces box has **Pick** (it said From context) and **Import**.
- **Draw context blocks.** Draw in the Context box draws an outline in the 3D view with the site editor and extrudes it
  to a height; blocks are listed beside the context files and joined into the context without changing any context file.
  Overlapping blocks are refused; touching ones are fine. The block rows follow the Sites table: a double click on the name renames,
  the height is a column, and a ⋯ menu holds Edit, Draw hole, Place on terrain and Remove. A click on a block in the 3D view edits
  it, also in projects whose maximum volume comes from files; where a site and a block are both under the click, the smaller one is
  edited.
- **The Sites table and the block rows scroll past five rows**, under a fixed column heading, and a row that starts being edited
  scrolls into view.

### Settings

- **A rough time under Voxel size**: after a run, how long its scoring took on this computer, and at another voxel size an
  estimate scaled by the number of voxels.

### Simulate

- **Quicker results after a run.** A study that keeps its test points between runs now sends only the new values to the app,
  not its patches again: on Allatini (1.5 million points) 11.7 MB in place of 82.2 MB.

### Fixes

- **Inspect does not flip picked or drawn sets.** A set picked on the context is built again from its picks when the context
  changes, so a flip saved in Inspect was lost without a word. Its Flip buttons are now off, and the row says to pick the face again
  from the other side; a set drawn on the ground says it faces up.
- **Picked pieces that touch stay apart.** Two pieces of a picked set that shared an edge (two walls at a corner, a wall and
  its canopy) were read by the engine as one surface: the sampling skipped it as non-planar, so the criterion protected neither, and
  on single-sheet context one piece could turn to agree with the other. Each piece now keeps corners of its own with its normal.
  Picked sets stored before are built again once when the project is opened, which puts the criteria that use them out of date.
- **Rename and Reset ask about turns not saved in Inspect** first, as leaving Inspect does: both open the project afresh, which
  dropped them.
- **A broken file no longer blocks Save and Restore in Inspect**: a context or terrain file that cannot be read only refuses a save
  of that file.
- **Two criteria named after the same mode** read apart in the Criteria summary: by their whole name, numbered if that is shared too.
- **A criterion card no longer stays on "Running"** when the run summary cannot be read after a run (it waited for a summary that
  differed, and the first run's stays empty).
- **Envelope and massing shows the base volume**, so the built mass reads against the base level.
- **The install guide gives the Python versions the installer accepts**: 3.12 or newer (it said 3.10), and 3.12 to 3.14 for the
  tested versions. A new section says how long a run takes without an NVIDIA GPU, with the bundled examples timed on both.
- **A copy of a copy is "*name* copy 2"**, not "*name* copy copy", for criteria and studies; a second copy of the same one counts on.
- **Simulation warnings name their study**, as the progress does, since one run can simulate several studies.
- **Leaving Inspect during a restore** says "A restore is under way.", not that a save is.
- **The eighth criterion colour** is a dark red (`#8B2F3C`) instead of a grey close to the context's. A criterion keeps the colour
  it was given, so only new criteria take it.
- The workspace tests no longer print "document is not defined" after they finish: one test opened three workspaces without
  closing the first two.

### Criteria

- **The criterion that holds the run is easy to find.** When Run analysis waits for another criterion's test surfaces, **Open *name*** beside
  the reason shows that criterion with its Test surfaces open, and its card's status line carries a warning sign.

### Inputs

- **Holes in sites.** A site may have holes, closed outlines strictly inside it (a courtyard): the maximum volume and the base
  volume leave them out from the ground to the top. **Draw hole** in a site's editor draws a hole, and an outline nested inside
  another in an imported DXF or OBJ file becomes its hole; holes are edited with the outline and have Delete hole. Sites may no
  longer overlap or lie inside one another: such a change is refused, and an import leaves the overlapping outline out. Overlaps
  a project already has are warned about, and a site lying inside another has Make a hole of.
  Engine: `Site.holes` in `sites.py`.
- **Site step wording.** Every box says in a line what geometry it expects, filled or empty. "Existing surroundings" is
  now **Context** everywhere in the app (the box, From context, the Settings group, the layer). A file row shows its name
  only; its triangle count and, for a test surface set, who uses it are in the remove button's tooltip. The drop line
  reads "You can also drag files onto this box.", and the Sites box no longer repeats the heights set for all sites.
  The boxes come in the order Context, Test surfaces, Terrain, Sites, so the context and the test surfaces picked on it
  come before the site is drawn.
- **No building massing legend.** The 3D view no longer shows the "Building massing, by storey" legend with its
  numbered storey swatches; the massing keeps its storey colours.
- **A removed file is kept.** Removing a file in the Site step (maximum volume, surroundings, terrain, weather, test
  surfaces) takes it out of the project and its calculations; the stored copy moves to `inputs/removed/<role>/` in the
  project folder instead of being deleted, so a removal by mistake is undone by adding the file again. Right after a removal the box offers **Undo**; under the
  boxes, a line says how many removed files are kept, with **Show** to open the folder.
- **A site as the input.** A project makes its maximum volume from mesh files or from **sites**, chosen with two tiles in
  Inputs: closed outlines drawn in the 3D view, each with its own height. The vertices carry the ground's elevation (typed
  after drawing); the ground inside is a smooth membrane on the boundary, and the top is flat at the lowest vertex plus the
  height. Drawing snaps to the first point and to other sites, Shift holds 15 degree steps; vertices are dragged, added on an
  edge and removed; Ctrl+Z undoes. The engine module `sites.py` builds the volume; carving is unchanged.
- Service: `GET`/`PUT /projects/{name}/sites`, `PUT /projects/{name}/max-volume-source`, `GET /projects/{name}/max-volume`.
- **Base height and max height.** A base height keeps everything below it: no criterion carves there, and the carving decides
  only the volume between the base and the max height, so a result reads as what can be built above the current or
  permissible height. In Settings › Heights each height is Global or set per site (a new project starts Global, base 0 m, max 50 m); a mesh maximum volume takes a
  base height as one level above its lowest point. A criterion's card gives the volume kept and the volume built above it. A
  base height change re-runs the carving only.
- Simulate: a study can account for the **Base volume** while the project has a base height (`CheckSettings.geometry`
  `base_volume`, the request's `base_volume_path`).
- 3D view: panning moves the picture and no longer the orbit point, which stays at the compass ring's centre.
- **Test surfaces are sets of the project, in the Site step.** The Site step's **Test surfaces** box lists every set (a file added,
  or faces picked on the surroundings) with the criteria and studies that use it; a criterion's Test surfaces section is one switch
  per set, which replaces its own upload and "Use a file from another criterion". A set stays until it is removed from the box, and
  one in use cannot be removed (`POST`/`DELETE /projects/{name}/inputs/test_surfaces`, `InputFileInfo.used_by`). Run reasons read
  "Choose test surfaces for *name*".
- **Test surfaces picked on the surroundings.** **From surroundings** in the Site step's Test surfaces box picks whole flat faces of
  the surroundings in the view and stores them as a set (`POST /projects/{name}/surface-sets/picked`), turned to face the side they
  were clicked from. Picked sets keep their picks (**Edit picks**) and are built again when the surroundings change. Every set is
  shown by a name, which **Rename** changes (`PUT .../surface-sets/{file}/name`).
- **Update the carving as I change its settings** moved from each criterion's Carving rule to Settings > Carving, kept in
  the project (`project.json` `carving_updates_itself`, `PUT /projects/{name}/carving-updates`) instead of the browser. The
  view's Out of date stamp in Carve has the run that brings the results up to date (Update carving or Run analysis); it never
  runs studies.
- **Rays per sky patch is a project setting**, in Settings under More detail settings, shared by every criterion and the
  studies (engine: `chain_config.SHARED_MODE_SETTINGS`; a chain file sets it at the top level). A project that kept it per
  criterion takes the value of its first criterion that is on.
- Simulate: a study on the base volume of a project whose base height was set back to 0 says it waits ("Set a base height in
  Settings") at once, also when the change was made in Settings while Simulate was open, and its Account for choice says so.
- **Inputs is now the Site step**, and holds the site's geometry only: the weather file moved to Settings, in a **Location**
  group with North direction. A missing weather file says "Add a weather file in Settings to run ..." with **Open settings**.
  The Settings button's tooltip names the weather file's location.
- **Set up the project.** Create project opens a three-page setup window: Location (weather file and north), the site's way in
  (Sites or Maximum volume) and Heights. Start opens the Site step, drawing the first site after Sites; Skip setup closes it.
- **Importing sites.** **Import** in the Sites box reads the closed polylines of a DXF or OBJ file (2D or 3D, in blocks,
  in the drawing's units) as sites. Elevations are taken relative to the file's lowest vertex and placed at the level drawn
  sites start at, so survey elevations do not move the model. A window shows what was found and left out before anything is
  added. An imported site keeps its original outline (**Restore original**). **Place on terrain** sets a site's vertices to
  the terrain's height below them. The draw button reads **Draw**. Engine: `outlines.py` (new dependency `ezdxf`). Service:
  `POST /projects/{name}/outlines`, `POST /projects/{name}/terrain-heights`, `SiteJson.original`.
- **DXF mesh inputs.** Every mesh input (maximum volume, surroundings, terrain, test and study surfaces) takes DXF files:
  `3DFACE`, polyface and polygon-mesh polylines and `MESH` entities, in the drawing's units (`io.load_mesh`).
- Input boxes: the action (Add files, Replace, Draw) is at the right of the title in every box, empty or not; "Optional"
  is a muted line under the title in place of "(optional)" and "Required". The box of drawn sites is titled **Sites**.
- Engine: `kept_volume_path`, a shared setting read by thresholding: the voxels inside the mesh are kept, and the threshold
  and `carve_fraction` act on the other voxels. Service: `PUT /projects/{name}/heights`.

### Simulate

- **Simulate the resulting volumes.** A study accounts for one geometry (**Account for**: nothing, the max volume, the
  envelope or the massing) and can simulate its own facades and roofs, beside the context, the ground and its files, so
  you see how much sun or sky the new building gets. Faces that face down or that another part covers (the top of a floor
  under the next) are left out; a smoothed envelope is sampled triangle by triangle.
- The result card gives the building's points a block of their own, with a table by facing (roofs, north, east, south,
  west) in a fold; the card minimises to its title.
- Each study traces its geometry and the no-build case, not every geometry: the **Geometry bar** and **Difference** are
  gone. Make two studies (**Duplicate study**) to compare two geometries. A study no longer goes out of date when another
  geometry is rebuilt.
- The **ground** a study samples is a disc on the compass circle, not a square around the max volume.
- A study has its own test point **spacing** (More settings), following Carve's until you type one.
- The study's surfaces are one list of switches: its geometry, **Context**, **Terrain** or **Ground**, and each of the
  project's test surface files. A study no longer takes uploads of its own, and switching a file off or deleting a study
  leaves the file in the project.
- By value the colours end by default at the 99th percentile of the values, not the highest one.
- An out-of-date study is drawn in grey, not in muted colours.
- **Faster studies.** A study keeps its test points between runs while its surfaces and spacing are the same (a one-day sun
  hours run on 1.5 million points: 7.5 s to 0.6 s), and writes its values uncompressed. Sun hours have a **Quick count**:
  the sun on every n-th day, at most about 240 positions (seven months in about a second).
- **The sun tool** moved from Simulate's Sun panel to a button in the view's toolbar, in Carve, Simulate and Inspect. It
  shows the sun path and the shadows at a time; the view's count of hours in shade is gone (a Sun hours study replaces it).

### Carve

- **Settings** in the top bar opens the project settings: north, Account for context blocking, the voxel size with its
  grid, and the rays per batch. The **Site and grid** step is gone, so Carve has four steps. The button shows a red **!**
  while one of these settings is to fix, and Run analysis (in Criteria) names Settings with an **Open settings** button.
- Without surroundings or terrain, Account for context blocking is shown greyed out with what to add, not hidden.

### Fixed

- The orbit point stays in the middle of the free part of the view when the window is resized or a panel opens, closes or
  changes size (another workspace). It used to keep the place it had at the last framing, so the camera seemed to turn
  about a point off centre, by up to half the panel's width.

## [0.11.0] - 2026-11-07

### Highlights

- **North turns the sky of irradiance and Solar heating.** In 0.10.0 a North other than 0 left their sky unturned.
- **Python 3.12 or newer, with new packages**: torch 2.14.1, Warp 1.19, numpy 2.5, trimesh 5.2, tested on Python 3.14.
  The results of the examples are unchanged. `setup_env.py` now installs these tested versions by default.
- **Scores count the angle of incidence** in irradiance and Solar heating, and the typical building's room **runs free**
  (no heating or cooling; the sun counts by the degree-hours it removes below a comfort band).
- **App**: the mode is chosen once per criterion, warnings in plain words with a link to their setting, skipped test
  surfaces drawn in the 3D view, typed dates in the analysis period, the camera orbits the compass ring's centre,
  Inspect's panel is named Geometries, and many smaller fixes.

### Upgrading from 0.10.0

- Python 3.10 and 3.11 are no longer supported: install Python 3.12 or newer and run `setup_env.py` again.
- Irradiance and Solar heating scores fall to about 58 to 67 % of before, so a numeric threshold of these modes carves
  less; a carve fraction is barely affected. Typical building weights are calculated again on the next run.
- Projects whose North is not 0 that used irradiance or Solar heating are not marked out of date: run them again.
- Projects made with development builds before 0.10.0 no longer open as chains; recreate them.
- Grasshopper: USC_ZoneOperation has three new inputs (`free_running`, `vent_above`, `vent_ach`); run USC_SyncCanvas.

The full list of changes is in the CHANGELOG at the v0.11.0 tag:
https://github.com/avarth/UrbanSolarCarver/blob/v0.11.0/CHANGELOG.md

### Added

- **Skipped test surfaces** in the 3D view: the Layers menu draws the surfaces a run left out and says why ("8 of 43
  surfaces not protected: 8 not flat"); `GET .../run/skipped-surfaces`.
- **Windows with an altitude** in an explicit archetype (90 for a skylight); weights file schema version 2.
- **Progress of Calculate** in the typical building window, and in a run that calculates the weights first.
- **The model of the simulated weights** in the docs: the 5R1C equations, the archetype rules, the attribution and the
  weights file's format.
- **`setup_env.py` installs the tested versions** from `requirements-lock.txt` (`--latest` takes the newest).
- For developers: import rules checked by import-linter and dependency-cruiser, drawn by `tools/draw_maps.py`; ESLint for
  the app; Ruff in the tests; `tools/check_references.py` and `tools/repo_state.py`.

### Changed

- **Python 3.12 or newer, and new package versions**: torch 2.14.1, Warp 1.19, numpy 2.5, trimesh 5.2, tested on
  Python 3.14. The results of the examples are unchanged.
- **The typical building runs free**: no heating or cooling; the sun counts by the degree-hours it removes below a
  comfort band (benefit) and adds above it (harm), with windows opened for natural ventilation. `conditioned` stays the
  engine's default. Grasshopper's USC_Archetype and USC_ZoneOperation follow.
- **Irradiance and benefit rays count the angle of incidence** to their test surface, as Simulate does. Scores fall to
  about 58 to 67 % of before, so a numeric threshold carves less.
- **One averaged room values the sun for every facade**: the rooms per facade direction are removed.
- **The app**:
  - the mode is chosen once: a new project shows the mode tiles when Criteria opens, and a criterion's Mode section is gone;
  - Solar time-based is named Sun hours and Solar usefulness Solar heating (engine names unchanged); Bliss constant,
    Detailed statistics and Drop mesh fragments left the app, the engine keeps them;
  - warnings of a run in plain words with a link to their setting, the engine's wording folded under them;
  - the balance temperature has one handle while summer overheating is not subtracted;
  - dates and hours of the analysis period can be typed in their bubbles, and the period counts its days and hours;
  - one orbit about the compass ring's centre in every workspace;
  - Inspect's panel is named Geometries, and saving turned surfaces says which criteria went out of date;
  - fewer numbers on the carving; the last run's time in the top bar; clearer labels and help.
- The simulated weights take about 4 s instead of 7 s, with the same numbers.

### Removed

- Support for projects of development builds before 0.10.0.
- The service routes `POST /projects/{name}/carve-further` and `PUT /projects/{name}/config`, the `criterion` query of
  `GET /projects/{name}`, and test surfaces as a project input (they go to a criterion or a study).
- The settings `score_rule` and a typical building's `by_direction`, now refused on read.

### Fixed

- **North now turns the sky of irradiance and benefit**: every `north_deg` used to get the sky of north 0. Run projects
  with a North other than 0 again.
- A NaN score no longer carves its neighbours through the score smoothing.
- A cancelled or failed run keeps the criteria it finished.
- Flat test surfaces with sliver triangles are sampled.
- A result file that is gone, or cannot be read, says so and makes its stage missing, in place of an empty layer or a
  stuck project.
- Simulate: patches drawn in the wrong place on some turned panels, stripes with the test surfaces shown, legend ends
  that could meet, a colour range kept after the study settings changed.
- A chain run of preprocessing alone that leaves the last criterion out no longer fails; a criterion turned back on
  shows its result again; `carve_above_applied` is false with nothing left to decide.
- The New building example's roofs no longer have a bottom.
- The Criteria bar offers only the run the project needs; the browser tab has an icon.

## [0.10.0] - 2026-10-30

### Highlights

- **Browser app** (`usc ui`): projects with their inputs, a Carve workspace (criteria, carving rule with a histogram,
  envelope and building massing, export), a Simulate workspace (studies of sun hours, irradiance, daylight and useful
  solar gains on any test surfaces, the sky dome, a Sun panel with sun paths, shadows and hours in shade) and an Inspect
  workspace (input files, face normals, turning faces). Light and dark themes.
- **Chained carvings**: several criteria, each with its own test surfaces and mode, carved one after another.
- **Context and terrain**: existing surroundings and the ground block sun and sky in every mode and client.
- **Energy-weighted Solar usefulness**: hours weighted by what their sun saves a typical building in heating, from a
  simple hourly model of one room; a library of typical buildings with example buildings.
- **Building massing** on floor plates, also on sloped ground.
- **Sky sampling**: several jittered rays per sky patch (`rays_per_patch`), removing banding far from the test surfaces.
- **Time basis** for time-based mode: standard, daylight saving or solar time.
- **Test point access evaluation** in the Python API; cold period preset from the weather file; scores in kWh or m².

The full list of changes is in the CHANGELOG at the v0.10.0 tag:
https://github.com/avarth/UrbanSolarCarver/blob/v0.10.0/CHANGELOG.md

### Added

- **Browser app** (`usc ui`; `--port`, `--projects-folder`, `--no-browser`, `--device`), the optional `ui` extra that
  `setup_env.py` installs unless `--no-ui` is given; `start-urbansolarcarver.bat` and `.sh` start it. The service
  listens on `127.0.0.1` with a per-launch token. A project is a folder under `~/UrbanSolarCarver/projects` (by
  default) with `inputs/`, `project.json`, `run/` and a `config.yaml` that `usc run -c` runs. Typical buildings are kept
  in `~/.urbansolarcarver/typical_buildings/`. See [Browser UI](docs/ui.md).
- **Chained carvings.** A config with a `criteria:` list carves criteria one after the other on one grid, each with its
  own mode, test surfaces, mode settings and carving rule; each decides only among the voxels the one before kept.
  - `usc run -c chain.yaml` and `run_chain(chain, out_dir, produce, start_from, context)` write
    `<out>/criteria/<id>/preprocessing` and `.../thresholding`, then `<out>/exporting` and `<out>/massing`.
    `load_config` refuses a chain file; `load_chain` and `ChainConfig` are in `chain_config.py`.
  - One step at a time: `thresholding(..., after=...)`, `usc thresholding --after <folder or manifest>`, and the `after`
    input of USC_ThresholdStage.
- **Context and terrain** (`context_path`, `terrain_path`): context removes the voxel columns it overlaps, terrain the
  voxels below the ground, and rays that hit either are dropped before scoring (`context_blocks_rays`, default on).
  Also on USC_Preprocess, USC_RunPipeline and USC_RaySettings.
- **Floor-plate massing**, stage 4 (`usc massing`, USC_Massing, USC_MassingSettings): floors of square modules
  (`ground_floor_height` 5 m, `floor_height` 3 m, `min_plate_dimension` 3 m, `plate_tolerance` 0.2, `plate_stacking`),
  written as `plates.json`, `plates.obj` and the plates in `final_mesh_format`.
- **Simulated weights for benefit mode.** `usc simulate-weights` and `generate_simulated_weights` run an ISO 13790
  simple hourly (5R1C) model of an archetype (`usc archetype`, `configs/archetype_example.yaml`) and write
  `simulated_weights.json` with hourly `benefit[t]` and `harm[t]`. Benefit mode reads it with `simulated_weights_path`
  in place of the balance rule. Grasshopper: USC_Archetype, five USC_Zone* feeders, USC_SimulateWeights. Tutorial 5.
- **New settings.** `rays_per_patch` (1, 4, 9 or 16) in the weighted modes. `time_basis: standard | daylight_saving |
  solar` for `time-based`. `edge_taper` (weighted modes) and `min_sky_elevation_deg` (`radiative_cooling`). `threshold`
  also takes `{method, value}` (`carve_fraction`, `headtail`, `cutoff`), `analysis_period` one Ladybug mapping.
- **Python API.** `run_pipeline(config, out_dir, produce=("exporting",), start_from="preprocessing", context=None)`
  returns a `PipelineResult`; `build_config(values)`; errors derived from `UrbanSolarCarverError` (`ConfigError`,
  `InputError`, `StageChainError`, `RunCancelled`); a `RunContext` with progress, `cancel()` and issues that replace
  `warnings.warn`; `test_point_access_evaluation`, `urbansolarcarver.cold_period` and `urbansolarcarver.grid_planning`.
- **CLI and daemon.** `usc run --produce` and `--start-from`, `usc warmup [-d cpu|cuda]`, the daemon's `run` and
  `simulate_weights` requests, a session cache kept between daemon commands (1 GiB). Thresholding writes
  `scores_compared_with_cutoff.npy`. A Golden, CO EPW ships in `examples/weather/`; USC_SyncCanvas updates a canvas.

### Changed

- **Weighted-mode scores are in physical units (results change).** `irradiance` and `benefit` in kWh (they were
  labelled Wh/m²), `daylight` and `radiative_cooling` in m² of hidden sky, `time-based` in m²·h (it was a ray count).
  A numeric `threshold` must be chosen again: at 0.5 m spacing an earlier `irradiance` score is 4 times the new one,
  `daylight` about 17 times. `carve_fraction` and `headtail` do not depend on the scale.
- **New defaults (results change).** `grid_step` unset samples at half the voxel size (was 1.0 m; a run takes about
  twice as long). `rays_per_patch` 4 (`1` gives earlier scores). `sun_steps_per_hour` 12 (the sun was sampled hourly).
  `ray_length` 3000 m (was 300 m). `carve_above` `true` (was `false`). `balance_temperature` 15 °C (was 20).
- **Thresholding (results change).** Rules and retention count occupied voxels only (empty cells held 60-80 % of the
  score mass). `carve_fraction` counts what `carve_above` removes: 0.4 before is about 0.55 now. `carve_above` ignores
  empty cells and no longer refills short runs. The new `max_slope_deg` (75 degrees in the weighted modes, `90` off) caps
  each column's rise over its neighbours.
- **Ray rules (results change, all modes).** A voxel obstructs a test surface only when wholly in front of it, and a
  surface no longer counts the boundary voxels of its own mass. `tilted_plane` removes all mass above the plane, not a
  band, and turns the plane around convex corners. On the CPU the same Warp kernel as on CUDA runs (the old marcher
  skipped up to about 37 % of voxels; `full_blocks` daylight 101 s to 5.8 s, score +61 %).
- **Benefit mode (results change).** The weights are the irradiance of the hours below `balance_temperature -
  balance_offset` (they were Ladybug's benefit minus harm, clipped at zero); `include_harm: true` subtracts hot hours.
  `balance_offset` must be `>= 0`.
- **Stage chain.** Manifests carry `run_id` and `upstream_run_id` in place of `hash` and `upstream_hash`; a stage whose
  upstream is missing or from another run raises `StageChainError`. `PreprocessingResult.hash` and
  `ThresholdingResult.hash` are `run_id`, `ThresholdingResult.upstream` is `upstream_run_id`. Manifest paths are
  relative, so run folders can be moved. A stage deletes its old outputs first; a config whose `mode` differs from the
  run's raises `StageChainError`.
- **Errors and modules.** Some `FileNotFoundError` and `RuntimeError` are now `InputError`, `StageChainError` or
  `ConfigError` (`ValueError` subclasses); `load_mesh` raises `InputError`. `grid.py` is split into
  `surface_sampling.py`, `voxelization.py` and `meshing.py`, `raytracer.py` into `warp_kernels.py` and
  `ray_tracing.py`.
- **Diagnostics keys.** `voxels_carved` is `voxels_retained`, `voxels_total` is `voxels_occupied`,
  `normalized_score_stats` is `occupied_score_stats`, `upstream_hash` is `upstream_run_id`; `threshold_method` reports
  `cutoff` for `numeric`. The `diagnostics` flag, unused before, now adds the detailed score statistics (median, standard
  deviation, percentiles).
- **Relative paths** in a YAML resolve against its folder, not the working directory (USC_Config: the `.gh` file).
- **Grasshopper.** Stage components send the daemon's `run` command and read their upstream from `<out_dir>/<stage>`;
  issues show as warnings; daemon calls time out; geometry passes in double precision; all `.ghuser` files are rebuilt.
- **Speed.** Full pipeline on a 306³ grid (daylight, CPU) 112 s to about 34 s; sky weights and EPW files are cached.

### Removed

- `ground_reflectance` (it never affected results; a config with it fails validation), `configs/user_config.yaml` and
  the dotted `a.b=c` override form.
- The `cuda` extra, the daemon's `--authkey` option and USC_RunPipeline's subprocess fallback.
- The fixed-step fallback tracer: without a working Warp the carvers raise `WarpBackendUnavailableError`.

### Fixed

- **Georeferenced coordinates** keep float64 precision through preprocessing, PLY and GLB export (float32 rounded to
  about 0.5 m at UTM northings).
- **`north_deg`** is honoured by `time-based` and `tilted_plane`.
- **Carving and export.** `headtail` follows Jiang (2013) (its stop rule was inverted); `carve_above` set on USC_Threshold
  had no effect; the trimesh voxelizer placed the grid half a voxel off; the smoothed mesher no longer
  binarizes the SDF or shrinks the mesh.
- **Runs.** Two sky matrices of one weather file no longer read each other's file; a client can no longer stop the
  daemon; the grid size limit is checked before allocation; `setup_env.py` maps CUDA 13 drivers to CUDA wheels.

### Upgrading from 0.9.0

- **Re-run every run folder from preprocessing.** 0.9.0 manifests have no `run_id`, and thresholding, exporting and
  massing refuse them with a `StageChainError` naming the stage to re-run.
- **Expect different results** in every mode. Choose numeric thresholds of the weighted modes again; raise
  `carve_fraction` for a result like 0.9.0's. Set `rays_per_patch: 1` to compare scores, `carve_above: false` to keep
  floating mass.
- **Configs:** remove `ground_reflectance` and dotted overrides; check relative paths and `balance_temperature`.
- **Python:** `result.export_path` is `result.exporting.export_path`; `.hash` is `run_id`; imports from
  `urbansolarcarver.grid` and `urbansolarcarver.raytracer` move; rename the diagnostics keys you read.
- **Install:** drop the `cuda` extra; add `ui` for the browser app; refresh an editable install with
  `pip install -e . --no-deps`.
- **Grasshopper:** restart the daemon (an old one answers "Unknown command: 'run'"), then run USC_SyncCanvas.

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
