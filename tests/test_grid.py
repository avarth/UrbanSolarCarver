"""Invariant tests for grid operations: voxelization, meshing, surface sampling,
edge taper and smoothing."""
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
        """A single-face mesh has zero spread, so it is always planar."""
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
        # Corners have slightly larger gaps because edge points are offset
        # inward; allow up to 1.2 * step.
        assert max_gap < step * 1.2, (
            f"Largest gap from boundary to nearest sample: {max_gap:.3f} "
            f"(should be < {step * 1.2:.3f})"
        )

    def test_no_duplicate_near_grid(self):
        """Edge points should not be too close to interior grid points."""
        from urbansolarcarver.grid import sample_planar_surface, _sample_boundary_edges
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
        from urbansolarcarver.grid import sample_planar_surface
        mesh = self._make_flat_quad(1.0, 1.0)
        pts, norms, qv, qf, _w = sample_planar_surface(mesh, sample_step=0.3)
        assert len(qf) == len(pts), (
            f"Quad faces ({len(qf)}) != points ({len(pts)})"
        )

    def test_thin_rectangle_gets_edge_points(self):
        """A rectangle thinner than sample_step should still get edge points."""
        from urbansolarcarver.grid import sample_planar_surface
        # Width 0.1, height 3.0, step 0.5: too thin for interior grid points
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
        return grid.cpu().numpy().astype(bool), origin, res

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
    @pytest.mark.parametrize(
        "device",
        ["cpu", pytest.param("cuda", marks=pytest.mark.skipif(
            not torch.cuda.is_available(), reason="CUDA unavailable"))],
    )
    def test_differences_confined_to_surface_shell(self, shape, device):
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
        occ = voxelize_solid_warp(mesh.vertices, mesh.faces, origin, 0.5, res, torch.device(device))

        st = np.ones((3, 3, 3), dtype=bool)
        assert not (occ & ~binary_dilation(ref, structure=st)).any()
        assert not (ref & ~binary_dilation(occ, structure=st)).any()
        # And the interiors overwhelmingly agree
        iou = (ref & occ).sum() / max((ref | occ).sum(), 1)
        assert iou > 0.9


def test_warp_voxelizer_failure_raises_instead_of_switching_to_trimesh(monkeypatch):
    """A Warp run that fails (here a simulated CUDA out-of-memory) must raise:
    trimesh classifies boundary voxels differently, and a long-lived session
    would cache that other grid for the geometry.  The trimesh path is only
    for when Warp cannot run on the device at all."""
    import trimesh
    import urbansolarcarver.raytracer as rt
    from urbansolarcarver.grid import voxelize_mesh
    from urbansolarcarver.session import CarverSession

    def failing_warp_voxelizer(*args, **kwargs):
        raise RuntimeError("simulated CUDA out of memory")

    monkeypatch.setattr(rt, "voxelize_solid_warp", failing_warp_voxelizer)
    cube = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    with CarverSession("cpu") as session:
        with pytest.raises(RuntimeError, match="simulated CUDA out of memory"):
            voxelize_mesh(cube, voxel_size=1.0, margin_frac=0.1,
                          device=torch.device("cpu"), session=session)


