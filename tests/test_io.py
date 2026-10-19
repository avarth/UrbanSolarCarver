"""Mesh loading and saving (io.py)."""
import numpy as np
import pytest
import trimesh

from urbansolarcarver.errors import InputError
from urbansolarcarver.io import load_mesh, save_mesh


def test_missing_file_is_an_input_error(tmp_path):
    with pytest.raises(InputError, match="not found"):
        load_mesh(str(tmp_path / "absent.ply"))


def test_file_without_triangles_is_an_input_error(tmp_path):
    path = tmp_path / "points_only.ply"
    trimesh.points.PointCloud(np.random.rand(10, 3)).export(str(path))
    with pytest.raises(InputError, match="no triangle geometry"):
        load_mesh(str(path))


def test_unreadable_file_is_an_input_error(tmp_path):
    path = tmp_path / "corrupt.ply"
    path.write_bytes(b"ply\nformat binary_little_endian 1.0\nelement vertex 3\n\x00\x01garbage")
    with pytest.raises(InputError, match="corrupt.ply"):
        load_mesh(str(path))


def test_inside_out_closed_mesh_is_turned_outward(tmp_path):
    box = trimesh.creation.box(extents=(2, 2, 2))
    box.invert()
    assert box.volume < 0
    path = tmp_path / "inverted.ply"
    save_mesh(box, str(path))
    loaded = load_mesh(str(path))
    assert loaded.volume > 0


def test_two_closed_bodies_one_inverted(tmp_path):
    a = trimesh.creation.box(extents=(1, 1, 1))
    b = trimesh.creation.box(extents=(1, 1, 1))
    b.apply_translation((3, 0, 0))
    b.invert()
    path = tmp_path / "pair.ply"
    save_mesh(trimesh.util.concatenate([a, b]), str(path))
    loaded = load_mesh(str(path))
    assert all(body.volume > 0 for body in loaded.split(only_watertight=True))


def test_open_surface_keeps_its_side(tmp_path):
    quad = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
                           faces=[[0, 1, 2], [0, 2, 3]])
    path = tmp_path / "quad.ply"
    save_mesh(quad, str(path))
    np.testing.assert_allclose(load_mesh(str(path)).face_normals[:, 2], 1.0)


def _georeferenced_box():
    box = trimesh.creation.box(extents=(30.0, 12.0, 20.0))
    box.apply_translation((500000.37, 4200000.61, 10.0))     # float32 spacing: 0.03 m at x, 0.5 m at y
    return box


def test_glb_keeps_georeferenced_coordinates_by_placing_the_offset_in_the_node(tmp_path):
    box = _georeferenced_box()
    path = tmp_path / "box.glb"
    save_mesh(box, str(path))
    loaded = trimesh.load(str(path), force="mesh", process=False)
    assert np.abs(np.sort(loaded.vertices, axis=0) - np.sort(box.vertices, axis=0)).max() < 1e-4
    scene = trimesh.load(str(path))
    transform, geometry = scene.graph[scene.graph.nodes_geometry[0]]
    assert np.abs(transform[:2, 3]).max() > 1e5                            # the offset, a double in the JSON
    assert np.abs(scene.geometry[geometry].vertices).max() < 100.0        # float32 vertices near the origin


@pytest.mark.parametrize("name", ["box.stl", "box.glb", "box.ply"])
def test_only_stl_warns_that_georeferenced_coordinates_are_rounded_to_float32(tmp_path, name):
    import warnings
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        save_mesh(_georeferenced_box(), str(tmp_path / name))
    rounded = [str(w.message) for w in caught if "float32" in str(w.message)]
    assert len(rounded) == (1 if name.endswith(".stl") else 0)
    assert all(name in message for message in rounded)


def test_stl_near_the_origin_does_not_warn(tmp_path):
    import warnings
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        save_mesh(trimesh.creation.box(extents=(30.0, 12.0, 20.0)), str(tmp_path / "box.stl"))
    assert not [w for w in caught if "float32" in str(w.message)]
