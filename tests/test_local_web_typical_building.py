"""The typical building of an energy-weighted Solar usefulness criterion (local_web_service.typical_building): its values, the
library, routes, the generated config.yaml, stage status and the run that calculates its weights first.

The engine is the fake of local_web_test_support.py. The fast tests replace the weights generator (about 7 s on the bundled
weather file) by a fake that writes a valid weights file at once; the tests marked slow run the real one. Every test has a home
folder of its own, so the library's own entries (beside the user preferences file) are never those of the user.
"""
import copy
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from local_web_test_support import GOLDEN_EPW, FakeEngine, box_bytes, make_worker, run_and_wait, wait_until_finished
from test_local_web_server import build_client, client, client_with_blocking_run, create_project, projects_folder, upload  # noqa: F401 (fixtures)
from urbansolarcarver import simulated_weights
from urbansolarcarver.errors import ConfigError
from urbansolarcarver.local_web_service import typical_building
from urbansolarcarver.local_web_service.api_models import TypicalBuildingEntry
from urbansolarcarver.local_web_service.projects import ProjectStore
from urbansolarcarver.local_web_service.stage_records import criterion_status

pytestmark = pytest.mark.skipif(not GOLDEN_EPW.is_file(), reason="the bundled weather file is missing")

DEFAULT = typical_building.EXAMPLES["kenak-apartment-b"].values
OFFICE = typical_building.EXAMPLES["kenak-office-b"].values
BOX = typical_building.EXAMPLES["ashrae140-600"].values
EXAMPLE_IDS = ["kenak-apartment-a", "kenak-apartment-b", "kenak-apartment-c", "kenak-apartment-d",
               "kenak-office-a", "kenak-office-b", "kenak-office-c", "kenak-office-d", "ashrae140-600", "ashrae140-900"]


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """A home folder of its own (as test_local_web_server.home_folder), so the library's folder is in it."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    assert Path.home() == home
    return home


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
        benefit = np.where(hours < 1000, 0.5, 0.0)          # 1,000 hours above 0.01, 500 of them with the sun up
        harm = np.where(hours > 8000, 0.2345, 0.0)
        sun_up = [int(hour >= 500) for hour in hours]
        path = simulated_weights.write_simulated_weights(out_path, benefit, harm,
                                                         {"heating_kwh_m2": 41.5, "cooling_kwh_m2": 12.25, "sun_up": sun_up})
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
    """A copy of *values* with *changes*; a key "wwr_<side>" changes one window share, a value None of "drop_<key>" removes a key."""
    copied = copy.deepcopy(values)
    for key, value in changes.items():
        if key.startswith("wwr_"):
            copied["wwr"][key.removeprefix("wwr_")] = value
        elif key.startswith("drop_"):
            copied.pop(key.removeprefix("drop_"))
        else:
            copied[key] = value
    return copied


# ---- The examples and the archetype ----

def test_the_examples_are_valid_and_stored_as_given():
    entries = typical_building.library()
    assert [entry.id for entry in entries] == EXAMPLE_IDS
    assert [entry.name for entry in entries[:5]] == ["Apartment, zone Α", "Apartment, zone Β", "Apartment, zone Γ", "Apartment, zone Δ",
                                                     "Office, zone Α"]
    assert [entry.name for entry in entries[-2:]] == ["ASHRAE 140 case 600 (light)", "ASHRAE 140 case 900 (heavy)"]
    assert [entry.group for entry in entries] == ["apartment"] * 4 + ["office"] * 4 + ["test"] * 2
    assert all(entry.read_only and entry.source for entry in entries)
    assert entries[0].source == "ΤΟΤΕΕ 20701-1/2017 (ΦΕΚ Β' 4003/17.11.2017), reference building, zone Α"
    for entry in entries:
        assert typical_building.validate(entry.values) == entry.values


def test_the_kenak_examples_have_the_values_of_the_reference_building():
    by_zone = {zone: typical_building.EXAMPLES[f"kenak-apartment-{zone}"].values for zone in "abcd"}
    assert [(v["u_wall"], v["u_roof"], v["u_floor"], v["u_window"]) for v in by_zone.values()] == [
        (0.60, 0.50, 0.50, 3.20), (0.50, 0.45, 0.45, 3.00), (0.45, 0.40, 0.40, 2.80), (0.40, 0.35, 0.35, 2.60)]
    assert [(v["shading_start"], v["shading_end"]) for v in by_zone.values()] == [("05-15", "09-15")] * 2 + [("06-01", "08-31")] * 2
    assert {key: DEFAULT[key] for key in ("schedule", "gains_w_m2", "fresh_air_m3h_m2", "heat_recovery", "totee_category")} == {
        "schedule": "apartment", "gains_w_m2": 6.0, "fresh_air_m3h_m2": 0.75, "heat_recovery": 0.0, "totee_category": "reference"}
    assert {key: OFFICE[key] for key in ("schedule", "gains_w_m2", "fresh_air_m3h_m2", "heat_recovery", "totee_category")} == {
        "schedule": "office", "gains_w_m2": 28.5, "fresh_air_m3h_m2": 3.0, "heat_recovery": 0.5, "totee_category": "reference"}
    assert all(entry.values["mass_kind"] == "totee" and entry.values["totee_category"] == "reference"
               for entry in typical_building.library() if entry.id.startswith("kenak-"))
    assert typical_building.TOTEE_CATEGORIES["reference"] == (250.0, "Reference building (ΚΕΝΑΚ art. 9): 250 kJ/m²K")
    assert (DEFAULT["g_value"], DEFAULT["shading_factor"], DEFAULT["infiltration_m3h_m2_window"]) == (0.55, 0.77, 5.5)
    assert (DEFAULT["room"], DEFAULT["depth"], DEFAULT["height"], DEFAULT["wwr"]) == (
        "average", 6.0, 3.0, {"ne": 0.4, "se": 0.4, "sw": 0.4, "nw": 0.4})
    assert (DEFAULT["roof_exposed"], DEFAULT["floor_exposed"]) == (False, False)


def test_the_average_room_is_a_box_turned_45_degrees():
    archetype = typical_building.archetype_of(DEFAULT, GOLDEN_EPW)
    assert (archetype["width"], archetype["length"], archetype["orientation"]) == (24.0, 24.0, 45.0)
    assert archetype["wwr"] == {"north": 0.4, "east": 0.4, "south": 0.4, "west": 0.4}
    as_box = {key: value for key, value in DEFAULT.items() if key != "depth"} | {
        "room": "box", "width": 24.0, "length": 24.0, "orientation": 45.0, "wwr": {"north": 0.4, "east": 0.4, "south": 0.4, "west": 0.4}}
    assert typical_building.archetype_of(typical_building.validate(as_box), GOLDEN_EPW) == archetype
    expanded = simulated_weights.expand_shoebox({key: value for key, value in archetype.items()
                                                 if key not in ("internal_gains_w_m2", "shading_hot", "shading_hot_period")})
    assert sorted(azimuth for azimuth, _area, _g in expanded["windows"]) == [45.0, 135.0, 225.0, 315.0]
    assert expanded["area_opaque"] == pytest.approx(4 * 24 * 3 * 0.6)      # the walls only: roof and floor adiabatic
    assert expanded["u_opaque"] == pytest.approx(0.5)


def test_the_air_and_the_gains_follow_the_schedule():
    archetype = typical_building.archetype_of(DEFAULT, GOLDEN_EPW)
    vent, gains = np.asarray(archetype["ach_vent"]), np.asarray(archetype["internal_gains_w_m2"])
    assert vent.shape == gains.shape == (8760,)
    assert list(gains[:24]) == [0.0] * 6 + [6.0] * 18                           # 6:00 to 24:00 every day
    assert vent.max() == pytest.approx(0.75 / 3.0) and (vent > 0).sum() == 365 * 18
    assert archetype["ach_infiltration"] == pytest.approx(5.5 * 0.4 * 4 * 24 * 3 / (24 * 24 * 3))
    office = np.asarray(typical_building.archetype_of(OFFICE, GOLDEN_EPW)["internal_gains_w_m2"]).reshape(365, 24)
    # 1 January of the Golden file is a Sunday (DATA PERIODS), so the first working day is the second day of the year
    assert office[0].sum() == 0.0 and list(office[1]) == [0.0] * 8 + [28.5] * 10 + [0.0] * 6
    assert (office.sum(axis=1) > 0).sum() == 52 * 5                             # 365 days from a Sunday to a Sunday: 260 working days
    box = typical_building.archetype_of(BOX, GOLDEN_EPW)                        # every hour: one value each
    assert (box["ach_vent"], box["internal_gains_w_m2"]) == (0.0, BOX["gains_w_m2"])
    assert box["ach_infiltration"] == pytest.approx(0.5, abs=1e-3)


def test_the_mass_and_the_shading_become_engine_keys():
    archetype = typical_building.archetype_of(DEFAULT)
    assert archetype["mass_capacity_kj_m2k"] == 250.0 and "mass_class" not in archetype
    category_5 = typical_building.archetype_of(changed(DEFAULT, totee_category=5.0))
    assert category_5["mass_capacity_kj_m2k"] == 280.0
    assert typical_building.validate(changed(DEFAULT, totee_category=5.0))["totee_category"] == 5
    assert (archetype["shading_hot"], archetype["shading_hot_period"]) == (0.77, [135, 258])     # 15 May to 15 September
    iso = typical_building.archetype_of(changed(DEFAULT, mass_kind="iso", shading_factor=None))
    assert iso["mass_class"] == "heavy" and "mass_capacity_kj_m2k" not in iso
    assert not {"shading_hot", "shading_hot_period"} & set(iso)


def test_the_weekday_of_the_first_day_comes_from_the_weather_file(tmp_path):
    assert typical_building.first_weekday(GOLDEN_EPW) == 6
    no_header = tmp_path / "plain.epw"
    no_header.write_text("LOCATION,x\n1999,1,1,1,0\n", encoding="latin-1")
    assert typical_building.first_weekday(no_header) == 0 and typical_building.first_weekday(None) == 0
    assert typical_building.first_weekday(tmp_path / "missing.epw") == 0


@pytest.mark.parametrize("values, changes, field", [
    (DEFAULT, {"schedule": "night"}, "schedule"),                       # Use
    (DEFAULT, {"t_set_cooling": 19.0}, "t_set_cooling"),
    (DEFAULT, {"gains_w_m2": -1.0}, "gains_w_m2"),
    (DEFAULT, {"fresh_air_m3h_m2": "a lot"}, "fresh_air_m3h_m2"),
    (DEFAULT, {"heat_recovery": 1.5}, "heat_recovery"),
    (DEFAULT, {"u_wall": 0.0}, "u_wall"),                               # Fabric
    (DEFAULT, {"u_window": None}, "u_window"),
    (DEFAULT, {"g_value": 1.2}, "g_value"),
    (DEFAULT, {"mass_kind": "stone"}, "mass_kind"),
    (DEFAULT, {"mass_class": "granite"}, "mass_class"),
    (DEFAULT, {"totee_category": 7}, "totee_category"),
    (DEFAULT, {"totee_category": True}, "totee_category"),
    (DEFAULT, {"totee_category": "Reference"}, "totee_category"),
    (DEFAULT, {"u_wall": 100.0}, "u_wall"),                             # the engine's check: more loss than the mass can take
    (DEFAULT, {"shading_factor": 2.0}, "shading_factor"),               # Summer shading
    (DEFAULT, {"shading_start": "02-29"}, "shading_start"),
    (DEFAULT, {"shading_end": "9-15"}, "shading_end"),
    (DEFAULT, {"room": "castle"}, "room"),                              # Room
    (DEFAULT, {"height": 0}, "height"),
    (DEFAULT, {"depth": -6.0}, "depth"),
    (DEFAULT, {"wwr_ne": 0.95}, "wwr.ne"),
    (DEFAULT, {"wwr": {"north": 0.4}}, "wwr"),                          # a side of the box in the average room
    (DEFAULT, {"wwr": {"ne": 0, "se": 0, "sw": 0, "nw": 0}}, "wwr"),
    (BOX, {"width": 0.0}, "width"),
    (BOX, {"orientation": "south"}, "orientation"),
    (DEFAULT, {"roof_exposed": "yes"}, "roof_exposed"),                 # Roof and floor
    (DEFAULT, {"floor_exposed": 1}, "floor_exposed"),
    (DEFAULT, {"u_roof": 0.0}, "u_roof"),
    (DEFAULT, {"u_floor": "0.4"}, "u_floor"),
    (DEFAULT, {"infiltration_m3h_m2_window": -1.0}, "infiltration_m3h_m2_window"),     # Air
    (DEFAULT, {"infiltration_m3h_m2_window": 0.0}, "infiltration_m3h_m2_window"),      # no air change at night
])
def test_a_bad_value_is_refused_at_its_field(values, changes, field):
    with pytest.raises(ConfigError) as refused:
        typical_building.validate(changed(values, **changes))
    assert [error.field for error in refused.value.errors] == [field]


def test_the_messages_name_what_to_give():
    def messages(**changes):
        with pytest.raises(ConfigError) as refused:
            typical_building.validate(changed(DEFAULT, **changes))
        return [error.message for error in refused.value.errors]

    assert messages(schedule="night") == ["Choose one of apartment, office, always."]
    assert messages(totee_category=0) == ["Choose one of 1, 2, 3, 4, 5, 6, reference."]
    assert messages(shading_start="02-29") == ["Give a day as MM-DD, for example 05-15 for 15 May (not 02-29)."]
    assert messages(roof_exposed="yes") == ["Give true or false."]
    assert messages(wwr_ne=0.95) == ["Give a number from 0 to 0.9."]
    assert messages(infiltration_m3h_m2_window=0.0) == [
        "Some hours have no air change (no fresh air and no infiltration): give the infiltration a value above 0."]


def test_a_missing_or_unknown_value_is_refused():
    with pytest.raises(ConfigError) as refused:
        typical_building.validate({**changed(DEFAULT, drop_u_wall=None), "colour": "red", "width": 8.0})
    assert {(error.field, error.message) for error in refused.value.errors} == {
        ("u_wall", "This value is missing."), ("colour", "Not a value of the typical building."),
        ("width", "Not a value of the average room.")}
    with pytest.raises(ConfigError) as refused:
        typical_building.validate(changed(BOX, drop_orientation=None))
    assert [(error.field, error.message) for error in refused.value.errors] == [("orientation", "This value is missing.")]


def test_the_key_follows_the_values_and_the_weather_file(tmp_path):
    other_weather = tmp_path / "other.epw"
    other_weather.write_bytes(GOLDEN_EPW.read_bytes() + b"\n")
    key = typical_building.weights_key(DEFAULT, GOLDEN_EPW)
    assert key == typical_building.weights_key(copy.deepcopy(DEFAULT), GOLDEN_EPW)
    assert len({key, typical_building.weights_key(changed(DEFAULT, depth=5.0), GOLDEN_EPW),
                typical_building.weights_key(DEFAULT, other_weather), typical_building.weights_key(DEFAULT, None)}) == 4


# ---- The library ----

def test_the_library_lists_the_examples_then_the_own_entries(client, home_folder):
    listed = client.get("/api/typical-building-library").json()
    assert [entry["id"] for entry in listed] == EXAMPLE_IDS
    assert listed[1] == {"id": "kenak-apartment-b", "name": "Apartment, zone Β", "group": "apartment", "read_only": True,
                         "source": "ΤΟΤΕΕ 20701-1/2017 (ΦΕΚ Β' 4003/17.11.2017), reference building, zone Β", "values": DEFAULT}
    added = client.post("/api/typical-building-library", json={"name": "  My flat ", "values": changed(DEFAULT, u_wall=0.3)})
    assert added.status_code == 200, added.text
    entry = added.json()
    assert entry["id"].startswith("own-") and (entry["name"], entry["group"], entry["read_only"], entry["source"]) == (
        "My flat", "own", False, None)
    client.post("/api/typical-building-library", json={"name": "Another flat", "values": DEFAULT})
    listed = client.get("/api/typical-building-library").json()
    assert [entry["name"] for entry in listed[len(EXAMPLE_IDS):]] == ["Another flat", "My flat"]
    stored = yaml.safe_load((home_folder / ".urbansolarcarver" / "typical_buildings" / f"{entry['id']}.yaml").read_text(encoding="utf-8"))
    assert stored == {"name": "My flat", "values": changed(DEFAULT, u_wall=0.3)}


def test_an_own_entry_is_renamed_changed_and_deleted(client):
    entry_id = client.post("/api/typical-building-library", json={"name": "Mine", "values": DEFAULT}).json()["id"]
    renamed = client.put(f"/api/typical-building-library/{entry_id}", json={"name": "Ours"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Ours" and renamed.json()["values"] == DEFAULT
    saved = client.put(f"/api/typical-building-library/{entry_id}", json={"values": changed(DEFAULT, depth=5.0)}).json()
    assert saved["name"] == "Ours" and saved["values"]["depth"] == 5.0
    assert client.delete(f"/api/typical-building-library/{entry_id}").status_code == 204
    assert client.delete(f"/api/typical-building-library/{entry_id}").status_code == 404
    assert client.put(f"/api/typical-building-library/{entry_id}", json={"name": "Again"}).status_code == 404
    assert [entry["id"] for entry in client.get("/api/typical-building-library").json()] == EXAMPLE_IDS


def test_the_examples_are_read_only(client):
    refused = client.put("/api/typical-building-library/kenak-office-a", json={"name": "Mine"})
    assert refused.status_code == 409 and "example" in refused.json()["detail"]
    assert client.delete("/api/typical-building-library/ashrae140-600").status_code == 409
    assert client.delete("/api/typical-building-library/..%5Cui").status_code == 404
    assert typical_building.EXAMPLES["kenak-office-a"].name == "Office, zone Α"


def test_a_name_in_use_or_a_bad_value_is_refused_and_nothing_is_saved(client, home_folder):
    entry_id = client.post("/api/typical-building-library", json={"name": "Mine", "values": DEFAULT}).json()["id"]
    for name in ("mine", "Apartment, zone Β"):
        refused = client.post("/api/typical-building-library", json={"name": name, "values": DEFAULT})
        assert refused.status_code == 409 and name in refused.json()["detail"]
    assert client.put(f"/api/typical-building-library/{entry_id}", json={"name": "MINE"}).status_code == 200     # its own name
    refused = client.post("/api/typical-building-library", json={"name": " ", "values": DEFAULT})
    assert refused.status_code == 422 and refused.json()["field_errors"] == [{"field": "name", "message": "Give the building a name."}]
    refused = client.post("/api/typical-building-library", json={"name": "x" * 81, "values": DEFAULT})
    assert refused.json()["field_errors"][0]["field"] == "name"
    refused = client.put(f"/api/typical-building-library/{entry_id}", json={"values": changed(DEFAULT, wwr_se=0.95)})
    assert refused.status_code == 422 and refused.json()["field_errors"] == [{"field": "wwr.se", "message": "Give a number from 0 to 0.9."}]
    assert len(list((home_folder / ".urbansolarcarver" / "typical_buildings").iterdir())) == 1
    assert typical_building.library_entry(entry_id).values == DEFAULT


def test_the_openapi_document_names_the_library_routes():
    from urbansolarcarver.local_web_service.server import openapi_document
    paths = openapi_document()["paths"]
    assert paths["/api/typical-building-library"]["get"]["operationId"] == "typical_building_library"
    assert paths["/api/typical-building-library"]["post"]["operationId"] == "add_typical_building_library_entry"
    assert {method: operation["operationId"] for method, operation in paths["/api/typical-building-library/{entry_id}"].items()} == {
        "put": "update_typical_building_library_entry", "delete": "delete_typical_building_library_entry"}
    assert "/api/typical-building-presets" not in paths


def test_a_damaged_own_entry_is_left_out(home_folder):
    entry = typical_building.add_entry("Mine", DEFAULT)
    folder = typical_building.library_folder()
    assert folder == home_folder / ".urbansolarcarver" / "typical_buildings"
    (folder / "own-0123456789ab.yaml").write_text("{not yaml", encoding="utf-8")
    (folder / "own-ba9876543210.yaml").write_text(yaml.safe_dump({"name": "Old", "values": {"width": 5.0}}), encoding="utf-8")
    assert [own.id for own in typical_building.own_entries()] == [entry.id]
    assert typical_building.library_entry("own-0123456789ab") is None


# ---- The project's building ----

def test_a_new_project_has_a_copy_of_the_default_entry(client):
    create_project(client, "p", "benefit")
    reply = client.get("/api/projects/p/typical-building").json()
    assert reply == {"values": DEFAULT, "library_id": "kenak-apartment-b", "library_name": "Apartment, zone Β", "changed": False,
                     "state": "missing", "heating_kwh_m2": None, "cooling_kwh_m2": None, "counted_hours": None}
    assert client.get("/api/projects/p/typical-building/weights").status_code == 404


def test_choosing_an_entry_and_editing_the_copy(client):
    create_project(client, "p", "benefit")
    chosen = client.put("/api/projects/p/typical-building", json={"values": OFFICE, "library_id": "kenak-office-b"})
    assert chosen.status_code == 200, chosen.text
    assert (chosen.json()["library_id"], chosen.json()["library_name"], chosen.json()["changed"]) == (
        "kenak-office-b", "Office, zone Β", False)
    edited = client.put("/api/projects/p/typical-building", json={"values": changed(OFFICE, depth=5)}).json()     # library_id left out
    assert (edited["library_id"], edited["changed"], edited["values"]["depth"]) == ("kenak-office-b", True, 5.0)
    assert client.get("/api/projects/p/typical-building").json() == edited
    detached = client.put("/api/projects/p/typical-building", json={"values": OFFICE, "library_id": None}).json()
    assert (detached["library_id"], detached["library_name"], detached["changed"]) == (None, None, False)
    refused = client.put("/api/projects/p/typical-building", json={"values": OFFICE, "library_id": "kenak-office-z"})
    assert refused.status_code == 422 and refused.json()["field_errors"] == [
        {"field": "library_id", "message": "Not a building in the library."}]


def test_the_copy_survives_a_change_and_a_deletion_of_its_entry(client):
    create_project(client, "p", "benefit")
    entry_id = client.post("/api/typical-building-library", json={"name": "Mine", "values": BOX}).json()["id"]
    client.put("/api/projects/p/typical-building", json={"values": BOX, "library_id": entry_id})
    client.put(f"/api/typical-building-library/{entry_id}", json={"name": "Ours", "values": changed(BOX, width=10.0)})
    reply = client.get("/api/projects/p/typical-building").json()
    assert (reply["values"], reply["library_name"], reply["changed"]) == (BOX, "Ours", True)
    client.put(f"/api/typical-building-library/{entry_id}", json={"values": BOX})          # Save to library
    assert client.get("/api/projects/p/typical-building").json()["changed"] is False
    client.delete(f"/api/typical-building-library/{entry_id}")
    reply = client.get("/api/projects/p/typical-building").json()
    assert (reply["values"], reply["library_id"], reply["library_name"], reply["changed"]) == (BOX, entry_id, "Mine", False)


def test_a_building_of_the_first_form_reads_as_the_default(tmp_path):
    store, name = benefit_project(tmp_path)
    project_json = store.read_project_json(name)
    project_json.typical_building = TypicalBuildingEntry(values={"width": 5.0, "u_opaque": 0.5}, calculated_key="old")
    store.write_project_json(name, project_json)
    building = typical_building.building_of(store.read_project_json(name))
    assert (building.values, building.library_id, building.calculated_key) == (DEFAULT, "kenak-apartment-b", None)


def test_a_bad_value_is_refused_by_the_route_and_nothing_changes(client):
    create_project(client, "p", "benefit")
    refused = client.put("/api/projects/p/typical-building", json={"values": changed(DEFAULT, wwr_sw=0.95)})
    assert refused.status_code == 422
    assert refused.json()["field_errors"] == [{"field": "wwr.sw", "message": "Give a number from 0 to 0.9."}]
    assert client.get("/api/projects/p/typical-building").json()["values"] == DEFAULT


def test_calculate_writes_the_weights_and_answers_the_numbers(client, fake_generator):
    create_project(client, "p", "benefit")
    assert upload(client, "p", "weather", ("golden.epw", GOLDEN_EPW.read_bytes())).status_code == 200
    reply = client.post("/api/projects/p/typical-building/calculate")
    assert reply.status_code == 200, reply.text
    assert reply.json() | {"values": None} == {"values": None, "library_id": "kenak-apartment-b", "library_name": "Apartment, zone Β",
                                               "changed": False, "state": "current", "heating_kwh_m2": 41.5, "cooling_kwh_m2": 12.25,
                                               "counted_hours": 500}       # the hours with the sun up only
    assert json.dumps(fake_generator.archetypes) == json.dumps([typical_building.archetype_of(DEFAULT, GOLDEN_EPW)])
    weights = client.get("/api/projects/p/typical-building/weights").json()
    assert len(weights["benefit"]) == len(weights["harm"]) == len(weights["sun_up"]) == 8760
    assert weights["benefit"][0] == 0.5 and weights["harm"][-1] == 0.234      # 3 decimals
    assert weights["sun_up"][499:501] == [0, 1]
    # a change after the calculation leaves the numbers and dates them
    saved = client.put("/api/projects/p/typical-building", json={"values": changed(DEFAULT, depth=5.0)}).json()
    assert saved["state"] == "out_of_date" and saved["counted_hours"] == 500 and saved["changed"] is True


def test_a_weights_file_without_sun_up_counts_every_hour(tmp_path):
    store, name = benefit_project(tmp_path)
    path = typical_building.weights_file(store.open(name))
    benefit = np.where(np.arange(8760) < 1000, 0.5, 0.0)
    simulated_weights.write_simulated_weights(path, benefit, np.zeros(8760), {})
    assert typical_building.reply(store, name).counted_hours == 1000
    assert typical_building.weights_reply(store, name).sun_up == [1] * 8760


def test_calculate_without_a_weather_file_is_refused(client, fake_generator):
    create_project(client, "p", "benefit")
    refused = client.post("/api/projects/p/typical-building/calculate")
    assert refused.status_code == 404 and refused.json()["detail"] == typical_building.NO_WEATHER_FILE_MESSAGE
    assert fake_generator.archetypes == []


def test_calculate_is_refused_while_a_run_of_the_project_is_active(client_with_blocking_run, fake_generator):
    client, _run_id = client_with_blocking_run
    assert client.post("/api/projects/p/typical-building/calculate").status_code == 409
    assert client.put("/api/projects/p/typical-building", json={"values": DEFAULT}).status_code == 409


def test_a_failed_calculation_is_reported_and_keeps_the_earlier_weights(tmp_path, monkeypatch):
    store, name = benefit_project(tmp_path)
    monkeypatch.setattr(simulated_weights, "generate_simulated_weights", FakeGenerator())
    first_key = typical_building.calculate(store, name)
    monkeypatch.setattr(simulated_weights, "generate_simulated_weights", FakeGenerator(ValueError("the weather file is broken")))
    with pytest.raises(typical_building.ProjectError, match="the weather file is broken") as refused:
        typical_building.calculate(store, name, changed(DEFAULT, depth=5.0))
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
    typical_building.save(store, name, changed(DEFAULT, mass_kind="iso", mass_class="very_heavy"))
    assert criterion_status(store, name) == {"1": {"preprocessing": "current", "thresholding": "current"},
                                             "2": {"preprocessing": "out_of_date", "thresholding": "out_of_date"}}
    reply = run_and_wait(worker, name, ["thresholding"])
    assert reply.criterion_stages == {"1": [], "2": ["preprocessing", "thresholding"]}
    assert fake_generator.archetypes[-1]["mass_class"] == "very_heavy" and len(fake_generator.archetypes) == 2
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
    assert reply["counted_hours"] == int(((benefit > 0.01) & np.asarray(meta["sun_up"], dtype=bool)).sum())
    weights = client.get("/api/projects/p/typical-building/weights").json()
    january, july = slice(0, 31 * 24), slice(181 * 24, 212 * 24)
    assert np.mean(weights["benefit"][january]) > np.mean(weights["benefit"][july])


@pytest.mark.slow
def test_every_example_calculates_on_the_bundled_weather_file(tmp_path):
    """Each example's weights on the Golden weather file (about 7 s each); the numbers are printed (-s) for the docs."""
    numbers = {}
    for entry in typical_building.library():
        out = simulated_weights.generate_simulated_weights(str(GOLDEN_EPW), typical_building.archetype_of(entry.values, GOLDEN_EPW),
                                                           tmp_path / f"{entry.id}.json")
        benefit, harm, meta = simulated_weights.read_simulated_weights(out)
        sun_up = np.asarray(meta["sun_up"], dtype=bool)
        numbers[entry.id] = (meta["heating_kwh_m2"], meta["cooling_kwh_m2"], int(((benefit > 0.01) & sun_up).sum()))
        print(f"{entry.id}: heating {numbers[entry.id][0]:.1f}, cooling {numbers[entry.id][1]:.1f} kWh/m², "
              f"hours that count {numbers[entry.id][2]}")
        assert numbers[entry.id][0] > 0 and numbers[entry.id][1] > 0 and 0 < numbers[entry.id][2] <= sun_up.sum()
        assert not (benefit[~sun_up] > 0.5).all()           # the mass carries some of the day's sun into the night
    for use in ("apartment", "office"):
        heating = [numbers[f"kenak-{use}-{zone}"][0] for zone in "abcd"]
        assert heating == sorted(heating, reverse=True)     # the colder zones' walls are better insulated
    assert numbers["ashrae140-900"][0] < numbers["ashrae140-600"][0]        # the heavy box stores the sun of the day
