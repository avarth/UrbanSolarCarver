"""Tests for the preprocessing stage: NaN/Inf score warnings (api_core/_diagnostics.py; score_statistics is tested in
test_util.py), the refusal of a test surface that gives no sample points, and the manifest a real run writes."""
import warnings
import pytest
import numpy as np


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


def _cube_and_test_surface_config(tmp_path, test_surface):
    """The conftest cube as the max volume, *test_surface* as the test surface, sampled every 2 m."""
    import trimesh
    from urbansolarcarver.load_config import user_config
    trimesh.creation.box(extents=(10.0, 10.0, 10.0)).export(str(tmp_path / "max_volume.ply"))
    test_surface.export(str(tmp_path / "test_surface.ply"))
    return user_config(max_volume_path=str(tmp_path / "max_volume.ply"), test_surface_path=str(tmp_path / "test_surface.ply"),
                       out_dir=str(tmp_path / "out"), mode="daylight", voxel_size=2.0, grid_step=2.0, device="cpu")


def _bent_panel():
    """A 6 m panel under the cube with one corner raised so its two triangles are 20 degrees apart (the tolerance is 5)."""
    import trimesh
    raised = -6.0 + 6.0 * np.tan(np.radians(20.0))
    return trimesh.Trimesh([[-3, -3, -6], [3, -3, -6], [3, 3, raised], [-3, 3, -6]], [[0, 1, 2], [0, 2, 3]], process=False)


def _zero_area_panel():
    import trimesh
    return trimesh.Trimesh([[0, 0, -6], [1, 0, -6], [2, 0, -6]], [[0, 1, 2]], process=False)


@pytest.mark.parametrize("test_surface", [_bent_panel, _zero_area_panel], ids=["non-planar", "zero area"])
def test_preprocessing_refuses_a_test_surface_that_gives_no_sample_points(tmp_path, test_surface):
    """Every component skipped leaves nothing to protect: the run stops before tracing and writes no manifest.

    sample_surface raises this error; the InputError after it in _run_preprocessing ("No sample points were generated")
    is not reached, since sample_surface never returns zero points.
    """
    from urbansolarcarver import preprocessing
    from urbansolarcarver.errors import InputError
    config = _cube_and_test_surface_config(tmp_path, test_surface())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")     # the warning that the component was skipped
        with pytest.raises(InputError, match="No points sampled from test surfaces"):
            preprocessing(config, tmp_path / "out")
    assert not (tmp_path / "out" / "manifest.json").exists()
    assert not (tmp_path / "out" / "scores.npy").exists()


def test_a_test_surface_smaller_than_the_sample_spacing_is_sampled_once(tmp_path):
    """A 1 cm square sampled every 2 m is not refused: it gets one sample point, on the square."""
    import trimesh
    from urbansolarcarver import preprocessing
    from urbansolarcarver.pydantic_schemas import PreprocessingManifest
    square = trimesh.Trimesh([[0.3, 0.3, -6], [0.31, 0.3, -6], [0.31, 0.31, -6], [0.3, 0.31, -6]], [[0, 1, 2], [0, 2, 3]],
                             process=False)
    result = preprocessing(_cube_and_test_surface_config(tmp_path, square), tmp_path / "out")
    assert PreprocessingManifest.model_validate_json(result.manifest_path.read_text()).sample_point_count == 1
    (point,) = np.load(tmp_path / "out" / "test_points.npy")
    # Within float32 rounding of the square's closed outline (the points are traced in float32).
    assert 0.3 - 1e-6 <= point[0] <= 0.31 + 1e-6 and 0.3 - 1e-6 <= point[1] <= 0.31 + 1e-6
    assert point[2] == pytest.approx(-6.0)


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
    assert m.grid_step == 2.0          # the sample spacing used, as given


def test_manifest_records_the_sample_spacing_used_when_unset(tmp_path, tmp_mesh_files):
    """An unset grid_step samples at half the voxel size, and the manifest says so."""
    from urbansolarcarver import preprocessing
    from urbansolarcarver.load_config import user_config
    from urbansolarcarver.pydantic_schemas import PreprocessingManifest
    vol_path, srf_path = tmp_mesh_files
    cfg = user_config(
        max_volume_path=str(vol_path), test_surface_path=str(srf_path),
        out_dir=str(tmp_path / "out"), mode="daylight",
        voxel_size=2.0, ray_length=50.0, device="cpu",
    )
    result = preprocessing(cfg, tmp_path / "out")
    assert PreprocessingManifest.model_validate_json(result.manifest_path.read_text()).grid_step == 1.0


def test_a_manifest_from_before_preprocessing_recorded_the_sample_spacing_reads_as_none():
    from urbansolarcarver.pydantic_schemas import PreprocessingManifest
    old_manifest = {"run_id": "r", "scores_path": "scores.npy", "scores_kind": "weighted_sum", "shape": [2, 2, 2],
                    "origin": [0.0, 0.0, 0.0], "voxel_size": 1.0, "mode": "daylight", "voxel_grid_path": "voxel_grid.npy",
                    "sample_point_count": 4, "footprint_path": "footprint.npy"}
    assert PreprocessingManifest.model_validate(old_manifest).grid_step is None
