# Local web UI for UrbanSolarCarver: UX design (milestone 1)

- Date: 2026-10-17
- Status: approved by the user on 2026-10-17, including section 14 (service and engine changes).
- Technical spec: `2026-10-16-local-web-ui-design.md` (approved). This document replaces its section 7 ("Browser app flow") and the screen parts of section 6; section 14 below lists the changes it needs in the technical spec and in plan Tasks 1 to 8.
- Plan: `docs/superpowers/plans/2026-10-16-local-web-ui.md`. Tasks 9 to 12 are rewritten from this document after it is approved.
- Mockups from the design session: `.superpowers/brainstorm/` in the worktree (not committed). High-fidelity screens follow in Claude Design after approval (section 17).

Marking used below: **(user)** for what the user decided in the design session, **(proposed)** for a call made by the designer that the user has not confirmed. Unmarked statements follow from the technical spec or from the engine.

## 1. Who it is for and why

Designers, planners and researchers who use neither Grasshopper, nor notebooks, nor the command line, and who find the number of settings hard to face. The CLI, Grasshopper and notebooks remain the tools for heavy or automated work; the browser UI is for exploring one site at a time **(user)**.

The work pattern it serves **(user)**: bring geometry made in another program, look at it, pick a mode, set the few controls that matter, run the analysis, then stay on the voxel result and adjust the threshold until the carving looks right. Only then build the envelope mesh and the building massing, and export them back to the design tool.

Success: at every moment the user can see which mode they are in, which few controls matter for it, and what their last change did, in the 3D view and in numbers.

## 2. Goals, non-goals, anti-goals

Goals:

1. A first-time user opens an example, runs it and understands the result without reading the docs.
2. Mode choice is visible and distinct: tiles with a symbol, a plain name and a one-line description **(user)**.
3. Important controls are in view; advanced settings are folded but one click away **(user)**.
4. The threshold can be adjusted with direct feedback: voxel view, histogram with the cutoff, share of volume kept and carved **(user)**.
5. Every setting has a plain label, a unit and a tooltip that also gives its config name **(user)**.
6. The 3D view gives a sense of scale and orientation: compass, ground grid from 10 m out to 1 km, scale bar, axes **(user)**.

Non-goals for milestone 1 (each listed in section 16):

- Geometry checks and diagnosis of imported files.
- Simulated benefit weights (upload or generation).
- Ghost planes for the angle rule.
- Comparison with earlier runs, snapshots or run history.
- Time estimates per stage, and CPU timing work.
- Drawing tools.

Anti-goals, things that would make it a failure even if it works:

- The envelope and the building massing are rebuilt after every threshold change. Postprocessing and massing take 13 to 18 seconds on the user's machine and are only wanted once the carving looks right **(user)**.
- Settings appear under their YAML names, or with developer wording ("Taubin polish passes", "Ladybug timestep") as the only explanation.
- The app tries to repair geometry made elsewhere ("geometry doctor") **(user)**.
- Code names leak into the interface: "floor plates" in particular. The stage is "building massing" **(user)**.

## 3. Decisions

| Topic | Decision |
|---|---|
| Overall layout | One page: an accordion of steps in a left panel, the 3D view always on the right **(user)**, chosen over a three-stage layout with a results drawer after both were drawn at the same detail. |
| First screen | A welcome screen that is also the start screen: new project, open project, try an example; it shows the device and the CUDA warm-up status **(user)**. |
| Steps | Inputs, Mode, Settings, Carving, Envelope and massing, Export. The technical spec's "Project" step moves to the start screen; its "Run" step becomes buttons in the steps that run something; its "Review" step splits into Carving and Envelope and massing **(user)**. |
| Two phases | "Run analysis" runs preprocessing and thresholding only. "Build envelope and massing" runs exporting and massing, by an explicit action **(user)**. |
| Threshold loop | Changing the threshold in the Carving step reruns thresholding only. An "Update when I change the threshold" switch (on by default, **proposed**) reruns it automatically; with it off, a button does **(user)**. |
| Out-of-date results | After the carving changes, an existing envelope and massing stay visible, dimmed, and are marked "out of date for the current carving" **(proposed)**. |
| CUDA warm-up | Starts when `usc ui` starts, in the background **(user)**. |
| Mode tiles | Compact 3 × 2 tiles; the longer description, engine name and requirements in a tooltip **(user)**. |
| Weather file | Optional in Inputs; required before running a mode that needs it **(user)**. |
| Setting labels | Plain labels, units and tooltips from a table in `app/` (section 7) **(user** approved the first draft**)**. |
| "Voxel" | Kept as the word in the interface **(proposed)**. |
| Viewport colours | Light viewport by default; a toolbar button switches to a dark viewport; panels stay light **(user** asked for the switch; light default **proposed)**. |
| Simulated weights, ghost planes, snapshots | Milestone 2 or later **(user)**. |
| Engine changes | One, approved by the user on 2026-10-17: thresholding saves the scores it compares with the cutoff (section 14, item 10). |

## 4. Screen structure

