"""Shared fixtures for UrbanSolarCarver tests."""
import os
import shutil
import pytest
from pathlib import Path


@pytest.fixture
def tiny_cube_mesh():
    """A minimal watertight cube mesh (8 vertices, 12 faces), z -5 to 5, for smoke tests (_stage_scene.py)."""
    from _stage_scene import cube_volume
    return cube_volume()


@pytest.fixture
def tiny_surface_mesh():
    """A small horizontal quad as a test surface, 1 m under tiny_cube_mesh and facing up into it (_stage_scene.py)."""
    from _stage_scene import surface_under_cube
    return surface_under_cube()


@pytest.fixture
def tmp_mesh_files(tmp_path, tiny_cube_mesh, tiny_surface_mesh):
    """Save cube and surface meshes to tmp_path and return paths."""
    vol_path = tmp_path / "max_volume.ply"
    srf_path = tmp_path / "test_surface.ply"
    tiny_cube_mesh.export(str(vol_path))
    tiny_surface_mesh.export(str(srf_path))
    return vol_path, srf_path


@pytest.fixture(scope="session")
def example_epw_path():
    """Return path to a real EPW file, else skip the test: the one way a test that needs a weather file skips without one.

    Uses ``USC_EPW_PATH`` if set, otherwise the NREL TMY3 file bundled in
    ``examples/weather/`` (_epw.py). A test that reads the bundled file itself uses ``_epw.BUNDLED_EPW``.
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


@pytest.fixture(autouse=True)
def no_real_recycle_bin(monkeypatch):
    """What the local web service sends to the recycle bin (a removed project, a test surface file no criterion uses) is
    removed instead, so a test run never fills the recycle bin of this computer. A test that checks the moves gives send2trash
    its own FakeRecycleBin (local_web_test_support.py)."""
    try:
        import send2trash
    except ImportError:     # the [ui] extra is not installed: nothing sends anything to the recycle bin
        return

    def remove(path):
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    monkeypatch.setattr(send2trash, "send2trash", remove)


@pytest.fixture(autouse=True)
def no_real_home_folder(tmp_path_factory, monkeypatch):
    """Every test has a home folder of its own, so none reads or writes the user's ~/.urbansolarcarver (the typical building
    library, the preferences, the daemon key) or ~/UrbanSolarCarver/projects. A test that looks into the home folder asks
    for it by its own fixture (home_folder)."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def home_folder(no_real_home_folder):
    """The home folder of this test (no_real_home_folder), for a test that reads or writes in it."""
    assert Path.home() == no_real_home_folder
    return no_real_home_folder


def pytest_configure(config):
    """Warp finds its kernel cache from the user's folders: with the home folder moved (no_real_home_folder) it would make a
    new cache in the working folder (an NVIDIA folder in the checkout) and compile every kernel again. Each test process
    pins it first, to a folder of the tests' own, so it reads nothing of Warp's internals, which move between versions."""
    os.environ.setdefault("WARP_CACHE_PATH", str(Path.home() / ".cache" / "urbansolarcarver-tests" / "warp"))


@pytest.fixture
def project_with_inputs(tmp_path):
    """For the local web service tests: a daylight project with a max volume and a test surface; the store and its name."""
    from local_web_test_support import add_project_with_inputs
    return add_project_with_inputs(tmp_path)


@pytest.fixture
def projects_folder(tmp_path):
    """For the local web service tests: the projects folder of the service that ``client`` and the fixtures below serve."""
    return tmp_path / "projects"


@pytest.fixture
def client(projects_folder):
    """For the local web service tests: a TestClient of a service whose engine is the fake (local_web_test_support.build_client)."""
    from local_web_test_support import build_client
    return build_client(projects_folder)[0]


@pytest.fixture
def client_with_inputs(client):
    """``client`` with a daylight project 'p' that has a max volume and a test surface."""
    from local_web_test_support import create_project_with_inputs
    create_project_with_inputs(client)
    return client


@pytest.fixture
def client_with_blocking_run(projects_folder):
    """A project 'p' whose run has started and waits until it is cancelled; yields the client and the run id."""
    from local_web_test_support import WaitsForCancel, build_client, create_project_with_inputs, start_run
    handler = WaitsForCancel()
    client, worker = build_client(projects_folder, handle_request=handler)
    create_project_with_inputs(client)
    run_id = start_run(client)["run_id"]
    assert handler.started.wait(10)
    yield client, run_id
    worker.cancel(run_id)
    worker.run_state(run_id).wait_for_events(10 ** 9, 10)     # returns when the run has ended


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
