"""Surface sets picked on the surroundings, and the names of surface sets (picked_surfaces.py, design/test-surfaces-on-context.md)."""
import numpy as np
import pytest
import trimesh

from local_web_test_support import box_bytes, upload

# A building 10 m wide centred on (20, 0, 5): its east wall is the plane x = 25, its north wall y = 5
BUILDING = ("block.ply", box_bytes([20, 0, 5]))
EAST = {"point": [25, 0, 5], "ray": [-1, 0, 0]}          # looked at from the east
NORTH = {"point": [20, 5, 5], "ray": [0, -1, 0]}
OFF = {"point": [100, 100, 0], "ray": [0, 0, -1]}


def _stored_mesh(projects_folder, file_name):
    return trimesh.load(str(projects_folder / "p" / "inputs" / "test_surfaces" / file_name), force="mesh")


def _pick(client, picks, **extra):
    return client.post("/api/projects/p/surface-sets/picked", json={"picks": picks, **extra})


@pytest.fixture
def with_building(client_with_inputs):
    assert upload(client_with_inputs, "p", "context", BUILDING).status_code == 200
    return client_with_inputs


def test_a_pick_on_a_wall_makes_a_set_of_that_wall_facing_the_viewer(with_building, projects_folder):
    reply = _pick(with_building, [EAST])
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["name"] == "picked_1.ply" and body["shown_name"] == "Picked 1" and body["picked"] is True
    assert body["triangle_count"] == 2 and body["picks_lost"] is None
    mesh = _stored_mesh(projects_folder, "picked_1.ply")
    assert np.allclose(mesh.face_normals, [1, 0, 0]) and np.allclose(mesh.vertices[:, 0], 25)
    files = with_building.get("/api/projects/p").json()["inputs"]["test_surfaces"]
    assert any(file["name"] == "picked_1.ply" and file["shown_name"] == "Picked 1" for file in files)


def test_a_wall_wound_inward_still_faces_the_side_it_was_clicked_from(client_with_inputs, projects_folder):
    inward = trimesh.creation.box(extents=(10, 10, 10))
    inward.apply_translation([20, 0, 5])
    inward.invert()
    upload(client_with_inputs, "p", "context", ("inward.ply", inward.export(file_type="ply")))
    _pick(client_with_inputs, [EAST])
    assert np.allclose(_stored_mesh(projects_folder, "picked_1.ply").face_normals, [1, 0, 0])


def test_two_picks_of_one_wall_count_once_and_a_corner_is_two_pieces(with_building, projects_folder):
    assert _pick(with_building, [EAST, {"point": [25, 3, 8], "ray": [-1, 0, 0]}]).json()["triangle_count"] == 2
    corner = _pick(with_building, [EAST, NORTH]).json()
    assert corner["name"] == "picked_2.ply" and corner["shown_name"] == "Picked 2" and corner["triangle_count"] == 4


def test_a_facade_of_many_coplanar_triangles_is_one_piece(client_with_inputs, projects_folder):
    fine = trimesh.creation.box(extents=(10, 10, 10)).subdivide().subdivide()
    fine.apply_translation([20, 0, 5])
    upload(client_with_inputs, "p", "context", ("fine.ply", fine.export(file_type="ply")))
    body = _pick(client_with_inputs, [EAST]).json()
    assert body["triangle_count"] == 32                                    # 2 triangles, each divided in four twice
    assert np.allclose(_stored_mesh(projects_folder, "picked_1.ply").vertices[:, 0], 25)


def test_corners_kept_apart_by_their_own_normals_still_join_a_face(with_building, projects_folder):
    # The joined surroundings as some files leave them: every triangle with its own corners, each with a normal, which a reader keeps apart
    loose = trimesh.creation.box(extents=(10, 10, 10))
    loose.apply_translation([20, 0, 5])
    loose.unmerge_vertices()
    rng = np.random.default_rng(1)
    loose.vertices += rng.uniform(-2e-6, 2e-6, loose.vertices.shape)          # a few micrometres apart, as modelling tools leave them
    tilted = loose.vertex_normals + rng.uniform(-1e-2, 1e-2, loose.vertices.shape)     # no two corners alike
    loose.vertex_normals = tilted / np.linalg.norm(tilted, axis=1)[:, None]
    (projects_folder / "p" / "inputs" / "joined" / "context.ply").write_bytes(trimesh.exchange.ply.export_ply(loose, vertex_normal=True))
    assert _pick(with_building, [EAST]).json()["triangle_count"] == 2


