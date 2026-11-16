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
LINUX_SETUP = REPOSITORY / "setup-urbansolarcarver.sh"
RUNNING_ON_LINUX = platform.system() == "Linux"
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


@pytest.mark.parametrize("script", [UNIX_LAUNCHER, LINUX_SETUP])
def test_the_linux_scripts_keep_unix_line_endings_and_a_shebang(script):
    text = script.read_bytes().decode("utf-8")
    assert text.startswith("#!/usr/bin/env bash\n") and "\r" not in text


@pytest.mark.parametrize("script", [UNIX_LAUNCHER, LINUX_SETUP])
def test_the_linux_scripts_are_executable_in_git(script):
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    entry = subprocess.run(["git", "ls-files", "-s", script.name], cwd=REPOSITORY,
                           capture_output=True, text=True, check=True).stdout
    assert entry.startswith("100755"), entry


@pytest.mark.parametrize("launcher", [WINDOWS_LAUNCHER, UNIX_LAUNCHER])
def test_both_launchers_find_their_folder_and_start_usc_ui(launcher):
    text = launcher.read_text(encoding="utf-8")
    assert "urbansolarcarver.carver_cli ui" in text
    assert "USC_VENV" in text and ".venv" in text
    assert "D:\\" not in text and "/home/" not in text and "C:\\Users" not in text   # no machine paths


def test_the_unix_launcher_uses_only_the_environment_in_its_folder():
    text = UNIX_LAUNCHER.read_text(encoding="utf-8")
    assert "setup-urbansolarcarver.sh" in text and "WARP_CACHE_PATH" in text and ".runtime" in text
    assert ".usc-venv" not in text
    assert "command -v python" not in text      # no system Python


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not available")
def test_the_unix_launcher_asks_for_setup_when_there_is_no_environment(tmp_path):
    folder = tmp_path / "A B (1)"
    folder.mkdir()
    shutil.copy(UNIX_LAUNCHER, folder)
    result = subprocess.run(["bash", (folder / UNIX_LAUNCHER.name).as_posix()], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=60, env=launcher_environment())
    assert result.returncode == 1
    assert "Run ./setup-urbansolarcarver.sh first." in result.stdout, result.stdout + result.stderr
    assert not (folder / ".venv").exists()


def _assignment(text: str, name: str) -> str:
    return re.search(rf'^(?:set ")?{name}="?([^"\r\n]+)"?$', text, re.MULTILINE).group(1)


def test_the_linux_setup_pins_uv_and_python_as_the_windows_one_does_and_checks_uvs_hash():
    linux, windows = LINUX_SETUP.read_text(encoding="utf-8"), WINDOWS_SETUP.read_text(encoding="utf-8")
    assert re.fullmatch(r"[0-9a-f]{64}", _assignment(linux, "USC_UV_SHA256"))
    assert _assignment(linux, "USC_UV_SHA256") != _assignment(windows, "USC_UV_SHA256")    # another file, another hash
    for name in ("USC_UV_VERSION", "USC_PYTHON_VERSION"):
        assert _assignment(linux, name) == _assignment(windows, name), name
    for needed in ("sha256sum", "uv-x86_64-unknown-linux-gnu.tar.gz", "--self-contained", 'UV_PYTHON_PREFERENCE="only-managed"',
                   "UV_PYTHON_INSTALL_DIR", "UV_CACHE_DIR", "UV_NO_CONFIG=1", "UV_NATIVE_TLS=1", "--no-bin", "--proto '=https'",
                   "--https-only", 'export TMPDIR="$runtime/tmp"'):
        assert needed in linux, needed


def test_the_linux_setup_unpacks_and_runs_uv_only_after_its_hash_matched():
    text = LINUX_SETUP.read_text(encoding="utf-8")
    check = text.index('!= "$USC_UV_SHA256"')
    assert check < text.index("tar -xzf") < text.index('"$uv" python install')
    assert 'rm -f "$download"' in text[check:text.index("tar -xzf")]


def test_the_linux_setup_checks_before_downloading():
    text = LINUX_SETUP.read_text(encoding="utf-8")
    first_download = text.index("curl --fail")
    for check in ('uname -m)" != "x86_64"', 'id -u)" = "0"', "GNU_LIBC_VERSION", "msdos|vfat|exfat|ntfs|ntfs3|fuseblk",
                  "exec-check", "link-check", "df -Pk", "UV_*|PIP_*) unset", "needed_gb=12", "needed_gb=2"):
        assert text.index(check) < first_download, check


def test_the_linux_setup_changes_nothing_outside_its_folder_but_the_menu_entry():
    text = LINUX_SETUP.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("#", "echo", "fail ", '"')))
    for forbidden in ("sudo", ".bashrc", ".profile", "export PATH", "eval ", "| sh", "| bash", "/etc/", "/usr/", "chmod -R"):
        assert forbidden not in code, forbidden
    assert re.search(r'read -r -t 30 -p "Add UrbanSolarCarver to the applications menu\? \[y/N\] "', text)
    assert 'entry="$applications/urbansolarcarver.desktop"' in text and "Terminal=true" in text


