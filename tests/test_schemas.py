"""Validation guard tests for Pydantic schemas and grid bounds."""
import os
import pytest
import numpy as np
from pydantic import ValidationError


def _make_config(**overrides):
    """Build a minimal valid UserConfig dict, then apply overrides."""
    from urbansolarcarver.pydantic_schemas import UserConfig
    base = {
        "max_volume_path": "dummy.ply",
        "test_surface_path": "dummy_srf.ply",
        "out_dir": "out",
        "mode": "tilted_plane",
        "tilted_plane_angle_deg": 45.0,
        "voxel_size": 2.0,
        "grid_step": 2.0,
        "ray_length": 50.0,
        "device": "cpu",
    }
    base.update(overrides)
    return UserConfig(**base)


class TestVoxelSizeBounds:
    def test_voxel_size_too_small(self):
        with pytest.raises(ValidationError, match="voxel_size"):
            _make_config(voxel_size=0.005)

    def test_voxel_size_too_large(self):
        with pytest.raises(ValidationError, match="voxel_size"):
            _make_config(voxel_size=150.0)

    def test_voxel_size_at_lower_bound(self):
        cfg = _make_config(voxel_size=0.01, grid_step=0.01)
        assert cfg.voxel_size == 0.01

    def test_voxel_size_at_upper_bound(self):
        cfg = _make_config(voxel_size=100.0)
        assert cfg.voxel_size == 100.0


class TestModeRequirements:
    def test_irradiance_requires_epw(self):
        with pytest.raises(ValidationError, match="epw_path"):
            _make_config(mode="irradiance", epw_path=None,
                         start_month=1, start_day=1, start_hour=8,
                         end_month=1, end_day=1, end_hour=16)

    def test_benefit_requires_epw(self):
        with pytest.raises(ValidationError, match="epw_path"):
            _make_config(mode="benefit", epw_path=None,
                         start_month=1, start_day=1, start_hour=8,
                         end_month=1, end_day=1, end_hour=16)

    def test_tilted_plane_requires_angle(self):
        with pytest.raises(ValidationError, match="tilted_plane"):
            _make_config(mode="tilted_plane", tilted_plane_angle_deg=None)

    def test_time_based_requires_analysis_period(self):
        with pytest.raises(ValidationError, match="analysis period"):
            _make_config(mode="time-based", epw_path="dummy.epw")


class TestGridStepValidation:
    def test_grid_step_exceeds_voxel_size(self):
        with pytest.raises(ValidationError, match="grid_step"):
            _make_config(voxel_size=1.0, grid_step=2.0)


class TestResolutionCap:
    def test_resolution_exceeds_cap(self):
        """voxelize_mesh should reject resolution > 2048."""
        import trimesh
        from urbansolarcarver.grid import voxelize_mesh
        # 100m cube / 0.01m voxel = 10000 resolution → should fail
        big_cube = trimesh.creation.box(extents=(100, 100, 100))
        with pytest.raises(ValueError, match="per-axis limit"):
            voxelize_mesh(big_cube, voxel_size=0.01)


