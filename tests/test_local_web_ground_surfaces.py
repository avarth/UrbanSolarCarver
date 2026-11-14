"""Test surfaces drawn on flat ground (ground_surfaces.py, design/test-surfaces-on-ground.md): the mesh from an outline, and the
drawn sets of a project."""
import numpy as np
import pytest

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
