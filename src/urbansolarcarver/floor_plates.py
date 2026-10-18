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


def _facade(part, xy, closed) -> Facade:
    """A facade through the points *xy*; straight when every point lies within
    a micrometre of the line from the first to the last (stray collinear
    vertices from mesh edges do not make it curved)."""
    start, end = xy[0], xy[-1]
    chord = end - start
    norm = float(np.hypot(*chord))
    direction = chord / norm if norm > 0.0 else np.array([1.0, 0.0])
    off_line = np.abs((xy[:, 0] - start[0]) * direction[1] - (xy[:, 1] - start[1]) * direction[0])
    straight = (not closed) and norm > 0.0 and bool(off_line.max() <= 1e-6)
    line = LineString([start, end] if straight else xy)
    return Facade(part=part, line=line, length=float(line.length), straight=straight,
                  direction=direction, start=start, end=end, closed=closed)


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
    ``u`` is the projection on the facade direction measured from the
    part's centroid for straight facades (so parallel facades share cut
    positions), the arc length otherwise, continued along the end edges
    past either end.
    """
    xy = np.asarray(xy, dtype=np.float64)
    # Columns whose centre lies exactly on a ridge (aligned grids, odd voxel
    # counts) would make every test below a tie; a fixed sub-micrometre shift
    # sends all of them to the same side, so faces stay rectangular.
    probe = xy + _TIE_SHIFT
    points = shapely.points(probe)
    part = part_of_points(points, polygons)
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
    for k, f in enumerate(facades):
        mine = face == k
        if not mine.any():
            continue
        if f.straight:
            u[mine] = (xy[mine] - centroids[f.part]) @ f.direction
        else:
            t = shapely.line_locate_point(f.line, points[mine])
            if not f.closed:
                # Past either end (corner squares at reflex corners) the arc
                # length continues along the end edge instead of stopping.
                coords = np.asarray(f.line.coords)
                first, last = coords[1] - coords[0], coords[-1] - coords[-2]
                before = (xy[mine] - f.start) @ (first / np.hypot(*first))
                after = (xy[mine] - f.end) @ (last / np.hypot(*last))
                t = np.where(t <= 1e-9, np.minimum(before, 0.0),
                             np.where(t >= f.length - 1e-9, f.length + np.maximum(after, 0.0), t))
            u[mine] = t
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


def _rectangle(origin, along, inward, u0, u1, d0, d1):
    corners = [(u0, d0), (u1, d0), (u1, d1), (u0, d1)]
    return Polygon([origin + u * along + d * inward for u, d in corners])


def bay_polygons(xy, faces: Faces, bay, bay_face, facades, polygons, bay_width, voxel_size):
    """The outline of each bay on a straight facade, as a rectangle in the
    facade's frame (local xy); None for the others.

    In the frame of its facade (u along the facade from the part's
    centroid, d inward from the facade) a bay is the rectangle around its
    columns' squares, with its sides moved onto exact lines:

    * a side with columns of the same face across it lies on its cut line
      ``u = k * bay_width``;
    * a back with only columns of the face of a parallel, opposite facade
      across it lies on the midline between the two facades (the ridge
      the nearest-facade rule draws there);
    * a side with no columns across it borders the outline and moves one
      voxel past it, and so does the front wherever the facade runs, so
      that clipping to the footprint gives the outline itself;
    * any other side stays at the edge of the columns' squares.

    A bay whose rectangle holds column centres of another bay (a slanted
    end where a corner is not square) and a bay on a curved facade get
    None; ``plate_polygons`` draws those from their columns.
    """
    xy = np.asarray(xy, dtype=np.float64)
    vs, w = float(voxel_size), float(bay_width)
    part = part_of_points(shapely.points(xy), polygons)
    shapes = [None] * len(bay_face)
    for f_index in np.unique(bay_face):
        facade = facades[f_index]
        if not facade.straight:
            continue
        origin = np.array(polygons[facade.part].centroid.coords[0])
        along = facade.direction
        inward = np.array([-along[1], along[0]])             # solid on the left
        reach = 0.5 * vs * (abs(along[0]) + abs(along[1]))  # half a column square along u and d
        same_part = part == facade.part
        on_facade = origin + ((facade.start - origin) @ inward) * inward   # u = 0, d = 0
        u_all = (xy - on_facade) @ along
        d_all = (xy - on_facade) @ inward
        k_face = np.floor(u_all[faces.face == f_index] / w + 1e-9)
        u_start, u_end = (facade.start - on_facade) @ along, (facade.end - on_facade) @ along
        for b in np.flatnonzero(bay_face == f_index):
            mine = bay == b
            others = same_part & ~mine
            u, d = u_all[mine], d_all[mine]
            u_lo, u_hi, d_lo, d_hi = u.min(), u.max(), d.min(), d.max()
            if (others & (u_all > u_lo + 1e-9) & (u_all < u_hi - 1e-9)
                    & (d_all > d_lo + 1e-9) & (d_all < d_hi - 1e-9)).any():
                continue
            in_u = others & (u_all >= u_lo - 1e-9) & (u_all <= u_hi + 1e-9)
            in_d = others & (d_all >= d_lo - 1e-9) & (d_all <= d_hi + 1e-9)
            gap = 2.0 * reach + 1e-9                          # a neighbouring column is this close

            def side(edge, outward, beyond):
                """Edge of the columns' squares, or one voxel further when nothing lies beyond."""
                return edge + outward * (reach if beyond.any() else reach + vs)

            k_lo, k_hi = np.floor(u_lo / w + 1e-9), np.floor(u_hi / w + 1e-9)
            u0 = (k_lo * w if (k_face == k_lo - 1).any()
                  else side(u_lo, -1.0, in_d & (u_all < u_lo) & (u_all >= u_lo - gap)))
            u1 = ((k_hi + 1) * w if (k_face == k_hi + 1).any()
                  else side(u_hi, 1.0, in_d & (u_all > u_hi) & (u_all <= u_hi + gap)))
            d0 = side(d_lo, -1.0, in_u & (d_all < d_lo) & (d_all >= d_lo - gap))
            behind = in_u & (d_all > d_hi) & (d_all <= d_hi + gap)
            d1 = side(d_hi, 1.0, behind)
            across = np.unique(faces.face[behind])
            if len(across) == 1 and facades[across[0]].straight                     and facades[across[0]].direction @ along < -1.0 + 1e-9:   # parallel, opposite
                d1 = 0.5 * ((facades[across[0]].start - on_facade) @ inward)
            pieces = [_rectangle(on_facade, along, inward, u0, u1, d0, d1)]
            a, z = max(u0, u_start), min(u1, u_end)
            if z > a and d0 > -vs:
                pieces.append(_rectangle(on_facade, along, inward, a, z, -vs, d1))
            shapes[b] = shapely.union_all(pieces)
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


