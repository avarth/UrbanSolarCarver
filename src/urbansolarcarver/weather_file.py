"""
Cached reading of EPW weather files.

``read_weather_file(path)`` parses an EnergyPlus weather (EPW) file with
Ladybug once and returns a ``ParsedWeatherFile`` that every later call
for the same file shares. Parsing a year of hourly weather takes about
0.2 s; the engine needs the same file for the sun positions, the sky
matrices, the cold period, the simulated weights and the service's sun
path, often several times in one run.

The cache key is the file's absolute path, its modification time and its
size, so a file replaced on disk (a new upload, an edited EPW while the
daemon or the browser service runs) is read again.

Ladybug's EPW, Location, data collections and Wea are mutable: a caller
that set ``values`` on a collection, or the city of a location, would
change what every later caller reads. ``ParsedWeatherFile`` therefore
keeps the parsed EPW to itself and hands out copies: a new Location, a
new numpy array, a new Wea on each call. A copy costs under a
millisecond, against the parse it saves, and callers get the Ladybug
types they pass on to Ladybug (a read-only numpy array could not stand in
for a Wea or a Location).
"""

import os
from functools import lru_cache

import numpy as np

# Each parsed file holds about 7 MB (35 hourly fields of a year); a few
# files cover the service switching between projects and the test suite.
CACHED_WEATHER_FILE_COUNT = 8


class ParsedWeatherFile:
    """One parsed EPW file, shared by all callers: every accessor returns a copy."""

    __slots__ = ("path", "_epw")

    def __init__(self, path: str, epw) -> None:
        self.path = path
        self._epw = epw

    @property
    def location(self):
        """A copy of the file's Ladybug Location (latitude, longitude, time zone, city)."""
        return self._epw.location.duplicate()

    def dry_bulb_temperature(self) -> np.ndarray:
        """A new float64 array of the 8760 hourly dry-bulb temperatures [°C]."""
        return np.array(self._epw.dry_bulb_temperature.values, dtype=np.float64)

    def solar_irradiance_wea(self):
        """A new Ladybug Wea with the file's hourly direct normal and diffuse horizontal irradiance [W/m²].

        Built as ``Wea.from_epw_file`` builds it, from the same values,
        location, one value per hour and the file's leap-year flag; only
        the collections' metadata is shorter (source, country, city), which
        no computation of the engine reads.
        """
        from ladybug.wea import Wea
        return Wea.from_annual_values(
            self._epw.location.duplicate(),
            self._epw.direct_normal_radiation.values,
            self._epw.diffuse_horizontal_radiation.values,
            timestep=1,
            is_leap_year=self._epw.is_leap_year,
        )


@lru_cache(maxsize=CACHED_WEATHER_FILE_COUNT)
def _parse_weather_file(absolute_path: str, modification_time_ns: int, size_bytes: int) -> ParsedWeatherFile:
    """Parse the EPW file at *absolute_path*; the time and size are only part of the cache key.

    Reading the first hourly field makes Ladybug load the whole file now,
    so a file that cannot be read fails here and the cached EPW is never
    loaded lazily later by two threads at once.
    """
    from ladybug.epw import EPW
    try:
        epw = EPW(absolute_path)
        epw.dry_bulb_temperature
    except Exception as error:
        raise IOError(f"Cannot read the EPW weather file '{absolute_path}': {error}") from error
    return ParsedWeatherFile(absolute_path, epw)


def read_weather_file(epw_path) -> ParsedWeatherFile:
    """The parsed EPW file at *epw_path* (a str or a Path), read once while the file stays unchanged.

    Different spellings of one path (relative, forward or back slashes)
    share a cache entry.

    Raises:
      ValueError: If the path is empty or not a str or Path.
      FileNotFoundError: If no file exists at the path.
      IOError: If Ladybug cannot parse the file.
    """
    if not isinstance(epw_path, (str, os.PathLike)) or not str(epw_path):
        raise ValueError(f"read_weather_file: invalid path: {epw_path!r}")
    absolute_path = os.path.normpath(os.path.abspath(epw_path))
    if not os.path.isfile(absolute_path):
        raise FileNotFoundError(f"read_weather_file: file not found: {epw_path}")
    file_status = os.stat(absolute_path)
    return _parse_weather_file(absolute_path, file_status.st_mtime_ns, file_status.st_size)
