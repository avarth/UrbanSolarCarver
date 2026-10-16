"""Pipeline tests: full runs on a tiny cube mesh, stage-boundary validation, config
override parsing, simulated weights, edge taper, default-threshold reporting and
score smoothing."""
import json
import os
import pytest
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# EPW path resolution: USC_EPW_PATH env var wins, else the bundled NREL file.
# ---------------------------------------------------------------------------
from _epw import resolve_epw
_EPW = resolve_epw()
_SKIP_EPW = pytest.mark.skipif(
    not _EPW,
    reason="EPW file not available; set USC_EPW_PATH env var to enable",
)


@_SKIP_EPW
def test_full_pipeline_benefit(tmp_path, tiny_cube_mesh, tiny_surface_mesh):
    """Run preprocessing → thresholding → exporting on a tiny cube."""
    from urbansolarcarver import load_config, preprocessing, thresholding, exporting

    # Write test meshes
    vol_path = tmp_path / "max_volume.ply"
    srf_path = tmp_path / "test_surface.ply"
    tiny_cube_mesh.export(str(vol_path))
    tiny_surface_mesh.export(str(srf_path))

    # Write a minimal config
    cfg_dict = {
        "max_volume_path": str(vol_path),
        "test_surface_path": str(srf_path),
        "epw_path": _EPW,
        "out_dir": str(tmp_path / "out"),
        "mode": "benefit",
        "voxel_size": 2.0,
        "grid_step": 2.0,
        "ray_length": 50.0,
        "ray_batch_size": 50000,
        "threshold": "carve_fraction",
        "carve_fraction": 0.5,
        "start_month": 1, "start_day": 1, "start_hour": 8,
        "end_month": 1, "end_day": 1, "end_hour": 16,
        "apply_smoothing": False,
        "min_voxels": 1,
        "min_face_count": 1,
        "device": "cpu",
    }
    import yaml
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg_dict), encoding="utf-8")

    cfg = load_config(str(cfg_path))
    base = tmp_path / "out"

    # Stage 1: preprocessing
    pre = preprocessing(cfg, base / "preprocessing")
    assert pre.volume_path.exists(), "scores.npy not written"
    assert (pre.out_dir / "manifest.json").exists(), "preprocessing manifest missing"
    manifest = json.loads((pre.out_dir / "manifest.json").read_text())
    assert "scores_path" in manifest
    assert "shape" in manifest

    # Stage 2: thresholding
    thr = thresholding(pre, cfg, base / "thresholding")
    assert thr.mask_path.exists(), "mask.npy not written"
    assert (thr.out_dir / "manifest.json").exists(), "thresholding manifest missing"

    # Stage 3: exporting
    result = exporting(thr, cfg, base / "exporting")
    assert result.export_path.exists(), "exported mesh not written"

    # Check diagnostics exist
    pre_diag = pre.out_dir / "diagnostics"
    assert (pre_diag / "diagnostic.json").exists(), "preprocessing diagnostics missing"
    thr_diag = thr.out_dir / "diagnostics"
    assert (thr_diag / "diagnostic.json").exists(), "thresholding diagnostics missing"

    # Check preprocessing diagnostic has expected fields
    pre_summary = json.loads((pre_diag / "diagnostic.json").read_text())
    assert "score_stats" in pre_summary
    assert "mode" in pre_summary
    assert "voxel_size" in pre_summary
    assert "timings" in pre_summary

    # Check thresholding diagnostic has expected fields
    thr_summary = json.loads((thr_diag / "diagnostic.json").read_text())
    assert "threshold_method" in thr_summary
    assert "voxels_kept" in thr_summary
    assert "retention_pct" in thr_summary
    assert "timings" in thr_summary


