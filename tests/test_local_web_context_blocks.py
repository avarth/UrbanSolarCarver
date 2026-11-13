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
