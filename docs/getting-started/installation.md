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
```

## Manual installation

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install torch --index-url https://download.pytorch.org/whl/cu126
pip install -e .[dev,ui]       # leave out ,ui if you do not want the browser UI
```

Pick the PyTorch index for your driver on https://pytorch.org/get-started/locally/ (`nvidia-smi` shows the highest CUDA version the driver supports; `python setup_env.py --dry-run` shows the index the installer would choose). PyTorch stops publishing to older indexes, so prefer one that still receives releases.

An editable install keeps the version number it was installed with. After pulling a new version, refresh it with `pip install -e . --no-deps` so `usc --version` reports it.

## Browser UI

The browser interface is an optional extra of the package (`ui`). `setup_env.py` installs it unless `--no-ui` is given. To add it to an existing environment:

```bash
python -m pip install -e ".[ui]"
```

Then start it with `usc ui`. Without the extra, every other `usc` command works as before, and `usc ui` prints the install command above and exits.

## Requirements

- Python >= 3.10
- NVIDIA GPU + CUDA driver (recommended; CPU mode available but significantly slower)

## Verifying the installation

```python
import torch
print(torch.cuda.is_available())  # True if GPU is available

from urbansolarcarver import load_config
print("USC ready")
```
