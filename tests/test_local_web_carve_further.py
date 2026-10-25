"""Carve further: the exported envelope of a project becomes its next maximum volume.

The engine is replaced by the fake of local_web_test_support.py; its exporting stage writes a placeholder file, which these
tests replace by a real mesh before carving further. The fixture project_with_inputs is in conftest.py.
"""
import pytest

from local_web_test_support import box_bytes, change_settings, make_worker, run_and_wait, write_envelope_as_exported, write_fake_chain_run
from urbansolarcarver.local_web_service.carve_further import NEW_PROJECT_MODE, carve_further
from urbansolarcarver.local_web_service.project_names import ProjectError
from urbansolarcarver.local_web_service.stage_records import stage_status


@pytest.fixture
def built_project(project_with_inputs):
    """A daylight project after a build with the fake engine, with a real exported envelope; the store, the name and the worker."""
    store, name = project_with_inputs
    worker = make_worker(store)
    change_settings(store, name, mode="daylight", carve_fraction=0.3)
    run_and_wait(worker, name, ["exporting", "massing"])
    write_envelope_as_exported(store.open(name))
    return store, name, worker


def test_the_envelope_becomes_the_max_volume_and_the_replaced_file_is_kept(built_project):
    store, name, _ = built_project
    original_volume = (store.open(name) / "inputs" / "max_volume" / "volume.ply").read_bytes()
    carve_further(store, name)
    assert [file.name for file in store.input_files(name, "max_volume")] == ["carved_envelope_1.ply"]
    assert (store.open(name) / "inputs" / "earlier_max_volumes" / "1" / "volume.ply").read_bytes() == original_volume
    assert store.joined_bounds(name) == [[-4.0, -4.0, 0.0], [4.0, 4.0, 6.0]]
    assert [file.name for file in store.input_files(name, "test_surfaces")] == ["surface.ply"]


def test_carve_further_still_works_on_a_chain_of_one(built_project):
    """The settings of the only criterion return to a new project's and it stays the project's criterion "1"."""
    store, name, _ = built_project
    [entry] = store.criteria(name)
    carve_further(store, name)
    assert [criterion.id for criterion in store.criteria(name)] == ["1"]
    assert store.criteria(name)[0].colour == entry.colour and store.criteria(name)[0].test_surface_files == entry.test_surface_files
    assert store.read_settings(name, "1")["mode"] == NEW_PROJECT_MODE
    assert [file.name for file in store.input_files(name, "max_volume")] == ["carved_envelope_1.ply"]


def test_a_project_with_several_criteria_refuses_before_any_change(project_with_inputs):
    """Its settings belong to no single criterion, so it has none to return to a new project's: refused with the max volume,
    the project and the settings as they were."""
    store, name = project_with_inputs
    entry = store.add_criterion(name, "daylight")
    store.add_criterion_test_surface(name, entry.id, "surface_2.ply", box_bytes([2, 0, 0], extents=(6, 6, 0.1)))
    write_fake_chain_run(store, name, ["1", "2"])
    write_envelope_as_exported(store.open(name))
    before = store.read_project_json(name)
    settings_before = store.read_settings(name, "1")
    with pytest.raises(ProjectError) as error:
        carve_further(store, name)
    assert error.value.status_code == 409 and str(error.value) == "Carve further works on a project with one criterion."
    assert store.read_project_json(name) == before and store.read_settings(name, "1") == settings_before
    assert [file.name for file in store.input_files(name, "max_volume")] == ["volume.ply"]
    assert not (store.open(name) / "inputs" / "earlier_max_volumes").exists()


def test_the_chain_records_the_mode_and_settings_the_envelope_was_carved_with(built_project):
    store, name, _ = built_project
    carve_further(store, name)
    [step] = store.read_project_json(name).carving_chain
    assert step.step == 1 and step.mode == "daylight"
    assert step.settings["carve_fraction"] == 0.3 and "max_volume_path" not in step.settings
    assert step.earlier_max_volume_files == ["volume.ply"] and step.max_volume_file == "carved_envelope_1.ply"


def test_settings_return_to_the_defaults_of_a_new_project_and_every_stage_is_out_of_date(built_project):
    store, name, _ = built_project
    carve_further(store, name)
    settings = store.read_settings(name)
    assert settings["mode"] == NEW_PROJECT_MODE == "time-based" and "carve_fraction" not in settings
    assert set(stage_status(store, name).values()) == {"out_of_date"}


def test_a_second_step_numbers_its_file_and_keeps_the_first_envelope(built_project):
    store, name, worker = built_project
    carve_further(store, name)
    store.write_config_from_values(name, {"mode": "daylight"})   # the default mode needs a weather file this project has not got
    run_and_wait(worker, name, ["exporting", "massing"])
    write_envelope_as_exported(store.open(name), extents=(6, 6, 4))
    carve_further(store, name)
    assert [file.name for file in store.input_files(name, "max_volume")] == ["carved_envelope_2.ply"]
    assert (store.open(name) / "inputs" / "earlier_max_volumes" / "2" / "carved_envelope_1.ply").is_file()
    assert [step.step for step in store.read_project_json(name).carving_chain] == [1, 2]


def test_without_a_current_envelope_nothing_changes(built_project):
    store, name, _ = built_project
    change_settings(store, name, carve_fraction=0.5)    # the envelope no longer matches the settings
    before = store.read_project_json(name)
    with pytest.raises(ProjectError) as error:
        carve_further(store, name)
    assert error.value.status_code == 409
    assert store.read_project_json(name) == before
    assert not (store.open(name) / "inputs" / "earlier_max_volumes").exists()


def test_a_project_never_built_cannot_carve_further(project_with_inputs):
    store, name = project_with_inputs
    with pytest.raises(ProjectError) as error:
        carve_further(store, name)
    assert error.value.status_code == 409


def test_a_default_voxel_size_over_the_grid_budget_keeps_the_voxel_size_the_envelope_was_built_with(project_with_inputs):
    store, name = project_with_inputs
    change_settings(store, name, mode="daylight", voxel_size=4.0)
    run_and_wait(make_worker(store), name, ["exporting", "massing"])
    write_envelope_as_exported(store.open(name), extents=(1000, 1000, 10))     # at the default 1 m: 1010^3 voxels, over the budget
    carve_further(store, name)
    settings = store.read_settings(name)
    assert settings["mode"] == NEW_PROJECT_MODE and settings["voxel_size"] == 4.0


def test_carve_further_returns_the_settings_of_a_criterion_whose_id_is_not_1(project_with_inputs):
    store, name = project_with_inputs
    entry = store.add_criterion(name, "daylight")
    store.add_criterion_test_surface(name, entry.id, "surface_2.ply", box_bytes([2, 0, 0], extents=(6, 6, 0.1)))
    store.delete_criterion(name, "1")
    assert [criterion.id for criterion in store.criteria(name)] == ["2"]
    write_fake_chain_run(store, name, ["2"])
    write_envelope_as_exported(store.open(name))
    carve_further(store, name)
    assert [criterion.id for criterion in store.criteria(name)] == ["2"]
    assert store.read_settings(name, "2")["mode"] == NEW_PROJECT_MODE
    assert [file.name for file in store.input_files(name, "max_volume")] == ["carved_envelope_1.ply"]
