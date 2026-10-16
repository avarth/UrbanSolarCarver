"""Meshing of the carved grid (meshing.py): cubic and smoothed paths, pruning,
diffusion, Taubin polish and cleanup."""
import pytest
import numpy as np
import torch


class TestMeshFromVoxels:
    def test_cubic_mesh_has_axis_aligned_normals(self, tiny_cube_mesh):
        """Cubic meshing should produce only axis-aligned face normals."""
        from urbansolarcarver.voxelization import voxelize_mesh
        from urbansolarcarver.meshing import mesh_from_voxels
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
        from urbansolarcarver.voxelization import voxelize_mesh
        from urbansolarcarver.meshing import mesh_from_voxels
        grid, origin, extent, res = voxelize_mesh(tiny_cube_mesh, voxel_size=2.0)
        mesh = mesh_from_voxels(grid, origin, voxel_size=2.0)
        if len(mesh.vertices) == 0:
            pytest.skip("No vertices produced")
        orig_min, orig_max = tiny_cube_mesh.bounds
        margin = 2.0  # one voxel margin
        assert np.all(mesh.bounds[0] >= orig_min - margin)
        assert np.all(mesh.bounds[1] <= orig_max + margin)


class TestSmoothedMeshPath:
    """Tests for mesh_from_voxels_smoothed (SDF + marching cubes)."""

    def _cube_voxels(self):
        vox = torch.zeros((24, 24, 24), dtype=torch.uint8)
        vox[4:20, 4:20, 4:20] = 1  # 16^3 cube, volume 4096
        return vox

    def test_watertight_positive_volume(self):
        from urbansolarcarver.meshing import mesh_from_voxels_smoothed
        mesh = mesh_from_voxels_smoothed(self._cube_voxels(), np.zeros(3), 1.0)
        assert len(mesh.faces) > 0
        assert mesh.is_watertight
        assert mesh.volume > 0, "faces must be wound outward"

    def test_volume_matched(self):
        """Volume-matched iso keeps the mesh volume close to the voxel count."""
        from urbansolarcarver.meshing import mesh_from_voxels_smoothed
        mesh = mesh_from_voxels_smoothed(self._cube_voxels(), np.zeros(3), 1.0)
        assert 0.85 * 4096 < mesh.volume < 1.15 * 4096

    def test_surface_actually_smoothed(self):
        """Marching cubes must run on the continuous SDF: vertices should
        interpolate between voxel centers, not sit on the binary lattice."""
        from urbansolarcarver.meshing import mesh_from_voxels_smoothed
        mesh = mesh_from_voxels_smoothed(self._cube_voxels(), np.zeros(3), 1.0)
        frac = np.abs(mesh.vertices - np.round(mesh.vertices))
        assert (frac > 0.05).any(), "all vertices on lattice; SDF was binarized"

    def test_world_alignment(self):
        """Voxel [4:20) at voxel_size=1 spans world [4, 20] (+/- smoothing)."""
        from urbansolarcarver.meshing import mesh_from_voxels_smoothed
        origin = np.array([100.0, 200.0, 300.0])
        mesh = mesh_from_voxels_smoothed(self._cube_voxels(), origin, 1.0)
        lo, hi = mesh.bounds - origin
        assert np.all(lo > 2.5) and np.all(hi < 21.5), f"bounds off: {lo}..{hi}"

    def test_finalize_mesh_smooth_path(self):
        """The full smoothed finalize path (prune → SDF → MC → cleanup →
        Taubin) must deliver a watertight, positive-volume mesh."""
        from urbansolarcarver.meshing import finalize_mesh
        from urbansolarcarver.stage_settings import ExportingSettings
        settings = ExportingSettings(
            final_mesh_format="ply", apply_smoothing=True, min_voxels=10,
            min_face_count=10, smooth_iters=2,
        )
        _, _, final = finalize_mesh(self._cube_voxels(), np.zeros(3), settings, 1.0)
        assert len(final.faces) > 0
        assert final.is_watertight
        assert final.volume > 0.8 * 4096


