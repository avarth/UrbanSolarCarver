"""Tests for carve_above_columns post-processing."""
import numpy as np
import pytest


def _col_grid(columns: dict, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Build small 3D grids from per-column specs.

    Parameters
    ----------
    columns : dict
        Mapping of (x, y) -> str where each character is '#' (occupied+kept),
        'x' (occupied+carved), '.' (empty in original envelope, mask True), or
        'o' (empty in original envelope, mask False).
        String is ordered top-to-bottom (index -1 is z=0, index 0 is z=height-1).
        Cells not covered by a column string are occupied and kept.
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
            elif ch == 'o':
                mask[x, y, z] = False        # empty, but the mask says carved
                voxel_grid[x, y, z] = False  # (thresholding marks air False)
            else:
                raise ValueError(f"Unknown char '{ch}' in column ({x},{y})")
    return mask, voxel_grid


class TestCarveAboveColumns:
    """Tests for the carve_above_columns function."""

    def test_spec_example_min2(self):
        """Worked example with three columns and min_consecutive=2.

        Grid (top-to-bottom, reading each column):
            ABC       A: ##xxx#   B: ###x##   C: #xx###
            ###       (top-to-bottom strings)
            ##x
            x#x       A bottom-up: #,x,x,x,#,#: 3 consec >= 2 → carve 2 above
            xx#       B bottom-up: #,#,x,#,#,#: 1 consec < 2  → no trigger, x stays carved
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

        # B: run of 1 at z2, below threshold → no trigger; the x stays carved
        assert result[1, 0, 2] == False  # never refilled (would undo the constraint)
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

    def test_empty_cells_never_trigger(self):
        """Air below a mass (a passage, the grid margin) is not carved mass,
        whatever the mask says about it."""
        from urbansolarcarver.carving import carve_above_columns

        # bottom-up: o, o, o, #, #: a bridge over a passage the mask marks False
        mask, vg = _col_grid({(0, 0): "##ooo"}, height=5)
        result = carve_above_columns(mask, vg, min_consecutive=1)
        assert result[0, 0, 3] and result[0, 0, 4]

    def test_empty_cells_break_runs(self):
        """x, o, x is two runs of one, not a run of three."""
        from urbansolarcarver.carving import carve_above_columns

        # bottom-up: #, x, o, x, #
        mask, vg = _col_grid({(0, 0): "#xox#"}, height=5)
        result = carve_above_columns(mask, vg, min_consecutive=2)
        assert result[0, 0, 4]  # not triggered: no run reaches 2

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

    def test_short_runs_do_not_trigger_and_stay_carved(self):
        """Carved runs shorter than min_consecutive neither trigger nor refill."""
        from urbansolarcarver.carving import carve_above_columns

        # bottom-up: #, #, x, #, #: a single carved voxel, min=2
        mask, vg = _col_grid({(0, 0): "##x##"}, height=5)
        result = carve_above_columns(mask, vg, min_consecutive=2)

        np.testing.assert_array_equal(result, mask)

    def test_short_run_below_long_run_stays_carved(self):
        """A short run below a qualifying run stays carved; carve-above fires."""
        from urbansolarcarver.carving import carve_above_columns

        # bottom-up: #, x, #, x, x, #, #: run of 1 at z1, run of 2 at z3-z4
        mask, vg = _col_grid({(0, 0): "##xx#x#"}, height=7)
        result = carve_above_columns(mask, vg, min_consecutive=2)

        assert result[0, 0, 0] == True   # bottom #
        assert result[0, 0, 1] == False  # x stays carved (run of 1 < 2)
        assert result[0, 0, 2] == True   # #
        assert result[0, 0, 3] == False  # x (part of qualifying run)
        assert result[0, 0, 4] == False  # x (part of qualifying run)
        assert result[0, 0, 5] == False  # # carved above
        assert result[0, 0, 6] == False  # # carved above

    def test_multiple_columns_independent(self):
        """Each column is processed independently."""
        from urbansolarcarver.carving import carve_above_columns

        mask, vg = _col_grid({
            (0, 0): "##xx#",  # 2 consecutive → carve above
            (1, 0): "#x###",  # 1 consecutive → no trigger (min=2)
        }, height=5)
        result = carve_above_columns(mask, vg, min_consecutive=2)

        # Column (0,0): bottom-up #,x,x,#,# → #,x,x,carved,carved
        assert result[0, 0, 3] == False
        assert result[0, 0, 4] == False

        # Column (1,0): bottom-up #,#,#,x,# → x stays carved, top not triggered
        assert result[1, 0, 3] == False
        assert result[1, 0, 4] == True


# ---------------------------------------------------------------------------
# Slope limit (limit_column_slope)
# ---------------------------------------------------------------------------

def _heights(mask):
    z = np.arange(mask.shape[2])
    return np.where(mask.any(axis=2), (mask * (z + 1)).max(axis=2), 0)


class TestLimitColumnSlope:
    def test_spire_is_cut_to_one_step_above_its_surroundings(self):
        from urbansolarcarver.carving import limit_column_slope
        m = np.zeros((9, 9, 60), bool)
        m[:, :, :10] = True
        m[4, 4, :] = True                      # 60-voxel spire on a 10-voxel plateau
        out = limit_column_slope(m, m.copy(), 45.0)      # one step = 1 voxel
        assert _heights(out)[4, 4] == 11
        assert (_heights(out)[_heights(m) == 10] == 10).all()

    def test_cliff_becomes_a_ramp_no_steeper_than_the_limit(self):
        from urbansolarcarver.carving import limit_column_slope
        m = np.zeros((70, 6, 60), bool)
        m[:20, :, :10] = True                  # low part
        m[20:, :, :60] = True                  # tall part: a 50-voxel cliff
        out = limit_column_slope(m, m.copy(), 60.0)
        h = _heights(out)[:, 3].astype(float)
        rise = np.tan(np.radians(60.0))
        ramp = h[20:][h[20:] < 60]
        # Along the ramp the height climbs at the limit's rate (heights are
        # whole voxels, so single steps vary by one); a column may also stand
        # one step above its reference, which shows at the foot.
        assert np.all(np.diff(h) <= 2 * rise + 1.0)
        assert abs((ramp[-1] - ramp[0]) / (len(ramp) - 1) - rise) < 0.1
        assert h[-1] == 60                     # far from the cliff: untouched

    def test_only_removes_voxels(self):
        from urbansolarcarver.carving import limit_column_slope
        rng = np.random.default_rng(0)
        h = rng.integers(0, 40, (20, 20))
        m = np.arange(40)[None, None, :] < h[:, :, None]
        out = limit_column_slope(m, m.copy(), 70.0)
        assert not (out & ~m).any()

    def test_narrow_slot_does_not_pull_neighbours_down(self):
        from urbansolarcarver.carving import limit_column_slope
        occ = np.ones((20, 20, 30), bool)
        m = occ.copy()
        m[9:11, :, :] = False                  # a 2-column slot carved to the ground
        out = limit_column_slope(m, occ, 45.0)
        assert np.array_equal(out, m)

    def test_wide_carved_area_gets_a_ramp_beside_it(self):
        from urbansolarcarver.carving import limit_column_slope
        occ = np.ones((50, 6, 30), bool)
        m = occ.copy()
        m[:10, :, :] = False                   # 10 columns carved to the ground
        out = limit_column_slope(m, occ, 45.0)
        h = _heights(out)[:, 3]
        assert h[10] < 30 and h[-1] == 30      # ramp next to the carved area

    def test_columns_outside_the_building_take_no_part(self):
        from urbansolarcarver.carving import limit_column_slope
        occ = np.zeros((20, 20, 30), bool)
        occ[:, :8, :] = True                   # two blocks across an open street
        occ[:, 12:, :] = True
        out = limit_column_slope(occ.copy(), occ, 45.0)
        assert np.array_equal(out, occ)

    def test_carving_more_never_keeps_more(self):
        from urbansolarcarver.carving import limit_column_slope
        rng = np.random.default_rng(1)
        occ = np.ones((24, 24, 40), bool)
        h_loose = rng.integers(0, 41, (24, 24))
        h_tight = np.minimum(h_loose, rng.integers(0, 41, (24, 24)))
        z = np.arange(40)[None, None, :]
        loose = limit_column_slope(z < h_loose[:, :, None], occ, 60.0)
        tight = limit_column_slope(z < h_tight[:, :, None], occ, 60.0)
        assert not (tight & ~loose).any()

    def test_single_low_stub_does_not_pull_neighbours_down(self):
        from urbansolarcarver.carving import limit_column_slope
        m = np.zeros((11, 11, 30), bool)
        m[:, :, :30] = True
        m[5, 5, 1:] = False                    # one column cut to a 1-voxel stub
        out = limit_column_slope(m, m.copy(), 45.0)
        assert np.array_equal(out, m)

    def test_rejects_angles_outside_0_90(self):
        from urbansolarcarver.carving import limit_column_slope
        with pytest.raises(ValueError):
            limit_column_slope(np.ones((2, 2, 2), bool), np.ones((2, 2, 2), bool), 90.0)
