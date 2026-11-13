"""Drawn context blocks (design/context-blocks.md): the model, its checks and volumes, the joined context, saving and the routes."""
from urbansolarcarver.local_web_service.api_models import ContextBlockJson, ProjectJson
from urbansolarcarver.local_web_service.context_blocks import block_meshes, refused_blocks


def square(x0, y0, side=10.0, z=0.0):
    return [[x0, y0, z], [x0 + side, y0, z], [x0 + side, y0 + side, z], [x0, y0 + side, z]]


def block(name, points, height=12.0, holes=()):
    return ContextBlockJson(name=name, points=points, height=height, holes=list(holes))


# --- Task 1: the model, its checks and its volumes

def test_a_square_block_makes_a_closed_volume_from_its_lowest_vertex_up():
    points = square(0, 0)
    points[2][2] = 1.0          # one vertex higher: the top is the lowest vertex plus the height
    (mesh,) = block_meshes([block("Block 1", points, height=12.0)])
    assert mesh.is_watertight
    assert mesh.bounds[0][2] <= 0.0 and abs(mesh.bounds[1][2] - 12.0) < 1e-9


def test_blocks_that_overlap_are_refused_and_touching_ones_are_not():
    a, b, c = block("Block 1", square(0, 0)), block("Block 2", square(5, 0)), block("Block 3", square(10, 0))
    assert refused_blocks([a, b]) == ["Block 2 overlaps Block 1."]
    assert refused_blocks([a, c]) == []


def test_a_block_wholly_inside_another_is_an_overlap_too():
    assert refused_blocks([block("Block 1", square(0, 0, 20)), block("Block 2", square(5, 5, 5))]) == ["Block 2 overlaps Block 1."]


def test_a_repeated_name_is_refused_whatever_its_letter_case():
    assert refused_blocks([block("Block 1", square(0, 0)), block("block 1", square(20, 0))]) == ["Two blocks are named block 1."]


def test_a_self_crossing_outline_is_refused_with_its_block_name():
    bow_tie = [[0, 0, 0], [10, 10, 0], [10, 0, 0], [0, 10, 0]]
    reasons = refused_blocks([block("Block 1", bow_tie)])
    assert len(reasons) == 1 and reasons[0].startswith("Block 1: ")


def test_a_project_json_without_blocks_reads_as_before():
    assert ProjectJson.model_validate({"name": "p", "created": "2026-11-13T00:00:00+00:00"}).context_blocks == []


# --- Task 2: the joined context holds the blocks on every path

import os  # noqa: E402

import trimesh  # noqa: E402
import yaml  # noqa: E402
from local_web_test_support import box_bytes  # noqa: E402
from urbansolarcarver.local_web_service.projects import ProjectStore  # noqa: E402

BLOCK_FACES = len(block_meshes([block("Block 1", square(100, 100))])[0].faces)
TOWN = box_bytes([0, 0, 5])
TOWN_FACES = 12


