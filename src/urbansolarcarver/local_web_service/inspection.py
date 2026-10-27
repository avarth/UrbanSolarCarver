"""The input mesh files seen by the Inspect workspace: a summary of each file and the geometry of the test surfaces.

A surface (a body, for the other roles) is the triangles joined by shared edges in the mesh ``load_mesh`` returns: with
``fix_normals`` for the maximum volume and the test surfaces, as stored for context and terrain (as ProjectStore reads them).
A test surface file whose mesh is closed as a whole cannot be flipped: ``load_mesh`` turns every closed body outward again.
Saving flips writes the file again in its own format, checks that ``load_mesh`` reads the written file as the turned mesh, and only
then puts it in place of the stored file; the file as it was is kept first, so Restore original can put it back.

Reading a file takes seconds for a large mesh, so a file is inspected once and the result is kept until its size or modification
time changes. A kept mesh is shared by every reader; whoever turns faces does it on a copy.
"""
from __future__ import annotations

import contextlib
import filecmp
import json
import os
import shutil
import struct
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

from ..errors import InputError
from ..io import load_mesh, save_mesh
from . import stored_files, test_surfaces
from .api_models import InspectedFile, InspectReply
from .project_names import ProjectError
from .projects import MESH_ROLES, OPTIONAL_MESH_ROLES, ProjectStore

ORIGINALS_FOLDER = test_surfaces.ORIGINALS_FOLDER
HEADER_ALIGNMENT_BYTES = 4      # the geometry header is padded so the arrays after it start aligned
FRAME_STEP_M = 1.0              # the frame of the geometry is the minimum corner of the bounds rounded down to this
KEPT_FILE_COUNT = 32            # inspected files kept, the least recently used leaving first
NORMAL_TOLERANCE = 1e-6         # how far a face normal of a saved file may be from the one expected
POSITION_TOLERANCE_M = 1e-6     # how far a corner of a saved file may be from the one written
OBJ_DECIMALS = 10              # the decimals of a written OBJ: georeferenced coordinates keep their millimetres and more


@dataclass(frozen=True)
class FileInspection:
    """The mesh of a stored file with what was worked out from it; the mesh and the arrays are shared, so not to be changed."""
    mesh: trimesh.Trimesh
    surface_of_face: np.ndarray     # int32 per face: its surface for a test surface file, zero for the other roles
    summary: InspectedFile          # original_kept is not known here: project_inspection sets it from the project folder


_kept: OrderedDict[tuple[str, int, int], FileInspection] = OrderedDict()
_kept_lock = threading.Lock()


def inspect_file(path: Path, role: str) -> FileInspection:
    """The inspection of the stored mesh file *path* of *role*, kept until the file changes; InputError when it cannot be read."""
    status = Path(path).stat()
    key = (str(path), status.st_size, status.st_mtime_ns)
    with _kept_lock:
        found = _kept.get(key)
        if found is not None:
            _kept.move_to_end(key)
            return found
    mesh = load_mesh(str(path), fix_normals=role not in OPTIONAL_MESH_ROLES)
    inspected = _inspect_mesh(mesh, Path(path).name, role)
    _keep(key, inspected)
    return inspected


def _keep(key: tuple[str, int, int], inspected: FileInspection) -> None:
    with _kept_lock:
        _kept[key] = inspected
        _kept.move_to_end(key)
        while len(_kept) > KEPT_FILE_COUNT:
            _kept.popitem(last=False)