def test_picks_off_the_surroundings_are_counted_and_none_on_it_is_refused(with_building):
    assert _pick(with_building, [EAST, OFF]).json()["picks_lost"] == 1
    reply = _pick(with_building, [OFF])
    assert reply.status_code == 422 and "None of the picks" in reply.json()["detail"]


def test_without_surroundings_picking_is_refused(client_with_inputs):
    assert _pick(client_with_inputs, [EAST]).status_code == 404


def test_new_picks_replace_a_picked_set_and_the_criteria_using_it_are_joined_again(with_building, projects_folder):
    client = with_building
    _pick(client, [EAST])
    assert client.put("/api/projects/p/criteria/1/test-surfaces/picked_1.ply").status_code == 200
    joined = projects_folder / "p" / "inputs" / "joined" / "test_surfaces_1.ply"
    before = trimesh.load(str(joined), force="mesh").area
    reply = _pick(client, [EAST, NORTH], replace="picked_1.ply")
    assert reply.status_code == 200 and reply.json()["triangle_count"] == 4 and reply.json()["shown_name"] == "Picked 1"
    assert trimesh.load(str(joined), force="mesh").area == pytest.approx(before + 100)
    assert client.get("/api/projects/p/surface-sets/picked_1.ply/picks").json()["picks"] == [EAST, NORTH]


def test_an_uploaded_set_takes_no_picks_but_can_be_renamed(with_building):
    client = with_building
    uploaded = client.get("/api/projects/p").json()["inputs"]["test_surfaces"][0]["name"]
    assert _pick(client, [EAST], replace=uploaded).status_code == 422
    assert client.get(f"/api/projects/p/surface-sets/{uploaded}/picks").status_code == 422
    reply = client.put(f"/api/projects/p/surface-sets/{uploaded}/name", json={"name": "  South windows  "})
    assert reply.status_code == 200 and reply.json()["shown_name"] == "South windows" and reply.json()["picked"] is None


def test_a_name_another_set_has_or_an_empty_one_is_refused(with_building):
    client = with_building
    _pick(client, [EAST], name="Facades")
    _pick(client, [NORTH])
    assert client.put("/api/projects/p/surface-sets/picked_2.ply/name", json={"name": "facades"}).status_code == 422
    assert client.put("/api/projects/p/surface-sets/picked_2.ply/name", json={"name": "  "}).status_code == 422
    assert _pick(client, [NORTH], name="FACADES").status_code == 422


def test_a_picked_set_follows_the_surroundings_and_counts_the_picks_that_found_no_face(with_building, projects_folder):
    client = with_building
    _pick(client, [EAST, NORTH])
    # The building is replaced by one 2 m narrower in x: the east wall moves to x = 24, the north wall stays
    narrower = trimesh.creation.box(extents=(8, 10, 10))
    narrower.apply_translation([20, 0, 5])
    upload(client, "p", "context", ("block.ply", narrower.export(file_type="ply")))
    files = {file["name"]: file for file in client.get("/api/projects/p").json()["inputs"]["test_surfaces"]}
    assert files["picked_1.ply"]["picks_lost"] == 1 and files["picked_1.ply"]["triangle_count"] == 2
    assert np.allclose(_stored_mesh(projects_folder, "picked_1.ply").face_normals, [0, 1, 0])


