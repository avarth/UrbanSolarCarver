"""Build the app downloads of a release: build/UrbanSolarCarver-windows.zip and build/UrbanSolarCarver-linux.tar.gz.

    .venv/Scripts/python.exe tools/build_app_zip.py            # from the tag of the version in pyproject.toml (v0.12.0)
    .venv/Scripts/python.exe tools/build_app_zip.py --ref v0.12.0
    gh release upload v0.12.0 build/UrbanSolarCarver-windows.zip build/UrbanSolarCarver-linux.tar.gz

Each holds only what the setup and the app need on its system, in one folder, UrbanSolarCarver/: the package with the built app
and the example projects (src/), pyproject.toml, install/, the setup and start scripts of that system, and the README, licence,
citation and changelog. The developer files (the app's sources, tests, docs, notebooks, Grasshopper) stay in the release's source
zip, which Zenodo archives. Both are made by ``git archive`` from the tag, so they hold the committed files of that release, with
the line endings .gitattributes gives them (CRLF for the .bat files, LF for the .sh files). The Linux one is a tar.gz because a tar
keeps the scripts executable, which a zip extracted on Linux often does not. The installation guide links to
releases/latest/download/<name>, so every release needs both files under these names.
"""
import argparse
import subprocess
import tomllib
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
ZIP_NAME = "UrbanSolarCarver-windows.zip"
LINUX_ARCHIVE_NAME = "UrbanSolarCarver-linux.tar.gz"
FOLDER_IN_ZIP = "UrbanSolarCarver"
COMMON_PATHS = ("src", "install", "pyproject.toml", "README.md", "LICENSE", "CITATION.cff", "CHANGELOG.md")
APP_PATHS = (*COMMON_PATHS, "setup-urbansolarcarver.bat", "start-urbansolarcarver.bat")   # the Windows zip
LINUX_PATHS = (*COMMON_PATHS, "setup-urbansolarcarver.sh", "start-urbansolarcarver.sh")


def release_tag() -> str:
    """The tag of the version in pyproject.toml: "v0.12.0"."""
    with open(REPOSITORY / "pyproject.toml", "rb") as file:
        return "v" + tomllib.load(file)["project"]["version"]


def _archive(ref: str, output: Path, archive_format: str, paths: tuple[str, ...]) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "archive", f"--format={archive_format}", f"--prefix={FOLDER_IN_ZIP}/", f"--output={output}", ref, *paths],
                   cwd=REPOSITORY, check=True)
    return output


def build_app_zip(ref: str, output: Path) -> Path:
    """Writes the Windows zip of *ref* (a tag, a branch or a commit) to *output*; CalledProcessError when git cannot archive it."""
    return _archive(ref, output, "zip", APP_PATHS)


def build_linux_archive(ref: str, output: Path) -> Path:
    """Writes the Linux tar.gz of *ref* to *output*; CalledProcessError when git cannot archive it."""
    return _archive(ref, output, "tar.gz", LINUX_PATHS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", help="the tag, branch or commit to build from (default: the tag of the pyproject.toml version)")
    parser.add_argument("--output-folder", type=Path, default=REPOSITORY / "build")
    arguments = parser.parse_args()
    ref = arguments.ref or release_tag()
    for written in (build_app_zip(ref, arguments.output_folder / ZIP_NAME),
                    build_linux_archive(ref, arguments.output_folder / LINUX_ARCHIVE_NAME)):
        print(f"{written} ({written.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
