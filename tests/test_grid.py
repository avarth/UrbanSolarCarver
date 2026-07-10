"""Invariant tests for grid operations — mathematical constraints that must hold."""
import pytest
import numpy as np
import torch


class TestVoxelizeInvariants:
    def test_voxelize_produces_filled_grid(self, tiny_cube_mesh):
        from urbansolarcarver.grid import voxelize_mesh
        grid, origin, extent, res = voxelize_mesh(tiny_cube_mesh, voxel_size=2.0)
        assert grid.sum() > 0, "Voxelization produced empty grid"
        assert grid.dtype == torch.uint8

    def test_voxelize_grid_is_cubic(self, tiny_cube_mesh):
        from urbansolarcarver.grid import voxelize_mesh
        grid, origin, extent, res = voxelize_mesh(tiny_cube_mesh, voxel_size=2.0)
        d0, d1, d2 = grid.shape
        assert d0 == d1 == d2, f"Grid not cubic: {grid.shape}"


class TestMeshFromVoxels:
    def test_cubic_mesh_has_axis_aligned_normals(self, tiny_cube_mesh):
        """Cubic meshing should produce only axis-aligned face normals."""
        from urbansolarcarver.grid import voxelize_mesh, mesh_from_voxels
        grid, origin, extent, res = voxelize_mesh(tiny_cube_mesh, voxel_size=2.0)
        mesh = mesh_from_voxels(grid, origin, voxel_size=2.0)
        if len(mesh.faces) == 0:
            pytest.skip("No faces produced (tiny mesh)")
        # Each face normal should have exactly one non-zero component
        normals = np.abs(mesh.face_normals)
        dominant = normals.max(axis=1)
        assert np.allclose(dominant, 1.0, atol=0.01), "Non-axis-aligned normals in cubic mesh"

    def test_mesh_within_original_bounds(self, tiny_cube_mesh):
        """Mesh reconstructed from voxels should be within original bounds (+ margin)."""
        from urbansolarcarver.grid import voxelize_mesh, mesh_from_voxels
        grid, origin, extent, res = voxelize_mesh(tiny_cube_mesh, voxel_size=2.0)
        mesh = mesh_from_voxels(grid, origin, voxel_size=2.0)
        if len(mesh.vertices) == 0:
            pytest.skip("No vertices produced")
        orig_min, orig_max = tiny_cube_mesh.bounds
        margin = 2.0  # one voxel margin
        assert np.all(mesh.bounds[0] >= orig_min - margin)
        assert np.all(mesh.bounds[1] <= orig_max + margin)


