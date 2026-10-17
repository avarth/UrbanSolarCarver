"""What the package carries for the local web app: the example projects, which must stay copies of examples/, the built front-end, which must match app/, and the settings form's presentation file, which must match the engine's config."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from urbansolarcarver.mode_registry import MODES
from urbansolarcarver.pydantic_schemas import UserConfig
from urbansolarcarver.stage_settings import (
    ExportingSettings, MassingSettings, PreprocessingSettings, RunOptions, ThresholdingSettings,
)

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_FOLDER = REPOSITORY_ROOT / "src" / "urbansolarcarver"
EXAMPLE_PROJECTS_FOLDER = PACKAGE_FOLDER / "example_projects"
WEATHER_FILE_NAME = "USA_CO_Golden-NREL.724666_TMY3.epw"
MAXIMUM_EXAMPLE_PROJECTS_BYTES = 2_000_000
APP_FOLDER = REPOSITORY_ROOT / "app"
BUILD_INFO_PATH = PACKAGE_FOLDER / "ui_static" / "build_info.json"


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


def app_source_sha256(app_folder: Path) -> str:
    """The hash that app/scripts/write_build_info.mjs records: package.json, package-lock.json, index.html, vite.config.ts,
    tsconfig.json and every file under src/.

    Files are taken in the order of their paths relative to app/ (written with "/"); each adds its relative path,
    a newline, and its bytes with every CRLF turned into LF, so a Windows checkout gives the same hash as a Linux one.
    """
    source_files = [*(app_folder / name for name in ("package.json", "package-lock.json", "index.html", "vite.config.ts", "tsconfig.json")),
                    *(path for path in (app_folder / "src").rglob("*") if path.is_file())]
    relative_paths = sorted(path.relative_to(app_folder).as_posix() for path in source_files)
    digest = hashlib.sha256()
    for relative_path in relative_paths:
        digest.update((relative_path + "\n").encode("utf-8"))
        digest.update((app_folder / relative_path).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def test_front_end_build_matches_its_sources():
    recorded = json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))["app_source_sha256"]
    assert recorded == app_source_sha256(APP_FOLDER), "app/ changed without a rebuild: run `cd app && npm run build` and commit ui_static/"


# ---- The settings form: setting_presentation.json against the engine's config and stages (UX 7) ----

SETTING_PRESENTATION_PATH = APP_FOLDER / "src" / "settings_form" / "setting_presentation.json"
STEP_STAGES = {"settings": {*PreprocessingSettings.model_fields, *RunOptions.model_fields},
               "carving": set(ThresholdingSettings.model_fields),
               "envelope_and_massing": {*ExportingSettings.model_fields, *MassingSettings.model_fields} - {"final_mesh_format"},
               "export": {"final_mesh_format"}}
# Set by the service, chosen in the Mode step, replaced by the in-app charts, or left for milestone 2: never in the form.
NOT_IN_THE_FORM = {"max_volume_path", "test_surface_path", "epw_path", "out_dir", "device", "mode", "diagnostic_plots",
                   "simulated_weights_path"}


def presented_settings() -> dict:
    return json.loads(SETTING_PRESENTATION_PATH.read_text(encoding="utf-8"))["settings"]


def test_every_shown_setting_is_presented_exactly_once():
    assert set(presented_settings()) == set(UserConfig.model_fields) - NOT_IN_THE_FORM


def test_each_step_holds_only_settings_of_its_stage():
    for name, entry in presented_settings().items():
        assert name in STEP_STAGES[entry["step"]], (name, entry["step"])


def test_mode_lists_name_engine_modes():
    for name, entry in presented_settings().items():
        for key in ("modes", "essential", "label_for_modes", "unit_for_modes", "help_for_modes"):
            if isinstance(entry.get(key), (list, dict)):
                assert set(entry[key]) <= set(MODES), (name, key)


# ---- The Mode step: mode_tiles.json against the engine's modes (UX 5.3) ----

MODE_TILES_PATH = APP_FOLDER / "src" / "steps" / "mode_tiles.json"


def test_mode_tiles_name_every_engine_mode_once():
    tiles = json.loads(MODE_TILES_PATH.read_text(encoding="utf-8"))
    assert sorted(t["engine_name"] for t in tiles) == sorted(MODES)
