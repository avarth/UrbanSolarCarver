"""The inspection of the input files: a summary of each mesh file and the geometry of the test surfaces (inspection.py)."""
import json
import os
import struct
import time

import numpy as np
import pytest

from local_web_test_support import GOLDEN_EPW, box_bytes
from test_local_web_server import build_client, create_project, upload
from urbansolarcarver.local_web_service import inspection
from urbansolarcarver.local_web_service.projects import ProjectStore
from urbansolarcarver.local_web_service.inspection import ORIGINALS_FOLDER, inspection_geometry, project_inspection

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