def project_inspection(store: ProjectStore, name: str) -> InspectReply:
    """The summary of each mesh file of project *name*, by role (max volume, test surfaces, context, terrain) then file name.

    A recorded file that is not in the folder any more is left out (the stage status reports it as missing). A file that cannot be
    read is listed with its ``problem`` and zero counts, the others as usual. ProjectError 404 for an unknown project."""
    project_folder = store.open(name)
    with store.project_lock(name):
        file_names = {role: sorted(store.read_project_json(name).input_files.get(role, {})) for role in MESH_ROLES}
    files = []
    for role in MESH_ROLES:
        for file_name in file_names[role]:
            path = store._stored_file_path(project_folder, role, file_name)
            if not path.is_file():
                continue
            try:
                summary = inspect_file(path, role).summary
            except (InputError, OSError) as error:
                files.append(_unreadable_summary(role, file_name, error))
                continue
            if role == test_surfaces.ROLE:
                summary = _with_original_kept(summary, project_folder)
            files.append(summary)
    return InspectReply(files=files)


def save_turned_surfaces(store: ProjectStore, name: str, file_name: str, surfaces: list[int]) -> InspectedFile:
    """Turn the surfaces numbered *surfaces* of the stored test surface file *file_name* the other way and save the file.

    The file is written again in its own format with those surfaces turned (a surface is turned as a whole), read back with
    ``load_mesh``, and replaces the stored file only when it reads as the same triangles with the turned surfaces' normals
    negated and the others' unchanged, and at the same places (to 1e-6 m). Before the first save the stored file is copied to
    ``inputs/originals/test_surfaces/`` and stays there until Restore original, an upload that replaces the file, or the file's
    removal. The save has the effects of an upload (stored_files.build_in_test_surface_file): the joined files of the criteria and
    studies that list the file are built again and the criteria and studies go out of date by them; there is no changed-file
    notice and inputs_revision does not change. Returns the file's summary.

    ProjectError: 404 for a file that is not stored, 422 for a file that cannot be read, that is closed as a whole, or for no
    surface or one that does not exist, 500 when the written file does not read as turned (nothing is saved then). The caller
    refuses it during a run.
    """
    with store.project_lock(name):
        project_folder = store.open(name)
        path = store.input_file_path(name, test_surfaces.ROLE, file_name)
        inspected = _inspect_or_refuse(path, test_surfaces.ROLE)
        if not inspected.summary.flippable:
            raise ProjectError("This file is closed as a whole, and the loader always turns its bodies outward, so its surfaces cannot be flipped.",
                               status_code=422)
        surface_count = int(inspected.summary.surface_count)
        turned_surfaces = sorted(set(surfaces))
        if not turned_surfaces or turned_surfaces[0] < 0 or turned_surfaces[-1] >= surface_count:
            raise ProjectError(f"Name at least one surface of the file, numbered from 0 to {surface_count - 1}; got {surfaces}.", status_code=422)
        mesh = inspected.mesh
        is_turned = np.isin(inspected.surface_of_face, turned_surfaces)
        faces = mesh.faces.copy()       # the mesh is shared: the turned one is a mesh of its own
        faces[is_turned] = faces[is_turned][:, ::-1]
        turned_mesh = trimesh.Trimesh(vertices=mesh.vertices.copy(), faces=faces, process=False)
        expected_normals = np.where(is_turned[:, None], -mesh.face_normals, mesh.face_normals)
        temporary_path = _temporary_path_beside(path)
        try:
            written = _write_turned_file(turned_mesh, temporary_path, file_name, inspected, expected_normals)
            original_path = test_surfaces.original_path(project_folder, file_name)
            original_is_new = not original_path.is_file()
            if original_is_new:
                _copy_atomically(path, original_path)
            try:
                _put_in_place(store, name, project_folder, file_name, temporary_path)
            except BaseException:
                # The new original is the only copy of the file as it was when the stored file did not come back: then it stays.
                if original_is_new and _same_content(path, original_path):
                    original_path.unlink(missing_ok=True)
                raise
        finally:
            temporary_path.unlink(missing_ok=True)
        status = path.stat()
        _keep((str(path), status.st_size, status.st_mtime_ns), written)      # the file just checked is what is stored now
        return _summary_of_stored_file(store, name, project_folder, file_name)


