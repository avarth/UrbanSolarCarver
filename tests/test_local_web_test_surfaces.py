"""Test surface files stored once per project, protected per criterion, one joined file per criterion (local web service)."""
import hashlib

import pytest
import send2trash
import trimesh

from local_web_test_support import FakeRecycleBin, box_bytes, has_vertex_normals
from urbansolarcarver.local_web_service import test_surfaces
from urbansolarcarver.local_web_service.projects import ProjectError, ProjectStore
from urbansolarcarver.local_web_service.stage_records import missing_inputs


def _panel(x, extents=(4, 4, 0.1)) -> bytes:
    return box_bytes([x, 0, 0], extents=extents)


def _store_with_criteria(tmp_path, count=2):
    """A daylight project with *count* criteria (ids "1", "2", ...) and no test surface."""
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    for _ in range(count - 1):
        store.add_criterion("p", "daylight")
    return store


def _stored_file_names(store):
    return sorted(path.name for path in (store.open("p") / "inputs" / "test_surfaces").iterdir())


def _uses(store, criterion_id):
    return next(entry for entry in store.criteria("p") if entry.id == criterion_id).test_surface_files


def _fingerprints(store, *ids):
    return [test_surfaces.fingerprint(store.open("p"), criterion_id) for criterion_id in ids]


def test_the_same_file_in_two_criteria_is_stored_once(tmp_path):
    store = _store_with_criteria(tmp_path)
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "facade.ply", _panel(0))
    assert _stored_file_names(store) == ["facade.ply"]
    assert _uses(store, "1") == ["facade.ply"] and _uses(store, "2") == ["facade.ply"]
    assert [file.name for file in store.input_files("p", "test_surfaces")] == ["facade.ply"]


def test_an_upload_with_the_content_of_a_stored_file_reuses_it_under_its_name(tmp_path):
    store = _store_with_criteria(tmp_path)
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "same_facade_again.ply", _panel(0))
    assert _stored_file_names(store) == ["facade.ply"]
    assert _uses(store, "2") == ["facade.ply"]
    assert _fingerprints(store, "1") == _fingerprints(store, "2")


def test_a_new_file_with_a_stored_name_replaces_it_for_every_criterion(tmp_path):
    store = _store_with_criteria(tmp_path, count=3)
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "3", "roof.ply", _panel(50))
    first_before, second_before, third_before = _fingerprints(store, "1", "2", "3")
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0, extents=(8, 8, 0.1)))
    first_after, second_after, third_after = _fingerprints(store, "1", "2", "3")
    assert first_after != first_before and second_after != second_before
    assert third_after == third_before
    assert _stored_file_names(store) == ["facade.ply", "roof.ply"]
    for criterion_id in ("1", "2"):
        joined = trimesh.load(test_surfaces.joined_path(store.open("p"), criterion_id), force="mesh")
        assert joined.bounds[1][0] - joined.bounds[0][0] == pytest.approx(8)


def test_removing_a_file_from_one_criterion_keeps_it_for_the_other(tmp_path):
    store = _store_with_criteria(tmp_path)
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "facade.ply", _panel(0))
    second_before = _fingerprints(store, "2")
    store.remove_criterion_test_surface("p", "1", "facade.ply")
    assert _uses(store, "1") == [] and _uses(store, "2") == ["facade.ply"]
    assert _stored_file_names(store) == ["facade.ply"]
    assert not test_surfaces.joined_path(store.open("p"), "1").exists()
    assert _fingerprints(store, "2") == second_before


def test_a_set_no_criterion_uses_stays_until_it_is_deleted_and_then_goes_to_the_recycle_bin(tmp_path, monkeypatch):
    recycle_bin = FakeRecycleBin()
    monkeypatch.setattr(send2trash, "send2trash", recycle_bin)
    store = _store_with_criteria(tmp_path)
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "roof.ply", _panel(50))
    store.remove_criterion_test_surface("p", "1", "facade.ply")
    store.delete_criterion("p", "2")
    assert _stored_file_names(store) == ["facade.ply", "roof.ply"] and recycle_bin.files == []
    store.remove_input("p", "test_surfaces", "facade.ply")
    assert _stored_file_names(store) == ["roof.ply"]
    assert [file.name for file in store.input_files("p", "test_surfaces")] == ["roof.ply"]
    assert recycle_bin.files == [store.open("p") / "inputs" / "test_surfaces" / "facade.ply"]


