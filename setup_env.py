#!/usr/bin/env python3
"""
UrbanSolarCarver: Environment Setup
===================================

One-command bootstrap: creates a virtual environment, detects your GPU,
installs the correct PyTorch build, and installs UrbanSolarCarver with
all dependencies.

Usage
-----
    python setup_env.py                   # auto-detect GPU, install everything
    python setup_env.py --cpu             # force CPU-only (no CUDA)
    python setup_env.py --dry-run         # show what would be installed
    python setup_env.py --no-ui           # leave out the browser UI (the ui extra)
    python setup_env.py --venv-dir PATH   # put the virtual environment at PATH

Requirements
------------
- Python >= 3.10 (system or conda)
- NVIDIA GPU + driver (optional, for CUDA acceleration)

What this script does
---------------------
1. Creates  .venv/  in the repo if it doesn't exist (on Windows, falls back to
   ~/.usc-venv when the repo path is too deep for the 260-character path limit)
2. Reads the CUDA version supported by the driver from  nvidia-smi
3. Asks the PyTorch wheel indexes the driver can run which torch they offer,
   and picks the one with the newest torch
4. Upgrades pip and installs PyTorch from that index
5. Installs UrbanSolarCarver in editable mode with its dependencies, including
   warp-lang and the ui extra for  usc ui  (pip install -e .[dev,ui]; with
   --no-ui: pip install -e .[dev])
6. Verifies that torch, warp and urbansolarcarver import
7. Precompiles the Warp kernels so the first run does not pay the compile time
8. Unless --no-ui: writes a double-clickable launcher for the browser app in
   the repo, "Start UrbanSolarCarver.cmd" (Windows) or ".command" (macOS, Linux)
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────

VENV_DIR = ".venv"
MIN_PYTHON = (3, 10)

# Deepest path the torch wheel creates under site-packages (its dist-info
# license tree nests ~160 chars); used to predict Windows MAX_PATH failures.
TORCH_PATH_HEADROOM = 170
WINDOWS_MAX_PATH = 260

# PyTorch's wheel indexes, by the CUDA version their wheels need.  PyTorch
# stops publishing to older indexes (cu124 ends at torch 2.6, cu128 at 2.11),
# so the installer asks every index the driver can run which torch it offers
# and takes the newest (see resolve_torch_index).  Add new indexes here.
CPU_WHEEL_INDEX = "https://download.pytorch.org/whl/cpu"
CUDA_WHEEL_INDEXES = {
    (11, 8): "https://download.pytorch.org/whl/cu118",
    (12, 1): "https://download.pytorch.org/whl/cu121",
    (12, 4): "https://download.pytorch.org/whl/cu124",
    (12, 6): "https://download.pytorch.org/whl/cu126",
    (12, 8): "https://download.pytorch.org/whl/cu128",
    (12, 9): "https://download.pytorch.org/whl/cu129",
    (13, 0): "https://download.pytorch.org/whl/cu130",
    (13, 2): "https://download.pytorch.org/whl/cu132",
}

# ── Helpers ────────────────────────────────────────────────────────────

def log(msg: str, level: str = "info"):
    prefix = {"info": "[+]", "warn": "[!]", "error": "[X]", "ok": "[OK]"}
    print(f"{prefix.get(level, '   ')} {msg}")


def run(cmd: list[str], check: bool = True, capture: bool = False, **kw):
    """Run a subprocess, optionally capturing output."""
    if capture:
        r = subprocess.run(cmd, capture_output=True, text=True, **kw)
        if check and r.returncode != 0:
            raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{r.stderr}")
        return r
    else:
        subprocess.run(cmd, check=check, **kw)


def detect_cuda_version() -> str | None:
    """
    Read the highest CUDA version the installed NVIDIA driver supports,
    as printed by nvidia-smi (this is not the CUDA toolkit version).
    Returns a string like "12.6", or None if no GPU / driver is found.
    """
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        # Windows: try default install location
        default = Path(r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe")
        if default.is_file():
            nvidia_smi = str(default)
        else:
            return None

    try:
        r = run([nvidia_smi], capture=True, check=False)
        # Parse "CUDA Version: 12.6" from the output
        m = re.search(r"CUDA Version:\s*([\d.]+)", r.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _version_tuple(text: str) -> tuple[int, ...]:
    """(2, 14, 1) for "2.14.1" or "2.14.1+cu126"."""
    return tuple(int(part) for part in re.findall(r"\d+", text.split("+")[0]))


def newest_torch_on_index(index_url: str) -> tuple[int, ...] | None:
    """The newest torch version *index_url* offers for this Python and
    platform (asked with ``pip index versions``), or None if it cannot be
    asked (no network, old pip, nothing for this platform)."""
    try:
        r = run([sys.executable, "-m", "pip", "index", "versions", "torch",
                 "--index-url", index_url], capture=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"^torch \(([^)]+)\)", r.stdout, re.MULTILINE)
    return _version_tuple(m.group(1)) if m else None


def resolve_torch_index(cuda_version: str | None, force_cpu: bool,
                        newest_torch_on=newest_torch_on_index) -> tuple[str, str]:
    """Return (index_url, description) for the driver's CUDA version.

    Among the wheel indexes whose CUDA version the driver supports (drivers
    run wheels built for their CUDA version or older), the one offering the
    newest torch wins, the higher CUDA version breaking ties.  When no index
    can be asked, the highest supported one is used.  No driver, a forced
    CPU install, or a driver older than every index gives CPU wheels.
    *newest_torch_on* maps an index URL to its newest torch version, or None.
    """
    if force_cpu or cuda_version is None:
        return CPU_WHEEL_INDEX, "CPU-only"
    try:
        driver = tuple(int(part) for part in cuda_version.split(".")[:2])
    except ValueError:
        log(f"Unreadable CUDA version {cuda_version!r}, falling back to CPU", "warn")
        return CPU_WHEEL_INDEX, f"CPU-only (unreadable CUDA {cuda_version})"
    supported = sorted(cuda for cuda in CUDA_WHEEL_INDEXES if cuda <= driver)
    if not supported:
        log(f"CUDA {cuda_version} is older than every PyTorch wheel index, falling back to CPU", "warn")
        return CPU_WHEEL_INDEX, f"CPU-only (CUDA {cuda_version} too old)"
    log(f"Asking {len(supported)} PyTorch wheel indexes which torch they offer...")
    offers = {cuda: newest_torch_on(CUDA_WHEEL_INDEXES[cuda]) for cuda in supported}
    reachable = {cuda: version for cuda, version in offers.items() if version is not None}
    driver_text = ".".join(map(str, driver))
    if not reachable:
        cuda = supported[-1]
        log("No PyTorch wheel index could be asked; using the highest one the driver supports", "warn")
        return (CUDA_WHEEL_INDEXES[cuda],
                f"CUDA {driver_text} (cu{cuda[0]}{cuda[1]} wheels; the indexes could not be checked)")
    cuda = max(reachable, key=lambda c: (reachable[c], c))
    torch_text = ".".join(map(str, reachable[cuda]))
    return CUDA_WHEEL_INDEXES[cuda], f"CUDA {driver_text} (cu{cuda[0]}{cuda[1]} wheels, torch {torch_text})"


def venv_python(venv_dir: Path) -> Path:
    """Return path to the venv's Python executable."""
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