```
+--------------------------------------------------------------------------------+
| UrbanSolarCarver   <project name>  [Projects]               (o) GPU ready      |
+---------------------------+----------------------------------------------------+
| v Inputs     summary      | [compass]                              [Layers v]  |
| v Mode       summary      |                                                    |
| > Settings                |                    3D view                         |
|   ...open step content... |                                                    |
|   [ primary action ]      |                                                    |
| v Carving    summary      | [axes]        [ 0 ---- 20 m ]          [legend ]  |
| v Envelope and massing    |                [toolbar: frame, top, light/dark]   |
| v Export                  |                                                    |
+---------------------------+----------------------------------------------------+
```

- **Top bar.** Product name, the open project's name, a "Projects" link back to the start screen, and the device status (section 6.1).
- **Left panel.** Fixed width of 340 px **(proposed)**, its own scroll. One step open at a time. Each closed step shows a one-line summary of its state, so the results of other steps stay readable as text while another step is open.
- **3D view.** Fills the rest. Overlays in the corners: compass (top left), layers menu (top right), axis gizmo (bottom left), scale bar (bottom centre), legend for the colouring on screen (bottom right), a small toolbar (frame all, top view, light or dark viewport). A thin progress bar runs along its top edge during runs.
- **Minimum window.** 1280 × 720 **(proposed)**. Below 1100 px wide the left panel overlays the view instead of pushing it **(proposed)**; phones are not a target.

### 4.1 Steps and their summary lines

| Step | Opens with | Summary when closed (examples) |
|---|---|---|
| Inputs | File boxes per role | "1 volume, 2 test surfaces, weather" or "Test surfaces missing" |
| Mode | Six tiles | "Sun at set hours" |
| Settings | Analysis settings, Run analysis | "21 Dec, 10 to 14 h; 1 m voxels" or "1 setting to fix" |
| Carving | Threshold, histogram, numbers | "61 % kept" or "Not run yet" |
| Envelope and massing | Envelope and massing settings, Build | "4 820 m², 7 storeys" or "Out of date" or "Not built yet" |
| Export | Downloads | "Ready" or "Build the envelope first" |

A step that cannot be used yet is shown but explains why when opened (for example Carving before any analysis: "Run the analysis in Settings to see the carving"). Steps are never locked shut **(proposed)**.

## 5. Steps in detail

### 5.1 Start screen (welcome)

Shown at launch and from the "Projects" link. Content:

- Product name and version.
- Device status line: "Preparing the GPU" while warming up, then "GPU ready: <device name as the engine reports it>". Without one: "No CUDA-enabled GPU found. USC runs on the CPU, which is slower." **(user:** no brand names). If Warp cannot run, the engine's reason and the pointer to `setup_env.py` (technical spec 5.6).
- Three actions: **New project** (asks for a name), **Open a project** (list with name and last modified date), **Try an example** (the three bundled examples, each with a one-line description).

The user can choose a project and add files while the warm-up runs; only the run buttons wait for it, showing "Waiting for the GPU to be ready" **(proposed)**.

### 5.2 Inputs

Three boxes: **Maximum volume**, **Test surfaces**, **Weather file (optional)**.

- Each box: "Add files" (file picker; drag and drop onto the box also works), and the list of files with name, triangle count and a remove button. The weather box takes one `.epw` and shows its location name.
- Each mesh is drawn in the 3D view as it arrives and the view frames all inputs.
- Under the boxes: the size of the joined inputs in metres, and the warning from the technical spec when the longest side is over 10 km or under 1 m.
- The weather box text says which modes need it: "Needed for Sun at set hours, Solar energy and Solar heat when cold."
- Layout leaves room for a "Draw" button next to "Add files" in each mesh box, for milestone 2 **(user)**.
- While a run of this project is active, add and remove are disabled with the reason shown.

### 5.3 Mode

Six tiles in a 3 × 2 grid, each with a symbol, the plain name and one line **(user)**. Hover or keyboard focus shows a tooltip with the longer description, the engine name and what the mode needs; a small "i" on the tile opens the same text by click or touch **(proposed)**. "Experimental" is marked on the Night cooling tile.

| Engine name | Plain name | One line | Tooltip adds | Needs |
|---|---|---|---|---|
| `time-based` | Sun at set hours | Direct sun in a chosen period | Keeps direct sun on the test surfaces during the hours you choose, for example 21 December, 10 to 14 h. | weather file, period |
| `irradiance` | Solar energy | Sun and sky energy over a season | Keeps the sun and sky energy that reaches the surfaces over the period. | weather file, period |
| `benefit` | Solar heat when cold | Sun in hours that need heating | Like solar energy, counting only hours cold enough to need heating. | weather file, period |
| `daylight` | Daylight | Light from an overcast sky | Keeps the view of an overcast sky, for daylight rules and visual comfort. | nothing extra |
| `tilted_plane` | Angle rule | A fixed plane from each facade | Removes everything above a plane at a fixed angle from each facade. | angle |
| `radiative_cooling` | Night cooling | View of the cold night sky | Keeps a flat roof's view of the cold night sky. Experimental; assumes horizontal test surfaces. | dew point |

