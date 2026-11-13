# Simulate

A carving protects sun, sky or solar energy on test surfaces. **Simulate** shows how much of it reaches each test point with the maximum volume, the carved envelope or the building massing standing on the plot, so you can see whether the carving did what it should, and how much the new building itself gets, on its own facades and roofs. It is a quick check while designing, inside the browser UI. It traces triangle meshes, not voxels, and it does not replace a check of the finished design with an external tool.

Simulate is a workspace beside the pipeline. It changes no criterion, no shared setting and no pipeline step, and it starts nothing by itself: a study runs only when you press **Run**.

## Carve and Simulate

The switch **Carve | Simulate | Inspect** in the header, next to the project name, changes the workspace. Simulate hides the steps and gives the 3D view the whole window. Carve shows the step you left, with its folds and scroll position. The Layers menu and the viewer tools are the same in all three. The context and the terrain are drawn in Simulate; the test surfaces of criteria and of other studies are not, only those of the selected study.

The **Sky dome** layer (Layers menu, off at first) is the selected study's, not Carve's: each of the 145 sky patches coloured by the value it carried in the study's last run, the solar energy of the period from that patch for Solar energy and Useful solar gains (kWh/m²), its weight of the overcast sky, the night sky cooling or the sky for the three sky metrics. It changes with the study selected and is dimmed with it when the study is out of date. A sun hours study traces sun positions, not patches, so it has no dome; nor has a result run before the patch values were kept: the Layers menu then lists the Sky dome without a check box and says to run the study again.

## Studies

A study is a metric on **study surfaces** over a period. Simulate calls them study surfaces so they are not taken for the test surfaces of the criteria, which Carve protects. The **Studies** panel floats over the top left of the 3D view and collapses to an icon. Each row has a colour swatch, the study's name (whole, on up to two lines; the whole on hover) and one line: what it simulates while its result is current (its geometry when it simulates it, its files, then the project's surfaces it samples, for example "the massing, facades.obj, the context"), otherwise **Out of date**, **Not run yet** or the reason it cannot run (for example **Add study surfaces**). Pressing a row selects the study for the view: **one study is on the view at a time**, with the geometry it accounts for, and its test surfaces are the ones coloured. When none is selected, the first study with a result is (or the first study), so a finished run shows its values without a press. The settings button of a row opens its popover.

**Add study** offers two kinds of entries in one menu:

- **Like *criterion name*** makes a study from a criterion: the metric of its mode (see the table below), its period, the mode settings the metric reads and a copy of its test surface files. No link to the criterion is kept; changing the criterion later does not change the study.
- A **metric** makes a study with the metric's default period and no test surface files. A metric that needs the weather file is greyed until the project has one.

The popover of a study holds:

| Control | Meaning |
|---|---|
| Name | A study is named from its metric and period, for example "Sun hours, 21 Dec" or "Useful solar gains, 15 Oct to 15 Apr". Typing a name keeps it from then on |
| Metric | One of the metrics below. Changing it resets the settings to those of the new metric and keeps the values both metrics have |
| Analysis period | The same control as in the Criteria step. Shown for the metrics that sum over a period |
| More settings | The test point spacing (below), and the few settings the metric reads: balance temperature, dead band and harm for useful solar gains; dew point and Bliss coefficient for the cooling sky; the time basis (standard, daylight saving or solar time) for sun hours |
| Study surfaces | **Account for**: what stands on the plot, a list like the metric's (see [Geometry](#geometry)). **Simulate**: one switch for each surface whose test points the study measures: the geometry it accounts for, the context, and the terrain or the ground (see below), then under **Test surface files** each test surface file the project stores (the criteria's). A study does not take files of its own: add them in the Test surfaces box of the Site step. Switching a file off, or deleting the study, leaves the file in the project |
| Duplicate study | Adds a copy of the study at the end of the list, named "*name* copy": its metric, settings and files, not its results. With it the same metric can be run with the maximum volume in one study and the envelope in the other |
| Delete study | Removes the study and moves its results to the recycle bin. Its number is not used again |

Every change is saved at once. The studies are stored in `project.json` under `studies`, apart from the criteria. They cannot be changed while a carving run or a simulation is going.

