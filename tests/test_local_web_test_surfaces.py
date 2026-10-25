"""Test surface files stored once per project, protected per criterion, one joined file per criterion (local web service)."""
import hashlib

import pytest
import trimesh

from local_web_test_support import box_bytes, has_vertex_normals
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


def test_a_file_no_criterion_uses_is_deleted(tmp_path):
    store = _store_with_criteria(tmp_path)
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "roof.ply", _panel(50))
    store.remove_criterion_test_surface("p", "1", "facade.ply")
    store.remove_criterion_test_surface("p", "2", "facade.ply")
    assert _stored_file_names(store) == ["roof.ply"]
    assert [file.name for file in store.input_files("p", "test_surfaces")] == ["roof.ply"]
    store.delete_criterion("p", "2")
    assert _stored_file_names(store) == [] and store.input_files("p", "test_surfaces") == []
    assert not test_surfaces.joined_path(store.open("p"), "2").exists()


def test_deleting_a_criterion_keeps_the_files_another_criterion_uses(tmp_path):
    store = _store_with_criteria(tmp_path)
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "roof.ply", _panel(50))
    store.delete_criterion("p", "2")
    assert _stored_file_names(store) == ["facade.ply"] and _uses(store, "1") == ["facade.ply"]


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
    assert store.criteria("p")[0].name == "daylight on windows"
    store.use_test_surface("p", "2", "doors.ply")
    assert store.criteria("p")[1].name == "daylight on doors"
    store.update_criterion("p", "1", name="Windows of the block")
    store.remove_criterion_test_surface("p", "1", "windows.ply")
    store.remove_criterion_test_surface("p", "1", "doors.ply")
    assert store.criteria("p")[0].name == "Windows of the block"
    store.remove_criterion_test_surface("p", "2", "doors.ply")
    assert store.criteria("p")[1].name == "daylight"
    assert "daylight on" not in store.open("p").joinpath("config.yaml").read_text(encoding="utf-8")


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
    config = store.load_project_config("p")
    assert missing_inputs(store, "p", config) == ["test_surfaces:1", "test_surfaces:2"]
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    assert missing_inputs(store, "p", config) == ["test_surfaces:2"]
    store.update_criterion("p", "2", bypassed=True)
    assert missing_inputs(store, "p", config) == []
    store.update_criterion("p", "1", bypassed=True)
    assert missing_inputs(store, "p", config) == ["criteria"]


def test_the_apps_test_surface_upload_goes_to_the_only_criterion(tmp_path):
    store = _store_with_criteria(tmp_path, count=1)
    revision = store.read_project_json("p").inputs_revision
    reply = store.add_input("p", "test_surfaces", "facade.ply", _panel(0))
    assert [file.name for file in reply.files] == ["facade.ply"] and reply.role == "test_surfaces"
    assert _uses(store, "1") == ["facade.ply"]
    assert test_surfaces.joined_path(store.open("p"), "1").is_file()
    assert store.read_project_json("p").inputs_revision == revision
    reply = store.remove_input("p", "test_surfaces", "facade.ply")
    assert reply.files == [] and _uses(store, "1") == [] and _stored_file_names(store) == []
    assert not test_surfaces.joined_path(store.open("p"), "1").exists()


def test_the_apps_test_surface_upload_with_several_criteria_says_which_one(tmp_path):
    store = _store_with_criteria(tmp_path)
    with pytest.raises(ProjectError, match="Say which criterion") as refused:
        store.add_input("p", "test_surfaces", "facade.ply", _panel(0))
    assert refused.value.status_code == 422
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    with pytest.raises(ProjectError, match="Say which criterion"):
        store.remove_input("p", "test_surfaces", "facade.ply")
    assert _stored_file_names(store) == ["facade.ply"]


def test_a_joined_file_without_normals_is_rebuilt_for_each_criterion(tmp_path):
    store = _store_with_criteria(tmp_path)
    store.add_criterion_test_surface("p", "1", "facade.ply", _panel(0))
    store.add_criterion_test_surface("p", "2", "roof.ply", _panel(50))
    folder = store.open("p")
    for criterion_id in ("1", "2"):
        mesh = trimesh.load(test_surfaces.joined_path(folder, criterion_id), force="mesh")
        mesh.export(test_surfaces.joined_path(folder, criterion_id), file_type="ply", include_attributes=False)
        assert not has_vertex_normals(test_surfaces.joined_path(folder, criterion_id))
    revision = store.read_project_json("p").inputs_revision
    assert store.rebuild_joined_test_surfaces_without_normals("p") is True
    assert all(has_vertex_normals(test_surfaces.joined_path(folder, criterion_id)) for criterion_id in ("1", "2"))
    assert store.read_project_json("p").inputs_revision == revision + 1
    assert store.rebuild_joined_test_surfaces_without_normals("p") is False
