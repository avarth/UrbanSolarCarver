"""Floor-plate massing: stacked floor plates that follow the footprint.

The carved envelope is turned into floors (a ground floor, then floors of
equal height).  Each floor plate is made of *bays*: square modules of the
footprint that belong to one facade, cut along it and in depth behind it.  A
module is built on a floor when its full floor height fits the envelope
within a tolerance and stays inside the maximum volume.  See docs/massing.md.

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
MIN_CUT_ANGLE_DEG = 30.0  # a module cut at a slanted end keeps no angle sharper than this (see bay_polygons)
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
    across_short_facades: bool = False   # facades too short for a face lie between the two


def footprint_polygons(mesh, offset_xy) -> list:
    """The plan projection of *mesh* in local xy: the area it covers seen from above.

    Every triangle is projected onto the ground plane and the projections
    are merged, so the outline does not depend on the height or flatness of
    each body's base (an uneven or raised base keeps its whole footprint);
    overhangs are included.  Coordinates are snapped to 1 micrometre so that
    shared triangle edges merge exactly.  Returns shapely Polygons (exterior
    counter-clockwise, holes kept), or an empty list when the mesh covers no
    area in plan.
    """
    tri = np.asarray(mesh.triangles, dtype=np.float64)[:, :, :2] - np.asarray(offset_xy, dtype=np.float64)[:2]
    a, b = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    tri = tri[np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) > 1e-12]   # walls project to lines
    if not len(tri):
        return []
    merged = shapely.union_all(shapely.polygons(tri), grid_size=1e-6)
    parts = getattr(merged, "geoms", [merged])
    return [orient(p, 1.0) for p in parts if isinstance(p, Polygon) and p.area > 0.0]


def footprint_to_dict(polygons) -> dict:
    """*polygons* as plain data for JSON: ``{"polygons": [{"exterior": [[x, y], ...],
    "holes": [[[x, y], ...], ...]}, ...]}``."""
    return {"polygons": [{
        "exterior": np.asarray(p.exterior.coords).tolist(),
        "holes": [np.asarray(ring.coords).tolist() for ring in p.interiors],
    } for p in polygons]}


def footprint_from_dict(data) -> list:
    """The shapely Polygons of data written by :func:`footprint_to_dict`."""
    return [Polygon(entry["exterior"], entry["holes"]) for entry in data["polygons"]]


def footprint_from_columns(columns, voxel_size) -> list:
    """Fallback outline: the union of the occupied columns' squares (local xy),
    simplified to three quarters of a voxel.

    The tolerance is above the 0.71 voxel by which a 45-degree staircase
    deviates from its straight line, so diagonal outlines become straight
    facades instead of one facade per step."""
    i, j = np.nonzero(columns)
    vs = float(voxel_size)
    squares = shapely.box(i * vs, j * vs, (i + 1) * vs, (j + 1) * vs)
    merged = shapely.coverage_union_all(squares).simplify(0.75 * vs, preserve_topology=True)
    parts = getattr(merged, "geoms", [merged])
    return [orient(p, 1.0) for p in parts if isinstance(p, Polygon) and p.area > 0.0]


def _facade(part, xy, closed, straight_tolerance=1e-6) -> Facade:
    """A facade through the points *xy*; straight when every point lies within
    *straight_tolerance* of the line from the first to the last (stray
    vertices from mesh sections, off the line by less than the voxel grid
    can resolve, do not make it curved)."""
    start, end = xy[0], xy[-1]
    chord = end - start
    norm = float(np.hypot(*chord))
    direction = chord / norm if norm > 0.0 else np.array([1.0, 0.0])
    off_line = np.abs((xy[:, 0] - start[0]) * direction[1] - (xy[:, 1] - start[1]) * direction[0])
    straight = (not closed) and norm > 0.0 and bool(off_line.max() <= straight_tolerance)
    line = LineString([start, end] if straight else xy)
    return Facade(part=part, line=line, length=float(line.length), straight=straight,
                  direction=direction, start=start, end=end, closed=closed)


def _ring_facades(coords, part, corner_angle_deg, straight_tolerance):
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
        facades.append(_facade(part, pts[idx], closed=False, straight_tolerance=straight_tolerance))
        # Rings are oriented with the solid on the left (exterior counter-
        # clockwise, holes clockwise), so a left turn is a convex corner.
        convex.append(bool(turn[b] > 0.0))
    return facades, convex


def split_facades(polygons, corner_angle_deg=CORNER_ANGLE_DEG, straight_tolerance=1e-6):
    """Split every ring of every footprint polygon into facades at its corners.

    A corner is a vertex where the outline turns by more than
    *corner_angle_deg*; smaller turns (curved or faceted facades) continue
    the facade.  A ring without corners is one closed facade.  A facade
    whose vertices all lie within *straight_tolerance* of the line from its
    first to its last is straight (the massing stage passes 1 cm, more for
    coordinates far from the origin, at most half a voxel).

    Returns
    -------
    (list of Facade, list of Corner)
    """
    facades, corners = [], []
    for part, polygon in enumerate(polygons):
        polygon = orient(polygon, 1.0)
        for ring in [polygon.exterior, *polygon.interiors]:
            ring_facades, convex = _ring_facades(ring.coords, part, corner_angle_deg, straight_tolerance)
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
    """For each footprint column: its facade, its position along that facade and its depth behind it."""
    face: np.ndarray   # (N,) facade index
    u: np.ndarray      # (N,) m along the facade
    d: np.ndarray      # (N,) m behind the facade: from its line when straight, from the facade itself when curved
                       #      (past either end of a curved facade, from the line through its end edge)


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
    step_inside = 1e-6
    for p, d in zip(at, inward):
        ray = LineString([p + d * step_inside, p + d * reach])
        inside = ray.intersection(polygon)
        pieces = [g for g in getattr(inside, "geoms", [inside]) if g.length > 0.0]
        first = [g for g in pieces if shapely.distance(g, shapely.Point(p)) < 1e-4]
        if first:
            thickness.append(first[0].length + step_inside)   # the ray starts that far inside
    return 0.5 * float(np.median(thickness)) if thickness else 0.0


def _longer(a, b, facades):
    """(longer, shorter) facade index.

    Equal lengths (a square) go to the facade closer to the x axis, so the
    partition does not depend on where the outline's vertex list starts;
    only a tie in that too (a square at 45 degrees) falls back to the lower
    index."""
    la, lb = facades[a].length, facades[b].length
    if abs(la - lb) > 1e-9:
        return (a, b) if la > lb else (b, a)
    xa, xb = abs(facades[a].direction[0]), abs(facades[b].direction[0])
    if abs(xa - xb) > 1e-9:
        return (a, b) if xa > xb else (b, a)
    return (a, b) if a < b else (b, a)


def _corners_across_short_facades(facades, corners, short):
    """The corners between facades that carry faces.

    Where facades marked *short* lie between two others (a chamfer, a
    small step), the two meet at one corner, convex when the first one's
    last edge turns left into the second one's first edge."""
    following = {c.ending: c.starting for c in corners}
    kept = []
    for c in corners:
        if short[c.ending]:
            continue
        nxt = c.starting
        while short[nxt] and nxt != c.ending:
            nxt = following[nxt]
        if nxt == c.ending:          # no other facade on this ring carries a face
            continue
        if nxt == c.starting:
            kept.append(c)
            continue
        a = np.asarray(facades[c.ending].line.coords)
        b = np.asarray(facades[nxt].line.coords)
        ea, eb = a[-1] - a[-2], b[1] - b[0]
        kept.append(Corner(c.ending, nxt, bool(ea[0] * eb[1] - ea[1] * eb[0] > 0.0),
                           facades[c.ending].end, across_short_facades=True))
    return kept