Besides its files, a study can simulate surfaces of the project, each with a switch under **Simulate**: the geometry it accounts for, to see how much sun or sky the new building gets; the context and the ground, for example to count the sun hours on the neighbours' facades or on the ground. A study needs at least one surface to simulate:

- **The geometry** it accounts for (named by it: Max volume, Envelope or Massing; greyed for Nothing): the faces of its mesh, without those facing down (its bottom, which stands on the ground, and the soffits of overhangs), and without the parts of faces that another part covers: the massing is one closed block per floor, so the top of each floor under the next is left out while an uncovered terrace is kept; a maximum volume joined from several bodies loses the faces where they touch. The envelope and the massing lose the faces that stand further past the maximum volume than their voxel size (a voxel envelope stands up to a voxel outside the maximum volume along its facades and roofs, and those faces are kept). The envelope is sampled as it was built: a voxel envelope has a flat piece on every step, and the pieces smaller than the spacing give no point. A smoothed envelope, whose triangles are mostly smaller than the spacing, is sampled triangle by triangle instead, about one point per spacing squared of area (placed by a fixed seed, so a run again gives the same points). The setting is `sample_geometry`.
- **Context**: the faces of the context files, without those facing down (the bottoms, which stand on the ground). Each closed body is turned to face out first, so its facades and roofs face away from it. The switch is greyed until the project has surroundings files.
- **Terrain**: the terrain file, turned to face up when most of its area faces down. Offered when the project has a terrain file.
- **Ground**: offered when the project has no terrain. A flat disc at the lowest point of the maximum volume with the centre and radius of the compass ring that the view draws: the middle of the plan of the maximum volume and the project's test surface files together, and 0.75 times their longer side, at least their height. For a 30 m by 50 m maximum volume 20 m high, with no test surface beyond it, the disc has a radius of 37.5 m. The ring and the disc move together when a test surface file reaches further out.

The context and the terrain are sampled face by face (each flat piece of them on its own), and the ground as one panel. They are sampled in the setting `surfaces_from` of the study (`context`, `terrain`, `ground`); choosing or dropping one makes the result out of date. A study that names the context or the terrain while the project has no such file cannot run (**Add surroundings**, **Add a terrain**).

The surroundings still block while they are sampled. A test point on one of their faces starts its rays a centimetre off the face, along the face's normal (the origin offset every test point has), so the face it stands on does not block it, while the rest of its body and the other bodies do. That needs closed bodies, which face out once turned. An open body (a facade without a roof, say) or one whose faces point into it after the turn reads as shaded by itself on the faces that point the wrong way: a point on such a face looks into its own body. The ground or terrain under the bodies sees nothing and gets 0, and those points count in the result card's statistics. The faces of the study's own geometry are traced the same way: a point on its facade does not read its own building as shading it, while the rest of the building does.

## Metrics

Each carving mode has a metric of the same quantity, which "Like *criterion*" takes. Any metric whose inputs exist can be chosen for a study.

| Metric | Unit | Carving mode it matches | Weather file |
|---|---|---|---|
| Sun hours | h | Sun hours | needed |
| Solar energy | kWh/m² | Solar energy | needed |
| Useful solar gains | kWh/m² | Solar heating | needed |
| Overcast sky component | % | Daylight | not needed |
| Cooling sky | % | Night cooling | not needed |
| Sky view factor | % | Angle rule | not needed |

