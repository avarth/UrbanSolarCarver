"""Projects of an earlier version of the local web service open as a chain of one criterion, their results still current.

The earlier projects are written by write_earlier_version_project (local_web_test_support.py): project.json without criteria,
a config.yaml of one criterion and the single-criterion run layout (run/preprocessing, run/thresholding, ...).
"""
import json
import logging
import os
import warnings
from pathlib import Path

import pytest
import yaml

with warnings.catch_warnings():     # newer Starlette versions announce that TestClient will need httpx2; the project pins httpx
    warnings.filterwarnings("ignore", message=".*httpx.*testclient|.*testclient.*httpx", category=Warning)
    from starlette.testclient import TestClient

from local_web_test_support import (
    ALL_CURRENT, EARLIER_JOINED_TEST_SURFACES, add_project_with_inputs, make_worker, write_earlier_version_project,
)
from urbansolarcarver.api_core._stage_io import load_upstream
from urbansolarcarver.chain_config import CRITERION_KEYS, load_chain
from urbansolarcarver.local_web_service import create_app, test_surfaces
from urbansolarcarver.local_web_service.criteria import CRITERION_COLOURS
from urbansolarcarver.local_web_service.projects import ProjectStore
from urbansolarcarver.local_web_service.stage_records import criterion_status, stage_status
from urbansolarcarver.stage_settings import PIPELINE_STAGES

TOKEN = "a" * 64
PORT = 8770
UPSTREAM_STAGE = {"thresholding": "preprocessing", "exporting": "thresholding", "massing": "thresholding"}


@pytest.fixture
def store(tmp_path):
    return ProjectStore(tmp_path / "projects")


def _snapshot(folder: Path) -> tuple[dict[str, bytes], set[str]]:
    """Every file of a folder (relative path -> bytes) and every sub folder."""
    files = {path.relative_to(folder).as_posix(): path.read_bytes() for path in folder.rglob("*") if path.is_file()}
    folders = {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_dir()}
    return files, folders


def _manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolved_upstream(manifest_path: Path) -> Path:
    """The manifest that a manifest names as its upstream, resolved as the engine's load_upstream resolves it."""
    stored = Path(_manifest(manifest_path)["upstream_manifest"])
    return stored if stored.is_absolute() else Path(os.path.normpath(manifest_path.parent / stored))


def _earlier_version_stage_status(store: ProjectStore, name: str) -> dict[str, str]:
    """The state of each stage as the earlier version told it: current when its record matches its manifest, the inputs revision
    and the stored config.yaml, and its manifest read the run its upstream stage's record describes."""
    project_json = store.read_project_json(name)
    run = store.open(name) / "run"
    states = {}
    for stage in PIPELINE_STAGES:
        record = project_json.stage_records.get(stage)
        manifest_path = run / stage / "manifest.json"
        if record is None or not manifest_path.is_file():
            states[stage] = "missing"
            continue
        manifest = _manifest(manifest_path)
        upstream = project_json.stage_records.get(UPSTREAM_STAGE.get(stage, ""))
        current = (record.manifest_run_id == manifest["run_id"] and record.inputs_revision == project_json.inputs_revision
                   and record.config == store.read_stored_config(name)
                   and (stage == "preprocessing" or (upstream is not None and manifest["upstream_run_id"] == upstream.manifest_run_id)))
        states[stage] = "current" if current else "out_of_date"
    return states


def _client(projects_folder: Path) -> TestClient:
    app = create_app(projects_folder, TOKEN, PORT, worker=make_worker(ProjectStore(projects_folder)))
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", headers={"X-USC-Token": TOKEN})


def test_an_earlier_project_keeps_its_results_current(store):
    write_earlier_version_project(store, "p")
    assert _earlier_version_stage_status(store, "p") == ALL_CURRENT
    assert store.migrate_to_criteria("p") is True
    assert stage_status(store, "p") == ALL_CURRENT
    assert criterion_status(store, "p") == {"1": {"preprocessing": "current", "thresholding": "current"}}
    run = store.open("p") / "run"
    for stage in ("exporting", "massing"):
        assert _resolved_upstream(run / stage / "manifest.json") == run / "criteria" / "1" / "thresholding" / "manifest.json"
    assert [_manifest(run / "criteria" / "1" / stage / "manifest.json")["run_id"] for stage in ("preprocessing", "thresholding")] \
        == ["pre-run", "thr-run"]
    assert _manifest(run / "criteria" / "chain.json") == {
        "criteria": [{"id": "1", "name": "daylight", "mode": "daylight", "thresholding_run_id": "thr-run"}]}
    assert make_worker(store).start("p", ["exporting", "massing"]).status == "up_to_date"


