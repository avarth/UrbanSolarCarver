from __future__ import annotations
import time
import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Union, overload
import numpy as np
from ..load_config import user_config
from ..pydantic_schemas import (
    PreprocessingManifest,
    ThresholdingManifest,
    schema_from_json,
    schema_to_json,
)
from ..scoring import carve_fraction_threshold, headtail_threshold
from ..mode_registry import MODES
from ._util import _resolve_cfg, _ensure_out_dir, ensure_diag, write_json
from ._diagnostics import save_histogram, score_statistics, warn_score_anomalies

@dataclass(frozen=True)
class ThresholdingResult:
    """Immutable record returned by :func:`thresholding`.

    Stores the path to the binary mask and the provenance chain back to the
    upstream preprocessing run (via ``upstream`` hash and
    ``upstream_manifest`` path).  Implements ``__fspath__`` so it can be
    passed directly as a path-like to :func:`exporting`.
    """
    out_dir: Path
    mask_path: Path
    hash: str
    upstream: str
    upstream_manifest: Path
    threshold_method: str = ""
    threshold_value: float = 0.0
    voxels_kept: int = 0
    voxels_removed: int = 0
    retention_pct: float = 0.0
    @property
    def manifest_path(self) -> Path:
        return self.out_dir / "manifest.json"
    def __fspath__(self) -> str:
        return str(self.manifest_path)

def _apply_score_smoothing(raw, kind, voxel_size, score_smoothing):
    """Gaussian-blur the continuous score volume before thresholding.

    Smooths resolution-dependent noise so the binary mask (and carved mesh)
    is cleaner at fine voxel sizes.  Only applied to weighted-score modes;
    violation-count modes (time-based, tilted_plane) are left untouched.

    ``score_smoothing`` semantics: None → auto (1.1 × voxel_size);
    0 → disabled; > 0 → explicit radius in meters.

    Returns (scores, applied, radius_m, sigma_voxels).
    """
    if kind != "weighted_sum":
        return raw, False, 0.0, 0.0

    radius_m = 0.0
    if score_smoothing is None and voxel_size and voxel_size > 0:
        radius_m = 1.1 * voxel_size  # auto-default
    elif score_smoothing is not None and score_smoothing > 0:
        radius_m = float(score_smoothing)

    if radius_m <= 0:
        return raw, False, 0.0, 0.0
    if not voxel_size or voxel_size <= 0:
        import warnings
        warnings.warn(
            "score_smoothing requested but the preprocessing manifest has no "
            "voxel_size — cannot convert meters to voxels, skipping smoothing. "
            "Re-run preprocessing to regenerate the manifest.",
            stacklevel=3,
        )
        return raw, False, 0.0, 0.0

    from scipy.ndimage import gaussian_filter
    sigma_voxels = float(np.clip(radius_m / voxel_size, 0.5, 8.0))
    smoothed = gaussian_filter(raw.astype(np.float32), sigma=sigma_voxels)
    return smoothed, True, radius_m, sigma_voxels


def _resolve_threshold(scores, spec):
    """Resolve a validated :class:`ThresholdSpec` into a numeric cutoff.

    The config layer guarantees the spec is complete and valid for the
    mode (see ``UserConfig._resolve_threshold_spec``), so this is a pure
    dispatch: ``cutoff`` is the value itself; ``headtail`` (Jiang 2013
    head/tail breaks) and ``carve_fraction`` (score-mass cutoff — NOT a
    percentile: it weights by obstruction severity) compute it from the
    score distribution.
    """
    if spec.method == "cutoff":
        return float(spec.value)
    if spec.method == "headtail":
        return float(headtail_threshold(scores, max_iterations=50))
    if spec.method == "carve_fraction":
        return carve_fraction_threshold(scores, float(spec.value))
    raise ValueError(f"Unknown threshold method: {spec.method!r}")


@overload
def thresholding(volume: "PreprocessingResult", cfg: Union[user_config, str, Path], out_dir: Union[str, Path]) -> ThresholdingResult: ...
@overload
def thresholding(volume: Union[str, Path], cfg: Union[user_config, str, Path], out_dir: Union[str, Path]) -> ThresholdingResult: ...