- **Sun hours**: hours of direct sun in the period. Each hour counts the sun position of that hour, and a position counts 1 h when it is above 5° altitude and in front of the test surface (no cosine of incidence). The 5° is the same for every study: "Like *criterion*" does not copy the minimum altitude of a time-based criterion, so a study counts the sun above 5° whatever the criterion's minimum altitude. The time basis says which clock the hours are read in; it is a setting of sun hours only. A new study starts at 21 December, 10 to 14 h. **Quick count** (a switch under the analysis period, off at first; the setting `quick`) counts the sun on every n-th day only, n chosen so that the period gives at most about 240 sun positions, each kept day counting for the days it stands for: 1 October to 30 April then takes every 22nd day. A run of a study whose test points are kept (below) then takes about a second on 1.5 million points; the result card says "Quick count: the sun on every 22nd day". Off, every hour of every day counts.
- **Solar energy** and **Useful solar gains**: direct and diffuse energy that reaches the surface in the period, from the weather file's Perez sky and the cosine of incidence. Useful solar gains count only the hours that need heating (the gains that heat the building; it was called useful solar energy before), with the balance temperature, dead band and weights of Solar heating. Ground reflection is left out. A new study starts with the whole year (solar energy) or 15 October to 15 April, 7 to 19 h (useful solar gains).
- **Overcast sky component**: light from a CIE overcast sky. On a vertical facade this is the vertical sky component, at most 39.6 %.
- **Cooling sky**: the long-wave cooling potential toward the clear night sky that the surface sees, from the dew point and the Bliss coefficient.
- **Sky view factor**: the cosine-weighted share of the view taken by the sky. An unobstructed horizontal surface has 100 %, an unobstructed wall 50 %.

The three sky metrics are a percentage of what an unobstructed horizontal surface receives. Study names, units and the per-study defaults are listed by `GET /projects/{name}/studies`.

## What Simulate fixes

These choices are not settings:

- **Sky**: Tregenza's 145 patches. Each patch is traced with jittered sub-rays, as the carving traces them, at the project's rays per patch (the value of the first criterion that is on, 4 when the project has no criterion). One ray per patch would leave gaps of about 12° between the rays and show banding.
- **Sun**: one position per hour.
- **Test points**: sampled on the study's surfaces at its **spacing** (More settings). Until you type one, a study follows the carving's spacing (the grid step of the shared settings, else half the voxel size), and the field shows that value with "Follows Carve"; a typed spacing is kept with the study (`sample_spacing`), and **Follow Carve** takes it back. A study keeps its test points between runs while what they are sampled from is the same (its files, the project's surfaces it samples and their files, the ground disc, the geometry whose faces it samples, the spacing): a new metric, period or setting then traces at once, without sampling again (on Allatini, 1.5 million points, a sun hours run of one day went from 7.5 s to 0.6 s). The app then reads only the new values: it sends the points key of the patches it holds (`GET /projects/{name}/studies/{study_id}/values?points_key=...`), and the service leaves the patches out while the points are the same (on Allatini 11.7 MB in place of 82.2 MB). The app keeps the patches of the three studies read last, and lets them go when Simulate closes. A study with more than 2 million test points is refused, and the message gives the spacing that fits. The context and a large ground disc can reach that quickly: a disc of 100 m radius at 0.5 m is about 126,000 points.
- **Blocking**: the context and the terrain of the project always block, with the geometry the study accounts for.
- **North and ray length** come from the shared settings.

## Geometry

A study accounts for one geometry, chosen under **Account for** in its settings (the setting `geometry`): it stands on the plot and blocks while the study's points are traced, with the context and the terrain.

| Account for | What blocks |
|---|---|
| **Nothing** | Only the context and the terrain: the no-build case. The view draws the maximum volume as a ghost, so the site still reads |
| **Max volume** | The maximum volume mesh as you added it (not its voxels). A new study accounts for it |
| **Envelope** | The envelope mesh that **Build envelope** wrote, clipped by the maximum volume |
| **Massing** | The building massing mesh, clipped by the maximum volume |

**Envelope** and **Massing** are greyed until Carve has built them, with the reason on hover ("Build the envelope in Carve"); a study that accounts for one that is gone says so on its row and does not run. With several criteria the envelope is the result of the whole chain. Carve may show the geometry out of date; Simulate still traces the mesh on disk. To compare two geometries, make two studies (**Duplicate study**) and select one, then the other.

## Run

**Run** runs every study that can run. Each study traces its points twice: with the geometry it accounts for, and with nothing built (the no-build values, see below). A study that cannot run says why on its row (nothing to simulate, no surroundings or terrain file for a study that samples them, no maximum volume, its envelope or massing not built, no weather file for a metric that needs one, a setting the engine refuses). One that the engine refuses, for example for too many test points, keeps its message until its inputs change, and the other studies still run.

There is one job at a time. While a carving run is going, Run shows "A carving run is in progress" and waits; while a simulation is going, Carve's run buttons say so. Nothing is queued. The progress shows under Run with a Cancel button.

## The legend, the colour range and the result card

The legend along the bottom of the view shows the scale the values are coloured by, with a switch between two:

- **Value** in the study's unit (for example kWh/m²), the default: each point coloured by its value.
- **% of no-build**: each point coloured by its share of its **no-build value**, its value with nothing built on the plot (no maximum volume, envelope or massing). The surroundings and the terrain still block, so the no-build value is not a value without any context: it is the most each point can receive in the city as it is. The scale runs from 0 to 100 %, the same for every geometry, so studies on Max volume, Envelope and Massing compare directly. For a point on the faces of the study's own geometry, the no-build value is its value with that geometry taken away, so the share is what the building's own shape costs it. A point that gets nothing in the no-build case (a facade that sees no sun in the period, say) loses nothing, so it counts as 100 %.

A study's values spread mostly with the way each surface faces: on Allatini's Solar energy study the roofs reach about 1,550 kWh/m² while the facades lie between 200 and 800. By value, move the high end down to the facades' range to see their differences (below); by share, every point is measured against its own no-build value, and the maximum volume keeps 78 % of the no-build value there and the envelope 99 %.

**The colour range.** Two marks on the legend set the low and the high end of the colours. The palette runs between them, and a value beyond an end takes that end's colour, so the colours can spread over the values that matter (the facades between 200 and 800 kWh/m², say, rather than 0 to the roofs' 1,550). Drag a mark, or press on the bar to move the nearer one; or focus a mark and use the arrow keys (1 % of the bar), Page Up and Page Down (10 %) and Home and End; Delete puts it back to its default. The ends cannot pass each other. By value the low end is the study's **target** and the high end its upper end, both saved with the study (by default 0 and the 99th percentile of the values shown, so a few high values, a roof turned to the sun, do not leave the rest in the middle of the palette; the bar still runs to the highest value); the result card's last line, for example "92 % at or above the target", counts the points at or above the low end. By share the ends are percentages, 0 and 100 by default, kept for each study while the app is open.

