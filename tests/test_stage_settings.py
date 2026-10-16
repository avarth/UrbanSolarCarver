import pytest

from _stage_scene import daylight_cube_config
from urbansolarcarver.pydantic_schemas import UserConfig
from urbansolarcarver.stage_settings import (
    PIPELINE_STAGES, ExportingSettings, MassingSettings, PreprocessingSettings,
    RunOptions, ThresholdingSettings, applied_smoothing_radius_m, stages_to_rerun,
)


def test_every_config_field_belongs_to_exactly_one_settings_model():
    models = (PreprocessingSettings, ThresholdingSettings, ExportingSettings, MassingSettings, RunOptions)
    owners = {}
    for model in models:
        for name in model.model_fields:
            owners.setdefault(name, []).append(model.__name__)
    assert set(owners) == set(UserConfig.model_fields)
    assert all(len(v) == 1 for v in owners.values())


def test_from_config_copies_the_values_and_the_models_are_frozen(tmp_path):
    config = daylight_cube_config(tmp_path, plate_tolerance=0.3)
    massing = MassingSettings.from_config(config)
    assert massing.plate_tolerance == 0.3
    with pytest.raises(Exception):
        massing.plate_tolerance = 0.5


def test_unset_and_explicit_defaults_compare_equal(tmp_path):
    a = daylight_cube_config(tmp_path)                       # max_slope_deg None, weighted mode
    b = daylight_cube_config(tmp_path, max_slope_deg=75.0, score_smoothing=1.1)
    assert stages_to_rerun(a, b, {"exporting"}) == []


def test_a_massing_setting_reruns_massing_only(tmp_path):
    a = daylight_cube_config(tmp_path)
    assert stages_to_rerun(a, daylight_cube_config(tmp_path, plate_tolerance=0.3),
                           {"exporting", "massing"}) == ["massing"]


def test_a_threshold_change_reruns_thresholding_and_the_produced_leaves(tmp_path):
    a = daylight_cube_config(tmp_path)
    assert stages_to_rerun(a, daylight_cube_config(tmp_path, carve_fraction=0.5),
                           {"exporting"}) == ["thresholding", "exporting"]


def test_a_preprocessing_change_reruns_everything_produced(tmp_path):
    a = daylight_cube_config(tmp_path)
    b = daylight_cube_config(tmp_path, voxel_size=2.0)
    assert stages_to_rerun(a, b, {"exporting", "massing"}) == [
        "preprocessing", "thresholding", "exporting", "massing"]


def test_producing_an_early_stage_stops_the_list_there(tmp_path):
    a = daylight_cube_config(tmp_path)
    b = daylight_cube_config(tmp_path, voxel_size=2.0)
    assert stages_to_rerun(a, b, {"preprocessing"}) == ["preprocessing"]
    assert stages_to_rerun(a, b, {"thresholding"}) == ["preprocessing", "thresholding"]
    c = daylight_cube_config(tmp_path, carve_fraction=0.5)
    assert stages_to_rerun(a, c, {"preprocessing"}) == []


def test_a_field_the_mode_does_not_read_reruns_nothing(tmp_path):
    a = daylight_cube_config(tmp_path)
    with pytest.warns(UserWarning):                      # settings_unused_by_mode
        b = daylight_cube_config(tmp_path, bliss_k=1.5)
    assert stages_to_rerun(a, b, {"exporting"}) == []


def test_run_options_never_cause_a_rerun(tmp_path):
    a = daylight_cube_config(tmp_path)
    assert stages_to_rerun(a, daylight_cube_config(tmp_path, ray_batch_size=1000, diagnostics=True),
                           {"exporting"}) == []


def test_no_previous_config_runs_everything_needed(tmp_path):
    assert stages_to_rerun(None, daylight_cube_config(tmp_path), {"massing"}) == [
        "preprocessing", "thresholding", "massing"]


def test_smooth_iters_is_ignored_without_smoothing(tmp_path):
    a = daylight_cube_config(tmp_path)
    assert stages_to_rerun(a, daylight_cube_config(tmp_path, smooth_iters=4), {"exporting"}) == []
    with_smoothing = daylight_cube_config(tmp_path, apply_smoothing=True)
    assert stages_to_rerun(with_smoothing, daylight_cube_config(
        tmp_path, apply_smoothing=True, smooth_iters=4), {"exporting"}) == ["exporting"]


def test_an_unknown_produce_stage_is_a_value_error(tmp_path):
    with pytest.raises(ValueError, match="nonsense"):
        stages_to_rerun(None, daylight_cube_config(tmp_path), {"nonsense"})


def test_pipeline_stages_are_in_pipeline_order():
    assert PIPELINE_STAGES == ("preprocessing", "thresholding", "exporting", "massing")


def test_thresholding_effective_values_are_resolved(tmp_path):
    config = daylight_cube_config(tmp_path)
    values = ThresholdingSettings.from_config(config).effective_values("daylight", 1.0)
    assert values == {
        "threshold": {"method": "carve_fraction", "value": 0.7},
        "score_smoothing_m": 1.1,
        "max_slope_deg": 75.0,
        "carve_above": True,
        "carve_above_min_consecutive": 1,
    }


def test_preprocessing_effective_values_leave_out_unread_mode_fields(tmp_path):
    with pytest.warns(UserWarning):
        config = daylight_cube_config(tmp_path, bliss_k=1.5)
    values = PreprocessingSettings.from_config(config).effective_values()
    assert "bliss_k" not in values and "epw_path" not in values
    assert values["mode"] == "daylight" and values["voxel_size"] == 1.0


@pytest.mark.parametrize("kind, voxel_size, smoothing, expected", [
    ("violation_count", 1.0, None, 0.0),
    ("violation_count", 1.0, 2.0, 0.0),
    ("weighted_sum", 1.0, None, 1.1),
    ("weighted_sum", 2.0, None, 2.2),
    ("weighted_sum", 1.0, 0.0, 0.0),
    ("weighted_sum", 1.0, 3.0, 3.0),
    ("weighted_sum", 1.0, 0.1, 0.5),      # clipped up to 0.5 voxel
    ("weighted_sum", 0.5, 10.0, 4.0),     # clipped down to 8 voxels
    ("weighted_sum", 0.0, 1.0, 0.0),      # no voxel size: nothing applies
])
def test_applied_smoothing_radius(kind, voxel_size, smoothing, expected):
    assert applied_smoothing_radius_m(kind, voxel_size, smoothing) == pytest.approx(expected)


def test_stage_folder_is_the_run_folder_plus_the_stage_name():
    from pathlib import Path
    from urbansolarcarver.stage_settings import stage_folder
    assert stage_folder("run", "massing") == Path("run") / "massing"
