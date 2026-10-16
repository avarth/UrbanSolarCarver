"""
UrbanSolarCarver: test-surface sampling

Samples the test surfaces into the points and normals that rays start
from, and the analysis-mesh quads that show one face per sample point.
Used by preprocessing.

Pipeline entry point
--------------------
sample_surface(insolation_mesh, settings)
    discretize_surface_with_normals with the preprocessing settings; raises
    when no sample points are produced.

Public API
----------
sample_planar_surface(mesh, sample_step=1.0, include_boundary=True, edge_taper=0.0)
    Sample one planar connected component on a regular grid. Returns points,
    normals, analysis-mesh quads (vertices + faces), and edge-taper weights.

discretize_surface_with_normals(mesh, sample_step=1.0, coplanarity_tol_deg=5.0,
                                edge_taper=0.0)
    Split the mesh into connected components, sample each planar one, and
    return points, normals, an AnalysisMesh, weights, and taper statistics.

AnalysisMesh
    Quad mesh with one face per sample point; serialised to analysis_mesh.json.

Internal helpers
----------------
plane_frame(surface_normal)
    Orthonormal in-plane basis for planar sampling.

_mesh_boundary_loops(mesh), _sample_boundary_edges(polygon, ...)
    Boundary extraction and extra samples along boundary edges.

Data types and units
--------------------
- Points and normals: np.ndarray, shape (N, 3), world units.
"""

import numpy as np
import trimesh
from scipy.spatial import cKDTree
from shapely import contains_xy
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient

from .errors import InputError
from .run_context import report_issue
from .stage_settings import PreprocessingSettings


def sample_surface(insolation_mesh, settings: PreprocessingSettings):
    """
    Sample quasi-planar patches to produce point/normal sets for carving.

    Parameters
    ----------
    insolation_mesh : trimesh.Trimesh
        Test surfaces; each connected component should be one flat panel.
    settings : PreprocessingSettings
        Supplies ``grid_step`` (sample spacing) and ``edge_taper``.

    Returns
    -------
    sample_points : np.ndarray (N, 3), float32
    sample_normals : np.ndarray (N, 3), float32
    analysis_mesh : AnalysisMesh or None
        The analysis mesh whose face centroids are the sample points.
    sample_weights : np.ndarray (N,)
        Edge-taper design weights in [0, 1] (all ones when
        ``settings.edge_taper`` is 0).
    taper_stats : list of dict
        Per-component taper statistics (empty when edge_taper is 0).

    Raises
    ------
    InputError
        If no points are sampled from the insolation surface.
    """
    sample_points, sample_normals, analysis_mesh, sample_weights, taper_stats = (
        discretize_surface_with_normals(
            insolation_mesh, settings.grid_step, edge_taper=settings.edge_taper
        )
    )

    if sample_points.size == 0:
        n_components = len(insolation_mesh.split(only_watertight=False))
        raise InputError(
            "No points sampled from test surfaces (insolation mesh). "
            "The mesh has {:d} connected component(s), but none produced sample points. "
            "Most likely cause: test_surfaces is a joined polysurface (e.g. an extruded block "
            "boundary) whose wall panels share corner edges, so the whole block is treated as "
            "one non-planar component and rejected. "
            "Fix: explode your polysurfaces into individual flat panels in Grasshopper before "
            "connecting to USC_Preprocess. Also check that grid_step ({:g} m) is smaller than "
            "your smallest surface.".format(n_components, settings.grid_step)
        )
    return sample_points, sample_normals, analysis_mesh, sample_weights, taper_stats


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
        Unit vectors with cross(axis_u, axis_v) equal to the unit normal, so
        (axis_u, axis_v, normal) is a right-handed frame.

    Raises
    ------
    ValueError
        If `surface_normal` has near-zero length.

    Notes
    -----
    - The normal is normalized internally.
    - The reference axis is X, or Y when the normal is within about 26 deg of
      X, so the cross product never degenerates.
    - The result depends only on the normal, so panels with the same normal
      get the same frame (up to the sign of axis_u when the normal is negated).
    - Used by `sample_planar_surface` to build a local 2D sampling frame.
    """
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
    axis_u = np.cross(plane_normal, ref_axis)
    axis_u /= np.linalg.norm(axis_u)
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

    Walks each boundary ring (exterior + holes) at intervals of at most
    *sample_step*, moves each candidate inward by ``inset_fraction *
    sample_step`` (or less, for thin polygons), and keeps only candidates
    farther than ``min_dist_fraction * sample_step`` from every interior
    grid point and from every other kept candidate.

    Parameters
    ----------
    polygon : shapely Polygon
        Footprint in the local 2D frame.
    sample_step : float
        Grid spacing in world units.
    interior_pts_2d : (M, 2) np.ndarray
        Grid points already selected inside the polygon.
    min_dist_fraction, inset_fraction : float
        Minimum spacing and inward offset, as fractions of sample_step.

    Returns an (K, 2) array of accepted edge points in the polygon's local 2D
    coordinate frame, or an empty (0, 2) array if none qualify.
    """
    inset = inset_fraction * sample_step
    min_dist = min_dist_fraction * sample_step
    # Tiny buffer so points near (but not exactly on) the boundary pass
    # Shapely's strict-interior containment test.
    test_poly = polygon.buffer(sample_step * 1e-3)
    candidates = []

    # Exterior counter-clockwise, holes clockwise: the polygon's interior is
    # then on the left of the direction of travel along every ring.
    polygon = orient(polygon, sign=1.0)
    for ring in [polygon.exterior, *polygon.interiors]:
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

            nx, ny = -ty, tx  # inward: left of the tangent

            # Try progressively smaller insets: in thin polygons the full
            # inset can land outside the boundary.
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


