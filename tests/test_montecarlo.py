"""A few fixed Monte Carlo cases in the regular suite.

The full randomized sweep is ``tests/montecarlo.py`` (see its docstring).
These seeds cover every mode except radiative_cooling, carve_above with
min_consecutive > 1, octant tilt tables, rotated scenes, a non-zero
time-based tolerance, headtail, and georeferenced offsets; each case also
runs the translation check.
"""
import pytest

import montecarlo

SEEDS = [
    1006,  # tilted_plane, octant table, carve_above, rotated, UTM
    1036,  # time-based, carve_above
    1001,  # time-based, threshold 2 m²·h
    1017,  # benefit, carve_above, UTM
    1048,  # irradiance, UTM
    1009,  # irradiance, headtail, carve_above
    1042,  # daylight, carve_above, rotated
    1035,  # daylight, irregular: found the edge-row sampling bug
]


@pytest.fixture(scope="module")
def epw():
    from _epw import resolve_epw
    path = resolve_epw()
    if not path:
        pytest.skip("No EPW file found")
    return path


@pytest.mark.parametrize("seed", SEEDS)
def test_montecarlo_case(tmp_path, epw, seed):
    rec = montecarlo.run_case(seed, epw, "cpu", tmp_path, translate_prob=1.0)
    assert not rec["failed"], (rec["failed"], rec.get("error"), rec.get("traceback"), rec["metrics"])
