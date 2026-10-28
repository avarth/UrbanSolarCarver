# Floor-plate massing

The massing stage turns the carved envelope into stacked floor plates: a
ground floor, then floors of equal height, each a closed prism whose outline
follows the maximum volume's footprint and steps back where the envelope does
not allow the floor. Use it for massing models, floor-area figures and as
simulation input (one closed prism per floor and plate).

## How plates are formed

1. **Footprint and facades.** The footprint is the maximum volume's plan
   projection (the area it covers seen from above), so an uneven or raised
   base does not change it. Preprocessing saves this footprint
   (`footprint.json` in its folder, world coordinates) from the mesh it
   voxelized; massing reads that file, not the mesh in the config passed to
   massing and not the mesh file on disk, so later edits to either change
   nothing. If preprocessing could not compute a footprint, massing uses the
   outline of the occupied voxel columns and warns. The footprint outline is split into facades
   wherever it turns by more than 30 degrees. Curved or faceted outlines with smaller
   turns stay one facade. A facade whose vertices all lie within 1 cm of the
   line from its first to its last vertex is straight: footprints cut from
   meshes carry vertices micrometres off a straight wall. Far from the origin,
   where a mesh stored in float32 rounds its coordinates by more, the
   tolerance is four of those float32 steps, and it is never more than half a
   voxel. A real bend, a few degrees over a few metres, stays a bend.