def thresholding(
    volume: Union["PreprocessingResult", str, Path],
    cfg: Union[user_config, str, Path],
    out_dir: Union[str, Path],
) -> ThresholdingResult:
    """Second stage of the 3-stage pipeline: score-to-mask binarisation.

    Loads the per-voxel obstruction scores produced by :func:`preprocessing`
    and applies a threshold strategy to produce a Boolean mask indicating
    which voxels to *retain* in the final envelope (``True`` = keep,
    ``False`` = carve away).

    For ``violation_count`` scores (time-based / tilted_plane modes),
    a numeric threshold from the config is applied directly.

    Threshold strategies (set via ``cfg.threshold``; the config layer
    normalizes every accepted spelling into a ``ThresholdSpec``):

    * ``cutoff`` (shorthand: a bare number) -- a literal cutoff; voxels with
      ``score <= value`` are kept.
    * ``headtail`` -- Head/tail breaks (Jiang 2013): iteratively splits the
      distribution at the arithmetic mean until the head proportion falls
      below 40 %, targeting heavy-tailed score distributions common in
      urban solar access studies.
    * ``carve_fraction`` (default) -- cumulative-score cutoff: sorts voxels
      by descending score and finds the cutoff that accounts for the given
      fraction of the total score mass.

    Score smoothing (``cfg.score_smoothing``):

    Before thresholding, a Gaussian blur can be applied to the continuous
    score volume to smooth resolution-dependent noise.  This produces a
    cleaner binary mask (and carved mesh) at fine voxel sizes.

    * ``None`` (default) -- auto: ``1.1 × voxel_size`` metres.
    * ``0`` -- disabled, no smoothing.
    * Positive float -- explicit radius in metres.  Rule of thumb: keep
      close to ``voxel_size`` (1.0–1.2×).  Values above 2× ``voxel_size``
      over-smooth and round features.

    Only applied to weighted-score modes (irradiance, benefit, daylight,
    radiative_cooling).  Violation-count modes (time-based, tilted_plane)
    are unaffected.

    Future: target-based thresholding (binary search on carve_fraction to
    achieve a physical performance target in kWh/m²/year) requires iterative
    re-simulation and is not yet implemented.  Use the performance metrics in
    diagnostics/summary.json to manually iterate on carve_fraction.

    Parameters
    ----------
    volume : PreprocessingResult | str | Path
        Either the :class:`PreprocessingResult` returned by the previous
        stage, or a path to its output directory / ``manifest.json``.
    cfg : user_config | str | Path
        Validated config or path to config file.
    out_dir : str | Path
        Output directory for this stage; created if it does not exist.
        All artifacts are written directly into it.

    Returns
    -------
    ThresholdingResult
        Frozen dataclass carrying the mask path and provenance metadata.

    Persisted artifacts
    -------------------
    ``mask.npy``
        3-D Boolean array (same shape as the voxel grid).
    ``manifest.json``
        ``ThresholdingManifest`` recording the resolved threshold value,
        upstream hash, and file paths.
    ``diagnostics/``
        Score histogram with threshold line overlay, voxel retention
        statistics, and wall/CPU timings.
    """
    # Timers start.
    t0_wall = time.perf_counter()
    t0_cpu = time.process_time()
    conf = _resolve_cfg(cfg)
    out_path = _ensure_out_dir(out_dir, "thresholding")

    # Resolve upstream manifest.
    if isinstance(volume, (str, Path)):
        pre_manifest_path = Path(volume)
        if pre_manifest_path.is_dir():
            pre_manifest_path = pre_manifest_path / "manifest.json"
    else:
        pre_manifest_path = volume.manifest_path
    try:
        pre_manifest = schema_from_json(PreprocessingManifest, pre_manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("Unable to load preprocessing manifest") from exc

    scores_path = Path(pre_manifest.scores_path)
    upstream_hash = pre_manifest.hash
    grid_shape = tuple(pre_manifest.shape)
    kind = pre_manifest.scores_kind

    # Load scores — validate against the manifest so a stale or mismatched
    # artifact fails here with a clear message instead of deep in numpy.
    if not scores_path.is_file():
        raise FileNotFoundError(
            f"Scores file not found: {scores_path} (referenced by manifest "
            f"{pre_manifest_path}). Re-run preprocessing, or fix the manifest path."
        )
    raw = np.load(scores_path, allow_pickle=False)
    if raw.ndim == 1:
        raw = raw.reshape(grid_shape)
    elif tuple(raw.shape) != grid_shape:
        raise ValueError(
            f"Scores array shape {tuple(raw.shape)} does not match the grid shape "
            f"{grid_shape} recorded in {pre_manifest_path} — the scores file and "
            f"manifest are from different runs."
        )

    # Guard the consumer side too: thresholding can run standalone (CLI,
    # daemon, Grasshopper) on a scores.npy that never went through this
    # process's preprocessing, and `score <= thr` silently carves every
    # non-finite voxel.
    warn_score_anomalies(raw, context="thresholding")

    raw, _smooth_applied, _smooth_radius_m, _sigma_voxels = _apply_score_smoothing(
        raw, kind, pre_manifest.voxel_size, conf.score_smoothing
    )

    scores = raw.astype(np.float32, copy=False)
    spec = conf.threshold
    # Cross-check config vs manifest: standalone re-thresholding can pair a
    # weighted-mode config with violation-count scores (or vice versa) —
    # the config-time validation only saw the config's own mode.
    if kind == "violation_count" and spec.method != "cutoff":
        raise ValueError(
            f"Scores in {scores_path} are violation counts (preprocessing mode "
            f"'{pre_manifest.mode}'), but the config requests threshold method "
            f"'{spec.method}'. Use a numeric threshold (tolerated violation "
            f"count) or match the config mode to the preprocessing run."
        )
    thr_val = _resolve_threshold(scores, spec)

    # Threshold to mask.
    mask = (scores <= thr_val).reshape(grid_shape)
    if mask.all():
        import warnings
        warnings.warn(
            f"Thresholding produced an all-True mask (nothing carved). "
            f"Threshold value {thr_val:.4g} may be too high.",
            stacklevel=2,
        )
    elif not mask.any():
        import warnings
        warnings.warn(
            f"Thresholding produced an all-False mask (everything carved). "
            f"Threshold value {thr_val:.4g} may be too low.",
            stacklevel=2,
        )
    mask_path = out_path / "mask.npy"
    np.save(mask_path, mask, allow_pickle=False)

    # Stable stage hash for reproducibility: method + configured value,
    # never the resolved (score-dependent) cutoff.
    snippet = {
        "threshold_method": spec.method,
        "threshold_value": spec.value,
        "score_smoothing": conf.score_smoothing,
    }
    stage_hash = hashlib.sha256((json.dumps(snippet, sort_keys=True) + upstream_hash).encode()).hexdigest()[:8]

    # Manifest.
    tm = ThresholdingManifest(
        hash=stage_hash,
        mask_path=str(mask_path),
        upstream_manifest=str(pre_manifest_path),
    )
    (out_path / "manifest.json").write_text(schema_to_json(tm), encoding="utf-8")

    # Per-stage diagnostics
    diag_dir = ensure_diag(out_path)
    nn = np.asarray(scores).ravel()
    total_voxels = int(nn.size)
    kept = int(mask.sum())
    removed = total_voxels - kept
    threshold_method = spec.method
    summary = {
        "threshold_method": threshold_method,
        "threshold_value": float(thr_val),
        "voxels_total": total_voxels,
        "voxels_kept": kept,
        "voxels_removed": removed,
        "retention_pct": round(100.0 * kept / max(total_voxels, 1), 2),
        "mask_shape": [int(x) for x in grid_shape],
        "upstream_hash": upstream_hash,
        "score_smooth_applied": _smooth_applied,
        "score_smoothing_m": _smooth_radius_m,
        "score_smoothing_sigma_voxels": _sigma_voxels,
        "normalized_score_stats": score_statistics(nn, detailed=conf.diagnostics),
    }
    # Performance reporting — physical units from mode registry
    mode_name = pre_manifest.mode or "unknown"
    mode_spec = MODES.get(mode_name)
    weight_unit = mode_spec.weight_unit if mode_spec else "dimensionless"
    # Load patch weights if available
    pw_path = pre_manifest.patch_weights_path
    n_samples = pre_manifest.sample_point_count
    if pw_path and Path(pw_path).is_file():
        patch_weights = np.load(pw_path, allow_pickle=False)
        total_weight = float(patch_weights.sum())
        summary["total_patch_weight"] = total_weight
        summary["weight_unit"] = weight_unit
        # Obstruction removed: sum of scores of carved voxels / total score mass
        carved_mask = ~mask.ravel()  # True = carved away
        score_mass_carved = float(nn[carved_mask].sum())
        score_mass_total = float(nn.sum())
        if score_mass_total > 0:
            summary["obstruction_fraction_carved"] = round(score_mass_carved / score_mass_total, 4)
        if n_samples and n_samples > 0:
            # Mean score per sample point gives avg obstruction per point
            summary["mean_obstruction_per_sample"] = round(score_mass_total / n_samples, 2)
            summary["mean_obstruction_carved_per_sample"] = round(score_mass_carved / n_samples, 2)
            summary["sample_point_count"] = n_samples

    # Histogram with threshold line — only when diagnostic plots are enabled.
    if conf.diagnostic_plots:
        summary["threshold_histogram"] = str(diag_dir / "threshold_histogram.png")
        save_histogram(
            nn, diag_dir, "threshold_histogram.png",
            threshold_line=thr_val,
            title=f"Voxel Scores — threshold={thr_val:.4g} ({threshold_method})",
            xlabel=weight_unit,
        )

    # Consolidated diagnostic — one file per stage.
    summary["timings"] = {
        "wall_seconds": float(time.perf_counter() - t0_wall),
        "cpu_seconds": float(time.process_time() - t0_cpu),
    }
    write_json(diag_dir, "diagnostic.json", summary)

    return ThresholdingResult(
        out_dir=out_path,
        mask_path=mask_path,
        hash=stage_hash,
        upstream=upstream_hash,
        upstream_manifest=pre_manifest_path,
        threshold_method=threshold_method,
        threshold_value=float(thr_val),
        voxels_kept=kept,
        voxels_removed=removed,
        retention_pct=round(100.0 * kept / max(total_voxels, 1), 2),
    )