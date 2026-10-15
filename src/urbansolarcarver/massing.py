"""Floor-plate massing: stacked floor plates that follow the footprint.

The carved envelope is turned into floors (a ground floor, then floors of
equal height).  Each floor plate is made of *bays*: slices of the footprint
that belong to one facade and are cut perpendicular to it.  A bay is built on
a floor when its full floor height fits the envelope within a tolerance and
stays inside the maximum volume.  See docs/massing.md.

All geometry is in a local frame: world xy minus the voxel grid's origin, so
voxel column (i, j) covers [i*vs, (i+1)*vs] x [j*vs, (j+1)*vs].  The stage
wrapper is ``api_core/massing.py``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient

CORNER_ANGLE_DEG = 30.0  # turns sharper than this split facades
_TIE_SHIFT = np.array([1.1e-6, 2.3e-6])  # m; see assign_faces


# ----------------------------------------------------------------- footprint and facades
@dataclass(frozen=True)
class Facade:
    """A run of footprint edges between two corners (local xy, m)."""
    part: int               # index of the footprint polygon it belongs to
    line: LineString
    length: float
    straight: bool          # a single edge
    direction: np.ndarray   # unit vector from start to end
    start: np.ndarray
    end: np.ndarray
    closed: bool            # a whole ring without corners (e.g. a round tower)


@dataclass(frozen=True)
class Corner:
    """Where facade *ending* meets facade *starting* (indices into the facade list)."""
    ending: int
    starting: int
    convex: bool            # the outline turns towards the solid side
    point: np.ndarray


def footprint_polygons(mesh, offset_xy) -> list:
    """The base outline of every body of *mesh*, in local xy.

    Each connected body is sectioned 1 cm above its own lowest point, so a
    block that starts higher than the others is not missed; the outlines
    are merged.  Returns shapely Polygons (exterior counter-clockwise, holes
    kept), or an empty list when no section has a closed outline.
    """
    outlines = []
    for body in mesh.split(only_watertight=False):
        z = float(body.bounds[0, 2]) + 0.01
        section = body.section(plane_origin=[0.0, 0.0, z], plane_normal=[0.0, 0.0, 1.0])
        if section is None:
            continue
        to_plane = np.eye(4)
        to_plane[0, 3], to_plane[1, 3], to_plane[2, 3] = -offset_xy[0], -offset_xy[1], -z
        planar, _ = section.to_2D(to_2D=to_plane)
        outlines.extend(p for p in planar.polygons_full if p.area > 0.0)
    if not outlines:
        return []
    merged = shapely.union_all(outlines)
    parts = getattr(merged, "geoms", [merged])
    return [orient(p, 1.0) for p in parts if isinstance(p, Polygon) and p.area > 0.0]


def footprint_from_columns(columns, voxel_size) -> list:
    """Fallback outline: the union of the occupied columns' squares (local xy),
    simplified to half a voxel."""
    i, j = np.nonzero(columns)
    vs = float(voxel_size)
    squares = shapely.box(i * vs, j * vs, (i + 1) * vs, (j + 1) * vs)
    merged = shapely.union_all(squares).simplify(vs / 2, preserve_topology=True)
    parts = getattr(merged, "geoms", [merged])
    return [orient(p, 1.0) for p in parts if isinstance(p, Polygon) and p.area > 0.0]


def _facade(part, xy, closed) -> Facade:
    start, end = xy[0], xy[-1]
    chord = end - start
    norm = float(np.hypot(*chord))
    direction = chord / norm if norm > 0.0 else np.array([1.0, 0.0])
    line = LineString(xy)
    return Facade(part=part, line=line, length=float(line.length),
                  straight=(not closed) and len(xy) == 2, direction=direction,
                  start=start, end=end, closed=closed)


def _ring_facades(coords, part, corner_angle_deg):
    """Facades of one ring, and for each the convexity of the corner at its end."""
    pts = np.asarray(coords, dtype=np.float64)[:-1]          # drop the closing point
    edge = np.roll(pts, -1, axis=0) - pts                     # edge k: pts[k] -> pts[k+1]
    incoming = np.roll(edge, 1, axis=0)                       # edge ending at pts[k]
    cross = incoming[:, 0] * edge[:, 1] - incoming[:, 1] * edge[:, 0]
    dot = (incoming * edge).sum(axis=1)
    turn = np.degrees(np.arctan2(cross, dot))                 # signed turn at each vertex
    corners = np.flatnonzero(np.abs(turn) > corner_angle_deg)
    if corners.size == 0:
        return [_facade(part, np.vstack([pts, pts[:1]]), closed=True)], []
    n = len(pts)
    facades, convex = [], []
    for a, b in zip(corners, np.roll(corners, -1)):
        idx = np.arange(a, b + 1) if b > a else np.r_[np.arange(a, n), np.arange(0, b + 1)]
        facades.append(_facade(part, pts[idx], closed=False))
        # Rings are oriented with the solid on the left (exterior counter-
        # clockwise, holes clockwise), so a left turn is a convex corner.
        convex.append(bool(turn[b] > 0.0))
    return facades, convex


def split_facades(polygons, corner_angle_deg=CORNER_ANGLE_DEG):
    """Split every ring of every footprint polygon into facades at its corners.

    A corner is a vertex where the outline turns by more than
    *corner_angle_deg*; smaller turns (curved or faceted facades) continue
    the facade.  A ring without corners is one closed facade.

    Returns
    -------
    (list of Facade, list of Corner)
    """
    facades, corners = [], []
    for part, polygon in enumerate(polygons):
        polygon = orient(polygon, 1.0)
        for ring in [polygon.exterior, *polygon.interiors]:
            ring_facades, convex = _ring_facades(ring.coords, part, corner_angle_deg)
            first = len(facades)
            facades.extend(ring_facades)
            count = len(ring_facades)
            if ring_facades[0].closed:
                continue
            for m in range(count):
                a, b = first + m, first + (m + 1) % count
                if a != b:
                    corners.append(Corner(a, b, convex[m], facades[a].end))
    return facades, corners


# ----------------------------------------------------------------- faces
@dataclass(frozen=True)
class Faces:
    """For each footprint column: its facade and its position along that facade."""
    face: np.ndarray   # (N,) facade index
    u: np.ndarray      # (N,) m along the facade


def part_of_points(points, polygons):
    """Index of the polygon containing each point; points on no polygon (edge
    rounding) take the nearest one."""
    part = np.full(len(points), -1, dtype=np.int64)
    for k, polygon in enumerate(polygons):
        part[(part < 0) & shapely.intersects(polygon, points)] = k
    missing = part < 0
    if missing.any():
        dist = np.stack([shapely.distance(p, points[missing]) for p in polygons], axis=1)
        part[missing] = np.argmin(dist, axis=1)
    return part


def _half_depth(facade, polygon, voxel_size):
    """Half the part's thickness measured inward from *facade* along its normal
    (median over positions along the facade, one per voxel)."""
    n = max(1, int(facade.length / voxel_size))
    t = (np.arange(n) + 0.5) * facade.length / n
    step = min(1e-3, facade.length / (4 * n))
    ahead = shapely.get_coordinates(shapely.line_interpolate_point(facade.line, np.minimum(t + step, facade.length)))
    behind = shapely.get_coordinates(shapely.line_interpolate_point(facade.line, np.maximum(t - step, 0.0)))
    at = shapely.get_coordinates(shapely.line_interpolate_point(facade.line, t))
    tangent = ahead - behind
    tangent /= np.linalg.norm(tangent, axis=1, keepdims=True)
    inward = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)   # solid on the left
    x0, y0, x1, y1 = polygon.bounds
    reach = float(np.hypot(x1 - x0, y1 - y0)) + 1.0
    thickness = []
    for p, d in zip(at, inward):
        ray = LineString([p + d * 1e-6, p + d * reach])
        inside = ray.intersection(polygon)
        pieces = [g for g in getattr(inside, "geoms", [inside]) if g.length > 0.0]
        first = [g for g in pieces if shapely.distance(g, shapely.Point(p)) < 1e-4]
        if first:
            thickness.append(first[0].length)
    return 0.5 * float(np.median(thickness)) if thickness else 0.0


def _longer(a, b, facades):
    """(longer, shorter) facade index; ties go to the lower index."""
    la, lb = facades[a].length, facades[b].length
    return (a, b) if (la > lb + 1e-9 or (abs(la - lb) <= 1e-9 and a < b)) else (b, a)


def _distance_to_tangent(facade, at_end, xy):
    """Distance from *xy* to the line through the facade's first or last edge."""
    coords = np.asarray(facade.line.coords)
    a, b = (coords[-2], coords[-1]) if at_end else (coords[0], coords[1])
    d = (b - a) / np.hypot(*(b - a))
    rel = xy - a
    return np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0])


