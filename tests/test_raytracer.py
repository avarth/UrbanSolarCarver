"""Tests for raytracer module: fixed-step marcher, DDA, session cache, auto_batch."""
import math
import pytest
import numpy as np
import torch

from urbansolarcarver.raytracer import (
    _trace_fixed_step,
    trace_multi_hit_grid,
    generate_sky_patch_rays,
    generate_sun_rays,
    auto_batch_size,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _axis_aligned_ray(origin, direction, resolution=10, voxel_size=1.0):
    """Create tensors for a single ray through a known grid."""
    scale = resolution * voxel_size
    min_corner = (0.0, 0.0, 0.0)
    origins = torch.tensor([origin], dtype=torch.float32)
    dirs = torch.tensor([direction], dtype=torch.float32)
    patch_ids = torch.tensor([0], dtype=torch.long)
    ray_length = scale * 2  # enough to traverse entire grid
    return min_corner, scale, resolution, origins, dirs, patch_ids, voxel_size, ray_length


# ---------------------------------------------------------------------------
# Fixed-step marcher
# ---------------------------------------------------------------------------

class TestFixedStepMarcher:
    def test_axis_aligned_ray_hits_all_cells(self):
        """A +X ray through a 10-cell grid should hit all 10 cells along X."""
        args = _axis_aligned_ray(
            origin=(-0.5, 0.5, 0.5),
            direction=(1.0, 0.0, 0.0),
            resolution=10, voxel_size=1.0,
        )
        ray_ids, patch_ids, voxel_indices = _trace_fixed_step(*args)
        # Should hit cells (0..9, 0, 0)
        hit_x = set(voxel_indices[:, 0].tolist())
        assert hit_x == set(range(10)), f"Expected cells 0-9 on X, got {hit_x}"

    def test_diagonal_ray_reaches_far_corner(self):
        """A diagonal ray should reach the far corner of the grid.

        With voxel_size=1.0 and resolution=10, the grid diagonal is
        10*sqrt(3) ~ 17.32. int(17.32/1.0) = 17 steps — enough with
        the 0.5-offset to still reach (9,9,9). The truncation bug (A1)
        manifests at specific grid sizes where the last partial step
        would land in a new voxel.
        """
        resolution = 10
        voxel_size = 1.0
        scale = resolution * voxel_size
        direction = np.array([1.0, 1.0, 1.0])
        direction = direction / np.linalg.norm(direction)
        ray_length = scale * math.sqrt(3) + voxel_size

        min_corner = (0.0, 0.0, 0.0)
        origins = torch.tensor([[-0.01, -0.01, -0.01]], dtype=torch.float32)
        dirs = torch.tensor([direction.tolist()], dtype=torch.float32)
        patch_ids = torch.tensor([0], dtype=torch.long)

        ray_ids, p_ids, voxel_indices = _trace_fixed_step(
            min_corner, scale, resolution,
            origins, dirs, patch_ids,
            voxel_size, ray_length,
        )
        hit_set = set(map(tuple, voxel_indices.tolist()))
        assert (9, 9, 9) in hit_set, f"Far corner (9,9,9) not reached. Max: {voxel_indices.max(dim=0).values.tolist()}"

    def test_truncation_bug_specific_case(self):
        """Demonstrate the fixed-step truncation: int() vs ceil().

        With ray_length=7.5 and voxel_size=1.0, int(7.5)=7 steps.
        Sample positions at (0.5, 1.5, ..., 6.5)*voxel_size → cells 0-6.
        Cell 7 (at 7.5) is missed. With ceil(7.5)=8 steps, cell 7 is reached.
        """
        num_steps_int = int(7.5 / 1.0)    # 7
        num_steps_ceil = math.ceil(7.5 / 1.0)  # 8
        assert num_steps_int == 7
        assert num_steps_ceil == 8
        # The fixed-step marcher uses int(), losing the last cell
        # This is a mathematical demonstration of the truncation

    def test_no_duplicate_ray_voxel_pairs(self):
        """Each (ray, voxel) pair must appear at most once — duplicates would
        inflate scores and violation counts downstream."""
        # A nearly axis-aligned ray samples some voxels twice per step
        # without dedup (discrete stepping overshoot).
        origins = torch.tensor([[-0.5, 2.5, 2.5]], dtype=torch.float32)
        dirs = torch.nn.functional.normalize(
            torch.tensor([[1.0, 0.001, 0.001]]), dim=1)
        pids = torch.tensor([0], dtype=torch.long)
        rid, _, vox = _trace_fixed_step(
            (0.0, 0.0, 0.0), 10.0, 10, origins, dirs, pids, 1.0, 30.0,
        )
        pairs = list(zip(rid.tolist(), map(tuple, vox.tolist())))
        assert len(pairs) == len(set(pairs)), "duplicate (ray, voxel) hits"

    def test_zero_ray_length_returns_empty(self):
        """ray_length=0 should produce no hits."""
        min_corner = (0.0, 0.0, 0.0)
        origins = torch.tensor([[0.5, 0.5, 0.5]], dtype=torch.float32)
        dirs = torch.tensor([[1.0, 0.0, 0.0]], dtype=torch.float32)
        patch_ids = torch.tensor([0], dtype=torch.long)
        ray_ids, p_ids, voxel_indices = _trace_fixed_step(
            min_corner, 10.0, 10, origins, dirs, patch_ids, 1.0, 0.0,
        )
        assert ray_ids.shape[0] == 0

    def test_ray_outside_grid_returns_empty(self):
        """A ray that never enters the grid should produce no hits."""
        min_corner = (0.0, 0.0, 0.0)
        origins = torch.tensor([[20.0, 20.0, 20.0]], dtype=torch.float32)
        dirs = torch.tensor([[1.0, 0.0, 0.0]], dtype=torch.float32)
        patch_ids = torch.tensor([0], dtype=torch.long)
        ray_ids, p_ids, voxel_indices = _trace_fixed_step(
            min_corner, 10.0, 10, origins, dirs, patch_ids, 1.0, 20.0,
        )
        # Ray starts at (20,20,20) going +X, grid is [0,10]^3 — should miss
        assert ray_ids.shape[0] == 0


# ---------------------------------------------------------------------------
# trace_multi_hit_grid dispatch
# ---------------------------------------------------------------------------

class TestTraceMultiHitGrid:
    def test_empty_rays_returns_empty(self):
        """Zero rays should return empty tensors."""
        empty_origins = torch.empty((0, 3), dtype=torch.float32)
        empty_dirs = torch.empty((0, 3), dtype=torch.float32)
        empty_ids = torch.empty((0,), dtype=torch.long)
        ray_ids, p_ids, voxels = trace_multi_hit_grid(
            (0, 0, 0), 10.0, 10,
            empty_origins, empty_dirs, empty_ids,
            1.0, 20.0,
        )
        assert ray_ids.shape[0] == 0
        assert voxels.shape == (0, 3)

    def test_cpu_path_produces_hits(self):
        """On CPU, trace_multi_hit_grid should produce valid hits."""
        args = _axis_aligned_ray(
            origin=(-0.5, 0.5, 0.5),
            direction=(1.0, 0.0, 0.0),
            resolution=5, voxel_size=1.0,
        )
        ray_ids, p_ids, voxels = trace_multi_hit_grid(*args)
        assert ray_ids.shape[0] > 0
        # All voxel indices should be in [0, 5)
        assert (voxels >= 0).all()
        assert (voxels < 5).all()


# ---------------------------------------------------------------------------
# Ray generation
# ---------------------------------------------------------------------------

class TestGenerateSkyPatchRays:
    def test_face_culling(self):
        """Rays should only be generated for patches above the surface (dot > 0)."""
        pts = np.array([[0, 0, 0]], dtype=np.float32)
        norms = np.array([[0, 0, 1]], dtype=np.float32)  # facing +Z
        # Two patches: one above (+Z), one below (-Z)
        patch_dirs = torch.tensor([[0, 0, 1], [0, 0, -1]], dtype=torch.float32)
        origins, dirs, ids, normals, point_idx = generate_sky_patch_rays(pts, norms, patch_dirs, torch.device("cpu"))
        # Only the +Z patch should produce a ray
        assert origins.shape[0] == 1
        assert ids[0].item() == 0  # first patch (+Z)
        assert point_idx[0].item() == 0  # from point 0

    def test_multiple_points_and_patches(self):
        """Multiple points x multiple patches should produce correct ray count."""
        pts = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32)
        norms = np.array([[0, 0, 1], [0, 0, 1]], dtype=np.float32)
        # 3 patches, all above hemisphere
        patch_dirs = torch.tensor([
            [0.0, 0.0, 1.0],
            [0.5, 0.0, 0.866],
            [0.0, 0.5, 0.866],
        ], dtype=torch.float32)
        origins, dirs, ids, normals, point_idx = generate_sky_patch_rays(pts, norms, patch_dirs, torch.device("cpu"))
        # 2 points x 3 patches = 6 rays (all patches are above the surface)
        assert origins.shape[0] == 6
        # point_idx should map each ray back to its source point (0 or 1)
        assert set(point_idx.tolist()) == {0, 1}


