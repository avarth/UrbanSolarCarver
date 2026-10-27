"""The inspection of the input files: a summary of each mesh file and the geometry of the test surfaces (inspection.py)."""
import json
import os
import struct
import time
from pathlib import Path

import numpy as np
import pytest

from local_web_test_support import GOLDEN_EPW, box_bytes, write_fake_chain_run
from test_local_web_server import build_client, client_with_blocking_run, create_project, projects_folder, upload  # noqa: F401 (fixtures)
from urbansolarcarver.io import load_mesh
from urbansolarcarver.local_web_service import inspection
from urbansolarcarver.local_web_service.projects import ProjectError, ProjectStore
from urbansolarcarver.local_web_service.inspection import (
    ORIGINALS_FOLDER, inspection_geometry, project_inspection, restore_original, save_turned_surfaces,
)
from urbansolarcarver.local_web_service.stage_records import criterion_status, stage_status_reply

PANEL_SIZE = 6.0


def obj_panels(x_offsets, x_origin=0.0, z=0.0) -> bytes:
    """OBJ text of one open square panel (two triangles, facing up) at each x offset."""
    lines = []
    for index, offset in enumerate(x_offsets):
        x = x_origin + offset
        lines += [f"v {x} 0 {z}", f"v {x + PANEL_SIZE} 0 {z}", f"v {x + PANEL_SIZE} {PANEL_SIZE} {z}", f"v {x} {PANEL_SIZE} {z}"]
        first = 4 * index + 1
        lines += [f"f {first} {first + 1} {first + 2}", f"f {first} {first + 2} {first + 3}"]
    return ("\n".join(lines) + "\n").encode()


def obj_box(size=PANEL_SIZE) -> bytes:
    """OBJ text of a closed box of 12 triangles, outward."""
    corners = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    lines = [f"v {x * size} {y * size} {z * size}" for x, y, z in corners]
    faces = [(1, 3, 2), (1, 4, 3), (5, 6, 7), (5, 7, 8), (1, 2, 6), (1, 6, 5), (4, 8, 7), (4, 7, 3), (1, 5, 8), (1, 8, 4), (2, 3, 7), (2, 7, 6)]
    lines += [f"f {a} {b} {c}" for a, b, c in faces]
    return ("\n".join(lines) + "\n").encode()


def ply_of_a_box_and_a_panel() -> bytes:
    """A context file of one closed box and one open panel, 5 m apart."""
    import trimesh
    box = trimesh.creation.box(extents=(4, 4, 4))
    box.apply_translation((-20, 0, 2))
    panel = trimesh.Trimesh(vertices=[[10, 0, 0], [16, 0, 0], [16, 6, 0], [10, 6, 0]], faces=[[0, 1, 2], [0, 2, 3]], process=False)
    return trimesh.util.concatenate([box, panel]).export(file_type="ply")


