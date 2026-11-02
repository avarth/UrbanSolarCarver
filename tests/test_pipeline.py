"""Pipeline tests: a benefit run stage by stage on a plot across the street from a neighbour's facade, the
run_pipeline wrapper against the stages, stage-boundary validation, config override parsing, simulated weights, edge
taper, default-threshold reporting and score smoothing."""
import json
import pytest
import numpy as np
from pathlib import Path


def _cube_config_2m(folder, **settings):
    """The cube scene of _stage_scene.py with 2 m voxels and sample spacing, run into ``folder / "out"``."""
    from _stage_scene import cube_config
    return cube_config(folder, **{"out_dir": str(folder / "out"), "voxel_size": 2.0, "grid_step": 2.0, **settings})


def test_full_pipeline_benefit(tmp_path, example_epw_path):
    """Preprocessing, thresholding and exporting called one by one, in benefit mode, on the plot scene: the
    carving takes the plot's side toward the neighbour, and each stage writes its manifest and diagnostics."""
    from _plot_scene import assert_carves_the_north_side, plot_scene
    from urbansolarcarver import preprocessing, thresholding, exporting

    scene = plot_scene(tmp_path)
    cfg = scene.config(tmp_path / "out", "benefit", str(example_epw_path), threshold="carve_fraction", carve_fraction=0.7)
    base = tmp_path / "out"

    pre = preprocessing(cfg, base / "preprocessing")
    manifest = json.loads((pre.out_dir / "manifest.json").read_text())
    assert manifest["mode"] == "benefit" and manifest["context_path"] == str(scene.context)
    thr = thresholding(pre, cfg, base / "thresholding")
    result = exporting(thr, cfg, base / "exporting")
    assert result.export_path.is_file()

    voxels = scene.voxels(thr.out_dir)
    assert_carves_the_north_side(voxels)
    # Every hour of the January day lies below the balance point, so benefit weighs the sky as irradiance does and
    # removes the same voxels (test_modes.py pins irradiance at 1272). Measured 2026-11-02; after a deliberate change
    # of the scene or the scoring, take the new value from the thresholding diagnostics.
    assert int(voxels.removed.sum()) == pytest.approx(1272, rel=0.02)

    # The diagnostics each stage writes for the run report.
    pre_summary = json.loads((pre.out_dir / "diagnostics" / "diagnostic.json").read_text())
    assert pre_summary["mode"] == "benefit" and pre_summary["voxel_size"] == 1.0
    assert {"score_stats", "timings"} <= set(pre_summary)
    thr_summary = json.loads((thr.out_dir / "diagnostics" / "diagnostic.json").read_text())
    assert thr_summary["threshold_method"] == "carve_fraction"
    assert thr_summary["voxels_kept"] == int(voxels.kept.sum())
    assert thr_summary["retention_pct"] == pytest.approx(100.0 * voxels.kept.mean(), abs=0.01)
    assert "timings" in thr_summary


def test_run_pipeline_convenience(tmp_path):
    """run_pipeline runs the stages into ``out_dir/<stage>`` and keeps the voxels the stages called one by one keep.
    Daylight on the 10 m cube, which needs no weather file: which voxels a mode carves is checked above and in
    test_modes.py."""
    from _stage_scene import daylight_cube_config
    from urbansolarcarver import exporting, preprocessing, run_pipeline, thresholding

    cfg = daylight_cube_config(tmp_path)
    result = run_pipeline(cfg, tmp_path / "wrapped")
    assert [p.parent for p in (result.preprocessing.out_dir, result.thresholding.out_dir, result.exporting.out_dir)] \
        == [tmp_path / "wrapped"] * 3
    assert [p.name for p in (result.preprocessing.out_dir, result.thresholding.out_dir, result.exporting.out_dir)] \
        == ["preprocessing", "thresholding", "exporting"]
    thr = thresholding(preprocessing(cfg, tmp_path / "staged" / "pre"), cfg, tmp_path / "staged" / "thr")
    exporting(thr, cfg, tmp_path / "staged" / "exp")
    wrapped_mask = np.load(result.thresholding.mask_path)
    np.testing.assert_array_equal(wrapped_mask, np.load(thr.mask_path))
    assert 0 < wrapped_mask.sum() < np.load(result.preprocessing.out_dir / "voxel_grid.npy").sum()


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

