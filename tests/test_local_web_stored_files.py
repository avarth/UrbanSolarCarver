"""Stored input files changed in the project folder from outside the app (stored_files.py, local web service)."""
import os
import shutil

import pytest
import trimesh

from local_web_test_support import (
    ALL_CURRENT, GOLDEN_EPW, FakeEngine, box_bytes, make_worker, run_and_wait, write_fake_chain_run,
)
from urbansolarcarver.io import load_mesh, save_mesh
from urbansolarcarver.local_web_service import stored_files, test_surfaces
from urbansolarcarver.local_web_service.projects import ProjectError, ProjectStore
from urbansolarcarver.local_web_service.stage_records import criterion_status, stage_status, stage_status_reply

CURRENT = {"preprocessing": "current", "thresholding": "current"}
OUT_OF_DATE = {"preprocessing": "out_of_date", "thresholding": "out_of_date"}


def _panel(x=0, extents=(6, 6, 0.1)) -> bytes:
    return box_bytes([x, 0, 0], extents=extents)


def _open_panel(x=0) -> bytes:
    """A flat 6 m square facing up, open as a test surface is (the loader turns a closed mesh outward, whatever its file says)."""
    vertices = [[x, 0, 0], [x + 6, 0, 0], [x + 6, 6, 0], [x, 6, 0]]
    return trimesh.Trimesh(vertices=vertices, faces=[[0, 1, 2], [0, 2, 3]], process=False).export(file_type="ply")


def _flipped(data: bytes) -> bytes:
    """The same mesh with every face turned the other way (a surface exported with its normals inverted)."""
    mesh = trimesh.load(trimesh.util.wrap_as_stream(data), file_type="ply", process=False)
    mesh.invert()
    return mesh.export(file_type="ply")


@pytest.fixture
def chain_of_two(tmp_path):
    """A daylight project with a max volume and two criteria, each with its own test surface file, after a run of every stage."""
    store = ProjectStore(tmp_path / "projects")
    store.create("p", "daylight")
    store.add_input("p", "max_volume", "volume.ply", box_bytes([0, 0, 5]))
    store.add_criterion("p", "daylight")
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "roof.ply", _open_panel(20))
    write_fake_chain_run(store, "p", ["1", "2"])
    return store


def _replace_on_disk(store, role, file_name, data: bytes) -> None:
    """Overwrite a stored file as a file manager does, with a modification time the record does not have."""
    path = store.open("p") / "inputs" / (file_name if role == "weather" else f"{role}/{file_name}")
    old_time = path.stat().st_mtime_ns
    path.write_bytes(data)
    os.utime(path, ns=(old_time + 10 ** 9, old_time + 10 ** 9))


def _changes(store):
    return [(change.role, change.file_name, change.state) for change in stage_status_reply(store, "p").input_changes]


def test_a_test_surface_file_replaced_in_the_folder_dates_only_its_criterion(chain_of_two):
    store = chain_of_two
    folder = store.open("p")
    roof_before = test_surfaces.fingerprint(folder, "2")
    _replace_on_disk(store, "test_surfaces", "facade.ply", _panel(0, extents=(9, 9, 0.1)))
    assert criterion_status(store, "p") == {"1": CURRENT, "2": CURRENT}        # not looked at yet
    assert store.refresh_changed_inputs("p") is True
    joined = trimesh.load(test_surfaces.joined_path(folder, "1"), force="mesh")
    assert joined.bounds[1][0] - joined.bounds[0][0] == pytest.approx(9)
    assert test_surfaces.fingerprint(folder, "2") == roof_before
    # the second keeps its scores and carves again from what the first keeps
    assert criterion_status(store, "p") == {"1": OUT_OF_DATE, "2": {"preprocessing": "current", "thresholding": "out_of_date"}}
    assert _changes(store) == [("test_surfaces", "facade.ply", "changed")]
    assert store.refresh_changed_inputs("p") is False                         # found once


def test_a_surface_exported_with_its_faces_turned_is_a_change(chain_of_two):
    store = chain_of_two
    data = (store.open("p") / "inputs" / "test_surfaces" / "roof.ply").read_bytes()
    _replace_on_disk(store, "test_surfaces", "roof.ply", _flipped(data))
    store.refresh_changed_inputs("p")
    assert criterion_status(store, "p") == {"1": CURRENT, "2": OUT_OF_DATE}
    assert _changes(store) == [("test_surfaces", "roof.ply", "changed")]