@pytest.mark.skipif(not RUNNING_ON_LINUX, reason="the Linux setup stops on other systems")
def test_the_linux_setup_run_alone_asks_to_extract_first(tmp_path):
    folder = tmp_path / "R&D (1)"
    folder.mkdir()
    shutil.copy(LINUX_SETUP, folder)
    result = subprocess.run(["bash", str(folder / LINUX_SETUP.name)], stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=60, env=launcher_environment())
    assert result.returncode == 1
    assert "Extract the whole folder first" in result.stdout, result.stdout + result.stderr
    assert not (folder / ".runtime").exists()


@pytest.mark.skipif(not RUNNING_ON_LINUX, reason="the Linux setup stops on other systems")
def test_a_uv_archive_whose_hash_does_not_match_is_deleted_and_the_linux_setup_stops(tmp_path):
    folder = tmp_path / "A B (1)"
    folder.mkdir()
    shutil.copy(LINUX_SETUP, folder)
    for name in (*SETUP_NEIGHBOURS, "install/requirements-linux-cuda-hashed.txt"):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPOSITORY / name, folder / name)
    junk = tmp_path / "junk.tar.gz"
    junk.write_bytes(b"not uv")
    result = subprocess.run(["bash", str(folder / LINUX_SETUP.name), "--cpu"], stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=60, env=launcher_environment(USC_UV_ARCHIVE=str(junk)))
    assert result.returncode == 1
    assert "does not match" in result.stdout, result.stdout + result.stderr
    assert not (folder / ".runtime" / "uv").exists()
    assert not list((folder / ".runtime" / "download").glob("*.tar.gz"))
    assert junk.exists()


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
    unzipped_copy(folder)
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


def run_as_explorer_does(script: Path, **variables: str) -> subprocess.CompletedProcess:
    """Start a .bat as a double-click does, cmd /c ""<path>"", so an & or ) in the path stays inside the quotes."""
    return subprocess.run(f'cmd /s /c ""{script}""', stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=60, env=launcher_environment(**variables))


SETUP_NEIGHBOURS = ("install/setup_env.py", "install/requirements-lock.txt", "install/requirements-lock-hashed.txt")
PATH_VARIABLES = re.compile(r"%USC_(FOLDER|RUNTIME|POWERSHELL|VENV|DOWNLOAD|PYTHON|REPOSITORY|UV|TMP)%")


def unzipped_copy(folder: Path) -> Path:
    """The setup script with the files it needs beside it, as after unzipping the repository."""
    folder.mkdir(parents=True)
    shutil.copy(WINDOWS_SETUP, folder)
    for name in SETUP_NEIGHBOURS:
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPOSITORY / name, folder / name)
    return folder / WINDOWS_SETUP.name


@pytest.mark.skipif(not RUNNING_ON_WINDOWS, reason="runs cmd.exe")
def test_the_setup_run_alone_from_inside_the_zip_asks_to_unzip_first(tmp_path):
    """Explorer copies a .bat run from inside a zip alone to a temp folder: stop before anything is downloaded."""
    folder = tmp_path / "R&D (1)"
    folder.mkdir()
    shutil.copy(WINDOWS_SETUP, folder)
    result = run_as_explorer_does(folder / WINDOWS_SETUP.name)
    assert result.returncode == 1
    assert "Unzip the whole folder first, then run setup from there." in result.stdout, result.stdout + result.stderr
    assert str(folder) in result.stdout            # the & did not split the echoed path
    assert "is not recognized" not in result.stdout + result.stderr
    assert not (folder / ".runtime").exists()


@pytest.mark.parametrize("script", [WINDOWS_SETUP, WINDOWS_LAUNCHER])
def test_every_echoed_path_is_in_quotes_so_an_ampersand_cannot_split_the_line(script):
    for line in script.read_text(encoding="utf-8").splitlines():
        if line.lstrip().lower().startswith("echo"):
            outside_quotes = re.sub(r'"[^"]*"', "", line)
            assert not PATH_VARIABLES.search(outside_quotes), line


def test_the_setup_stops_in_a_onedrive_folder_before_downloading():
    text = WINDOWS_SETUP.read_text(encoding="utf-8")
    for variable in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        assert f"'{variable}'" in text
    assert "OrdinalIgnoreCase" in text and "goto onedrive" in text
    assert text.index("goto onedrive") < text.index("Invoke-WebRequest")
    message = text[text.index(":onedrive"):text.index("goto fail", text.index(":onedrive"))]
    assert "upload" in message and "online-only" in message and "LOCALAPPDATA%\\Programs\\UrbanSolarCarver" in message


