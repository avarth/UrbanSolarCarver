"""Diagnostics for pipeline stages: summary statistics, plots and the
writers that put a stage's diagnostics on disk.

Stages compute their ``summary`` dict and hand it to
:func:`write_preprocessing_diagnostics` or :func:`write_thresholding_diagnostics`,
which write ``diagnostic.json`` and, when plots are on, the plot images.

matplotlib is imported inside the plot helpers only, so importing the package
does not load it.  Plots draw on :class:`matplotlib.figure.Figure` and save
through the Agg canvas, so no pyplot state or interactive backend is involved
and plots render correctly from background threads and in notebooks.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List, Union, Optional

import numpy as np
from ..stage_settings import PreprocessingSettings, RunOptions
from ..run_context import report_issue
from ._util import write_json


def _new_figure(**kwargs):
    """A matplotlib Figure with the Agg canvas attached (imports matplotlib)."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(**kwargs)
    FigureCanvasAgg(fig)
    return fig


def save_histogram(
    values: np.ndarray,
    out_dir: Union[str, Path],
    fname: str = "score_histogram.png",
    threshold_line: Optional[float] = None,
    title: str = "Score Distribution",
    xlabel: str = "Score",
) -> Optional[Path]:
    """Save a histogram of the finite values as a PNG.

    Only positive values are binned when there are any; the share of zeros
    is written on the plot instead.  Returns the PNG path, or None if
    matplotlib is missing or there are no finite values.
    """
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return None
    d = Path(out_dir); d.mkdir(parents=True, exist_ok=True)
    path = d / fname
    flat = np.asarray(values, dtype=float).ravel()
    flat = flat[np.isfinite(flat)]
    if flat.size == 0:
        return None
    fig = _new_figure(figsize=(6, 3))
    ax = fig.subplots()
    zero_count = int((flat == 0).sum())
    positive = flat[flat > 0]
    ax.hist(positive if positive.size > 0 else flat, bins=80, color="#4c72b0", edgecolor="none", alpha=0.85)
    if zero_count > 0:
        pct = 100.0 * zero_count / flat.size
        ax.annotate(
            f"{zero_count} zero-score voxels ({pct:.0f}%)",
            xy=(0.02, 0.95), xycoords="axes fraction",
            fontsize=7, color="gray", va="top",
        )
    if threshold_line is not None:
        ax.axvline(threshold_line, color="red", linewidth=1.5, linestyle="--", label=f"threshold = {threshold_line:.4g}")
        ax.legend(fontsize=8)
    ax.set_title(title, fontsize=10)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Count")
    fig.tight_layout()
    fig.savefig(str(path), dpi=120)
    return path


def warn_score_anomalies(scores: np.ndarray, context: str = "preprocessing") -> dict:
    """Emit a warning if a score array contains NaN or Inf values.

    Non-finite scores indicate a numerical problem upstream (degenerate
    geometry, broken weights) and would silently corrupt thresholding:
    ``NaN <= thr`` is False, so NaN (and +Inf) voxels are always carved
    without any other signal to the user.

    Returns a dict with ``nan_count`` and ``inf_count`` for diagnostics.
    """

    nan_count = int(np.isnan(scores).sum())
    inf_count = int(np.isinf(scores).sum())
    if nan_count or inf_count:
        total = scores.size
        report_issue(
            "nonfinite_scores",
            f"{context}: scores contain {nan_count} NaN and {inf_count} Inf "
            f"values ({100.0 * (nan_count + inf_count) / max(total, 1):.2f}% "
            f"of {total} voxels). Check input geometry and weights; "
            f"NaN and +Inf voxels will always be carved.",
        )
    return {"nan_count": nan_count, "inf_count": inf_count}


def score_statistics(values: np.ndarray, detailed: bool = True) -> dict:
    """Compute summary statistics for a score array.

    Basic statistics (count, min, max, mean, nonzero counts) are cheap
    single-pass reductions and are always included.  ``detailed=True``
    adds median, std, and percentiles, which need sorting-like passes
    over the full array and are noticeably slower on large score volumes.
    The pipeline computes the detailed set only when ``cfg.diagnostics``
    is True.  Non-finite values are excluded from all statistics.
    """
    flat = np.asarray(values, dtype=float).ravel()
    finite = flat[np.isfinite(flat)]
    if finite.size == 0:
        return {"count": 0}
    stats = {
        "count": int(finite.size),
        "min": float(finite.min()),
        "max": float(finite.max()),
        "mean": float(finite.mean()),
        "nonzero_count": int((finite != 0).sum()),
        "nonzero_fraction": float((finite != 0).mean()),
    }
    if detailed:
        stats.update({
            "median": float(np.median(finite)),
            "std": float(finite.std()),
            "p5": float(np.percentile(finite, 5)),
            "p25": float(np.percentile(finite, 25)),
            "p75": float(np.percentile(finite, 75)),
            "p95": float(np.percentile(finite, 95)),
        })
    return stats


