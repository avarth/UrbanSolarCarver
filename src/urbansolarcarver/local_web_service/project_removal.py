"""The guardrails for removing a project folder, and the move to the recycle bin.

Deleting or resetting a project must never remove anything but that one project folder (spec R2 7.3). A folder is
removed only when the checks below pass, and then it is moved to the recycle bin (Windows) or trash (macOS, Linux)
with the ``send2trash`` package, not deleted for good, so a mistake can be undone. The check that no run of the
project is active belongs to the caller, which holds the project lock. A file a project no longer needs (a test surface
file no criterion uses) goes the same way (discard_file).
"""
from __future__ import annotations

import ctypes
import ntpath
import os
import shutil
import stat
import sys
from pathlib import Path

import send2trash
from pydantic import ValidationError

from .api_models import ProjectJson
from .project_names import PROJECT_JSON_FILE_NAME, ProjectError, validate_project_name


DRIVE_FIXED = 3     # the GetDriveTypeW result of a volume that has a recycle bin; every other kind (removable, network, CD, RAM disk) has none


class ProjectRemovalRefused(ProjectError):
    """A project folder that must not be removed, or that could not be moved to the recycle bin; the status is 422."""

    def __init__(self, message: str):
        super().__init__(message, status_code=422)


def _is_link(path: Path | str) -> bool:
    """Whether *path* is a symbolic link or, on Windows, any reparse point (a junction, a mount point, ...), not followed."""
    if os.path.islink(path):
        return True
    # Every reparse point is refused, not only the junction and symlink kinds: a reparse point may lead outside the project.
    # OneDrive placeholders do not show the attribute through os.lstat since Python 3.8, so they are not refused by it.
    return bool(getattr(os.lstat(path), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _windows_volume_root(path: str) -> str:
    """The root of the volume *path* is on: a drive letter's root, or the folder a volume is mounted at."""
    buffer = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetVolumePathNameW(path, buffer, len(buffer)):
        raise ctypes.WinError()
    return buffer.value


def _windows_drive_type(volume_root: str) -> int:
    return ctypes.windll.kernel32.GetDriveTypeW(volume_root)


def _check_folder_has_a_recycle_bin(project_folder: Path) -> None:
    """On Windows, raise ProjectRemovalRefused unless the folder is on a fixed volume.

    send2trash asks the shell to recycle the folder without a confirmation, and the shell then deletes for good what it
    cannot recycle, which is everything on a network share or a USB stick. UNC paths count as network. The volume is
    found with GetVolumePathNameW, so a removable or network volume mounted into a folder of a fixed drive is seen as what it is.
    """
    if sys.platform != "win32":
        return
    try:
        on_a_fixed_volume = not ntpath.splitdrive(str(project_folder))[0].startswith("\\\\") and (
            _windows_drive_type(_windows_volume_root(str(project_folder))) == DRIVE_FIXED)
    except OSError:
        on_a_fixed_volume = False   # a volume that cannot be asked about is not trusted to have a recycle bin
    if not on_a_fixed_volume:
        raise ProjectRemovalRefused(
            f"The folder {project_folder} is not on a fixed disk of this computer (it is on a network, removable or other drive), which has "
            "no recycle bin, so UrbanSolarCarver leaves it in place instead of deleting it for good. You can delete it in the file manager.")


def _check_nothing_is_a_link(project_folder: Path) -> None:
    """Raise ProjectRemovalRefused for the first link at or below *project_folder*; links are never followed.

    ``os.walk`` goes into a folder only when the caller asks for the next entry, so a link to a folder is refused
    here before the walk could enter it.
    """
    try:
        if _is_link(project_folder):
            raise ProjectRemovalRefused(f"The project folder {project_folder} is a link to another place, so it is left as it is.")
        for current_folder, folder_names, file_names in os.walk(project_folder, onerror=_raise_unreadable_folder):
            for entry_name in (*folder_names, *file_names):
                if _is_link(os.path.join(current_folder, entry_name)):
                    raise ProjectRemovalRefused(
                        f"{os.path.join(current_folder, entry_name)} is a link to another place, which a project folder must not contain: "
                        "the project is left as it is. Remove the link first if you want to remove the project.")
    except OSError as error:
        raise ProjectRemovalRefused(f"The project folder {project_folder} cannot be checked for links ({error}), so it is left as it is.") from error


def _raise_unreadable_folder(error: OSError) -> None:
    raise error


def check_project_folder_can_be_removed(projects_folder: Path, name: str) -> Path:
    """The resolved folder of project *name* when it may be removed; ProjectError otherwise (404 when there is none, 422 when refused).

    Checks: the name passes the project-name rule; the folder is a direct child of the projects folder after resolving
    every link, and not the projects folder itself; it holds a project.json that reads as a project of that name; neither
    it nor anything inside it is a symbolic link or a junction; on Windows the folder is not on a network or removable drive.
    """
    project_name = validate_project_name(name)
    real_projects_folder = Path(projects_folder).resolve()
    project_folder = (Path(projects_folder) / project_name).resolve()
    if project_folder.parent != real_projects_folder or project_folder == real_projects_folder:
        raise ProjectRemovalRefused(f"'{project_name}' is not a folder directly inside the projects folder, so it is left as it is.")
    if not project_folder.is_dir():
        raise ProjectError(f"There is no project named '{project_name}'.", status_code=404)
    try:
        project_json = ProjectJson.model_validate_json((project_folder / PROJECT_JSON_FILE_NAME).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProjectRemovalRefused(f"'{project_name}' has no {PROJECT_JSON_FILE_NAME}, so it is not a project of this app and is left as it is.") from None
    except (ValidationError, OSError, UnicodeDecodeError) as error:
        raise ProjectRemovalRefused(f"{PROJECT_JSON_FILE_NAME} of '{project_name}' cannot be read as a project ({error}), so it is left as it is.") from error
    if project_json.name != project_folder.name:
        raise ProjectRemovalRefused(
            f"{PROJECT_JSON_FILE_NAME} in the folder '{project_folder.name}' names the project '{project_json.name}', so it is left as it is.")
    _check_folder_has_a_recycle_bin(project_folder)
    _check_nothing_is_a_link(Path(projects_folder) / project_name)
    return project_folder


def discard_file(path: Path) -> None:
    """Move a file to the recycle bin or trash, or delete it on a drive that has none (where a project folder would be left in
    place, see _check_folder_has_a_recycle_bin); nothing for a file that is not there. OSError when neither works (the file
    then stays)."""
    if not path.is_file():
        return
    try:
        _check_folder_has_a_recycle_bin(path.parent)
    except ProjectRemovalRefused:
        path.unlink()
        return
    send2trash.send2trash(str(path))


def discard_folder(path: Path) -> None:
    """Move a folder to the recycle bin or trash, or delete it on a drive that has none, as discard_file does for a file; nothing
    for a folder that is not there. OSError when neither works (the folder then stays)."""
    if not path.is_dir():
        return
    try:
        _check_folder_has_a_recycle_bin(path.parent)
    except ProjectRemovalRefused:
        shutil.rmtree(path)
        return
    send2trash.send2trash(str(path))


def move_to_recycle_bin(folder: Path) -> None:
    """Move *folder* to the recycle bin or trash; ProjectRemovalRefused, with the reason, when that fails (the folder then stays)."""
    try:
        send2trash.send2trash(str(folder))
    except OSError as error:        # send2trash's TrashPermissionError is an OSError
        raise ProjectRemovalRefused(f"The folder {folder} could not be moved to the recycle bin: {error}") from error
