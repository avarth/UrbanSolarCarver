# Inspect

A test surface is read from one side only. A carving and a Simulate study see the side its normal points to: a surface that faces into a building, or a roof that faces down, sees nothing, so the criterion barely protects it and nothing else in the app says so. **Inspect** shows which way every test surface faces, lets you turn the ones that face the wrong way by clicking them, and gives a short summary of every input mesh file.

Inspect is a workspace beside the pipeline, like [Simulate](simulate.md). It runs no engine step, changes no criterion or setting and makes nothing out of date by itself. Only **Save** and **Restore original** change a file, and only when you press them.

USC does not decide which way a surface should face. Only you know whether a surface is a roof for PV, a facade, or a soffit that faces down on purpose. Inspect shows the orientation and leaves the choice to you.

## Design, Simulate and Inspect

The switch **Design | Simulate | Inspect** in the header, next to the project name, changes the workspace. Inspect hides the steps and gives the 3D view the whole window. Switching away keeps Design's step and scroll position and Simulate's selection as they were. The Layers menu and the viewer tools are the same in all three; Inspect adds one layer, **Surface orientation**.

Inspect works while a run of the project is going. Only Save and Restore original wait for it to end, as uploads do.

## The Files panel

The **Files** panel floats over the top left of the 3D view and collapses to an icon. It lists the input mesh files by role: maximum volume, test surfaces, existing surroundings and terrain. The weather file has no geometry and is not listed. Each row gives the file name, its triangle count and its area. A file that cannot be read stays in the list with its problem, for example a broken export, and has nothing to select.

Pressing a row selects the file. The view frames it and draws the other test surface files faint, so you see what the selected one faces. The selected row also opens the file's summary:

- **Bounds**: the minimum and maximum corner in the file's own coordinates. When a corner is more than 10 km from zero, a note says the coordinates look georeferenced and how far they are. Under the list, the panel says which point the view is drawn around, since the view uses a local origin.
- **Surfaces**, for a test surface file: how many surfaces it has (below).

