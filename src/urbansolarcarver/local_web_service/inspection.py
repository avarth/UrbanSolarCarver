"""The input mesh files seen by the Inspect workspace: a summary of each file and the geometry of the test surfaces.

A surface (a body, for the other roles) is the triangles joined by shared edges in the mesh ``load_mesh`` returns: with
``fix_normals`` for the maximum volume and the test surfaces, as stored for context and terrain (as ProjectStore reads them).
A test surface file whose mesh is closed as a whole cannot be flipped: ``load_mesh`` turns every closed body outward again.

Reading a file takes seconds for a large mesh, so a file is inspected once and the result is kept until its size or modification
time changes. A kept mesh is shared by every reader; whoever turns faces does it on a copy.
"""
from __future__ import annotations

import json
import struct
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

from ..errors import InputError
from ..io import load_mesh
from . import test_surfaces
from .api_models import InspectedFile, InspectReply
from .project_names import ProjectError
from .projects import INPUTS_FOLDER, MESH_ROLES, OPTIONAL_MESH_ROLES, ProjectStore

# Where the original of a test surface file is kept from its first flip until it is restored (the file name is kept as stored).
ORIGINALS_FOLDER = f"{INPUTS_FOLDER}/originals/{test_surfaces.ROLE}"
HEADER_ALIGNMENT_BYTES = 4      # the geometry header is padded so the arrays after it start aligned
FRAME_STEP_M = 1.0              # the frame of the geometry is the minimum corner of the bounds rounded down to this
KEPT_FILE_COUNT = 32            # inspected files kept, the least recently used leaving first


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
    with _kept_lock:
        _kept[key] = inspected
        _kept.move_to_end(key)
        while len(_kept) > KEPT_FILE_COUNT:
            _kept.popitem(last=False)
    return inspected


def project_inspection(store: ProjectStore, name: str) -> InspectReply:
    """The summary of each mesh file of project *name*, by role (max volume, test surfaces, context, terrain) then file name.

    A recorded file that is not in the folder any more is left out (the stage status reports it as missing). ProjectError 422
    for a file that cannot be read; 404 for an unknown project."""
    project_folder = store.open(name)
    with store.project_lock(name):
        file_names = {role: sorted(store.read_project_json(name).input_files.get(role, {})) for role in MESH_ROLES}
    files = []
    for role in MESH_ROLES:
        for file_name in file_names[role]:
            path = store._stored_file_path(project_folder, role, file_name)
            if not path.is_file():
                continue
            summary = _inspect_or_refuse(path, role).summary
            if role == test_surfaces.ROLE:
                summary = summary.model_copy(update={"original_kept": (project_folder / ORIGINALS_FOLDER / file_name).is_file()})
            files.append(summary)
    return InspectReply(files=files)


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


def _inspect_or_refuse(path: Path, role: str) -> FileInspection:
    try:
        return inspect_file(path, role)
    except (InputError, OSError) as error:
        raise ProjectError(f"The {role} file '{path.name}' cannot be read: {str(error).removeprefix('load_mesh: ')}", status_code=422) from error


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
    """The numbers of the bodies that have an edge which is not shared by exactly two faces running opposite ways (as
    ``Trimesh.is_watertight`` takes it, for each body)."""
    edges = mesh.edges                                  # directed, three per face
    unique_of_edge = mesh.edges_unique_inverse
    faces_per_edge = np.bincount(unique_of_edge)
    direction = np.where(edges[:, 0] < edges[:, 1], 1.0, -1.0)
    unbalanced = np.bincount(unique_of_edge, weights=direction) != 0
    open_edge = (faces_per_edge != 2) | unbalanced
    body_of_edge = np.zeros(len(faces_per_edge), dtype=np.int64)
    body_of_edge[unique_of_edge] = body_of_face[np.arange(len(edges)) // 3]
    return np.unique(body_of_edge[open_edge])
