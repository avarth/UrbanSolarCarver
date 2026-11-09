"""Test surfaces picked on the existing surroundings, and the names of surface sets (design/test-surfaces-on-context.md).

A **surface set** is a stored test surface file (inputs/test_surfaces/), as before; project.json's ``surface_sets`` gives it a name to
show (none: the file name without its extension) and, for a set picked in the view, its **picks**: the point clicked on the
surroundings and the direction of the click's ray, in the input files' coordinates.

A pick stands for the **flat piece** under the point: the triangle of the joined surroundings closest to it (within PICK_DISTANCE) and
the triangles reached from it across shared edges whose normal is within FLAT_ANGLE of its own and whose corners lie within
FLAT_DISTANCE of its plane. The piece is turned to face the side it was clicked from (its normal against the ray), whatever the file's
winding: the joined surroundings keep their faces as stored. A set's file is built from its picks again whenever the surroundings
change; a pick that finds no face any more is counted (``picks_lost``) and said in the set's row.
"""
from __future__ import annotations

import os
import tempfile
from collections import deque
from pathlib import Path

import numpy as np
import trimesh

from ..io import save_mesh
from .api_models import ProjectJson, SurfacePick, SurfaceSetJson
from .project_names import ProjectError

FLAT_ANGLE_DEG = 1.0            # the normals of one flat piece differ by no more than this
FLAT_DISTANCE_M = 0.01          # and its corners lie this close to the clicked triangle's plane
PICK_DISTANCE_M = 0.05          # a pick finds the triangle within this of its point
PICKED_PREFIX = "picked_"
JOINED_CONTEXT = "inputs/joined/context.ply"


def shown_name(file_name: str, surface_set: SurfaceSetJson | None) -> str:
    """The name a set is shown by: its own, else the file name without its extension."""
    if surface_set is not None and surface_set.name:
        return surface_set.name
    return Path(file_name).stem


# Corners closer than this are one vertex: modelling tools repeat a vertex where faces meet, a few micrometres apart (the view merges
# them the same way, context_pieces.ts)
SAME_CORNER_DIGITS = 4          # 0.1 mm


def load_context(project_folder: Path) -> trimesh.Trimesh | None:
    """The joined surroundings, with their faces as stored and the vertices within 0.1 mm of each other merged; None without
    surroundings."""
    path = project_folder / JOINED_CONTEXT
    if not path.is_file():
        return None
    mesh = trimesh.load(str(path), force="mesh", process=True)
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces):
        return None
    mesh.merge_vertices(merge_tex=True, merge_norm=True, digits_vertex=SAME_CORNER_DIGITS)     # stored vertex normals would keep corners apart
    return mesh


def flat_piece(mesh: trimesh.Trimesh, seed: int) -> np.ndarray:
    """The faces of the flat piece of *seed*: reached from it across shared edges, within FLAT_ANGLE_DEG of its normal (either way
    round: neighbouring faces may be wound opposite) and FLAT_DISTANCE_M of its plane."""
    normals = mesh.face_normals
    seed_normal = normals[seed]
    plane_point = mesh.triangles[seed][0]
    cos_limit = np.cos(np.radians(FLAT_ANGLE_DEG))
    in_plane = np.all(np.abs((mesh.triangles - plane_point) @ seed_normal) <= FLAT_DISTANCE_M, axis=1)
    parallel = np.abs(normals @ seed_normal) >= cos_limit
    eligible = in_plane & parallel
    neighbours: dict[int, list[int]] = {}
    for a, b in mesh.face_adjacency:
        neighbours.setdefault(int(a), []).append(int(b))
        neighbours.setdefault(int(b), []).append(int(a))
    found = {seed}
    queue = deque([seed])
    while queue:
        face = queue.popleft()
        for other in neighbours.get(face, ()):
            if other not in found and eligible[other]:
                found.add(other)
                queue.append(other)
    return np.array(sorted(found), dtype=np.int64)


def picked_mesh(context: trimesh.Trimesh, picks: list[SurfacePick]) -> tuple[trimesh.Trimesh | None, int]:
    """The flat pieces of *picks*, each turned to face its click (two picks of one piece count once), as one mesh, and how many picks
    found no face; None when none did."""
    if not picks:
        return None, 0
    points = np.asarray([pick.point for pick in picks], dtype=float)
    _closest, distances, triangles = trimesh.proximity.closest_point(context, points)
    lost = 0
    faces_by_piece: dict[int, tuple[np.ndarray, bool]] = {}
    taken: set[int] = set()
    for pick, distance, triangle in zip(picks, distances, triangles):
        if not np.isfinite(distance) or distance > PICK_DISTANCE_M:
            lost += 1
            continue
        if int(triangle) in taken:
            continue
        piece = flat_piece(context, int(triangle))
        taken.update(int(face) for face in piece)
        facing = context.face_normals[int(triangle)]
        flip = float(np.dot(facing, np.asarray(pick.ray, dtype=float))) > 0.0      # the normal points away from the viewer
        faces_by_piece[int(triangle)] = (piece, flip)
    if not faces_by_piece:
        return None, lost
    seed_normals = {seed: context.face_normals[seed] * (-1.0 if flip else 1.0) for seed, (_piece, flip) in faces_by_piece.items()}
    vertices, faces = [], []
    for seed, (piece, _flip) in faces_by_piece.items():
        wanted = seed_normals[seed]
        for face in piece:
            corners = context.vertices[context.faces[face]]
            if float(np.dot(context.face_normals[face], wanted)) < 0.0:      # wound against its piece: turned with it
                corners = corners[::-1]
            start = len(vertices)
            vertices.extend(corners.tolist())
            faces.append([start, start + 1, start + 2])
    mesh = trimesh.Trimesh(vertices=np.asarray(vertices), faces=np.asarray(faces), process=True)
    return mesh, lost


def next_picked_file_name(recorded_names) -> str:
    """picked_<n>.ply with the lowest n not stored yet (letter case ignored)."""
    taken = {name.lower() for name in recorded_names}
    number = 1
    while f"{PICKED_PREFIX}{number}.ply" in taken:
        number += 1
    return f"{PICKED_PREFIX}{number}.ply"


def write_set_file(path: Path, mesh: trimesh.Trimesh) -> None:
    """Write a set's mesh through a temporary file in its folder, so a reader never sees a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix="picked-", suffix=".tmp.ply")
    os.close(descriptor)
    try:
        save_mesh(mesh, temporary_name)
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def checked_set_name(name: str, project_json: ProjectJson, own_file: str | None) -> str:
    """*name* trimmed, refused (422) when empty, longer than 80 characters, or shown by another set already (letter case ignored)."""
    trimmed = name.strip()
    if not trimmed:
        raise ProjectError("A surface set needs a name.", status_code=422)
    if len(trimmed) > 80:
        raise ProjectError("A surface set's name has at most 80 characters.", status_code=422)
    from .test_surfaces import ROLE
    for other in project_json.input_files.get(ROLE, {}):
        if other != own_file and shown_name(other, project_json.surface_sets.get(other)).lower() == trimmed.lower():
            raise ProjectError(f"Another surface set is named '{trimmed}'.", status_code=422)
    return trimmed


def next_picked_name(project_json: ProjectJson) -> str:
    """"Picked n" with the lowest n no set is shown by."""
    from .test_surfaces import ROLE
    shown = {shown_name(file_name, project_json.surface_sets.get(file_name)).lower() for file_name in project_json.input_files.get(ROLE, {})}
    number = 1
    while f"picked {number}" in shown:
        number += 1
    return f"Picked {number}"