def _distance_to_tangent(facade, at_end, xy):
    """Distance from *xy* to the line through the facade's first or last edge."""
    coords = np.asarray(facade.line.coords)
    a, b = (coords[-2], coords[-1]) if at_end else (coords[0], coords[1])
    d = (b - a) / np.hypot(*(b - a))
    rel = xy - a
    return np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0])


def _outside_columns_onto_the_footprint(probe, part, polygons, step_inside=1e-4):
    """*probe* with each point outside its part moved to the nearest point of the part, then *step_inside* further
    in the same direction (into the part).

    Along a facade not aligned with the grid the voxelizer fills columns whose centre lies just outside it.  Beside
    a corner such a column would be nearest to the other facade there and past the end of the facade that takes the
    corner square, so it would keep a face of its own, cut in rows that do not line up with the depth cuts of the
    faces beside it.  Assigned from the point of the footprint nearest to it, it joins the face that point is in."""
    probe = probe.copy()
    for k, polygon in enumerate(polygons):
        outside = np.flatnonzero((part == k) & ~shapely.contains_xy(polygon, probe[:, 0], probe[:, 1]))
        if not outside.size:
            continue
        on_outline = shapely.get_coordinates(shapely.shortest_line(shapely.points(probe[outside]), polygon))[1::2]
        towards = on_outline - probe[outside]
        length = np.maximum(np.hypot(towards[:, 0], towards[:, 1]), 1e-12)
        probe[outside] = on_outline + towards / length[:, None] * step_inside
    return probe


def assign_faces(xy, facades, corners, polygons, voxel_size, min_facade_length=0.0) -> Faces:
    """Assign footprint columns (centres *xy*, local) to faces.

    Each column first goes to its nearest facade of the same part, which
    splits the footprint into faces meeting along ridges (diagonal at
    corners).  Facades shorter than *min_facade_length* (chamfers, small
    steps) get no face of their own: their columns go to the neighbouring
    facades, which then meet at one corner across them (a part whose
    facades are all that short keeps them).  Corners are then squared:

    * convex corner: the shorter facade's columns that lie in front of the
      longer facade (projection within its extent) and within its half
      depth (half the part's thickness behind it) move to the longer facade;
      across short facades the corner square reaches past the longer
      facade's end up to the outline, with the depth measured from the
      line through its last edge;
    * reflex corner: the columns that lie past the end of one facade and
      before the start of the other, and within each facade's half depth of
      its tangent line, move to the longer facade, extending it past its end.

    Equal lengths go to the facade closer to the x axis (see ``_longer``).
    A column whose centre lies outside the footprint gets the face of the
    footprint point nearest to it (see ``_outside_columns_onto_the_footprint``).
    ``u`` is the projection on the facade direction measured from the
    part's centroid for straight facades (so parallel facades share cut
    positions), the arc length otherwise, continued along the end edges
    past either end. ``d`` is the distance behind the facade: from the line
    through a straight facade (so a corner square past its end keeps its
    depth), from the facade itself when it is curved, and past either end of
    a curved facade from the line through its end edge, as ``u`` continues.
    Columns whose centre lies outside a straight facade's line get ``d < 0``.
    """
    xy = np.asarray(xy, dtype=np.float64)
    # Columns whose centre lies exactly on a ridge (aligned grids, odd voxel
    # counts) would make every test below a tie; a fixed sub-micrometre shift
    # sends all of them to the same side, so faces stay rectangular.
    probe = xy + _TIE_SHIFT
    part = part_of_points(shapely.points(probe), polygons)
    probe = _outside_columns_onto_the_footprint(probe, part, polygons)
    points = shapely.points(probe)
    facade_part = np.array([f.part for f in facades])
    short = np.array([f.length < min_facade_length for f in facades])
    for p in np.unique(facade_part):
        if short[facade_part == p].all():
            short[facade_part == p] = False
    corners = _corners_across_short_facades(facades, corners, short)
    lines = np.array([f.line for f in facades], dtype=object)
    dist = shapely.distance(points[:, None], lines[None, :])
    dist = np.where((part[:, None] == facade_part[None, :]) & ~short[None, :], dist, np.inf)
    nearest = np.argmin(dist, axis=1)

    half_depth = np.array([_half_depth(f, polygons[f.part], voxel_size) for f in facades])

    face = nearest.copy()
    for c in (c for c in corners if c.convex):
        longer, shorter = _longer(c.ending, c.starting, facades)
        at_end = longer == c.ending            # the corner is at the longer facade's end
        length = facades[longer].length
        t = shapely.line_locate_point(facades[longer].line, points)
        if c.across_short_facades:
            within = (t > 1e-9) if at_end else (t < length - 1e-9)   # only its far end limits
            depth = _distance_to_tangent(facades[longer], at_end, probe)
        else:
            within = (t > 1e-9) & (t < length - 1e-9)
            depth = dist[:, longer]
        face[(nearest == shorter) & within & (depth <= half_depth[longer])] = longer
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
    d = np.zeros(len(xy))
    for k, f in enumerate(facades):
        mine = face == k
        if not mine.any():
            continue
        if f.straight:
            u[mine] = (xy[mine] - centroids[f.part]) @ f.direction
            inward = np.array([-f.direction[1], f.direction[0]])     # solid on the left
            d[mine] = (xy[mine] - f.start) @ inward
        else:
            d[mine] = shapely.distance(points[mine], f.line)
            t = shapely.line_locate_point(f.line, points[mine])
            if not f.closed:
                # Past either end (corner squares at reflex corners) the arc
                # length continues along the end edge instead of stopping.
                coords = np.asarray(f.line.coords)
                first, last = coords[1] - coords[0], coords[-1] - coords[-2]
                first, last = first / np.hypot(*first), last / np.hypot(*last)
                before, after = (xy[mine] - f.start) @ first, (xy[mine] - f.end) @ last
                at_start, at_end = t <= 1e-9, t >= f.length - 1e-9
                t = np.where(at_start, np.minimum(before, 0.0),
                             np.where(at_end, f.length + np.maximum(after, 0.0), t))
                # The depth there is measured from the line through the end
                # edge too (solid on the left), so modules stay square.
                inward_first, inward_last = np.array([-first[1], first[0]]), np.array([-last[1], last[0]])
                d[mine] = np.where(at_start, (xy[mine] - f.start) @ inward_first,
                                   np.where(at_end, (xy[mine] - f.end) @ inward_last, d[mine]))
            u[mine] = t
    return Faces(face=face, u=u, d=d)


