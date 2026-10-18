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
        bays, _ = mg.cut_bays(mg.assign_faces(xy, facades, corners, [poly], 1.0), 3.0, 1.0)
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
    bay, bay_face = mg.cut_bays(faces, 3.0, vs)
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
    bay, bay_face = mg.cut_bays(faces, 3.0, vs)
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
    bay, bay_face = mg.cut_bays(faces, 3.0, 0.5)
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
    bay, bay_face = mg.cut_bays(faces, 3.0, vs)
    shapes = mg.bay_polygons(xy, faces, bay, bay_face, facades, [bar], 3.0, vs)
    front = np.isin(bay, np.unique(bay[faces.d < 3.0]))
    plates = mg.plate_polygons(ij, front, ~front, vs, bar, bay=bay, bay_shapes=shapes)
    assert sorted(p.bounds for p in plates) == [(0.0, 0.0, 30.0, 3.0), (0.0, 11.0, 30.0, 14.0)]
    assert all(p.area == pytest.approx(90.0) for p in plates)
