"""Sites: closed outlines on the ground, each raised to its own height, as the maximum volume.

A site is a closed outline whose vertices carry the elevation of the ground, in the coordinates of the other input files, and a
height. Its volume is the closed mesh of
- the ground inside the outline (the bottom): linear along each edge between its two vertices, and inside the harmonic function of
  those boundary values, the shape a stretched membrane takes on the outline, never above the highest or below the lowest vertex;
- a flat top at the site's lowest elevation plus its height;
- the walls from the boundary ground up to the top.

A site may have holes (design/site-holes.md): closed outlines strictly inside its outline, whose vertices carry the ground's elevation
too. The volume leaves them out from the ground to the top: the ground's boundary follows every ring, and walls go up every ring.

The service joins the volumes of a project's sites into the maximum volume file the engine carves, so carving needs nothing new.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LinearRing, Polygon
from shapely.geometry.polygon import orient

MIN_SITE_AREA = 1.0                 # m2
MAX_GROUND_POINTS = 20_000          # the membrane's spacing grows on a site so large that a finer one would pass this
MIN_POINTS_ACROSS = 20              # a small site still gets about this many points across its shorter side
_SAME_POINT = 1e-6                  # m


Ring = tuple[tuple[float, float, float], ...]


@dataclass(frozen=True)
class Site:
    name: str
    points: Ring                                        # the outline's vertices, (x, y, z), not repeated at the end
    height: float                                       # m above the site's lowest vertex (holes' vertices included): the flat top
    holes: tuple[Ring, ...] = ()                        # closed outlines strictly inside the outline, left out of the volume


def _ring(points) -> Ring:
    return tuple(tuple(float(c) for c in p) for p in points)


def site_from_dict(data: dict) -> Site:
    return Site(str(data.get("name", "")), _ring(data.get("points", ())), float(data.get("height", 0.0)),
                tuple(_ring(hole) for hole in data.get("holes", ()) or ()))


def site_to_dict(site: Site) -> dict:
    data = {"name": site.name, "points": [list(p) for p in site.points], "height": site.height}
    if site.holes:
        data["holes"] = [[list(p) for p in hole] for hole in site.holes]
    return data


def ring_points(points) -> np.ndarray:
    """A ring's vertices as an (n, 3) array, without a repeated last point or consecutive repeats."""
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if len(points) > 1 and np.hypot(*(points[-1, :2] - points[0, :2])) < _SAME_POINT:
        points = points[:-1]
    keep = [0] + [i for i in range(1, len(points)) if np.hypot(*(points[i, :2] - points[i - 1, :2])) >= _SAME_POINT]
    return points[keep] if len(points) else points


def outline_points(site: Site) -> np.ndarray:
    """The site's outline vertices as an (n, 3) array, without a repeated last point or consecutive repeats."""
    return ring_points(site.points)


def hole_points(site: Site) -> list[np.ndarray]:
    """Each hole's vertices as an (n, 3) array, cleaned as the outline's."""
    return [ring_points(hole) for hole in site.holes]


def all_points(site: Site) -> np.ndarray:
    """Every vertex of the site, the outline's then the holes'."""
    return np.vstack([outline_points(site), *hole_points(site)]) if site.holes else outline_points(site)


def site_polygon(site: Site) -> Polygon:
    """The site in plan: its outline with its holes."""
    return Polygon(outline_points(site)[:, :2], [hole[:, :2] for hole in hole_points(site)])


def site_rise(site: Site) -> float:
    """How much higher the site's highest vertex is than its lowest, the holes' vertices included."""
    z = all_points(site)[:, 2]
    return float(z.max() - z.min()) if len(z) else 0.0


def check_site(site: Site) -> list[str]:
    """The plain reasons the site cannot make a volume; empty when it can."""
    points = outline_points(site)
    if not np.all(np.isfinite(points)) or not all(np.all(np.isfinite(hole)) for hole in hole_points(site)):
        return ["a vertex has no number for a coordinate"]
    if len(points) < 3:
        return ["an outline needs at least 3 vertices"]
    reasons = []
    if len(points) > 3 and not LinearRing(points[:, :2]).is_simple:
        reasons.append("the outline crosses itself")
    else:
        hole_reasons = _hole_reasons(points, hole_points(site))
        reasons += hole_reasons
        area = site_polygon(site).area if not hole_reasons else Polygon(points[:, :2]).area
        if area < MIN_SITE_AREA:
            reasons.append(f"the site's area is {area:.2f} m², less than {MIN_SITE_AREA:g} m²")
    if not math.isfinite(site.height) or site.height <= 0:
        reasons.append("the height must be more than 0 m")
    else:
        rise = site_rise(site)
        if site.height <= rise:
            reasons.append(f"this site rises {rise:.2f} m, so its height must be more than {rise:.2f} m")
    return reasons