# ----------------------------------------------------------------- bays
def _bay_span(u, voxel_size):
    return float(u.max() - u.min()) + voxel_size


def row_cut_lines(facade, polygon, bay_width):
    """Positions ``u`` (along a straight *facade*, from the centroid of its
    part *polygon*) of the cuts between rows of modules, in increasing order.

    Rows of *bay_width* are laid from both ends of the part's extent along
    the facade; what is left over widens the middle row, or the two middle
    rows equally.  An end wing therefore starts with a whole row, whatever
    the building's length, and the cuts are the same lines for the parallel
    facade opposite (the extent and its middle do not depend on the
    direction)."""
    w = float(bay_width)
    centroid = np.array(polygon.centroid.coords[0])
    extent = (np.asarray(polygon.exterior.coords) - centroid) @ facade.direction
    lo, hi = float(extent.min()), float(extent.max())
    n = int(np.floor((hi - lo) / w + 1e-9))       # whole rows
    from_each_end = max(n - 1, 0) // 2
    cuts = [lo + w * np.arange(1, from_each_end + 1), hi - w * np.arange(from_each_end, 0, -1)]
    if n >= 2 and n % 2 == 0:
        cuts.append([0.5 * (lo + hi)])
    return np.sort(np.concatenate(cuts))


def _rows(faces, mine, facade, polygon, bay_width):
    """Row of each of the columns *mine* of *facade*'s face: between the cut lines of ``row_cut_lines`` on a straight
    facade, every *bay_width* of arc length from its start on a curved one."""
    if facade.straight:
        return np.searchsorted(row_cut_lines(facade, polygon, bay_width), faces.u[mine] + 1e-9, side="right")
    return np.floor(faces.u[mine] / bay_width + 1e-9).astype(np.int64)


def cut_bays(faces: Faces, facades, polygons, bay_width, voxel_size):
    """Cut each face into bays: square modules of *bay_width*, cut along the facade in rows (see ``row_cut_lines``;
    on a curved facade every *bay_width* of arc length) and in depth behind it at ``d = m * bay_width``.

    A row of modules at either end of a face that is narrower than
    *bay_width* (where the face ends inside the building, at a corner square)
    merges into its neighbour, and so does a module at the back of a row
    (the ridge where the face ends) shallower than *bay_width*. Each
    module is built on a floor on its own, so a wing keeps its floors
    whatever lies behind it in the same face (a courtyard carved lower).

    Returns
    -------
    bay : ndarray (N,) int
        Bay of each column, numbered 0..B-1.
    bay_face : ndarray (B,) int
        Facade index of each bay.
    """
    k = np.zeros(len(faces.u), dtype=np.int64)
    for f in np.unique(faces.face):
        mine = faces.face == f
        k[mine] = _rows(faces, mine, facades[f], polygons[facades[f].part], bay_width)
    # Columns whose centre lies in front of the facade line (d < 0, along
    # facades not aligned with the grid) belong to the first module.
    m = np.floor(np.maximum(faces.d, 0.0) / bay_width + 1e-9).astype(np.int64)
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
        for row in np.unique(ks):
            in_row = mine[ks == row]
            ms, ds = m[in_row], faces.d[in_row]
            lo, hi = ms.min(), ms.max()
            if hi > lo and _bay_span(ds[ms == hi], voxel_size) < bay_width - 1e-9:
                ms[ms == hi] = hi - 1
            m[in_row] = ms
    keys, bay = np.unique(np.stack([faces.face, k, m], axis=1), axis=0, return_inverse=True)
    return bay.ravel().astype(np.int64), keys[:, 0].astype(np.int64)


def _rectangle(origin, along, inward, u0, u1, d0, d1):
    corners = [(u0, d0), (u1, d0), (u1, d1), (u0, d1)]
    return Polygon([origin + u * along + d * inward for u, d in corners])


def _inward(facade):
    return np.array([-facade.direction[1], facade.direction[0]])    # solid on the left


def _bisector(facade, other):
    """The line of points as far behind straight *facade* as behind straight *other* (the ridge the nearest-facade
    rule draws between their faces), as (unit normal, offset) of ``normal @ p == offset``; None when they are
    parallel and face the same way."""
    towards = _inward(facade) - _inward(other)
    norm = float(np.hypot(*towards))
    if norm <= 1e-9:
        return None
    return towards / norm, (_inward(facade) @ facade.start - _inward(other) @ other.start) / norm


def _neighbours(facades, k, part_facades):
    """The facades among *part_facades* that meet facade *k* at one of its ends."""
    f = facades[k]
    return [j for j in part_facades if j != k
            and (np.allclose(facades[j].end, f.start, atol=1e-9) or np.allclose(facades[j].start, f.end, atol=1e-9))]


def _lines_between_faces(facades, mine, theirs, part_facades, half_depth):
    """Lines along which the face of facade *mine* (straight) can meet the face of facade *theirs*, as (unit normal,
    offset) of ``normal @ p == offset``, in the order they are tried: the bisector of the two facades; the lines of
    their corner squares (``assign_faces``: for each of the two that is straight, the line *half_depth* of it behind
    it and the lines across it at its two ends); then the bisectors of each with the facades that meet it
    (*part_facades*, indices into *facades*, are the facades of their part).  A facade that touches neither gives no
    line: one that happens to separate the columns would cut a wedge where the faces do not meet."""
    pair = [k for k in (mine, theirs) if facades[k].straight]
    lines = [_bisector(facades[mine], facades[theirs])] if len(pair) == 2 else []
    for k in pair:
        f = facades[k]
        lines += [(_inward(f), _inward(f) @ f.start + half_depth(k)),
                  (f.direction, f.direction @ f.start), (f.direction, f.direction @ f.end)]
    lines += [_bisector(facades[k], facades[j]) for k in pair for j in _neighbours(facades, k, part_facades)
              if j not in (mine, theirs) and facades[j].straight]
    return [line for line in lines if line is not None]


def _separates(mine, theirs, normal, offset):
    return (mine @ normal - offset).max() <= 1e-9 and (theirs @ normal - offset).min() >= -1e-9