class TestDateValidation:
    """Date field bounds and cross-field validation."""

    def test_month_zero_rejected(self):
        with pytest.raises(ValidationError):
            _make_config(mode="time-based", epw_path="dummy.epw",
                         start_month=0, start_day=1, start_hour=8,
                         end_month=1, end_day=1, end_hour=16)

    def test_month_13_rejected(self):
        with pytest.raises(ValidationError):
            _make_config(mode="time-based", epw_path="dummy.epw",
                         start_month=13, start_day=1, start_hour=8,
                         end_month=1, end_day=1, end_hour=16)

    def test_day_zero_rejected(self):
        with pytest.raises(ValidationError):
            _make_config(mode="time-based", epw_path="dummy.epw",
                         start_month=1, start_day=0, start_hour=8,
                         end_month=1, end_day=1, end_hour=16)

    def test_day_32_rejected(self):
        with pytest.raises(ValidationError):
            _make_config(mode="time-based", epw_path="dummy.epw",
                         start_month=1, start_day=32, start_hour=8,
                         end_month=1, end_day=1, end_hour=16)

    def test_hour_negative_rejected(self):
        with pytest.raises(ValidationError):
            _make_config(mode="time-based", epw_path="dummy.epw",
                         start_month=1, start_day=1, start_hour=-1,
                         end_month=1, end_day=1, end_hour=16)

    def test_hour_24_rejected(self):
        with pytest.raises(ValidationError):
            _make_config(mode="time-based", epw_path="dummy.epw",
                         start_month=1, start_day=1, start_hour=24,
                         end_month=1, end_day=1, end_hour=16)

    def test_feb_31_rejected(self):
        """February 31 should be rejected as an invalid calendar date."""
        with pytest.raises(ValidationError, match="invalid for month 2"):
            _make_config(mode="time-based", epw_path="dummy.epw",
                         start_month=2, start_day=31, start_hour=8,
                         end_month=3, end_day=1, end_hour=16)

    def test_valid_date_accepted(self):
        cfg = _make_config(mode="time-based", epw_path="dummy.epw",
                           start_month=6, start_day=21, start_hour=10,
                           end_month=6, end_day=21, end_hour=14)
        assert cfg.start_month == 6
        assert cfg.start_day == 21


class TestCarveFractionBounds:
    def test_zero_valid(self):
        cfg = _make_config(carve_fraction=0.0)
        assert cfg.carve_fraction == 0.0

    def test_one_valid(self):
        cfg = _make_config(carve_fraction=1.0)
        assert cfg.carve_fraction == 1.0

    def test_above_one_rejected(self):
        with pytest.raises(ValidationError):
            _make_config(carve_fraction=1.1)

    def test_negative_rejected(self):
        with pytest.raises(ValidationError):
            _make_config(carve_fraction=-0.1)


class TestThresholdValidation:
    def _benefit_base(self, **kw):
        """Use benefit mode (accepts all threshold types) for threshold tests."""
        return _make_config(
            mode="benefit", epw_path="dummy.epw",
            start_month=1, start_day=1, start_hour=8,
            end_month=1, end_day=1, end_hour=16,
            tilted_plane_angle_deg=None,
            **kw,
        )

    def test_string_shorthand_normalized(self):
        cfg = self._benefit_base(threshold="headtail")
        assert cfg.threshold.method == "headtail"
        assert cfg.threshold.value is None

    def test_invalid_string_rejected(self):
        with pytest.raises(ValidationError):
            self._benefit_base(threshold="bogus")

    def test_numeric_shorthand_becomes_cutoff(self):
        cfg = self._benefit_base(threshold=0.5)
        assert cfg.threshold.method == "cutoff"
        assert cfg.threshold.value == 0.5

    def test_none_resolves_to_mode_default(self):
        """Unset threshold resolves to carve_fraction for weighted modes,
        picking up the carve_fraction key as its value."""
        cfg = self._benefit_base(threshold=None, carve_fraction=0.6)
        assert cfg.threshold.method == "carve_fraction"
        assert cfg.threshold.value == 0.6

    def test_canonical_mapping_accepted(self):
        cfg = self._benefit_base(threshold={"method": "carve_fraction", "value": 0.4})
        assert cfg.threshold.method == "carve_fraction"
        assert cfg.threshold.value == 0.4

    def test_carve_fraction_shorthand_fills_value(self):
        cfg = self._benefit_base(threshold="carve_fraction", carve_fraction=0.3)
        assert cfg.threshold.method == "carve_fraction"
        assert cfg.threshold.value == 0.3

    def test_headtail_with_value_rejected(self):
        with pytest.raises(ValidationError):
            self._benefit_base(threshold={"method": "headtail", "value": 0.5})

    def test_cutoff_requires_value(self):
        with pytest.raises(ValidationError):
            self._benefit_base(threshold={"method": "cutoff"})

    def test_bool_threshold_rejected(self):
        with pytest.raises(ValidationError):
            self._benefit_base(threshold=True)

    def test_numeric_placeholder_rejected(self):
        with pytest.raises(ValidationError):
            self._benefit_base(threshold="numeric")

    def _timebased_base(self, **kw):
        return _make_config(
            mode="time-based", epw_path="dummy.epw",
            start_month=1, start_day=1, start_hour=8,
            end_month=1, end_day=1, end_hour=16,
            tilted_plane_angle_deg=None,
            **kw,
        )

    def test_violation_mode_default_is_strict_cutoff(self):
        cfg = self._timebased_base(threshold=None)
        assert cfg.threshold.method == "cutoff"
        assert cfg.threshold.value == 0.0

    def test_violation_mode_rejects_strategy(self):
        with pytest.raises(ValidationError):
            self._timebased_base(threshold="carve_fraction")

    def test_tilted_plane_rejects_string_threshold(self):
        with pytest.raises(ValidationError):
            _make_config(threshold="headtail")

    def test_tilted_plane_rejects_nonzero_numeric(self):
        with pytest.raises(ValidationError):
            _make_config(threshold=0.5)

    def test_tilted_plane_accepts_zero(self):
        cfg = _make_config(threshold=0)
        assert cfg.threshold.method == "cutoff"
        assert cfg.threshold.value == 0.0

    def test_otsu_rejected(self):
        """Otsu was removed — should no longer be accepted."""
        with pytest.raises(ValidationError):
            self._benefit_base(threshold="otsu")


