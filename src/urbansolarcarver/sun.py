"""
UrbanSolarCarver Solar Vector Module

This module handles solar position computations and caching for the
UrbanSolarCarver pipeline. It converts meteorological data and date-time
information into normalized sun direction vectors suitable for voxel
carving or ray tracing.

Core Responsibilities
---------------------
1. EPW Loading and Caching
   • _load_epw(epw_file: str) → EPW
     - Validates and reads an EnergyPlus weather (EPW) file.
     - Caches the EPW object to avoid repeated disk and parse overhead.

2. Sunpath Initialization and Caching
   • _get_sunpath(latitude: float, longitude: float, time_zone: float) → Sunpath
     - Creates a Ladybug Sunpath instance for the site location.
     - Caches the Sunpath to reuse across multiple calls.

3. Cache Pre-Warming
   • warm_up(epw_file: str) → None
     - Loads EPW and Sunpath caches on demand to improve the first-call latency.

4. Sun Vector Computation
   • get_sun_vectors(
         epw_file: str,
         datetimes: Sequence[DateTime],
         min_altitude: float,
         device: torch.device
     ) → torch.Tensor
     - Validates inputs: EPW path, Ladybug DateTime sequence, and altitude threshold.
     - Computes sun position for each DateTime.
     - Filters out sun positions below the minimum solar altitude.
     - Returns an Nx3 tensor of unit vectors (x, y, z) pointing toward the sun.

Key Data Structures
-------------------
• EPW                - Ladybug class representing weather data.
• Sunpath            - Ladybug class for solar geometry calculations.
• torch.Tensor       - Used to return GPU- or CPU-ready arrays of sun vectors.
• Ladybug DateTime   - Input time stamps for sun position queries.

Usage Context
-------------
Import this module when you need to translate a series of date-times into
sun direction vectors for carving routines. The caching mechanisms ensure
that repeated calls reuse loaded EPW and Sunpath objects, minimizing I/O
and initialization overhead during high-throughput analyses.
"""

import os
from functools import lru_cache
from typing import Sequence
import warnings
import torch
from ladybug.dt import DateTime
from ladybug.epw import EPW
from ladybug.sunpath import Sunpath

@lru_cache(maxsize=None)
#lru_cache accelerates repeated calls in long‐running processes and keeps identical inputs from blowing up memory.
def _load_epw_file(weather_file_path: str) -> EPW:
    """
    Load an EPW weather file from disk and cache it.

    Explanation:
      - EPW files contain location-specific climate data.
      - Caching avoids reloading the same file repeatedly, saving time.

    Args:
      weather_file_path: Path string pointing to the EPW file.

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
        raise IOError(f"_load_epw_file: failed to load EPW '{weather_file_path}': {err}")
    return epw_object


def _load_epw(weather_file_path: str) -> EPW:
    """Normalize the file path then delegate to the cached loader.

    This ensures that ``"C:/data/w.epw"`` and ``"C:\\\\data\\\\w.epw"``
    resolve to a single cache entry on Windows.
    """
    if not isinstance(weather_file_path, str) or not weather_file_path:
        raise ValueError(f"_load_epw: invalid path: {weather_file_path!r}")
    canonical = os.path.normpath(os.path.abspath(weather_file_path))
    return _load_epw_file(canonical)

@lru_cache(maxsize=None)
def _initialize_sunpath(
    latitude: float, longitude: float, time_zone: float, north_angle: float = 0.0
) -> Sunpath:
    """
    Create and cache a Sunpath instance for given geographic coordinates.

    Explanation:
      - Sunpath computes the sun's position over time at a fixed location.
      - Caching prevents re-initialization overhead for repeated calls.

    Args:
      north_angle: Ladybug convention — degrees COUNTERCLOCKWISE from the
        +Y axis. Callers using the USC ``north_deg`` config value (clockwise)
        must negate it before passing it here.

    Raises:
      RuntimeError: If the Sunpath constructor fails.

    Returns:
      A Ladybug Sunpath object for sun position calculations.
    """
    try:
        sunpath_object = Sunpath(latitude, longitude, time_zone, north_angle=north_angle)
    except Exception as err:
        raise RuntimeError(f"_initialize_sunpath: failed to init Sunpath: {err}")
    return sunpath_object

# Function to pre-load both EPW and Sunpath caches
def warm_up(epw_file: str) -> None:
    """
    Load weather and sunpath data into memory to reduce latency on first real call.
    Ensures that subsequent calls to get_sun_vectors are faster.
    """
    weather_data = _load_epw(epw_file)
    location_info = weather_data.location
    _initialize_sunpath(
        location_info.latitude,
        location_info.longitude,
        location_info.time_zone
    )

# Main function for users: computes sun direction vectors
def get_sun_vectors(
    epw_file: str,
    date_list: Sequence[DateTime],
    min_altitude: float = 5.0,
    device: torch.device = torch.device('cpu'),
    north_deg: float = 0.0,
) -> torch.Tensor:
    """
    Determine the sun's unit direction vectors at specified times.

    Explanation:
      1. Read location and climate data from an EPW file.
      2. For each datetime in the list, compute sun position.
      3. Filter out moments when the sun is below a minimum elevation angle.
      4. Return a list of 3D vectors pointing toward the sun for each valid time.

    Args:
      epw_file    : File path to the climate data (EPW format).
      date_list   : Collection of Ladybug DateTime objects to evaluate.
      min_altitude: Minimum sun elevation (degrees) to include.
      device      : Torch device to store result (CPU or GPU).
      north_deg   : Model north in degrees CLOCKWISE from the +Y axis
                    (USC convention, same as ``cfg.north_deg``).  Sun
                    vectors are returned in model coordinates.

    Returns:
      A torch.Tensor of shape (N,3), dtype float32, where each row
      is a normalized vector pointing from origin toward the sun.

    Raises:
      ValueError: If inputs are of incorrect type or empty.
      RuntimeError: If sun position calculation fails.
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
    sun_vectors = []  # Will collect valid sun direction tuples
    for date_time in date_list:
        try:
            # Retrieve sun data for a given date/time
            sun_data = sunpath_calculator.calculate_sun_from_date_time(
                date_time,
                is_solar_time=False  # EPW files use standard/DST time, not solar time
            )
        except Exception as err:
            raise RuntimeError(
                f"get_sun_vectors: error computing sun for {date_time}: {err}"
            )

        # Filter: sun must be above the horizon AND above min_altitude.
        # Low-altitude sun has long atmospheric paths and contributes little
        # direct irradiance — filtering avoids noisy near-horizon rays.
        if sun_data.is_during_day and sun_data.altitude > min_altitude:
            # Ladybug's sun_vector points FROM the sun TO the surface (downward).
            # sun_vector_reversed points FROM the surface TOWARD the sun —
            # which is the ray direction we need for obstruction testing.
            inverted_vector = sun_data.sun_vector_reversed
            if inverted_vector is not None:
                sun_vectors.append(
                    (inverted_vector.x, inverted_vector.y, inverted_vector.z)
                )

    # Warn if no valid vectors found
    if not sun_vectors:
        warnings.warn(
            f"get_sun_vectors: no sun vectors above {min_altitude:.1f}° for file '{epw_file}'",
            UserWarning,
            stacklevel=2,
        )
    # Step 5: Convert Python list into a Torch tensor
    result_array = (
        torch.tensor(
            sun_vectors, dtype=torch.float32, device=device
        ) if sun_vectors else torch.empty(
            (0, 3), dtype=torch.float32, device=device
        )
    )
    return result_array
