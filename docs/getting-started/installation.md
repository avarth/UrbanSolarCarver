# Installation

## Quick setup (recommended)

```bash
git clone https://github.com/avarth/UrbanSolarCarver.git
cd UrbanSolarCarver
python setup_env.py
```

This creates a virtual environment (`.venv/` in the repository; on Windows it falls back to `~/.usc-venv` when the repository path is too long for the 260-character path limit), reads the CUDA version from your NVIDIA driver, installs the matching PyTorch wheels, installs USC in editable mode, and precompiles the Warp kernels.

```bash
python setup_env.py --cpu             # force CPU-only (no CUDA)
python setup_env.py --dry-run         # show what would be installed
python setup_env.py --venv-dir PATH   # put the virtual environment at PATH
```

## Manual installation

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e .[dev]
```

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
