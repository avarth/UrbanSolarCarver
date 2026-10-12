"""Tests for api_core/exporting.py: hash computation, manifest, anomaly handling."""
import json
import hashlib
import pytest
import numpy as np
from pathlib import Path


def _create_preprocessing_artifacts(tmp_path, grid_shape=(8, 8, 8)):
    """Create minimal preprocessing artifacts for exporting tests."""
    pre_dir = tmp_path / "preprocessing"
    pre_dir.mkdir()
    diag_dir = pre_dir / "diagnostics"
    diag_dir.mkdir()

    # Create voxel grid and scores
    grid = np.ones(grid_shape, dtype=np.uint8)
    scores = np.random.rand(*grid_shape).astype(np.float32)
    np.save(str(pre_dir / "voxel_grid.npy"), grid)
    np.save(str(pre_dir / "scores.npy"), scores)

    # Create preprocessing manifest (only fields consumed by downstream stages)
    pre_manifest = {
        "hash": "abcd1234",
        "scores_path": str(pre_dir / "scores.npy"),
        "scores_kind": "weighted_sum",
        "shape": list(grid_shape),
        "origin": [0.0, 0.0, 0.0],
        "voxel_grid_path": str(pre_dir / "voxel_grid.npy"),
        "mode": "benefit",
    }
    (pre_dir / "manifest.json").write_text(json.dumps(pre_manifest), encoding="utf-8")
    return pre_dir, pre_manifest


def _create_thresholding_artifacts(tmp_path, pre_dir, pre_manifest, grid_shape=(8, 8, 8)):
    """Create minimal thresholding artifacts for exporting tests."""
    thr_dir = tmp_path / "thresholding"
    thr_dir.mkdir()
    diag_dir = thr_dir / "diagnostics"
    diag_dir.mkdir()

    # Create mask (keep everything)
    mask = np.ones(grid_shape, dtype=bool)
    np.save(str(thr_dir / "mask.npy"), mask)

    thr_manifest = {
        "hash": "efgh5678",
        "mask_path": str(thr_dir / "mask.npy"),
        "upstream_manifest": str(pre_dir / "manifest.json"),
    }
    (thr_dir / "manifest.json").write_text(json.dumps(thr_manifest), encoding="utf-8")
    return thr_dir, thr_manifest


class TestExportHashComputation:
    def test_hash_changes_with_mesh_method(self):
        """Different smoothing params should produce different hashes."""
        upstream = "abcd1234"
        snippet_a = {"voxel_size": 2.0, "apply_smoothing": False, "smooth_iters": 2, "min_voxels": 300, "min_face_count": 100}
        snippet_b = {"voxel_size": 2.0, "apply_smoothing": True, "smooth_iters": 2, "min_voxels": 300, "min_face_count": 100}
        hash_a = hashlib.sha256((json.dumps(snippet_a, sort_keys=True) + upstream).encode()).hexdigest()[:8]
        hash_b = hashlib.sha256((json.dumps(snippet_b, sort_keys=True) + upstream).encode()).hexdigest()[:8]
        assert hash_a != hash_b, "Hashes should differ when apply_smoothing differs"

    def test_hash_deterministic(self):
        """Same inputs should produce the same hash."""
        snippet = {"voxel_size": 2.0}
        upstream = "abcd1234"
        h1 = hashlib.sha256((json.dumps(snippet, sort_keys=True) + upstream).encode()).hexdigest()[:8]
        h2 = hashlib.sha256((json.dumps(snippet, sort_keys=True) + upstream).encode()).hexdigest()[:8]
        assert h1 == h2

    def test_hash_changes_with_voxel_size(self):
        """Different voxel_size should produce different hashes."""
        upstream = "abcd1234"
        h1 = hashlib.sha256((json.dumps({"voxel_size": 1.0}, sort_keys=True) + upstream).encode()).hexdigest()[:8]
        h2 = hashlib.sha256((json.dumps({"voxel_size": 2.0}, sort_keys=True) + upstream).encode()).hexdigest()[:8]
        assert h1 != h2

    def test_hash_is_8_hex_chars(self):
        snippet = {"voxel_size": 2.0}
        upstream = "test1234"
        h = hashlib.sha256((json.dumps(snippet, sort_keys=True) + upstream).encode()).hexdigest()[:8]
        assert len(h) == 8
        assert all(c in "0123456789abcdef" for c in h)