class TestAnalysisPeriodMapping:
    """analysis_period mapping (ladybug AnalysisPeriod.to_dict() keys)
    expands into the six flat period fields."""

    _PERIOD = {"st_month": 10, "st_day": 15, "st_hour": 7,
               "end_month": 4, "end_day": 15, "end_hour": 19}

    def test_ladybug_keys_expand(self):
        cfg = _make_config(
            mode="benefit", epw_path="dummy.epw",
            tilted_plane_angle_deg=None,
            analysis_period=self._PERIOD,
        )
        assert (cfg.start_month, cfg.start_day, cfg.start_hour) == (10, 15, 7)
        assert (cfg.end_month, cfg.end_day, cfg.end_hour) == (4, 15, 19)

    def test_ladybug_to_dict_extras_tolerated(self):
        """type/timestep/is_leap_year from AnalysisPeriod.to_dict() are ignored."""
        period = dict(self._PERIOD, type="AnalysisPeriod", timestep=1, is_leap_year=False)
        cfg = _make_config(
            mode="benefit", epw_path="dummy.epw",
            tilted_plane_angle_deg=None,
            analysis_period=period,
        )
        assert cfg.start_month == 10

    def test_start_spellings_accepted(self):
        cfg = _make_config(
            mode="benefit", epw_path="dummy.epw",
            tilted_plane_angle_deg=None,
            analysis_period={"start_month": 1, "start_day": 1, "start_hour": 8,
                             "end_month": 12, "end_day": 31, "end_hour": 16},
        )
        assert cfg.start_hour == 8
        assert cfg.end_hour == 16

    def test_unknown_key_rejected(self):
        with pytest.raises(ValidationError, match="analysis_period"):
            _make_config(
                mode="benefit", epw_path="dummy.epw",
                tilted_plane_angle_deg=None,
                analysis_period=dict(self._PERIOD, st_minute=30),
            )

    def test_conflict_with_flat_field_rejected(self):
        with pytest.raises(ValidationError, match="conflicts"):
            _make_config(
                mode="benefit", epw_path="dummy.epw",
                tilted_plane_angle_deg=None,
                start_month=1,
                analysis_period=self._PERIOD,
            )

    def test_matching_flat_field_allowed(self):
        cfg = _make_config(
            mode="benefit", epw_path="dummy.epw",
            tilted_plane_angle_deg=None,
            start_month=10,
            analysis_period=self._PERIOD,
        )
        assert cfg.start_month == 10


class TestDesignConstraintFields:
    def test_edge_taper_default_off(self):
        cfg = _make_config()
        assert cfg.edge_taper == 0.0

    def test_edge_taper_negative_rejected(self):
        with pytest.raises(ValidationError, match="edge_taper"):
            _make_config(edge_taper=-1.0)

    def test_min_sky_elevation_bounds(self):
        cfg = _make_config(min_sky_elevation_deg=30.0)
        assert cfg.min_sky_elevation_deg == 30.0
        with pytest.raises(ValidationError, match="min_sky_elevation_deg"):
            _make_config(min_sky_elevation_deg=90.0)
        with pytest.raises(ValidationError, match="min_sky_elevation_deg"):
            _make_config(min_sky_elevation_deg=-5.0)


