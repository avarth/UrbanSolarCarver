"""End-to-end carving checks on procedural urban typologies.

Each test runs the full three-stage pipeline on a small scene (2 m voxels,
CPU) and checks the result against an independent reference (oracle.py)
or against an invariant the carving must satisfy whatever the geometry.
The randomized version of the same checks lives in montecarlo.py.
"""
from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest
import torch

import cases
import oracle
from typologies import TYPOLOGIES, SceneSpec, build

BINARY_MODES = ("tilted_plane", "time-based")


@pytest.fixture(scope="module")
def epw():
    from _epw import resolve_epw
    path = resolve_epw()
    if not path:
        pytest.skip("No EPW file found")
    return path


def _must_carve(run, epw):
    """Reference set of occupied voxels the mode must remove (zero tolerance)."""
    if run.cfg["mode"] == "tilted_plane":
        return oracle.column_above(oracle.tilted_hits(run))
    minutes = 60 // run.cfg.get("sun_steps_per_hour", 12)
    return oracle.time_based_hits(run, epw, minutes=minutes)


# ----------------------------------------------------------------- reference agreement
@pytest.mark.parametrize("typology", TYPOLOGIES)
@pytest.mark.parametrize("mode", BINARY_MODES)
def test_binary_modes_match_reference(tmp_path, epw, typology, mode):
    """Every voxel on a violating ray (or above a plane) is carved, and
    nothing else is: the protected facades' own voxels included."""
    run = cases.run(build(SceneSpec(typology, seed=7)), tmp_path, epw, mode)
    must = _must_carve(run, epw)
    assert oracle.soundness_violations(run, must) == 0
    unexplained, carved = oracle.unexplained_carving(run, must)
    assert carved > 0
    assert unexplained == 0


@pytest.mark.parametrize("typology", ["courtyard", "freeform", "passage", "irregular"])
@pytest.mark.parametrize("mode", ["benefit", "daylight"])
def test_weighted_scores_match_reference(tmp_path, epw, typology, mode):
    """Raw scores on occupied voxels agree with the independent marcher.

    The marcher misses corner clips, so it may only under-count: USC must
    not score a voxel below it (beyond float32 accumulation error and the odd
    ray passing within rounding of a voxel edge), and the excess (clips)
    stays small. See oracle.score_agreement.
    """
    run = cases.run(build(SceneSpec(typology, seed=7)), tmp_path, epw, mode)
    agree = oracle.score_agreement(run)
    assert agree["ref_mass"] > 0
    assert agree["shortfall_voxels"] <= 2
    assert agree.get("excess_fine", agree["excess"]) < 0.10


@pytest.mark.parametrize("mode", ["tilted_plane", "time-based", "benefit", "daylight"])
def test_protected_floors_not_carved_by_own_rays(tmp_path, epw, mode):
    """A podium whose own lower facades are the only protected surfaces:
    every ray leaves the mass, so nothing may be carved or scored."""
    spec = SceneSpec("podium", neighbours=False, own_h=6.0)
    run = cases.run(build(spec), tmp_path, epw, mode)
    assert float(run.scores[run.occ].max()) == 0.0
    if mode in BINARY_MODES:
        assert run.mask[run.occ].all()


@pytest.mark.parametrize("typology", ["courtyard", "towers", "freeform", "passage"])
@pytest.mark.parametrize("mode", ["benefit", "daylight"])
def test_protect_share_matches_reference(tmp_path, epw, typology, mode):
    """protect_share carves every voxel on a ray from a test point to a
    protected patch, and nothing else (as for the binary modes)."""
    run = cases.run(build(SceneSpec(typology, seed=7)), tmp_path, epw, mode,
                    threshold="protect_share", protect_share=0.3)
    must = oracle.protected_hits(run, 0.3)
    assert oracle.soundness_violations(run, must) == 0
    unexplained, carved = oracle.unexplained_carving(run, must)
    assert carved > 0
    assert unexplained == 0
    assert run.diag("thr")["protected_weight_share"] >= 0.3


