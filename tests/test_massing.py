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
