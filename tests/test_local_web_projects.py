"""Project folders, names and project.json of the local web service."""
import os
import threading
import warnings
from pathlib import Path

import numpy as np
import pytest
import send2trash
import trimesh
import yaml
from local_web_test_support import (
    FakeRecycleBin, has_vertex_normals, make_link_to_folder, wait_until_finished, write_joined_test_surfaces_without_normals,
)

from urbansolarcarver.errors import ConfigError
from urbansolarcarver.io import load_mesh
from urbansolarcarver.run_context import RunContext, run_context
from urbansolarcarver.surface_sampling import discretize_surface_with_normals

from urbansolarcarver.local_web_service import project_removal, projects
from urbansolarcarver.local_web_service.example_catalog import EXAMPLE_PROJECTS_FOLDER, EXAMPLE_WEATHER_FILE_NAME, read_examples
from urbansolarcarver.local_web_service.project_removal import ProjectRemovalRefused
from urbansolarcarver.local_web_service.projects import SERVICE_PATHS, ProjectError, ProjectStore, sanitize_file_name
from urbansolarcarver.local_web_service.server import _example_input_files

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


@pytest.fixture(scope="module")
def example_project_to_read(tmp_path_factory, example_project_templates):
    """A function giving, for an example name, the example and the sampled panels of the joined test surface file of a
    project made from it.

    Each example is made into a project and sampled once per module (the district example takes seconds); only tests
    that read the project without changing it use this.
    """
    store = ProjectStore(tmp_path_factory.mktemp("examples_to_read"))
    made = {}

    def example_and_joined_panels(example_name):
        if example_name not in made:
            example = example_project_templates.copy_example_project(store, example_name, example_name)
            joined_panels = _sampled_panels([store.open(example_name) / SERVICE_PATHS["test_surface_path"]])
            made[example_name] = (example, joined_panels)
        return made[example_name]

    return example_and_joined_panels


@pytest.mark.parametrize("example_name", ["basic_perimeter_block", "new_building",
                                          pytest.param("multiple_buildings", marks=pytest.mark.slow)])
def test_the_joined_test_surfaces_of_an_example_sample_as_its_uploaded_files(example_project_to_read, example_name):
    """The engine finds in the joined test surface file the panels and sample points of the uploaded files.

    The example files keep panels that share corners apart only through their per-vertex normals: load_mesh merges
    coincident vertices whose normals are equal, so a joined file without normals fuses neighbouring panels.
    """
    example, joined_panels = example_project_to_read(example_name)
    uploaded_panels = _sampled_panels(EXAMPLE_PROJECTS_FOLDER / example.name / name for name in example.test_surfaces)
    assert len(joined_panels) == len(uploaded_panels)
    np.testing.assert_allclose(_sorted_rows(joined_panels), _sorted_rows(uploaded_panels), atol=1e-4)


def test_a_joined_test_surface_file_written_without_normals_is_rebuilt_once_and_raises_the_inputs_revision(tmp_path, example_project_templates):
    store = ProjectStore(tmp_path)
    example_project_templates.copy_example_project(store, "p", "basic_perimeter_block")
    joined_path = write_joined_test_surfaces_without_normals(store, "p")
    assert len(_sampled_panels([joined_path])) == 4             # the courtyard walls welded into one ring
    inputs_revision = store.read_project_json("p").inputs_revision
    assert store.rebuild_joined_test_surfaces_without_normals("p") is True
    assert has_vertex_normals(joined_path) and len(_sampled_panels([joined_path])) == 8
    assert store.read_project_json("p").inputs_revision == inputs_revision + 1
    assert store.rebuild_joined_test_surfaces_without_normals("p") is False
    assert store.read_project_json("p").inputs_revision == inputs_revision + 1


def test_a_project_without_test_surfaces_has_no_joined_test_surface_file_to_rebuild(tmp_path):
    store = ProjectStore(tmp_path); store.create("p", "daylight")
    inputs_revision = store.read_project_json("p").inputs_revision
    assert store.rebuild_joined_test_surfaces_without_normals("p") is False
    assert store.read_project_json("p").inputs_revision == inputs_revision