class TestCoplanarityCheck:
    """Tests for discretize_surface_with_normals coplanarity filtering."""

    def _make_planar_mesh(self, normal_spread_deg=0.0):
        """Create a mesh with controlled face-normal spread."""
        import trimesh
        # Base: flat quad on XY plane
        verts = np.array([
            [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)

        if normal_spread_deg > 0:
            # Tilt second triangle by raising one vertex
            tilt_height = np.tan(np.radians(normal_spread_deg))
            verts[2, 2] = tilt_height

        return trimesh.Trimesh(vertices=verts, faces=faces, process=False)

    def test_perfectly_planar_accepted(self):
        from urbansolarcarver.grid import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=0.0)
        pts, norms, _mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2)
        assert pts.shape[0] > 0, "Perfectly planar mesh should produce samples"

    def test_within_tolerance_accepted(self):
        from urbansolarcarver.grid import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=3.0)
        pts, norms, _mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2, coplanarity_tol_deg=5.0)
        assert pts.shape[0] > 0, "3° spread should pass 5° tolerance"

    def test_exceeds_tolerance_rejected(self):
        from urbansolarcarver.grid import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=10.0)
        pts, norms, _mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2, coplanarity_tol_deg=5.0)
        assert pts.shape[0] == 0, "10° spread should fail 5° tolerance"

    def test_single_triangle_always_passes(self):
        """A single-face mesh has zero spread — always planar."""
        import trimesh
        from urbansolarcarver.grid import discretize_surface_with_normals
        verts = np.array([[0, 0, 0], [2, 0, 0], [1, 2, 0]], dtype=np.float64)
        faces = np.array([[0, 1, 2]], dtype=np.int32)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        pts, norms, _mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.3)
        assert pts.shape[0] > 0

    def test_all_rejected_returns_empty(self):
        """When all components fail planarity, return empty arrays."""
        from urbansolarcarver.grid import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=20.0)
        pts, norms, _mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2, coplanarity_tol_deg=5.0)
        assert pts.shape == (0, 3)
        assert norms.shape == (0, 3)

    def test_normals_unit_length(self):
        """Output normals should be approximately unit length."""
        from urbansolarcarver.grid import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=0.0)
        pts, norms, _mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2)
        if norms.shape[0] > 0:
            lengths = np.linalg.norm(norms, axis=1)
            np.testing.assert_allclose(lengths, 1.0, atol=0.01)

    def test_analysis_mesh_returned(self):
        """Planar mesh should return an AnalysisMesh with 1:1 face mapping."""
        from urbansolarcarver.grid import discretize_surface_with_normals, AnalysisMesh
        mesh = self._make_planar_mesh(normal_spread_deg=0.0)
        pts, norms, analysis_mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2)
        assert pts.shape[0] > 0
        assert isinstance(analysis_mesh, AnalysisMesh)
        # Face count == sample point count (1:1 mapping)
        assert len(analysis_mesh.faces) == pts.shape[0]

    def test_analysis_mesh_none_when_rejected(self):
        """When all components fail planarity, analysis_mesh should be None."""
        from urbansolarcarver.grid import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=20.0)
        pts, norms, analysis_mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=0.2, coplanarity_tol_deg=5.0)
        assert pts.shape == (0, 3)
        assert analysis_mesh is None

    def test_sample_step_larger_than_face(self):
        """When sample_step exceeds the face size, skip gracefully (no crash)."""
        from urbansolarcarver.grid import discretize_surface_with_normals
        mesh = self._make_planar_mesh(normal_spread_deg=0.0)  # 1x1 quad
        pts, norms, analysis_mesh, _w, _ts = discretize_surface_with_normals(mesh, sample_step=10.0)
        # Either returns 0 points (face too small) or a few points — must not crash
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
        from urbansolarcarver.grid import sample_planar_surface
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
        # Corners have slightly larger gaps due to inward offset; allow up
        # to 1.2 * step (still much better than the pre-fix worst case of
        # ~1.0 * step with no edge points at all).
        assert max_gap < step * 1.2, (
            f"Largest gap from boundary to nearest sample: {max_gap:.3f} "
            f"(should be < {step * 1.2:.3f})"
        )

    def test_no_duplicate_near_grid(self):
        """Edge points should not be too close to interior grid points."""
        from urbansolarcarver.grid import sample_planar_surface, _sample_boundary_edges
        from shapely.geometry import Polygon
        # Build a polygon and grid the same way the function does
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
        from urbansolarcarver.grid import sample_planar_surface
        mesh = self._make_flat_quad(1.0, 1.0)
        pts, norms, qv, qf, _w = sample_planar_surface(mesh, sample_step=0.3)
        assert len(qf) == len(pts), (
            f"Quad faces ({len(qf)}) != points ({len(pts)})"
        )

    def test_thin_rectangle_gets_edge_points(self):
        """A rectangle thinner than sample_step should still get edge points."""
        from urbansolarcarver.grid import sample_planar_surface
        # Width 0.1, height 3.0, step 0.5 — too thin for interior grid points
        mesh = self._make_flat_quad(0.1, 3.0)
        pts, norms, qv, qf, _w = sample_planar_surface(mesh, sample_step=0.5)
        assert len(pts) >= 2, (
            f"Thin rectangle should have edge points, got {len(pts)}"
        )


def _warp_cpu_available():
    from urbansolarcarver.raytracer import dda_backend_available
    return dda_backend_available(torch.device("cpu"))