class TestGenerateSunRays:
    def test_back_facing_sun_filtered(self):
        """Sun vectors below the surface should not produce rays."""
        pts = np.array([[0, 0, 0]], dtype=np.float32)
        norms = np.array([[0, 0, 1]], dtype=np.float32)
        # Sun above and sun below
        sun_dirs = np.array([[0, 0, 1], [0, 0, -1]], dtype=np.float32)
        origins, dirs = generate_sun_rays(pts, norms, sun_dirs, torch.device("cpu"))
        assert origins.shape[0] == 1


# ---------------------------------------------------------------------------
# Fused count kernel (binary carving modes)
# ---------------------------------------------------------------------------

class TestFusedCountKernel:
    @pytest.mark.skipif(
        not __import__("urbansolarcarver.raytracer", fromlist=["dda_backend_available"])
        .dda_backend_available(torch.device("cpu")),
        reason="Warp CPU unavailable",
    )
    def test_matches_buffered_trace_counts(self):
        """The fused count kernel must produce exactly the same per-voxel
        hit counts as accumulating the buffered DDA trace output."""
        from urbansolarcarver.raytracer import trace_and_count_dda

        res, scale, voxel, ray_len = 20, 20.0, 1.0, 60.0
        rng = np.random.default_rng(3)
        n = 2000
        origins = torch.from_numpy(rng.uniform(0, scale, (n, 3)).astype(np.float32))
        d = rng.normal(size=(n, 3)).astype(np.float32)
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        dirs = torch.from_numpy(d)
        pids = torch.zeros(n, dtype=torch.long)

        counts_fused = torch.zeros(res**3, dtype=torch.int32)
        trace_and_count_dda((0.0, 0.0, 0.0), scale, res, origins, dirs,
                            counts_fused, ray_len)

        _, _, vox = trace_multi_hit_grid((0.0, 0.0, 0.0), scale, res,
                                         origins, dirs, pids, voxel, ray_len)
        counts_ref = torch.zeros(res**3, dtype=torch.int32)
        flat = vox[:, 0] * res * res + vox[:, 1] * res + vox[:, 2]
        counts_ref.index_add_(0, flat, torch.ones_like(flat, dtype=torch.int32))

        torch.testing.assert_close(counts_fused, counts_ref)