def _mesh_boundary_loops(mesh: trimesh.Trimesh) -> "list[list[int]]":
    """Extract the mesh's boundary loops as ordered vertex-index rings.

    Interior edges are shared by 2 faces; boundary edges belong to only
    one.  The boundary edges are chained into loops by a greedy walk over
    their adjacency graph, removing each edge as it is visited so each
    loop is extracted once.  A closed loop ends with its start vertex
    repeated.  A walk that stops before returning to its start (an open
    chain) is still returned if it has more than 2 entries; shorter walks
    are discarded.
    """
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
    return boundary_loops


def sample_planar_surface(
    mesh: trimesh.Trimesh,
    sample_step: float = 1.0,
    include_boundary: bool = True,
    edge_taper: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Sample points on a regular grid over one planar submesh.

    Parameters
    ----------
    mesh : trimesh.Trimesh
        Single planar connected component (convex or not, with or without holes).
    sample_step : float, default 1.0
        Spacing of the sampling grid in world units.
    include_boundary : bool, default True
        If True, keep grid points that fall on the polygon boundary; otherwise
        drop them.  Extra points seeded along the boundary edges
        (`_sample_boundary_edges`) are added in both cases.
    edge_taper : float, default 0.0
        Design-constraint taper distance (world units).  When > 0, each
        sample gets a weight ramping linearly from 0 at the component
        outline (exterior and holes) to 1 at ``edge_taper`` from it.

    Returns
    -------
    points : (N, 3) float64 np.ndarray
        Sample locations in world coordinates.
    normals : (N, 3) np.ndarray
        Unit normal, the same for every point, oriented to agree with the
        area-weighted normal of the mesh faces.
    quad_verts : (4N, 3) float64 np.ndarray
        Corner positions of one analysis-mesh quad per sample point.
    quad_faces : (N, 4) int32 np.ndarray
        Vertex indices of each quad (indices into `quad_verts`).
    weights : (N,) float32 np.ndarray
        Edge-taper design weights in [0, 1]; all ones when edge_taper == 0.

    Notes
    -----
    - Builds a local 2D grid in the plane (see `plane_frame`) and rasterizes the
      polygon footprint to select in-polygon grid sites.
    - If no grid site falls inside the polygon, one point guaranteed to lie
      inside it (Shapely's ``representative_point``) is used as the single
      sample.
    - Used by `discretize_surface_with_normals` for planar-only sampling.
    """
    # 1) Compute centroid and best-fit plane normal via principal component
    #    analysis (PCA).  The eigenvector of the vertex covariance matrix
    #    with the smallest eigenvalue is the direction of least variance,
    #    i.e. the normal of the plane that best fits the vertices.
    vertices = mesh.vertices                # (N, 3)
    centroid = vertices.mean(axis=0)        # (3,)
    cov_mat = np.cov((vertices - centroid).T)
    evals, evecs = np.linalg.eigh(cov_mat)
    plane_normal = evecs[:, np.argmin(evals)]

    # 2) Build a local 2D orthonormal frame (u, v) lying in the plane.
    #    All subsequent sampling happens in this 2D coordinate system.
    axis_u, axis_v = plane_frame(plane_normal)

    # 3) Extract the mesh's boundary loops (ordered vertex-index rings).
    boundary_loops = _mesh_boundary_loops(mesh)

    # 4) Project loops into the local 2D frame and identify exterior/interior.
    #    Each 3D vertex is projected to (u, v) by dotting with the plane
    #    basis vectors.  The loop enclosing the largest area is the exterior
    #    boundary; all others become holes.  Shapely takes holes from the
    #    `holes` argument regardless of ring direction, so reversing them
    #    has no effect on the result.
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

    # 5) Generate a regular 2D sampling grid over the polygon's bounding box.
    #    The grid is aligned to the world origin projected into this face's
    #    local 2D frame.  Because plane_frame() returns the same (u, v) axes
    #    for all faces sharing the same normal, coplanar submeshes get grids
    #    on the same world-space lattice, which avoids phase-shift banding
    #    between adjacent panels at coarse grid steps.
    xmin, ymin, xmax, ymax = planar_polygon.bounds
    world_ref_u = -np.dot(centroid, axis_u)  # world origin (0,0,0) in local u
    world_ref_v = -np.dot(centroid, axis_v)  # world origin (0,0,0) in local v
    # A lattice line that falls on the polygon's edge (e.g. every facade's
    # ground edge when the frame origin is at ground level) gives a remainder
    # of ~0 or ~sample_step depending on rounding noise; snap both to exactly
    # 0 so the edge row is treated the same way on every run and position.
    tol = sample_step * 1e-6

    def _phase(ref, lo):
        r = (ref - lo) % sample_step
        return 0.0 if (r < tol or r > sample_step - tol) else r
    x0 = xmin + _phase(world_ref_u, xmin)
    y0 = ymin + _phase(world_ref_v, ymin)
    # The upper bound includes a lattice line lying on the far edge, as the
    # phase snap does for the near edge, so both edges are treated alike.
    grid_x = np.arange(x0, xmax + tol, sample_step)
    grid_y = np.arange(y0, ymax + tol, sample_step)
    grid_X, grid_Y = np.meshgrid(grid_x, grid_y)

    # 6) Optionally inflate the polygon by a tiny epsilon so that points
    #    lying exactly on the boundary are included (Shapely's contains_xy
    #    is a strict-interior test).
    if include_boundary:
        buffer_epsilon = sample_step * 1e-3
        test_polygon = planar_polygon.buffer(buffer_epsilon)
    else:
        test_polygon = planar_polygon

    # 7) Rasterize: keep only grid points that fall inside the polygon.
    inside_mask = contains_xy(test_polygon, grid_X.ravel(), grid_Y.ravel()).reshape(grid_X.shape)
    points_2d = np.vstack((grid_X[inside_mask], grid_Y[inside_mask])).T  # (M, 2)

    # 8) Edge seeding: fill gaps along polygon boundary where the grid
    #    doesn't reach close enough to the edges.
    edge_pts = _sample_boundary_edges(planar_polygon, sample_step, points_2d)
    if edge_pts.size > 0:
        points_2d = np.vstack([points_2d, edge_pts]) if points_2d.size > 0 else edge_pts

    # Fall back to one sample when the grid is too coarse to produce any
    # points inside the polygon.  representative_point lies inside the
    # polygon even when it is non-convex (the centroid may not).
    if len(points_2d) == 0 and planar_polygon.area > 0:
        rep = planar_polygon.representative_point()
        points_2d = np.array([[rep.x, rep.y]])

    # Edge-taper design weights: exact 2D distance from each sample to the
    # component outline (exterior ring and holes), ramped linearly over
    # `edge_taper`.  The polygon is the welded component boundary, so
    # internal seams of exploded-but-coincident panels do not count as
    # edges (trimesh merges duplicate vertices at load).
    if edge_taper > 0.0 and len(points_2d) > 0:
        import shapely
        dists = shapely.distance(
            shapely.points(points_2d), planar_polygon.boundary
        )
        point_weights = np.clip(
            np.asarray(dists, dtype=np.float64) / float(edge_taper), 0.0, 1.0
        ).astype(np.float32)
    else:
        point_weights = np.ones(len(points_2d), dtype=np.float32)

    # 9) Lift the 2D samples back to 3D world coordinates (inverse of the
    #    projection): p = centroid + u * axis_u + v * axis_v.
    points_3d = (
        centroid
        + points_2d[:, 0:1] * axis_u
        + points_2d[:, 1:2] * axis_v
    )  # (M, 3)

    # 10) Assign normals.  The PCA normal may point either way; flip it
    #     to agree with the area-weighted face normal (a single face may
    #     have zero area and a zero normal).  Also flip
    #     axis_v so cross(axis_u, axis_v) stays equal to the normal; the
    #     quads built below then wind counter-clockwise around it, which
    #     viewers such as Plotly and Rhino use for front-face lighting.
    face_normal = (mesh.face_normals * mesh.area_faces[:, None]).sum(axis=0)
    if np.dot(face_normal, plane_normal) < 0:
        plane_normal = -plane_normal
        axis_v = -axis_v  # flip one axis so cross(u,v) matches new normal
    point_normals = np.tile(plane_normal, (len(points_3d), 1))  # (M, 3)

    # 11) Build analysis-mesh quad data.  Each sample point becomes a
    #     square quad centred on it, with corners at ±sample_step/2 along
    #     the plane's (u, v) axes.  Quads do not share vertices (4 per
    #     quad), and quads of edge-seeded points may overlap their neighbours.
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

    return points_3d, point_normals, quad_verts_3d, quad_faces, point_weights

class AnalysisMesh:
    """One quad per sample point: the patch of test surface each point stands for.

    Written to ``analysis_mesh.json`` by preprocessing, for visualising
    sampling density or per-point results.

    Attributes
    ----------
    vertices : (V, 3) float64 array of quad corners
    faces : (N, 4) int32 array of quad vertex indices, one quad per sample point
    face_normals : (N, 3) float32 array of outward unit normals, or None
    """
    __slots__ = ("vertices", "faces", "face_normals")

    def __init__(self, vertices: np.ndarray, faces: np.ndarray,
                 face_normals: np.ndarray | None = None):
        self.vertices = vertices
        self.faces = faces
        self.face_normals = face_normals

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


def discretize_surface_with_normals(
    mesh: trimesh.Trimesh,
    sample_step: float = 1.0,
    coplanarity_tol_deg: float = 5.0,
    edge_taper: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, "AnalysisMesh | None", np.ndarray, list]:
    """
    Sample the nearly planar connected components of a mesh and return
    point/normal pairs.

    Each connected component whose faces all lie within
    `coplanarity_tol_deg` of the component's area-weighted mean normal is
    sampled with ``sample_planar_surface``; other components are skipped
    with a UserWarning.  The quad analysis mesh has one face per sample
    point, suitable for per-face colouring (e.g. "LB Spatial Heatmap" in
    Grasshopper/Rhino).

    Parameters
    ----------
    mesh : trimesh.Trimesh
        Input triangle mesh (test surface).
    sample_step : float
        Sampling grid spacing in world units.
    coplanarity_tol_deg : float, default 5.0
        Maximum face-normal deviation (degrees) to consider a component planar.
    edge_taper : float, default 0.0
        Design-constraint taper distance (meters): sample weights ramp
        from 0 at each component's outline to 1 at ``edge_taper`` inward.
        Distances are measured in the component's plane, which the
        coplanarity check guarantees exists.

    Returns
    -------
    points : (N, 3) float32 np.ndarray
        Sample points (centroids of the analysis-mesh quads).
    normals : (N, 3) float32 np.ndarray
        Outward-facing normals at each sample point.
    analysis_mesh : AnalysisMesh or None
        Combined quad analysis mesh, or None if no points were sampled.
    weights : (N,) float32 np.ndarray
        Edge-taper design weights in [0, 1]; all ones when edge_taper == 0.
    taper_stats : list of dict
        Per-component taper statistics (empty when edge_taper == 0).
        Components that never reach full weight (narrower than ~2× the
        taper) also emit a UserWarning, so the user knows that geometry
        is partly or wholly excluded from the protected program.
    """
    # repair=False: trimesh's default submesh repair fills small (3-4
    # vertex) boundary loops, which destroys real openings: a plate with
    # a rectangular hole comes back closed, its boundary loops vanish, and
    # the component is rejected.  Sampling needs the true open boundary.
    submeshes = mesh.split(only_watertight=False, repair=False)
    all_points, all_normals, all_weights = [], [], []
    all_quad_verts, all_quad_faces = [], []
    vertex_offset = 0
    taper_stats: list = []
    skipped = {"degenerate": [], "non-planar": [], "no samples": []}

    for component_index, submesh in enumerate(submeshes):
        # 1) Planarity check on the faces with real area: a zero-area sliver
        #    has a (0, 0, 0) normal and must not disqualify the panel.
        face_areas = submesh.area_faces
        real = face_areas > 1e-12 * max(float(face_areas.max()), 1e-30)
        face_normals = submesh.face_normals[real]
        mean_normal = (face_normals * face_areas[real][:, None]).sum(axis=0)
        norm_len = np.linalg.norm(mean_normal)
        if norm_len < 1e-12:
            skipped["degenerate"].append(component_index)
            continue
        mean_normal /= norm_len
        angles = np.degrees(np.arccos(np.clip(face_normals @ mean_normal, -1.0, 1.0)))
        if angles.max() > coplanarity_tol_deg:
            skipped["non-planar"].append(component_index)
            continue

        # 2) Sample this planar sheet
        pts3d, nrm3d, qv, qf, wts = sample_planar_surface(
            submesh, sample_step, edge_taper=edge_taper
        )

        if pts3d.size == 0:
            skipped["no samples"].append(component_index)
            continue

        # 2b) Record taper statistics.  A component that never reaches
        # full weight is narrower than ~2× edge_taper and is partially or
        # wholly excluded from the protected program, so warn about it.
        if edge_taper > 0.0:
            max_w = float(wts.max())
            taper_stats.append({
                "component": component_index,
                "points": int(wts.size),
                "mean_weight": round(float(wts.mean()), 4),
                "max_weight": round(max_w, 4),
                "near_zero_fraction": round(float((wts < 0.1).mean()), 4),
            })
            if max_w < 0.999:
                report_issue(
                    "edge_taper_excluded_component",
                    f"edge_taper={edge_taper:g} m: test-surface component "
                    f"{component_index} never reaches full weight "
                    f"(max {max_w:.2f}); it is narrower than ~2x edge_taper "
                    f"and is partially or wholly excluded from the protected "
                    f"program.",
                )

        # 3) Orient normals to agree with the component's area-weighted
        #    mean face normal (the quad winding from step 2 is not changed).
        if np.dot(mean_normal, nrm3d[0]) < 0:
            nrm3d = -nrm3d

        all_points.append(pts3d)
        all_normals.append(nrm3d)
        all_weights.append(wts)

        # 4) Accumulate quad mesh data (offset face indices)
        if qf.size > 0:
            all_quad_verts.append(qv)
            all_quad_faces.append(qf + vertex_offset)
            vertex_offset += qv.shape[0]

    problems = [f"{len(idx)} {why} (components {idx[:10]}{'...' if len(idx) > 10 else ''})"
                for why, idx in skipped.items() if idx]
    if problems:
        report_issue(
            "test_surface_components_skipped",
            f"Test surface: {', '.join(problems)} of {len(submeshes)} components "
            f"were skipped and are not protected. Each panel must be a single "
            f"flat face (coplanarity tolerance {coplanarity_tol_deg:g} deg); "
            f"explode polysurfaces into planar faces.",
        )

    if not all_points:
        return (np.empty((0, 3), dtype=np.float32),
                np.empty((0, 3), dtype=np.float32), None,
                np.empty((0,), dtype=np.float32), taper_stats)

    points = np.vstack(all_points).astype(np.float32)
    normals = np.vstack(all_normals).astype(np.float32)
    weights = np.concatenate(all_weights).astype(np.float32)

    # 5) Build the analysis mesh as plain numpy arrays (no Ladybug objects).
    analysis_mesh = None
    if all_quad_verts:
        analysis_mesh = AnalysisMesh(
            np.vstack(all_quad_verts),
            np.vstack(all_quad_faces),
            normals,  # one normal per face, since there is one face per point
        )

    return points, normals, analysis_mesh, weights, taper_stats
