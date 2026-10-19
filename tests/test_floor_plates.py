"""Floor-plate massing geometry (floor_plates.py)."""
import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Point, Polygon, box

from urbansolarcarver import floor_plates as mg

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

    def test_raised_body_keeps_its_footprint(self):
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
    bay, bay_face = mg.cut_bays(faces, facades, [polygon], width, vs)
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

    @pytest.mark.parametrize("length, widths", [(10, [3.0, 4.0, 3.0]), (13, [3.0, 3.5, 3.5, 3.0]),
                                                (12, [3.0, 3.0, 3.0, 3.0]), (7, [3.5, 3.5])])
    def test_rows_are_laid_from_both_ends_with_the_rest_in_the_middle(self, length, widths):
        # Rows of 3 m from each end of the bar; what is left widens the middle row, or the two middle rows equally.
        _, xy, _, _, bay, bay_face = _bays(box(0, 0, length, 6), 0.5, 3.0)
        for f in np.unique(bay_face):
            rows = sorted((xy[bay == b, 0].min() - 0.25, xy[bay == b, 0].max() + 0.25) for b in np.flatnonzero(bay_face == f))
            assert [hi - lo for lo, hi in rows] == widths

    def test_round_tower_bays_follow_the_curve(self):
        _, _, facades, faces, bay, bay_face = _bays(Point(0, 0).buffer(10, quad_segs=16), 0.5, 3.0)
        front = np.unique(bay[faces.d < 3.0])                 # the ring of modules along the facade
        assert abs(len(front) - facades[0].length / 3.0) <= 1.0

    def test_bays_are_square_modules_cut_in_depth_too(self):
        # 30 m deep block: each long face is 15 m deep, so five 3 m modules from its facade.
        _, _, _, faces, bay, bay_face = _bays(box(0, 0, 60, 30), 0.5, 3.0)
        for b in range(len(bay_face)):
            u, d = faces.u[bay == b], faces.d[bay == b]
            assert 3.0 - 1e-9 <= np.ptp(u) + 0.5 < 6.0 and 3.0 - 1e-9 <= np.ptp(d) + 0.5 < 6.0

    def test_a_shallow_back_module_joins_the_one_in_front(self):
        # 14 m deep bar: each face is 7 m deep, cut at 3 and 6 m; the 1 m deep back slice joins the module in front.
        _, _, _, faces, bay, bay_face = _bays(box(0, 0, 30, 14), 0.5, 3.0)
        depths = sorted({round(np.ptp(faces.d[bay == b]) + 0.5, 6) for b in range(len(bay_face))})
        assert depths == [3.0, 4.0]


def _bar_grid(nx=20, ny=6, nz=40, top=33, bay=3.0):
    """A 20 x 6 m bar on a 1 m grid aligned with the polygon; occupied below z = top."""
    poly = box(0, 0, nx, ny)
    ij, xy = _cells(poly, 1.0)
    facades, corners = mg.split_facades([poly])
    bays, _ = mg.cut_bays(mg.assign_faces(xy, facades, corners, [poly], 1.0), facades, [poly], bay, 1.0)
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

    def test_a_layer_mostly_below_the_base_does_not_count_against_the_ground_floor(self):
        """The grid starts 0.62 m below the base at z 0, so layer 0 spans -0.62..0.38 and its centre lies below the base.

        Such a layer is filled only where rays hit the base; here it is empty in the bar's first two rows of columns.
        """
        ij, bays, occ = _bar_grid()
        occ[:, :2, 0] = False
        levels = mg.floor_levels(0.0, 32.38, 5.0, 3.0)
        counted_layers = mg.layers_centred_within(-0.62, 1.0, occ.shape[2], 0.0, 32.38)
        assert not counted_layers[0] and counted_layers[1:33].all()
        floors = mg.build_floors(ij, bays, occ, occ.copy(), -0.62, 1.0, levels, 0.0, "supported", 3.0,
                                 counted_layers=counted_layers)
        assert all(floor.kept_bays.all() for floor in floors)
        assert np.allclose(floors[0].outside_share, 0.0)

    def test_a_layer_mostly_above_the_top_does_not_count_against_the_top_floor(self):
        """The grid starts 0.2 m below the base at z 0 and the volume ends at z 17.1: layer 17 spans 16.8..17.8 and
        its centre lies above the top.

        Such a layer is filled only where rays hit the roof; here it is empty in the bar's first two rows of columns.
        The floor 14..17 reaches 0.2 m into it.
        """
        ij, bays, occ = _bar_grid(top=18)
        occ[:, :2, 17] = False
        levels = mg.floor_levels(0.0, 17.1, 5.0, 3.0)
        assert levels[-1] == (14.0, 17.0)
        counted_layers = mg.layers_centred_within(-0.2, 1.0, occ.shape[2], 0.0, 17.1)
        assert counted_layers[:17].all() and not counted_layers[17:].any()
        floors = mg.build_floors(ij, bays, occ, occ.copy(), -0.2, 1.0, levels, 0.0, "supported", 3.0,
                                 counted_layers=counted_layers)
        assert all(floor.kept_bays.all() for floor in floors)
        assert np.allclose(floors[-1].outside_share, 0.0)

    def test_the_wings_of_a_courtyard_block_keep_their_upper_floors(self):
        """A 40 x 30 m block carved into wings 9 m deep (8 m at the ends) around a courtyard kept only up to 5 m.

        The faces of the long facades reach the middle of the block, 15 m deep; a module of a wing must not fail with the
        courtyard behind it (as a 15 m deep strip, 7 of 15 m outside the envelope above 5 m).
        """
        poly = box(0, 0, 40, 30)
        ij, xy = _cells(poly, 1.0)
        facades, corners = mg.split_facades([poly])
        bays, _ = mg.cut_bays(mg.assign_faces(xy, facades, corners, [poly], 1.0), facades, [poly], 3.0, 1.0)
        occ = np.zeros((40, 30, 40), bool)
        occ[:, :, :33] = True
        kept = occ.copy()
        kept[8:32, 9:21, 5:] = False                         # the courtyard
        floors = _floors(ij, bays, occ, kept, tolerance=0.3)
        north_wing = ij[:, 1] >= 21
        courtyard = (ij[:, 0] >= 11) & (ij[:, 0] < 29) & (ij[:, 1] >= 11) & (ij[:, 1] < 19)
        for floor in floors:
            assert (floor.plate[north_wing] >= 0).all()
            if floor.zb >= 5:
                assert not (floor.plate[courtyard] >= 0).any()

    def test_outside_share_by_length(self):
        ij, bays, occ = _bar_grid()
        kept = occ.copy()
        kept[:, :, 2:] = False
        fl = _floors(ij, bays, occ, kept, levels=[(0.0, 2.5)], tolerance=1.0)[0]
        assert np.allclose(fl.outside_share, 0.5 / 2.5)


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


