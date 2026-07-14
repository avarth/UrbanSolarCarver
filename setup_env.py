#!/usr/bin/env python3
"""
UrbanSolarCarver — Environment Setup
=====================================

One-command bootstrap: creates a virtual environment, detects your GPU,
installs the correct PyTorch build, and installs UrbanSolarCarver with
all dependencies.

Usage
-----
    python setup_env.py            # auto-detect GPU, install everything
    python setup_env.py --cpu      # force CPU-only (no CUDA)
    python setup_env.py --dry-run  # show what would be installed

Requirements
------------
- Python >= 3.10 (system or conda)
- NVIDIA GPU + driver (optional, for CUDA acceleration)

What this script does
---------------------
1. Creates  .venv/  (if it doesn't exist)
2. Detects CUDA version via  nvidia-smi
3. Picks the matching PyTorch wheel index
4. Installs PyTorch + warp-lang
5. Installs UrbanSolarCarver in editable mode  (pip install -e .)
6. Verifies the installation
"""

from __future__ import annotations

import argparse
import os
import platform
import re
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

# PyTorch CUDA version → pip index URL
# Updated for PyTorch 2.5+; check https://pytorch.org/get-started/locally/
TORCH_INDEX = {
    "cpu":   "https://download.pytorch.org/whl/cpu",
    "11.8":  "https://download.pytorch.org/whl/cu118",
    "12.1":  "https://download.pytorch.org/whl/cu121",
    "12.4":  "https://download.pytorch.org/whl/cu124",
    "12.6":  "https://download.pytorch.org/whl/cu124",  # 12.6 driver uses cu124 wheels
    "12.8":  "https://download.pytorch.org/whl/cu124",  # 12.8 driver uses cu124 wheels
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
    Detect CUDA toolkit version from nvidia-smi.
    Returns a string like "12.6" or None if no GPU / driver found.
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


def resolve_torch_index(cuda_version: str | None, force_cpu: bool) -> tuple[str, str]:
    """
    Given CUDA version string (or None), return (index_url, description).
    """
    if force_cpu or cuda_version is None:
        return TORCH_INDEX["cpu"], "CPU-only"

    # Match major.minor to our known index URLs
    major_minor = ".".join(cuda_version.split(".")[:2])

    if major_minor in TORCH_INDEX:
        return TORCH_INDEX[major_minor], f"CUDA {major_minor}"

    # Try just the major version with common minor
    major = cuda_version.split(".")[0]
    if major.isdigit() and int(major) >= 13:
        # Drivers are backward compatible: newer-than-known CUDA runs cu128 wheels
        return "https://download.pytorch.org/whl/cu128", f"CUDA {major_minor} (using cu128 wheels)"
    if major == "12":
        # All CUDA 12.x uses cu124 wheels (binary compatible)
        return TORCH_INDEX["12.4"], f"CUDA {major_minor} (using cu124 wheels)"
    elif major == "11":
        return TORCH_INDEX["11.8"], f"CUDA {major_minor} (using cu118 wheels)"

    log(f"Unknown CUDA version {cuda_version}, falling back to CPU", "warn")
    return TORCH_INDEX["cpu"], f"CPU-only (unknown CUDA {cuda_version})"


def venv_python(venv_dir: Path) -> Path:
    """Return path to the venv's Python executable."""
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


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
        log("No NVIDIA GPU detected — installing CPU-only PyTorch", "warn")

    index_url, desc = resolve_torch_index(cuda_version, args.cpu)
    log(f"PyTorch target: {desc}")
    log(f"Index URL: {index_url}")

    venv_dir = resolve_venv_dir(args.venv_dir)

    if args.dry_run:
        log("Dry run — would execute:", "info")
        print(f"  1. python -m venv {venv_dir}")
        print(f"  2. pip install torch --index-url {index_url}")
        print(f"  3. pip install .[dev]")
        return

    # ── 2. Create venv ──
    vpy = venv_python(venv_dir)
    if not vpy.is_file():
        log(f"Creating virtual environment in {venv_dir}")
        run([sys.executable, "-m", "venv", str(venv_dir)])
    else:
        log(f"Virtual environment already exists at {venv_dir}")

    if not vpy.is_file():
        log(f"venv creation failed — {vpy} not found", "error")
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
    run([str(vpy), "-m", "pip", "install", "-e", ".[dev]", "--quiet"])

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
        log("PyTorch import failed!", "error")
        print(r.stderr)
        sys.exit(1)

    # Check warp
    r = run([str(vpy), "-c", "import warp; print(f'Warp {warp.__version__}')"],
            capture=True, check=False)
    if r.returncode == 0:
        log(r.stdout.strip(), "ok")
    else:
        log("Warp import failed — GPU kernels won't work", "warn")

    # Check urbansolarcarver
    r = run([str(vpy), "-c",
             "from urbansolarcarver import load_config, run_pipeline; "
             "print('UrbanSolarCarver OK')"],
            capture=True, check=False)
    if r.returncode == 0:
        log(r.stdout.strip(), "ok")
    else:
        log("UrbanSolarCarver import failed!", "error")
        print(r.stderr)
        sys.exit(1)

    # ── 7. Precompile Warp kernels ──
    # Warp JIT-compiles kernels on first use (~3-10 s, once per machine,
    # cached on disk).  Doing it now — while the user already expects the
    # installer to take time — means the first carving run reflects real
    # compute time instead of compilation.
    log("Precompiling Warp compute kernels (one-time, cached)...")
    r = run([str(vpy), "-c",
             "from urbansolarcarver.raytracer import warmup_kernels; "
             "print('warm' if warmup_kernels() else 'skipped')"],
            capture=True, check=False)
    if r.returncode == 0 and "warm" in r.stdout:
        log("Warp kernels compiled and cached", "ok")
    else:
        log("Kernel precompilation skipped — kernels will compile on first run", "warn")

    # ── Done ──
    print()
    log("Setup complete!", "ok")
    print()
    print(f"  Activate:  {venv_dir}\\Scripts\\activate" if platform.system() == "Windows"
          else f"  Activate:  source {venv_dir}/bin/activate")
    print(f"  CLI:       urbansolarcarver --help")
    print(f"  Jupyter:   {vpy} -m jupyter notebook")
    print()


if __name__ == "__main__":
    main()