def restore_original(store: ProjectStore, name: str, file_name: str) -> InspectedFile:
    """Put the original kept before the first saved flip of the test surface file *file_name* back in place of the stored file.

    It has the effects of a save (save_turned_surfaces), and the kept original is removed. ProjectError 404 for a file that is not
    stored or has no kept original. The caller refuses it during a run."""
    with store.project_lock(name):
        project_folder = store.open(name)
        path = store.input_file_path(name, test_surfaces.ROLE, file_name)
        original_path = test_surfaces.original_path(project_folder, file_name)
        if not original_path.is_file():
            raise ProjectError(f"No original is kept for the {test_surfaces.ROLE} file '{file_name}'.", status_code=404)
        temporary_path = _temporary_path_beside(path)
        try:
            shutil.copy2(original_path, temporary_path)
            _put_in_place(store, name, project_folder, file_name, temporary_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        original_path.unlink(missing_ok=True)
        return _summary_of_stored_file(store, name, project_folder, file_name)


def inspection_geometry(store: ProjectStore, name: str, file_name: str) -> bytes:
    """The triangles of the test surface file *file_name* with the surface of each, all numbers little-endian:

    * ``uint32`` length n of the header in bytes;
    * the header as UTF-8 JSON, padded with spaces to a multiple of 4: ``frame`` (world coordinates the corners and centres are
      relative to), ``triangle_count``, ``surface_count`` and ``surfaces`` (per surface its ``centre``, unit ``normal`` and ``area``);
    * ``float32`` the three corners of each triangle, x y z each, relative to ``frame``;
    * ``uint32`` the surface number of each triangle.

    ProjectError 404 for a file that is not a recorded test surface file or not in the folder, 422 when it cannot be read.
    """
    path = store.input_file_path(name, test_surfaces.ROLE, file_name)
    if not path.is_file():
        raise ProjectError(f"There is no {test_surfaces.ROLE} file named '{file_name}'.", status_code=404)
    inspected = _inspect_or_refuse(path, test_surfaces.ROLE)
    mesh = inspected.mesh
    surface_numbers = inspected.surface_of_face
    frame = np.floor(mesh.bounds[0] / FRAME_STEP_M) * FRAME_STEP_M
    corners = (mesh.vertices[mesh.faces] - frame).astype("<f4")
    areas = mesh.area_faces
    surface_count = int(inspected.summary.surface_count)
    area = np.bincount(surface_numbers, weights=areas, minlength=surface_count)
    centre = np.stack([np.bincount(surface_numbers, weights=mesh.triangles_center[:, axis] * areas, minlength=surface_count)
                       for axis in range(3)], axis=1) / np.maximum(area, np.finfo(float).tiny)[:, None]
    normal = np.stack([np.bincount(surface_numbers, weights=mesh.face_normals[:, axis] * areas, minlength=surface_count)
                       for axis in range(3)], axis=1)
    length = np.linalg.norm(normal, axis=1)
    normal = np.where(length[:, None] > 0, normal / np.maximum(length, np.finfo(float).tiny)[:, None], [0.0, 0.0, 1.0])
    header = {"frame": frame.tolist(), "triangle_count": int(len(mesh.faces)), "surface_count": surface_count,
              "surfaces": [{"centre": (centre[number] - frame).tolist(), "normal": normal[number].tolist(), "area": float(area[number])}
                           for number in range(surface_count)]}
    header_bytes = json.dumps(header).encode("utf-8")
    header_bytes += b" " * (-len(header_bytes) % HEADER_ALIGNMENT_BYTES)
    return b"".join([struct.pack("<I", len(header_bytes)), header_bytes, corners.tobytes(), surface_numbers.astype("<u4").tobytes()])


def _with_original_kept(summary: InspectedFile, project_folder: Path) -> InspectedFile:
    return summary.model_copy(update={"original_kept": test_surfaces.original_path(project_folder, summary.file_name).is_file()})


def _summary_of_stored_file(store: ProjectStore, name: str, project_folder: Path, file_name: str) -> InspectedFile:
    path = store.input_file_path(name, test_surfaces.ROLE, file_name)
    return _with_original_kept(_inspect_or_refuse(path, test_surfaces.ROLE).summary, project_folder)


def _temporary_path_beside(path: Path) -> Path:
    """A new empty file next to *path* with its extension (the format of a file follows it), for the caller to write and remove."""
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.stem}-", suffix=f".tmp{path.suffix}")
    os.close(descriptor)
    return Path(temporary_name)