def _drop_narrow_bays(keep, bay, cells_ij, grid_shape, side, n_cols):
    """Drop bays that keep less than half of their columns after a morphological
    opening with a *side* x *side* square (parts narrower than the minimum)."""
    from scipy.ndimage import binary_opening
    built = keep[bay]
    grid = np.zeros(grid_shape, dtype=bool)
    grid[cells_ij[built, 0], cells_ij[built, 1]] = True
    opened = binary_opening(grid, structure=np.ones((side, side), dtype=bool))
    surviving = opened[cells_ij[:, 0], cells_ij[:, 1]] & built
    share = np.bincount(bay, weights=surviving.astype(np.float64), minlength=len(keep))
    return keep & (share >= 0.5 * np.maximum(n_cols, 1))


def _label_plates(built, cells_ij, grid_shape):
    from scipy.ndimage import label
    grid = np.zeros(grid_shape, dtype=bool)
    grid[cells_ij[built, 0], cells_ij[built, 1]] = True
    labels, _ = label(grid)
    plate = labels[cells_ij[:, 0], cells_ij[:, 1]].astype(np.int64) - 1
    plate[~built] = -1
    return plate


def build_floors(cells_ij, bay, occupancy, kept, z_grid0, voxel_size, levels,
                 tolerance, stacking, min_dimension):
    """Decide, floor by floor, which bays are built.

    A bay is built on a floor when every one of its columns is filled by
    the maximum volume (*occupancy*) over the floor's full height, the share
    of its volume outside the carved envelope (*kept*) is at most
    *tolerance*, and, with ``stacking == "supported"``, it is built on the
    floor below.  Bays left in parts narrower than *min_dimension* are then
    dropped.  The connected built columns of a floor are its plates.

    The base is the bottom of the first level (the maximum volume's lowest
    point).  A voxel layer whose centre lies below it lies mostly below the
    maximum volume, and its voxels are filled only where rays hit the base,
    so columns along facades that are not aligned with the grid lack them.
    Such a layer does not count: the floor's height and the share outside
    the envelope are measured over the layers whose centre is at or above
    the base.
    """
    n_bays = int(bay.max()) + 1 if bay.size else 0
    occ_cols = occupancy[cells_ij[:, 0], cells_ij[:, 1], :].astype(np.float64)
    kept_cols = (kept & occupancy)[cells_ij[:, 0], cells_ij[:, 1], :].astype(np.float64)
    n_cols = np.bincount(bay, minlength=n_bays)
    grid_shape = occupancy.shape[:2]
    side = max(1, int(round(min_dimension / voxel_size)))
    n_layers = occupancy.shape[2]
    base = levels[0][0] if levels else z_grid0
    below_base = z_grid0 + (np.arange(n_layers) + 0.5) * voxel_size < base - 1e-9
    floors, below = [], None
    for zb, zt in levels:
        overlap = layer_overlaps(z_grid0, voxel_size, n_layers, zb, zt)
        height = zt - zb - overlap[below_base].sum()
        overlap[below_base] = 0.0
        column_full = occ_cols @ overlap >= height - 1e-6
        in_max = np.bincount(bay, weights=(~column_full).astype(np.float64), minlength=n_bays) == 0
        outside = (np.bincount(bay, weights=height - kept_cols @ overlap, minlength=n_bays)
                   / (np.maximum(n_cols, 1) * height))
        keep = in_max & (outside <= tolerance + 1e-9)
        if stacking == "supported" and below is not None:
            keep &= below
        keep = _drop_narrow_bays(keep, bay, cells_ij, grid_shape, side, n_cols)
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
    cut lines and ridges on the ridges; bays without a rectangle (curved
    facades, slanted ends) are drawn from their columns as below.  Without
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
        shape = _from_columns(cells_ij, in_plate, removed, vs)
    else:
        has_shape = np.array([s is not None for s in bay_shapes])
        pieces = [bay_shapes[b] for b in np.unique(bay[in_plate]) if has_shape[b]]
        by_columns = in_plate & ~has_shape[bay]
        if by_columns.any():
            pieces.append(_from_columns(cells_ij, by_columns, removed, vs))
        shape = shapely.union_all(pieces).buffer(vs / 2, join_style="mitre").buffer(-vs / 2, join_style="mitre")
        nearby_removed = np.unique(bay[removed & _near(cells_ij, in_plate, 2)])
        removed_rectangles = [bay_shapes[b] for b in nearby_removed if has_shape[b]]
        if removed_rectangles:
            shape = shape.difference(shapely.union_all(removed_rectangles))
        shape = shape.simplify(1e-6)
    shape = shape.intersection(footprint)
    parts = [p for p in getattr(shape, "geoms", [shape]) if isinstance(p, Polygon) and p.area > vs * vs]
    if min_dimension > 0.0:
        parts = [p for p in parts if not p.buffer(-0.5 * min_dimension + 1e-3).is_empty]
    return [orient(p, 1.0) for p in parts]


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