**The palettes** are fixed: Magma by value, Viridis by share. Both are matplotlib's perceptually even palettes, from dark to light without a grey middle (Viridis is the one most readable with the common colour vision deficiencies), so the two colourings do not look alike.

The **result card** in the bottom right corner is for the selected study. It gives:

- what the points keep of the no-build value: the sum of their values over the sum with nothing built on the plot, for example "keeps 99 % of the no-build value",
- the mean,
- the lowest tenth (10th percentile),
- with a target (the low end by value), the share of points at or above it ("92 % at or above the target").

A study that simulates the faces of its geometry has these lines twice: under **Study surfaces** for its files, the context and the ground, and under **The massing** (or The envelope, The max volume) for the points on the building, so the ground and the neighbours do not hide what the building gets. Under the building's block, **By facing** opens a table of the mean, the lowest tenth and the share at the target for the roofs (faces whose normal points up by more than about 45 degrees) and the facades facing north, east, south and west (in 90 degree sectors centred on each, from the project's north). The table is closed at first, and the button at the top right of the card minimises it to its title, so it covers less of the view.

## Out of date

A result is **out of date** when any of these changed since it was computed: the study's settings (including its metric, its period, the geometry it accounts for, what it simulates and its spacing), its study surface files, the weather file, the context, the terrain, the maximum volume, or the envelope or massing mesh it accounts for (a study on the maximum volume stays current when the envelope is rebuilt). The surface tolerance of the envelope and massing, which follows the voxel size they were built with, counts too. So do the shared settings a study reads: north, the ray length, the test point spacing of the carving for a study that follows it (the voxel size and the grid step) and the rays per patch of the first criterion that is on. A study that samples the ground goes out of date when the compass ring moves (a test surface file reaching further out). Turning a criterion on or off in Carve can therefore make every study out of date. The result stays on the view in grey, with the **Out of date** stamp at the top of the view, and the row says "Out of date". Nothing reruns by itself: press **Run**. Moving the project folder does not make a result out of date. Changing the target does not either. A file saved over an input file in the project folder counts as a change once the app has found it (see [Replacing a file in the project folder](ui.md#replacing-a-file-in-the-project-folder)).

## Where the results are kept

