"""Run-report generation and grid memory estimation.

Used by the exporting stage and the CLI ``estimate`` command.
"""
from pathlib import Path
from typing import Union

import json

import numpy as np

from ..load_config import user_config
from ..mode_registry import MODES_NEEDING_EPW


def estimate_grid_memory(voxel_size: float, mesh_path: str, margin_frac: float = 0.01) -> dict:
    """Estimate voxel grid dimensions and memory without running the full pipeline.

    Mirrors :func:`~urbansolarcarver.grid.voxelize_mesh`, which always builds
    a CUBIC grid sized to the largest bounding-box side plus margin.

    Returns dict with keys: grid_dims, total_voxels, memory_mb, warning.
    """
    import trimesh
    mesh = trimesh.load(mesh_path, force='mesh')
    bbox = mesh.bounds
    span = bbox[1] - bbox[0]
    max_dim = float(span.max())
    side = max_dim + 2 * max_dim * margin_frac
    resolution = int(np.ceil(side / voxel_size))
    dims = (resolution, resolution, resolution)
    total = resolution ** 3
    # float32 scores + bool grid + overhead ≈ 5 bytes/voxel
    mem_mb = total * 5 / (1024**2)
    warning = None
    if total > 500_000_000:
        warning = (
            f"Grid would contain {total:,} voxels ({mem_mb:,.0f} MB). "
            f"This will likely exhaust memory. Consider increasing voxel_size "
            f"(currently {voxel_size}m) or reducing the mesh bounding box."
        )
    elif total > 50_000_000:
        warning = (
            f"Grid contains {total:,} voxels ({mem_mb:,.0f} MB). "
            f"This is large and may be slow. Consider voxel_size > {voxel_size}m for faster iteration."
        )
    return {"grid_dims": dims, "total_voxels": total, "memory_mb": mem_mb, "warning": warning}


