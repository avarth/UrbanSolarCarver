"""Mesh file input and output.

``load_mesh`` reads a mesh file (PLY, OBJ, STL...) into a trimesh mesh;
``save_mesh`` writes one, switching PLY to double-precision vertices when
float32 would round georeferenced coordinates.
"""

import os
import numpy as np
import trimesh

from .errors import InputError

def _ensure_dir(path: str) -> None:
    """Create parent directory if it doesn’t exist."""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

def load_mesh(path: str) -> trimesh.Trimesh:
    """
    Load a triangle mesh from file.

    trimesh's default processing on load removes NaN/inf vertices and merges
    duplicate vertices; it does not fix winding or remove degenerate faces.
    ``fix_normals`` is then called: it makes the face winding consistent
    across connected faces, and for watertight meshes it also turns each
    closed body that is stored inside out so its normals point outward.

    Raises
    ------
    InputError
        If *path* is not a file, if trimesh cannot parse it, or if it has no
        triangles (empty, or only points or curves).  Without the last check
        the problem would only show up later as an empty voxel grid.
    """
    if not os.path.isfile(path):
        raise InputError(f"load_mesh: file not found: {path}")
    try:
        mesh = trimesh.load(path, force="mesh")
    except Exception as exc:
        # trimesh's parsers fail with many unrelated exception types
        # (IndexError, KeyError, struct.error...); callers get one.
        raise InputError(
            f"load_mesh: could not read {path!r} as a mesh "
            f"({type(exc).__name__}: {exc})"
        ) from exc
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise InputError(
            f"load_mesh: no triangle geometry found in {path!r}; the file is "
            f"empty, contains only points/curves, or could not be parsed as a mesh."
        )
    mesh.fix_normals(multibody=mesh.is_watertight)
    return mesh

FLOAT32_REL_SPACING = 2.0 ** -23  # float32 spacing relative to magnitude


def float32_resolution(coords) -> float:
    """Spacing between adjacent float32 values at the largest |coordinate|."""
    c = np.asarray(coords, dtype=np.float64)
    return float(np.abs(c).max()) * FLOAT32_REL_SPACING if c.size else 0.0


def _export_ply_double(mesh: trimesh.Trimesh, path: str) -> None:
    """Binary PLY with float64 vertices (trimesh's writer always emits float32)."""
    v = np.ascontiguousarray(mesh.vertices, dtype="<f8")
    f = np.asarray(mesh.faces, dtype="<i4")
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(v)}\n"
        "property double x\nproperty double y\nproperty double z\n"
        f"element face {len(f)}\n"
        "property list uchar int vertex_indices\nend_header\n"
    ).encode("ascii")
    faces = np.empty(len(f), dtype=[("n", "u1"), ("i", "<i4", (3,))])
    faces["n"] = 3
    faces["i"] = f
    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(v.tobytes())
        fh.write(faces.tobytes())


def save_mesh(mesh: trimesh.Trimesh, path: str) -> str:
    """
    Save a mesh to disk, creating the output directory if needed, and
    return the absolute file path.

    The format follows the file extension.  PLY is written with float64
    vertices when float32 spacing at the largest coordinate exceeds 1 mm
    (as with georeferenced coordinates); otherwise trimesh's exporter is used.
    """
    _ensure_dir(path)
    if str(path).lower().endswith(".ply") and float32_resolution(mesh.vertices) > 1e-3:
        _export_ply_double(mesh, path)
    else:
        mesh.export(path)
    return os.path.abspath(path)
