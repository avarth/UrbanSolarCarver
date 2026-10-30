"""Weights per facade direction: the rooms per direction, their series in the artifact, the factors, and how a test point takes one.

Option A of the study: level factors.
"""
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import urbansolarcarver.sky_patches as sky_patches
import urbansolarcarver.simulated_weights as sw
from urbansolarcarver.simulated_weights import (
    DIRECTION_AZIMUTHS, DIRECTION_ROOMS, HOURS, ROOF_ROOM, direction_archetypes, read_direction_weights,
    read_simulated_weights, write_simulated_weights,
)
from urbansolarcarver.sky_patches import point_direction_factors

GOLDEN_EPW = Path(__file__).resolve().parents[1] / "examples" / "weather" / "USA_CO_Golden-NREL.724666_TMY3.epw"

# The app's average room of the KENAK examples: a square of side 4 x 6 m turned 45°, 3 m storey, 40 % glass on each side.
AVERAGE_ROOM = {"width": 24.0, "length": 24.0, "height": 3.0, "orientation": 45.0,
                "wwr": {"north": 0.4, "east": 0.4, "south": 0.4, "west": 0.4}, "g_value": 0.55,
                "u_wall": 0.5, "u_roof": 0.45, "u_floor": 0.45, "roof_exposed": False, "floor_exposed": False,
                "u_window": 3.0, "ach_vent": 0.25, "ach_infiltration": 0.37, "mass_capacity_kj_m2k": 250.0}


# ---- The rooms per direction ----

def test_a_facade_room_has_the_ratios_of_the_room_and_all_its_glass_on_one_facade():
    rooms = direction_archetypes(AVERAGE_ROOM)
    assert tuple(rooms) == DIRECTION_ROOMS
    for name, azimuth in DIRECTION_AZIMUTHS.items():
        room = rooms[name]
        assert room["floor_area"] == pytest.approx(576.0) and room["volume"] == pytest.approx(1728.0)
        assert room["area_window"] == pytest.approx(115.2)                     # 0.2 m² of glass per m² of floor, as a room 6 m deep
        assert room["area_opaque"] == pytest.approx(288.0 - 115.2)            # 0.5 m² of facade per m² of floor
        assert room["u_opaque"] == pytest.approx(0.5)
        assert room["windows"] == [[azimuth, pytest.approx(115.2), 0.55]]
        assert room["ach_infiltration"] == 0.37 and room["mass_capacity_kj_m2k"] == 250.0
        assert not set(room) & {"width", "length", "height", "wwr", "orientation", "u_wall", "u_roof", "roof_exposed"}


def test_the_roof_room_has_a_skylight_of_the_room_s_glass_in_its_roof():
    roof = direction_archetypes(AVERAGE_ROOM)[ROOF_ROOM]
    assert roof["area_opaque"] == pytest.approx(576.0 - 115.2)
    assert roof["u_opaque"] == pytest.approx(0.45)
    assert roof["windows"] == [[180.0, pytest.approx(115.2), 0.55, 90.0]]


def test_an_exposed_roof_and_floor_lose_heat_in_the_rooms_as_in_the_room():
    rooms = direction_archetypes({**AVERAGE_ROOM, "roof_exposed": True, "floor_exposed": True})
    walls = 288.0 - 115.2
    assert rooms["S"]["area_opaque"] == pytest.approx(walls + 2 * 576.0)
    assert rooms["S"]["u_opaque"] * rooms["S"]["area_opaque"] == pytest.approx(0.5 * walls + 0.45 * 576.0 * 2)
    assert rooms[ROOF_ROOM]["u_opaque"] * rooms[ROOF_ROOM]["area_opaque"] == pytest.approx(0.45 * (576.0 - 115.2) + 0.45 * 576.0)


def test_one_u_for_the_opaque_envelope_serves_the_roof_room():
    one_u = {key: value for key, value in AVERAGE_ROOM.items() if key not in ("u_wall", "u_roof", "u_floor")} | {"u_opaque": 0.6}
    rooms = direction_archetypes(one_u)
    assert rooms["N"]["u_opaque"] == pytest.approx(0.6) and rooms[ROOF_ROOM]["u_opaque"] == pytest.approx(0.6)


