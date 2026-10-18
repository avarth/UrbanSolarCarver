"""The program that shows the folder picker: ``python -I folder_picker_child.py <initial folder>``.

``folder_picker.choose_folder`` starts it as a short-lived child process, so the service never loads Tcl/Tk: a Tk root must
be created, used and freed on one thread (the main thread on macOS), and a service thread cannot promise that. This file
imports nothing but the standard library, because it runs as a plain script.

The result is the exit code: ``EXIT_CHOSEN`` with ``{"folder": "<path>"}`` as JSON on stdout (JSON keeps a non-ASCII path
intact whatever the console code page is), ``EXIT_CANCELLED``, or ``EXIT_UNAVAILABLE`` with the reason on stderr.
"""
import json
import sys

EXIT_CHOSEN = 0
EXIT_CANCELLED = 10
EXIT_UNAVAILABLE = 11
DIALOG_TITLE = "Choose the projects folder"


class PickerUnavailable(Exception):
    """tkinter is missing, or there is no display."""


def choose_folder_in_this_process(initial_folder: str) -> str | None:
    """Show the folder picker above the other windows, starting in *initial_folder*; None when the user cancels.

    A hidden, topmost Tk root is created for the dialog and destroyed after it, on the calling thread.
    """
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as error:
        raise PickerUnavailable("tkinter is not installed with this Python.") from error
    try:
        root = tkinter.Tk()
    except tkinter.TclError as error:
        raise PickerUnavailable(f"There is no display to show the folder picker on: {error}") from error
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(parent=root, initialdir=initial_folder, title=DIALOG_TITLE, mustexist=False)
    finally:
        root.destroy()
    return str(chosen) if chosen else None     # a cancelled dialog gives "" (or an empty tuple on some platforms)


def main(arguments: list[str]) -> int:
    if len(arguments) != 1:
        sys.stderr.write("Usage: folder_picker_child.py <initial folder>\n")
        return EXIT_UNAVAILABLE
    try:
        chosen = choose_folder_in_this_process(arguments[0])
    except PickerUnavailable as error:
        sys.stderr.write(str(error))
        return EXIT_UNAVAILABLE
    if chosen is None:
        return EXIT_CANCELLED
    sys.stdout.write(json.dumps({"folder": chosen}))
    return EXIT_CHOSEN


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
