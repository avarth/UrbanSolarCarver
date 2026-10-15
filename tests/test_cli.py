"""Tests for carver_cli.py: the mode registry behind `schema --mode`, the
schema command itself, and the archetype command."""
import pytest

from urbansolarcarver.mode_registry import MODES
from urbansolarcarver.pydantic_schemas import UserConfig

_PERIOD = {"start_month", "start_day", "start_hour", "end_month", "end_day", "end_hour"}


class TestModeRegistry:
    def test_all_six_modes(self):
        assert set(MODES) == {"tilted_plane", "time-based", "irradiance", "benefit",
                              "daylight", "radiative_cooling"}

    def test_mode_params_are_config_fields(self):
        fields = set(UserConfig.model_fields)
        for name, spec in MODES.items():
            orphans = set(spec.extra_params) - fields
            assert not orphans, f"{name} lists unknown config fields: {orphans}"

    @pytest.mark.parametrize("mode", ["time-based", "irradiance", "benefit"])
    def test_weather_modes_take_epw_and_period(self, mode):
        assert {"epw_path"} | _PERIOD <= set(MODES[mode].extra_params)

    @pytest.mark.parametrize("mode", ["daylight", "radiative_cooling", "tilted_plane"])
    def test_other_modes_take_no_epw(self, mode):
        assert not ({"epw_path"} | _PERIOD) & set(MODES[mode].extra_params)


def _schema_names(args):
    from typer.testing import CliRunner
    from urbansolarcarver.carver_cli import app
    result = CliRunner().invoke(app, ["schema", *args], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    return {line.split()[0] for line in result.output.splitlines()
            if line and not line.startswith((" ", "-", "Name"))}


@pytest.mark.parametrize("mode", sorted(MODES))
def test_schema_for_mode_shows_own_fields_and_hides_others(mode):
    names = _schema_names(["--mode", mode])
    own = set(MODES[mode].extra_params)
    others = set().union(*(s.extra_params for s in MODES.values())) - own
    assert own <= names
    assert not (others & names)
    assert {"voxel_size", "carve_above", "out_dir"} <= names


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


def test_massing_command_exists():
    from typer.testing import CliRunner
    from urbansolarcarver.carver_cli import app
    result = CliRunner().invoke(app, ["massing", "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0 and "--from" in result.output and "--config" in result.output
