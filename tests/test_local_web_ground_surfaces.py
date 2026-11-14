"""Test surfaces drawn on flat ground (ground_surfaces.py, design/test-surfaces-on-ground.md): the mesh from an outline, and the
drawn sets of a project."""
import numpy as np
import pytest
import trimesh

from local_web_test_support import box_bytes, upload

from urbansolarcarver.local_web_service.api_models import GroundOutline
from urbansolarcarver.local_web_service.ground_surfaces import ground_mesh, next_ground_file_name
from urbansolarcarver.local_web_service.project_names import ProjectError

SQUARE = {"points": [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]]}


# ---- The mesh

def test_a_square_makes_two_triangles_facing_up_at_its_elevation():
    mesh = ground_mesh(GroundOutline(points=[[0, 0, 3], [10, 0, 3], [10, 10, 3], [0, 10, 3]]))
    assert np.isclose(mesh.area, 100) and np.allclose(mesh.face_normals, [0, 0, 1]) and np.allclose(mesh.vertices[:, 2], 3)


def test_a_clockwise_outline_with_a_hole_faces_up_and_leaves_the_hole_out():
    mesh = ground_mesh(GroundOutline(points=[[0, 0, 0], [0, 10, 0], [10, 10, 0], [10, 0, 0]],
                                     holes=[[[4, 4, 0], [6, 4, 0], [6, 6, 0], [4, 6, 0]]]))
    assert np.isclose(mesh.area, 96) and np.allclose(mesh.face_normals, [0, 0, 1])


def test_a_concave_outline_keeps_only_its_own_area():
    mesh = ground_mesh(GroundOutline(points=[[0, 0, 0], [60, 0, 0], [60, 20, 0], [20, 20, 0], [20, 50, 0], [0, 50, 0]]))
    assert np.isclose(mesh.area, 60 * 20 + 20 * 30)


@pytest.mark.parametrize("outline, reason", [
    ({"points": [[0, 0, 0], [10, 0, 0], [10, 10, 1]]}, "one elevation"),
    ({"points": [[0, 0, 0], [10, 10, 0], [10, 0, 0], [0, 10, 0]]}, "the outline crosses itself"),
    ({"points": [[0, 0, 0], [0.5, 0, 0], [0.5, 0.5, 0]]}, "less than 1"),
    ({**SQUARE, "holes": [[[8, 8, 0], [12, 8, 0], [12, 12, 0]]]}, "hole 1 is not strictly inside the outline"),
    ({**SQUARE, "holes": [[[2, 2, 0], [5, 2, 0], [5, 5, 0], [2, 5, 0]], [[4, 4, 0], [7, 4, 0], [7, 7, 0]]]}, "hole 1 and hole 2 touch or cross"),
    ({**SQUARE, "holes": [[[2, 2, 0], [5, 5, 0], [5, 2, 0], [2, 5, 0]]]}, "hole 1 crosses itself"),
])
def test_an_outline_the_engine_would_refuse_is_refused_with_the_reason(outline, reason):
    with pytest.raises(ProjectError, match=reason) as refused:
        ground_mesh(GroundOutline(**outline))
    assert refused.value.status_code == 422


def test_file_names_take_the_lowest_free_number():
    assert next_ground_file_name(["ground_1.ply", "GROUND_2.ply", "picked_3.ply"]) == "ground_3.ply"
    assert next_ground_file_name([]) == "ground_1.ply"


# ---- Drawn sets in a project

WIDE = {"points": [[0, 0, 0], [20, 0, 0], [20, 10, 0], [0, 10, 0]]}


def _draw(client, outline, **extra):
    return client.post("/api/projects/p/surface-sets/drawn", json={"outline": outline, **extra})


def _stored(projects_folder, file_name):
    return trimesh.load(str(projects_folder / "p" / "inputs" / "test_surfaces" / file_name), force="mesh")


