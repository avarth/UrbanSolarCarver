"""setup_env.py: choosing the PyTorch wheel index for the NVIDIA driver, and the locked install."""
import importlib.util
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

_spec = importlib.util.spec_from_file_location(
    "setup_env", Path(__file__).resolve().parents[1] / "setup_env.py")
setup_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup_env)

_spec = importlib.util.spec_from_file_location(
    "write_lockfile", Path(__file__).resolve().parents[1] / "tools" / "write_lockfile.py")
write_lockfile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(write_lockfile)

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


LOCK = "# torch-wheels: cu121\nnumpy==1.26.4\ntorch==2.5.1\n"


@pytest.mark.parametrize("driver", ["12.1", "12.8", "13.2"])
def test_a_locked_install_takes_the_locked_torch_whatever_newer_wheels_the_driver_could_run(driver):
    requirement, url, _ = setup_env.locked_torch(LOCK, driver, force_cpu=False)
    assert requirement == "torch==2.5.1"
    assert url.endswith("/cu121")


@pytest.mark.parametrize("driver, force_cpu", [(None, False), ("13.2", True), ("11.8", False), ("not a version", False)])
def test_a_locked_install_falls_back_to_cpu_wheels_of_the_same_torch(driver, force_cpu):
    requirement, url, description = setup_env.locked_torch(LOCK, driver, force_cpu=force_cpu)
    assert requirement == "torch==2.5.1"
    assert url == setup_env.CPU_WHEEL_INDEX
    assert description.startswith("CPU-only")


def test_the_default_install_takes_the_lockfile_and_latest_asks_the_indexes(monkeypatch):
    monkeypatch.setattr(setup_env, "newest_torch_on_index", offered)
    requirement, options, constraints, url, _ = setup_env.install_choice(False, "13.2", force_cpu=False)
    assert requirement.startswith("torch==") and options == ["--no-deps"]
    assert constraints == ["-c", str(setup_env.LOCKFILE)]
    locked_wheels = next(line for line in setup_env.LOCKFILE.read_text(encoding="utf-8").splitlines() if line.startswith("# torch-wheels: "))
    assert url.endswith("/" + locked_wheels.rsplit(" ", 1)[1])
    # newest_torch_on is bound as a default argument, so --latest reaches the indexes through it
    monkeypatch.setattr(setup_env.resolve_torch_index, "__defaults__", (offered,))
    requirement, options, constraints, url, _ = setup_env.install_choice(True, "13.2", force_cpu=False)
    assert (requirement, options, constraints) == ("torch", [], [])
    assert url.endswith("/cu132")


@pytest.mark.parametrize("version, stopped", [((3, 12), False), ((3, 14), False), ((3, 15), True)])
def test_a_locked_install_stops_on_a_python_the_locked_versions_do_not_support(version, stopped):
    problem = setup_env.locked_python_problem(version)
    assert bool(problem) is stopped
    if stopped:
        assert "--latest" in problem


def test_a_lockfile_without_torch_stops_the_install():
    with pytest.raises(SystemExit):
        setup_env.locked_torch("numpy==1.26.4\n", "12.8", force_cpu=False)


def test_the_lockfile_pins_every_dependency_within_what_pyproject_allows():
    """Fails when pyproject.toml gains or tightens a dependency and tools/write_lockfile.py was not run after it."""
    text = setup_env.LOCKFILE.read_text(encoding="utf-8")
    assert "# torch-wheels: " in text
    pins = dict(line.split("==") for line in text.splitlines() if not line.startswith("#"))
    for wanted in write_lockfile.project_requirements():
        requirement = Requirement(wanted)
        name = canonicalize_name(requirement.name)
        assert name in pins, f"{name} is not in requirements-lock.txt: run tools/write_lockfile.py"
        assert requirement.specifier.contains(pins[name], prereleases=True), (
            f"{name}=={pins[name]} is outside {requirement.specifier}: upgrade it, test, run tools/write_lockfile.py")


def test_the_docs_give_the_python_versions_the_installer_accepts():
    """Fails when MIN_PYTHON or MAX_LOCKED_PYTHON changes and the install guide, the UI guide or pyproject.toml still say the old
    versions (they once said 3.10 while the installer asked for 3.12)."""
    root = Path(__file__).resolve().parents[1]
    low, high = (f"{major}.{minor}" for major, minor in (setup_env.MIN_PYTHON, setup_env.MAX_LOCKED_PYTHON))
    installation = (root / "docs" / "getting-started" / "installation.md").read_text(encoding="utf-8")
    assert f"Python {low} or newer" in installation
    assert f"Python {low} to {high}" in installation
    assert f"needs Python {low} or newer" in (root / "docs" / "ui.md").read_text(encoding="utf-8")
    assert f'requires-python = ">={low}"' in (root / "pyproject.toml").read_text(encoding="utf-8")
    for launcher in ("start-urbansolarcarver.bat", "start-urbansolarcarver.sh"):
        assert f"Python {low} or newer" in (root / launcher).read_text(encoding="utf-8")
