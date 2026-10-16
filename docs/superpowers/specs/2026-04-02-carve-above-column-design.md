# Carve-Above-Column Post-Processing

**Date:** 2026-04-02
**Branch:** `20260402_a`
**Status:** Approved

## Summary

Add a post-processing option that, after thresholding produces a binary mask,
carves all occupied voxels in each (x, y) column above the lowest
sufficiently-carved region. This removes leftover "floating" mass above
already-carved zones without requiring re-scoring.

## Motivation

Thresholding can leave isolated occupied voxels above large carved-out
regions. These fragments are structurally implausible (floating in air) and
should be removable with a simple toggle. A `min_consecutive` parameter
prevents stray single-voxel carvings (from voxelization artifacts or noise)
from triggering aggressive column removal.

## Configuration

Two new fields on `UserConfig` (`pydantic_schemas.py`), in a new
"column post-processing" section after the existing postprocessing fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `carve_above` | `bool` | `False` | Enable column carve-above post-processing |
| `carve_above_min_consecutive` | `int` (>= 1) | `1` | Minimum consecutive carved voxels in a column to trigger carve-above |

## Algorithm

**Function:** `carve_above_columns(mask, voxel_grid, min_consecutive)` in `carving.py`

**Inputs:**
- `mask`: `np.ndarray` (D, D, D) bool: `True` = keep, `False` = carved
- `voxel_grid`: `np.ndarray` (D, D, D) bool: `True` = occupied in original envelope
- `min_consecutive`: `int`: minimum run length of carved voxels to trigger

**Output:** Modified `mask` (D, D, D) bool (new array, input not mutated)

**Per-column logic (z-axis is vertical, z=0 is bottom):**

1. Extract column: `mask[x, y, :]`
2. Scan bottom-to-top (z=0 upward) for runs of consecutive `False` (carved) values
3. At the first (lowest) run with length >= `min_consecutive`:
   - Find the top z-index of that run (`top_of_run`)
   - Set `mask[x, y, z] = False` for all `z > top_of_run`
     where `voxel_grid[x, y, z] == True` (only carve occupied voxels)
   - Stop scanning this column (one trigger per column)

**Example** (cross-section, `min_consecutive=2`):

```
     A B C
top  # # #      # = occupied/kept
     # # x      x = carved (empty)
     x x x
     x x #
     x # #
bot  # # #
```

- Column A: 3 consecutive carved >= 2 -> carve 2 occupied above -> result: top 2 become `x`
- Column B: only 1 consecutive carved < 2 -> no change
- Column C: 2 consecutive carved >= 2 -> carve 1 occupied above -> result: top becomes `x`

**Vectorization strategy:**

The implementation should be vectorized across all (x, y) columns using NumPy
to avoid Python-level loops. Approach: for each column, detect run boundaries
via `np.diff`, find the first qualifying run, then broadcast the carve-above
flag upward using cumulative operations.

## Integration Point

**File:** `api_core/exporting.py`

Insert after the existing `carve_grid = voxel_grid.bool() & mask_tensor`
(line ~132), before `finalize_mesh`:

```python
if getattr(conf, 'carve_above', False):
    from ..carving import carve_above_columns
    mask_np = carve_above_columns(
        mask, voxel_grid.cpu().numpy(),
        min_consecutive=conf.carve_above_min_consecutive,
    )
    mask_tensor = torch.as_tensor(mask_np, dtype=torch.bool, device=resolved_device)
    carve_grid = voxel_grid.bool() & mask_tensor
```

## Diagnostics

Added to the exporting stage `diagnostic.json`:

- `carve_above_applied`: `bool`, whether carve-above was active
- `carve_above_min_consecutive`: `int`, the threshold used
- `carve_above_extra_voxels_removed`: `int`, count of additionally carved voxels

## Scope

**Changed files:**
1. `pydantic_schemas.py`: add 2 config fields
2. `carving.py`: add `carve_above_columns()` function
3. `api_core/exporting.py`: call the function, add diagnostics

**Unchanged:**
- Preprocessing stage
- Thresholding stage (manifest, hash)
- `finalize_mesh` and downstream mesh export
- Ray tracing infrastructure

## Testing

- Unit test for `carve_above_columns()` with known small grids
- Test with `min_consecutive=1` (any carved voxel triggers)
- Test with `min_consecutive=2` (the example from the spec)
- Test that columns with no qualifying runs are untouched
- Test that only occupied voxels are carved (empty voxels ignored)
- Test that `carve_above=False` (default) produces no change
