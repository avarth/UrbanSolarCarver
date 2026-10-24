"""Run-report generation, used by the exporting and massing stages."""
import logging
from pathlib import Path
from typing import Union

import json

from ..mode_registry import MODES_NEEDING_EPW
from ..stage_settings import stage_folder

log = logging.getLogger(__name__)

# Stages that read the thresholding output and add a section to the report.
_REPORTED_LEAF_STAGES = ("exporting", "massing")


def write_run_report(stage: str, stage_out_path: Path, pre_dir: Path, thr_dir: Path,
                     thresholding_run_id: str):
    """Write ``run_report.md`` at the end of the exporting or massing *stage*.

    The report goes to the run folder in the standard ``<run>/<stage>``
    layout, otherwise into *stage_out_path*.  Besides the finishing stage,
    it has a section for the other one (exporting or massing) when that
    stage's folder in the run folder holds a manifest built from the same
    thresholding run (*thresholding_run_id*); a section of an earlier
    thresholding run is left out.  The old report is removed first, so a
    failed regeneration leaves none instead of stale numbers; a failure is
    logged, not raised.  Returns the report path, or None.
    """
    report_folder = stage_out_path.parent if stage_out_path.name == stage else stage_out_path
    (report_folder / "run_report.md").unlink(missing_ok=True)
    leaf_stage_dirs = {name: _leaf_stage_dir(stage_folder(report_folder, name), thresholding_run_id)
                       for name in _REPORTED_LEAF_STAGES if name != stage}
    leaf_stage_dirs[stage] = stage_out_path
    try:
        return generate_run_report(report_folder, pre_dir, thr_dir,
                                   exporting_dir=leaf_stage_dirs["exporting"],
                                   massing_dir=leaf_stage_dirs["massing"])
    except Exception as exc:
        log.warning("Could not generate run report: %s", exc)
        return None


def _context_lines(context: dict) -> list:
    """The "Context and terrain" block of the report, from preprocessing's ``summary["context"]``."""
    used = [name for name, key in (("context", "context_used"), ("terrain", "terrain_used")) if context.get(key)]
    lines = ["### Context and terrain\n", f"- **Used:** {' and '.join(used) or 'none'}"]
    if context.get("context_closed") is False:
        lines.append("- **Context mesh not closed:** the columns removed may be too few or too many where it reaches the grid")
    lines.append(f"- **Voxels removed by context columns:** {context.get('voxels_removed_by_context', 0):,}")
    lines.append(f"- **Voxels removed below the ground:** {context.get('voxels_removed_below_ground', 0):,}")
    lines.append(f"- **Volume removed:** {context.get('volume_removed_m3', 0.0):,.1f} m³ "
                 f"({100 * context.get('share_of_max_volume_removed', 0.0):.1f}% of the maximum volume)")
    if context.get("context_blocks_rays") is False:
        lines.append("- **Account for context blocking:** off (no ray was tested against the context or the terrain)")
    total = context.get("rays_total", 0)
    if total:
        dropped = context.get("rays_dropped", 0)
        lines.append(f"- **Rays dropped:** {dropped:,} of {total:,} ({100 * dropped / total:.1f}%), "
                     f"{100 * context.get('weight_dropped_share', 0.0):.1f}% of the ray weight")
        lines.append(f"- **Test points with every ray blocked:** {context.get('test_points_fully_blocked', 0):,}")
    lines.append("")
    return lines


def _leaf_stage_dir(stage_dir: Path, thresholding_run_id: str):
    """*stage_dir* if its manifest was built from the given thresholding run, else None."""
    manifest_path = stage_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        upstream_run_id = json.loads(manifest_path.read_text(encoding="utf-8")).get("upstream_run_id")
    except (OSError, ValueError):
        return None
    return stage_dir if upstream_run_id == thresholding_run_id else None


