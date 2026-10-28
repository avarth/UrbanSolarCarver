"""The typical building of an energy-weighted Solar usefulness criterion (local_web_service.typical_building): its values, presets,
routes, the generated config.yaml, stage status and the run that calculates its weights first.

The engine is the fake of local_web_test_support.py. The fast tests replace the weights generator (about 9 s on the bundled
weather file) by a fake that writes a valid weights file at once; the tests marked slow run the real one.
"""
import copy

import numpy as np
import pytest
import yaml

from local_web_test_support import GOLDEN_EPW, FakeEngine, box_bytes, make_worker, run_and_wait, wait_until_finished
from test_local_web_server import build_client, client, client_with_blocking_run, create_project, projects_folder, upload  # noqa: F401 (fixtures)
from urbansolarcarver import simulated_weights
from urbansolarcarver.errors import ConfigError
from urbansolarcarver.local_web_service import sun_study, typical_building
from urbansolarcarver.local_web_service.projects import ProjectStore
from urbansolarcarver.local_web_service.stage_records import criterion_status

pytestmark = pytest.mark.skipif(not GOLDEN_EPW.is_file(), reason="the bundled weather file is missing")

OFFICE = typical_building.PRESETS["office"].values


class FakeGenerator:
    """Stands in for simulated_weights.generate_simulated_weights: writes a valid weights file (with the heatmap file beside it) and
    keeps the archetypes it was given. ``error`` makes it raise instead."""

    def __init__(self, error: Exception | None = None):
        self.archetypes = []
        self.error = error

    def __call__(self, epw_path, archetype, out_path, internal_gains_w_m2=None, eps=1.0):
        if self.error is not None:
            raise self.error
        self.archetypes.append(archetype)
        hours = np.arange(simulated_weights.HOURS)
        benefit = np.where(hours < 1000, 0.5, 0.0)          # 1,000 hours above 0.01
        harm = np.where(hours > 8000, 0.2345, 0.0)
        path = simulated_weights.write_simulated_weights(out_path, benefit, harm, {"heating_kwh_m2": 41.5, "cooling_kwh_m2": 12.25})
        path.with_suffix(".png").write_bytes(b"png")
        return path


@pytest.fixture
def fake_generator(monkeypatch):
    generator = FakeGenerator()
    monkeypatch.setattr(simulated_weights, "generate_simulated_weights", generator)
    return generator


def benefit_project(tmp_path, criteria=("benefit",)) -> tuple[ProjectStore, str]:
    """A project with a max volume, the bundled weather file and one criterion per mode in *criteria*, each with a test surface."""
    store = ProjectStore(tmp_path / "projects")
    store.create("p", criteria[0])
    store.add_input("p", "max_volume", "volume.ply", box_bytes([0, 0, 5]))
    store.add_input("p", "weather", "golden.epw", GOLDEN_EPW.read_bytes())
    for mode in criteria[1:]:
        store.add_criterion("p", mode)
    for criterion in store.criteria("p"):
        store.add_criterion_test_surface("p", criterion.id, f"surface_{criterion.id}.ply", box_bytes([0, 0, 0], extents=(6, 6, 0.1)))
    return store, "p"


def config_criteria(store, name) -> list[dict]:
    return yaml.safe_load((store.open(name) / "config.yaml").read_text(encoding="utf-8"))["criteria"]


def changed(values: dict, **changes) -> dict:
    """A copy of *values* with *changes*; a key "wwr_<side>" changes one window share."""
    copied = copy.deepcopy(values)
    for key, value in changes.items():
        if key.startswith("wwr_"):
            copied["wwr"][key.removeprefix("wwr_")] = value
        else:
            copied[key] = value
    return copied


# ---- Values and presets ----