def test_the_setup_keeps_its_temporary_files_in_the_folder():
    text = WINDOWS_SETUP.read_text(encoding="utf-8")
    assert r'set "TEMP=%USC_RUNTIME%\tmp"' in text and r'set "TMP=%USC_RUNTIME%\tmp"' in text
    assert text.index('set "TEMP=') < text.index("Invoke-WebRequest")


def test_the_setup_checks_free_disk_space_before_downloading():
    text = WINDOWS_SETUP.read_text(encoding="utf-8")
    assert "AvailableFreeSpace" in text and "$env:USC_NEEDED_GB" in text
    assert 'set "USC_NEEDED_GB=7"' in text and 'set "USC_NEEDED_GB=1.5"' in text
    assert text.index("goto low_disk") < text.index("Invoke-WebRequest")
    assert "could not be checked" in text      # a UNC path: a note, then setup continues


def test_the_setup_suggests_the_per_user_programs_folder_and_never_the_root_of_c():
    for path in (WINDOWS_SETUP, REPOSITORY / "install" / "setup_env.py", REPOSITORY / "README.md",
                 REPOSITORY / "docs" / "getting-started" / "installation.md"):
        text = path.read_text(encoding="utf-8")
        assert "C:\\UrbanSolarCarver" not in text, path
    setup = WINDOWS_SETUP.read_text(encoding="utf-8")
    for label in (":path_too_long", ":not_writable", ":onedrive"):
        block = setup[setup.index(label):setup.index("goto fail", setup.index(label))]
        assert "%LOCALAPPDATA%\\Programs\\UrbanSolarCarver" in block, label


def test_the_setup_offers_a_desktop_shortcut_that_defaults_to_no():
    text = WINDOWS_SETUP.read_text(encoding="utf-8")
    assert re.search(r'choice /c YN /n /t 30 /d N /m "Make a shortcut on the desktop\? \[Y/N\] ?"', text)
    assert 'if not "%errorlevel%"=="1" goto no_shortcut' in text
    assert "[Environment]::GetFolderPath('Desktop')" in text and "WScript.Shell" in text
    assert "UrbanSolarCarver.lnk" in text and "start-urbansolarcarver.bat" in text
    # Nothing else is written outside the folder: the profile folders appear only in messages.
    for line in text.splitlines():
        if not line.lstrip().lower().startswith(("echo", "rem")):
            for outside in ("%USERPROFILE%", "%APPDATA%", "%LOCALAPPDATA%", "%TEMP%", "%TMP%", "GetFolderPath"):
                assert outside not in line or "GetFolderPath('Desktop')" in line, line


def test_the_setup_trusts_the_windows_certificates_and_clears_the_users_pip_and_uv_settings():
    text = WINDOWS_SETUP.read_text(encoding="utf-8")
    assert 'set "UV_NATIVE_TLS=1"' in text
    assert """for /f "delims==" %%V in ('set UV_ 2^>nul') do set "%%V=\"""" in text
    assert """for /f "delims==" %%V in ('set PIP_ 2^>nul') do set "%%V=\"""" in text
    assert text.index("in ('set UV_") < text.index('set "UV_NATIVE_TLS=1"')


def test_the_setup_says_the_right_python_download_size():
    assert "Python %USC_PYTHON_VERSION%, about 22 MB" in WINDOWS_SETUP.read_text(encoding="utf-8")


@pytest.mark.skipif(not RUNNING_ON_WINDOWS, reason="runs cmd.exe")
def test_the_windows_launcher_asks_for_setup_again_when_the_environment_does_not_start(tmp_path):
    """After the folder is moved, .venv's python.exe exists but names a Python that is gone."""
    folder = tmp_path / "R&D (1)"
    scripts = folder / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_bytes(b"not a program")
    shutil.copy(WINDOWS_LAUNCHER, folder)
    result = run_as_explorer_does(folder / WINDOWS_LAUNCHER.name)
    assert result.returncode == 1
    assert "run setup-urbansolarcarver.bat again" in result.stdout, result.stdout + result.stderr


@pytest.mark.slow   # one PowerShell start
@pytest.mark.skipif(not RUNNING_ON_WINDOWS, reason="runs cmd.exe")
@pytest.mark.parametrize("variable", ["OneDrive", "OneDriveCommercial"])
def test_the_setup_in_a_onedrive_folder_stops_before_downloading(tmp_path, variable):
    synced = tmp_path / "OneDrive - R&D"
    script = unzipped_copy(synced / "Downloads" / "UrbanSolarCarver-main (1)")
    result = run_as_explorer_does(script, **{variable: str(synced).upper()})   # compared without case
    assert result.returncode == 1
    assert "This folder is in OneDrive" in result.stdout, result.stdout + result.stderr
    assert not (script.parent / ".runtime").exists()
