# Simulate

A carving protects sun, sky or solar energy on test surfaces. **Simulate** shows how much of it reaches each test point once the maximum volume stands (before) and once the carved envelope or the building massing stands (after), so you can see whether the carving did what it should. It is a quick check while designing, inside the browser UI. It traces triangle meshes, not voxels, and it does not replace a check of the finished design with an external tool.

Simulate is a workspace beside the pipeline. It changes no criterion, no shared setting and no pipeline step, and it starts nothing by itself: a study runs only when you press **Run**.

## Design and Simulate

The switch **Design | Simulate** in the header, next to the project name, changes the workspace. Simulate hides the steps and gives the 3D view the whole window. Design shows the step you left, with its folds and scroll position. The Layers menu and the viewer tools are the same in both. The context and the terrain are drawn in Simulate; the test surfaces of criteria and of other studies are not, only those of the selected study.

The **Sky dome** layer (Layers menu, off at first) is the selected study's, not Design's: each of the 145 sky patches coloured by the value it carried in the study's last run, the solar energy of the period from that patch for Solar energy and Useful solar gains (kWh/m²), its weight of the overcast sky, the night sky cooling or the sky for the three sky metrics. It changes with the study selected and is dimmed with it when the study is out of date. A sun hours study traces sun positions, not patches, so it has no dome; nor has a result run before the patch values were kept, until it is run again.

## Studies

A study is a metric on test surface files over a period. The **Studies** panel floats over the top left of the 3D view and collapses to an icon. Each row has a colour swatch, the study's name and one line: its test surface files while its result is current, otherwise **Out of date**, **Not run yet** or the reason it cannot run (for example **Add test surfaces**). Pressing a row selects the study for the view: **one study is on the view at a time**, and its test surfaces are the ones coloured. When none is selected, the first study with a result is (or the first study), so a finished run shows its values without a press. The settings button of a row opens its popover.

**Add study** offers two kinds of entries in one menu:

- **Like *criterion name*** makes a study from a criterion: the metric of its mode (see the table below), its period, the mode settings the metric reads and a copy of its test surface files. No link to the criterion is kept; changing the criterion later does not change the study.
- A **metric** makes a study with the metric's default period and no test surface files. A metric that needs the weather file is greyed until the project has one.

The popover of a study holds:

| Control | Meaning |
|---|---|
| Name | A study is named from its metric and period, for example "Sun hours, 21 Dec" or "Useful solar gains, 15 Oct to 15 Apr". Typing a name keeps it from then on |
| Metric | One of the metrics below. Changing it resets the settings to those of the new metric and keeps the values both metrics have |
| Analysis period | The same control as in the Criteria step. Shown for the metrics that sum over a period |
| More settings | The few settings the metric reads: balance temperature, dead band and harm for useful solar gains; dew point and Bliss coefficient for the cooling sky; the time basis (standard, daylight saving or solar time) for sun hours |
| Test surfaces | The files the study uses. You can add new files (button or drop) or use a file the project stores already, for example a criterion's. A stored file is kept while a criterion or a study lists it and goes to the recycle bin when none does |
| Delete study | Removes the study and moves its results to the recycle bin. Its number is not used again |

Every change is saved at once. The studies are stored in `project.json` under `studies`, apart from the criteria. They cannot be changed while a Design run or a simulation is going.

## Metrics

Each carving mode has a metric of the same quantity, which "Like *criterion*" takes. Any metric whose inputs exist can be chosen for a study.

| Metric | Unit | Carving mode it matches | Weather file |
|---|---|---|---|
| Sun hours | h | Solar time-based | needed |
| Solar energy | kWh/m² | Solar energy | needed |
| Useful solar gains | kWh/m² | Solar usefulness | needed |
| Overcast sky component | % | Daylight | not needed |
| Cooling sky | % | Night cooling | not needed |
| Sky view factor | % | Angle rule | not needed |

- **Sun hours**: hours of direct sun in the period. Each hour counts the sun position of that hour, and a position counts 1 h when it is above 5° altitude and in front of the test surface (no cosine of incidence). The 5° is the same for every study: "Like *criterion*" does not copy the minimum altitude of a time-based criterion, so a study counts the sun above 5° whatever the criterion's minimum altitude. The time basis says which clock the hours are read in; it is a setting of sun hours only. A new study starts at 21 December, 10 to 14 h.
- **Solar energy** and **Useful solar gains**: direct and diffuse energy that reaches the surface in the period, from the weather file's Perez sky and the cosine of incidence. Useful solar gains count only the hours that need heating (the gains that heat the building; it was called useful solar energy before), with the balance temperature, dead band and weights of Solar usefulness. Ground reflection is left out. A new study starts with the whole year (solar energy) or 15 October to 15 April, 7 to 19 h (useful solar gains).
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