@pytest.mark.parametrize("archetype, message", [
    ({"floor_area": 10.0, "volume": 30.0, "area_opaque": 10.0, "area_window": 2.0, "windows": [[180, 2, 0.6]]}, "shoebox"),
    ({**AVERAGE_ROOM, "u_roof": None}, "u_roof"),
    ({**AVERAGE_ROOM, "width": 2.0, "length": 2.0, "height": 4.0, "wwr": {"north": 0.9, "south": 0.9}}, "skylight"),
])
def test_rooms_per_direction_are_refused_for_what_they_cannot_be_built_from(archetype, message):
    with pytest.raises(ValueError, match=message):
        direction_archetypes({key: value for key, value in archetype.items() if value is not None})


# ---- The artifact ----

def _series(level: float) -> tuple[np.ndarray, np.ndarray]:
    return np.full(HOURS, level), np.full(HOURS, level / 2)


def test_the_artifact_keeps_the_series_of_the_rooms_per_direction(tmp_path):
    directions = {name: _series(0.1 * (index + 1)) for index, name in enumerate(DIRECTION_ROOMS)}
    path = write_simulated_weights(tmp_path / "w.json", *_series(0.5), {"x": 1}, directions)
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2
    benefit, harm, meta = read_simulated_weights(path)
    assert benefit[0] == 0.5 and harm[0] == 0.25 and meta == {"x": 1}
    read = read_direction_weights(path)
    assert tuple(read) == DIRECTION_ROOMS
    assert read[ROOF_ROOM][0][0] == pytest.approx(0.9) and read[ROOF_ROOM][1][0] == pytest.approx(0.45)


def test_an_artifact_without_rooms_per_direction_and_one_of_version_1_have_none(tmp_path):
    path = write_simulated_weights(tmp_path / "w.json", *_series(0.5), {})
    assert read_direction_weights(path) is None
    payload = json.loads(path.read_text(encoding="utf-8")) | {"schema_version": 1}
    (tmp_path / "v1.json").write_text(json.dumps(payload), encoding="utf-8")
    assert read_simulated_weights(tmp_path / "v1.json")[0][0] == 0.5
    assert read_direction_weights(tmp_path / "v1.json") is None


def test_rooms_per_direction_must_be_all_of_them(tmp_path):
    with pytest.raises(ValueError, match="directions must name"):
        write_simulated_weights(tmp_path / "w.json", *_series(0.5), {}, {"N": _series(0.1)})


# ---- The generator ----

def test_the_generator_calculates_the_rooms_per_direction_and_records_them(tmp_path, monkeypatch):
    """The generator's plumbing, with the room simulation, the sun and the factors stood in for (the real thing is the slow test
    below)."""
    rooms = []

    def room_weights(epw_path, arch, gains, eps, outdoor_temperature):
        rooms.append(arch)
        level = 0.5 if len(arch["windows"]) > 1 else 0.1 + 0.01 * len(rooms)
        return {"benefit": np.full(HOURS, level), "harm": np.zeros(HOURS), "archetype": dict(arch),
                "heating_kwh_m2": 10.0 * level, "cooling_kwh_m2": 1.0}

    monkeypatch.setattr(sw, "_room_weights", room_weights)
    monkeypatch.setattr(sw, "sun_up_hours", lambda epw: np.zeros(HOURS, dtype=np.int8))
    calls = []
    monkeypatch.setattr(sky_patches, "direction_factors",
                        lambda epw, averaged, directions, hoys, include_harm=False: calls.append(include_harm) or np.arange(9.0))
    path = sw.generate_simulated_weights("weather.epw", {**AVERAGE_ROOM, "direction_rooms": True}, tmp_path / "w.json")
    assert len(rooms) == 10 and len(rooms[0]["windows"]) == 4             # the room itself first, then the 9 rooms
    benefit, _harm, meta = read_simulated_weights(path)
    assert benefit[0] == 0.5
    assert [series[0][0] for series in read_direction_weights(path).values()] == pytest.approx([0.12 + 0.01 * i for i in range(9)])
    assert set(meta["direction_rooms"]) == set(DIRECTION_ROOMS)
    assert meta["direction_rooms"]["S"]["windows"] == [[180.0, pytest.approx(115.2), 0.55]]
    assert meta["direction_factors"]["benefit"] == dict(zip(DIRECTION_ROOMS, np.arange(9.0)))
    assert set(meta["direction_factors"]) == {"benefit", "benefit_minus_harm"} and calls == [False, True]
    assert "direction_rooms" not in meta["archetype"]


