"""
UrbanSolarCarver — Grid utilities

Tools for sampling nearly planar geometry, converting meshes to voxels,
cleaning occupancy, and building meshes. Used by the carving pipeline
to generate point/normal sets, binary grids, and final surfaces.

Overview
--------
Two meshing modes are supported:

1) Cubic (apply_smoothing == False)
   - Clean the binary grid with component pruning and a 3×3×3 majority filter.
   - Triangulate with the shared-vertex cubic mesher
     (`_cubic_mesh_from_occupancy`).

2) Smoothed SDF (apply_smoothing == True)
   - Convert occupancy to a signed distance field (SDF) in voxel units.
   - Light Gaussian blur, then edge-preserving Perona–Malik diffusion
     applied only near the zero level.
   - Pick an iso value that preserves the original inside volume.
   - Extract a surface with marching cubes (trimesh + scikit-image).
   - Optionally run a tiny Taubin polish (0..6 iters) after cleanup.

Public API
----------
sample_planar_surface(mesh, sample_step, include_boundary=True)
    Uniformly sample a strictly planar patch. Returns points, normals, and
    quad-mesh data (vertices + faces) for the analysis mesh.

discretize_surface_with_normals(mesh, sample_step, coplanarity_tol_deg=5.0)
    Collect point/normal pairs and an analysis mesh from near-planar components.

voxelize_mesh(mesh, voxel_size, margin_frac, device=None)
    Rasterize a watertight mesh into a padded cubic occupancy grid.

prune_voxels(voxels, min_voxels)
    Remove 26-connected components smaller than min_voxels.

prune_voxels_morph(voxels, min_voxels)
    Gentle cleanup for the cubic path: component prune, majority filter,
    single closing. Preserves thin slabs better than erosion/opening.

voxelize_and_clean(mesh, voxel_size, margin_frac, min_voxels)
    Convenience wrapper: voxelize_mesh then prune_voxels.

mesh_from_voxels(voxels, min_corner, voxel_size)
    Build a blocky mesh from the binary grid. Returns an unprocessed Trimesh.

mesh_from_voxels_smoothed(voxels, min_corner, voxel_size)
    Build a smooth mesh by contouring a smoothed SDF with marching cubes.
    Uses a volume-matched iso to avoid systematic thinning.

mesh_from_voxels_select(voxels, min_corner, voxel_size, apply_smoothing)
    Dispatch to the cubic or SDF path based on the flag above.

cleanup_mesh(mesh, min_face_count=100)
    Fix winding/normals, weld vertices, drop tiny fragments.

polish_mesh_taubin(mesh, iters=0)
    Optional micro-polish after SDF+MC. Scale-normalized. Safe for 0..6 iters.

Internal helpers
----------------
plane_frame(normal)
    Orthonormal in-plane basis for planar sampling.

_voxel_presmooth(field_bool)
    SDF build + Gaussian + narrow-band Perona–Malik diffusion.

_pm_anisotropic_diffuse(sdf, iters, k, tau)
    Edge-preserving diffusion stepper used by _voxel_presmooth.

_volume_matched_threshold(sdf, target_inside_voxels)
    Iso selection that matches the original inside count.

_median_edge_length(mesh)
    Median of unique edge lengths; used to normalize the Taubin polish.

Data types and units
--------------------
- Points and normals: np.ndarray, shape (N, 3), world units.
- Voxel grids: torch.Tensor, shape (D, D, D), uint8/bool, 1 = inside.
- Meshes: trimesh.Trimesh in world coordinates.
- voxel_size is in world units and is passed to marching cubes as pitch.

Notes
-----
- The cubic path aims for stable, interpretable “voxel look” with minimal
  flicker between runs. No erosion by default to protect thin volumes.
- The smoothed path operates in SDF space, not on the triangle mesh. This
  removes terracing while keeping the overall form.
- The Taubin step is deliberately tiny and optional. Heavy smoothing belongs
  in SDF space, not post-mesh.

"""

from typing import Tuple, Sequence, List, Union
import logging
import math
import os
import torch
import numpy as np

_log = logging.getLogger(__name__)
from numba import njit, prange
from scipy import ndimage as ndi
from scipy.ndimage import distance_transform_edt, gaussian_filter
from scipy.spatial import cKDTree

from shapely.geometry import Polygon, LineString
from shapely import contains_xy
import trimesh
from trimesh import repair
from urbansolarcarver.session import session_cache

# Helpers migrated from api_core
from .load_config import user_config

def voxelize(envelope_mesh, config: user_config, device: torch.device | None = None):
    """
    Rasterize the envelope into a padded cubic voxel grid.

    Parameters
    ----------
    envelope_mesh : trimesh.Trimesh
    config : user_config
    device : torch.device or None

    Returns
    -------
    voxel_grid : torch.Tensor (D, D, D), uint8
        1 indicates inside/filled.
    grid_origin : np.ndarray(3,)
        World-space min corner for index (0,0,0).
    grid_extent : float
        Physical cube size (meters).
    grid_resolution : int
        Number of voxels per side (D).

    Raises
    ------
    RuntimeError
        If voxelization returns an empty grid.
    """
    voxel_grid, grid_origin, grid_extent, grid_resolution = voxelize_mesh(
        envelope_mesh,
        voxel_size=config.voxel_size,
        margin_frac=config.margin_frac,
        device=device                    
    )

    if voxel_grid.numel() == 0 or voxel_grid.sum() == 0:
        raise RuntimeError("Voxel grid is empty after voxelization")
    
    return voxel_grid, grid_origin, grid_extent, grid_resolution

def sample_surface(insolation_mesh, config: user_config):
    """
    Sample quasi-planar patches to produce point/normal sets for carving.

    Returns
    -------
    sample_points : np.ndarray (N, 3)
    sample_normals : np.ndarray (N, 3)
    analysis_mesh : ladybug_geometry.geometry3d.mesh.Mesh3D or None
        The analysis mesh whose face centroids are the sample points.

    Raises
    ------
    RuntimeError
        If no points are sampled from the insolation surface.
    """
    sample_points, sample_normals, analysis_mesh = discretize_surface_with_normals(
        insolation_mesh, config.grid_step
    )

    if sample_points.size == 0:
        n_components = len(insolation_mesh.split(only_watertight=False))
        raise RuntimeError(
            "No points sampled from test surfaces (insolation mesh). "
            "The mesh has {:d} connected component(s), but none passed the planarity check. "
            "Most likely cause: test_surfaces is a joined polysurface (e.g. an extruded block "
            "boundary) whose wall panels share corner edges — the whole block is treated as one "
            "non-planar component and rejected. "
            "Fix: explode your polysurfaces into individual flat panels in Grasshopper before "
            "connecting to USC_Preprocess. Also check that grid_step ({:g} m) is smaller than "
            "your smallest surface.".format(n_components, config.grid_step)
        )
    return sample_points, sample_normals, analysis_mesh

