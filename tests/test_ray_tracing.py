"""Tests for ray_tracing.py: Warp DDA kernel launches, ray generation and auto
batch size."""
import math
import pytest
import numpy as np
import torch

from urbansolarcarver.ray_tracing import (
    generate_sky_patch_rays,
    generate_sun_rays,
    auto_batch_size,
)


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
        origins, dirs, ids, point_idx = generate_sky_patch_rays(pts, norms, patch_dirs, torch.device("cpu"))
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
        origins, dirs, ids, point_idx = generate_sky_patch_rays(pts, norms, patch_dirs, torch.device("cpu"))
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

def _counts_by_fine_sampling(origins, directions, scale, res, ray_length, step):
    """Per-voxel ray counts from sampling each ray at (k + 0.5) * step, a
    reference for the DDA count kernel that shares no code with it.  A ray
    counts once per voxel; corner clips shorter than *step* are missed.  The
    grid's minimum corner is the origin; float32, like the kernel."""
    distances = (torch.arange(math.ceil(ray_length / step), dtype=torch.float32) + 0.5) * step
    counts = torch.zeros(res ** 3, dtype=torch.int32)
    for start in range(0, origins.shape[0], 20):
        points = (origins[start:start + 20, None, :]
                  + directions[start:start + 20, None, :] * distances[None, :, None])
        voxels = torch.floor(points / scale * res).long()
        inside = ((voxels >= 0) & (voxels < res)).all(dim=2)
        rays = torch.arange(voxels.shape[0])[:, None].expand_as(inside)[inside]
        hit = voxels[inside]
        flat = hit[:, 0] * res * res + hit[:, 1] * res + hit[:, 2]
        once_per_ray = torch.unique(rays * res ** 3 + flat) % res ** 3
        counts.index_add_(0, once_per_ray, torch.ones_like(once_per_ray, dtype=torch.int32))
    return counts


class TestFusedCountKernel:
    @pytest.mark.skipif(
        not __import__("urbansolarcarver.warp_kernels", fromlist=["dda_backend_available"])
        .dda_backend_available(torch.device("cpu")),
        reason="Warp CPU unavailable",
    )
    def test_matches_fine_step_reference(self):
        """The fused count kernel visits every voxel a finely sampled ray
        passes through, and almost nothing else.

        The reference marches each ray in steps of voxel/400, so it can only
        miss corner clips shorter than that; the exact DDA must count at
        least what the reference counts and at most a sliver more.
        """
        from urbansolarcarver.ray_tracing import trace_and_count_dda

        res, scale, voxel, ray_len = 20, 20.0, 1.0, 60.0
        rng = np.random.default_rng(3)
        n = 2000
        origins = torch.from_numpy(rng.uniform(0, scale, (n, 3)).astype(np.float32))
        d = rng.normal(size=(n, 3)).astype(np.float32)
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        dirs = torch.from_numpy(d)

        counts_fused = torch.zeros(res**3, dtype=torch.int32)
        trace_and_count_dda((0.0, 0.0, 0.0), scale, res, origins, dirs,
                            counts_fused, ray_len)

        counts_ref = _counts_by_fine_sampling(origins, dirs, scale, res, ray_len, voxel / 400)

        assert (counts_fused >= counts_ref).all()
        extra = (counts_fused - counts_ref).sum().item()
        # Measured: 33 extra out of ~28k (0.12 %); 6 at voxel/4000.
        assert extra <= 0.005 * counts_ref.sum().item()


# ---------------------------------------------------------------------------
# Point-weighted fused score kernel (edge_taper)
# ---------------------------------------------------------------------------

class TestFusedScorePointWeighted:
    @pytest.mark.skipif(
        not __import__("urbansolarcarver.warp_kernels", fromlist=["dda_backend_available"])
        .dda_backend_available(torch.device("cpu")),
        reason="Warp CPU unavailable",
    )
    def test_point_weights_scale_scores(self):
        """Per-ray contribution must be patch_weight × point_weight."""
        from urbansolarcarver.ray_tracing import trace_and_score_dda

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
        from urbansolarcarver.ray_tracing import trace_and_score_dda
        from urbansolarcarver.warp_kernels import dda_backend_available
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
# Auto batch size
# ---------------------------------------------------------------------------

class TestAutoBatchSize:
    def test_cpu_returns_fallback(self):
        result = auto_batch_size(torch.device("cpu"))
        assert result == 300_000

    def test_returns_positive_integer(self):
        result = auto_batch_size(torch.device("cpu"), fallback=50_000)
        assert isinstance(result, int)
        assert result > 0

