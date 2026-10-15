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
