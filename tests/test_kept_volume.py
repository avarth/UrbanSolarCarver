"""A kept volume (``kept_volume_path``): the occupied voxels whose centres lie inside it are never carved, and the
threshold is taken over the other voxels only (design/base-height.md). Daylight mode on the chain test box, CPU."""
import json

import numpy as np
import pytest
import trimesh

from _chain_scene import chain_scene, copy_preprocessing_with_occupancy, daylight_on_east, daylight_on_south
from urbansolarcarver import preprocessing, thresholding
from urbansolarcarver.chain_config import CRITERION_KEYS
from urbansolarcarver.stage_settings import stages_to_rerun

BASE = 8.0      # the kept box ends 8 m above the ground; the max volume is a 30 x 12 x 20 m box from z = 0


def _kept_box(tmp_path, top=BASE, name="kept.ply"):
    box = trimesh.creation.box(extents=(60.0, 40.0, top + 10.0))
    box.apply_translation([0.0, 0.0, top - (top + 10.0) / 2])    # from 10 m below the ground up to *top*
    path = tmp_path / name
    box.export(path)
    return path


def _centre_z(pre_dir, shape):
    manifest = json.loads((pre_dir / "manifest.json").read_text())
    k = np.arange(shape[2])
    return manifest["origin"][2] + (k + 0.5) * manifest["voxel_size"]


def _kept_cells(pre, top=BASE):
    occ = np.load(pre.out_dir / json.loads((pre.out_dir / "manifest.json").read_text())["voxel_grid_path"]).astype(bool)
    z = _centre_z(pre.out_dir, occ.shape)
    return occ & (z < top - 1e-6)[None, None, :], occ      # a centre on the top face is outside


@pytest.fixture
def scene(tmp_path):
    return chain_scene(tmp_path)


def test_the_kept_voxels_stay_whatever_the_cutoff(scene, tmp_path):
    conf = scene.config(tmp_path / "a", kept_volume_path=_kept_box(tmp_path), threshold=0.0)
    pre = preprocessing(conf, tmp_path / "a/pre")
    with pytest.warns(UserWarning, match="everything carved"):     # judged on the voxels above the base
        thr = thresholding(pre, conf, tmp_path / "a/thr")
    mask = np.load(thr.mask_path)
    kept, occ = _kept_cells(pre)
    assert kept.any() and (mask & ~kept).sum() < (occ & ~kept).sum()
    assert not (kept & ~mask).any()


def test_the_cutoff_is_taken_over_the_voxels_above_the_base(scene, tmp_path):
    # Without carve_above, the slope limit and smoothing, the result is the base plus what thresholding keeps
    # of the other voxels alone.
    plain = dict(carve_fraction=0.4, carve_above=False, max_slope_deg=90.0, score_smoothing=0.0)
    conf = scene.config(tmp_path / "a", kept_volume_path=_kept_box(tmp_path), **plain)
    pre = preprocessing(conf, tmp_path / "a/pre")
    mask = np.load(thresholding(pre, conf, tmp_path / "a/thr").mask_path)
    kept, occ = _kept_cells(pre)
    reference_pre = copy_preprocessing_with_occupancy(pre, occ & ~kept, tmp_path / "ref/pre")
    reference = np.load(thresholding(reference_pre, scene.config(tmp_path / "ref", **plain), tmp_path / "ref/thr").mask_path)
    assert np.array_equal(mask, reference | kept)


@pytest.mark.parametrize("values", [dict(carve_above=True), dict(carve_above=True, max_slope_deg=30.0)])
def test_carve_above_and_the_slope_limit_keep_the_base(scene, tmp_path, values):
    conf = scene.config(tmp_path / "a", kept_volume_path=_kept_box(tmp_path), carve_fraction=0.6, **values)
    pre = preprocessing(conf, tmp_path / "a/pre")
    thr = thresholding(pre, conf, tmp_path / "a/thr")
    mask = np.load(thr.mask_path)
    kept, occ = _kept_cells(pre)
    assert not (kept & ~mask).any() and not (mask & ~occ).any()
    assert (occ & ~mask).any()


def test_a_larger_carve_amount_never_keeps_more(scene, tmp_path):
    path = _kept_box(tmp_path)
    masks = []
    for fraction in (0.2, 0.5, 0.8):
        conf = scene.config(tmp_path / f"f{fraction}", kept_volume_path=path, carve_fraction=fraction)
        pre = preprocessing(conf, tmp_path / f"f{fraction}/pre")
        masks.append(np.load(thresholding(pre, conf, tmp_path / f"f{fraction}/thr").mask_path))
    assert not (masks[1] & ~masks[0]).any() and not (masks[2] & ~masks[1]).any()


