"""Write install/requirements-lock.txt: the exact versions of this environment that the project needs.

    .venv/Scripts/python.exe tools/write_lockfile.py

Run it after upgrading a package here and passing the tests. It starts from pyproject.toml (the dependencies and the dev and ui
extras) and follows what each installed package requires, so packages this environment holds for other reasons stay out. Those
requirements are read for this platform: the file is a pip constraints file (``-c``), so a package another platform needs and
this one does not is simply not pinned. ``install/setup_env.py`` installs from it unless given ``--latest``.

    .venv/Scripts/python.exe tools/write_lockfile.py --hashes

also writes install/requirements-lock-hashed.txt: the same pins as a pip requirements file (``-r``) with the SHA-256 of every file of
each release on PyPI, and for torch those of its Windows and Linux x86_64 files on both wheel indexes the installer can choose (the
one in ``# torch-wheels:`` and cpu). ``setup_env.py --self-contained`` installs from it with ``--require-hashes``.

On Linux the CUDA build of torch needs packages the Windows one does not (the nvidia-*-cu12 libraries, cuda-toolkit and triton).
``--hashes`` also writes them, with their hashes, to install/requirements-linux-cuda-hashed.txt, which the Linux setup adds when it
installs the CUDA build. Their versions come from ``uv pip compile`` for Linux, constrained by requirements-lock.txt, so uv must be on
PATH for ``--hashes``.
"""
import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

import tomllib

ROOT = Path(__file__).resolve().parents[1]
LOCKFILE = ROOT / "install" / "requirements-lock.txt"
HASHED_LOCKFILE = ROOT / "install" / "requirements-lock-hashed.txt"
LINUX_CUDA_LOCKFILE = ROOT / "install" / "requirements-linux-cuda-hashed.txt"
TORCH_PLATFORMS = ("-win_amd64.", "-manylinux_2_28_x86_64.")   # the platforms the setup scripts install on
TORCH_WHEEL_PAGE = "https://download.pytorch.org/whl/{build}/torch/"
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


def pypi_hashes(name: str, version: str) -> list[str]:
    """The SHA-256 of every file PyPI holds for *name* *version*."""
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=60) as response:
        release = json.load(response)
    hashes = sorted({file["digests"]["sha256"] for file in release["urls"]})
    if not hashes:
        sys.exit(f"PyPI has no files for {name}=={version}")
    return hashes


def torch_hashes(version: str, build: str) -> list[str]:
    """The SHA-256 of every Windows and Linux x86_64 file of torch *version*+*build* on PyTorch's *build* wheel index."""
    with urllib.request.urlopen(TORCH_WHEEL_PAGE.format(build=build), timeout=60) as response:
        page = response.read().decode("utf-8").replace("%2B", "+")
    prefix = f"torch-{version}+{build}-"
    links = re.findall(r'/([^/"#]+\.whl)#sha256=([0-9a-f]{64})', page)
    found = {(filename, digest) for filename, digest in links if filename.startswith(prefix)}
    for platform_tag in TORCH_PLATFORMS:
        if not any(platform_tag in filename for filename, _ in found):
            sys.exit(f"{TORCH_WHEEL_PAGE.format(build=build)} has no {platform_tag.strip('-.')} file of torch {version}+{build}")
    return sorted({digest for filename, digest in found if any(tag in filename for tag in TORCH_PLATFORMS)})


