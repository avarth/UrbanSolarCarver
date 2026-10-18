"""The operating system's folder picker and file manager, shown on the computer the service runs on.

The browser never sends a path, so choosing a folder is done on this computer with Python's tkinter. The dialog runs in a
short-lived child process (``folder_picker_child.py``): a Tk root must live and die on one thread, the main thread on
macOS, which a request thread of the service cannot promise, and a Tk root freed on the wrong thread aborts the whole
Python process. A Python without tkinter, or a computer without a display, raises FolderPickerUnavailable and the rest of the
service is unaffected.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .folder_picker_child import EXIT_CANCELLED, EXIT_CHOSEN

CHILD_SCRIPT = Path(__file__).with_name("folder_picker_child.py")


class FolderPickerUnavailable(Exception):
    """The folder picker cannot open here (tkinter is missing, there is no display, or the dialog program failed)."""


def choose_folder(initial_folder: Path) -> Path | None:
    """Show the folder picker above the other windows, starting in *initial_folder*; None when the user cancels.

    Waits as long as the dialog stays open. Raises FolderPickerUnavailable, with the child's own message when it gave one.
    """
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        completed = subprocess.run([sys.executable, "-I", str(CHILD_SCRIPT), str(initial_folder)], capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", env=environment)
    except OSError as error:
        raise FolderPickerUnavailable(f"The folder picker program could not start: {error}") from error
    if completed.returncode == EXIT_CANCELLED:
        return None
    if completed.returncode == EXIT_CHOSEN:
        try:
            return Path(json.loads(completed.stdout)["folder"])
        except (ValueError, KeyError, TypeError) as error:
            raise FolderPickerUnavailable("The folder picker program gave an answer that cannot be read.") from error
    raise FolderPickerUnavailable(completed.stderr.strip() or f"The folder picker program stopped with exit code {completed.returncode}.")


def open_in_file_manager(folder: Path) -> None:
    """Open *folder* in Explorer (Windows), Finder (macOS) or the file manager of the desktop (Linux)."""
    if sys.platform == "win32":
        os.startfile(folder)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