def test_every_criterion_of_a_chain_keeps_the_base(scene, tmp_path):
    path = _kept_box(tmp_path)
    c1 = scene.config(tmp_path / "c1", kept_volume_path=path, carve_fraction=0.7)
    pre1 = preprocessing(c1, tmp_path / "c1/pre")
    thr1 = thresholding(pre1, c1, tmp_path / "c1/thr")
    c2 = scene.config(tmp_path / "c2", test_surface_path=scene.east, kept_volume_path=path, carve_fraction=0.7)
    pre2 = preprocessing(c2, tmp_path / "c2/pre")
    mask2 = np.load(thresholding(pre2, c2, tmp_path / "c2/thr", after=thr1).mask_path)
    kept, _ = _kept_cells(pre2)
    assert not (kept & ~mask2).any()


def test_a_kept_volume_over_everything_leaves_nothing_to_decide(scene, tmp_path):
    conf = scene.config(tmp_path / "a", kept_volume_path=_kept_box(tmp_path, top=30.0), carve_fraction=0.5)
    pre = preprocessing(conf, tmp_path / "a/pre")
    with pytest.warns(UserWarning, match="nothing left to decide"):
        thr = thresholding(pre, conf, tmp_path / "a/thr")
    _, occ = _kept_cells(pre)
    assert np.array_equal(np.load(thr.mask_path), occ)


def test_the_summary_reports_the_kept_and_the_decided_voxels(scene, tmp_path):
    conf = scene.config(tmp_path / "a", kept_volume_path=_kept_box(tmp_path), carve_fraction=0.5)
    pre = preprocessing(conf, tmp_path / "a/pre")
    thr = thresholding(pre, conf, tmp_path / "a/thr")
    diag = json.loads((thr.out_dir / "diagnostics/diagnostic.json").read_text())
    kept, occ = _kept_cells(pre)
    mask = np.load(thr.mask_path)
    assert diag["kept_volume"]["voxels"] == int(kept.sum())
    assert diag["kept_volume"]["volume_m3"] == pytest.approx(kept.sum() * 1.0)
    assert 0.0 < diag["kept_volume"]["score_mass_share"] < 1.0
    assert diag["kept_volume"]["decided_voxels"] == int((occ & ~kept).sum())
    assert diag["kept_volume"]["decided_voxels_kept"] == int((mask & ~kept).sum())
    plain = scene.config(tmp_path / "b", carve_fraction=0.5)
    pre_b = preprocessing(plain, tmp_path / "b/pre")
    assert json.loads((thresholding(pre_b, plain, tmp_path / "b/thr").out_dir
                       / "diagnostics/diagnostic.json").read_text())["kept_volume"] is None


def test_the_kept_volume_is_shared_and_reruns_thresholding_only(scene, tmp_path):
    assert "kept_volume_path" not in CRITERION_KEYS
    before = scene.config(tmp_path / "a")
    after = scene.config(tmp_path / "a", kept_volume_path=_kept_box(tmp_path))
    assert stages_to_rerun(before, after, ["exporting", "massing"]) == ["thresholding", "exporting", "massing"]


def test_overlapping_bodies_of_the_kept_volume_keep_their_overlap(scene, tmp_path):
    # Two boxes over the west and east halves that overlap in the middle: the middle stays kept.
    west = trimesh.creation.box(bounds=[[-30, -20, -10], [5, 20, BASE]])
    east = trimesh.creation.box(bounds=[[-5, -20, -10], [30, 20, BASE]])
    path = tmp_path / "two.ply"
    trimesh.util.concatenate([west, east]).export(path)
    conf = scene.config(tmp_path / "a", kept_volume_path=path, threshold=0.0)
    pre = preprocessing(conf, tmp_path / "a/pre")
    with pytest.warns(UserWarning, match="everything carved"):
        mask = np.load(thresholding(pre, conf, tmp_path / "a/thr").mask_path)
    kept, _ = _kept_cells(pre)
    assert not (kept & ~mask).any()


def test_a_chain_config_gives_its_kept_volume_to_every_criterion_and_its_run_keeps_it(scene, tmp_path):
    import yaml

    from urbansolarcarver.api import run_chain
    from urbansolarcarver.chain_config import load_chain
    kept_path = _kept_box(tmp_path)
    chain = scene.chain_config(tmp_path / "chain", [daylight_on_south(0.6), daylight_on_east(0.6)])
    path = tmp_path / "chain" / "chain.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["kept_volume_path"] = str(kept_path)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    chain = load_chain(str(path))
    assert all(criterion.config.kept_volume_path == str(kept_path) for criterion in chain.criteria)
    result = run_chain(chain, produce=["thresholding"])
    last = result.criteria[-1]
    diag = json.loads((last.thresholding.out_dir / "diagnostics/diagnostic.json").read_text())
    assert diag["kept_volume"]["voxels"] > 0