def test_a_drawn_outline_makes_a_set_named_ground_1(client_with_inputs, projects_folder):
    reply = _draw(client_with_inputs, SQUARE)
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["name"] == "ground_1.ply" and body["shown_name"] == "Ground 1" and body["drawn"] is True and body["picked"] is None
    assert body["triangle_count"] == 2 and np.isclose(_stored(projects_folder, "ground_1.ply").area, 100)
    outline = client_with_inputs.get("/api/projects/p/surface-sets/ground_1.ply/outline").json()
    assert outline == {**SQUARE, "holes": []}
    files = client_with_inputs.get("/api/projects/p").json()["inputs"]["test_surfaces"]
    assert any(file["name"] == "ground_1.ply" and file["drawn"] is True for file in files)


def test_editing_a_drawn_set_rewrites_it_and_joins_its_criteria_again(client_with_inputs, projects_folder):
    client = client_with_inputs
    _draw(client, SQUARE, name="Square")
    assert client.put("/api/projects/p/criteria/1/test-surfaces/ground_1.ply").status_code == 200
    joined = projects_folder / "p" / "inputs" / "joined" / "test_surfaces_1.ply"
    before = trimesh.load(str(joined), force="mesh").area
    reply = _draw(client, WIDE, replace="ground_1.ply")
    assert reply.status_code == 200 and reply.json()["shown_name"] == "Square"
    assert np.isclose(_stored(projects_folder, "ground_1.ply").area, 200)
    assert trimesh.load(str(joined), force="mesh").area == pytest.approx(before + 100)
    assert client.get("/api/projects/p/surface-sets/ground_1.ply/outline").json()["points"] == WIDE["points"]


def test_kinds_do_not_mix(client_with_inputs, projects_folder):
    client = client_with_inputs
    upload(client, "p", "context", ("block.ply", box_bytes([20, 0, 5])))
    assert client.post("/api/projects/p/surface-sets/picked", json={"picks": [{"point": [25, 0, 5], "ray": [-1, 0, 0]}]}).status_code == 200
    _draw(client, SQUARE)
    uploaded = next(file["name"] for file in client.get("/api/projects/p").json()["inputs"]["test_surfaces"]
                    if not file.get("picked") and not file.get("drawn"))
    assert _draw(client, WIDE, replace="picked_1.ply").status_code == 422
    assert _draw(client, WIDE, replace=uploaded).status_code == 422
    assert client.post("/api/projects/p/surface-sets/picked", json={"picks": [{"point": [25, 0, 5], "ray": [-1, 0, 0]}],
                                                                     "replace": "ground_1.ply"}).status_code == 422
    assert client.get("/api/projects/p/surface-sets/picked_1.ply/outline").status_code == 422
    assert client.get("/api/projects/p/surface-sets/nothing.ply/outline").status_code == 404
    assert _draw(client, WIDE, replace="nothing.ply").status_code == 404
    assert np.isclose(_stored(projects_folder, "ground_1.ply").area, 100)


def test_a_refused_outline_writes_nothing(client_with_inputs, projects_folder):
    reply = _draw(client_with_inputs, {"points": [[0, 0, 0], [10, 10, 0], [10, 0, 0], [0, 10, 0]]})
    assert reply.status_code == 422 and "crosses itself" in reply.json()["detail"]
    assert not (projects_folder / "p" / "inputs" / "test_surfaces" / "ground_1.ply").exists()
    names = [file["name"] for file in client_with_inputs.get("/api/projects/p").json()["inputs"]["test_surfaces"]]
    assert "ground_1.ply" not in names


def test_the_name_skips_one_already_shown(client_with_inputs):
    client = client_with_inputs
    uploaded = client.get("/api/projects/p").json()["inputs"]["test_surfaces"][0]["name"]
    client.put(f"/api/projects/p/surface-sets/{uploaded}/name", json={"name": "Ground 1"})
    body = _draw(client, SQUARE).json()
    assert body["name"] == "ground_1.ply" and body["shown_name"] == "Ground 2"
    assert _draw(client, SQUARE, name="ground 1").status_code == 422