def assign_faces(xy, facades, corners, polygons, voxel_size) -> Faces:
    """Assign footprint columns (centres *xy*, local) to faces.

    Each column first goes to its nearest facade of the same part, which
    splits the footprint into faces meeting along ridges (diagonal at
    corners).  Corners are then squared:

    * convex corner: the shorter facade's columns that lie in front of the
      longer facade (projection within its extent) and within its half
      depth (half the part's thickness behind it) move to the longer facade;
    * reflex corner: the columns whose nearest point on both facades is the
      corner vertex, and that lie within each facade's half depth of its
      tangent line, move to the longer facade, extending it past its end.

    Equal lengths go to the lower facade index.  ``u`` is the projection on the facade
    direction measured from the part's centroid for straight facades (so
    parallel facades share cut positions), the arc length otherwise.
    """
    xy = np.asarray(xy, dtype=np.float64)
    # Columns whose centre lies exactly on a ridge (aligned grids, odd voxel
    # counts) would make every test below a tie; a fixed sub-micrometre shift
    # sends all of them to the same side, so faces stay rectangular.
    probe = xy + _TIE_SHIFT
    points = shapely.points(probe)
    part = part_of_points(points, polygons)
    facade_part = np.array([f.part for f in facades])
    lines = np.array([f.line for f in facades], dtype=object)
    dist = shapely.distance(points[:, None], lines[None, :])
    dist = np.where(part[:, None] == facade_part[None, :], dist, np.inf)
    nearest = np.argmin(dist, axis=1)

    half_depth = np.array([_half_depth(f, polygons[f.part], voxel_size) for f in facades])

    face = nearest.copy()
    for c in (c for c in corners if c.convex):
        longer, shorter = _longer(c.ending, c.starting, facades)
        t = shapely.line_locate_point(facades[longer].line, points)
        in_front = (t > 1e-9) & (t < facades[longer].length - 1e-9)
        face[(nearest == shorter) & in_front & (dist[:, longer] <= half_depth[longer])] = longer
    for c in (c for c in corners if not c.convex):
        ending, starting = facades[c.ending], facades[c.starting]
        longer, _ = _longer(c.ending, c.starting, facades)
        at_vertex = ((shapely.line_locate_point(ending.line, points) >= ending.length - 1e-9)
                     & (shapely.line_locate_point(starting.line, points) <= 1e-9))
        near = ((_distance_to_tangent(ending, True, probe) <= half_depth[c.ending])
                & (_distance_to_tangent(starting, False, probe) <= half_depth[c.starting]))
        face[at_vertex & near & (part == ending.part)] = longer

    centroids = np.array([[p.centroid.x, p.centroid.y] for p in polygons])
    u = np.zeros(len(xy))
    for k, f in enumerate(facades):
        mine = face == k
        if not mine.any():
            continue
        if f.straight:
            u[mine] = (xy[mine] - centroids[f.part]) @ f.direction
        else:
            u[mine] = shapely.line_locate_point(f.line, points[mine])
    return Faces(face=face, u=u)