def test_the_generator_without_rooms_per_direction_writes_none(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "_room_weights", lambda epw, arch, gains, eps, outdoor: {
        "benefit": np.full(HOURS, 0.5), "harm": np.zeros(HOURS), "archetype": dict(arch), "heating_kwh_m2": 1.0, "cooling_kwh_m2": 1.0})
    monkeypatch.setattr(sw, "sun_up_hours", lambda epw: np.zeros(HOURS, dtype=np.int8))
    path = sw.generate_simulated_weights("weather.epw", AVERAGE_ROOM, tmp_path / "w.json")
    assert read_direction_weights(path) is None and "direction_factors" not in read_simulated_weights(path)[2]


@pytest.mark.parametrize("value", ["yes", 1])
def test_direction_rooms_must_be_true_or_false(tmp_path, value):
    with pytest.raises(ValueError, match="direction_rooms must be true or false"):
        sw.generate_simulated_weights("weather.epw", {**AVERAGE_ROOM, "direction_rooms": value}, tmp_path / "w.json")


# ---- The factors ----

def test_a_factor_is_the_ratio_of_the_patch_sums_the_direction_faces(monkeypatch):
    """Stand-in patch weights: the averaged room 1 on every patch, room k (counted from 0) k + 1 on the patches north of the zenith
    and 0 on the others. A room's factor is then k + 1 times the share of the patches it faces that lie north of the zenith."""
    patch_dirs = sky_patches.fetch_tregenza_patch_directions(sky_patches.torch.device("cpu")).numpy().astype(np.float64)
    north_half = patch_dirs[:, 1] > 0.0
    weights = {"averaged": np.ones(len(patch_dirs))}
    for index, name in enumerate(DIRECTION_ROOMS):
        weights[name] = np.where(north_half, index + 1.0, 0.0)
    series = {name: (np.full(HOURS, float(index)), np.zeros(HOURS)) for index, name in enumerate(DIRECTION_ROOMS)}
    lookup = {float(index): name for index, name in enumerate(DIRECTION_ROOMS)}
    monkeypatch.setattr(sky_patches, "_simulated_patch_weights",
                        lambda epw, benefit, harm, hoys, north, patches, include_harm:
                        weights["averaged"] if benefit[0] < 0 else weights[lookup[float(benefit[0])]])
    factors = sky_patches.direction_factors("weather.epw", (np.full(HOURS, -1.0), np.zeros(HOURS)), series, range(HOURS))
    for index, name in enumerate(DIRECTION_ROOMS):
        if name == ROOF_ROOM:
            facing = patch_dirs[:, 2] > 0.0
        else:
            azimuth = math.radians(DIRECTION_AZIMUTHS[name])
            facing = patch_dirs @ np.array([math.sin(azimuth), math.cos(azimuth), 0.0]) > 0.0
        assert factors[index] == pytest.approx((index + 1.0) * (north_half & facing).sum() / facing.sum())
    assert factors[0] == pytest.approx(1.0)                                 # every patch the north room faces is north of the zenith


def test_a_direction_whose_averaged_weights_are_zero_takes_1(monkeypatch):
    monkeypatch.setattr(sky_patches, "_simulated_patch_weights", lambda *args: np.zeros(145) if args[1][0] < 0 else np.ones(145))
    series = {name: (np.full(HOURS, 0.5), np.zeros(HOURS)) for name in DIRECTION_ROOMS}
    assert sky_patches.direction_factors("weather.epw", (np.full(HOURS, -1.0), np.zeros(HOURS)), series, range(HOURS)).tolist() == [1.0] * 9


# ---- A test point's factor ----

FACTORS = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]       # N, NE, E, SE, S, SW, W, NW, roof


def _unit(azimuth_deg: float, tilt_from_up_deg: float) -> list[float]:
    azimuth, tilt = math.radians(azimuth_deg), math.radians(tilt_from_up_deg)
    return [math.sin(tilt) * math.sin(azimuth), math.sin(tilt) * math.cos(azimuth), math.cos(tilt)]


