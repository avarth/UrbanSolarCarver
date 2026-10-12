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
from ..scoring import (
    carve_fraction_threshold, headtail_threshold, protected_patch_count, protection_order,
)
from ..carving import carve_above_columns
from ..mode_registry import MODES
from ._util import _resolve_cfg, _ensure_out_dir, ensure_diag, write_json, load_occupancy
from ._diagnostics import save_histogram, score_statistics, warn_score_anomalies

@dataclass(frozen=True)
class ThresholdingResult:
    """Immutable record returned by :func:`thresholding`.

    Stores the path to the binary mask, the provenance chain back to the
    upstream preprocessing run (``upstream`` hash and ``upstream_manifest``
    path), the resolved threshold, and voxel counts over occupied voxels.
    Implements ``__fspath__`` (returning the manifest path) so it can be
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

def _apply_score_smoothing(raw, kind, voxel_size, score_smoothing, occ=None):
    """Gaussian-blur the continuous score volume before thresholding.

    Smooths resolution-dependent noise so the binary mask (and carved mesh)
    is cleaner at fine voxel sizes.  Only applied to weighted-score modes;
    violation-count modes (time-based, tilted_plane) are left untouched.

    With an occupancy grid *occ*, the blur is a normalized convolution over
    occupied voxels only: G*(s·occ) / G*occ, and empty cells are set to 0.
    Empty cells carry the scores of every ray crossing the street or
    courtyard in front of a facade; a plain blur would leak that air into
    the building's boundary voxels.

    ``score_smoothing``: None means auto (1.1 × voxel_size), 0 disables
    smoothing, and a positive value is the radius in meters.  The radius is
    used as the Gaussian sigma and clipped to 0.5-8 voxels (with a warning).
    Smoothing is skipped with a warning if *voxel_size* is missing.

    Returns (scores, applied, radius_m, sigma_voxels), where radius_m is the
    radius after clipping.
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
            "voxel_size, so meters cannot be converted to voxels; skipping smoothing. "
            "Re-run preprocessing to regenerate the manifest.",
            stacklevel=3,
        )
        return raw, False, 0.0, 0.0

    from scipy.ndimage import gaussian_filter
    requested = radius_m / voxel_size
    sigma_voxels = float(np.clip(requested, 0.5, 8.0))
    if sigma_voxels != requested:
        import warnings
        warnings.warn(
            f"score_smoothing={radius_m:g} m is {requested:.2g} voxels; clipped to "
            f"{sigma_voxels:g} voxels ({sigma_voxels * voxel_size:g} m).",
            stacklevel=3,
        )
        radius_m = sigma_voxels * voxel_size
    if occ is None:
        smoothed = gaussian_filter(raw.astype(np.float32), sigma=sigma_voxels)
        return smoothed, True, radius_m, sigma_voxels
    w = occ.astype(np.float32)
    num = gaussian_filter(np.where(occ, raw, 0.0).astype(np.float32), sigma=sigma_voxels)
    den = gaussian_filter(w, sigma=sigma_voxels)
    smoothed = np.where(occ, num / np.maximum(den, 1e-12), 0.0).astype(np.float32)
    return smoothed, True, radius_m, sigma_voxels


def _protect_patches(pre_manifest, pre_manifest_path, share):
    """Carved voxels for the protect_share method, plus diagnostics.

    Returns a dict with ``carved`` (flat bool array: the voxel blocks one of
    the protected patches) and the diagnostic entries
    ``protected_patch_count``, ``protected_patches`` (Tregenza indices) and
    ``protected_weight_share`` (the share actually protected, which can
    exceed *share* because patches are whole).
    """
    rank_path = pre_manifest.patch_rank_path
    weights_path = pre_manifest.patch_weights_path
    if not (rank_path and Path(rank_path).is_file() and weights_path
            and Path(weights_path).is_file()):
        raise ValueError(
            f"threshold method protect_share needs patch_rank.npy and "
            f"patch_weights.npy from preprocessing, and {pre_manifest_path} does not "
            f"point to them (it was written by an older USC version, or by a mode "
            f"without sky patches). Re-run preprocessing."
        )
    weights = np.load(weights_path, allow_pickle=False)
    rank = np.load(rank_path, allow_pickle=False)
    n = protected_patch_count(weights, share)
    order = protection_order(weights)
    positive = float(weights[order].sum()) if order.size else 0.0
    return {
        "carved": rank < n,
        "protected_patch_count": n,
        "protected_patches": [int(i) for i in order[:n]],
        "protected_weight_share": round(float(weights[order[:n]].sum()) / positive, 4)
        if positive > 0 else 0.0,
    }


