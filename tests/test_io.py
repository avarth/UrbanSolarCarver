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