def _benefit_cube_config(tmp_path, out_dir, epw_path, artifact, **settings):
    """The 2 m cube scene in benefit mode, 1 to 5 January from 8:00 to 16:00, weighted by the simulated weights in *artifact*."""
    return _cube_config_2m(tmp_path, out_dir=str(out_dir), mode="benefit", epw_path=str(epw_path),
                           start_month=1, start_day=1, start_hour=8, end_month=1, end_day=5, end_hour=16,
                           simulated_weights_path=str(artifact), **settings)


def test_benefit_with_weights_artifact(tmp_path, example_epw_path):
    """Full benefit preprocessing consuming a simulated-weights artifact: each hour's sun and sky are scaled by the
    artifact's benefit weight, and the artifact's provenance is recorded in the diagnostics."""
    import numpy as _np
    from urbansolarcarver import preprocessing
    from urbansolarcarver.simulated_weights import write_simulated_weights

    def run(name, benefit):
        artifact = write_simulated_weights(
            tmp_path / f"{name}.json",
            _np.full(8760, benefit), _np.zeros(8760),
            {"method": "test-schedule", "generated": "2026",
             "archetype": {"mass_class": "medium"}},
        )
        cfg = _benefit_cube_config(tmp_path, tmp_path / name, example_epw_path, artifact)
        return preprocessing(cfg, tmp_path / name)

    result = run("weighted", 0.8)
    scores = np.load(result.volume_path).astype(np.float64)
    full = np.load(run("all_ones", 1.0).volume_path).astype(np.float64)
    assert (full > 0).all(), "every voxel of the cube lies between the surface and the sky"
    # Every hour of 1 to 5 January in Golden is below the balance point, so the balance-point filter gives weight 1
    # to each hour, as the all-ones artifact does: an ignored artifact gives a ratio of 1.00. The Perez sky of an
    # hour depends on its direct and diffuse irradiance nonlinearly, so scaling both by 0.8 scales the patch weights
    # by about 0.8, not exactly (measured: 0.793 of the total, 0.747 to 0.852 per voxel).
    assert scores.sum() / full.sum() == pytest.approx(0.8, abs=0.02)
    assert ((scores / full > 0.7) & (scores / full < 0.9)).all()
    diag = json.loads(
        (result.out_dir / "diagnostics" / "diagnostic.json").read_text())
    assert diag["simulated_weights"]["method"] == "test-schedule"
    assert diag["simulated_weights"]["archetype"]["mass_class"] == "medium"


