"""Mesh file input and output, and the preprocessing inputs.

``load_mesh`` reads a mesh file (PLY, OBJ, STL...) into a trimesh mesh;
``save_mesh`` writes one, switching PLY to double-precision vertices when
float32 would round georeferenced coordinates.  ``validate_inputs`` checks
that the files a preprocessing run needs exist, and ``load_meshes`` loads
the maximum volume and the test surfaces, reporting coordinates that a
float32 file has rounded; ``load_optional_mesh`` loads the optional context
and terrain meshes.
"""

import os
import numpy as np
import trimesh

from .errors import InputError
from .mode_registry import ALL_MODE_NAMES, MODES_NEEDING_EPW
from .run_context import report_issue
from .stage_settings import PreprocessingSettings

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
    mesh = _read_triangles(path)
    if mesh is None:
        raise InputError(
            f"load_mesh: no triangle geometry found in {path!r}; the file is "
            f"empty, contains only points/curves, or could not be parsed as a mesh."
        )
    return mesh


def _read_triangles(path: str):
    """The triangle mesh in *path* with its normals fixed as :func:`load_mesh` describes, or None when it has no triangles.

    Raises InputError if *path* is not a file or trimesh cannot parse it.
    """
    if not os.path.isfile(path):
        raise InputError(f"load_mesh: file not found: {path}")
    if os.path.getsize(path) == 0:
        return None
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
        return None
    mesh.fix_normals(multibody=mesh.is_watertight)
    return mesh


def load_optional_mesh(path, name: str):
    """Load an optional input mesh (context, terrain), or None when there is none.

    No path gives None. A file without triangles counts as absent: it is
    reported as a ``<name>_empty`` issue and gives None, so the run behaves as
    without it. A missing or unreadable file raises InputError.
    """
    if path is None:
        return None
    mesh = _read_triangles(path)
    if mesh is None:
        report_issue(f"{name}_empty", f"{os.path.basename(path)}: the {name} file has no triangles; it is ignored.")
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
    (as with georeferenced coordinates), and GLB with its offset in the node
    (``save_glb``); otherwise trimesh's exporter is used.  STL can only hold
    float32 vertices, so a float32_coordinates issue is reported when that
    rounds them by more than 1 mm.
    """
    _ensure_dir(path)
    extension = str(path).lower().rsplit(".", 1)[-1]
    if extension == "ply" and float32_resolution(mesh.vertices) > 1e-3:
        _export_ply_double(mesh, path)
    elif extension == "glb" and len(mesh.vertices):
        save_glb([(None, mesh)], path)
    else:
        if extension == "stl":
            _report_float32_rounding(path, mesh.vertices)
        mesh.export(path)
    return os.path.abspath(path)


def save_glb(named_meshes, path: str) -> None:
    """Write the (name, mesh) pairs as one GLB scene, one node each (a name of None lets trimesh name it).

    glTF stores vertices as float32, which rounds georeferenced coordinates by up to half a metre; every mesh is
    therefore moved by the same whole-metre offset near the scene's lowest corner, and each node's translation, a
    double in the file's JSON, moves it back, so readers place the vertices exactly.
    """
    import trimesh.transformations as tf
    _ensure_dir(path)
    offset = np.floor(np.min([mesh.vertices.min(axis=0) for _name, mesh in named_meshes], axis=0))
    scene = trimesh.Scene()
    for name, mesh in named_meshes:
        near_origin = mesh.copy()
        near_origin.apply_translation(-offset)
        scene.add_geometry(near_origin, geom_name=name, transform=tf.translation_matrix(offset))
    scene.export(str(path), file_type="glb")


def _report_float32_rounding(path: str, vertices) -> None:
    """Report a float32_coordinates issue when writing *vertices* as float32 to *path* rounds them by more than 1 mm."""
    res = float32_resolution(vertices)
    if res > 1e-3:
        report_issue(
            "float32_coordinates",
            f"{os.path.basename(path)}: STL stores float32 vertices, so coordinates reaching "
            f"{float(np.abs(vertices).max()):,.0f} m are rounded to ~{res:.2g} m. Choose PLY, OBJ or GLB "
            f"to keep them, or move the model near the origin.",
        )


def validate_inputs(settings: PreprocessingSettings):
    """
    Validate file paths and supported modes.

    Raises
    ------
    InputError
        If the max-volume or test-surface mesh is missing, a context or
        terrain path is given and its file is missing, or the EPW file is
        missing for a mode that needs one.
    ValueError
        If `settings.mode` is not one of:
        {'time-based','irradiance','benefit','daylight','radiative_cooling','tilted_plane'}.
    """
    for filepath, name in [
        (settings.max_volume_path, 'max_volume'),
        (settings.test_surface_path,    'test_surface'),
    ]:
        if not filepath or not os.path.isfile(filepath):
            raise InputError(f"{name} file missing: {filepath!r}")
    for filepath, key in [(settings.context_path, 'context_path'), (settings.terrain_path, 'terrain_path')]:
        if filepath is not None and not os.path.isfile(filepath):
            raise InputError(f"{key}: file missing: {filepath!r}")
    # EPW is required for modes that use weather data
    if settings.mode in MODES_NEEDING_EPW:
        if not settings.epw_path or not os.path.isfile(settings.epw_path):
            raise InputError(f"EPW file missing: {settings.epw_path!r}")
    if settings.mode not in ALL_MODE_NAMES:
        raise ValueError(f"Unsupported mode: {settings.mode!r}")


def load_meshes(settings: PreprocessingSettings):
    """
    Load the maximum envelope mesh and the insolation sampling surface.

    Warns when a PLY file stores large (georeferenced) coordinates as float32,
    because that rounding happened on disk and cannot be undone here.

    Returns
    -------
    envelope_mesh : trimesh.Trimesh
    insolation_mesh : trimesh.Trimesh
    """
    envelope_mesh = load_mesh(settings.max_volume_path)
    insolation_mesh = load_mesh(settings.test_surface_path)
    for path, mesh in ((settings.max_volume_path, envelope_mesh),
                       (settings.test_surface_path, insolation_mesh)):
        _warn_float32_input(path, mesh, settings.voxel_size)
    return envelope_mesh, insolation_mesh


def _stores_float32_vertices(path: str) -> bool:
    """True if *path* is a PLY file whose header declares float32 x coordinates."""
    if not str(path).lower().endswith(".ply"):
        return False
    with open(path, "rb") as fh:
        header = fh.read(4096).split(b"end_header")[0].decode("ascii", errors="replace")
    return any(line.split()[:3] in (["property", "float", "x"], ["property", "float32", "x"])
               for line in header.splitlines())


def _warn_float32_input(path: str, mesh, voxel_size: float) -> None:
    """Warn if the file's float32 vertices are rounded by more than 1 % of a voxel.

    Large (georeferenced) coordinates stored as float32 lose precision when
    the file is written, so the rounding cannot be recovered on load.
    """
    res = float32_resolution(mesh.vertices)
    if res > 0.01 * float(voxel_size) and _stores_float32_vertices(path):
        report_issue(
            "float32_coordinates",
            f"{os.path.basename(path)}: coordinates reach "
            f"{float(np.abs(mesh.vertices).max()):,.0f} m and the file stores "
            f"float32 vertices, so its geometry is rounded to ~{res:.2g} m on disk "
            f"({100 * res / voxel_size:.0f}% of a voxel). Move the model near the "
            f"origin before export, or export PLY with double-precision vertices.",
        )
