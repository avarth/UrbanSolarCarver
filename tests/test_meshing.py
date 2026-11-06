"""Meshing of the carved grid (meshing.py): cubic and smoothed paths, pruning,
diffusion, Taubin polish and cleanup."""
import pytest
import numpy as np
import torch


class TestMeshFromVoxels:
    def test_cubic_mesh_has_axis_aligned_normals(self, tiny_cube_mesh):
        """Cubic meshing of the 10 m cube at 2 m voxels gives a closed box of 125 voxels with only axis-aligned face
        normals."""
        from urbansolarcarver.voxelization import voxelize_mesh
        from urbansolarcarver.meshing import mesh_from_voxels
        grid, origin, extent, res = voxelize_mesh(tiny_cube_mesh, voxel_size=2.0)
        mesh = mesh_from_voxels(grid, origin, voxel_size=2.0)
        # An empty mesh is the regression to catch, so it fails here rather than skipping.
        assert len(mesh.faces) > 0
        assert mesh.is_watertight
        assert mesh.volume == pytest.approx(125 * 2.0 ** 3)       # 5 x 5 x 5 voxels of 8 m3
        # Each face normal should have exactly one non-zero component
        normals = np.abs(mesh.face_normals)
        dominant = normals.max(axis=1)
        assert np.allclose(dominant, 1.0, atol=0.01), "Non-axis-aligned normals in cubic mesh"

    def test_mesh_lies_on_the_bounds_of_the_original(self, tiny_cube_mesh):
        """The 10 m cube is a whole number of 2 m voxels, so the mesh rebuilt from them has the cube's own bounds."""
        from urbansolarcarver.voxelization import voxelize_mesh
        from urbansolarcarver.meshing import mesh_from_voxels
        grid, origin, extent, res = voxelize_mesh(tiny_cube_mesh, voxel_size=2.0)
        mesh = mesh_from_voxels(grid, origin, voxel_size=2.0)
        assert len(mesh.vertices) > 0
        np.testing.assert_allclose(mesh.bounds, tiny_cube_mesh.bounds, atol=1e-6)


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
        """Voxel [4:20) at voxel_size=1 spans world [4, 20]: the field is sampled at voxel centres, half a voxel
        inside each voxel, and the mesh is moved back by that half voxel."""
        from urbansolarcarver.meshing import mesh_from_voxels_smoothed
        origin = np.array([100.0, 200.0, 300.0])
        mesh = mesh_from_voxels_smoothed(self._cube_voxels(), origin, 1.0)
        lo, hi = mesh.bounds - origin
        # Measured 3.994..20.006 (the smoothed edges bulge by under 0.01 m); without the half-voxel offset every
        # bound moves by 0.5.
        np.testing.assert_allclose(lo, 4.0, atol=0.1)
        np.testing.assert_allclose(hi, 20.0, atol=0.1)

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


class TestPruneVoxelsMorph:
    """The light cleanup of the cubic path: small components, then voxels with fewer than two occupied neighbours."""

    @staticmethod
    def _prune(cells, min_voxels, shape=(8, 8, 8)):
        from urbansolarcarver.meshing import prune_voxels_morph
        grid = torch.zeros(shape, dtype=torch.uint8)
        for cell in cells:
            grid[cell] = 1
        cleaned = prune_voxels_morph(grid, min_voxels)
        assert cleaned.dtype == torch.uint8 and cleaned.shape == grid.shape
        assert not (cleaned.bool() & ~grid.bool()).any()      # only removes
        return {tuple(cell) for cell in cleaned.nonzero().tolist()}

    def test_a_component_under_the_size_goes_and_one_at_it_stays(self):
        small = [(0, 0, z) for z in range(3)]
        block = [(x, y, z) for x in (4, 5) for y in (4, 5) for z in (4, 5)]
        assert self._prune(small + block, 8) == set(block)
        assert (0, 0, 1) in self._prune(small + block, 3)

    def test_voxels_touching_at_a_corner_are_one_component(self):
        diagonal = [(1, 1, 1), (2, 2, 2), (3, 3, 3)]
        assert self._prune(diagonal, 3) == {(2, 2, 2)}      # kept as one component; the two ends have one neighbour each

    def test_a_speck_and_the_ends_of_a_rod_go(self):
        rod = [(1, 1, z) for z in range(1, 6)]
        assert self._prune(rod + [(6, 6, 6)], 1) == {(1, 1, z) for z in range(2, 5)}

    def test_the_grid_border_counts_as_empty(self):
        corner_block = [(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
        assert self._prune(corner_block, 1) == set(corner_block)


class TestPMDiffusion:
    """Tests for Perona-Malik anisotropic diffusion."""

    def test_uniform_field_unchanged(self):
        """A uniform field has zero gradients, so diffusion should be a no-op."""
        from urbansolarcarver.meshing import _pm_anisotropic_diffuse
        field = np.full((20, 20, 20), 5.0, dtype=np.float32)
        result = _pm_anisotropic_diffuse(field, iters=16, k=1.0, tau=0.15)
        np.testing.assert_allclose(result, field, atol=1e-6)

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