**Change** colours each test point by its change from the maximum volume (the baseline) on the geometry shown: gains in Viridis from no change (dark) to the largest gain (yellow), losses in the colour the carving uses for carved voxels, a change smaller than a thousandth of the highest value without any geometry as none. Change waits while Max volume is shown.

## Run

**Run** runs every study that can run, for every geometry that is built: the maximum volume always, the envelope and the massing when they exist. Switching the geometry afterwards needs no new run. A study that cannot run says why on its row (no test surface files, no maximum volume, no weather file for a metric that needs one, a setting the engine refuses). One that the engine refuses, for example for too many test points, keeps its message until its inputs change, and the other studies still run.

There is one job at a time. While a Design run is going, Run shows "A Design run is in progress" and waits; while a simulation is going, Design's run buttons say so. Nothing is queued. The progress shows under Run with a Cancel button.

## The legend, the colour range and the result card

The legend along the bottom of the view shows the scale the values are coloured by, with a switch between two:

- **Value** in the study's unit (for example kWh/m²), the default: each point coloured by its value.
- **% of no-build**: each point coloured by its share of its **no-build value**, its value with nothing built on the plot (no maximum volume, envelope or massing). The surroundings and the terrain still block, so the no-build value is not a value without any context: it is the most each point can receive in the city as it is. The scale runs from 0 to 100 %, the same for every geometry, so Max volume, Envelope and Massing compare directly. A point that gets nothing in the no-build case (a facade that sees no sun in the period, say) loses nothing, so it counts as 100 %.

A study's values spread mostly with the way each surface faces: on Allatini's Solar energy study the roofs reach about 1,550 kWh/m² while the facades lie between 200 and 800. By value, move the high end down to the facades' range to see their differences (below); by share, every point is measured against its own no-build value, and the maximum volume keeps 78 % of the no-build value there and the envelope 99 %.

**The colour range.** Two marks on the legend set the low and the high end of the colours. The palette runs between them, and a value beyond an end takes that end's colour, so the colours can spread over the values that matter (the facades between 200 and 800 kWh/m², say, rather than 0 to the roofs' 1,550). Drag a mark, or press on the bar to move the nearer one; or focus a mark and use the arrow keys (1 % of the bar), Page Up and Page Down (10 %) and Home and End; Delete puts it back to its default. The ends cannot pass each other. By value the low end is the study's **target** and the high end its upper end, both saved with the study (by default 0 and the highest value of the geometry shown); the result card's "at target" counts the points at or above the low end. By share the ends are percentages, 0 and 100 by default, kept for each study while the app is open.

**The palettes** are fixed: Magma by value, Viridis by share and for Change. Both are matplotlib's perceptually even palettes, from dark to light without a grey middle (Viridis is the one most readable with the common colour vision deficiencies), so the two colourings do not look alike. In the Change view the legend shows the change ramp instead, without ends, and the loss colour when some point lost.

The **result card** in the bottom right corner is for the selected study on the geometry shown. It gives:

- what the geometry keeps of the no-build value: the sum of its values over the sum with nothing built on the plot, for example "keeps 99 % of the no-build value (78)",
- the mean,
- the lowest tenth (10th percentile),
- with a target (the low end by value), the share of points at or above it.

On Envelope and Massing each line has the maximum volume's value in brackets, for example "mean 3.6 h (4.1)".

## Out of date

A result is **out of date** when any of these changed since it was computed: the study's settings (including its metric and period), its test surface files, the weather file, the context, the terrain, the maximum volume, or the envelope or massing mesh it traced (including one built or removed). The surface tolerance of the envelope and massing, which follows the voxel size they were built with, counts too. So do the shared settings a study reads: north, the ray length, the test point spacing (the voxel size and the grid step) and the rays per patch of the first criterion that is on. Turning a criterion on or off in Design can therefore make every study out of date. The result stays on the view, dimmed, with the **Out of date** stamp at the top of the view, and the row says "Out of date". Nothing reruns by itself: press **Run**. Moving the project folder does not make a result out of date. Changing the target does not either. A file saved over an input file in the project folder counts as a change once the app has found it (see [Replacing a file in the project folder](ui.md#replacing-a-file-in-the-project-folder)).

## Where the results are kept

Each study's results are in `<project>/simulate/<study number>/`:

| File | Content |
|---|---|
| `check_points.npz` | The test points, their normals, the corners of the square patch each draws and the frame the coordinates are relative to |
| `check_values.npz` | One value per point for each geometry (`open` with no geometry, `max_volume`, then `envelope` and `massing` when traced) |
| `check_sky.json` | The value of each of the 145 sky patches for the study's metric, drawn as the study's sky dome; none for sun hours |
| `check_summary.json` | The metric, unit, settings, and for each geometry its mesh, triangle count, surface tolerance and statistics, and what the result was computed from. It is written last, so a folder without it has no result |
| `refusal.json` | Only for a study the engine refused: the message and the inputs it was refused with |

Reopening the project shows the last results. The studies also use `inputs/joined/study_surfaces_<number>.ply`, the joined test surface file of a study, beside the criteria's.

The service routes are under `/projects/{name}/studies` and `POST /projects/{name}/simulate`; the engine request is `check` (see [Engine requests](api/engine-requests.md#commands)).

## The Sun panel

The **Sun** panel, under the studies panel and collapsed at first (the sun icon opens it), shows the site with the sun as architects study it on a sun path diagram and with shadow drawings, beside the studies. It needs the project's weather file, whose location gives the sun's course; without one it says so. North is the project's, as in the carving.

- **Clock**: the times are read as the weather file's **local standard time**, **local solar time** (noon when the sun crosses the meridian) or **local daylight saving time** (an hour ahead of standard time on every date, as the engine reads it).
- **Sun path of the year and of the day** draws, on the hemisphere around the scene, the sun's arcs on the March equinox (the September one lies within a fraction of a degree of it) and the two solstices (dashed), a line for each whole hour showing where the sun stands at that hour through the year (labelled at its highest point), the day's arc (bold) and, at a moment, the sun.
- A switch then chooses what the view shows besides the sun path, one at a time: **Sun path only**, **Shadows at a time** or **Hours in shade**. Each has its own controls.

**Shadows at a time** is a moment: a day on a year strip (with 21 Mar, 21 Jun, 21 Sep and 21 Dec as presets) and a time on a day strip, each with one handle, as the criteria panel's strips are drawn (drag the handle or press on the strip; the arrow keys move a day or 5 minutes, Page Up and Page Down a month or an hour). The panel says how high the sun stands and its bearing from north, or that it is below the horizon. The scene is lit by the sun at that moment: the maximum volume, the envelope, the massing, the surroundings and the terrain cast shadows on each other, and on the ground where there is no terrain. The sky light is lowered meanwhile, so the shade reads.

**Hours in shade** is a period: the criteria panel's analysis period control, a range of days on the year strip and a range of hours on the day strip (the end hour counted: 8 to 15 h is 08:00 to 16:00; days across the new year and hours across midnight wrap), with its presets. For every surface the view shows it counts how many of those hours the surface spends in shade, on the one day or as a mean per day over the days. A surface is in shade at a time when something stands between it and the sun or it faces away from the sun. **Colours** chooses viridis (yellow in sun all the range, dark in shade all of it) or grey (light to dark). The colours are drawn under the sun path, which stays visible over them.

The hours in shade are a quick count, not a study. They are worked out on the graphics card from the camera: the view is drawn once for each sun position (every 10 minutes on one day, every 30 minutes over several days, on every n-th day when that would be more than 240 positions), and each draw adds the time it stands for where the surface is in shade. So the count is of what the camera sees, at the resolution of the shadow map (4096 pixels across about five times the site's radius), and it is counted again when the camera stops moving. A **Sun hours** study is the precise count, per test point, traced against the meshes.

The **Show** switch beside the studies panel's title hides the selected study from the view (its colours, legend and result card) and shows it again, for a clear view of the shadows or the hours in shade.

The panel reads two routes: `GET /projects/{name}/sun-chart?date=MM-DD&time_basis=` (the arcs of the March equinox, the solstices and `date`, every 5 minutes, and an hour line for each whole hour, a point a week) and `GET /projects/{name}/sun-positions?from=MM-DD&to=MM-DD&start=&end=&step=&time_basis=` (the sun above the horizon every `step` minutes from minute `start` to `end` of each day from `from` to `to`, over the new year when `to` comes first and over midnight when `end` comes before `start`, with its altitude and azimuth; on every n-th day, `day_step`, when that would be more than 240 positions). `time_basis` is `standard` (the default), `solar` or `daylight_saving`. Both answer 404 without a weather file.

## Not there yet

These belong to a later milestone:

- studies on other designs (meshes added for Simulate only),
- snapshots of results,
- CSV export of the values,
- side-by-side views with linked cameras,
- a command-line command and a Grasshopper component for the check.
