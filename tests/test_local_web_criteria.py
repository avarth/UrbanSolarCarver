"""Criteria in project.json and the chain-form config.yaml generated from them (local web service)."""
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from urbansolarcarver.chain_config import CRITERION_KEYS, is_chain_file, load_chain
from urbansolarcarver.errors import ConfigError
from urbansolarcarver.local_web_service.api_models import CriterionEntry
from urbansolarcarver.local_web_service.criteria import CRITERION_COLOURS, MODE_LABELS, chain_config_document, default_criterion_name, split_settings
from urbansolarcarver.local_web_service.projects import ProjectError, ProjectStore
from urbansolarcarver.mode_registry import MODES

COMMENT_LINE = "# Written by the UrbanSolarCarver app from project.json; change settings in the app."
# The names of the modes as the app shows them (step_summaries.ts reads them for the Mode step and the step summaries).
APP_MODE_TILES_PATH = Path(__file__).resolve().parent.parent / "app" / "src" / "steps" / "mode_tiles.json"


def _config_path(store, name):
    return store.open(name) / "config.yaml"


def _stored(store, name):
    return yaml.safe_load(_config_path(store, name).read_text(encoding="utf-8"))


def _ids_in_config(store, name):
    return [criterion["id"] for criterion in _stored(store, name)["criteria"]]


