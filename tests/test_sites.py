"""Sites: the volume of a closed outline with elevations raised to a flat top (design/site-input.md)."""
import numpy as np
import pytest

from urbansolarcarver.sites import (
    Site, check_site, ground_spacing, site_base_volume, site_from_dict, site_ground, site_rise, site_to_dict, site_volume, sites_volume,
)

SQUARE = ((0, 0, 100), (40, 0, 100), (40, 30, 100), (0, 30, 100))
SLOPED = ((0, 0, 100), (40, 0, 102), (40, 30, 106), (0, 30, 101))
L_SHAPE = ((0, 0, 0), (60, 0, 3), (60, 20, 4), (20, 20, 5), (20, 50, 8), (0, 50, 2))


def test_a_flat_site_is_the_prism_from_its_level_to_the_top():
    mesh = site_volume(Site("a", SQUARE, 20), 1.0)
    assert mesh.is_watertight and mesh.is_volume
    assert mesh.volume == pytest.approx(40 * 30 * 20)
    assert mesh.bounds.tolist() == [[0, 0, 100], [40, 30, 120]]


def test_a_sloped_site_stands_on_its_ground_with_a_flat_top_at_the_lowest_vertex_plus_the_height():
    site = Site("b", SLOPED, 20)
    mesh = site_volume(site, 1.0)
    assert mesh.is_watertight and mesh.is_volume
    assert mesh.bounds.tolist() == [[0, 0, 100], [40, 30, 120]]
    # The corners' ground is bilinear on the rectangle, which is harmonic: the membrane is that surface, so the volume is exact
    mean_ground = (100 + 102 + 106 + 101) / 4
    assert mesh.volume == pytest.approx(40 * 30 * (120 - mean_ground), rel=1e-6)


def test_the_ground_takes_the_boundary_along_the_edges_and_stays_between_the_lowest_and_highest_vertex_inside():
    ground, triangles, boundary = site_ground(Site("b", SLOPED, 20), 1.0)
    assert (~boundary).sum() > 100
    assert ground[:, 2].min() >= 100 - 1e-9 and ground[:, 2].max() <= 106 + 1e-9
    on_south_edge = boundary & (np.abs(ground[:, 1]) < 1e-9)
    assert np.allclose(ground[on_south_edge, 2], 100 + 2 * ground[on_south_edge, 0] / 40)       # linear from 100 to 102
    assert len(triangles) > 0


@pytest.mark.slow
def test_an_l_shaped_site_is_one_closed_volume_inside_its_outline():
    site = Site("L", L_SHAPE, 15)
    mesh = site_volume(site, 0.5)
    assert mesh.is_watertight and mesh.is_volume
    assert mesh.bounds[1, 2] == pytest.approx(15)                    # lowest vertex 0
    assert mesh.bounds[0, 2] == pytest.approx(0)
    # No triangle reaches into the corner the L leaves out
    centres = mesh.triangles_center
    assert not np.any((centres[:, 0] > 20 + 1e-6) & (centres[:, 1] > 20 + 1e-6))


def test_two_overlapping_sites_join_into_one_mesh():
    other = tuple((x + 20, y + 10, z) for x, y, z in SQUARE)
    mesh = sites_volume([Site("a", SQUARE, 20), Site("b", other, 30)], 1.0)
    assert mesh.bounds.tolist() == [[0, 0, 100], [60, 40, 130]]
    with pytest.raises(ValueError):
        sites_volume([], 1.0)


@pytest.mark.parametrize(("points", "height", "reason"), [
    (((0, 0, 0), (1, 0, 0)), 5, "at least 3 vertices"),
    (((0, 0, 0), (10, 10, 0), (10, 0, 0), (0, 10, 0)), 5, "crosses itself"),
    (((0, 0, 0), (0.5, 0, 0), (0.5, 0.5, 0)), 5, "less than 1 m²"),
    (SQUARE, 0, "more than 0 m"),
    (((0, 0, 0), (10, 0, 0), (10, 10, 7)), 5, "rises 7.00 m, so its height must be more than 7.00 m"),
    (((0, 0, 0), (10, 0, float("nan")), (10, 10, 0)), 5, "no number"),
])
def test_a_site_that_cannot_make_a_volume_says_why(points, height, reason):
    reasons = check_site(Site("x", points, height))
    assert any(reason in text for text in reasons), reasons
    with pytest.raises(ValueError, match="site 'x'"):
        site_volume(Site("x", points, height), 1.0)


def test_a_repeated_last_point_is_the_first_and_does_not_count():
    closed = SQUARE + (SQUARE[0],)
    assert check_site(Site("a", closed, 10)) == []
    assert site_volume(Site("a", closed, 10), 1.0).volume == pytest.approx(40 * 30 * 10)


