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
        assert np.allclose(mg.layer_overlaps(0.0, 1.0, 5, 0.5, 2.5), [0.5, 1, 0.5, 0, 0])

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
