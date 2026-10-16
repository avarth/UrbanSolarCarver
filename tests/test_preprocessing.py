"""Tests for the preprocessing stage's helpers: NaN/Inf score warnings and score
statistics (api_core/_diagnostics.py), ray generation from zero sample points,
and the manifest a real run writes."""
import json
import warnings
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock

from urbansolarcarver.api_core._diagnostics import score_statistics


class TestScoreAnomalyDetection:
    """Verify NaN/Inf detection via the real preprocessing anomaly check."""

    def test_nan_produces_warning(self):
        from urbansolarcarver.api_core._diagnostics import warn_score_anomalies
        scores = np.array([1.0, np.nan, 3.0], dtype=np.float32)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            counts = warn_score_anomalies(scores)
        assert counts == {"nan_count": 1, "inf_count": 0}
        assert len(w) == 1
        assert "NaN" in str(w[0].message)

    def test_inf_produces_warning(self):
        from urbansolarcarver.api_core._diagnostics import warn_score_anomalies
        scores = np.array([1.0, np.inf, 3.0], dtype=np.float32)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            counts = warn_score_anomalies(scores)
        assert counts == {"nan_count": 0, "inf_count": 1}
        assert len(w) == 1

    def test_clean_scores_no_warning(self):
        from urbansolarcarver.api_core._diagnostics import warn_score_anomalies
        scores = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            counts = warn_score_anomalies(scores)
        assert counts == {"nan_count": 0, "inf_count": 0}
        assert len(w) == 0


class TestScoreStatisticsIntegration:
    """Verify score_statistics produces all required keys."""

    def test_all_keys_present(self):
        scores = np.random.rand(100)
        stats = score_statistics(scores)
        required_keys = {"count", "min", "max", "mean", "median", "std",
                         "p5", "p25", "p75", "p95", "nonzero_count", "nonzero_fraction"}
        assert required_keys <= set(stats.keys())

    def test_empty_scores(self):
        stats = score_statistics(np.array([]))
        assert stats == {"count": 0}


class TestEmptySamplePoints:
    """Guard against empty sample points before ray generation."""

    def test_generate_sky_patch_rays_with_empty_points(self):
        """generate_sky_patch_rays with 0 points should return 0 rays (no crash)."""
        import torch
        from urbansolarcarver.raytracer import generate_sky_patch_rays
        pts = np.empty((0, 3), dtype=np.float32)
        norms = np.empty((0, 3), dtype=np.float32)
        patch_dirs = torch.tensor([[0, 0, 1]], dtype=torch.float32)
        # The ray generator returns empty arrays without warning; preprocessing
        # raises its own error for an empty test surface before reaching it.
        origins, dirs, ids, point_idx = generate_sky_patch_rays(
            pts, norms, patch_dirs, torch.device("cpu")
        )
        assert origins.shape[0] == 0


def test_manifest_written_by_preprocessing(tmp_path, tmp_mesh_files):
    """The manifest a real run writes validates against the schema, points at
    files that exist, and matches the arrays it describes."""
    from urbansolarcarver import preprocessing
    from urbansolarcarver.load_config import user_config
    from urbansolarcarver.pydantic_schemas import PreprocessingManifest
    vol_path, srf_path = tmp_mesh_files
    cfg = user_config(
        max_volume_path=str(vol_path), test_surface_path=str(srf_path),
        out_dir=str(tmp_path / "out"), mode="daylight",
        voxel_size=2.0, grid_step=2.0, ray_length=50.0, device="cpu",
    )
    result = preprocessing(cfg, tmp_path / "out")
    m = PreprocessingManifest.model_validate_json(result.manifest_path.read_text())

    assert m.mode == "daylight" and m.voxel_size == 2.0
    assert m.scores_kind == "weighted_sum"
    scores = np.load(result.out_dir / m.scores_path)
    grid = np.load(result.out_dir / m.voxel_grid_path)
    assert grid.shape == tuple(m.shape)
    assert scores.size == int(np.prod(m.shape))
    assert m.sample_point_count == len(np.load(tmp_path / "out" / "test_points.npy"))
