"""
Sun direction vectors for UrbanSolarCarver.

``get_sun_vectors(epw_file, date_list, min_altitude, device, north_deg)``
reads the site location from an EnergyPlus weather (EPW) file, computes
the sun position for each Ladybug ``DateTime`` with a Ladybug ``Sunpath``,
drops positions at or below ``min_altitude`` degrees, and returns an
(N, 3) float32 tensor of unit vectors pointing from the model toward the
sun, in model coordinates.

EPW files are read through the cached ``weather_file.read_weather_file``
and Sunpath objects (``_initialize_sunpath``) are cached, so repeated
calls, for example in the daemon, do not re-read or rebuild them.

``sample_period`` turns the analysis period of the preprocessing settings
into the Ladybug ``DateTime`` list the sun positions are computed for.
"""

from functools import lru_cache
from typing import Sequence
import torch
from ladybug.analysisperiod import AnalysisPeriod
from ladybug.dt import DateTime
from ladybug.sunpath import Sunpath

from .run_context import report_issue
from .weather_file import read_weather_file
from .stage_settings import PreprocessingSettings

@lru_cache(maxsize=None)
def _initialize_sunpath(
    latitude: float, longitude: float, time_zone: float, north_angle: float = 0.0
) -> Sunpath:
    """
    Create a Ladybug Sunpath for a location (cached per argument set).

    Args:
      latitude, longitude: Site location in degrees.
      time_zone: Offset from UTC in hours.
      north_angle: Ladybug convention, degrees counterclockwise from the
        +Y axis. The USC ``north_deg`` config value is clockwise, so
        callers negate it before passing it here.

    Raises:
      RuntimeError: If the Sunpath constructor fails.

    Returns:
      A Ladybug Sunpath object for sun position calculations.
    """
    try:
        sunpath_object = Sunpath(latitude, longitude, time_zone, north_angle=north_angle)
    except Exception as err:
        raise RuntimeError(f"_initialize_sunpath: failed to init Sunpath: {err}") from err
    return sunpath_object

def get_sun_vectors(
    epw_file: str,
    date_list: Sequence[DateTime],
    min_altitude: float = 5.0,
    device: torch.device = torch.device('cpu'),
    north_deg: float = 0.0,
) -> torch.Tensor:
    """
    Unit vectors toward the sun at the given times, for times when the sun
    is above ``min_altitude``.

    Args:
      epw_file    : Path to the EPW weather file; only its location
                    (latitude, longitude, time zone) is used.
      date_list   : Iterable of Ladybug DateTime objects, in the EPW's
                    local standard time.
      min_altitude: Sun altitude in degrees; times with the sun at or
                    below it are dropped.
      device      : Torch device for the result.
      north_deg   : Model north in degrees clockwise from the +Y axis
                    (USC convention, same as the ``north_deg`` setting).  Sun
                    vectors are returned in model coordinates.

    Returns:
      A float32 torch.Tensor of shape (N, 3), N <= len(date_list), one
      unit vector per kept time pointing from the model toward the sun.
      Empty (0, 3) with a UserWarning if no time is kept.

    Raises:
      ValueError: If date_list is not iterable, is empty or holds
        non-DateTime items, or min_altitude is not a finite number.
      FileNotFoundError, IOError: If the EPW file is missing or unreadable.
      RuntimeError: If the sun position calculation fails.
    """
    # Step 1: Load EPW and extract geographic info
    location_info = read_weather_file(epw_file).location

    # Step 2: Validate the list of DateTime inputs
    if not hasattr(date_list, '__iter__'):
        raise ValueError("get_sun_vectors: date_list must be iterable")
    date_list = list(date_list)
    if not date_list:
        raise ValueError("get_sun_vectors: date_list must not be empty")
    for date_time in date_list:
        if not isinstance(date_time, DateTime):
            raise ValueError(
                "get_sun_vectors: each element must be a Ladybug DateTime"
            )

    if not isinstance(min_altitude, (int, float)):
        raise ValueError(
            f"get_sun_vectors: min_altitude must be a number, got {type(min_altitude).__name__}"
        )
    import math as _math
    if _math.isnan(min_altitude) or _math.isinf(min_altitude):
        raise ValueError(
            f"get_sun_vectors: min_altitude must be finite, got {min_altitude}"
        )

    # Step 3: Initialize sunpath for this location.
    # USC's north_deg is clockwise from +Y; Ladybug's north_angle is
    # counterclockwise, so negate to convert.
    sunpath_calculator = _initialize_sunpath(
        location_info.latitude,
        location_info.longitude,
        location_info.time_zone,
        north_angle=-float(north_deg),
    )

    # Step 4: Compute and filter sun vectors
    sun_vectors = []
    for date_time in date_list:
        try:
            sun_data = sunpath_calculator.calculate_sun_from_date_time(
                date_time,
                is_solar_time=False  # EPW hours are local standard time, not solar time
            )
        except Exception as err:
            raise RuntimeError(
                f"get_sun_vectors: error computing sun for {date_time}: {err}"
            ) from err

        # Keep only times when the sun is above the horizon and above
        # min_altitude.  Near the horizon the sun's light crosses a long
        # path through the atmosphere and adds little direct irradiance.
        if sun_data.is_during_day and sun_data.altitude > min_altitude:
            # Ladybug's sun_vector points from the sun down to the surface;
            # sun_vector_reversed points from the surface toward the sun,
            # which is the ray direction used for obstruction testing.
            inverted_vector = sun_data.sun_vector_reversed
            if inverted_vector is not None:
                sun_vectors.append(
                    (inverted_vector.x, inverted_vector.y, inverted_vector.z)
                )

    if not sun_vectors:
        report_issue(
            "no_sun_vectors",
            f"get_sun_vectors: no sun vectors above {min_altitude:.1f}° for file '{epw_file}'",
        )
    result_array = (
        torch.tensor(
            sun_vectors, dtype=torch.float32, device=device
        ) if sun_vectors else torch.empty(
            (0, 3), dtype=torch.float32, device=device
        )
    )
    return result_array


def sample_period(settings: PreprocessingSettings, steps_per_hour: int = 1):
    """
    Build analysis datetimes and HOYs via Ladybug's AnalysisPeriod.

    Returns
    -------
    datetimes : list[datetime.datetime]
        Start to end (inclusive) at ``1/steps_per_hour``-hour steps.
    hoys : list[int]
        Hour-of-year indices (0..8759, 0 = 1 January 00:00) of the period,
        always hourly: they index EPW records, which are hourly.
    """
    def _ap(timestep):
        return AnalysisPeriod(
            st_month=settings.start_month, st_day=settings.start_day, st_hour=settings.start_hour,
            end_month=settings.end_month,   end_day=settings.end_day,   end_hour=settings.end_hour,
            timestep=timestep,
        )
    hourly = _ap(1)
    if steps_per_hour == 1:
        return hourly.datetimes, hourly.hoys_int
    return _ap(steps_per_hour).datetimes, hourly.hoys_int
