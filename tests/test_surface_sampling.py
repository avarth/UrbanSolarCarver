"""Test-surface sampling (surface_sampling.py): coplanarity, boundary samples,
edge taper and degenerate faces."""
import pytest
import numpy as np


class TestCoplanarityCheck:
    """Tests for discretize_surface_with_normals coplanarity filtering."""

    def _make_planar_mesh(self, normal_spread_deg=0.0):
        """Create a two-triangle unit quad, optionally bent.

        Raising vertex 2 (shared by both triangles) by tan(normal_spread_deg)
        tilts the two triangles in different directions. Each face normal then
        sits about 0.7 x normal_spread_deg from the mean normal, which is the
        angle the coplanarity check compares with its tolerance.
        """
        import trimesh
        # Base: flat quad on XY plane
        verts = np.array([
            [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)

        if normal_spread_deg > 0:
            tilt_height = np.tan(np.radians(normal_spread_deg))
            verts[2, 2] = tilt_height

        return trimesh.Trimesh(vertices=verts, faces=faces, process=False)

    def test_perfectly_planar_accepted(self):
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=0.0)
        pts, norms, _mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2)
        assert pts.shape[0] > 0, "Perfectly planar mesh should produce samples"

    def test_within_tolerance_accepted(self):
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=3.0)
        pts, norms, _mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2, coplanarity_tol_deg=5.0)
        assert pts.shape[0] > 0, "3° spread should pass 5° tolerance"

    def test_exceeds_tolerance_rejected(self):
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=10.0)
        pts, norms, _mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2, coplanarity_tol_deg=5.0)
        assert pts.shape[0] == 0, "10° spread should fail 5° tolerance"

    def test_single_triangle_always_passes(self):
        """A single-face mesh has zero spread, so it is always planar."""
        import trimesh
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        verts = np.array([[0, 0, 0], [2, 0, 0], [1, 2, 0]], dtype=np.float64)
        faces = np.array([[0, 1, 2]], dtype=np.int32)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        pts, norms, _mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.3)
        assert pts.shape[0] > 0

    def test_all_rejected_returns_empty(self):
        """When all components fail planarity, return empty arrays."""
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=20.0)
        pts, norms, _mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2, coplanarity_tol_deg=5.0)
        assert pts.shape == (0, 3)
        assert norms.shape == (0, 3)

    def test_normals_unit_length(self):
        """Output normals should be approximately unit length."""
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=0.0)
        pts, norms, _mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2)
        if norms.shape[0] > 0:
            lengths = np.linalg.norm(norms, axis=1)
            np.testing.assert_allclose(lengths, 1.0, atol=0.01)

    def test_analysis_mesh_returned(self):
        """Planar mesh should return an AnalysisMesh with 1:1 face mapping."""
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals, AnalysisMesh
        mesh = self._make_planar_mesh(normal_spread_deg=0.0)
        pts, norms, analysis_mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2)
        assert pts.shape[0] > 0
        assert isinstance(analysis_mesh, AnalysisMesh)
        # Face count == sample point count (1:1 mapping)
        assert len(analysis_mesh.faces) == pts.shape[0]

    def test_analysis_mesh_none_when_rejected(self):
        """When all components fail planarity, analysis_mesh should be None."""
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=20.0)
        pts, norms, analysis_mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2, coplanarity_tol_deg=5.0)
        assert pts.shape == (0, 3)
        assert analysis_mesh is None

    def test_sample_step_larger_than_face(self):
        """When sample_step exceeds the face size, skip gracefully (no crash)."""
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=0.0)  # 1x1 quad
        pts, norms, analysis_mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=10.0)
        # Either 0 points (face too small) or a few points; it must not raise
        assert pts.shape[1] == 3


