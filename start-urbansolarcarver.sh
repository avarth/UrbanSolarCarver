#!/usr/bin/env bash
# Starts the UrbanSolarCarver browser app on Linux and macOS. Run it from a
# terminal, with usc ui options if you like, for example:
#   ./start-urbansolarcarver.sh --port 8780
# The first run installs UrbanSolarCarver with setup_env.py. To use an
# environment made elsewhere (setup_env.py --venv-dir), set USC_VENV to it.
set -u
repository="$(cd "$(dirname "$0")" && pwd)"

# The environments setup_env.py makes: .venv in this folder, or ~/.usc-venv.
find_environment() {
  for candidate in "$repository/.venv" "$HOME/.usc-venv"; do
    if [ -x "$candidate/bin/python" ]; then
      usc_python="$candidate/bin/python"
      return 0
    fi
  done
  return 1
}

if [ -n "${USC_VENV:-}" ]; then
  usc_python="$USC_VENV/bin/python"
  if [ ! -x "$usc_python" ]; then
    echo "No Python environment was found at USC_VENV: $USC_VENV"
    echo "Unset USC_VENV to use the one in this folder, or point it at an environment made by setup_env.py."
    exit 1
  fi
elif ! find_environment; then
  echo "UrbanSolarCarver is not installed yet. Installing it now with setup_env.py; this takes several minutes."
  system_python="$(command -v python3 || command -v python || true)"
  if [ -z "$system_python" ]; then
    echo "Python 3.10 or newer was not found. Install it, then run this script again."
    exit 1
  fi
  if ! (cd "$repository" && "$system_python" setup_env.py) || ! find_environment; then
    echo "The installation did not finish. Read the messages above, then run this script again."
    exit 1
  fi
fi

export PYTHONPATH="$repository/src"
echo "Starting UrbanSolarCarver. Your browser opens when it is ready."
echo "Keep this terminal open while you work; press Ctrl+C to stop UrbanSolarCarver."
exec "$usc_python" -m urbansolarcarver.carver_cli ui "$@"
