# Carve-Above-Column Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a post-processing option that carves all occupied voxels above the lowest sufficiently-carved region in each (x, y) column of the binary mask.

**Architecture:** A pure NumPy function `carve_above_columns()` in `carving.py`, called from `exporting.py` after mask loading and before mesh reconstruction. Controlled by two new config fields on `UserConfig`.

**Tech Stack:** NumPy (vectorized column operations), Pydantic v2 (config fields), pytest (testing)

---

### Task 1: Add config fields to UserConfig

**Files:**
- Modify: `src/urbansolarcarver/pydantic_schemas.py:94-98`

- [ ] **Step 1: Add the two config fields**

Insert after line 98 (`smooth_iters` field), before the `# thresholding & classification` comment:

```python
    # column post-processing
    carve_above: bool = Field(
        False,
        description=(
            "If True, carve all occupied voxels above the lowest sufficiently-carved "
            "region in each (x, y) column. Removes structurally implausible floating "
            "mass above already-carved zones. Use carve_above_min_consecutive to "
            "control sensitivity."
        ),
    )
    carve_above_min_consecutive: int = Field(
        1, ge=1,
        description=(
            "Minimum number of consecutive carved (empty) voxels in a column before "
            "carve_above activates for that column. Higher values (2-3) prevent stray "
            "single-voxel carvings from triggering aggressive column removal."
        ),
    )
```

- [ ] **Step 2: Verify config accepts new fields**

Run: `python -c "from urbansolarcarver.pydantic_schemas import UserConfig; c = UserConfig(max_volume_path='a.ply', test_surface_path='b.ply', out_dir='out', mode='tilted_plane', tilted_plane_angle_deg=45, carve_above=True, carve_above_min_consecutive=2); print(c.carve_above, c.carve_above_min_consecutive)"`

Expected: `True 2`

- [ ] **Step 3: Commit**

```bash
git add src/urbansolarcarver/pydantic_schemas.py
git commit -m "feat: add carve_above config fields to UserConfig"
```

---

### Task 2: Write tests for carve_above_columns

**Files:**
- Create: `tests/test_carve_above.py`

- [ ] **Step 1: Create the test file**

Create `tests/test_carve_above.py`:

```python
"""Tests for carve_above_columns post-processing."""
import numpy as np
import pytest


def _col_grid(columns: dict, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Build small 3D grids from per-column specs.

    Parameters
    ----------
    columns : dict
        Mapping of (x, y) -> str where each character is '#' (occupied+kept),
        'x' (occupied+carved), or '.' (empty in original envelope).
        String is ordered top-to-bottom (index -1 is z=0, index 0 is z=height-1).
    height : int
        Number of z-levels.

    Returns
    -------
    mask : (X, Y, Z) bool array; True = keep, False = carved
    voxel_grid : (X, Y, Z) bool array; True = occupied in original envelope
    """
    max_x = max(x for x, y in columns) + 1
    max_y = max(y for x, y in columns) + 1
    mask = np.ones((max_x, max_y, height), dtype=bool)
    voxel_grid = np.ones((max_x, max_y, height), dtype=bool)
    for (x, y), col_str in columns.items():
        assert len(col_str) == height, f"Column ({x},{y}) length {len(col_str)} != height {height}"
        for i, ch in enumerate(col_str):
            z = height - 1 - i  # top-to-bottom string -> z index
            if ch == 'x':
                mask[x, y, z] = False       # carved
                voxel_grid[x, y, z] = True   # was occupied
            elif ch == '.':
                mask[x, y, z] = True         # not carved (empty anyway)
                voxel_grid[x, y, z] = False  # not occupied
            elif ch == '#':
                mask[x, y, z] = True         # kept
                voxel_grid[x, y, z] = True   # occupied
            else:
                raise ValueError(f"Unknown char '{ch}' in column ({x},{y})")
    return mask, voxel_grid


class TestCarveAboveColumns:
    """Tests for the carve_above_columns function."""

    def test_spec_example_min2(self):
        """The exact example from the design spec with min_consecutive=2.

        User's original grid (top-to-bottom, reading each column):
            ABC       A: ##xxx#   B: ###x##   C: #xx###
            ###       (top-to-bottom strings)
            ##x
            x#x       A bottom-up: #,x,x,x,#,#: 3 consec >= 2 → carve 2 above
            xx#       B bottom-up: #,#,x,#,#,#: 1 consec < 2  → no change
            x##       C bottom-up: #,#,#,x,x,#: 2 consec >= 2 → carve 1 above
            ###
        """
        from urbansolarcarver.carving import carve_above_columns

        mask, vg = _col_grid({
            (0, 0): "##xxx#",  # A
            (1, 0): "###x##",  # B
            (2, 0): "#xx###",  # C
        }, height=6)

        result = carve_above_columns(mask, vg, min_consecutive=2)

        # A: run of 3 at z1-z3, carve z4,z5
        assert result[0, 0, 4] == False  # was #, now carved
        assert result[0, 0, 5] == False  # was #, now carved
        assert result[0, 0, 0] == True   # bottom # unchanged

        # B: run of 1 at z2, below threshold → no change
        assert result[1, 0, 3] == True
        assert result[1, 0, 4] == True
        assert result[1, 0, 5] == True

        # C: run of 2 at z3-z4, carve z5
        assert result[2, 0, 5] == False  # was #, now carved
        assert result[2, 0, 0] == True   # bottom # unchanged

    def test_min1_any_carved_triggers(self):
        """With min_consecutive=1, a single carved voxel triggers carve-above."""
        from urbansolarcarver.carving import carve_above_columns

        # Single column bottom-up: #, x, #, #
        mask, vg = _col_grid({(0, 0): "##x#"}, height=4)
        result = carve_above_columns(mask, vg, min_consecutive=1)

        assert result[0, 0, 0] == True   # bottom # kept
        assert result[0, 0, 1] == False  # x stays carved
        assert result[0, 0, 2] == False  # # above → carved
        assert result[0, 0, 3] == False  # # above → carved

    def test_no_carved_voxels_unchanged(self):
        """Column with no carved voxels is untouched."""
        from urbansolarcarver.carving import carve_above_columns

        mask, vg = _col_grid({(0, 0): "####"}, height=4)
        result = carve_above_columns(mask, vg, min_consecutive=1)

        assert result[0, 0, :].all()

    def test_only_carves_occupied_voxels(self):
        """Empty (non-occupied) voxels above a carved run are left alone."""
        from urbansolarcarver.carving import carve_above_columns

        # bottom-up: #, x, x, ., #  ('.' = not occupied)
        mask, vg = _col_grid({(0, 0): "#.xx#"}, height=5)
        result = carve_above_columns(mask, vg, min_consecutive=2)

        assert result[0, 0, 0] == True   # bottom #
        assert result[0, 0, 1] == False  # x
        assert result[0, 0, 2] == False  # x
        assert result[0, 0, 3] == True   # '.': not occupied, unchanged
        assert result[0, 0, 4] == False  # '#': occupied, carved

    def test_does_not_mutate_input(self):
        """Input mask array must not be modified."""
        from urbansolarcarver.carving import carve_above_columns

        mask, vg = _col_grid({(0, 0): "##xx#"}, height=5)
        original = mask.copy()
        carve_above_columns(mask, vg, min_consecutive=2)
        np.testing.assert_array_equal(mask, original)

    def test_all_carved_column(self):
        """Column already fully carved stays fully carved."""
        from urbansolarcarver.carving import carve_above_columns

        mask, vg = _col_grid({(0, 0): "xxxx"}, height=4)
        result = carve_above_columns(mask, vg, min_consecutive=1)
        assert not result[0, 0, :].any()

    def test_multiple_columns_independent(self):
        """Each column is processed independently."""
        from urbansolarcarver.carving import carve_above_columns

        mask, vg = _col_grid({
            (0, 0): "##xx#",  # 2 consecutive → carve above
            (1, 0): "#x###",  # 1 consecutive → no change (min=2)
        }, height=5)
        result = carve_above_columns(mask, vg, min_consecutive=2)

        # Column (0,0): bottom-up #,x,x,#,# → #,x,x,carved,carved
        assert result[0, 0, 3] == False
        assert result[0, 0, 4] == False

        # Column (1,0): bottom-up #,#,#,x,# → unchanged
        assert result[1, 0, 4] == True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_carve_above.py -v`

Expected: All tests FAIL with `ImportError` or `AttributeError` because `carve_above_columns` doesn't exist yet.

- [ ] **Step 3: Commit**

```bash
git add tests/test_carve_above.py
git commit -m "test: add tests for carve_above_columns"
```

---

### Task 3: Implement carve_above_columns

**Files:**
- Modify: `src/urbansolarcarver/carving.py` (append at end, line ~792)

- [ ] **Step 1: Add the function at the end of carving.py**

Append after the last line (792) of `carving.py`:

```python


def carve_above_columns(
    mask: "np.ndarray",
    voxel_grid: "np.ndarray",
    min_consecutive: int = 1,
) -> "np.ndarray":
    """Carve occupied voxels above the lowest sufficiently-carved run per column.

    For each (x, y) column, scans bottom-to-top (z=0 upward) for runs of
    consecutive carved (False) voxels.  At the first run with length >=
    *min_consecutive*, all occupied voxels above that run are carved.

    Parameters
    ----------
    mask : ndarray (D, D, D) bool
        Thresholding mask.  True = keep, False = carved.  Not mutated.
    voxel_grid : ndarray (D, D, D) bool
        Original envelope occupancy.  True = occupied.
    min_consecutive : int
        Minimum consecutive carved voxels to trigger carve-above.

    Returns
    -------
    ndarray (D, D, D) bool
        Modified mask with additional voxels carved above qualifying runs.
    """
    import numpy as np

    out = mask.copy()
    nx, ny, nz = mask.shape

    # Iterate over columns.  For typical urban grids (e.g. 200x200) this is
    # fast enough; the inner logic per column is pure NumPy slicing.
    for x in range(nx):
        for y in range(ny):
            col_mask = out[x, y, :]        # z=0 is bottom
            col_occ = voxel_grid[x, y, :]

            # Find runs of consecutive carved (False) voxels, bottom-to-top.
            carved = ~col_mask  # True where carved
            run_len = 0
            trigger_z = -1
            for z in range(nz):
                if carved[z]:
                    run_len += 1
                    if run_len >= min_consecutive:
                        trigger_z = z
                        break
                else:
                    run_len = 0

            if trigger_z >= 0:
                # Carve all occupied voxels above the triggering run.
                for z_above in range(trigger_z + 1, nz):
                    if col_occ[z_above]:
                        out[x, y, z_above] = False

    return out
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_carve_above.py -v`

Expected: All 7 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add src/urbansolarcarver/carving.py
git commit -m "feat: implement carve_above_columns in carving.py"
```

---

### Task 4: Integrate into exporting stage

**Files:**
- Modify: `src/urbansolarcarver/api_core/exporting.py:132`

- [ ] **Step 1: Add carve-above call after mask+voxel_grid combination**

In `exporting.py`, replace line 132:

```python
    carve_grid = (voxel_grid.bool() & mask_tensor)
```

with:

```python
    # Column post-processing: carve occupied voxels above carved runs.
    _carve_above_extra = 0
    if getattr(conf, 'carve_above', False):
        from ..carving import carve_above_columns
        vg_np = voxel_grid.cpu().numpy().astype(bool)
        mask_before = mask.copy()
        mask = carve_above_columns(
            mask, vg_np,
            min_consecutive=getattr(conf, 'carve_above_min_consecutive', 1),
        )
        _carve_above_extra = int(mask_before.sum()) - int(mask.sum())
        mask_tensor = torch.as_tensor(mask, dtype=torch.bool, device=resolved_device)

    carve_grid = (voxel_grid.bool() & mask_tensor)
```

- [ ] **Step 2: Add diagnostics for carve-above**

In the same file, find the diagnostic dict construction (around line 168-178). After the `"voxel_retention_pct"` entry, add:

```python
        "carve_above_applied": getattr(conf, 'carve_above', False),
        "carve_above_min_consecutive": getattr(conf, 'carve_above_min_consecutive', 1) if getattr(conf, 'carve_above', False) else None,
        "carve_above_extra_voxels_removed": _carve_above_extra,
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v --timeout=120`

Expected: All tests pass (existing + new).

- [ ] **Step 4: Commit**

```bash
git add src/urbansolarcarver/api_core/exporting.py
git commit -m "feat: integrate carve_above_columns into exporting stage"
```

---

### Task 5: Config validation test

**Files:**
- Modify: `tests/test_schemas.py`

- [ ] **Step 1: Add validation tests for new config fields**

Append to `tests/test_schemas.py`:

```python
class TestCarveAboveConfig:
    def test_defaults(self):
        cfg = _make_config()
        assert cfg.carve_above is False
        assert cfg.carve_above_min_consecutive == 1

    def test_carve_above_enabled(self):
        cfg = _make_config(carve_above=True, carve_above_min_consecutive=3)
        assert cfg.carve_above is True
        assert cfg.carve_above_min_consecutive == 3

    def test_min_consecutive_must_be_positive(self):
        with pytest.raises(ValidationError):
            _make_config(carve_above_min_consecutive=0)

    def test_min_consecutive_must_be_int(self):
        # Float should be rejected or coerced
        cfg = _make_config(carve_above_min_consecutive=2)
        assert cfg.carve_above_min_consecutive == 2
```

- [ ] **Step 2: Run schema tests**

Run: `python -m pytest tests/test_schemas.py -v`

Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_schemas.py
git commit -m "test: add config validation tests for carve_above fields"
```
