"""Inspect's sun tool: the sun path of the year and of a chosen day, and the sun at chosen times, for the project's weather file.

The sun is computed as the engine computes it (sun.get_sun_vectors: Ladybug's sunpath at the weather file's location, the project's
North), from the weather file's local standard time. The vectors point from the model toward the sun, in model coordinates.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import NamedTuple, Optional

from .api_models import SunChart, SunChartDay, SunHourLine, SunPosition, SunPositions
from .project_names import ProjectError

# The days the year's sun path shows: the March equinox (21 September's arc lies within a fraction of a degree of it) and the
# two solstices.
KEY_DATES = ((3, 21), (6, 21), (12, 21))
DAY_PATH_STEP_MINUTES = 5
# The hour lines (analemmas) are sampled every week of the year.
HOUR_LINE_STEP_DAYS = 7
# The most sun positions one request gives: a longer period is sampled on every second, third... day.
MAX_POSITIONS = 240
DAYS_OF_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
MINUTES_PER_DAY = 24 * 60
NO_WEATHER_FILE_MESSAGE = "The project has no weather file: add one in Design (Inputs) to see the sun."


class SunSite(NamedTuple):
    """Where the sun is computed for: the project's weather file (None without one) and its North (north_deg)."""
    epw_path: Optional[str]
    north_deg: float


def days_of_year() -> list[tuple[int, int]]:
    """The 365 (month, day) pairs of a year without 29 February, the year of the weather file."""
    return [(month, day) for month, days in enumerate(DAYS_OF_MONTH, start=1) for day in range(1, days + 1)]


def parse_date(text: str) -> tuple[int, int]:
    """("MM-DD") -> (month, day); ProjectError 422 for anything else, 29 February included."""
    try:
        month_text, day_text = text.split("-")
        month, day = int(month_text), int(day_text)
    except ValueError:
        raise ProjectError(f"'{text}' is not a date as MM-DD.", status_code=422) from None
    if not (1 <= month <= 12 and 1 <= day <= DAYS_OF_MONTH[month - 1]):
        raise ProjectError(f"'{text}' is not a day of the year (MM-DD, without 29 February).", status_code=422)
    return month, day


def _sunpath(site: SunSite):
    """Ladybug's sunpath at the weather file's location with the project's North; ProjectError 404 without a weather file."""
    if site.epw_path is None or not Path(site.epw_path).is_file():
        raise ProjectError(NO_WEATHER_FILE_MESSAGE, status_code=404)
    from ..sun import _initialize_sunpath
    from ..weather_file import read_weather_file
    location = read_weather_file(site.epw_path).location
    return _initialize_sunpath(location.latitude, location.longitude, location.time_zone, north_angle=-float(site.north_deg))


def _sun(sunpath, month: int, day: int, minute: int):
    from ladybug.dt import DateTime
    return sunpath.calculate_sun_from_date_time(DateTime(month, day, minute // 60, minute % 60))


def _vector(sun) -> list[float]:
    reversed_vector = sun.sun_vector_reversed
    return [reversed_vector.x, reversed_vector.y, reversed_vector.z]


def _runs_above_horizon(suns) -> list[list[list[float]]]:
    """The vectors of the suns above the horizon, split where the sun is below it."""
    runs: list[list[list[float]]] = []
    previous_above = False
    for sun in suns:
        above = sun.altitude > 0
        if above:
            if not previous_above:
                runs.append([])
            runs[-1].append(_vector(sun))
        previous_above = above
    return [run for run in runs if len(run) > 1]


def _day(sunpath, month: int, day: int) -> SunChartDay:
    suns = [_sun(sunpath, month, day, minute) for minute in range(0, MINUTES_PER_DAY, DAY_PATH_STEP_MINUTES)]
    return SunChartDay(date=f"{month:02d}-{day:02d}", runs=_runs_above_horizon(suns))


def sun_chart(site: SunSite, month: int, day: int) -> SunChart:
    """The arcs of the key days and of the day *month*/*day*, and for each whole hour the sun's place at that hour through the
    year (its analemma, the year closed back to 1 January)."""
    sunpath = _sunpath(site)
    year = days_of_year()
    sampled_days = year[::HOUR_LINE_STEP_DAYS] + [year[0]]
    hour_lines = []
    for hour in range(24):
        runs = _runs_above_horizon([_sun(sunpath, month_of_year, day_of_month, hour * 60) for month_of_year, day_of_month in sampled_days])
        if runs:
            hour_lines.append(SunHourLine(hour=hour, runs=runs))
    return SunChart(key_days=[_day(sunpath, *date) for date in KEY_DATES], hour_lines=hour_lines, day=_day(sunpath, month, day))


def sun_positions(site: SunSite, first: tuple[int, int], last: tuple[int, int], start_minute: int, end_minute: int,
                  step_minutes: int) -> SunPositions:
    """The sun above the horizon on the days from *first* to *last* (over the new year when *last* comes before *first*), every
    *step_minutes* from *start_minute* to *end_minute* of each day. More than MAX_POSITIONS times are sampled on every n-th day
    (*day_step*); *days_sampled* says on how many days, so that a sum over the positions divided by it is a mean per day."""
    if not (0 <= start_minute <= end_minute <= MINUTES_PER_DAY):
        raise ProjectError("The start of the time range must be at or before its end, within the day.", status_code=422)
    if step_minutes < 1:
        raise ProjectError("The time step must be at least one minute.", status_code=422)
    sunpath = _sunpath(site)
    year = days_of_year()
    first_index, last_index = year.index(first), year.index(last)
    days = year[first_index:last_index + 1] if first_index <= last_index else year[first_index:] + year[:last_index + 1]
    minutes = list(range(start_minute, min(end_minute, MINUTES_PER_DAY - 1) + 1, step_minutes))
    day_step = max(1, math.ceil(len(days) * len(minutes) / MAX_POSITIONS))
    sampled = days[::day_step]
    positions = []
    for month, day in sampled:
        for minute in minutes:
            sun = _sun(sunpath, month, day, minute)
            if sun.altitude > 0:
                positions.append(SunPosition(date=f"{month:02d}-{day:02d}", minute=minute, vector=_vector(sun),
                                             altitude=round(sun.altitude, 2), azimuth=round(sun.azimuth, 2)))
    return SunPositions(positions=positions, days_sampled=len(sampled), day_step=day_step, step_minutes=step_minutes)
