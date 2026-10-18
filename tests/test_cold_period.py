"""Cold period from the weather file: the longest run of days colder than a base temperature."""
import numpy as np
import pytest

from urbansolarcarver.cold_period import (
    DAYS_IN_YEAR,
    ColdPeriod,
    cold_day_span,
    cold_period_from_weather_file,
    daily_mean_temperatures,
)
from _epw import resolve_epw


def winter_cold_year(coldest_day_index: int = 15, mean: float = 12.0, amplitude: float = 10.0) -> np.ndarray:
    """Daily means of a year whose coldest day is *coldest_day_index* (0 = 1 January)."""
    days = np.arange(DAYS_IN_YEAR)
    return mean - amplitude * np.cos(2 * np.pi * (days - coldest_day_index) / DAYS_IN_YEAR)


def test_a_winter_cold_season_wraps_across_the_new_year():
    start, end = cold_day_span(winter_cold_year(), base_temperature=12.0)
    assert start > end                      # starts in autumn, ends in spring
    assert 270 <= start <= 310 and 90 <= end <= 125


def test_no_cold_day_gives_no_period():
    assert cold_day_span(np.full(DAYS_IN_YEAR, 25.0), base_temperature=13.0) is None


def test_every_day_cold_gives_the_whole_year():
    assert cold_day_span(np.full(DAYS_IN_YEAR, 2.0), base_temperature=13.0) == (0, DAYS_IN_YEAR - 1)


def test_a_mild_week_inside_the_cold_season_does_not_split_it():
    daily = winter_cold_year()
    daily[20:27] = 20.0                     # a mild week in January
    start, end = cold_day_span(daily, base_temperature=12.0)
    assert start > end and end > 27         # one season across the mild week


def test_a_cold_snap_in_summer_is_not_the_cold_period():
    daily = winter_cold_year()
    daily[190:196] = -5.0                   # six cold days in July
    start, end = cold_day_span(daily, base_temperature=12.0)
    assert start > end                      # still the winter season
    assert not (start <= 190 <= end)


def test_a_cold_season_inside_the_year_does_not_wrap():
    start, end = cold_day_span(winter_cold_year(coldest_day_index=196), base_temperature=12.0)   # southern hemisphere
    assert start < end and start < 196 < end


def test_daily_means_of_a_leap_year_leave_out_29_february():
    hourly = np.concatenate([np.full(59 * 24, 1.0), np.full(24, 100.0), np.full(306 * 24, 3.0)])   # 366 days
    daily = daily_mean_temperatures(hourly)
    assert daily.shape == (DAYS_IN_YEAR,)
    assert 100.0 not in daily and daily[58] == 1.0 and daily[59] == 3.0


def test_hours_marked_missing_are_left_out_and_a_day_without_any_takes_its_neighbours():
    hourly = np.full(8760, 10.0)
    hourly[5] = 99.9                         # one missing hour on 1 January
    hourly[24 * 100:24 * 101] = 99.9         # a whole day missing, between days of 10 and 20 °C
    hourly[24 * 101:] = 20.0
    daily = daily_mean_temperatures(hourly)
    assert daily[0] == 10.0 and daily[100] == pytest.approx(15.0) and daily.max() == 20.0


def test_a_one_day_window_reads_the_daily_means_themselves():
    daily = np.full(DAYS_IN_YEAR, 20.0)
    daily[[10, 11, 12]] = 0.0                # three cold days, with no smoothing
    assert cold_day_span(daily, base_temperature=5.0, smoothing_days=1) == (10, 12)


def test_the_cold_run_needs_one_value_for_each_day_of_a_non_leap_year():
    with pytest.raises(ValueError, match="365"):
        cold_day_span(np.zeros(366), base_temperature=5.0)


def test_daily_means_refuse_a_series_that_is_not_one_year_of_hours():
    with pytest.raises(ValueError, match="8760"):
        daily_mean_temperatures(np.zeros(100))


@pytest.mark.skipif(not resolve_epw(), reason="no EPW available")
def test_the_cold_period_of_golden_colorado_runs_from_autumn_to_spring():
    period = cold_period_from_weather_file(resolve_epw(), base_temperature=13.0)
    assert isinstance(period, ColdPeriod)
    assert period.start_month in (9, 10, 11) and period.end_month in (3, 4, 5)


@pytest.mark.skipif(not resolve_epw(), reason="no EPW available")
def test_a_base_below_every_day_of_the_weather_file_gives_none():
    assert cold_period_from_weather_file(resolve_epw(), base_temperature=-40.0) is None