@pytest.mark.parametrize("normal, expected", [
    ([0.0, 1.0, 0.0], 1.0),                 # a north facade
    ([1.0, 0.0, 0.0], 3.0),                 # east
    ([0.0, -2.0, 0.0], 5.0),                # south, not of unit length
    (_unit(22.5, 90.0), 1.5),               # NNE: half way between N and NE
    (_unit(337.5, 90.0), 4.5),              # NNW: half way between NW and N
    (_unit(100.0, 90.0), 3.0 + 10.0 / 45.0),
    ([0.0, 0.0, 1.0], 9.0),                 # a flat roof
    (_unit(180.0, 44.0), 9.0),              # within 45° of up: the roof
    (_unit(180.0, 46.0), 5.0),              # steeper: its planimetric direction
    (_unit(90.0, 150.0), 3.0),              # facing down, to the east
    ([0.0, 0.0, -1.0], 1.0),                # straight down: no planimetric direction
    ([0.0, 0.0, 0.0], 1.0),
])
def test_a_point_takes_the_factor_of_its_planimetric_direction_or_the_roof(normal, expected):
    assert point_direction_factors([normal], FACTORS)[0] == pytest.approx(expected, rel=1e-6)


def test_the_model_north_turns_the_directions():
    # model north 90° clockwise from +Y: +X is north, -Y is east
    assert point_direction_factors([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0]], FACTORS, north_deg=90.0).tolist() == [1.0, 3.0]


# ---- Where the factors apply ----

def test_get_direction_factors_is_none_for_weights_without_rooms_per_direction(tmp_path):
    from urbansolarcarver.scoring import get_direction_factors
    path = write_simulated_weights(tmp_path / "w.json", *_series(0.5), {})
    assert get_direction_factors("no weather needed", [0, 1], False, str(path)) is None


def test_the_carving_scales_each_point_by_its_direction(monkeypatch):
    import urbansolarcarver.carving as carving
    asked = []
    monkeypatch.setattr(carving, "get_direction_factors", lambda epw, hoys, harm, path: asked.append((hoys, harm)) or np.array(FACTORS))
    settings = SimpleNamespace(mode="benefit", simulated_weights_path="w.json", epw_path="weather.epw", include_harm=True, north_deg=0.0)
    weights = carving.direction_point_weights(settings, range(3), np.array([[0.0, -1.0, 0.0], [0.0, 0.0, 1.0]]))
    assert weights.tolist() == [5.0, 9.0] and asked == [([0, 1, 2], True)]
    assert carving.direction_point_weights(SimpleNamespace(**{**vars(settings), "mode": "irradiance"}), range(3), np.zeros((2, 3))) is None
    assert carving.direction_point_weights(SimpleNamespace(**{**vars(settings), "simulated_weights_path": None}), range(3),
                                           np.zeros((2, 3))) is None


def test_simulate_scales_useful_solar_energy_by_each_point_s_direction(monkeypatch):
    import urbansolarcarver.scoring as scoring
    import urbansolarcarver.solar_check as solar_check
    import urbansolarcarver.sun as sun
    monkeypatch.setattr(scoring, "get_direction_factors", lambda epw, hoys, harm, path: np.array(FACTORS))
    monkeypatch.setattr(sun, "sample_period", lambda settings, steps_per_hour=1: ([], range(HOURS)))
    settings = SimpleNamespace(metric="useful_solar_energy", simulated_weights_path="w.json", epw_path="weather.epw",
                               include_harm=False, north_deg=0.0)
    assert solar_check._direction_point_factors(settings, np.array([[0.0, 1.0, 0.0]])).tolist() == [1.0]
    assert solar_check._direction_point_factors(SimpleNamespace(**{**vars(settings), "metric": "solar_energy"}), np.zeros((1, 3))) is None


# ---- With the engine ----

@pytest.mark.slow
@pytest.mark.sweep
@pytest.mark.skipif(not GOLDEN_EPW.is_file(), reason="the bundled weather file is missing")
def test_rooms_per_direction_on_the_bundled_weather_file(tmp_path):
    """The KENAK apartment of zone B with rooms per direction on the Golden weather file (about 70 s): south counts less than the
    averaged room, north more."""
    from urbansolarcarver.local_web_service.typical_building import EXAMPLES, archetype_of
    archetype = archetype_of(EXAMPLES["kenak-apartment-b"].values, GOLDEN_EPW)
    assert archetype["direction_rooms"] is True
    path = sw.generate_simulated_weights(str(GOLDEN_EPW), archetype, tmp_path / "w.json")
    _benefit, _harm, meta = read_simulated_weights(path)
    factors = meta["direction_factors"]["benefit"]
    print(meta["direction_factors"])
    assert factors["S"] < 1.0 < factors["N"] and factors["SE"] < factors["E"] and factors[ROOF_ROOM] < 1.0
    rooms = meta["direction_rooms"]
    assert rooms["S"]["heating_kwh_m2"] < meta["heating_kwh_m2"] < rooms["N"]["heating_kwh_m2"]