def test_protect_share_nested(tmp_path, epw):
    """Protecting more sky never keeps a voxel that protecting less removed."""
    from urbansolarcarver.api_core.thresholding import thresholding
    from urbansolarcarver.load_config import user_config

    run = cases.run(build(SceneSpec("towers")), tmp_path / "a", epw, "benefit",
                    threshold="protect_share")
    masks = []
    for share in (0.0, 0.1, 0.3, 0.6, 1.0):
        cfg = dict(run.cfg, protect_share=share)
        thr = thresholding(run.pre, user_config(**cfg), tmp_path / f"t{share}")
        masks.append(np.load(thr.mask_path))
    assert np.array_equal(masks[0], run.occ)  # nothing protected, nothing carved
    for loose, tight in zip(masks, masks[1:]):
        assert not (tight & ~loose).any()
    assert masks[-1].sum() < masks[1].sum()


# ----------------------------------------------------------------- thresholding
def test_threshold_ignores_empty_cells(tmp_path, epw):
    """The mask over the building must not depend on scores stored in air."""
    from urbansolarcarver.api_core.thresholding import thresholding
    from urbansolarcarver.load_config import user_config

    run = cases.run(build(SceneSpec("courtyard")), tmp_path / "a", epw, "benefit")
    rng = np.random.default_rng(0)
    noisy = run.scores.copy()
    noisy[~run.occ] = rng.uniform(0, 10 * float(run.scores.max()), (~run.occ).sum())
    np.save(run.pre / "scores.npy", noisy)
    thr = thresholding(run.pre, user_config(**run.cfg), tmp_path / "b")
    assert np.array_equal(np.load(thr.mask_path).reshape(run.shape), run.mask)


@pytest.mark.parametrize("method", ["carve_fraction", "headtail"])
def test_mask_is_false_on_empty_cells(tmp_path, epw, method):
    run = cases.run(build(SceneSpec("rows")), tmp_path, epw, "benefit", threshold=method)
    assert not run.mask[~run.occ].any()


def test_carve_fraction_nested(tmp_path, epw):
    """Carving more never keeps a voxel that carving less removed."""
    from urbansolarcarver.api_core.thresholding import thresholding
    from urbansolarcarver.load_config import user_config

    run = cases.run(build(SceneSpec("towers")), tmp_path / "a", epw, "benefit")
    masks = []
    for cf in (0.3, 0.5, 0.7, 0.9):
        cfg = dict(run.cfg, carve_fraction=cf)
        thr = thresholding(run.pre, user_config(**cfg), tmp_path / f"t{cf}")
        masks.append(np.load(thr.mask_path))
    for loose, tight in zip(masks, masks[1:]):
        assert not (tight & ~loose).any()
        assert tight.sum() < loose.sum()


def test_tilted_angle_monotone(tmp_path, epw):
    """A steeper plane forbids less: kept(30°) ⊆ kept(45°) ⊆ kept(60°)."""
    scene = build(SceneSpec("courtyard"))
    kept = [cases.run(scene, tmp_path / str(a), epw, "tilted_plane",
                      tilted_plane_angle_deg=a).mask for a in (30.0, 45.0, 60.0)]
    for low, high in zip(kept, kept[1:]):
        assert not (low & ~high).any()


# ----------------------------------------------------------------- carve_above
@pytest.mark.parametrize("typology", ["courtyard", "towers", "freeform", "passage"])
@pytest.mark.parametrize("mode", ["benefit", "daylight"])
@pytest.mark.parametrize("carve_above", [False, True])
def test_recovered_sky_matches_reference(tmp_path, epw, typology, mode, carve_above):
    """The share reported is at least the one asked for (above it only by
    rays that clear at the same cut), and an independent recount on the
    final mask agrees; it can differ slightly because the stepped
    reference misses rays that only clip a voxel corner."""
    run = cases.run(build(SceneSpec(typology, seed=7)), tmp_path, epw, mode,
                    threshold="recovered_sky", recovered_sky=0.4, carve_above=carve_above)
    d = run.diag("thr")
    assert d["threshold_method"] == "recovered_sky" and d["max_slope_deg"] is None
    assert 0.4 <= d["recovered_sky_actual"] <= 0.46
    assert abs(oracle.recovered_share(run, run.occ & run.mask) - d["recovered_sky_actual"]) < 0.03


