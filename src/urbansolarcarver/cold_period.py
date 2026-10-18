"""
The cold period of a site, from its EnergyPlus weather (EPW) file.

A day is cold when the mean dry-bulb temperature of the month around it
(a running mean of SMOOTHING_WINDOW_DAYS days, centred on the day and
wrapping across the new year) is below a base temperature. The cold period
is the longest unbroken run of cold days, which may wrap across the new
year (start after end, as Ladybug's analysis period reads it). The running
mean keeps a mild week inside winter from splitting the season and a cold
snap in summer from being taken for one.

For benefit mode the base temperature is balance_temperature -
balance_offset, the same threshold its heating-benefit filter applies to
each hour. This is a degree-day reading of the weather file: a cold day is
one with heating degree days at that base after smoothing. A later source of
the daily heating need (the 5R1C simulation of simulated_weights.py) can
feed cold_day_span in place of the daily temperatures.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from ladybug.epw import EPW

DAYS_IN_YEAR = 365
HOURS_IN_DAY = 24
SMOOTHING_WINDOW_DAYS = 31              # a month, centred on the day
LEAP_DAY_INDEX = 59                     # 29 February, counted from 1 January = 0
DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


@dataclass(frozen=True)
class ColdPeriod:
    """Start and end dates of the cold period (inclusive, non-leap calendar); start after end wraps across the new year."""
    start_month: int
    start_day: int
    end_month: int
    end_day: int


def daily_mean_temperatures(hourly_dry_bulb: Sequence[float]) -> np.ndarray:
    """The 365 daily means of one year of hourly temperatures (8760 values, or 8784 with 29 February left out)."""
    hourly = np.asarray(hourly_dry_bulb, dtype=float)
    if hourly.shape not in ((DAYS_IN_YEAR * HOURS_IN_DAY,), ((DAYS_IN_YEAR + 1) * HOURS_IN_DAY,)):
        raise ValueError(f"Expected one year of hourly values (8760, or 8784 in a leap year), got {hourly.size}.")
    daily = hourly.reshape(-1, HOURS_IN_DAY).mean(axis=1)
    if daily.size == DAYS_IN_YEAR + 1:
        daily = np.delete(daily, LEAP_DAY_INDEX)
    return daily


def _running_mean_around_the_year(daily: np.ndarray, window_days: int) -> np.ndarray:
    half = window_days // 2
    wrapped = np.concatenate([daily[-half:], daily, daily[:half]])
    return np.convolve(wrapped, np.full(2 * half + 1, 1.0 / (2 * half + 1)), mode="valid")


def cold_day_span(daily_mean: Sequence[float], base_temperature: float,
                  smoothing_days: int = SMOOTHING_WINDOW_DAYS) -> tuple[int, int] | None:
    """First and last day (0 = 1 January) of the longest run of cold days; None when no day is cold.

    The run may wrap across the new year, in which case start > end. Every day
    cold gives (0, 364). Of two runs of equal length, the one with more degree
    days below the base is taken.
    """
    smoothed = _running_mean_around_the_year(np.asarray(daily_mean, dtype=float), smoothing_days)
    cold = smoothed < base_temperature
    if not cold.any():
        return None
    if cold.all():
        return 0, DAYS_IN_YEAR - 1
    first_warm_day = int(np.argmin(cold))           # runs are counted from a warm day, so none is cut by the new year
    order = np.roll(np.arange(DAYS_IN_YEAR), -first_warm_day)
    best: tuple[int, float, int, int] | None = None  # (length, degree days, start, end)
    run_start = None
    for position, day in enumerate(order):
        if cold[day] and run_start is None:
            run_start = position
        ends_here = run_start is not None and (position == DAYS_IN_YEAR - 1 or not cold[order[position + 1]])
        if ends_here:
            run_days = order[run_start:position + 1]
            candidate = (len(run_days), float(np.sum(base_temperature - smoothed[run_days])), int(run_days[0]), int(run_days[-1]))
            if best is None or candidate[:2] > best[:2]:
                best = candidate
            run_start = None
    return best[2], best[3]


def month_and_day(day_index: int) -> tuple[int, int]:
    """(month, day) of a day of a non-leap year, 0 = 1 January."""
    for month_index, days in enumerate(DAYS_IN_MONTH):
        if day_index < days:
            return month_index + 1, day_index + 1
        day_index -= days
    raise ValueError("day_index must be between 0 and 364.")


def cold_period_from_weather_file(epw_path: str, base_temperature: float) -> ColdPeriod | None:
    """The cold period of the site of *epw_path* for *base_temperature* (°C); None when no day is cold enough."""
    span = cold_day_span(daily_mean_temperatures(EPW(epw_path).dry_bulb_temperature.values), base_temperature)
    if span is None:
        return None
    (start_month, start_day), (end_month, end_day) = month_and_day(span[0]), month_and_day(span[1])
    return ColdPeriod(start_month, start_day, end_month, end_day)
