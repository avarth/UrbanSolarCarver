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


NOT_SLOW_LIMIT_SECONDS = 1.0
_not_slow_tests_over_the_limit = []     # (seconds, test id), filled in the process that writes the terminal summary


def pytest_runtest_logreport(report):
    """Note each test outside ``slow`` whose body ran longer than NOT_SLOW_LIMIT_SECONDS.

    With pytest-xdist the reports of the workers reach the controller too, so it notes them all.
    """
    if report.when == "call" and "slow" not in report.keywords and report.duration > NOT_SLOW_LIMIT_SECONDS:
        _not_slow_tests_over_the_limit.append((report.duration, report.nodeid))


def pytest_terminal_summary(terminalreporter, config):
    """List the tests outside ``slow`` that ran over the limit: mark them slow or make them faster.

    Times grow by about half under -n 8, so a test listed only in a parallel run may be fine on its own.
    """
    if hasattr(config, "workerinput") or not _not_slow_tests_over_the_limit:
        return
    terminalreporter.section(f"tests not marked slow that ran over {NOT_SLOW_LIMIT_SECONDS:g} s")
    for seconds, nodeid in sorted(_not_slow_tests_over_the_limit, reverse=True):
        terminalreporter.write_line(f"{seconds:6.2f}s  {nodeid}")


def pytest_collection_modifyitems(config, items):
    """Skip the tests marked ``gpu`` when torch sees no CUDA GPU."""
    import torch
    if torch.cuda.is_available():
        return
    needs_cuda = pytest.mark.skip(reason="needs a CUDA GPU")
    for item in items:
        if "gpu" in item.keywords:
            item.add_marker(needs_cuda)
