# Installation

## Quick setup (recommended)

```bash
git clone https://github.com/avarth/UrbanSolarCarver.git
cd UrbanSolarCarver
python setup_env.py
```

This creates a virtual environment (`.venv/` in the repository; on Windows it falls back to `~/.usc-venv` when the repository path is too long for the 260-character path limit), reads the CUDA version from your NVIDIA driver, asks the PyTorch wheel indexes that driver can run which torch they offer and installs the newest, installs USC in editable mode together with the browser UI (the `ui` extra), and precompiles the Warp kernels.

```bash
python setup_env.py --cpu             # force CPU-only (no CUDA)
python setup_env.py --dry-run         # show what would be installed
python setup_env.py --no-ui           # leave out the browser UI (the ui extra)
python setup_env.py --venv-dir PATH   # put the virtual environment at PATH
python setup_env.py --latest          # the newest versions, not the tested ones
```

`setup_env.py` installs the versions in `requirements-lock.txt`, which the tests last passed on, so results can be reproduced.
They install on Python 3.12 to 3.14. With a newer Python, or if PyTorch reports that your GPU is too new for it, add `--latest` for the
newest versions, which have not been tested with this release.

## Manual installation

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install torch --index-url https://download.pytorch.org/whl/cu126
pip install -e .[dev,ui]       # leave out ,ui if you do not want the browser UI
```

This route takes the newest versions, not the tested ones. Pick the PyTorch index for your driver on https://pytorch.org/get-started/locally/ (`nvidia-smi` shows the highest CUDA version the driver supports; `python setup_env.py --dry-run` shows the index the installer would choose). PyTorch stops publishing to older indexes, so prefer one that still receives releases.

An editable install keeps the version number it was installed with. After pulling a new version, refresh it with `pip install -e . --no-deps` so `usc --version` reports it.

## Browser UI

The browser interface is an optional extra of the package (`ui`). `setup_env.py` installs it unless `--no-ui` is given. To add it to an existing environment:

```bash
python -m pip install -e ".[ui]"
```

Then start it by double-clicking `start-urbansolarcarver.bat` (Windows) or running `./start-urbansolarcarver.sh` (Linux, macOS) in the repository folder; on a fresh clone the launcher runs `setup_env.py` first. From a terminal, `usc ui` does the same. Without the extra, every other `usc` command works as before, and `usc ui` prints the install command above and exits.

## Requirements

- Python 3.12 or newer (3.12 to 3.14 for the tested versions; see above)
- An NVIDIA GPU with its driver (recommended). Without one, everything runs on the CPU, more slowly: see
  [Without an NVIDIA GPU](#without-an-nvidia-gpu).

## Without an NVIDIA GPU

Everything runs on the CPU too: Macs, and computers with AMD or Intel graphics, use it, as does `setup_env.py --cpu`. The
scoring stage, where rays are traced from every test point, is the part that slows down; the other stages take about as long.
The bundled examples, scored on one desktop (AMD Ryzen 7 3800X, 8 cores; NVIDIA RTX 3060), voxel size 1 m:

| Example | Test points | GPU | CPU |
|---|---|---|---|
| New building among neighbours (Solar energy, a year) | 16,289 | 2.9 s | 3.3 s |
| Perimeter block (Sun hours, 21 December, 10 to 14 h) | 145,473 | 2.0 s | 3.2 s |
| District of many buildings (Solar energy, a year) | 527,633 | 12 s | 100 s |

Each run also takes about 6 s to start. Time grows with the number of test points and voxels: halving the voxel size makes eight
times as many voxels, and the grid step follows the voxel size unless it is set, so test points grow too. On the CPU, a large
site at a fine voxel size can take many minutes; try a coarse voxel size first.

## Verifying the installation

```python
import torch
print(torch.cuda.is_available())  # True if GPU is available

from urbansolarcarver import load_config
print("USC ready")
```