@pytest.mark.slow
def test_benefit_with_weights_artifact_writes_the_comparison_plot(tmp_path, example_epw_path):
    """With diagnostic_plots, a benefit run with simulated weights also plots
    them against the simple balance-point weights and records the result."""
    import numpy as _np
    from urbansolarcarver import preprocessing
    from urbansolarcarver.simulated_weights import write_simulated_weights

    artifact = write_simulated_weights(
        tmp_path / "u.json", _np.full(8760, 0.8), _np.zeros(8760),
        {"method": "test-schedule", "generated": "2026", "archetype": {"mass_class": "medium"}},
    )
    cfg = _benefit_cube_config(tmp_path, tmp_path / "out", example_epw_path, artifact, diagnostic_plots=True)
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
    def _run_preprocessing(self, tmp_path, sub, **cfg_extra):
        from urbansolarcarver import preprocessing
        cfg = _cube_config_2m(tmp_path / sub, **cfg_extra)
        return preprocessing(cfg, tmp_path / sub / "out")

    def test_taper_reduces_score_mass(self, tmp_path):
        """A taper wider than the surface strictly reduces every weight,
        so total blocked score mass must drop versus the untapered run."""
        base = self._run_preprocessing(tmp_path, "base")
        tapered = self._run_preprocessing(
            tmp_path, "tapered",
            edge_taper=10.0)  # surface is 6x6 → max boundary distance 3
        s_base = np.load(base.volume_path).sum(dtype=np.float64)
        s_tap = np.load(tapered.volume_path).sum(dtype=np.float64)
        assert s_base > 0
        assert 0 < s_tap < 0.6 * s_base  # all weights <= 3/10

    def test_taper_recorded_in_diagnostics(self, tmp_path):
        import json as _json
        result = self._run_preprocessing(tmp_path, "diag", edge_taper=1.0)
        diag = _json.loads(
            (result.out_dir / "diagnostics" / "diagnostic.json").read_text())
        assert diag["edge_taper"]["meters"] == 1.0
        assert diag["edge_taper"]["applied"] is True
        assert diag["edge_taper"]["components"]

    def test_taper_ignored_for_violation_modes(self, tmp_path):
        from urbansolarcarver import preprocessing
        cfg = _cube_config_2m(tmp_path / "tp", mode="tilted_plane", tilted_plane_angle_deg=45.0, edge_taper=1.0)
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
        path) and must not crash on the default carve_fraction strategy.
        NaN voxels are always carved and count for no score mass, so the rest
        of the mask is that of the same scores with 0 in their place."""
        rng = np.random.default_rng(13)
        scores = rng.uniform(0, 100, size=(8, 8, 8)).astype(np.float32)
        zeroed = scores.copy()
        zeroed[0, 0, :] = 0.0
        scores[0, 0, :] = np.nan
        # Smoothing off; the next test does the same through the default smoothing.
        with pytest.warns(UserWarning, match="thresholding: scores contain 8 NaN and 0 Inf"):
            result = self._run_thresholding(tmp_path, "nonfinite", scores, score_smoothing=0)
        mask = np.load(result.mask_path)
        reference = np.load(self._run_thresholding(tmp_path, "zeroed", zeroed, score_smoothing=0).mask_path)
        assert not mask[0, 0, :].any()
        assert reference[0, 0, :].any()          # the comparison would be empty if 0 scores were carved too
        rest = np.ones(mask.shape, dtype=bool)
        rest[0, 0, :] = False
        np.testing.assert_array_equal(mask[rest], reference[rest])

    def test_a_nonfinite_score_carves_no_neighbour_through_the_default_smoothing(self, tmp_path):
        """With the default smoothing, the voxels around a NaN column are carved as in the same run with 0 there: the NaN adds
        no score to its neighbours' blur instead of spreading to them. A fixed cutoff and no slope limit keep the column's own
        smoothed value (which the run with 0 has and the NaN run has not) out of the comparison."""
        rng = np.random.default_rng(13)
        scores = rng.uniform(0, 100, size=(8, 8, 8)).astype(np.float32)
        zeroed = scores.copy()
        zeroed[0, 0, :] = 0.0
        scores[0, 0, :] = np.nan
        with pytest.warns(UserWarning, match="thresholding: scores contain"):
            mask = np.load(self._run_thresholding(tmp_path, "nonfinite", scores, threshold=50.0, max_slope_deg=90).mask_path)
        reference = np.load(self._run_thresholding(tmp_path, "zeroed", zeroed, threshold=50.0, max_slope_deg=90).mask_path)
        assert not mask[0, 0, :].any()
        rest = np.ones(mask.shape, dtype=bool)
        rest[0, 0, :] = False
        np.testing.assert_array_equal(mask[rest], reference[rest])


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
        # The setting is in metres: 1 m at 0.5 m voxels is a sigma of 2 voxels (1 if taken as voxels, 0.5 if divided twice).
        assert diag["score_smoothing_m"] == pytest.approx(1.0)
        assert diag["score_smoothing_sigma_voxels"] == pytest.approx(2.0)

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


def test_missing_occupancy_grid_is_an_error(tmp_path):
    """Without voxel_grid.npy the preprocessing run is incomplete: thresholding refuses it rather than rebuild the
    grid from a config that may describe other geometry."""
    from urbansolarcarver import thresholding
    from urbansolarcarver.errors import StageChainError
    pre = TestEdgeTaperPipeline()._run_preprocessing(tmp_path, "fb")
    manifest = json.loads(pre.manifest_path.read_text(encoding="utf-8"))
    (pre.out_dir / manifest["voxel_grid_path"]).unlink()
    cfg = _cube_config_2m(tmp_path / "fb")
    with pytest.raises(StageChainError, match="Re-run preprocessing"):
        thresholding(pre, cfg, tmp_path / "fb" / "thresholding")
    assert not (tmp_path / "fb" / "thresholding" / "mask.npy").exists()


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
