"""Baseline: test point access gained per m3 removed, on the bundled examples.

For each example and weighted mode, preprocessing runs once. The script then
finds the score cutoff that removes about 5, 10, 25 and 50 % of the max
volume after the default post-processing (score smoothing, carve_above, slope
limit 75 degrees). test_point_access_evaluation gives each test point's
accessible weight before and after; the gain is reported per m3 removed,
with the share of test points that gain anything and counts of shapes to
look at. A scoring or thresholding change can be compared with it at the
same volumes.

    python benchmarks/access_baseline.py [--out runs/access_baseline] [--cases name,...]

Writes <out>/results.json and <out>/summary.md.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import trimesh
from scipy import ndimage

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from urbansolarcarver.access_evaluation import test_point_access_evaluation  # noqa: E402
from urbansolarcarver.api import preprocessing  # noqa: E402
from urbansolarcarver.api_core.thresholding import _apply_score_smoothing  # noqa: E402
from urbansolarcarver.column_postprocessing import carve_above_scores, limit_column_slope  # noqa: E402
from urbansolarcarver.load_config import user_config  # noqa: E402
from urbansolarcarver.mode_registry import MODES  # noqa: E402
from urbansolarcarver.session import CarverSession  # noqa: E402
from urbansolarcarver.stage_settings import PreprocessingSettings  # noqa: E402

EXAMPLES = REPO / "src" / "urbansolarcarver" / "example_projects"
EPW = EXAMPLES / "weather" / "USA_CO_Golden-NREL.724666_TMY3.epw"
GEOMETRY = {  # name: (max volume, test surfaces, voxel size m)
    "perimeter_block": ("basic_perimeter_block/maxVolume.ply", ["basic_perimeter_block/testSrfs.ply"], 1.0),
    "new_building": ("new_building/max_volume.ply",
                     ["new_building/neighbor_roofs.ply", "new_building/neighbor_windows.ply"], 0.5),
    "district": ("multiple_buildings/max_volume.ply", ["multiple_buildings/test_surfaces.ply"], 1.0),
}
CASES = [(g, m) for g in GEOMETRY for m in ("irradiance", "benefit")] + [("perimeter_block", "daylight")]
TARGETS = (0.05, 0.10, 0.25, 0.50)
SLOPE_DEFAULT = 75.0


def _config(geometry, mode, out_dir, test_surface_path):
    max_volume, _, voxel = GEOMETRY[geometry]
    values = dict(max_volume_path=str(EXAMPLES / max_volume), test_surface_path=str(test_surface_path),
                  out_dir=str(out_dir), mode=mode, voxel_size=voxel, device="auto",
                  diagnostics=False, diagnostic_plots=False)
    if MODES[mode].needs_epw:
        values["epw_path"] = str(EPW)
    if mode == "irradiance":
        values.update(start_month=1, start_day=1, start_hour=0, end_month=12, end_day=31, end_hour=23)
    elif MODES[mode].needs_period:
        values.update(MODES[mode].starting_values)
    return user_config(**values)


def _test_surfaces(geometry, out):
    """One PLY with all test surface files of the example."""
    files = GEOMETRY[geometry][1]
    if len(files) == 1:
        return EXAMPLES / files[0]
    path = out / f"{geometry}_test_surfaces.ply"
    if not path.exists():
        trimesh.util.concatenate([trimesh.load(EXAMPLES / f, force="mesh") for f in files]).export(path)
    return path


def _post(occ, removal, cutoff):
    return limit_column_slope(occ & (removal <= cutoff), occ, SLOPE_DEFAULT)


def _cutoff_for_volume(occ, removal, target):
    """The cutoff whose mask removes the share of the occupied voxels closest to *target*."""
    values = np.unique(removal[occ])
    n = int(occ.sum())
    removed = lambda i: 1.0 - _post(occ, removal, values[i]).sum() / n  # noqa: E731
    lo, hi = 0, len(values) - 1            # removed(lo) is the most, removed(hi) the least
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if removed(mid) >= target:
            lo = mid
        else:
            hi = mid
    best = min((lo, hi), key=lambda i: abs(removed(i) - target))
    return float(values[best])


def _shape(mask, occ, voxel):
    """Counts of shapes to look at: floating parts, spires, columns cut to the ground, cliffs."""
    heights = mask.sum(axis=2)
    building = occ.any(axis=2)
    labels, n = ndimage.label(mask)
    base = np.zeros_like(mask)
    lowest = np.argmax(occ, axis=2)
    xs, ys = np.nonzero(building)
    base[xs, ys, lowest[xs, ys]] = True
    grounded = set(np.unique(labels[base & mask])) - {0}
    floating = int(sum((labels == k).sum() for k in range(1, n + 1) if k not in grounded))
    padded = np.pad(np.where(building, heights, -1), 1, constant_values=-1)
    neighbours = np.stack([padded[:-2, 1:-1], padded[2:, 1:-1], padded[1:-1, :-2], padded[1:-1, 2:]])
    valid = neighbours >= 0
    neighbour_max = np.where(valid, neighbours, -1).max(axis=0)
    step = 3.0 / voxel
    spires = int((building & (heights > 0) & (neighbour_max >= 0) & (heights >= neighbour_max + step)).sum())
    neighbour_min = np.where(valid, neighbours, 10 ** 6).min(axis=0)
    cliffs = int((building & (heights - neighbour_min >= 10.0 / voxel)).sum())
    to_ground = int((building & (heights == 0)).sum())
    return {"floating_voxels": floating, "spire_columns": spires, "cliff_columns_10m": cliffs,
            "columns_cut_to_ground": to_ground, "building_columns": int(building.sum())}


def _evaluate(occupancy, grid, settings, max_volume=None):
    result = test_point_access_evaluation(occupancy, (0.0, 0.0, 0.0), grid["extent"], grid["res"],
                                          grid["points"], grid["normals"], settings,
                                          max_volume=max_volume, device=grid["device"])
    return result.test_point_accessible_weight, result.test_point_blocked_weight


def run_case(geometry, mode, out):
    case = f"{geometry}_{mode}"
    run = out / case
    cfg = _config(geometry, mode, run, _test_surfaces(geometry, out))
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    preprocessing(cfg, run / "preprocessing")
    seconds = time.perf_counter() - t0
    peak_mb = torch.cuda.max_memory_allocated() / 2 ** 20 if torch.cuda.is_available() else None

    manifest = json.loads((run / "preprocessing" / "manifest.json").read_text())
    voxel = manifest["voxel_size"]
    occ = np.load(run / "preprocessing" / "voxel_grid.npy").astype(bool)
    res = occ.shape[0]
    origin = np.asarray(manifest["origin"])
    # The local frame of the grid: georeferenced coordinates lose too much in float32.
    grid = {"extent": res * voxel, "res": res, "device": "cuda" if torch.cuda.is_available() else "cpu",
            "points": (np.load(run / "preprocessing" / "test_points.npy") - origin).astype(np.float32),
            "normals": np.load(run / "preprocessing" / "test_normals.npy").astype(np.float32)}
    settings = PreprocessingSettings.from_config(cfg)
    sample_area = settings.grid_step ** 2
    raw = np.load(run / "preprocessing" / "scores.npy").reshape(occ.shape)
    smoothed, *_ = _apply_score_smoothing(raw, "weighted_sum", voxel, None, occ=occ)
    removal = carve_above_scores(smoothed, occ, 1)
    total_mass = float(smoothed[occ].sum())
    print(f"{case}: preprocessing {seconds:.1f} s, peak GPU {peak_mb or 0:.0f} MB, grid {res}^3, "
          f"{int(occ.sum())} occupied, {len(grid['points'])} test points", flush=True)

    records = []
    # The evaluations reuse the patch weights (the EPW sky matrix) through the session cache.
    with CarverSession(grid["device"]):
        base_acc, base_blocked = _evaluate(occ, grid, settings)
        for target in TARGETS:
            cutoff = _cutoff_for_volume(occ, removal, target)
            mask = _post(occ, removal, cutoff)
            removed = int(occ.sum() - mask.sum())
            kept_before_slope_limit = int((occ & (removal <= cutoff)).sum())
            acc, _ = _evaluate(mask, grid, settings, max_volume=occ)
            gain = acc - base_acc
            scale = max(float(np.abs(base_acc).max()), 1e-12)
            rec = {
                "case": case, "geometry": geometry, "mode": mode, "target": target,
                "removed_share": removed / int(occ.sum()), "removed_m3": removed * voxel ** 3, "cutoff": cutoff,
                "slope_limit_removed_share": (kept_before_slope_limit - int(mask.sum())) / int(occ.sum()),
                "carve_fraction_equivalent": float(smoothed[occ & ~mask].sum()) / total_mass,
                "gain_total": float(gain.sum()) * sample_area,
                "gain_per_m3": float(gain.sum()) * sample_area / max(removed * voxel ** 3, 1e-12),
                "freed_share_of_blocked": float(gain.sum()) / max(float(base_blocked.sum()), 1e-12),
                "gain_mean_per_point": float(gain.mean()), "gain_min_per_point": float(gain.min()),
                "points_improved": float((gain > 1e-6 * scale).mean()),
                "points_worse": float((gain < -1e-6 * scale).mean()),
                "weight_unit": MODES[mode].weight_unit, "gain_unit": MODES[mode].score_unit,
                "preprocessing_s": seconds, "peak_gpu_mb": peak_mb,
                "n_points": len(grid["points"]), "grid_res": res, "voxel_size": voxel,
                **_shape(mask, occ, voxel),
            }
            records.append(rec)
            print(f"   target {target:.0%}: removed {rec['removed_share']:.1%}, gain/m3 {rec['gain_per_m3']:.4g}, "
                  f"improved {rec['points_improved']:.0%}, carve_fraction {rec['carve_fraction_equivalent']:.2f}, "
                  f"cliffs {rec['cliff_columns_10m']}", flush=True)
    return records


def summary_markdown(records):
    lines = ["# Access baseline: gain per m³ removed", "",
             "Gain = accessible weight of the test points after carving minus before, times the sample area "
             "(grid_step²), per m³ removed. Default post-processing (smoothing, carve_above, slope limit 75°).", ""]
    by_case = {}
    for r in records:
        by_case.setdefault(r["case"], []).append(r)
    for case, recs in by_case.items():
        first = recs[0]
        lines += [f"## {case}", "",
                  f"{first['n_points']} test points, grid {first['grid_res']}³ at {first['voxel_size']} m. "
                  f"Gain unit: {first['gain_unit']} per m³ (weights in {first['weight_unit']}). Preprocessing "
                  f"{first['preprocessing_s']:.1f} s, peak GPU {(first['peak_gpu_mb'] or 0):.0f} MB.", "",
                  "| Target | Removed | By slope limit | Gain per m³ | Freed share of blocked | Mean gain/pt | Pts improved | Pts worse | carve_fraction equiv. | Spires | Floating vox | Cols to ground | Cliffs ≥10 m |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in recs:
            lines.append(
                f"| {r['target']:.0%} | {r['removed_share']:.1%} | {r['slope_limit_removed_share']:.1%} | "
                f"{r['gain_per_m3']:.4g} | {r['freed_share_of_blocked']:.1%} | {r['gain_mean_per_point']:.4g} | "
                f"{r['points_improved']:.0%} | {r['points_worse']:.1%} | {r['carve_fraction_equivalent']:.2f} | "
                f"{r['spire_columns']} | {r['floating_voxels']} | {r['columns_cut_to_ground']}/{r['building_columns']} | "
                f"{r['cliff_columns_10m']} |")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(REPO / "runs" / "access_baseline"))
    parser.add_argument("--cases", default="", help="comma-separated case names (geometry_mode); default all")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wanted = set(filter(None, args.cases.split(",")))
    records = []
    for geometry, mode in CASES:
        if wanted and f"{geometry}_{mode}" not in wanted:
            continue
        records += run_case(geometry, mode, out)
        (out / "results.json").write_text(json.dumps(records, indent=1))
        (out / "summary.md").write_text(summary_markdown(records), encoding="utf-8")


if __name__ == "__main__":
    main()