def _hole_reasons(outline: np.ndarray, holes: list[np.ndarray]) -> list[str]:
    """Why the holes do not fit the outline: each needs 3 vertices, must not cross itself, needs 1 m², must lie strictly inside the
    outline (touching it is not inside) and must not touch or cross another hole."""
    reasons = []
    outer = Polygon(outline[:, :2])
    rings = []
    for number, hole in enumerate(holes, start=1):
        label = f"hole {number}"
        if len(hole) < 3:
            reasons.append(f"{label} needs at least 3 vertices")
            continue
        if len(hole) > 3 and not LinearRing(hole[:, :2]).is_simple:
            reasons.append(f"{label} crosses itself")
            continue
        polygon = Polygon(hole[:, :2])
        if polygon.area < MIN_SITE_AREA:
            reasons.append(f"{label}'s area is {polygon.area:.2f} m², less than {MIN_SITE_AREA:g} m²")
            continue
        if not outer.contains(polygon) or outer.exterior.intersects(polygon.exterior):
            reasons.append(f"{label} is not strictly inside the outline")
            continue
        rings.append((label, polygon))
    for index, (label, polygon) in enumerate(rings):
        for other_label, other in rings[index + 1:]:
            if polygon.intersects(other):
                reasons.append(f"{label} and {other_label} touch or cross")
    return reasons


def ground_spacing(site: Site, spacing: float) -> float:
    """The spacing of the ground's points: *spacing*, finer on a small site, coarser on a site so large it would need too many."""
    polygon = site_polygon(site)
    rectangle = shapely.minimum_rotated_rectangle(Polygon(polygon.exterior))
    corners = np.asarray(rectangle.exterior.coords)
    shorter = min(np.hypot(*(corners[1] - corners[0])), np.hypot(*(corners[2] - corners[1])))
    result = min(spacing, shorter / MIN_POINTS_ACROSS)
    return max(result, math.sqrt(polygon.area / MAX_GROUND_POINTS), 1e-3)


def site_ground(site: Site, spacing: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The ground inside the outline and outside the holes: (vertices (n, 3), triangles (m, 3) counter-clockwise from above, boundary
    flags (n,)).

    The site is triangulated (shapely's constrained Delaunay) and the triangles divided until no edge is longer than the ground
    spacing; the boundary vertices (on the outline or a hole) take the ground along the edges, the others the harmonic function of
    those values.
    """
    import trimesh

    points = outline_points(site)
    origin = points[:, :2].min(axis=0)
    rings = []
    for ring_xyz in [points, *hole_points(site)]:
        ring = ring_xyz.copy()
        ring[:, :2] -= origin
        rings.append(ring)
    polygon = Polygon(rings[0][:, :2], [ring[:, :2] for ring in rings[1:]])
    step = ground_spacing(site, spacing)

    # Triangulate the rings' own vertices, then divide: the midpoints of boundary edges stay on the boundary, linear in z
    corner_z = {(round(x, 9), round(y, 9)): z for ring in rings for x, y, z in ring}
    vertices, triangles = [], []
    index: dict[tuple[float, float], int] = {}

    def vertex(x: float, y: float) -> int:
        key = (round(x, 9), round(y, 9))
        if key not in index:
            index[key] = len(vertices)
            vertices.append((x, y, corner_z.get(key, 0.0)))
        return index[key]

    for triangle in shapely.constrained_delaunay_triangles(orient(polygon, 1.0)).geoms:
        a, b, c = np.asarray(orient(triangle, 1.0).exterior.coords)[:3]
        triangles.append([vertex(*a), vertex(*b), vertex(*c)])
    vertices_array, triangles_array = trimesh.remesh.subdivide_to_size(np.asarray(vertices), np.asarray(triangles), max_edge=step,
                                                                         max_iter=64)
    mesh = trimesh.Trimesh(vertices_array, triangles_array, process=True)       # merges the midpoints two triangles share
    vertices_array, triangles_array = np.asarray(mesh.vertices, dtype=np.float64).copy(), np.asarray(mesh.faces)

    # Boundary vertices: on an edge used by one triangle; their z is the ground along the outline (linear between its vertices)
    boundary_edges = mesh.edges_sorted[trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)]
    boundary = np.zeros(len(vertices_array), dtype=bool)
    boundary[boundary_edges.ravel()] = True
    vertices_array[boundary, 2] = _ground_along_rings(rings, vertices_array[boundary, :2])
    vertices_array[~boundary, 2] = _harmonic(vertices_array, triangles_array, boundary)
    vertices_array[:, :2] += origin
    return vertices_array, triangles_array, boundary


def _ground_along_rings(rings: list[np.ndarray], xy: np.ndarray) -> np.ndarray:
    """The ground at points lying on the outline or a hole: linear along the edge, of any ring, each point is nearest to."""
    start = np.vstack(rings)
    end = np.vstack([np.roll(ring, -1, axis=0) for ring in rings])
    direction = end[:, :2] - start[:, :2]
    length_squared = np.maximum((direction ** 2).sum(axis=1), 1e-18)
    offset = xy[:, None, :] - start[None, :, :2]
    t = np.clip((offset * direction[None]).sum(axis=2) / length_squared[None], 0.0, 1.0)
    nearest = start[None, :, :2] + t[..., None] * direction[None]
    edge = np.argmin(((xy[:, None, :] - nearest) ** 2).sum(axis=2), axis=1)
    rows = np.arange(len(xy))
    return start[edge, 2] + t[rows, edge] * (end[edge, 2] - start[edge, 2])


def _harmonic(vertices: np.ndarray, triangles: np.ndarray, boundary: np.ndarray) -> np.ndarray:
    """z at the inner vertices: the discrete harmonic function of the boundary values, with cotangent weights kept positive so it
    stays between the lowest and highest boundary value."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import spsolve

    inner = np.flatnonzero(~boundary)
    if not len(inner):
        return np.empty(0)
    xy = vertices[:, :2]
    rows, columns, weights = [], [], []
    for k in range(3):
        i, j, o = triangles[:, k], triangles[:, (k + 1) % 3], triangles[:, (k + 2) % 3]
        u, v = xy[i] - xy[o], xy[j] - xy[o]
        cross = np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])
        cotangent = (u * v).sum(axis=1) / np.maximum(cross, 1e-18)
        weight = np.maximum(cotangent / 2, 1e-6)
        rows += [i, j]
        columns += [j, i]
        weights += [weight, weight]
    n = len(vertices)
    matrix = coo_matrix((np.concatenate(weights), (np.concatenate(rows), np.concatenate(columns))), shape=(n, n)).tocsr()
    degree = np.asarray(matrix.sum(axis=1)).ravel()
    known = np.flatnonzero(boundary)
    inner_matrix = (-matrix[inner][:, inner]).tolil()
    inner_matrix.setdiag(degree[inner])
    right = matrix[inner][:, known] @ vertices[known, 2]
    return np.asarray(spsolve(inner_matrix.tocsc(), right)).ravel()