def finalize_mesh(carved_grid, grid_origin, config: user_config):
    """
    Convert carved voxels to a mesh and clean results.

    Behavior
    --------
    • If `apply_smoothing` is False:
        prune small components + gentle morphology (majority + closing),
        cubic meshing, then `cleanup_mesh`.
    • If `apply_smoothing` is True:
        prune small components,
        SDF presmooth + marching cubes, then `cleanup_mesh`,
        optional micro Taubin polish capped to 0..6 iterations.

    Parameters
    ----------
    carved_grid : torch.Tensor (D, D, D)
        Binary occupancy after carving.
    grid_origin : np.ndarray(3,)
        World-space min corner for index (0,0,0).
    config : user_config

    Returns
    -------
    cleaned_voxels : torch.Tensor (D, D, D)
        Post-pruned (and possibly morphologically cleaned) occupancy.
    initial_mesh : trimesh.Trimesh
        Mesh directly from the selected meshing path (pre-cleanup copy).
    final_mesh : trimesh.Trimesh
        Cleaned (and optionally micro-polished) mesh.
    """
    use_smooth = bool(config.apply_smoothing)

    if use_smooth:
        # Smooth path: prune → SDF smooth → marching cubes → full repair → Taubin
        cleaned_voxels = prune_voxels(carved_grid, config.min_voxels)
        raw_mesh = mesh_from_voxels_smoothed(cleaned_voxels, grid_origin, config.voxel_size)
        initial_mesh = raw_mesh.copy()
        filtered_mesh = cleanup_mesh(raw_mesh, config.min_face_count, light=False)
        iters = int(min(max(getattr(config, "smooth_iters", 0), 0), 6))
        final_mesh = polish_mesh_taubin(filtered_mesh, iters=iters)
    else:
        # Cubic path: prune + gentle morphology, cubic meshing, then cleanup
        cleaned_voxels = prune_voxels_morph(carved_grid, config.min_voxels)
        raw_mesh = mesh_from_voxels(cleaned_voxels, grid_origin, config.voxel_size)
        initial_mesh = raw_mesh.copy()
        final_mesh = cleanup_mesh(raw_mesh, config.min_face_count, light=True)

    return cleaned_voxels, initial_mesh, final_mesh