def _separating_line(mine, theirs, candidate_lines, snap_normals=()):
    """(unit normal, offset) of a line with the points *mine* on its side ``normal @ p <= offset`` and the points
    *theirs* on the other, or None.

    The first of *candidate_lines* that separates them; otherwise the line midway across the widest gap between their
    convex hulls, turned to the nearest of *snap_normals* (the directions of the two facades, their normals and their
    bisector) and placed midway across the gap the columns leave in that direction, when that still separates them.
    A line at any other angle would cut a wedge into the module, so there is none: it is drawn from its columns."""
    for normal, offset in candidate_lines:
        for sign in (1.0, -1.0):
            if _separates(mine, theirs, sign * normal, sign * offset):
                return sign * normal, sign * offset
    hull_mine = shapely.MultiPoint(mine).convex_hull
    hull_theirs = shapely.MultiPoint(theirs).convex_hull
    if not len(snap_normals) or hull_mine.distance(hull_theirs) <= 1e-9:
        return None
    a, z = shapely.get_coordinates(shapely.shortest_line(hull_mine, hull_theirs))
    widest = (z - a) / np.hypot(*(z - a))
    snapped = max(snap_normals, key=lambda normal: abs(normal @ widest))
    normal = snapped if snapped @ widest > 0.0 else -snapped
    low, high = (mine @ normal).max(), (theirs @ normal).min()
    return (normal, float(0.5 * (low + high))) if high > low + 1e-9 else None


def _convex_cut(polygon, lines):
    """The part of the convex *polygon* on the side ``normal @ p <= offset`` of every line (normal, offset) in
    *lines*, or None when nothing is left.

    Cut edge by edge (each edge keeps its start when on that side and gains the point where it crosses the line),
    with vertices closer than a nanometre merged, so that two lines crossing at a vertex leave no spike."""
    points = np.asarray(polygon.exterior.coords)[:-1]
    for normal, offset in lines:
        side = points @ normal - offset
        kept = []
        for k in range(len(points)):
            p, q, side_p, side_q = points[k - 1], points[k], side[k - 1], side[k]
            if (side_p < 0.0 < side_q) or (side_q < 0.0 < side_p):
                kept.append(p + (q - p) * side_p / (side_p - side_q))
            if side_q <= 0.0:
                kept.append(q)
        kept = [p for k, p in enumerate(kept) if np.hypot(*(p - kept[k - 1])) > 1e-9] if len(kept) > 1 else kept
        if len(kept) < 3:
            return None
        points = np.array(kept)
    return Polygon(points)


