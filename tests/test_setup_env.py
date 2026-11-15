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


HASHED_LOCKFILE = setup_env.LOCKFILE.with_name("requirements-lock-hashed.txt")


def test_the_hashed_lockfile_text_gives_every_pin_its_hashes_and_torch_both_builds():
    def hashes_of(name, version):
        return {"numpy": ["a" * 64, "b" * 64]}[name]

    def torch_hashes_of(version, build):
        assert version == "2.14.1"
        return {"cu126": ["c" * 64], "cpu": ["d" * 64]}[build]

    text = write_lockfile.hashed_lockfile_text({"numpy": "2.5.0", "torch": "2.14.1"}, "cu126", hashes_of, torch_hashes_of)
    header = [line for line in text.splitlines() if line.startswith("#")]
    assert "# torch-hashes: cu126 cpu" in header
    numpy_block = text.split("numpy==2.5.0", 1)[1].split("torch==", 1)[0]
    assert f"--hash=sha256:{'a' * 64}" in numpy_block and f"--hash=sha256:{'b' * 64}" in numpy_block
    torch_block = text.split("torch==2.14.1", 1)[1]
    assert f"--hash=sha256:{'c' * 64}" in torch_block and f"--hash=sha256:{'d' * 64}" in torch_block


def test_the_committed_hashed_lockfile_matches_the_lockfile():
    """Fails when requirements-lock.txt changed and tools/write_lockfile.py --hashes was not run after it."""
    import re
    lock = setup_env.LOCKFILE.read_text(encoding="utf-8")
    hashed = HASHED_LOCKFILE.read_text(encoding="utf-8")
    wheels = re.search(r"^# torch-wheels: (\S+)$", lock, re.MULTILINE).group(1)
    assert f"# torch-hashes: {wheels} cpu" in hashed
    blocks = dict(re.findall(r"^(\S+==\S+) \\\n((?:    --hash=sha256:\S+(?: \\)?\n)+)", hashed, re.MULTILINE))
    pins = [line for line in lock.splitlines() if line and not line.startswith("#")]
    assert sorted(blocks) == sorted(pins)
    for pin in pins:
        assert re.search(r"--hash=sha256:[0-9a-f]{64}", blocks[pin]), pin


def test_a_self_contained_install_keeps_its_venv_and_caches_in_the_folder(tmp_path):
    vpy = tmp_path / ".venv" / "Scripts" / "python.exe"
    environment, commands = setup_env.self_contained_plan(tmp_path, vpy, "torch==2.14.1", setup_env.CPU_WHEEL_INDEX)
    cache = tmp_path / ".runtime" / "cache"
    assert Path(environment["PIP_CACHE_DIR"]) == cache / "pip"
    assert Path(environment["WARP_CACHE_PATH"]) == cache / "warp"
    assert len(commands) == 2
    torch_command, rest_command = commands
    for command in commands:
        assert command[:4] == [str(vpy), "-m", "pip", "install"]
        assert "--require-hashes" in command
        assert "-e" not in command and "--editable" not in command
        assert "--upgrade" not in command and "pip" not in command[4:]   # no pip self-upgrade, which would be unchecked
    assert "--no-deps" in torch_command
    assert torch_command[torch_command.index("--index-url") + 1] == setup_env.CPU_WHEEL_INDEX
    assert rest_command[rest_command.index("-r") + 1] == str(tmp_path / "requirements-lock-hashed.txt")


def test_the_torch_requirement_of_a_self_contained_install_carries_both_builds_hashes():
    text = setup_env.torch_hashed_requirement(HASHED_LOCKFILE.read_text(encoding="utf-8"))
    assert text.startswith("torch==")
    assert text.count("--hash=sha256:") >= 2 and "numpy" not in text


def test_a_self_contained_install_on_a_too_long_path_stops_and_says_to_move_the_folder(monkeypatch):
    monkeypatch.setattr(setup_env.platform, "system", lambda: "Windows")
    monkeypatch.setattr(setup_env, "_windows_long_paths_enabled", lambda: False)
    root = Path("C:/") / ("d" * 117)
    assert len(str(root)) >= 120
    with pytest.raises(SystemExit) as stopped:
        setup_env.self_contained_venv(root)
    message = str(stopped.value)
    assert "shorter path" in message and ".usc-venv" not in message


def test_a_self_contained_install_on_a_short_path_keeps_its_venv_in_the_folder(monkeypatch):
    monkeypatch.setattr(setup_env.platform, "system", lambda: "Windows")
    monkeypatch.setattr(setup_env, "_windows_long_paths_enabled", lambda: False)
    assert setup_env.self_contained_venv(Path("C:/UrbanSolarCarver")) == Path("C:/UrbanSolarCarver") / ".venv"


@pytest.mark.parametrize("driver, build", [("13.0", "cu126"), (None, "cpu")])
def test_a_self_contained_install_takes_the_locked_torch_rule(driver, build):
    requirement, url, _ = setup_env.locked_torch(setup_env.LOCKFILE.read_text(encoding="utf-8"), driver, force_cpu=False)
    assert url.endswith("/" + build)
    assert "# torch-hashes: cu126 cpu" in HASHED_LOCKFILE.read_text(encoding="utf-8")