def test_plate_narrower_than_the_minimum_is_dropped():
    # A 2 m deep footprint touches 3 voxel columns at 1 m; the geometric check
    # removes it even though the column-based opening keeps it.
    poly = box(0, 0, 20, 2)
    ij, _ = _cells(box(-0.5, -0.5, 20.5, 2.5), 1.0)
    out = mg.plate_polygons(ij, np.ones(len(ij), bool), np.zeros(len(ij), bool), 1.0, poly,
                            min_dimension=3.0)
    assert out == []
    kept = mg.plate_polygons(ij, np.ones(len(ij), bool), np.zeros(len(ij), bool), 1.0, poly,
                             min_dimension=2.0)
    assert len(kept) == 1


# ----------------------------------------------------------------- final-review fixes
def test_uneven_base_keeps_the_whole_footprint():
    import trimesh
    mesh = trimesh.creation.box(extents=[30, 12, 20])
    mesh.apply_translation([0, 0, 10])
    v = mesh.vertices.copy()
    low = v[:, 2] < 1e-9
    v[low, 2] -= 0.01 * (v[low, 0] + 15)          # base drops 0.3 m over 30 m
    mesh.vertices = v
    polys = mg.footprint_polygons(mesh, offset_xy=(0, 0))
    assert sum(p.area for p in polys) == pytest.approx(360.0, rel=1e-6)


def test_square_tie_does_not_depend_on_the_ring_start():
    a = Polygon([(0, 0), (24, 0), (24, 24), (0, 24)])
    b = Polygon([(24, 24), (0, 24), (0, 0), (24, 0)])          # same square, other start
    parts = []
    for poly in (a, b):
        ij, _, facades, faces = _faces(poly)
        groups = {tuple(map(tuple, ij[faces.face == k])) for k in np.unique(faces.face)}
        parts.append(groups)
        for k in np.unique(faces.face):
            assert _is_rectangle(ij[faces.face == k])
    assert parts[0] == parts[1] and len(parts[0]) == 2


def test_short_chamfer_belongs_to_the_corner():
    block = Polygon([(0, 0), (40, 0), (40, 17), (37, 20), (0, 20)])   # 3 m chamfer
    ij, xy = _cells(block, 1.0)
    facades, corners = mg.split_facades([block])
    faces = mg.assign_faces(xy, facades, corners, [block], 1.0, min_facade_length=6.0)
    used = [k for k in np.unique(faces.face) if (faces.face == k).sum() > 0]
    assert len(used) == 2
    assert all(facades[k].length > 30 for k in used)