Symbols **(proposed)**: sun with a clock; sun over heat waves; sun with a thermometer; overcast sky dome; a facade with a dashed angled line; a crescent moon with an upward arrow. Drawn as simple two-colour line icons in the colours of section 10.

Choosing a mode fills its starting values (technical spec 6). If the mode needs a weather file and none is in Inputs, a weather drop zone appears under the tiles; the run buttons stay disabled until it is there.

### 5.4 Settings

The settings the analysis reads (preprocessing settings), in folding groups, essential ones first (section 7 has the full table):

- **When** (sun modes): Analysis period, North direction; folded: Sun positions per hour, Lowest sun protected.
- **Mode specific**: only the current mode's settings; essential: Balance temperature (Solar heat when cold), Plane angle (Angle rule), Night dew point (Night cooling).
- **Detail**: Voxel size essential; folded: Sample spacing, Edge strip with less weight, Ray length, Grid margin.
- **Computer** (folded): Rays per batch, Detailed statistics.

Under Voxel size: the grid it gives ("92 × 64 × 41 = 241 000 voxels"), updated on each change from the `PUT config` reply. A grid over the budget shows the message of section 11 and disables Run analysis.

The step ends with **Run analysis**, pinned to the bottom of the panel while this step is open. It runs preprocessing and thresholding. After a successful run the Carving step opens.

### 5.5 Carving

This is the step the user stays in **(user)**. Content, top to bottom:

1. **Threshold control**, by mode:
   - Sun at set hours: **Shadow tolerated**, in m²·h, a number field with a slider (0 to the score maximum).
   - Solar energy, Solar heat when cold, Daylight, Night cooling: **Carve amount**, in %, a slider from 0 to 100 with a number field. Folded under it: Carving rule (carve amount, automatic split, score cutoff), Score smoothing, Remove everything above a cut, Cut voxels needed to remove above, Steepest step between columns.
   - Angle rule: no threshold. The step says "The angle rule has no threshold: everything above the planes is removed. Change the angle in Settings."
2. **Histogram** of the scores the engine compares with the cutoff, for the occupied voxels, with a vertical line at the cutoff labelled with its value **(user** chose this over a raw-score histogram without a line**)**. The engine does not compare the raw scores: weighted modes blur them first (`score_smoothing`), and with "Remove everything above a cut" each voxel is compared at the cutoff of the lowest cut run below it. Thresholding therefore saves these compared scores (section 14, item 10), and the histogram reads them, so the line falls on the same scale as the bars. Each bar is split into its kept part (accent colour) and its carved part (carved colour) from `mask.npy`, because the slope limit removes some voxels left of the line; a note under the chart says so when that count is above zero: "The slope limit removed 312 voxels below the cutoff." Axis titles: "Shadow tolerated at which a voxel is carved, m²·h" (Sun at set hours) and "Score compared with the cutoff (relative)" (weighted modes) **(proposed)**. The Angle rule has no histogram.

   The y axis can switch between linear and logarithmic; logarithmic by default, since time-based scores pile up at 0 **(proposed)**. Hovering a bar shows its range and its kept and carved counts. The histogram is read only in milestone 1; the control above sets the threshold **(proposed)**. The voxel colours in 3D stay on the raw scores (the score layer and its legend), which keep their physical unit.
3. **Numbers**: Volume kept (%), Volume carved (%), Kept volume (m³), and for the weighted modes Obstruction removed (%), from the thresholding diagnostics (`retention_pct`, `voxels_kept`, `obstruction_fraction_carved`). Plus how long the last analysis took (measured in the browser).
4. **Update when I change the threshold** switch. On: letting go of the slider, or leaving the number field, reruns thresholding. Off: an **Update carving** button appears. If a new value arrives during a thresholding run, the app keeps only the latest value and runs it as soon as the current run ends (the engine checks for cancel only between stages, so cancelling a one-stage run saves nothing) **(proposed)**.
5. **Build envelope and massing**, the step's primary button, pinned to the bottom of the panel.

3D layers in this step: section 8.2.

To change the period, voxel size or mode the user goes back to Settings or Mode and runs the analysis again **(user)**.

**When the analysis itself is out of date** (the mode, an analysis setting or an input changed since the last Run analysis; `stage-status` reports preprocessing `out_of_date`) **(proposed)**: the Carving step shows the last carving dimmed with "Settings changed since the analysis. Run the analysis again to update the carving.", the threshold control and auto-update are disabled, and a Run analysis button is shown in the step. This keeps a threshold change from quietly starting a full analysis, and keeps a new mode's threshold control from being applied to the old mode's scores.

### 5.6 Envelope and massing

Opened by the Build button or directly. Content:

- **Envelope** settings: Smooth the envelope surface (essential); folded: Smoothing passes, Drop pieces smaller than, Drop mesh fragments under.
- **Building massing** settings: Ground floor height, Upper floor height, Bay width (essential); folded: Allowed overhang, Floors rest on floors below.
- **Build envelope and massing** button. It runs exporting and massing, and any earlier stage that is out of date. After a first build, a change to a massing setting reruns massing only, a change to an envelope setting reruns exporting only (the service decides, technical spec 5.5).
- **Results**: Gross floor area (m²), Storeys, Envelope volume (m³), and a table of floor area per storey (storey number, bottom and top height in m, area in m²). From `plates.json` and the massing diagnostics.
- **Run report**: a link that opens `run_report.md` in a panel over the 3D view **(proposed)**.