@pytest.mark.parametrize("typology", ["courtyard", "towers", "irregular"])
def test_recovered_sky_full_share_clears_every_ray(tmp_path, epw, typology):
    """With share 1, no kept voxel stands on any obstructed ray (the stepped
    reference sees a subset of the exact rays' voxels, so this is exact)."""
    run = cases.run(build(SceneSpec(typology, seed=7)), tmp_path, epw, "benefit",
                    threshold="recovered_sky", recovered_sky=1.0, carve_above=True)
    assert run.diag("thr")["recovered_sky_actual"] == 1.0
    assert oracle.recovered_share(run, run.occ & run.mask) == 1.0


def test_recovered_sky_nested(tmp_path, epw):
    """Recovering more never keeps a voxel that recovering less removed."""
    from urbansolarcarver.api_core.thresholding import thresholding
    from urbansolarcarver.load_config import user_config

    run = cases.run(build(SceneSpec("towers")), tmp_path / "a", epw, "benefit",
                    threshold="recovered_sky", carve_above=True)
    masks = []
    for share in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        thr = thresholding(run.pre, user_config(**dict(run.cfg, recovered_sky=share)),
                           tmp_path / f"t{share}")
        masks.append(np.load(thr.mask_path))
    assert np.array_equal(masks[0], run.occ)
    for loose, tight in zip(masks, masks[1:]):
        assert not (tight & ~loose).any()
    assert masks[-1].sum() < masks[1].sum()


def test_recovered_sky_without_warp(tmp_path, epw, monkeypatch):
    """The fixed-step fallback gives the same share and nearly the same mask."""
    import urbansolarcarver.carving as C
    scene = build(SceneSpec("courtyard"))
    over = dict(threshold="recovered_sky", recovered_sky=0.5)
    exact = cases.run(scene, tmp_path / "w", epw, "daylight", **over)
    monkeypatch.setattr(C, "dda_backend_available", lambda device: False)
    fallback = cases.run(scene, tmp_path / "f", epw, "daylight", **over)
    assert fallback.diag("thr")["recovered_sky_actual"] >= 0.5
    differ = (exact.mask != fallback.mask).sum() / exact.occ.sum()
    assert differ < 0.05


@pytest.mark.parametrize("typology", ["courtyard", "freeform", "rows"])
def test_carve_fraction_with_carve_above_leaves_no_spires(tmp_path, epw, typology):
    """With a 45 degree slope limit (one voxel of rise per voxel), no kept
    column stands 4 or more voxels above the median of its 5 x 5
    neighbourhood. (At 2 m voxels the default 75 degrees allows about 3.7
    voxels per column, too much for this criterion.)"""
    from numpy.lib.stride_tricks import sliding_window_view
    run = cases.run(build(SceneSpec(typology, seed=7)), tmp_path, epw, "benefit",
                    threshold="carve_fraction", carve_fraction=0.4, carve_above=True,
                    max_slope_deg=45.0)
    z = np.arange(run.shape[2])
    kept = run.mask.any(axis=2)
    h = np.where(kept, (run.mask * (z + 1)).max(axis=2), np.nan)
    med = np.nanmedian(sliding_window_view(np.pad(h, 2, constant_values=np.nan), (5, 5)),
                       axis=(-2, -1))
    assert run.diag("thr")["max_slope_deg"] == 45.0
    assert not ((h - med) >= 4)[kept].any()


@pytest.mark.parametrize("min_run", [1, 3])
@pytest.mark.parametrize("mode", ["time-based", "benefit", "benefit-protect"])
def test_carve_above_leaves_no_floating_mass(tmp_path, epw, mode, min_run):
    over = {}
    if mode == "benefit-protect":
        mode, over = "benefit", dict(threshold="protect_share")
    run = cases.run(build(SceneSpec("courtyard")), tmp_path, epw, mode,
                    carve_above=True, carve_above_min_consecutive=min_run, **over)
    kept = oracle.kept_grid(run)
    assert oracle.floating_voxels(kept, run.occ, min_run) == 0
    assert not (kept & ~run.mask).any()   # only removes: never undoes the constraint


def test_carve_above_keeps_bridge_over_existing_passage(tmp_path, epw):
    """Air under a bridge is not carved mass and must not trigger carve-above.

    Only the plot's own facades are protected and every ray leaves the mass,
    so nothing is carved; carve_above must then remove nothing either,
    although the mask is False in the passage below the bridge.
    """
    run = cases.run(build(SceneSpec("passage", neighbours=False, own_h=3.0)),
                    tmp_path, epw, "tilted_plane", carve_above=True)
    assert run.mask[run.occ].all()
    assert np.array_equal(oracle.kept_grid(run), run.occ)
    assert run.diag("thr")["carve_above_extra_voxels_removed"] == 0