# ----------------------------------------------------------------- bays
def _bay_span(u, voxel_size):
    return float(u.max() - u.min()) + voxel_size


def cut_bays(faces: Faces, bay_width, voxel_size):
    """Cut each face into bays at ``u = k * bay_width`` (perpendicular to its facade).

    A bay at either end of a face that is narrower than *bay_width* merges
    into its neighbour.

    Returns
    -------
    bay : ndarray (N,) int
        Bay of each column, numbered 0..B-1.
    bay_face : ndarray (B,) int
        Facade index of each bay.
    """
    k = np.floor(faces.u / bay_width + 1e-9).astype(np.int64)
    for f in np.unique(faces.face):
        mine = np.flatnonzero(faces.face == f)
        ks, us = k[mine], faces.u[mine]
        lo, hi = ks.min(), ks.max()
        if hi > lo and _bay_span(us[ks == lo], voxel_size) < bay_width - 1e-9:
            ks[ks == lo] = lo + 1
        lo, hi = ks.min(), ks.max()
        if hi > lo and _bay_span(us[ks == hi], voxel_size) < bay_width - 1e-9:
            ks[ks == hi] = hi - 1
        k[mine] = ks
    keys, bay = np.unique(np.stack([faces.face, k], axis=1), axis=0, return_inverse=True)
    return bay.ravel().astype(np.int64), keys[:, 0].astype(np.int64)
