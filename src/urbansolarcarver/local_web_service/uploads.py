"""Checking an uploaded mesh file before the service keeps it (shared by the mesh roles and the test surfaces)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import trimesh

from ..errors import InputError
from ..io import load_mesh
from .project_names import ProjectError


def matching_stored_name(recorded_names, clean_name: str) -> str | None:
    """The recorded file name that *clean_name* is, letter case ignored (one name, one file on Windows); None for a new name."""
    return next((recorded for recorded in recorded_names if recorded.lower() == clean_name.lower()), None)


def checked_upload(folder: Path, clean_name: str, data: bytes, fix_normals: bool = True) -> tuple[Path, trimesh.Trimesh]:
    """Write an upload to a temporary file in *folder* and read it with the engine's loader: (that file, its mesh).

    The folder is made when it does not exist (a project made before the role existed has none). The caller moves the file into
    place or removes it. ProjectError(422), and no temporary file left, when the engine's loader refuses the file; its message
    names the file as the person knows it, *clean_name*.
    """
    folder.mkdir(parents=True, exist_ok=True)
    descriptor, upload_name = tempfile.mkstemp(dir=folder, prefix="upload", suffix=Path(clean_name).suffix.lower())
    upload_path = Path(upload_name)
    try:
        with os.fdopen(descriptor, "wb") as upload_file:
            upload_file.write(data)
        try:
            mesh = load_mesh(str(upload_path), fix_normals=fix_normals)
        except InputError as error:
            # the engine message names the temporary file; the person knows the file by its own name
            message = str(error).removeprefix("load_mesh: ")
            raise ProjectError(message.replace(repr(str(upload_path)), repr(clean_name)).replace(str(upload_path), clean_name),
                               status_code=422) from error
    except BaseException:
        upload_path.unlink(missing_ok=True)
        raise
    return upload_path, mesh