def _plot_tregenza_hemisphere(
    w: np.ndarray,
    title: str,
    cbar_label: str,
    path: Path,
    cmap: str = "viridis",
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
) -> Path:
    """Render a 145-patch Tregenza hemisphere as a polar sector chart.

    Parameters
    ----------
    w : ndarray, shape (145,)
        Value per patch (weight, intensity, etc.), in Tregenza order from
        the horizon ring up; the last entry is the zenith patch.
    title : str
        Figure title.
    cbar_label : str
        Colorbar axis label.
    path : Path
        Output PNG path (parent directory must exist).
    cmap : str
        Matplotlib colormap name (e.g. "RdBu_r" for signed differences).
    vmin, vmax : float, optional
        Color scale limits; default to the data range.

    Returns
    -------
    Path to the saved PNG.
    """
    import matplotlib as _mpl

    ring_counts = [30, 30, 24, 24, 18, 12, 6]  # patches per Tregenza ring
    zenith = w[-1]
    wmin = float(w.min()) if vmin is None else float(vmin)
    wmax = float(w.max()) if vmax is None else float(vmax)
    _norm = _mpl.colors.Normalize(vmin=wmin, vmax=wmax)
    _cmap = _mpl.colormaps[cmap]

    fig = _new_figure(figsize=(5, 5))
    ax = fig.add_subplot(111, projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_thetagrids([0, 90, 180, 270], labels=["N", "E", "S", "W"])
    ax.set_rlim(0.0, 1.0)
    alt_deg = np.array([0, 30, 60, 90], dtype=float)
    r_ticks = 1.0 - alt_deg / 90.0
    ax.set_rgrids(r_ticks, labels=[f"{int(a)}\u00b0" for a in alt_deg], angle=22.5)
    ax.set_rlabel_position(22.5)
    # Faint guide circles at the Tregenza band centre altitudes
    tregenza_alt = np.array([6, 18, 30, 42, 54, 66, 78], dtype=float)
    tt = np.linspace(0, 2 * np.pi, 361)
    for rr in 1.0 - tregenza_alt / 90.0:
        ax.plot(tt, np.full_like(tt, rr), linewidth=0.3, alpha=0.3, color="k")
    # Sector boundaries: the seven Tregenza bands are 12° tall (edges at
    # 0°, 12°, ..., 84°); the zenith cap covers 84°-90°.
    band_edges_deg = np.arange(0.0, 85.0, 12.0)
    r_edges = 1.0 - band_edges_deg / 90.0
    # Draw sectors
    idx = 0
    for r_i, m in enumerate(ring_counts):
        r1, r2 = r_edges[r_i], r_edges[r_i + 1]
        thetas = np.linspace(0, 2 * np.pi, m + 1)
        for j in range(m):
            ax.bar(
                x=(thetas[j] + thetas[j + 1]) / 2,
                height=r1 - r2,
                width=thetas[j + 1] - thetas[j],
                bottom=r2, align="center", edgecolor="none",
                color=_cmap(_norm(w[idx])),
            )
            idx += 1
    # Zenith cap
    ax.bar(x=0.0, height=r_edges[-1], width=2 * np.pi,
           bottom=0.0, align="edge", edgecolor="none",
           color=_cmap(_norm(zenith)))
    # Colorbar
    sm = _mpl.cm.ScalarMappable(norm=_norm, cmap=_cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label(cbar_label)
    ax.set_title(title, fontsize=10, pad=15)
    fig.savefig(str(path), bbox_inches="tight", dpi=120)
    return path


def _get_tregenza_solid_angles() -> np.ndarray:
    """Return (145,) array of Tregenza patch solid angles in steradians."""
    from ..sky_patches import tregenza_solid_angles
    return tregenza_solid_angles()


def save_sky_patch_weights(
    patch_weights: np.ndarray,
    out_dir: Union[str, Path],
    fname: str = "sky_patch_weights.png",
    weight_unit: str = "W/m²",
) -> Optional[List[Path]]:
    """Save two hemisphere plots for Tregenza (145) sky patches.

    Plot 1, **patch weight** (radiance × solid angle): what the ray
    tracer actually uses.  Mid-altitude patches often dominate because
    they subtend larger solid angles.  Saved as *fname*.

    Plot 2, **patch intensity** (weight / solid angle = radiance): the
    directional luminance/irradiance pattern.  For CIE overcast the
    zenith should be brightest; for winter benefit in the northern
    hemisphere the low southern sky usually dominates.  Saved as
    ``<fname stem>_intensity.<ext>``.

    For a patch count other than 145, only a line plot of weight against
    patch index is saved.

    Parameters
    ----------
    weight_unit : str
        Physical unit label from the mode registry (e.g. "kWh/m²", "CIE
        overcast sky obstruction score (dimensionless)").  Used in the
        colorbar and axis labels.

    Returns
    -------
    List of Paths to the generated plots, or None if matplotlib is
    unavailable.
    """
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return None

    n = int(patch_weights.size)
    w = np.asarray(patch_weights, dtype=float).reshape(-1)

    if n == 145:
        paths: List[Path] = []
        # Plot 1: patch weight (what the tracer uses)
        weight_path = d / fname
        _plot_tregenza_hemisphere(
            w, title="Patch weight (radiance \u00d7 solid angle)",
            cbar_label=f"Weight [{weight_unit}]", path=weight_path,
        )
        paths.append(weight_path)
        # Plot 2: intensity (weight / solid angle)
        omega = _get_tregenza_solid_angles()
        intensity = np.where(omega > 0, w / omega, 0.0)
        base, ext = fname.rsplit(".", 1)
        intensity_path = d / f"{base}_intensity.{ext}"
        _plot_tregenza_hemisphere(
            intensity, title="Patch intensity (per steradian)",
            cbar_label=f"Intensity [{weight_unit}/sr]",
            path=intensity_path,
        )
        paths.append(intensity_path)
        return paths

    # Fallback: simple line plot for non-Tregenza
    path = d / fname
    fig = _new_figure(figsize=(6, 3))
    ax = fig.subplots()
    ax.plot(np.arange(n), w)
    ax.set_title("Sky patch weights")
    ax.set_xlabel("Patch index")
    ax.set_ylabel(f"Weight [{weight_unit}]")
    fig.savefig(str(path), bbox_inches="tight", dpi=120)
    return [path]


def save_sky_patch_comparison(
    weights_a: np.ndarray,
    weights_b: np.ndarray,
    out_dir: Union[str, Path],
    labels: tuple = ("A", "B"),
    fname: str = "sky_patch_comparison.png",
) -> Optional[tuple]:
    """Save a difference hemisphere comparing two 145-patch weight sets.

    Both weight sets are normalized to sum to 1 first, so the plot shows
    how the *share* of credited sky moved between the two runs per patch
    (diverging colors: red = ``B`` weights that direction more than ``A``).
    Useful for comparing benefit formulations, analysis periods, or
    weight archetypes on otherwise identical runs.

    Parameters
    ----------
    weights_a, weights_b : ndarray, shape (145,)
        Per-patch weights of the two runs (``preprocessing/patch_weights.npy``).
    out_dir : str or Path
        Directory to write the PNG into (created if missing).
    labels : (str, str)
        Names for the two runs, used in the figure title.
    fname : str
        Output file name.

    Returns
    -------
    (path, stats), or None if matplotlib is unavailable.  ``stats``
    reports the redistribution in relative terms:
    ``mass_redistributed_pct`` (share of total weight that moved),
    ``patches_over_20pct`` (patches whose own share changed by more than
    20 %), and ``rel_change_min_pct`` / ``rel_change_max_pct`` (extremes).

    Raises
    ------
    ValueError
        If either set does not have 145 patches or sums to zero or less.
    """
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return None

    a = np.asarray(weights_a, dtype=float).reshape(-1)
    b = np.asarray(weights_b, dtype=float).reshape(-1)
    if a.size != 145 or b.size != 145:
        raise ValueError(
            f"expected two 145-patch Tregenza weight sets, got {a.size} and {b.size}"
        )
    if a.sum() <= 0 or b.sum() <= 0:
        raise ValueError("patch weights must have positive total mass")

    na, nb = a / a.sum(), b / b.sum()
    diff = nb - na
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(na > 1e-12, diff / na * 100.0, np.nan)
    stats = {
        "mass_redistributed_pct": float(np.abs(diff).sum() / 2 * 100),
        "patches_over_20pct": int(np.nansum(np.abs(rel) > 20)),
        "rel_change_min_pct": float(np.nanmin(rel)),
        "rel_change_max_pct": float(np.nanmax(rel)),
    }

    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    lim = float(np.abs(diff).max()) or 1.0
    path = _plot_tregenza_hemisphere(
        diff,
        title=f"Sky-share difference: {labels[1]} − {labels[0]}\n"
              f"(red = {labels[1]} weights this direction more)",
        cbar_label="Δ normalized patch weight",
        path=d / fname,
        cmap="RdBu_r", vmin=-lim, vmax=lim,
    )
    return path, stats


@dataclass(frozen=True)
class PreprocessingPlotInputs:
    """What the preprocessing plots draw: the raw score volume, the sky-patch
    weights (None for modes without them) and the score unit label."""
    raw_scores: np.ndarray
    patch_weights: Optional[np.ndarray]
    weight_unit: str


@dataclass(frozen=True)
class ThresholdingPlotInputs:
    """What the thresholding plot draws: the scores of the occupied voxels,
    the threshold applied and its method, and the score unit label."""
    occupied_scores: np.ndarray
    threshold_value: float
    method: str
    weight_unit: str


def write_preprocessing_diagnostics(summary: dict, folder: Path, settings: PreprocessingSettings,
                                    options: RunOptions,
                                    plot_inputs: PreprocessingPlotInputs) -> None:
    """Write preprocessing's diagnostics into *folder* (its ``diagnostics`` folder).

    Writes ``diagnostic.json`` from *summary*, plus, with
    ``options.diagnostic_plots``, the score histogram, the sky-patch
    weight plots and, for a benefit run with simulated weights, the plot
    comparing them with the simple balance-point weights.  The paths of the
    plots written are added to the ``diagnostic.json`` content.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    summary = dict(summary)
    if options.diagnostic_plots:
        patch_weights = plot_inputs.patch_weights
        if patch_weights is not None and patch_weights.size > 0:
            summary["sky_patch_images"] = [
                str(folder / "sky_patch_weights.png"),
                str(folder / "sky_patch_weights_intensity.png"),
            ]
            save_sky_patch_weights(patch_weights, folder, weight_unit=plot_inputs.weight_unit)
            if settings.mode == "benefit" and settings.simulated_weights_path:
                _write_simulated_weights_comparison(summary, folder, settings, patch_weights)
        summary["score_histogram"] = str(folder / "score_histogram.png")
        save_histogram(plot_inputs.raw_scores, folder, "score_histogram.png",
                       title=f"Raw Scores ({settings.mode})", xlabel=plot_inputs.weight_unit)
    write_json(folder, "diagnostic.json", summary)


def _write_simulated_weights_comparison(summary: dict, folder: Path, settings: PreprocessingSettings,
                                        patch_weights: np.ndarray) -> None:
    """Plot how the simulated weights shifted the sky relative to the simple
    balance-point rule under the same settings.  Parses the EPW a second time to
    get the simple weights."""
    import torch
    from ..carving import sample_period
    from ..scoring import get_weights
    _, hours_of_year = sample_period(settings)
    simple = get_weights(
        "benefit", device=torch.device("cpu"),
        epw_file=settings.epw_path, hoys=hours_of_year,
        balance_temperature=settings.balance_temperature,
        balance_offset=settings.balance_offset,
        north_deg=settings.north_deg,
        include_harm=settings.include_harm,
    ).cpu().numpy()
    comparison = save_sky_patch_comparison(
        simple, np.asarray(patch_weights, dtype=float), folder,
        labels=("simple (balance point)", "simulated"),
    )
    if comparison is not None:
        comparison_path, comparison_stats = comparison
        summary["sky_patch_comparison_image"] = str(comparison_path)
        summary["sky_patch_comparison_stats"] = comparison_stats


def write_thresholding_diagnostics(summary: dict, folder: Path, plot_inputs: ThresholdingPlotInputs,
                                   diagnostic_plots: bool) -> None:
    """Write thresholding's diagnostics into *folder* (its ``diagnostics`` folder):
    ``diagnostic.json`` from *summary* and, with *diagnostic_plots*, the
    threshold histogram."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    summary = dict(summary)
    if diagnostic_plots:
        summary["threshold_histogram"] = str(folder / "threshold_histogram.png")
        save_histogram(
            plot_inputs.occupied_scores, folder, "threshold_histogram.png",
            threshold_line=plot_inputs.threshold_value,
            title=f"Voxel scores, threshold={plot_inputs.threshold_value:.4g} ({plot_inputs.method})",
            xlabel=plot_inputs.weight_unit,
        )
    write_json(folder, "diagnostic.json", summary)