def generate_run_report(
    out_dir: Union[str, Path],
    pre_dir: Union[str, Path],
    thr_dir: Union[str, Path],
    exporting_dir: Union[str, Path, None] = None,
    massing_dir: Union[str, Path, None] = None,
) -> Path:
    """Compile a human-readable run report from the stage diagnostics.

    Reads ``diagnostics/diagnostic.json`` from each stage directory (a
    missing file leaves that section empty), takes the configuration table
    from the config snapshot preprocessing saved (the settings the run
    used, not a config passed to a later stage), and writes a single
    ``run_report.md`` into *out_dir*.  The
    Export and Massing sections are added when *exporting_dir* and
    *massing_dir* are given.

    Returns the path to the written report.
    """
    from datetime import datetime

    lines = []
    lines.append("# UrbanSolarCarver run report")
    lines.append(f"\n*Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")

    # --- Helper to load JSON safely ---
    def _load(stage_dir, subpath):
        p = Path(stage_dir) / subpath
        if p.is_file():
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _load_diag(stage_dir):
        """Return (diagnostics, timings) for one stage; empty dicts if missing."""
        diag = _load(stage_dir, "diagnostics/diagnostic.json")
        return diag, diag.get("timings", {})

    # --- Configuration overview: the settings preprocessing ran with ---
    lines.append("## Configuration\n")
    run_cfg = _load(pre_dir, "diagnostics/config_snapshot.json")
    if run_cfg:
        lines.append("| Parameter | Value |")
        lines.append("|-----------|-------|")
        mode = run_cfg.get("mode")
        # The sample spacing the run used: the manifest records it (an unset grid_step is half the voxel size); a
        # manifest written before it did leaves the config's value.
        grid_step = _load(pre_dir, "manifest.json").get("grid_step", run_cfg.get("grid_step"))
        cfg_items = [
            ("Mode", mode),
            ("Voxel size", f"{run_cfg.get('voxel_size')} m"),
            ("Grid step", f"{grid_step} m"),
            ("Ray length", f"{run_cfg.get('ray_length')} m"),
            ("Min altitude", f"{run_cfg.get('min_altitude')}\u00b0"),
            ("Device", run_cfg.get("device")),
        ]
        if mode in MODES_NEEDING_EPW:
            cfg_items.append(("EPW", run_cfg.get("epw_path") or "\u2014"))
            if run_cfg.get("start_month") is not None:
                period = (f"{run_cfg['start_month']}/{run_cfg['start_day']} {run_cfg['start_hour']}:00 \u2192 "
                          f"{run_cfg['end_month']}/{run_cfg['end_day']} {run_cfg['end_hour']}:00")
                cfg_items.append(("Analysis period", period))
        if mode == "time-based":
            # A snapshot written before time_basis existed was read in standard time.
            cfg_items.append(("Time basis", run_cfg.get("time_basis", "standard")))
        if mode == "benefit":
            cfg_items.append(("Balance temperature", f"{run_cfg.get('balance_temperature')}\u00b0C"))
            cfg_items.append(("Balance offset", f"\u00b1{run_cfg.get('balance_offset')}\u00b0C"))
        if mode == "radiative_cooling":
            cfg_items.append(("Dew point", f"{run_cfg.get('dew_point_celsius')}\u00b0C"))
            cfg_items.append(("Bliss k", run_cfg.get("bliss_k")))
        for label, val in cfg_items:
            lines.append(f"| {label} | {val} |")
    else:
        lines.append("- No configuration snapshot in the preprocessing diagnostics.")
    lines.append("")

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
            if "median" in stats:  # detailed stats (cfg.diagnostics=True)
                lines.append(f"- **Score mean / median:** {stats.get('mean', 0):.4g} / {stats['median']:.4g}")
            else:
                lines.append(f"- **Score mean:** {stats.get('mean', 0):.4g}")
            nzf = stats.get("nonzero_fraction", 0)
            lines.append(f"- **Non-zero voxels:** {stats.get('nonzero_count', 0):,} ({100*nzf:.1f}%)")
    if pre_timing:
        lines.append(f"- **Time:** {pre_timing.get('wall_seconds', 0):.1f}s")
    lines.append("")
    context = pre_summary.get("context") if pre_summary else None
    if context:
        lines.extend(_context_lines(context))

    # --- Thresholding ---
    thr_summary, thr_timing = _load_diag(thr_dir)
    lines.append("## Thresholding\n")
    if thr_summary:
        method = thr_summary.get("threshold_method", "unknown")
        value = thr_summary.get("threshold_value", 0)
        lines.append(f"- **Method:** {method}")
        lines.append(f"- **Threshold value:** {value:.4g}")
        if thr_summary.get("max_slope_deg") is not None:
            lines.append(
                f"- **Slope limit:** {thr_summary['max_slope_deg']:g} deg, removed "
                f"{thr_summary.get('slope_limit_extra_voxels_removed', 0):,} voxels "
                f"({100 * thr_summary.get('obstruction_fraction_carved_by_slope_limit', 0.0):.1f}% "
                f"of the obstruction score)")
        lines.append(f"- **Voxels kept / removed:** {thr_summary.get('voxels_kept', 0):,} / {thr_summary.get('voxels_removed', 0):,}")
        obs = thr_summary.get("obstruction_fraction_carved")
        if obs is not None:
            lines.append(f"- **Obstruction fraction carved:** {100*obs:.1f}%")
        unit = thr_summary.get("score_unit")
        if unit:
            lines.append(f"- **Score unit:** {unit}")
        if thr_summary.get("weight_unit"):
            lines.append(f"- **Sky patch weight unit:** {thr_summary['weight_unit']}")
    if thr_timing:
        lines.append(f"- **Time:** {thr_timing.get('wall_seconds', 0):.1f}s")
    lines.append("")

    # --- Exporting ---
    exp_timing = {}
    if exporting_dir is not None:
        exp_summary, exp_timing = _load_diag(exporting_dir)
        lines.append("## Export\n")
        if exp_summary:
            _mesh_path = exp_summary.get('mesh_path', '\u2014')
            lines.append(f"- **Output mesh:** `{_mesh_path}`")
            lines.append(f"- **Vertices:** {exp_summary.get('vertices') or 0:,}")
            lines.append(f"- **Triangles:** {exp_summary.get('triangles') or 0:,}")
            vol = exp_summary.get("mesh_volume_m3")
            if vol is not None:
                lines.append(f"- **Mesh volume:** {vol:,.1f} m\u00b3")
            bbox = exp_summary.get("bbox_dimensions_m")
            if bbox:
                lines.append(f"- **Bounding box:** {bbox[0]:.1f} \u00d7 {bbox[1]:.1f} \u00d7 {bbox[2]:.1f} m")
            if exp_summary.get("apply_smoothing") is not None:
                lines.append(f"- **Smoothing:** {'on' if exp_summary['apply_smoothing'] else 'off'}")
            ret = exp_summary.get("voxel_retention_pct")
            if ret is not None:
                lines.append(f"- **Voxel retention:** {ret:.1f}%")
        if exp_timing:
            lines.append(f"- **Time:** {exp_timing.get('wall_seconds', 0):.1f}s")
        lines.append("")

    # --- Massing ---
    m_timing = {}
    if massing_dir is not None:
        m_summary, m_timing = _load_diag(massing_dir)
        lines.append("## Massing\n")
        if m_summary:
            lines.append(f"- **Floors built:** {m_summary.get('floors_built', 0)} of {m_summary.get('floors', 0)}")
            lines.append(f"- **Floor plates:** {m_summary.get('plates', 0)}")
            lines.append(f"- **Total floor area:** {m_summary.get('total_floor_area_m2', 0.0):,.0f} m²")
            per_floor = m_summary.get("floor_area_m2_per_floor") or []
            if per_floor:
                lines.append("- **Floor area per floor (m²):** " + ", ".join(f"{a:,.0f}" for a in per_floor))
            share = m_summary.get("envelope_share_in_plates")
            if share is not None:
                lines.append(f"- **Share of the carved envelope inside plates:** {100 * share:.1f}%")
            lines.append(f"- **Volume outside the envelope (tolerance):** "
                         f"{m_summary.get('volume_outside_envelope_m3', 0.0):,.0f} m³")
            if m_summary.get("footprint_source") == "voxels":
                lines.append("- **Footprint:** from the voxels (the mesh outline could not be read)")
        if m_timing:
            lines.append(f"- **Time:** {m_timing.get('wall_seconds', 0):.1f}s")
        lines.append("")

    # --- Total time ---
    total_wall = sum(
        t.get("wall_seconds", 0) for t in [pre_timing, thr_timing, exp_timing, m_timing]
    )
    lines.append("## Total\n")
    lines.append(f"- **Total time:** {total_wall:.1f}s")

    report_path = Path(out_dir) / "run_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
