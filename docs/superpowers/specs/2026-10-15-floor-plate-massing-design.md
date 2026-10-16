# Floor-Plate Massing

**Date:** 2026-10-15
**Branch:** `20261015_floor_plate_massing`
**Status:** Draft, for review

## Summary

A new pipeline stage, `massing`, turns the carved envelope into a plausible
built form: stacked floor plates of fixed height (ground floor 5 m, upper
floors 3 m) whose outlines follow the maximum volume's footprint and step back
in straight cuts where the envelope does not allow a floor. Each floor plate is
a closed prism. The stage reports floor area per floor and in total.

## Purpose

The carved envelope is a voxel volume. Designers, and the energy analysts who
model their buildings, work with floors. The massing stage serves three uses at
once:

- a massing model to show and develop, so the forms must read as buildings;
- floor area figures, to compare options by buildable area;
- simulation input: one closed prism per floor and plate, so the geometry can
  feed energy and daylight tools (e.g. Honeybee rooms).

The floor plates are drawn the way an energy analyst would zone a building:
full floors, outlines that keep the facades as modelled, and cuts that run
perpendicular or parallel to the facades.

## Terms

| Term | Meaning |
|---|---|
| footprint | The outline of the maximum volume at its base (exact, from the mesh). Its separate pieces are *parts* (each tower, each row, the courtyard ring). |
| facade | A run of footprint edges between two corners. A corner is a vertex where the outline turns by more than 30 degrees; smaller turns (curved or faceted facades) continue the same facade. Inner rings (courtyards) have facades too. |
| face | The part of the footprint that belongs to one facade (see Faces). |
| bay | A slice of a face between two cuts perpendicular to its facade, `min_plate_dimension` wide. The unit kept or removed on each floor. |
| floor plate | On one floor, a connected union of kept bays. Exported as one prism. |

## Configuration

New fields on `UserConfig` (`pydantic_schemas.py`), in a "massing" section:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `ground_floor_height` | float > 0 | 5.0 | Height of the ground floor (m) |
| `floor_height` | float > 0 | 3.0 | Height of every floor above the ground floor (m) |
| `min_plate_dimension` | float > 0 | 3.0 | Bay width, and the minimum width of any floor plate (m) |
| `plate_tolerance` | float in [0, 1] | 0.2 | Largest share of a bay's volume on a floor that may lie outside the carved envelope |
| `plate_stacking` | `"supported"` or `"free"` | `"supported"` | supported: a bay is built on a floor only if it is built on the floor below; free: each floor is decided on its own |

The plates never leave the maximum volume: the tolerance only allows reaching
into volume that the carving removed.

## Algorithm

### 1. Footprint and facades (once per run)

- Section the maximum-volume mesh 1 cm above its lowest point (shapely
  polygons via trimesh). Each polygon is a part; holes are kept.
- If the section fails (open or broken mesh), fall back to the voxel
  footprint (columns with any occupied voxel), vectorised and simplified to
  half a voxel, and warn.
- Split each ring (outer and inner) into facades at corners (turn > 30
  degrees).

### 2. Faces (once per run)

Work on the voxel-column grid: every column whose centre lies inside the
footprint belongs to exactly one face.

1. **Nearest facade.** Assign each column to the facade at the smallest
   distance (distance to the facade polyline). This splits each part into
   faces meeting along ridges; at corners the ridges are diagonal.
2. **Square corners.**
   - Convex corner between facades A and B, A the longer (ties: lower facade
     index): columns of B whose projection onto A falls within A's extent and
     whose distance to A is at most A's typical half depth move to A. A's
     typical half depth is the median, over positions along A, of the largest
     distance of A's own columns at that position.
   - Reflex corner (inner corner, e.g. where the two arms of an L meet):
     columns whose nearest point on their facade is the shared corner vertex
     move to the longer of the two facades, extending its face past its end.

   After this, every face is bounded by its facade, by lines perpendicular to
   its facade and by lines parallel to it.
3. **Along-facade position.** For each column, `u` = position along its
   facade:
   - straight facades: projection onto the facade direction, measured from the
     part's footprint centroid, so parallel facades (both sides of a bar)
     share the same cut positions;
   - curved facades: arc length of the nearest point, measured from the
     facade's first corner.

### 3. Bays (once per run)

- Cut each face at `u = k * min_plate_dimension`. Cuts are perpendicular to
  the facade; on curved facades they fan out with the curve.
- A bay at either end of a face that is narrower than `min_plate_dimension`
  merges into its neighbour.
- Each bay is a set of voxel columns.

### 4. Floors

- Floor levels from `z0`, the bottom of the lowest occupied voxel: ground floor
  `[z0, z0 + ground_floor_height)`, then `floor_height` per floor, while the
  floor's top is at or below the top of the maximum volume.
