# Floor-plate massing

The massing stage turns the carved envelope into stacked floor plates: a
ground floor, then floors of equal height, each a closed prism whose outline
follows the maximum volume's footprint and steps back where the envelope does
not allow the floor. Use it for massing models, floor-area figures and as
simulation input (one closed prism per floor and plate).

## How plates are formed

1. **Footprint and facades.** The outline of each body of the maximum volume,
   1 cm above its own base, is split into facades wherever it turns by more
   than 30 degrees. Curved or faceted outlines with smaller turns stay one
   facade.
2. **Faces.** Every footprint column belongs to its nearest facade. At corners
   the longer facade takes the corner square (up to half the building's depth
   behind it), so every face ends in a line perpendicular to its facade.
3. **Bays.** Each face is cut into bays of `min_plate_dimension` (3 m) along its
   facade, perpendicular to it. Cuts on the two sides of a straight building
   line up. A short end bay joins its neighbour.
4. **Floors.** For each floor (ground floor `ground_floor_height`, then
   `floor_height`), a bay is built when it stays inside the maximum volume over
   the floor's full height, at most `plate_tolerance` of its volume lies outside
   the carved envelope, and (with `plate_stacking: supported`) it is built on
   the floor below. Parts narrower than `min_plate_dimension` are dropped.
5. **Plates.** The connected built bays of a floor form a plate. Its facade
   edges are the footprint's own; its other edges are perpendicular or parallel
   to a facade, straight to within half a voxel.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `ground_floor_height` | 5.0 | Height of the ground floor (m) |
| `floor_height` | 3.0 | Height of every floor above it (m) |
| `min_plate_dimension` | 3.0 | Bay width and minimum plate width (m) |
| `plate_tolerance` | 0.2 | Largest share of a bay's volume on a floor outside the carved envelope |
| `plate_stacking` | supported | `supported`: build a bay only on a built bay; `free`: each floor on its own |

Plates never leave the maximum volume. The three sizes must be at least the
voxel size of the preprocessing run; the stage reports an error naming the
setting otherwise.

## Outputs

In `<out_dir>/massing/`:

- `plates.json`: one entry per plate (floor, z bottom and top, outline and
  holes in world coordinates, area, number of bays, share of its volume outside
  the envelope), plus the floor area per floor and in total;
- `plates.obj`: one closed mesh per plate, named `floor_<n>_plate_<m>`;
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
  higher gets a warning (sloped ground is not supported yet).
- If the maximum volume's outline cannot be read from the mesh, the voxel
  footprint is used, with a warning; plates can then be up to one voxel larger
  than the true footprint.
- Bays are rectangles in their face's frame; there are no interior zones (core,
  perimeter) and roofs are flat.