BROWSER_APP_LAUNCHER_NAME = "Start UrbanSolarCarver"


def write_browser_app_launcher(repository: Path, python: Path, system: str | None = None) -> Path:
    """Write a double-clickable file in *repository* that starts the browser app.

    The launcher holds the absolute paths of this installation (the venv's
    *python* and the repository's ``src``), because the venv can live outside
    the repository (``--venv-dir`` or the long-path fallback). It runs
    ``usc ui``, which opens the browser once the service listens, and keeps
    its window open on an error so the reason stays readable. Windows gets a
    ``.cmd``; macOS and Linux get an executable ``.command`` shell script.
    Running setup_env.py again rewrites it.
    """
    system = system or platform.system()
    source_folder = repository / "src"
    if system == "Windows":
        launcher = repository / f"{BROWSER_APP_LAUNCHER_NAME}.cmd"
        lines = [
            "@echo off",
            "rem Starts the UrbanSolarCarver browser app. Written by setup_env.py; run it again to update.",
            "setlocal",
            "title UrbanSolarCarver",
            f'set "USC_PYTHON={python}"',
            f'set "PYTHONPATH={source_folder}"',
            # A goto rather than an if (...) block: a ")" in the path, as in
            # "Program Files (x86)", would end such a block early.
            'if exist "%USC_PYTHON%" goto start',
            "echo The Python environment of UrbanSolarCarver was not found:",
            "echo %USC_PYTHON%",
            "echo Run setup_env.py again in this folder to repair it.",
            "pause",
            "exit /b 1",
            ":start",
            "echo Starting UrbanSolarCarver. Your browser opens when it is ready.",
            "echo Keep this window open while you work; close it to stop UrbanSolarCarver.",
            '"%USC_PYTHON%" -m urbansolarcarver.carver_cli ui %*',
            "if errorlevel 1 pause",
        ]
        launcher.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
        return launcher

    launcher = repository / f"{BROWSER_APP_LAUNCHER_NAME}.command"
    lines = [
        "#!/bin/sh",
        "# Starts the UrbanSolarCarver browser app. Written by setup_env.py; run it again to update.",
        f"usc_python={shlex.quote(str(python))}",
        'if [ ! -x "$usc_python" ]; then',
        '  echo "The Python environment of UrbanSolarCarver was not found: $usc_python"',
        '  echo "Run setup_env.py again in this folder to repair it."',
        "  exit 1",
        "fi",
        f"PYTHONPATH={shlex.quote(str(source_folder))}",
        "export PYTHONPATH",
        'echo "Starting UrbanSolarCarver. Your browser opens when it is ready."',
        'echo "Keep this window open while you work; close it to stop UrbanSolarCarver."',
        'exec "$usc_python" -m urbansolarcarver.carver_cli ui "$@"',
    ]
    launcher.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    launcher.chmod(0o755)
    return launcher


