"""The small settings file of the browser app's user: ``~/.urbansolarcarver/ui.json``.

It holds the projects folder the user chose with Change folder, so the next launch of ``usc ui`` opens it.
Reading never raises: a missing or damaged file means no preference. The file is rewritten as a whole, through a
temporary file in the same folder, so a crash while writing cannot leave half a file.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

PROJECTS_FOLDER_KEY = "projects_folder"


def preferences_file() -> Path:
    return Path.home() / ".urbansolarcarver" / "ui.json"


def _read_preferences() -> dict:
    """The stored preferences; empty when the file is missing, unreadable, or not a JSON object."""
    try:
        stored = json.loads(preferences_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return stored if isinstance(stored, dict) else {}


def read_projects_folder_preference() -> Path | None:
    """The projects folder the user chose, None when there is none or the file cannot be read."""
    stored_folder = _read_preferences().get(PROJECTS_FOLDER_KEY)
    if not isinstance(stored_folder, str) or not stored_folder.strip():
        return None
    return Path(stored_folder)


def write_projects_folder_preference(folder: Path) -> None:
    """Remember *folder* as the projects folder, keeping any other stored preference; creates *folder* as well.

    Raises OSError when the folder or the file cannot be written.
    """
    Path(folder).mkdir(parents=True, exist_ok=True)
    file_path = preferences_file()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    preferences = _read_preferences()
    preferences[PROJECTS_FOLDER_KEY] = str(folder)
    descriptor, temporary_name = tempfile.mkstemp(prefix="ui-", suffix=".json.tmp", dir=file_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            json.dump(preferences, temporary_file, indent=2)
        os.replace(temporary_name, file_path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