@_SKIP_EPW
def test_run_pipeline_convenience(tmp_path, tiny_cube_mesh, tiny_surface_mesh):
    """Test the run_pipeline() convenience wrapper."""
    from urbansolarcarver import run_pipeline, load_config

    vol_path = tmp_path / "max_volume.ply"
    srf_path = tmp_path / "test_surface.ply"
    tiny_cube_mesh.export(str(vol_path))
    tiny_surface_mesh.export(str(srf_path))

    import yaml
    cfg_dict = {
        "max_volume_path": str(vol_path),
        "test_surface_path": str(srf_path),
        "epw_path": _EPW,
        "out_dir": str(tmp_path / "out"),
        "mode": "benefit",
        "voxel_size": 2.0,
        "grid_step": 2.0,
        "ray_length": 50.0,
        "ray_batch_size": 50000,
        "threshold": "carve_fraction",
        "carve_fraction": 0.5,
        "start_month": 1, "start_day": 1, "start_hour": 8,
        "end_month": 1, "end_day": 1, "end_hour": 16,
        "apply_smoothing": False,
        "min_voxels": 1,
        "min_face_count": 1,
        "device": "cpu",
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg_dict), encoding="utf-8")

    cfg = load_config(str(cfg_path))
    result = run_pipeline(cfg, tmp_path / "pipeline_out")
    assert result.exporting.export_path.exists()


# ---------------------------------------------------------------------------
# Stage-boundary validation (no GPU / EPW needed)
# ---------------------------------------------------------------------------

class TestStageBoundaryValidation:
    """Mismatched or missing artifacts must fail with clear errors, not
    cryptic numpy/torch failures deep in a stage."""

    def _cfg(self, tmp_path):
        from urbansolarcarver.load_config import user_config
        return user_config(
            max_volume_path="dummy", test_surface_path="dummy",
            out_dir=str(tmp_path), mode="irradiance", epw_path="dummy",
            start_month=1, start_day=1, start_hour=0,
            end_month=12, end_day=31, end_hour=23,
            threshold=50.0,
        )

    def _write_pre_manifest(self, tmp_path, scores, manifest_shape):
        from urbansolarcarver.pydantic_schemas import PreprocessingManifest, schema_to_json
        pre_dir = tmp_path / "preprocessing"
        pre_dir.mkdir(parents=True, exist_ok=True)
        scores_path = pre_dir / "scores.npy"
        np.save(scores_path, scores, allow_pickle=False)
        pm = PreprocessingManifest(
            run_id="t", scores_path=str(scores_path), scores_kind="weighted_sum",
            shape=manifest_shape, origin=(0.0, 0.0, 0.0), voxel_size=1.0,
            mode="irradiance", voxel_grid_path="voxel_grid.npy", sample_point_count=1,
            footprint_path="footprint.json",
        )
        (pre_dir / "manifest.json").write_text(schema_to_json(pm), encoding="utf-8")
        return pre_dir

    def test_scores_shape_mismatch_rejected(self, tmp_path):
        from urbansolarcarver.api_core.thresholding import thresholding
        from urbansolarcarver.errors import StageChainError
        pre_dir = self._write_pre_manifest(
            tmp_path, np.zeros((8, 8, 8), dtype=np.float32), manifest_shape=(9, 9, 9),
        )
        with pytest.raises(StageChainError, match="does not match the grid shape"):
            thresholding(pre_dir, self._cfg(tmp_path), tmp_path / "thr")

    def test_missing_scores_file_rejected(self, tmp_path):
        from urbansolarcarver.api_core.thresholding import thresholding
        from urbansolarcarver.errors import StageChainError
        pre_dir = self._write_pre_manifest(
            tmp_path, np.zeros((8, 8, 8), dtype=np.float32), manifest_shape=(8, 8, 8),
        )
        (pre_dir / "scores.npy").unlink()
        with pytest.raises(StageChainError, match="Scores file not found"):
            thresholding(pre_dir, self._cfg(tmp_path), tmp_path / "thr")


class TestLoadMeshGuards:
    def test_empty_mesh_rejected(self, tmp_path):
        """A PLY with no faces must fail at load, not as a cryptic
        empty-voxel-grid error later."""
        import trimesh
        from urbansolarcarver.io import load_mesh
        pc_path = tmp_path / "points_only.ply"
        trimesh.points.PointCloud(np.random.rand(10, 3)).export(str(pc_path))
        with pytest.raises(ValueError, match="no triangle geometry"):
            load_mesh(str(pc_path))