If the carving changed since the last build, the step's summary reads "Out of date", the results are shown greyed with "Out of date for the current carving", and the envelope and massing layers are dimmed in 3D **(proposed)**.

### 5.7 Export

Download links: carved envelope mesh (in the format chosen here), building massing (`plates.obj` and `plates.json`, shown as "Building massing (OBJ)" and "Building massing data (JSON)"), settings (`config.yaml`), and the whole project as a zip. The mesh format (ply, obj, stl, glb) is chosen here; changing it reruns exporting only. Out-of-date files are labelled as such and still downloadable **(proposed)**.

## 6. Runs and feedback

### 6.1 Warm-up and device status

The service starts CUDA and compiles the Warp kernels in the background when `usc ui` starts **(user)**. The top bar shows a small status dot and text: "Preparing the GPU", "GPU ready", "CPU mode" or "GPU not available" with a link to the reason. The same status appears on the start screen.

### 6.2 What each button runs

| Button | Stages | Opens afterwards |
|---|---|---|
| Run analysis (Settings) | preprocessing, thresholding (preprocessing skipped when its settings and inputs are unchanged) | Carving |
| Threshold change with auto-update, or Update carving | thresholding | stays in Carving |
| Build envelope and massing | exporting, massing, plus any earlier stage that is out of date | stays in Envelope and massing |
| Export format change | exporting | stays in Export |

"Results are up to date" is shown briefly when the service replies that nothing needs to run.

### 6.3 Progress

During a run: the progress bar along the top of the 3D view; in the panel, under the button that started it, the stage names in plain words with a state each (waiting, running, done) and the elapsed time; during ray tracing, the batch count as a fraction. **Cancel** sits next to them. Stage names: "Sun analysis" (preprocessing), "Carving" (thresholding), "Envelope mesh" (exporting), "Building massing" (massing) **(proposed)**.

Results appear stage by stage: the voxel layers update when thresholding ends; the envelope when exporting ends; the massing when massing ends. Until a layer's new data arrives, its previous data stays on screen, dimmed **(proposed)**.

Time estimates per stage are parked until the user runs a performance test **(user)**.

### 6.4 One run at a time

The engine runs one pipeline at a time. While a run is active, the other run buttons are disabled with "A run is in progress"; the settings stay editable for the next run only where the service allows it (technical spec 5.5: uploads and `PUT config` reply 409 during a run of the same project, so those controls are disabled during it).

## 7. Settings: labels, units, help

Each setting shows a plain label, its unit beside the value, and an "i" that opens a tooltip on hover, focus or click. The tooltip has three parts: one or two plain sentences; then "Config name: `voxel_size`, default 1.0 m"; then, for voxel size, the current grid size **(proposed)**.

The labels, units, help texts, step and group placement and essential flags live in `app/src/settings_form/setting_presentation.json` **(proposed)**, next to the tier lists of the technical spec, which it replaces. The engine's own field descriptions stay as they are, for developers. Tests:

- every setting name in the file exists in `UserConfig`, and every `UserConfig` field the form shows appears exactly once (as in plan Task 11);
- each step holds only settings of the matching engine stage: Settings only `PreprocessingSettings` and `RunOptions` fields, Carving only `ThresholdingSettings`, Envelope and massing only `ExportingSettings` and `MassingSettings` (plus `final_mesh_format`, shown in Export).

First-draft table, approved by the user as a starting point. "E" marks essential settings, shown without opening a fold.