def test_voxel_fallback_straightens_diagonal_outlines():
    from shapely import affinity
    bar = affinity.rotate(box(-30, -7, 30, 7), 45, origin=(0, 0))
    bar = affinity.translate(bar, 40, 40)
    ij, _ = _cells(bar, 0.5)
    columns = np.zeros((200, 200), bool)
    columns[ij[:, 0], ij[:, 1]] = True
    polys = mg.footprint_from_columns(columns, 0.5)
    facades, _ = mg.split_facades(polys)
    assert len(facades) <= 8


def test_cut_edges_are_straight_on_rotated_footprints():
    from shapely import affinity
    bar = affinity.rotate(box(-30, -7, 30, 7), 30, origin=(0, 0))
    bar = affinity.translate(bar, 40, 40)
    vs = 0.5
    ij, xy = _cells(bar, vs)
    facades, corners = mg.split_facades([bar])
    faces = mg.assign_faces(xy, facades, corners, [bar], vs)
    bay, bay_face = mg.cut_bays(faces, facades, [bar], 3.0, vs)
    shapes = mg.bay_polygons(xy, faces, bay, bay_face, facades, [bar], 3.0, vs)
    # Both long faces are cut at the bar's middle (u is measured from the
    # centroid); split the bar there, by whole bays.
    axis = np.array([np.cos(np.radians(30)), np.sin(np.radians(30))])
    west = (xy - (40.0, 40.0)) @ axis < 0.0
    in_a = np.isin(bay, np.unique(bay[west]))
    a = mg.plate_polygons(ij, in_a, ~in_a, vs, bar, bay=bay, bay_shapes=shapes)
    b = mg.plate_polygons(ij, ~in_a, in_a, vs, bar, bay=bay, bay_shapes=shapes)
    assert len(a) == 1 and len(b) == 1
    assert len(a[0].exterior.coords) <= 8 and len(b[0].exterior.coords) <= 8
    assert a[0].intersection(b[0]).area < 1e-6
    assert a[0].area + b[0].area == pytest.approx(bar.area, rel=1e-6)


def test_plates_do_not_cover_neighbouring_bays_on_a_rotated_l():
    from shapely import affinity
    poly = affinity.translate(affinity.rotate(L_SHAPE, 20, origin=(0, 0)), 40, 10)
    vs = 0.5
    ij, xy = _cells(poly, vs)
    facades, corners = mg.split_facades([poly])
    faces = mg.assign_faces(xy, facades, corners, [poly], vs, min_facade_length=6.0)
    bay, bay_face = mg.cut_bays(faces, facades, [poly], 3.0, vs)
    shapes = mg.bay_polygons(xy, faces, bay, bay_face, facades, [poly], 3.0, vs)
    in_a = bay % 2 == 0                       # every other bay, on both sides of every ridge
    a = shapely.union_all(mg.plate_polygons(ij, in_a, ~in_a, vs, poly, bay=bay, bay_shapes=shapes))
    b = shapely.union_all(mg.plate_polygons(ij, ~in_a, in_a, vs, poly, bay=bay, bay_shapes=shapes))
    assert a.intersection(b).area < 1e-6
    # face ends that are not cuts or ridges lie within half a voxel of the columns
    assert a.area + b.area == pytest.approx(poly.area, rel=1e-2)


def test_collinear_vertices_keep_a_facade_straight():
    # A stray vertex on a straight edge (mesh sections, T-junctions) must not
    # turn the facade into a curved one, whose positions are arc lengths.
    block = Polygon([(0, 0), (20, 0), (40, 0), (40, 15), (0, 15)])
    facades, corners = mg.split_facades([block])
    assert len(facades) == 4 and all(f.straight for f in facades)


def test_corner_square_of_a_curved_facade_is_cut_into_bays():
    # The inner facade of this L bends by 10 degrees, so it is one curved
    # facade; at the reflex corner it takes the corner square past its end.
    # Those columns must be cut into bays like the rest, not lumped into one.
    bent_l = Polygon([(0, 0), (60, 0), (60, 15), (37, 17), (15, 15), (15, 60), (0, 60)])
    ij, xy, facades, faces = _faces(bent_l, 0.5)
    bay, bay_face = mg.cut_bays(faces, facades, [bent_l], 3.0, 0.5)
    bent = next(k for k, f in enumerate(facades) if not f.straight)
    for b in np.flatnonzero(bay_face == bent):
        x = xy[bay == b, 0]
        assert np.ptp(x) < 2 * 3.0


def test_footprint_with_a_hole_survives_the_json_round_trip():
    import json
    courtyard = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)],
                        [[(5, 5), (5, 15), (15, 15), (15, 5)]])
    data = json.loads(json.dumps(mg.footprint_to_dict([courtyard])))
    (restored,) = mg.footprint_from_dict(data)
    assert restored.area == pytest.approx(courtyard.area) == pytest.approx(300.0)
    assert len(restored.interiors) == 1
    assert Polygon(restored.interiors[0]).area == pytest.approx(100.0)
    assert restored.equals(courtyard)


