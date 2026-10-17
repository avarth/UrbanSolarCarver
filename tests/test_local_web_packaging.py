"""What the package carries for the local web app: the example projects, which must stay copies of examples/."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_FOLDER = REPOSITORY_ROOT / "src" / "urbansolarcarver"
EXAMPLE_PROJECTS_FOLDER = PACKAGE_FOLDER / "example_projects"
WEATHER_FILE_NAME = "USA_CO_Golden-NREL.724666_TMY3.epw"
MAXIMUM_EXAMPLE_PROJECTS_BYTES = 2_000_000


def source_of(packaged_file: Path) -> Path:
    """The file under examples/ that a file under example_projects/ must be a copy of."""
    relative_path = packaged_file.relative_to(EXAMPLE_PROJECTS_FOLDER)
    if relative_path.parts[0] == "weather":
        return REPOSITORY_ROOT / "examples" / relative_path
    return REPOSITORY_ROOT / "examples" / "test_inputs" / relative_path


def packaged_files():
    return [path for path in EXAMPLE_PROJECTS_FOLDER.rglob("*") if path.is_file() and path.name != "examples.json"]


def test_packaged_examples_match_the_examples_folder():
    assert packaged_files()
    for packaged in packaged_files():
        source = source_of(packaged)
        assert packaged.read_bytes() == source.read_bytes(), f"{packaged} differs from {source}: copy it again"


def test_packaged_examples_are_under_two_megabytes():
    total_bytes = sum(path.stat().st_size for path in EXAMPLE_PROJECTS_FOLDER.rglob("*") if path.is_file())
    assert total_bytes < MAXIMUM_EXAMPLE_PROJECTS_BYTES


def test_examples_json_lists_exactly_the_packaged_files():
    entries = json.loads((EXAMPLE_PROJECTS_FOLDER / "examples.json").read_text(encoding="utf-8"))
    assert [entry["name"] for entry in entries] == ["basic_perimeter_block", "new_building", "multiple_buildings"]
    listed_files = set()
    for entry in entries:
        assert entry["title"] and entry["description"].endswith(".") and entry["mode"]
        listed_files.update(EXAMPLE_PROJECTS_FOLDER / entry["name"] / file_name for file_name in (*entry["max_volume"], *entry["test_surfaces"]))
        if entry["weather"]:
            listed_files.add(EXAMPLE_PROJECTS_FOLDER / "weather" / WEATHER_FILE_NAME)
    assert listed_files == set(packaged_files())


def test_the_package_data_setting_includes_the_example_projects():
    pyproject_text = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    package_data_section = pyproject_text.split("[tool.setuptools.package-data]")[1].split("\n[")[0]
    assert '"example_projects/**/*"' in package_data_section


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_no_packaged_example_file_is_ignored_by_git():
    """A rule such as the one for *.epw files would leave a file out of a commit, and so out of a clone and a wheel."""
    files = [str(path.relative_to(REPOSITORY_ROOT)) for path in EXAMPLE_PROJECTS_FOLDER.rglob("*") if path.is_file()]
    result = subprocess.run(["git", "check-ignore", *files], cwd=REPOSITORY_ROOT, capture_output=True, text=True)
    assert result.returncode == 1 and result.stdout == "", f"git ignores: {result.stdout}"    # 1 means no file matched
