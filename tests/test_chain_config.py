"""The ``criteria:`` form of a config: shared settings at the top level, one validated config per criterion."""
import warnings

import pytest
import yaml

from urbansolarcarver.chain_config import CRITERION_KEYS, ChainConfig, Criterion, is_chain_file, load_chain
from urbansolarcarver.errors import ConfigError, UrbanSolarCarverWarning
from urbansolarcarver.load_config import load_config
from urbansolarcarver.pydantic_schemas import UserConfig
from urbansolarcarver.stage_settings import ThresholdingSettings

SHARED = {"max_volume_path": "vol.ply", "voxel_size": 2.0, "out_dir": "run"}
DAYLIGHT = {"name": "Daylight on windows", "mode": "daylight", "test_surface_path": "w.ply", "carve_fraction": 0.7}
TILTED = {"mode": "tilted_plane", "test_surface_path": "y.ply", "tilted_plane_angle_deg": 30}
PERIOD = {"st_month": 10, "st_day": 15, "st_hour": 7, "end_month": 4, "end_day": 15, "end_hour": 19}


def write_yaml(folder, data, name="chain.yaml"):
    path = folder / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def chain_data(*criteria, **top):
    return {**SHARED, **top, "criteria": list(criteria)}


def test_each_criterion_gets_the_shared_settings_and_its_own(tmp_path):
    path = write_yaml(tmp_path, chain_data(DAYLIGHT, TILTED))
    chain = load_chain(str(path))
    assert isinstance(chain, ChainConfig) and all(isinstance(c, Criterion) for c in chain.criteria)
    assert [c.id for c in chain.criteria] == ["1", "2"]
    assert [c.name for c in chain.criteria] == ["Daylight on windows", "tilted_plane"]
    assert all(c.config.voxel_size == 2.0 for c in chain.criteria)
    assert chain.criteria[0].config.carve_fraction == 0.7
    assert chain.criteria[1].config.mode == "tilted_plane"
    assert chain.criteria[0].config.test_surface_path == str((tmp_path / "w.ply").resolve())
    assert chain.criteria[1].config.test_surface_path == str((tmp_path / "y.ply").resolve())  # relative to the YAML
    assert chain.criteria[0].config.max_volume_path == str((tmp_path / "vol.ply").resolve())
    assert chain.shared is chain.criteria[-1].config


def test_an_explicit_id_is_kept_and_a_default_name_is_the_mode(tmp_path):
    path = write_yaml(tmp_path, chain_data({**TILTED, "id": "slope"}, {**DAYLIGHT, "id": 7}))
    chain = load_chain(str(path))
    assert [c.id for c in chain.criteria] == ["slope", "7"]
    assert chain.criteria[0].name == "tilted_plane"


def test_a_criterion_may_carry_its_own_analysis_period(tmp_path):
    benefit = {"mode": "benefit", "test_surface_path": "s.ply", "analysis_period": PERIOD}
    path = write_yaml(tmp_path, chain_data(benefit, DAYLIGHT, epw_path="w.epw"))
    chain = load_chain(str(path))
    assert (chain.criteria[0].config.start_month, chain.criteria[0].config.end_hour) == (10, 19)
    assert chain.criteria[1].config.start_month is None


def test_a_shared_setting_inside_a_criterion_is_refused(tmp_path):
    path = write_yaml(tmp_path, chain_data(DAYLIGHT, {**TILTED, "voxel_size": 1.0}))
    with pytest.raises(ConfigError, match="voxel_size.*shared") as caught:
        load_chain(str(path))
    assert "criterion 2" in str(caught.value)


def test_a_criterion_setting_at_the_top_level_is_refused(tmp_path):
    path = write_yaml(tmp_path, chain_data(DAYLIGHT, carve_fraction=0.5))
    with pytest.raises(ConfigError, match="carve_fraction.*criteria"):
        load_chain(str(path))


def test_a_top_level_period_is_a_criterion_setting(tmp_path):
    path = write_yaml(tmp_path, chain_data(DAYLIGHT, analysis_period=PERIOD))
    with pytest.raises(ConfigError, match="start_month.*criteria"):
        load_chain(str(path))