- Per bay and floor:
  - **inside the maximum volume (hard):** every column of the bay is occupied
    by the maximum volume over the floor's full height;
  - **outside share:** the length of the floor's height range that the
    carving removed, summed over the bay's columns, divided by
    (columns x floor height). Partial voxel overlaps count by length, so
    floor heights need not be multiples of the voxel size.
- A bay is **kept** on a floor if it is inside the maximum volume, its outside
  share is at most `plate_tolerance`, and, with `supported` stacking, it is
  kept on the floor below (the ground floor has no floor below).
- **Minimum width:** the kept columns of the floor are opened morphologically
  with a square of side `min_plate_dimension`. A bay keeping less than half of
  its columns after the opening is dropped. One pass; with `supported`
  stacking, a dropped bay stays dropped on the floors above.
- **Floor plates:** the connected pieces of the kept bays of a floor.

Carving more never keeps more: every test above only gets stricter when the
envelope loses voxels.

### 5. Plate geometry

- Each plate outline is the union of its bays' columns, vectorised and
  simplified to half a voxel, then intersected with the exact footprint
  polygon. Facade edges are therefore exact; cut and ridge edges are straight
  to within half a voxel.
- The prism is the outline extruded from the floor's bottom to its top. Cap
  triangles come from shapely's constrained Delaunay triangulation, so no new
  dependency is needed.
- Floor area = outline area (gross floor area).

## Outputs

In `<out_dir>/`:

- `plates.json`: per plate: floor index, z bottom and top, outline (outer ring
  and holes, world coordinates), area, number of bays, outside share (volume
  outside the envelope / plate volume).
- `plates.obj`: one closed mesh per plate, one object group per plate, named
  `floor_<n>_plate_<m>`.
- `manifest.json`: paths and stage hash (settings + upstream thresholding hash).
- `diagnostics/diagnostic.json`: number of floors and plates, floor area per
  floor and in total, share of the carved envelope's volume inside plates,
  volume placed outside the envelope through the tolerance, timings.
- The run report gets a "Massing" section with these figures.

## Interfaces

- **Python:** `massing(thr_result, cfg, out_dir) -> MassingResult`, alongside
  `exporting` in `api_core/`. Reads `mask.npy` and the occupancy grid through
  the thresholding manifest, and the maximum-volume mesh path from the config.
- **CLI:** `usc massing -c config.yaml`.
- **Daemon:** a `massing` command, as for the other stages.
- **Grasshopper:** `USC_Massing`, inputs `config`, `thr_result`,
  `massing_overrides`, `run`; outputs `plates` (Rhino Breps built natively
  from the JSON outlines as extrusions, so they stay exact), `floor_areas`
  (list per floor), `total_floor_area`, `diagnostics`, `report_path`. A
  `USC_MassingSettings` component formats the five settings, like
  `USC_Threshold` does for thresholding.

Module layout: `massing.py` (footprint, faces, bays, floors, outlines; pure
functions) and `api_core/massing.py` (stage I/O, manifest, diagnostics).

## Errors

- Envelope too low for the ground floor: empty result, a warning, valid empty
  outputs; no exception.
- Footprint section fails: voxel-footprint fallback with a warning.
- Settings below one voxel (e.g. `min_plate_dimension` < `voxel_size`):
  validation error naming the setting.
- A part smaller than one bay in both directions: one bay for the whole part.

## Testing

- **Faces and bays:**
  - bar: front, back and two end faces become two long faces after squaring;
    cuts on both sides align;
  - square: four faces, square corners, longer-facade tie rule deterministic;
  - L-shape: the reflex-corner square joins the longer arm (as in the design
    discussion);
  - ring: four outer faces and four inner (courtyard) faces;
  - curved bar: one facade per side, cuts perpendicular to the curve.
- **Floors:**
  - `plate_tolerance = 0`: no kept bay has any column outside the envelope on
    its floor;
  - plates never leave the maximum volume;
  - `supported`: no bay is kept above a bay that is not;
  - carving more never builds more (nested masks give nested plates);
  - no plate narrower than `min_plate_dimension`;
  - floor heights that are not multiples of the voxel size give correct
    outside shares.
- **Geometry:** prisms are watertight; floor area per floor equals the sum of
  outline areas; outlines lie inside the footprint polygon.
- **Stage:** manifest, diagnostics and empty-result handling; Grasshopper
  component docstrings match their UI blocks (existing test).
- **End to end:** the four ReSBE scenes (33 m), with 3D views reviewed by the
  user before merging.

## Out of scope

- Sloped ground (floors are counted from the lowest point of the maximum
  volume).
- Rotated or non-rectangular bays inside a face; interior partitions (core,
  perimeter zones); roofs other than flat.