def bay_polygons(xy, faces: Faces, bay, bay_face, facades, polygons, bay_width, voxel_size):
    """The outline of each bay on a straight facade, as a rectangle in the
    facade's frame (local xy); None for the others.

    In the frame of its facade (u along the facade from the part's
    centroid, d inward from the facade) a bay is the rectangle around its
    columns' squares, with its sides moved onto exact lines:

    * a side with columns of the same face across it lies on its cut line:
      a line of ``row_cut_lines`` along the facade, ``d = m * bay_width`` in depth;
    * a back with only columns of the face of a parallel, opposite facade
      across it lies on the midline between the two facades (the ridge
      the nearest-facade rule draws there);
    * a side with no columns across it borders the outline and moves one
      voxel past it, and so does the front wherever the facade runs, so
      that clipping to the footprint gives the outline itself;
    * any other side stays at the edge of the columns' squares.

    A rectangle that holds column centres of another bay (a slanted end
    where a corner is not square) is first grown, on each side that is not a
    cut line and has columns beyond it, by a module up to the next cut line,
    then cut by a line between its columns and those of every other bay
    inside it: one of ``_lines_between_faces`` (for two straight facades
    first the bisector of their corner, which the nearest-facade rule
    draws), else the line across the widest gap between the columns turned
    to a direction of the two facades or their bisector
    (``_separating_line``).  Where no line separates them, or the cut leaves
    a piece narrower than a voxel or an angle under MIN_CUT_ANGLE_DEG away
    from the footprint's corners, the rectangle is cut without being grown;
    where that fails too, and for a bay on a curved facade, the bay gets
    None: ``plate_polygons`` draws those from their columns.

    *xy* are voxel column centres, one per grid square.  Every test looks at
    columns within two modules of the bay, so each bay reads only the columns
    of a window of the grid around it.
    """
    xy = np.asarray(xy, dtype=np.float64)
    vs, w = float(voxel_size), float(bay_width)
    part = part_of_points(shapely.points(xy), polygons)
    # Where assign_faces saw each column (columns exactly on a ridge moved off it), for the lines between faces.  Only
    # columns whose centre lies inside the footprint count there: the others, along facades not aligned with the grid,
    # were assigned from a point of the outline and lie where clipping to the footprint removes their squares anyway.
    seen_at = xy + _TIE_SHIFT
    in_footprint = shapely.contains_xy(shapely.union_all(polygons), seen_at[:, 0], seen_at[:, 1])
    facades_of_part = {}
    for k, f in enumerate(facades):
        facades_of_part.setdefault(f.part, []).append(k)
    half_depths = {}

    def half_depth(f_index):
        if f_index not in half_depths:
            half_depths[f_index] = _half_depth(facades[f_index], polygons[facades[f_index].part], vs)
        return half_depths[f_index]

    shapes = [None] * len(bay_face)
    columns_of_bay = np.split(np.argsort(bay, kind="stable"),
                              np.cumsum(np.bincount(bay, minlength=len(bay_face)))[:-1])
    grid_cell = np.rint(xy / vs - 0.5).astype(np.int64)
    first_cell = grid_cell.min(axis=0)
    grid_cell -= first_cell
    column_at_cell = np.full(grid_cell.max(axis=0) + 1, -1, dtype=np.int64)
    column_at_cell[grid_cell[:, 0], grid_cell[:, 1]] = np.arange(len(xy))

    def columns_near(corners_xy):
        """Columns whose centre lies within a voxel of the bounding box of *corners_xy*."""
        lo = np.maximum(np.floor(corners_xy.min(axis=0) / vs).astype(np.int64) - first_cell - 1, 0)
        hi = np.floor(corners_xy.max(axis=0) / vs).astype(np.int64) - first_cell + 2
        window = column_at_cell[lo[0]:max(hi[0], 0), lo[1]:max(hi[1], 0)].ravel()
        return window[window >= 0]

    def snap_normals_of(f_index, other):
        """The directions a line between the faces of two facades may take: along or across either, or their bisector."""
        straight = [facades[k] for k in (f_index, other) if facades[k].straight]
        normals = [direction for f in straight for direction in (f.direction, _inward(f))]
        bisector = _bisector(facades[f_index], facades[other]) if len(straight) == 2 else None
        return normals + ([bisector[0]] if bisector is not None else [])

    def well_shaped(shape, lines, part_index):
        """Whether *shape*, cut by *lines*, has within its part neither a piece narrower than a voxel nor, on a cut line
        and away from the part's own vertices, an angle sharper than MIN_CUT_ANGLE_DEG: a wedge or a sliver the cut made."""
        polygon = polygons[part_index]
        corners = shapely.MultiPoint(np.vstack([np.asarray(ring.coords) for ring in [polygon.exterior, *polygon.interiors]]))
        for piece in shapely.get_parts(shape.intersection(polygon)):
            if not isinstance(piece, Polygon) or piece.area <= 1e-6:
                continue
            if piece.buffer(-0.5 * vs, join_style="mitre").is_empty:
                return False
            for ring in [piece.exterior, *piece.interiors]:
                points = np.asarray(ring.coords)[:-1]
                for k, point in enumerate(points):
                    u, v = points[k - 1] - point, points[(k + 1) % len(points)] - point
                    cosine = u @ v / max(np.hypot(*u) * np.hypot(*v), 1e-18)
                    on_a_cut = any(abs(point @ normal - offset) < 1e-6 for normal, offset in lines)
                    if (on_a_cut and cosine > np.cos(np.radians(MIN_CUT_ANGLE_DEG))
                            and corners.distance(shapely.Point(point)) > 1e-3):
                        return False
        return True

    def cut_between_bays(pieces, b, f_index):
        """The union of the convex *pieces* cut by a line between bay *b*'s columns and those of each other bay with
        a column centre inside it; None when no line separates the two or the cut is not ``well_shaped``."""
        shape = shapely.union_all(pieces)
        x0, y0, x1, y1 = shape.bounds
        near = columns_near(np.array([[x0, y0], [x1, y1]]))
        near = near[bay[near] != b]
        inside = near[shapely.contains_xy(shape, xy[near, 0], xy[near, 1]) & in_footprint[near]]
        mine = columns_of_bay[b]
        mine = seen_at[mine[in_footprint[mine]]] if in_footprint[mine].any() else seen_at[mine]
        lines = []
        for other in np.unique(bay[inside]):
            theirs = seen_at[inside[bay[inside] == other]]
            candidates = _lines_between_faces(facades, f_index, bay_face[other], facades_of_part[facades[f_index].part],
                                              half_depth)
            lines.append(_separating_line(mine, theirs, candidates, snap_normals_of(f_index, bay_face[other])))
            if lines[-1] is None:
                return None
        cut = [piece for piece in (_convex_cut(piece, lines) for piece in pieces) if piece is not None]
        shape = shapely.union_all(cut) if cut else None
        return shape if shape is not None and well_shaped(shape, lines, facades[f_index].part) else None

    for f_index in np.unique(bay_face):
        facade = facades[f_index]
        if not facade.straight:
            continue
        origin = np.array(polygons[facade.part].centroid.coords[0])
        along = facade.direction
        inward = np.array([-along[1], along[0]])             # solid on the left
        reach = 0.5 * vs * (abs(along[0]) + abs(along[1]))  # half a column square along u and d
        gap = 2.0 * reach + 1e-9                              # a neighbouring column is this close
        on_facade = origin + ((facade.start - origin) @ inward) * inward   # u = 0, d = 0
        u_all = (xy - on_facade) @ along
        d_all = (xy - on_facade) @ inward
        u_start, u_end = (facade.start - on_facade) @ along, (facade.end - on_facade) @ along
        cuts = row_cut_lines(facade, polygons[facade.part], w)

        def side(edge, outward, beyond):
            """Edge of the columns' squares, or one voxel further when nothing lies beyond."""
            return edge + outward * (reach if beyond.any() else reach + vs)

        for b in np.flatnonzero(bay_face == f_index):
            mine = columns_of_bay[b]
            u, d = u_all[mine], d_all[mine]
            u_lo, u_hi, d_lo, d_hi = u.min(), u.max(), d.min(), d.max()
            k_lo, k_hi = np.searchsorted(cuts, [u_lo + 1e-9, u_hi + 1e-9], side="right")
            # Every column the tests below look at lies in this rectangle of the facade's frame: the rows on either
            # side (an end row is at most two modules wide).
            row_before = cuts[k_lo - 2] if k_lo >= 2 else u_lo - 2 * w
            row_after = cuts[k_hi + 1] if k_hi + 1 < len(cuts) else u_hi + 2 * w
            u_min, u_max = min(row_before, u_lo - gap) - vs, max(row_after, u_hi + gap) + vs
            d_min, d_max = d_lo - gap - vs, d_hi + gap + vs
            near = columns_near(np.array([on_facade + uu * along + dd * inward
                                          for uu in (u_min, u_max) for dd in (d_min, d_max)]))
            near = near[bay[near] != b]
            others = near[part[near] == facade.part]
            u_o, d_o = u_all[others], d_all[others]
            slanted_end = ((u_o > u_lo + 1e-9) & (u_o < u_hi - 1e-9)
                           & (d_o > d_lo + 1e-9) & (d_o < d_hi - 1e-9)).any()
            in_u = (u_o >= u_lo - 1e-9) & (u_o <= u_hi + 1e-9)
            in_d = (d_o >= d_lo - 1e-9) & (d_o <= d_hi + 1e-9)
            others_on_face = faces.face[others] == f_index
            face_near = near[faces.face[near] == f_index]
            k_face, d_face = np.searchsorted(cuts, u_all[face_near] + 1e-9, side="right"), d_all[face_near]
            at_depth = (d_face >= d_lo - 1e-9) & (d_face <= d_hi + 1e-9)    # the face's columns beside this module
            u0_on_cut, u1_on_cut = ((k_face == k_lo - 1) & at_depth).any(), ((k_face == k_hi + 1) & at_depth).any()
            before, after = in_d & (u_o < u_lo) & (u_o >= u_lo - gap), in_d & (u_o > u_hi) & (u_o <= u_hi + gap)
            u0 = cuts[k_lo - 1] if u0_on_cut else side(u_lo, -1.0, before)
            u1 = cuts[k_hi] if u1_on_cut else side(u_hi, 1.0, after)
            in_front = in_u & (d_o < d_lo) & (d_o >= d_lo - gap)
            behind = in_u & (d_o > d_hi) & (d_o <= d_hi + gap)
            module_in_front = (in_front & others_on_face).any()        # cut in depth: modules of the same row
            module_behind = (behind & others_on_face).any()
            m_lo = np.floor(max(d_lo, 0.0) / w + 1e-9)
            d0 = m_lo * w if module_in_front else side(d_lo, -1.0, in_front)
            d1 = (m_lo + 1) * w if module_behind else side(d_hi, 1.0, behind)
            across = np.unique(faces.face[others[behind]])
            on_ridge = (not module_behind and len(across) == 1 and facades[across[0]].straight
                        and facades[across[0]].direction @ along < -1.0 + 1e-9)   # parallel, opposite
            if on_ridge:
                d1 = 0.5 * ((facades[across[0]].start - on_facade) @ inward)

            def module(u0, u1, d0, d1):
                """The rectangle, and where the facade runs one reaching a voxel in front of it."""
                pieces = [_rectangle(on_facade, along, inward, u0, u1, d0, d1)]
                a, z = max(u0, u_start), min(u1, u_end)
                if z > a and d0 > -vs and not module_in_front:
                    pieces.append(_rectangle(on_facade, along, inward, a, z, -vs, d1))
                return pieces

            rectangles = module(u0, u1, d0, d1)
            shapes[b] = shapely.union_all(rectangles)
            if slanted_end:
                # Each side that is not a cut line and has columns beyond it moves out by a module, up to the next
                # cut line, so that the line between the faces, not the edge of the columns, ends the module.
                m_hi = np.floor(max(d_hi, 0.0) / w + 1e-9)
                if not u0_on_cut and before.any():
                    u0 = max(u0 - w, cuts[k_lo - 1] if k_lo > 0 else -np.inf)
                if not u1_on_cut and after.any():
                    u1 = min(u1 + w, cuts[k_hi] if k_hi < len(cuts) else np.inf)
                if not module_in_front and m_lo > 0 and in_front.any():
                    d0 = max(d0 - w, m_lo * w)
                if not module_behind and not on_ridge and behind.any():
                    d1 = min(d1 + w, (m_hi + 1) * w)
                # A cut that leaves a wedge or a sliver falls back to the cut of the rectangle not grown, then to None.
                grown = cut_between_bays(module(u0, u1, d0, d1), b, f_index)
                shapes[b] = grown if grown is not None else cut_between_bays(rectangles, b, f_index)
    return _without_overlaps(shapes)