def test_an_unknown_key_in_a_criterion_is_reported_by_the_schema_not_as_shared(tmp_path):
    path = write_yaml(tmp_path, chain_data({**DAYLIGHT, "voxle_size": 1.0}))
    with pytest.raises(ConfigError, match="voxle_size") as caught:
        load_chain(str(path))
    assert "shared" not in str(caught.value)


def test_the_weather_file_reaches_only_the_criteria_that_read_it(tmp_path):
    benefit = {"mode": "benefit", "test_surface_path": "s.ply", "analysis_period": PERIOD}
    path = write_yaml(tmp_path, chain_data(benefit, DAYLIGHT, epw_path="weather.epw"))
    with warnings.catch_warnings():
        warnings.simplefilter("error", UrbanSolarCarverWarning)  # settings_unused_by_mode would raise here
        chain = load_chain(str(path))
    assert chain.criteria[0].config.epw_path == str((tmp_path / "weather.epw").resolve())
    assert chain.criteria[1].config.epw_path is None


def test_a_criterion_error_names_the_criterion(tmp_path):
    benefit_without_period = {"name": "Winter heat", "mode": "benefit", "test_surface_path": "s.ply"}
    path = write_yaml(tmp_path, chain_data(DAYLIGHT, benefit_without_period, epw_path="w.epw"))
    with pytest.raises(ConfigError, match=r"criterion 2 \(Winter heat\): ") as caught:
        load_chain(str(path))
    assert "analysis period" in str(caught.value)
    assert caught.value.errors and "analysis period" in caught.value.errors[0].message


@pytest.mark.parametrize("ids", [["a/b", "x"], ["x", "x"], ["A", "a"], ["Slope", "x", "slope"], ["", "x"], ["a" * 41, "x"], ["a b", "x"]])
def test_ids_must_be_unique_and_safe_folder_names(tmp_path, ids):
    path = write_yaml(tmp_path, chain_data(*({**DAYLIGHT, "id": i} for i in ids)))
    with pytest.raises(ConfigError, match="id"):
        load_chain(str(path))


@pytest.mark.parametrize("criteria", [[], "daylight", [{"mode": "daylight"}, "daylight"]])
def test_criteria_must_be_a_non_empty_list_of_mappings(tmp_path, criteria):
    path = write_yaml(tmp_path, {**SHARED, "criteria": criteria})
    with pytest.raises(ConfigError, match="criteria"):
        load_chain(str(path))


def test_overrides_replace_shared_settings_and_refuse_criterion_settings(tmp_path):
    path = write_yaml(tmp_path, chain_data(DAYLIGHT, TILTED))
    chain = load_chain(str(path), ["voxel_size=4"])
    assert all(c.config.voxel_size == 4 for c in chain.criteria)
    with pytest.raises(ConfigError, match="carve_fraction.*criteria"):
        load_chain(str(path), {"carve_fraction": 0.5})


def test_a_file_without_criteria_is_not_a_chain(tmp_path):
    plain = write_yaml(tmp_path, {**SHARED, **DAYLIGHT}, "plain.yaml")
    chain = write_yaml(tmp_path, chain_data(DAYLIGHT), "chain.yaml")
    assert not is_chain_file(str(plain)) and is_chain_file(str(chain))
    with pytest.raises(ConfigError, match="criteria"):
        load_chain(str(plain))


def test_load_config_points_a_chain_file_to_load_chain(tmp_path):
    path = write_yaml(tmp_path, chain_data(DAYLIGHT))
    with pytest.raises(ConfigError, match="load_chain") as caught:
        load_config(str(path))
    assert str(path) in str(caught.value) and "usc run" in str(caught.value)


def test_the_criterion_keys_are_the_settings_one_criterion_decides():
    assert {"name", "id", "mode", "test_surface_path", "edge_taper", "carve_fraction", "threshold",
            "tilted_plane_angle_deg", "start_month", "min_altitude"} <= CRITERION_KEYS
    assert set(ThresholdingSettings.model_fields) <= CRITERION_KEYS
    assert not {"epw_path", "voxel_size", "max_volume_path", "out_dir", "context_path", "final_mesh_format"} & CRITERION_KEYS
    assert CRITERION_KEYS - {"name", "id"} <= set(UserConfig.model_fields)
