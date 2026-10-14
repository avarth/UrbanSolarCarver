"""Building blocks of the recovered_sky threshold (carving.py)."""
import numpy as np
import pytest

from urbansolarcarver.carving import carve_above_columns, recovered_sky_cut, removal_order


@pytest.mark.parametrize("min_consecutive", [1, 2, 3])
@pytest.mark.parametrize("carve_above", [True, False])
def test_removal_order_matches_carve_above(min_consecutive, carve_above):
    """For every cut n, occupancy & (removal >= n) equals carving the voxels
    with rank < n and then running carve_above_columns."""
    rng = np.random.default_rng(min_consecutive)
    for _ in range(60):
        shape = (4, 4, int(rng.integers(3, 15)))
        occ = rng.random(shape) < 0.8                      # with empty cells
        rank = rng.integers(0, 30, shape).astype(np.int32)
        removal = removal_order(rank, occ, carve_above, min_consecutive)
        for n in range(32):
            want = occ & (rank >= n)
            if carve_above:
                want = carve_above_columns(want, occ, min_consecutive)
            assert np.array_equal(occ & (removal >= n), want)


def test_cut_recovers_at_least_the_share_and_no_more_than_needed():
    clear_at = np.array([0, 0, 1, 2, 5, 5, 9])
    weight = np.array([1.0, 1.0, 2.0, 1.0, 3.0, 1.0, 1.0])  # total 10
    cut, rec = recovered_sky_cut(clear_at, weight, 0.4)
    assert (cut, rec) == (2, 0.4)                       # rays clearing at 0 and 1
    cut, rec = recovered_sky_cut(clear_at, weight, 0.41)
    assert (cut, rec) == (3, 0.5)                       # next ray needed
    cut, rec = recovered_sky_cut(clear_at, weight, 0.6)
    assert (cut, rec) == (6, 0.9)                       # both rays at 5 come together
    assert recovered_sky_cut(clear_at, weight, 1.0) == (10, 1.0)
    assert recovered_sky_cut(clear_at, weight, 0.0) == (0, 0.0)