def _without_overlaps(shapes):
    """*shapes* with each one's overlap with a shape of lower index removed.

    At a slanted end the rectangles of two modules can overlap where neither
    holds the other's column centres; the overlap goes to the module of lower
    index, so plates made of different modules neither overlap nor both leave
    it out."""
    indices = np.array([b for b, shape in enumerate(shapes) if shape is not None], dtype=np.int64)
    if not len(indices):
        return shapes
    geoms = np.array([shapes[b] for b in indices], dtype=object)
    this, other = shapely.STRtree(geoms).query(geoms, predicate="intersects")
    lower = other < this
    this, other = this[lower], other[lower]
    interiors_meet = shapely.relate_pattern(geoms[this], geoms[other], "2********")    # not only touching
    this, other = this[interiors_meet], other[interiors_meet]
    overlap = shapely.area(shapely.intersection(geoms[this], geoms[other])) > 1e-9
    shapes = list(shapes)
    for n in np.unique(this[overlap]):           # increasing, so each lower shape is already final
        b = indices[n]
        shapes[b] = shapes[b].difference(shapely.union_all([shapes[indices[m]] for m in other[overlap & (this == n)]]))
    return shapes


# ----------------------------------------------------------------- floors
def floor_levels(z0, z_top, ground_floor_height, floor_height):
    """(bottom, top) of each floor from *z0*: the ground floor, then equal
    floors, while the floor's top is at or below *z_top*."""
    levels = []
    zb, zt = float(z0), float(z0) + ground_floor_height
    while zt <= z_top + 1e-6:
        levels.append((zb, zt))
        zb, zt = zt, zt + floor_height
    return levels


def layers_centred_within(z_grid0, voxel_size, nz, lowest_z, highest_z):
    """(nz,) bool: the voxel layers whose centre lies between *lowest_z* and
    *highest_z*, the maximum volume's lowest and highest points.

    A layer whose centre lies below the lowest point (above the highest) lies
    mostly outside the maximum volume.  Its voxels are filled only where rays
    hit the base (the roof), so columns along facades that are not aligned
    with the grid lack them; ``build_floors`` does not count such a layer.
    """
    centres = z_grid0 + (np.arange(nz) + 0.5) * voxel_size
    return (centres >= lowest_z - 1e-9) & (centres <= highest_z + 1e-9)


def layer_overlaps(z_grid0, voxel_size, nz, zb, zt):
    """Length of [zb, zt) inside each of the *nz* voxel layers (layer k spans
    [z_grid0 + k*vs, z_grid0 + (k+1)*vs])."""
    bottoms = z_grid0 + np.arange(nz) * voxel_size
    return np.clip(np.minimum(zt, bottoms + voxel_size) - np.maximum(zb, bottoms), 0.0, voxel_size)


@dataclass(frozen=True)
class Floor:
    zb: float
    zt: float
    kept_bays: np.ndarray      # (B,) bool
    outside_share: np.ndarray  # (B,) share of each bay's volume outside the envelope
    plate: np.ndarray          # (N,) plate index of each column, -1 = not built


def _disc(side):
    """(side, side) bool: the cells whose centre lies within a disc of diameter *side* cells."""
    offset = np.arange(side) - 0.5 * (side - 1)
    return offset[:, None] ** 2 + offset[None, :] ** 2 <= (0.5 * side) ** 2


def _drop_narrow_bays(keep, bay, cells_ij, grid_shape, side, column_share, bay_columns):
    """Drop bays that keep less than half of their columns (counted by *column_share*,
    *bay_columns* in all) after a morphological opening with a disc *side* columns
    across (parts narrower than the minimum).

    A disc fits a strip of the minimum width at any angle to the grid, as
    the inward offset in ``plate_polygons`` does; a square fits only one
    ``side * (cos t + sin t)`` wide at angle t."""
    from scipy.ndimage import binary_opening
    built = keep[bay]
    grid = np.zeros(grid_shape, dtype=bool)
    grid[cells_ij[built, 0], cells_ij[built, 1]] = True
    opened = binary_opening(grid, structure=_disc(side))
    surviving = opened[cells_ij[:, 0], cells_ij[:, 1]] & built
    share = np.bincount(bay, weights=surviving * column_share, minlength=len(keep))
    return keep & (share >= 0.5 * bay_columns)


def _label_plates(built, cells_ij, grid_shape):
    from scipy.ndimage import label
    grid = np.zeros(grid_shape, dtype=bool)
    grid[cells_ij[built, 0], cells_ij[built, 1]] = True
    labels, _ = label(grid)
    plate = labels[cells_ij[:, 0], cells_ij[:, 1]].astype(np.int64) - 1
    plate[~built] = -1
    return plate


