"""Procedural urban-block scenes for end-to-end carving tests.

Every scene is one plot (max volume) with, unless ``neighbours`` is False,
four edge neighbours across streets. Protected test surfaces are the neighbour facades facing the plot
and, optionally, the plot's own lower floors (0..own_h). Each protected
panel is a separate inset quad: USC rejects joined non-planar components.
The neighbours' masses (one closed box behind each neighbour facade, its
front face on the facade) are the scene's context.

Scenes are built around the origin, then rotated by ``rotation_deg`` about
+Z and translated by ``offset``; rotation and translation tests rely on
that order.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import trimesh
from shapely.affinity import rotate as shp_rotate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

INSET = 0.05
TYPOLOGIES = (
    "courtyard", "towers", "rows", "freeform",
    "lshape", "podium", "irregular", "passage",
)


@dataclass(frozen=True)
class SceneSpec:
    typology: str
    plot: float = 20.0          # half-width of the plot (m)
    max_h: float = 24.0
    street: float = 10.0
    neigh_h: float = 12.0
    own_h: float = 6.0          # 0 disables own-facade protection
    neighbours: bool = True
    courtyard_ground: bool = False
    rotation_deg: float = 0.0
    offset: tuple = (0.0, 0.0, 0.0)
    seed: int = 0


@dataclass
class Scene:
    spec: SceneSpec
    volume: trimesh.Trimesh
    surfaces: trimesh.Trimesh
    panels: list = field(default_factory=list)   # [(quad_vertices (4,3), normal (3,))]
    own_panels: list = field(default_factory=list)
    context: "trimesh.Trimesh | None" = None      # the neighbour masses, when the scene has neighbours

    def write(self, folder: Path) -> tuple[Path, Path]:
        """PLY files with float64 vertices, so translated copies of a scene
        carry identical geometry (float32 rounding differs with magnitude)."""
        from urbansolarcarver.io import _export_ply_double
        folder.mkdir(parents=True, exist_ok=True)
        vol, srf = folder / "max_volume.ply", folder / "test_surfaces.ply"
        _export_ply_double(self.volume, str(vol))
        _export_ply_double(self.surfaces, str(srf))
        return vol, srf

    def write_context(self, folder: Path) -> "Path | None":
        """The context as ``context.ply`` (float64 vertices) in *folder*; None when the scene has none."""
        if self.context is None:
            return None
        from urbansolarcarver.io import _export_ply_double
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "context.ply"
        _export_ply_double(self.context, str(path))
        return path


# --------------------------------------------------------------------- footprints
def _star_polygon(rng, r_mean, n=9):
    ang = np.sort(rng.uniform(0, 2 * np.pi, n))
    rad = r_mean * rng.uniform(0.55, 1.0, n)
    poly = Polygon(np.c_[rad * np.cos(ang), rad * np.sin(ang)]).buffer(0)
    return poly if poly.geom_type == "Polygon" else max(poly.geoms, key=lambda g: g.area)


def footprint(spec: SceneSpec):
    P = spec.plot
    t = spec.typology
    if t == "courtyard":
        return box(-P, -P, P, P).difference(box(-0.55 * P, -0.55 * P, 0.55 * P, 0.55 * P))
    if t == "towers":
        w = 0.55 * P
        return unary_union([box(sx * P - (w if sx > 0 else 0), sy * P - (w if sy > 0 else 0),
                                sx * P + (0 if sx > 0 else w), sy * P + (0 if sy > 0 else w))
                            for sx in (-1, 1) for sy in (-1, 1)])
    if t == "rows":
        d = 0.35 * P
        return unary_union([box(-P, y0, P, y0 + d) for y0 in (-P, -d / 2, P - d)])
    if t == "freeform":
        xs = np.linspace(-0.75 * P, 0.75 * P, 30)
        curve = LineString(np.c_[xs, 0.5 * P * np.sin(np.pi * xs / (0.75 * P))])
        return curve.buffer(0.25 * P, quad_segs=4).simplify(0.2)
    if t == "lshape":
        return unary_union([box(-P, -P, P, -0.2 * P), box(-P, -P, -0.2 * P, P)])
    if t in ("podium", "passage"):
        return box(-P, -P, P, P)
    if t == "irregular":
        return _star_polygon(np.random.default_rng(spec.seed), 0.95 * P)
    raise ValueError(f"unknown typology {t!r}")


def _polys(geom):
    return list(geom.geoms) if hasattr(geom, "geoms") else [geom]


def _extrude(geom, z0, z1):
    parts = []
    for p in _polys(geom):
        m = trimesh.creation.extrude_polygon(orient(p, 1.0), z1 - z0)
        m.apply_translation((0, 0, z0))
        parts.append(m)
    return trimesh.util.concatenate(parts)


def max_volume(spec: SceneSpec, fp):
    P, H = spec.plot, spec.max_h
    if spec.typology == "podium":
        podium_h = 0.3 * H
        return trimesh.util.concatenate([
            _extrude(fp, 0, podium_h),
            _extrude(box(-0.4 * P, -0.4 * P, 0.4 * P, 0.4 * P), podium_h, H),
        ])
    if spec.typology == "passage":
        # Two wings joined by a bridge over a 6 m ground-floor passage (pre-existing void).
        gap, ph = 0.2 * P, min(6.0, 0.4 * H)
        return trimesh.util.concatenate([
            _extrude(box(-P, -P, -gap, P), 0, H),
            _extrude(box(gap, -P, P, P), 0, H),
            _extrude(box(-gap, -P, gap, P), ph, H),
        ])
    return _extrude(fp, 0, H)


# --------------------------------------------------------------------- panels
def _quad(p, q, z0, z1):
    p, q = np.asarray(p, float), np.asarray(q, float)
    d = q - p
    L = float(np.linalg.norm(d))
    if L <= 2 * INSET + 0.5:
        return None
    u = d / L
    p, q = p + u * INSET, q - u * INSET
    v = np.array([[p[0], p[1], z0], [q[0], q[1], z0], [q[0], q[1], z1], [p[0], p[1], z1]])
    n = np.array([d[1], -d[0], 0.0]) / L  # right-hand side of p->q
    return v, n


def _ground_quad(poly: Polygon, z=0.02):
    x0, y0, x1, y1 = poly.bounds
    v = np.array([[x0 + INSET, y0 + INSET, z], [x1 - INSET, y0 + INSET, z],
                  [x1 - INSET, y1 - INSET, z], [x0 + INSET, y1 - INSET, z]])
    return v, np.array([0.0, 0.0, 1.0])


def own_facades(fp, z0, z1):
    out = []
    for poly in _polys(fp):
        poly = orient(poly, sign=1.0)  # exterior CCW, holes CW -> right-hand normal faces out
        for ring in [poly.exterior, *poly.interiors]:
            c = list(ring.coords)
            for a, b in zip(c[:-1], c[1:]):
                qd = _quad(a, b, z0, z1)
                if qd is not None:
                    probe = qd[0].mean(axis=0) + 0.3 * qd[1]
                    assert not fp.contains(Point(probe[:2])), "own facade faces into the mass"
                    out.append(qd)
    return out


def neighbour_facades(spec: SceneSpec):
    P, S, Hn = spec.plot, spec.street, spec.neigh_h
    e = P + S
    return [q for q in (
        _quad((-P, e), (P, e), 0, Hn),     # north neighbour, faces -y
        _quad((P, -e), (-P, -e), 0, Hn),   # south neighbour, faces +y
        _quad((e, P), (e, -P), 0, Hn),     # east neighbour, faces -x
        _quad((-e, -P), (-e, P), 0, Hn),   # west neighbour, faces +x
    ) if q is not None]


NEIGHBOUR_DEPTH = 10.0


def neighbour_masses(spec: SceneSpec) -> list:
    """One closed box behind each neighbour facade: its front face is the facade quad, NEIGHBOUR_DEPTH deep, as high
    as the neighbours (before the scene's rotation and offset)."""
    return [trimesh.convex.convex_hull(np.vstack([v, v - NEIGHBOUR_DEPTH * n])) for v, n in neighbour_facades(spec)]


def _panel_mesh(v, n):
    m = trimesh.Trimesh(v, [[0, 1, 2], [0, 2, 3]], process=False)
    a, b, c = v[:3]
    if np.dot(np.cross(b - a, c - a), n) < 0:
        m = trimesh.Trimesh(v, [[0, 2, 1], [0, 3, 2]], process=False)
    return m


def _transform(spec: SceneSpec):
    T = trimesh.transformations.rotation_matrix(math.radians(spec.rotation_deg), (0, 0, 1))
    T[:3, 3] = spec.offset
    return T


def build(spec: SceneSpec) -> Scene:
    fp = footprint(spec)
    vol = max_volume(spec, fp)
    panels = neighbour_facades(spec) if spec.neighbours else []
    own = own_facades(fp, 0.0, spec.own_h) if spec.own_h > 0 else []
    if spec.courtyard_ground and spec.typology == "courtyard":
        own.append(_ground_quad(_polys(fp)[0].interiors and Polygon(_polys(fp)[0].interiors[0])))
    all_panels = panels + own
    if not all_panels:
        raise ValueError("scene has no protected surfaces")

    T = _transform(spec)
    R = T[:3, :3]

    def tf(v, n):
        return (v @ R.T) + T[:3, 3], n @ R.T

    all_panels = [tf(v, n) for v, n in all_panels]
    own = [tf(v, n) for v, n in own]
    vol = vol.copy()
    vol.apply_transform(T)
    surfaces = trimesh.util.concatenate([_panel_mesh(v, n) for v, n in all_panels])
    context = None
    if spec.neighbours:
        context = trimesh.util.concatenate(neighbour_masses(spec))
        context.apply_transform(T)
    return Scene(spec=spec, volume=vol, surfaces=surfaces, panels=all_panels, own_panels=own, context=context)


def random_spec(rng: np.random.Generator, **overrides) -> SceneSpec:
    """Draw a plausible scene: dimensions, orientation and georeferenced offsets vary."""
    offsets = [(0.0, 0.0, 0.0), (rng.uniform(-50, 50), rng.uniform(-50, 50), rng.uniform(0, 30)),
               (500000.0 + rng.uniform(0, 1000), 4500000.0 + rng.uniform(0, 1000), rng.uniform(0, 80))]
    spec = SceneSpec(
        typology=str(rng.choice(TYPOLOGIES)),
        plot=float(rng.uniform(14, 26)),
        max_h=float(rng.uniform(15, 35)),
        street=float(rng.uniform(6, 18)),
        neigh_h=float(rng.uniform(6, 18)),
        own_h=float(rng.choice([0.0, 3.0, 6.0, 9.0])),
        neighbours=bool(rng.random() < 0.85),
        courtyard_ground=bool(rng.random() < 0.3),
        rotation_deg=float(rng.choice([0.0, 0.0, 90.0, rng.uniform(0, 360)])),
        offset=tuple(float(x) for x in offsets[int(rng.integers(0, 3))]),
        seed=int(rng.integers(0, 2**31 - 1)),
    )
    spec = replace(spec, **overrides)
    if not spec.neighbours and spec.own_h == 0:
        spec = replace(spec, own_h=6.0)
    return spec