| Step, group | Label | Unit | Help (tooltip) | Config name | E |
|---|---|---|---|---|---|
| Settings, When | Analysis period | dates, hours | The dates and hours whose sun or sky is protected. | `start_month` ... `end_hour` | E (sun modes) |
| Settings, When | North direction | ° | Angle of north, clockwise from the model's +Y axis. 0 means +Y points north. | `north_deg` | E |
| Settings, When | Sun positions per hour | per hour | How often the sun is sampled. 12 means every 5 minutes. More is more precise and slower. | `sun_steps_per_hour` | |
| Settings, When | Lowest sun protected | ° | Sun positions lower than this above the horizon are not protected. | `min_altitude` | |
| Settings, Mode specific | Balance temperature | °C | Sun counts only in hours colder than this, minus the dead band. About 12 °C for offices, 18 °C for homes. | `balance_temperature` | E (Solar heat when cold) |
| Settings, Mode specific | Dead band | °C | Hours within this many degrees below the balance temperature do not count either. | `balance_offset` | |
| Settings, Mode specific | Subtract summer overheating (experimental) | on/off | Also counts sun in hot hours against the volume. Results then depend on how much summer the period includes. | `include_harm` | |
| Settings, Mode specific | Plane angle | ° | Angle of the limiting plane above the horizontal: one value, or one per compass direction. | `tilted_plane_angle_deg` | E (Angle rule) |
| Settings, Mode specific | Night dew point | °C | A typical night-time dew point; it sets how cold the clear sky is. | `dew_point_celsius` | E (Night cooling) |
| Settings, Mode specific | Protect sky above | ° | Sky lower than this angle is not protected. 0 protects the whole sky. | `min_sky_elevation_deg` | |
| Settings, Mode specific | Bliss constant | | A physical constant of the sky model. Leave at 1.8 unless you know why. | `bliss_k` | |
| Settings, Detail | Voxel size | m | Edge of the cubes the volume is divided into. Smaller is finer and slower: halving it makes 8 times as many voxels. | `voxel_size` | E |
| Settings, Detail | Sample spacing on test surfaces | m | Distance between the points on the test surfaces that rays start from. | `grid_step` | |
| Settings, Detail | Edge strip with less weight | m | Points this close to a test surface's edge count less, so corners do not force extra carving. Weighted modes only. | `edge_taper` | |
| Settings, Detail | Ray length | m | How far from the test surfaces obstruction is checked. | `ray_length` | |
| Settings, Detail | Grid margin | fraction | Empty space added around the maximum volume. | `margin_frac` | |
| Settings, Computer | Rays per batch | | 0 sizes batches from free GPU memory. Lower it if the computer runs out of memory. | `ray_batch_size` | |
| Settings, Computer | Detailed statistics | on/off | Adds median, spread and percentiles to the run report. | `diagnostics` | |
| Carving | Shadow tolerated | m²·h | How much shade one voxel may cast on the protected surfaces over the period. 0 removes any voxel that casts any shade; 5 allows 5 m² for one hour. | `threshold` (number) | E (Sun at set hours) |
| Carving | Carve amount | % | Share of the total obstruction to remove, not of the volume. Higher gives a slimmer, lower building. | `carve_fraction` | E (weighted modes) |
| Carving | Carving rule | choice | Carve amount (recommended), automatic split, or a cutoff on the raw score. | `threshold` (method) | |
| Carving | Score smoothing | m | Blurs the scores before cutting so the surface is cleaner. Empty means automatic (1.1 × voxel size). | `score_smoothing` | |
| Carving | Remove everything above a cut | on/off | Once a column is cut, everything above it goes too, so nothing floats. | `carve_above` | |
| Carving | Cut voxels needed to remove above | voxels | How many cut voxels in a row start the removal above. 2 or 3 ignores stray single voxels. | `carve_above_min_consecutive` | |
| Carving | Steepest step between columns | ° | Limits how steeply heights may jump between neighbours, turning spikes into ramps. 90 turns it off. | `max_slope_deg` | |
| Envelope and massing, Envelope | Smooth the envelope surface | on/off | Off: a stepped voxel surface. On: a smoothed surface. | `apply_smoothing` | E |
| Envelope and massing, Envelope | Smoothing passes | 0 to 6 | How many polishing passes the smoothed surface gets. | `smooth_iters` | |
| Envelope and massing, Envelope | Drop pieces smaller than | voxels | Loose clusters smaller than this are removed before meshing. | `min_voxels` | |
| Envelope and massing, Envelope | Drop mesh fragments under | faces | Mesh pieces with fewer faces than this are removed. | `min_face_count` | |
| Envelope and massing, Building massing | Ground floor height | m | Height of the ground floor. | `ground_floor_height` | E |
| Envelope and massing, Building massing | Upper floor height | m | Height of every floor above the ground floor. | `floor_height` | E |
| Envelope and massing, Building massing | Bay width | m | The grid the storeys are built from, and the narrowest piece of floor allowed. | `min_plate_dimension` | E |
| Envelope and massing, Building massing | Allowed overhang | % | Share of a bay on a storey that may lie outside the carved envelope. The massing never leaves the maximum volume. | `plate_tolerance` | |
| Envelope and massing, Building massing | Floors rest on floors below | choice | Supported: a bay is built only on a bay below. Free: each storey is decided on its own. | `plate_stacking` | |
| Export | Mesh file format | choice | The file type of the carved envelope. | `final_mesh_format` | E |

Not shown: `mode` (the Mode step), `epw_path` (the weather box), `max_volume_path`, `test_surface_path`, `out_dir`, `device` (set by the service), `diagnostic_plots` (the in-app charts replace them), `simulated_weights_path` (milestone 2).

Values shown as % (`carve_fraction`, `plate_tolerance`) are stored as 0 to 1; the form converts **(proposed)**.

## 8. The 3D view

### 8.1 Scale and orientation aids **(user** asked for these; details **proposed)**

- **Ground grid** on z = 0 of the local origin: 10 m cells, stronger lines every 50 m and 100 m, labels on the 100 m lines, extending to 1 km from the model centre and fading with distance. For a model whose longest side is under 30 m the cells are 1 m and the stronger lines 10 m and 50 m.
- **Compass** (top left): a ring with N, turning with the camera, pointing to north as set by North direction. Clicking it moves to a top view with north up. A small north arrow is also drawn on the ground grid.
- **Axis gizmo** (bottom left): X, Y, Z drawn in three colours and lettered.
- **Scale bar** (bottom centre): a length that adjusts to the zoom so it stays 100 to 200 px long, labelled "0 to 20 m".
- **Legend** (bottom right): for the colouring currently on screen, with its unit.
- **Toolbar**: frame all, top view, light or dark viewport. The viewport choice is remembered on the computer (browser storage).
- **Camera**: orbit with the left mouse button, pan with the right, zoom with the wheel (three.js orbit controls) **(proposed)**. Z up, and the local origin of technical spec 7.

