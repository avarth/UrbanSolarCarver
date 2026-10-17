"""Project folders, names and project.json of the local web service."""
from pathlib import Path

import pytest
import trimesh

from urbansolarcarver.local_web_service.projects import ProjectError, ProjectStore, sanitize_file_name

GOLDEN_EPW = Path(__file__).resolve().parent.parent / "examples" / "weather" / "USA_CO_Golden-NREL.724666_TMY3.epw"


@pytest.mark.parametrize("bad", ["", "   ", "../x", "a/b", "a\\b", ".hidden", "x" * 65, "naïve"])
def test_invalid_project_names_are_rejected_without_writing(tmp_path, bad):
    store = ProjectStore(tmp_path / "projects")
    with pytest.raises(ProjectError) as err:
        store.create(bad, "time-based")
    assert err.value.status_code == 422
    assert not any(p for p in tmp_path.rglob("*") if p.is_file())


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
    assert [p.name for p in store.list()] == ["good"]
    assert store.list()[0].mode == "daylight"


def test_write_project_json_replaces_the_file_and_leaves_no_temporary_file(tmp_path):
    store = ProjectStore(tmp_path)
    folder = store.create("a", "time-based")
    data = store.read_project_json("a")
    data.inputs_revision = 5
    store.write_project_json("a", data)
    assert store.read_project_json("a").inputs_revision == 5
    assert sorted(path.name for path in folder.iterdir() if path.is_file()) == ["config.yaml", "project.json"]


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