def test_front_modules_draw_on_the_depth_cut_line():
    # A 30 x 14 m bar at 0.5 m voxels: the first row of modules behind each long facade is 3 m deep, drawn exactly.
    bar = box(0, 0, 30, 14)
    vs = 0.5
    ij, xy, facades, faces = _faces(bar, vs)
    bay, bay_face = mg.cut_bays(faces, facades, [bar], 3.0, vs)
    shapes = mg.bay_polygons(xy, faces, bay, bay_face, facades, [bar], 3.0, vs)
    front = np.isin(bay, np.unique(bay[faces.d < 3.0]))
    plates = mg.plate_polygons(ij, front, ~front, vs, bar, bay=bay, bay_shapes=shapes)
    assert sorted(p.bounds for p in plates) == [(0.0, 0.0, 30.0, 3.0), (0.0, 11.0, 30.0, 14.0)]
    assert all(p.area == pytest.approx(90.0) for p in plates)


# ----------------------------------------------------------------- review fixes of the square modules
def _surface_cells(polygon, vs):
    """Grid columns (ij) and centres (xy) of every voxel square *polygon* covers, as the voxelizer marks the voxels
    the surface passes through: columns along a facade that is not aligned with the grid have their centre outside."""
    x0, y0, x1, y1 = polygon.bounds
    i, j = np.meshgrid(np.arange(int(np.floor(x0 / vs)), int(np.ceil(x1 / vs))),
                       np.arange(int(np.floor(y0 / vs)), int(np.ceil(y1 / vs))), indexing="ij")
    ij = np.stack([i.ravel(), j.ravel()], axis=1)
    squares = shapely.box(ij[:, 0] * vs, ij[:, 1] * vs, (ij[:, 0] + 1) * vs, (ij[:, 1] + 1) * vs)
    covered = shapely.area(shapely.intersection(squares, polygon)) > 0.0
    return ij[covered], (ij[covered] + 0.5) * vs


def _modules(polygon, ij, xy, vs, width=3.0):
    facades, corners = mg.split_facades([polygon])
    faces = mg.assign_faces(xy, facades, corners, [polygon], vs, min_facade_length=2 * width)
    bay, bay_face = mg.cut_bays(faces, facades, [polygon], width, vs)
    shapes = mg.bay_polygons(xy, faces, bay, bay_face, facades, [polygon], width, vs)
    return facades, faces, bay, bay_face, shapes


@pytest.mark.parametrize("base", [box(0, 0, 60, 14), L_SHAPE], ids=["slab", "L"])
@pytest.mark.parametrize("angle", [12, 35, 45, 65, 75, 90])
def test_plates_on_rotated_footprints_have_no_zero_length_edges_and_close_into_watertight_prisms(base, angle):
    from shapely import affinity
    poly = affinity.translate(affinity.rotate(base, angle, origin=(0, 0)), 20.13, 3.37)
    vs = 0.5
    ij, xy = _surface_cells(poly, vs)
    _, faces, bay, _, shapes = _modules(poly, ij, xy, vs)
    whole = np.ones(len(xy), bool)
    every_other_module = bay % 2 == 0
    front_row = np.isin(bay, np.unique(bay[faces.d < 3.0]))
    for in_plate in (whole, every_other_module, front_row):
        for plate in mg.plate_polygons(ij, in_plate, ~in_plate, vs, poly, min_dimension=3.0, bay=bay,
                                       bay_shapes=shapes):
            for ring in [plate.exterior, *plate.interiors]:
                edge_lengths = np.hypot(*np.diff(np.asarray(ring.coords), axis=0).T)
                assert edge_lengths.min() >= 1e-6
            assert mg.prism_mesh(plate, 0.0, 3.0).is_watertight


