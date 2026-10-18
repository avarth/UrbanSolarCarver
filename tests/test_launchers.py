"""The committed launchers of the browser app: start-urbansolarcarver.bat and .sh."""
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]
WINDOWS_LAUNCHER = REPOSITORY / "start-urbansolarcarver.bat"
UNIX_LAUNCHER = REPOSITORY / "start-urbansolarcarver.sh"
RUNNING_ON_WINDOWS = platform.system() == "Windows"


def environment_of_this_interpreter() -> Path:
    """The venv folder of the Python running the tests (its Scripts or bin parent)."""
    return Path(sys.executable).resolve().parents[1]


def launcher_environment(**variables: str) -> dict:
    environment = {key: value for key, value in os.environ.items() if key != "USC_VENV"}
    environment.update(variables)
    return environment


def test_the_windows_launcher_keeps_windows_line_endings():
    text = WINDOWS_LAUNCHER.read_bytes().decode("utf-8")
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")


def test_the_unix_launcher_keeps_unix_line_endings_and_a_shebang():
    text = UNIX_LAUNCHER.read_bytes().decode("utf-8")
    assert text.startswith("#!/usr/bin/env bash\n") and "\r" not in text


def test_the_unix_launcher_is_executable_in_git():
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    entry = subprocess.run(["git", "ls-files", "-s", UNIX_LAUNCHER.name], cwd=REPOSITORY,
                           capture_output=True, text=True, check=True).stdout
    assert entry.startswith("100755"), entry


@pytest.mark.parametrize("launcher", [WINDOWS_LAUNCHER, UNIX_LAUNCHER])
def test_both_launchers_find_their_folder_and_start_usc_ui(launcher):
    text = launcher.read_text(encoding="utf-8")
    assert "urbansolarcarver.carver_cli ui" in text
    assert "setup_env.py" in text            # the first run installs
    assert "USC_VENV" in text and ".usc-venv" in text and ".venv" in text
    assert "D:\\" not in text and "/home/" not in text and "C:\\Users" not in text   # no machine paths


@pytest.mark.skipif(not RUNNING_ON_WINDOWS, reason="runs cmd.exe")
def test_the_windows_launcher_starts_usc_ui_with_the_given_environment():
    result = subprocess.run(["cmd", "/c", str(WINDOWS_LAUNCHER), "--help"], input="\n",
                            capture_output=True, text=True, timeout=120,
                            env=launcher_environment(USC_VENV=str(environment_of_this_interpreter())))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--port" in result.stdout and "--no-browser" in result.stdout


@pytest.mark.skipif(not RUNNING_ON_WINDOWS, reason="runs cmd.exe")
def test_the_windows_launcher_explains_a_missing_given_environment(tmp_path):
    missing = tmp_path / "no venv (here)"
    result = subprocess.run(["cmd", "/c", str(WINDOWS_LAUNCHER)], input="\n",
                            capture_output=True, text=True, timeout=60,
                            env=launcher_environment(USC_VENV=str(missing)))
    assert result.returncode == 1
    assert "No Python environment was found at USC_VENV" in result.stdout
    assert str(missing) in result.stdout


@pytest.mark.skipif(RUNNING_ON_WINDOWS, reason="a Windows venv has no bin/python")
def test_the_unix_launcher_starts_usc_ui_with_the_given_environment():
    result = subprocess.run(["bash", str(UNIX_LAUNCHER), "--help"], capture_output=True, text=True,
                            timeout=120, env=launcher_environment(USC_VENV=str(environment_of_this_interpreter())))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--port" in result.stdout and "--no-browser" in result.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not available")
def test_the_unix_launcher_explains_a_missing_given_environment(tmp_path):
    missing = tmp_path / "no venv here"
    result = subprocess.run(["bash", UNIX_LAUNCHER.as_posix()], capture_output=True, text=True, timeout=60,
                            env=launcher_environment(USC_VENV=missing.as_posix()))
    assert result.returncode == 1
    assert "No Python environment was found at USC_VENV" in result.stdout
