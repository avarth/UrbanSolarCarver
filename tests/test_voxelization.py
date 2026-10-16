"""Voxelization of the maximum volume (voxelization.py): invariants, the Warp
parity voxelizer, the grid budget and cavity filling."""
import pytest
import numpy as np
import torch


class TestVoxelizeInvariants:
    def test_voxelize_produces_filled_grid(self, tiny_cube_mesh):
        from urbansolarcarver.voxelization import voxelize_mesh
        grid, origin, extent, res = voxelize_mesh(tiny_cube_mesh, voxel_size=2.0)
        assert grid.sum() > 0, "Voxelization produced empty grid"
        assert grid.dtype == torch.uint8

    def test_voxelize_grid_is_cubic(self, tiny_cube_mesh):
        from urbansolarcarver.voxelization import voxelize_mesh
        grid, origin, extent, res = voxelize_mesh(tiny_cube_mesh, voxel_size=2.0)
        d0, d1, d2 = grid.shape
        assert d0 == d1 == d2, f"Grid not cubic: {grid.shape}"


def _warp_cpu_available():
    from urbansolarcarver.warp_kernels import dda_backend_available
    return dda_backend_available(torch.device("cpu"))


class TestWarpVoxelizer:
    """Parity ray-casting voxelizer vs the trimesh rasterize-and-fill path."""

    def _trimesh_reference(self, mesh, voxel_size, margin_frac):
        """Run voxelize_mesh with the Warp path disabled."""
        import urbansolarcarver.voxelization as voxelization
        from urbansolarcarver.voxelization import voxelize_mesh
        saved = voxelization.voxelize_solid_warp
        voxelization.voxelize_solid_warp = lambda *a, **k: None
        try:
            grid, origin, _, res = voxelize_mesh.__wrapped__(
                mesh, voxel_size=voxel_size, margin_frac=margin_frac
            )
        finally:
            voxelization.voxelize_solid_warp = saved
        return grid.cpu().numpy().astype(bool), origin, res

    @pytest.mark.skipif(not _warp_cpu_available(), reason="Warp CPU unavailable")
    def test_cube_matches_center_truth_exactly(self):
        """On a boundary-aligned cube, the parity voxelizer must reproduce
        the center-inside ground truth voxel for voxel."""
        import trimesh
        from urbansolarcarver.voxelization import voxelize_solid_warp
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
        from urbansolarcarver.voxelization import voxelize_solid_warp

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
    import urbansolarcarver.voxelization as voxelization
    from urbansolarcarver.voxelization import voxelize_mesh
    from urbansolarcarver.session import CarverSession

    def failing_warp_voxelizer(*args, **kwargs):
        raise RuntimeError("simulated CUDA out of memory")

    monkeypatch.setattr(voxelization, "voxelize_solid_warp", failing_warp_voxelizer)
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
        from urbansolarcarver.voxelization import voxelize_mesh
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
        import urbansolarcarver.voxelization as voxelization
        from urbansolarcarver.voxelization import voxelize_mesh
        from urbansolarcarver.grid_planning import MAX_GRID_VOXELS

        def voxelizer_must_not_run(*args, **kwargs):
            pytest.fail("the voxelizer ran (and allocated) for a grid over the budget")

        monkeypatch.setattr(voxelization, "voxelize_solid_warp", voxelizer_must_not_run)
        cube = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
        side = int(np.ceil(MAX_GRID_VOXELS ** (1 / 3))) + 1
        with pytest.raises(ValueError, match="voxel_size"):
            voxelize_mesh.__wrapped__(cube, voxel_size=10.0 / side, margin_frac=0.0,
                                      device=torch.device("cpu"))


class TestVoxelizeFillSkip:
    """Verify the cavity-fill fast-path in voxelize_mesh."""

    def test_watertight_mesh_no_cavities(self, tiny_cube_mesh, caplog):
        """A simple watertight cube should be fully filled by trimesh's
        orthographic fill; with no interior cavities, binary_fill_holes
        is skipped and a debug message says so."""
        import logging
        from urbansolarcarver.voxelization import voxelize_mesh
        with caplog.at_level(logging.DEBUG, logger="urbansolarcarver.voxelization"):
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
        from urbansolarcarver.voxelization import voxelize_mesh
        grid, origin, extent, res = voxelize_mesh.__wrapped__(
            tiny_cube_mesh, voxel_size=2.0
        )
        total = grid.sum().item()
        assert total > 100, f"Expected solid fill, got {total} voxels"