@pytest.mark.parametrize("angle", [17, 45])
def test_strips_one_module_deep_keep_their_floors_at_any_angle(angle):
    """A 100 x 92 m courtyard block, wings 4.5 m deep kept up to 33 m, the courtyard only up to 14 m.

    Above the courtyard only the first row of modules (3 m deep) fits each wing: the second one, 3 to 6 m deep, is
    half outside the envelope. The test for parts narrower than the minimum must keep that strip at any angle of the
    block to the voxel grid, not only where it is aligned with the grid.
    """
    from shapely import affinity
    vs, depth, offset = 0.5, 4.5, (60.13, 3.37)
    areas = {}
    for a in (0, angle):
        poly = affinity.translate(affinity.rotate(box(0, 0, 100, 92), a, origin=(0, 0)), *offset)
        ij, xy = _surface_cells(poly, vs)
        _, _, bay, _, shapes = _modules(poly, ij, xy, vs)
        cos, sin = np.cos(np.radians(a)), np.sin(np.radians(a))
        x = (xy[:, 0] - offset[0]) * cos + (xy[:, 1] - offset[1]) * sin       # in the block's own frame
        y = -(xy[:, 0] - offset[0]) * sin + (xy[:, 1] - offset[1]) * cos
        in_wing = np.minimum.reduce([x, 100 - x, y, 92 - y]) < depth
        top = np.where(in_wing, 33.0, 14.0)
        grid_ij = ij - ij.min(axis=0)
        occ = np.zeros((*(grid_ij.max(axis=0) + 1), 82), bool)
        centres = (np.arange(occ.shape[2]) + 0.5) * vs
        occ[grid_ij[:, 0], grid_ij[:, 1]] = centres[None, :] < 40.0
        kept = np.zeros_like(occ)
        kept[grid_ij[:, 0], grid_ij[:, 1]] = centres[None, :] < top[:, None]
        levels = mg.floor_levels(0.0, 40.0, 5.0, 3.0)
        floor = mg.build_floors(grid_ij, bay, occ, kept, 0.0, vs, levels, 0.2, "supported", 3.0)[5]   # 20 to 23 m
        assert floor.zb > 14.0
        areas[a] = sum(p.area for k in range(int(floor.plate.max()) + 1)
                       for p in mg.plate_polygons(ij, floor.plate == k, floor.plate != k, vs, poly,
                                                  min_dimension=3.0, bay=bay, bay_shapes=shapes))
    one_voxel_row_around_the_wings = 2 * (100 + 92) * vs
    assert areas[0] > 1000.0
    assert abs(areas[angle] - areas[0]) <= one_voxel_row_around_the_wings


def test_corner_square_of_a_curved_facade_is_cut_in_depth_from_its_end_edge():
    # Past the end of the bent facade (the corner square at the reflex corner) depth is measured from the line
    # through its last edge, as u continues along it, so the modules there are square like the others.
    bent_l = Polygon([(0, 0), (60, 0), (60, 15), (37, 17), (15, 15), (15, 60), (0, 60)])
    vs, width = 0.5, 3.0
    _, xy, facades, faces = _faces(bent_l, vs)
    bay, bay_face = mg.cut_bays(faces, facades, [bent_l], width, vs)
    bent = next(k for k, f in enumerate(facades) if not f.straight)
    facade = facades[bent]
    coords = np.asarray(facade.line.coords)
    last = (coords[-1] - coords[-2]) / np.hypot(*(coords[-1] - coords[-2]))
    past_end = (xy - facade.end) @ last > 0.0
    depth = np.where(past_end, (xy - facade.end) @ np.array([-last[1], last[0]]),
                     shapely.distance(shapely.points(xy), facade.line))
    assert (past_end & (faces.face == bent)).sum() > 100
    modules = np.flatnonzero(bay_face == bent)
    for b in modules:
        mine = bay == b
        u_lo, u_hi = faces.u[mine].min(), faces.u[mine].max()
        row_mates = [o for o in modules if o != b
                     and faces.u[bay == o].min() <= u_hi and faces.u[bay == o].max() >= u_lo]
        depth_span = np.ptp(depth[mine]) + vs
        if not row_mates and depth_span < width:
            continue                    # a row shallower than one module
        assert width - 1e-9 <= depth_span < 2 * width


# ----------------------------------------------------------------- refinements of the square modules
def _floor_on(base, angle, top, floor, vs=0.5, width=3.0, offset=(20.13, 3.37), z_top=40.0, tolerance=0.2,
              stacking="supported"):
    """Floor *floor* of *base* turned by *angle* and moved by *offset* on a voxel grid of *vs*, with the surface
    columns the voxelizer fills, the maximum volume up to *z_top* and the envelope up to ``top(x, y)`` (x, y in the
    block's own frame).  Returns the footprint, the floor, its plates and the columns' (x, y)."""
    from shapely import affinity
    poly = affinity.translate(affinity.rotate(base, angle, origin=(0, 0)), *offset)
    ij, xy = _surface_cells(poly, vs)
    _, _, bay, _, shapes = _modules(poly, ij, xy, vs, width)
    cos, sin = np.cos(np.radians(angle)), np.sin(np.radians(angle))
    x = (xy[:, 0] - offset[0]) * cos + (xy[:, 1] - offset[1]) * sin
    y = -(xy[:, 0] - offset[0]) * sin + (xy[:, 1] - offset[1]) * cos
    grid_ij = ij - ij.min(axis=0)
    centres = (np.arange(int(np.ceil(z_top / vs)) + 2) + 0.5) * vs
    occ = np.zeros((*(grid_ij.max(axis=0) + 1), len(centres)), bool)
    occ[grid_ij[:, 0], grid_ij[:, 1]] = centres[None, :] < z_top
    kept = np.zeros_like(occ)
    kept[grid_ij[:, 0], grid_ij[:, 1]] = centres[None, :] < top(x, y)[:, None]
    levels = mg.floor_levels(0.0, z_top, 5.0, 3.0)
    floors = mg.build_floors(grid_ij, bay, occ, kept, 0.0, vs, levels, tolerance, stacking, width,
                             column_share=mg.column_shares_inside(ij, vs, poly))
    plates = [p for k in range(int(floors[floor].plate.max()) + 1)
              for p in mg.plate_polygons(ij, floors[floor].plate == k, floors[floor].plate != k, vs, poly,
                                         min_dimension=width, bay=bay, bay_shapes=shapes)]
    return poly, floors[floor], plates, (x, y)