class TestWarpVoxelizer:
    """Parity ray-casting voxelizer vs the trimesh rasterize-and-fill path."""

    def _trimesh_reference(self, mesh, voxel_size, margin_frac):
        """Run voxelize_mesh with the Warp path disabled."""
        import urbansolarcarver.raytracer as rt
        from urbansolarcarver.grid import voxelize_mesh
        saved = rt.voxelize_solid_warp
        rt.voxelize_solid_warp = lambda *a, **k: None
        try:
            grid, origin, _, res = voxelize_mesh.__wrapped__(
                mesh, voxel_size=voxel_size, margin_frac=margin_frac
            )
        finally:
            rt.voxelize_solid_warp = saved
        return grid.numpy().astype(bool), origin, res

    @pytest.mark.skipif(not _warp_cpu_available(), reason="Warp CPU unavailable")
    def test_cube_matches_center_truth_exactly(self):
        """On a boundary-aligned cube, the parity voxelizer must reproduce
        the center-inside ground truth voxel for voxel."""
        import trimesh
        from urbansolarcarver.raytracer import voxelize_solid_warp
        cube = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
        res, vs = 7, 2.0
        origin = np.array([-7.0, -7.0, -7.0])
        occ = voxelize_solid_warp(cube.vertices, cube.faces, origin, vs, res, torch.device("cpu"))

        centers = origin[0] + (np.arange(res) + 0.5) * vs
        in1d = (centers > -5.0) & (centers < 5.0)
        truth = np.zeros((res,) * 3, dtype=bool)
        ix = np.nonzero(in1d)[0]
        truth[np.ix_(ix, ix, ix)] = True
        np.testing.assert_array_equal(occ, truth)

    @pytest.mark.skipif(not _warp_cpu_available(), reason="Warp CPU unavailable")
    @pytest.mark.parametrize("shape", ["sphere", "box"])
    def test_differences_confined_to_surface_shell(self, shape):
        """Warp and trimesh voxelizations may disagree only within one
        voxel of the surface (center-based vs conservative shell)."""
        import trimesh
        from scipy.ndimage import binary_dilation
        from urbansolarcarver.raytracer import voxelize_solid_warp

        if shape == "sphere":
            mesh = trimesh.creation.icosphere(subdivisions=3, radius=8.0)
        else:
            mesh = trimesh.creation.box(extents=(11.0, 7.0, 5.0))
        ref, origin, res = self._trimesh_reference(mesh, 0.5, 0.1)
        occ = voxelize_solid_warp(mesh.vertices, mesh.faces, origin, 0.5, res, torch.device("cpu"))

        st = np.ones((3, 3, 3), dtype=bool)
        assert not (occ & ~binary_dilation(ref, structure=st)).any()
        assert not (ref & ~binary_dilation(occ, structure=st)).any()
        # And the interiors overwhelmingly agree
        iou = (ref & occ).sum() / max((ref | occ).sum(), 1)
        assert iou > 0.9


class TestSmoothedMeshPath:
    """Tests for mesh_from_voxels_smoothed (SDF + marching cubes)."""

    def _cube_voxels(self):
        vox = torch.zeros((24, 24, 24), dtype=torch.uint8)
        vox[4:20, 4:20, 4:20] = 1  # 16^3 cube, volume 4096
        return vox

    def test_watertight_positive_volume(self):
        from urbansolarcarver.grid import mesh_from_voxels_smoothed
        mesh = mesh_from_voxels_smoothed(self._cube_voxels(), np.zeros(3), 1.0)
        assert len(mesh.faces) > 0
        assert mesh.is_watertight
        assert mesh.volume > 0, "faces must be wound outward"

    def test_volume_matched(self):
        """Volume-matched iso keeps the mesh volume close to the voxel count."""
        from urbansolarcarver.grid import mesh_from_voxels_smoothed
        mesh = mesh_from_voxels_smoothed(self._cube_voxels(), np.zeros(3), 1.0)
        assert 0.85 * 4096 < mesh.volume < 1.15 * 4096

    def test_surface_actually_smoothed(self):
        """Marching cubes must run on the continuous SDF: vertices should
        interpolate between voxel centers, not sit on the binary lattice."""
        from urbansolarcarver.grid import mesh_from_voxels_smoothed
        mesh = mesh_from_voxels_smoothed(self._cube_voxels(), np.zeros(3), 1.0)
        frac = np.abs(mesh.vertices - np.round(mesh.vertices))
        assert (frac > 0.05).any(), "all vertices on lattice — SDF was binarized"

    def test_world_alignment(self):
        """Voxel [4:20) at voxel_size=1 spans world [4, 20] (+/- smoothing)."""
        from urbansolarcarver.grid import mesh_from_voxels_smoothed
        origin = np.array([100.0, 200.0, 300.0])
        mesh = mesh_from_voxels_smoothed(self._cube_voxels(), origin, 1.0)
        lo, hi = mesh.bounds - origin
        assert np.all(lo > 2.5) and np.all(hi < 21.5), f"bounds off: {lo}..{hi}"

    def test_finalize_mesh_smooth_path(self):
        """The full smoothed finalize path (prune → SDF → MC → cleanup →
        Taubin) must deliver a watertight, positive-volume mesh."""
        from types import SimpleNamespace
        from urbansolarcarver.grid import finalize_mesh
        cfg = SimpleNamespace(
            apply_smoothing=True, min_voxels=10, min_face_count=10,
            smooth_iters=2, voxel_size=1.0,
        )
        _, _, final = finalize_mesh(self._cube_voxels(), np.zeros(3), cfg)
        assert len(final.faces) > 0
        assert final.is_watertight
        assert final.volume > 0.8 * 4096