def column_shares_inside(cells_ij, voxel_size, footprint):
    """(N,) share of each column's square inside *footprint* (local xy).

    Along a facade not aligned with the grid the voxelizer fills every column
    the facade passes through, so these columns lie partly, some mostly,
    outside the footprint."""
    i, j = cells_ij[:, 0], cells_ij[:, 1]
    vs = float(voxel_size)
    squares = shapely.box(i * vs, j * vs, (i + 1) * vs, (j + 1) * vs)
    shapely.prepare(footprint)
    share = np.ones(len(squares))
    on_outline = ~shapely.contains_properly(footprint, squares)
    share[on_outline] = shapely.area(shapely.intersection(squares[on_outline], footprint)) / (vs * vs)
    return np.clip(share, 0.0, 1.0)


def bay_column_counts(bay, n_bays, column_share=None):
    """(B,) number of columns of each bay, each counted by its share inside the footprint (None: 1 each)."""
    return np.bincount(bay, weights=column_share, minlength=n_bays).astype(np.float64)


def build_floors(cells_ij, bay, occupancy, kept, z_grid0, voxel_size, levels,
                 tolerance, stacking, min_dimension, counted_layers=None, column_share=None, ground=None):
    """Decide, floor by floor, which bays are built.

    A bay is built on a floor when every one of its columns is filled by
    the maximum volume (*occupancy*) over the floor's full height, the share
    of its volume outside the carved envelope (*kept*) is at most
    *tolerance*, and, with ``stacking == "supported"``, it is built on the
    floor below.  Bays left in parts narrower than *min_dimension* are then
    dropped.  The connected built columns of a floor are its plates.

    Only the voxel layers in *counted_layers* ((nz,) bool, from
    ``layers_centred_within``; None: every layer) count: a floor's height
    and its share outside the envelope are measured over them, so a layer
    mostly outside the maximum volume, filled only where rays hit its base or
    roof, does not fail the columns that lack it.

    Each column counts by *column_share* ((N,), from ``column_shares_inside``;
    None: 1 for every column), its share inside the footprint, in a bay's share
    outside the envelope and in the test for narrow parts: a column along a
    facade not aligned with the grid counts only for the part of its volume
    inside the building, so a module's share does not depend on the angle of
    the footprint to the grid.  A column less than half inside the footprint
    need not be filled for its bay to stay in the maximum volume: along a
    wall the voxels can reach up to a voxel past the footprint (the envelope
    of an earlier carving, voxelized again on another grid, does), and one
    such column, empty above the lowest floors, would otherwise fail the
    whole module.

    *ground* ((nx, ny, nz) bool, the cells below the terrain; None: no
    terrain) lets a floor reach into sloped ground (user, 2026-10-28: "partly
    buried floor plates should be ok"): a cell below the ground counts as
    filled and as inside the envelope, so a module is built when its part
    above the ground stays in the maximum volume; a module wholly below the
    ground over the floor's height is not built; and a module whose columns
    reach the ground within the floor or just under it stands on the ground,
    which supports it as a built bay below does.
    """
    n_bays = int(bay.max()) + 1 if bay.size else 0
    column_share = np.ones(len(bay)) if column_share is None else np.asarray(column_share, dtype=np.float64)
    occ_cols = occupancy[cells_ij[:, 0], cells_ij[:, 1], :].astype(np.float64)
    kept_cols = (kept & occupancy)[cells_ij[:, 0], cells_ij[:, 1], :].astype(np.float64)
    ground_cols = None if ground is None else ground[cells_ij[:, 0], cells_ij[:, 1], :].astype(np.float64)
    if ground_cols is not None:
        occ_cols = np.maximum(occ_cols, ground_cols)
        kept_cols = np.maximum(kept_cols, ground_cols)
    bay_columns = np.maximum(bay_column_counts(bay, n_bays, column_share), 1e-9)
    mostly_inside = column_share >= 0.5
    grid_shape = occupancy.shape[:2]
    side = max(1, int(round(min_dimension / voxel_size)))
    n_layers = occupancy.shape[2]
    not_counted = np.zeros(n_layers, dtype=bool) if counted_layers is None else ~np.asarray(counted_layers, dtype=bool)
    floors, below = [], None
    for zb, zt in levels:
        overlap = layer_overlaps(z_grid0, voxel_size, n_layers, zb, zt)
        height = zt - zb - overlap[not_counted].sum()
        overlap[not_counted] = 0.0
        column_full = occ_cols @ overlap >= height - 1e-6
        in_max = np.bincount(bay, weights=(~column_full & mostly_inside).astype(np.float64), minlength=n_bays) == 0
        outside = (np.bincount(bay, weights=(height - kept_cols @ overlap) * column_share, minlength=n_bays)
                   / (bay_columns * height))
        keep = in_max & (outside <= tolerance + 1e-9)
        on_ground = np.zeros(n_bays, dtype=bool)
        if ground_cols is not None:
            in_floor = ground_cols @ overlap
            buried = in_floor >= height - 1e-6
            keep &= np.bincount(bay, weights=(~buried).astype(np.float64), minlength=n_bays) > 0
            layer_under = int(np.floor((zb - z_grid0) / voxel_size + 1e-6)) - 1
            under = ground_cols[:, layer_under] > 0 if 0 <= layer_under < n_layers else np.zeros(len(bay), dtype=bool)
            on_ground = np.bincount(bay, weights=((in_floor > 1e-6) | under).astype(np.float64), minlength=n_bays) > 0
        if stacking == "supported" and below is not None:
            keep &= below | on_ground
        keep = _drop_narrow_bays(keep, bay, cells_ij, grid_shape, side, column_share, bay_columns)
        floors.append(Floor(zb=zb, zt=zt, kept_bays=keep, outside_share=outside,
                            plate=_label_plates(keep[bay], cells_ij, grid_shape)))
        below = keep
    return floors


# ----------------------------------------------------------------- plate geometry
def _squares(cells_ij, mask, voxel_size):
    """Union of the masked columns' squares (they tile, so a coverage union)."""
    i, j = cells_ij[mask, 0], cells_ij[mask, 1]
    vs = float(voxel_size)
    return shapely.coverage_union_all(shapely.box(i * vs, j * vs, (i + 1) * vs, (j + 1) * vs))


def _near(cells_ij, mask, columns):
    """Columns at most *columns* columns away (in i and in j) from a masked column."""
    from scipy.ndimage import binary_dilation
    ij = cells_ij - cells_ij.min(axis=0)
    grid = np.zeros(ij.max(axis=0) + 1, dtype=bool)
    grid[ij[mask, 0], ij[mask, 1]] = True
    grid = binary_dilation(grid, structure=np.ones((2 * columns + 1,) * 2, dtype=bool))
    return grid[ij[:, 0], ij[:, 1]]


def _from_columns(cells_ij, in_plate, removed, voxel_size):
    """The plate columns' squares grown by one and a half voxels (enough to
    reach the facade after simplification), minus the squares of the
    removed columns, simplified to half a voxel."""
    vs = float(voxel_size)
    shape = _squares(cells_ij, in_plate, vs).buffer(1.5 * vs, join_style="mitre")
    removed = removed & _near(cells_ij, in_plate, 2)    # only these reach the grown squares
    if removed.any():
        shape = shape.difference(_squares(cells_ij, removed, vs))
    return shape.simplify(vs / 2, preserve_topology=True)