# ---------------------------------------------------------------------------
# Point-weighted fused score kernel (edge_taper)
# ---------------------------------------------------------------------------

class TestFusedScorePointWeighted:
    @pytest.mark.skipif(
        not __import__("urbansolarcarver.raytracer", fromlist=["dda_backend_available"])
        .dda_backend_available(torch.device("cpu")),
        reason="Warp CPU unavailable",
    )
    def test_point_weights_scale_scores(self):
        """Per-ray contribution must be patch_weight × point_weight."""
        from urbansolarcarver.raytracer import trace_and_score_dda

        res, scale, ray_len = 8, 8.0, 20.0
        # Two vertical rays in different columns, same patch, different points.
        origins = torch.tensor([[2.5, 2.5, 0.5], [5.5, 5.5, 0.5]],
                               dtype=torch.float32)
        dirs = torch.tensor([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]],
                            dtype=torch.float32)
        patch_ids = torch.zeros(2, dtype=torch.long)
        patch_weights = torch.tensor([2.0], dtype=torch.float32)

        baseline = torch.zeros(res**3, dtype=torch.float32)
        trace_and_score_dda((0.0, 0.0, 0.0), scale, res, origins, dirs,
                            patch_ids, patch_weights, baseline, ray_len)

        weighted = torch.zeros(res**3, dtype=torch.float32)
        trace_and_score_dda((0.0, 0.0, 0.0), scale, res, origins, dirs,
                            patch_ids, patch_weights, weighted, ray_len,
                            point_ids=torch.tensor([0, 1], dtype=torch.int32),
                            point_weights=torch.tensor([1.0, 0.25],
                                                       dtype=torch.float32))

        b = baseline.reshape(res, res, res)
        w = weighted.reshape(res, res, res)
        # Column of point 0 (full weight) identical; column of point 1 scaled.
        torch.testing.assert_close(w[2, 2, :], b[2, 2, :])
        torch.testing.assert_close(w[5, 5, :], b[5, 5, :] * 0.25)

    def test_point_args_must_come_together(self):
        from urbansolarcarver.raytracer import (
            trace_and_score_dda, dda_backend_available,
        )
        if not dda_backend_available(torch.device("cpu")):
            pytest.skip("Warp CPU unavailable")
        with pytest.raises(ValueError, match="together"):
            trace_and_score_dda(
                (0.0, 0.0, 0.0), 8.0, 8,
                torch.zeros((1, 3)), torch.tensor([[0.0, 0.0, 1.0]]),
                torch.zeros(1, dtype=torch.long),
                torch.ones(1), torch.zeros(512), 10.0,
                point_ids=torch.zeros(1, dtype=torch.int32),
            )