def _resolve_threshold(scores, spec):
    """Resolve a validated :class:`ThresholdSpec` into a numeric cutoff.

    The config layer guarantees the spec is complete and valid for the
    mode (see ``UserConfig._resolve_threshold_spec``), so this only
    dispatches: ``cutoff`` is the value itself; ``headtail`` (Jiang 2013
    head/tail breaks) and ``carve_fraction`` (a score-mass cutoff, not a
    percentile of voxel counts) compute it from *scores*.
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

    For ``violation_count`` scores (time-based / tilted_plane modes), only
    a numeric threshold (``cutoff``) is accepted and applied directly.

    Threshold strategies (set via ``cfg.threshold``; the config layer
    normalizes every accepted spelling into a ``ThresholdSpec``):

    * ``cutoff`` (shorthand: a bare number): a literal cutoff; voxels with
      ``score <= value`` are kept.
    * ``headtail``: head/tail breaks (Jiang 2013).  The scores are split at
      their mean; while the part above the mean (the head) holds at most
      40 % of the values, the head is split again at its own mean.  The
      last such mean is the cutoff.  Suited to the heavy-tailed score
      distributions common in urban solar access studies.
    * ``protect_share`` (default for weighted modes): sky-patch
      protection.  The sky patches are ranked by weight; the top patches
      holding the given share of the total weight are protected, and every
      voxel that blocks one of them from some test point is carved.  Uses
      ``patch_rank.npy`` from preprocessing, so the scores are not used and
      score smoothing does not apply.  Because whole rays are cleared, the
      envelope varies continuously, as in time-based carving.
    * ``carve_fraction``: cumulative-score cutoff.  Sorting the occupied
      voxels by descending score, it finds the cutoff above which the voxels
      hold the given fraction of the building's total score mass.  With
      ``carve_above`` each column is then decided by its highest-scoring
      voxel, which can leave cliffs and single-voxel spires.

    All threshold statistics, retention counts and smoothing use occupied
    voxels only; the mask is False on empty cells.  With ``carve_above``
    (the default), occupied voxels above a carved run in their column are
    removed as well, so ``mask.npy`` is the final mask that gets exported.

    Score smoothing (``cfg.score_smoothing``):

    Before thresholding, a Gaussian blur can be applied to the continuous
    score volume to smooth resolution-dependent noise.  This produces a
    cleaner binary mask (and carved mesh) at fine voxel sizes.

    * ``None`` (default): auto, ``1.1 × voxel_size`` metres.
    * ``0``: disabled, no smoothing.
    * Positive float: explicit radius (Gaussian sigma) in metres.  Rule of
      thumb: keep close to ``voxel_size`` (1.0–1.2×).  Values above 2×
      ``voxel_size`` over-smooth and round features.

    Only applied to weighted-score modes (irradiance, benefit, daylight,
    radiative_cooling).  Violation-count modes (time-based, tilted_plane)
    are unaffected.

    To tune ``carve_fraction`` against a performance target, compare
    ``obstruction_fraction_carved`` in ``diagnostics/diagnostic.json``
    across runs.

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
        3-D Boolean array (same shape as the voxel grid), True = keep.
    ``manifest.json``
        ``ThresholdingManifest`` recording the stage hash, the mask path and
        the path of the upstream preprocessing manifest.
    ``diagnostics/``
        ``diagnostic.json`` (resolved threshold, voxel retention, smoothing
        and carve_above statistics, wall/CPU timings) and, with
        ``cfg.diagnostic_plots``, a score histogram with the threshold line.

    Raises
    ------
    ValueError
        If the preprocessing manifest cannot be read, the scores do not
        match its grid shape, the config's mode differs from the
        preprocessing run's, a non-numeric threshold is used with
        violation-count scores, or protect_share is used with a
        preprocessing run that has no ``patch_rank.npy``.
    FileNotFoundError
        If the scores file named in the manifest is missing.
    """
    t0_wall = time.perf_counter()
    t0_cpu = time.process_time()
    conf = _resolve_cfg(cfg)
    out_path = _ensure_out_dir(out_dir, "thresholding")
    (out_path / "manifest.json").unlink(missing_ok=True)  # written last; see preprocessing

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

    # Load scores and check them against the manifest so a stale or mismatched
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
            f"{grid_shape} recorded in {pre_manifest_path}; the scores file and "
            f"manifest are from different runs."
        )

    # Guard the consumer side too: thresholding can run standalone (CLI,
    # daemon, Grasshopper) on a scores.npy that never went through this
    # process's preprocessing, and `score <= thr` silently carves every
    # NaN voxel.
    warn_score_anomalies(raw, context="thresholding")

    # Only occupied voxels can be kept or carved. Empty cells still hold
    # score (rays cross streets and courtyards), and 60-80% of the total
    # score mass can sit there, so every statistic below is taken over the
    # building alone; otherwise carve_fraction/headtail would depend on how
    # much air the grid happens to contain.
    occ = load_occupancy(pre_manifest, conf)

    spec = conf.threshold
    if spec.method == "protect_share":
        # The mask comes from patch_rank.npy; smoothing the scores would
        # change nothing but the statistics below.
        _smooth_applied, _smooth_radius_m, _sigma_voxels = False, 0.0, 0.0
    else:
        raw, _smooth_applied, _smooth_radius_m, _sigma_voxels = _apply_score_smoothing(
            raw, kind, pre_manifest.voxel_size, conf.score_smoothing, occ=occ
        )

    scores = raw.astype(np.float32, copy=False)
    occ_scores = scores[occ]
    # Standalone re-thresholding (CLI, daemon, Grasshopper) can pair a config
    # with scores from a run in another mode; the threshold defaults and
    # units differ per mode, so refuse instead of carving with the wrong rule.
    if pre_manifest.mode and pre_manifest.mode != conf.mode:
        raise ValueError(
            f"The scores in {scores_path} come from a '{pre_manifest.mode}' run, but "
            f"the config's mode is '{conf.mode}'. Re-run preprocessing or use a "
            f"config with mode '{pre_manifest.mode}'."
        )
    if kind == "violation_count" and spec.method != "cutoff":
        raise ValueError(
            f"Scores in {scores_path} are violation counts (preprocessing mode "
            f"'{pre_manifest.mode}'), but the config requests threshold method "
            f"'{spec.method}'. Use a numeric threshold (a raw-score cutoff) "
            f"or match the config mode to the preprocessing run."
        )
    protection = None
    if spec.method == "protect_share":
        protection = _protect_patches(pre_manifest, pre_manifest_path, float(spec.value))
        thr_val = float(spec.value)
        # Empty cells are False: there is nothing to keep.
        mask = occ & ~protection.pop("carved").reshape(grid_shape)
    else:
        thr_val = _resolve_threshold(occ_scores, spec)
        # Threshold to mask. Empty cells are False: there is nothing to keep.
        mask = occ & (scores <= thr_val).reshape(grid_shape)
    if mask.sum() == occ.sum():
        import warnings
        warnings.warn(
            f"Thresholding produced an all-True mask (nothing carved). "
            f"{spec} may be too lenient.",
            stacklevel=2,
        )
    elif not mask.any():
        import warnings
        warnings.warn(
            f"Thresholding produced an all-False mask (everything carved). "
            f"{spec} may be too strict.",
            stacklevel=2,
        )
    # Column post-processing belongs to the mask, so that mask.npy and the
    # retention reported below describe the envelope that gets exported.
    carve_above_removed = 0
    if conf.carve_above:
        kept_before = int(mask.sum())
        mask = carve_above_columns(mask, occ, min_consecutive=conf.carve_above_min_consecutive)
        carve_above_removed = kept_before - int(mask.sum())

    mask_path = out_path / "mask.npy"
    np.save(mask_path, mask, allow_pickle=False)

    # Stable stage hash for reproducibility: method + configured value,
    # never the resolved (score-dependent) cutoff.
    snippet = {
        "threshold_method": spec.method,
        "threshold_value": spec.value,
        "score_smoothing": conf.score_smoothing,
        "carve_above": conf.carve_above,
        "carve_above_min_consecutive": conf.carve_above_min_consecutive,
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
    nn = occ_scores
    occupied = int(occ.sum())
    kept = int(mask.sum())
    removed = occupied - kept
    threshold_method = spec.method
    summary = {
        "threshold_method": threshold_method,
        "threshold_value": float(thr_val),
        "voxels_grid": int(np.prod(grid_shape)),
        "voxels_occupied": occupied,
        "voxels_kept": kept,
        "voxels_removed": removed,
        "retention_pct": round(100.0 * kept / max(occupied, 1), 2),
        "mask_shape": [int(x) for x in grid_shape],
        "upstream_hash": upstream_hash,
        "carve_above_applied": conf.carve_above,
        "carve_above_min_consecutive": conf.carve_above_min_consecutive if conf.carve_above else None,
        "carve_above_extra_voxels_removed": carve_above_removed,
        "score_smooth_applied": _smooth_applied,
        "score_smoothing_m": _smooth_radius_m,
        "score_smoothing_sigma_voxels": _sigma_voxels,
        # Scores the threshold was compared with: occupied voxels only, after
        # score smoothing when it is applied.
        "occupied_score_stats": score_statistics(nn, detailed=conf.diagnostics),
    }
    if protection is not None:
        summary.update(protection)
    # Performance reporting, with the score unit from the mode registry
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
        # Obstruction removed: score mass of carved voxels / building score mass
        carved_mask = ~mask[occ]  # aligned with nn (occupied voxels)
        score_mass_carved = float(nn[carved_mask].sum())
        score_mass_total = float(nn.sum())
        if score_mass_total > 0:
            summary["obstruction_fraction_carved"] = round(score_mass_carved / score_mass_total, 4)
        if n_samples and n_samples > 0:
            # Score mass divided by the number of sample points
            summary["mean_obstruction_per_sample"] = round(score_mass_total / n_samples, 2)
            summary["mean_obstruction_carved_per_sample"] = round(score_mass_carved / n_samples, 2)
            summary["sample_point_count"] = n_samples

    # Histogram with threshold line, only when diagnostic plots are enabled.
    if conf.diagnostic_plots:
        summary["threshold_histogram"] = str(diag_dir / "threshold_histogram.png")
        save_histogram(
            nn, diag_dir, "threshold_histogram.png",
            threshold_line=None if protection is not None else thr_val,
            title=f"Voxel scores, threshold={thr_val:.4g} ({threshold_method})",
            xlabel=weight_unit,
        )

    # One diagnostic file per stage.
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
        retention_pct=round(100.0 * kept / max(occupied, 1), 2),
    )