def _copy_atomically(source: Path, target: Path) -> None:
    """Copy *source* to *target* (in a folder made if needed) so that *target* is there whole or not at all."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=target.parent, prefix=f"{target.stem}-", suffix=".tmp")
    os.close(descriptor)
    try:
        shutil.copy2(source, temporary_name)
        os.replace(temporary_name, target)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _write_mesh_in_its_format(mesh: trimesh.Trimesh, path: Path) -> None:
    """Write *mesh* to *path* in the format its extension names, with the precision of the coordinates kept.

    The vertices are as ``load_mesh`` returned them. Vertices at one position that the loader kept apart (panels that meet along
    an edge, told apart by their normals) have to stay apart, and vertices it merged have to stay merged: the loader merges on
    position and, when the file has them, vertex normals, so an OBJ or PLY is written with the vertex normals of the mesh, which are
    equal on a merged vertex and differ between panels that meet at an angle. PLY is float64 (test_surfaces.write_joined_ply), OBJ
    has OBJ_DECIMALS decimals, GLB keeps georeferenced coordinates through io.save_mesh, and STL is float32 as it always is.
    """
    extension = path.suffix.lower()
    if extension == ".ply":
        test_surfaces.write_joined_ply([mesh], path)
    elif extension == ".obj":
        path.write_text(trimesh.exchange.obj.export_obj(mesh, include_normals=True, digits=OBJ_DECIMALS), encoding="utf-8")
    elif extension == ".glb":
        save_mesh(mesh, str(path))
    else:
        mesh.export(str(path), file_type=extension.lstrip("."))


def _write_turned_file(turned_mesh: trimesh.Trimesh, temporary_path: Path, file_name: str, before: FileInspection,
                       expected_normals: np.ndarray) -> FileInspection:
    """Write *turned_mesh* to *temporary_path* and check that ``load_mesh`` reads it as the triangles of *before*, with the
    expected face normals and the same corners; the inspection of what was read, named *file_name*.

    ProjectError 500 when the file cannot be written, or reads as other triangles, normals or corners."""
    try:
        _write_mesh_in_its_format(turned_mesh, temporary_path)
    except Exception as error:      # the exporters fail with many kinds of error
        raise ProjectError(f"The turned file could not be written: {error}", status_code=500) from error
    refusal = ProjectError("The turned file did not load as turned, so nothing was saved.", status_code=500)
    try:
        reloaded = load_mesh(str(temporary_path))
    except InputError as error:
        raise refusal from error
    if len(reloaded.faces) != len(before.mesh.faces):
        raise refusal
    if not np.all(np.abs(reloaded.face_normals - expected_normals) <= NORMAL_TOLERANCE):
        raise refusal
    if np.abs(reloaded.vertices[reloaded.faces] - turned_mesh.vertices[turned_mesh.faces]).max() > POSITION_TOLERANCE_M:
        raise refusal
    # The surfaces may differ from the ones before: two panels that were told apart only by facing opposite ways join into one
    # surface once one is turned, and that is a turn that holds.
    return _inspect_mesh(reloaded, file_name, test_surfaces.ROLE)


def _put_in_place(store: ProjectStore, name: str, project_folder: Path, file_name: str, new_path: Path) -> None:
    """Replace the stored test surface file *file_name* by the file *new_path* (moved), build it into the joined files and write
    project.json. If any of that fails the stored file is the one it was, the joined files are built from it again as far as that
    can be done, and the error is raised."""
    stored_path = test_surfaces.stored_path(project_folder, file_name)
    backup_path = _temporary_path_beside(stored_path)
    replaced = False
    backup_is_needed = False
    try:
        shutil.copy2(stored_path, backup_path)
        project_json = store.read_project_json(name)
        try:
            os.replace(new_path, stored_path)
            replaced = True
            stored_files.build_in_test_surface_file(project_folder, project_json, file_name)
            store.write_project_json(name, project_json)
        except BaseException:
            if replaced:
                backup_is_needed = True         # until the stored file is known to be back
                os.replace(backup_path, stored_path)
                backup_is_needed = False
                with contextlib.suppress(Exception):        # the joined files follow the stored file again, if they can
                    stored_files.build_in_test_surface_file(project_folder, store.read_project_json(name), file_name)
            raise
    finally:
        if not backup_is_needed:
            backup_path.unlink(missing_ok=True)


def _same_content(first: Path, second: Path) -> bool:
    try:
        return filecmp.cmp(first, second, shallow=False)
    except OSError:
        return False


def _inspect_or_refuse(path: Path, role: str) -> FileInspection:
    try:
        return inspect_file(path, role)
    except (InputError, OSError) as error:
        raise ProjectError(f"The {role} file '{path.name}' cannot be read: {_reason(error)}", status_code=422) from error


def _reason(error: Exception) -> str:
    return str(error).removeprefix("load_mesh: ")


def _unreadable_summary(role: str, file_name: str, error: Exception) -> InspectedFile:
    """The entry of a file that cannot be read: its problem and nothing counted."""
    return InspectedFile(role=role, file_name=file_name, triangle_count=0, area_m2=0.0, bounds=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                         body_count=0, closed_body_count=0, problem=_reason(error))


def _inspect_mesh(mesh: trimesh.Trimesh, file_name: str, role: str) -> FileInspection:
    face_count = len(mesh.faces)
    labels = trimesh.graph.connected_component_labels(mesh.face_adjacency, node_count=face_count)
    _, first_face, numbers = np.unique(labels, return_index=True, return_inverse=True)
    numbers = np.argsort(np.argsort(first_face))[numbers].astype(np.int32)     # numbered in the order of their first triangle
    body_count = int(numbers.max()) + 1
    closed_body_count = body_count - len(_open_bodies(mesh, numbers))
    is_test_surface = role == test_surfaces.ROLE
    surface_of_face = numbers if is_test_surface else np.zeros(face_count, dtype=np.int32)
    surface_of_face.flags.writeable = False
    summary = InspectedFile(
        role=role, file_name=file_name, triangle_count=int(face_count), area_m2=float(mesh.area), bounds=mesh.bounds.tolist(),
        body_count=body_count, closed_body_count=closed_body_count, surface_count=body_count if is_test_surface else None,
        flippable=is_test_surface and not mesh.is_watertight, original_kept=False)
    return FileInspection(mesh=mesh, surface_of_face=surface_of_face, summary=summary)


def _open_bodies(mesh: trimesh.Trimesh, body_of_face: np.ndarray) -> np.ndarray:
    """The numbers of the bodies that have an edge which is not shared by exactly two of the body's own faces running opposite
    ways (as ``Trimesh.is_watertight`` takes it for the body alone). Two closed bodies that touch along an edge are both closed."""
    edges = mesh.edges                                  # directed, three per face
    unique_of_edge = mesh.edges_unique_inverse
    edge_count = int(unique_of_edge.max()) + 1
    body_of_edge = body_of_face[np.arange(len(edges)) // 3].astype(np.int64)
    edge_in_body, group_of_edge = np.unique(body_of_edge * edge_count + unique_of_edge, return_inverse=True)
    direction = np.where(edges[:, 0] < edges[:, 1], 1.0, -1.0)
    faces_per_group = np.bincount(group_of_edge)
    unbalanced = np.bincount(group_of_edge, weights=direction) != 0
    return np.unique(edge_in_body[(faces_per_group != 2) | unbalanced] // edge_count)