def test_the_same_content_saved_again_changes_nothing(chain_of_two):
    store = chain_of_two
    path = store.open("p") / "inputs" / "test_surfaces" / "facade.ply"
    _replace_on_disk(store, "test_surfaces", "facade.ply", path.read_bytes())
    revision = store.read_project_json("p").inputs_revision
    assert store.refresh_changed_inputs("p") is True        # the record follows the new time
    assert store.read_project_json("p").stored_files["test_surfaces"]["facade.ply"].modified_ns == path.stat().st_mtime_ns
    assert store.read_project_json("p").inputs_revision == revision
    assert criterion_status(store, "p") == {"1": CURRENT, "2": CURRENT} and _changes(store) == []
    assert store.refresh_changed_inputs("p") is False


def test_a_project_made_before_the_records_is_checked_against_its_joined_files(chain_of_two):
    store = chain_of_two
    with store.project_lock("p"):
        project_json = store.read_project_json("p")
        project_json.stored_files = {}
        store.write_project_json("p", project_json)
    _replace_on_disk(store, "test_surfaces", "roof.ply", _panel(20, extents=(3, 3, 0.1)))
    assert store.refresh_changed_inputs("p") is True
    assert criterion_status(store, "p") == {"1": CURRENT, "2": OUT_OF_DATE}
    assert stage_status(store, "p")["exporting"] == "out_of_date"
    assert _changes(store) == [("test_surfaces", "roof.ply", "changed")]
    records = store.read_project_json("p").stored_files
    assert sorted(records["test_surfaces"]) == ["facade.ply", "roof.ply"] and sorted(records["max_volume"]) == ["volume.ply"]


def test_a_max_volume_replaced_in_the_folder_dates_every_stage(chain_of_two):
    store = chain_of_two
    revision = store.read_project_json("p").inputs_revision
    _replace_on_disk(store, "max_volume", "volume.ply", box_bytes([0, 0, 5], extents=(12, 12, 10)))
    store.refresh_changed_inputs("p")
    assert store.read_project_json("p").inputs_revision == revision + 1
    assert set(stage_status(store, "p").values()) == {"out_of_date"}
    assert store.joined_bounds("p")[1][0] == pytest.approx(6)
    assert _changes(store) == [("max_volume", "volume.ply", "changed")]


def test_a_context_file_replaced_in_the_folder_dates_every_stage(chain_of_two):
    store = chain_of_two
    store.add_input("p", "context", "town.ply", box_bytes([40, 0, 5]))
    write_fake_chain_run(store, "p", ["1", "2"])
    _replace_on_disk(store, "context", "town.ply", box_bytes([40, 0, 5], extents=(10, 10, 30)))
    store.refresh_changed_inputs("p")
    assert set(stage_status(store, "p").values()) == {"out_of_date"}
    assert store.input_files("p", "context")[0].triangle_count == 12


def test_a_weather_file_replaced_in_the_folder_dates_every_stage_once_recorded(chain_of_two):
    store = chain_of_two
    store.add_input("p", "weather", "golden.epw", GOLDEN_EPW.read_bytes())
    write_fake_chain_run(store, "p", ["1", "2"])
    weather_path = store.open("p") / "inputs" / "weather.epw"
    _replace_on_disk(store, "weather", "weather.epw", weather_path.read_bytes().replace(b"Golden", b"Denver", 1))
    store.refresh_changed_inputs("p")
    assert set(stage_status(store, "p").values()) == {"out_of_date"}
    assert _changes(store) == [("weather", "weather.epw", "changed")]


def test_a_weather_file_without_a_record_is_taken_as_it_is(chain_of_two):
    store = chain_of_two
    store.add_input("p", "weather", "golden.epw", GOLDEN_EPW.read_bytes())
    write_fake_chain_run(store, "p", ["1", "2"])
    with store.project_lock("p"):
        project_json = store.read_project_json("p")
        del project_json.stored_files["weather"]
        store.write_project_json("p", project_json)
    store.refresh_changed_inputs("p")
    assert stage_status(store, "p") == ALL_CURRENT and _changes(store) == []
    assert "weather.epw" in store.read_project_json("p").stored_files["weather"]


def test_a_file_missing_from_the_folder_is_listed_and_refuses_a_run(chain_of_two):
    store = chain_of_two
    (store.open("p") / "inputs" / "test_surfaces" / "roof.ply").unlink()
    assert store.refresh_changed_inputs("p") is False
    assert _changes(store) == [("test_surfaces", "roof.ply", "missing")]
    with pytest.raises(ProjectError, match=r"the test surface file 'roof.ply'") as refusal:
        make_worker(store).start("p", ["exporting", "massing"])
    assert refusal.value.status_code == 422
    store.dismiss_input_changes("p")
    assert _changes(store) == [("test_surfaces", "roof.ply", "missing")]       # it stays until it is back or removed