def test_its_test_surfaces_belong_to_criterion_1(store):
    write_earlier_version_project(store, "p")
    project_folder = store.open("p")
    joined_before = (project_folder / EARLIER_JOINED_TEST_SURFACES).read_bytes()
    stored_config = yaml.safe_load((project_folder / "config.yaml").read_text(encoding="utf-8"))
    settings_before = store.read_settings("p")
    store.migrate_to_criteria("p")
    [criterion] = store.criteria("p")
    assert (criterion.id, criterion.name, criterion.colour, criterion.test_surface_files) == ("1", "daylight", CRITERION_COLOURS[0], ["surface.ply"])
    assert criterion.settings == {key: value for key, value in stored_config.items() if key in CRITERION_KEYS and key != "test_surface_path"}
    assert store.read_project_json("p").next_criterion_id == 2
    assert test_surfaces.joined_path(project_folder, "1").read_bytes() == joined_before
    assert not (project_folder / EARLIER_JOINED_TEST_SURFACES).exists()
    records = store.read_project_json("p").criterion_records["1"]
    assert {record.test_surfaces_fingerprint for record in records.values()} == {test_surfaces.fingerprint(project_folder, "1")}
    assert [criterion.id for criterion in load_chain(project_folder / "config.yaml").criteria] == ["1"]
    assert store.read_settings("p") == settings_before


def test_a_project_carved_further_opens_as_a_chain_of_one(store):
    write_earlier_version_project(store, "p", carved_further=True)
    project_folder = store.open("p")
    carving_chain = store.read_project_json("p").carving_chain
    earlier_files = _snapshot(project_folder / "inputs" / "earlier_max_volumes")
    max_volume_files = _snapshot(project_folder / "inputs" / "max_volume")
    store.migrate_to_criteria("p")
    assert store.read_project_json("p").carving_chain == carving_chain
    assert _snapshot(project_folder / "inputs" / "earlier_max_volumes") == earlier_files
    assert _snapshot(project_folder / "inputs" / "max_volume") == max_volume_files
    assert [criterion.id for criterion in store.criteria("p")] == ["1"]
    assert stage_status(store, "p") == ALL_CURRENT


def test_migration_runs_once(store):
    write_earlier_version_project(store, "p")
    assert store.migrate_to_criteria("p") is True
    after_first = _snapshot(store.open("p"))
    assert store.migrate_to_criteria("p") is False
    assert _snapshot(store.open("p")) == after_first


def test_a_project_in_the_chain_layout_is_left_as_it_is(tmp_path):
    store, name = add_project_with_inputs(tmp_path)
    before = _snapshot(store.open(name))
    assert store.migrate_to_criteria(name) is False
    assert _snapshot(store.open(name)) == before


def test_opening_a_project_migrates_it(store):
    write_earlier_version_project(store, "p")
    reply = _client(store.projects_folder).get("/api/projects/p")
    assert reply.status_code == 200, reply.text
    assert reply.json()["stage_status"]["stages"] == ALL_CURRENT
    assert [criterion.id for criterion in store.criteria("p")] == ["1"]
    assert (store.open("p") / "run" / "criteria" / "1" / "thresholding" / "manifest.json").is_file()