class TestOverrideParsing:
    def test_scientific_notation(self):
        from urbansolarcarver.load_config import parse_override_value
        assert parse_override_value("1e-3") == pytest.approx(0.001)
        assert parse_override_value("2E5") == pytest.approx(200000.0)

    def test_inf_nan_stay_strings(self):
        """'inf'/'nan' as config values are almost certainly typos. They
        stay strings so that schema validation produces a clear error."""
        from urbansolarcarver.load_config import parse_override_value
        assert parse_override_value("inf") == "inf"
        assert parse_override_value("nan") == "nan"

    def test_plain_types_unchanged(self):
        from urbansolarcarver.load_config import parse_override_value
        assert parse_override_value("3") == 3
        assert parse_override_value("3.5") == 3.5
        assert parse_override_value("true") is True
        assert parse_override_value("none") is None
        assert parse_override_value("hello") == "hello"


# ---------------------------------------------------------------------------
# simulated_weights_path end-to-end (benefit mode + artifact)
# ---------------------------------------------------------------------------

@_SKIP_EPW
def test_benefit_with_weights_artifact(tmp_path, tiny_cube_mesh,
                                          tiny_surface_mesh):
    """Full benefit preprocessing consuming a simulated-weights artifact: runs
    green and records the artifact's provenance in the diagnostics."""
    import numpy as _np
    from urbansolarcarver import preprocessing
    from urbansolarcarver.load_config import user_config
    from urbansolarcarver.simulated_weights import write_simulated_weights

    vol_path = tmp_path / "vol.ply"
    srf_path = tmp_path / "srf.ply"
    tiny_cube_mesh.export(str(vol_path))
    tiny_surface_mesh.export(str(srf_path))

    artifact = write_simulated_weights(
        tmp_path / "u.json",
        _np.full(8760, 0.8), _np.zeros(8760),
        {"method": "test-schedule", "generated": "2026",
         "archetype": {"mass_class": "medium"}},
    )
    cfg = user_config(
        max_volume_path=str(vol_path), test_surface_path=str(srf_path),
        out_dir=str(tmp_path / "out"), mode="benefit", epw_path=_EPW,
        start_month=1, start_day=1, start_hour=8,
        end_month=1, end_day=5, end_hour=16,
        voxel_size=2.0, grid_step=2.0, ray_length=50.0,
        min_voxels=1, min_face_count=1, device="cpu",
        simulated_weights_path=str(artifact),
    )
    result = preprocessing(cfg, tmp_path / "out")
    scores = np.load(result.volume_path)
    assert scores.sum() > 0, "artifact-weighted carve produced no scores"
    diag = json.loads(
        (result.out_dir / "diagnostics" / "diagnostic.json").read_text())
    assert diag["simulated_weights"]["method"] == "test-schedule"
    assert diag["simulated_weights"]["archetype"]["mass_class"] == "medium"


@_SKIP_EPW
def test_benefit_with_weights_artifact_writes_the_comparison_plot(tmp_path, tiny_cube_mesh,
                                                                  tiny_surface_mesh):
    """With diagnostic_plots, a benefit run with simulated weights also plots
    them against the simple balance-point weights and records the result."""
    import numpy as _np
    from urbansolarcarver import preprocessing
    from urbansolarcarver.load_config import user_config
    from urbansolarcarver.simulated_weights import write_simulated_weights

    vol_path = tmp_path / "vol.ply"
    srf_path = tmp_path / "srf.ply"
    tiny_cube_mesh.export(str(vol_path))
    tiny_surface_mesh.export(str(srf_path))
    artifact = write_simulated_weights(
        tmp_path / "u.json", _np.full(8760, 0.8), _np.zeros(8760),
        {"method": "test-schedule", "generated": "2026", "archetype": {"mass_class": "medium"}},
    )
    cfg = user_config(
        max_volume_path=str(vol_path), test_surface_path=str(srf_path),
        out_dir=str(tmp_path / "out"), mode="benefit", epw_path=_EPW,
        start_month=1, start_day=1, start_hour=8,
        end_month=1, end_day=5, end_hour=16,
        voxel_size=2.0, grid_step=2.0, ray_length=50.0,
        min_voxels=1, min_face_count=1, device="cpu",
        simulated_weights_path=str(artifact), diagnostic_plots=True,
    )
    result = preprocessing(cfg, tmp_path / "out")
    diag_dir = result.out_dir / "diagnostics"
    diag = json.loads((diag_dir / "diagnostic.json").read_text())
    for name in ("sky_patch_weights.png", "sky_patch_weights_intensity.png",
                 "sky_patch_comparison.png", "score_histogram.png", "config_snapshot.json"):
        assert (diag_dir / name).is_file(), name
    assert diag["sky_patch_comparison_image"].endswith("sky_patch_comparison.png")
    assert set(diag["sky_patch_comparison_stats"]) == {
        "mass_redistributed_pct", "patches_over_20pct", "rel_change_min_pct", "rel_change_max_pct"}
    assert len(diag["sky_patch_images"]) == 2 and diag["score_histogram"].endswith("score_histogram.png")


