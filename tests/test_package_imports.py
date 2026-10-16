"""What importing the package costs, and which names it offers."""
import subprocess
import sys


def test_every_public_name_resolves():
    import urbansolarcarver
    missing = [name for name in urbansolarcarver.__all__ if not hasattr(urbansolarcarver, name)]
    assert missing == []


def _modules_loaded_by(code, env=None):
    out = subprocess.run(
        [sys.executable, "-c", code + "\nimport sys; print('LOADED_MODULES ' + ' '.join(sys.modules))"],
        capture_output=True, text=True, check=True, env=env)
    line = next(l for l in out.stdout.splitlines() if l.startswith("LOADED_MODULES "))
    return set(line.split()[1:])


def test_importing_the_package_does_not_load_torch():
    assert "torch" not in _modules_loaded_by("import urbansolarcarver")


def test_usc_daemon_status_does_not_load_torch(tmp_path):
    from _daemon_home import isolated_home_env
    code = ("from typer.testing import CliRunner\n"
            "from urbansolarcarver.carver_cli import app\n"
            "CliRunner().invoke(app, ['daemon', 'status'])")
    assert "torch" not in _modules_loaded_by(code, env=isolated_home_env(tmp_path))