An earlier version also counted closed bodies. It was dropped: CAD exports (Rhino's OBJ, for one) keep a corner per face, with that face's normal, so faces share no edges and every face counted as an open body (Allatini's maximum volume: 0 of 24). The voxelizer does not depend on it either: it fills by ray crossings along three axes with a two-of-three vote, so a missing floor or a T-junction does not change the voxels.

The summary is worked out when Inspect asks for it, not at upload, and it is kept until the file changes. The test surface and maximum volume files are read as the engine's loader reads them, with their normals made consistent, so the triangles you see are the ones the engine uses. The surroundings and terrain files are read as stored, without that step, as the engine reads them too: nothing reads their orientation, and fixing it takes seconds on a large mesh.

## What the colours and face normals mean

Test surfaces are drawn two-sided. The side the normal points to has the test surface colour of the viewport theme. The back side is orange. A surface that is the wrong way round therefore shows orange when you look at it from outside, whichever side of it the camera is on.

The **Face normals** box in the panel draws one normal per surface, an arrow from its centre along its normal, 0.3 times the square root of its area long, between 1 m and 10 m. One per surface rather than per triangle keeps a large file readable. The normals do not take clicks. A surface you have turned and not saved is drawn, and its normal points, the new way.

The maximum volume is drawn see-through, and the surroundings and the terrain grey, as in Design. Their orientation is not drawn: nothing reads the orientation of the surroundings and terrain, and the loader turns the closed bodies of the maximum volume outward by itself.

## Surfaces, and why a click turns a whole surface

A **surface** is a set of triangles joined by shared edges, as the engine's loader reads the file. A click in flip mode turns the whole surface under the pointer, not the single triangle. The loader makes neighbouring triangles agree in winding, so a lone triangle turned in the file would be turned back the next time the file is loaded.

For the same reason a test surface file that is **closed as a whole** cannot be flipped. The loader turns every closed body outward, so its surfaces would come back the way they were. Such a file shows **This file is closed as a whole, so its surfaces cannot be flipped.** and its Flip mode and Flip all buttons are off.

## Flipping

Flipping applies to test surface files only. Select a test surface file, then:

- **Flip mode** (a toggle on the selected row): a click on a surface turns it, and a second click turns it back.
- **Flip all** turns every surface of the file, for a whole export that came out the wrong way round.

Turns are **staged**. The view shows them at once and the row says, for example, "3 surfaces turned, not saved". Nothing is written until you press **Save**, so the criteria go out of date once, not at every click. **Discard** drops the staged turns.

### Save

**Save** writes the file once, in its own format:

| Format | What is written |
|---|---|
| OBJ | The coordinates with 10 decimals |
| PLY | float64 coordinates |
| GLB, STL | float32, as these formats hold nothing finer; coordinates are kept as precisely as the format allows |

A GLB or STL that another program wrote with coordinates float32 cannot hold exactly may have a corner move by about one float32 step when it is saved: for a GLB that is about 4 µm at 50 m from the file's whole-metre offset, for an STL about 0.25 mm at 4 km from zero. OBJ and PLY corners do not move.

The service then reads the written file back with the engine's loader and compares it with what you turned. If the triangles or their normals are not what was written, or a corner moved by more than 1 µm (for GLB and STL, more than two float32 steps at the file's largest coordinate), nothing is saved and the file stays as it was. A saved file keeps the geometry only. USC reads geometry only, so OBJ groups, materials and texture coordinates and PLY colours are not in the saved file. The original, which is kept (below), still has them.

Save has the effects of uploading the file again through the app:

- The joined files of the criteria and studies that list the file are built again.
- Those criteria and studies go out of date, and the criteria after them have to carve again. A run traces the file again.
- The file's record in `project.json` is renewed. There is no "changed in the project folder" notice, since you made the change in the app.

Save and Restore original are not available while a run of the project is going. The panel says so beside the buttons.

### A file that changed in the project folder

Turns are staged on the version of the file Inspect read, and Save sends that version with them. Before it writes anything, the service builds the files changed in the project folder into the project, as when the window comes back to the front, and compares the file stored now with that version. If you replaced the file by hand meanwhile, even with one that has as many triangles and surfaces and the same bounds, Save writes nothing and says **The file changed in the project folder since its surfaces were turned, so nothing was saved.** Its staged turns are dropped, since the surfaces of the new version are numbered anew, and Inspect reads the files again. Restore original does the same with **The file changed in the project folder since Inspect read it, so nothing was restored.**, so it never puts an older original over a file you replaced. The kept original of a file replaced by hand is dropped (below), and the file has a "changed in the project folder" notice as any file replaced by hand.

Inspect also reads the files again when the stage status finds a file changed in the project folder, for example when the window comes back to the front, so turns staged on a replaced file are dropped before you press Save.

### Restore original

Before the first save of a file, the file as it was is kept in the project folder, in `inputs/originals/test_surfaces/`. **Restore original** puts it back byte for byte, with the same effects as a save, and removes the kept copy. The button shows on the selected row while an original is kept.

The kept original is dropped when you upload a file with the same name, when you remove the file in the app, and when you replace the file by hand in the project folder. After that the stored file is the only version, and Restore original is not offered.

### Leaving Inspect with turns not saved

Switching to Design or Simulate while a file has staged turns, or while a save or restore is under way, asks **Save the turned surfaces before leaving Inspect?** with three answers: **Save** (writes every file with turns, then leaves), **Discard** (drops them and leaves) and **Stay**. While a save is under way the dialog says **A save is under way.**; Save and Discard wait for it, and when it is written with nothing left to save the dialog leaves by itself. If a save is refused, the one under way included, for example because a run is going or the file changed in the project folder, the dialog stays open with the reason, so a failed save is never left unseen in another workspace.

If a file changed while turns were staged on it (a new version uploaded, or replaced in the project folder), the staged turns are dropped and the panel says **The file changed, so its turns not saved were dropped.** The surfaces of the new version are numbered anew, so the old turns would not mean the same surfaces.

## Where the service keeps things

The service computes all of this in `local_web_service/inspection.py`, with trimesh, from the stored files as the engine's loader returns them, so the view and a flip use the triangles the engine uses. No engine function is involved. Routes (all under `/api`):

| Route | What it does |
|---|---|
| `GET /projects/{name}/inspect` | The summary of every mesh file of the project; allowed while a run is going |
| `GET /projects/{name}/inspect/test_surfaces/{file}/geometry` | The triangles of a test surface file with a surface number per triangle, as one binary (layout in `inspection.inspection_geometry`) |
| `POST /projects/{name}/inspect/test_surfaces/{file}/turn` | Turn the surfaces named in `surfaces` of the file of `version` and save the file; 409 while a run of the project is active, or with `stored_file_changed: true` when the file stored now is not that version; 422 for a file closed as a whole, one that cannot be read, a surface that does not exist, or a file changed in the folder that cannot be read; 500 when the written file does not read as turned |
| `GET /projects/{name}/sun-chart?date=MM-DD` | The Sun panel's sun path: the arcs of the March equinox and the solstices and of `date`, every 5 minutes, and an hour line for each whole hour, a point a week; 404 without a weather file |
| `GET /projects/{name}/sun-positions?from=MM-DD&to=MM-DD&start=&end=&step=` | The sun above the horizon every `step` minutes from minute `start` to `end` of each day from `from` to `to` (over the new year when `to` comes first), with its altitude and azimuth; on every n-th day (`day_step`) when that would be more than 240 positions |
| `POST /projects/{name}/inspect/test_surfaces/{file}/restore` | Put the kept original back in place of the file of `version`; 404 when none is kept, 409 while a run is active or (`stored_file_changed`) when the file stored now is another |

Each file of the summary has a `version`, the sha256 of its bytes. A turn or a restore names it, and both first build the files changed in the project folder into the project. The service keeps the summary of each file it read, and for a test surface file its triangles and their surfaces, up to 32 files and 5 million kept triangles, the least recently used leaving first.

## The Sun panel

The **Sun** panel, under the Files panel and collapsed at first (the sun icon opens it), shows the site with the sun as architects study it on a sun path diagram and with shadow drawings. It needs the project's weather file, whose location gives the sun's course; without one it says so. The times are the weather file's local standard time, without daylight saving, and North is the project's, as in the carving.

- **Day** and **Time** choose a moment: a month and a day (or 21 Mar, 21 Jun, 21 Sep, 21 Dec), and the time on a slider in 5 minute steps. The panel says how high the sun stands and its bearing from north, or that it is below the horizon.
- **Sun path of the year and of this day** draws, on the hemisphere around the scene, the sun's arcs on the March equinox (the September one lies within a fraction of a degree of it) and the two solstices (dashed), a line for each whole hour showing where the sun stands at that hour through the year (labelled at its highest point), the chosen day's arc (bold) and the sun at the chosen time.
- **Shadows at this time** lights the scene with the sun at that moment: the maximum volume, the test surfaces, the surroundings and the terrain cast shadows on each other, and on the ground where there is no terrain. The sky light is lowered meanwhile, so the shade reads.
- **Hours in shade** counts, for every surface the view shows, how many of the hours from a start to an end hour it spends in shade on the chosen day, or as a mean per day over several days (**Over several days, until**). A surface is in shade at a time when something stands between it and the sun or it faces away from the sun. The legend's ramp runs from yellow (in sun all the range) to dark (in shade all of it).

The hours in shade are a quick count, not an analysis. They are worked out on the graphics card from the camera: the view is drawn once for each sun position (every 10 minutes on one day, every 30 minutes over several days, on every n-th day when that would be more than 240 positions), and each draw adds the time it stands for where the surface is in shade. So the count is of what the camera sees, at the resolution of the shadow map (4096 pixels across about five times the site's radius), and it is counted again when the camera stops moving. Simulate's **Sun hours** study is the precise count, per test point, traced against the meshes.

## Not in Inspect

Inspect does not change axes (Y-up), coordinates in the millions, open volumes or heavy files, and it does not flag surfaces that probably face the wrong way. It does not inspect the envelope, the massing or the joined files. Further checks (a Y-up guess, the estimated voxel grid before a run) are planned separately.