# ---------------------------------------------------------------------------
# edge_taper end-to-end (daylight mode needs no EPW)
# ---------------------------------------------------------------------------

class TestEdgeTaperPipeline:
    def _run_preprocessing(self, tmp_path, sub, tiny_cube_mesh, tiny_surface_mesh,
                           **cfg_extra):
        from urbansolarcarver import preprocessing
        from urbansolarcarver.load_config import user_config
        vol_path = tmp_path / sub / "vol.ply"
        srf_path = tmp_path / sub / "srf.ply"
        vol_path.parent.mkdir(parents=True, exist_ok=True)
        tiny_cube_mesh.export(str(vol_path))
        tiny_surface_mesh.export(str(srf_path))
        cfg = user_config(
            max_volume_path=str(vol_path), test_surface_path=str(srf_path),
            out_dir=str(tmp_path / sub / "out"), mode="daylight",
            voxel_size=2.0, grid_step=2.0, ray_length=50.0,
            min_voxels=1, min_face_count=1, device="cpu",
            **cfg_extra,
        )
        return preprocessing(cfg, tmp_path / sub / "out")

    def test_taper_reduces_score_mass(self, tmp_path, tiny_cube_mesh, tiny_surface_mesh):
        """A taper wider than the surface strictly reduces every weight,
        so total blocked score mass must drop versus the untapered run."""
        base = self._run_preprocessing(
            tmp_path, "base", tiny_cube_mesh, tiny_surface_mesh)
        tapered = self._run_preprocessing(
            tmp_path, "tapered", tiny_cube_mesh, tiny_surface_mesh,
            edge_taper=10.0)  # surface is 6x6 → max boundary distance 3
        s_base = np.load(base.volume_path).sum(dtype=np.float64)
        s_tap = np.load(tapered.volume_path).sum(dtype=np.float64)
        assert s_base > 0
        assert 0 < s_tap < 0.6 * s_base  # all weights <= 3/10

    def test_taper_recorded_in_diagnostics(self, tmp_path, tiny_cube_mesh, tiny_surface_mesh):
        import json as _json
        result = self._run_preprocessing(
            tmp_path, "diag", tiny_cube_mesh, tiny_surface_mesh, edge_taper=1.0)
        diag = _json.loads(
            (result.out_dir / "diagnostics" / "diagnostic.json").read_text())
        assert diag["edge_taper"]["meters"] == 1.0
        assert diag["edge_taper"]["applied"] is True
        assert diag["edge_taper"]["components"]

    def test_taper_ignored_for_violation_modes(self, tmp_path, tiny_cube_mesh, tiny_surface_mesh):
        from urbansolarcarver import preprocessing
        from urbansolarcarver.load_config import user_config
        vol_path = tmp_path / "tp" / "vol.ply"
        srf_path = tmp_path / "tp" / "srf.ply"
        vol_path.parent.mkdir(parents=True, exist_ok=True)
        tiny_cube_mesh.export(str(vol_path))
        tiny_surface_mesh.export(str(srf_path))
        cfg = user_config(
            max_volume_path=str(vol_path), test_surface_path=str(srf_path),
            out_dir=str(tmp_path / "tp" / "out"), mode="tilted_plane",
            tilted_plane_angle_deg=45.0, voxel_size=2.0, grid_step=2.0,
            ray_length=50.0, min_voxels=1, min_face_count=1, device="cpu",
            edge_taper=1.0,
        )
        with pytest.warns(UserWarning, match="edge_taper.*ignored"):
            preprocessing(cfg, tmp_path / "tp" / "out")


