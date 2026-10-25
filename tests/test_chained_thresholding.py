"""Thresholding after a previous criterion (``after=``): the criterion decides
only among the voxels the previous one kept (daylight mode on a box with two
facades, CPU, no EPW needed)."""
import json
import re

import numpy as np
import pytest

from _chain_scene import chain_scene, copy_preprocessing_with_occupancy
from urbansolarcarver import exporting, preprocessing, thresholding
from urbansolarcarver.errors import StageChainError


def _first_criterion(s, tmp_path, name="c1", **values):
    conf = s.config(tmp_path / name, test_surface_path=s.south, **values)
    pre = preprocessing(conf, tmp_path / name / "pre")
    return pre, conf, thresholding(pre, conf, tmp_path / name / "thr")


def test_a_criterion_after_another_equals_thresholding_on_its_kept_voxels(tmp_path):
    # Reference: the same thresholding with the preprocessing occupancy replaced by criterion 1's mask.
    s = chain_scene(tmp_path)
    _, _, thr1 = _first_criterion(s, tmp_path, carve_fraction=0.6)
    c2 = s.config(tmp_path / "c2", test_surface_path=s.east, carve_fraction=0.5)
    pre2 = preprocessing(c2, tmp_path / "c2/pre")
    thr2 = thresholding(pre2, c2, tmp_path / "c2/thr", after=thr1)
    ref_pre = copy_preprocessing_with_occupancy(pre2, np.load(thr1.mask_path), tmp_path / "ref/pre")
    ref = thresholding(ref_pre, c2, tmp_path / "ref/thr")
    assert np.array_equal(np.load(thr2.mask_path), np.load(ref.mask_path))
    assert not (np.load(thr2.mask_path) & ~np.load(thr1.mask_path)).any()
    manifest = json.loads((thr2.out_dir / "manifest.json").read_text())
    assert manifest["after_run_id"] == thr1.run_id and manifest["after_manifest"].endswith("manifest.json")
    diag = json.loads((thr2.out_dir / "diagnostics/diagnostic.json").read_text())
    assert diag["after_run_id"] == thr1.run_id
    assert diag["voxels_at_start"] == int(np.load(thr1.mask_path).sum()) == diag["voxels_occupied"]


def test_after_accepts_a_folder_and_a_manifest_path(tmp_path):
    s = chain_scene(tmp_path)
    _, _, thr1 = _first_criterion(s, tmp_path, carve_fraction=0.6)
    c2 = s.config(tmp_path / "c2", test_surface_path=s.east, carve_fraction=0.5)
    pre2 = preprocessing(c2, tmp_path / "c2/pre")
    by_result = thresholding(pre2, c2, tmp_path / "c2/a", after=thr1)
    by_folder = thresholding(pre2, c2, tmp_path / "c2/b", after=thr1.out_dir)
    by_manifest = thresholding(pre2, c2, tmp_path / "c2/c", after=thr1.manifest_path)
    expected = np.load(by_result.mask_path)
    assert np.array_equal(np.load(by_folder.mask_path), expected)
    assert np.array_equal(np.load(by_manifest.mask_path), expected)


def test_a_run_without_after_records_no_previous_criterion(tmp_path):
    s = chain_scene(tmp_path)
    _, _, thr1 = _first_criterion(s, tmp_path, carve_fraction=0.6)
    manifest = json.loads(thr1.manifest_path.read_text())
    assert manifest["after_manifest"] is None and manifest["after_run_id"] is None
    diag = json.loads((thr1.out_dir / "diagnostics/diagnostic.json").read_text())
    assert diag["after_run_id"] is None and diag["voxels_at_start"] == diag["voxels_occupied"]


def test_after_a_run_on_another_grid_is_refused(tmp_path):     # voxel size 1.0 vs 2.0
    s = chain_scene(tmp_path)
    _, _, thr1 = _first_criterion(s, tmp_path, carve_fraction=0.6)
    c2 = s.config(tmp_path / "c2", test_surface_path=s.east, voxel_size=2.0, grid_step=2.0)
    pre2 = preprocessing(c2, tmp_path / "c2/pre")
    with pytest.raises(StageChainError, match="voxel size") as refused:
        thresholding(pre2, c2, tmp_path / "c2/thr", after=thr1)
    assert "share the max volume, context, terrain, voxel size and margin" in str(refused.value)


def test_after_a_run_on_another_occupancy_is_refused(tmp_path):
    s = chain_scene(tmp_path)
    _, _, thr1 = _first_criterion(s, tmp_path, carve_fraction=0.6)
    c2 = s.config(tmp_path / "c2", test_surface_path=s.east)
    pre2 = preprocessing(c2, tmp_path / "c2/pre")
    half = np.zeros(np.load(thr1.mask_path).shape, dtype=bool)
    half[: half.shape[0] // 2] = True
    other = copy_preprocessing_with_occupancy(pre2, half, tmp_path / "c2/other_pre")
    with pytest.raises(StageChainError, match="maximum volume"):
        thresholding(other, c2, tmp_path / "c2/thr", after=thr1)


def test_nothing_left_to_carve_gives_an_empty_mask_and_an_issue(tmp_path):
    s = chain_scene(tmp_path)
    # A cutoff of 0 carves every voxel that has any score in criterion 1.
    with pytest.warns(UserWarning, match="everything carved"):
        _, _, thr1_all_carved = _first_criterion(s, tmp_path, threshold=0.0)
    assert not np.load(thr1_all_carved.mask_path).any()
    c2 = s.config(tmp_path / "c2", test_surface_path=s.east, carve_fraction=0.5)
    pre2 = preprocessing(c2, tmp_path / "c2/pre")
    with pytest.warns(UserWarning, match="kept no voxel"):
        thr2 = thresholding(pre2, c2, tmp_path / "c2/thr", after=thr1_all_carved)
    assert not np.load(thr2.mask_path).any()
    assert [issue.code for issue in thr2.issues] == ["nothing_left_to_carve"]
    assert thr2.voxels_kept == 0 and thr2.voxels_removed == 0
    diag = json.loads((thr2.out_dir / "diagnostics/diagnostic.json").read_text())
    assert diag["voxels_at_start"] == 0 and diag["voxels_kept"] == 0
    assert (thr2.out_dir / "manifest.json").is_file()


def test_a_stale_previous_criterion_refuses_the_chain_downstream(tmp_path):
    # Re-run criterion 1's thresholding after criterion 2's: exporting from criterion 2 must refuse.
    s = chain_scene(tmp_path)
    pre1, c1, thr1 = _first_criterion(s, tmp_path, carve_fraction=0.6)
    c2 = s.config(tmp_path / "c2", test_surface_path=s.east, carve_fraction=0.5)
    pre2 = preprocessing(c2, tmp_path / "c2/pre")
    thr2 = thresholding(pre2, c2, tmp_path / "c2/thr", after=thr1)
    exporting(thr2, c2, tmp_path / "exp_before")
    rerun = thresholding(pre1, c1, thr1.out_dir)
    assert rerun.run_id != thr1.run_id
    with pytest.raises(StageChainError, match=re.escape(str(thr1.out_dir))) as refused:
        exporting(thr2, c2, tmp_path / "exp")
    assert "was re-run after this one" in str(refused.value)