class TestVoxelGridPlan:
    """The grid size is planned and checked against the budget from the mesh
    bounds alone, before anything is allocated."""

    def test_plan_matches_the_voxelized_grid(self):
        import trimesh
        from urbansolarcarver.grid import voxelize_mesh
        from urbansolarcarver.grid_planning import plan_voxel_grid
        slab = trimesh.creation.box(extents=(40.0, 10.0, 5.0))
        slab.apply_translation([3.0, -7.0, 2.0])
        plan = plan_voxel_grid(slab.bounds, voxel_size=2.0, margin_frac=0.05)
        _, origin, extent, resolution = voxelize_mesh.__wrapped__(
            slab, voxel_size=2.0, margin_frac=0.05, device=torch.device("cpu"))
        assert plan.resolution == resolution
        assert plan.total_voxels == resolution ** 3
        assert plan.extent == pytest.approx(extent)
        np.testing.assert_allclose(plan.origin, origin)

    def test_budget_check_accepts_a_small_grid_and_rejects_a_large_one(self):
        from urbansolarcarver.errors import ConfigError
        from urbansolarcarver.grid_planning import (
            MAX_GRID_VOXELS, check_voxel_grid_budget, plan_voxel_grid,
        )
        bounds = np.array([[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]])
        check_voxel_grid_budget(plan_voxel_grid(bounds, voxel_size=1.0, margin_frac=0.0))
        side = int(np.ceil(MAX_GRID_VOXELS ** (1 / 3))) + 1
        too_fine = 10.0 / side
        with pytest.raises(ConfigError) as caught:
            check_voxel_grid_budget(plan_voxel_grid(bounds, voxel_size=too_fine, margin_frac=0.0))
        assert caught.value.errors[0].field == "voxel_size"

    def test_voxelize_mesh_rejects_an_oversized_grid_before_allocating(self, monkeypatch):
        import trimesh
        import urbansolarcarver.raytracer as rt
        from urbansolarcarver.grid import voxelize_mesh
        from urbansolarcarver.grid_planning import MAX_GRID_VOXELS

        def voxelizer_must_not_run(*args, **kwargs):
            pytest.fail("the voxelizer ran (and allocated) for a grid over the budget")

        monkeypatch.setattr(rt, "voxelize_solid_warp", voxelizer_must_not_run)
        cube = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
        side = int(np.ceil(MAX_GRID_VOXELS ** (1 / 3))) + 1
        with pytest.raises(ValueError, match="voxel_size"):
            voxelize_mesh.__wrapped__(cube, voxel_size=10.0 / side, margin_frac=0.0,
                                      device=torch.device("cpu"))


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
        assert (frac > 0.05).any(), "all vertices on lattice; SDF was binarized"

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
        """A uniform field has zero gradients, so diffusion should be a no-op."""
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
        orthographic fill; with no interior cavities, binary_fill_holes
        is skipped and a debug message says so."""
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


# ---------------------------------------------------------------------------
# Degenerate input and fallback paths: warnings, empty results, EPW cache
# ---------------------------------------------------------------------------

def _sampling_config():
    from urbansolarcarver.load_config import user_config
    return user_config(max_volume_path="x", test_surface_path="x", out_dir="x",
                       mode="tilted_plane", tilted_plane_angle_deg=45,
                       grid_step=1.0, voxel_size=1.0)


def test_zero_area_face_does_not_drop_panel_and_bent_panel_warns():
    import trimesh
    from urbansolarcarver.grid import sample_surface
    rect = trimesh.Trimesh([[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3], [4, 0, 3]],
                           [[0, 1, 2], [0, 2, 3], [1, 2, 4]], process=False)  # last face: zero area
    bent = trimesh.Trimesh([[10, 0, 0], [14, 0, 0], [14, 1, 3], [10, 0, 3]],
                           [[0, 1, 2], [0, 2, 3]], process=False)
    with pytest.warns(UserWarning, match="1 non-planar"):
        pts, *_ = sample_surface(trimesh.util.concatenate([rect, bent]), _sampling_config())
    assert len(pts) > 0 and pts[:, 0].max() <= 4.0  # the rectangle is sampled, the bent panel is not


def test_taubin_polish_preserves_volume():
    from urbansolarcarver.grid import mesh_from_voxels_smoothed, polish_mesh_taubin
    g = np.zeros((16, 16, 16), bool)
    g[3:13, 3:13, 3:13] = True
    base = mesh_from_voxels_smoothed(torch.from_numpy(g), np.zeros(3), 1.0)
    polished = polish_mesh_taubin(base.copy(), iters=6)
    assert polished.volume == pytest.approx(base.volume, rel=0.01)


def test_smoothed_mesh_of_empty_grid_is_empty():
    from urbansolarcarver.grid import mesh_from_voxels_smoothed
    mesh = mesh_from_voxels_smoothed(torch.zeros((8, 8, 8), dtype=torch.bool), np.zeros(3), 1.0)
    assert len(mesh.faces) == 0


def test_cleanup_keeps_largest_part_when_none_pass():
    import trimesh
    from urbansolarcarver.grid import cleanup_mesh
    a = trimesh.creation.box((1, 1, 1))
    b = trimesh.creation.icosphere(subdivisions=2)
    b.apply_translation((5, 0, 0))
    with pytest.warns(UserWarning, match="keeping only the largest"):
        out = cleanup_mesh(trimesh.util.concatenate([a, b]), min_face_count=10**6, light=True)
    assert len(out.faces) == len(b.faces)


def test_epw_cache_rereads_a_replaced_file(tmp_path):
    import os
    import shutil
    from _epw import resolve_epw
    from urbansolarcarver.sun import _load_epw
    src = resolve_epw()
    if not src:
        pytest.skip("No EPW available")
    path = tmp_path / "w.epw"
    shutil.copy(src, path)
    first = _load_epw(str(path))
    text = path.read_text(encoding="utf-8", errors="replace").splitlines(True)
    text[0] = text[0].replace(text[0].split(",")[1], "Renamed City", 1)
    path.write_text("".join(text), encoding="utf-8")
    os.utime(path, ns=(first_mtime := os.stat(path).st_mtime_ns, first_mtime + 10**9))
    assert _load_epw(str(path)).location.city == "Renamed City"


def test_volume_matched_threshold_keeps_exactly_target_cells():
    from urbansolarcarver.grid import _volume_matched_threshold
    sdf = np.array([[-1.0, 0.5, 2.0]], dtype=np.float32)
    kept = [int((sdf >= _volume_matched_threshold(sdf, t)).sum()) for t in range(4)]
    assert kept == [0, 1, 2, 3]
