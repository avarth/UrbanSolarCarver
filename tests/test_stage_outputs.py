"""Stage outputs after repeated and failed runs: a stage removes the outputs of
its previous run before it starts, writes its manifest last, and the run
report keeps the sections of every stage built on the same thresholding run."""
import importlib
import json
import warnings

import numpy as np
import pytest

from _stage_scene import daylight_cube_config


@pytest.fixture
def thresholded_run(tmp_path):
    """(config, thresholding result) for the daylight cube in tmp_path/run."""
    from urbansolarcarver import preprocessing, thresholding
    conf = daylight_cube_config(tmp_path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = preprocessing(conf, tmp_path / "run" / "preprocessing")
        thr = thresholding(pre, conf, tmp_path / "run" / "thresholding")
    return conf, thr


def _quietly(stage, *args):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return stage(*args)


class TestExporting:
    def test_writes_a_manifest_with_the_thresholding_run_id(self, tmp_path, thresholded_run):
        from urbansolarcarver import exporting
        from urbansolarcarver.pydantic_schemas import ExportingManifest
        conf, thr = thresholded_run
        result = _quietly(exporting, thr, conf, tmp_path / "run" / "exporting")
        manifest = ExportingManifest.model_validate_json(
            (result.out_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest.upstream_run_id == thr.run_id
        assert manifest.mesh_path == result.export_path.name

    def test_another_mesh_format_removes_the_previous_export(self, tmp_path, thresholded_run):
        from urbansolarcarver import exporting
        conf, thr = thresholded_run
        out = tmp_path / "run" / "exporting"
        _quietly(exporting, thr, conf, out)
        _quietly(exporting, thr, conf.model_copy(update={"final_mesh_format": "obj"}), out)
        assert sorted(p.name for p in out.glob("export.*")) == ["export.obj"]

    def test_a_failed_run_leaves_no_manifest_or_export(self, tmp_path, thresholded_run, monkeypatch):
        exporting_module = importlib.import_module("urbansolarcarver.api_core.exporting")
        conf, thr = thresholded_run
        out = tmp_path / "run" / "exporting"
        _quietly(exporting_module.exporting, thr, conf, out)

        def failing_save_mesh(*args, **kwargs):
            raise OSError("simulated write failure")

        monkeypatch.setattr(exporting_module, "save_mesh", failing_save_mesh)
        with pytest.raises(OSError, match="simulated write failure"):
            _quietly(exporting_module.exporting, thr, conf, out)
        assert not (out / "manifest.json").exists()
        assert not list(out.glob("export.*"))


def test_preprocessing_again_removes_plots_it_no_longer_writes(tmp_path):
    from urbansolarcarver import preprocessing
    out = tmp_path / "run" / "preprocessing"
    _quietly(preprocessing, daylight_cube_config(tmp_path, diagnostic_plots=True), out)
    assert (out / "diagnostics" / "score_histogram.png").is_file()
    _quietly(preprocessing, daylight_cube_config(tmp_path), out)
    assert not (out / "diagnostics" / "score_histogram.png").exists()


def test_failed_thresholding_diagnostics_leave_no_manifest(tmp_path, thresholded_run, monkeypatch):
    thresholding_module = importlib.import_module("urbansolarcarver.api_core.thresholding")
    conf, thr = thresholded_run

    def failing_statistics(*args, **kwargs):
        raise RuntimeError("simulated diagnostics failure")

    monkeypatch.setattr(thresholding_module, "score_statistics", failing_statistics)
    with pytest.raises(RuntimeError, match="simulated diagnostics failure"):
        _quietly(thresholding_module.thresholding, thr.upstream_manifest, conf, thr.out_dir)
    assert not thr.manifest_path.exists()


def test_failed_massing_leaves_no_manifest_or_plates(tmp_path, thresholded_run, monkeypatch):
    import trimesh
    from urbansolarcarver import massing
    conf, thr = thresholded_run
    out = tmp_path / "run" / "massing"
    first = _quietly(massing, thr, conf, out)
    assert first.n_plates > 0

    def failing_export(*args, **kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr(trimesh.Scene, "export", failing_export)
    with pytest.raises(OSError, match="simulated write failure"):
        _quietly(massing, thr, conf, out)
    assert not (out / "manifest.json").exists()
    assert not (out / "plates.json").exists()
    assert not (out / "plates.obj").exists()


class TestRunReport:
    def test_exporting_again_keeps_the_massing_section(self, tmp_path, thresholded_run):
        from urbansolarcarver import exporting, massing
        conf, thr = thresholded_run
        run = tmp_path / "run"
        _quietly(exporting, thr, conf, run / "exporting")
        _quietly(massing, thr, conf, run / "massing")
        _quietly(exporting, thr, conf, run / "exporting")
        report = (run / "run_report.md").read_text(encoding="utf-8")
        assert "## Massing" in report and "## Export" in report

    def test_massing_from_an_earlier_thresholding_run_is_left_out(self, tmp_path, thresholded_run):
        from urbansolarcarver import exporting, massing, thresholding
        conf, thr = thresholded_run
        run = tmp_path / "run"
        _quietly(massing, thr, conf, run / "massing")
        from urbansolarcarver.pydantic_schemas import ThresholdSpec
        stricter = conf.model_copy(update={"threshold": ThresholdSpec(method="carve_fraction", value=0.3)})
        rethresholded = _quietly(thresholding, thr.upstream_manifest, stricter, run / "thresholding")
        assert rethresholded.run_id != thr.run_id
        _quietly(exporting, rethresholded, stricter, run / "exporting")
        report = (run / "run_report.md").read_text(encoding="utf-8")
        assert "## Export" in report and "## Massing" not in report


def test_run_report_shows_the_settings_preprocessing_ran_with(tmp_path, thresholded_run):
    """Exporting with a config whose preprocessing settings differ from the
    run's: the report's configuration is the run's."""
    from urbansolarcarver import exporting
    conf, thr = thresholded_run
    _quietly(exporting, thr, conf.model_copy(update={"ray_length": 30.0}),
             tmp_path / "run" / "exporting")
    report = (tmp_path / "run" / "run_report.md").read_text(encoding="utf-8")
    assert "| Ray length | 50.0 m |" in report


def test_thresholding_manifest_records_the_resolved_settings(tmp_path, thresholded_run):
    """The config keeps the "None = auto" settings unset; the thresholding
    manifest records what they resolved to for this run."""
    from urbansolarcarver.pydantic_schemas import ThresholdingManifest
    conf, thr = thresholded_run
    assert conf.threshold is None and conf.score_smoothing is None and conf.max_slope_deg is None
    manifest = ThresholdingManifest.model_validate_json(thr.manifest_path.read_text(encoding="utf-8"))
    assert manifest.resolved_threshold.method == "carve_fraction"
    assert manifest.resolved_threshold.value == conf.carve_fraction
    assert manifest.score_smoothing_m == pytest.approx(1.1 * conf.voxel_size)
    assert manifest.max_slope_deg == 75.0


def test_thresholding_saves_the_scores_it_compares_with_the_cutoff(tmp_path, thresholded_run):
    from urbansolarcarver.pydantic_schemas import ThresholdingManifest
    conf, thr = thresholded_run
    folder = thr.out_dir
    manifest = ThresholdingManifest.model_validate_json((folder / "manifest.json").read_text(encoding="utf-8"))
    compared = np.load(folder / manifest.scores_compared_with_cutoff_path)
    mask = np.load(folder / manifest.mask_path)
    occupied = np.load(tmp_path / "run" / "preprocessing" / "voxel_grid.npy").astype(bool)
    summary = json.loads((folder / "diagnostics" / "diagnostic.json").read_text(encoding="utf-8"))
    kept_before_slope_limit = occupied & (compared <= summary["threshold_value"])
    assert compared.dtype == np.float32 and compared.shape == mask.shape
    assert not (mask & ~kept_before_slope_limit).any()
    assert int(kept_before_slope_limit.sum()) - int(mask.sum()) == summary["slope_limit_extra_voxels_removed"]


def test_without_carve_above_time_based_compares_the_raw_scores(tmp_path, example_epw_path):
    from urbansolarcarver import preprocessing, thresholding
    from urbansolarcarver.pydantic_schemas import ThresholdingManifest
    conf = daylight_cube_config(
        tmp_path, mode="time-based", threshold=0, carve_above=False, epw_path=str(example_epw_path),
        start_month=12, start_day=21, start_hour=10, end_month=12, end_day=21, end_hour=14)
    pre = _quietly(preprocessing, conf, tmp_path / "run" / "preprocessing")
    thr = _quietly(thresholding, pre, conf, tmp_path / "run" / "thresholding")
    manifest = ThresholdingManifest.model_validate_json(thr.manifest_path.read_text(encoding="utf-8"))
    compared = np.load(thr.out_dir / manifest.scores_compared_with_cutoff_path)
    raw_scores = np.load(pre.out_dir / "scores.npy").reshape(compared.shape)
    occupied = np.load(pre.out_dir / "voxel_grid.npy").astype(bool)
    assert np.array_equal(compared[occupied], raw_scores[occupied].astype(np.float32))


def test_thresholding_result_carries_its_issues(tmp_path, thresholded_run):
    from urbansolarcarver import thresholding
    from urbansolarcarver.pydantic_schemas import ThresholdSpec
    conf, thr = thresholded_run
    keep_everything = conf.model_copy(update={"threshold": ThresholdSpec(method="cutoff", value=1e9)})
    result = _quietly(thresholding, thr.upstream_manifest, keep_everything, thr.out_dir)
    assert [i.code for i in result.issues] == ["nothing_carved"]


def test_preprocessing_reports_an_empty_footprint_projection(tmp_path, monkeypatch):
    from urbansolarcarver import floor_plates, preprocessing
    monkeypatch.setattr(floor_plates, "footprint_polygons", lambda mesh, offset_xy: [])
    result = _quietly(preprocessing, daylight_cube_config(tmp_path), tmp_path / "run" / "preprocessing")
    assert "footprint_unreadable" in [issue.code for issue in result.issues]


def test_ray_batch_size_reaches_the_carvers(tmp_path, monkeypatch):
    from urbansolarcarver import carving, preprocessing
    received = []
    resolve_batch_size = carving._resolve_batch_size

    def recording_resolve_batch_size(device, *, ray_batch_size):
        received.append(ray_batch_size)
        return resolve_batch_size(device, ray_batch_size=ray_batch_size)

    monkeypatch.setattr(carving, "_resolve_batch_size", recording_resolve_batch_size)
    _quietly(preprocessing, daylight_cube_config(tmp_path, ray_batch_size=7),
             tmp_path / "run" / "preprocessing")
    assert received and set(received) == {7}
