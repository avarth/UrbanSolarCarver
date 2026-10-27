"""Studies of the Simulate workspace in project.json, apart from the criteria (local web service)."""
import json

import pytest
import send2trash

from local_web_test_support import GOLDEN_EPW, FakeRecycleBin
from test_local_web_server import client, client_with_blocking_run, client_with_inputs, projects_folder     # noqa: F401  (fixtures)
from urbansolarcarver.local_web_service.criteria import CRITERION_COLOURS
from urbansolarcarver.local_web_service.projects import ProjectError, ProjectStore
from urbansolarcarver.local_web_service.studies import (
    STUDY_SETTING_KEYS, default_study_name, study_from_criterion,
)

PERIOD_21_DEC = {"start_month": 12, "start_day": 21, "start_hour": 10, "end_month": 12, "end_day": 21, "end_hour": 14}


def _with_weather(project):
    store, name = project
    store.add_input(name, "weather", "golden.epw", GOLDEN_EPW.read_bytes())
    return store, name


def test_a_project_without_studies_reads_and_lists_none(project_with_inputs):
    store, name = project_with_inputs
    project_json_path = store.open(name) / "project.json"
    stored = json.loads(project_json_path.read_text(encoding="utf-8"))
    stored.pop("studies", None)
    stored.pop("next_study_id", None)
    project_json_path.write_text(json.dumps(stored), encoding="utf-8")      # as an earlier version wrote it
    assert store.studies(name) == []
    assert store.read_project_json(name).next_study_id == 1


def test_add_a_study_from_a_metric_takes_its_defaults_and_name(project_with_inputs):
    store, name = _with_weather(project_with_inputs)
    study = store.add_study(name, metric="sun_hours")
    assert (study.id, study.name, study.named_by_user, study.colour) == ("1", "Sun hours, 21 Dec", False, CRITERION_COLOURS[0])
    assert study.metric == "sun_hours" and study.test_surface_files == [] and study.target is None
    assert study.settings == PERIOD_21_DEC
    assert store.studies(name) == [study]
    benefit = store.add_study(name, metric="useful_solar_energy")
    assert benefit.id == "2" and benefit.colour == CRITERION_COLOURS[1]
    assert benefit.name == "Useful solar energy, 15 Oct to 15 Apr"
    assert benefit.settings["balance_temperature"] == 15.0 and benefit.settings["include_harm"] is False
    assert benefit.settings["start_month"] == 10 and benefit.settings["end_month"] == 4
    sky = store.add_study(name, metric="sky_component")
    assert (sky.name, sky.settings) == ("Overcast sky component", {})
    cooling = store.add_study(name, metric="cooling_sky")
    assert cooling.settings == {"dew_point_celsius": 14.0, "bliss_k": 1.8}


def test_the_default_name_is_the_label_and_the_period_the_metric_needs():
    assert default_study_name("sun_hours", PERIOD_21_DEC) == "Sun hours, 21 Dec"
    assert default_study_name("solar_energy", {**PERIOD_21_DEC, "start_month": 9, "start_day": 1, "end_month": 5, "end_day": 31}) == \
        "Solar energy, 1 Sep to 31 May"
    assert default_study_name("sky_view", {}) == "Sky view factor"
    assert default_study_name("sky_view", PERIOD_21_DEC) == "Sky view factor"      # a period the metric does not use is not named
    assert default_study_name("sun_hours", {}) == "Sun hours"       # no period to name


def test_an_unknown_metric_is_refused(project_with_inputs):
    store, name = project_with_inputs
    with pytest.raises(ProjectError) as refused:
        store.add_study(name, metric="shininess")
    assert refused.value.status_code == 422 and store.studies(name) == []