# ---------------------------------------------------------------------------
# Default-threshold reporting (no GPU / EPW needed)
# ---------------------------------------------------------------------------

class TestDefaultThresholdReporting:
    """With threshold unset on weighted scores, the default strategy must be
    recorded by name ('carve_fraction')."""

    def _run_thresholding(self, tmp_path, sub, scores, **overrides):
        pre_dir = tmp_path / sub / "preprocessing"
        pre_dir.mkdir(parents=True, exist_ok=True)
        scores_path = pre_dir / "scores.npy"
        np.save(scores_path, scores, allow_pickle=False)
        vg_path = pre_dir / "voxel_grid.npy"
        np.save(vg_path, np.ones(scores.shape, dtype=bool), allow_pickle=False)
        from urbansolarcarver.pydantic_schemas import PreprocessingManifest, schema_to_json
        pm = PreprocessingManifest(
            run_id="test1234",
            scores_path=str(scores_path),
            scores_kind="weighted_sum",
            shape=tuple(scores.shape),
            origin=(0.0, 0.0, 0.0),
            voxel_size=1.0,
            mode="irradiance",
            voxel_grid_path=str(vg_path),
            sample_point_count=1,
            footprint_path="footprint.json",
        )
        (pre_dir / "manifest.json").write_text(schema_to_json(pm), encoding="utf-8")

        from urbansolarcarver.load_config import user_config
        cfg = user_config(
            max_volume_path="dummy", test_surface_path="dummy",
            out_dir=str(tmp_path / sub), mode="irradiance", epw_path="dummy",
            start_month=1, start_day=1, start_hour=0,
            end_month=12, end_day=31, end_hour=23,
            # threshold intentionally left unset (None → carve_fraction)
            **overrides,
        )
        from urbansolarcarver.api_core.thresholding import thresholding
        return thresholding(pre_dir, cfg, tmp_path / sub / "thr")

    def test_default_reported_as_carve_fraction(self, tmp_path):
        rng = np.random.default_rng(11)
        scores = rng.uniform(0, 100, size=(8, 8, 8)).astype(np.float32)
        result = self._run_thresholding(tmp_path, "a", scores)
        diag = json.loads((result.out_dir / "diagnostics" / "diagnostic.json").read_text())
        assert diag["threshold_method"] == "carve_fraction"
        assert diag["max_slope_deg"] == 75.0  # default slope limit for the weighted modes
        assert diag["slope_limit_extra_voxels_removed"] >= 0

    def test_max_slope_90_turns_the_limit_off(self, tmp_path):
        rng = np.random.default_rng(14)
        scores = rng.uniform(0, 100, size=(8, 8, 8)).astype(np.float32)
        result = self._run_thresholding(tmp_path, "off", scores, max_slope_deg=90)
        diag = json.loads((result.out_dir / "diagnostics" / "diagnostic.json").read_text())
        assert diag["max_slope_deg"] is None
        assert diag["slope_limit_extra_voxels_removed"] == 0

    def test_carve_fraction_counts_carve_above(self, tmp_path):
        """Without smoothing and slope limit, the removed voxels (carve_above
        included) hold the carve_fraction share of the score, up to one
        group of tied voxels."""
        rng = np.random.default_rng(15)
        scores = rng.uniform(0, 100, size=(8, 8, 8)).astype(np.float32)
        result = self._run_thresholding(tmp_path, "share", scores, carve_fraction=0.4,
                                        score_smoothing=0, max_slope_deg=90)
        mask = np.load(result.mask_path)
        share = scores[~mask].sum(dtype=np.float64) / scores.sum(dtype=np.float64)
        assert 0.4 - 0.03 < share <= 0.4 + 1e-9

    def test_thresholding_warns_on_nonfinite_scores(self, tmp_path):
        """Standalone thresholding (CLI/daemon/GH) must warn about NaN/Inf
        scores loaded from disk (preprocessing's guard does not cover this
        path) and must not crash on the default carve_fraction strategy."""
        rng = np.random.default_rng(13)
        scores = rng.uniform(0, 100, size=(8, 8, 8)).astype(np.float32)
        scores[0, 0, :] = np.nan
        with pytest.warns(UserWarning, match="thresholding: scores contain"):
            result = self._run_thresholding(tmp_path, "nonfinite", scores)
        assert result.mask_path.exists()


