"""Stage chain checks: every stage records the hash of the upstream manifest it
was built from, and every consumer refuses an upstream that has changed since
(daylight mode on a 10 m cube, CPU, no EPW needed)."""
import warnings

import numpy as np
import pytest
import trimesh


def _write_scene(tmp_path):
    from urbansolarcarver.io import save_mesh
    volume = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    surface = trimesh.Trimesh(
        vertices=np.array([[-3, -3, 0], [3, -3, 0], [3, 3, 0], [-3, 3, 0]], dtype=float),
        faces=[[0, 1, 2], [0, 2, 3]],
    )
    volume_path, surface_path = tmp_path / "vol.ply", tmp_path / "srf.ply"
    save_mesh(volume, str(volume_path))
    save_mesh(surface, str(surface_path))
    return volume_path, surface_path


def _config(tmp_path, **overrides):
    from urbansolarcarver.load_config import user_config
    volume_path, surface_path = _write_scene(tmp_path)
    settings = dict(
        max_volume_path=str(volume_path), test_surface_path=str(surface_path),
        out_dir=str(tmp_path / "run"), mode="daylight",
        voxel_size=1.0, grid_step=1.0, ray_length=50.0,
        min_voxels=1, min_face_count=1, device="cpu",
    )
    settings.update(overrides)
    return user_config(**settings)


@pytest.fixture
def chain_with_rerun_preprocessing(tmp_path):
    """Thresholding output whose preprocessing folder was then overwritten by
    a run with a different ray length: same grid shape, different scores."""
    from urbansolarcarver import preprocessing, thresholding
    first = _config(tmp_path)
    run = tmp_path / "run"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = preprocessing(first, run / "preprocessing")
        thr = thresholding(pre, first, run / "thresholding")
        second = _config(tmp_path, ray_length=30.0)
        rerun = preprocessing(second, run / "preprocessing")
    assert rerun.volume_shape == pre.volume_shape and rerun.hash != pre.hash
    return second, thr


def test_thresholding_manifest_records_the_preprocessing_hash(tmp_path):
    from urbansolarcarver import preprocessing, thresholding
    from urbansolarcarver.pydantic_schemas import ThresholdingManifest
    conf = _config(tmp_path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = preprocessing(conf, tmp_path / "run" / "preprocessing")
        thr = thresholding(pre, conf, tmp_path / "run" / "thresholding")
    manifest = ThresholdingManifest.model_validate_json(thr.manifest_path.read_text())
    assert manifest.upstream_hash == pre.hash


def test_exporting_refuses_a_mask_from_an_older_preprocessing_run(tmp_path, chain_with_rerun_preprocessing):
    from urbansolarcarver import exporting
    from urbansolarcarver.pydantic_schemas import UpstreamMismatchError
    conf, thr = chain_with_rerun_preprocessing
    with pytest.raises(UpstreamMismatchError, match="preprocessing"):
        exporting(thr, conf, tmp_path / "run" / "exporting")


def test_massing_refuses_a_mask_from_an_older_preprocessing_run(tmp_path, chain_with_rerun_preprocessing):
    from urbansolarcarver import massing
    from urbansolarcarver.pydantic_schemas import UpstreamMismatchError
    conf, thr = chain_with_rerun_preprocessing
    with pytest.raises(UpstreamMismatchError, match="preprocessing"):
        massing(thr, conf, tmp_path / "run" / "massing")


def test_massing_manifest_records_the_thresholding_hash(tmp_path):
    from urbansolarcarver import massing, preprocessing, thresholding
    from urbansolarcarver.pydantic_schemas import MassingManifest
    conf = _config(tmp_path, ground_floor_height=3.0, floor_height=3.0, min_plate_dimension=2.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = preprocessing(conf, tmp_path / "run" / "preprocessing")
        thr = thresholding(pre, conf, tmp_path / "run" / "thresholding")
        result = massing(thr, conf, tmp_path / "run" / "massing")
    manifest = MassingManifest.model_validate_json((result.out_dir / "manifest.json").read_text())
    assert manifest.upstream_hash == thr.hash