# ---------------------------------------------------------------------------
# Kernel warmup
# ---------------------------------------------------------------------------

class TestWarmupKernels:
    def test_warmup_matches_backend_availability(self):
        """warmup_kernels succeeds exactly when the Warp backend exists on
        the device, and must never raise."""
        from urbansolarcarver.raytracer import warmup_kernels, dda_backend_available
        expected = dda_backend_available(torch.device("cpu"))
        assert warmup_kernels("cpu") == expected

    def test_warmup_auto_device(self):
        from urbansolarcarver.raytracer import warmup_kernels
        assert isinstance(warmup_kernels(), bool)  # must not raise


# ---------------------------------------------------------------------------
# Auto batch size
# ---------------------------------------------------------------------------

class TestAutoBatchSize:
    def test_cpu_returns_fallback(self):
        result = auto_batch_size(100, torch.device("cpu"))
        assert result == 300_000

    def test_returns_positive_integer(self):
        result = auto_batch_size(100, torch.device("cpu"), fallback=50_000)
        assert isinstance(result, int)
        assert result > 0


class TestFixedStepChunking:
    """Verify that internal chunking in _trace_fixed_step produces
    identical results regardless of chunk size."""

    def test_chunked_matches_unchunked(self):
        """A batch of rays should produce the same hits whether processed
        in one chunk or many small chunks."""
        import urbansolarcarver.raytracer as rt

        resolution = 20
        voxel_size = 1.0
        scale = resolution * voxel_size
        min_corner = (0.0, 0.0, 0.0)
        ray_length = scale * 1.5

        # 500 rays in random directions from one side of the grid
        rng = np.random.RandomState(42)
        n_rays = 500
        origins = torch.zeros(n_rays, 3, dtype=torch.float32)
        origins[:, 0] = -0.5  # just outside grid on -X face
        origins[:, 1] = torch.from_numpy(rng.uniform(0.5, scale - 0.5, n_rays).astype(np.float32))
        origins[:, 2] = torch.from_numpy(rng.uniform(0.5, scale - 0.5, n_rays).astype(np.float32))
        dirs = torch.zeros(n_rays, 3, dtype=torch.float32)
        dirs[:, 0] = 1.0  # +X direction
        patch_ids = torch.arange(n_rays, dtype=torch.long) % 145

        # Run with a very large budget (no chunking)
        saved = getattr(rt, '_FIXED_STEP_BUDGET_BYTES', None)
        rt._FIXED_STEP_BUDGET_BYTES = 10 * 1024**3  # 10 GB -- effectively no chunking
        r1_ray, r1_patch, r1_vox = rt._trace_fixed_step(
            min_corner, scale, resolution,
            origins, dirs, patch_ids,
            voxel_size, ray_length,
        )
        # Run with a tiny budget (forces many chunks)
        rt._FIXED_STEP_BUDGET_BYTES = 1024  # 1 KB -- extreme chunking
        r2_ray, r2_patch, r2_vox = rt._trace_fixed_step(
            min_corner, scale, resolution,
            origins, dirs, patch_ids,
            voxel_size, ray_length,
        )
        # Restore
        if saved is not None:
            rt._FIXED_STEP_BUDGET_BYTES = saved
        elif hasattr(rt, '_FIXED_STEP_BUDGET_BYTES'):
            del rt._FIXED_STEP_BUDGET_BYTES

        # Results must be identical (same rays, same order)
        assert r1_ray.shape == r2_ray.shape, (
            f"Hit count mismatch: {r1_ray.shape[0]} vs {r2_ray.shape[0]}"
        )
        torch.testing.assert_close(r1_ray, r2_ray)
        torch.testing.assert_close(r1_patch, r2_patch)
        torch.testing.assert_close(r1_vox, r2_vox)

    def test_single_ray_still_works(self):
        """Edge case: a single ray should work regardless of chunk size."""
        import urbansolarcarver.raytracer as rt
        args = _axis_aligned_ray(
            origin=(-0.5, 0.5, 0.5),
            direction=(1.0, 0.0, 0.0),
            resolution=10, voxel_size=1.0,
        )
        saved = getattr(rt, '_FIXED_STEP_BUDGET_BYTES', None)
        rt._FIXED_STEP_BUDGET_BYTES = 1  # absurdly small
        ray_ids, patch_ids, voxel_indices = rt._trace_fixed_step(*args)
        if saved is not None:
            rt._FIXED_STEP_BUDGET_BYTES = saved
        hit_x = set(voxel_indices[:, 0].tolist())
        assert hit_x == set(range(10))
