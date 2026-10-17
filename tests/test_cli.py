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


# ---------------------------------------------------------------------------
# The run contract: produce / start-from, issues printed, clean errors
# ---------------------------------------------------------------------------
def _write_cube_config(tmp_path, **overrides):
    import yaml
    from _stage_scene import daylight_cube_config
    conf = daylight_cube_config(tmp_path, **overrides)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(conf.model_dump(mode="json", exclude_none=True)),
                    encoding="utf-8")
    return path


def _invoke(args):
    from typer.testing import CliRunner
    from urbansolarcarver.carver_cli import app
    return CliRunner().invoke(app, args, env={"COLUMNS": "200"})


def test_run_produce_massing_skips_exporting(tmp_path):
    config = _write_cube_config(tmp_path)
    result = _invoke(["run", "-c", str(config), "--produce", "massing"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "run" / "massing" / "plates.json").is_file()
    assert not (tmp_path / "run" / "exporting").exists()
    assert "plates.json" in result.output


def test_run_defaults_to_exporting(tmp_path):
    config = _write_cube_config(tmp_path)
    result = _invoke(["run", "-c", str(config)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "run" / "exporting").is_dir()
    assert not (tmp_path / "run" / "massing").exists()


def test_run_start_from_reuses_the_earlier_stages(tmp_path):
    config = _write_cube_config(tmp_path)
    assert _invoke(["run", "-c", str(config), "--produce", "thresholding"]).exit_code == 0
    scores_modified = (tmp_path / "run" / "preprocessing" / "scores.npy").stat().st_mtime_ns
    result = _invoke(["run", "-c", str(config), "--produce", "exporting",
                      "--start-from", "thresholding"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "run" / "preprocessing" / "scores.npy").stat().st_mtime_ns == scores_modified
    assert (tmp_path / "run" / "exporting").is_dir()


def test_run_unknown_stage_is_a_usage_error(tmp_path):
    config = _write_cube_config(tmp_path)
    result = _invoke(["run", "-c", str(config), "--produce", "rendering"])
    assert result.exit_code == 2 and "rendering" in result.output


def test_run_start_from_outside_the_path_is_a_usage_error(tmp_path):
    config = _write_cube_config(tmp_path)
    result = _invoke(["run", "-c", str(config), "--produce", "preprocessing",
                      "--start-from", "massing"])
    assert result.exit_code == 2, result.output
    assert "--start-from" in result.output and "massing" in result.output
    assert "Traceback" not in result.output
    assert not (tmp_path / "run").exists()          # refused before anything ran


def test_invalid_config_prints_a_clean_error(tmp_path):
    config = _write_cube_config(tmp_path, voxel_size=2.0)
    text = config.read_text(encoding="utf-8").replace("voxel_size: 2.0", "voxel_size: 0")
    config.write_text(text, encoding="utf-8")
    result = _invoke(["run", "-c", str(config)])
    assert result.exit_code == 1
    assert "Error:" in result.output and "voxel_size" in result.output
    assert "Traceback" not in result.output
    assert isinstance(result.exception, SystemExit)


def test_error_without_manifest_to_start_from_is_clean(tmp_path):
    config = _write_cube_config(tmp_path)
    result = _invoke(["run", "-c", str(config), "--produce", "exporting",
                      "--start-from", "thresholding"])
    assert result.exit_code == 1
    assert "Error:" in result.output and "Traceback" not in result.output


def test_thresholding_prints_the_issues_of_the_stage(tmp_path):
    config = _write_cube_config(tmp_path)
    assert _invoke(["preprocessing", "-c", str(config)]).exit_code == 0
    result = _invoke(["thresholding", "-c", str(config), "-o", "threshold=1e9"])
    assert result.exit_code == 0, result.output
    assert "nothing_carved" in result.output


def test_config_issues_are_printed_and_a_clean_run_prints_none(tmp_path):
    import yaml
    config = _write_cube_config(tmp_path)
    result = _invoke(["preprocessing", "-c", str(config)])
    assert result.exit_code == 0, result.output
    assert "settings_unused_by_mode" in result.output  # the YAML sets weather fields daylight ignores
    minimal = yaml.safe_load(config.read_text(encoding="utf-8"))
    kept = {k: minimal[k] for k in ("max_volume_path", "test_surface_path", "out_dir", "mode",
                                    "voxel_size", "grid_step", "ray_length", "device")}
    config.write_text(yaml.safe_dump(kept), encoding="utf-8")
    result = _invoke(["preprocessing", "-c", str(config)])
    assert result.exit_code == 0, result.output
    assert "Issues" not in result.output


def test_run_on_the_daemon_sends_the_run_command(tmp_path, monkeypatch):
    from urbansolarcarver import carver_cli
    config = _write_cube_config(tmp_path)
    sent = []

    def fake_send(payload):
        sent.append(payload)
        return {"status": "ok", "stage_folders": {}, "manifest": "m.json",
                "issues": [{"stage": "thresholding", "code": "nothing_carved", "message": "all kept"}]}

    monkeypatch.setattr(carver_cli, "_daemon_send", fake_send)
    result = _invoke(["run", "-c", str(config), "--daemon", "--produce", "massing",
                      "--produce", "exporting", "--start-from", "thresholding"])
    assert result.exit_code == 0, result.output
    payload = sent[0]
    assert payload["cmd"] == "run"
    assert payload["produce"] == ["massing", "exporting"]
    assert payload["start_from"] == "thresholding"
    assert payload["run_folder"] == str((tmp_path / "run").resolve())
    assert payload["config"] == str(config.resolve())
    assert "nothing_carved" in result.output


def test_daemon_error_reply_is_reported(tmp_path, monkeypatch):
    from urbansolarcarver import carver_cli
    config = _write_cube_config(tmp_path)
    monkeypatch.setattr(carver_cli, "_daemon_send", lambda payload: {
        "status": "error", "error": "ConfigError: bad", "error_type": "ConfigError"})
    result = _invoke(["run", "-c", str(config), "--daemon"])
    assert result.exit_code == 1 and "ConfigError: bad" in result.output


def test_importing_the_cli_does_not_load_torch():
    import subprocess
    import sys
    code = ("import sys; import urbansolarcarver.carver_cli as c; "
            "sys.exit(1 if 'torch' in sys.modules else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_importing_the_cli_does_not_load_the_web_service():
    import subprocess
    import sys
    code = ("import sys; import urbansolarcarver.carver_cli as c; "
            "sys.exit(1 if 'fastapi' in sys.modules else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


class TestUiCommand:
    """`usc ui` checks the install, then starts the local service on 127.0.0.1 with a fresh token."""

    @pytest.fixture
    def built_front_end(self, tmp_path, monkeypatch):
        """A static folder with an index.html, standing in for the built front-end."""
        from urbansolarcarver import carver_cli
        static_folder = tmp_path / "ui_static"
        static_folder.mkdir()
        (static_folder / "index.html").write_text("<html></html>", encoding="utf-8")
        monkeypatch.setattr(carver_cli, "_ui_static_folder", lambda: static_folder)
        return static_folder

    @pytest.fixture
    def service_never_starts(self, monkeypatch):
        """Fails the test if the command gets as far as starting the service."""
        import uvicorn
        monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: pytest.fail("the service must not start"))
        monkeypatch.setattr(uvicorn.Server, "run", lambda *args, **kwargs: pytest.fail("the service must not start"))

    @staticmethod
    def _without_module(monkeypatch, missing_module):
        """Makes importlib.util.find_spec report one module as not installed."""
        import importlib.util
        real_find_spec = importlib.util.find_spec
        monkeypatch.setattr(importlib.util, "find_spec",
                            lambda name, *args, **kwargs: None if name == missing_module else real_find_spec(name, *args, **kwargs))

    @pytest.mark.parametrize("missing_module", ["fastapi", "uvicorn", "multipart", "websockets"])
    def test_without_the_extra_names_the_install_command(self, monkeypatch, built_front_end, service_never_starts, missing_module):
        import sys
        self._without_module(monkeypatch, missing_module)
        result = _invoke(["ui", "--no-browser"])
        assert result.exit_code == 1
        assert "[ui]" in result.output
        assert "-m pip install" in result.output
        assert sys.executable in result.output
        assert missing_module in result.output

    def test_the_install_command_quotes_a_python_path_with_spaces(self, monkeypatch, built_front_end, service_never_starts):
        monkeypatch.setattr("sys.executable", "C:\\Program Files\\Python 3\\python.exe")
        self._without_module(monkeypatch, "websockets")
        result = _invoke(["ui", "--no-browser"])
        assert result.exit_code == 1
        assert '"C:\\Program Files\\Python 3\\python.exe" -m pip install' in result.output

    def test_the_install_command_leaves_a_python_path_without_spaces_bare(self, monkeypatch):
        from urbansolarcarver import carver_cli
        monkeypatch.setattr("sys.executable", "C:\\Python3\\python.exe")
        assert carver_cli._ui_install_command().startswith("C:\\Python3\\python.exe -m pip install")

    def test_without_the_front_end_names_the_build_command(self, monkeypatch, tmp_path):
        from urbansolarcarver import carver_cli
        missing_folder = tmp_path / "no_front_end"
        monkeypatch.setattr(carver_cli, "_ui_static_folder", lambda: missing_folder)
        result = _invoke(["ui", "--no-browser", "--projects-folder", str(tmp_path / "projects")])
        assert result.exit_code == 1
        assert "npm run build" in result.output
        assert "no_front_end" in result.output

    @staticmethod
    def _server_that_starts_listening(monkeypatch, events):
        """Replaces the uvicorn server run by one that records its address, then listens until the browser was asked to open."""
        import time
        import uvicorn

        def run(server, sockets=None):
            events.append(("server_run", server.config.host, server.config.port))
            server.started = True
            deadline = time.monotonic() + 10
            while not any(event[0] == "browser_open" for event in events) and time.monotonic() < deadline:
                time.sleep(0.01)

        monkeypatch.setattr(uvicorn.Server, "run", run)

    def test_starts_uvicorn_on_localhost_with_a_token(self, monkeypatch, tmp_path, built_front_end):
        import re
        import webbrowser
        from urbansolarcarver.local_web_service.gpu_warm_up import GpuWarmUp

        events = []
        monkeypatch.setattr(GpuWarmUp, "start", lambda self: events.append("warm_up_start"))
        self._server_that_starts_listening(monkeypatch, events)
        monkeypatch.setattr(webbrowser, "open", lambda url: events.append(("browser_open", url)))

        projects_folder = tmp_path / "projects"
        result = _invoke(["ui", "--projects-folder", str(projects_folder)])

        assert result.exit_code == 0, result.output
        assert events[:2] == ["warm_up_start", ("server_run", "127.0.0.1", 8770)] and len(events) == 3
        opened_url = events[2][1]
        assert re.fullmatch(r"http://127\.0\.0\.1:8770/\?token=[0-9a-f]{64}", opened_url)
        assert opened_url in result.output
        assert projects_folder.is_dir()

    def test_the_browser_opens_only_once_the_server_listens(self, monkeypatch, tmp_path, built_front_end):
        import time
        import uvicorn
        import webbrowser
        from urbansolarcarver.local_web_service.gpu_warm_up import GpuWarmUp

        opened_urls = []
        urls_opened_before_listening = []

        def run(server, sockets=None):
            time.sleep(0.3)     # longer than the polling of the thread that waits to open the browser
            urls_opened_before_listening.extend(opened_urls)
            server.started = True
            deadline = time.monotonic() + 10
            while not opened_urls and time.monotonic() < deadline:
                time.sleep(0.01)

        monkeypatch.setattr(GpuWarmUp, "start", lambda self: None)
        monkeypatch.setattr(uvicorn.Server, "run", run)
        monkeypatch.setattr(webbrowser, "open", opened_urls.append)

        result = _invoke(["ui", "--projects-folder", str(tmp_path / "projects")])

        assert result.exit_code == 0, result.output
        assert urls_opened_before_listening == [] and len(opened_urls) == 1

    def test_no_browser_prints_the_url_and_opens_nothing(self, monkeypatch, tmp_path, built_front_end):
        import webbrowser
        from urbansolarcarver.local_web_service.gpu_warm_up import GpuWarmUp

        events = []
        monkeypatch.setattr(GpuWarmUp, "start", lambda self: None)
        self._server_that_starts_listening(monkeypatch, events)
        events.append(("browser_open", "not expected"))      # lets the fake server return at once
        monkeypatch.setattr(webbrowser, "open", lambda url: pytest.fail("the browser must not open"))

        result = _invoke(["ui", "--no-browser", "--port", "8123", "--projects-folder", str(tmp_path / "projects")])

        assert result.exit_code == 0, result.output
        assert events[1] == ("server_run", "127.0.0.1", 8123)
        assert "http://127.0.0.1:8123/?token=" in result.output

    def test_a_taken_port_is_named_and_the_browser_never_opens(self, monkeypatch, tmp_path, built_front_end):
        import socket
        import webbrowser
        from urbansolarcarver.local_web_service.gpu_warm_up import GpuWarmUp

        monkeypatch.setattr(GpuWarmUp, "start", lambda self: None)
        monkeypatch.setattr(webbrowser, "open", lambda url: pytest.fail("the browser must not open"))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as other_program:
            other_program.bind(("127.0.0.1", 0))
            other_program.listen()
            taken_port = other_program.getsockname()[1]

            result = _invoke(["ui", "--port", str(taken_port), "--projects-folder", str(tmp_path / "projects")])

        assert result.exit_code == 1, result.output
        assert f"port {taken_port}" in result.output and "--port" in result.output
        assert f"http://127.0.0.1:{taken_port}/?token=" in result.output      # the launch URL is still printed

    def test_an_unknown_device_is_refused(self, tmp_path, built_front_end):
        result = _invoke(["ui", "--no-browser", "--device", "tpu", "--projects-folder", str(tmp_path / "projects")])
        assert result.exit_code == 1
        assert "tpu" in result.output

    def test_the_token_is_kept_out_of_uvicorn_log_lines(self):
        import logging
        from urbansolarcarver.carver_cli import _TokenRedactingFilter

        token = "ab" * 32
        record = logging.LogRecord(
            "uvicorn.error", logging.INFO, __file__, 0, '%s - "WebSocket %s" [accepted]',
            ("127.0.0.1:50000", f"/api/v1/events?token={token}&x=1"), None)
        assert _TokenRedactingFilter().filter(record) is True
        assert token not in record.getMessage()
        assert "token=" in record.getMessage() and "x=1" in record.getMessage()