@pytest.mark.slow
def test_the_joined_test_surfaces_keep_every_facade_of_the_district_example(example_project_to_read):
    _example, joined_panels = example_project_to_read("multiple_buildings")
    assert (len(joined_panels), sum(len(points) for points in joined_panels)) == (423, 138_641)


def test_the_joined_test_surfaces_keep_the_courtyard_facades_of_the_perimeter_block(example_project_to_read):
    """The four courtyard walls stand on the rectangle x -1294.74..-1208.33, y -45.98..6.09, 20 m inside the block's edges."""
    _example, joined_panels = example_project_to_read("basic_perimeter_block")
    courtyard_panels = [points for points in joined_panels
                        if (-1295.0 <= points[:, 0]).all() and (points[:, 0] <= -1208.0).all()
                        and (-46.5 <= points[:, 1]).all() and (points[:, 1] <= 6.5).all()]
    assert (len(joined_panels), len(courtyard_panels)) == (8, 4)


@pytest.mark.slow
def test_the_perimeter_block_carved_through_the_service_equals_the_cli_run_on_the_example_files(tmp_path, example_project_templates):
    """The service's run of the example project keeps the voxels the CLI keeps from the packaged files (150,679 of them)."""
    from typer.testing import CliRunner
    from urbansolarcarver.carver_cli import app
    from urbansolarcarver.local_web_service.run_worker import RunWorker

    store = ProjectStore(tmp_path / "projects")
    example = example_project_templates.copy_example_project(store, "block", "basic_perimeter_block")
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


# ---- Rename, delete, reset and the example a project came from ----

@pytest.fixture
def recycle_bin(monkeypatch):
    bin_stub = FakeRecycleBin()
    monkeypatch.setattr(send2trash, "send2trash", bin_stub)
    return bin_stub


def example_by_name(name):
    return next(example for example in read_examples() if example.name == name)


def create_example_project(store, project_name, example_name="new_building"):
    example = example_by_name(example_name)
    store.create_example_project(project_name, example, _example_input_files(example))
    return example


def link_kind_of_this_platform():
    return "junction" if os.name == "nt" else "symlink"