def store_with_a_block(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    store.create("p", "daylight")
    project_json = store.read_project_json("p")
    project_json.context_blocks = [block("Block 1", square(100, 100))]
    store.write_project_json("p", project_json)
    return store


def joined_context_faces(store):
    path = store.open("p") / "inputs" / "joined" / "context.ply"
    return len(trimesh.load(path, process=False).faces) if path.is_file() else 0


def context_path_in_config(store):
    return "context_path" in yaml.safe_load((store.open("p") / "config.yaml").read_text(encoding="utf-8"))


def test_adding_a_context_file_keeps_the_blocks_in_the_joined_context(tmp_path):
    store = store_with_a_block(tmp_path)
    store.add_input("p", "context", "town.ply", TOWN)
    assert joined_context_faces(store) == TOWN_FACES + BLOCK_FACES
    assert store.input_file_path("p", "context", "town.ply").read_bytes() == TOWN


def test_removing_the_last_context_file_leaves_the_blocks_and_the_context_path(tmp_path):
    store = store_with_a_block(tmp_path)
    store.add_input("p", "context", "town.ply", TOWN)
    store.remove_input("p", "context", "town.ply")
    assert joined_context_faces(store) == BLOCK_FACES
    assert context_path_in_config(store)


def test_a_context_file_changed_in_the_folder_is_joined_again_with_the_blocks(tmp_path):
    store = store_with_a_block(tmp_path)
    store.add_input("p", "context", "town.ply", TOWN)
    path = store.input_file_path("p", "context", "town.ply")
    old_time = path.stat().st_mtime_ns
    path.write_bytes(box_bytes([0, 0, 5], extents=(20, 20, 10)))
    os.utime(path, ns=(old_time + 10 ** 9, old_time + 10 ** 9))
    store.refresh_changed_inputs("p")
    assert joined_context_faces(store) == TOWN_FACES + BLOCK_FACES
    assert trimesh.load(store.open("p") / "inputs" / "joined" / "context.ply").bounds[1][0] > 9.0     # the new file's box


# --- Task 3: saving blocks, and the routes

import pytest  # noqa: E402
from local_web_test_support import build_client, create_project, write_fake_chain_run  # noqa: E402
from urbansolarcarver.local_web_service.context_blocks import save_context_blocks  # noqa: E402
from urbansolarcarver.local_web_service.projects import ProjectError  # noqa: E402
from urbansolarcarver.local_web_service.stage_records import stage_status_reply  # noqa: E402

FACADE_OBJ = b"v 0 -20 0\nv 10 -20 0\nv 10 -20 10\nv 0 -20 10\nf 1 2 3\nf 1 3 4\n"


def empty_store(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    store.create("p", "daylight")
    return store


def test_saving_a_block_alone_writes_the_joined_context_and_the_context_path(tmp_path):
    store = empty_store(tmp_path)
    reply = save_context_blocks(store, "p", [block("Block 1", square(100, 100))])
    assert [entry.name for entry in reply.blocks] == ["Block 1"] and reply.has_mesh
    assert joined_context_faces(store) == BLOCK_FACES and context_path_in_config(store)
    assert (store.open("p") / "inputs" / "joined" / "context_blocks.ply").is_file()


def test_removing_the_last_block_without_files_removes_the_joined_context_and_the_path(tmp_path):
    store = empty_store(tmp_path)
    save_context_blocks(store, "p", [block("Block 1", square(100, 100))])
    reply = save_context_blocks(store, "p", [])
    assert reply.blocks == [] and not reply.has_mesh
    assert joined_context_faces(store) == 0 and not context_path_in_config(store)
    assert not (store.open("p") / "inputs" / "joined" / "context_blocks.ply").exists()


def test_a_refused_list_stores_nothing_and_names_every_problem(tmp_path):
    store = empty_store(tmp_path)
    with pytest.raises(ProjectError) as refused:
        save_context_blocks(store, "p", [block("Block 1", square(0, 0)), block("Block 2", square(5, 0)), block("block 2", square(50, 0))])
    assert refused.value.status_code == 422
    assert "Block 2 overlaps Block 1." in str(refused.value) and "Two blocks are named block 2." in str(refused.value)
    assert store.read_project_json("p").context_blocks == [] and joined_context_faces(store) == 0


def test_a_block_change_puts_the_criteria_out_of_date_and_leaves_the_context_files_unchanged(tmp_path):
    store = empty_store(tmp_path)
    store.add_input("p", "max_volume", "volume.ply", box_bytes([5, 5, 5]))
    store.add_criterion_test_surface("p", "1", "facades.obj", FACADE_OBJ)
    store.add_input("p", "context", "town.ply", TOWN)
    write_fake_chain_run(store, "p", ["1"])
    assert stage_status_reply(store, "p").stages["preprocessing"] == "current"
    revision = store.read_project_json("p").inputs_revision
    save_context_blocks(store, "p", [block("Block 1", square(100, 100))])
    assert store.read_project_json("p").inputs_revision > revision
    assert stage_status_reply(store, "p").stages["preprocessing"] == "out_of_date"
    assert store.input_file_path("p", "context", "town.ply").read_bytes() == TOWN


def test_the_routes_store_list_and_serve_the_blocks_mesh(tmp_path):
    client, _ = build_client(tmp_path / "projects")
    create_project(client)
    body = {"blocks": [{"name": "Block 1", "points": square(100, 100), "height": 12}]}
    assert client.put("/api/projects/p/context-blocks", json=body).status_code == 200
    listed = client.get("/api/projects/p/context-blocks").json()
    assert [entry["name"] for entry in listed["blocks"]] == ["Block 1"] and listed["has_mesh"] is True
    mesh = client.get("/api/projects/p/context-blocks/mesh")
    assert mesh.status_code == 200 and mesh.content.startswith(b"ply")
    overlapping = {"blocks": [*body["blocks"], {"name": "Block 2", "points": square(105, 100), "height": 8}]}
    refused = client.put("/api/projects/p/context-blocks", json=overlapping)
    assert refused.status_code == 422 and "Block 2 overlaps Block 1." in refused.json()["detail"]
    assert client.put("/api/projects/p/context-blocks", json={"blocks": []}).status_code == 200
    assert client.get("/api/projects/p/context-blocks/mesh").status_code == 404