def _windows_long_paths_enabled() -> bool:
    """True if Windows has long-path support enabled in the registry."""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
            return value == 1
    except OSError:
        return False


def resolve_venv_dir(requested: str | None) -> Path:
    """Pick the venv location, avoiding Windows MAX_PATH failures.

    The torch wheel's dist-info tree nests deeply enough that extracting it
    into a venv under a long repo path exceeds MAX_PATH (WinError 206,
    'filename too long') unless long-path support is enabled.  Predict that
    before pip dies mid-install: if the default in-repo .venv would be too
    deep and long paths are off, fall back to a short per-user location.
    """
    if requested:
        venv_dir = Path(requested).resolve()
    else:
        venv_dir = Path(VENV_DIR).resolve()

    if platform.system() != "Windows":
        return venv_dir

    projected = len(str(venv_dir)) + TORCH_PATH_HEADROOM
    if projected <= WINDOWS_MAX_PATH or _windows_long_paths_enabled():
        return venv_dir

    if requested:
        # Explicit choice: respect it, but tell the user what's coming.
        log(f"venv path is {len(str(venv_dir))} chars; torch install may hit "
            f"the Windows 260-char path limit. Enable long paths "
            f"(LongPathsEnabled=1) if the install fails.", "warn")
        return venv_dir

    fallback = Path.home() / ".usc-venv"
    log(f"Repo path is too deep for an in-repo venv on this system: "
        f"{venv_dir}", "warn")
    log(f"Installing torch there would exceed the Windows 260-character "
        f"path limit (projected {projected} chars) and long-path support "
        f"is not enabled.", "warn")
    log(f"Using {fallback} instead.", "warn")
    log("To keep the venv in the repo: enable long paths (run as admin: "
        "reg add HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem "
        "/v LongPathsEnabled /t REG_DWORD /d 1) or pass --venv-dir.", "info")
    return fallback


# ── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Set up UrbanSolarCarver development environment"
    )
    parser.add_argument(
        "--cpu", action="store_true",
        help="Force CPU-only installation (skip CUDA detection)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be installed without doing anything"
    )
    parser.add_argument(
        "--venv-dir", default=None, metavar="PATH",
        help=f"Virtual environment location (default: {VENV_DIR}/ in the repo; "
             f"on Windows a short per-user path is used automatically when the "
             f"repo path is too deep for the 260-char limit)"
    )
    parser.add_argument(
        "--no-ui", action="store_true",
        help="Do not install the ui extra (the packages behind 'usc ui')"
    )
    args = parser.parse_args()

    # ── 0. Check Python version ──
    if sys.version_info < MIN_PYTHON:
        log(f"Python >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]} required, "
            f"found {sys.version_info[0]}.{sys.version_info[1]}", "error")
        sys.exit(1)
    log(f"Python {sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}")

    # ── 1. Detect GPU ──
    cuda_version = detect_cuda_version()
    if cuda_version and not args.cpu:
        log(f"Detected CUDA {cuda_version}")
    elif args.cpu:
        log("CPU-only mode (--cpu flag)")
    else:
        log("No NVIDIA GPU detected; installing CPU-only PyTorch", "warn")

    index_url, desc = resolve_torch_index(cuda_version, args.cpu)
    log(f"PyTorch target: {desc}")
    log(f"Index URL: {index_url}")

    venv_dir = resolve_venv_dir(args.venv_dir)
    install_target = ".[dev]" if args.no_ui else ".[dev,ui]"

    if args.dry_run:
        log("Dry run, would execute:", "info")
        print(f"  1. python -m venv {venv_dir}")
        print(f"  2. pip install torch --index-url {index_url}")
        print(f"  3. pip install -e {install_target}")
        if not args.no_ui:
            launcher_suffix = ".cmd" if platform.system() == "Windows" else ".command"
            print(f"  4. write {BROWSER_APP_LAUNCHER_NAME}{launcher_suffix} in {Path(__file__).resolve().parent}")
        return

    # ── 2. Create venv ──
    vpy = venv_python(venv_dir)
    if not vpy.is_file():
        log(f"Creating virtual environment in {venv_dir}")
        run([sys.executable, "-m", "venv", str(venv_dir)])
    else:
        log(f"Virtual environment already exists at {venv_dir}")

    if not vpy.is_file():
        log(f"venv creation failed: {vpy} not found", "error")
        sys.exit(1)

    # ── 3. Upgrade pip ──
    log("Upgrading pip...")
    run([str(vpy), "-m", "pip", "install", "--upgrade", "pip", "--quiet"])

    # ── 4. Install PyTorch ──
    log(f"Installing PyTorch ({desc})...")
    run([str(vpy), "-m", "pip", "install",
         "torch", "--index-url", index_url, "--quiet"])

    # ── 5. Install UrbanSolarCarver + all deps ──
    log("Installing UrbanSolarCarver and dependencies...")
    run([str(vpy), "-m", "pip", "install", "-e", install_target, "--quiet"])

    # ── 6. Verify ──
    log("Verifying installation...")

    # Check torch
    r = run([str(vpy), "-c",
             "import torch; "
             "print(f'PyTorch {torch.__version__}'); "
             "print(f'CUDA available: {torch.cuda.is_available()}'); "
             "print(f'Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"CPU\"}')"
             ], capture=True, check=False)
    if r.returncode == 0:
        for line in r.stdout.strip().split("\n"):
            log(line, "ok")
    else:
        log("PyTorch import failed.", "error")
        print(r.stderr)
        sys.exit(1)

    # Check warp
    r = run([str(vpy), "-c", "import warp; print(f'Warp {warp.__version__}')"],
            capture=True, check=False)
    if r.returncode == 0:
        log(r.stdout.strip(), "ok")
    else:
        log("Warp import failed; GPU kernels won't work", "warn")

    # Check urbansolarcarver
    r = run([str(vpy), "-c",
             "from urbansolarcarver import load_config, run_pipeline; "
             "print('UrbanSolarCarver OK')"],
            capture=True, check=False)
    if r.returncode == 0:
        log(r.stdout.strip(), "ok")
    else:
        log("UrbanSolarCarver import failed.", "error")
        print(r.stderr)
        sys.exit(1)

    # ── 7. Precompile Warp kernels ──
    # Warp JIT-compiles kernels on first use (~3-10 s, once per machine,
    # cached on disk). Doing it now, while the user already expects the
    # installer to take time, means the first carving run reflects real
    # compute time instead of compilation.
    log("Precompiling Warp compute kernels (one-time, cached)...")
    r = run([str(vpy), "-c",
             "from urbansolarcarver.warp_kernels import warmup_kernels; "
             "print('warm' if warmup_kernels() else 'skipped')"],
            capture=True, check=False)
    if r.returncode == 0 and "warm" in r.stdout:
        log("Warp kernels compiled and cached", "ok")
    else:
        log("Kernel precompilation skipped; kernels will compile on first run", "warn")

    launcher = None
    if not args.no_ui:
        launcher = write_browser_app_launcher(Path(__file__).resolve().parent, vpy)
        log(f"Browser app launcher written: {launcher}", "ok")

    # ── Done ──
    print()
    log("Setup complete.", "ok")
    print()
    print(f"  Activate:  {venv_dir}\\Scripts\\activate" if platform.system() == "Windows"
          else f"  Activate:  source {venv_dir}/bin/activate")
    print(f"  CLI:       urbansolarcarver --help")
    if launcher is not None:
        print(f"  Browser:   double-click \"{launcher.name}\" in {launcher.parent}  (or run: usc ui)")
    print(f"  Jupyter:   {vpy} -m jupyter notebook")
    print()


if __name__ == "__main__":
    main()