def test_the_presets_are_valid_and_stored_as_given():
    assert list(typical_building.PRESETS) == ["office", "heavy_home", "light_home"]
    assert [preset.label for preset in typical_building.PRESETS.values()] == [
        "Office, medium mass", "Older home, heavy masonry", "Light, well-insulated home"]
    for preset in typical_building.PRESETS.values():
        assert set(preset.values) == set(typical_building.VALUE_KEYS)
        assert typical_building.validate(preset.values) == preset.values


def test_the_archetype_has_the_gains_by_day_and_night_and_leaves_out_what_is_not_set():
    archetype = typical_building.archetype_of(OFFICE)
    assert archetype["wwr"] == {"east": 0.10, "south": 0.27, "west": 0.10}         # no window on the north side
    assert archetype["internal_gains_profile_w_m2"] == [1.7] * 8 + [7.1] * 12 + [1.7] * 4
    assert not {"internal_gains_w_m2", "shading_permanent", "shading_hot", "hot_months"} & set(archetype)
    home = typical_building.archetype_of(changed(typical_building.PRESETS["heavy_home"].values, shading_hot=0.4, shading_permanent=0.9))
    assert home["internal_gains_w_m2"] == 5.0 and "internal_gains_profile_w_m2" not in home
    assert (home["shading_hot"], home["hot_months"], home["shading_permanent"]) == (0.4, [6, 7, 8], 0.9)
    expanded = simulated_weights.expand_shoebox({key: value for key, value in archetype.items() if not key.startswith("internal_gains")})
    assert expanded["floor_area"] == 35.0


@pytest.mark.parametrize("changes, field", [
    ({"width": 0}, "width"),                                    # Shape
    ({"height": "3"}, "height"),
    ({"wwr_south": 0.95}, "wwr.south"),                         # Windows
    ({"wwr": {"north": 0, "east": 0, "south": 0, "west": 0}}, "wwr"),
    ({"g_value": 1.2}, "g_value"),
    ({"mass_class": "stone"}, "mass_class"),                    # Walls and glass
    ({"u_opaque": 40.0}, "u_opaque"),                           # the engine's check: more loss than the mass can take
    ({"ach_vent": 0.0, "ach_infiltration": 0.0}, "ach_vent"),   # Air
    ({"heat_recovery": 1.5}, "heat_recovery"),
    ({"t_set_cooling": 19.0}, "t_set_cooling"),                 # Use
    ({"gains_day_w_m2": -1.0}, "gains_day_w_m2"),
    ({"shading_permanent": 2.0}, "shading_permanent"),          # Summer shading
    ({"shading_hot": 0.5, "hot_months": []}, "hot_months"),
    ({"hot_months": [13]}, "hot_months"),
])
def test_a_bad_value_is_refused_at_its_field(changes, field):
    with pytest.raises(ConfigError) as refused:
        typical_building.validate(changed(OFFICE, **changes))
    assert [error.field for error in refused.value.errors] == [field]


def test_a_missing_or_unknown_value_is_refused():
    values = {key: value for key, value in OFFICE.items() if key != "width"}
    with pytest.raises(ConfigError) as refused:
        typical_building.validate({**values, "colour": "red"})
    assert {error.field for error in refused.value.errors} == {"width", "colour"}


def test_the_key_follows_the_values_and_the_weather_file(tmp_path):
    other_weather = tmp_path / "other.epw"
    other_weather.write_bytes(GOLDEN_EPW.read_bytes() + b"\n")
    key = typical_building.weights_key(OFFICE, GOLDEN_EPW)
    assert key == typical_building.weights_key(copy.deepcopy(OFFICE), GOLDEN_EPW)
    assert len({key, typical_building.weights_key(changed(OFFICE, width=6.0), GOLDEN_EPW),
                typical_building.weights_key(OFFICE, other_weather), typical_building.weights_key(OFFICE, None)}) == 4


# ---- Routes ----

