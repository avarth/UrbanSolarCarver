"""Project folders, names and project.json of the local web service."""
import threading
import warnings
from pathlib import Path

import numpy as np
import pytest
import trimesh
import yaml
from local_web_test_support import wait_until_finished

from urbansolarcarver.errors import ConfigError
from urbansolarcarver.io import load_mesh
from urbansolarcarver.run_context import RunContext, run_context
from urbansolarcarver.surface_sampling import discretize_surface_with_normals

from urbansolarcarver.local_web_service import projects
from urbansolarcarver.local_web_service.projects import SERVICE_PATHS, ProjectError, ProjectStore, sanitize_file_name
from urbansolarcarver.local_web_service.server import EXAMPLE_PROJECTS_FOLDER, EXAMPLE_WEATHER_FILE_NAME, _read_examples

GOLDEN_EPW = Path(__file__).resolve().parent.parent / "examples" / "weather" / "USA_CO_Golden-NREL.724666_TMY3.epw"


@pytest.mark.parametrize("bad", ["", "   ", "../x", "a/b", "a\\b", ".hidden", "x" * 65, "naïve"])
def test_invalid_project_names_are_rejected_without_writing(tmp_path, bad):
    store = ProjectStore(tmp_path / "projects")
    with pytest.raises(ProjectError) as err:
        store.create(bad, "time-based")
    assert err.value.status_code == 422
    assert not any(p for p in tmp_path.rglob("*") if p.is_file())


WINDOWS_DEVICE_NAMES = ["CON", "PRN", "AUX", "NUL", *(f"COM{digit}" for digit in range(1, 10)), *(f"LPT{digit}" for digit in range(1, 10))]


@pytest.mark.parametrize("device_name", WINDOWS_DEVICE_NAMES)
def test_windows_device_names_are_not_project_names_in_any_letter_case(tmp_path, device_name):
    store = ProjectStore(tmp_path / "projects")
    for bad in (device_name, device_name.lower(), device_name.capitalize(), f" {device_name} "):
        with pytest.raises(ProjectError) as err:
            store.create(bad, "time-based")
        assert err.value.status_code == 422 and "device name" in str(err.value)
    assert not any(p for p in tmp_path.rglob("*") if p.is_file())


@pytest.mark.parametrize("fine", ["Console", "COM10", "COM0", "LPT", "nul 2", "my-con", "Aux_1"])
def test_names_that_only_contain_a_device_name_are_project_names(tmp_path, fine):
    assert projects.validate_project_name(fine) == fine


def test_create_makes_the_folder_layout_and_project_json(tmp_path):
    store = ProjectStore(tmp_path)
    folder = store.create("Block 7", "time-based")
    for sub in ("inputs/max_volume", "inputs/test_surfaces", "inputs/joined", "run"):
        assert (folder / sub).is_dir()
    data = store.read_project_json("Block 7")
    assert data.name == "Block 7" and data.inputs_revision == 1 and data.stage_records == {}


