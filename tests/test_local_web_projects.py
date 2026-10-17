"""Project folders, names and project.json of the local web service."""
import pytest

from urbansolarcarver.local_web_service.projects import ProjectError, ProjectStore


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