class TestEdgeSampling:
    """Tests for boundary edge seeding in sample_planar_surface."""

    def _make_flat_quad(self, width=1.0, height=1.0):
        """Create a flat rectangular trimesh on the XY plane."""
        import trimesh
        verts = np.array([
            [0, 0, 0], [width, 0, 0], [width, height, 0], [0, height, 0],
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)
        return trimesh.Trimesh(vertices=verts, faces=faces, process=False)

    def test_edge_coverage(self):
        """Every boundary segment should have a sample point nearby."""
        from urbansolarcarver.surface_sampling import sample_planar_surface
        from shapely.geometry import Polygon, LineString
        mesh = self._make_flat_quad(1.0, 1.0)
        step = 0.3
        pts, norms, qv, qf, _w = sample_planar_surface(mesh, sample_step=step)
        # Project points to XY (mesh is on XY plane)
        pts_2d = pts[:, :2]
        # Check that every point along the boundary has a nearby sample
        boundary = LineString([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
        max_gap = 0
        for d in np.arange(0, boundary.length, step * 0.25):
            bp = boundary.interpolate(d)
            dists = np.linalg.norm(pts_2d - np.array([bp.x, bp.y]), axis=1)
            max_gap = max(max_gap, dists.min())
        # Corners have slightly larger gaps because edge points are offset
        # inward; allow up to 1.2 * step.
        assert max_gap < step * 1.2, (
            f"Largest gap from boundary to nearest sample: {max_gap:.3f} "
            f"(should be < {step * 1.2:.3f})"
        )

    def test_no_duplicate_near_grid(self):
        """Edge points should not be too close to interior grid points."""
        from urbansolarcarver.surface_sampling import sample_planar_surface, _sample_boundary_edges
        from shapely.geometry import Polygon
        mesh = self._make_flat_quad(2.0, 2.0)
        step = 0.4
        pts, _, _, _, _w = sample_planar_surface(mesh, sample_step=step)
        # All pairwise distances should be > step * 0.3 (generous margin)
        from scipy.spatial import cKDTree
        pts_2d = pts[:, :2]
        if len(pts_2d) > 1:
            tree = cKDTree(pts_2d)
            dists, _ = tree.query(pts_2d, k=2)  # k=2: nearest != self
            min_pair_dist = dists[:, 1].min()
            assert min_pair_dist > step * 0.3, (
                f"Points too close: {min_pair_dist:.4f} < {step * 0.3:.4f}"
            )

    def test_analysis_mesh_count(self):
        """Quad face count must equal sample point count (1:1 mapping)."""
        from urbansolarcarver.surface_sampling import sample_planar_surface
        mesh = self._make_flat_quad(1.0, 1.0)
        pts, norms, qv, qf, _w = sample_planar_surface(mesh, sample_step=0.3)
        assert len(qf) == len(pts), (
            f"Quad faces ({len(qf)}) != points ({len(pts)})"
        )

    def test_thin_rectangle_gets_edge_points(self):
        """A rectangle thinner than sample_step should still get edge points."""
        from urbansolarcarver.surface_sampling import sample_planar_surface
        # Width 0.1, height 3.0, step 0.5: too thin for interior grid points
        mesh = self._make_flat_quad(0.1, 3.0)
        pts, norms, qv, qf, _w = sample_planar_surface(mesh, sample_step=0.5)
        assert len(pts) >= 2, (
            f"Thin rectangle should have edge points, got {len(pts)}"
        )


class TestEdgeTaper:
    """edge_taper design weights: distance-to-boundary ramp on sample points."""

    def _flat_quad(self, w, h, z=0.0):
        import trimesh
        verts = np.array([[0, 0, z], [w, 0, z], [w, h, z], [0, h, z]],
                         dtype=np.float64)
        faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)
        return trimesh.Trimesh(vertices=verts, faces=faces, process=False)

    def test_taper_off_returns_ones(self):
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        mesh = self._flat_quad(10, 10)
        pts, _n, _m, w, stats = discretize_surface_with_normals(
            mesh, sample_step=1.0, edge_taper=0.0)
        assert w.shape == (pts.shape[0],)
        np.testing.assert_array_equal(w, 1.0)
        assert stats == []

    def test_square_ramp_matches_analytic_distance(self):
        """On a rectangle the boundary distance is min(x, w-x, y, h-y)."""
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        taper = 2.0
        mesh = self._flat_quad(10, 10)
        pts, _n, _m, w, _s = discretize_surface_with_normals(
            mesh, sample_step=0.5, edge_taper=taper)
        x, y = pts[:, 0], pts[:, 1]
        dist = np.minimum.reduce([x, 10 - x, y, 10 - y])
        expected = np.clip(dist / taper, 0.0, 1.0)
        np.testing.assert_allclose(w, expected, atol=1e-4)
        # Deep interior reaches full weight; edge-seeded points are ~0.
        assert w.max() == pytest.approx(1.0)
        assert w.min() < 0.05

    def test_exploded_coincident_panels_have_no_seam(self):
        """Two abutting coplanar panels with duplicated (coincident) vertices
        weld into one component (trimesh process=True), so the internal seam
        must NOT count as a boundary."""
        import trimesh
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        verts = np.array([
            # panel A: [0,5]x[0,10]
            [0, 0, 0], [5, 0, 0], [5, 10, 0], [0, 10, 0],
            # panel B: [5,10]x[0,10], seam vertices duplicated
            [5, 0, 0], [10, 0, 0], [10, 10, 0], [5, 10, 0],
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]],
                         dtype=np.int32)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
        assert len(mesh.split(only_watertight=False)) == 1, "panels must weld"

        pts, _n, _m, w, _s = discretize_surface_with_normals(
            mesh, sample_step=0.5, edge_taper=1.0)
        # Points on the seam line (x≈5) but deep inside the outline must have
        # full weight; a phantom seam boundary would drag them to ~0.
        on_seam = (np.abs(pts[:, 0] - 5.0) < 0.3) & (np.abs(pts[:, 1] - 5.0) < 2.0)
        assert on_seam.any(), "expected samples near the seam"
        assert w[on_seam].min() > 0.99

    def test_narrow_component_warns_and_never_reaches_full_weight(self):
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        mesh = self._flat_quad(1.5, 20)  # narrower than 2 x taper
        with pytest.warns(UserWarning, match="never reaches full weight"):
            pts, _n, _m, w, stats = discretize_surface_with_normals(
                mesh, sample_step=0.25, edge_taper=1.0)
        assert w.max() < 1.0
        assert len(stats) == 1
        assert stats[0]["max_weight"] < 1.0

    def test_hole_boundary_tapers(self):
        """Interior holes count as boundary: points near the hole edge taper."""
        import trimesh
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        # 10x10 plate with a 2x2 hole in the middle (ring of 8 triangles).
        o = [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]]
        i = [[4, 4, 0], [6, 4, 0], [6, 6, 0], [4, 6, 0]]
        verts = np.array(o + i, dtype=np.float64)
        faces = np.array([
            [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
            [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
        ], dtype=np.int32)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        pts, _n, _m, w, _s = discretize_surface_with_normals(
            mesh, sample_step=0.5, edge_taper=1.0)
        # A point ~0.5 m from the hole edge must taper to ~0.5 even though it
        # is 3.5 m from the outer boundary.
        near_hole = (np.abs(pts[:, 0] - 3.5) < 0.15) & (np.abs(pts[:, 1] - 5.0) < 0.15)
        assert near_hole.any()
        assert w[near_hole].max() < 0.6

    def test_l_shape_concave(self):
        """Concave (L-shaped) outlines are handled by plain boundary distance."""
        import trimesh
        from urbansolarcarver.surface_sampling import discretize_surface_with_normals
        # L: 10x10 square minus the [4..10]x[4..10] corner.
        verts = np.array([
            [0, 0, 0], [10, 0, 0], [10, 4, 0], [4, 4, 0], [4, 10, 0], [0, 10, 0],
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 5]],
                         dtype=np.int32)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        pts, _n, _m, w, _s = discretize_surface_with_normals(
            mesh, sample_step=0.5, edge_taper=1.0)
        assert ((w >= 0.0) & (w <= 1.0)).all()
        # Centers of both legs are >= 1 m from any edge: full weight.
        leg_a = (np.abs(pts[:, 0] - 7.0) < 0.3) & (np.abs(pts[:, 1] - 2.0) < 0.3)
        leg_b = (np.abs(pts[:, 0] - 2.0) < 0.3) & (np.abs(pts[:, 1] - 7.0) < 0.3)
        assert w[leg_a].min() > 0.99
        assert w[leg_b].min() > 0.99


def _sampling_settings():
    from urbansolarcarver.load_config import user_config
    from urbansolarcarver.stage_settings import PreprocessingSettings
    return PreprocessingSettings.from_config(user_config(
        max_volume_path="x", test_surface_path="x", out_dir="x",
        mode="tilted_plane", tilted_plane_angle_deg=45,
        grid_step=1.0, voxel_size=1.0))


def test_zero_area_face_does_not_drop_panel_and_bent_panel_warns():
    import trimesh
    from urbansolarcarver.surface_sampling import sample_surface
    rect = trimesh.Trimesh([[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3], [4, 0, 3]],
                           [[0, 1, 2], [0, 2, 3], [1, 2, 4]], process=False)  # last face: zero area
    bent = trimesh.Trimesh([[10, 0, 0], [14, 0, 0], [14, 1, 3], [10, 0, 3]],
                           [[0, 1, 2], [0, 2, 3]], process=False)
    with pytest.warns(UserWarning, match="1 non-planar"):
        pts, *_ = sample_surface(trimesh.util.concatenate([rect, bent]), _sampling_settings())
    assert len(pts) > 0 and pts[:, 0].max() <= 4.0  # the rectangle is sampled, the bent panel is not
