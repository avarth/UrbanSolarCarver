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
- **Closed bodies**: how many of the file's bodies are closed, of how many. A body is the triangles joined by shared edges. For the maximum volume an open body is shown as a warning, because the voxelizer needs closed volumes. For the surroundings and the test surfaces it is information only.
- **Surfaces**, for a test surface file: how many surfaces it has (below).

The summary is worked out when Inspect asks for it, not at upload, and it is kept until the file changes. It reads each file as the engine's loader does, so the triangles you see are the ones the engine uses.

## What the colours and arrows mean

Test surfaces are drawn two-sided. The side the normal points to has the test surface colour of the viewport theme. The back side is orange. A surface that is the wrong way round therefore shows orange when you look at it from outside, whichever side of it the camera is on.

The **Arrows** box in the panel draws one arrow per surface, from its centre along its normal, 0.3 times the square root of its area long, between 1 m and 10 m. One arrow per surface rather than per triangle keeps a large file readable. Arrows do not take clicks. A surface you have turned and not saved is drawn, and its arrow points, the new way.

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

The service then reads the written file back with the engine's loader and compares it with what you turned. If the triangles, their normals or their corners are not what was written, nothing is saved and the file stays as it was. A saved file keeps the geometry only. USC reads geometry only, so OBJ groups, materials and texture coordinates and PLY colours are not in the saved file. The original, which is kept (below), still has them.

Save has the effects of uploading the file again through the app:

- The joined files of the criteria and studies that list the file are built again.
- Those criteria and studies go out of date, and the criteria after them have to carve again. A run traces the file again.
- The file's record in `project.json` is renewed. There is no "changed in the project folder" notice, since you made the change in the app.

Save and Restore original are not available while a run of the project is going. The panel says so beside the buttons.

### Restore original

Before the first save of a file, the file as it was is kept in the project folder, in `inputs/originals/test_surfaces/`. **Restore original** puts it back byte for byte, with the same effects as a save, and removes the kept copy. The button shows on the selected row while an original is kept.

The kept original is dropped when you upload a file with the same name, when you remove the file in the app, and when you replace the file by hand in the project folder. After that the stored file is the only version, and Restore original is not offered.

### Leaving Inspect with turns not saved

Switching to Design or Simulate while a file has staged turns asks **Save the turned surfaces before leaving Inspect?** with three answers: **Save** (writes every file with turns, then leaves), **Discard** (drops them and leaves) and **Stay**. If a save is refused, for example because a run is going, the dialog stays open with the reason.

If a file changed while turns were staged on it (a new version uploaded, or replaced in the project folder), the staged turns are dropped and the panel says **The file changed, so its turns not saved were dropped.** The surfaces of the new version are numbered anew, so the old turns would not mean the same surfaces.

## Where the service keeps things

The service computes all of this in `local_web_service/inspection.py`, with trimesh, from the stored files as the engine's loader returns them, so the view and a flip use the triangles the engine uses. No engine function is involved. Routes (all under `/api`):

| Route | What it does |
|---|---|
| `GET /projects/{name}/inspect` | The summary of every mesh file of the project; allowed while a run is going |
| `GET /projects/{name}/inspect/test_surfaces/{file}/geometry` | The triangles of a test surface file with a surface number per triangle, as one binary (layout in `inspection.inspection_geometry`) |
| `POST /projects/{name}/inspect/test_surfaces/{file}/turn` | Turn the surfaces named in `surfaces` and save the file; 409 while a run of the project is active, 422 for a file closed as a whole, one that cannot be read or a surface that does not exist, 500 when the written file does not read as turned |
| `POST /projects/{name}/inspect/test_surfaces/{file}/restore` | Put the kept original back; 404 when none is kept, 409 while a run is active |

## Not in Inspect

Inspect does not change axes (Y-up), coordinates in the millions, open volumes or heavy files, and it does not flag surfaces that probably face the wrong way. It does not inspect the envelope, the massing or the joined files. Further checks (a Y-up guess, the estimated voxel grid before a run) are planned separately.