def test_the_ground_spacing_is_finer_on_a_small_site_and_coarser_on_a_huge_one():
    assert ground_spacing(Site("a", SQUARE, 10), 1.0) == pytest.approx(1.0)
    small = ((0, 0, 0), (4, 0, 0), (4, 3, 1), (0, 3, 0))
    assert ground_spacing(Site("s", small, 10), 1.0) == pytest.approx(3 / 20)
    huge = ((0, 0, 0), (2000, 0, 0), (2000, 1500, 0), (0, 1500, 0))
    assert ground_spacing(Site("h", huge, 10), 0.5) > 10


def test_a_site_round_trips_through_a_dict_and_reports_its_rise():
    site = Site("b", SLOPED, 20.5)
    assert site_from_dict(site_to_dict(site)) == Site("b", tuple(tuple(float(c) for c in p) for p in SLOPED), 20.5)
    assert site_rise(site) == pytest.approx(6)


def test_the_base_volume_is_the_outline_from_the_bottom_to_the_lowest_vertex_plus_the_base():
    mesh = site_base_volume(Site("b", SLOPED, 20), 8, 90)
    assert mesh.is_watertight and mesh.is_volume
    assert mesh.bounds.tolist() == [[0, 0, 90], [40, 30, 108]]
    assert mesh.volume == pytest.approx(40 * 30 * 18)
    low = site_base_volume(Site("b", SLOPED, 20), 2, 90)            # below the uphill ground: still the whole outline
    assert low.bounds[1][2] == 102
    with pytest.raises(ValueError, match="more than 0"):
        site_base_volume(Site("b", SLOPED, 20), 0, 90)


# ---- Holes (design/site-holes.md) ----

def _square(x0, y0, x1, y1, z=100.0):
    return ((x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z))


COURTYARD = _square(10, 10, 30, 20)


def test_a_flat_site_with_a_hole_leaves_the_hole_out_from_its_level_to_the_top():
    site = Site("block", SQUARE, 20, (COURTYARD,))
    mesh = site_volume(site, 1.0)
    assert mesh.is_watertight and mesh.is_volume
    assert mesh.volume == pytest.approx((40 * 30 - 20 * 10) * 20)
    assert mesh.contains([[20, 15, 110], [5, 5, 110]]).tolist() == [False, True]


def test_a_sloped_site_with_a_hole_takes_the_holes_vertices_into_its_ground_and_levels():
    hole = ((10, 10, 99), (30, 10, 99), (30, 20, 103), (10, 20, 103))      # its ground dips below the outline's lowest vertex
    site = Site("block", SLOPED, 20, (hole,))
    assert site_rise(site) == pytest.approx(7)
    mesh = site_volume(site, 1.0)
    assert mesh.is_watertight and mesh.is_volume
    assert mesh.bounds[1][2] == pytest.approx(99 + 20)                      # the top is the lowest vertex, a hole's, plus the height
    assert not mesh.contains([[20, 15, 110]])[0]
    vertices, _, boundary = site_ground(site, 1.0)
    on_hole = boundary & (np.abs(vertices[:, 0] - 10) < 1e-9) & (vertices[:, 1] > 10) & (vertices[:, 1] < 20)
    # Along a hole edge the ground is linear between its vertices: 99 at y = 10, 103 at y = 20
    assert np.allclose(vertices[on_hole, 2], 99 + (vertices[on_hole, 1] - 10) * 0.4)


def test_the_base_volume_of_a_site_with_a_hole_leaves_the_hole_out():
    mesh = site_base_volume(Site("block", SQUARE, 20, (COURTYARD,)), 5, 90)
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx((40 * 30 - 20 * 10) * 15)


@pytest.mark.parametrize(("holes", "reason"), [
    ((_square(30, 10, 50, 20),), "hole 1 is not strictly inside the outline"),
    ((_square(0, 10, 10, 20),), "hole 1 is not strictly inside the outline"),             # touching the outline is not inside
    ((((10, 10, 100), (30, 20, 100), (30, 10, 100), (10, 20, 100)),), "hole 1 crosses itself"),
    ((_square(10, 10, 10.5, 10.5),), "hole 1's area is 0.25 m², less than 1 m²"),
    ((COURTYARD, _square(25, 15, 35, 25)), "hole 1 and hole 2 touch or cross"),
    ((COURTYARD, _square(30, 10, 35, 20)), "hole 1 and hole 2 touch or cross"),           # sharing an edge is touching
])
def test_a_hole_that_does_not_fit_is_refused_with_its_reason(holes, reason):
    assert reason in check_site(Site("block", SQUARE, 20, holes))


def test_two_holes_apart_are_accepted_and_holes_round_trip_through_a_dict():
    site = Site("block", SQUARE, 20, (_square(5, 5, 15, 15), _square(25, 5, 35, 15)))
    assert check_site(site) == []
    assert site_from_dict(site_to_dict(site)) == site
    assert "holes" not in site_to_dict(Site("plain", SQUARE, 20))
    assert site_from_dict({"name": "old", "points": [list(p) for p in SQUARE], "height": 20}).holes == ()
