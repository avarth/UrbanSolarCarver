# Simulate

A carving protects sun, sky or solar energy on test surfaces. **Simulate** shows how much of it reaches each test point once the maximum volume stands (before) and once the carved envelope or the building massing stands (after), so you can see whether the carving did what it should. It is a quick check while designing, inside the browser UI. It traces triangle meshes, not voxels, and it does not replace a check of the finished design with an external tool.

Simulate is a workspace beside the pipeline. It changes no criterion, no shared setting and no pipeline step, and it starts nothing by itself: a study runs only when you press **Run**.

## Design and Simulate

The switch **Design | Simulate** in the header, next to the project name, changes the workspace. Simulate hides the steps and gives the 3D view the whole window. Design shows the step you left, with its folds and scroll position. The Layers menu and the viewer tools are the same in both. The context and the terrain are drawn in Simulate; the test surfaces of criteria and of other studies are not, only those of the selected study.

## Studies

A study is a metric on test surface files over a period. The **Studies** panel floats over the top left of the 3D view and collapses to an icon. Each row has a colour swatch, the study's name and one line: its test surface files while its result is current, otherwise **Out of date**, **Not run yet** or the reason it cannot run (for example **Add test surfaces**). Pressing a row selects the study for the view: **one study is on the view at a time**, and its test surfaces are the ones coloured. The settings button of a row opens its popover.

**Add study** offers two kinds of entries in one menu:

- **Like *criterion name*** makes a study from a criterion: the metric of its mode (see the table below), its period, the mode settings the metric reads and a copy of its test surface files. No link to the criterion is kept; changing the criterion later does not change the study.
- A **metric** makes a study with the metric's default period and no test surface files. A metric that needs the weather file is greyed until the project has one.

The popover of a study holds:

| Control | Meaning |
|---|---|
| Name | A study is named from its metric and period, for example "Sun hours, 21 Dec" or "Useful solar energy, 15 Oct to 15 Apr". Typing a name keeps it from then on |
| Metric | One of the metrics below. Changing it resets the settings to those of the new metric and keeps the values both metrics have |
| Analysis period | The same control as in the Criteria step. Shown for the metrics that sum over a period |
| More settings | The few settings the metric reads: balance temperature, dead band and harm for useful solar energy; dew point and Bliss coefficient for the cooling sky; the time basis (standard, daylight saving or solar time) for sun hours |
| Test surfaces | The files the study uses. You can add new files (button or drop) or use a file the project stores already, for example a criterion's. A stored file is kept while a criterion or a study lists it and goes to the recycle bin when none does |
| Delete study | Removes the study and moves its results to the recycle bin. Its number is not used again |

Every change is saved at once. The studies are stored in `project.json` under `studies`, apart from the criteria. They cannot be changed while a Design run or a simulation is going.

## Metrics

Each carving mode has a metric of the same quantity, which "Like *criterion*" takes. Any metric whose inputs exist can be chosen for a study.

| Metric | Unit | Carving mode it matches | Weather file |
|---|---|---|---|
| Sun hours | h | Solar time-based | needed |
| Solar energy | kWh/m² | Solar energy | needed |
| Useful solar energy | kWh/m² | Solar usefulness | needed |
| Overcast sky component | % | Daylight | not needed |
| Cooling sky | % | Night cooling | not needed |
| Sky view factor | % | Angle rule | not needed |

- **Sun hours**: hours of direct sun in the period. Each hour counts the sun position of that hour, and a position counts 1 h when it is above 5° altitude and in front of the test surface (no cosine of incidence). The 5° is the same for every study: "Like *criterion*" does not copy the minimum altitude of a time-based criterion, so a study counts the sun above 5° whatever the criterion's minimum altitude. The time basis says which clock the hours are read in; it is a setting of sun hours only. A new study starts at 21 December, 10 to 14 h.
- **Solar energy** and **Useful solar energy**: direct and diffuse energy that reaches the surface in the period, from the weather file's Perez sky and the cosine of incidence. Useful solar energy counts the hours that need heating, with the balance temperature, dead band and weights of Solar usefulness. Ground reflection is left out. A new study starts with the whole year (solar energy) or 15 October to 15 April, 7 to 19 h (useful solar energy).
- **Overcast sky component**: light from a CIE overcast sky. On a vertical facade this is the vertical sky component, at most 39.6 %.
- **Cooling sky**: the long-wave cooling potential toward the clear night sky that the surface sees, from the dew point and the Bliss coefficient.
- **Sky view factor**: the cosine-weighted share of the view taken by the sky. An unobstructed horizontal surface has 100 %, an unobstructed wall 50 %.

The three sky metrics are a percentage of what an unobstructed horizontal surface receives. Study names, units and the per-study defaults are listed by `GET /projects/{name}/studies`.

## What Simulate fixes

These choices are not settings:

- **Sky**: Tregenza's 145 patches. Each patch is traced with jittered sub-rays, as the carving traces them, at the project's rays per patch (the value of the first criterion that is on, 4 when the project has no criterion). One ray per patch would leave gaps of about 12° between the rays and show banding.
- **Sun**: one position per hour.
- **Test points**: sampled on the study's test surfaces at the carving's spacing (the grid step of the shared settings, else half the voxel size). A study with more than 2 million test points is refused, and the message gives the spacing that fits.
- **Blocking**: the context and the terrain of the project block in every geometry.
- **North and ray length** come from the shared settings.

## Geometry

The geometry switch at the top centre of the view chooses what the values are shown on. While a study's settings are open it moves to the right of the popover, and on windows narrower than 1000 px it sits at the top right, with the popover under the studies panel:

| Geometry | What blocks |
|---|---|
| **Max volume** | The maximum volume mesh as you added it (not its voxels) |
| **Envelope** | The envelope mesh that **Build envelope** wrote, clipped by the maximum volume |
| **Massing** | The building massing mesh, clipped by the maximum volume |

The context and the terrain block in all three. With several criteria the envelope is the result of the whole chain. **Envelope** and **Massing** wait, with the reason as a tooltip, until Design has built them, and also when the selected study ran before they were built (the tooltip says to run the study again). A geometry that Design shows out of date is marked; Simulate still traces the mesh on disk.

**Change** colours each test point by its change from the maximum volume (the baseline) on the geometry shown: gains on a ramp from no change to the largest gain, losses in the colour the carving uses for carved voxels, a change smaller than a thousandth of the highest value without any geometry as none. Change waits while Max volume is shown.

## Run

**Run** runs every study that can run, for every geometry that is built: the maximum volume always, the envelope and the massing when they exist. Switching the geometry afterwards needs no new run. A study that cannot run says why on its row (no test surface files, no maximum volume, no weather file for a metric that needs one, a setting the engine refuses). One that the engine refuses, for example for too many test points, keeps its message until its inputs change, and the other studies still run.

There is one job at a time. While a Design run is going, Run shows "A Design run is in progress" and waits; while a simulation is going, Design's run buttons say so. Nothing is queued. The progress shows under Run with a Cancel button.

## The legend, the target and the result card

The legend along the bottom of the view shows the selected study's scale in its unit: cividis from 0 to the highest value of the geometry shown. In the Change view it shows the change ramp, and the loss colour when some point lost.

The **target** is a mark on the legend. Drag it, or focus it and use the arrow keys (1 % of the range), Page Up and Page Down (10 %) and Home and End; Delete clears it. The target is saved with the study, once per drag. Points below the target are drawn in one muted colour of their own, apart from the scale. The target does not apply to the Change view.

The **result card** in the bottom right corner is for the selected study on the geometry shown. It gives:

- the mean,
- the lowest tenth (10th percentile),
- with a target, the share of points at or above it.

On Envelope and Massing each line has the maximum volume's value in brackets, for example "mean 3.6 h (4.1)".

## Out of date

A result is **out of date** when any of these changed since it was computed: the study's settings (including its metric and period), its test surface files, the weather file, the context, the terrain, the maximum volume, or the envelope or massing mesh it traced (including one built or removed). The surface tolerance of the envelope and massing, which follows the voxel size they were built with, counts too. So do the shared settings a study reads: north, the ray length, the test point spacing (the voxel size and the grid step) and the rays per patch of the first criterion that is on. Turning a criterion on or off in Design can therefore make every study out of date. The result stays on the view, dimmed, with the **Out of date** stamp at the top of the view, and the row says "Out of date". Nothing reruns by itself: press **Run**. Moving the project folder does not make a result out of date. Changing the target does not either.

## Where the results are kept

Each study's results are in `<project>/simulate/<study number>/`:

| File | Content |
|---|---|
| `check_points.npz` | The test points, their normals, the corners of the square patch each draws and the frame the coordinates are relative to |
| `check_values.npz` | One value per point for each geometry (`open` with no geometry, `max_volume`, then `envelope` and `massing` when traced) |
| `check_summary.json` | The metric, unit, settings, and for each geometry its mesh, triangle count, surface tolerance and statistics, and what the result was computed from. It is written last, so a folder without it has no result |
| `refusal.json` | Only for a study the engine refused: the message and the inputs it was refused with |

Reopening the project shows the last results. The studies also use `inputs/joined/study_surfaces_<number>.ply`, the joined test surface file of a study, beside the criteria's.

The service routes are under `/projects/{name}/studies` and `POST /projects/{name}/simulate`; the engine request is `check` (see [Engine requests](api/engine-requests.md#commands)).

## Not there yet

These belong to a later milestone:

- studies on other designs (meshes added for Simulate only),
- snapshots of results,
- CSV export of the values,
- side-by-side views with linked cameras,
- a command-line command and a Grasshopper component for the check.