Each study's results are in `<project>/simulate/<study number>/`:

| File | Content |
|---|---|
| `check_points.npz` | The test points, their normals, the corners of the square patch each draws, the frame the coordinates are relative to, and `geometry_point_count`: how many of the points, the last ones, are on the faces of the study's geometry |
| `check_values.npz` | One value per point for `open` (nothing built) and for the geometry the study accounts for (`max_volume`, `envelope` or `massing`; none for Nothing) |
| `check_sky.json` | The value of each of the 145 sky patches for the study's metric, drawn as the study's sky dome; none for sun hours |
| `check_summary.json` | The metric, unit, settings, the geometry, the point counts and the spacing, for each column its mesh, triangle count, surface tolerance and statistics, and what the result was computed from (with the ground disc when the ground is sampled). It is written last, so a folder without it has no result |
| `refusal.json` | Only for a study the engine refused: the message and the inputs it was refused with |

Reopening the project shows the last results. The studies also use `inputs/joined/study_surfaces_<number>.ply`, the joined test surface file of a study, beside the criteria's.

The service routes are under `/projects/{name}/studies` (with `POST /projects/{name}/studies/{id}/duplicate` for Duplicate study) and `POST /projects/{name}/simulate`; the engine request is `check`, which takes the ground disc as `ground_disc` (see [Engine requests](api/engine-requests.md#commands)).

## The sun tool

The **Sun** button in the view's toolbar (beside Frame all, the top view and the ground aid), in Carve, Simulate and Inspect alike, opens the sun tool: the site with the sun as architects study it on a sun path diagram and with shadow drawings. Its panel opens under the toolbar; the button again, or the panel's close button, takes everything of the sun away. It stays open when you change workspace. It needs the project's weather file, whose location gives the sun's course; without one it says so. North is the project's, as in the carving.

- The **sun path** is drawn while the tool is open, on the hemisphere around the scene: the sun's arcs on the March equinox (the September one lies within a fraction of a degree of it) and the two solstices (dashed), a line for each whole hour showing where the sun stands at that hour through the year (labelled at its highest point), the day's arc (bold) and, at a moment, the sun.
- A switch chooses **Sun path only** or **Shadows at a time**.
- A moment: a day on a year strip (with 21 Mar, 21 Jun, 21 Sep and 21 Dec as presets) and a time on a day strip, each with one handle, as the criteria panel's strips are drawn (drag the handle or press on the strip; the arrow keys move a day or 5 minutes, Page Up and Page Down a month or an hour). The panel says how high the sun stands and its bearing from north, or that it is below the horizon.
- **Clock**, at the end: the times are read as the weather file's **local standard time**, **local solar time** (noon when the sun crosses the meridian) or **local daylight saving time** (an hour ahead of standard time on every date, as the engine reads it).

With **Shadows at a time** the scene is lit by the sun at that moment: the maximum volume, the envelope, the massing, the surroundings and the terrain cast shadows on each other, and on the ground where there is no terrain. The sky light is lowered meanwhile, so the shade reads. The hours of sun over a period are a **Sun hours** study (its **Quick count** gives them in about a second); the view's earlier count of hours in shade is gone.

The **Show** switch beside the studies panel's title hides the selected study from the view (its colours, legend and result card) and shows it again, for a clear view of the shadows.

The tool reads two routes: `GET /projects/{name}/sun-chart?date=MM-DD&time_basis=` (the arcs of the March equinox, the solstices and `date`, every 5 minutes, and an hour line for each whole hour, a point a week) and `GET /projects/{name}/sun-positions?from=MM-DD&to=MM-DD&start=&end=&step=&time_basis=` (the sun above the horizon every `step` minutes from minute `start` to `end` of each day from `from` to `to`, over the new year when `to` comes first and over midnight when `end` comes before `start`, with its altitude and azimuth; on every n-th day, `day_step`, when that would be more than 240 positions). `time_basis` is `standard` (the default), `solar` or `daylight_saving`. Both answer 404 without a weather file.

## Not there yet

These belong to a later milestone:

- studies on other designs (meshes added for Simulate only),
- snapshots of results,
- CSV export of the values,
- side-by-side views with linked cameras,
- a command-line command and a Grasshopper component for the check.
