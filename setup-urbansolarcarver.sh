#!/usr/bin/env bash
# Sets up UrbanSolarCarver in this folder on Linux. Extract the whole release
# first, run this once from a terminal, then start the app with
# ./start-urbansolarcarver.sh. Run it again to repair or update.
#
# What it downloads, each file checked before it is used:
#   uv, the version below, from github.com/astral-sh/uv, against USC_UV_SHA256 below;
#   Python, uv's own build, against the checksums built into uv;
#   PyTorch and the other packages, against install/requirements-lock-hashed.txt
#   (and, for the CUDA build, install/requirements-linux-cuda-hashed.txt).
# Everything it makes stays in this folder (.runtime and .venv): nothing on PATH,
# nothing in your shell's startup files, no root rights, any installed Python untouched.
# The one exception, only if you answer y at the end: an entry in the applications
# menu (~/.local/share/applications/urbansolarcarver.desktop).
# Options go to install/setup_env.py, for example --cpu for the CPU build of PyTorch.
set -u

USC_UV_VERSION="0.13.8"
USC_UV_SHA256="5acfd9177cfecf0bf87578f059728215ccc884388988f55f7a65041b57387d91"
USC_PYTHON_VERSION="3.14.6"

# The real path (-P): uv reports its Python by the real path, which is compared with it below.
folder="$(cd "$(dirname "$0")" && pwd -P)"
runtime="$folder/.runtime"
uv_file="uv-x86_64-unknown-linux-gnu.tar.gz"
uv_url="https://github.com/astral-sh/uv/releases/download/$USC_UV_VERSION/$uv_file"
download="$runtime/download/$uv_file"
uv="$runtime/uv/uv"
suggested="${XDG_DATA_HOME:-$HOME/.local/share}/urbansolarcarver"

fail() {
  for line in "$@"; do echo "$line"; done
  exit 1
}

# 1. Checks, before anything is downloaded.
if [ "$(uname -s)" != "Linux" ]; then
  fail "This setup is for Linux (found $(uname -s))."
fi
if [ "$(uname -m)" != "x86_64" ]; then
  fail "This setup needs a 64-bit Intel or AMD processor (found $(uname -m))."
fi
if [ "$(id -u)" = "0" ]; then
  fail "Do not run this setup as root or with sudo: it needs no root rights, and files made as root" \
       "could not be changed by your own account later. Run it again as yourself."
fi
for needed in install/setup_env.py install/requirements-lock.txt install/requirements-lock-hashed.txt \
              install/requirements-linux-cuda-hashed.txt; do
  if [ ! -f "$folder/$needed" ]; then
    fail "setup-urbansolarcarver.sh is not next to the other files of UrbanSolarCarver in:" \
         "  \"$folder\"" "Extract the whole folder first, then run setup from there."
  fi
done
# PyTorch's Linux builds need glibc 2.28 or newer (Fedora 29, Ubuntu 18.10 and later); musl, as on Alpine, has none.
glibc="$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')"
if ! echo "$glibc" | awk -F. '/^[0-9]+\.[0-9]+/ && ($1 > 2 || ($1 == 2 && $2 >= 28)) {ok = 1} END {exit !ok}'; then
  fail "PyTorch needs glibc 2.28 or newer (found ${glibc:-none}). Use a newer Linux distribution."
fi
for tool in tar sha256sum df; do
  command -v "$tool" >/dev/null 2>&1 || fail "Setup needs the $tool command, which was not found."
done
if command -v curl >/dev/null 2>&1; then
  downloader="curl"
elif command -v wget >/dev/null 2>&1; then
  downloader="wget"
else
  fail "Setup needs curl or wget to download uv; neither was found. Install one of them, then run setup again."
fi

# A drive formatted for Windows (NTFS, FAT, exFAT) cannot hold the links and file modes a Python environment needs.
filesystem="$(stat -f -c %T "$folder" 2>/dev/null || true)"
case "$filesystem" in
  msdos|vfat|exfat|ntfs|ntfs3|fuseblk)
    fail "This folder is on a drive formatted for Windows ($filesystem):" "  \"$folder\"" \
         "A Python environment cannot be made there. Move this folder into your home folder, for example" \
         "  \"$suggested\"" "and run setup again." ;;
