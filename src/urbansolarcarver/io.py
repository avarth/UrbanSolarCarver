"""Mesh file input and output.

``load_mesh`` reads a mesh file (PLY, OBJ, STL...) into a trimesh mesh;
``save_mesh`` writes one, switching PLY to double-precision vertices when
float32 would round georeferenced coordinates.
"""

import os
import numpy as np
import trimesh

def _ensure_dir(path: str) -> None:
    """Create parent directory if it doesn’t exist."""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

def load_mesh(path: str) -> trimesh.Trimesh:
    """
    Load a triangle mesh from file and ensure face normals are consistently
    oriented (outward-facing). Trimesh’s process=True fixes winding order,
    merges duplicate vertices, and removes degenerate faces.

    Raises a clear error for files that contain no usable triangles, which
    would otherwise surface much later as a cryptic empty-grid failure.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"load_mesh: file not found: {path}")
    mesh = trimesh.load(path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError(
            f"load_mesh: no triangle geometry found in {path!r} — the file is "
            f"empty, contains only points/curves, or could not be parsed as a mesh."
        )
    if not mesh.is_watertight:
        mesh.fix_normals()
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
    Save a mesh to disk. Creates output directory if needed.
    Returns the file path.

    PLY is written with float64 vertices when float32 would round them by
    more than 1 mm (georeferenced coordinates); otherwise as usual.
    """
    _ensure_dir(path)
    if str(path).lower().endswith(".ply") and float32_resolution(mesh.vertices) > 1e-3:
        _export_ply_double(mesh, path)
    else:
        mesh.export(path)
    return os.path.abspath(path)
