#!/usr/bin/env bash
# Starts the UrbanSolarCarver browser app on Linux and macOS. Run it from a terminal, with
# usc ui options if you like, for example:
#   ./start-urbansolarcarver.sh --port 8780
# It runs on the environment setup-urbansolarcarver.sh (or install/setup_env.py)
# made in this folder (.venv), never on a system Python. To use an environment
# made elsewhere (setup_env.py --venv-dir), set USC_VENV to it.
set -u
repository="$(cd "$(dirname "$0")" && pwd)"

if [ -n "${USC_VENV:-}" ]; then
  usc_python="$USC_VENV/bin/python"
  if [ ! -x "$usc_python" ]; then
    echo "No Python environment was found at USC_VENV: $USC_VENV"
    echo "Unset USC_VENV to use the one in this folder, or point it at another UrbanSolarCarver environment."
    exit 1
  fi
else
  usc_python="$repository/.venv/bin/python"
  if [ ! -x "$usc_python" ]; then
    echo "UrbanSolarCarver is not set up in this folder yet."
    echo "Run ./setup-urbansolarcarver.sh first."
    exit 1
  fi
  # After the folder is moved, .venv's python still points at the old folder's Python.
  if ! "$usc_python" -c "pass" >/dev/null 2>&1; then
    echo "The Python environment in this folder does not start (was the folder moved or renamed?):"
    echo "  \"$usc_python\""
    echo "To repair it, run ./setup-urbansolarcarver.sh again."
    exit 1
  fi
fi

export PYTHONPATH="$repository/src"
# Warp's compiled kernels stay in this folder, like everything the setup made.
export WARP_CACHE_PATH="${WARP_CACHE_PATH:-$repository/.runtime/cache/warp}"
echo "Starting UrbanSolarCarver. Your browser opens when it is ready."
echo "Keep this terminal open while you work; press Ctrl+C to stop UrbanSolarCarver."
exec "$usc_python" -m urbansolarcarver.carver_cli ui "$@"