def generate_run_report(
    out_dir: Union[str, Path],
    pre_dir: Union[str, Path],
    thr_dir: Union[str, Path],
    exp_dir: Union[str, Path],
    conf: user_config,
) -> Path:
    """Compile a human-readable run report from all three stage diagnostics.

    Reads ``diagnostics/summary.json`` and ``diagnostics/timings.json`` from
    each stage directory, plus the config snapshot, and writes a single
    ``run_report.md`` into *out_dir*.

    Returns the path to the written report.
    """
    from datetime import datetime

    lines = []
    lines.append("# UrbanSolarCarver — Run Report")
    lines.append(f"\n*Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")

    # --- Configuration overview ---
    lines.append("## Configuration\n")
    lines.append("| Parameter | Value |")
    lines.append("|-----------|-------|")
    cfg_items = [
        ("Mode", conf.mode),
        ("Voxel size", f"{conf.voxel_size} m"),
        ("Grid step", f"{conf.grid_step} m"),
        ("Ray length", f"{conf.ray_length} m"),
        ("Min altitude", f"{conf.min_altitude}\u00b0"),
        ("Device", conf.device),
        ("Smoothing", conf.apply_smoothing),
        ("Output format", getattr(conf, "final_mesh_format", "ply")),
    ]
    if conf.mode in MODES_NEEDING_EPW:
        cfg_items.append(("EPW", conf.epw_path or "\u2014"))
        if conf.start_month is not None:
            period = (f"{conf.start_month}/{conf.start_day} {conf.start_hour}:00 \u2192 "
                      f"{conf.end_month}/{conf.end_day} {conf.end_hour}:00")
            cfg_items.append(("Analysis period", period))
    if conf.mode == "benefit":
        cfg_items.append(("Balance temperature", f"{conf.balance_temperature}\u00b0C"))
        cfg_items.append(("Balance offset", f"\u00b1{conf.balance_offset}\u00b0C"))
    if conf.mode == "radiative_cooling":
        cfg_items.append(("Dew point", f"{conf.dew_point_celsius}\u00b0C"))
        cfg_items.append(("Bliss k", conf.bliss_k))
    for label, val in cfg_items:
        lines.append(f"| {label} | {val} |")
    lines.append("")

    # --- Helper to load JSON safely ---
    def _load(stage_dir, subpath):
        p = Path(stage_dir) / subpath
        if p.is_file():
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _load_diag(stage_dir):
        """Load consolidated diagnostic.json, falling back to legacy split files."""
        diag = _load(stage_dir, "diagnostics/diagnostic.json")
        if diag:
            return diag, diag.get("timings", {})
        # Legacy fallback: separate summary.json + timings.json
        return _load(stage_dir, "diagnostics/summary.json"), _load(stage_dir, "diagnostics/timings.json")

    # --- Preprocessing ---
    pre_summary, pre_timing = _load_diag(pre_dir)
    lines.append("## Preprocessing\n")
    if pre_summary:
        grid_shape = pre_summary.get("grid_shape")
        if grid_shape:
            lines.append(f"- **Grid dimensions:** {grid_shape[0]} \u00d7 {grid_shape[1]} \u00d7 {grid_shape[2]}")
        total_v = pre_summary.get("voxels_total")
        filled_v = pre_summary.get("voxels_filled")
        if total_v is not None:
            lines.append(f"- **Total voxels:** {total_v:,}")
        if filled_v is not None:
            lines.append(f"- **Filled voxels:** {filled_v:,} ({100*filled_v/max(total_v,1):.1f}%)")
        pts = pre_summary.get("test_surface_points")
        if pts is not None:
            lines.append(f"- **Test surface sample points:** {pts:,}")
        dev = pre_summary.get("device")
        if dev:
            lines.append(f"- **Compute device:** {dev}")
        stats = pre_summary.get("score_stats", {})
        if stats and stats.get("count", 0) > 0:
            lines.append(f"- **Score range:** [{stats.get('min', 0):.4g}, {stats.get('max', 0):.4g}]")
            lines.append(f"- **Score mean / median:** {stats.get('mean', 0):.4g} / {stats.get('median', 0):.4g}")
            nzf = stats.get("nonzero_fraction", 0)
            lines.append(f"- **Non-zero voxels:** {stats.get('nonzero_count', 0):,} ({100*nzf:.1f}%)")
    if pre_timing:
        lines.append(f"- **Time:** {pre_timing.get('wall_seconds', 0):.1f}s")
    lines.append("")

    # --- Thresholding ---
    thr_summary, thr_timing = _load_diag(thr_dir)
    lines.append("## Thresholding\n")
    if thr_summary:
        method = thr_summary.get("threshold_method", "unknown")
        value = thr_summary.get("threshold_value", 0)
        lines.append(f"- **Method:** {method}")
        lines.append(f"- **Threshold value:** {value:.4g}")
        lines.append(f"- **Voxels kept / removed:** {thr_summary.get('voxels_kept', 0):,} / {thr_summary.get('voxels_removed', 0):,}")
        obs = thr_summary.get("obstruction_fraction_carved")
        if obs is not None:
            lines.append(f"- **Obstruction fraction carved:** {100*obs:.1f}%")
        unit = thr_summary.get("weight_unit")
        if unit:
            lines.append(f"- **Score unit:** {unit}")
    if thr_timing:
        lines.append(f"- **Time:** {thr_timing.get('wall_seconds', 0):.1f}s")
    lines.append("")

    # --- Exporting ---
    exp_summary, exp_timing = _load_diag(exp_dir)
    lines.append("## Export\n")
    if exp_summary:
        _mesh_path = exp_summary.get('mesh_path', '\u2014')
        lines.append(f"- **Output mesh:** `{_mesh_path}`")
        lines.append(f"- **Vertices:** {exp_summary.get('vertices', 0):,}")
        lines.append(f"- **Triangles:** {exp_summary.get('triangles', 0):,}")
        vol = exp_summary.get("mesh_volume_m3")
        if vol is not None:
            lines.append(f"- **Mesh volume:** {vol:,.1f} m\u00b3")
        bbox = exp_summary.get("bbox_dimensions_m")
        if bbox:
            lines.append(f"- **Bounding box:** {bbox[0]:.1f} \u00d7 {bbox[1]:.1f} \u00d7 {bbox[2]:.1f} m")
        ret = exp_summary.get("voxel_retention_pct")
        if ret is not None:
            lines.append(f"- **Voxel retention:** {ret:.1f}%")
    if exp_timing:
        lines.append(f"- **Time:** {exp_timing.get('wall_seconds', 0):.1f}s")
    lines.append("")

    # --- Total time ---
    total_wall = sum(
        t.get("wall_seconds", 0) for t in [pre_timing, thr_timing, exp_timing]
    )
    lines.append("## Total\n")
    lines.append(f"- **Total time:** {total_wall:.1f}s")

    report_path = Path(out_dir) / "run_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
