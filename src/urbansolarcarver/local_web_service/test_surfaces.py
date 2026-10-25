"""Test surface files of a project: stored once, protected per criterion, one joined file per criterion.

The files are kept in ``inputs/test_surfaces/`` named as uploaded; project.json's ``input_files["test_surfaces"]`` records each
with its triangle count, and every criterion lists the file names it protects (``CriterionEntry.test_surface_files``). The engine
reads one joined file per criterion, ``inputs/joined/test_surfaces_<id>.ply``, built from that list. Its fingerprint tells a
stage that a criterion's test surfaces changed. This module holds the file work; ProjectStore does the project.json changes
under the project lock.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import numpy as np
import trimesh

from ..errors import InputError
from ..io import load_mesh
from .api_models import CriterionEntry
from .criteria import default_criterion_name, joined_test_surfaces_path
from .project_names import ProjectError

ROLE = "test_surfaces"
STORED_FOLDER = "inputs/test_surfaces"
JOINED_FOLDER = "inputs/joined"


def content_digest(path: Path) -> str:
    """The sha256 of the bytes of a file, as hex."""
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def joined_path(project_folder: Path, criterion_id: str) -> Path:
    """The joined test surface file of a criterion (it may not exist: a criterion without test surfaces has none)."""
    return Path(project_folder) / joined_test_surfaces_path(criterion_id)


def fingerprint(project_folder: Path, criterion_id: str) -> str | None:
    """The content digest of a criterion's joined test surface file, None when it has none."""
    path = joined_path(project_folder, criterion_id)
    return content_digest(path) if path.is_file() else None


def stored_path(project_folder: Path, file_name: str) -> Path:
    """Where a stored test surface file is."""
    return Path(project_folder) / STORED_FOLDER / file_name


def criteria_using(criteria: list[CriterionEntry], file_name: str) -> list[CriterionEntry]:
    """The criteria that list this stored file."""
    return [criterion for criterion in criteria if file_name in criterion.test_surface_files]


def follow_default_name(entry: CriterionEntry) -> bool:
    """Name a criterion the user did not name after its mode and first test surface file; whether the name changed."""
    if entry.named_by_user:
        return False
    default_name = default_criterion_name(entry.settings.get("mode"), entry.test_surface_files)
    changed = default_name != entry.name
    entry.name = default_name
    return changed


def write_joined_ply(meshes: list[trimesh.Trimesh], path: Path) -> None:
    """Write the meshes, concatenated, as one binary PLY with float64 positions and the vertex normals of each mesh.

    The engine reads test surfaces with load_mesh, which merges coincident vertices only when their normals are
    equal too (trimesh merges on position and, when the file has them, vertex normals). Test surface files keep
    panels that share corners apart that way, and each panel is one connected component for the sampling. The
    normals of a mesh as load_mesh returned it are those of its faces, so a vertex of one flat panel carries the
    panel's normal, and panels that met at a corner in the uploaded file stay apart in the joined file. Without
    normals they would merge into one component, which the sampling skips as degenerate or non-planar. Positions
    are float64, as save_mesh writes georeferenced coordinates.
    """
    vertex_offsets = np.cumsum([0] + [len(mesh.vertices) for mesh in meshes[:-1]])
    vertex_rows = np.empty(sum(len(mesh.vertices) for mesh in meshes), dtype=[("position", "<f8", (3,)), ("normal", "<f4", (3,))])
    vertex_rows["position"] = np.vstack([mesh.vertices for mesh in meshes])
    vertex_rows["normal"] = np.vstack([mesh.vertex_normals for mesh in meshes])
    face_rows = np.empty(sum(len(mesh.faces) for mesh in meshes), dtype=[("count", "u1"), ("vertex_indices", "<i4", (3,))])
    face_rows["count"] = 3
    face_rows["vertex_indices"] = np.vstack([mesh.faces + offset for mesh, offset in zip(meshes, vertex_offsets)])
    header = ("ply\nformat binary_little_endian 1.0\n"
              f"element vertex {len(vertex_rows)}\n"
              "property double x\nproperty double y\nproperty double z\n"
              "property float nx\nproperty float ny\nproperty float nz\n"
              f"element face {len(face_rows)}\n"
              "property list uchar int vertex_indices\nend_header\n")
    with open(path, "wb") as ply_file:
        ply_file.write(header.encode("ascii"))
        ply_file.write(vertex_rows.tobytes())
        ply_file.write(face_rows.tobytes())


def has_vertex_normals(path: Path) -> bool:
    """Whether the header of a PLY file declares the vertex property nx (a PLY header is ASCII in every format)."""
    with open(path, "rb") as ply_file:
        for line in ply_file:
            words = line.split()
            if words == [b"end_header"]:
                return False
            if words[:1] == [b"property"] and words[-1:] == [b"nx"]:
                return True
    return False