def test_a_new_project_has_the_office_not_calculated(client):
    create_project(client, "p", "benefit")
    reply = client.get("/api/projects/p/typical-building").json()
    assert reply == {"values": OFFICE, "start_from": "office", "state": "missing", "heating_kwh_m2": None, "cooling_kwh_m2": None,
                     "counted_hours": None}
    presets = client.get("/api/typical-building-presets").json()
    assert list(presets) == ["office", "heavy_home", "light_home"] and presets["office"] == {"label": "Office, medium mass", "values": OFFICE}
    assert client.get("/api/projects/p/typical-building/weights").status_code == 404


def test_the_building_is_saved_and_read_back(client):
    create_project(client, "p", "benefit")
    values = changed(typical_building.PRESETS["light_home"].values, width=6, wwr_north=0.1)
    saved = client.put("/api/projects/p/typical-building", json={"values": values, "start_from": "light_home"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["values"]["width"] == 6.0 and saved.json()["values"]["wwr"]["north"] == 0.1
    assert client.get("/api/projects/p/typical-building").json() == saved.json()
    assert saved.json()["start_from"] == "light_home" and saved.json()["state"] == "missing"


def test_a_bad_value_is_refused_by_the_route_and_nothing_changes(client):
    create_project(client, "p", "benefit")
    refused = client.put("/api/projects/p/typical-building", json={"values": changed(OFFICE, wwr_south=0.95), "start_from": "office"})
    assert refused.status_code == 422
    assert refused.json()["field_errors"] == [{"field": "wwr.south", "message": "Give a number from 0 to 0.9."}]
    refused = client.put("/api/projects/p/typical-building", json={"values": OFFICE, "start_from": "castle"})
    assert refused.status_code == 422 and refused.json()["field_errors"][0]["field"] == "start_from"
    assert client.get("/api/projects/p/typical-building").json()["values"] == OFFICE


def test_calculate_writes_the_weights_and_answers_the_numbers(client, fake_generator):
    create_project(client, "p", "benefit")
    assert upload(client, "p", "weather", ("golden.epw", GOLDEN_EPW.read_bytes())).status_code == 200
    reply = client.post("/api/projects/p/typical-building/calculate")
    assert reply.status_code == 200, reply.text
    assert reply.json() | {"values": None} == {"values": None, "start_from": "office", "state": "current", "heating_kwh_m2": 41.5,
                                               "cooling_kwh_m2": 12.25, "counted_hours": 1000}
    assert fake_generator.archetypes == [typical_building.archetype_of(OFFICE)]
    weights = client.get("/api/projects/p/typical-building/weights").json()
    assert len(weights["benefit"]) == len(weights["harm"]) == 8760
    assert weights["benefit"][0] == 0.5 and weights["harm"][-1] == 0.234      # 3 decimals
    # a change after the calculation leaves the numbers and dates them
    saved = client.put("/api/projects/p/typical-building", json={"values": changed(OFFICE, width=6.0), "start_from": None}).json()
    assert saved["state"] == "out_of_date" and saved["counted_hours"] == 1000


def test_calculate_without_a_weather_file_is_refused(client, fake_generator):
    create_project(client, "p", "benefit")
    refused = client.post("/api/projects/p/typical-building/calculate")
    assert refused.status_code == 404 and refused.json()["detail"] == sun_study.NO_WEATHER_FILE_MESSAGE
    assert fake_generator.archetypes == []


def test_calculate_is_refused_while_a_run_of_the_project_is_active(client_with_blocking_run, fake_generator):
    client, _run_id = client_with_blocking_run
    assert client.post("/api/projects/p/typical-building/calculate").status_code == 409
    assert client.put("/api/projects/p/typical-building", json={"values": OFFICE}).status_code == 409


def test_a_failed_calculation_is_reported_and_keeps_the_earlier_weights(tmp_path, monkeypatch):
    store, name = benefit_project(tmp_path)
    monkeypatch.setattr(simulated_weights, "generate_simulated_weights", FakeGenerator())
    first_key = typical_building.calculate(store, name)
    monkeypatch.setattr(simulated_weights, "generate_simulated_weights", FakeGenerator(ValueError("the weather file is broken")))
    with pytest.raises(typical_building.ProjectError, match="the weather file is broken") as refused:
        typical_building.calculate(store, name, changed(OFFICE, width=6.0))
    assert refused.value.status_code == 422
    assert store.read_project_json(name).typical_building.calculated_key == first_key
    folder = store.open(name) / "inputs" / "typical_building"
    assert sorted(path.name for path in folder.iterdir()) == ["weights.json", "weights.png"]


# ---- The criterion and config.yaml ----

def test_an_energy_weighted_criterion_names_the_weights_and_keeps_its_balance_temperature(tmp_path):
    store, name = benefit_project(tmp_path)
    store.update_criterion(name, "1", values={"mode": "benefit", "balance_temperature": 16.0, "balance_offset": 1.0})
    assert config_criteria(store, name)[0]["balance_temperature"] == 16.0
    entry = store.update_criterion(name, "1", energy_weighted=True)
    assert entry.energy_weighted and entry.settings["balance_temperature"] == 16.0
    criterion = config_criteria(store, name)[0]
    assert criterion["simulated_weights_path"] == typical_building.WEIGHTS_PATH
    assert "balance_temperature" not in criterion and "balance_offset" not in criterion
    flat = store.read_stored_config(name, "1")
    assert flat["simulated_weights_path"] == typical_building.WEIGHTS_PATH and "balance_temperature" not in flat
    assert store.read_settings(name, "1")["balance_temperature"] == 16.0          # the browser's settings keep it
    assert "simulated_weights_path" not in store.read_settings(name, "1")
    store.update_criterion(name, "1", energy_weighted=False)                        # switching back restores it
    criterion = config_criteria(store, name)[0]
    assert (criterion["balance_temperature"], criterion["balance_offset"]) == (16.0, 1.0) and "simulated_weights_path" not in criterion


def test_the_flag_is_ignored_by_another_mode_and_kept_by_a_copy(tmp_path):
    store, name = benefit_project(tmp_path, ("benefit", "irradiance"))
    store.update_criterion(name, "2", energy_weighted=True)
    assert "simulated_weights_path" not in config_criteria(store, name)[1]
    store.update_criterion(name, "1", energy_weighted=True)
    copied = store.duplicate_criterion(name, "1")
    assert copied.energy_weighted and config_criteria(store, name)[2]["simulated_weights_path"] == typical_building.WEIGHTS_PATH


def test_the_criterion_route_takes_the_flag(client):
    create_project(client, "p", "benefit")
    reply = client.patch("/api/projects/p/criteria/1", json={"energy_weighted": True})
    assert reply.status_code == 200, reply.text
    assert reply.json()["energy_weighted"] is True
    assert client.get("/api/projects/p").json()["criteria"][0]["energy_weighted"] is True


# ---- Stage status and runs ----

def test_a_run_with_missing_weights_calculates_them_first(tmp_path, fake_generator):
    store, name = benefit_project(tmp_path)
    store.update_criterion(name, "1", energy_weighted=True)
    worker = make_worker(store)
    reply = worker.start(name, ["thresholding"])
    events = wait_until_finished(worker, reply.run_id)
    assert events[-1]["type"] == "run_finished", events[-1]
    progress = [(event["stage"], event["criterion"], event["done"], event["total"]) for event in events if event["type"] == "stage_progress"]
    assert progress[:2] == [("typical_building", None, 0, 1), ("typical_building", None, 1, 1)]
    assert progress[2][0] == "preprocessing"
    assert len(fake_generator.archetypes) == 1
    key = typical_building.current_key(store, name)
    project_json = store.read_project_json(name)
    assert project_json.typical_building.calculated_key == key
    assert project_json.criterion_records["1"]["preprocessing"].weights_key == key
    assert project_json.criterion_records["1"]["thresholding"].weights_key is None
    assert criterion_status(store, name)["1"] == {"preprocessing": "current", "thresholding": "current"}
    assert typical_building.reply(store, name).state == "current"


def test_a_run_with_current_weights_does_not_calculate_them_again(tmp_path, fake_generator):
    store, name = benefit_project(tmp_path)
    store.update_criterion(name, "1", energy_weighted=True)
    typical_building.calculate(store, name)
    worker = make_worker(store)
    events = wait_until_finished(worker, worker.start(name, ["thresholding"]).run_id)
    assert events[-1]["type"] == "run_finished"
    assert len(fake_generator.archetypes) == 1
    assert not any(event.get("stage") == "typical_building" for event in events)


def test_a_changed_building_dates_only_the_energy_weighted_criteria(tmp_path, fake_generator):
    store, name = benefit_project(tmp_path, ("benefit", "benefit"))
    store.update_criterion(name, "2", energy_weighted=True)
    worker = make_worker(store)
    run_and_wait(worker, name, ["thresholding"])
    assert criterion_status(store, name) == {criterion_id: {"preprocessing": "current", "thresholding": "current"} for criterion_id in "12"}
    typical_building.save(store, name, changed(OFFICE, mass_class="heavy"), "office")
    assert criterion_status(store, name) == {"1": {"preprocessing": "current", "thresholding": "current"},
                                             "2": {"preprocessing": "out_of_date", "thresholding": "out_of_date"}}
    reply = run_and_wait(worker, name, ["thresholding"])
    assert reply.criterion_stages == {"1": [], "2": ["preprocessing", "thresholding"]}
    assert fake_generator.archetypes[-1]["mass_class"] == "heavy" and len(fake_generator.archetypes) == 2
    assert criterion_status(store, name)["2"] == {"preprocessing": "current", "thresholding": "current"}


def test_switching_to_cold_hours_dates_the_criterion_through_its_settings(tmp_path, fake_generator):
    store, name = benefit_project(tmp_path)
    store.update_criterion(name, "1", energy_weighted=True)
    run_and_wait(make_worker(store), name, ["thresholding"])
    store.update_criterion(name, "1", energy_weighted=False)
    assert criterion_status(store, name)["1"]["preprocessing"] == "out_of_date"


def test_a_failed_calculation_ends_the_run(tmp_path, monkeypatch):
    store, name = benefit_project(tmp_path)
    store.update_criterion(name, "1", energy_weighted=True)
    monkeypatch.setattr(simulated_weights, "generate_simulated_weights", FakeGenerator(ValueError("no sun in this file")))
    engine = FakeEngine()
    worker = make_worker(store, handle_request=engine)
    events = wait_until_finished(worker, worker.start(name, ["thresholding"]).run_id)
    assert events[-1]["type"] == "run_failed" and "no sun in this file" in events[-1]["message"]
    assert engine.requests == []
    assert criterion_status(store, name)["1"]["preprocessing"] == "missing"


# ---- With the real generator ----

@pytest.mark.slow
def test_calculate_with_the_engine_gives_the_numbers_of_its_file(client, projects_folder):
    create_project(client, "p", "benefit")
    assert upload(client, "p", "weather", ("golden.epw", GOLDEN_EPW.read_bytes())).status_code == 200
    reply = client.post("/api/projects/p/typical-building/calculate").json()
    assert reply["state"] == "current"
    assert 0 < reply["heating_kwh_m2"] < 300 and 0 < reply["cooling_kwh_m2"] < 300
    benefit, _harm, meta = simulated_weights.read_simulated_weights(projects_folder / "p" / typical_building.WEIGHTS_PATH)
    assert (reply["heating_kwh_m2"], reply["cooling_kwh_m2"]) == (meta["heating_kwh_m2"], meta["cooling_kwh_m2"])
    assert reply["counted_hours"] == int((benefit > 0.01).sum())
    weights = client.get("/api/projects/p/typical-building/weights").json()
    january, july = slice(0, 31 * 24), slice(181 * 24, 212 * 24)
    assert np.mean(weights["benefit"][january]) > np.mean(weights["benefit"][july])
