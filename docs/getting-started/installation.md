# Installation

## Windows: from a release zip

No Python, git or administrator rights needed beforehand.

1. Download [UrbanSolarCarver-windows.zip](https://github.com/avarth/UrbanSolarCarver/releases/latest/download/UrbanSolarCarver-windows.zip), the app zip of the
   [latest release](https://github.com/avarth/UrbanSolarCarver/releases/latest). It holds only what the app needs; the
   release's **Source code (zip)** and the main branch (**Code > Download ZIP**) hold the developer files too, and the main
   branch may hold work in progress. Extract the whole zip (right-click,
   **Extract All**) to any folder you can write to, outside OneDrive. A per-user programs folder such as
   `%LOCALAPPDATA%\Programs\UrbanSolarCarver` works well; a short path avoids Windows path-length limits. Running the setup
   from inside the zip does not work; it asks you to extract first.
2. Double-click `setup-urbansolarcarver.bat` in that folder. It says what it will download and waits for a key press. At the
   end it offers a shortcut on the desktop.
3. From then on, double-click `start-urbansolarcarver.bat`, or the shortcut. The interface opens in your browser.

Windows may warn that the `.bat` files come from the internet: choose **More info > Run anyway**, or first right-click each file,
choose **Properties** and tick **Unblock**. Both files are plain text; open them in Notepad to read what they do.

What the setup downloads, each file checked against a SHA-256 hash that is already in the folder before the download starts:

| What | From | Size | Checked against |
|---|---|---|---|
| uv, a pinned version | github.com/astral-sh/uv | about 16 MB | the hash in `setup-urbansolarcarver.bat` |
| Python 3.14, uv's own build | github.com/astral-sh/python-build-standalone | about 22 MB | the checksums built into uv |
| PyTorch: with CUDA for an NVIDIA graphics card, else the CPU build | download.pytorch.org | about 2.6 GB, or about 130 MB | `install/requirements-lock-hashed.txt` |
| The other packages | pypi.org | about 300 MB | `install/requirements-lock-hashed.txt` |

It needs about 7 GB of free disk space with CUDA (the packages and their download cache), or about 1.5 GB with the CPU build;
the setup checks before downloading and says how much is free.

The setup picks the CUDA build of PyTorch when the NVIDIA driver can run it, and the CPU build otherwise, and says which. Most
cards get the build for CUDA 12.6; RTX 50-series cards (and other GPUs of compute capability 10 or higher) get the build for
CUDA 13.0, which needs NVIDIA driver 580 or newer. At the end the setup runs a small computation on the GPU. When the app
finds a GPU that its PyTorch has no code for, it uses the CPU and says so, rather than failing at the first run.
`setup-urbansolarcarver.bat --cpu` forces the CPU build. Everything it makes stays in the folder: uv, Python, the download
caches and its temporary files in `.runtime`, the packages in `.venv`. Nothing is added to PATH or the registry, and a Python
installed on the computer is not used or changed. The one file it can write outside the folder is the desktop shortcut, and only
if you answer Y. Running the setup again repairs or updates the installation, reusing what it already downloaded after checking
it again. To remove UrbanSolarCarver, delete the folder; a desktop shortcut stays behind, so delete it by hand.

The setup stops before downloading, and says why, when:

- the folder is in OneDrive: a synced folder would upload gigabytes of packages, and files OneDrive locks or keeps online-only
  break the install. Move the folder out of OneDrive, for example to `%LOCALAPPDATA%\Programs\UrbanSolarCarver`;
- the folder's path is too long for PyTorch's files: move it to a shorter path, such as the one above;
- the drive has too little free space.

pip and uv read no settings from your profile during this setup (no `pip.ini`, no `PIP_` or `UV_` variables), so a company
package mirror set there is not used. uv trusts the certificates Windows trusts, as pip does.

If the setup says that PyTorch cannot be imported, the Microsoft Visual C++ Redistributable (x64) may be missing. Install it from
Microsoft (<https://aka.ms/vs/17/release/vc_redist.x64.exe>; this needs administrator rights), then run the setup again.

Your projects are kept apart from the app, in `UrbanSolarCarver\projects` in your user folder, so replacing or deleting the app
folder keeps them. To keep them elsewhere, for example in a `projects` folder inside the app folder, use **Change folder** at the
foot of the project list on the home screen.

## Linux: from a release archive

No Python, git or root rights needed beforehand. It runs on 64-bit Intel or AMD computers with glibc 2.28 or newer: Fedora 29,
Ubuntu 18.10, Debian 10 and later, not Alpine.

1. Download [UrbanSolarCarver-linux.tar.gz](https://github.com/avarth/UrbanSolarCarver/releases/latest/download/UrbanSolarCarver-linux.tar.gz)
   from the [latest release](https://github.com/avarth/UrbanSolarCarver/releases/latest) and extract it in your home folder,
   for example to `~/.local/share/urbansolarcarver`:

    ```bash
    mkdir -p ~/.local/share && tar -xzf ~/Downloads/UrbanSolarCarver-linux.tar.gz -C ~/.local/share
    mv ~/.local/share/UrbanSolarCarver ~/.local/share/urbansolarcarver
    ```

    A file manager's **Extract** works too. Keep the folder on a Linux drive: on a drive formatted for Windows (NTFS, FAT,
    exFAT), or one mounted `noexec`, the setup stops and says to move it.
2. In a terminal, in that folder, run `./setup-urbansolarcarver.sh`. It says what it will download and waits for Enter. At the
   end it offers an entry in the applications menu.
3. From then on, run `./start-urbansolarcarver.sh`, or choose UrbanSolarCarver in the applications menu. The interface opens
   in your browser; the terminal stays open while it runs, and Ctrl+C stops it.

The setup works as the Windows one does: it downloads uv (a pinned version, checked against the SHA-256 in the script), uv's
own Python 3.14, and the packages, each checked against the hashes in `install/`. With the CUDA build of PyTorch it also
downloads NVIDIA's CUDA libraries from pypi.org, about 2.8 GB, checked against `install/requirements-linux-cu126-hashed.txt` (`-cu130-` for RTX 50-series cards); no
CUDA toolkit is needed, only the NVIDIA driver. It needs about 12 GB of free disk space with CUDA, or about 2 GB with the CPU
build (`./setup-urbansolarcarver.sh --cpu`, or when `nvidia-smi` is not found). Everything stays in the folder, in `.runtime`
and `.venv`: nothing is added to PATH or to your shell's startup files, and it does not use or change a Python installed on the
computer. It needs no root rights and stops if run with sudo. The one file it can write outside the folder is the menu entry,
`~/.local/share/applications/urbansolarcarver.desktop`, and only if you answer y. To remove UrbanSolarCarver, delete the folder
and that file.

## Quick setup with Python (developers)

```bash
git clone https://github.com/avarth/UrbanSolarCarver.git
cd UrbanSolarCarver
python install/setup_env.py
```

This creates a virtual environment (`.venv/` in the repository; on Windows it falls back to `~/.usc-venv` when the repository path is too long for the 260-character path limit), reads the CUDA version from your NVIDIA driver, asks the PyTorch wheel indexes that driver can run which torch they offer and installs the newest, installs USC in editable mode together with the browser UI (the `ui` extra), and precompiles the Warp kernels.

```bash
python install/setup_env.py --cpu             # force CPU-only (no CUDA)
python install/setup_env.py --dry-run         # show what would be installed
python install/setup_env.py --no-ui           # leave out the browser UI (the ui extra)
python install/setup_env.py --venv-dir PATH   # put the virtual environment at PATH
python install/setup_env.py --latest          # the newest versions, not the tested ones
```

`install/setup_env.py` installs the versions in `install/requirements-lock.txt`, which the tests last passed on, so results can be reproduced.
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

This route takes the newest versions, not the tested ones. Pick the PyTorch index for your driver on https://pytorch.org/get-started/locally/ (`nvidia-smi` shows the highest CUDA version the driver supports; `python install/setup_env.py --dry-run` shows the index the installer would choose). PyTorch stops publishing to older indexes, so prefer one that still receives releases.

An editable install keeps the version number it was installed with. After pulling a new version, refresh it with `pip install -e . --no-deps` so `usc --version` reports it.

## Browser UI

The browser interface is an optional extra of the package (`ui`). `install/setup_env.py` installs it unless `--no-ui` is given. To add it to an existing environment:

```bash
python -m pip install -e ".[ui]"
```

Then start it by double-clicking `start-urbansolarcarver.bat` (Windows) or running `./start-urbansolarcarver.sh` (Linux, macOS) in the repository folder. The launcher runs on the environment in `.venv` in that folder, made by the setup script or by `setup_env.py`, or on the one `USC_VENV` names; it does not install anything itself. From a terminal, `usc ui` does the same. Without the extra, every other `usc` command works as before, and `usc ui` prints the install command above and exits.

## Requirements

- Python 3.12 or newer (3.12 to 3.14 for the tested versions; see above)
- An NVIDIA GPU with its driver (recommended). Without one, everything runs on the CPU, more slowly: see
  [Without an NVIDIA GPU](#without-an-nvidia-gpu).

## Without an NVIDIA GPU

Everything runs on the CPU too: Macs, and computers with AMD or Intel graphics, use it, as does `install/setup_env.py --cpu`. The
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
