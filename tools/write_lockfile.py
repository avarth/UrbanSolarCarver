"""Write requirements-lock.txt: the exact versions of this environment that the project needs.

    .venv/Scripts/python.exe tools/write_lockfile.py

Run it after upgrading a package here and passing the tests. It starts from pyproject.toml (the dependencies and the dev and ui
extras) and follows what each installed package requires, so packages this environment holds for other reasons stay out. Those
requirements are read for this platform: the file is a pip constraints file (``-c``), so a package another platform needs and
this one does not is simply not pinned. ``setup_env.py`` installs from it unless given ``--latest``.
"""
import platform
import re
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

try:
    import tomllib
except ModuleNotFoundError:     # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
LOCKFILE = ROOT / "requirements-lock.txt"
EXTRAS = ("dev", "ui")


def project_requirements() -> list[str]:
    with open(ROOT / "pyproject.toml", "rb") as file:
        project = tomllib.load(file)["project"]
    return project["dependencies"] + [text for extra in EXTRAS for text in project["optional-dependencies"][extra]]


def is_active(requirement: Requirement, extras: tuple[str, ...]) -> bool:
    return requirement.marker is None or any(requirement.marker.evaluate({"extra": extra}) for extra in (*extras, ""))


def installed_versions(requirements: list[str]) -> dict[str, str]:
    """Each required package and what it requires, by name, with its installed version without a +local part."""
    versions: dict[str, str] = {}
    visited = set()

    def visit(text: str, wanted_by: str) -> None:
        requirement = Requirement(text)
        key = (canonicalize_name(requirement.name), tuple(sorted(requirement.extras)))
        if key in visited:
            return
        visited.add(key)
        try:
            package = distribution(requirement.name)
        except PackageNotFoundError:
            sys.exit(f"{requirement.name}, required by {wanted_by}, is not installed here: install it and run the tests first")
        versions[key[0]] = package.version.split("+")[0]
        for inner in package.requires or []:
            if is_active(Requirement(inner), key[1]):
                visit(inner, requirement.name)

    for text in requirements:
        visit(text, "pyproject.toml")
    return versions


def torch_wheels() -> str:
    """The wheel index of the installed torch, such as cu121 or cpu, from its +local part."""
    local = distribution("torch").version.partition("+")[2]
    return local if re.fullmatch(r"cu\d+", local) else "cpu"


def lockfile_text(versions: dict[str, str], wheels: str) -> str:
    python = ".".join(platform.python_version_tuple())
    header = [
        "# The versions the tests last passed on. Written by tools/write_lockfile.py; do not edit by hand.",
        f"# Python {python} on {platform.system()}. A pip constraints file: setup_env.py installs from it.",
        f"# torch-wheels: {wheels}",
    ]
    return "\n".join(header + [f"{name}=={versions[name]}" for name in sorted(versions)]) + "\n"


def main() -> None:
    versions = installed_versions(project_requirements())
    LOCKFILE.write_text(lockfile_text(versions, torch_wheels()), encoding="utf-8", newline="\n")
    print(f"{LOCKFILE.name}: {len(versions)} packages")


if __name__ == "__main__":
    main()