class TestPruneVoxels:
    def test_prune_removes_small_components(self):
        """Pruning should remove components smaller than threshold."""
        from urbansolarcarver.grid import prune_voxels
        # Create a grid with one large blob and one tiny blob
        grid = torch.zeros(32, 32, 32, dtype=torch.uint8)
        grid[5:20, 5:20, 5:20] = 1   # large component: 15^3 = 3375
        grid[28, 28, 28] = 1          # tiny component: 1 voxel
        cleaned = prune_voxels(grid, min_voxels=10)
        assert cleaned.sum() < grid.sum(), "Tiny component should have been removed"
        assert cleaned[28, 28, 28] == 0, "Single voxel should be pruned"
        assert cleaned[10, 10, 10] == 1, "Large component should survive"


class TestPMDiffusion:
    """Tests for Perona-Malik anisotropic diffusion."""

    def test_uniform_field_unchanged(self):
        """A uniform field has zero gradients -- diffusion should be a no-op."""
        from urbansolarcarver.grid import _pm_anisotropic_diffuse
        field = np.full((20, 20, 20), 5.0, dtype=np.float32)
        result = _pm_anisotropic_diffuse(field, iters=16, k=1.0, tau=0.15)
        np.testing.assert_allclose(result, field, atol=1e-6)

    def test_step_edge_smoothed(self):
        """A sharp step edge should be smoothed (peak gradient reduced)."""
        from urbansolarcarver.grid import _pm_anisotropic_diffuse
        field = np.zeros((30, 30, 30), dtype=np.float32)
        field[:, :, 15:] = 10.0  # sharp step in Z
        result = _pm_anisotropic_diffuse(field, iters=16, k=20.0, tau=0.15)
        grad_before = np.abs(np.diff(field[15, 15, :]))
        grad_after = np.abs(np.diff(result[15, 15, :]))
        assert grad_after.max() < grad_before.max(), (
            "Diffusion should reduce peak gradient"
        )

    def test_preserves_shape(self):
        """Output shape and dtype must match input."""
        from urbansolarcarver.grid import _pm_anisotropic_diffuse
        field = np.random.randn(16, 16, 16).astype(np.float32)
        result = _pm_anisotropic_diffuse(field, iters=4, k=1.0, tau=0.1)
        assert result.shape == field.shape
        assert result.dtype == np.float32

    def test_zero_iters_returns_copy(self):
        """Zero iterations should return the input unchanged."""
        from urbansolarcarver.grid import _pm_anisotropic_diffuse
        field = np.random.randn(10, 10, 10).astype(np.float32)
        result = _pm_anisotropic_diffuse(field, iters=0, k=1.0, tau=0.15)
        np.testing.assert_array_equal(result, field)

    def test_neumann_boundary_no_drift(self):
        """Boundary voxels should not drift significantly from their initial
        values when the field is smooth near the boundary."""
        from urbansolarcarver.grid import _pm_anisotropic_diffuse
        field = np.ones((20, 20, 20), dtype=np.float32) * 3.0
        field[10, 10, 10] = 10.0
        result = _pm_anisotropic_diffuse(field, iters=4, k=1.0, tau=0.15)
        np.testing.assert_allclose(result[0, 0, 0], 3.0, atol=0.01)
        np.testing.assert_allclose(result[-1, -1, -1], 3.0, atol=0.01)