@pytest.mark.parametrize("stored_as", ["relative", "absolute"])
def test_the_moved_manifests_name_the_moved_runs_as_the_engine_reads_them(store, stored_as):
    write_earlier_version_project(store, "p")
    run = store.open("p") / "run"
    if stored_as == "absolute":     # the form a manifest has when no relative path exists (another drive on Windows)
        for stage, upstream in UPSTREAM_STAGE.items():
            manifest = _manifest(run / stage / "manifest.json")
            manifest["upstream_manifest"] = (run / upstream / "manifest.json").as_posix()
            (run / stage / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    store.migrate_to_criteria("p")
    criterion_folder = run / "criteria" / "1"
    assert _resolved_upstream(criterion_folder / "thresholding" / "manifest.json") == criterion_folder / "preprocessing" / "manifest.json"
    for stage in ("exporting", "massing"):
        assert _manifest(run / stage / "manifest.json")["upstream_manifest"] == "../criteria/1/thresholding/manifest.json"
    assert _manifest(criterion_folder / "thresholding" / "manifest.json")["upstream_manifest"] == "../preprocessing/manifest.json"
    load_upstream(run / "exporting", "exporting")       # raises StageChainError when a link is broken
    load_upstream(run / "massing", "massing")
    assert [_manifest(run / stage / "manifest.json")["run_id"] for stage in ("exporting", "massing")] == ["exp-run", "mas-run"]


@pytest.mark.parametrize("failing", ["project_json", "config", "manifest"])
def test_a_migration_that_fails_leaves_the_project_as_it_was(store, monkeypatch, failing):
    write_earlier_version_project(store, "p")
    before = _snapshot(store.open("p"))

    def fail(*_arguments, **_keywords):
        raise OSError("the disk is full")
    if failing == "project_json":
        monkeypatch.setattr(store, "write_project_json", fail)
    elif failing == "config":
        monkeypatch.setattr(store, "_write_bytes_atomically", fail)
    else:
        monkeypatch.setattr("urbansolarcarver.local_web_service.migration._write_manifest", fail)
    with pytest.raises(OSError):
        store.migrate_to_criteria("p")
    assert _snapshot(store.open("p")) == before


def test_a_project_that_fails_to_migrate_still_opens_as_it_was(store, monkeypatch, caplog):
    write_earlier_version_project(store, "p")
    before = _snapshot(store.open("p"))

    def fail(*_arguments, **_keywords):
        raise OSError("the disk is full")
    monkeypatch.setattr("urbansolarcarver.local_web_service.migration._write_manifest", fail)
    with caplog.at_level(logging.ERROR):
        reply = _client(store.projects_folder).get("/api/projects/p")
    assert reply.status_code == 200, reply.text
    assert _snapshot(store.open("p")) == before
    assert "the disk is full" in caplog.text


def test_saving_the_settings_of_an_earlier_project_migrates_it_first(store):
    write_earlier_version_project(store, "p")
    store.write_config_from_values("p", store.read_settings("p"))
    [criterion] = store.criteria("p")
    assert criterion.test_surface_files == ["surface.ply"]
    assert (store.open("p") / "run" / "criteria" / "1" / "preprocessing" / "manifest.json").is_file()
    assert stage_status(store, "p") == ALL_CURRENT
    store.remove_input("p", "test_surfaces", "surface.ply")
    assert store.input_files("p", "test_surfaces") == []
    assert not (store.open("p") / "inputs" / "test_surfaces" / "surface.ply").exists()


@pytest.mark.parametrize("stages", [(), ("preprocessing",)])
def test_a_project_without_a_run_or_with_preprocessing_only_migrates(store, stages):
    write_earlier_version_project(store, "p", stages=stages)
    assert store.migrate_to_criteria("p") is True
    run = store.open("p") / "run"
    assert (run / "criteria" / "1" / "preprocessing").is_dir() == ("preprocessing" in stages)
    assert not (run / "preprocessing").exists() and not (run / "criteria" / "1" / "thresholding").exists()
    assert not (run / "criteria" / "chain.json").exists()
    expected = "current" if stages else "missing"
    assert criterion_status(store, "p") == {"1": {"preprocessing": expected, "thresholding": "missing"}}


def test_a_config_file_with_a_yaml_error_stays_for_the_next_save(store):
    write_earlier_version_project(store, "p")
    config_path = store.open("p") / "config.yaml"
    config_path.write_text("mode: [daylight\n", encoding="utf-8")
    assert store.migrate_to_criteria("p") is True
    assert config_path.read_text(encoding="utf-8") == "mode: [daylight\n"
    assert store.criteria("p")[0].test_surface_files == ["surface.ply"]
    store.write_config_from_values("p", {"mode": "daylight"})
    assert [criterion.id for criterion in load_chain(config_path).criteria] == ["1"]


def test_a_missing_joined_file_is_built_from_the_stored_files(store):
    write_earlier_version_project(store, "p")
    project_folder = store.open("p")
    (project_folder / EARLIER_JOINED_TEST_SURFACES).unlink()
    store.migrate_to_criteria("p")
    assert test_surfaces.has_vertex_normals(test_surfaces.joined_path(project_folder, "1"))
    record = store.read_project_json("p").criterion_records["1"]["preprocessing"]
    assert record.test_surfaces_fingerprint == test_surfaces.fingerprint(project_folder, "1")
