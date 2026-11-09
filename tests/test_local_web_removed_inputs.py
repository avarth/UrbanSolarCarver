"""Removed inputs are kept under inputs/removed/<role>/ and can be added back (user, 2026-11-09)."""
import pytest
import trimesh

from local_web_test_support import box_bytes, build_client, create_project
from urbansolarcarver.local_web_service.projects import ProjectError, ProjectStore


def _panel(x) -> bytes:
    return trimesh.creation.box(extents=(4, 4, 0.1)).apply_translation([x, 0, 3]).export(file_type="ply")


@pytest.fixture
def store(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("p", "daylight")
    store.add_input("p", "max_volume", "site.ply", box_bytes([0, 0, 0]))
    return store


def test_a_removed_file_says_where_it_is_kept_and_comes_back_as_it_was(store):
    store.add_input("p", "context", "ctx.ply", box_bytes([30, 0, 5]))
    removed = store.remove_input("p", "context", "ctx.ply")
    assert removed.kept_as == "ctx.ply" and removed.files == [] and store.removed_inputs_count("p") == 1
    restored = store.restore_removed_input("p", "context", "ctx.ply", "ctx.ply")
    assert [file.name for file in restored.files] == ["ctx.ply"] and restored.kept_as is None
    assert store.load_project_config("p").context_path is not None
    assert store.removed_inputs_count("p") == 0
    assert (store.open("p") / "inputs" / "context" / "ctx.ply").read_bytes() == box_bytes([30, 0, 5])


def test_a_second_removal_of_a_name_is_numbered_and_restores_under_the_name_it_had(store):
    for x in (30, 60):
        store.add_input("p", "context", "ctx.ply", box_bytes([x, 0, 5]))
        kept_as = store.remove_input("p", "context", "ctx.ply").kept_as
    assert kept_as == "ctx (2).ply" and store.removed_inputs_count("p") == 2
    store.restore_removed_input("p", "context", kept_as, "ctx.ply")
    assert (store.open("p") / "inputs" / "context" / "ctx.ply").read_bytes() == box_bytes([60, 0, 5])


def test_a_removed_set_comes_back_with_the_name_it_was_given(store):
    store.add_input("p", "test_surfaces", "facade.ply", _panel(0))
    store.rename_surface_set("p", "facade.ply", "South facade")
    kept_as = store.remove_input("p", "test_surfaces", "facade.ply").kept_as
    assert kept_as == "facade.ply" and store.removed_inputs_count("p") == 1   # its record beside it is not counted
    restored = store.restore_removed_input("p", "test_surfaces", kept_as, "facade.ply")
    assert [(file.name, file.shown_name) for file in restored.files] == [("facade.ply", "South facade")]
    assert not any((store.open("p") / "inputs" / "removed" / "test_surfaces").iterdir())


@pytest.mark.parametrize("kept_as", ["missing.ply", "../context/ctx.ply"])
def test_a_kept_file_that_is_not_there_is_refused(store, kept_as):
    store.add_input("p", "context", "ctx.ply", box_bytes([30, 0, 5]))
    with pytest.raises(ProjectError) as refusal:
        store.restore_removed_input("p", "context", kept_as, "ctx.ply")
    assert refusal.value.status_code == 404


def test_the_routes_undo_a_removal_count_what_is_kept_and_open_its_folder(tmp_path):
    opened = []
    def opener(folder):
        opened.append(folder.resolve())
    client, _ = build_client(tmp_path, open_folder_function=opener)
    create_project(client, "p")
    upload = {"file": ("ctx.ply", box_bytes([30, 0, 5]))}
    assert client.post("/api/projects/p/inputs/context", files=upload).status_code == 200
    removed = client.delete("/api/projects/p/inputs/context/ctx.ply").json()
    assert removed["kept_as"] == "ctx.ply" and removed["files"] == []
    assert client.get("/api/projects/p/removed-inputs").json() == {"count": 1}
    assert client.post("/api/projects/p/removed-inputs/open-folder").status_code == 204
    assert opened == [(tmp_path / "p" / "inputs" / "removed").resolve()]
    restored = client.post("/api/projects/p/inputs/context/restore", json={"kept_as": "ctx.ply", "file_name": "ctx.ply"})
    assert restored.status_code == 200 and [file["name"] for file in restored.json()["files"]] == ["ctx.ply"]
    assert client.get("/api/projects/p/removed-inputs").json() == {"count": 0}
    assert client.post("/api/projects/p/inputs/context/restore", json={"kept_as": "ctx.ply", "file_name": "ctx.ply"}).status_code == 404