# ---------------------------------------------------------------------------
# Score smoothing unit tests (no GPU / EPW needed)
# ---------------------------------------------------------------------------

class TestScoreSmoothing:
    """Tests for Gaussian score smoothing before thresholding."""

    def _make_preprocessing_output(self, tmp_path, scores, kind="weighted_sum", voxel_size=1.0):
        """Write a fake preprocessing output dir with scores and manifest."""
        pre_dir = tmp_path / "preprocessing"
        pre_dir.mkdir(parents=True, exist_ok=True)
        scores_path = pre_dir / "scores.npy"
        np.save(scores_path, scores, allow_pickle=False)
        vg_path = pre_dir / "voxel_grid.npy"
        np.save(vg_path, np.ones(scores.shape, dtype=bool), allow_pickle=False)
        from urbansolarcarver.pydantic_schemas import PreprocessingManifest, schema_to_json
        pm = PreprocessingManifest(
            run_id="test1234",
            scores_path=str(scores_path),
            scores_kind=kind,
            shape=tuple(scores.shape),
            origin=(0.0, 0.0, 0.0),
            voxel_size=voxel_size,
            mode="irradiance" if kind == "weighted_sum" else "time-based",
            voxel_grid_path=str(vg_path),
            sample_point_count=1,
            footprint_path="footprint.json",
        )
        manifest_path = pre_dir / "manifest.json"
        manifest_path.write_text(schema_to_json(pm), encoding="utf-8")
        return pre_dir

    def test_smoothing_explicit_value(self, tmp_path):
        """Explicit score_smoothing value should apply Gaussian blur."""
        rng = np.random.default_rng(42)
        scores = rng.uniform(0, 100, size=(16, 16, 16)).astype(np.float32)
        pre_dir = self._make_preprocessing_output(tmp_path, scores, voxel_size=0.5)

        from urbansolarcarver.load_config import user_config
        cfg = user_config(
            max_volume_path="dummy", test_surface_path="dummy", out_dir=str(tmp_path),
            mode="irradiance", epw_path="dummy",
            start_month=1, start_day=1, start_hour=0,
            end_month=12, end_day=31, end_hour=23,
            score_smoothing=1.0,  # 1m → 2 voxels at 0.5m resolution
            threshold=50.0,
        )
        from urbansolarcarver.api_core.thresholding import thresholding
        result = thresholding(pre_dir, cfg, tmp_path / "thr_out")

        diag = json.loads((result.out_dir / "diagnostics" / "diagnostic.json").read_text())
        assert diag["score_smooth_applied"] is True
        assert diag["score_smoothing_sigma_voxels"] > 0

    def test_smoothing_auto_default(self, tmp_path):
        """score_smoothing=None should auto-compute as 1.1 × voxel_size."""
        rng = np.random.default_rng(42)
        scores = rng.uniform(0, 100, size=(16, 16, 16)).astype(np.float32)
        pre_dir = self._make_preprocessing_output(tmp_path, scores, voxel_size=2.0)

        from urbansolarcarver.load_config import user_config
        cfg = user_config(
            max_volume_path="dummy", test_surface_path="dummy", out_dir=str(tmp_path),
            mode="irradiance", epw_path="dummy",
            start_month=1, start_day=1, start_hour=0,
            end_month=12, end_day=31, end_hour=23,
            # score_smoothing left as None (default)
            threshold=50.0,
        )
        from urbansolarcarver.api_core.thresholding import thresholding
        result = thresholding(pre_dir, cfg, tmp_path / "thr_out_auto")

        diag = json.loads((result.out_dir / "diagnostics" / "diagnostic.json").read_text())
        assert diag["score_smooth_applied"] is True
        # Auto: 1.1 * 2.0 = 2.2m → 2.2/2.0 = 1.1 voxels
        assert 1.0 <= diag["score_smoothing_sigma_voxels"] <= 1.2
        assert abs(diag["score_smoothing_m"] - 2.2) < 0.01

    def test_smoothing_skipped_for_violation_count(self, tmp_path):
        """Violation-count scores (time-based) should NOT be smoothed."""
        scores = np.ones((8, 8, 8), dtype=np.float32) * 3.0
        pre_dir = self._make_preprocessing_output(tmp_path, scores, kind="violation_count", voxel_size=1.0)

        from urbansolarcarver.load_config import user_config
        cfg = user_config(
            max_volume_path="dummy", test_surface_path="dummy", out_dir=str(tmp_path),
            mode="time-based", epw_path="dummy",
            start_month=1, start_day=1, start_hour=0,
            end_month=12, end_day=31, end_hour=23,
            score_smoothing=2.0,
            threshold=0,
        )
        from urbansolarcarver.api_core.thresholding import thresholding
        result = thresholding(pre_dir, cfg, tmp_path / "thr_out2")

        diag = json.loads((result.out_dir / "diagnostics" / "diagnostic.json").read_text())
        assert diag["score_smooth_applied"] is False

    def test_smoothing_zero_disables(self, tmp_path):
        """score_smoothing=0 should disable smoothing entirely."""
        rng = np.random.default_rng(99)
        scores = rng.uniform(0, 50, size=(8, 8, 8)).astype(np.float32)
        pre_dir = self._make_preprocessing_output(tmp_path, scores, voxel_size=1.0)

        from urbansolarcarver.load_config import user_config
        cfg = user_config(
            max_volume_path="dummy", test_surface_path="dummy", out_dir=str(tmp_path),
            mode="irradiance", epw_path="dummy",
            start_month=1, start_day=1, start_hour=0,
            end_month=12, end_day=31, end_hour=23,
            score_smoothing=0.0,
            threshold=25.0,
        )
        from urbansolarcarver.api_core.thresholding import thresholding
        result = thresholding(pre_dir, cfg, tmp_path / "thr_out3")

        diag = json.loads((result.out_dir / "diagnostics" / "diagnostic.json").read_text())
        assert diag["score_smooth_applied"] is False
        assert diag["score_smoothing_sigma_voxels"] == 0.0


