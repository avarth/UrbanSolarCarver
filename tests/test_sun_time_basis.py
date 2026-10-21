"""time_basis in get_sun_vectors: with "solar", 12:00 is the moment the sun
crosses the meridian, so it lies due south of a northern mid-latitude site on
any date; with "standard", 12:00 is the EPW's clock and the sun is off south
by the equation of time and the site's distance from its time-zone meridian."""
import math

import numpy as np
import pytest

from _epw import resolve_epw

_EPW = resolve_epw()
pytestmark = pytest.mark.skipif(not _EPW, reason="EPW file not available; set USC_EPW_PATH env var to enable")


def _azimuth_deg(month, day, hour, minute, time_basis, north_deg=0.0):
    """Clockwise from +Y (north when north_deg is 0) of the sun at a time, in degrees."""
    from ladybug.dt import DateTime
    from urbansolarcarver.sun import get_sun_vectors
    x, y, _ = get_sun_vectors(_EPW, [DateTime(month, day, hour, minute)], min_altitude=0.0,
                              north_deg=north_deg, time_basis=time_basis).numpy()[0]
    return math.degrees(math.atan2(x, y)) % 360.0


@pytest.mark.parametrize("month, day", [(12, 21), (2, 11), (6, 21), (11, 3)])
def test_sun_at_solar_noon_is_due_south(month, day):
    from urbansolarcarver.weather_file import read_weather_file
    assert read_weather_file(_EPW).location.latitude > 23.5   # a northern mid-latitude site (Golden, CO)
    assert _azimuth_deg(month, day, 12, 0, "solar") == pytest.approx(180.0, abs=0.05)


def test_standard_noon_differs_from_solar_noon():
    # On 3 November the equation of time is about +16 min, so at 12:00 standard time the sun has already passed south.
    assert _azimuth_deg(11, 3, 12, 0, "standard") > 183.0


def test_solar_noon_follows_north_deg():
    # Model north along +X: south is -X, 270° clockwise from +Y.
    assert _azimuth_deg(12, 21, 12, 0, "solar", north_deg=90.0) == pytest.approx(270.0, abs=0.05)


def test_default_is_standard_time():
    from ladybug.dt import DateTime
    from urbansolarcarver.sun import get_sun_vectors
    times = [DateTime(11, 3, 12, 0)]
    np.testing.assert_array_equal(get_sun_vectors(_EPW, times, 0.0).numpy(),
                                  get_sun_vectors(_EPW, times, 0.0, time_basis="standard").numpy())


def test_unknown_time_basis_is_refused():
    from ladybug.dt import DateTime
    from urbansolarcarver.sun import get_sun_vectors
    with pytest.raises(ValueError, match="time_basis"):
        get_sun_vectors(_EPW, [DateTime(11, 3, 12, 0)], 0.0, time_basis="local")
