# Floor-Plate Massing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `massing` pipeline stage that turns the carved envelope into stacked floor plates (ground floor 5 m, upper floors 3 m) whose outlines follow the maximum volume's footprint and step back in bays cut perpendicular to the facades.

**Architecture:** Pure geometry functions in `src/urbansolarcarver/massing.py` (footprint and facades, nearest-facade faces with squared corners, bays, per-floor bay selection, plate outlines, prisms). A stage wrapper in `src/urbansolarcarver/api_core/massing.py` reads the thresholding chain, runs the functions, writes `plates.json`, `plates.obj`, manifest, diagnostics and the run report. CLI, daemon and two Grasshopper components expose it.

**Tech Stack:** Python 3.10, numpy, shapely 2.1 (`distance`, `line_locate_point`, `constrained_delaunay_triangles`), scipy.ndimage (`binary_opening`, `label`), trimesh (section, mesh, OBJ export), pydantic v2, typer, pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-floor-plate-massing-design.md`

## Global Constraints

- Run Python and tests with `.venv/Scripts/python` from the repo root (Windows, Git Bash). Test command form: `.venv/Scripts/python -m pytest <path> -q -p no:cacheprovider`.
- No new dependencies. Use only numpy, scipy, shapely (>= 2.1.1), trimesh, pydantic, typer already in `pyproject.toml`. Do not use `trimesh.creation.extrude_polygon` (needs `mapbox-earcut`, dev-only).
- Defaults, verbatim: `ground_floor_height = 5.0`, `floor_height = 3.0`, `min_plate_dimension = 3.0`, `plate_tolerance = 0.2`, `plate_stacking = "supported"`; corner angle 30 degrees.
- Plates never leave the maximum volume; `plate_tolerance` only allows volume the carving removed.
- Floors count from the lowest point of the maximum volume (sloped ground is out of scope).
- Work on branch `20261015_floor_plate_massing`. Do not merge or push.
- Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Writing style in code comments, docstrings and docs: no em dashes; no inflated labels ("the spine", "the crux", "load-bearing", "the heart of", "cornerstone"); state things plainly with numbers.
- Match the surrounding code: numpy-style docstrings, comment density like `carving.py` and `api_core/exporting.py`.
- Grasshopper component docstring ports must match their GH UI blocks (`tests/test_gh_components.py`).

## Review Focus

1. **Georeferenced coordinates** (footprint at x ~ 500 000 m): plate outlines must land on the footprint to within 1 cm; work in a local frame (world xy minus grid origin) and add the origin back on output. Test in Task 7.
2. **Parts starting above the lowest point** (a second block whose base is 2 m higher): no crash; a warning names the part; with `free` stacking it gets plates from the first floor fully inside it, with `supported` none. Test in Task 7.
3. **Footprint outline unreadable** (section of the mesh yields no closed polygon): fall back to the voxel footprint with a warning and still produce plates. Test in Task 7.
4. **Nothing buildable** (envelope lower than the ground floor, or a part thinner than `min_plate_dimension`): valid empty outputs (`plates.json` with an empty list, an empty `plates.obj`), a warning, no exception. Test in Task 7.
5. **Config voxel size differing from the preprocessing run**: the stage uses the manifest's voxel size and validates `min_plate_dimension` and the floor heights against it. Test in Task 7.

---

### Task 1: Massing settings in the config schema

**Files:**
- Modify: `src/urbansolarcarver/pydantic_schemas.py` (add fields after the `carve_above_min_consecutive` / `max_slope_deg` fields; add a validator next to `_check_sampling_and_batches`)
- Modify: `configs/REFERENCE_all_options.yaml` (add a "Massing" block after the slope-limit block)
- Test: `tests/test_massing_config.py`

**Interfaces:**
- Produces: `UserConfig.ground_floor_height: float`, `UserConfig.floor_height: float`, `UserConfig.min_plate_dimension: float`, `UserConfig.plate_tolerance: float`, `UserConfig.plate_stacking: Literal["supported", "free"]`.

- [ ] **Step 1: Write the failing test**

```python
"""Massing settings in UserConfig."""
import pytest

from urbansolarcarver.load_config import user_config

BASE = dict(max_volume_path="v.ply", test_surface_path="s.ply", out_dir="out",
            mode="tilted_plane", tilted_plane_angle_deg=45.0, voxel_size=1.0, grid_step=1.0)


def test_defaults():
    cfg = user_config(**BASE)
    assert cfg.ground_floor_height == 5.0
    assert cfg.floor_height == 3.0
    assert cfg.min_plate_dimension == 3.0
    assert cfg.plate_tolerance == 0.2
    assert cfg.plate_stacking == "supported"


@pytest.mark.parametrize("name", ["ground_floor_height", "floor_height", "min_plate_dimension"])
def test_sizes_below_one_voxel_are_rejected(name):
    with pytest.raises(ValueError, match=name):
        user_config(**dict(BASE, **{name: 0.5}))


@pytest.mark.parametrize("value", [-0.1, 1.5])
def test_tolerance_outside_0_1_is_rejected(value):
    with pytest.raises(ValueError):
        user_config(**dict(BASE, plate_tolerance=value))