def _setbacks_on_both_long_sides(x, y):
    return np.where((y < 3.0) | (y > 11.0), 14.0, 33.0)


@pytest.mark.parametrize("angle", [0, 12, 30, 35, 65])
def test_a_slab_set_back_on_both_long_sides_keeps_a_straight_middle_strip_at_any_angle(angle):
    """A 60 x 14 m slab whose front 3 m on both long sides stop at 14 m: above, the plate is the middle strip, 60 x 8 m,
    without notches where the end facades are.  Columns whose centre lies just outside an end facade belong to the
    face of the footprint next to them, cut on the same depth lines."""
    from shapely import affinity
    _, _, plates, _ = _floor_on(box(0, 0, 60, 14), angle, _setbacks_on_both_long_sides, floor=5)
    strip = affinity.translate(affinity.rotate(box(0, 3, 60, 11), angle, origin=(0, 0)), 20.13, 3.37)
    assert len(plates) == 1
    assert plates[0].symmetric_difference(strip).area < 1e-4


def test_a_column_counts_by_its_share_inside_the_footprint():
    ij = np.array([[0, 0], [1, 0], [2, 0]])
    assert np.allclose(mg.column_shares_inside(ij, 1.0, box(0, 0, 2.5, 1)), [1.0, 1.0, 0.5])


def _sloping_across_the_depth(x, y):
    return 36.0 - 1.5 * y                         # 36 m on one long side, 15 m on the other


@pytest.mark.parametrize("angle", [17, 30, 45])
def test_a_floor_near_the_tolerance_does_not_depend_on_the_angle_to_the_grid(angle):
    """A 60 x 14 m slab whose envelope slopes across its depth from 36 to 15 m; on the floor from 14 to 17 m the front
    modules on the low side are close to the tolerance.  Columns along the facades that lie partly outside the
    footprint count only for their share inside it, so the floor is the same at any angle (840 m2, the whole slab)."""
    areas = [sum(p.area for p in _floor_on(box(0, 0, 60, 14), a, _sloping_across_the_depth, floor=4,
                                           stacking="free")[2]) for a in (0, angle)]
    one_voxel_row_around_the_slab = 2 * (60 + 14) * 0.5
    assert areas[0] == pytest.approx(840.0)
    assert abs(areas[1] - areas[0]) <= one_voxel_row_around_the_slab


def _parallelogram(shear):
    return Polygon([(0, 0), (60, 0), (60 + shear, 14), (shear, 14)])


def _plates_of_two_complementary_module_sets(polygon, vs, every):
    ij, xy = _surface_cells(polygon, vs)
    _, _, bay, _, shapes = _modules(polygon, ij, xy, vs)
    in_a = bay % every == 0
    a = shapely.union_all(mg.plate_polygons(ij, in_a, ~in_a, vs, polygon, bay=bay, bay_shapes=shapes))
    b = shapely.union_all(mg.plate_polygons(ij, ~in_a, in_a, vs, polygon, bay=bay, bay_shapes=shapes))
    return a, b


def _assert_disjoint_and_covering(polygon, a, b, vs):
    assert a.intersection(b).area < 1e-6
    # What the two leave uncovered are slivers along module edges drawn from columns, never a module or a strip
    # a voxel wide.
    assert polygon.difference(a).difference(b).buffer(-0.5 * vs).is_empty


@pytest.mark.parametrize("offset", [(20.13, 3.37), (20.0, 3.0)])
@pytest.mark.parametrize("angle", [0, 20])
@pytest.mark.parametrize("shear", [10, 20])
@pytest.mark.parametrize("every", [2, 3])
def test_plates_of_neighbouring_modules_at_slanted_ends_neither_overlap_nor_leave_a_module_out(shear, angle, offset,
                                                                                                every):
    """A parallelogram's slanted ends have modules cut by the bisector of the corner.  Two plates made of complementary
    sets of modules (every other module, every third) do not overlap, and together they cover the footprint up to
    slivers."""
    from shapely import affinity
    poly = affinity.translate(affinity.rotate(_parallelogram(shear), angle, origin=(0, 0)), *offset)
    a, b = _plates_of_two_complementary_module_sets(poly, 0.5, every)
    _assert_disjoint_and_covering(poly, a, b, 0.5)


