"""Monte Carlo end-to-end checks: random scenes x random settings.

Every case draws a typology, dimensions, orientation, georeferenced offset,
voxel size, mode and mode parameters from a seeded RNG, runs the full
pipeline, and checks it against oracle.py and a set of invariants. A failing
case is reproducible from its seed alone:

    .venv/Scripts/python tests/montecarlo.py --n 300 --seed 0 --device auto
    .venv/Scripts/python tests/montecarlo.py --case 1234      # rerun one case

Writes one JSON line per case (settings, metrics, failed checks) and exits
non-zero when any case fails.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import traceback
import warnings
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cases  # noqa: E402
import oracle  # noqa: E402
from typologies import build, random_spec  # noqa: E402

MODES = ("tilted_plane", "time-based", "benefit", "irradiance", "daylight")
WEIGHTED = ("benefit", "irradiance", "daylight")


# ----------------------------------------------------------------- sampling
def _random_period(rng):
    month = int(rng.integers(1, 13))
    day = int(rng.integers(1, 28))
    start = int(rng.integers(7, 13))
    end = min(start + int(rng.integers(1, 7)), 18)
    end_day = min(day + int(rng.choice([0, 0, 0, 2, 6])), 28)
    return dict(start_month=month, start_day=day, start_hour=start,
                end_month=month, end_day=end_day, end_hour=end)


def draw_case(seed: int, device: str) -> tuple:
    rng = np.random.default_rng(seed)
    spec = random_spec(rng)
    mode = str(rng.choice(MODES))
    voxel = float(rng.choice([1.0, 1.5, 2.0]))
    drawn_device = str(rng.choice(["cpu", "cuda"]))  # always drawn: a seed means the same case on any --device
    over = dict(
        voxel=voxel,
        grid_step=float(voxel if rng.random() < 0.7 else voxel / 2),
        north_deg=float(rng.uniform(0, 360)) if rng.random() < 0.5 else 0.0,
        margin_frac=float(rng.choice([0.01, 0.01, 0.15])),
        device=drawn_device if device == "auto" else device,
    )
    if rng.random() < 0.4:
        over.update(carve_above=True, carve_above_min_consecutive=int(rng.integers(1, 4)))
    if mode == "tilted_plane":
        over["tilted_plane_angle_deg"] = (float(rng.uniform(25, 70)) if rng.random() < 0.6
                                          else [float(a) for a in rng.uniform(25, 70, 8)])
    elif mode == "time-based":
        over.update(_random_period(rng))
        over["sun_steps_per_hour"] = int(rng.choice([4, 6, 12]))
        over["threshold"] = float(rng.choice([0.0, 0.0, 0.0, 0.5]))
    else:
        if mode != "daylight":
            over.update(_random_period(rng))
            if mode == "benefit":
                over.update(start_hour=7, end_hour=18, end_day=min(over["start_day"] + 20, 28))
        if rng.random() < 0.7:
            over.update(threshold="carve_fraction", carve_fraction=float(rng.uniform(0.2, 0.85)))
        else:
            over.update(threshold="headtail")
        over["score_smoothing"] = None if rng.random() < 0.7 else 0.0
        if mode == "benefit" and rng.random() < 0.25:
            over["edge_taper"] = float(rng.uniform(0.5, 4.0))
    return spec, mode, over


# ----------------------------------------------------------------- checks
def _rethreshold(run, root, **cfg_over):
    from urbansolarcarver.api_core.thresholding import thresholding
    from urbansolarcarver.load_config import user_config
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        thr = thresholding(run.pre, user_config(**dict(run.cfg, **cfg_over)), root)
    return np.load(thr.mask_path).reshape(run.shape)


def check(run, mode, epw, root: Path, rng) -> tuple[dict, list]:
    metrics, failed = {}, []
    occ = run.occ
    metrics["occupied"] = int(occ.sum())
    metrics["retention_pct"] = round(100.0 * float((run.mask & occ).sum()) / max(int(occ.sum()), 1), 2)

    # 1. reference agreement
    if mode == "tilted_plane":
        must = oracle.column_above(oracle.tilted_hits(run))
    elif mode == "time-based":
        steps = run.cfg["sun_steps_per_hour"]
        hours = oracle.time_based_hours(run, epw, minutes=60 // steps)
        must = hours > run.cfg["threshold"] + 1e-6
    else:
        must = None
    if must is not None:
        kept_bad = int((run.occ & run.mask & must).sum())
        unexplained, carved = oracle.unexplained_carving(run, must)
        metrics.update(must_carve_kept=kept_bad, unexplained=unexplained, carved=carved)
        if kept_bad:
            failed.append("soundness")
        if unexplained:
            failed.append("tightness")
    elif not run.cfg.get("edge_taper"):
        agree = oracle.score_agreement(run)
        if agree["ref_mass"] > 0:
            metrics.update(score_shortfall_voxels=agree["shortfall_voxels"],
                           score_excess=round(agree["excess"], 4))
            if "excess_fine" in agree:
                metrics["score_excess_fine"] = round(agree["excess_fine"], 4)
            if agree["shortfall_voxels"] > max(2, 1e-4 * int(occ.sum())):
                failed.append("score_shortfall")
            if agree.get("excess_fine", 0.0) > 0.05:
                failed.append("score_excess")

    # 2. thresholding ignores empty cells
    noisy = run.scores.copy()
    noisy[~occ] = rng.uniform(0, 10 * float(max(run.scores.max(), 1.0)), int((~occ).sum()))
    np.save(run.pre / "scores.npy", noisy)
    try:
        if not np.array_equal(_rethreshold(run, root / "air"), run.mask):
            failed.append("air_dependence")
    finally:
        np.save(run.pre / "scores.npy", run.scores)
    if run.mask[~occ].any():
        failed.append("mask_true_on_air")

    # 3. carve_fraction nesting
    if run.cfg.get("threshold") == "carve_fraction":
        tighter = _rethreshold(run, root / "nest", carve_fraction=min(run.cfg["carve_fraction"] + 0.1, 0.99))
        if (tighter & ~run.mask).any():
            failed.append("carve_fraction_not_nested")

    # 4. carve_above: no floating mass, and it only ever removes voxels
    if run.cfg.get("carve_above"):
        kept = oracle.kept_grid(run)
        metrics["floating"] = oracle.floating_voxels(kept, occ, run.cfg.get("carve_above_min_consecutive", 1))
        metrics["refilled"] = int((kept & ~run.mask).sum())
        if metrics["floating"]:
            failed.append("floating_mass")
        if metrics["refilled"]:
            failed.append("carve_above_refill")
        exp_removed = run.diag("exp")["carve_above_extra_voxels_removed"]
        if exp_removed != int((run.mask & ~kept).sum()):
            failed.append("diag_carve_above")

    # 5. diagnostics agree across stages
    pre, thr, exp = run.diag("pre"), run.diag("thr"), run.diag("exp")
    if not (pre["voxels_filled"] == thr["voxels_occupied"] == exp["voxels_original"] == int(occ.sum())):
        failed.append("diag_occupied")
    if thr["voxels_kept"] != int(run.mask.sum()) or thr["voxels_kept"] + thr["voxels_removed"] != int(occ.sum()):
        failed.append("diag_threshold")
    if exp["voxels_retained"] + exp["voxels_removed"] != exp["voxels_original"]:
        failed.append("diag_export")

    # 6. exported mesh: volume matches voxels, and it sits inside the max volume
    import trimesh
    mesh_path = Path(exp["mesh_path"])
    if exp["voxels_retained"] > 0 and mesh_path.is_file():
        mesh = trimesh.load(mesh_path, force="mesh")
        vol = trimesh.load(run.cfg["max_volume_path"], force="mesh")
        if len(mesh.vertices):
            tol = run.vs * 1.01
            if (mesh.bounds[0] < vol.bounds[0] - tol).any() or (mesh.bounds[1] > vol.bounds[1] + tol).any():
                failed.append("export_outside_volume")
            if exp["mesh_volume_m3"] is not None:
                metrics["mesh_volume_err"] = round(
                    abs(exp["mesh_volume_m3"] / (exp["voxels_retained"] * run.vs ** 3) - 1), 5)
                if metrics["mesh_volume_err"] > 1e-3:
                    failed.append("mesh_volume")
    return metrics, failed


def run_case(seed: int, epw: str, device: str, workdir: Path, translate_prob: float = 0.15) -> dict:
    spec, mode, over = draw_case(seed, device)
    root = workdir / f"case_{seed}"
    rec = dict(seed=seed, mode=mode, spec=asdict(spec), settings=over, failed=[], metrics={})
    t0 = time.perf_counter()
    try:
        run = cases.run(build(spec), root, epw, mode, **over)
        rng = np.random.default_rng(seed + 1)
        rec["metrics"], rec["failed"] = check(run, mode, epw, root, rng)
        if rng.random() < translate_prob:
            moved = replace(spec, offset=(500000.0 + 123.0, 4500000.0 + 456.0, spec.offset[2] + 10.0))
            run2 = cases.run(build(moved), root / "moved", epw, mode, **over)
            differ = int((run.mask ^ run2.mask).sum()) if run.shape == run2.shape else -1
            rec["metrics"]["translated_mask_diff"] = differ
            if differ < 0 or differ > 0.002 * max(int(run.occ.sum()), 1):
                rec["failed"].append("translation")
    except Exception as exc:
        rec["failed"].append("exception")
        rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["traceback"] = traceback.format_exc(limit=6)
    rec["seconds"] = round(time.perf_counter() - t0, 2)
    if not rec["failed"]:
        shutil.rmtree(root, ignore_errors=True)
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0, help="first case seed")
    ap.add_argument("--case", type=int, help="run a single case seed and keep its files")
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    ap.add_argument("--out", default=str(HERE.parent / "runs" / "montecarlo.jsonl"))
    ap.add_argument("--workdir", default=None)
    a = ap.parse_args(argv)

    from _epw import resolve_epw
    epw = resolve_epw()
    if not epw:
        sys.exit("No EPW available (set USC_EPW_PATH)")
    if a.device in ("auto", "cuda"):
        import torch
        if not torch.cuda.is_available():
            a.device = "cpu"
    workdir = Path(a.workdir or tempfile.mkdtemp(prefix="usc_mc_"))
    seeds = [a.case] if a.case is not None else list(range(a.seed, a.seed + a.n))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n_fail = 0
    by_check: dict[str, int] = {}
    with out.open("w", encoding="utf-8") as fh:
        for s in seeds:
            rec = run_case(s, epw, a.device, workdir)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            status = "FAIL " + ",".join(rec["failed"]) if rec["failed"] else "ok"
            print(f"seed {s:5d} {rec['mode']:12s} {rec['spec']['typology']:9s} "
                  f"{rec['seconds']:6.1f}s  {status}  {rec.get('error', '')}", flush=True)
            if rec["failed"]:
                n_fail += 1
                for c in rec["failed"]:
                    by_check[c] = by_check.get(c, 0) + 1
    print(f"\n{len(seeds) - n_fail}/{len(seeds)} cases passed; failures by check: {by_check or 'none'}")
    print(f"report: {out}  (failed cases kept under {workdir})")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
