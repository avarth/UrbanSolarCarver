"""Build the app zip of a release: build/UrbanSolarCarver-windows.zip, what a user of the app downloads.

    .venv/Scripts/python.exe tools/build_app_zip.py            # from the tag of the version in pyproject.toml (v0.12.0)
    .venv/Scripts/python.exe tools/build_app_zip.py --ref v0.12.0
    gh release upload v0.12.0 build/UrbanSolarCarver-windows.zip

It holds only what the Windows setup and the app need (APP_PATHS), in one folder, UrbanSolarCarver/: the package with the built
app and the example projects (src/), pyproject.toml, install/, the setup and start scripts, and the README, licence, citation and
changelog. The developer files (the app's sources, tests, docs, notebooks, Grasshopper) stay in the release's source zip, which
Zenodo archives. The zip is made by ``git archive`` from the tag, so it holds the committed files of that release, with the line
endings .gitattributes gives them (CRLF for the .bat files). The installation guide links to
releases/latest/download/UrbanSolarCarver-windows.zip, so every release needs this file under that name.
"""
import argparse
import subprocess
import tomllib
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
ZIP_NAME = "UrbanSolarCarver-windows.zip"
FOLDER_IN_ZIP = "UrbanSolarCarver"
APP_PATHS = (
    "src",
    "install",
    "pyproject.toml",
    "setup-urbansolarcarver.bat",
    "start-urbansolarcarver.bat",
    "README.md",
    "LICENSE",
    "CITATION.cff",
    "CHANGELOG.md",
)


def release_tag() -> str:
    """The tag of the version in pyproject.toml: "v0.12.0"."""
    with open(REPOSITORY / "pyproject.toml", "rb") as file:
        return "v" + tomllib.load(file)["project"]["version"]


def build_app_zip(ref: str, output: Path) -> Path:
    """Writes the app zip of *ref* (a tag, a branch or a commit) to *output*; CalledProcessError when git cannot archive it."""
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "archive", "--format=zip", f"--prefix={FOLDER_IN_ZIP}/", f"--output={output}", ref, *APP_PATHS],
                   cwd=REPOSITORY, check=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", help="the tag, branch or commit to build from (default: the tag of the pyproject.toml version)")
    parser.add_argument("--output", type=Path, default=REPOSITORY / "build" / ZIP_NAME)
    arguments = parser.parse_args()
    written = build_app_zip(arguments.ref or release_tag(), arguments.output)
    print(f"{written} ({written.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