esac

# Your own pip and uv settings do not apply here: a PIP_TARGET, for example,
# would install outside this folder. Only the ones set below count.
for variable in $(compgen -e); do
  case "$variable" in UV_*|PIP_*) unset "$variable" ;; esac
done

# The disk space it needs: the CUDA build of PyTorch with its download cache, or
# the CPU build (with --cpu, or when no NVIDIA driver is found).
needed_gb=12
command -v nvidia-smi >/dev/null 2>&1 || needed_gb=2
for argument in "$@"; do
  [ "$argument" = "--cpu" ] && needed_gb=2
done

mkdir -p "$runtime/download" "$runtime/tmp" 2>/dev/null
if ! : > "$runtime/write-check" 2>/dev/null; then
  fail "Setup cannot write in this folder:" "  \"$folder\"" \
       "Move it somewhere you can write, for example" "  \"$suggested\"" "and run setup again."
fi
rm -f "$runtime/write-check"
# A drive mounted noexec lets files be written but not run.
printf '#!/bin/sh\nexit 0\n' > "$runtime/exec-check" && chmod +x "$runtime/exec-check"
if ! "$runtime/exec-check" 2>/dev/null; then
  rm -f "$runtime/exec-check"
  fail "Programs cannot run from this folder (its drive is mounted noexec):" "  \"$folder\"" \
       "Move this folder into your home folder, for example" "  \"$suggested\"" "and run setup again."
fi
rm -f "$runtime/exec-check"
# The environment's python is a symbolic link; some drives (and older stat versions that do not name them) cannot hold one.
rm -f "$runtime/link-check"
if ! ln -s write-check "$runtime/link-check" 2>/dev/null || [ ! -L "$runtime/link-check" ]; then
  rm -f "$runtime/link-check"
  fail "This folder's drive cannot hold symbolic links, which a Python environment needs:" "  \"$folder\"" \
       "Move this folder into your home folder, for example" "  \"$suggested\"" "and run setup again."
fi
rm -f "$runtime/link-check"
free_kb="$(df -Pk "$folder" 2>/dev/null | awk 'NR==2 {print $4}')"
if [ -z "$free_kb" ]; then
  echo "Free disk space could not be checked on this drive; setup continues."
elif [ "$free_kb" -lt $((needed_gb * 1024 * 1024)) ]; then
  fail "Setup needs about $needed_gb GB of free disk space on this drive; $((free_kb / 1024 / 1024)) GB is free." \
       "Free some disk space or move this folder to another drive, then run setup again."
fi

# Temporary files of this setup stay in the folder too.
export TMPDIR="$runtime/tmp"

# 2. What it will do.
echo "This sets up UrbanSolarCarver in this folder:"
echo "  \"$folder\""
echo "It downloads, checking each file before it is used:"
echo "  uv $USC_UV_VERSION, about 17 MB, from github.com/astral-sh/uv"
echo "  Python $USC_PYTHON_VERSION, about 30 MB, uv's own build, from github.com/astral-sh/python-build-standalone"
echo "  PyTorch: with CUDA (NVIDIA graphics cards), about 870 MB from download.pytorch.org and 2.8 GB of NVIDIA libraries from pypi.org;"
echo "    without, about 200 MB from download.pytorch.org"
echo "  the other packages, about 350 MB, from pypi.org"
echo "It needs about $needed_gb GB of free disk space."
echo "Everything stays in this folder: deleting the folder removes it all."
read -r -p "Press Enter to start, or Ctrl+C to stop. " _ || true

# 3. uv: an archive already downloaded is checked again and reused.
if [ -n "${USC_UV_ARCHIVE:-}" ]; then
  # For the tests only: USC_UV_ARCHIVE names a local file that stands in for the download.
  cp "$USC_UV_ARCHIVE" "$download" || fail "uv could not be copied from $USC_UV_ARCHIVE"
