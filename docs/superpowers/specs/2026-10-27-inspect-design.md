# Inspect: normals and a short summary of the input files, beside the pipeline

Date: 2026-10-27. Status: draft for the user's review. Background: `vault/features/inspect-workspace.md`, the "Geometry checks"
item of the UI/UX design (`docs/superpowers/specs/2026-10-17-local-web-ui-ux-design.md`, section on later work) and the Allatini
case of 2026-10-27 (`vault/bugs/allatini-pv-test-surfaces-face-down.md`).

Marking: **(user)** for what the user asked for or decided, **(proposed)** for a call made here that the user has not confirmed.

## 1. Intent

Test surfaces drawn the wrong way round are "the most frequent f*ck up in these analyses" **(user)**. A test surface that faces
into a building, or a roof that faces down, is read by the carving and by Simulate from the wrong side: it sees nothing, the
criterion barely protects it, and nothing in the app says so. On Allatini 95 % of the PV roof area, 46 % of the solar gains area and
28 % of the daylight area faced into a mass; it was found only because a Simulate study read 0 on most points, and fixing it took a
round trip through Rhino.

Inspect shows the orientation of every test surface and lets the user flip them in USC by clicking them. It also gives a short
summary of every input file. USC does not judge which way a surface should face: only the user knows whether a surface is a roof
for PV, a facade, or a soffit facing down on purpose **(user)**. Drawn two-sided, a surface the wrong way round shows its back colour
from outside, which is how the Allatini facades and roofs would have shown. It is a third workspace beside Design and Simulate, because it is not a step of the
pipeline **(user)**.

The earlier rule for geometry checks was "USC finds and shows, the CAD program fixes" **(user, 2026-10-17)**. It is relaxed for
the orientation of test surfaces only: flipping is safe in USC, since the stored file is the project's own copy and a changed
stored file dates what was built on it (`6403f07`). Everything else is shown only **(user, 2026-10-27)**.

## 2. Goals, non-goals

Goals (first version) **(user)**:
- The orientation of the test surfaces on the 3D view.
- Flipping test surfaces by clicking them, with a way back.
- A short summary per input file: triangles, area, origin, closed bodies.

Non-goals for the first version:
- Fixes of anything other than test surface orientation: axes (Y-up), coordinates in the millions, open volumes, heavy files are
  not changed **(user)**.
- Automatic flags of surfaces that are probably wrong (facing into a mass, facing down) **(user: the view and the user's eye
  instead)**. The check of 2026-10-27 stays a script.
- Further checks from the backlog (a Y-up guess, the estimated voxel grid before a run, linked test surfaces) **(user:
  later)**.
- Inspecting the envelope, the massing or the joined files; checks at upload; a CLI or Grasshopper counterpart **(proposed)**.

Anti-goals: a file changed without the user saving it; a flip that the engine's loader undoes; a check that makes a pipeline stage
out of date by itself; a slower upload.

## 3. The workspace

- **Design | Simulate | Inspect** in the header switch **(user)**. Inspect hides the steps, as Simulate does, and gives the 3D view
  the whole window. Switching away keeps Design's step and scroll and Simulate's selection as they are now.
- A floating **Files** panel at the top left, as Simulate's Studies panel (collapsible). It lists the input files by role:
  maximum volume, test surfaces, existing surroundings, terrain. The weather file is not listed (no geometry).
- Each row: the file name, its triangle count and area. Pressing a row selects the file: the view frames it and draws the other
  files dimmed. The selected row opens its summary (section 5).
- Nothing in Inspect runs the engine or changes a setting. Inspect works while a Design run or a simulation is going, except Save
  (section 6), which is refused then, as uploads are.

## 4. Orientation on the view

- Test surfaces are drawn two-sided: the front (the side the normal points to) in the test surface colour, the back in a warning
  colour that reads on both viewport themes **(proposed)**. A surface the wrong way round then shows its warning colour from
  outside, whichever side the camera is on.
- **Arrows**, a toggle in the Files panel: one arrow per surface, from its centre along its normal, scaled to the scene
  **(proposed)**. One per surface rather than per triangle keeps large files readable.
