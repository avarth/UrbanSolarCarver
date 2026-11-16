"""The app zip of a release (tools/build_app_zip.py): what the Windows setup needs, and none of the developer files."""
import importlib.util
import zipfile
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_app_zip", REPOSITORY / "tools" / "build_app_zip.py")
build_app_zip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_app_zip)


def _names(tmp_path: Path) -> tuple[set[str], zipfile.ZipFile]:
    archive = zipfile.ZipFile(build_app_zip.build_app_zip("HEAD", tmp_path / build_app_zip.ZIP_NAME))
    return set(archive.namelist()), archive


def test_the_app_zip_holds_what_the_setup_and_the_app_need_in_one_folder(tmp_path):
    names, _ = _names(tmp_path)
    assert all(name.startswith("UrbanSolarCarver/") for name in names)
    for needed in ("setup-urbansolarcarver.bat", "start-urbansolarcarver.bat", "pyproject.toml", "README.md", "LICENSE",
                   "install/setup_env.py", "install/requirements-lock-hashed.txt", "install/requirements-lock.txt",
                   "src/urbansolarcarver/__init__.py", "src/urbansolarcarver/ui_static/index.html",
                   "src/urbansolarcarver/example_projects/examples.json"):
        assert f"UrbanSolarCarver/{needed}" in names, needed


def test_the_app_zip_leaves_out_the_developer_files(tmp_path):
    names, _ = _names(tmp_path)
    top_level = {name.split("/")[1] for name in names if name.count("/") >= 1 and name.split("/")[1]}
    assert top_level == set(build_app_zip.APP_PATHS)
    assert not any("/__pycache__/" in name for name in names)


def test_the_setup_scripts_keep_their_windows_line_endings(tmp_path):
    _, archive = _names(tmp_path)
    for script in ("setup-urbansolarcarver.bat", "start-urbansolarcarver.bat"):
        text = archive.read(f"UrbanSolarCarver/{script}")
        assert b"\r\n" in text and text.count(b"\n") == text.count(b"\r\n"), script


def test_the_release_tag_follows_the_pyproject_version():
    assert build_app_zip.release_tag().startswith("v0.") and build_app_zip.release_tag()[1:].count(".") == 2