def test_sets_are_added_and_deleted_as_inputs_of_the_project_and_a_set_in_use_is_kept(with_building):
    client = with_building
    reply = client.post("/api/projects/p/inputs/test_surfaces", files={"file": ("roof.ply", box_bytes([0, 30, 0], extents=(4, 4, 0.1)))})
    assert reply.status_code == 200, reply.text
    assert {file["name"]: file["used_by"] for file in reply.json()["files"]}["roof.ply"] == []
    client.put("/api/projects/p/criteria/1/test-surfaces/roof.ply")
    refused = client.delete("/api/projects/p/inputs/test_surfaces/roof.ply")
    assert refused.status_code == 422 and "Switch it off there first" in refused.json()["detail"]
    client.delete("/api/projects/p/criteria/1/test-surfaces/roof.ply")
    assert client.delete("/api/projects/p/inputs/test_surfaces/roof.ply").status_code == 200
    assert "roof.ply" not in {file["name"] for file in client.get("/api/projects/p").json()["inputs"]["test_surfaces"]}


# --- Touching pieces stay apart for the engine: its loader merges corners only where their normals agree (write_joined_ply)

from urbansolarcarver.io import load_mesh, save_mesh  # noqa: E402
from urbansolarcarver.local_web_service.projects import ProjectStore  # noqa: E402
from urbansolarcarver.local_web_service.stored_files import record_stored_file, refresh_changed_inputs  # noqa: E402

# A single-sheet wall x = 0 (z 0 to 5) with a canopy z = 5 over its east side (x 0 to 5): not a closed body
SHEET_L = trimesh.Trimesh([[0, 0, 0], [0, 10, 0], [0, 10, 5], [0, 0, 5], [5, 0, 5], [5, 10, 5]], [[0, 1, 2], [0, 2, 3], [3, 2, 5], [3, 5, 4]])
WALL_FROM_EAST = {"point": [0, 5, 2], "ray": [-1, 0, 0]}
CANOPY_FROM_ABOVE = {"point": [2.5, 5, 5], "ray": [0, 0, -1]}


def _surfaces_as_the_engine_reads(projects_folder, file_name):
    """The normal of each connected surface of a stored set as load_mesh reads it, sorted."""
    mesh = load_mesh(str(projects_folder / "p" / "inputs" / "test_surfaces" / file_name))
    return sorted(np.round(part.face_normals.mean(axis=0), 6).tolist() for part in mesh.split(only_watertight=False))


def test_two_walls_picked_at_a_corner_stay_two_surfaces_for_the_engine(with_building, projects_folder):
    _pick(with_building, [EAST, NORTH])
    assert _surfaces_as_the_engine_reads(projects_folder, "picked_1.ply") == [[0, 1, 0], [1, 0, 0]]


def test_pieces_seen_from_opposite_sides_of_one_sheet_each_keep_the_side_they_were_clicked_from(client_with_inputs, projects_folder):
    upload(client_with_inputs, "p", "context", ("sheet.ply", SHEET_L.export(file_type="ply")))
    _pick(client_with_inputs, [WALL_FROM_EAST, CANOPY_FROM_ABOVE])
    assert _surfaces_as_the_engine_reads(projects_folder, "picked_1.ply") == [[0, 0, 1], [1, 0, 0]]


def test_a_picked_set_written_with_its_pieces_joined_is_built_again_once(with_building, projects_folder):
    _pick(with_building, [EAST, NORTH])
    store = ProjectStore(projects_folder)
    path = projects_folder / "p" / "inputs" / "test_surfaces" / "picked_1.ply"
    stored = _stored_mesh(projects_folder, "picked_1.ply")
    save_mesh(trimesh.Trimesh(stored.vertices, stored.faces, process=True), str(path))     # as sets were written before: corners merged
    project_json = store.read_project_json("p")
    record_stored_file(project_json, "test_surfaces", "picked_1.ply", path)
    store.write_project_json("p", project_json)
    assert len(_surfaces_as_the_engine_reads(projects_folder, "picked_1.ply")) == 1
    refresh_changed_inputs(store, "p")
    assert _surfaces_as_the_engine_reads(projects_folder, "picked_1.ply") == [[0, 1, 0], [1, 0, 0]]
    modified = path.stat().st_mtime_ns
    refresh_changed_inputs(store, "p")
    assert path.stat().st_mtime_ns == modified                       # once: a set written with its pieces apart is left alone
