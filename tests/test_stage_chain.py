"""Stage chain checks: every manifest has a random run ID, every downstream
manifest records the run ID of the upstream manifest it was built from, and
every consumer refuses an upstream that was re-run since (daylight mode on a
10 m cube, CPU, no EPW needed). Manifest paths are relative to the manifest's
folder, so a run folder can be moved."""
import json
import shutil
import warnings
from pathlib import Path

import pytest


def _config(tmp_path, **overrides):
    from _stage_scene import daylight_cube_config
    return daylight_cube_config(tmp_path, **overrides)


def _run_pre_and_thr(tmp_path, conf, run_name="run"):
    from urbansolarcarver import preprocessing, thresholding
    run = tmp_path / run_name
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = preprocessing(conf, run / "preprocessing")
        thr = thresholding(pre, conf, run / "thresholding")
    return pre, thr


@pytest.fixture
def chain_with_rerun_preprocessing(tmp_path):
    """Thresholding output whose preprocessing folder was then overwritten by
    a run with a different ray length: same grid shape, different scores."""
    from urbansolarcarver import preprocessing
    first = _config(tmp_path)
    run = tmp_path / "run"
    pre, thr = _run_pre_and_thr(tmp_path, first)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        second = _config(tmp_path, ray_length=30.0)
        rerun = preprocessing(second, run / "preprocessing")
    assert rerun.volume_shape == pre.volume_shape and rerun.run_id != pre.run_id
    return second, thr


def test_thresholding_manifest_records_the_preprocessing_run_id(tmp_path):
    from urbansolarcarver.pydantic_schemas import ThresholdingManifest
    pre, thr = _run_pre_and_thr(tmp_path, _config(tmp_path))
    manifest = ThresholdingManifest.model_validate_json(thr.manifest_path.read_text())
    assert manifest.upstream_run_id == pre.run_id
    assert manifest.run_id == thr.run_id and thr.upstream_run_id == pre.run_id


def test_exporting_refuses_a_mask_from_an_older_preprocessing_run(tmp_path, chain_with_rerun_preprocessing):
    from urbansolarcarver import exporting
    from urbansolarcarver.errors import StageChainError
    conf, thr = chain_with_rerun_preprocessing
    with pytest.raises(StageChainError, match="preprocessing"):
        exporting(thr, conf, tmp_path / "run" / "exporting")


def test_massing_refuses_a_mask_from_an_older_preprocessing_run(tmp_path, chain_with_rerun_preprocessing):
    from urbansolarcarver import massing
    from urbansolarcarver.errors import StageChainError
    conf, thr = chain_with_rerun_preprocessing
    with pytest.raises(StageChainError, match="preprocessing"):
        massing(thr, conf, tmp_path / "run" / "massing")


def test_rerunning_preprocessing_with_identical_settings_still_refuses_the_old_mask(tmp_path):
    # Identical config twice: the settings are equal, the run IDs differ.
    from urbansolarcarver import exporting, preprocessing
    from urbansolarcarver.errors import StageChainError
    conf = _config(tmp_path)
    pre, thr = _run_pre_and_thr(tmp_path, conf)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        again = preprocessing(conf, tmp_path / "run" / "preprocessing")
    assert again.run_id != pre.run_id
    with pytest.raises(StageChainError, match="preprocessing"):
        exporting(thr, conf, tmp_path / "run" / "exporting")


def test_massing_manifest_records_the_thresholding_run_id(tmp_path):
    from urbansolarcarver import massing
    from urbansolarcarver.pydantic_schemas import MassingManifest
    conf = _config(tmp_path)
    _pre, thr = _run_pre_and_thr(tmp_path, conf)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = massing(thr, conf, tmp_path / "run" / "massing")
    manifest = MassingManifest.model_validate_json((result.out_dir / "manifest.json").read_text())
    assert manifest.upstream_run_id == thr.run_id


def test_a_moved_run_folder_still_exports(tmp_path):
    from urbansolarcarver import exporting
    conf = _config(tmp_path)
    _run_pre_and_thr(tmp_path, conf)
    shutil.move(str(tmp_path / "run"), str(tmp_path / "moved"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = exporting(tmp_path / "moved" / "thresholding", conf, tmp_path / "moved" / "exporting")
    assert result.export_path.is_file()
    manifest = json.loads((tmp_path / "moved" / "thresholding" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mask_path"] == "mask.npy"
    assert manifest["upstream_manifest"] == "../preprocessing/manifest.json"


def test_absolute_paths_still_load(tmp_path):
    from urbansolarcarver import exporting
    conf = _config(tmp_path)
    pre, thr = _run_pre_and_thr(tmp_path, conf)
    for stage_result in (pre, thr):
        manifest_path = stage_result.manifest_path
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key, value in data.items():
            if (key.endswith("_path") or key == "upstream_manifest") and isinstance(value, str):
                data[key] = str((manifest_path.parent / value).resolve())
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
    assert Path(json.loads(thr.manifest_path.read_text(encoding="utf-8"))["mask_path"]).is_absolute()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = exporting(thr, conf, tmp_path / "run" / "exporting")
    assert result.export_path.is_file()


def test_a_manifest_without_run_id_asks_for_a_rerun(tmp_path):
    from urbansolarcarver import thresholding
    from urbansolarcarver.errors import StageChainError
    conf = _config(tmp_path)
    pre, _thr = _run_pre_and_thr(tmp_path, conf)
    data = json.loads(pre.manifest_path.read_text(encoding="utf-8"))
    del data["run_id"]
    pre.manifest_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(StageChainError, match="re-run preprocessing"):
        thresholding(pre, conf, tmp_path / "run" / "thresholding")


def test_stored_path_is_relative_with_forward_slashes(tmp_path):
    from urbansolarcarver.api_core._stage_io import stored_path
    folder = tmp_path / "run" / "thresholding"
    assert stored_path(folder / "mask.npy", folder) == "mask.npy"
    assert stored_path(tmp_path / "run" / "preprocessing" / "manifest.json", folder) \
        == "../preprocessing/manifest.json"


def test_run_ids_are_new_every_time():
    from urbansolarcarver.api_core._stage_io import new_run_id
    first, second = new_run_id(), new_run_id()
    assert first != second and len(first) == 32
