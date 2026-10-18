"""setup_env.py: choosing the PyTorch wheel index for the NVIDIA driver."""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "setup_env", Path(__file__).resolve().parents[1] / "setup_env.py")
setup_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup_env)

# What the indexes offered on 2026-10-16 (newest Windows torch per index).
OFFERS = {"cu118": (2, 7, 1), "cu121": (2, 5, 1), "cu124": (2, 6, 0), "cu126": (2, 14, 1),
          "cu128": (2, 11, 0), "cu129": (2, 9, 0), "cu130": (2, 14, 1), "cu132": (2, 14, 1)}


def offered(index_url):
    return OFFERS.get(index_url.rstrip("/").rsplit("/", 1)[-1])


def unreachable(index_url):
    return None


@pytest.mark.parametrize("driver, expected_index", [
    ("12.8", "cu126"),   # cu128 stopped at torch 2.11; cu126 has 2.14.1
    ("12.9", "cu126"),   # cu129 stopped at torch 2.9
    ("12.6", "cu126"),
    ("12.4", "cu118"),   # cu118 (torch 2.7.1) is newer than cu124 (2.6.0)
    ("13.2", "cu132"),   # cu130 and cu132 both offer 2.14.1: the higher CUDA wins
    ("13.1", "cu130"),
])
def test_the_index_with_the_newest_torch_the_driver_can_run_is_chosen(driver, expected_index):
    url, description = setup_env.resolve_torch_index(driver, force_cpu=False, newest_torch_on=offered)
    assert url.endswith("/" + expected_index)
    assert "2." in description  # the description names the torch version found


def test_without_answers_the_highest_supported_index_is_used(capsys):
    url, description = setup_env.resolve_torch_index("12.8", force_cpu=False, newest_torch_on=unreachable)
    assert url.endswith("/cu128")
    assert "could not" in description


def test_a_driver_older_than_every_index_gets_cpu_wheels():
    url, description = setup_env.resolve_torch_index("11.4", force_cpu=False, newest_torch_on=offered)
    assert url.endswith("/cpu")


@pytest.mark.parametrize("driver, force_cpu", [(None, False), ("12.8", True)])
def test_no_driver_or_forced_cpu_gets_cpu_wheels(driver, force_cpu):
    url, _ = setup_env.resolve_torch_index(driver, force_cpu=force_cpu, newest_torch_on=offered)
    assert url.endswith("/cpu")


def test_pip_version_text_with_a_local_label_is_read():
    assert setup_env._version_tuple("2.14.1+cu126") == (2, 14, 1)


# The browser app launcher that setup_env.py writes after installing.

def test_the_windows_launcher_starts_the_browser_app_with_the_installed_python(tmp_path):
    repository = tmp_path / "my projects" / "urbanSolarCarver"
    repository.mkdir(parents=True)
    python = tmp_path / "venvs" / "usc venv" / "Scripts" / "python.exe"
    launcher = setup_env.write_browser_app_launcher(repository, python, system="Windows")
    assert launcher == repository / "Start UrbanSolarCarver.cmd"
    text = launcher.read_bytes().decode("utf-8")
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")
    assert f'set "USC_PYTHON={python}"' in text
    assert f'set "PYTHONPATH={repository / "src"}"' in text
    assert '"%USC_PYTHON%" -m urbansolarcarver.carver_cli ui %*' in text
    assert 'if exist "%USC_PYTHON%" goto start' in text   # a moved or deleted venv is explained, not a cryptic error
    assert "pause" in text                                # the window stays open to show why it stopped
    assert " (" not in text.split(":start")[0].replace('"', "")  # no if (...) block a ")" in a path could end


def test_the_windows_launcher_runs_from_a_path_with_parentheses(tmp_path):
    if setup_env.platform.system() != "Windows":
        pytest.skip("runs cmd.exe")
    import subprocess
    repository = tmp_path / "Program Files (x86)" / "urbanSolarCarver"
    repository.mkdir(parents=True)
    launcher = setup_env.write_browser_app_launcher(repository, repository / "missing (venv)" / "python.exe")
    result = subprocess.run(["cmd", "/c", str(launcher)], input="\n", capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert "was not found" in result.stdout and "missing (venv)" in result.stdout


def test_the_macos_and_linux_launcher_starts_the_browser_app_with_the_installed_python(tmp_path):
    repository = tmp_path / "my projects" / "urbanSolarCarver"
    repository.mkdir(parents=True)
    python = tmp_path / "usc venv" / "bin" / "python"
    launcher = setup_env.write_browser_app_launcher(repository, python, system="Darwin")
    assert launcher == repository / "Start UrbanSolarCarver.command"
    text = launcher.read_bytes().decode("utf-8")
    assert text.startswith("#!/bin/sh\n") and "\r" not in text
    assert f"usc_python='{python}'" in text
    assert f"PYTHONPATH='{repository / 'src'}'" in text
    assert 'exec "$usc_python" -m urbansolarcarver.carver_cli ui "$@"' in text
    if setup_env.platform.system() != "Windows":
        assert launcher.stat().st_mode & 0o111   # double-clickable on macOS, runnable on Linux


def test_writing_the_launcher_again_replaces_the_old_one(tmp_path):
    first = setup_env.write_browser_app_launcher(tmp_path, tmp_path / "old" / "python.exe", system="Windows")
    second = setup_env.write_browser_app_launcher(tmp_path, tmp_path / "new" / "python.exe", system="Windows")
    assert first == second
    text = second.read_text(encoding="utf-8")
    assert "new" in text and str(tmp_path / "old") not in text