TRAPEZOID = Polygon([(0, 0), (60, 0), (50, 14), (8, 14)])     # acute corners of 54 and 60 degrees at its base


def _directions_modules_may_be_cut_along(facades):
    """Directions (degrees, modulo 180) of every straight facade, of its normal and of the bisector of every two of
    them (the ridge the nearest-facade rule draws between their faces)."""
    straight = [f for f in facades if f.straight]
    normals = [np.array([-f.direction[1], f.direction[0]]) for f in straight]
    lines = [f.direction for f in straight] + normals
    for a in normals:
        for b in normals:
            if np.hypot(*(a - b)) > 1e-9:
                lines.append(np.array([-(a - b)[1], (a - b)[0]]))
    return np.degrees(np.arctan2([v[1] for v in lines], [v[0] for v in lines])) % 180.0


def _edges(polygon, shortest=0.0):
    """(start, end) of every edge of *polygon*'s rings at least *shortest* long."""
    for ring in [polygon.exterior, *polygon.interiors]:
        xy = np.asarray(ring.coords)
        for p, q in zip(xy[:-1], xy[1:]):
            if np.hypot(*(q - p)) >= shortest:
                yield p, q


def _footprint_with_corners_that_are_not_square(shape, angle):
    from shapely import affinity
    base = _parallelogram(20) if shape == "parallelogram" else TRAPEZOID
    return affinity.translate(affinity.rotate(base, angle, origin=(0, 0)), 20.13, 3.37)


@pytest.mark.parametrize("angle", [0, 20])
@pytest.mark.parametrize("shape", ["parallelogram", "trapezoid"])
def test_modules_at_corners_that_are_not_square_end_on_one_straight_slanted_edge(shape, angle):
    """At a corner that is not square the faces of its two facades meet along the bisector of the corner.  A module
    there is its rectangle cut by that line: every module has a shape, the shapes do not overlap, together they cover
    the footprint up to a voxel row along the outline, and every edge runs along a facade, across one or along a
    bisector (no staircase of voxel columns)."""
    poly = _footprint_with_corners_that_are_not_square(shape, angle)
    vs = 0.5
    ij, xy = _surface_cells(poly, vs)
    facades, _, _, _, shapes = _modules(poly, ij, xy, vs)
    assert all(shape is not None for shape in shapes)
    modules = np.array([shape.intersection(poly) for shape in shapes], dtype=object)
    first, second = shapely.STRtree(modules).query(modules, predicate="intersects")
    pairs = first < second
    assert shapely.area(shapely.intersection(modules[first[pairs]], modules[second[pairs]])).sum() < 1e-6
    uncovered = poly.difference(shapely.union_all(modules))
    assert uncovered.area <= poly.length * vs
    assert uncovered.buffer(-0.5 * vs).is_empty
    allowed = _directions_modules_may_be_cut_along(facades)
    for module in modules:
        for p, q in _edges(module, shortest=1e-3):
            direction = np.degrees(np.arctan2(q[1] - p[1], q[0] - p[0])) % 180.0
            off = np.abs(allowed - direction)
            assert np.minimum(off, 180.0 - off).min() < 0.01, (p, q)


@pytest.mark.parametrize("angle", [0, 20])
@pytest.mark.parametrize("shape", ["parallelogram", "trapezoid"])
def test_plates_at_corners_that_are_not_square_close_into_watertight_prisms(shape, angle):
    poly = _footprint_with_corners_that_are_not_square(shape, angle)
    vs = 0.5
    ij, xy = _surface_cells(poly, vs)
    _, faces, bay, _, shapes = _modules(poly, ij, xy, vs)
    from scipy.ndimage import label
    whole = np.ones(len(xy), bool)
    front_row = np.isin(bay, np.unique(bay[faces.d < 3.0]))
    grid_ij = ij - ij.min(axis=0)
    for built in (whole, bay % 2 == 0, bay % 3 == 0, front_row):
        grid = np.zeros(grid_ij.max(axis=0) + 1, bool)
        grid[grid_ij[built, 0], grid_ij[built, 1]] = True
        plate_of_column = np.where(built, label(grid)[0][grid_ij[:, 0], grid_ij[:, 1]], 0)   # as build_floors
        for k in range(1, plate_of_column.max() + 1):
            in_plate = plate_of_column == k
            for plate in mg.plate_polygons(ij, in_plate, ~in_plate, vs, poly, bay=bay, bay_shapes=shapes):
                assert all(np.hypot(*(q - p)) >= 1e-6 for p, q in _edges(plate))
                assert mg.prism_mesh(plate, 0.0, 3.0).is_watertight
    whole_plate = shapely.union_all(mg.plate_polygons(ij, whole, ~whole, vs, poly, bay=bay, bay_shapes=shapes))
    assert whole_plate.symmetric_difference(poly).area < 1e-6


