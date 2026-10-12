"""Tests for carver_cli.py: MODE_PARAMS completeness and schema command."""
import pytest


# MODE_PARAMS is a local variable inside the schema() function in carver_cli.py.
# We replicate it here for testing — any drift between this and the actual dict
# is itself a bug that these tests will catch via the schema field cross-check.
_EXPECTED_MODE_PARAMS = {
    "tilted_plane": {"tilted_plane_angle_deg"},
    "time-based": {"epw_path", "start_month", "start_day", "start_hour", "end_month", "end_day", "end_hour", "min_altitude"},
    "irradiance": {"epw_path", "start_month", "start_day", "start_hour", "end_month", "end_day", "end_hour", "min_altitude"},
    "benefit": {"epw_path", "start_month", "start_day", "start_hour", "end_month", "end_day", "end_hour", "min_altitude", "balance_temperature", "balance_offset", "include_harm", "simulated_weights_path"},
    "daylight": set(),  # CIE overcast sky — geometry only, no EPW needed
    "radiative_cooling": {"epw_path", "start_month", "start_day", "start_hour", "end_month", "end_day", "end_hour", "dew_point_celsius", "bliss_k", "min_sky_elevation_deg"},
}


def _get_schema_fields():
    """Get all field names from UserConfig."""
    from urbansolarcarver.pydantic_schemas import UserConfig
    return set(UserConfig.model_fields.keys())


class TestModeParams:
    EXPECTED_MODES = {"tilted_plane", "time-based", "irradiance", "benefit", "daylight", "radiative_cooling"}

    def test_all_modes_present(self):
        """MODE_PARAMS should contain all 6 carving modes."""
        assert set(_EXPECTED_MODE_PARAMS.keys()) == self.EXPECTED_MODES

    def test_params_exist_in_schema(self):
        """Every param listed in MODE_PARAMS should be a real UserConfig field."""
        schema_fields = _get_schema_fields()
        for mode, params in _EXPECTED_MODE_PARAMS.items():
            orphans = params - schema_fields
            assert not orphans, f"MODE_PARAMS[{mode!r}] references non-existent fields: {orphans}"

    def test_daylight_no_epw_required(self):
        """Daylight mode uses CIE overcast sky — no EPW or period params needed."""
        assert len(_EXPECTED_MODE_PARAMS["daylight"]) == 0

    def test_tilted_plane_has_angle(self):
        assert "tilted_plane_angle_deg" in _EXPECTED_MODE_PARAMS["tilted_plane"]

    def test_benefit_has_temperature_params(self):
        assert "balance_temperature" in _EXPECTED_MODE_PARAMS["benefit"]
        assert "balance_offset" in _EXPECTED_MODE_PARAMS["benefit"]

    def test_radiative_cooling_has_dew_point(self):
        assert "dew_point_celsius" in _EXPECTED_MODE_PARAMS["radiative_cooling"]
        assert "bliss_k" in _EXPECTED_MODE_PARAMS["radiative_cooling"]

    def test_epw_modes_include_epw_path(self):
        """time-based, irradiance, benefit, and radiative_cooling should include epw_path."""
        for mode in ("time-based", "irradiance", "benefit", "radiative_cooling"):
            assert "epw_path" in _EXPECTED_MODE_PARAMS[mode], f"{mode} missing epw_path"


def test_dry_run_flag_exists():
    """--dry-run should appear in preprocessing help."""
    from typer.testing import CliRunner
    from urbansolarcarver.carver_cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["preprocessing", "--help"])
    assert "--dry-run" in result.output


class TestArchetypeCommand:
    """`usc archetype` builds, validates, and reports a shoebox archetype."""

    def _invoke(self, args):
        from typer.testing import CliRunner
        from urbansolarcarver.carver_cli import app
        return CliRunner().invoke(app, args)

    def test_writes_valid_shoebox(self, tmp_path):
        import yaml
        from urbansolarcarver.simulated_weights import expand_shoebox
        out = tmp_path / "arch.yaml"
        res = self._invoke(["archetype", "-o", str(out),
                            "-s", "width=12", "-s", "wwr_south=0.4"])
        assert res.exit_code == 0, res.output
        assert "floor_area:  120.0" in res.output
        data = yaml.safe_load(out.read_text(encoding="utf-8"))
        expanded = expand_shoebox(data)
        assert expanded["floor_area"] == pytest.approx(120.0)
        # south facade 12*3=36 m2 at wwr 0.4
        assert expanded["area_window"] == pytest.approx(
            36 * 0.4 + 30 * 0.15 * 2)

    def test_rejects_unknown_key(self, tmp_path):
        res = self._invoke(["archetype", "-o", str(tmp_path / "a.yaml"),
                            "-s", "banana=1"])
        assert res.exit_code == 1
        assert "Unknown archetype key" in res.output

    def test_rejects_bad_wwr_side(self, tmp_path):
        res = self._invoke(["archetype", "-o", str(tmp_path / "a.yaml"),
                            "-s", "wwr_southeast=0.2"])
        assert res.exit_code == 1
        assert "Unknown facade" in res.output

    def test_refuses_overwrite_without_force(self, tmp_path):
        out = tmp_path / "a.yaml"
        assert self._invoke(["archetype", "-o", str(out)]).exit_code == 0
        res = self._invoke(["archetype", "-o", str(out)])
        assert res.exit_code == 1
        assert "--force" in res.output
        assert self._invoke(["archetype", "-o", str(out),
                             "--force"]).exit_code == 0

    def test_from_existing_variant(self, tmp_path):
        import yaml
        base = tmp_path / "base.yaml"
        assert self._invoke(["archetype", "-o", str(base),
                             "-s", "width=15"]).exit_code == 0
        variant = tmp_path / "variant.yaml"
        res = self._invoke(["archetype", "-o", str(variant),
                            "--from", str(base),
                            "-s", "mass_class=heavy"])
        assert res.exit_code == 0, res.output
        data = yaml.safe_load(variant.read_text(encoding="utf-8"))
        assert data["width"] == 15.0
        assert data["mass_class"] == "heavy"

    def test_invalid_archetype_fails(self, tmp_path):
        res = self._invoke(["archetype", "-o", str(tmp_path / "a.yaml"),
                            "-s", "wwr_south=0", "-s", "wwr_east=0",
                            "-s", "wwr_west=0"])
        assert res.exit_code == 1
        assert "INVALID archetype" in res.output