2. **Faces.** Every footprint column belongs to its nearest facade. Facades
   shorter than two modules (`2 * min_plate_dimension`: chamfers, small steps)
   get no face of their own; their neighbours meet at one corner across
   them. At corners the longer facade takes the corner square (up to half
   the building's depth behind it), so every face ends in a line
   perpendicular to its facade. At equal lengths (a square) the facade
   closer to the x axis takes the corner. Along a facade not aligned with the
   voxel grid, the voxelizer also fills columns whose centre lies just
   outside the footprint; such a column belongs to the face of the footprint
   point nearest to it, so the end of a slab is cut on the same lines as the
   rest of it.
3. **Bays.** Each face is cut into square modules of `min_plate_dimension`
   (3 m): along its facade, perpendicular to it, and in depth behind it,
   parallel to it. Along a straight facade the rows of modules are laid from
   both ends of the building (its extent along the facade) towards the
   middle; what is left over widens the middle row, or the two middle rows
   equally (a 10 m bar: 3, 4 and 3 m; 13 m: 3, 3.5, 3.5 and 3 m). An end wing
   therefore starts with a whole row whatever the building's length, and the
   cuts on the two sides of a straight building line up. Along a curved
   facade the rows are cut every module of length from its start. A row
   narrower than a module at the end of a face that ends inside the building
   (at a corner square) joins its neighbour, and a module at the back of a
   row (where the face meets the one opposite) shallower than
   `min_plate_dimension` joins the one in front of it. Each
   module is built on its own, so a wing keeps its floors whatever the
   envelope does behind it in the same face, for example a courtyard of a
   perimeter block carved lower. Behind any facade a plate can therefore be
   as shallow as one module, `min_plate_dimension`.
4. **Floors.** For each floor (ground floor `ground_floor_height`, then
   `floor_height`), a module is built when it stays inside the maximum volume over
   the floor's full height, at most `plate_tolerance` of its volume lies outside
   the carved envelope, and (with `plate_stacking: supported`) it is built on
   the floor below. A column along a facade not aligned with the voxel grid
   counts only for its share inside the footprint, so whether a module is
   built does not depend on the angle of the footprint to the grid; a column
   less than half inside the footprint need not be filled by the maximum
   volume at all (along a wall the voxels can reach up to a voxel past the
   footprint, as the re-voxelized envelope of an earlier carving does). A module
   over the tolerance is not built even when built modules enclose it, so a
   local dip in the envelope can leave a hole of one or two modules in a
   floor; holes are not filled. Parts narrower than `min_plate_dimension` are dropped
   (the test is the same at any angle of the footprint to the voxel grid), so
   a strip one module deep, `min_plate_dimension`, is kept.
   The ground floor starts at the maximum volume's lowest point, and the top
   floor ends at or below its highest point; preprocessing records both in
   its manifest. The voxel grid is not aligned with these points, so the
   lowest occupied voxel layer can lie mostly below the base (its centre below
   it) and the highest mostly above the roof. Such a layer is filled only
   where rays hit the base or the roof, which they miss in columns along
   facades that are not aligned with the grid, so it does not count: a floor's
   height and its share outside the envelope are measured over the layers
   whose centre lies between the lowest and the highest point. A preprocessing
   run from before the manifest recorded these points starts the ground floor
   at the bottom of the lowest occupied layer and lets the top floor reach the
   top of the highest occupied layer, up to one voxel outside the maximum
   volume at each end; running preprocessing again gives the floors above.
5. **Plates.** The connected built modules of a floor form a plate. A module on a
   straight facade is drawn as a rectangle in its facade's frame: cuts lie
   on the cut lines (along the facade and in depth), the back of the last
   module lies on the midline where the facade faces a parallel one, and the
   facade edges are the footprint's own. Other edges
   (face ends at corners) are within half a voxel of the voxel columns. Where
   a corner is not square, the faces of its two facades meet along the
   bisector of the corner; a module there is its rectangle cut by that line
   (or by a line of the two facades' corner squares, or by a bisector with a
   facade that meets one of them; where the faces meet along a curve, by the
   line midway between the two faces' columns turned to a direction of the
   two facades or their bisector), so it ends on one straight slanted edge.
   A cut that would leave an angle under 30 degrees or a piece narrower than
   a voxel is not used. Modules on curved facades, and the modules no such
   line separates from a neighbouring face, follow their voxel columns,
   straight to within half a voxel; they stay off the columns of modules not
   in the plate. Where the shapes of two modules overlap, the overlap belongs
   to one of them, so plates of different modules never overlap. Spikes and
   cracks of no width that the boolean operations leave are removed.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `ground_floor_height` | 5.0 | Height of the ground floor (m) |
| `floor_height` | 3.0 | Height of every floor above it (m) |
| `min_plate_dimension` | 3.0 | Side of the square module and minimum plate width (m); "Grid module" in the browser UI |
| `plate_tolerance` | 0.2 | Largest share of a module's volume on a floor outside the carved envelope; "Permitted volume exceedance" in the browser UI |
| `plate_stacking` | supported | `supported`: build a module only on a built module; `free`: each floor on its own |

Plates never leave the maximum volume. The three sizes must be at least the
voxel size of the preprocessing run; the stage reports an error naming the
setting otherwise.

## Outputs

In `<out_dir>/massing/`:

- `plates.json`: one entry per plate (floor, z bottom and top, outline and
  holes in world coordinates, area, number of modules (`bays`), share of its volume outside
  the envelope), plus the floor area per floor and in total;
- `plates.obj`: one closed mesh per plate, named `floor_<n>_plate_<m>`,
  written whatever `final_mesh_format` says (the browser interface draws it and
  reads its parts by name);
- `plates.ply`, `plates.stl` or `plates.glb` when `final_mesh_format` is one of
  them: the same plates, as one mesh in PLY and STL (formats without named
  parts) and with one named part per plate in GLB. The manifest names this
  file as `export_mesh_path` (`plates.obj` itself for OBJ). A change of
  `final_mesh_format` reruns massing as well as exporting. Far from the
  origin (georeferenced models) PLY keeps the coordinates in double
  precision and GLB places the offset in each node, while STL can only hold
  float32 and the run reports a `float32_coordinates` issue when that rounds
  them by more than 1 mm;
- `manifest.json` and `diagnostics/diagnostic.json` (floors built, plates,
  floor areas, share of the carved envelope inside plates, volume placed outside
  the envelope through the tolerance, footprint source).

The run report gets a Massing section.

## Running it

- Python: `massing(thr_result, cfg, out_dir)`
- CLI: `usc massing -c config.yaml` (finds the thresholding manifest of the run, or pass `-f`)
- Grasshopper: `USC_Massing` after `USC_ThresholdStage`, with `USC_MassingSettings`

## Limits

- Floors count from the lowest point of the maximum volume; a part that starts
  higher gets a warning (sloped ground is not supported yet). With a terrain
  that cuts the maximum volume (its lowest point lies below the ground the
  carving keeps), a warning says how far below: floors that reach into the
  ground are not built, so on sloped ground the massing may have few floors
  or none (a 1 in 6 slope under the "New building" example gave none).
- If the maximum volume's footprint cannot be read from the mesh, or does not
  match the voxel grid (more than 5% of the occupied voxel columns more than
  one voxel outside it, for example when the file was replaced after
  preprocessing), the voxel
  footprint is used, with a warning; plates can then be up to one voxel larger
  than the true footprint.
- Modules are rectangles in their face's frame; there are no interior zones (core,
  perimeter) and roofs are flat.
