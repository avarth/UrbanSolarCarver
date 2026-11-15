"""The committed launchers of the browser app: start-urbansolarcarver.bat and .sh."""
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]
WINDOWS_LAUNCHER = REPOSITORY / "start-urbansolarcarver.bat"
UNIX_LAUNCHER = REPOSITORY / "start-urbansolarcarver.sh"
WINDOWS_SETUP = REPOSITORY / "setup-urbansolarcarver.bat"
RUNNING_ON_WINDOWS = platform.system() == "Windows"


def environment_of_this_interpreter() -> Path:
    """The venv folder of the Python running the tests (its Scripts or bin parent)."""
    return Path(sys.executable).resolve().parents[1]


def launcher_environment(**variables: str) -> dict:
    environment = {key: value for key, value in os.environ.items() if key != "USC_VENV"}
    environment.update(variables)
    return environment


@pytest.mark.parametrize("script", [WINDOWS_LAUNCHER, WINDOWS_SETUP])
def test_the_windows_scripts_keep_windows_line_endings(script):
    text = script.read_bytes().decode("utf-8")
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
    assert "USC_VENV" in text and ".venv" in text
    assert "D:\\" not in text and "/home/" not in text and "C:\\Users" not in text   # no machine paths


def test_the_unix_launcher_still_installs_on_its_first_run():
    text = UNIX_LAUNCHER.read_text(encoding="utf-8")
    assert "setup_env.py" in text and ".usc-venv" in text


def test_the_windows_launcher_uses_only_the_environment_in_its_folder():
    text = WINDOWS_LAUNCHER.read_text(encoding="utf-8")
    assert "setup-urbansolarcarver.bat" in text and "WARP_CACHE_PATH" in text and ".runtime" in text
    assert ".usc-venv" not in text and "setup_env.py" not in text
    assert "where py" not in text and "where python" not in text      # no system Python


def test_the_setup_script_pins_uv_and_checks_its_hash():
    text = WINDOWS_SETUP.read_text(encoding="utf-8")
    assert re.search(r"USC_UV_VERSION=\d+\.\d+\.\d+", text)
    assert re.search(r"USC_UV_SHA256=[0-9a-f]{64}\b", text)
    for needed in ("Get-FileHash", "uv-x86_64-pc-windows-msvc.zip", "--self-contained", "UV_PYTHON_PREFERENCE=only-managed",
                   "UV_PYTHON_INSTALL_DIR", "UV_CACHE_DIR", "--no-registry", "--no-bin"):
        assert needed in text, needed


def test_the_setup_script_changes_nothing_outside_its_folder():
    lowered = WINDOWS_SETUP.read_text(encoding="utf-8").lower()
    for forbidden in ("setx", "reg ", "runas", "invoke-expression", "iex", "| powershell", "|powershell",
                      'set "path=', "set path="):
        assert forbidden not in lowered, forbidden


@pytest.mark.slow   # two PowerShell starts, about 1 s
@pytest.mark.skipif(not RUNNING_ON_WINDOWS, reason="runs cmd.exe")
def test_a_uv_zip_whose_hash_does_not_match_is_deleted_and_setup_stops(tmp_path):
    folder = tmp_path / "A B (1)"
    folder.mkdir()
    shutil.copy(WINDOWS_SETUP, folder)
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not uv")
    result = subprocess.run(["cmd", "/c", str(folder / WINDOWS_SETUP.name)], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=120, env=launcher_environment(USC_UV_ZIP=str(junk)))
    assert result.returncode != 0
    assert "does not match" in result.stdout, result.stdout + result.stderr
    assert not (folder / ".runtime" / "uv").exists()
    assert not list((folder / ".runtime" / "download").glob("*.zip"))
    assert junk.exists()   # the test's own file is copied, never deleted


@pytest.mark.skipif(not RUNNING_ON_WINDOWS, reason="runs cmd.exe")
def test_the_windows_launcher_asks_for_setup_when_there_is_no_environment(tmp_path):
    folder = tmp_path / "A B (1)"
    folder.mkdir()
    shutil.copy(WINDOWS_LAUNCHER, folder)
    result = subprocess.run(["cmd", "/c", str(folder / WINDOWS_LAUNCHER.name)], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=60, env=launcher_environment())
    assert result.returncode == 1
    assert "Run setup-urbansolarcarver.bat first." in result.stdout, result.stdout + result.stderr
    assert not (folder / ".venv").exists()


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


def test_the_setup_script_finds_its_python_without_reading_a_file_in_the_console_code_page():
    """set /p reads a file in the console code page, so a UTF-8 path with Greek letters came back garbled and setup stopped."""
    text = WINDOWS_SETUP.read_text(encoding="utf-8")
    assert "set /p" not in text.lower()
    assert r'USC_PYTHON=%USC_RUNTIME%\python\cpython-%USC_PYTHON_VERSION%-windows-x86_64-none\python.exe' in text


def test_the_setup_script_runs_uv_only_after_a_hash_check_that_returned_exactly_zero():
    """if errorlevel N means at least N: a crashed PowerShell (a negative exit code) passed both checks."""
    lines = WINDOWS_SETUP.read_text(encoding="utf-8").splitlines()
    check = next(index for index, line in enumerate(lines) if "Get-FileHash" in line)
    assert lines[check + 1:check + 4].count('if not "%errorlevel%"=="0" goto unzip_failed') == 1