def test_a_file_that_cannot_be_read_is_tried_again_and_the_others_go_ahead(chain_of_two):
    store = chain_of_two
    old_record = store.read_project_json("p").stored_files["test_surfaces"]["facade.ply"]
    _replace_on_disk(store, "test_surfaces", "facade.ply", b"ply\nformat ascii 1.0\nend_header\nnot a mesh\n")
    _replace_on_disk(store, "max_volume", "volume.ply", box_bytes([0, 0, 5], extents=(12, 12, 10)))
    with pytest.raises(ProjectError, match="facade.ply"):
        store.refresh_changed_inputs("p")
    project_json = store.read_project_json("p")
    assert project_json.stored_files["test_surfaces"]["facade.ply"] == old_record
    assert [notice.file_name for notice in project_json.changed_files] == ["volume.ply"]
    with pytest.raises(ProjectError, match="facade.ply"):
        store.refresh_changed_inputs("p")


def test_a_study_follows_a_test_surface_file_replaced_in_the_folder(chain_of_two):
    store = chain_of_two
    study = store.add_study("p", from_criterion="2")
    study_joined = test_surfaces.joined_path_of_key(store.open("p"), test_surfaces.study_key(study.id))
    before = study_joined.read_bytes()
    _replace_on_disk(store, "test_surfaces", "roof.ply", _panel(20, extents=(3, 3, 0.1)))
    store.refresh_changed_inputs("p")
    assert study_joined.read_bytes() != before


def test_the_notice_is_dismissed_and_a_new_change_brings_it_back(chain_of_two):
    store = chain_of_two
    _replace_on_disk(store, "test_surfaces", "facade.ply", _panel(0, extents=(9, 9, 0.1)))
    store.refresh_changed_inputs("p")
    store.dismiss_input_changes("p")
    assert _changes(store) == []
    _replace_on_disk(store, "test_surfaces", "facade.ply", _panel(0, extents=(7, 7, 0.1)))
    store.refresh_changed_inputs("p")
    assert _changes(store) == [("test_surfaces", "facade.ply", "changed")]


def test_uploads_through_the_app_are_recorded_and_not_noticed(chain_of_two):
    store = chain_of_two
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0, extents=(9, 9, 0.1)))
    store.add_input("p", "max_volume", "volume.ply", box_bytes([0, 0, 5], extents=(12, 12, 10)))
    assert store.refresh_changed_inputs("p") is False and _changes(store) == []
    store.remove_input("p", "max_volume", "volume.ply")
    assert "volume.ply" not in store.read_project_json("p").stored_files.get("max_volume", {})


def test_a_run_after_a_change_in_the_folder_traces_the_criterion_again(chain_of_two):
    store = chain_of_two
    engine = FakeEngine()
    worker = make_worker(store, handle_request=engine)
    run_and_wait(worker, "p", ["exporting", "massing"])
    _replace_on_disk(store, "test_surfaces", "roof.ply", _panel(20, extents=(3, 3, 0.1)))
    reply = run_and_wait(worker, "p", ["exporting", "massing"])
    assert reply.criterion_stages == {"1": [], "2": ["preprocessing", "thresholding"]}
    assert engine.requests[-1].trace_criteria == ["2"]


def test_an_example_project_copied_with_new_file_times_is_not_noticed(tmp_path, chain_of_two):
    store = chain_of_two
    copy_folder = store.projects_folder / "q"
    shutil.copytree(store.open("p"), copy_folder, copy_function=shutil.copy)     # new file times, same content
    with store.project_lock("q"):
        project_json = store.read_project_json("q")
        store.write_project_json("q", project_json.model_copy(update={"name": "q"}))
    store.refresh_changed_inputs("q")
    assert stored_files.input_changes(store, "q") == []
    assert stage_status(store, "q") == ALL_CURRENT


def test_a_context_joined_with_turned_faces_by_an_earlier_version_is_not_a_change(chain_of_two):
    store = chain_of_two
    town = trimesh.creation.box(extents=(10, 10, 10))
    town.apply_translation([40, 0, 5])
    town.faces[0] = town.faces[0][::-1]         # one face wound the other way, as exports often have
    store.add_input("p", "context", "town.ply", town.export(file_type="ply"))
    write_fake_chain_run(store, "p", ["1", "2"])
    folder = store.open("p")
    earlier = load_mesh(str(folder / "inputs" / "context" / "town.ply"), fix_normals=True)    # an earlier version joined it so
    earlier.merge_vertices()
    save_mesh(earlier, str(folder / "inputs" / "joined" / "context.ply"))
    with store.project_lock("p"):
        project_json = store.read_project_json("p")
        project_json.stored_files = {}
        store.write_project_json("p", project_json)
    store.refresh_changed_inputs("p")
    assert stage_status(store, "p") == ALL_CURRENT and _changes(store) == []