def test_rename_moves_the_folder_and_changes_the_name_in_project_json(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("Old", "time-based")
    store.add_input("Old", "max_volume", "volume.ply", _box_bytes([0, 0, 5]))
    new_folder = store.rename_project("Old", "New name")
    assert new_folder == (tmp_path / "New name").resolve() and not (tmp_path / "Old").exists()
    assert store.read_project_json("New name").name == "New name"
    assert [file.name for file in store.input_files("New name", "max_volume")] == ["volume.ply"]
    assert store.joined_bounds("New name") is not None
    assert [row.name for row in store.list()] == ["New name"]
    assert not list(new_folder.glob("*.tmp"))


def test_rename_refuses_a_bad_new_name_with_422_and_changes_nothing(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("a", "time-based")
    for bad in ("", "..", "x/y", "con"):
        with pytest.raises(ProjectError) as err:
            store.rename_project("a", bad)
        assert err.value.status_code == 422
    assert [row.name for row in store.list()] == ["a"]


@pytest.mark.parametrize("new_name", ["b", "B", "b ", "a"])
def test_rename_to_an_existing_name_or_the_same_name_in_another_letter_case_is_409_and_moves_nothing(tmp_path, new_name):
    store = ProjectStore(tmp_path)
    store.create("a", "time-based")
    store.create("b", "time-based")
    with pytest.raises(ProjectError) as err:
        store.rename_project("a", new_name)
    assert err.value.status_code == 409 and "already exists" in str(err.value) and "letter case" in str(err.value)
    assert sorted(folder.name for folder in tmp_path.iterdir()) == ["a", "b"]
    assert [store.read_project_json(name).name for name in ("a", "b")] == ["a", "b"]


def test_rename_that_changes_only_the_letter_case_is_409_with_its_own_message_and_moves_nothing(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("Perimeter block", "time-based")
    with pytest.raises(ProjectError) as err:
        store.rename_project("Perimeter block", "perimeter block")
    assert err.value.status_code == 409
    assert "already exists" not in str(err.value) and "differ only in letter case" in str(err.value)
    assert [folder.name for folder in tmp_path.iterdir()] == ["Perimeter block"]
    assert store.read_project_json("Perimeter block").name == "Perimeter block"


def test_rename_of_an_unknown_project_is_404(tmp_path):
    with pytest.raises(ProjectError) as err:
        ProjectStore(tmp_path).rename_project("nothing", "other")
    assert err.value.status_code == 404


def test_rename_that_cannot_move_the_folder_is_422_and_changes_nothing(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    store.create("a", "time-based")

    def refuse_to_move(source, target):
        raise PermissionError("the folder is open in another program")

    monkeypatch.setattr(projects.os, "replace", refuse_to_move)
    with pytest.raises(ProjectError) as err:
        store.rename_project("a", "b")
    assert err.value.status_code == 422 and "open in another program" in str(err.value)
    assert store.read_project_json("a").name == "a"


def test_rename_whose_project_json_cannot_be_written_puts_the_folder_back(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    store.create("a", "time-based")

    def fail_to_write(name, data):
        raise OSError("disk full")

    monkeypatch.setattr(store, "write_project_json", fail_to_write)
    with pytest.raises(OSError):
        store.rename_project("a", "b")
    assert [folder.name for folder in tmp_path.iterdir()] == ["a"]


def test_rename_waits_for_the_lock_of_the_new_name_too(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("a", "time-based")
    finished = threading.Event()
    with store.project_lock("B"):       # a request that is working on the name the project is to get
        renaming = threading.Thread(target=lambda: (store.rename_project("a", "b"), finished.set()))
        renaming.start()
        assert not finished.wait(0.3)
    renaming.join(10)
    assert finished.is_set() and (tmp_path / "b").is_dir()


def test_check_returns_the_resolved_folder_of_a_project(tmp_path):
    ProjectStore(tmp_path).create("Block", "time-based")
    assert project_removal.check_project_folder_can_be_removed(tmp_path, "Block") == (tmp_path / "Block").resolve()


@pytest.mark.parametrize("bad_name", ["", "..", "a/b", "con", "../outside"])
def test_check_applies_the_project_name_rule(tmp_path, bad_name):
    with pytest.raises(ProjectError) as err:
        project_removal.check_project_folder_can_be_removed(tmp_path, bad_name)
    assert err.value.status_code == 422


def test_check_of_a_project_that_is_not_there_is_404(tmp_path):
    with pytest.raises(ProjectError) as err:
        project_removal.check_project_folder_can_be_removed(tmp_path, "nothing")
    assert err.value.status_code == 404


def test_check_refuses_a_folder_without_project_json(tmp_path):
    (tmp_path / "plain").mkdir()
    with pytest.raises(ProjectRemovalRefused) as err:
        project_removal.check_project_folder_can_be_removed(tmp_path, "plain")
    assert err.value.status_code == 422 and "project.json" in str(err.value)


@pytest.mark.parametrize("content", ["not json", "{}", '{"name": "other", "created": "2026-01-01T00:00:00+00:00"}'])
def test_check_refuses_a_project_json_that_does_not_read_as_a_project_of_that_name(tmp_path, content):
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "project.json").write_text(content, encoding="utf-8")
    with pytest.raises(ProjectRemovalRefused):
        project_removal.check_project_folder_can_be_removed(tmp_path, "p")


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_check_refuses_a_link_inside_the_project_and_the_folder_it_leads_to_is_untouched(tmp_path, kind):
    store = ProjectStore(tmp_path / "projects")
    project_folder = store.create("p", "time-based")
    outside = tmp_path / "outside"
    (outside / "deep").mkdir(parents=True)
    (outside / "deep" / "precious.txt").write_text("keep", encoding="utf-8")
    make_link_to_folder(project_folder / "inputs" / "linked", outside, kind)
    with pytest.raises(ProjectRemovalRefused) as err:
        project_removal.check_project_folder_can_be_removed(store.projects_folder, "p")
    assert err.value.status_code == 422 and "linked" in str(err.value)
    assert (outside / "deep" / "precious.txt").read_text(encoding="utf-8") == "keep" and project_folder.is_dir()


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_check_refuses_a_link_many_levels_down(tmp_path, kind):
    store = ProjectStore(tmp_path / "projects")
    project_folder = store.create("p", "time-based")
    (tmp_path / "outside").mkdir()
    (project_folder / "run" / "a" / "b").mkdir(parents=True)
    make_link_to_folder(project_folder / "run" / "a" / "b" / "deep link", tmp_path / "outside", kind)
    with pytest.raises(ProjectRemovalRefused):
        project_removal.check_project_folder_can_be_removed(store.projects_folder, "p")


def test_check_refuses_a_file_that_is_a_symbolic_link(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    project_folder = store.create("p", "time-based")
    (tmp_path / "outside.txt").write_text("keep", encoding="utf-8")
    try:
        os.symlink(tmp_path / "outside.txt", project_folder / "run" / "result.txt")
    except OSError as error:
        pytest.skip(f"a symbolic link cannot be made here: {error}")
    with pytest.raises(ProjectRemovalRefused):
        project_removal.check_project_folder_can_be_removed(store.projects_folder, "p")


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_check_refuses_a_project_folder_that_is_itself_a_link_out_of_the_projects_folder(tmp_path, kind):
    projects_folder = tmp_path / "projects"
    projects_folder.mkdir()
    ProjectStore(tmp_path / "elsewhere").create("p", "time-based")
    make_link_to_folder(projects_folder / "p", tmp_path / "elsewhere" / "p", kind)
    with pytest.raises(ProjectRemovalRefused):
        project_removal.check_project_folder_can_be_removed(projects_folder, "p")
    assert (tmp_path / "elsewhere" / "p" / "project.json").is_file()


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_check_refuses_a_project_folder_that_is_a_link_to_another_project(tmp_path, kind):
    store = ProjectStore(tmp_path)
    store.create("real", "time-based")
    make_link_to_folder(tmp_path / "alias", tmp_path / "real", kind)
    with pytest.raises(ProjectRemovalRefused):
        project_removal.check_project_folder_can_be_removed(tmp_path, "alias")


def test_a_project_is_moved_to_the_recycle_bin_with_its_folder_only(tmp_path, recycle_bin):
    store = ProjectStore(tmp_path)
    store.create("a", "time-based")
    store.create("b", "time-based")
    store.delete_project("a")
    assert recycle_bin.folders == [(tmp_path / "a").resolve()]
    assert [row.name for row in store.list()] == ["b"]


def test_a_project_with_a_link_inside_is_not_moved_to_the_recycle_bin(tmp_path, recycle_bin):
    store = ProjectStore(tmp_path / "projects")
    project_folder = store.create("p", "time-based")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "precious.txt").write_text("keep", encoding="utf-8")
    make_link_to_folder(project_folder / "inputs" / "linked", tmp_path / "outside", link_kind_of_this_platform())
    with pytest.raises(ProjectRemovalRefused):
        store.delete_project("p")
    assert recycle_bin.folders == [] and (tmp_path / "outside" / "precious.txt").is_file() and project_folder.is_dir()


@pytest.mark.parametrize("error", [PermissionError("the folder is in use"), send2trash.TrashPermissionError("no permission"), OSError("no bin")])
def test_a_recycle_bin_that_fails_leaves_the_project_and_says_why(tmp_path, monkeypatch, error):
    monkeypatch.setattr(send2trash, "send2trash", FakeRecycleBin(error=error))
    store = ProjectStore(tmp_path)
    store.create("a", "time-based")
    with pytest.raises(ProjectRemovalRefused) as err:
        store.delete_project("a")
    assert err.value.status_code == 422 and "recycle bin" in str(err.value) and str(error) in str(err.value)
    assert [row.name for row in store.list()] == ["a"]


def test_reset_gives_a_fresh_copy_of_the_example_under_the_same_name(tmp_path, recycle_bin, example_project_templates):
    store = ProjectStore(tmp_path)
    example = example_project_templates.copy_example_project(store, "My copy", "new_building")
    store.write_config_from_values("My copy", {"mode": "daylight"})
    store.remove_input("My copy", "test_surfaces", "neighbor_roofs.ply")
    (tmp_path / "My copy" / "run" / "old_result.txt").write_text("old", encoding="utf-8")
    store.reset_project_to_example("My copy", example, _example_input_files(example))
    assert recycle_bin.folders == [(tmp_path / "My copy").resolve()]
    assert [row.name for row in store.list()] == ["My copy"]
    assert store.read_settings("My copy")["mode"] == "irradiance"
    assert [file.name for file in store.input_files("My copy", "test_surfaces")] == ["neighbor_roofs.ply", "neighbor_windows.ply"]
    assert [file.name for file in store.input_files("My copy", "weather")] == ["weather.epw"]
    assert list((tmp_path / "My copy" / "run").iterdir()) == [] and store.read_project_json("My copy").example == "new_building"


def test_reset_refuses_a_project_that_did_not_come_from_the_example(tmp_path, recycle_bin, example_project_templates):
    store = ProjectStore(tmp_path)
    store.create("plain", "time-based")
    example = example_by_name("new_building")
    with pytest.raises(ProjectError) as err:
        store.reset_project_to_example("plain", example, _example_input_files(example))
    assert err.value.status_code == 422 and recycle_bin.folders == []
    example_project_templates.copy_example_project(store, "other", "basic_perimeter_block")
    with pytest.raises(ProjectError):       # recorded as from another example
        store.reset_project_to_example("other", example, _example_input_files(example))
    assert recycle_bin.folders == []


def test_reset_counts_a_project_without_the_example_field_as_from_the_example_when_its_name_is_the_title(tmp_path, recycle_bin, example_project_templates):
    store = ProjectStore(tmp_path)
    example = example_by_name("new_building")
    example_project_templates.copy_example_project(store, example.title, "new_building")
    project_json = store.read_project_json(example.title)
    project_json.example = None     # a project made before the field existed
    store.write_project_json(example.title, project_json)
    store.reset_project_to_example(example.title, example, _example_input_files(example))
    assert store.read_project_json(example.title).example == "new_building" and len(recycle_bin.folders) == 1


def test_reset_checks_the_guardrails_before_it_moves_anything(tmp_path, recycle_bin, example_project_templates):
    store = ProjectStore(tmp_path / "projects")
    example = example_project_templates.copy_example_project(store, "p", "new_building")
    (tmp_path / "outside").mkdir()
    make_link_to_folder(tmp_path / "projects" / "p" / "run" / "linked", tmp_path / "outside", link_kind_of_this_platform())
    with pytest.raises(ProjectRemovalRefused):
        store.reset_project_to_example("p", example, _example_input_files(example))
    assert recycle_bin.folders == [] and [file.name for file in store.input_files("p", "max_volume")] == ["max_volume.ply"]


def test_reset_with_a_recycle_bin_that_fails_changes_nothing(tmp_path, monkeypatch, example_project_templates):
    monkeypatch.setattr(send2trash, "send2trash", FakeRecycleBin(error=OSError("no bin")))
    store = ProjectStore(tmp_path)
    example = example_project_templates.copy_example_project(store, "p", "new_building")
    (tmp_path / "p" / "run" / "result.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ProjectRemovalRefused):
        store.reset_project_to_example("p", example, _example_input_files(example))
    assert (tmp_path / "p" / "run" / "result.txt").is_file()


def test_reset_that_cannot_recreate_the_project_says_the_old_content_is_in_the_recycle_bin(tmp_path, recycle_bin, example_project_templates):
    store = ProjectStore(tmp_path)
    example = example_project_templates.copy_example_project(store, "p", "new_building")
    with pytest.raises(ProjectError) as err:
        store.reset_project_to_example("p", example, [("max_volume", "max_volume.ply", b"not a mesh")])
    assert err.value.status_code == 500 and "old content" in str(err.value) and "recycle bin" in str(err.value)
    assert len(recycle_bin.folders) == 1 and not (tmp_path / "p").exists()      # no half-made project is left


def test_an_example_project_that_fails_midway_leaves_no_folder_and_a_name_that_is_free(tmp_path):
    store = ProjectStore(tmp_path)
    example = example_by_name("new_building")
    with pytest.raises(ProjectError):
        store.create_example_project("p", example, [("max_volume", "max_volume.ply", b"not a mesh")])
    assert list(tmp_path.iterdir()) == []


def test_a_project_made_from_an_example_records_the_example(tmp_path):
    store = ProjectStore(tmp_path)
    create_example_project(store, "p")
    store.create("q", "time-based")
    assert store.read_project_json("p").example == "new_building" and store.read_project_json("q").example is None


def test_project_of_example_finds_a_renamed_project_by_the_recorded_example(tmp_path, example_project_templates):
    store = ProjectStore(tmp_path)
    example_project_templates.copy_example_project(store, "first", "new_building")
    store.rename_project("first", "Renamed")
    assert store.project_of_example("new_building", "New building among neighbors") == "Renamed"
    assert store.project_of_example("basic_perimeter_block", "Perimeter block") is None


def test_a_project_without_the_example_field_named_like_the_example_keeps_the_example_when_renamed(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("Perimeter block", "time-based")     # made before the field existed: no example recorded
    assert store.read_project_json("Perimeter block").example is None
    store.rename_project("Perimeter block", "My block")
    assert store.read_project_json("My block").example == "basic_perimeter_block"
    assert store.summary("My block").example == "basic_perimeter_block"
    titles = {example.name: example.title for example in read_examples()}
    assert store.projects_of_examples(titles)["basic_perimeter_block"] == "My block"


def test_renaming_a_project_without_the_example_field_that_is_from_no_example_records_none(tmp_path):
    store = ProjectStore(tmp_path)
    store.create("plain", "time-based")
    store.rename_project("plain", "Perimeter block 2")
    assert store.read_project_json("Perimeter block 2").example is None


def test_project_of_example_counts_a_project_without_the_field_only_when_its_name_is_exactly_the_title(tmp_path):
    numbered_copies = ProjectStore(tmp_path / "copies")
    for name in ("Perimeter block 2", "perimeter block"):
        numbered_copies.create(name, "time-based")
    assert numbered_copies.project_of_example("basic_perimeter_block", "Perimeter block") is None
    exact = ProjectStore(tmp_path / "exact")
    exact.create("Perimeter block", "time-based")
    assert exact.project_of_example("basic_perimeter_block", "Perimeter block") == "Perimeter block"


def test_project_of_example_prefers_the_most_recently_modified_project(tmp_path, example_project_templates):
    store = ProjectStore(tmp_path)
    example_project_templates.copy_example_project(store, "older", "new_building")
    example_project_templates.copy_example_project(store, "newer", "new_building")
    example_project_templates.copy_example_project(store, "newest", "basic_perimeter_block")
    for name, seconds in (("older", 1_700_000_000), ("newer", 1_800_000_000), ("newest", 1_900_000_000)):
        for file_name in ("project.json", "config.yaml"):
            os.utime(tmp_path / name / file_name, (seconds, seconds))
    assert store.project_of_example("new_building", "New building among neighbors") == "newer"


def test_project_of_example_with_no_projects_folder_is_none(tmp_path):
    assert ProjectStore(tmp_path / "missing").project_of_example("new_building", "New building among neighbors") is None


# ---- Fix round: locks of two projects, the rename rollback, drives without a recycle bin, one pass over the examples ----

def test_project_locks_are_taken_in_one_order_whatever_the_order_of_the_names(tmp_path):
    store = ProjectStore(tmp_path)
    taken = []

    class RecordingLock:
        def __init__(self, key):
            self.key = key

        def __enter__(self):
            taken.append(self.key)

        def __exit__(self, *exc_info):
            return False

    store.project_lock = RecordingLock
    with store.project_locks("z", "A", "a"):
        pass
    with store.project_locks("a", "Z"):
        pass
    assert taken == ["a", "z", "a", "z"]        # each project once, in the same order for both calls


def test_rename_whose_rollback_fails_tells_where_the_folder_is_and_keeps_the_first_error(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    store.create("a", "time-based")
    real_replace = os.replace
    moves = []

    def move_once_then_fail(source, target):
        moves.append((Path(source).name, Path(target).name))
        if len(moves) == 1:
            real_replace(source, target)
        else:
            raise PermissionError("the folder is open in another program")

    def fail_to_write(name, data):
        raise OSError("disk full")

    monkeypatch.setattr(projects.os, "replace", move_once_then_fail)
    monkeypatch.setattr(store, "write_project_json", fail_to_write)
    with pytest.raises(ProjectError) as err:
        store.rename_project("a", "b")
    assert err.value.status_code == 500 and "renamed to 'b'" in str(err.value)
    assert "disk full" in str(err.value) and "open in another program" in str(err.value) and "now" in str(err.value)
    assert isinstance(err.value.__cause__, OSError) and "disk full" in str(err.value.__cause__)
    assert [folder.name for folder in tmp_path.iterdir()] == ["b"]


def pretend_to_be_on_windows_volume(monkeypatch, volume_root, drive_type):
    """Makes the drive check run as on Windows, with the volume of every folder at *volume_root* and of the given type; the questions asked."""
    asked = {"paths": [], "volume_roots": []}
    monkeypatch.setattr(project_removal.sys, "platform", "win32")
    monkeypatch.setattr(project_removal, "_windows_volume_root", lambda path: asked["paths"].append(path) or volume_root)
    monkeypatch.setattr(project_removal, "_windows_drive_type", lambda root: asked["volume_roots"].append(root) or drive_type)
    return asked


@pytest.mark.parametrize("drive_type, allowed", [(0, False), (1, False), (2, False), (3, True), (4, False), (5, False), (6, False)])
def test_on_windows_only_a_fixed_volume_is_allowed_and_a_refusal_comes_before_anything_moves(tmp_path, monkeypatch, drive_type, allowed):
    ProjectStore(tmp_path).create("p", "time-based")
    asked = pretend_to_be_on_windows_volume(monkeypatch, "M:\\mounted\\", drive_type)
    if allowed:
        assert project_removal.check_project_folder_can_be_removed(tmp_path, "p") == (tmp_path / "p").resolve()
    else:
        with pytest.raises(ProjectRemovalRefused) as err:
            project_removal.check_project_folder_can_be_removed(tmp_path, "p")
        assert err.value.status_code == 422 and "no recycle bin" in str(err.value) and "file manager" in str(err.value)
    assert asked["paths"] == [str((tmp_path / "p").resolve())]
    assert asked["volume_roots"] == ["M:\\mounted\\"]       # the volume root, which may be a folder, not the drive letter


def test_on_windows_a_network_path_is_refused_without_asking_the_volume(monkeypatch):
    monkeypatch.setattr(project_removal.sys, "platform", "win32")
    monkeypatch.setattr(project_removal, "_windows_volume_root", lambda path: pytest.fail("a UNC path is refused first"))
    with pytest.raises(ProjectRemovalRefused, match="no recycle bin"):
        project_removal._check_folder_has_a_recycle_bin(Path("//server/share/projects/p"))


def test_on_windows_a_volume_that_cannot_be_asked_about_is_refused(monkeypatch):
    def cannot_ask(path):
        raise OSError("the volume is not ready")

    monkeypatch.setattr(project_removal.sys, "platform", "win32")
    monkeypatch.setattr(project_removal, "_windows_volume_root", cannot_ask)
    with pytest.raises(ProjectRemovalRefused, match="no recycle bin"):
        project_removal._check_folder_has_a_recycle_bin(Path("C:/projects/p"))


def test_the_drive_type_is_not_asked_off_windows(tmp_path, monkeypatch):
    ProjectStore(tmp_path).create("p", "time-based")
    monkeypatch.setattr(project_removal.sys, "platform", "linux")
    monkeypatch.setattr(project_removal, "_windows_volume_root", lambda path: pytest.fail("only Windows has volumes to ask about"))
    assert project_removal.check_project_folder_can_be_removed(tmp_path, "p") == (tmp_path / "p").resolve()


@pytest.mark.skipif(os.name != "nt", reason="the Windows functions of the drive check")
def test_the_real_volume_of_the_test_folder_is_asked_about_and_has_a_root_and_a_type(tmp_path):
    volume_root = project_removal._windows_volume_root(str(tmp_path))
    assert str(tmp_path.resolve()).lower().startswith(volume_root.lower()) and project_removal._windows_drive_type(volume_root) in range(7)


def test_delete_and_reset_leave_a_project_on_a_removable_volume_in_place(tmp_path, monkeypatch, recycle_bin, example_project_templates):
    store = ProjectStore(tmp_path)
    example = example_project_templates.copy_example_project(store, "p", "new_building")
    pretend_to_be_on_windows_volume(monkeypatch, "E:\\", 2)
    with pytest.raises(ProjectRemovalRefused):
        store.delete_project("p")
    with pytest.raises(ProjectRemovalRefused):
        store.reset_project_to_example("p", example, _example_input_files(example))
    assert recycle_bin.folders == [] and (tmp_path / "p" / "project.json").is_file()


def test_reset_refuses_a_project_json_that_names_another_project_before_it_moves_anything(tmp_path, recycle_bin, example_project_templates):
    store = ProjectStore(tmp_path)
    example = example_project_templates.copy_example_project(store, "a", "new_building")
    store.create("b", "time-based")
    project_json = store.read_project_json("a")
    project_json.name = "b"     # a hand edit
    store.write_project_json("a", project_json)
    with pytest.raises(ProjectRemovalRefused) as err:
        store.reset_project_to_example("a", example, _example_input_files(example))
    assert err.value.status_code == 422 and "'b'" in str(err.value)
    assert recycle_bin.folders == [] and sorted(folder.name for folder in tmp_path.iterdir()) == ["a", "b"]
    assert [file.name for file in store.input_files("a", "max_volume")] == ["max_volume.ply"]


@pytest.mark.skipif(os.name != "nt", reason="folder names ignore letter case on Windows only")
def test_reset_works_when_the_name_in_the_address_differs_from_the_stored_name_in_letter_case_only(tmp_path, recycle_bin, example_project_templates):
    store = ProjectStore(tmp_path)
    example = example_project_templates.copy_example_project(store, "Mine", "new_building")
    store.reset_project_to_example("mine", example, _example_input_files(example))
    assert [row.name for row in store.list()] == ["Mine"] and len(recycle_bin.folders) == 1


def test_a_project_summary_names_its_example_with_the_backfill_rule(tmp_path, example_project_templates):
    store = ProjectStore(tmp_path)
    example_project_templates.copy_example_project(store, "made here", "basic_perimeter_block")
    store.create("plain", "time-based")
    store.create("Perimeter block", "time-based")       # no example field, named like the example's title
    store.create("Perimeter block 2", "time-based")     # a numbered copy stays an ordinary project
    assert {row.name: row.example for row in store.list()} == {
        "Perimeter block": "basic_perimeter_block", "Perimeter block 2": None, "made here": "basic_perimeter_block", "plain": None}
    assert store.summary("made here").example == "basic_perimeter_block"


def test_the_examples_are_matched_to_projects_in_one_pass_over_the_projects(tmp_path, monkeypatch, example_project_templates):
    store = ProjectStore(tmp_path)
    example_project_templates.copy_example_project(store, "a", "new_building")
    example_project_templates.copy_example_project(store, "b", "basic_perimeter_block")
    listings = []
    real_list = store.list
    monkeypatch.setattr(store, "list", lambda: listings.append(1) or real_list())
    titles = {example.name: example.title for example in read_examples()}
    assert store.projects_of_examples(titles) == {"basic_perimeter_block": "b", "new_building": "a", "multiple_buildings": None}
    assert len(listings) == 1