def linux_cuda_versions(versions: dict[str, str], wheels: str) -> dict[str, str]:
    """The packages the Linux CUDA build of torch needs beyond *versions*, by name, with the version uv resolves for them."""
    uv = shutil.which("uv")
    if uv is None:
        sys.exit("--hashes needs uv on PATH to find the packages of torch's Linux CUDA build")
    with tempfile.TemporaryDirectory() as folder:
        constraints = Path(folder) / "constraints.txt"
        constraints.write_text("".join(f"{name}=={version}\n" for name, version in versions.items()), encoding="utf-8")
        output = Path(folder) / "linux.txt"
        subprocess.run([uv, "pip", "compile", str(ROOT / "pyproject.toml"), *[f"--extra={extra}" for extra in EXTRAS],
                        "-c", str(constraints), "--python-version", ".".join(platform.python_version_tuple()[:2]),
                        "--python-platform", "x86_64-manylinux_2_28", "--only-binary", ":all:",
                        "--index-strategy", "unsafe-best-match", "--extra-index-url", f"https://download.pytorch.org/whl/{wheels}",
                        "--no-header", "--no-annotate", "-q", "-o", str(output)], check=True)
        resolved = dict(line.split("==", 1) for line in output.read_text(encoding="utf-8").split() if "==" in line)
    return {name: version for name, version in resolved.items() if canonicalize_name(name) not in
            {canonicalize_name(known) for known in versions}}


def linux_cuda_lockfile_text(versions: dict[str, str], wheels: str, hashes_of: Callable[[str, str], list[str]]) -> str:
    """*versions* as a pip requirements file with every file's hash, for the Linux setup's CUDA build of torch."""
    header = [
        f"# The packages the Linux {wheels} build of torch needs beyond requirements-lock-hashed.txt, with the SHA-256 of every file.",
        "# Written by tools/write_lockfile.py --hashes; do not edit by hand. setup_env.py --self-contained adds it on Linux",
        "# when it installs the CUDA build of torch.",
        f"# torch-wheels: {wheels}",
    ]
    blocks = [" \\\n".join([f"{name}=={versions[name]}"] + [f"    --hash=sha256:{digest}" for digest in hashes_of(name, versions[name])])
              for name in sorted(versions)]
    return "\n".join(header + blocks) + "\n"


def hashed_lockfile_text(versions: dict[str, str], wheels: str, hashes_of: Callable[[str, str], list[str]],
                         torch_hashes_of: Callable[[str, str], list[str]]) -> str:
    """The pins of *versions* as a pip requirements file with every file's hash, torch with both builds' hashes."""
    builds = [wheels] if wheels == "cpu" else [wheels, "cpu"]
    header = [
        "# The versions of requirements-lock.txt with the SHA-256 of every file pip may download for them.",
        "# Written by tools/write_lockfile.py --hashes; do not edit by hand. setup_env.py --self-contained installs",
        "# from it with --require-hashes.",
        f"# torch-hashes: {' '.join(builds)}",
    ]
    blocks = []
    for name in sorted(versions):
        version = versions[name]
        if name == "torch":
            hashes = [digest for build in builds for digest in torch_hashes_of(version, build)]
        else:
            hashes = hashes_of(name, version)
        lines = [f"{name}=={version}"] + [f"    --hash=sha256:{digest}" for digest in hashes]
        blocks.append(" \\\n".join(lines))
    return "\n".join(header + blocks) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Write requirements-lock.txt from this environment.")
    parser.add_argument("--hashes", action="store_true",
                        help=f"also write {HASHED_LOCKFILE.name} (asks PyPI and PyTorch's wheel indexes)")
    args = parser.parse_args()
    versions = installed_versions(project_requirements())
    wheels = torch_wheels()
    LOCKFILE.write_text(lockfile_text(versions, wheels), encoding="utf-8", newline="\n")
    print(f"{LOCKFILE.name}: {len(versions)} packages")
    if args.hashes:
        text = hashed_lockfile_text(versions, wheels, pypi_hashes, torch_hashes)
        HASHED_LOCKFILE.write_text(text, encoding="utf-8", newline="\n")
        print(f"{HASHED_LOCKFILE.name}: {len(versions)} packages with their hashes")
        if wheels != "cpu":
            linux = linux_cuda_versions(versions, wheels)
            LINUX_CUDA_LOCKFILE.write_text(linux_cuda_lockfile_text(linux, wheels, pypi_hashes), encoding="utf-8", newline="\n")
            print(f"{LINUX_CUDA_LOCKFILE.name}: {len(linux)} packages with their hashes")


if __name__ == "__main__":
    main()