def test_add_a_study_like_a_criterion_copies_metric_period_settings_and_files(project_with_inputs):
    store, name = _with_weather(project_with_inputs)
    criterion = store.add_criterion(name, "benefit", "Winter sun on facades")
    store.use_test_surface(name, criterion.id, "surface.ply")
    store.update_criterion(name, criterion.id, values={"balance_temperature": 17.5, "start_month": 11, "end_month": 3})
    criterion = store.criteria(name)[1]
    study = store.add_study(name, from_criterion=criterion.id)
    assert study.metric == "useful_solar_energy" and study.test_surface_files == ["surface.ply"]
    assert study.settings["balance_temperature"] == 17.5 and study.settings["start_month"] == 11 and study.settings["end_month"] == 3
    assert study.settings["start_day"] == criterion.settings["start_day"]
    assert study.name == "Useful solar energy, 15 Nov to 15 Mar" and not study.named_by_user
    assert store.criteria(name)[1] == criterion      # no link is kept, and the criterion is as it was
    study.test_surface_files.append("elsewhere.ply")
    assert store.criteria(name)[1].test_surface_files == ["surface.ply"]
    like_the_first = store.add_study(name, from_criterion="1")      # daylight: the sky component, no period
    assert like_the_first.metric == "sky_component" and like_the_first.settings == {} and like_the_first.test_surface_files == ["surface.ply"]
    with pytest.raises(ProjectError) as unknown:
        store.add_study(name, from_criterion="9")
    assert unknown.value.status_code == 404


def test_study_from_criterion_takes_only_the_keys_the_metric_reads(project_with_inputs):
    store, name = project_with_inputs
    entry = store.criteria(name)[0]
    entry.settings = {**entry.settings, "mode": "time-based", "start_month": 6, "include_harm": True, "threshold": "carve_fraction"}
    metric, settings, files = study_from_criterion(entry)
    assert metric == "sun_hours" and files == entry.test_surface_files == ["surface.ply"]
    assert settings["start_month"] == 6 and "include_harm" not in settings and "threshold" not in settings
    assert set(settings) <= set(STUDY_SETTING_KEYS)


def test_ids_are_never_reused_after_a_delete(project_with_inputs):
    store, name = project_with_inputs
    first, second = store.add_study(name, metric="sky_view"), store.add_study(name, metric="sky_view")
    store.delete_study(name, second.id)
    third = store.add_study(name, metric="sky_view")
    assert [first.id, second.id, third.id] == ["1", "2", "3"]
    assert [study.id for study in store.studies(name)] == ["1", "3"]
    assert third.colour == CRITERION_COLOURS[2]


def test_changing_metric_or_period_renames_a_study_the_user_did_not_name(project_with_inputs):
    store, name = _with_weather(project_with_inputs)
    study = store.add_study(name, metric="sun_hours")
    changed = store.update_study(name, study.id, values={"start_month": 9, "start_day": 1, "end_month": 5, "end_day": 31})
    assert changed.name == "Sun hours, 1 Sep to 31 May" and not changed.named_by_user
    changed = store.update_study(name, study.id, metric="solar_energy")
    assert changed.name == "Solar energy, 1 Sep to 31 May"      # the period is kept where the keys match
    assert changed.settings["start_month"] == 9 and changed.settings["end_hour"] == 14
    changed = store.update_study(name, study.id, metric="cooling_sky")
    assert changed.name == "Cooling sky" and changed.settings == {"dew_point_celsius": 14.0, "bliss_k": 1.8}
    named = store.update_study(name, study.id, name="  My facade  ")
    assert (named.name, named.named_by_user) == ("My facade", True)
    kept = store.update_study(name, study.id, metric="sun_hours")
    assert kept.name == "My facade" and kept.settings == PERIOD_21_DEC     # reset to the new metric's defaults
    assert store.studies(name) == [kept]


