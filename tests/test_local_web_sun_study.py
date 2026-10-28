"""Inspect's sun tool (local_web_service.sun_study): the year's sun path, the sun at chosen times, and their routes."""
import numpy as np
import pytest

from _epw import resolve_epw
from test_local_web_server import GOLDEN_EPW, client, create_project, projects_folder, upload  # noqa: F401 (fixtures)
from urbansolarcarver.local_web_service import sun_study
from urbansolarcarver.local_web_service.project_names import ProjectError

EPW = resolve_epw()
REQUIRES_EPW = pytest.mark.skipif(not EPW, reason="no EPW file")


def config(north_deg=0.0):
    return sun_study.SunSite(EPW, north_deg)


def test_dates_are_month_and_day_of_a_year_without_29_february():
    assert sun_study.parse_date("06-21") == (6, 21)
    assert len(sun_study.days_of_year()) == 365
    for text in ("02-29", "13-01", "6/21", "06-31"):
        with pytest.raises(ProjectError):
            sun_study.parse_date(text)


@REQUIRES_EPW
def test_the_chart_has_the_key_days_the_hour_lines_and_the_chosen_day_above_the_horizon():
    chart = sun_study.sun_chart(config(), 2, 1)
    assert [day.date for day in chart.key_days] == ["03-21", "06-21", "12-21"] and chart.day.date == "02-01"
    vectors = np.array([point for day in [*chart.key_days, chart.day] for run in day.runs for point in run])
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-6) and (vectors[:, 2] > 0).all()
    highest = {day.date: max(point[2] for run in day.runs for point in run) for day in chart.key_days}
    assert highest["06-21"] > highest["03-21"] > highest["12-21"]          # the bundled weather file is in the north
    hours = [line.hour for line in chart.hour_lines]
    assert 12 in hours and 0 not in hours                                  # no sun at midnight


@REQUIRES_EPW
def test_positions_are_the_sun_above_the_horizon_and_a_long_range_is_sampled_on_fewer_days():
    noon = sun_study.sun_positions(config(), (6, 21), (6, 21), 720, 720, 15)
    assert len(noon.positions) == 1 and noon.days_sampled == 1 and noon.positions[0].altitude > 60
    assert sun_study.sun_positions(config(), (6, 21), (6, 21), 0, 0, 15).positions == []          # midnight
    year = sun_study.sun_positions(config(), (1, 1), (12, 31), 0, 1440, 60)
    assert year.day_step > 1 and len(year.positions) <= sun_study.MAX_POSITIONS and year.days_sampled == len(range(0, 365, year.day_step))
    winter = sun_study.sun_positions(config(), (12, 1), (1, 31), 720, 720, 15)                    # over the new year
    assert winter.days_sampled == 62 and {position.date for position in winter.positions} >= {"12-01", "01-31"}
    with pytest.raises(ProjectError):
        sun_study.sun_positions(config(), (6, 21), (6, 21), 900, 600, 15)


@REQUIRES_EPW
def test_north_turns_the_sun_as_the_engine_does():
    straight = sun_study.sun_positions(config(), (6, 21), (6, 21), 720, 720, 15).positions[0].vector
    turned = sun_study.sun_positions(config(north_deg=90.0), (6, 21), (6, 21), 720, 720, 15).positions[0].vector
    angle = np.radians(90.0)        # north_deg turns the sun clockwise in plan
    expected = [straight[0] * np.cos(angle) + straight[1] * np.sin(angle), -straight[0] * np.sin(angle) + straight[1] * np.cos(angle), straight[2]]
    assert np.allclose(turned, expected, atol=1e-6)


def test_the_routes_need_the_weather_file_and_a_date(client):
    create_project(client, "p", "daylight")
    assert client.get("/api/projects/p/sun-chart").status_code == 404
    assert client.get("/api/projects/p/sun-positions", params={"from": "06-21", "to": "06-21", "start": 720, "end": 720}).status_code == 404
    assert client.get("/api/projects/p/sun-chart", params={"date": "02-30"}).status_code == 422


@pytest.mark.skipif(not GOLDEN_EPW.is_file(), reason="the bundled weather file is missing")
def test_the_routes_follow_the_uploaded_weather_file(client):
    create_project(client, "p", "daylight")
    upload(client, "p", "weather", ("golden.epw", GOLDEN_EPW.read_bytes()))
    chart = client.get("/api/projects/p/sun-chart", params={"date": "02-01"}).json()
    assert chart["day"]["date"] == "02-01" and len(chart["key_days"]) == 3
    positions = client.get("/api/projects/p/sun-positions", params={"from": "12-21", "to": "12-21", "start": 480, "end": 960, "step": 60}).json()
    assert positions["days_sampled"] == 1 and [position["minute"] for position in positions["positions"]] == list(range(480, 961, 60))