def test_a_set_the_recycle_bin_refuses_stays_on_disk_and_leaves_the_project(tmp_path, monkeypatch):
    store = _store_with_criteria(tmp_path, count=1)
    store.add_input("p", "test_surfaces", "facade.ply", _panel(0))
    monkeypatch.setattr(send2trash, "send2trash", FakeRecycleBin(error=OSError("the file is open in another program")))
    store.delete_surface_set("p", "facade.ply")
    assert store.input_files("p", "test_surfaces") == [] and _stored_file_names(store) == ["facade.ply"]


def test_a_set_added_to_the_project_is_used_by_nothing_until_switched_on(tmp_path):
    store = _store_with_criteria(tmp_path, count=1)
    reply = store.add_input("p", "test_surfaces", "facade.ply", _panel(0))
    assert [(file.name, file.used_by) for file in reply.files] == [("facade.ply", [])]
    assert _uses(store, "1") == [] and not test_surfaces.joined_path(store.open("p"), "1").exists()
    store.use_test_surface("p", "1", "facade.ply")
    assert store.input_files("p", "test_surfaces")[0].used_by == [store.criteria("p")[0].name]
    first = _fingerprints(store, "1")
    store.add_input("p", "test_surfaces", "facade.ply", _panel(0, extents=(8, 8, 0.1)))      # replaced: its criterion is joined again
    assert _fingerprints(store, "1") != first


def test_a_set_in_use_is_not_deleted_and_the_reason_names_its_users(tmp_path):
    store = _store_with_criteria(tmp_path, count=1)
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    study = store.add_study("p", from_criterion="1")
    before = store.read_project_json("p")
    with pytest.raises(ProjectError) as refused:
        store.remove_input("p", "test_surfaces", "facade.ply")
    criterion_name = store.criteria("p")[0].name
    assert refused.value.status_code == 422
    assert str(refused.value) == f"facade is used by {criterion_name} and {study.name}. Switch it off there first."
    assert store.read_project_json("p") == before and _stored_file_names(store) == ["facade.ply"]


def test_deleting_a_criterion_keeps_its_sets_in_the_project(tmp_path):
    store = _store_with_criteria(tmp_path)
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "roof.ply", _panel(50))
    store.delete_criterion("p", "2")
    assert _stored_file_names(store) == ["facade.ply", "roof.ply"] and _uses(store, "1") == ["facade.ply"]


def test_a_missing_criterion_or_file_is_a_404(tmp_path):
    store = _store_with_criteria(tmp_path)
    with pytest.raises(ProjectError) as unknown_criterion:
        store.add_criterion_test_surface("p", "9", "facade.ply", _panel(0))
    assert unknown_criterion.value.status_code == 404
    with pytest.raises(ProjectError) as not_stored:
        store.use_test_surface("p", "1", "facade.ply")
    assert not_stored.value.status_code == 404
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    with pytest.raises(ProjectError) as not_used:
        store.remove_criterion_test_surface("p", "2", "facade.ply")
    assert not_used.value.status_code == 404
    assert _stored_file_names(store) == ["facade.ply"]


def test_test_surface_changes_do_not_raise_inputs_revision(tmp_path):
    store = _store_with_criteria(tmp_path)
    revision = store.read_project_json("p").inputs_revision
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    store.use_test_surface("p", "2", "facade.ply")
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0, extents=(8, 8, 0.1)))
    store.remove_criterion_test_surface("p", "1", "facade.ply")
    store.remove_criterion_test_surface("p", "2", "facade.ply")
    assert store.read_project_json("p").inputs_revision == revision


def test_use_test_surface_adds_a_stored_file_and_builds_the_joined_file(tmp_path):
    store = _store_with_criteria(tmp_path)
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    entry = store.use_test_surface("p", "2", "facade.ply")
    assert entry.id == "2" and entry.test_surface_files == ["facade.ply"]
    assert _fingerprints(store, "1") == _fingerprints(store, "2") != [None]
    assert store.use_test_surface("p", "2", "facade.ply").test_surface_files == ["facade.ply"]


def test_the_joined_file_keeps_vertex_normals_and_follows_sorted_file_names(tmp_path):
    store = _store_with_criteria(tmp_path, count=1)
    for file_name, x in (("b.ply", 100), ("a.ply", 0), ("c.ply", 200)):
        store.add_criterion_test_surface("p", "1", file_name, _panel(x))
    joined_path = test_surfaces.joined_path(store.open("p"), "1")
    assert has_vertex_normals(joined_path)
    centres = trimesh.load(joined_path, force="mesh").triangles_center
    assert [round(float(centres[start:start + 12, 0].mean())) for start in range(0, len(centres), 12)] == [0, 100, 200]
    assert _uses(store, "1") == ["b.ply", "a.ply", "c.ply"]    # the criterion lists its files in the order they were added


