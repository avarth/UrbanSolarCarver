"""Tests for the free-running zone of the simulated weights: no heating or cooling, windows opened for natural ventilation, the sun
valued by the degree-hours below and above the comfort band it removes or adds (simulated_weights.simulate_free_running,
attribute_free_running, generate_simulated_weights with operation free_running)."""
import json
from pathlib import Path

import numpy as np
import pytest

from _epw import BUNDLED_EPW
from urbansolarcarver import simulated_weights as sw
from urbansolarcarver.simulated_weights import HOURS, ZoneParams

_REF = json.loads((Path(__file__).parent / "data" / "oracle_5r1c_reference.json").read_text(encoding="utf-8"))
VOLUME = 300.0


def _zone(**changes) -> ZoneParams:
    """A 100 m² room, 3 m high, 20 m² of glass; the comfort band 20 to 26 °C."""
    values = dict(floor_area=100.0, volume=VOLUME, u_opaque=0.5, area_opaque=150.0, u_window=2.0, area_window=20.0,
                  ach_vent=0.5, ach_infiltration=0.2, mass_class="medium", t_set_heating=20.0, t_set_cooling=26.0)
    return ZoneParams.from_archetype(**{**values, **changes})


def _constant(value: float) -> np.ndarray:
    return np.full(HOURS, float(value))


def test_the_loss_coefficient_is_the_windows_the_fabric_and_the_air():
    p = _zone()
    fabric = 1.0 / (1.0 / p.h_tr_em + 1.0 / p.h_tr_ms)
    assert fabric == pytest.approx(0.5 * 150.0)                       # H_tr,em and H_tr,ms in series give U x A back
    assert sw.loss_coefficient(p) == pytest.approx(2.0 * 20.0 + 0.5 * 150.0 + 1200.0 * VOLUME * 0.7 / 3600.0)
    assert sw.window_conductance(VOLUME, 4.0) == pytest.approx(1200.0 * VOLUME * 4.0 / 3600.0)


def test_a_zone_without_gains_floats_at_the_outdoor_temperature():
    result = sw.simulate_free_running(_zone(), _constant(10.0), _constant(0.0), _constant(0.0), t_m_init=10.0)
    assert result.t_air == pytest.approx(np.full(HOURS, 10.0))
    assert result.underheating_kh == pytest.approx(10.0 * HOURS)
    assert (result.hours_below, result.hours_above, result.overheating_kh) == (HOURS, 0, 0.0)
    assert not result.window_share.any()


def test_opened_windows_hold_the_air_at_their_opening_temperature():
    """Gains that would bring the closed room far above the band, outdoors 15 °C: opening the windows holds the air at 25 °C, so
    nothing lies above the band; with the windows closed it overheats."""
    p, gains = _zone(), _constant(5000.0)
    opened = sw.simulate_free_running(p, _constant(15.0), gains, _constant(0.0), sw.window_conductance(VOLUME, 10.0), 25.0,
                                      t_m_init=20.0)
    assert opened.t_air[24:] == pytest.approx(np.full(HOURS - 24, 25.0))     # after the first hours of warming from 20 °C
    assert opened.overheating_kh == 0.0 and 0.0 < opened.window_share[24:].min() < 1.0
    closed = sw.simulate_free_running(p, _constant(15.0), gains, _constant(0.0), 0.0, 25.0, t_m_init=20.0)
    assert closed.hours_above >= HOURS - 24 and closed.overheating_kh > 0.0


def test_windows_stay_closed_when_outdoors_is_warmer():
    """Above the opening temperature but hotter outside: opening would warm the room, so the windows stay shut."""
    result = sw.simulate_free_running(_zone(), _constant(35.0), _constant(0.0), _constant(0.0), sw.window_conductance(VOLUME, 4.0),
                                      t_m_init=35.0)
    assert not result.window_share.any() and result.t_air == pytest.approx(np.full(HOURS, 35.0))


def test_an_unknown_operation_is_refused(tmp_path):
    with pytest.raises(ValueError, match="operation"):
        sw.generate_simulated_weights("weather.epw", {"width": 10, "length": 10, "height": 3, "wwr": {"south": 0.3},
                                                      "operation": "heated"}, tmp_path / "w.json")


def test_the_window_opening_belongs_to_a_free_running_zone(tmp_path):
    with pytest.raises(ValueError, match="free-running"):
        sw.generate_simulated_weights("weather.epw", {"width": 10, "length": 10, "height": 3, "wwr": {"south": 0.3},
                                                      "vent_above": 25.0}, tmp_path / "w.json")