def plane_frame(surface_normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Return two orthonormal vectors spanning the plane orthogonal to `surface_normal`.

    Parameters
    ----------
    surface_normal : (3,) array_like
        Plane normal (need not be unit length).

    Returns
    -------
    axis_u, axis_v : (3,) np.ndarray
        Unit vectors forming a right-handed 2D basis in the plane.

    Notes
    -----
    - The normal is normalized internally.
    - A stable reference axis is chosen to avoid degeneracy when the normal is
      almost aligned with X.
    - Used by `sample_planar_surface` to build a local 2D sampling frame.
    """
    # Normalize input normal
    norm_len = np.linalg.norm(surface_normal)
    if norm_len < 1e-12:
        raise ValueError("plane_frame: surface_normal has near-zero length")
    plane_normal = surface_normal / norm_len
    # Choose a reference vector not parallel to the normal.
    # 0.9 threshold: if the normal is nearly aligned with X (|cos| > 0.9,
    # i.e. < ~26 deg from the X axis), use Y as the reference axis instead
    # to avoid near-parallel cross-product degeneracy.
    if abs(plane_normal[0]) < 0.9:
        ref_axis = np.array([1.0, 0.0, 0.0])
    else:
        ref_axis = np.array([0.0, 1.0, 0.0])
    # First in-plane axis
    axis_u = np.cross(plane_normal, ref_axis)
    axis_u /= np.linalg.norm(axis_u)
    # Second in-plane axis
    axis_v = np.cross(plane_normal, axis_u)
    return axis_u, axis_v


def _sample_boundary_edges(
    polygon: Polygon,
    sample_step: float,
    interior_pts_2d: np.ndarray,
    min_dist_fraction: float = 0.5,
    inset_fraction: float = 0.3,
) -> np.ndarray:
    """Generate sample points along polygon boundary edges to fill grid gaps.

    Walks each boundary ring (exterior + holes) at *sample_step* intervals,
    offsets candidates inward, and keeps only those far enough from existing
    interior grid points.

    Returns an (K, 2) array of accepted edge points in the polygon's local 2D
    coordinate frame, or an empty (0, 2) array if none qualify.
    """
    inset = inset_fraction * sample_step
    min_dist = min_dist_fraction * sample_step
    # Tiny buffer so points near (but not exactly on) the boundary pass
    # Shapely's strict-interior containment test.
    test_poly = polygon.buffer(sample_step * 1e-3)
    candidates = []

    rings = [polygon.exterior] + list(polygon.interiors)
    for ring in rings:
        is_exterior = ring is polygon.exterior
        coords = np.asarray(ring.coords)
        line = LineString(coords)
        length = line.length
        if length < 1e-12:
            continue

        # Walk along ring at sample_step intervals
        n_samples = max(1, int(np.ceil(length / sample_step)))
        distances = np.linspace(0, length, n_samples, endpoint=False)

        for d in distances:
            pt = line.interpolate(d)
            px, py = pt.x, pt.y

            # Compute local edge tangent from nearby interpolation
            d2 = min(d + sample_step * 0.01, length)
            pt2 = line.interpolate(d2)
            tx, ty = pt2.x - px, pt2.y - py
            tlen = np.hypot(tx, ty)
            if tlen < 1e-12:
                continue
            tx /= tlen
            ty /= tlen

            # Inward normal: for CCW exterior, left of tangent is inward
            if is_exterior:
                nx, ny = -ty, tx
            else:
                nx, ny = ty, -tx

            # Try progressively smaller insets — handles thin polygons where
            # the full inset lands outside the boundary.
            placed = False
            for frac in (1.0, 0.5, 0.1):
                cx = px + nx * inset * frac
                cy = py + ny * inset * frac
                if contains_xy(test_poly, cx, cy):
                    candidates.append((cx, cy))
                    placed = True
                    break
            if not placed:
                # Fall back to the raw boundary point
                if contains_xy(test_poly, px, py):
                    candidates.append((px, py))

    if not candidates:
        return np.empty((0, 2), dtype=np.float64)

    candidates = np.array(candidates, dtype=np.float64)

    # Deduplicate against interior grid points
    if interior_pts_2d.size > 0:
        tree = cKDTree(interior_pts_2d)
        dists, _ = tree.query(candidates)
        candidates = candidates[dists > min_dist]

    # Deduplicate among edge candidates themselves
    if len(candidates) > 1:
        edge_tree = cKDTree(candidates)
        pairs = edge_tree.query_pairs(r=min_dist)
        if pairs:
            remove = set()
            for i, j in pairs:
                remove.add(max(i, j))  # keep lower index
            keep = np.array(sorted(set(range(len(candidates))) - remove))
            candidates = candidates[keep]

    return candidates if len(candidates) > 0 else np.empty((0, 2), dtype=np.float64)


def sample_planar_surface(
    mesh: trimesh.Trimesh,
    sample_step: float = 1.0,
    include_boundary: bool = True
) -> tuple[np.ndarray, np.ndarray]:
    """
    Uniformly sample points on a strictly planar submesh and return per-point normals.

    Parameters
    ----------
    mesh : trimesh.Trimesh
        Single planar connected component (convex or with holes).
    sample_step : float, default 1.0
        Spacing of the sampling grid in world units.
    include_boundary : bool, default True
        If True, include points that fall on polygon boundaries; otherwise drop them.

    Returns
    -------
    points : (N, 3) np.ndarray
        Sample locations in world coordinates.
    normals : (N, 3) np.ndarray
        Unit normals (constant over the patch, oriented consistently with the mesh).
    quad_verts : (4N, 3) float64 np.ndarray
        Corner positions of one analysis-mesh quad per sample point.
    quad_faces : (N, 4) int32 np.ndarray
        Vertex indices of each quad (indices into `quad_verts`).

    Notes
    -----
    - Builds a local 2D grid in the plane (see `plane_frame`) and rasterizes the
      polygon footprint to select in-polygon grid sites.
    - Used by `discretize_surface_with_normals` for planar-only sampling.
    """
    # 1) Compute centroid and best-fit plane normal via PCA.
    #    The covariance matrix's eigenvectors span the point cloud's
    #    principal axes; the eigenvector with the *smallest* eigenvalue
    #    has the least variance — i.e., it points perpendicular to the
    #    plane that best fits the vertices.
    vertices = mesh.vertices                # (N, 3)
    centroid = vertices.mean(axis=0)        # (3,)
    cov_mat = np.cov((vertices - centroid).T)
    evals, evecs = np.linalg.eigh(cov_mat)
    plane_normal = evecs[:, np.argmin(evals)]

    # 2) Build a local 2D orthonormal frame (u, v) lying in the plane.
    #    All subsequent sampling happens in this 2D coordinate system.
    axis_u, axis_v = plane_frame(plane_normal)

    # 3) Extract mesh boundary edges.
    #    Interior edges are shared by exactly 2 faces; boundary edges
    #    appear only once.  Sort vertex pairs so (a,b) == (b,a).
    faces = mesh.faces                      # (F, 3)
    all_edges = np.vstack([
        faces[:, [0, 1]],
        faces[:, [1, 2]],
        faces[:, [2, 0]]
    ])                                      # (3F, 2)
    all_edges = np.sort(all_edges, axis=1)  # make edges undirected
    unique_edges, edge_counts = np.unique(
        all_edges, axis=0, return_counts=True
    )
    boundary_edges = unique_edges[edge_counts == 1]

    # 4) Chain boundary edges into ordered vertex loops.
    #    Build an adjacency graph from boundary edges, then walk each
    #    connected component by always choosing the neighbor that isn't
    #    the previous vertex (greedy Euler-path traversal).  Remove
    #    edges as they're consumed so each loop is extracted once.
    adjacency: dict[int, list[int]] = {}
    for v_start, v_end in boundary_edges:
        adjacency.setdefault(int(v_start), []).append(int(v_end))
        adjacency.setdefault(int(v_end), []).append(int(v_start))
    boundary_loops: list[list[int]] = []
    while adjacency:
        start_vertex = next(iter(adjacency))
        loop = [start_vertex]
        current, previous = start_vertex, None
        while True:
            neighbors = [nbr for nbr in adjacency[current] if nbr != previous]
            if not neighbors:
                break
            next_vertex = neighbors[0]
            loop.append(next_vertex)
            adjacency[current].remove(next_vertex)
            adjacency[next_vertex].remove(current)
            if not adjacency[current]:
                adjacency.pop(current)
            if not adjacency.get(next_vertex):
                adjacency.pop(next_vertex, None)
            previous, current = current, next_vertex
            if current == start_vertex:
                break
        if len(loop) > 2:
            boundary_loops.append(loop)

    # 5) Project loops into the local 2D frame and identify exterior/interior.
    #    Each 3D vertex is projected to (u, v) by dotting with the plane
    #    basis vectors.  The loop enclosing the largest absolute area is
    #    the exterior boundary; all others are holes (interior loops).
    #    Interior loops are reversed so Shapely treats them as holes.
    loops_2d = [
        (vertices[loop_idx] - centroid) @ np.vstack([axis_u, axis_v]).T
        for loop_idx in boundary_loops
    ]
    loop_areas = [Polygon(ring).area for ring in loops_2d]
    exterior_index = int(np.argmax(np.abs(loop_areas)))
    exterior_loop = loops_2d[exterior_index]
    interior_loops = [
        loops_2d[i] for i in range(len(loops_2d)) if i != exterior_index
    ]
    planar_polygon = Polygon(exterior_loop, holes=[ring[::-1] for ring in interior_loops])

    # 6) Generate a regular 2D sampling grid over the polygon's bounding box.
    #    The grid is aligned to the *world origin* projected into this face's
    #    local 2D frame.  Because plane_frame() returns identical (u, v) axes
    #    for all faces sharing the same normal, this guarantees that coplanar
    #    submeshes produce grids on the same world-space lattice — eliminating
    #    phase-shift banding between adjacent panels at coarse grid steps.
    xmin, ymin, xmax, ymax = planar_polygon.bounds
    world_ref_u = -np.dot(centroid, axis_u)  # world origin (0,0,0) in local u
    world_ref_v = -np.dot(centroid, axis_v)  # world origin (0,0,0) in local v
    x0 = xmin + ((world_ref_u - xmin) % sample_step)
    y0 = ymin + ((world_ref_v - ymin) % sample_step)
    grid_x = np.arange(x0, xmax, sample_step)
    grid_y = np.arange(y0, ymax, sample_step)
    grid_X, grid_Y = np.meshgrid(grid_x, grid_y)

    # 7) Optionally inflate the polygon by a tiny epsilon so that points
    #    lying exactly on the boundary are included (Shapely's contains_xy
    #    uses strict interior containment by default).
    if include_boundary:
        buffer_epsilon = sample_step * 1e-3
        test_polygon = planar_polygon.buffer(buffer_epsilon)
    else:
        test_polygon = planar_polygon

    # 8) Rasterize: keep only grid points that fall inside the polygon.
    inside_mask = contains_xy(test_polygon, grid_X.ravel(), grid_Y.ravel()).reshape(grid_X.shape)

    # 9) Lift valid 2D samples back to 3D world coordinates.
    #    p_3D = centroid + u·axis_u + v·axis_v  (inverse of the projection).
    points_2d = np.vstack((grid_X[inside_mask], grid_Y[inside_mask])).T  # (M, 2)

    # 9b) Edge seeding: fill gaps along polygon boundary where the grid
    #     doesn't reach close enough to the edges.
    edge_pts = _sample_boundary_edges(planar_polygon, sample_step, points_2d)
    if edge_pts.size > 0:
        points_2d = np.vstack([points_2d, edge_pts]) if points_2d.size > 0 else edge_pts

    # Guarantee at least one sample (centroid) when the grid is too coarse
    # to produce any points inside the polygon.
    if len(points_2d) == 0 and planar_polygon.area > 0:
        points_2d = np.array([[0.0, 0.0]])  # centroid in local frame

    points_3d = (
        centroid
        + points_2d[:, 0:1] * axis_u
        + points_2d[:, 1:2] * axis_v
    )  # (M, 3)

    # 10) Assign normals.  The PCA normal may point either way; flip it
    #     to match the mesh's face-normal orientation (outward-facing).
    #     Also fix the local frame so cross(axis_u, axis_v) aligns with
    #     the outward normal — ensures consistent quad vertex winding for
    #     correct lighting in Plotly / Rhino viewers.
    face_normal = mesh.face_normals[0]
    if np.dot(face_normal, plane_normal) < 0:
        plane_normal = -plane_normal
        axis_v = -axis_v  # flip one axis so cross(u,v) matches new normal
    point_normals = np.tile(plane_normal, (len(points_3d), 1))  # (M, 3)

    # 11) Build analysis-mesh quad data.  Each included cell becomes a
    #     quad face whose centroid == the sample point.  Corners are at
    #     ±half_step from the cell centre in the plane's (u, v) frame.
    #     Non-shared vertices (4 per quad) — simple & correct.
    n_pts = len(points_2d)
    if n_pts > 0:
        hs = sample_step / 2.0
        offsets = np.array([[-hs, -hs], [hs, -hs], [hs, hs], [-hs, hs]])  # (4, 2)
        quad_verts_2d = points_2d[:, None, :] + offsets[None, :, :]         # (N, 4, 2)
        quad_verts_2d = quad_verts_2d.reshape(-1, 2)                        # (4N, 2)
        quad_verts_3d = (
            centroid
            + quad_verts_2d[:, 0:1] * axis_u
            + quad_verts_2d[:, 1:2] * axis_v
        ).astype(np.float64)                                                # (4N, 3)
        quad_faces = np.arange(4 * n_pts, dtype=np.int32).reshape(n_pts, 4) # (N, 4)
    else:
        quad_verts_3d = np.empty((0, 3), dtype=np.float64)
        quad_faces = np.empty((0, 4), dtype=np.int32)

    return points_3d, point_normals, quad_verts_3d, quad_faces

class AnalysisMesh:
    """Lightweight quad mesh container.  Holds raw numpy arrays and builds
    a Ladybug ``Mesh3D`` or trimesh ``Trimesh`` on demand.

    Attributes
    ----------
    vertices : (V, 3) float64 ndarray — quad corner positions.
    faces    : (N, 4) int32 ndarray   — quad face vertex indices.
    face_normals : (N, 3) float32 ndarray or None — outward unit normals per face.
    """
    __slots__ = ("vertices", "faces", "face_normals")

    def __init__(self, vertices: np.ndarray, faces: np.ndarray,
                 face_normals: np.ndarray | None = None):
        self.vertices = vertices
        self.faces = faces
        self.face_normals = face_normals

    # -- Serialisation helpers (called once, outside the hot path) ----------

    def to_dict(self) -> dict:
        """Serialise to a plain dict (vertices + faces as nested lists)."""
        out = {
            "type": "AnalysisMesh",
            "vertices": self.vertices.tolist(),
            "faces": self.faces.tolist(),
        }
        if self.face_normals is not None:
            out["face_normals"] = self.face_normals.tolist()
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "AnalysisMesh":
        fn = None
        if "face_normals" in d:
            fn = np.asarray(d["face_normals"], dtype=np.float32)
        return cls(
            np.asarray(d["vertices"], dtype=np.float64),
            np.asarray(d["faces"], dtype=np.int32),
            fn,
        )

    def to_ladybug_mesh3d(self):
        """Build a ``ladybug_geometry.geometry3d.mesh.Mesh3D`` (slow, use lazily)."""
        from ladybug_geometry.geometry3d.pointvector import Point3D
        from ladybug_geometry.geometry3d.mesh import Mesh3D
        lb_verts = [Point3D(float(v[0]), float(v[1]), float(v[2])) for v in self.vertices]
        lb_faces = [tuple(int(i) for i in f) for f in self.faces]
        return Mesh3D(lb_verts, lb_faces)

    def to_trimesh(self, face_colors=None):
        """Triangulate quads and return a ``trimesh.Trimesh``."""
        tri_faces = []
        tri_colors = [] if face_colors is not None else None
        for i, f in enumerate(self.faces):
            tri_faces.append([f[0], f[1], f[2]])
            tri_faces.append([f[0], f[2], f[3]])
            if face_colors is not None:
                tri_colors.append(face_colors[i])
                tri_colors.append(face_colors[i])
        kw = {"process": False}
        if tri_colors is not None:
            kw["face_colors"] = np.array(tri_colors)
        return trimesh.Trimesh(
            vertices=self.vertices, faces=np.array(tri_faces), **kw,
        )


def discretize_surface_with_normals(
    mesh: trimesh.Trimesh,
    sample_step: float = 1.0,
    coplanarity_tol_deg: float = 5.0
) -> tuple[np.ndarray, np.ndarray, "AnalysisMesh | None"]:
    """
    Sample nearly planar regions of a mesh and return point/normal pairs.

    Uses the fast Shapely-based rasterizer (``sample_planar_surface``) for
    point/normal generation and builds a quad analysis mesh from the same
    2D grid.  The mesh has a 1:1 face-to-point mapping suitable for
    per-face coloring (e.g. "LB Spatial Heatmap" in GH/Rhino).

    Parameters
    ----------
    mesh : trimesh.Trimesh
        Input triangle mesh (test surface).
    sample_step : float
        Sampling grid spacing in world units.
    coplanarity_tol_deg : float, default 5.0
        Maximum face-normal deviation (degrees) to consider a component planar.

    Returns
    -------
    points : (N, 3) float32 np.ndarray
        Sample points (centroids of the analysis-mesh quads).
    normals : (N, 3) float32 np.ndarray
        Outward-facing normals at each sample point.
    analysis_mesh : AnalysisMesh or None
        Combined quad analysis mesh, or None if no points were sampled.
    """
    submeshes = mesh.split(only_watertight=False)
    all_points, all_normals = [], []
    all_quad_verts, all_quad_faces = [], []
    vertex_offset = 0

    for submesh in submeshes:
        # 1) Planarity check via face normals (area-weighted reference)
        face_normals = submesh.face_normals  # (F, 3)
        face_areas = submesh.area_faces       # (F,)
        mean_normal = (face_normals * face_areas[:, None]).sum(axis=0)
        norm_len = np.linalg.norm(mean_normal)
        if norm_len < 1e-12:
            continue  # degenerate component
        mean_normal /= norm_len
        cos_angles = face_normals @ mean_normal
        angles = np.degrees(np.arccos(np.clip(cos_angles, -1.0, 1.0)))
        if angles.max() > coplanarity_tol_deg:
            continue

        # 2) Sample this planar sheet (fast Shapely rasterizer)
        pts3d, nrm3d, qv, qf = sample_planar_surface(submesh, sample_step)

        if pts3d.size == 0:
            continue

        # 3) Ensure normal orientation matches component
        avg_face_normal = face_normals.mean(axis=0)
        if np.dot(avg_face_normal, nrm3d[0]) < 0:
            nrm3d = -nrm3d

        all_points.append(pts3d)
        all_normals.append(nrm3d)

        # 4) Accumulate quad mesh data (offset face indices)
        if qf.size > 0:
            all_quad_verts.append(qv)
            all_quad_faces.append(qf + vertex_offset)
            vertex_offset += qv.shape[0]

    if not all_points:
        return np.empty((0, 3), dtype=np.float32), np.empty((0, 3), dtype=np.float32), None

    points = np.vstack(all_points).astype(np.float32)
    normals = np.vstack(all_normals).astype(np.float32)

    # 5) Build lightweight analysis mesh (numpy only — no Ladybug overhead)
    analysis_mesh = None
    if all_quad_verts:
        analysis_mesh = AnalysisMesh(
            np.vstack(all_quad_verts),
            np.vstack(all_quad_faces),
            normals,  # correct outward-facing normals (1 per face = 1 per point)
        )

    return points, normals, analysis_mesh


def voxelize_and_clean(
    mesh: trimesh.Trimesh,
    voxel_size: float = 1.0,
    margin_frac: float = 0.2,
    min_voxels: int = 100,
) -> Tuple[torch.Tensor, np.ndarray, float, int]:
    """
    Convenience wrapper: voxelize a mesh and prune tiny connected components.

    Returns
    -------
    voxels : (D, D, D) uint8 torch.Tensor
        Binary occupancy (1 = inside/filled).
    origin : (3,) np.ndarray
        World-space min corner of the grid.
    grid_extent : float
        Physical cube size covered by the grid.
    resolution : int
        Voxel resolution (D).

    See Also
    --------
    voxelize_mesh, prune_voxels
    """
    vox, origin, scale, res = voxelize_mesh(mesh, voxel_size, margin_frac)
    clean = prune_voxels(vox, min_voxels)
    return clean, origin, scale, res


@session_cache("vox:{args[0].identifier}:{kwargs[voxel_size]}:{kwargs[margin_frac]}")
def voxelize_mesh(
    mesh: trimesh.Trimesh,
    voxel_size: float = 1.0,
    margin_frac: float = 0.2,
    device: torch.device = None
) -> Tuple[torch.Tensor, np.ndarray, float, int]:
    """
    Rasterize a watertight mesh into a padded binary voxel grid.

    Parameters
    ----------
    mesh : trimesh.Trimesh
    voxel_size : float
        Edge length of one voxel in world units.
    margin_frac : float
        Padding on each side as a fraction of the mesh AABB's max side.
    device : torch.device or None
        Target device for the returned tensor.

    Returns
    -------
    voxels : (D, D, D) uint8 torch.Tensor
        1 where inside/filled, 0 otherwise.
    origin : (3,) np.ndarray
        World-space min corner of the grid.
    grid_extent : float
        Physical size of the cubic domain.
    resolution : int
        Number of voxels per side (D).

    Notes
    -----
    - Uses trimesh ray-based voxelization and scipy cavity fill.
    - Grid is axis-aligned and cubic by construction.
    - No GPU dependency for voxelization itself (runs on CPU via trimesh).
    """

    # resolve a real device at runtime if none was passed
    if device is None:
        device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')

    if voxel_size <= 0 or margin_frac < 0:
        raise ValueError("voxelize_mesh: invalid voxel_size or margin_frac")

    bmin, bmax = mesh.bounds
    bbox = bmax - bmin
    max_dim = float(np.max(bbox))
    margin = max_dim * margin_frac
    side = max_dim + 2*margin
    resolution = int(np.ceil(side / voxel_size))
    _MAX_RES = 4096  # per-axis cap; memory protection is the 500M-voxel guard below
    if resolution > _MAX_RES:
        raise ValueError(
            f"Grid resolution {resolution} exceeds per-axis limit {_MAX_RES} "
            f"(domain {side:.1f} m / voxel {voxel_size:g} m). Increase voxel_size."
        )
    total_voxels = resolution ** 3
    if total_voxels > 500_000_000:
        mem_est_gb = total_voxels * 5 / (1024**3)
        _log.warning(
            "Large grid: %d³ = %s voxels (~%.1f GB). "
            "Consider increasing voxel_size for faster iteration.",
            resolution, f"{total_voxels:,}", mem_est_gb,
        )
    grid_extent  = resolution * voxel_size
    center = (bmin + bmax) / 2.0
    origin = center - grid_extent/2.0

    # Voxelize with trimesh.  The default 'subdivide' method produces
    # surface-only voxels; we then fill the interior.
    try:
        vox = mesh.voxelized(pitch=voxel_size)

        # Try trimesh's orthographic fill first — it casts rays from all
        # 6 axis directions and is robust to small gaps in the surface
        # shell (which binary_fill_holes cannot handle).
        try:
            vox = vox.fill(method='orthographic')
        except Exception as exc:
            _log.warning("Orthographic fill failed (%s), trying default fill", exc)
            try:
                vox = vox.fill()
            except Exception as exc2:
                _log.warning("Default fill also failed (%s), proceeding with surface-only voxels", exc2)

        raw_grid = vox.matrix  # (Dx, Dy, Dz) bool, tightly cropped to mesh AABB

        # Embed the cropped grid into the padded cubic grid.
        # trimesh's voxel origin may differ from ours, so we re-index.
        vox_origin = np.asarray(vox.transform[:3, 3])  # world-space origin of trimesh grid
        offset = np.round((vox_origin - origin) / voxel_size).astype(int)

        grid_np = np.zeros((resolution, resolution, resolution), dtype=bool)
        # Clip insertion to valid bounds
        src_start = np.maximum(-offset, 0)
        dst_start = np.maximum(offset, 0)
        src_end = np.minimum(np.array(raw_grid.shape), np.array(grid_np.shape) - offset)
        copy_shape = np.minimum(src_end - src_start, np.array(grid_np.shape) - dst_start)
        if (copy_shape > 0).all():
            slc_dst = tuple(slice(d, d + s) for d, s in zip(dst_start, copy_shape))
            slc_src = tuple(slice(s, s + sz) for s, sz in zip(src_start, copy_shape))
            grid_np[slc_dst] = raw_grid[slc_src]
    except Exception as e:
        raise RuntimeError(f"voxelize_mesh: trimesh voxelization failed: {e}")

    # --- Cavity fill: skip if orthographic fill left no interior voids ---
    # The padded grid guarantees corner [0,0,0] is empty exterior.
    # If all empty voxels form a single connected component (6-connectivity),
    # there are no sealed interior cavities and binary_fill_holes would be
    # a no-op.  This check is much cheaper than running the full fill.
    surface_count = int(grid_np.sum())
    if surface_count == 0:
        filled = grid_np
    else:
        empty_space = ~grid_np
        # 6-connectivity: cavities must be fully enclosed (not diagonally
        # connected to the exterior) to count as interior voids.
        _, num_empty_components = ndi.label(empty_space)
        if num_empty_components <= 1:
            # All empty space is one connected region (the exterior) —
            # no interior cavities exist, skip the expensive fill.
            _log.debug(
                "voxelize_mesh: no interior cavities detected "
                "(single exterior component) — skipping binary_fill_holes"
            )
            filled = grid_np
        else:
            # Multiple empty regions → some are sealed cavities.
            # Run binary_fill_holes to seal them.
            filled = ndi.binary_fill_holes(grid_np)
            cavities_sealed = int(filled.sum()) - surface_count
            _log.debug(
                "voxelize_mesh: binary_fill_holes sealed %d cavity voxels "
                "(%d empty components detected)",
                cavities_sealed, num_empty_components,
            )

    _log.info(
        "voxelize_mesh: watertight=%s surface_voxels=%d filled_voxels=%d "
        "fill_ratio=%.1fx",
        mesh.is_watertight, surface_count, int(filled.sum()),
        int(filled.sum()) / max(surface_count, 1),
    )

    voxels = torch.from_numpy(filled.astype(np.uint8)).to(device)
    return voxels, origin, grid_extent, resolution

def prune_voxels(
    voxels: torch.Tensor,
    min_voxels: int
) -> torch.Tensor:
    """
    Remove connected components smaller than `min_voxels` (26-connectivity).

    Parameters
    ----------
    voxels : (D, D, D) uint8/bool torch.Tensor
    min_voxels : int
        Size threshold; components with fewer voxels are removed.

    Returns
    -------
    cleaned : (D, D, D) uint8 torch.Tensor
        Binary occupancy on the same device as `voxels`.

    Notes
    -----
    - Used on the smoothed path (`apply_smoothing=True`) prior to SDF smoothing.
    """
    arr = voxels.detach().cpu().numpy().astype(bool)
    struct26 = np.ones((3, 3, 3), dtype=bool)
    labeled, num = ndi.label(arr, structure=struct26)
    counts = np.bincount(labeled.ravel())
    small = np.where((counts < int(min_voxels)) & (np.arange(counts.size) != 0))[0]
    if small.size:
        arr[np.isin(labeled, small)] = False
    return torch.from_numpy(arr.astype(np.uint8)).to(voxels.device)

def prune_voxels_morph(
    voxels: torch.Tensor,
    min_voxels: int,
) -> torch.Tensor:
    """
    Gentle cleanup for the cubic (unsmoothed) path.

    Steps
    -----
    1. Remove tiny connected components (26-connectivity).
    2. Apply a 3×3×3 majority filter (keeps voxels with ≥3 neighbors) to
       suppress isolated specks.
    3. Run a single binary closing with a 6-connected structuring element to
       seal pinholes without shrinking slabs.

    Parameters
    ----------
    voxels : (D, D, D) uint8/bool torch.Tensor
    min_voxels : int

    Returns
    -------
    cleaned : (D, D, D) uint8 torch.Tensor
    """
    arr = voxels.detach().cpu().numpy().astype(bool)
    # 26-connectivity for component labeling (keep connectivity liberal here)
    struct26 = np.ones((3, 3, 3), dtype=bool)
    labeled, _ = ndi.label(arr, structure=struct26)
    counts = np.bincount(labeled.ravel())
    # drop small components (ignore label 0 = background)
    small = np.where((counts < int(min_voxels)) & (np.arange(counts.size) != 0))[0]
    if small.size:
        arr[np.isin(labeled, small)] = False

    # Gentle denoise: majority in 3×3×3 — only REMOVE noisy voxels,
    # never ADD new ones (prevents spilling beyond the max volume).
    k = np.ones((3, 3, 3), dtype=np.int16)
    cnt = ndi.convolve(arr.astype(np.int16), k, mode="constant", cval=0)
    # A voxel must have >= 3 filled neighbors (of 27 including self) to survive.
    # Crucially: only apply to voxels that were already ON. Never turn OFF→ON.
    arr = arr & (cnt >= 3)

    return torch.from_numpy(arr.astype(np.uint8)).to(voxels.device)

@njit(cache=True, parallel=True)
def _pm_stencil_step(src, dst, k2, tau):
    """Single Perona-Malik diffusion step (6-neighbor 3D Jacobi stencil).

    Reads from ``src`` and writes interior voxels of ``dst`` — a Jacobi
    update, which is safe to parallelize (numba ``prange`` over z-slabs)
    because no cell reads a value written in the same step.  Operates on
    *padded* arrays: the border ring is left unchanged by this kernel;
    the caller refreshes it after each step to maintain the Neumann
    (zero-flux) boundary condition.

    Parameters
    ----------
    src : (Nz+2, Ny+2, Nx+2) float32 ndarray
        Padded SDF read by the stencil (not modified).
    dst : (Nz+2, Ny+2, Nx+2) float32 ndarray
        Output buffer; interior voxels are overwritten.
    k2 : float
        Squared edge-stopping scale (k^2).
    tau : float
        Diffusion time step (keep <= 0.18 for stability).
    """
    nz, ny, nx = src.shape
    for z in prange(1, nz - 1):
        for y in range(1, ny - 1):
            for x in range(1, nx - 1):
                c = src[z, y, x]
                # Forward/backward finite differences to 6 face-neighbors
                dxp = src[z, y, x + 1] - c
                dxm = c - src[z, y, x - 1]
                dyp = src[z, y + 1, x] - c
                dym = c - src[z, y - 1, x]
                dzp = src[z + 1, y, x] - c
                dzm = c - src[z - 1, y, x]
                # Edge-stopping coefficients: c_i = exp(-(grad_i / k)^2)
                # Small gradients -> c ~ 1 (smooth), large -> c ~ 0 (preserve)
                div = (math.exp(-(dxp * dxp) / k2) * dxp
                     - math.exp(-(dxm * dxm) / k2) * dxm
                     + math.exp(-(dyp * dyp) / k2) * dyp
                     - math.exp(-(dym * dym) / k2) * dym
                     + math.exp(-(dzp * dzp) / k2) * dzp
                     - math.exp(-(dzm * dzm) / k2) * dzm)
                dst[z, y, x] = c + tau * div


def _pm_anisotropic_diffuse(sdf: np.ndarray, iters: int = 16, k: float = 1.0, tau: float = 0.15) -> np.ndarray:
    """
    Perona-Malik anisotropic diffusion on a 3D scalar field.

    Parameters
    ----------
    sdf : (Z, Y, X) float32 np.ndarray
        Signed-distance field in voxel units (positive inside).
    iters : int
        Number of explicit diffusion steps.
    k : float
        Edge-stopping scale (larger = more smoothing across gradients).
    tau : float
        Time step; for a 6-neighbor stencil keep tau <= 0.18 for stability.

    Returns
    -------
    filtered : (Z, Y, X) float32 np.ndarray

    Notes
    -----
    - Uses a numba-compiled parallel Jacobi stencil: each step reads the
      previous buffer and writes a second one, so z-slabs can run on all
      cores (~10x over the serial in-place sweep on a 306-cube grid).
    - Used inside ``_voxel_presmooth``; typically applied only within a narrow
      band around the zero-level set to avoid volume drift.
    """
    iters = int(iters)
    if iters <= 0:
        return sdf.astype(np.float32, copy=True)

    k2 = float(k) * float(k)
    if k2 == 0.0:
        k2 = 1e-12  # guard against k=0
    tau_f = float(tau)

    # Pad with edge values (Neumann boundary: zero normal derivative).
    # The border ring is never updated by the stencil, so it acts as
    # a fixed boundary condition throughout all iterations.
    src = np.pad(sdf.astype(np.float32), 1, mode="edge")
    dst = src.copy()

    for _ in range(iters):
        _pm_stencil_step(src, dst, k2, tau_f)
        # Refresh border from interior to maintain Neumann condition
        # after each step (interior voxels adjacent to the border may
        # have changed, so the border must reflect the new edge values).
        dst[0, :, :] = dst[1, :, :]
        dst[-1, :, :] = dst[-2, :, :]
        dst[:, 0, :] = dst[:, 1, :]
        dst[:, -1, :] = dst[:, -2, :]
        dst[:, :, 0] = dst[:, :, 1]
        dst[:, :, -1] = dst[:, :, -2]
        src, dst = dst, src  # ping-pong buffers

    # Strip padding and return interior (src holds the latest step)
    return src[1:-1, 1:-1, 1:-1].copy()

def _voxel_presmooth(field_bool: np.ndarray) -> np.ndarray:
    """
    Build a smoothed signed-distance field (SDF) from a boolean occupancy grid.

    Pipeline
    --------
    1) Compute inside/outside Euclidean distance transforms and form SDF = d_in − d_out.
    2) Apply a light Gaussian blur (voxel units).
    3) Run Perona–Malik diffusion in a narrow band |SDF| < ~2 voxels to reduce
       terracing while preserving edges.

    Parameters
    ----------
    field_bool : (Z, Y, X) bool/uint8 np.ndarray

    Returns
    -------
    sdf : (Z, Y, X) float32 np.ndarray
        Smoothed SDF to be contoured by marching cubes.
    """
    occ = field_bool.astype(bool)

    # Step 1: Build a signed distance field via dual distance transforms.
    # d_in  = Euclidean distance from each occupied voxel to the nearest empty one.
    # d_out = distance from each empty voxel to the nearest occupied one.
    # SDF = d_in − d_out: positive inside the volume, negative outside,
    # zero at the boundary.  This gives a proper signed distance with
    # consistent sign convention for marching cubes.
    # The two transforms are independent and scipy releases the GIL, so
    # run them concurrently (~1.9x on large grids).
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as _pool:
        _f_in = _pool.submit(distance_transform_edt, occ)
        _f_out = _pool.submit(distance_transform_edt, ~occ)
        d_in, d_out = _f_in.result(), _f_out.result()
    sdf0 = (d_in - d_out).astype(np.float32)

    # Step 2: Light Gaussian blur (σ = 0.3 voxels) to remove voxel-scale
    # staircase artifacts without over-diffusing sharp features.
    sdf = gaussian_filter(sdf0, sigma=0.3, mode="nearest")

    # Step 3: Edge-preserving Perona–Malik diffusion, restricted to a narrow
    # band of |SDF| < 2 voxels around the zero-level isosurface.
    # Limiting to the band prevents interior volume drift while smoothing
    # the terraced surface contour.
    band = np.abs(sdf) < 2.0
    if np.any(band):
        # Set the PM edge-stopping scale k to 1.05× the median gradient
        # magnitude within the band.  For a true SDF, |∇SDF| ≈ 1 everywhere;
        # the 5% margin ensures that normal gradients diffuse freely while
        # sharp transitions (features, corners) are preserved.
        g = np.gradient(sdf)
        mag = np.sqrt(g[0]**2 + g[1]**2 + g[2]**2)
        k = max(1.05 * float(np.median(mag[band])), 1e-6)
        sdf_band = _pm_anisotropic_diffuse(sdf, iters=16, k=k, tau=0.15)
        # Restore original SDF outside the band — only the surface zone changes.
        sdf = np.where(band, sdf_band, sdf0)
    else:
        sdf = sdf0
    return sdf

def _volume_matched_threshold(sdf: np.ndarray, target_inside_voxels: int) -> float:
    """
    Choose an isosurface value so that the number of voxels with SDF > iso
    matches `target_inside_voxels`.

    Parameters
    ----------
    sdf : (Z, Y, X) float32 np.ndarray
        Smoothed signed-distance field.
    target_inside_voxels : int
        Count of 'inside' cells in the original binary occupancy.

    Returns
    -------
    iso : float
        Threshold for marching cubes.

    Notes
    -----
    - Offsets the iso-value away from 0 to compensate for smoothing-induced
      thinning or thickening.
    """
    flat = sdf.ravel()
    n = flat.size
    tgt = int(max(0, min(n, target_inside_voxels)))
    idx = n - tgt
    # guard for degenerate cases
    if idx <= 0: 
        return float(np.max(flat))
    if idx >= n:
        return float(np.min(flat))
    return float(np.partition(flat, idx)[idx])

def _median_edge_length(m: trimesh.Trimesh) -> float:
    """Median edge length of a trimesh, used to normalize Taubin smoothing.

    Returns 1.0 for empty meshes to avoid division by zero.
    """
    el = m.edges_unique_length
    return float(np.median(el)) if len(el) else 1.0

def polish_mesh_taubin(mesh: trimesh.Trimesh, iters: int = 2) -> trimesh.Trimesh:
    """
    Apply a tiny, scale-normalized Taubin pass to knock down micro-ripples.

    Parameters
    ----------
    mesh : trimesh.Trimesh
    iters : int, default 2
        Small integer in [0, 6]. If 0, the mesh is returned unchanged.

    Returns
    -------
    mesh : trimesh.Trimesh

    Notes
    -----
    - Uses fixed stable parameters (λ≈0.28, ν≈−0.31) and normalizes by the
      median edge length to avoid scale sensitivity.
    - Intended only after the SDF+MC path. Keep very small to avoid shape drift.
    """
    if iters <= 0 or len(mesh.vertices) == 0:
        return mesh

    # Taubin (1995) signal-processing smoothing parameters.
    # lambda > 0 contracts the mesh (smoothing pass),
    # nu < 0 inflates it (anti-shrinkage pass).
    # These standard values ensure volume preservation.
    # Ref: Taubin, G. 1995. "A Signal Processing Approach to Fair Surface
    #      Design." SIGGRAPH.
    lamb, nu = 0.28, -0.31

    # Normalize to avoid scale sensitivity
    V = mesh.vertices.view(np.ndarray)
    c = V.mean(axis=0)
    V -= c
    s = _median_edge_length(mesh)
    if not np.isfinite(s) or s <= 0:
        s = 1.0
    V /= s

    # Do the tiny polish
    from trimesh.smoothing import filter_taubin
    filter_taubin(mesh, lamb=lamb, nu=nu, iterations=int(min(iters, 6)))

    # Restore original scale and world-space position.
    # Do NOT call mesh.rezero() — it translates the bbox min to (0,0,0),
    # stripping the world-space offset set by apply_translation(min_corner).
    mesh.vertices[:] = mesh.vertices * s + c
    mesh.update_faces(mesh.nondegenerate_faces())
    return mesh


def mesh_from_voxels(
    voxels: torch.Tensor,
    min_corner: np.ndarray,
    voxel_size: float
) -> trimesh.Trimesh:
    """
    Construct a blocky (cubic) mesh from a binary occupancy grid.

    Parameters
    ----------
    voxels : (D, D, D) uint8/bool torch.Tensor
    min_corner : (3,) array_like
        World-space origin of the grid (maps index [0,0,0] to this point).
    voxel_size : float
        Size of one voxel in world units.

    Returns
    -------
    mesh : trimesh.Trimesh
        Unprocessed triangle mesh (process=False). Call `cleanup_mesh` next.

    See Also
    --------
    mesh_from_voxels_smoothed, mesh_from_voxels_select
    """
    verts, faces = _cubic_mesh_from_occupancy(voxels, min_corner, voxel_size)
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def _cubic_mesh_from_occupancy(
    voxels: torch.Tensor,
    min_corner: np.ndarray,
    voxel_size: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Emit axis-aligned cuboid faces using a shared vertex grid.

    Uses a (D+1)³ vertex grid so neighboring faces share vertices — no
    duplicates. For a D=180 grid this is ~6M vertices vs ~40M+ with the
    per-quad approach. Face indices reference the shared grid directly.

    Parameters
    ----------
    voxels : (D, D, D) uint8/bool torch.Tensor
        Binary occupancy grid.
    min_corner : (3,) array_like
        World-space origin of grid index [0,0,0].
    voxel_size : float
        Edge length of one voxel in world units.

    Returns
    -------
    vertices : (V, 3) float32 ndarray   (only vertices referenced by faces)
    faces : (F, 3) int32 ndarray
    """
    occ = voxels.detach().cpu().numpy().astype(bool)
    D = occ.shape[0]
    s = float(voxel_size)

    # Pad with empty voxels on all sides so neighbor lookups at grid
    # boundaries don't need special-case bounds checking.
    padded = np.pad(occ, 1, mode='constant', constant_values=False)

    # Shared vertex grid: a D³ voxel grid has (D+1)³ corner vertices.
    # Flat index for corner (i,j,k): i*(D+1)² + j*(D+1) + k  (row-major).
    # Sharing vertices between adjacent quads avoids duplicates and keeps
    # the mesh manifold-friendly.
    D1 = D + 1
    D1sq = D1 * D1

    # 6 face definitions — one per axis-aligned direction.
    # Each entry: (neighbor offset, 4 corner offsets relative to voxel (i,j,k)).
    # Corner offsets index into the (D+1)³ vertex grid.
    # Winding is counter-clockwise when viewed from outside (outward normal).
    face_defs = [
        # +X face: exposed at (i+1, *, *). Quad corners at i+1 plane.
        ((1, 0, 0), [(1,0,0), (1,1,0), (1,1,1), (1,0,1)]),
        # -X face
        ((-1, 0, 0), [(0,0,1), (0,1,1), (0,1,0), (0,0,0)]),
        # +Y face
        ((0, 1, 0), [(0,1,0), (0,1,1), (1,1,1), (1,1,0)]),
        # -Y face
        ((0, -1, 0), [(1,0,0), (1,0,1), (0,0,1), (0,0,0)]),
        # +Z face
        ((0, 0, 1), [(0,0,1), (1,0,1), (1,1,1), (0,1,1)]),
        # -Z face
        ((0, 0, -1), [(0,0,0), (0,1,0), (1,1,0), (1,0,0)]),
    ]

    all_faces = []

    for (si, sj, sk), corners in face_defs:
        # Find exposed faces: occupied voxels whose neighbor in (si,sj,sk) is empty.
        # Using padded array with +1 offset.
        exposed = occ & ~padded[1+si:D+1+si, 1+sj:D+1+sj, 1+sk:D+1+sk]
        if not exposed.any():
            continue

        # Get voxel indices of exposed faces
        ei, ej, ek = np.nonzero(exposed)  # each (M,)

        # Map 4 quad corners to flat vertex indices in the (D+1)³ grid
        v = np.empty((ei.shape[0], 4), dtype=np.int32)
        for c, (di, dj, dk) in enumerate(corners):
            v[:, c] = (ei + di) * D1sq + (ej + dj) * D1 + (ek + dk)

        # Two triangles per quad: (0,1,2) and (0,2,3)
        tri1 = v[:, [0, 1, 2]]
        tri2 = v[:, [0, 2, 3]]
        all_faces.append(tri1)
        all_faces.append(tri2)

    if not all_faces:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.int32)

    faces_all = np.vstack(all_faces)

    # Only emit vertices that are actually referenced by faces.
    # Most of the (D+1)³ grid corners are interior and never used.
    used = np.unique(faces_all)

    # Convert flat vertex indices back to (i,j,k) grid coordinates,
    # then to world-space positions.
    gi = used // D1sq
    gj = (used % D1sq) // D1
    gk = used % D1
    verts = np.column_stack([
        min_corner[0] + gi * s,
        min_corner[1] + gj * s,
        min_corner[2] + gk * s,
    ]).astype(np.float32)

    # Remap face indices from the sparse (D+1)³ space into a compact
    # [0, len(used)) range so the vertex array has no gaps.
    remap = np.empty(used.max() + 1, dtype=np.int32)
    remap[used] = np.arange(used.size, dtype=np.int32)
    faces_compact = remap[faces_all]

    return verts, faces_compact