def site_volume(site: Site, spacing: float):
    """The site's closed volume (a trimesh): the ground below, a flat top at the lowest vertex plus the height, walls between, up the
    outline and every hole."""
    import trimesh

    from .floor_plates import prism_mesh

    reasons = check_site(site)
    if reasons:
        raise ValueError(f"site {site.name!r}: " + "; ".join(reasons))
    low = float(all_points(site)[:, 2].min())
    top = low + site.height
    if site_rise(site) < 1e-9:
        return prism_mesh(site_polygon(site), low, top)
    ground, triangles, _ = site_ground(site, spacing)
    n = len(ground)
    lid = ground.copy()
    lid[:, 2] = top
    faces = [triangles[:, ::-1], triangles + n]                      # the ground faces down, the top up
    edges = np.sort(np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]), axis=1)
    once = trimesh.grouping.group_rows(edges, require_count=1)
    directed = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])[once]
    a, b = directed[:, 0], directed[:, 1]                            # along every ring with the inside on the left
    faces.append(np.stack([a, b, b + n], axis=1))
    faces.append(np.stack([a, b + n, a + n], axis=1))
    mesh = trimesh.Trimesh(np.concatenate([ground, lid]), np.concatenate(faces), process=True)
    trimesh.repair.fix_normals(mesh)
    return mesh


def site_base_volume(site: Site, base: float, bottom: float):
    """The prism of the site's outline from *bottom* up to its lowest vertex plus *base* (a trimesh): the volume a base height keeps.

    *bottom* is below every site's ground, so the prism holds every voxel of the site up to the base level; the voxels below the
    ground are not part of the maximum volume, so the prism needs no ground. ValueError when the outline is refused, *base* is not
    more than 0 or *bottom* is not below the base level.
    """
    from .floor_plates import prism_mesh

    reasons = check_site(Site(site.name, site.points, site_rise(site) + 1.0, site.holes))     # the outline's and holes' reasons only
    if reasons:
        raise ValueError(f"site {site.name!r}: " + "; ".join(reasons))
    if not base > 0:
        raise ValueError(f"site {site.name!r}: the base height must be more than 0 m")
    level = float(all_points(site)[:, 2].min()) + base
    if not bottom < level:
        raise ValueError(f"site {site.name!r}: the bottom {bottom} is not below the base level {level}")
    return prism_mesh(site_polygon(site), bottom, level)


def sites_volume(sites: list[Site], spacing: float):
    """The volumes of all the sites joined into one mesh, as several maximum volume files are joined."""
    import trimesh

    if not sites:
        raise ValueError("no site")
    return trimesh.util.concatenate([site_volume(site, spacing) for site in sites])