class TestDaylightMode:
    def test_daylight_no_epw_required(self):
        """Daylight mode uses CIE overcast sky — should not require EPW."""
        cfg = _make_config(
            mode="daylight",
            tilted_plane_angle_deg=None,
        )
        assert cfg.mode == "daylight"

    def test_daylight_no_period_required(self):
        """Daylight mode should not require analysis period fields."""
        cfg = _make_config(
            mode="daylight",
            tilted_plane_angle_deg=None,
        )
        assert cfg.start_month is None

    def test_daylight_with_period_accepted(self):
        """Daylight with explicit period should also work."""
        cfg = _make_config(
            mode="daylight",
            tilted_plane_angle_deg=None,
            start_month=1, start_day=1, start_hour=8,
            end_month=12, end_day=31, end_hour=17,
        )
        assert cfg.mode == "daylight"


class TestNorthDegAndGroundReflectance:
    def test_north_deg_default(self):
        cfg = _make_config()
        assert cfg.north_deg == 0.0

    def test_north_deg_valid(self):
        cfg = _make_config(north_deg=180.0)
        assert cfg.north_deg == 180.0

    def test_north_deg_negative_rejected(self):
        with pytest.raises(ValidationError):
            _make_config(north_deg=-1.0)

    def test_north_deg_360_rejected(self):
        with pytest.raises(ValidationError):
            _make_config(north_deg=360.0)

    def test_ground_reflectance_removed(self):
        """ground_reflectance never affected results and was removed; the
        strict schema (extra='forbid') must reject configs that carry it."""
        with pytest.raises(ValidationError, match="ground_reflectance"):
            _make_config(ground_reflectance=0.2)


class TestBenefitParams:
    def test_balance_defaults_follow_ladybug(self):
        cfg = _make_config()
        assert cfg.balance_temperature == 15.0
        assert cfg.balance_offset == 2.0

    def test_negative_balance_offset_rejected(self):
        """A negative offset would silently invert the dead-band."""
        with pytest.raises(ValidationError, match="balance_offset"):
            _make_config(balance_offset=-1.0)

    def test_zero_offset_allowed(self):
        cfg = _make_config(balance_offset=0.0)
        assert cfg.balance_offset == 0.0

    def test_include_harm_default_false(self):
        cfg = _make_config()
        assert cfg.include_harm is False


class TestEnvVarFallback:
    def test_garbage_ray_batch_env(self, monkeypatch):
        monkeypatch.setenv("USC_MAX_RAY_BATCH", "not_a_number")
        cfg = _make_config(ray_batch_size=999999999)
        # Should clamp to default 2M, not crash
        assert cfg.ray_batch_size == 2_000_000


class TestExtraFieldsRejected:
    def test_unknown_key_rejected(self):
        """Unknown YAML keys must raise, not be silently swallowed."""
        with pytest.raises(ValidationError, match="extra"):
            _make_config(score_scale="linear")

    def test_typo_key_rejected(self):
        with pytest.raises(ValidationError, match="extra"):
            _make_config(vocel_size=0.5)


class TestCarveAboveConfig:
    def test_defaults(self):
        cfg = _make_config()
        assert cfg.carve_above is False
        assert cfg.carve_above_min_consecutive == 1

    def test_carve_above_enabled(self):
        cfg = _make_config(carve_above=True, carve_above_min_consecutive=3)
        assert cfg.carve_above is True
        assert cfg.carve_above_min_consecutive == 3

    def test_min_consecutive_must_be_positive(self):
        with pytest.raises(ValidationError):
            _make_config(carve_above_min_consecutive=0)

    def test_min_consecutive_must_be_int(self):
        cfg = _make_config(carve_above_min_consecutive=2)
        assert cfg.carve_above_min_consecutive == 2