def test_missing_occupancy_grid_is_an_error(tmp_path, tiny_cube_mesh, tiny_surface_mesh):
    """Without voxel_grid.npy the preprocessing run is incomplete: the grid
    is not rebuilt from a config that may describe other geometry."""
    from urbansolarcarver.api_core._stage_io import load_upstream
    from urbansolarcarver.api_core._util import load_occupancy
    from urbansolarcarver.errors import StageChainError
    run = TestEdgeTaperPipeline()._run_preprocessing(
        tmp_path, "fb", tiny_cube_mesh, tiny_surface_mesh)
    pre = load_upstream(run, "preprocessing")
    pre.resolve(pre.manifest.voxel_grid_path).unlink()
    with pytest.raises(StageChainError, match="Re-run preprocessing"):
        load_occupancy(pre)


def test_curved_own_facade_is_not_shaded_by_its_own_skin(tmp_path):
    """A convex tower protecting only its own faceted facade: nothing shades
    it, so no voxel may score. The facets lie inside the curved mass, so
    the voxels they pass through have centres slightly in front of them;
    those are the building's skin, not obstructions."""
    import trimesh
    from urbansolarcarver import preprocessing
    from urbansolarcarver.load_config import user_config
    from urbansolarcarver.io import save_mesh
    tower = trimesh.creation.cylinder(radius=8.0, height=12.0, sections=64)
    tower.apply_translation((0.3, 0.7, 6.0))
    facets = trimesh.creation.cylinder(radius=8.0, height=12.0, sections=12)  # coarser, inside
    facets.apply_translation((0.3, 0.7, 6.0))
    # One separate flat panel per facet (as exploded in Grasshopper), shrunk
    # slightly so neighbouring panels do not share edges.
    panels = []
    for group in facets.facets:
        if abs(facets.face_normals[group[0], 2]) > 0.5:
            continue  # top and bottom caps
        panel = trimesh.Trimesh(facets.vertices, facets.faces[group])
        panel.remove_unreferenced_vertices()
        c = panel.vertices.mean(axis=0)
        panel.vertices = c + 0.98 * (panel.vertices - c)
        panels.append(panel)
    facade = trimesh.util.concatenate(panels)
    save_mesh(tower, str(tmp_path / "vol.ply"))
    save_mesh(facade, str(tmp_path / "srf.ply"))
    cfg = user_config(max_volume_path=str(tmp_path / "vol.ply"),
                      test_surface_path=str(tmp_path / "srf.ply"), out_dir=str(tmp_path / "out"),
                      mode="daylight", voxel_size=1.0, grid_step=1.0, ray_length=60.0, device="cpu")
    pre = preprocessing(cfg, tmp_path / "out" / "preprocessing")
    scores = np.load(pre.volume_path)
    occ = np.load(tmp_path / "out" / "preprocessing" / "voxel_grid.npy").astype(bool).ravel()
    assert scores[occ].max() == 0.0


