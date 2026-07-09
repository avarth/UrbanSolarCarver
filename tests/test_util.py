"""Tests for api_core/_util.py: histograms, score statistics, Tregenza helpers."""
import numpy as np
import pytest
from pathlib import Path

from urbansolarcarver.api_core._diagnostics import save_histogram, score_statistics


class TestEstimateGridMemory:
    def test_matches_actual_cubic_grid(self, tmp_path):
        """The dry-run estimate must mirror voxelize_mesh, which always
        builds a CUBIC grid sized to the longest bounding-box side."""
        import trimesh
        from urbansolarcarver.api_core._reporting import estimate_grid_memory
        from urbansolarcarver.grid import voxelize_mesh

        slab = trimesh.creation.box(extents=(40.0, 10.0, 5.0))
        slab_path = tmp_path / "slab.ply"
        slab.export(str(slab_path))

        est = estimate_grid_memory(2.0, str(slab_path), margin_frac=0.01)
        _, _, _, res = voxelize_mesh.__wrapped__(slab, voxel_size=2.0, margin_frac=0.01)
        assert est["grid_dims"] == (res, res, res)
        assert est["total_voxels"] == res ** 3


# ---------------------------------------------------------------------------
# score_statistics
# ---------------------------------------------------------------------------

class TestScoreStatistics:
    def test_empty_array(self):
        result = score_statistics(np.array([]))
        assert result == {"count": 0}

    def test_all_nan(self):
        result = score_statistics(np.array([np.nan, np.nan]))
        assert result == {"count": 0}

    def test_normal_array(self):
        scores = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = score_statistics(scores)
        assert result["count"] == 5
        assert result["min"] == 1.0
        assert result["max"] == 5.0
        assert result["mean"] == pytest.approx(3.0)
        assert "median" in result
        assert "std" in result
        assert "p5" in result
        assert "p95" in result
        assert "nonzero_count" in result
        assert "nonzero_fraction" in result

    def test_with_inf(self):
        scores = np.array([1.0, np.inf, 3.0])
        result = score_statistics(scores)
        assert result["count"] == 2  # inf filtered out

    def test_3d_array(self):
        scores = np.ones((5, 5, 5))
        result = score_statistics(scores)
        assert result["count"] == 125


# ---------------------------------------------------------------------------
# save_histogram
# ---------------------------------------------------------------------------

class TestSaveHistogram:
    def test_creates_png(self, tmp_path):
        scores = np.random.rand(100) * 10
        path = save_histogram(scores, tmp_path, "test_hist.png")
        assert path is not None
        assert path.exists()
        assert path.suffix == ".png"

    def test_empty_array_returns_none(self, tmp_path):
        result = save_histogram(np.array([]), tmp_path)
        assert result is None

    def test_all_nan_returns_none(self, tmp_path):
        result = save_histogram(np.array([np.nan, np.nan, np.nan]), tmp_path)
        assert result is None

    def test_with_threshold_line(self, tmp_path):
        scores = np.random.rand(100)
        path = save_histogram(scores, tmp_path, threshold_line=0.5)
        assert path is not None
        assert path.exists()

    def test_zero_dominant_scores_creates_histogram(self, tmp_path):
        """When most voxels score zero, the histogram should still be created.

        BUG B3: currently the histogram filters to flat > 0, hiding the
        zero-score population. After fix, the plot should annotate the
        zero count (e.g., '900 zero-score voxels (90%)').
        """
        scores = np.concatenate([np.zeros(900), np.random.rand(100) * 10])
        path = save_histogram(scores, tmp_path, "zero_test.png")
        assert path is not None
        assert path.exists()

    def test_constant_scores(self, tmp_path):
        """All-identical scores should not crash."""
        scores = np.full(50, 3.14)
        path = save_histogram(scores, tmp_path, "const.png")
        # May return a histogram or None depending on implementation
        # Just verify no crash