def test_stacking_accepts_free_only_besides_supported():
    assert user_config(**dict(BASE, plate_stacking="free")).plate_stacking == "free"
    with pytest.raises(ValueError):
        user_config(**dict(BASE, plate_stacking="stacked"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_massing_config.py -q -p no:cacheprovider`
Expected: FAIL (`AttributeError: 'UserConfig' object has no attribute 'ground_floor_height'` or similar).

- [ ] **Step 3: Add the fields and validator**

In `pydantic_schemas.py`, after the `max_slope_deg` field, add:

```python
    # massing (floor plates; see docs/massing.md)
    ground_floor_height: float = Field(
        5.0, gt=0.0, description="Massing: height of the ground floor (m)")
    floor_height: float = Field(
        3.0, gt=0.0, description="Massing: height of every floor above the ground floor (m)")
    min_plate_dimension: float = Field(
        3.0, gt=0.0,
        description="Massing: bay width, and the minimum width of any floor plate (m)")
    plate_tolerance: float = Field(
        0.2, ge=0.0, le=1.0,
        description=(
            "Massing: largest share (0-1) of a bay's volume on a floor that may lie "
            "outside the carved envelope. Plates never leave the maximum volume."
        ),
    )
    plate_stacking: Literal["supported", "free"] = Field(
        "supported",
        description=(
            "Massing: 'supported' builds a bay on a floor only where it is built on the "
            "floor below; 'free' decides each floor on its own."
        ),
    )
```

Next to the other `@model_validator(mode='after')` methods, add:

```python
    @model_validator(mode='after')
    def _check_massing_sizes(self) -> 'UserConfig':
        """Massing sizes of less than one voxel cannot be represented on the grid."""
        for name in ("ground_floor_height", "floor_height", "min_plate_dimension"):
            value = getattr(self, name)
            if value < self.voxel_size - 1e-9:
                raise ValueError(
                    f"{name} ({value:g} m) must be at least voxel_size ({self.voxel_size:g} m)"
                )
        return self
```

In `configs/REFERENCE_all_options.yaml`, after the `max_slope_deg: null` block, add:

```yaml
# Massing (stage 4, see docs/massing.md): stacked floor plates that follow the
# maximum volume's footprint, cut into bays perpendicular to the facades.
ground_floor_height: 5.0          # m
floor_height: 3.0                 # m, every floor above the ground floor
min_plate_dimension: 3.0          # m, bay width and minimum plate width
plate_tolerance: 0.2              # share of a bay's volume allowed outside the carved envelope
plate_stacking: supported         # supported | free
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_massing_config.py tests/test_schemas.py tests/test_cli.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/pydantic_schemas.py configs/REFERENCE_all_options.yaml tests/test_massing_config.py
git commit -m "feat(massing): config settings for floor-plate massing

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Footprint and facades

**Files:**
- Create: `src/urbansolarcarver/massing.py`
- Test: `tests/test_massing.py`

**Interfaces:**
- Produces:
  - `CORNER_ANGLE_DEG: float = 30.0`
  - `@dataclass(frozen=True) class Facade: part: int; line: shapely.LineString; length: float; straight: bool; direction: np.ndarray; start: np.ndarray; end: np.ndarray; closed: bool`
  - `@dataclass(frozen=True) class Corner: ending: int; starting: int; convex: bool; point: np.ndarray`
  - `footprint_polygons(mesh: trimesh.Trimesh, offset_xy) -> list[shapely.Polygon]` (each body of the mesh sectioned 1 cm above its own lowest point, merged; local xy = world xy - offset_xy; empty list when no closed outline)
  - `footprint_from_columns(columns: np.ndarray (X, Y) bool, voxel_size: float) -> list[shapely.Polygon]` (local xy; column (i, j) covers [i*vs, (i+1)*vs] x [j*vs, (j+1)*vs])
  - `split_facades(polygons, corner_angle_deg=CORNER_ANGLE_DEG) -> tuple[list[Facade], list[Corner]]`

- [ ] **Step 1: Write the failing tests**

```python
"""Floor-plate massing geometry (massing.py)."""
import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Point, Polygon, box

from urbansolarcarver import massing as mg

L_SHAPE = Polygon([(0, 0), (60, 0), (60, 15), (15, 15), (15, 60), (0, 60)])


class TestFacades:
    def test_bar_has_four_straight_facades_and_convex_corners(self):
        facades, corners = mg.split_facades([box(0, 0, 80, 14)])
        assert sorted(round(f.length) for f in facades) == [14, 14, 80, 80]
        assert all(f.straight for f in facades)
        assert len(corners) == 4 and all(c.convex for c in corners)

    def test_l_shape_has_one_reflex_corner(self):
        facades, corners = mg.split_facades([L_SHAPE])
        assert len(facades) == 6
        reflex = [c for c in corners if not c.convex]
        assert len(reflex) == 1 and np.allclose(reflex[0].point, (15, 15))

    def test_courtyard_ring_has_outer_and_inner_facades(self):
        ring = box(0, 0, 80, 60).difference(box(15, 15, 65, 45))
        facades, corners = mg.split_facades([ring])
        assert len(facades) == 8
        assert sum(c.convex for c in corners) == 4
        assert sum(not c.convex for c in corners) == 4

    def test_round_tower_is_one_closed_facade(self):
        facades, corners = mg.split_facades([Point(0, 0).buffer(10, quad_segs=16)])
        assert len(facades) == 1 and facades[0].closed and not corners

    def test_kinks_below_30_degrees_continue_the_facade(self):
        a = np.radians(20)
        bar = LineString([(0, 0), (40, 0), (40 + 40 * np.cos(a), 40 * np.sin(a))]).buffer(
            7, cap_style="flat", join_style="mitre")
        facades, _ = mg.split_facades([bar])
        assert len(facades) == 4
        assert sum(not f.straight for f in facades) == 2


class TestFootprint:
    def test_section_is_in_local_coordinates(self):
        import trimesh
        mesh = trimesh.creation.box(extents=[20, 10, 5])
        mesh.apply_translation([500000.5, 4200000.25, 2.5])
        polys = mg.footprint_polygons(mesh, offset_xy=(499990.0, 4199995.0))
        assert len(polys) == 1
        assert np.allclose(polys[0].bounds, (0.5, 0.25, 20.5, 10.25))

    def test_each_body_is_sectioned_at_its_own_base(self):
        import trimesh
        low = trimesh.creation.box(extents=[10, 10, 20])
        low.apply_translation([-10, 0, 10])
        high = trimesh.creation.box(extents=[10, 10, 20])
        high.apply_translation([10, 0, 12])          # starts 2 m higher
        polys = mg.footprint_polygons(trimesh.util.concatenate([low, high]), offset_xy=(0, 0))
        assert len(polys) == 2 and sum(p.area for p in polys) == pytest.approx(200.0)

    def test_voxel_footprint_fallback(self):
        columns = np.zeros((10, 10), bool)
        columns[2:6, 3:6] = True
        polys = mg.footprint_from_columns(columns, 0.5)
        assert len(polys) == 1 and polys[0].area == pytest.approx(4 * 3 * 0.25)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_massing.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'massing'`.

- [ ] **Step 3: Write the implementation**

Create `src/urbansolarcarver/massing.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_massing.py -q -p no:cacheprovider`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/massing.py tests/test_massing.py
git commit -m "feat(massing): footprint outline and facades split at corners

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Faces (nearest facade, square corners)

**Files:**
- Modify: `src/urbansolarcarver/massing.py` (append)
- Test: `tests/test_massing.py` (append)

**Interfaces:**
- Consumes: `Facade`, `Corner`, `split_facades` (Task 2).
- Produces:
  - `part_of_points(points: shapely point array (N,), polygons) -> np.ndarray (N,) int`
  - `@dataclass(frozen=True) class Faces: face: np.ndarray (N,) int; u: np.ndarray (N,) float`
  - `assign_faces(xy: np.ndarray (N, 2), facades, corners, polygons, voxel_size: float) -> Faces`

Rules (from the spec): nearest facade; at a convex corner the shorter facade's columns inside the longer facade's strip and within its typical half depth move to the longer; at a reflex corner the columns whose nearest point on both facades is the corner vertex, within each facade's typical half depth of its tangent line, move to the longer. Ties: lower facade index. Convex rule first, reflex rule second. `u` = projection on the facade direction from the part centroid (straight facades) or arc length (others).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_massing.py`:

```python
def _cells(polygon, vs):
    """Grid columns (ij) and centres (xy) whose centre lies inside *polygon*."""
    x0, y0, x1, y1 = polygon.bounds
    i, j = np.meshgrid(np.arange(int(np.floor(x0 / vs)), int(np.ceil(x1 / vs))),
                       np.arange(int(np.floor(y0 / vs)), int(np.ceil(y1 / vs))), indexing="ij")
    ij = np.stack([i.ravel(), j.ravel()], axis=1)
    xy = (ij + 0.5) * vs
    inside = shapely.contains_xy(polygon, xy[:, 0], xy[:, 1])
    return ij[inside], xy[inside]


def _faces(polygon, vs=1.0):
    ij, xy = _cells(polygon, vs)
    facades, corners = mg.split_facades([polygon])
    return ij, xy, facades, mg.assign_faces(xy, facades, corners, [polygon], vs)


def _is_rectangle(ij):
    return len(ij) == (np.ptp(ij[:, 0]) + 1) * (np.ptp(ij[:, 1]) + 1)


class TestFaces:
    def test_bar_splits_into_two_long_faces(self):
        ij, xy, facades, faces = _faces(box(0, 0, 80, 14))
        long = {k for k, f in enumerate(facades) if f.length > 50}
        assert set(np.unique(faces.face)) == long
        bottom = next(k for k, f in enumerate(facades) if f.start[1] == 0 and f.end[1] == 0)
        assert (xy[faces.face == bottom, 1] < 7).all()
        for k in long:
            assert _is_rectangle(ij[faces.face == k])

    def test_square_faces_are_rectangles_and_cover_everything(self):
        ij, _, _, faces = _faces(box(0, 0, 24, 24))
        assert len(faces.face) == len(ij)
        for k in np.unique(faces.face):
            assert _is_rectangle(ij[faces.face == k])

    def test_l_reflex_corner_square_joins_one_45_m_arm(self):
        ij, xy, facades, faces = _faces(L_SHAPE)
        square = (xy[:, 0] > 7.5) & (xy[:, 0] < 15) & (xy[:, 1] > 7.5) & (xy[:, 1] < 15)
        owners = np.unique(faces.face[square])
        assert len(owners) == 1 and facades[owners[0]].length == pytest.approx(45)
        for k in np.unique(faces.face):
            assert _is_rectangle(ij[faces.face == k])

    def test_courtyard_faces_are_rectangles(self):
        ring = box(0, 0, 80, 60).difference(box(15, 15, 65, 45))
        ij, _, _, faces = _faces(ring)
        for k in np.unique(faces.face):
            assert _is_rectangle(ij[faces.face == k])

    def test_round_tower_uses_arc_length(self):
        circle = Point(0, 0).buffer(10, quad_segs=16)
        _, _, facades, faces = _faces(circle, vs=0.5)
        assert (faces.face == 0).all()
        assert faces.u.min() >= 0 and faces.u.max() <= facades[0].length + 1e-9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_massing.py::TestFaces -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: module 'urbansolarcarver.massing' has no attribute 'assign_faces'`.

- [ ] **Step 3: Write the implementation**

Append to `src/urbansolarcarver/massing.py`:

```python
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


def _typical_half_depth(depth, along, voxel_size):
    """Median, over positions along a facade, of the deepest column there."""
    if depth.size == 0:
        return 0.0
    bins = np.floor(along / voxel_size).astype(np.int64)
    order = np.argsort(bins, kind="stable")
    sorted_bins, sorted_depth = bins[order], depth[order]
    starts = np.flatnonzero(np.r_[True, sorted_bins[1:] != sorted_bins[:-1]])
    return float(np.median(np.maximum.reduceat(sorted_depth, starts)))


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
      longer facade (projection within its extent) and within its typical
      half depth move to the longer facade;
    * reflex corner: the columns whose nearest point on both facades is the
      corner vertex, and that lie within each facade's typical half depth of
      its tangent line, move to the longer facade, extending it past its end.

    Ties go to the lower facade index.  ``u`` is the projection on the facade
    direction measured from the part's centroid for straight facades (so
    parallel facades share cut positions), the arc length otherwise.
    """
    xy = np.asarray(xy, dtype=np.float64)
    points = shapely.points(xy)
    rows = np.arange(len(xy))
    part = part_of_points(points, polygons)
    facade_part = np.array([f.part for f in facades])
    lines = np.array([f.line for f in facades], dtype=object)
    dist = shapely.distance(points[:, None], lines[None, :])
    dist = np.where(part[:, None] == facade_part[None, :], dist, np.inf)
    nearest = np.argmin(dist, axis=1)

    half_depth = np.zeros(len(facades))
    for k, f in enumerate(facades):
        mine = nearest == k
        if mine.any():
            along = shapely.line_locate_point(f.line, points[mine])
            half_depth[k] = _typical_half_depth(dist[mine, k], along, voxel_size)

    face = nearest.copy()
    for c in (c for c in corners if c.convex):
        longer, shorter = _longer(c.ending, c.starting, facades)
        t = shapely.line_locate_point(facades[longer].line, points)
        in_front = (t > 1e-9) & (t < facades[longer].length - 1e-9)
        face[(nearest == shorter) & in_front & (dist[:, longer] <= half_depth[longer] + 1e-9)] = longer
    for c in (c for c in corners if not c.convex):
        ending, starting = facades[c.ending], facades[c.starting]
        longer, _ = _longer(c.ending, c.starting, facades)
        at_vertex = ((shapely.line_locate_point(ending.line, points) >= ending.length - 1e-9)
                     & (shapely.line_locate_point(starting.line, points) <= 1e-9))
        near = ((_distance_to_tangent(ending, True, xy) <= half_depth[c.ending] + 1e-9)
                & (_distance_to_tangent(starting, False, xy) <= half_depth[c.starting] + 1e-9))
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_massing.py -q -p no:cacheprovider`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/massing.py tests/test_massing.py
git commit -m "feat(massing): faces by nearest facade with squared corners

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Bays

**Files:**
- Modify: `src/urbansolarcarver/massing.py` (append)
- Test: `tests/test_massing.py` (append)

**Interfaces:**
- Consumes: `Faces` (Task 3).
- Produces: `cut_bays(faces: Faces, bay_width: float, voxel_size: float) -> tuple[np.ndarray, np.ndarray]` returning `bay` (N,) int ids `0..B-1` and `bay_face` (B,) facade index of each bay.

- [ ] **Step 1: Write the failing tests**

```python
def _bays(polygon, vs, width):
    ij, xy, facades, faces = _faces(polygon, vs)
    bay, bay_face = mg.cut_bays(faces, width, vs)
    return ij, xy, facades, faces, bay, bay_face


class TestBays:
    def test_cuts_line_up_on_both_sides_of_a_bar(self):
        _, xy, _, faces, bay, bay_face = _bays(box(0, 0, 80, 14), 0.5, 3.0)
        spans = {}
        for b in range(len(bay_face)):
            x = xy[bay == b, 0]
            spans.setdefault(bay_face[b], set()).add((round(x.min(), 6), round(x.max(), 6)))
        sides = list(spans.values())
        assert len(sides) == 2 and sides[0] == sides[1]

    def test_no_bay_narrower_than_the_bay_width(self):
        _, _, _, faces, bay, bay_face = _bays(box(0, 0, 80, 14), 0.5, 3.0)
        for b in range(len(bay_face)):
            u = faces.u[bay == b]
            assert u.max() - u.min() + 0.5 >= 3.0 - 1e-9

    def test_short_end_bays_merge(self):
        # 10 m bar, centroid at x = 5: cuts at x = 2, 5, 8; the 2 m end bays merge.
        _, xy, _, _, bay, bay_face = _bays(box(0, 0, 10, 6), 0.5, 3.0)
        for f in np.unique(bay_face):
            widths = sorted(np.ptp(xy[bay == b, 0]) + 0.5 for b in np.flatnonzero(bay_face == f))
            assert widths == [5.0, 5.0]

    def test_round_tower_bays_follow_the_curve(self):
        _, _, facades, _, bay, bay_face = _bays(Point(0, 0).buffer(10, quad_segs=16), 0.5, 3.0)
        assert abs(len(bay_face) - facades[0].length / 3.0) <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_massing.py::TestBays -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: ... has no attribute 'cut_bays'`.

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_massing.py -q -p no:cacheprovider`
Expected: PASS (17 tests).

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/massing.py tests/test_massing.py
git commit -m "feat(massing): bays cut perpendicular to the facades

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Floors (which bays are built)

**Files:**
- Modify: `src/urbansolarcarver/massing.py` (append)
- Test: `tests/test_massing.py` (append)

**Interfaces:**
- Consumes: `cut_bays` output (`bay` (N,)), footprint columns `cells_ij` (N, 2).
- Produces:
  - `floor_levels(z0, z_top, ground_floor_height, floor_height) -> list[tuple[float, float]]`
  - `layer_overlaps(z_grid0, voxel_size, nz, zb, zt) -> np.ndarray (nz,)`
  - `@dataclass(frozen=True) class Floor: zb: float; zt: float; kept_bays: np.ndarray (B,) bool; outside_share: np.ndarray (B,) float; plate: np.ndarray (N,) int (-1 = not built)`
  - `build_floors(cells_ij, bay, occupancy, kept, z_grid0, voxel_size, levels, tolerance, stacking, min_dimension) -> list[Floor]`

- [ ] **Step 1: Write the failing tests**

```python
def _bar_grid(nx=20, ny=6, nz=40, top=33, bay=3.0):
    """A 20 x 6 m bar on a 1 m grid aligned with the polygon; occupied below z = top."""
    poly = box(0, 0, nx, ny)
    ij, xy = _cells(poly, 1.0)
    facades, corners = mg.split_facades([poly])
    bays, _ = mg.cut_bays(mg.assign_faces(xy, facades, corners, [poly], 1.0), bay, 1.0)
    occ = np.zeros((nx, ny, nz), bool)
    occ[:, :, :top] = True
    return ij, bays, occ


def _floors(ij, bays, occ, kept, levels=None, tolerance=0.2, stacking="supported", min_dim=3.0):
    levels = levels if levels is not None else mg.floor_levels(0.0, 33.0, 5.0, 3.0)
    return mg.build_floors(ij, bays, occ, kept, 0.0, 1.0, levels, tolerance, stacking, min_dim)


class TestFloors:
    def test_floor_levels(self):
        levels = mg.floor_levels(0.0, 33.0, 5.0, 3.0)
        assert len(levels) == 10 and levels[0] == (0.0, 5.0) and levels[-1] == (29.0, 32.0)
        assert mg.floor_levels(0.0, 4.0, 5.0, 3.0) == []

    def test_layer_overlaps_count_partial_voxels_by_length(self):
        assert np.allclose(mg.layer_overlaps(0.0, 1.0, 5, 0.5, 2.5), [0.5, 1, 1, 0, 0])

    def test_tolerance_zero_builds_nothing_outside_the_envelope(self):
        ij, bays, occ = _bar_grid()
        kept = occ.copy()
        kept[10:, :, 20:] = False
        for fl in _floors(ij, bays, occ, kept, tolerance=0.0):
            assert np.all(fl.outside_share[fl.kept_bays] == 0.0)

    def test_never_outside_the_maximum_volume(self):
        ij, bays, occ = _bar_grid()
        occ[10:, :, 20:] = False
        for fl in _floors(ij, bays, occ, occ.copy(), tolerance=1.0):
            if fl.zt > 20:
                assert not (fl.plate[ij[:, 0] >= 10] >= 0).any()

    def test_supported_never_builds_on_nothing(self):
        ij, bays, occ = _bar_grid()
        kept = occ.copy()
        kept[:6, :, 20:23] = False
        supported = _floors(ij, bays, occ, kept, tolerance=0.0)
        for lower, upper in zip(supported, supported[1:]):
            assert not (upper.kept_bays & ~lower.kept_bays).any()
        free = _floors(ij, bays, occ, kept, tolerance=0.0, stacking="free")
        assert any((upper.kept_bays & ~lower.kept_bays).any() for lower, upper in zip(free, free[1:]))

    def test_carving_more_never_builds_more(self):
        ij, bays, occ = _bar_grid()
        loose = occ.copy()
        loose[12:, :, 15:] = False
        tight = loose.copy()
        tight[:5, :3, 10:] = False
        for a, b in zip(_floors(ij, bays, occ, loose), _floors(ij, bays, occ, tight)):
            assert not ((b.plate >= 0) & (a.plate < 0)).any()

    def test_plates_narrower_than_the_minimum_are_dropped(self):
        ij, bays, occ = _bar_grid()
        kept = occ.copy()
        kept[:, 3:, 20:] = False   # only the 3 m deep south face fits above 20 m
        floors = _floors(ij, bays, occ, kept, tolerance=0.0, min_dim=4.0)
        for fl in floors:
            if fl.zb >= 20:
                assert (fl.plate < 0).all()

    def test_outside_share_by_length(self):
        ij, bays, occ = _bar_grid()
        kept = occ.copy()
        kept[:, :, 2:] = False
        fl = _floors(ij, bays, occ, kept, levels=[(0.0, 2.5)], tolerance=1.0)[0]
        assert np.allclose(fl.outside_share, 0.5 / 2.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_massing.py::TestFloors -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: ... has no attribute 'floor_levels'`.

- [ ] **Step 3: Write the implementation**

```python
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
    """
    n_bays = int(bay.max()) + 1 if bay.size else 0
    occ_cols = occupancy[cells_ij[:, 0], cells_ij[:, 1], :].astype(np.float64)
    kept_cols = (kept & occupancy)[cells_ij[:, 0], cells_ij[:, 1], :].astype(np.float64)
    n_cols = np.bincount(bay, minlength=n_bays)
    grid_shape = occupancy.shape[:2]
    side = max(1, int(round(min_dimension / voxel_size)))
    floors, below = [], None
    for zb, zt in levels:
        overlap = layer_overlaps(z_grid0, voxel_size, occupancy.shape[2], zb, zt)
        height = zt - zb
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_massing.py -q -p no:cacheprovider`
Expected: PASS (25 tests).

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/massing.py tests/test_massing.py
git commit -m "feat(massing): floor-by-floor bay selection with tolerance and stacking

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Plate outlines and prisms

**Files:**
- Modify: `src/urbansolarcarver/massing.py` (append)
- Test: `tests/test_massing.py` (append)

**Interfaces:**
- Produces:
  - `plate_polygons(cells_ij, in_plate: (N,) bool, removed: (N,) bool, voxel_size, footprint) -> list[Polygon]` (local xy; facade edges taken from *footprint*)
  - `prism_mesh(polygon, zb, zt) -> trimesh.Trimesh` (closed, outward normals)

- [ ] **Step 1: Write the failing tests**

```python
class TestPlateGeometry:
    def test_full_plate_is_the_footprint(self):
        poly = box(0, 0, 20, 6)
        ij, _ = _cells(poly, 1.0)
        out = mg.plate_polygons(ij, np.ones(len(ij), bool), np.zeros(len(ij), bool), 1.0, poly)
        assert len(out) == 1 and out[0].symmetric_difference(poly).area < 1e-9

    def test_cut_edge_on_the_column_boundary(self):
        poly = box(0, 0, 20, 6)
        ij, _ = _cells(poly, 1.0)
        in_plate = ij[:, 0] < 10
        out = mg.plate_polygons(ij, in_plate, ~in_plate, 1.0, poly)
        assert len(out) == 1 and out[0].area == pytest.approx(60.0)

    def test_rotated_footprint_keeps_exact_facades(self):
        from shapely import affinity
        poly = affinity.rotate(box(0, 0, 20, 6), 30, origin=(0, 0))
        poly = affinity.translate(poly, 10, 2)
        ij, _ = _cells(poly, 0.5)
        out = mg.plate_polygons(ij, np.ones(len(ij), bool), np.zeros(len(ij), bool), 0.5, poly)
        assert len(out) == 1 and out[0].symmetric_difference(poly).area < 1e-6

    def test_prism_is_closed_with_the_right_volume(self):
        plate = box(0, 0, 10, 6).difference(box(3, 2, 5, 4))
        mesh = mg.prism_mesh(plate, 5.0, 8.0)
        assert mesh.is_watertight and mesh.is_winding_consistent
        assert mesh.volume == pytest.approx(plate.area * 3.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_massing.py::TestPlateGeometry -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: ... has no attribute 'plate_polygons'`.

- [ ] **Step 3: Write the implementation**

```python
# ----------------------------------------------------------------- plate geometry
def _squares(cells_ij, mask, voxel_size):
    i, j = cells_ij[mask, 0], cells_ij[mask, 1]
    vs = float(voxel_size)
    return shapely.union_all(shapely.box(i * vs, j * vs, (i + 1) * vs, (j + 1) * vs))


def plate_polygons(cells_ij, in_plate, removed, voxel_size, footprint):
    """Outline of one floor plate (local xy).

    The plate's column squares are grown by one and a half voxels (enough
    to reach the facade after simplification), the squares of the *removed*
    columns are subtracted, and the result is simplified to half a voxel
    and clipped to the exact *footprint*.  Facade edges therefore
    come from the footprint; cuts between built and removed columns are
    straight to within half a voxel.
    """
    vs = float(voxel_size)
    shape = _squares(cells_ij, in_plate, vs).buffer(1.5 * vs, join_style="mitre")
    if np.any(removed):
        shape = shape.difference(_squares(cells_ij, removed, vs))
    shape = shape.simplify(vs / 2, preserve_topology=True).intersection(footprint)
    parts = getattr(shape, "geoms", [shape])
    return [orient(p, 1.0) for p in parts if isinstance(p, Polygon) and p.area > vs * vs]


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_massing.py -q -p no:cacheprovider`
Expected: PASS (29 tests).

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/massing.py tests/test_massing.py
git commit -m "feat(massing): plate outlines and closed prisms

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The massing stage

**Files:**
- Modify: `src/urbansolarcarver/api_core/_util.py` (add `ThresholdedGrid`, `load_thresholded_grid`)
- Modify: `src/urbansolarcarver/api_core/exporting.py:118-153` (use `load_thresholded_grid`; behaviour and error messages unchanged)
- Modify: `src/urbansolarcarver/pydantic_schemas.py` (add `MassingManifest` after `ThresholdingManifest`)
- Create: `src/urbansolarcarver/api_core/massing.py`
- Modify: `src/urbansolarcarver/api_core/__init__.py`, `src/urbansolarcarver/api.py`, `src/urbansolarcarver/__init__.py` (export `massing`, `MassingResult`)
- Test: `tests/test_massing_stage.py`

**Interfaces:**
- Consumes: everything in `massing.py` (Tasks 2-6); `UserConfig` massing fields (Task 1).
- Produces:
  - `load_thresholded_grid(threshold_manifest, conf) -> ThresholdedGrid` with fields `thr_path: Path`, `thr_manifest`, `pre_path: Path`, `pre_manifest`, `mask: np.ndarray (X,Y,Z) bool`, `occupancy: np.ndarray (X,Y,Z) bool`, `origin: np.ndarray (3,)`, `voxel_size: float`
  - `MassingManifest(hash: str, plates_path: str, mesh_path: str, upstream_manifest: str)`
  - `@dataclass(frozen=True) class MassingResult: out_dir: Path; plates_path: Path; mesh_path: Path; floor_areas: list[float]; total_floor_area: float; n_plates: int` (`__fspath__` -> plates_path)
  - `massing(threshold_manifest, cfg, out_dir) -> MassingResult`
  - `plates.json` format: `{"plates": [{"floor": int, "plate": int, "z_bottom": float, "z_top": float, "area_m2": float, "bays": int, "outside_share": float, "outline": [[x, y], ...], "holes": [[[x, y], ...], ...]}], "floor_area_m2_per_floor": [float, ...], "total_floor_area_m2": float}` (world coordinates, rings closed)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_massing_stage.py`:

```python
"""The massing stage end to end on small synthetic scenes (CPU)."""
import json
import warnings

import numpy as np
import pytest
import trimesh
import yaml


def _run_upstream(tmp_path, volume, voxel=1.0, **cfg_over):
    """Preprocess and threshold *volume* (daylight mode, CPU); returns (cfg_path, thr_dir)."""
    from urbansolarcarver import preprocessing, thresholding
    from urbansolarcarver.load_config import load_config
    vol_path = tmp_path / "max_volume.ply"
    volume.export(vol_path)
    lo, hi = volume.bounds
    y = lo[1] - 8.0   # a facade 8 m south of the volume, facing it
    srf = trimesh.Trimesh([[lo[0], y, 0], [hi[0], y, 0], [hi[0], y, 10], [lo[0], y, 10]],
                          [[0, 2, 1], [0, 3, 2]])
    srf_path = tmp_path / "surface.ply"
    srf.export(srf_path)
    cfg = dict(max_volume_path=str(vol_path), test_surface_path=str(srf_path),
               out_dir=str(tmp_path / "out"), mode="daylight", voxel_size=voxel,
               grid_step=voxel, ray_length=80.0, device="cpu", min_voxels=1, min_face_count=0)
    cfg.update(cfg_over)
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))
    conf = load_config(str(cfg_path))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = preprocessing(conf, tmp_path / "out" / "preprocessing")
        thr = thresholding(pre, conf, tmp_path / "out" / "thresholding")
    return cfg_path, thr.out_dir


def _set_mask(thr_dir, fn):
    """Replace mask.npy with fn(occupancy) for deterministic tests."""
    man = json.loads((thr_dir / "manifest.json").read_text())
    pre = json.loads(open(man["upstream_manifest"]).read())
    occ = np.load(pre["voxel_grid_path"]).astype(bool)
    np.save(man["mask_path"], fn(occ))


def _box(extents, center_xy=(0.0, 0.0), z0=0.0):
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation([center_xy[0], center_xy[1], z0 + extents[2] / 2])
    return mesh


def _massing(cfg_path, thr_dir, out, **over):
    from urbansolarcarver import massing
    from urbansolarcarver.load_config import load_config
    conf = load_config(str(cfg_path), [f"{k}={v}" for k, v in over.items()])
    return massing(thr_dir, conf, out)


def test_full_envelope_gives_every_floor_the_footprint(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    res = _massing(cfg, thr, tmp_path / "out" / "massing")
    assert len(res.floor_areas) == 6            # 0-5, then five 3 m floors up to 20 m
    assert res.total_floor_area == pytest.approx(6 * 30 * 12, rel=1e-6)
    data = json.loads(res.plates_path.read_text())
    assert len(data["plates"]) == res.n_plates == 6
    scene = trimesh.load(res.mesh_path, force="scene")
    assert len(scene.geometry) == 6
    assert all(g.is_watertight for g in scene.geometry.values())


def test_georeferenced_outlines_land_on_the_footprint(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20], center_xy=(500000.0, 4200000.0)))
    _set_mask(thr, lambda occ: occ)
    res = _massing(cfg, thr, tmp_path / "out" / "massing")
    outline = np.array(json.loads(res.plates_path.read_text())["plates"][0]["outline"])
    assert np.allclose(outline.min(0), [499985.0, 4199994.0], atol=0.01)
    assert np.allclose(outline.max(0), [500015.0, 4200006.0], atol=0.01)


def test_raised_part_warns_and_follows_stacking(tmp_path):
    low = _box([12, 12, 20], center_xy=(-10.0, 0.0))
    high = _box([12, 12, 20], center_xy=(10.0, 0.0), z0=2.0)
    cfg, thr = _run_upstream(tmp_path, trimesh.util.concatenate([low, high]))
    _set_mask(thr, lambda occ: occ)
    with pytest.warns(UserWarning, match="above the lowest point"):
        supported = _massing(cfg, thr, tmp_path / "s")
    plates = json.loads(supported.plates_path.read_text())["plates"]
    assert all(np.array(p["outline"])[:, 0].max() < 0 for p in plates)    # only the low block
    with pytest.warns(UserWarning, match="above the lowest point"):
        free = _massing(cfg, thr, tmp_path / "f", plate_stacking="free")
    plates = json.loads(free.plates_path.read_text())["plates"]
    assert any(np.array(p["outline"])[:, 0].min() > 0 for p in plates)    # high block too


def test_unreadable_outline_falls_back_to_voxels(tmp_path, monkeypatch):
    from urbansolarcarver import massing as mg
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    monkeypatch.setattr(mg, "footprint_polygons", lambda mesh, offset_xy: [])
    with pytest.warns(UserWarning, match="voxel footprint"):
        res = _massing(cfg, thr, tmp_path / "m")
    assert res.n_plates == 6
    assert res.floor_areas[0] == pytest.approx(30 * 12, rel=0.1)


def test_nothing_buildable_gives_valid_empty_outputs(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))

    def low_only(occ):
        z = np.flatnonzero(occ.any(axis=(0, 1)))
        mask = occ.copy()
        mask[:, :, z.min() + 3:] = False      # 3 m left: lower than the 5 m ground floor
        return mask
    _set_mask(thr, low_only)
    with pytest.warns(UserWarning, match="no floor plates"):
        res = _massing(cfg, thr, tmp_path / "m", plate_tolerance=0.0)
    assert res.n_plates == 0 and res.total_floor_area == 0.0
    assert json.loads(res.plates_path.read_text())["plates"] == []
    assert res.mesh_path.is_file()


def test_part_thinner_than_the_minimum_builds_nothing(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 2, 20]))
    _set_mask(thr, lambda occ: occ)
    with pytest.warns(UserWarning, match="no floor plates"):
        res = _massing(cfg, thr, tmp_path / "m")
    assert res.n_plates == 0


def test_uses_the_preprocessing_voxel_size(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    a = _massing(cfg, thr, tmp_path / "a")
    b = _massing(cfg, thr, tmp_path / "b", voxel_size=2.0)       # config differs from the run
    assert a.floor_areas == pytest.approx(b.floor_areas)
    with pytest.raises(ValueError, match="min_plate_dimension"):
        _massing(cfg, thr, tmp_path / "c", voxel_size=0.5, grid_step=0.5, min_plate_dimension=0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_massing_stage.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'massing' from 'urbansolarcarver'`.

- [ ] **Step 3: Add the shared loader and refactor exporting**

In `api_core/_util.py` add (imports: `from dataclasses import dataclass`; `import numpy as np` is already imported inside `load_occupancy`, import it at module top):

```python
@dataclass(frozen=True)
class ThresholdedGrid:
    """The thresholding chain of a run: manifests, mask and occupancy grid."""
    thr_path: Path
    thr_manifest: object
    pre_path: Path
    pre_manifest: object
    mask: "np.ndarray"
    occupancy: "np.ndarray"
    origin: "np.ndarray"
    voxel_size: float


def load_thresholded_grid(threshold_manifest, conf) -> ThresholdedGrid:
    """Load a thresholding manifest, its preprocessing manifest, the mask and
    the occupancy grid.  *threshold_manifest* is a ThresholdingResult or a
    path to its folder or manifest.json."""
    import numpy as np
    from ..pydantic_schemas import PreprocessingManifest, ThresholdingManifest, schema_from_json
    thr_path = Path(threshold_manifest)
    if thr_path.is_dir():
        thr_path = thr_path / "manifest.json"
    try:
        thr_manifest = schema_from_json(ThresholdingManifest, thr_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("Unable to load thresholding manifest; pass a ThresholdingResult or a path to its manifest.json") from exc
    pre_path = Path(thr_manifest.upstream_manifest)
    try:
        pre_manifest = schema_from_json(PreprocessingManifest, pre_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(
            f"Unable to load the preprocessing manifest referenced by the "
            f"thresholding manifest ({pre_path}). Re-run preprocessing, "
            f"or fix the manifest chain."
        ) from exc
    grid_shape = tuple(pre_manifest.shape)
    mask_path = Path(thr_manifest.mask_path)
    if not mask_path.is_file():
        raise FileNotFoundError(
            f"Mask file not found: {mask_path} (referenced by {thr_path}). "
            f"Re-run thresholding."
        )
    mask = np.load(mask_path, allow_pickle=False)
    if mask.ndim == 1:
        mask = mask.reshape(grid_shape)
    elif tuple(mask.shape) != grid_shape:
        raise ValueError(
            f"Mask shape {tuple(mask.shape)} does not match the grid shape "
            f"{grid_shape} recorded in {pre_path}; the mask and manifest "
            f"are from different runs."
        )
    return ThresholdedGrid(
        thr_path=thr_path, thr_manifest=thr_manifest, pre_path=pre_path,
        pre_manifest=pre_manifest, mask=mask.astype(bool),
        occupancy=load_occupancy(pre_manifest, conf),
        origin=np.asarray(pre_manifest.origin, dtype=np.float64),
        voxel_size=float(pre_manifest.voxel_size or conf.voxel_size),
    )
```

In `exporting.py`, replace the block from `thr_path = Path(threshold_manifest)` through the mask-shape check (the manifest loading, `upstream_path`, `grid_shape`, mask loading) with:

```python
    chain = load_thresholded_grid(threshold_manifest, conf)
    thr_path, thr_manifest, pre_manifest = chain.thr_path, chain.thr_manifest, chain.pre_manifest
    mask = chain.mask
```

and replace `voxel_grid = torch.as_tensor(load_occupancy(pre_manifest, conf), device=resolved_device)` with `voxel_grid = torch.as_tensor(chain.occupancy, device=resolved_device)`. Update the import line to `from ._util import _resolve_cfg, _ensure_out_dir, ensure_diag, write_json, resolve_device, load_thresholded_grid`. Keep every later use of `thr_path`, `thr_manifest` and `pre_manifest` unchanged.

Run: `.venv/Scripts/python -m pytest tests/test_exporting.py tests/test_pipeline.py -q -p no:cacheprovider`
Expected: PASS (exporting unchanged).

- [ ] **Step 4: Add the manifest and the stage**

In `pydantic_schemas.py`, after `ThresholdingManifest`:

```python
class MassingManifest(BaseModel):
    """Manifest written by massing."""

    hash: str
    plates_path: str
    mesh_path: str
    upstream_manifest: str
```

Create `src/urbansolarcarver/api_core/massing.py`:

```python
"""Massing stage: stacked floor plates from the carved envelope.

Reads the thresholding manifest, builds floor plates that follow the
maximum volume's footprint (``urbansolarcarver.massing``), and writes them
as ``plates.json`` (outlines in world coordinates) and ``plates.obj`` (one
closed prism per plate), with a manifest, diagnostics and the run report.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

import numpy as np
import shapely

from .. import massing as mg
from ..io import load_mesh
from ..load_config import user_config
from ..pydantic_schemas import MassingManifest, schema_to_json
from ._reporting import generate_run_report
from ._util import _ensure_out_dir, _resolve_cfg, ensure_diag, load_thresholded_grid, write_json

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MassingResult:
    """Immutable record returned by :func:`massing`; path-like to ``plates.json``."""
    out_dir: Path
    plates_path: Path
    mesh_path: Path
    floor_areas: List[float]
    total_floor_area: float
    n_plates: int

    def __fspath__(self) -> str:
        return str(self.plates_path)


def _footprint(conf, origin, columns, voxel_size):
    """Footprint polygons (local xy) and their source ("mesh" or "voxels")."""
    try:
        polygons = mg.footprint_polygons(load_mesh(conf.max_volume_path), origin[:2])
    except Exception as exc:  # unreadable or broken mesh
        log.warning("massing: could not section the maximum volume: %s", exc)
        polygons = []
    if polygons:
        return polygons, "mesh"
    warnings.warn("massing: the maximum volume's base outline could not be read; "
                  "using the voxel footprint", UserWarning, stacklevel=3)
    return mg.footprint_from_columns(columns, voxel_size), "voxels"


def _warn_raised_parts(polygons, cells_ij, xy, occ, z0, origin_z, voxel_size):
    part = mg.part_of_points(shapely.points(xy), polygons)
    lowest = occ.argmax(axis=2)[cells_ij[:, 0], cells_ij[:, 1]]
    for k in range(len(polygons)):
        mine = part == k
        if not mine.any():
            continue
        base = origin_z + lowest[mine].min() * voxel_size
        if base > z0 + 1e-6:
            warnings.warn(f"massing: part {k} starts {base - z0:.2f} m above the lowest point; "
                          f"floors count from the lowest point (sloped ground is not supported yet)",
                          UserWarning, stacklevel=3)


def massing(threshold_manifest, cfg: Union[user_config, str, Path],
            out_dir: Union[str, Path]) -> MassingResult:
    """Fourth stage: floor plates that follow the footprint, from the carved envelope.

    Floors are ``ground_floor_height`` then ``floor_height`` tall, counted
    from the lowest point of the maximum volume.  The footprint (the maximum
    volume's outline 1 cm above its base) is split into faces, one per
    facade, and each face into bays ``min_plate_dimension`` wide, cut
    perpendicular to its facade.  A bay is built on a floor when it stays in
    the maximum volume over the floor's full height, at most
    ``plate_tolerance`` of its volume lies outside the carved envelope, and
    (with ``plate_stacking: supported``) it is built on the floor below.
    See :mod:`urbansolarcarver.massing`.

    Parameters
    ----------
    threshold_manifest : ThresholdingResult | str | Path
        Thresholding result, or a path to its folder or manifest.json.
    cfg : user_config | str | Path
        Validated config or path to config file.
    out_dir : str | Path
        Output directory for this stage; created if it does not exist.

    Returns
    -------
    MassingResult

    Persisted artifacts
    -------------------
    ``plates.json``
        One entry per plate: floor, z bottom and top, outline and holes in
        world coordinates, floor area, bay count and outside share; plus
        floor areas per floor and in total.
    ``plates.obj``
        One closed mesh per plate, named ``floor_<n>_plate_<m>``.
    ``manifest.json``, ``diagnostics/diagnostic.json``, ``run_report.md``

    Raises
    ------
    ValueError
        If a manifest cannot be read, or a massing size is smaller than the
        preprocessing run's voxel size.
    """
    t0_wall, t0_cpu = time.perf_counter(), time.process_time()
    conf = _resolve_cfg(cfg)
    out_path = _ensure_out_dir(out_dir, "massing")
    chain = load_thresholded_grid(threshold_manifest, conf)
    vs, origin = chain.voxel_size, chain.origin
    for name in ("min_plate_dimension", "ground_floor_height", "floor_height"):
        if getattr(conf, name) < vs - 1e-9:
            raise ValueError(f"{name} ({getattr(conf, name):g} m) is smaller than the voxel "
                             f"size of the preprocessing run ({vs:g} m)")

    occ = chain.occupancy
    kept = occ & chain.mask
    columns = occ.any(axis=2)
    cells_ij = np.argwhere(columns)
    xy = (cells_ij + 0.5) * vs
    polygons, footprint_source = _footprint(conf, origin, columns, vs)
    facades, corners = mg.split_facades(polygons)
    faces = mg.assign_faces(xy, facades, corners, polygons, vs)
    bay, _ = mg.cut_bays(faces, conf.min_plate_dimension, vs)
    n_cols = np.bincount(bay)

    layers = np.flatnonzero(occ.any(axis=(0, 1)))
    z0 = origin[2] + layers.min() * vs
    z_top = origin[2] + (layers.max() + 1) * vs
    _warn_raised_parts(polygons, cells_ij, xy, occ, z0, origin[2], vs)
    levels = mg.floor_levels(z0, z_top, conf.ground_floor_height, conf.floor_height)
    floors = mg.build_floors(cells_ij, bay, occ, kept, origin[2], vs, levels,
                             conf.plate_tolerance, conf.plate_stacking, conf.min_plate_dimension)

    footprint = shapely.union_all(polygons)
    plates, meshes, floor_areas = [], [], []
    for n, floor in enumerate(floors):
        area_this_floor = 0.0
        for p in range(int(floor.plate.max()) + 1):
            in_plate = floor.plate == p
            bays_in = np.unique(bay[in_plate])
            outside = float((floor.outside_share[bays_in] * n_cols[bays_in]).sum()
                            / n_cols[bays_in].sum())
            for m, poly in enumerate(mg.plate_polygons(cells_ij, in_plate, ~in_plate, vs, footprint)):
                world = shapely.affinity.translate(poly, origin[0], origin[1])
                plates.append({
                    "floor": n, "plate": len([q for q in plates if q["floor"] == n]),
                    "z_bottom": floor.zb, "z_top": floor.zt, "area_m2": float(poly.area),
                    "bays": int(len(bays_in)), "outside_share": round(outside, 4),
                    "outline": np.asarray(world.exterior.coords).tolist(),
                    "holes": [np.asarray(r.coords).tolist() for r in world.interiors],
                })
                prism = mg.prism_mesh(poly, floor.zb, floor.zt)
                prism.apply_translation([origin[0], origin[1], 0.0])
                meshes.append((f"floor_{n}_plate_{plates[-1]['plate']}", prism))
                area_this_floor += float(poly.area)
        floor_areas.append(area_this_floor)
    total = float(sum(floor_areas))

    plates_path = out_path / "plates.json"
    plates_path.write_text(json.dumps({"plates": plates, "floor_area_m2_per_floor": floor_areas,
                                       "total_floor_area_m2": total}, indent=1), encoding="utf-8")
    mesh_path = out_path / "plates.obj"
    if meshes:
        import trimesh
        scene = trimesh.Scene()
        for name, prism in meshes:
            scene.add_geometry(prism, geom_name=name)
        scene.export(str(mesh_path), file_type="obj")
    else:
        mesh_path.write_text("", encoding="utf-8")
        warnings.warn("massing: no floor plates fit the envelope with these settings",
                      UserWarning, stacklevel=2)

    settings = {k: getattr(conf, k) for k in ("ground_floor_height", "floor_height",
                                              "min_plate_dimension", "plate_tolerance",
                                              "plate_stacking")}
    upstream = getattr(chain.thr_manifest, "hash", "")
    stage_hash = hashlib.sha256((json.dumps(settings, sort_keys=True) + upstream).encode()).hexdigest()[:8]
    manifest = MassingManifest(hash=stage_hash, plates_path=str(plates_path),
                               mesh_path=str(mesh_path), upstream_manifest=str(chain.thr_path))
    (out_path / "manifest.json").write_text(schema_to_json(manifest), encoding="utf-8")

    plate_volume = sum(q["area_m2"] * (q["z_top"] - q["z_bottom"]) for q in plates)
    inside = sum(q["area_m2"] * (q["z_top"] - q["z_bottom"]) * (1.0 - q["outside_share"]) for q in plates)
    envelope = float(kept.sum()) * vs ** 3
    write_json(ensure_diag(out_path), "diagnostic.json", {
        "floors": len(levels), "floors_built": int(sum(a > 0 for a in floor_areas)),
        "plates": len(plates), "floor_area_m2_per_floor": floor_areas,
        "total_floor_area_m2": total, "envelope_volume_m3": envelope,
        "envelope_share_in_plates": inside / envelope if envelope > 0 else None,
        "volume_outside_envelope_m3": plate_volume - inside,
        "footprint_source": footprint_source, "settings": settings,
        "timings": {"wall_seconds": float(time.perf_counter() - t0_wall),
                    "cpu_seconds": float(time.process_time() - t0_cpu)},
    })
    return MassingResult(out_dir=out_path, plates_path=plates_path, mesh_path=mesh_path,
                         floor_areas=floor_areas, total_floor_area=total, n_plates=len(plates))
```

Add `import shapely.affinity` at the top (next to `import shapely`).

Exports:
- `api_core/__init__.py`: add `from .massing import massing, MassingResult  # noqa: F401`, add `"massing"`, `"MassingResult"` to `__all__`, and mention `massing.py` in the module docstring list.
- `api.py`: import `massing, MassingResult` from `.api_core`; add both to `__all__`.
- `__init__.py`: add `massing` and `MassingResult` to the `TYPE_CHECKING` import, the lazy `from .api import (...)` and `_api_names`, and to the module's public name list next to `"exporting"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_massing_stage.py tests/test_exporting.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/urbansolarcarver/api_core/_util.py src/urbansolarcarver/api_core/exporting.py src/urbansolarcarver/api_core/massing.py src/urbansolarcarver/api_core/__init__.py src/urbansolarcarver/api.py src/urbansolarcarver/__init__.py src/urbansolarcarver/pydantic_schemas.py tests/test_massing_stage.py
git commit -m "feat(massing): massing stage writing plates.json, plates.obj, manifest, diagnostics

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Run report section

**Files:**
- Modify: `src/urbansolarcarver/api_core/_reporting.py` (`generate_run_report` gets `massing_dir=None`)
- Modify: `src/urbansolarcarver/api_core/massing.py` (call it)
- Test: `tests/test_massing_stage.py` (append)

**Interfaces:**
- Consumes: `diagnostics/diagnostic.json` keys written in Task 7.
- Produces: `generate_run_report(out_dir, pre_dir, thr_dir, exp_dir, conf, massing_dir=None) -> Path`; report contains a `## Massing` section when `massing_dir` is given.

- [ ] **Step 1: Write the failing test**

```python
def test_run_report_has_a_massing_section(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    _massing(cfg, thr, tmp_path / "out" / "massing")
    report = (tmp_path / "out" / "run_report.md").read_text(encoding="utf-8")
    assert "## Massing" in report and "Total floor area" in report
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_massing_stage.py::test_run_report_has_a_massing_section -q -p no:cacheprovider`
Expected: FAIL (`FileNotFoundError` for run_report.md).

- [ ] **Step 3: Implement**

In `_reporting.py`, change the signature to `def generate_run_report(out_dir, pre_dir, thr_dir, exp_dir, conf, massing_dir=None) -> Path:` and update the docstring ("... from all stage diagnostics; the massing section is added when *massing_dir* is given"). Right before the report is written to disk (after the "## Export" section), add:

```python
    # --- Massing ---
    if massing_dir is not None:
        m_summary, m_timing = _load_diag(massing_dir)
        lines.append("## Massing\n")
        if m_summary:
            lines.append(f"- **Floors built:** {m_summary.get('floors_built', 0)} of {m_summary.get('floors', 0)}")
            lines.append(f"- **Floor plates:** {m_summary.get('plates', 0)}")
            lines.append(f"- **Total floor area:** {m_summary.get('total_floor_area_m2', 0.0):,.0f} m²")
            per_floor = m_summary.get("floor_area_m2_per_floor") or []
            if per_floor:
                lines.append("- **Floor area per floor (m²):** " + ", ".join(f"{a:,.0f}" for a in per_floor))
            share = m_summary.get("envelope_share_in_plates")
            if share is not None:
                lines.append(f"- **Share of the carved envelope inside plates:** {100 * share:.1f}%")
            lines.append(f"- **Volume outside the envelope (tolerance):** "
                         f"{m_summary.get('volume_outside_envelope_m3', 0.0):,.0f} m³")
        if m_timing:
            lines.append(f"- **Time:** {m_timing.get('wall_seconds', 0):.1f}s")
        lines.append("")
```

At the end of `massing()` in `api_core/massing.py`, before `return`:

```python
    report_root = out_path.parent if out_path.name == "massing" else out_path
    (report_root / "run_report.md").unlink(missing_ok=True)
    try:
        generate_run_report(report_root, chain.pre_path.parent, chain.thr_path.parent,
                            report_root / "exporting", conf, massing_dir=out_path)
    except Exception as exc:
        log.warning("Could not generate run report: %s", exc)
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_massing_stage.py tests/test_exporting.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/api_core/_reporting.py src/urbansolarcarver/api_core/massing.py tests/test_massing_stage.py
git commit -m "feat(massing): massing section in the run report

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: CLI and daemon

**Files:**
- Modify: `src/urbansolarcarver/carver_cli.py` (new `massing` command after `cmd_exporting`)
- Modify: `src/urbansolarcarver/daemon.py` (`_REQUIRED_KEYS`, `_handle_stage_command`, `serve` docstring)
- Test: `tests/test_cli.py`, `tests/test_daemon.py` (append)

**Interfaces:**
- Consumes: `massing` (Task 7) via `_api("massing")` and `api.massing`.
- Produces: CLI `usc massing -c CONFIG [-f MANIFEST] [-o KEY=VALUE] [--out DIR] [--daemon] [-q]`; daemon command `{"cmd": "massing", "config", "from", "overrides"?, "out_dir"?}` replying `{"status": "ok", "manifest", "plates_path", "mesh_path"}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_massing_command_exists():
    from typer.testing import CliRunner
    from urbansolarcarver.carver_cli import app
    result = CliRunner().invoke(app, ["massing", "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0 and "--from" in result.output and "--config" in result.output
```

Append to `tests/test_daemon.py`:

```python
def test_massing_command_runs_after_thresholding(tmp_path, tmp_mesh_files):
    import yaml
    from urbansolarcarver.daemon import _dispatch
    from urbansolarcarver.session import CarverSession

    vol_path, srf_path = tmp_mesh_files
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "max_volume_path": str(vol_path), "test_surface_path": str(srf_path),
        "out_dir": str(tmp_path / "out"), "mode": "daylight",
        "voxel_size": 2.0, "grid_step": 2.0, "ray_length": 50.0, "device": "cpu",
    }))
    with CarverSession(device="cpu") as sess:
        pre = _dispatch({"cmd": "preprocessing", "config": str(cfg_path)}, sess)
        thr = _dispatch({"cmd": "thresholding", "config": str(cfg_path), "from": pre["manifest"]}, sess)
        reply = _dispatch({"cmd": "massing", "config": str(cfg_path), "from": thr["manifest"]}, sess)
    assert reply["status"] == "ok", reply
    assert (tmp_path / "out" / "massing" / "plates.json").is_file()
    assert reply["plates_path"].endswith("plates.json")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py::test_massing_command_exists tests/test_daemon.py::test_massing_command_runs_after_thresholding -q -p no:cacheprovider`
Expected: FAIL (`No such command 'massing'`; daemon `Unknown command: 'massing'`).

- [ ] **Step 3: Implement**

In `carver_cli.py`, after `cmd_exporting`:

```python
@app.command("massing", help="Stage 4: floor plates from the carved envelope -> plates.json, plates.obj")
def cmd_massing(
    from_manifest: Optional[Path] = Option(None, "-f", "--from", help="Path to thresholding manifest.json (auto-detected if omitted)"),
    config: Path = Option(..., "-c", "--config", exists=True, readable=True, help="YAML config path"),
    override: List[str] = Option([], "-o", "--override", help="Override config fields"),
    out_dir: Optional[Path] = Option(None, "--out", help="Output directory"),
    daemon: bool = Option(False, "--daemon", help="Send to running daemon"),
    quiet: bool = Option(False, "-q", "--quiet", help="Minimal output"),
):
    """Build stacked floor plates that follow the footprint, from the carving mask.

    Reads the thresholding manifest (``-f``) and writes ``plates.json``
    (outlines in world coordinates) and ``plates.obj`` (one closed prism per
    plate).  Settings: ground_floor_height, floor_height,
    min_plate_dimension, plate_tolerance, plate_stacking.
    """
    cfg = load_config(str(config), override)
    out_dir = out_dir or (Path(cfg.out_dir) / "massing")
    if from_manifest is None:
        from_manifest = _find_manifest(cfg, out_dir, "thresholding", quiet)

    if daemon:
        _run_on_daemon({
            "cmd": "massing", "from": str(from_manifest.resolve()),
            "config": str(config.resolve()), "overrides": _absolute_overrides(override),
            "out_dir": str(out_dir.resolve()),
        }, quiet)
        return

    if not quiet:
        typer.secho(f"  Massing -> {out_dir}", fg="yellow")

    t0 = time.perf_counter()
    res = _api("massing")(from_manifest, cfg, out_dir)
    elapsed = time.perf_counter() - t0

    _echo_result("Massing", {
        "Plates": str(res.plates_path),
        "Floor plates": f"{res.n_plates}",
        "Total floor area": f"{res.total_floor_area:,.0f} m²",
        "Time": f"{elapsed:.1f}s",
    })
```

In `daemon.py`:
- add `"massing": ("config", "from"),` to `_REQUIRED_KEYS` after `"exporting"`;
- in `_handle_stage_command`, before the final `result = api.exporting(...)` line, add:

```python
    if cmd == "massing":
        result = api.massing(msg["from"], cfg, out_dir)
        return {"status": "ok", "manifest": str(result.out_dir / "manifest.json"),
                "plates_path": str(result.plates_path), "mesh_path": str(result.mesh_path)}
```

- in the `serve` docstring, change "preprocessing, thresholding, exporting," to "preprocessing, thresholding, exporting, massing,".

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py tests/test_daemon.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/carver_cli.py src/urbansolarcarver/daemon.py tests/test_cli.py tests/test_daemon.py
git commit -m "feat(massing): usc massing command and daemon support

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Grasshopper components

**Files:**
- Modify: `grasshopper/usc_gh.py` (add `read_plates`)
- Create: `grasshopper/components/USC_Massing.py`, `grasshopper/components/USC_MassingSettings.py`
- Modify: `grasshopper/components.json` (two entries)
- Create: `grasshopper/icons/USC_Massing.png` (copy of `USC_Export.png`), `grasshopper/icons/USC_MassingSettings.png` (copy of `USC_Postprocess.png`)
- Generated: `grasshopper/USC_GHplugin/USC Massing.ghuser`, `grasshopper/USC_GHplugin/USC Massing Settings.ghuser`
- Test: `tests/test_usc_gh.py` (append); `tests/test_gh_components.py` (unchanged, must pass)

**Interfaces:**
- Consumes: daemon `massing` reply (Task 9), `plates.json` format (Task 7).
- Produces: `usc_gh.read_plates(path) -> list[dict]`; GH `USC_Massing` (inputs `config`, `thr_result`, `massing_overrides`, `run`; outputs `plates`, `floor_areas`, `total_floor_area`, `plates_path`, `diagnostics`, `report_path`) and `USC_MassingSettings` (inputs `ground_floor_height`, `floor_height`, `min_plate_dimension`, `plate_tolerance`, `supported`; output `overrides`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_usc_gh.py` (it loads `grasshopper/usc_gh.py` through the module-scoped `gh` fixture):

```python
def test_read_plates(tmp_path, gh):
    import json
    path = tmp_path / "plates.json"
    path.write_text(json.dumps({"plates": [{"floor": 0, "plate": 0, "z_bottom": 0.0, "z_top": 5.0,
                                            "outline": [[0, 0], [1, 0], [1, 1], [0, 0]], "holes": []}],
                                "floor_area_m2_per_floor": [0.5], "total_floor_area_m2": 0.5}))
    plates = gh.read_plates(path)
    assert len(plates) == 1 and plates[0]["z_top"] == 5.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_usc_gh.py::test_read_plates -q -p no:cacheprovider`
Expected: FAIL (`AttributeError: ... no attribute 'read_plates'`).

- [ ] **Step 3: Implement**

In `grasshopper/usc_gh.py`, after `read_diagnostics`:

```python
def read_plates(path):
    """The plate list of a massing run's plates.json (outlines in world coordinates)."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)["plates"]
```

Create `grasshopper/components/USC_MassingSettings.py`:

```python
"""USC Massing Settings: floor heights, plate size, tolerance and stacking.

Generates override strings for the massing stage. Connect the output to
USC Massing's ``massing_overrides`` input.

Inputs
------
ground_floor_height : float, optional
    Height of the ground floor in metres. Default: 5.
floor_height : float, optional
    Height of every floor above the ground floor in metres. Default: 3.
min_plate_dimension : float, optional
    Bay width and minimum floor-plate width in metres. Default: 3.
plate_tolerance : float, optional
    Largest share (0-1) of a bay's volume on a floor that may lie outside
    the carved envelope. Plates never leave the maximum volume.
    Default: 0.2.
supported : bool, optional
    True: a bay is built only where it is built on the floor below.
    False: each floor is decided on its own. Default: True.

Outputs
-------
overrides : str
    Semicolon-joined key=value pairs. Connect to USC Massing's
    ``massing_overrides`` input: changes here re-run only Massing.
"""

try:
    ghenv.Component.Name = "USC Massing Settings"
    ghenv.Component.NickName = "USC_MassSet"
    ghenv.Component.Description = "Floor heights, bay width, tolerance and stacking for USC_Massing. Connect to USC_Massing's 'massing_overrides' input."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("ground_floor_height", "Height of the ground floor in metres. Default: 5."),
        ("floor_height", "Height of every floor above the ground floor in metres. Default: 3."),
        ("min_plate_dimension", "Bay width and minimum floor-plate width in metres. Bays are cut perpendicular to the facades at this spacing. Default: 3."),
        ("plate_tolerance", "Largest share (0-1) of a bay's volume on a floor that may lie outside the carved envelope. Plates never leave the maximum volume. Default: 0.2."),
        ("supported", "True: a bay is built only where it is built on the floor below. False: each floor is decided on its own. Default: True."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    oo[0].Name, oo[0].Description = "overrides", "Massing settings formatted for USC_Massing's 'massing_overrides' input. Changes here re-run only Massing."
except Exception:
    pass

_items = []
if ground_floor_height is not None:
    _items.append(f"ground_floor_height={float(ground_floor_height)}")
if floor_height is not None:
    _items.append(f"floor_height={float(floor_height)}")
if min_plate_dimension is not None:
    _items.append(f"min_plate_dimension={float(min_plate_dimension)}")
if plate_tolerance is not None:
    _items.append(f"plate_tolerance={float(plate_tolerance)}")
if supported is not None:
    _items.append("plate_stacking={}".format("supported" if bool(supported) else "free"))

overrides = ";".join(_items) if _items else None
```

Create `grasshopper/components/USC_Massing.py`:

```python
"""USC Massing: stacked floor plates that follow the footprint (stage 4).

Takes the thresholding result and builds floor plates: a ground floor and
equal floors above it, each made of bays cut perpendicular to the facades
and kept where they fit the carved envelope. The daemon writes the plates
to <out_dir>/massing/ and the component returns them as closed Breps.

Inputs
------
config : USCConfig
    Config handle from USC Config.
thr_result : str
    Thresholding manifest path from USC Threshold Stage.
massing_overrides : str, optional
    Settings from USC Massing Settings. Connect them here, not through
    Config, so that changing them re-runs only Massing.
run : bool
    True to execute. False to idle.

Outputs
-------
plates : list of Rhino.Geometry.Brep
    One closed Brep per floor plate.
floor_areas : list of float
    Gross floor area per floor (m2), from the ground floor up.
total_floor_area : float
    Sum of the floor areas (m2).
plates_path : str
    Path to plates.json (outlines in world coordinates).
diagnostics : str
    Floors, plates, floor areas and timing.
report_path : str
    Path to <out_dir>/run_report.md (None if not written).
"""

import time
from pathlib import Path


# -- GH UI ------------------------------------------------------------------
try:
    ghenv.Component.Name = "USC Massing"
    ghenv.Component.NickName = "USC_Massing"
    ghenv.Component.Description = "Stage 4: builds stacked floor plates that follow the footprint, cut into bays perpendicular to the facades, kept where they fit the carved envelope. Returns closed Breps and floor areas."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "config", "Configuration handle from USC_Config."
    ii[1].Name, ii[1].Description = "thr_result", "Thresholding manifest path from USC_ThresholdStage."
    ii[2].Name, ii[2].Description = "massing_overrides", "Override string from USC_MassingSettings. Connect it here, not through Config, so that changing massing settings re-runs only Massing."
    ii[3].Name, ii[3].Description = "run", "Boolean toggle. True to build the floor plates."
    oo[0].Name, oo[0].Description = "plates", "One closed Brep per floor plate, in world coordinates."
    oo[1].Name, oo[1].Description = "floor_areas", "Gross floor area per floor in m2, from the ground floor up."
    oo[2].Name, oo[2].Description = "total_floor_area", "Sum of the floor areas in m2."
    oo[3].Name, oo[3].Description = "plates_path", "Path to plates.json with the plate outlines in world coordinates."
    oo[4].Name, oo[4].Description = "diagnostics", "Text summary: floors, plates, floor areas, timing."
    oo[5].Name, oo[5].Description = "report_path", "Full path to run_report.md, which includes a Massing section."
except Exception:
    pass

# -- Helpers ------------------------------------------------------------------

def _usc_gh(root):
    """Shared helpers from <carver_root>/grasshopper/usc_gh.py, reloaded when that file changes."""
    import importlib.util
    import sys
    path = Path(root) / "grasshopper" / "usc_gh.py"
    stamp = (str(path), path.stat().st_mtime)
    mod = sys.modules.get("usc_gh")
    if mod is None or getattr(mod, "_source", None) != stamp:
        spec = importlib.util.spec_from_file_location("usc_gh", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod._source = stamp
        sys.modules["usc_gh"] = mod
    return mod


def _error(msg):
    """Show an error on the component (red) and return msg."""
    from Grasshopper.Kernel import GH_RuntimeMessageLevel
    ghenv.Component.AddRuntimeMessage(GH_RuntimeMessageLevel.Error, msg)
    return msg


def _plate_brep(plate, tol=0.001):
    """Closed Brep of one plate: its outline and holes extruded between z_bottom and z_top."""
    import Rhino.Geometry as rg
    zb, zt = plate["z_bottom"], plate["z_top"]
    rings = [plate["outline"]] + plate["holes"]
    curves = [rg.PolylineCurve([rg.Point3d(x, y, zb) for x, y in ring]) for ring in rings]
    planar = rg.Brep.CreatePlanarBreps(curves, tol)
    if not planar:
        return None
    path = rg.LineCurve(rg.Point3d(0, 0, zb), rg.Point3d(0, 0, zt))
    return planar[0].Faces[0].CreateExtrusion(path, True)


plates = []
floor_areas = []
total_floor_area = None
plates_path = None
diagnostics = ""
report_path = None

if not run:
    diagnostics = "Idle: set run=True"
elif config is None:
    diagnostics = _error("Connect a USC Config component")
elif thr_result is None:
    diagnostics = _error("Connect thr_result from USC Threshold Stage")
else:
    t_start = time.perf_counter()
    gh = _usc_gh(config.session.root)
    m_out = Path(config.out_dir) / "massing"
    # Massing settings are merged here, not in Config, so changing them
    # re-runs only Massing.
    overrides = dict(config.overrides, **gh.parse_overrides(massing_overrides))
    try:
        reply = gh.call_daemon(config.session, "massing", {
            "from": str(thr_result),
            "config": config.yaml_path,
            "overrides": gh.override_list(overrides),
            "out_dir": str(m_out),
        })
        plates_path = reply["plates_path"]
        for plate in gh.read_plates(plates_path):
            brep = _plate_brep(plate)
            if brep is not None:
                plates.append(brep)
        data = gh.read_diagnostics(m_out)
        floor_areas = data.get("floor_area_m2_per_floor", [])
        total_floor_area = data.get("total_floor_area_m2")
        lines = ["Massing: {:.1f}s".format(time.perf_counter() - t_start),
                 "Floors built: {} of {}".format(data.get("floors_built", "?"), data.get("floors", "?")),
                 "Plates: {}".format(data.get("plates", "?"))]
        if total_floor_area is not None:
            lines.append("Total floor area: {:,.0f} m2".format(total_floor_area))
        if data.get("footprint_source") == "voxels":
            lines.append("Footprint from voxels (the mesh outline could not be read)")
        diagnostics = "\n".join(lines)
        report = m_out.parent / "run_report.md"
        report_path = str(report) if report.is_file() else None
    except Exception as e:
        diagnostics = _error(str(e))
```

In `grasshopper/components.json`, add (alphabetical order with the other entries):

```json
    "USC_Massing.py": {
      "subcategory": "2::Main",
      "guid": "378d2a56-1267-4edf-b93a-dc45eb8037ce"
    },
    "USC_MassingSettings.py": {
      "subcategory": "1:: Config",
      "guid": "4f968208-bbce-4203-8fe7-98d68bcf3d24"
    },
```

Copy icons:

```bash
cp grasshopper/icons/USC_Export.png grasshopper/icons/USC_Massing.png
cp grasshopper/icons/USC_Postprocess.png grasshopper/icons/USC_MassingSettings.png
```

Build and check the .ghuser files, then install them:

```bash
.venv/Scripts/python grasshopper/build_ghuser.py
.venv/Scripts/python grasshopper/build_ghuser.py --check
cp grasshopper/USC_GHplugin/*.ghuser "$APPDATA/Grasshopper/UserObjects/"
```

Expected: the build writes `USC Massing.ghuser` and `USC Massing Settings.ghuser`; `--check` reports all files up to date.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_usc_gh.py tests/test_gh_components.py -q -p no:cacheprovider`
Expected: PASS (the docstring/UI checks include the two new components).

- [ ] **Step 5: Commit**

```bash
git add grasshopper/usc_gh.py grasshopper/components/USC_Massing.py grasshopper/components/USC_MassingSettings.py grasshopper/components.json grasshopper/icons/USC_Massing.png grasshopper/icons/USC_MassingSettings.png "grasshopper/USC_GHplugin/USC Massing.ghuser" "grasshopper/USC_GHplugin/USC Massing Settings.ghuser" tests/test_usc_gh.py
git commit -m "feat(massing): USC_Massing and USC_MassingSettings Grasshopper components

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Documentation

**Files:**
- Create: `docs/massing.md`
- Modify: `mkdocs.yml` (nav entry after the Carving Modes page), `docs/getting-started/configuration.md` (settings table rows), `docs/grasshopper.md` (two component entries), `docs/api/pipeline.md` (stage 4 section), `docs/project-map.md` (rows for `massing.py`, `api_core/massing.py`, the two components, the two test files), `README.md` (one feature line), `CHANGELOG.md` (Unreleased > Added)

**Interfaces:** none (text only).

- [ ] **Step 1: Write `docs/massing.md`**

```markdown
# Floor-plate massing

The massing stage turns the carved envelope into stacked floor plates: a
ground floor, then floors of equal height, each a closed prism whose outline
follows the maximum volume's footprint and steps back where the envelope does
not allow the floor. Use it for massing models, floor-area figures and as
simulation input (one closed prism per floor and plate).

## How plates are formed

1. **Footprint and facades.** The outline of the maximum volume 1 cm above its
   base is split into facades wherever it turns by more than 30 degrees.
   Curved or faceted outlines with smaller turns stay one facade.
2. **Faces.** Every footprint column belongs to its nearest facade. At corners
   the longer facade takes the corner square, so every face ends in a line
   perpendicular to its facade.
3. **Bays.** Each face is cut into bays of `min_plate_dimension` (3 m) along its
   facade, perpendicular to it. Cuts on the two sides of a straight building
   line up. A short end bay joins its neighbour.
4. **Floors.** For each floor (ground floor `ground_floor_height`, then
   `floor_height`), a bay is built when it stays inside the maximum volume over
   the floor's full height, at most `plate_tolerance` of its volume lies outside
   the carved envelope, and (with `plate_stacking: supported`) it is built on
   the floor below. Parts narrower than `min_plate_dimension` are dropped.
5. **Plates.** The connected built bays of a floor form a plate. Its facade
   edges are the footprint's own; its other edges are perpendicular or parallel
   to a facade.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `ground_floor_height` | 5.0 | Height of the ground floor (m) |
| `floor_height` | 3.0 | Height of every floor above it (m) |
| `min_plate_dimension` | 3.0 | Bay width and minimum plate width (m) |
| `plate_tolerance` | 0.2 | Largest share of a bay's volume on a floor outside the carved envelope |
| `plate_stacking` | supported | `supported`: build a bay only on a built bay; `free`: each floor on its own |

Plates never leave the maximum volume. All sizes must be at least the voxel size.

## Outputs

In `<out_dir>/massing/`: `plates.json` (outlines and holes in world coordinates,
floor, heights, area, outside share; floor areas per floor and in total),
`plates.obj` (one closed mesh per plate, named `floor_<n>_plate_<m>`),
`manifest.json` and `diagnostics/diagnostic.json`. The run report gets a
Massing section.

## Running it

- Python: `massing(thr_result, cfg, out_dir)`
- CLI: `usc massing -c config.yaml`
- Grasshopper: `USC_Massing` after `USC_ThresholdStage`, with `USC_MassingSettings`

## Limits

- Floors count from the lowest point of the maximum volume; a part that starts
  higher gets a warning (sloped ground is not supported yet).
- Bays are rectangles in their face's frame; there are no interior zones (core,
  perimeter) and roofs are flat.
```

- [ ] **Step 2: Update the other docs**

- `mkdocs.yml`: add `- Floor-plate massing: massing.md` to `nav` right after the entry for `modes.md`.
- `docs/getting-started/configuration.md`: add the five settings rows from the table above to the settings table, after `max_slope_deg`.
- `docs/grasshopper.md`: after the USC_Export entry add: `- **USC_Massing**: stage 4, builds floor plates from the carving mask (inputs config, thr_result, massing_overrides, run; outputs closed Breps, floor areas per floor and in total, plates.json path). See [Floor-plate massing](massing.md).` and `- **USC_MassingSettings**: floor heights, bay width, tolerance and stacking for USC_Massing.`
- `docs/api/pipeline.md`: add a "### massing()" section: "Builds stacked floor plates that follow the footprint from the carving mask (see [Floor-plate massing](../massing.md)). Writes `plates.json`, `plates.obj`, `manifest.json` and diagnostics, and adds a Massing section to the run report. Returns a `MassingResult` with the paths, floor areas per floor and in total, and the number of plates."
- `docs/project-map.md`: rows for `massing.py` ("Floor-plate massing geometry: footprint and facades, faces by nearest facade with squared corners, bays, floor-by-floor bay selection, plate outlines and prisms"), `api_core/massing.py` ("**Stage 4.** Reads the thresholding chain, runs the massing geometry, writes plates.json, plates.obj, manifest, diagnostics and the run report"), the two GH components and `tests/test_massing.py`, `tests/test_massing_stage.py`.
- `README.md`: in the features list add "Floor-plate massing: stacked floor plates (5 m ground floor, 3 m floors) that follow the footprint and step back where the envelope requires, with floor areas per floor."
- `CHANGELOG.md` under `## [Unreleased]` > `### Added` (create the heading if missing), first entry:

```markdown
- **Floor-plate massing (stage 4, `massing`).** Turns the carved envelope into
  stacked floor plates: a ground floor (`ground_floor_height`, 5 m), then
  floors of `floor_height` (3 m). The footprint is split into faces, one per
  facade (corners squared to the longer facade), and each face into bays of
  `min_plate_dimension` (3 m) cut perpendicular to its facade. A bay is built
  on a floor when it stays in the maximum volume, at most `plate_tolerance`
  (0.2) of its volume lies outside the envelope, and, with `plate_stacking:
  supported`, it is built on the floor below. Writes `plates.json` (world
  outlines, floor areas) and `plates.obj` (one closed prism per plate); adds a
  Massing section to the run report. `usc massing`, a daemon command, and the
  Grasshopper components USC_Massing and USC_MassingSettings.
```

- [ ] **Step 3: Check the docs build and links**

Run: `.venv/Scripts/python -m mkdocs build --strict -q` (if mkdocs is installed in the venv; otherwise run `.venv/Scripts/python -c "import yaml; yaml.safe_load(open('mkdocs.yml'))"` to check the nav syntax).
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add docs/massing.md mkdocs.yml docs/getting-started/configuration.md docs/grasshopper.md docs/api/pipeline.md docs/project-map.md README.md CHANGELOG.md
git commit -m "docs(massing): floor-plate massing page, settings, components, changelog

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Full suite and end-to-end check on the ReSBE scenes

**Files:**
- No source changes expected. Scripts go in the session scratchpad, not the repo.

**Interfaces:**
- Consumes: the whole stage.

- [ ] **Step 1: Full test suite**

Run: `.venv/Scripts/python -m pytest tests -q -p no:cacheprovider`
Expected: all pass (previously 482 plus the new tests).

- [ ] **Step 2: Run massing on the four ReSBE scenes**

Write a scratchpad script that, for each of `courtyard`, `towers`, `rows`, `freeform` in `D:\RESEARCH_CENTER\ACTIVE_PROJECTS\ReSBE_USC\presentation\scenes\<scene>\cfg_benefit.yaml` (33 m volumes, 0.5 m voxels, `carve_fraction: 0.4`), runs preprocessing, thresholding and massing into the scratchpad, and prints per scene: floors built, plates, total floor area, floor area per floor, envelope share in plates, volume outside the envelope, time.

Expected: every scene produces plates on the ground floor; no exception; timings of a few seconds.

- [ ] **Step 3: 3D views for the user**

Render a plotly HTML per scene (into the folder served by the `usc-visuals` preview server, `scratchpad/raycf/visuals_cf`): the maximum volume as a faint ghost, the carved envelope as a light mesh (toggle), and the floor plates coloured by floor, with buttons for `plate_tolerance` 0.0 / 0.2 / 0.4 and `plate_stacking` supported / free. Report the links and the numbers to the user.

- [ ] **Step 4: Stop for review**

Do not merge. Present the numbers and the 3D views to the user and wait for their review of the forms before any merge or push.
```