### 8.2 Layers

The layers menu lists only the layers that exist for the current mode and the results so far. A layer whose data is missing is listed with "No result for this stage: the last run stopped before it" (technical spec 7).

| Layer | Shown by default in | Drawing |
|---|---|---|
| Maximum volume | Inputs, Settings | light solid; in later steps a transparent ghost, off by default |
| Test surfaces | Inputs, Settings, Carving | solid, accent colour |
| Kept voxels, coloured by score | Carving | cubes or points, cividis scale (section 10), legend with the score unit: "Shading caused, m²·h" for Sun at set hours, "Obstruction score (relative)" for weighted modes |
| Carved voxels | Carving | the carved colour, about 10 % opacity; option to colour them by score too |
| Sun positions (Sun at set hours) | Settings, Carving | amber dots on a hemisphere around the model; available as soon as a weather file and period are set, before any run **(user** asked for the layer; showing it before a run **proposed)** |
| Sky dome (weighted modes) | Carving | the 145 Tregenza patches on a hemisphere around the model, coloured by patch weight on the sun ramp, with a transparency slider in the layers menu **(user)** |
| Carved envelope | Envelope and massing, Export | light solid with soft edges |
| Building massing | Envelope and massing, Export | one closed body per storey piece, coloured by storey on a light-to-slate ramp, with the storey number on hover |

The hemisphere for the sun positions and the sky dome has a radius of 1.5 times the largest horizontal side of the maximum volume, centred on its footprint **(proposed)**.

Score thinning above 1,000,000 voxels shows "Showing 1 of every k voxels" in the legend (technical spec 5.7).

## 9. Charts and numbers

- Histogram: section 5.5. Drawn in the browser from the score data the service sends; no chart images.
- All numbers use tabular figures, a thin space as thousands separator ("31 400 m³") and the unit after a space **(proposed)**.
- Percentages are rounded to whole numbers in the panel and given to one decimal in tooltips **(proposed)**.

## 10. Visual language

Direction: a light interface around a viewport that reads like a white study model on a site plan. The panels stay quiet; colour in the 3D view always means data **(proposed**, light and dark viewport both accepted by the user**)**.

### 10.1 Colour tokens **(proposed)**

| Token | Value | Use |
|---|---|---|
| `chrome` | `#eef1ef` | page background, number tiles |
| `panel` | `#ffffff` | panels, overlays on the light viewport |
| `ink` | `#1f2a30` | text, icons |
| `muted` | `#5e6b72` | secondary text (contrast 5.6:1 on white) |
| `line` | `#d5dbdb` | borders, dividers |
| `accent` | `#2f5d7c` | buttons, focus, selection, kept bars, test surfaces |
| `accent_soft` | `#e3edf3` | selected tile background |
| `sun` | `#f2b632` | everything sun related: sun positions, sky dome ramp end |
| `carved` | `#c8553d` | carved voxels, carved histogram bars; nothing else |
| `ready` | `#3f8f5a` | device ready, completed step tick |
| `error` | `#a3271c` | error text and field outlines in the panel only |
| `viewport_light` | `#e3e8e7` | light viewport background |
| `viewport_dark` | `#22303a` | dark viewport background |
| `grid_minor` / `grid_major` | `#cfd6d6` / `#a9b4b5` (light), `#2f3e48` / `#4b5d69` (dark) | ground grid |

Score colours: cividis, chosen because it stays readable with colour-vision deficiencies and is perceptually even. Sky dome: a ramp from `viewport` background to `sun`. Storeys: a ramp from `#dfe6ea` to `#2f5d7c`.

### 10.2 Type **(proposed)**

- One family: Atkinson Hyperlegible Next, designed for legibility, bundled with the app (SIL Open Font License) so it works offline.
- Sizes: 14 px body, 12 px secondary (the minimum), 16 px step titles, 20 px key numbers. Line height 1.4. Weights 400, 600, 700.
- Tabular figures for numbers where the font provides them; the builder checks, and if it does not, numbers in tables and key figures use a second bundled family with tabular figures.
- Sentence case everywhere; no all-caps labels.

### 10.3 Shape and spacing **(proposed)**

- Spacing on a 4 px base; panel padding 12 px; gaps between controls 8 px.
- Radius 6 px for steps, tiles and overlays; 4 px for inputs.
- No shadows except overlays on the 3D view and tooltips.
- Motion only in answer to an action (a step opening, a layer fading in), 150 ms; none with reduced motion.

## 11. Empty, error and warning states **(proposed)**

