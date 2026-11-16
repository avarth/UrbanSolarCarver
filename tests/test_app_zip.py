"""The app downloads of a release (tools/build_app_zip.py): what the setup needs on each system, and none of the developer files.

They are built from the tree in git's index (what the next commit holds), so a new or changed file counts once it is staged.
"""
import importlib.util
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_app_zip", REPOSITORY / "tools" / "build_app_zip.py")
build_app_zip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_app_zip)

COMMON_NEEDED = ("pyproject.toml", "README.md", "LICENSE",
                 "install/setup_env.py", "install/requirements-lock-hashed.txt", "install/requirements-lock.txt",
                 "src/urbansolarcarver/__init__.py", "src/urbansolarcarver/ui_static/index.html",
                 "src/urbansolarcarver/example_projects/examples.json")


def _index_tree(tmp_path: Path) -> str:
    """The tree of git's index, written from a copy of it: write-tree on the index itself takes its lock, which parallel
    tests would contend for."""
    index = subprocess.run(["git", "rev-parse", "--git-path", "index"], cwd=REPOSITORY, capture_output=True, text=True,
                           check=True).stdout.strip()
    copy = tmp_path / "index"
    shutil.copy(REPOSITORY / index, copy)
    return subprocess.run(["git", "write-tree"], cwd=REPOSITORY, capture_output=True, text=True, check=True,
                          env={**os.environ, "GIT_INDEX_FILE": str(copy)}).stdout.strip()


def _names(tmp_path: Path) -> tuple[set[str], zipfile.ZipFile]:
    archive = zipfile.ZipFile(build_app_zip.build_app_zip(_index_tree(tmp_path), tmp_path / build_app_zip.ZIP_NAME))
    return set(archive.namelist()), archive


def _linux(tmp_path: Path) -> tarfile.TarFile:
    return tarfile.open(build_app_zip.build_linux_archive(_index_tree(tmp_path), tmp_path / build_app_zip.LINUX_ARCHIVE_NAME))


def _top_level(names) -> set[str]:
    return {name.split("/")[1] for name in names if name.count("/") >= 1 and name.split("/")[1]}


def test_the_app_zip_holds_what_the_setup_and_the_app_need_in_one_folder(tmp_path):
    names, _ = _names(tmp_path)
    assert all(name.startswith("UrbanSolarCarver/") for name in names)
    for needed in ("setup-urbansolarcarver.bat", "start-urbansolarcarver.bat", *COMMON_NEEDED):
        assert f"UrbanSolarCarver/{needed}" in names, needed


def test_the_app_zip_leaves_out_the_developer_files(tmp_path):
    names, _ = _names(tmp_path)
    assert _top_level(names) == set(build_app_zip.APP_PATHS)
    assert not any("/__pycache__/" in name for name in names)


def test_the_setup_scripts_keep_their_windows_line_endings(tmp_path):
    _, archive = _names(tmp_path)
    for script in ("setup-urbansolarcarver.bat", "start-urbansolarcarver.bat"):
        text = archive.read(f"UrbanSolarCarver/{script}")
        assert b"\r\n" in text and text.count(b"\n") == text.count(b"\r\n"), script


def test_the_linux_archive_holds_what_the_linux_setup_needs_and_no_windows_scripts(tmp_path):
    names = set(_linux(tmp_path).getnames())
    assert all(name.startswith("UrbanSolarCarver") for name in names)
    for needed in ("setup-urbansolarcarver.sh", "start-urbansolarcarver.sh", "install/requirements-linux-cuda-hashed.txt",
                   *COMMON_NEEDED):
        assert f"UrbanSolarCarver/{needed}" in names, needed
    assert _top_level(names) == set(build_app_zip.LINUX_PATHS)
    assert not any(name.endswith(".bat") for name in names)


def test_the_linux_scripts_are_executable_and_keep_unix_line_endings_in_the_archive(tmp_path):
    archive = _linux(tmp_path)
    for script in ("setup-urbansolarcarver.sh", "start-urbansolarcarver.sh"):
        member = archive.getmember(f"UrbanSolarCarver/{script}")
        assert member.mode & 0o111 == 0o111, (script, oct(member.mode))
        assert b"\r" not in archive.extractfile(member).read(), script


def test_the_release_tag_follows_the_pyproject_version():
    assert build_app_zip.release_tag().startswith("v0.") and build_app_zip.release_tag()[1:].count(".") == 2
