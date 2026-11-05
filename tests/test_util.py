"""Tests for api_core/_diagnostics.py (histograms, score statistics) and the
grid memory estimate in grid_planning.py."""
import numpy as np
import pytest

from urbansolarcarver.api_core._diagnostics import save_histogram, score_statistics


class TestEstimateGridMemory:
    def test_matches_actual_cubic_grid(self, tmp_path):
        """The dry-run estimate must mirror voxelize_mesh, which always
        builds a CUBIC grid sized to the longest bounding-box side."""
        import trimesh
        from urbansolarcarver.grid_planning import estimate_grid_memory
        from urbansolarcarver.voxelization import voxelize_mesh

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
        """Each statistic of a small array, worked by hand. The array is skewed (median 2.5, mean 10/3) and holds a zero, so
        the median and the mean, and the counts of all and of non-zero scores, differ."""
        scores = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 10.0])
        assert score_statistics(scores) == pytest.approx({
            "count": 6, "min": 0.0, "max": 10.0, "mean": 10 / 3, "median": 2.5,
            "std": np.sqrt(95) / 3,          # population std (ddof 0): variance 130/6 - (10/3)² = 95/9
            # Linear interpolation between the sorted values at q/100 x 5: 0.25, 1.25, 3.75 and 4 + 0.75 x 6.
            "p5": 0.25, "p25": 1.25, "p75": 3.75, "p95": 8.5,
            "nonzero_count": 5, "nonzero_fraction": 5 / 6,
        })

    def test_with_inf(self):
        scores = np.array([1.0, np.inf, 3.0])
        result = score_statistics(scores)
        assert result["count"] == 2  # inf filtered out

    def test_basic_mode_skips_expensive_stats(self):
        """detailed=False (cfg.diagnostics off) keeps cheap single-pass stats
        and skips the sorting-based ones (median, std, percentiles)."""
        scores = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = score_statistics(scores, detailed=False)
        assert {"count", "min", "max", "mean",
                "nonzero_count", "nonzero_fraction"} <= set(result)
        assert not {"median", "std", "p5", "p25", "p75", "p95"} & set(result)


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

    @pytest.mark.parametrize("scores, threshold_line", [
        (np.random.rand(100), 0.5),                                          # with the threshold drawn
        (np.concatenate([np.zeros(900), np.random.rand(100) * 10]), None),   # 90 % zeros: only the rest is binned
        (np.full(50, 3.14), None),                                           # one value: a single bar
    ], ids=["threshold line", "mostly zeros", "constant"])
    def test_unusual_scores_still_give_a_png(self, tmp_path, scores, threshold_line):
        """A smoke test: none of these inputs stops the histogram from being written."""
        path = save_histogram(scores, tmp_path, threshold_line=threshold_line)
        assert path is not None and path.is_file()