def test_a_file_being_copied_or_locked_is_tried_again(chain_of_two, monkeypatch):
    store = chain_of_two
    old_record = store.read_project_json("p").stored_files["test_surfaces"]["facade.ply"]
    _replace_on_disk(store, "test_surfaces", "facade.ply", _panel(0, extents=(9, 9, 0.1)))
    real_record = stored_files.file_record

    def locked(path):
        if path.name == "facade.ply":
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real_record(path)

    monkeypatch.setattr(stored_files, "file_record", locked)
    with pytest.raises(ProjectError, match="facade.ply") as refusal:
        store.refresh_changed_inputs("p")
    assert refusal.value.status_code == 422
    assert store.read_project_json("p").stored_files["test_surfaces"]["facade.ply"] == old_record
    monkeypatch.setattr(stored_files, "file_record", real_record)
    store.refresh_changed_inputs("p")
    assert _changes(store) == [("test_surfaces", "facade.ply", "changed")]


def test_a_max_volume_whose_joined_file_cannot_be_replaced_still_dates_the_stages(chain_of_two, monkeypatch):
    store = chain_of_two
    _replace_on_disk(store, "max_volume", "volume.ply", box_bytes([0, 0, 5], extents=(12, 12, 10)))
    real_replace = ProjectStore._replace_joined_file

    def replaced_then_failed(project_folder, role, joined_temporary_path):
        real_replace(project_folder, role, joined_temporary_path)
        raise OSError("the disk went away after the move")

    monkeypatch.setattr(ProjectStore, "_replace_joined_file", staticmethod(replaced_then_failed))
    with pytest.raises(ProjectError):
        store.refresh_changed_inputs("p")
    monkeypatch.setattr(ProjectStore, "_replace_joined_file", staticmethod(real_replace))
    assert set(stage_status(store, "p").values()) == {"out_of_date"}
    store.refresh_changed_inputs("p")       # finds the joined file in place; the stages stay out of date
    assert set(stage_status(store, "p").values()) == {"out_of_date"}


def test_a_missing_file_only_a_study_lists_does_not_refuse_a_design_run(chain_of_two):
    store = chain_of_two
    study = store.add_study("p", metric="sky_view")
    store.add_study_test_surface("p", study.id, "courtyard.ply", _panel(60))
    (store.open("p") / "inputs" / "test_surfaces" / "courtyard.ply").unlink()
    stored_files.refuse_missing_files(store, "p", "run")
    with pytest.raises(ProjectError, match="courtyard.ply"):
        stored_files.refuse_missing_files(store, "p", "simulation")


def test_a_file_that_cannot_be_read_does_not_rewrite_project_json_at_each_look(chain_of_two):
    store = chain_of_two
    _replace_on_disk(store, "test_surfaces", "facade.ply", b"ply\nformat ascii 1.0\nend_header\nnot a mesh\n")
    project_json_path = store.open("p") / "project.json"
    with pytest.raises(ProjectError):
        store.refresh_changed_inputs("p")
    written = project_json_path.stat().st_mtime_ns
    with pytest.raises(ProjectError):
        store.refresh_changed_inputs("p")
    assert project_json_path.stat().st_mtime_ns == written


def test_each_change_of_a_file_is_a_notice_of_its_own(chain_of_two):
    store = chain_of_two
    _replace_on_disk(store, "test_surfaces", "facade.ply", _panel(0, extents=(9, 9, 0.1)))
    store.refresh_changed_inputs("p")
    with store.project_lock("p"):        # as if found earlier, so the next change is found at another time
        project_json = store.read_project_json("p")
        project_json.changed_files[0].noticed = "2026-01-01T00:00:00+00:00"
        store.write_project_json("p", project_json)
    _replace_on_disk(store, "test_surfaces", "facade.ply", _panel(0, extents=(7, 7, 0.1)))
    store.refresh_changed_inputs("p")
    change, = stage_status_reply(store, "p").input_changes
    assert change.state == "changed" and change.noticed not in (None, "2026-01-01T00:00:00+00:00")