- A **surface** is a group of triangles connected by shared edges, as the engine's loader gives the file (section 7). It is the unit
  of the arrows and of a flip: a click flips the whole surface under the pointer (section 6 says why not a single triangle).
- Other roles are drawn as in Design (maximum volume see-through, surroundings and terrain grey), so the user sees what a test
  surface faces. Their orientation is not drawn: nothing reads the orientation of the surroundings and terrain, and the loader
  turns closed maximum volume bodies outward by itself.

## 5. The summary

Per file **(user)**:
- Triangles; area (m²); surfaces (test surface files only).
- **Origin**: the file's bounds, minimum and maximum corner in the file's own coordinates, and a note when they are far from zero
  ("georeferenced coordinates, about 4,500 km from the origin"). The view's local origin is stated with them.
- **Closed bodies**: how many of the file's connected bodies are closed, of how many. For the maximum volume an open body is a
  warning (the voxelizer needs closed volumes); for the surroundings and test surfaces it is information.

## 6. Flipping

Test surface files only **(user)**.

- **Flip mode**, a toggle on the selected test surface file's row. In flip mode a click on a surface turns it; a second click
  turns it back **(user)**. **Flip all** turns every surface of the file (a whole export the wrong way round) **(proposed)**.
- Turns are staged: the view shows them at once, the row says "3 surfaces turned, not saved", and **Save** writes the file once
  **(proposed: one write, so the criteria go out of date once, not at every click)**. **Discard** drops the staged turns. Leaving
  Inspect with turns not saved asks to save or discard them.
- Save writes a new version of the stored file under its name, in its own format, and has the effects of uploading that version
  through the app: the joined files of the criteria and studies that list it are built again, those criteria and studies go out
  of date, and the file's record is renewed. It gives no "changed in the project folder" notice.
- Before the first save of a file, the stored original is kept in the project folder (`inputs/originals/test_surfaces/`).
  **Restore original** on the row puts it back, with the same effects as a save. A later upload of a file with that name drops
  its kept original **(proposed)**.
- **What a flip can be.** The engine's loader (`io.load_mesh`, `fix_normals`) makes the winding of edge-connected triangles agree,
  and turns closed bodies outward. A unit smaller than an edge-connected surface would be turned back at the next load, and a
  closed body of test surfaces is always turned outward. So a flip turns a whole surface, and a closed body cannot be flipped (its
  click says why). The file written must load, with `load_mesh`, to the same triangles with the turned surfaces turned and the
  others not; Save refuses (and writes nothing) when it does not.

## 7. Service

- Computed in the service (a new module, `local_web_service/inspection.py`), with trimesh, from each stored file as
  `load_mesh` gives it, so the view and a flip use the triangles the engine uses. No engine function is added
  **(proposed)**.
- Computed when Inspect asks, not at upload. A result is kept per file and reused while the file's record (size, time, digest) is
  the same.
- The app gets each file's geometry for Inspect from the service, with a surface number per triangle, so a click on a triangle
  names its surface exactly. (The meshes Design draws are parsed in the browser from the stored files; their triangles need not
  match the loader's.)
- Routes, as a proposal: the summary of every file of the project, the geometry of one file for Inspect,
  and a save of turned surfaces of one test surface file (409 while a run of the project is active, as uploads), plus restore.

## 8. Verification

- Allatini copy with the solar gains file: the 6 surfaces the check of 2026-10-27 found facing into a mass show their back colour
  from outside. Click them in flip mode, Save: they show their front, the check script finds none, the criterion that lists the
  file goes out of date (and the ones after it carve again), a run traces it again.
- A flipped file reloaded with `load_mesh` keeps its turned surfaces; a closed test surface body cannot be flipped.
- Restore original gives back the stored file byte for byte and dates the criteria again.
- Opening Inspect on the District example (the largest bundled one) answers within a few seconds; on Allatini within one second.
- The New building example shows its downward-facing roofs (`vault/bugs/new-building-downward-test-points.md`).

## 9. Calls left to the builder

The colours (within the theme tokens), the arrow length and look, the route paths and payloads, the binary layout of the geometry
(the Simulate values decoder is a model), how a file is written back in its format, and how the cache is kept.