class TestPruneVoxels:
    def test_prune_removes_small_components(self):
        """Pruning should remove components smaller than threshold."""
        from urbansolarcarver.meshing import prune_voxels
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
        from urbansolarcarver.meshing import _pm_anisotropic_diffuse
        field = np.full((20, 20, 20), 5.0, dtype=np.float32)
        result = _pm_anisotropic_diffuse(field, iters=16, k=1.0, tau=0.15)
        np.testing.assert_allclose(result, field, atol=1e-6)

    def test_step_edge_smoothed(self):
        """A sharp step edge should be smoothed (peak gradient reduced)."""
        from urbansolarcarver.meshing import _pm_anisotropic_diffuse
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
        from urbansolarcarver.meshing import _pm_anisotropic_diffuse
        field = np.random.randn(16, 16, 16).astype(np.float32)
        result = _pm_anisotropic_diffuse(field, iters=4, k=1.0, tau=0.1)
        assert result.shape == field.shape
        assert result.dtype == np.float32

    def test_zero_iters_returns_copy(self):
        """Zero iterations should return the input unchanged."""
        from urbansolarcarver.meshing import _pm_anisotropic_diffuse
        field = np.random.randn(10, 10, 10).astype(np.float32)
        result = _pm_anisotropic_diffuse(field, iters=0, k=1.0, tau=0.15)
        np.testing.assert_array_equal(result, field)

    def test_neumann_boundary_no_drift(self):
        """Boundary voxels should not drift significantly from their initial
        values when the field is smooth near the boundary."""
        from urbansolarcarver.meshing import _pm_anisotropic_diffuse
        field = np.ones((20, 20, 20), dtype=np.float32) * 3.0
        field[10, 10, 10] = 10.0
        result = _pm_anisotropic_diffuse(field, iters=4, k=1.0, tau=0.15)
        np.testing.assert_allclose(result[0, 0, 0], 3.0, atol=0.01)
        np.testing.assert_allclose(result[-1, -1, -1], 3.0, atol=0.01)


def test_taubin_polish_preserves_volume():
    from urbansolarcarver.meshing import mesh_from_voxels_smoothed, polish_mesh_taubin
    g = np.zeros((16, 16, 16), bool)
    g[3:13, 3:13, 3:13] = True
    base = mesh_from_voxels_smoothed(torch.from_numpy(g), np.zeros(3), 1.0)
    polished = polish_mesh_taubin(base.copy(), iters=6)
    assert polished.volume == pytest.approx(base.volume, rel=0.01)


def test_smoothed_mesh_of_empty_grid_is_empty():
    from urbansolarcarver.meshing import mesh_from_voxels_smoothed
    mesh = mesh_from_voxels_smoothed(torch.zeros((8, 8, 8), dtype=torch.bool), np.zeros(3), 1.0)
    assert len(mesh.faces) == 0


def test_cleanup_keeps_largest_part_when_none_pass():
    import trimesh
    from urbansolarcarver.meshing import cleanup_mesh
    a = trimesh.creation.box((1, 1, 1))
    b = trimesh.creation.icosphere(subdivisions=2)
    b.apply_translation((5, 0, 0))
    with pytest.warns(UserWarning, match="keeping only the largest"):
        out = cleanup_mesh(trimesh.util.concatenate([a, b]), min_face_count=10**6, light=True)
    assert len(out.faces) == len(b.faces)


def test_volume_matched_threshold_keeps_exactly_target_cells():
    from urbansolarcarver.meshing import _volume_matched_threshold
    sdf = np.array([[-1.0, 0.5, 2.0]], dtype=np.float32)
    kept = [int((sdf >= _volume_matched_threshold(sdf, t)).sum()) for t in range(4)]
    assert kept == [0, 1, 2, 3]