@pytest.fixture
def store(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    store.create("p", "daylight")
    return store


@pytest.fixture
def store_with_files(store):
    store.add_input("p", "max_volume", "volume.ply", box_bytes([0, 0, 5]))
    store.add_input("p", "test_surfaces", "facades.obj", obj_panels([0, 20]))
    store.add_input("p", "context", "town.ply", ply_of_a_box_and_a_panel())
    store.add_input("p", "weather", "golden.epw", GOLDEN_EPW.read_bytes())
    return store


def decoded_geometry(data: bytes) -> tuple[dict, np.ndarray, np.ndarray]:
    """The header, the corners (triangles x 3 x 3, relative to the frame) and the surface number of each triangle."""
    (header_length,) = struct.unpack_from("<I", data, 0)
    assert header_length % 4 == 0
    header = json.loads(data[4:4 + header_length])
    count = header["triangle_count"]
    corners = np.frombuffer(data, dtype="<f4", count=count * 9, offset=4 + header_length).reshape(count, 3, 3)
    surfaces = np.frombuffer(data, dtype="<u4", count=count, offset=4 + header_length + count * 36)
    assert len(data) == 4 + header_length + count * 36 + count * 4
    return header, corners, surfaces


def test_the_summary_lists_every_mesh_file_by_role(store_with_files):
    reply = project_inspection(store_with_files, "p")
    assert [(entry.role, entry.file_name) for entry in reply.files] == [
        ("max_volume", "volume.ply"), ("test_surfaces", "facades.obj"), ("context", "town.ply")]
    volume, facades, town = reply.files
    assert volume.surface_count is None and volume.flippable is False and volume.original_kept is False
    assert volume.body_count == 1 and volume.closed_body_count == 1 and volume.triangle_count == 12
    assert facades.triangle_count == 4
    assert facades.surface_count == 2
    assert facades.area_m2 == pytest.approx(72)
    assert facades.flippable is True
    assert facades.bounds == [[0, 0, 0], [26, 6, 0]]
    assert town.body_count == 2
    assert town.closed_body_count == 1
    assert town.surface_count is None
    assert town.flippable is False


def test_a_test_surface_file_closed_as_a_whole_is_not_flippable(store):
    store.add_input("p", "test_surfaces", "block.obj", obj_box())
    (entry,) = project_inspection(store, "p").files
    assert entry.flippable is False
    assert entry.closed_body_count == entry.body_count == 1
    assert entry.surface_count == 1


def test_the_geometry_numbers_each_triangle_by_its_surface(store_with_files):
    header, corners, surfaces = decoded_geometry(inspection_geometry(store_with_files, "p", "facades.obj"))
    assert header["triangle_count"] == 4 and header["surface_count"] == 2
    assert len(header["surfaces"]) == 2 and corners.shape == (4, 3, 3)
    assert set(surfaces.tolist()) == {0, 1}
    assert np.bincount(surfaces).tolist() == [2, 2]
    frame = np.array(header["frame"])
    for number, surface in enumerate(header["surfaces"]):
        assert surface["normal"] == pytest.approx([0, 0, 1])
        assert surface["area"] == pytest.approx(36)
        in_surface = corners[surfaces == number] + frame
        assert np.array(surface["centre"]) + frame == pytest.approx(in_surface.reshape(-1, 3).mean(axis=0), abs=1e-4)


def test_georeferenced_geometry_keeps_its_place(store):
    store.add_input("p", "test_surfaces", "site.obj", obj_panels([0], x_origin=4_500_000.25, z=12.5))
    header, corners, surfaces = decoded_geometry(inspection_geometry(store, "p", "site.obj"))
    assert header["frame"][0] == 4_500_000.0
    absolute = corners.astype(float) + np.array(header["frame"])
    assert absolute[:, :, 0].min() == pytest.approx(4_500_000.25, abs=1e-3)
    assert absolute[:, :, 0].max() == pytest.approx(4_500_006.25, abs=1e-3)
    assert absolute[:, :, 2] == pytest.approx(12.5, abs=1e-3)


def test_the_inspection_follows_a_changed_file(store):
    store.add_input("p", "test_surfaces", "facades.obj", obj_panels([0, 20]))
    assert project_inspection(store, "p").files[0].surface_count == 2
    path = store.input_file_path("p", "test_surfaces", "facades.obj")
    old_time = path.stat().st_mtime_ns
    path.write_bytes(obj_panels([0, 20, 40]))
    os.utime(path, ns=(old_time + 10 ** 9, old_time + 10 ** 9))
    assert project_inspection(store, "p").files[0].surface_count == 3
    _, _, surfaces = decoded_geometry(inspection_geometry(store, "p", "facades.obj"))
    assert set(surfaces.tolist()) == {0, 1, 2}


def test_an_unchanged_file_is_read_once(store_with_files, monkeypatch):
    project_inspection(store_with_files, "p")
    monkeypatch.setattr(inspection, "load_mesh", lambda *args, **kwargs: pytest.fail("the file was read again"))
    project_inspection(store_with_files, "p")
    inspection_geometry(store_with_files, "p", "facades.obj")


def test_two_closed_bodies_touching_along_an_edge_are_both_closed(store):
    import trimesh
    first = trimesh.creation.box(extents=(4, 4, 4))
    first.apply_translation((2, 2, 2))
    second = trimesh.creation.box(extents=(4, 4, 4))
    second.apply_translation((6, 6, 2))     # shares the vertical edge x = 4, y = 4 with the first
    store.add_input("p", "context", "pair.ply", trimesh.util.concatenate([first, second]).export(file_type="ply"))
    (entry,) = project_inspection(store, "p").files
    assert entry.body_count == 2
    assert entry.closed_body_count == 2


def _overwrite(store, role, file_name, data: bytes) -> None:
    path = store.input_file_path("p", role, file_name)
    old_time = path.stat().st_mtime_ns
    path.write_bytes(data)
    os.utime(path, ns=(old_time + 10 ** 9, old_time + 10 ** 9))


def test_an_unreadable_file_is_listed_with_its_problem_and_the_others_as_usual(store_with_files):
    _overwrite(store_with_files, "context", "town.ply", b"this is not a mesh")
    volume, facades, town = project_inspection(store_with_files, "p").files
    assert town.file_name == "town.ply" and town.role == "context"
    assert town.problem and not town.problem.startswith("load_mesh:")
    assert (town.triangle_count, town.area_m2, town.bounds, town.body_count, town.closed_body_count) == (0, 0, [[0, 0, 0], [0, 0, 0]], 0, 0)
    assert town.surface_count is None and town.flippable is False and town.original_kept is False
    assert volume.problem is None and volume.triangle_count == 12
    assert facades.problem is None and facades.surface_count == 2


def test_the_geometry_of_an_unreadable_file_is_422_and_of_a_deleted_file_404(store_with_files):
    _overwrite(store_with_files, "test_surfaces", "facades.obj", b"")
    with pytest.raises(ProjectError) as refused:
        inspection_geometry(store_with_files, "p", "facades.obj")
    assert refused.value.status_code == 422
    assert next(entry for entry in project_inspection(store_with_files, "p").files if entry.file_name == "facades.obj").problem
    store_with_files.input_file_path("p", "test_surfaces", "facades.obj").unlink()
    assert [entry.file_name for entry in project_inspection(store_with_files, "p").files] == ["volume.ply", "town.ply"]
    with pytest.raises(ProjectError) as missing:
        inspection_geometry(store_with_files, "p", "facades.obj")
    assert missing.value.status_code == 404


def test_the_original_is_reported_when_it_is_kept(store_with_files):
    kept = store_with_files.open("p") / ORIGINALS_FOLDER / "facades.obj"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(obj_panels([0, 20]))
    facades = next(entry for entry in project_inspection(store_with_files, "p").files if entry.file_name == "facades.obj")
    assert facades.original_kept is True


def test_the_routes_answer_and_an_unknown_file_is_404(tmp_path):
    client, _ = build_client(tmp_path / "projects")
    create_project(client)
    assert upload(client, "p", "max_volume", ("volume.ply", box_bytes([0, 0, 5]))).status_code == 200
    assert upload(client, "p", "test_surfaces", ("facades.obj", obj_panels([0, 20]))).status_code == 200
    reply = client.get("/api/projects/p/inspect")
    assert reply.status_code == 200
    files = reply.json()["files"]
    assert [(entry["role"], entry["file_name"]) for entry in files] == [("max_volume", "volume.ply"), ("test_surfaces", "facades.obj")]
    assert files[1]["surface_count"] == 2 and files[1]["flippable"] is True and files[1]["original_kept"] is False
    geometry = client.get("/api/projects/p/inspect/test_surfaces/facades.obj/geometry")
    assert geometry.status_code == 200
    assert geometry.headers["content-type"] == "application/octet-stream"
    assert decoded_geometry(geometry.content)[0]["surface_count"] == 2
    assert client.get("/api/projects/p/inspect/test_surfaces/nothing.obj/geometry").status_code == 404
    assert client.get("/api/projects/nothing/inspect").status_code == 404
    assert client.get("/api/projects/nothing/inspect/test_surfaces/facades.obj/geometry").status_code == 404


@pytest.mark.slow
def test_the_district_example_is_inspected_within_seconds(store, example_project_templates):
    example_project_templates.copy_example_project(store, "district", "multiple_buildings")
    started = time.perf_counter()
    reply = project_inspection(store, "district")
    for entry in reply.files:
        if entry.role == "test_surfaces":
            inspection_geometry(store, "district", entry.file_name)
    elapsed = time.perf_counter() - started
    assert any(entry.role == "test_surfaces" for entry in reply.files)
    assert elapsed < 5


# ---- Saving turned surfaces and restoring the original ----

CLOSED_MESSAGE = "This file is closed as a whole, and the loader always turns its bodies outward, so its surfaces cannot be flipped."
UNDONE_MESSAGE = "The turned file did not load as turned, so nothing was saved."


@pytest.fixture
def store_after_a_run(store):
    store.add_input("p", "max_volume", "volume.ply", box_bytes([0, 0, 5]))
    store.add_input("p", "test_surfaces", "facades.obj", obj_panels([0, 20]))
    write_fake_chain_run(store, "p", ["1"])
    return store


def _stored(store, file_name="facades.obj"):
    return store.input_file_path("p", "test_surfaces", file_name)


def _kept(store, file_name="facades.obj"):
    return store.open("p") / ORIGINALS_FOLDER / file_name


def _normals_by_surface(path):
    """The face normals of the file as the loader makes them and the surface of each face (inspected as stored)."""
    inspected = inspection.inspect_file(path, "test_surfaces")
    return inspected.mesh.face_normals, inspected.surface_of_face


def test_turned_surfaces_are_saved_and_hold_through_the_loader(store_after_a_run):
    store = store_after_a_run
    revision = store.read_project_json("p").inputs_revision
    assert criterion_status(store, "p")["1"]["preprocessing"] == "current"
    reply = save_turned_surfaces(store, "p", "facades.obj", [0])
    assert reply.file_name == "facades.obj" and reply.original_kept is True and reply.surface_count == 2 and reply.flippable is True
    mesh = load_mesh(str(_stored(store)))
    _, surfaces = _normals_by_surface(_stored(store))
    assert mesh.face_normals[surfaces == 0] == pytest.approx(np.array([[0, 0, -1.0]] * 2), abs=1e-6)
    assert mesh.face_normals[surfaces == 1] == pytest.approx(np.array([[0, 0, 1.0]] * 2), abs=1e-6)
    assert criterion_status(store, "p")["1"]["preprocessing"] == "out_of_date"
    assert stage_status_reply(store, "p").input_changes == []
    project_json = store.read_project_json("p")
    assert project_json.inputs_revision == revision and project_json.changed_files == []
    assert project_json.input_files["test_surfaces"]["facades.obj"] == 4
    assert store.refresh_changed_inputs("p") is False
    joined = load_mesh(str(store.open("p") / "inputs" / "joined" / "test_surfaces_1.ply"))
    assert sorted(joined.face_normals[:, 2].round(6).tolist()) == [-1, -1, 1, 1]


def test_panels_with_coinciding_edges_stay_two_surfaces(store):
    obj = "\n".join(["v 0 0 0", "v 6 0 0", "v 6 6 0", "v 0 6 0", "v 0 0 0", "v 6 0 0", "v 6 0 6", "v 0 0 6", "vn 0 0 1", "vn 0 -1 0",
                     "f 1//1 2//1 3//1", "f 1//1 3//1 4//1", "f 5//2 6//2 7//2", "f 5//2 7//2 8//2"]) + "\n"
    store.add_input("p", "test_surfaces", "corner.obj", obj.encode())
    assert project_inspection(store, "p").files[0].surface_count == 2
    reply = save_turned_surfaces(store, "p", "corner.obj", [1])
    assert reply.surface_count == 2
    normals, surfaces = _normals_by_surface(_stored(store, "corner.obj"))
    assert normals[surfaces == 0] == pytest.approx(np.array([[0, 0, 1.0]] * 2), abs=1e-6)
    assert normals[surfaces == 1] == pytest.approx(np.array([[0, 1.0, 0]] * 2), abs=1e-6)


def test_quads_keep_their_triangle_count(store):
    lines = ["v 0 0 0", "v 4 0 0", "v 4 4 0", "v 0 4 0",
             "v 10 0 0", "v 13 0 0", "v 14 3 0", "v 11.5 5 0", "v 9 3 0",
             "f 1 2 3 4", "f 5 6 7 8 9"]
    store.add_input("p", "test_surfaces", "mixed.obj", ("\n".join(lines) + "\n").encode())
    before = len(load_mesh(str(_stored(store, "mixed.obj"))).faces)
    assert before == 5
    reply = save_turned_surfaces(store, "p", "mixed.obj", [1])
    assert reply.triangle_count == before
    assert len(load_mesh(str(_stored(store, "mixed.obj"))).faces) == before
    assert store.read_project_json("p").input_files["test_surfaces"]["mixed.obj"] == before


def test_a_save_keeps_georeferenced_coordinates(store):
    store.add_input("p", "test_surfaces", "site.obj", obj_panels([0], x_origin=4_500_000.123456, z=12.345678))
    before = load_mesh(str(_stored(store, "site.obj")))
    save_turned_surfaces(store, "p", "site.obj", [0])
    after = load_mesh(str(_stored(store, "site.obj")))
    assert len(after.faces) == len(before.faces)
    assert after.vertices.shape == before.vertices.shape
    assert np.abs(after.vertices[np.lexsort(after.vertices.T)] - before.vertices[np.lexsort(before.vertices.T)]).max() < 1e-6
    assert after.face_normals[:, 2] == pytest.approx([-1, -1], abs=1e-6)


@pytest.mark.parametrize("extension", [".ply", ".stl", ".glb"])
def test_the_other_formats_are_saved_in_their_own_format(store, extension):
    import trimesh
    vertices = [[0, 0, 0], [6, 0, 0], [6, 6, 0], [0, 6, 0], [20, 0, 0], [26, 0, 0], [26, 6, 0], [20, 6, 0]]
    mesh = trimesh.Trimesh(vertices=vertices, faces=[[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], process=False)
    store.add_input("p", "test_surfaces", f"panels{extension}", mesh.export(file_type=extension.lstrip(".")))
    reply = save_turned_surfaces(store, "p", f"panels{extension}", [0])
    assert reply.surface_count == 2 and reply.triangle_count == 4
    normals, surfaces = _normals_by_surface(_stored(store, f"panels{extension}"))
    assert sorted(normals[:, 2].round(6).tolist()) == [-1, -1, 1, 1]
    assert normals[surfaces == 0][:, 2].tolist() == pytest.approx([-1, -1])


def test_a_file_closed_as_a_whole_cannot_be_turned(store):
    store.add_input("p", "test_surfaces", "block.obj", obj_box())
    before = _stored(store, "block.obj").read_bytes()
    with pytest.raises(ProjectError) as refused:
        save_turned_surfaces(store, "p", "block.obj", [0])
    assert refused.value.status_code == 422 and str(refused.value) == CLOSED_MESSAGE
    assert _stored(store, "block.obj").read_bytes() == before
    assert not _kept(store, "block.obj").exists()


def test_a_save_that_the_loader_would_undo_writes_nothing(store_after_a_run, monkeypatch):
    store = store_after_a_run
    before = _stored(store).read_bytes()
    monkeypatch.setattr(inspection, "_write_mesh_in_its_format", lambda mesh, path: Path(path).write_bytes(before))
    with pytest.raises(ProjectError) as undone:
        save_turned_surfaces(store, "p", "facades.obj", [0])
    assert undone.value.status_code == 500 and str(undone.value) == UNDONE_MESSAGE
    assert _stored(store).read_bytes() == before
    assert not _kept(store).exists()
    assert sorted(path.name for path in _stored(store).parent.iterdir()) == ["facades.obj"]
    assert criterion_status(store, "p")["1"]["preprocessing"] == "current"


def test_the_original_is_kept_once_and_restored_byte_for_byte(store_after_a_run):
    store = store_after_a_run
    original = _stored(store).read_bytes()
    save_turned_surfaces(store, "p", "facades.obj", [0])
    first_saved = _stored(store).read_bytes()
    assert first_saved != original and _kept(store).read_bytes() == original
    reply = save_turned_surfaces(store, "p", "facades.obj", [1])
    assert reply.original_kept is True
    assert _stored(store).read_bytes() not in (original, first_saved)
    assert _kept(store).read_bytes() == original
    write_fake_chain_run(store, "p", ["1"])
    assert criterion_status(store, "p")["1"]["preprocessing"] == "current"
    reply = restore_original(store, "p", "facades.obj")
    assert reply.original_kept is False and reply.triangle_count == 4
    assert _stored(store).read_bytes() == original
    assert not _kept(store).exists()
    assert criterion_status(store, "p")["1"]["preprocessing"] == "out_of_date"
    assert stage_status_reply(store, "p").input_changes == []
    assert store.refresh_changed_inputs("p") is False
    with pytest.raises(ProjectError) as nothing_kept:
        restore_original(store, "p", "facades.obj")
    assert nothing_kept.value.status_code == 404


def test_an_upload_with_the_same_name_drops_the_kept_original(store_after_a_run):
    store = store_after_a_run
    save_turned_surfaces(store, "p", "facades.obj", [0])
    assert _kept(store).is_file()
    store.add_criterion_test_surface("p", "1", "facades.obj", obj_panels([0, 20, 40]))
    assert not _kept(store).exists()
    assert project_inspection(store, "p").files[1].original_kept is False


def test_a_discarded_file_drops_its_kept_original(store_after_a_run):
    store = store_after_a_run
    save_turned_surfaces(store, "p", "facades.obj", [0])
    assert _kept(store).is_file()
    store.remove_criterion_test_surface("p", "1", "facades.obj")
    assert not _kept(store).exists()


def test_a_turn_outside_the_surfaces_is_422(store_after_a_run):
    store = store_after_a_run
    before = _stored(store).read_bytes()
    for surfaces in ([2], [-1], [0, 5], []):
        with pytest.raises(ProjectError) as refused:
            save_turned_surfaces(store, "p", "facades.obj", surfaces)
        assert refused.value.status_code == 422
    assert _stored(store).read_bytes() == before and not _kept(store).exists()


def test_a_file_that_is_not_stored_is_404(store_after_a_run):
    with pytest.raises(ProjectError) as refused:
        save_turned_surfaces(store_after_a_run, "p", "nothing.obj", [0])
    assert refused.value.status_code == 404
    with pytest.raises(ProjectError) as refused:
        restore_original(store_after_a_run, "p", "nothing.obj")
    assert refused.value.status_code == 404


def test_the_routes_turn_and_restore(tmp_path):
    client, _ = build_client(tmp_path / "projects")
    create_project(client)
    assert upload(client, "p", "test_surfaces", ("facades.obj", obj_panels([0, 20]))).status_code == 200
    turned = client.post("/api/projects/p/inspect/test_surfaces/facades.obj/turn", json={"surfaces": [1]})
    assert turned.status_code == 200 and turned.json()["original_kept"] is True
    assert client.get("/api/projects/p/inspect").json()["files"][0]["original_kept"] is True
    for body in ({"surfaces": []}, {"surfaces": [9]}, {"surfaces": ["a"]}, {}):
        assert client.post("/api/projects/p/inspect/test_surfaces/facades.obj/turn", json=body).status_code == 422
    assert client.post("/api/projects/p/inspect/test_surfaces/nothing.obj/turn", json={"surfaces": [0]}).status_code == 404
    restored = client.post("/api/projects/p/inspect/test_surfaces/facades.obj/restore")
    assert restored.status_code == 200 and restored.json()["original_kept"] is False
    assert client.post("/api/projects/p/inspect/test_surfaces/facades.obj/restore").status_code == 404


def test_turning_during_a_run_is_409(client_with_blocking_run, projects_folder):
    client, _ = client_with_blocking_run
    stored = projects_folder / "p" / "inputs" / "test_surfaces" / "surface.ply"
    before = stored.read_bytes()
    turn = client.post("/api/projects/p/inspect/test_surfaces/surface.ply/turn", json={"surfaces": [0]})
    assert turn.status_code == 409
    assert client.post("/api/projects/p/inspect/test_surfaces/surface.ply/restore").status_code == 409
    assert stored.read_bytes() == before
    assert not (projects_folder / "p" / ORIGINALS_FOLDER).exists()


# ---- Fix round 1: failures on the way, the reload check, a file replaced by hand ----

def _folder_names(store):
    return sorted(path.name for path in (store.open("p") / "inputs" / "test_surfaces").iterdir())


def _joined(store):
    return store.open("p") / "inputs" / "joined" / "test_surfaces_1.ply"


def test_a_save_that_fails_after_the_replacement_leaves_the_file_as_it_was(store_after_a_run, monkeypatch):
    from urbansolarcarver.local_web_service import stored_files
    store = store_after_a_run
    before, joined_before = _stored(store).read_bytes(), _joined(store).read_bytes()

    def fails(*args):
        raise ProjectError("the joined file could not be built", status_code=422)

    monkeypatch.setattr(stored_files, "build_in_test_surface_file", fails)
    with pytest.raises(ProjectError):
        save_turned_surfaces(store, "p", "facades.obj", [0])
    assert _stored(store).read_bytes() == before
    assert not _kept(store).exists()
    assert _folder_names(store) == ["facades.obj"]
    assert _joined(store).read_bytes() == joined_before
    assert criterion_status(store, "p")["1"]["preprocessing"] == "current"


def test_the_original_stays_when_the_stored_file_cannot_be_put_back(store_after_a_run, monkeypatch):
    from urbansolarcarver.local_web_service import stored_files
    store = store_after_a_run
    stored, before = _stored(store), _stored(store).read_bytes()
    real_replace = os.replace
    replaced_onto_stored = []

    def replace(source, target):
        if Path(target) == stored:
            replaced_onto_stored.append(source)
            if len(replaced_onto_stored) == 2:      # the second move onto the stored file is the rollback
                raise PermissionError("held by another program")
        real_replace(source, target)

    def fails(*args):
        raise ProjectError("the joined file could not be built", status_code=422)

    monkeypatch.setattr(stored_files, "build_in_test_surface_file", fails)
    monkeypatch.setattr(inspection.os, "replace", replace)
    with pytest.raises(PermissionError):
        save_turned_surfaces(store, "p", "facades.obj", [0])
    monkeypatch.undo()
    assert len(replaced_onto_stored) == 2
    assert stored.read_bytes() != before        # the turned file stayed
    assert _kept(store).read_bytes() == before  # so the original did too


def test_a_panel_inverted_next_to_its_neighbour_joins_it_when_turned(store):
    obj = "\n".join(["v 0 0 0", "v 6 0 0", "v 6 6 0", "v 0 6 0", "v 6 0 0", "v 12 0 0", "v 12 6 0", "v 6 6 0",
                     "vn 0 0 1", "vn 0 0 -1",
                     "f 1//1 2//1 3//1", "f 1//1 3//1 4//1", "f 5//2 7//2 6//2", "f 5//2 8//2 7//2"]) + "\n"
    store.add_input("p", "test_surfaces", "row.obj", obj.encode())
    assert project_inspection(store, "p").files[0].surface_count == 2
    normals, surfaces = _normals_by_surface(_stored(store, "row.obj"))
    assert normals[surfaces == 1][:, 2].tolist() == pytest.approx([-1, -1])
    reply = save_turned_surfaces(store, "p", "row.obj", [1])
    assert reply.surface_count == 1
    normals, _ = _normals_by_surface(_stored(store, "row.obj"))
    assert normals[:, 2].tolist() == pytest.approx([1, 1, 1, 1], abs=1e-6)


def test_a_save_that_rounds_the_coordinates_writes_nothing(store, monkeypatch):
    import trimesh
    store.add_input("p", "test_surfaces", "site.obj", obj_panels([0], x_origin=4_500_000.4))
    before = _stored(store, "site.obj").read_bytes()
    real_writer = inspection._write_mesh_in_its_format

    def rounding_writer(mesh, path):
        vertices = mesh.vertices.copy()
        vertices[:, 0] = np.round(vertices[:, 0])
        real_writer(trimesh.Trimesh(vertices=vertices, faces=mesh.faces, process=False), path)

    monkeypatch.setattr(inspection, "_write_mesh_in_its_format", rounding_writer)
    with pytest.raises(ProjectError) as undone:
        save_turned_surfaces(store, "p", "site.obj", [0])
    assert undone.value.status_code == 500 and str(undone.value) == UNDONE_MESSAGE
    assert _stored(store, "site.obj").read_bytes() == before
    assert not _kept(store, "site.obj").exists()
    assert _folder_names(store) == ["site.obj"]


def test_a_file_replaced_by_hand_drops_its_kept_original(store_after_a_run):
    store = store_after_a_run
    save_turned_surfaces(store, "p", "facades.obj", [0])
    assert _kept(store).is_file()
    _overwrite(store, "test_surfaces", "facades.obj", obj_panels([0, 20, 40]))
    assert store.refresh_changed_inputs("p") is True
    assert not _kept(store).exists()
    facades = next(entry for entry in project_inspection(store, "p").files if entry.file_name == "facades.obj")
    assert facades.original_kept is False and facades.surface_count == 3


# ---- Fix round 2: the corner tolerance of the float32 formats ----

def _grid_mesh(x_range, y_range, columns=7, rows=5):
    """An open flat grid of triangles facing up with non-integer coordinates."""
    import trimesh
    xs, ys = np.linspace(*x_range, columns), np.linspace(*y_range, rows)
    vertices = np.array([[x, y, 0.37] for y in ys for x in xs])
    faces = []
    for row in range(rows - 1):
        for column in range(columns - 1):
            first = row * columns + column
            faces += [[first, first + 1, first + columns + 1], [first, first + columns + 1, first + columns]]
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def test_a_glb_from_another_tool_with_odd_coordinates_is_saved(store):
    store.add_input("p", "test_surfaces", "site.glb", _grid_mesh((-37.3, 62.7), (-12.1, 41.9)).export(file_type="glb"))
    before = load_mesh(str(_stored(store, "site.glb")))
    reply = save_turned_surfaces(store, "p", "site.glb", [0])
    assert reply.triangle_count == len(before.faces)
    after = load_mesh(str(_stored(store, "site.glb")))
    assert after.face_normals[:, 2] == pytest.approx(-np.ones(len(after.faces)), abs=1e-6)
    assert np.abs(np.sort(after.vertices, axis=0) - np.sort(before.vertices, axis=0)).max() < 1e-4      # float32 near the offset


def test_an_stl_with_odd_coordinates_is_saved(store):
    store.add_input("p", "test_surfaces", "site.stl", _grid_mesh((4_000.3, 4_100.3), (1_200.1, 1_254.1)).export(file_type="stl"))
    reply = save_turned_surfaces(store, "p", "site.stl", [0])
    assert reply.original_kept is True
    assert load_mesh(str(_stored(store, "site.stl"))).face_normals[:, 2] == pytest.approx(-np.ones(reply.triangle_count), abs=1e-6)