def _wings(length, width, depth):
    def top(x, y):
        return np.where(np.minimum.reduce([x, length - x, y, width - y]) < depth, 33.0, 14.0)
    return top


@pytest.mark.parametrize("length", [100, 101, 102])
def test_the_end_wings_of_a_courtyard_block_keep_a_row_of_modules_whatever_its_length(length):
    """A courtyard block whose wings, 3.5 m deep, reach 33 m and whose courtyard is carved to 14 m.  Rows of modules
    are laid from both ends of the block, so each 92 m end wing keeps its first row (3 m) on the upper floors, whatever
    the length of the block; from the centroid, a 2 m end row joined its neighbour into a 5 m row, 30% outside the
    envelope, and the end wings vanished."""
    _, floor, _, (x, y) = _floor_on(box(0, 0, length, 92), 0, _wings(length, 92, 3.5), floor=5,
                                    offset=(60.13, 3.37))
    assert floor.zb > 14.0
    from_end = np.minimum(x, length - x)
    end_wings = (from_end > 0.5) & (from_end < 2.5) & (y > 5) & (y < 87)
    assert end_wings.sum() > 600
    assert (floor.plate[end_wings] >= 0).all()


def test_a_module_over_the_tolerance_leaves_a_hole_even_when_built_modules_enclose_it():
    """A local dip in the envelope (a cone 3 m deep, 5 m in radius) under the top floor of a 40 x 30 m block: the
    module over it has 41% of its volume outside the envelope, more than the tolerance, so it is not built and the
    plate has a hole of one module (9 m2).  Holes are not filled."""
    def dip(x, y):
        return 33.0 - 3.0 * np.clip(1.0 - np.hypot(x - 10.0, y - 10.0) / 5.0, 0.0, None)
    _, floor, plates, _ = _floor_on(box(0, 0, 40, 30), 0, dip, floor=9, z_top=33.0)
    assert (floor.zb, floor.zt) == (29.0, 32.0)
    unbuilt = np.flatnonzero(~floor.kept_bays)
    assert len(unbuilt) == 1 and floor.outside_share[unbuilt[0]] > 0.2
    assert len(plates) == 1 and [Polygon(h).area for h in plates[0].interiors] == [pytest.approx(9.0)]


@pytest.mark.slow
@pytest.mark.parametrize("vs", [0.5, 1.0])
def test_sweep_of_angles_and_shapes(vs):
    """The conditions above over more angles, shears and both voxel sizes."""
    from shapely import affinity
    for angle in range(0, 90, 7):
        _, _, plates, _ = _floor_on(box(0, 0, 60, 14), angle, _setbacks_on_both_long_sides, floor=5, vs=vs)
        strip = affinity.translate(affinity.rotate(box(0, 3, 60, 11), angle, origin=(0, 0)), 20.13, 3.37)
        assert len(plates) == 1 and plates[0].symmetric_difference(strip).area < 1e-4, angle
        area = sum(p.area for p in _floor_on(box(0, 0, 60, 14), angle, _sloping_across_the_depth, floor=4, vs=vs,
                                             stacking="free")[2])
        assert abs(area - 840.0) <= 2 * (60 + 14) * vs, angle
        for shear in (5, 10, 15, 20):
            poly = affinity.translate(affinity.rotate(_parallelogram(shear), angle, origin=(0, 0)), 20.13, 3.37)
            for every in (2, 3):
                a, b = _plates_of_two_complementary_module_sets(poly, vs, every)
                _assert_disjoint_and_covering(poly, a, b, vs)


def test_a_vertex_a_fraction_of_a_voxel_off_the_line_keeps_a_facade_straight():
    # Footprints from mesh sections carry vertices a fraction of a millimetre off a straight facade; within half a voxel
    # the facade stays straight, so its modules are rectangles. A bend the grid can resolve keeps it curved.
    block = Polygon([(0, 0), (20, 0.0003), (40, 0), (40, 15), (0, 15)])
    facades, _ = mg.split_facades([block], straight_tolerance=0.25)
    assert len(facades) == 4 and all(f.straight for f in facades)
    ij, xy = _cells(block, 0.5)
    facades, corners = mg.split_facades([block], straight_tolerance=0.25)
    faces = mg.assign_faces(xy, facades, corners, [block], 0.5)
    bay, bay_face = mg.cut_bays(faces, facades, [block], 3.0, 0.5)
    shapes = mg.bay_polygons(xy, faces, bay, bay_face, facades, [block], 3.0, 0.5)
    assert all(shape is not None for shape in shapes)
    bowed = Polygon([(0, 0), (20, 0.8), (40, 0), (40, 15), (0, 15)])
    facades, _ = mg.split_facades([bowed], straight_tolerance=0.25)
    assert sum(not f.straight for f in facades) == 1
