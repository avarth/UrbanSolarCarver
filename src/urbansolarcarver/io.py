"""
UrbanSolarCarver I/O Module

This module provides all file-based input and output functionality for the
UrbanSolarCarver pipeline, abstracting away format specifics and ensuring
consistent recording of geometry, point clouds, and diagnostic line sets.

Core Responsibilities
---------------------
1. Mesh Loading
   • load_mesh(path: str) → trimesh.Trimesh
     - Reads a mesh file (PLY, OBJ, etc.) from disk.
     - Repairs normals if the mesh is not watertight.
     - Returns a Trimesh instance ready for downstream processing.

2. Mesh Saving
   • save_mesh(mesh: trimesh.Trimesh, path: str) → str
     - Exports a Trimesh object to disk at the given path.
     - Ensures parent directories exist.
     - Returns the absolute path of the written file.

3. Point Cloud Export
   • save_pointcloud(points: np.ndarray, path: str) → str
     - Writes an Nx3 NumPy array of 3D points to a PLY point cloud.
     - Validates array shape.
     - Returns the written file path.

4. Line-Segment Export (OBJ)
   • export_sun_vectors(vectors: np.ndarray, origin: (x,y,z), scale: float, path: str) → str
   • export_rays(origins: np.ndarray, directions: np.ndarray, length: float, path: str) → str
     - Convert direction vectors or arbitrary ray sets into 3D line segments.
     - Each segment is two vertices and one line entry in OBJ format.
     - Facilitates visualization of sun directions or raytracing diagnostics.

5. Combined Point-and-Normal Export
   • export_points_with_normals(points: np.ndarray, normals: np.ndarray, path: str, normal_length: float) → ExportPaths
     - Writes a PLY point cloud and a matching OBJ of normal vectors.
     - Returns an ExportPaths dataclass with the two output file paths.

6. Bounding-Box Meshes
   • export_mesh_bbox_mesh(mesh: trimesh.Trimesh, path: str) → str
     - Computes the axis-aligned bounding box of a mesh.
     - Outputs a PLY box mesh for spatial context.
   • export_voxel_bbox_mesh(origin: np.ndarray, scale: float, path: str) → str
     - Constructs a cubic bounding box for a voxel grid.
     - Outputs as a PLY box mesh, aiding in debug and visualization.

Key Data Structures
-------------------
• trimesh.Trimesh      - Core mesh representation (vertices, faces, normals).
• np.ndarray (Nx3)     - Used for both point clouds and line-segment endpoints.
• ExportPaths          - Simple dataclass grouping point-cloud and normal-OBJ paths.

Usage Context
-------------
All functions return the path(s) of files written. This module ensures that geometry
and diagnostics are saved reliably and consistently for later analysis or publication.
"""

import os
import numpy as np
import trimesh
from trimesh.creation import box
from trimesh.transformations import translation_matrix
from dataclasses import dataclass
from typing import Tuple

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

def save_mesh(mesh: trimesh.Trimesh, path: str) -> str:
    """
    Save a mesh to disk. Creates output directory if needed.
    Returns the file path.
    """
    _ensure_dir(path)
    mesh.export(path)
    return os.path.abspath(path)

def save_pointcloud(points: np.ndarray, path: str) -> str:
    """
    Save an Nx3 array of points as a PLY point cloud.
    Returns the file path.

    Raises ValueError if points array is empty.
    """
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError(f"save_pointcloud: expected shape (N,3), got {points.shape}")
    if points.shape[0] == 0:
        raise ValueError("save_pointcloud: points array is empty")
    _ensure_dir(path)
    pc = trimesh.points.PointCloud(points)
    pc.export(path)
    return path