def test_create_twice_is_a_conflict_and_open_unknown_is_not_found(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("a", "time-based")
    with pytest.raises(ProjectError) as err:
        store.create("a", "time-based")
    assert err.value.status_code == 409
    with pytest.raises(ProjectError) as err:
        store.open("b")
    assert err.value.status_code == 404


def test_list_returns_projects_sorted_by_name(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("b", "time-based"); store.create("a", "daylight")
    assert [p.name for p in store.list()] == ["a", "b"]


def test_list_skips_folders_that_are_not_readable_projects_and_keeps_the_good_ones(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("good", "daylight")
    store.create("broken json", "time-based")
    (tmp_path / "broken json" / "project.json").write_text("{not json", encoding="utf-8")
    store.create("broken config", "time-based")
    (tmp_path / "broken config" / "config.yaml").write_text("mode: [unclosed", encoding="utf-8")
    for odd_name in ("my.proj", ".backup"):
        (tmp_path / odd_name).mkdir()
        (tmp_path / odd_name / "project.json").write_text(store.read_project_json("good").model_dump_json(), encoding="utf-8")
    (tmp_path / "no project file").mkdir()
    # A YAML syntax error is a hand edit the next save repairs, so that project stays listed, without a mode.
    assert [(p.name, p.mode) for p in store.list()] == [("broken config", ""), ("good", "daylight")]


def test_write_project_json_replaces_the_file_and_leaves_no_temporary_file(tmp_path):
    store = ProjectStore(tmp_path)
    folder = store.create("a", "time-based")
    data = store.read_project_json("a")
    data.inputs_revision = 5
    store.write_project_json("a", data)
    assert store.read_project_json("a").inputs_revision == 5
    assert sorted(path.name for path in folder.iterdir() if path.is_file()) == ["config.yaml", "project.json"]


def test_reading_project_json_waits_for_the_project_lock(tmp_path):
    """On Windows a write cannot replace project.json while a reader has it open, so readers take the lock the writers hold."""
    store = ProjectStore(tmp_path); store.create("p", "daylight")
    read_finished = threading.Event()
    with store.project_lock("p"):
        reader = threading.Thread(target=lambda: (store.read_project_json("p"), read_finished.set()))
        reader.start()
        assert not read_finished.wait(0.2)
    reader.join(10)
    assert read_finished.is_set()


def _box_bytes(center, ext=".ply"):
    m = trimesh.creation.box(extents=[10, 10, 10]); m.apply_translation(center)
    exported = m.export(file_type=ext.lstrip("."))
    return exported.encode("utf-8") if isinstance(exported, str) else exported   # trimesh returns OBJ as text


def test_two_test_surface_files_join_and_removal_rebuilds(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    a = trimesh.creation.box(extents=[4, 4, 4]); b = trimesh.creation.box(extents=[2, 2, 2])
    store.add_input("p", "test_surfaces", "a.ply", a.export(file_type="ply"))
    reply = store.add_input("p", "test_surfaces", "b.ply", b.export(file_type="ply"))
    assert [(f.name, f.triangle_count) for f in reply.files] == [("a.ply", len(a.faces)), ("b.ply", len(b.faces))]
    joined = trimesh.load(tmp_path / "p/inputs/joined/test_surfaces.ply", force="mesh")
    assert len(joined.faces) == len(a.faces) + len(b.faces)
    store.remove_input("p", "test_surfaces", "a.ply")
    joined = trimesh.load(tmp_path / "p/inputs/joined/test_surfaces.ply", force="mesh")
    assert len(joined.faces) == len(b.faces)


def test_two_closed_max_volume_files_stay_two_closed_bodies(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    reply = store.add_input("p", "max_volume", "b.obj", _box_bytes([30, 0, 5], ".obj"))
    joined = trimesh.load(tmp_path / "p/inputs/joined/max_volume.ply", force="mesh")
    bodies = joined.split(only_watertight=False)
    assert len(bodies) == 2 and all(b.is_watertight for b in bodies)
    assert reply.joined_bounds == [[-5.0, -5.0, 0.0], [35.0, 5.0, 10.0]]


@pytest.mark.parametrize("file_name, data", [("bad.ply", b"not a mesh"), ("model.3dm", b"x")])
def test_rejected_upload_keeps_earlier_files_and_joined_file(tmp_path, file_name, data):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    before = (tmp_path / "p/inputs/joined/max_volume.ply").read_bytes()
    with pytest.raises(ProjectError) as err:
        store.add_input("p", "max_volume", file_name, data)
    assert err.value.status_code == 422
    assert [f.name for f in store.input_files("p", "max_volume")] == ["a.ply"]
    assert (tmp_path / "p/inputs/joined/max_volume.ply").read_bytes() == before
    assert sorted(path.name for path in (tmp_path / "p/inputs/max_volume").iterdir()) == ["a.ply"]


@pytest.mark.parametrize("raw, clean", [("../../evil.ply", "evil.ply"), ("C:\\x\\my model.obj", "mymodel.obj"), ("bü ro.stl", "bro.stl")])
def test_file_names_are_sanitized(raw, clean):
    assert sanitize_file_name(raw) == clean


@pytest.mark.parametrize("raw", ["", "..", ".hidden.ply", "ü ö", "folder/"])
def test_file_names_without_a_usable_name_are_rejected(raw):
    with pytest.raises(ProjectError) as err:
        sanitize_file_name(raw)
    assert err.value.status_code == 422


@pytest.mark.parametrize("raw", [f"{device_name}{extension}" for device_name in ("CON", "nul", "Com1", "LPT9", "aux")
                                 for extension in ("", ".ply", ".tar.ply", ".")] + ["n u l.ply", "C:\\x\\prn.epw"])
def test_file_names_that_are_windows_device_names_are_rejected(raw):
    with pytest.raises(ProjectError) as err:
        sanitize_file_name(raw)
    assert err.value.status_code == 422 and "device name" in str(err.value)


@pytest.mark.parametrize("fine", ["console.ply", "com10.ply", "my_nul.ply", "nul_1.obj", "a.nul.ply"])
def test_file_names_that_only_contain_a_device_name_are_kept(fine):
    assert sanitize_file_name(fine) == fine


def test_an_upload_named_like_a_windows_device_is_refused_without_writing(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    for role, file_name in (("max_volume", "nul.ply"), ("weather", "CON.epw")):
        with pytest.raises(ProjectError) as err:
            store.add_input("p", role, file_name, b"x")
        assert err.value.status_code == 422
    assert store.read_project_json("p").input_files == {}


def test_upload_and_removal_raise_the_inputs_revision(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    assert store.read_project_json("p").inputs_revision == 2
    store.remove_input("p", "max_volume", "a.ply")
    assert store.read_project_json("p").inputs_revision == 3


def test_removing_the_last_file_removes_the_joined_file_and_an_absent_file_is_not_found(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    reply = store.remove_input("p", "max_volume", "a.ply")
    assert reply.files == [] and reply.joined_bounds is None
    assert not (tmp_path / "p/inputs/joined/max_volume.ply").exists()
    with pytest.raises(ProjectError) as err:
        store.remove_input("p", "max_volume", "a.ply")
    assert err.value.status_code == 404


def test_uploading_the_same_name_again_replaces_the_file(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    reply = store.add_input("p", "max_volume", "a.ply", _box_bytes([50, 0, 5]))
    assert [f.name for f in reply.files] == ["a.ply"]
    assert reply.joined_bounds == [[45.0, -5.0, 0.0], [55.0, 5.0, 10.0]]
    assert store.input_file_path("p", "max_volume", "a.ply") == (tmp_path / "p/inputs/max_volume/a.ply").resolve()


def test_unknown_role_is_rejected(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    with pytest.raises(ProjectError) as err:
        store.add_input("p", "sky", "a.ply", b"x")
    assert err.value.status_code == 422


def test_weather_location_comes_from_the_epw_header(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    assert store.weather_location("p") is None
    reply = store.add_input("p", "weather", "golden.epw", GOLDEN_EPW.read_bytes())   # examples/weather/USA_CO_Golden-NREL.724666_TMY3.epw
    assert reply.weather_location == "Denver Centennial Golden Nr, USA"
    assert (tmp_path / "p/inputs/weather.epw").is_file()
    assert store.weather_location("p") == "Denver Centennial Golden Nr, USA"
    with pytest.raises(ProjectError) as err:
        store.add_input("p", "weather", "golden.txt", b"x")
    assert err.value.status_code == 422


def _golden_epw_lines():
    return GOLDEN_EPW.read_bytes().splitlines(keepends=True)


@pytest.mark.parametrize("broken_name, broken_content", [
    ("truncated", lambda lines: b"".join(lines[:100])),                  # the header and 92 hourly rows
    ("without_header", lambda lines: b"".join(lines[8:])),               # hourly rows only
    ("header_only", lambda lines: b"".join(lines[:8])),
    ("not_a_weather_file", lambda lines: b"this is not weather data\n" * 20),
    ("empty", lambda lines: b""),
])
def test_a_weather_file_that_cannot_be_read_as_an_epw_is_refused_and_the_earlier_one_is_kept(tmp_path, broken_name, broken_content):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    store.add_input("p", "weather", "golden.epw", GOLDEN_EPW.read_bytes())
    stored_weather = tmp_path / "p/inputs/weather.epw"
    stored_bytes = stored_weather.read_bytes()
    revision_before = store.read_project_json("p").inputs_revision
    with pytest.raises(ProjectError) as err:
        store.add_input("p", "weather", f"{broken_name}.epw", broken_content(_golden_epw_lines()))
    assert err.value.status_code == 422
    assert f"{broken_name}.epw" in str(err.value) and "upload" not in str(err.value)    # the person's file name, not a temporary one
    assert stored_weather.read_bytes() == stored_bytes
    assert store.read_project_json("p").inputs_revision == revision_before
    assert store.weather_location("p") == "Denver Centennial Golden Nr, USA"
    assert sorted(path.name for path in (tmp_path / "p/inputs").glob("*.*")) == ["weather.epw"]    # no temporary file is left


def test_a_truncated_weather_file_as_the_first_upload_leaves_the_project_without_weather(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    with pytest.raises(ProjectError) as err:
        store.add_input("p", "weather", "cut.epw", b"".join(_golden_epw_lines()[:100]))
    assert err.value.status_code == 422 and "cut.epw" in str(err.value)
    assert not (tmp_path / "p/inputs/weather.epw").exists()
    assert store.read_project_json("p").input_files.get("weather", {}) == {}


def test_names_differing_only_in_letter_case_are_one_file(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    store.add_input("p", "max_volume", "A.ply", _box_bytes([0, 0, 5]))
    reply = store.add_input("p", "max_volume", "a.ply", _box_bytes([30, 0, 5]))
    assert [f.name for f in reply.files] == ["A.ply"]
    assert reply.joined_bounds == [[25.0, -5.0, 0.0], [35.0, 5.0, 10.0]]
    joined = trimesh.load(tmp_path / "p/inputs/joined/max_volume.ply", force="mesh")
    assert len(joined.faces) == 12 and joined.is_watertight
    assert [path.name for path in (tmp_path / "p/inputs/max_volume").iterdir()] == ["A.ply"]
    assert store.remove_input("p", "max_volume", "A.ply").files == []


def _state_of(store, tmp_path):
    return (
        store.read_project_json("p").model_dump_json(),
        {path.name: path.read_bytes() for path in (tmp_path / "p/inputs").rglob("*") if path.is_file()},
    )


def test_failed_join_after_an_upload_leaves_files_and_project_json_as_they_were(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    before = _state_of(store, tmp_path)
    def failing_save_mesh(mesh, path):
        raise OSError("disk full")
    monkeypatch.setattr(projects, "save_mesh", failing_save_mesh)
    for file_name in ("b.ply", "a.ply"):    # a new file, then a replacement of an existing one
        with pytest.raises(ProjectError) as err:
            store.add_input("p", "max_volume", file_name, _box_bytes([30, 0, 5]))
        assert err.value.status_code == 500 and "disk full" in str(err.value)
        assert _state_of(store, tmp_path) == before


def test_failed_join_after_a_removal_leaves_files_and_project_json_as_they_were(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    store.add_input("p", "max_volume", "b.ply", _box_bytes([30, 0, 5]))
    before = _state_of(store, tmp_path)
    monkeypatch.setattr(projects, "save_mesh", lambda mesh, path: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(ProjectError):
        store.remove_input("p", "max_volume", "a.ply")
    assert _state_of(store, tmp_path) == before


def test_a_recorded_file_missing_on_disk_is_a_project_error_and_can_still_be_removed(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    store.add_input("p", "max_volume", "b.ply", _box_bytes([30, 0, 5]))
    (tmp_path / "p/inputs/max_volume/a.ply").unlink()
    with pytest.raises(ProjectError):
        store.add_input("p", "max_volume", "c.ply", _box_bytes([60, 0, 5]))
    reply = store.remove_input("p", "max_volume", "a.ply")
    assert [f.name for f in reply.files] == ["b.ply"]


def test_rejection_message_names_the_uploaded_file_not_the_temporary_one(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    with pytest.raises(ProjectError) as err:
        store.add_input("p", "test_surfaces", "facade_b.obj", b"v 0 0 0\n")
    assert "facade_b.obj" in str(err.value)
    assert "upload" not in str(err.value) and str(tmp_path) not in str(err.value)


def test_uploads_from_two_threads_to_one_role_are_both_recorded(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    barrier = threading.Barrier(2)
    failures = []
    def upload(file_name, center):
        try:
            barrier.wait()
            store.add_input("p", "test_surfaces", file_name, _box_bytes(center))
        except Exception as error:     # reported to the test thread below
            failures.append(error)
    threads = [threading.Thread(target=upload, args=(f"{letter}.ply", [index * 30, 0, 5])) for index, letter in enumerate("ab")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []
    assert [f.name for f in store.input_files("p", "test_surfaces")] == ["a.ply", "b.ply"]
    assert store.read_project_json("p").inputs_revision == 3
    joined = trimesh.load(tmp_path / "p/inputs/joined/test_surfaces.ply", force="mesh")
    assert len(joined.faces) == 24
    assert [path.name for path in (tmp_path / "p/inputs/joined").iterdir()] == ["test_surfaces.ply"]


def _block_centres_x(joined_path):
    joined = trimesh.load(joined_path, force="mesh")
    centres = joined.triangles_center
    return [round(float(centres[start:start + 12, 0].mean())) for start in range(0, len(centres), 12)]


def test_joined_file_follows_sorted_file_names_whatever_the_upload_order(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "time-based")
    joined_path = tmp_path / "p/inputs/joined/test_surfaces.ply"
    store.add_input("p", "test_surfaces", "b.ply", _box_bytes([100, 0, 5]))
    store.add_input("p", "test_surfaces", "a.ply", _box_bytes([0, 0, 5]))
    store.add_input("p", "test_surfaces", "c.ply", _box_bytes([200, 0, 5]))
    assert _block_centres_x(joined_path) == [0, 100, 200]
    store.remove_input("p", "test_surfaces", "a.ply")
    assert _block_centres_x(joined_path) == [100, 200]
    store.add_input("p", "test_surfaces", "a.ply", _box_bytes([0, 0, 5]))
    assert _block_centres_x(joined_path) == [0, 100, 200]


def _create_example_project(store, project_name, example_name):
    """A project made as POST /projects/{name}/examples/{example} makes it: the example's mode and input files."""
    example = next(candidate for candidate in _read_examples() if candidate.name == example_name)
    example_folder = EXAMPLE_PROJECTS_FOLDER / example.name
    store.create(project_name, example.mode)
    for role, file_names in (("max_volume", example.max_volume), ("test_surfaces", example.test_surfaces)):
        for file_name in file_names:
            store.add_input(project_name, role, file_name, (example_folder / file_name).read_bytes())
    store.add_input(project_name, "weather", EXAMPLE_WEATHER_FILE_NAME,
                    (EXAMPLE_PROJECTS_FOLDER / "weather" / EXAMPLE_WEATHER_FILE_NAME).read_bytes())
    return example


def _sampled_panels(test_surface_paths):
    """The sample points of every panel the engine samples, over the given test surface files as the engine reads them.

    A panel is a connected component of the mesh load_mesh returns, sampled by the engine's surface sampling with the
    default grid_step of 1 m; a component the sampling skips (degenerate, non-planar) gives no points and is left out.
    """
    points_by_panel = []
    with run_context(RunContext()):     # the skipped components of the example data are recorded, not warned about
        for test_surface_path in test_surface_paths:
            mesh = load_mesh(str(test_surface_path))
            for component in mesh.split(only_watertight=False, repair=False):
                points = discretize_surface_with_normals(component, 1.0)[0]
                if len(points):
                    points_by_panel.append(points)
    return points_by_panel


def _sorted_rows(points_by_panel):
    points = np.vstack(points_by_panel)
    return points[np.lexsort(points.T[::-1])]


@pytest.mark.parametrize("example_name", ["basic_perimeter_block", "new_building", "multiple_buildings"])
def test_the_joined_test_surfaces_of_an_example_sample_as_its_uploaded_files(tmp_path, example_name):
    """The engine finds in the joined test surface file the panels and sample points of the uploaded files.

    The example files keep panels that share corners apart only through their per-vertex normals: load_mesh merges
    coincident vertices whose normals are equal, so a joined file without normals fuses neighbouring panels.
    """
    store = ProjectStore(tmp_path)
    example = _create_example_project(store, "p", example_name)
    uploaded_panels = _sampled_panels(EXAMPLE_PROJECTS_FOLDER / example.name / name for name in example.test_surfaces)
    joined_panels = _sampled_panels([tmp_path / "p" / SERVICE_PATHS["test_surface_path"]])
    assert len(joined_panels) == len(uploaded_panels)
    np.testing.assert_allclose(_sorted_rows(joined_panels), _sorted_rows(uploaded_panels), atol=1e-4)


def test_the_joined_test_surfaces_keep_every_facade_of_the_district_example(tmp_path):
    store = ProjectStore(tmp_path)
    _create_example_project(store, "p", "multiple_buildings")
    joined_panels = _sampled_panels([tmp_path / "p" / SERVICE_PATHS["test_surface_path"]])
    assert (len(joined_panels), sum(len(points) for points in joined_panels)) == (423, 138_641)


def test_the_joined_test_surfaces_keep_the_courtyard_facades_of_the_perimeter_block(tmp_path):
    """The four courtyard walls stand on the rectangle x -1294.74..-1208.33, y -45.98..6.09, 20 m inside the block's edges."""
    store = ProjectStore(tmp_path)
    _create_example_project(store, "p", "basic_perimeter_block")
    joined_panels = _sampled_panels([tmp_path / "p" / SERVICE_PATHS["test_surface_path"]])
    courtyard_panels = [points for points in joined_panels
                        if (-1295.0 <= points[:, 0]).all() and (points[:, 0] <= -1208.0).all()
                        and (-46.5 <= points[:, 1]).all() and (points[:, 1] <= 6.5).all()]
    assert (len(joined_panels), len(courtyard_panels)) == (8, 4)


@pytest.mark.slow
def test_the_perimeter_block_carved_through_the_service_equals_the_cli_run_on_the_example_files(tmp_path):
    """The service's run of the example project keeps the voxels the CLI keeps from the packaged files (150,679 of them)."""
    from typer.testing import CliRunner
    from urbansolarcarver.carver_cli import app
    from urbansolarcarver.local_web_service.run_worker import RunWorker

    store = ProjectStore(tmp_path / "projects")
    example = _create_example_project(store, "block", "basic_perimeter_block")
    worker = RunWorker(store, "auto")
    events = wait_until_finished(worker, worker.start("block", ["thresholding"]).run_id, deadline_seconds=600)
    assert events[-1]["type"] == "run_finished", events[-1]

    example_folder = EXAMPLE_PROJECTS_FOLDER / example.name
    cli_config = {**store.read_stored_config("block"),
                  "max_volume_path": str(example_folder / example.max_volume[0]),
                  "test_surface_path": str(example_folder / example.test_surfaces[0]),
                  "epw_path": str(EXAMPLE_PROJECTS_FOLDER / "weather" / EXAMPLE_WEATHER_FILE_NAME),
                  "out_dir": str(tmp_path / "cli_run")}
    cli_config_path = tmp_path / "cli_config.yaml"
    cli_config_path.write_text(yaml.safe_dump(cli_config), encoding="utf-8")
    result = CliRunner().invoke(app, ["run", "-c", str(cli_config_path), "--produce", "thresholding"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output

    service_mask = np.load(store.open("block") / "run" / "thresholding" / "mask.npy")
    cli_mask = np.load(tmp_path / "cli_run" / "thresholding" / "mask.npy")
    assert int((cli_mask > 0).sum()) == 150_679
    assert np.array_equal(service_mask, cli_mask)


def test_config_yaml_round_trips_through_load_config(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "daylight")
    reply = store.write_config_from_values("p", {"mode": "daylight", "voxel_size": 2.0, "carve_fraction": 0.3})
    loaded = store.load_project_config("p")
    assert loaded.voxel_size == 2.0 and loaded.carve_fraction == 0.3
    assert Path(loaded.max_volume_path) == (tmp_path / "p/inputs/joined/max_volume.ply").resolve()
    assert "max_volume_path" not in reply.settings and reply.settings["mode"] == "daylight"
    assert store.read_settings("p") == reply.settings


def test_config_from_settings_builds_the_config_of_a_settings_dict(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "daylight")
    stored = store.read_stored_config("p")
    config = store.config_from_settings("p", {**stored, "voxel_size": 2.0})
    assert config.voxel_size == 2.0 and Path(config.out_dir) == (tmp_path / "p/run").resolve()
    assert store.load_project_config("p") == store.config_from_settings("p", stored)
    with pytest.raises(ConfigError):
        store.config_from_settings("p", {**stored, "voxel_size": -1})


def test_browser_paths_and_device_are_ignored(tmp_path):
    store = ProjectStore(tmp_path, device="cpu"); store.create("p", "daylight")
    store.write_config_from_values("p", {"mode": "daylight", "out_dir": "C:/elsewhere", "max_volume_path": "/etc/x", "device": "cuda"})
    loaded = store.load_project_config("p")
    assert Path(loaded.out_dir) == (tmp_path / "p/run").resolve() and loaded.device == "cpu"


def test_config_yaml_holds_the_service_paths_relative_to_the_project_folder(tmp_path):
    store = ProjectStore(tmp_path, device="cpu")
    store.create("sunny", "time-based"); store.create("bright", "daylight")
    sunny = yaml.safe_load((tmp_path / "sunny/config.yaml").read_text(encoding="utf-8"))
    assert {key: sunny[key] for key in projects.SERVICE_PATHS} == projects.SERVICE_PATHS
    assert sunny["device"] == "cpu"
    bright = yaml.safe_load((tmp_path / "bright/config.yaml").read_text(encoding="utf-8"))
    assert {key: bright.get(key) for key in projects.SERVICE_PATHS} == {**projects.SERVICE_PATHS, "epw_path": None}


def test_simulated_weights_path_from_the_browser_is_never_stored(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "benefit")
    for path in ("C:/Windows/win.ini", "../other/x.json"):
        reply = store.write_config_from_values("p", {"mode": "benefit", "simulated_weights_path": path})
        assert "simulated_weights_path" not in reply.settings
    assert yaml.safe_load((tmp_path / "p/config.yaml").read_text(encoding="utf-8")).get("simulated_weights_path") is None
    assert store.load_project_config("p").simulated_weights_path is None


@pytest.mark.parametrize("mode", ["daylight", "time-based"])
def test_saving_and_loading_a_config_raises_no_warnings(tmp_path, mode):
    store = ProjectStore(tmp_path)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        store.create("p", mode)
        store.write_config_from_values("p", {"mode": mode, "voxel_size": 2.0})
        store.load_project_config("p")


def test_invalid_setting_raises_config_error_on_its_field(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "daylight")
    with pytest.raises(ConfigError) as err:
        store.write_config_from_values("p", {"mode": "daylight", "voxel_size": -1})
    assert [e.field for e in err.value.errors] == ["voxel_size"]


def test_unknown_mode_at_create_leaves_no_project_folder(tmp_path):
    store = ProjectStore(tmp_path)
    with pytest.raises(ConfigError):
        store.create("p", "no-such-mode")
    assert not (tmp_path / "p").exists()


def test_joined_bounds_do_not_need_the_engine_loader(tmp_path, monkeypatch):
    """The bounds are read without load_mesh's fix_normals, which takes most of its time and does not move a vertex."""
    store = ProjectStore(tmp_path); store.create("p", "daylight")
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    expected_bounds = projects.load_mesh(str(tmp_path / "p" / "inputs" / "joined" / "max_volume.ply")).bounds.tolist()

    def refuse(path):
        raise AssertionError("joined_bounds called load_mesh")
    monkeypatch.setattr(projects, "load_mesh", refuse)
    assert store.joined_bounds("p") == expected_bounds == [[-5.0, -5.0, 0.0], [5.0, 5.0, 10.0]]


def test_grid_plan_and_budget_use_the_joined_max_volume(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "daylight")
    assert store.write_config_from_values("p", {"mode": "daylight"}).grid_plan is None
    store.add_input("p", "max_volume", "a.ply", _box_bytes([0, 0, 5]))
    reply = store.write_config_from_values("p", {"mode": "daylight", "voxel_size": 1.0})
    assert reply.grid_plan.resolution == 11            # 10 m side + 1% margin each side, rounded up
    with pytest.raises(ConfigError) as err:
        store.write_config_from_values("p", {"mode": "daylight", "voxel_size": 0.0125, "grid_step": 0.0125})
    assert err.value.errors[0].field == "voxel_size"
    assert err.value.grid_plan.total_voxels > err.value.grid_plan.budget_voxels == 500_000_000
    assert store.load_project_config("p").voxel_size == 1.0   # the rejected value was not stored