def mesh_from_voxels_smoothed(
    voxels: torch.Tensor,
    min_corner: np.ndarray,
    voxel_size: float
) -> trimesh.Trimesh:
    """
    Construct a smooth mesh by conturing a smoothed SDF with marching cubes.

    Parameters
    ----------
    voxels : (D, D, D) uint8/bool torch.Tensor
        Binary occupancy (1 = inside).
    min_corner : (3,) array_like
        World-space grid origin.
    voxel_size : float
        World units per voxel (passed as `pitch` to marching cubes).

    Returns
    -------
    mesh : trimesh.Trimesh
        Triangle mesh positioned in world coordinates.

    Notes
    -----
    - Internally calls `_voxel_presmooth` and chooses an iso-value via
      `_volume_matched_threshold` to preserve volume.
    - Marching cubes runs directly on the continuous SDF so the surface
      interpolates smoothly between voxel centers.  (trimesh's
      ``matrix_to_marching_cubes(threshold=...)`` would binarize the field
      first, throwing the smoothing away.)
    """
    # Work on CPU ndarray
    occ = voxels.detach().to('cpu').numpy().astype(bool)
    field = _voxel_presmooth(occ)  # smoothed SDF
    # pick iso to match original volume so medium-thick parts don't disappear
    iso = _volume_matched_threshold(field, int(occ.sum()))

    s = float(voxel_size)
    # Pad with a strongly-outside value so surfaces touching the grid
    # boundary are closed rather than left open.
    pad_val = float(field.min()) - 1.0
    padded = np.pad(field, 1, mode="constant", constant_values=pad_val)
    # skimage requires the level to lie strictly inside the data range.
    lo, hi = float(padded.min()), float(padded.max())
    if hi <= lo:
        return trimesh.Trimesh()  # degenerate (constant) field — nothing to mesh
    iso = float(np.clip(iso, lo + 1e-6 * max(abs(lo), 1.0), hi - 1e-6 * max(abs(hi), 1.0)))

    from skimage import measure
    verts, faces, _normals, _values = measure.marching_cubes(
        padded, level=iso, spacing=(s, s, s),
    )
    # Index i samples the SDF at the voxel CENTER, which sits at
    # min_corner + (i + 0.5) * s in world space.  Remove the 1-voxel pad
    # (-s) and add the half-voxel center offset (+0.5 s).
    verts = verts - 0.5 * s
    # skimage's winding points normals inward for a positive-inside field;
    # reverse each face so normals face outward (positive enclosed volume).
    faces = faces[:, ::-1]
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    # Add world-space origin
    mesh.apply_translation(min_corner)
    return mesh

