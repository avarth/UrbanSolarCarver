"""The operating system's folder picker and file manager, shown on the computer the service runs on.

The browser never sends a path so choosing a folder is done here with Python's tkinter. tkinter is imported when
the dialog opens: a Python without it, or a computer without a display, raises FolderPickerUnavailable and the
rest of the service is unaffected.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DIALOG_TITLE = "Choose the projects folder"


class FolderPickerUnavailable(Exception):
    """The folder picker cannot open here (tkinter is missing, or there is no display)."""


def choose_folder(initial_folder: Path) -> Path | None:
    """Show the folder picker above the other windows, starting in *initial_folder*; None when the user cancels.

    A hidden, topmost Tk root is created for the dialog and destroyed after it, so the dialog appears above the browser.
    """
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as error:
        raise FolderPickerUnavailable("tkinter is not installed with this Python.") from error
    try:
        root = tkinter.Tk()
    except tkinter.TclError as error:
        raise FolderPickerUnavailable(f"There is no display to show the folder picker on: {error}") from error
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(parent=root, initialdir=str(initial_folder), title=DIALOG_TITLE, mustexist=False)
    finally:
        root.destroy()
    return Path(chosen) if chosen else None     # a cancelled dialog gives "" (or an empty tuple on some platforms)


def open_in_file_manager(folder: Path) -> None:
    """Open *folder* in Explorer (Windows), Finder (macOS) or the file manager of the desktop (Linux)."""
    if sys.platform == "win32":
        os.startfile(folder)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