| Situation | What the user sees |
|---|---|
| No inputs yet | 3D view with grid and compass; in the middle "Add a maximum volume and test surfaces to start", an "Add files" button and "or try an example". |
| A file cannot be read (`InputError` on upload) | A message in that file box naming the file and the reason, for example "No triangles found in facade_b.obj". The files already there stay. |
| Size looks wrong for metres | The technical spec's warning under the inputs, in muted text with a warning icon. |
| Mode needs a weather file that is missing | The weather drop zone under the tiles; under the run button "Add a weather file to run this mode". |
| Invalid setting (`ConfigError`, 422) | The message under the field, field outline in `error`; the step summary "1 setting to fix"; under the disabled button the reason. |
| Grid over the budget | Under Voxel size: the voxel count, the budget, and the smallest voxel size that fits ("Use 1.4 m or more"), computed as the current size times the cube root of count over budget, rounded up to 0.1 m. |
| Run failed | In the step that started it: a plain message, a "Details" fold with the error type and the engine's message, and a link to the field when the error names one. |
| Results out of date (`StageChainError`) | "Results are out of date; run the analysis again", with Run analysis enabled. |
| Run cancelled | "Cancelled." Layers whose stage did not finish show the missing-result note. |
| Warnings (issues) during a run | Listed under the step that started the run, with a count in its summary. |
| Engine not reachable | A full overlay: "The USC engine stopped. Start it again with `usc ui`, then reload this page." |
| No CUDA-enabled GPU | Start screen and top bar: "No CUDA-enabled GPU found. USC runs on the CPU, which is slower." |
| Warp cannot run | The engine's reason on the start screen, with the `setup_env.py` pointer. |
| Nothing to rerun | "Results are up to date" for three seconds next to the button. |

Messages say what happened and what to do, in the interface's voice, without apologies.

## 12. Accessibility **(proposed)**

- Every control works with the keyboard; focus is always visible (2 px `accent` outline).
- Mode tiles are one radio group: arrow keys move, Space or Enter selects.
- Tooltips open on hover, focus and click, and close with Escape.
- Text contrast meets WCAG 2.1 AA; colour is never the only signal (carved voxels are also counted, axes are lettered, histogram bars have a cutoff line and counts on hover, out-of-date results are also labelled).
- Text scales with browser zoom up to 200 % without loss; the panel scrolls.
- With `prefers-reduced-motion`, camera moves are instant and no transitions run.
- Step summaries and key numbers are text, readable by screen readers; the 3D view has a text summary of what it shows (layers on, counts) as its accessible name.
- English only and metric units only in milestone 1.

## 13. Naming

| Code or doc term | In the interface |
|---|---|
| preprocessing | Sun analysis |
| thresholding | Carving |
| exporting | Envelope mesh |
| massing, plates | Building massing; a plate is a piece of a storey; per-floor values are "per storey" |
| test surface | test surface |
| maximum volume | maximum volume |
| voxel | voxel |
| EPW | weather file (.epw) |
| modes | the plain names of section 5.3, with the engine name in tooltips |

## 14. Changes needed in the engine, the technical spec and plan Tasks 1 to 8

The UX above needs the following. Items 1 to 9 are service or front-end changes; item 10 is the one engine change. The user approved all ten on 2026-10-17; they are amendments to the technical spec and to plan Tasks 1 to 8.

1. **Two-phase runs and stage status.** The browser sends `produce: ["thresholding"]` for Run analysis and threshold updates, and `["exporting", "massing"]` for Build. `stages_to_rerun` compares settings only and leaves "was this stage ever run" to the caller, so the single `last_completed_run_config.yaml` (technical spec 5.3, 5.5) is not enough: after an analysis-only run, a Build with unchanged settings would be wrongly "up to date". The service keeps, per stage, the config it last completed with, and decides the stages from those. A new `GET projects/{name}/stage-status` replies, per stage, `current`, `out_of_date` (completed, but its settings, an earlier stage or the inputs changed since) or `missing`. It feeds the step summaries and the dimmed layers. Plan Task 5.
2. **Out-of-date outputs stay readable.** The UX shows the previous envelope and massing, dimmed, after a thresholding-only run. Checked during the design review: `run_pipeline(produce=["thresholding"])` touches only the preprocessing and thresholding folders, so `run/exporting` and `run/massing` stay in place. A Task 5 test keeps this true.
3. **Warm-up at launch.** `usc ui` starts a background warm-up (`warp_kernels.warmup_kernels`, as `usc warmup` does), and `GET health` reports `warm_up: running | ready | failed`, the device name, and whether CUDA is available. Importing the service still does not import torch; the warm-up thread does, after start. Plan Tasks 6 and 8.
4. **Sun positions.** `GET projects/{name}/sun-positions`: unit vectors from `sun.get_sun_vectors` for the stored period, `sun_steps_per_hour`, `min_altitude` and `north_deg`, available as soon as a weather file and a period are set. Plan Task 6 (plus a test).
5. **Sky dome.** `GET projects/{name}/run/sky-patches`: the 145 directions (`sky_patches.fetch_tregenza_patch_directions`), solid angles (`tregenza_solid_angles`) and weights (`run/preprocessing/patch_weights.npy`) for weighted modes. Plan Task 4 or 6.
6. **Carving summary.** `GET projects/{name}/run/summary` (or fields in the score-points header): the resolved threshold value, voxels kept and carved, `retention_pct`, `obstruction_fraction_carved` when present, from the thresholding manifest and diagnostics; kept voxels carved by "Remove everything above a cut" and by the slope limit; envelope volume (`envelope_volume_m3` in the massing diagnostics; the exporting manifest does not record it); floor area per storey and total from `plates.json`. Plan Task 4.
7. **Triangle counts.** The upload reply and the file list give a triangle count per file. Plan Task 2.
8. **Default `produce`.** The browser always sends `produce`; the default stays for other clients.
9. **Setting presentation file.** `setting_tiers.json` and `setting_sections.json` of plan Task 11 become `setting_presentation.json` (section 7), with the stage test of section 7. This is front-end only, listed here because Task 11's test file changes.