def mesh_from_voxels_select(
    voxels: torch.Tensor,
    min_corner: np.ndarray,
    voxel_size: float,
    apply_smoothing: bool
) -> trimesh.Trimesh:
    """
    Dispatch to cubic or SDF-smoothed meshing based on `apply_smoothing`.

    Returns
    -------
    mesh : trimesh.Trimesh

    See Also
    --------
    mesh_from_voxels, mesh_from_voxels_smoothed
    """
    return (
        mesh_from_voxels_smoothed(voxels, min_corner, voxel_size)
        if apply_smoothing else
        mesh_from_voxels(voxels, min_corner, voxel_size)
    )

def cleanup_mesh(
    mesh: trimesh.Trimesh,
    min_face_count: int = 100,
    light: bool = False,
) -> trimesh.Trimesh:
    """
    Repair and prune small fragments from a mesh.

    Parameters
    ----------
    mesh : trimesh.Trimesh
    min_face_count : int, default 100
        Fragments with fewer faces than this are discarded.
    light : bool, default False
        If True, skip expensive repair steps (fill_holes, fix_inversion,
        merge_vertices). Use for cubic meshes which are already watertight
        with correct winding. ~10x faster on large meshes.

    Returns
    -------
    mesh : trimesh.Trimesh
        Cleaned mesh (may be a concatenation of surviving components).
    """
    if light:
        # Cubic mesher produces watertight meshes with consistent winding.
        # Only remove degenerate/duplicate faces and prune small fragments.
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.update_faces(mesh.unique_faces())
        mesh.remove_unreferenced_vertices()
    else:
        # Full repair for marching-cubes output
        repair.fix_winding(mesh)
        repair.fix_normals(mesh, multibody=True)
        repair.fix_inversion(mesh, multibody=True)
        repair.fill_holes(mesh)
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.update_faces(mesh.unique_faces())
        mesh.merge_vertices()
        mesh.remove_unreferenced_vertices()
    parts = mesh.split(only_watertight=False)
    large = [p for p in parts if len(p.faces) >= min_face_count]
    return trimesh.util.concatenate(large) if large else mesh


