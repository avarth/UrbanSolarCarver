"""Diagnostics visualisation helpers for pipeline stages.

Histogram plots, sky-patch hemisphere charts, and score summary
statistics.  Used by preprocessing and thresholding.

The Agg backend is set before any matplotlib import so that plots
render correctly from background threads (no tkinter dependency).
"""
from pathlib import Path
from typing import List, Union, Optional

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
except ImportError:
    pass


def save_histogram(
    values: np.ndarray,
    out_dir: Union[str, Path],
    fname: str = "score_histogram.png",
    threshold_line: Optional[float] = None,
    title: str = "Score Distribution",
    xlabel: str = "Score",
) -> Optional[Path]:
    """Save a histogram of values as PNG. Returns path or None if matplotlib missing."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    d = Path(out_dir); d.mkdir(parents=True, exist_ok=True)
    path = d / fname
    flat = np.asarray(values, dtype=float).ravel()
    flat = flat[np.isfinite(flat)]
    if flat.size == 0:
        return None
    fig, ax = plt.subplots(figsize=(6, 3))
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
    plt.close(fig)
    return path


def warn_score_anomalies(scores: np.ndarray, context: str = "preprocessing") -> dict:
    """Warn loudly if a score array contains NaN or Inf values.

    Non-finite scores indicate a numerical problem upstream (degenerate
    geometry, broken weights) and would silently corrupt thresholding —
    ``NaN <= thr`` is False, so NaN voxels are always carved without any
    signal to the user.

    Returns a dict with ``nan_count`` and ``inf_count`` for diagnostics.
    """
    import warnings

    nan_count = int(np.isnan(scores).sum())
    inf_count = int(np.isinf(scores).sum())
    if nan_count or inf_count:
        total = scores.size
        warnings.warn(
            f"{context}: scores contain {nan_count} NaN and {inf_count} Inf "
            f"values ({100.0 * (nan_count + inf_count) / max(total, 1):.2f}% "
            f"of {total} voxels). Check input geometry and weights — "
            f"non-finite voxels will always be carved.",
            stacklevel=2,
        )
    return {"nan_count": nan_count, "inf_count": inf_count}


def score_statistics(values: np.ndarray, detailed: bool = True) -> dict:
    """Compute summary statistics for a score array.

    Basic statistics (count, min, max, mean, nonzero counts) are cheap
    single-pass reductions and are always included.  ``detailed=True``
    adds median, std, and percentiles, which need sorting-like passes
    over the full array — noticeably slower on large score volumes.
    The pipeline gates the detailed set behind ``cfg.diagnostics``.
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
) -> Path:
    """Render a 145-patch Tregenza hemisphere as a polar sector chart.

    Parameters
    ----------
    w : ndarray, shape (145,)
        Value per patch (weight, intensity, etc.).
    title : str
        Figure title.
    cbar_label : str
        Colorbar axis label.
    path : Path
        Output PNG path (parent directory must exist).

    Returns
    -------
    Path to the saved PNG.
    """
    import matplotlib.pyplot as plt
    import matplotlib as _mpl

    ring_counts = [30, 30, 24, 24, 18, 12, 6]  # patches per Tregenza ring
    zenith = w[-1]
    wmin, wmax = float(w.min()), float(w.max())
    _norm = _mpl.colors.Normalize(vmin=wmin, vmax=wmax)
    _cmap = plt.cm.viridis

    fig = plt.figure(figsize=(5, 5))
    ax = fig.add_subplot(111, projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_thetagrids([0, 90, 180, 270], labels=["N", "E", "S", "W"])
    ax.set_rlim(0.0, 1.0)
    alt_deg = np.array([0, 30, 60, 90], dtype=float)
    r_ticks = 1.0 - alt_deg / 90.0
    ax.set_rgrids(r_ticks, labels=[f"{int(a)}\u00b0" for a in alt_deg], angle=22.5)
    ax.set_rlabel_position(22.5)
    # Faint guides at Tregenza ring elevations
    tregenza_alt = np.array([6, 18, 30, 42, 54, 66, 78], dtype=float)
    tt = np.linspace(0, 2 * np.pi, 361)
    for rr in 1.0 - tregenza_alt / 90.0:
        ax.plot(tt, np.full_like(tt, rr), linewidth=0.3, alpha=0.3, color="k")
    # Ring edges from horizon to zenith
    elev = tregenza_alt * np.pi / 180.0
    r_edges = np.concatenate([[1.0], 1.0 - elev / (np.pi / 2)])
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
    plt.close(fig)
    return path


# Tregenza solid angles (steradians) for each of the 145 patches.
# Computed from the standard ViewSphere; cached here so the plotting
# utility does not need to import torch or ladybug at runtime.
_TREGENZA_SOLID_ANGLES: Optional[np.ndarray] = None

def _get_tregenza_solid_angles() -> np.ndarray:
    """Return (145,) array of Tregenza patch solid angles in steradians."""
    global _TREGENZA_SOLID_ANGLES
    if _TREGENZA_SOLID_ANGLES is None:
        try:
            from ladybug.viewsphere import view_sphere
            _TREGENZA_SOLID_ANGLES = np.array(
                view_sphere.tregenza_solid_angles, dtype=np.float64
            )
        except ImportError:
            # Fallback: approximate solid angles from ring geometry
            ring_counts = [30, 30, 24, 24, 18, 12, 6]
            alt_edges = np.radians([0, 12, 24, 36, 48, 60, 72, 84, 90])
            angles = []
            for i, m in enumerate(ring_counts):
                ring_omega = 2 * np.pi * (np.sin(alt_edges[i + 1]) - np.sin(alt_edges[i]))
                angles.extend([ring_omega / m] * m)
            zenith_omega = 2 * np.pi * (1.0 - np.sin(alt_edges[-2]))
            angles.append(zenith_omega)
            _TREGENZA_SOLID_ANGLES = np.array(angles, dtype=np.float64)
    return _TREGENZA_SOLID_ANGLES


def save_sky_patch_weights(
    patch_weights: np.ndarray,
    out_dir: Union[str, Path],
    fname: str = "sky_patch_weights.png",
    weight_unit: str = "W/m²",
) -> Optional[List[Path]]:
    """Save two hemisphere plots for Tregenza (145) sky patches.

    Plot 1 — **Patch weight** (radiance × solid angle): what the ray
    tracer actually uses.  Mid-altitude patches often dominate because
    they subtend larger solid angles.

    Plot 2 — **Patch intensity** (weight / solid angle = radiance):
    shows the directional luminance/irradiance pattern.  For CIE
    overcast the zenith should be brightest; for clear-sky benefit
    the south horizon ring should dominate.

    Falls back to a simple line plot for non-Tregenza patch counts.

    Parameters
    ----------
    weight_unit : str
        Physical unit label from mode registry (e.g. "Wh/m²", "CIE
        overcast sky obstruction score (dimensionless)").  Used in the
        intensity plot colorbar label.

    Returns
    -------
    List of Paths to the generated plots, or None if matplotlib is
    unavailable.
    """
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib.pyplot as plt
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
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot(np.arange(n), w)
    ax.set_title("Sky patch weights")
    ax.set_xlabel("Patch index")
    ax.set_ylabel(f"Weight [{weight_unit}]")
    fig.savefig(str(path), bbox_inches="tight", dpi=120)
    plt.close(fig)
    return [path]