elif [ ! -f "$download" ]; then
  echo "Downloading uv $USC_UV_VERSION..."
  if [ "$downloader" = "curl" ]; then
    curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 --output "$download" "$uv_url"
  else
    wget --quiet --https-only --output-document="$download" "$uv_url"
  fi
  if [ "$?" -ne 0 ]; then
    rm -f "$download"
    fail "uv could not be downloaded from $uv_url" \
         "Check the internet connection (or a proxy that blocks it) and run setup again."
  fi
fi
if [ "$(sha256sum "$download" | awk '{print $1}')" != "$USC_UV_SHA256" ]; then
  rm -f "$download"
  fail "The downloaded uv does not match the SHA-256 in this script, so it was deleted and not used." \
       "The download may have been cut short or changed on the way. Run setup again; if this repeats," \
       "do not use this network, and report it."
fi
echo "uv $USC_UV_VERSION: SHA-256 checked."
rm -rf "$runtime/uv"
mkdir -p "$runtime/uv"
if ! tar -xzf "$download" -C "$runtime/uv" --strip-components=1 || [ ! -x "$uv" ]; then
  fail "uv could not be unpacked into this folder. Run setup again:" "  \"$runtime/uv\""
fi

# 4. Python: uv's own build in .runtime/python, for this process only. uv reads
# no configuration file, ignores any other Python, adds nothing to PATH (--no-bin),
# and trusts the certificates this system trusts, as pip does.
export UV_PYTHON_INSTALL_DIR="$runtime/python"
export UV_CACHE_DIR="$runtime/cache/uv"
export UV_PYTHON_PREFERENCE="only-managed"
export UV_NO_CONFIG=1
export UV_NATIVE_TLS=1
unset VIRTUAL_ENV PYTHONHOME PYTHONPATH
export PYTHONNOUSERSITE=1
if ! "$uv" python install "$USC_PYTHON_VERSION" --no-bin; then
  fail "uv could not install Python $USC_PYTHON_VERSION into this folder:" "  \"$runtime/python\"" \
       "Read the messages above, check the internet connection, and run setup again."
fi
python="$("$uv" python find "$USC_PYTHON_VERSION" 2>/dev/null)"
case "$python" in
  "$runtime/python/"*) ;;
  *) fail "uv could not find the Python it installed in:" "  \"$runtime/python\"" "Run setup again." ;;
esac

# 5. The environment (.venv) and the packages, every download checked.
if ! "$python" "$folder/install/setup_env.py" --self-contained "$@"; then
  fail "The setup did not finish. Read the messages above, then run setup again:" \
       "what was already downloaded is checked again and reused."
fi

# 6. An entry in the applications menu, only if asked. No answer within 30 seconds means no.
echo
echo "Setup finished."
answer=""
read -r -t 30 -p "Add UrbanSolarCarver to the applications menu? [y/N] " answer || true
case "$answer" in
  y|Y|yes|Yes)
    applications="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    entry="$applications/urbansolarcarver.desktop"
    case "$folder" in
      *[\"\`\$\\%]*)
        echo "The menu entry was not made: this folder's path has a character a menu entry cannot hold (\" \` \$ \\ %)." ;;
      *)
        icon="$(ls "$folder"/src/urbansolarcarver/ui_static/assets/favicon-*.svg 2>/dev/null | head -n 1)"
        [ -n "$icon" ] && cp "$icon" "$runtime/urbansolarcarver.svg"
        if mkdir -p "$applications" && cat > "$entry" <<ENTRY
[Desktop Entry]
Type=Application
Name=UrbanSolarCarver
Comment=Solar envelopes for urban sites, in the browser
Exec="$folder/start-urbansolarcarver.sh"
Path=$folder
Icon=$runtime/urbansolarcarver.svg
Terminal=true
Categories=Science;Engineering;
ENTRY
        then
          echo "Added UrbanSolarCarver to the applications menu. Deleting this folder leaves that entry: delete it by hand:"
          echo "  \"$entry\""
        else
          echo "The menu entry could not be made."
        fi ;;
    esac ;;
esac
echo "Start UrbanSolarCarver with ./start-urbansolarcarver.sh in this folder."
echo "To remove it, delete this folder: setup kept everything it made inside it."