def test_a_new_project_has_one_criterion_and_a_chain_config(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("p", "time-based")
    config_path = _config_path(store, "p")
    assert is_chain_file(str(config_path))
    stored = _stored(store, "p")
    assert [(criterion["id"], criterion["mode"]) for criterion in stored["criteria"]] == [("1", "time-based")]
    assert stored["criteria"][0]["test_surface_path"] == "inputs/joined/test_surfaces_1.ply"
    assert "mode" not in {key for key in stored if key != "criteria"}    # the mode is the criterion's, not shared
    chain = load_chain(str(config_path))
    assert [(criterion.id, criterion.config.mode) for criterion in chain.criteria] == [("1", "time-based")]
    [entry] = store.criteria("p")
    assert (entry.id, entry.name, entry.named_by_user, entry.bypassed) == ("1", "Solar time-based", False, False)
    assert entry.colour == CRITERION_COLOURS[0] and entry.test_surface_files == []
    assert entry.settings["mode"] == "time-based" and "test_surface_path" not in entry.settings
    assert store.read_project_json("p").next_criterion_id == 2


# What a save of these mixed values (shared and criterion keys, the way the current app sends them) on a project made from
# the example "New building among neighbors" returned before criteria existed, and what reading it back returned.
MIXED_VALUES = {
    "mode": "irradiance", "voxel_size": 2.0, "threshold": "carve_fraction", "carve_fraction": 0.4, "north_deg": 20,
    "start_month": 5, "end_month": 8, "start_day": 1, "end_day": 31, "start_hour": 8, "end_hour": 16, "smooth_iters": 2,
    "final_mesh_format": "obj", "carve_above": True, "max_slope_deg": 60, "ground_floor_height": 3.0, "floor_height": 3.2,
    "out_dir": "elsewhere", "device": "cuda", "grid_step": 0.5, "epw_path": "x.epw", "max_volume_path": "y.ply",
}
SETTINGS_BEFORE_CRITERIA = {
    "carve_above": True, "carve_fraction": 0.4, "end_day": 31, "end_hour": 16, "end_month": 8, "final_mesh_format": "obj",
    "floor_height": 3.2, "ground_floor_height": 3.0, "max_slope_deg": 60.0, "mode": "irradiance", "north_deg": 20.0,
    "smooth_iters": 2, "start_day": 1, "start_hour": 8, "start_month": 5, "threshold": {"method": "carve_fraction"},
    "voxel_size": 2.0,
}


def test_the_apps_settings_save_reads_back_unchanged(tmp_path, example_project_templates):
    store = ProjectStore(tmp_path, device="cpu")
    example_project_templates.copy_example_project(store, "p", "new_building")
    reply = store.write_config_from_values("p", MIXED_VALUES)
    assert reply.settings == SETTINGS_BEFORE_CRITERIA
    assert reply.grid_plan.voxel_size == 2.0
    assert store.read_settings("p") == SETTINGS_BEFORE_CRITERIA
    assert store.read_settings("p", "1") == SETTINGS_BEFORE_CRITERIA
    stored = _stored(store, "p")
    assert stored["voxel_size"] == 2.0 and stored["epw_path"] == "inputs/weather.epw" and stored["device"] == "cpu"
    assert stored["criteria"][0]["carve_fraction"] == 0.4 and "voxel_size" not in stored["criteria"][0]
    config = store.load_project_config("p")
    assert (config.mode, config.voxel_size, config.carve_fraction) == ("irradiance", 2.0, 0.4)
    assert config.test_surface_path.endswith("test_surfaces_1.ply")
    again = store.write_config_from_values("p", {**store.read_settings("p")})      # the app saves what it read
    assert again.settings == SETTINGS_BEFORE_CRITERIA


def test_criteria_can_be_added_renamed_reordered_bypassed_duplicated_and_deleted(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    second = store.add_criterion("p", "time-based")
    third = store.add_criterion("p", "irradiance", criterion_name="Roofs")
    assert [(c.id, c.name, c.named_by_user) for c in store.criteria("p")] == [
        ("1", "Daylight", False), ("2", "Solar time-based", False), ("3", "Roofs", True)]
    assert (second.colour, third.colour) == CRITERION_COLOURS[1:3]
    assert second.settings["mode"] == "time-based" and second.settings["start_month"] == 12
    assert set(second.settings) <= CRITERION_KEYS - {"name", "id", "test_surface_path"}
    assert _ids_in_config(store, "p") == ["1", "2", "3"]

    renamed = store.update_criterion("p", "2", name="Winter sun")
    assert (renamed.name, renamed.named_by_user) == ("Winter sun", True)
    assert store.update_criterion("p", "1", values={"mode": "irradiance"}).name == "Solar energy"   # unnamed: follows the mode
    assert store.update_criterion("p", "2", values={"mode": "daylight"}).name == "Winter sun"      # named: keeps its name
    store.update_criterion("p", "2", colour="#112233")
    assert store.criteria("p")[1].colour == "#112233"

    store.reorder_criteria("p", ["3", "1", "2"])
    assert [c.id for c in store.criteria("p")] == ["3", "1", "2"] and _ids_in_config(store, "p") == ["3", "1", "2"]
    for wrong in (["1", "2"], ["1", "1", "2"], ["1", "2", "3", "4"], ["1", "2", "9"]):
        with pytest.raises(ProjectError) as caught:
            store.reorder_criteria("p", wrong)
        assert caught.value.status_code == 422

    assert store.update_criterion("p", "1", bypassed=True).bypassed is True
    assert _ids_in_config(store, "p") == ["3", "2"]                      # only the criteria that are on, in order
    assert [c.id for c in store.criteria("p")] == ["3", "1", "2"]        # the bypassed one stays in the list
    store.update_criterion("p", "1", bypassed=False)
    assert _ids_in_config(store, "p") == ["3", "1", "2"]

    joined_folder = store.open("p") / "inputs" / "joined"
    copy = store.duplicate_criterion("p", "3")
    assert (copy.id, copy.name) == ("4", "Roofs copy")
    assert copy.settings == store.criteria("p")[0].settings and copy.settings is not store.criteria("p")[0].settings
    assert [c.id for c in store.criteria("p")] == ["3", "1", "2", "4"]

    (joined_folder / "test_surfaces_2.ply").write_bytes(b"ply")
    (store.open("p") / "run" / "criteria" / "2" / "thresholding").mkdir(parents=True)
    (store.open("p") / "run" / "criteria" / "1").mkdir(parents=True)
    store.delete_criterion("p", "2")
    assert [c.id for c in store.criteria("p")] == ["3", "1", "4"] and _ids_in_config(store, "p") == ["3", "1", "4"]
    assert not (joined_folder / "test_surfaces_2.ply").exists() and not (store.open("p") / "run" / "criteria" / "2").exists()
    assert (store.open("p") / "run" / "criteria" / "1").is_dir()           # another criterion's folder stays
    assert store.add_criterion("p", "daylight").id == "5"                  # an id is never used again
    assert store.read_project_json("p").next_criterion_id == 6
    for unknown in ("2", "nope"):
        for call in (lambda: store.delete_criterion("p", unknown), lambda: store.duplicate_criterion("p", unknown),
                     lambda: store.update_criterion("p", unknown, bypassed=True)):
            with pytest.raises(ProjectError) as caught:
                call()
            assert caught.value.status_code == 404
    load_chain(str(_config_path(store, "p")))                              # the engine reads the result


def test_the_mode_labels_are_the_names_the_app_shows():
    app_names = {tile["engine_name"]: tile["plain_name"] for tile in json.loads(APP_MODE_TILES_PATH.read_text(encoding="utf-8"))}
    assert MODE_LABELS == app_names and set(MODE_LABELS) == set(MODES)


def test_a_default_name_is_the_mode_label_and_the_first_file():
    assert default_criterion_name("benefit", []) == "Solar usefulness"
    assert default_criterion_name("radiative_cooling", ["roof.ply", "b.ply"]) == "Night cooling on roof"
    assert default_criterion_name("no_such_mode", []) == "no_such_mode"      # a mode the engine does not know keeps its name


def test_the_only_criterion_cannot_be_deleted(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    store.add_criterion("p", "time-based")
    store.delete_criterion("p", "1")
    json_before, config_before = (store.open("p") / "project.json").read_bytes(), _config_path(store, "p").read_bytes()
    with pytest.raises(ProjectError, match="^A project needs at least one criterion.$") as caught:
        store.delete_criterion("p", "2")
    assert caught.value.status_code == 422
    assert (store.open("p") / "project.json").read_bytes() == json_before and _config_path(store, "p").read_bytes() == config_before
    store.update_criterion("p", "2", bypassed=True)        # also when it is bypassed: the project still holds it
    with pytest.raises(ProjectError, match="at least one criterion"):
        store.delete_criterion("p", "2")
    assert [c.id for c in store.criteria("p")] == ["2"]


@pytest.mark.parametrize("bad_id", ["..", "../..", "1/2", "a", "", " 1"])
def test_a_criterion_id_is_digits_only(tmp_path, bad_id):
    with pytest.raises(ValidationError):
        CriterionEntry(id=bad_id, name="x", colour="#000000")
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    project_json_path = store.open("p") / "project.json"
    stored = json.loads(project_json_path.read_text(encoding="utf-8"))
    stored["criteria"][0]["id"] = bad_id                     # a hand edit
    project_json_path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(ProjectError) as caught:
        store.read_project_json("p")
    assert caught.value.status_code == 422


def test_deleting_a_criterion_never_removes_a_folder_outside_run_criteria(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    store.add_criterion("p", "daylight")
    project_json = store.read_project_json("p")
    project_json.criteria[1] = project_json.criteria[1].model_copy(update={"id": ".."})   # model_copy does not validate
    monkeypatch.setattr(store, "read_project_json", lambda name: project_json.model_copy(deep=True))
    (store.open("p") / "run" / "criteria").mkdir()
    (store.open("p") / "run" / "kept.txt").write_text("a result", encoding="utf-8")
    json_before = (store.open("p") / "project.json").read_bytes()
    with pytest.raises(ProjectError) as caught:
        store.delete_criterion("p", "..")
    assert caught.value.status_code == 422
    assert (store.open("p") / "run" / "kept.txt").is_file() and (store.open("p") / "project.json").read_bytes() == json_before


def test_mixed_settings_need_a_criterion_when_there_are_several(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    store.add_criterion("p", "time-based")
    json_before, config_before = (store.open("p") / "project.json").read_bytes(), _config_path(store, "p").read_bytes()
    with pytest.raises(ProjectError, match=r"^Say which criterion these settings belong to\.$") as caught:
        store.write_config_from_values("p", {"mode": "daylight", "voxel_size": 2.0})
    assert caught.value.status_code == 422
    assert (store.open("p") / "project.json").read_bytes() == json_before and _config_path(store, "p").read_bytes() == config_before
    store.write_config_from_values("p", {"mode": "time-based", "voxel_size": 2.0, "start_month": 6}, criterion_id="2")
    stored = _stored(store, "p")
    assert stored["voxel_size"] == 2.0                                        # shared: at the top
    assert [criterion["id"] for criterion in stored["criteria"]] == ["1", "2"]
    assert stored["criteria"][1]["start_month"] == 6 and "start_month" not in stored["criteria"][0]
    assert store.read_settings("p", "2")["voxel_size"] == 2.0 and store.read_settings("p", "1")["voxel_size"] == 2.0
    assert store.read_settings("p")["mode"] == "daylight"                      # the default is the first criterion
    assert store.load_project_config("p", "2").start_month == 6
    with pytest.raises(ProjectError) as unknown:
        store.write_config_from_values("p", {"mode": "daylight"}, criterion_id="7")
    assert unknown.value.status_code == 404


def test_an_invalid_criterion_setting_changes_nothing(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    store.add_criterion("p", "time-based")
    project_json_path, config_path = store.open("p") / "project.json", _config_path(store, "p")
    json_before, config_before = project_json_path.read_bytes(), config_path.read_bytes()
    attempts = [
        lambda: store.update_criterion("p", "2", values={"mode": "time-based", "start_month": 13}),
        lambda: store.update_criterion("p", "2", values={"mode": "no-such-mode"}),
        lambda: store.add_criterion("p", "no-such-mode"),
        lambda: store.write_config_from_values("p", {"mode": "time-based", "carve_fraction": -1}, criterion_id="2"),
    ]
    for attempt in attempts:
        with pytest.raises(ConfigError):
            attempt()
        assert project_json_path.read_bytes() == json_before and config_path.read_bytes() == config_before
    with pytest.raises(ProjectError):
        store.update_criterion("p", "2", colour="red")
    with pytest.raises(ProjectError):
        store.update_criterion("p", "2", name="  ")
    assert project_json_path.read_bytes() == json_before and config_path.read_bytes() == config_before


def test_the_config_yaml_says_it_is_written_by_the_app(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    config_path = _config_path(store, "p")
    for change in (lambda: None, lambda: store.add_criterion("p", "time-based"), lambda: store.update_criterion("p", "2", bypassed=True),
                   lambda: store.write_config_from_values("p", {"mode": "daylight", "voxel_size": 3.0}, criterion_id="1"),
                   lambda: store.reorder_criteria("p", ["2", "1"]), lambda: store.delete_criterion("p", "2")):
        change()
        assert config_path.read_text(encoding="utf-8").splitlines()[0] == COMMENT_LINE
        assert load_chain(str(config_path)).criteria        # what `usc validate` reads
    store.add_input("p", "context", "ctx.ply", _box_bytes())      # an upload rewrites the file too
    assert config_path.read_text(encoding="utf-8").splitlines()[0] == COMMENT_LINE
    assert _stored(store, "p")["context_path"] == "inputs/joined/context.ply"


def _box_bytes() -> bytes:
    from local_web_test_support import box_bytes
    return box_bytes([30, 0, 5])


def test_a_criterions_config_equals_the_one_the_engine_builds_from_config_yaml(tmp_path):
    """The service builds each criterion's config from the flat mapping; the engine's loader reads the file: same result."""
    store = ProjectStore(tmp_path, device="cpu")
    store.create("p", "daylight")
    store.write_config_from_values("p", {"mode": "daylight", "voxel_size": 2.0, "north_deg": 10, "carve_fraction": 0.3,
                                         "threshold": "carve_fraction"})
    store.add_criterion("p", "time-based")
    store.update_criterion("p", "2", values={"mode": "time-based", "start_month": 6, "end_month": 7})
    store.add_criterion("p", "irradiance")
    store.update_criterion("p", "3", bypassed=True)
    store.add_input("p", "context", "ctx.ply", _box_bytes())
    chain = load_chain(str(_config_path(store, "p")))
    assert [criterion.id for criterion in chain.criteria] == ["1", "2"]
    for criterion in chain.criteria:
        assert store.load_project_config("p", criterion.id).model_dump() == criterion.config.model_dump()
    assert chain.criteria[1].config.start_month == 6 and chain.criteria[0].config.voxel_size == 2.0


def test_a_chain_with_every_criterion_bypassed_is_still_written(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    store.update_criterion("p", "1", bypassed=True)
    assert _stored(store, "p")["criteria"] == []
    with pytest.raises(ConfigError, match="criteria"):      # the engine wants a criterion: a run must say so in plain words (Task 5)
        load_chain(str(_config_path(store, "p")))
    assert store.read_settings("p")["mode"] == "daylight"        # a bypassed criterion keeps its settings
    store.update_criterion("p", "1", bypassed=False)
    assert _ids_in_config(store, "p") == ["1"]


def test_a_flat_config_yaml_from_an_earlier_version_reads_as_one_criterion(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    flat = {"max_volume_path": "inputs/joined/max_volume.ply", "test_surface_path": "inputs/joined/test_surfaces.ply",
            "out_dir": "run", "mode": "daylight", "voxel_size": 2.0, "device": "cpu"}
    _config_path(store, "p").write_text(yaml.safe_dump(flat), encoding="utf-8")
    assert store.read_settings("p") == {"mode": "daylight", "voxel_size": 2.0}
    assert store.read_stored_config("p") == flat
    assert store.load_project_config("p").voxel_size == 2.0


def test_split_settings_keeps_shared_and_criterion_keys_apart_and_never_takes_a_name_or_id():
    shared, criterion = split_settings({"voxel_size": 2.0, "mode": "daylight", "carve_fraction": 0.3, "north_deg": 5,
                                        "name": "typed in the browser", "id": "9"})
    assert shared == {"voxel_size": 2.0, "north_deg": 5} and criterion == {"mode": "daylight", "carve_fraction": 0.3}


def test_chain_config_document_lists_the_criteria_that_are_on(tmp_path):
    entries = [
        CriterionEntry(id="1", name="A", colour="#7F77DD", settings={"mode": "daylight"}),
        CriterionEntry(id="2", name="B", colour="#D85A30", bypassed=True, settings={"mode": "time-based"}),
        CriterionEntry(id="3", name="C", colour="#1D9E75", settings={"mode": "time-based", "start_month": 6}),
    ]
    document = chain_config_document({"voxel_size": 2.0, "device": "cpu"}, entries, tmp_path)
    assert document["voxel_size"] == 2.0 and document["device"] == "cpu" and document["out_dir"] == "run"
    assert document["max_volume_path"] == "inputs/joined/max_volume.ply" and document["epw_path"] == "inputs/weather.epw"
    assert document["criteria"] == [
        {"id": "1", "name": "A", "mode": "daylight", "test_surface_path": "inputs/joined/test_surfaces_1.ply"},
        {"id": "3", "name": "C", "mode": "time-based", "start_month": 6, "test_surface_path": "inputs/joined/test_surfaces_3.ply"},
    ]
    daylight_only = chain_config_document({}, entries[:1], tmp_path)
    assert "epw_path" not in daylight_only and "context_path" not in daylight_only
    (tmp_path / "inputs" / "joined").mkdir(parents=True)
    (tmp_path / "inputs" / "joined" / "terrain.ply").write_bytes(b"ply")
    assert chain_config_document({}, entries[:1], tmp_path)["terrain_path"] == "inputs/joined/terrain.ply"


# ---- Shared settings on their own ----

def _chain_of_two_with_a_max_volume(tmp_path):
    store = ProjectStore(tmp_path, device="cpu")
    store.create("p", "daylight")
    store.add_input("p", "max_volume", "volume.ply", _box_bytes())
    store.add_criterion("p", "time-based")
    return store


def test_shared_settings_save_without_a_mode(tmp_path):
    store = _chain_of_two_with_a_max_volume(tmp_path)
    criteria_before = [entry.model_dump() for entry in store.criteria("p")]
    reply = store.write_shared_settings("p", {"voxel_size": 2.0, "north_deg": 15})
    assert reply.settings["voxel_size"] == 2.0 and reply.settings["north_deg"] == 15.0 and "mode" not in reply.settings
    assert reply.grid_plan is not None and reply.grid_plan.voxel_size == 2.0
    assert [entry.model_dump() for entry in store.criteria("p")] == criteria_before     # every criterion's settings are as they were
    stored = _stored(store, "p")
    assert stored["voxel_size"] == 2.0 and stored["north_deg"] == 15.0 and stored["device"] == "cpu"
    assert [criterion["id"] for criterion in stored["criteria"]] == ["1", "2"]
    for criterion_id in ("1", "2"):
        assert store.read_settings("p", criterion_id)["voxel_size"] == 2.0
        assert store.load_project_config("p", criterion_id).north_deg == 15.0
    load_chain(str(_config_path(store, "p")))
    # a later save keeps the shared settings it does not send again
    again = store.write_shared_settings("p", {"voxel_size": 3.0})
    assert again.settings["voxel_size"] == 3.0 and again.settings["north_deg"] == 15.0
    # the paths and the device are the service's, whatever is sent
    store.write_shared_settings("p", {"voxel_size": 3.0, "out_dir": "elsewhere", "device": "cuda", "epw_path": "x.epw",
                                      "grid_step": 0.5, "score_rule": "summed"})
    stored = _stored(store, "p")
    assert stored["out_dir"] == "run" and stored["device"] == "cpu" and stored["epw_path"] == "inputs/weather.epw"
    assert "grid_step" not in stored and "score_rule" not in stored


def test_shared_settings_are_stored_and_returned_as_the_engine_reads_them(tmp_path):
    store = _chain_of_two_with_a_max_volume(tmp_path)
    reply = store.write_shared_settings("p", {"voxel_size": "2", "context_blocks_rays": "yes"})
    assert reply.settings["voxel_size"] == 2.0 and reply.settings["context_blocks_rays"] is True
    assert isinstance(reply.settings["voxel_size"], float)
    stored = _stored(store, "p")
    assert stored["voxel_size"] == 2.0 and isinstance(stored["voxel_size"], float) and stored["context_blocks_rays"] is True
    assert store.read_settings("p")["voxel_size"] == 2.0 and store.read_settings("p")["context_blocks_rays"] is True


def test_shared_settings_save_before_a_max_volume_has_no_grid_plan(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    assert store.write_shared_settings("p", {"voxel_size": 2.0}).grid_plan is None
    assert store.read_settings("p")["voxel_size"] == 2.0


def test_shared_settings_refuse_criterion_keys(tmp_path):
    store = _chain_of_two_with_a_max_volume(tmp_path)
    project_json_path, config_path = store.open("p") / "project.json", _config_path(store, "p")
    json_before, config_before = project_json_path.read_bytes(), config_path.read_bytes()
    with pytest.raises(ConfigError) as refused:
        store.write_shared_settings("p", {"voxel_size": 2.0, "threshold": "carve_fraction", "mode": "daylight"})
    assert [error.field for error in refused.value.errors] == ["mode", "threshold"]
    assert "threshold" in str(refused.value) and "criterion" in str(refused.value)
    assert project_json_path.read_bytes() == json_before and config_path.read_bytes() == config_before


def test_a_shared_setting_that_breaks_a_criterion_is_refused(tmp_path, monkeypatch):
    store = _chain_of_two_with_a_max_volume(tmp_path)
    project_json_path, config_path = store.open("p") / "project.json", _config_path(store, "p")
    json_before, config_before = project_json_path.read_bytes(), config_path.read_bytes()
    with pytest.raises(ConfigError) as refused:
        store.write_shared_settings("p", {"voxel_size": 0.0})
    assert [error.field for error in refused.value.errors] == ["voxel_size"]
    assert project_json_path.read_bytes() == json_before and config_path.read_bytes() == config_before
    # every criterion that is on is checked, not only the first: a config that fails for the second one alone refuses the save
    # (monkeypatched, since no real shared value breaks only one criterion)
    original = ProjectStore._config_from_browser_values

    def fails_for_the_second(self, project_folder, values, criterion_id):
        if criterion_id == "2":
            raise ConfigError("criterion 2 does not accept this")
        return original(self, project_folder, values, criterion_id)
    monkeypatch.setattr(ProjectStore, "_config_from_browser_values", fails_for_the_second)
    with pytest.raises(ConfigError, match="criterion 2"):
        store.write_shared_settings("p", {"voxel_size": 2.0})
    assert project_json_path.read_bytes() == json_before and config_path.read_bytes() == config_before
    # a bypassed criterion takes no part in the check
    monkeypatch.undo()
    store.update_criterion("p", "2", bypassed=True)
    monkeypatch.setattr(ProjectStore, "_config_from_browser_values", fails_for_the_second)
    assert store.write_shared_settings("p", {"voxel_size": 2.0}).settings["voxel_size"] == 2.0


def test_a_shared_setting_over_the_grid_budget_is_refused_with_the_plan(tmp_path):
    from urbansolarcarver.local_web_service.projects import GridOverBudget
    store = _chain_of_two_with_a_max_volume(tmp_path)
    config_before = _config_path(store, "p").read_bytes()
    with pytest.raises(GridOverBudget) as refused:
        store.write_shared_settings("p", {"voxel_size": 0.0125})
    assert refused.value.grid_plan.total_voxels > refused.value.grid_plan.budget_voxels
    assert _config_path(store, "p").read_bytes() == config_before


def test_a_rejected_criterion_change_names_the_criterion(tmp_path):
    from urbansolarcarver.local_web_service.projects import CriterionConfigError
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    store.add_criterion("p", "time-based")
    for attempt in (lambda: store.update_criterion("p", "2", values={"mode": "time-based", "start_month": 13}),
                    lambda: store.update_criterion("p", "2", values={"mode": "no-such-mode"})):
        with pytest.raises(CriterionConfigError) as refused:
            attempt()
        assert refused.value.criterion == "2" and refused.value.errors
        assert isinstance(refused.value, ConfigError)