def test_a_study_is_changed_by_its_target_and_its_settings(project_with_inputs):
    store, name = _with_weather(project_with_inputs)
    study = store.add_study(name, metric="useful_solar_energy")
    changed = store.update_study(name, study.id, target=120.5, values={"balance_temperature": 18})
    assert changed.target == 120.5 and changed.settings["balance_temperature"] == 18.0
    assert store.update_study(name, study.id, name="Renamed").target == 120.5       # not sent: stays
    assert store.update_study(name, study.id, target=None).target is None           # null: none
    for bad in ({"threshold": 1}, {"dew_point_celsius": 10}, {"start_month": 13}, {"balance_offset": -1}):
        before = store.studies(name)
        with pytest.raises(ProjectError) as refused:
            store.update_study(name, study.id, values=bad)
        assert refused.value.status_code == 422 and store.studies(name) == before
    with pytest.raises(ProjectError) as empty:
        store.update_study(name, study.id, name="   ")
    assert empty.value.status_code == 422
    with pytest.raises(ProjectError) as unknown:
        store.update_study(name, "9", name="x")
    assert unknown.value.status_code == 404
    with pytest.raises(ProjectError) as metric:
        store.update_study(name, study.id, metric="shininess")
    assert metric.value.status_code == 422


def test_studies_are_reordered_by_their_ids(project_with_inputs):
    store, name = project_with_inputs
    ids = [store.add_study(name, metric="sky_view").id for _ in range(3)]
    store.reorder_studies(name, ids[::-1])
    assert [study.id for study in store.studies(name)] == ["3", "2", "1"]
    for bad in (["1", "2"], ["1", "2", "2"], ["1", "2", "4"]):
        with pytest.raises(ProjectError) as refused:
            store.reorder_studies(name, bad)
        assert refused.value.status_code == 422
    assert [study.id for study in store.studies(name)] == ["3", "2", "1"]


def test_a_study_change_leaves_inputs_revision_stage_records_and_criteria_alone(project_with_inputs):
    store, name = _with_weather(project_with_inputs)
    store.add_criterion(name, "time-based")
    config_path = store.open(name) / "config.yaml"

    def untouched():
        project_json = store.read_project_json(name)
        return (project_json.model_dump(include={"criteria", "criterion_records", "stage_records", "inputs_revision", "next_criterion_id",
                                                 "input_files", "carving_chain"}), config_path.read_bytes())

    before = untouched()
    study = store.add_study(name, metric="sun_hours")
    assert untouched() == before
    store.add_study(name, from_criterion="2")
    assert untouched() == before
    store.update_study(name, study.id, metric="solar_energy", name="Mine", target=3, values={"start_month": 2})
    assert untouched() == before
    store.reorder_studies(name, ["2", "1"])
    assert untouched() == before
    store.delete_study(name, study.id)
    assert untouched() == before


def test_deleting_a_study_moves_its_results_folder_to_the_recycle_bin(project_with_inputs, monkeypatch):
    store, name = project_with_inputs
    study = store.add_study(name, metric="sky_view")
    kept = store.add_study(name, metric="sky_view")
    for study_id in (study.id, kept.id):
        results = store.open(name) / "simulate" / study_id
        results.mkdir(parents=True)
        (results / "values.bin").write_bytes(b"1")
    bin_stub = FakeRecycleBin()
    monkeypatch.setattr(send2trash, "send2trash", bin_stub)
    store.delete_study(name, study.id)
    assert bin_stub.folders == [(store.open(name) / "simulate" / study.id)]
    assert not (store.open(name) / "simulate" / study.id).exists() and (store.open(name) / "simulate" / kept.id / "values.bin").is_file()
    assert [other.id for other in store.studies(name)] == [kept.id]
    store.delete_study(name, kept.id)
    with pytest.raises(ProjectError) as gone:
        store.delete_study(name, kept.id)
    assert gone.value.status_code == 404


def test_a_study_whose_folder_cannot_be_recycled_is_still_removed_from_the_list(project_with_inputs, monkeypatch):
    store, name = project_with_inputs
    study = store.add_study(name, metric="sky_view")
    (store.open(name) / "simulate" / study.id).mkdir(parents=True)
    monkeypatch.setattr(send2trash, "send2trash", FakeRecycleBin(error=OSError("no bin")))
    store.delete_study(name, study.id)
    assert store.studies(name) == []