def plate_polygons(cells_ij, in_plate, removed, voxel_size, footprint, min_dimension=0.0,
                   bay=None, bay_shapes=None):
    """Outline of one floor plate (local xy).

    With *bay_shapes* (from ``bay_polygons``, *bay* giving each column's
    bay) the plate is the union of its bays' rectangles, so cuts lie on the
    cut lines and ridges on the ridges; bays without a shape (curved
    facades, slanted ends no line separates) are drawn from their columns as below.  Without
    them the whole plate is drawn from its columns: their squares grown by
    one and a half voxels, minus the squares of the *removed* columns,
    simplified to half a voxel, so cuts are straight to within half a voxel.
    Gaps narrower than a voxel between the pieces are closed, the
    rectangles of nearby bays not in the plate are cut out (so pieces drawn
    from columns do not spill into them), and the result is clipped to the
    exact *footprint*, which gives the facade edges.  Parts narrower than *min_dimension* everywhere (nothing left
    after an inward offset of half of it) are dropped: voxel columns can
    make a thin part look one voxel wider than it is.
    """
    vs = float(voxel_size)
    if bay_shapes is None:
        shape = _from_columns(cells_ij, in_plate, removed, vs).intersection(footprint)
    else:
        has_shape = np.array([s is not None for s in bay_shapes])
        rectangles = shapely.union_all([bay_shapes[b] for b in np.unique(bay[in_plate]) if has_shape[b]])
        pieces = [rectangles]
        by_columns = in_plate & ~has_shape[bay]
        if by_columns.any():
            pieces.append(_from_columns(cells_ij, by_columns, removed, vs))
        # Gaps narrower than a voxel closed by an outward then inward offset.  GEOS's inward mitre offset can drop
        # whole parts of what it offsets, so the pieces themselves are kept as well; at a sharp corner it can leave a
        # self-intersection, which a zero offset resolves.
        pieces = shapely.union_all(pieces)
        closed = pieces.buffer(vs / 2, join_style="mitre").buffer(-vs / 2, join_style="mitre")
        shape = shapely.union_all([pieces, closed if closed.is_valid else closed.buffer(0)])
        removed_near = removed & _near(cells_ij, in_plate, 2)
        if removed_near.any():
            # Outside its rectangles the plate (pieces drawn from columns, gaps
            # closed) stays off the squares of columns not in it.
            beyond_rectangles = shapely.get_parts(shape.difference(rectangles))
            # Rounding leaves lines and slivers along the rectangles' edges; they reach no square.
            beyond_rectangles = beyond_rectangles[shapely.area(beyond_rectangles) > 1e-9]
            i, j = cells_ij[removed_near, 0], cells_ij[removed_near, 1]
            squares = shapely.box(i * vs, j * vs, (i + 1) * vs, (j + 1) * vs)
            reached = squares[np.unique(shapely.STRtree(squares).query(beyond_rectangles, predicate="intersects")[1])]
            if len(reached):
                shape = shape.difference(shapely.coverage_union_all(reached).difference(rectangles))
        nearby_removed = np.unique(bay[removed_near])
        removed_rectangles = [bay_shapes[b] for b in nearby_removed if has_shape[b]]
        if removed_rectangles:
            shape = shape.difference(shapely.union_all(removed_rectangles))
        # Simplified after clipping: a rectangle side that ends on the facade
        # line would otherwise leave a vertex a rounding error away.
        shape = shape.intersection(footprint).simplify(1e-6)
    parts = [_without_spikes(p) for p in getattr(shape, "geoms", [shape]) if isinstance(p, Polygon) and p.area > vs * vs]
    if min_dimension > 0.0:
        parts = [p for p in parts if not p.buffer(-0.5 * min_dimension + 1e-3).is_empty]
    return [orient(p, 1.0) for p in parts]


def _without_spikes(polygon, max_angle_deg=0.5):
    """*polygon* without the spikes and cracks of no width that boolean operations leave: a vertex where the outline
    turns back on itself (an angle under *max_angle_deg*) is dropped, and so is a vertex a nanometre from the one
    before it.  *polygon* itself when the result would not be valid."""
    limit = np.cos(np.radians(max_angle_deg))

    def ring_without_spikes(coords):
        points = [np.asarray(p, dtype=np.float64) for p in np.asarray(coords)[:-1]]
        k = 0
        while k < len(points) and len(points) > 3:
            u, v = points[k - 1] - points[k], points[(k + 1) % len(points)] - points[k]
            length_u, length_v = np.hypot(*u), np.hypot(*v)
            if length_u < 1e-9 or length_v < 1e-9 or u @ v > limit * length_u * length_v:
                del points[k]
                k = max(k - 1, 0)            # the vertex before may now turn back too
            else:
                k += 1
        return points

    exterior = ring_without_spikes(polygon.exterior.coords)
    holes = [ring for ring in (ring_without_spikes(r.coords) for r in polygon.interiors) if len(ring) >= 3]
    if len(exterior) < 3:
        return polygon
    cleaned = Polygon(exterior, holes)
    return cleaned if cleaned.is_valid and not cleaned.is_empty else polygon


def prism_mesh(polygon, zb, zt):
    """Closed triangle mesh of *polygon* extruded from *zb* to *zt*.

    Caps come from shapely's constrained Delaunay triangulation (no extra
    triangulation dependency); walls follow every ring.
    """
    import trimesh
    polygon = orient(polygon, 1.0)
    vertices, faces = [], []

    def add(triangle):
        base = len(vertices)
        vertices.extend(triangle)
        faces.append([base, base + 1, base + 2])

    for tri in shapely.constrained_delaunay_triangles(polygon).geoms:
        a, b, c = np.asarray(orient(tri, 1.0).exterior.coords)[:3]
        add([(*a, zt), (*b, zt), (*c, zt)])      # top, counter-clockwise: normal up
        add([(*a, zb), (*c, zb), (*b, zb)])      # bottom, reversed: normal down
    for ring in [polygon.exterior, *polygon.interiors]:
        xy = np.asarray(ring.coords)
        for p, q in zip(xy[:-1], xy[1:]):
            # Solid on the left of p -> q, so (p, q, q_top) faces outward.
            add([(*p, zb), (*q, zb), (*q, zt)])
            add([(*p, zb), (*q, zt), (*p, zt)])
    mesh = trimesh.Trimesh(np.asarray(vertices, dtype=np.float64), np.asarray(faces), process=True)
    mesh.merge_vertices()
    trimesh.repair.fix_normals(mesh)
    return mesh
