"""Project folders, names and project.json of the local web service."""
import threading
import warnings
from pathlib import Path

import pytest
import trimesh
import yaml

from urbansolarcarver.errors import ConfigError

from urbansolarcarver.local_web_service import projects
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