def test_missing_max_volume_file_is_an_input_error(tmp_path):
    from _stage_scene import daylight_cube_config
    from urbansolarcarver import preprocessing
    from urbansolarcarver.errors import InputError
    conf = daylight_cube_config(tmp_path)
    Path(conf.max_volume_path).unlink()
    with pytest.raises(InputError, match="max_volume file missing"):
        preprocessing(conf, tmp_path / "run" / "preprocessing")


def test_thresholding_refuses_a_config_of_another_mode(tmp_path):
    """Scores from a daylight run cannot be thresholded with an irradiance config:
    the threshold defaults and units differ per mode."""
    import warnings
    from _stage_scene import daylight_cube_config
    from urbansolarcarver import preprocessing, thresholding
    from urbansolarcarver.errors import StageChainError
    from urbansolarcarver.load_config import user_config
    run = tmp_path / "run"
    daylight = daylight_cube_config(tmp_path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = preprocessing(daylight, run / "preprocessing")
    irradiance = user_config(
        max_volume_path=daylight.max_volume_path, test_surface_path=daylight.test_surface_path,
        out_dir=str(run), mode="irradiance", epw_path="dummy.epw",
        start_month=1, start_day=1, start_hour=8, end_month=1, end_day=1, end_hour=16,
        voxel_size=1.0, grid_step=1.0, ray_length=50.0, device="cpu",
    )
    with pytest.raises(StageChainError, match="daylight"):
        thresholding(pre, irradiance, run / "thresholding")


def test_exporting_meshes_with_the_preprocessing_voxel_size(tmp_path):
    """The grid's voxel size is a fact of the preprocessing run: a config with
    another voxel_size changes nothing and raises no warning."""
    import warnings
    import trimesh
    from _stage_scene import daylight_cube_config
    from urbansolarcarver import exporting, preprocessing, thresholding
    run = tmp_path / "run"
    conf = daylight_cube_config(tmp_path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = preprocessing(conf, run / "preprocessing")
        thr = thresholding(pre, conf, run / "thresholding")
    np.save(thr.mask_path, np.ones_like(np.load(thr.mask_path), dtype=bool))
    other_voxel_size = conf.model_copy(update={"voxel_size": 2.0})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = exporting(thr, other_voxel_size, run / "exporting")
    assert result.issues == ()
    mesh = trimesh.load(result.export_path, force="mesh")
    cube_bounds = np.array([[-5.0, -5.0, -5.0], [5.0, 5.0, 5.0]])
    assert np.abs(mesh.bounds - cube_bounds).max() <= 1.0 + 1e-6
