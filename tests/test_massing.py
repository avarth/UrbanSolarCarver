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