def test_the_study_folder_is_simulate_slash_id(tmp_path):
    from urbansolarcarver.local_web_service.studies import study_folder
    assert study_folder(tmp_path, "7") == tmp_path / "simulate" / "7"


# ---- Routes ----

def test_study_routes(client_with_inputs):
    client = client_with_inputs
    listed = client.get("/api/projects/p/studies")
    assert listed.status_code == 200 and listed.json()["studies"] == []
    metrics = {metric["name"]: metric for metric in listed.json()["metrics"]}
    assert set(metrics) == {"sun_hours", "solar_energy", "useful_solar_energy", "sky_component", "cooling_sky", "sky_view"}
    assert metrics["sun_hours"]["available"] is False and metrics["sun_hours"]["needs_epw"] is True      # no weather file yet
    assert metrics["sky_component"]["available"] is True
    assert metrics["sun_hours"]["default_settings"] == PERIOD_21_DEC and metrics["sky_view"]["default_settings"] == {}
    assert {"label", "unit"} <= set(metrics["sun_hours"])
    upload = client.post("/api/projects/p/inputs/weather", files={"file": ("golden.epw", GOLDEN_EPW.read_bytes(), "application/octet-stream")})
    assert upload.status_code == 200
    assert {m["name"]: m["available"] for m in client.get("/api/projects/p/studies").json()["metrics"]}["sun_hours"] is True

    added = client.post("/api/projects/p/studies", json={"metric": "sun_hours"})
    assert added.status_code == 200 and added.json()["id"] == "1" and added.json()["name"] == "Sun hours, 21 Dec"
    like = client.post("/api/projects/p/studies", json={"from_criterion": "1"})
    assert like.status_code == 200 and like.json()["metric"] == "sky_component" and like.json()["test_surface_files"] == ["surface.ply"]
    assert [study["id"] for study in client.get("/api/projects/p/studies").json()["studies"]] == ["1", "2"]

    assert client.post("/api/projects/p/studies", json={}).status_code == 422
    assert client.post("/api/projects/p/studies", json={"metric": "sun_hours", "from_criterion": "1"}).status_code == 422
    assert client.post("/api/projects/p/studies", json={"metric": "shininess"}).status_code == 422
    assert client.post("/api/projects/p/studies", json={"from_criterion": "9"}).status_code == 404

    patched = client.patch("/api/projects/p/studies/1", json={"name": "Dec sun", "target": 2.5, "values": {"end_hour": 15}})
    assert patched.status_code == 200
    assert (patched.json()["name"], patched.json()["target"], patched.json()["settings"]["end_hour"]) == ("Dec sun", 2.5, 15)
    assert client.patch("/api/projects/p/studies/1", json={"target": None}).json()["target"] is None
    assert client.patch("/api/projects/p/studies/1", json={"values": {"start_month": 13}}).status_code == 422
    assert client.patch("/api/projects/p/studies/9", json={"name": "x"}).status_code == 404

    assert client.put("/api/projects/p/studies/order", json={"ids": ["2", "1"]}).status_code == 200
    assert [study["id"] for study in client.get("/api/projects/p/studies").json()["studies"]] == ["2", "1"]
    assert client.put("/api/projects/p/studies/order", json={"ids": ["2"]}).status_code == 422

    assert client.delete("/api/projects/p/studies/1").status_code == 204
    assert client.delete("/api/projects/p/studies/1").status_code == 404
    assert [study["id"] for study in client.get("/api/projects/p/studies").json()["studies"]] == ["2"]
    assert client.get("/api/projects/nope/studies").status_code == 404


def test_study_changes_are_refused_while_a_run_is_active(client_with_blocking_run):
    client, _run_id = client_with_blocking_run
    assert client.post("/api/projects/p/studies", json={"metric": "sky_view"}).status_code == 409
    assert client.get("/api/projects/p/studies").status_code == 200
