"""
Sun direction vectors for UrbanSolarCarver.

``get_sun_vectors(epw_file, date_list, min_altitude, device, north_deg)``
reads the site location from an EnergyPlus weather (EPW) file, computes
the sun position for each Ladybug ``DateTime`` with a Ladybug ``Sunpath``,
drops positions at or below ``min_altitude`` degrees, and returns an
(N, 3) float32 tensor of unit vectors pointing from the model toward the
sun, in model coordinates.

Parsed EPW files (``_load_epw_file``) and Sunpath objects
(``_initialize_sunpath``) are cached, so repeated calls, for example in
the daemon, do not re-read or rebuild them.
"""

import os
from functools import lru_cache
from typing import Sequence
import warnings
import torch
from ladybug.dt import DateTime
from ladybug.epw import EPW
from ladybug.sunpath import Sunpath

@lru_cache(maxsize=16)
def _load_epw_file(weather_file_path: str, mtime_ns: int, size: int) -> EPW:
    """Parse an EPW file (cached).

    The modification time and size are part of the cache key, so an EPW
    replaced on disk while the daemon runs is read again.

    Args:
      weather_file_path: Normalised absolute path of the EPW file.
      mtime_ns, size: File modification time (ns) and size (bytes), used
        only as part of the cache key.

    Raises:
      ValueError: If the path is empty or not a string.
      FileNotFoundError: If no file exists at the path.
      IOError: If the EPW reader fails to parse the file.

    Returns:
      A Ladybug EPW object with weather and location attributes.
    """
    if not isinstance(weather_file_path, str) or not weather_file_path:
        raise ValueError(f"_load_epw_file: invalid path: {weather_file_path!r}")
    if not os.path.isfile(weather_file_path):
        raise FileNotFoundError(f"_load_epw_file: file not found: {weather_file_path}")
    try:
        epw_object = EPW(weather_file_path)
    except Exception as err:
        raise IOError(
            f"_load_epw_file: failed to load EPW '{weather_file_path}': {err}"
        ) from err
    return epw_object


def _load_epw(weather_file_path: str) -> EPW:
    """Normalize the file path, then call the cached loader.

    Normalizing makes different spellings of one path (for example
    forward and back slashes on Windows) share a single cache entry.

    Raises ValueError for an empty or non-string path and
    FileNotFoundError if the file does not exist.
    """
    if not isinstance(weather_file_path, str) or not weather_file_path:
        raise ValueError(f"_load_epw: invalid path: {weather_file_path!r}")
    canonical = os.path.normpath(os.path.abspath(weather_file_path))
    if not os.path.isfile(canonical):
        raise FileNotFoundError(f"_load_epw: file not found: {weather_file_path}")
    stat = os.stat(canonical)
    return _load_epw_file(canonical, stat.st_mtime_ns, stat.st_size)

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
                    (USC convention, same as ``cfg.north_deg``).  Sun
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
    weather_data = _load_epw(epw_file)
    location_info = weather_data.location

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
        warnings.warn(
            f"get_sun_vectors: no sun vectors above {min_altitude:.1f}° for file '{epw_file}'",
            UserWarning,
            stacklevel=2,
        )
    result_array = (
        torch.tensor(
            sun_vectors, dtype=torch.float32, device=device
        ) if sun_vectors else torch.empty(
            (0, 3), dtype=torch.float32, device=device
        )
    )
    return result_array