10. **Engine: thresholding saves the compared scores** (approved by the user on 2026-10-17). `api_core/thresholding.py` writes `scores_compared_with_cutoff.npy`: float32, grid shape, the values the cutoff is applied to (the removal scores when `carve_above` is on, otherwise the scores after `score_smoothing`), listed in the stage's outputs and manifest like `mask.npy`, with an engine test that `(scores_compared_with_cutoff <= threshold_value) & occupied` equals the mask before the slope limit. The slope-limit note under the histogram reads `slope_limit_extra_voxels_removed`, which thresholding already records. The service's score-points reply adds this array (technical spec 5.7). This is an engine task of its own in the plan, done before Task 4, so the guardrail's `NEEDS_ENGINE_CHANGE` stop does not apply to it.

## 15. What this means for plan Tasks 9 to 12

To be rewritten after approval, roughly:

- **Task 9** (scaffold, client, build hash): unchanged in substance; adds the bundled font and the colour tokens as CSS variables.
- **Task 10** (3D viewer): adds the scale and orientation aids, light and dark viewport, the sun positions and sky dome layers, carved voxels as a ghost, storey colouring, dimmed out-of-date layers, and keyboard and reduced-motion behaviour.
- **Task 11** (settings form): `setting_presentation.json` with labels, units, help, step and group placement; tooltips; % conversion; settings split across the Settings, Carving, and Envelope and massing steps.
- **Task 12** (steps): the start screen, the accordion with summaries, the six steps of section 5, the two-phase run buttons, auto-update with cancel and restart, progress, the states of section 11. Its hand check list gains: threshold loop with auto-update on and off, Build after an analysis-only run, out-of-date marking after a threshold change, light and dark viewport, keyboard-only pass.

## 16. Later work, recorded from the design session

- **Geometry checks** (user: after the draft app works; "not a geometry doctor", USC finds and shows, the CAD program fixes). Issues seen in practice: wrong axes from the file format (Y-up against Z-up), world coordinates in the millions, normals facing inward or mixed, linked test surfaces, badly drawn maximum volumes or test surfaces, geometry complex enough to crash the computer. Ideas: test surfaces drawn with their back side in a warning colour and a count of inward faces; the original origin stated; whether each maximum volume body is closed; triangle count and estimated grid before a run; possibly reading a file as Y-up. Where the checks live (service or an engine function such as `inspect_input_mesh`) is open; an engine function needs the user's yes.
- **Simulated benefit weights** (milestone 2, user): level 1, upload `simulated_weights.json` as an input role with a "Which hours count" choice in benefit mode; level 2, generate it in the app from a building form (the archetype, about 15 values, with starting archetypes to be chosen) through the existing `SimulateWeightsRequest`, with a weights chart.
- **Ghost planes for the angle rule** (milestone 2, user): need an engine function that writes the plane geometry.
- **Snapshots or run history** and comparison with the previous result (user: after the draft).
- **Time estimates per stage** and CPU timings (user: after a performance test).
- **Drawing tools** (milestone 2): a "Draw" button next to "Add files" in the mesh boxes.
- **Dragging the cutoff on the histogram** to set the threshold.

## 17. High-fidelity screens

After this document is approved, the key states are drawn in Claude Design: start screen during warm-up, Inputs empty and filled, Mode tiles with a tooltip, Carving in the light and dark viewport, Envelope and massing with results, and one error state. Changes made there come back into sections 10 and 11, so the build depends only on this document. Whether to use the account's ΤΜΧΠΠΑ design system or none is asked at that point.

Build order **(proposed)**: the service (Tasks 1 to 8) can start once section 14 is approved. The front-end tasks may start before the design pass ends: the colour, type and spacing tokens live in one CSS file and the state messages of section 11 in one messages module, so the design pass changes values there without restructuring components.

## 18. Left to the builder

- Exact icon drawings within section 5.3's descriptions.
- Debounce timings (the technical spec's 400 ms for `PUT config` stays).
- How voxels are drawn (instanced cubes or points) as long as 1,000,000 stay interactive.
- Tooltip placement and collision handling.
- Component structure in React, within the plan's file layout.

## 19. Questions settled with the user after the review

1. **Cutoff line for the weighted modes**: the engine saves the compared scores so every histogram has a cutoff line on the right scale (section 5.5, section 14 item 10).
2. **Service amendments**: section 14 approved as listed.
