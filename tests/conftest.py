"""Shared fixtures for UrbanSolarCarver tests."""
import os
import pytest
import numpy as np
from pathlib import Path


@pytest.fixture(scope="session", autouse=True)
def ladybug_weather_folder_of_this_test_process(tmp_path_factory):
    """Give this test process its own Ladybug weather folder.

    ladybug_radiance's SkyMatrix writes its Wea file to
    ``<default_epw_folder>/sky_matrices/<city>.wea`` and then runs gendaymtx
    on it. Every process on the machine shares that path by default, so two
    test processes (pytest -n 8, or another checkout testing at the same
    time) computing different sky matrices for the same city overwrite each
    other's input and get wrong weights. Each pytest-xdist worker has its own
    tmp_path_factory folder.
    """
    from ladybug.config import folders
    shared_folder = folders.default_epw_folder
    folders.default_epw_folder = str(tmp_path_factory.mktemp("ladybug_weather"))
    yield
    folders.default_epw_folder = shared_folder


@pytest.fixture(scope="session", autouse=True)
def each_weather_file_parsed_once_per_test_process():
    """Parse each EPW file content once per test process instead of at every ``EPW(...)`` read.

    The bundled Golden file was parsed about 250 times in a full run (0.23 s each). Ladybug's ``EPW._import_data`` is
    wrapped: the first full read of a given file content parses it and keeps it pickled; every later read of the same
    content unpickles a copy of its own (about 0.02 s), so a test that changes its EPW object or the data collections
    in it cannot change what another test reads. Header-only reads, files without the .epw extension and files that
    cannot be read go to Ladybug's parser as before, and a file that fails to parse is not kept.
    """
    import hashlib
    import pickle
    from ladybug.epw import EPW

    parse_epw_file = EPW._import_data
    parsed_epw_by_content = {}

    def import_data_from_a_parsed_copy(epw, import_header_only=False):
        if import_header_only or not epw.file_path.lower().endswith("epw"):
            return parse_epw_file(epw, import_header_only)
        try:
            content_key = hashlib.sha1(Path(epw.file_path).read_bytes()).digest()
        except OSError:
            return parse_epw_file(epw, import_header_only)
        if content_key not in parsed_epw_by_content:
            parsed = EPW(epw.file_path)
            parse_epw_file(parsed)
            parsed_epw_by_content[content_key] = pickle.dumps(parsed, pickle.HIGHEST_PROTOCOL)
        own_copy = pickle.loads(parsed_epw_by_content[content_key])
        for slot in EPW.__slots__:
            if slot != "_file_path" and hasattr(own_copy, slot):
                setattr(epw, slot, getattr(own_copy, slot))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(EPW, "_import_data", import_data_from_a_parsed_copy)
        yield


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
        pytest.skip("No EPW file found; set USC_EPW_PATH env var to enable integration tests")
    return Path(epw)


@pytest.fixture(scope="session")
def example_project_templates(tmp_path_factory):
    """For the local web service tests: copy_example_project(store, name, example) makes a project from a packaged example."""
    from local_web_test_support import ExampleProjectTemplates
    return ExampleProjectTemplates(tmp_path_factory.mktemp("example_project_templates"))


@pytest.fixture
def project_with_inputs(tmp_path):
    """For the local web service tests: a daylight project with a max volume and a test surface; the store and its name."""
    from local_web_test_support import add_project_with_inputs
    return add_project_with_inputs(tmp_path)


def pytest_collection_modifyitems(config, items):
    """Skip the tests marked ``gpu`` when torch sees no CUDA GPU."""
    import torch
    if torch.cuda.is_available():
        return
    needs_cuda = pytest.mark.skip(reason="needs a CUDA GPU")
    for item in items:
        if "gpu" in item.keywords:
            item.add_marker(needs_cuda)
