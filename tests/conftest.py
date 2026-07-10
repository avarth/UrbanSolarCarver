"""Shared fixtures for UrbanSolarCarver tests."""
import os
import pytest
import numpy as np
from pathlib import Path


@pytest.fixture
def tiny_cube_mesh():
    """A minimal watertight cube mesh (8 vertices, 12 faces) for smoke tests."""
    import trimesh
    return trimesh.creation.box(extents=(10.0, 10.0, 10.0))


@pytest.fixture
def tiny_surface_mesh():
    """A small horizontal quad as a test surface (facing +Z)."""
    import trimesh
    verts = np.array([
        [-3.0, -3.0, 0.0],
        [ 3.0, -3.0, 0.0],
        [ 3.0,  3.0, 0.0],
        [-3.0,  3.0, 0.0],
    ], dtype=np.float32)
    faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)
    return trimesh.Trimesh(vertices=verts, faces=faces)


@pytest.fixture
def tmp_mesh_files(tmp_path, tiny_cube_mesh, tiny_surface_mesh):
    """Save cube and surface meshes to tmp_path and return paths."""
    vol_path = tmp_path / "max_volume.ply"
    srf_path = tmp_path / "test_surface.ply"
    tiny_cube_mesh.export(str(vol_path))
    tiny_surface_mesh.export(str(srf_path))
    return vol_path, srf_path


@pytest.fixture
def example_epw_path():
    """Return path to a real EPW file, else skip the test.

    Uses ``USC_EPW_PATH`` if set, otherwise the NREL TMY3 file bundled in
    ``examples/weather/``.
    """
    from _epw import resolve_epw
    epw = resolve_epw()
    if not epw:
        pytest.skip("No EPW file found — set USC_EPW_PATH env var to enable integration tests")
    return Path(epw)