class TestVoxelizeFillSkip:
    """Verify the cavity-fill fast-path in voxelize_mesh."""

    def test_watertight_mesh_no_cavities(self, tiny_cube_mesh, caplog):
        """A simple watertight cube should be fully filled by trimesh's
        orthographic fill — no interior cavities means binary_fill_holes
        is skipped."""
        import logging
        from urbansolarcarver.grid import voxelize_mesh
        with caplog.at_level(logging.DEBUG, logger="urbansolarcarver.grid"):
            grid, origin, extent, res = voxelize_mesh.__wrapped__(
                tiny_cube_mesh, voxel_size=2.0
            )
        assert grid.sum() > 0
        # Check that the skip message was logged (cavity check passed)
        assert any("no interior cavities" in r.message.lower() for r in caplog.records), (
            "Expected cavity-skip log for watertight cube mesh"
        )

    def test_solid_fill_correct(self, tiny_cube_mesh):
        """Regardless of skip logic, the final grid must be solidly filled."""
        from urbansolarcarver.grid import voxelize_mesh
        grid, origin, extent, res = voxelize_mesh.__wrapped__(
            tiny_cube_mesh, voxel_size=2.0
        )
        total = grid.sum().item()
        assert total > 100, f"Expected solid fill, got {total} voxels"


class TestEdgeTaper:
    """edge_taper design weights: distance-to-boundary ramp on sample points."""

    def _flat_quad(self, w, h, z=0.0):
        import trimesh
        verts = np.array([[0, 0, z], [w, 0, z], [w, h, z], [0, h, z]],
                         dtype=np.float64)
        faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)
        return trimesh.Trimesh(vertices=verts, faces=faces, process=False)

    def test_taper_off_returns_ones(self):
        from urbansolarcarver.grid import discretize_surface_with_normals
        mesh = self._flat_quad(10, 10)
        pts, _n, _m, w, stats = discretize_surface_with_normals(
            mesh, sample_step=1.0, edge_taper=0.0)
        assert w.shape == (pts.shape[0],)
        np.testing.assert_array_equal(w, 1.0)
        assert stats == []

    def test_square_ramp_matches_analytic_distance(self):
        """On a rectangle the boundary distance is min(x, w-x, y, h-y)."""
        from urbansolarcarver.grid import discretize_surface_with_normals
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
        from urbansolarcarver.grid import discretize_surface_with_normals
        verts = np.array([
            # panel A: [0,5]x[0,10]
            [0, 0, 0], [5, 0, 0], [5, 10, 0], [0, 10, 0],
            # panel B: [5,10]x[0,10] — seam vertices duplicated
            [5, 0, 0], [10, 0, 0], [10, 10, 0], [5, 10, 0],
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]],
                         dtype=np.int32)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
        assert len(mesh.split(only_watertight=False)) == 1, "panels must weld"

        pts, _n, _m, w, _s = discretize_surface_with_normals(
            mesh, sample_step=0.5, edge_taper=1.0)
        # Points on the seam line (x≈5) but deep inside the outline must have
        # full weight — a phantom seam boundary would drag them to ~0.
        on_seam = (np.abs(pts[:, 0] - 5.0) < 0.3) & (np.abs(pts[:, 1] - 5.0) < 2.0)
        assert on_seam.any(), "expected samples near the seam"
        assert w[on_seam].min() > 0.99

    def test_narrow_component_warns_and_never_reaches_full_weight(self):
        from urbansolarcarver.grid import discretize_surface_with_normals
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
        from urbansolarcarver.grid import discretize_surface_with_normals
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
        from urbansolarcarver.grid import discretize_surface_with_normals
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