def load_stored_meshes(project_folder: Path, file_names: list[str]) -> dict[str, trimesh.Trimesh]:
    """The meshes of stored files by file name, in name order, or ProjectError(422) when one cannot be read."""
    meshes = {}
    for file_name in sorted(file_names):
        try:
            meshes[file_name] = load_mesh(str(stored_path(project_folder, file_name)))
        except InputError as error:
            raise ProjectError(f"The {ROLE} file '{file_name}' cannot be read, so the joined file was not rebuilt: {error}",
                               status_code=422) from error
    return meshes


def build_joined_files(project_folder: Path, file_names_by_criterion: dict[str, list[str]],
                       new_meshes: dict[str, trimesh.Trimesh] | None = None) -> dict[str, Path | None]:
    """Write the joined file of each criterion (id -> its file names) into a new temporary file; the paths by id.

    The meshes are joined in file name order; a name in *new_meshes* is taken from there (a file not stored yet, or about to
    be replaced), any other is read from the stored file once however many criteria use it. A criterion without files gets
    None: its joined file is to be removed. Nothing in the project changes; on an error the temporary files are removed.
    """
    meshes_by_name = dict(new_meshes or {})
    stored_names = {name for names in file_names_by_criterion.values() for name in names if name not in meshes_by_name}
    meshes_by_name.update(load_stored_meshes(project_folder, list(stored_names)))
    temporary_paths: dict[str, Path | None] = {}
    try:
        for criterion_id, file_names in file_names_by_criterion.items():
            temporary_paths[criterion_id] = _write_temporary_joined_file(
                project_folder, criterion_id, [meshes_by_name[file_name] for file_name in sorted(file_names)])
    except BaseException:
        remove_temporary_files(temporary_paths)
        raise
    return temporary_paths


def _write_temporary_joined_file(project_folder: Path, criterion_id: str, meshes: list[trimesh.Trimesh]) -> Path | None:
    """The joined meshes of a criterion in a temporary file with a unique name (concurrent builds never share one); None for none."""
    if not meshes:
        return None
    joined_folder = Path(project_folder) / JOINED_FOLDER
    joined_folder.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=joined_folder, prefix=f"test_surfaces_{criterion_id}-", suffix=".tmp.ply")
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        write_joined_ply(meshes, temporary_path)
    except Exception as error:
        temporary_path.unlink(missing_ok=True)
        raise ProjectError(f"The joined {ROLE} file could not be built: {error}", status_code=500) from error
    return temporary_path


def install_joined_files(project_folder: Path, temporary_paths: dict[str, Path | None]) -> None:
    """Move each built joined file into place, or remove the joined file of a criterion that has no file left (None)."""
    for criterion_id, temporary_path in temporary_paths.items():
        if temporary_path is None:
            joined_path(project_folder, criterion_id).unlink(missing_ok=True)
        else:
            os.replace(temporary_path, joined_path(project_folder, criterion_id))


def remove_temporary_files(temporary_paths: dict[str, Path | None]) -> None:
    """Remove the temporary joined files that are still there (those moved into place are not)."""
    for temporary_path in temporary_paths.values():
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def accept_upload(project_folder: Path, recorded_names: dict[str, int], clean_name: str,
                  data: bytes) -> tuple[str, Path | None, trimesh.Trimesh | None]:
    """Check an uploaded test surface file and say which stored file it is: (stored name, checked upload, its mesh).

    An upload that has the name of a stored file (letter case ignored, one name one file on Windows) is that file: the same
    content changes nothing, other content replaces it. Otherwise an upload with the content of another stored file is that
    file, stored under its name. Anything else is new. For a file already stored with this content the upload and mesh are None;
    otherwise the upload is a temporary file in the store's folder, for the caller to move into place or remove, and the mesh is
    what the engine's loader makes of it. ProjectError(422), and no temporary file, when the engine's loader refuses it.
    """
    folder = Path(project_folder) / STORED_FOLDER
    folder.mkdir(parents=True, exist_ok=True)       # a project made before the role existed has no folder for it
    same_name = next((recorded for recorded in recorded_names if recorded.lower() == clean_name.lower()), None)
    digest = hashlib.sha256(data).hexdigest()
    candidates = [same_name] if same_name is not None else list(recorded_names)
    for candidate in candidates:
        path = stored_path(project_folder, candidate)
        if path.is_file() and path.stat().st_size == len(data) and content_digest(path) == digest:
            return candidate, None, None
    descriptor, upload_name = tempfile.mkstemp(dir=folder, prefix="upload", suffix=Path(clean_name).suffix.lower())
    upload_path = Path(upload_name)
    try:
        with os.fdopen(descriptor, "wb") as upload_file:
            upload_file.write(data)
        try:
            mesh = load_mesh(str(upload_path))
        except InputError as error:
            # the engine message names the temporary file; the person knows the file by its own name
            message = str(error).removeprefix("load_mesh: ")
            raise ProjectError(message.replace(repr(str(upload_path)), repr(clean_name)).replace(str(upload_path), clean_name),
                               status_code=422) from error
    except BaseException:
        upload_path.unlink(missing_ok=True)
        raise
    return same_name or clean_name, upload_path, mesh