@pytest.mark.slow
def test_the_attribution_is_one_more_watt_hour_in_one_hour():
    """Each hour's benefit and harm are the degree-hours the year loses and gains with eps more watts of sun in that hour alone,
    times the loss coefficient: the vectorized perturbation gives what single runs give."""
    p = _zone()
    t_out = np.asarray(_REF["driving"]["t_out"], dtype=np.float64)
    phi_int = np.asarray(_REF["driving"]["internal_gains"], dtype=np.float64)
    phi_sol = np.asarray(_REF["driving"]["solar_medium_office"], dtype=np.float64)
    h_open, eps = sw.window_conductance(VOLUME, 4.0), 10.0
    benefit, harm = sw.attribute_free_running(p, t_out, phi_int, phi_sol, h_open, 25.0, eps=eps, t_m_init=20.0)
    scale = sw.loss_coefficient(p) / (2.0 * eps)
    for hour in (300, 2900, 4500, 6000, 8000):
        runs = []
        for sign in (1.0, -1.0):
            sun = phi_sol.copy()
            sun[hour] += sign * eps
            runs.append(sw.simulate_free_running(p, t_out, phi_int, sun, h_open, 25.0, t_m_init=20.0))
        assert benefit[hour] == pytest.approx(np.clip((runs[1].underheating_kh - runs[0].underheating_kh) * scale, 0, 1), abs=1e-9)
        assert harm[hour] == pytest.approx(np.clip((runs[0].overheating_kh - runs[1].overheating_kh) * scale, 0, 1), abs=1e-9)
    assert benefit.max() <= 1.0 and harm.max() <= 1.0
    january, july = slice(0, 31 * 24), slice(181 * 24, 212 * 24)
    assert benefit[january].mean() > benefit[july].mean() and harm[july].mean() > harm[january].mean()


@pytest.mark.slow
def test_a_zone_always_below_the_band_counts_most_of_its_sun():
    """A room that never reaches 20 °C: every watt-hour of sun warms it while it is too cold, so it counts close to 1 (the 5R1C
    splits it among air, surfaces and mass, so not exactly 1) and never harms."""
    sun = np.where(np.arange(HOURS) % 24 == 12, 500.0, 0.0)
    benefit, harm = sw.attribute_free_running(_zone(), _constant(0.0), _constant(0.0), sun)
    assert not harm.any()
    middle = benefit[24 * 30:24 * 330]
    assert middle.min() > 0.8 and middle.max() <= 1.0


@pytest.mark.slow
def test_the_generator_writes_a_free_running_zone(tmp_path):
    archetype = {"width": 10.0, "length": 10.0, "height": 3.0, "wwr": {"south": 0.4, "north": 0.2}, "u_opaque": 0.5, "u_window": 2.0,
                 "ach_vent": 0.5, "ach_infiltration": 0.2, "operation": "free_running", "vent_above": 24.0, "vent_ach": 3.0}
    path = sw.generate_simulated_weights(str(BUNDLED_EPW), archetype, tmp_path / "w.json")
    benefit, harm, meta = sw.read_simulated_weights(path)
    assert (meta["method"], meta["operation"]) == ("iso13790-5r1c-free-running-perturbation", "free_running")
    assert "heating_kwh_m2" not in meta and meta["comfort_band_c"] == [20.0, 26.0]
    assert (meta["archetype"]["vent_above"], meta["archetype"]["vent_ach"]) == (24.0, 3.0)
    assert 0 < meta["hours_below"] < HOURS and meta["underheating_kh"] > 0 and meta["overheating_kh"] >= 0
    # The degree-hours are those of simulate_free_running on the same zone (the generator takes them from its attribution's base
    # row), exactly.
    from urbansolarcarver.archetype_defaults import ARCHETYPE_DEFAULTS
    from urbansolarcarver.weather_file import read_weather_file
    zone = sw.expand_shoebox({key: value for key, value in archetype.items() if key not in ("operation", "vent_above", "vent_ach")})
    windows = zone.pop("windows")
    p = ZoneParams.from_archetype(**zone)
    free = sw.simulate_free_running(p, read_weather_file(str(BUNDLED_EPW)).dry_bulb_temperature(),
                                    _constant(ARCHETYPE_DEFAULTS["internal_gains_w_m2"] * p.floor_area),
                                    sw.transmitted_solar_from_epw(str(BUNDLED_EPW), windows),
                                    sw.window_conductance(zone["volume"], 3.0), 24.0)
    assert ((meta["underheating_kh"], meta["overheating_kh"], meta["hours_below"], meta["hours_above"])
            == (free.underheating_kh, free.overheating_kh, free.hours_below, free.hours_above))
    assert meta["loss_coefficient_w_k"] > 0 and benefit.max() > 0.5 and benefit.max() <= 1.0