def test_a_refused_upload_changes_nothing(tmp_path):
    store = _store_with_criteria(tmp_path)
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    before = _fingerprints(store, "1")
    with pytest.raises(ProjectError) as refused:
        store.add_criterion_test_surface("p", "1", "facade.ply", b"not a mesh")
    assert refused.value.status_code == 422
    with pytest.raises(ProjectError):
        store.add_criterion_test_surface("p", "1", "notes.txt", _panel(0))
    assert _fingerprints(store, "1") == before and _stored_file_names(store) == ["facade.ply"]
    assert [path.name for path in (store.open("p") / "inputs" / "joined").iterdir()] == ["test_surfaces_1.ply"]


def test_a_criterion_named_by_default_is_named_after_its_first_test_surface(tmp_path):
    store = _store_with_criteria(tmp_path)
    store.add_criterion_test_surface("p", "1", "windows.ply", _panel(0))
    store.add_criterion_test_surface("p", "1", "doors.ply", _panel(50))
    assert store.criteria("p")[0].name == "Daylight on windows"
    store.use_test_surface("p", "2", "doors.ply")
    assert store.criteria("p")[1].name == "Daylight on doors"
    store.update_criterion("p", "1", name="Windows of the block")
    store.remove_criterion_test_surface("p", "1", "windows.ply")
    store.remove_criterion_test_surface("p", "1", "doors.ply")
    assert store.criteria("p")[0].name == "Windows of the block"
    store.remove_criterion_test_surface("p", "2", "doors.ply")
    assert store.criteria("p")[1].name == "Daylight"
    assert "Daylight on" not in store.open("p").joinpath("config.yaml").read_text(encoding="utf-8")


def test_the_joined_file_and_fingerprint_helpers(tmp_path):
    joined = test_surfaces.joined_path(tmp_path, "7")
    assert joined == tmp_path / "inputs" / "joined" / "test_surfaces_7.ply"
    assert test_surfaces.fingerprint(tmp_path, "7") is None
    joined.parent.mkdir(parents=True)
    joined.write_bytes(b"abc")
    expected = hashlib.sha256(b"abc").hexdigest()
    assert test_surfaces.fingerprint(tmp_path, "7") == expected == test_surfaces.content_digest(joined)


def test_a_run_needs_test_surfaces_in_every_active_criterion(tmp_path):
    store = _store_with_criteria(tmp_path)
    store.add_input("p", "max_volume", "volume.ply", box_bytes([0, 0, 5]))
    assert missing_inputs(store, "p") == ["test_surfaces:1", "test_surfaces:2"]
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    assert missing_inputs(store, "p") == ["test_surfaces:2"]
    store.update_criterion("p", "2", bypassed=True)
    assert missing_inputs(store, "p") == []
    store.update_criterion("p", "1", bypassed=True)
    assert missing_inputs(store, "p") == ["criteria"]


def test_the_same_file_uploaded_twice_to_one_criterion_is_listed_once(tmp_path):
    store = _store_with_criteria(tmp_path, count=1)
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    before = _fingerprints(store, "1")
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    assert _uses(store, "1") == ["facade.ply"] and _stored_file_names(store) == ["facade.ply"]
    assert _fingerprints(store, "1") == before
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0, extents=(8, 8, 0.1)))
    assert _uses(store, "1") == ["facade.ply"] and _fingerprints(store, "1") != before


def test_a_name_that_differs_only_in_letter_case_is_the_stored_file(tmp_path):
    store = _store_with_criteria(tmp_path)
    store.add_criterion_test_surface("p", "1", "Facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "Facade.ply", _panel(0))
    before = _fingerprints(store, "1", "2")
    store.add_criterion_test_surface("p", "1", "FACADE.PLY", _panel(0, extents=(8, 8, 0.1)))
    assert _stored_file_names(store) == ["Facade.ply"]
    assert _uses(store, "1") == ["Facade.ply"] and _uses(store, "2") == ["Facade.ply"]
    assert [file.name for file in store.input_files("p", "test_surfaces")] == ["Facade.ply"]
    assert all(after != earlier for after, earlier in zip(_fingerprints(store, "1", "2"), before))
