"""The project-name rule and the error type of the project requests of the local web service.

Kept apart from ``projects.py`` so that ``project_removal.py`` and ``projects.py`` can both use them; ``projects.py`` re-exports them.
"""
from __future__ import annotations

import re

PROJECT_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,63}")
PROJECT_JSON_FILE_NAME = "project.json"
# Windows reserves these names for devices: a file or folder named so, with or without an extension, cannot be made there.
WINDOWS_DEVICE_NAME_PATTERN = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", re.IGNORECASE)


class ProjectError(Exception):
    """A project request that cannot be served; ``status_code`` is the HTTP status."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def check_not_a_windows_device_name(name: str) -> None:
    """Raise ProjectError(422) when the part of the name before its first '.' is a Windows device name (CON, NUL, COM1, ...)."""
    if WINDOWS_DEVICE_NAME_PATTERN.fullmatch(name.split(".")[0]) is not None:
        raise ProjectError(f"'{name}' is a Windows device name, which Windows does not allow for a file or folder: "
                           "choose another name.", status_code=422)


def validate_project_name(name: str) -> str:
    """Return the name without surrounding spaces, or raise ProjectError(422)."""
    stripped_name = name.strip(" ")
    if PROJECT_NAME_PATTERN.fullmatch(stripped_name) is None:
        raise ProjectError(
            "A project name has 1 to 64 characters: letters A-Z and a-z, digits, spaces, "
            "'-' and '_', starting with a letter or digit.",
            status_code=422,
        )
    check_not_a_windows_device_name(stripped_name)
    return stripped_name