def _export_obj_lines(
    origins: np.ndarray,
    directions: np.ndarray,
    length: float,
    path: str
) -> str:
    """
    Write line segments to an OBJ file.
    Each segment goes from origin[i] to origin[i] + normalized(direction[i])*length.
    Zero-length direction vectors are silently skipped. The OBJ line format
    uses 1-based vertex indexing (v1, v2 per segment).
    Returns the file path.
    """
    if origins.ndim != 2 or directions.ndim != 2 or origins.shape != directions.shape:
        raise ValueError(f"_export_obj_lines: shapes mismatch: {origins.shape} vs {directions.shape}")
    if length <= 0:
        raise ValueError(f"_export_obj_lines: length must be > 0, got {length}")
    _ensure_dir(path)
    with open(path, "w") as f:
        vert_count = 0
        for p0, vec in zip(origins, directions):
            n = np.linalg.norm(vec)
            if n < 1e-12:
                continue
            v = vec / n
            p1 = p0 + v * length
            f.write(f"v {p0[0]} {p0[1]} {p0[2]}\n")
            f.write(f"v {p1[0]} {p1[1]} {p1[2]}\n")
            vert_count += 2
            f.write(f"l {vert_count-1} {vert_count}\n")
    return path

def export_sun_vectors(
    vectors: np.ndarray,
    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: float = 30.0,
    path: str = "sun_vectors.obj",
) -> str:
    """
    Export sun direction vectors as OBJ line segments.
    Returns the file path.

    Args:
        vectors: Nx3 array of sun direction vectors.
        origin: Common origin point for all vectors.
        scale: Length of each rendered line segment.
        path: Output OBJ file path.
    """
    n = vectors.shape[0]
    origins = np.tile(origin, (n, 1))
    return _export_obj_lines(origins, vectors, scale, path)

def export_rays(
    ray_origins: np.ndarray,
    ray_dirs: np.ndarray,
    length: float = 30.0,
    path: str = "rays.obj",
) -> str:
    """
    Export arbitrary rays as OBJ line segments.
    Returns the file path.

    Args:
        ray_origins: Nx3 array of ray start points.
        ray_dirs: Nx3 array of ray direction vectors.
        length: Length of each rendered line segment.
        path: Output OBJ file path.
    """
    return _export_obj_lines(ray_origins, ray_dirs, length, path)

@dataclass
class ExportPaths:
    pointcloud: str
    normals_obj: str

def export_points_with_normals(
    points: np.ndarray,
    normals: np.ndarray,
    path: str,
    normal_length: float = 2.0
) -> ExportPaths:
    """
    Export a point cloud (PLY) and its normals (OBJ).
    Returns an ExportPaths dataclass with file paths.

    Args:
        points: Nx3 array of 3D point positions.
        normals: Nx3 array of normal vectors (must match points shape).
        path: Base output path (must end in .ply).
        normal_length: Length of each normal line segment.
    """
    base, ext = os.path.splitext(path)
    if ext.lower() != ".ply":
        raise ValueError("export_points_with_normals: path must end in .ply")
    if points.shape != normals.shape or points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("export_points_with_normals: shapes must match Nx3")
    pts_path = f"{base}_pts{ext}"
    norms_path = f"{base}_normals.obj"
    save_pointcloud(points, pts_path)
    _export_obj_lines(points, normals, normal_length, norms_path)
    return ExportPaths(pointcloud=pts_path, normals_obj=norms_path)

def export_mesh_bbox_mesh(mesh: trimesh.Trimesh, path: str) -> str:
    """
    Export the axis-aligned bounding box of a mesh as a PLY box.
    Returns the file path.
    """
    if len(mesh.vertices) == 0:
        raise ValueError("export_mesh_bbox_mesh: mesh has no vertices")
    _ensure_dir(path)
    bmin, bmax = mesh.bounds
    extents = bmax - bmin
    center = (bmin + bmax) / 2.0
    transform = translation_matrix(center)
    bbox = box(extents=extents, transform=transform)
    bbox.export(path)
    return path

def export_voxel_bbox_mesh(
    origin: np.ndarray,
    scale: float,
    path: str
) -> str:
    """
    Export a cubic bounding box for the voxel grid as PLY.
    Returns the file path.

    Args:
        origin: 3-element array, minimum corner of the voxel grid.
        scale: Side length of the cubic bounding box.
        path: Output PLY file path.
    """
    if scale <= 0:
        raise ValueError(f"export_voxel_bbox_mesh: scale must be > 0, got {scale}")
    _ensure_dir(path)
    extents = np.array([scale, scale, scale], float)
    center = origin + scale / 2.0
    transform = translation_matrix(center)
    bbox = box(extents=extents, transform=transform)
    bbox.export(path)
    return path