# ----------------------------------------------------------------- invariances
@pytest.mark.parametrize("mode", ["time-based", "benefit"])
def test_georeferenced_coordinates(tmp_path, epw, mode):
    """Moving the scene to UTM-scale coordinates must not change the carve."""
    base = SceneSpec("irregular", seed=11)
    local = cases.run(build(base), tmp_path / "local", epw, mode)
    far = cases.run(build(replace(base, offset=(500123.4, 4500456.7, 35.0))),
                    tmp_path / "utm", epw, mode)
    assert local.shape == far.shape
    assert np.array_equal(local.occ, far.occ)
    differ = int((local.mask ^ far.mask).sum())
    assert differ <= 0.002 * local.occ.sum()
    if mode == "time-based":
        assert oracle.soundness_violations(far, _must_carve(far, epw)) == 0


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA unavailable")
@pytest.mark.parametrize("mode", ["tilted_plane", "time-based", "benefit"])
def test_cpu_cuda_parity(tmp_path, epw, mode):
    scene = build(SceneSpec("freeform"))
    cpu = cases.run(scene, tmp_path / "cpu", epw, mode, device="cpu")
    gpu = cases.run(scene, tmp_path / "gpu", epw, mode, device="cuda")
    if mode in BINARY_MODES:
        assert np.array_equal(cpu.mask, gpu.mask)
    else:
        np.testing.assert_allclose(gpu.scores, cpu.scores, rtol=1e-4, atol=1e-3)
        assert np.array_equal(np.load(cpu.pre / "patch_rank.npy"),
                              np.load(gpu.pre / "patch_rank.npy"))
        with np.load(cpu.pre / "recovery_rays.npz") as c, np.load(gpu.pre / "recovery_rays.npz") as g:
            assert np.array_equal(c["voxel_rank"], g["voxel_rank"])


@pytest.mark.parametrize("mode", ["daylight", "time-based"])
def test_threaded_cpu_accumulation_matches_sequential(tmp_path, epw, mode, monkeypatch):
    """Warp's CPU atomic_add is not atomic across threads: threaded batches
    must not share an accumulation buffer (lost updates, run-to-run noise)."""
    import urbansolarcarver.carving as C

    scene = build(SceneSpec("courtyard"))
    over = dict(ray_batch_size=4000)
    threaded = cases.run(scene, tmp_path / "t", epw, mode, **over)
    run_batches = C._run_batches
    monkeypatch.setattr(C, "_run_batches",
                        lambda b, launch, out, device, parallel, **kw: run_batches(b, launch, out, device,
                                                                                False, **kw))
    sequential = cases.run(scene, tmp_path / "s", epw, mode, **over)
    if mode == "time-based":
        assert np.array_equal(threaded.scores, sequential.scores)
    else:
        np.testing.assert_allclose(threaded.scores, sequential.scores, rtol=1e-5, atol=1e-6)


# ----------------------------------------------------------------- diagnostics
@pytest.mark.parametrize("mode", ["tilted_plane", "benefit"])
def test_diagnostics_agree_across_stages(tmp_path, epw, mode):
    run = cases.run(build(SceneSpec("lshape")), tmp_path, epw, mode)
    pre, thr, exp = run.diag("pre"), run.diag("thr"), run.diag("exp")
    occupied = int(run.occ.sum())
    assert pre["voxels_filled"] == thr["voxels_occupied"] == exp["voxels_original"] == occupied
    assert thr["voxels_kept"] == int(run.mask.sum())
    assert thr["voxels_kept"] + thr["voxels_removed"] == occupied
    # Export meshes the thresholded voxels minus the small-fragment cleanup.
    assert exp["voxels_retained"] + exp["voxels_removed_by_cleanup"] == thr["voxels_kept"]
    assert exp["voxels_retained"] + exp["voxels_removed"] == occupied
    if exp["mesh_volume_m3"] is not None:
        assert exp["mesh_volume_m3"] == pytest.approx(exp["voxels_retained"] * run.vs ** 3, rel=1e-3)
