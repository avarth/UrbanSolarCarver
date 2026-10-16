from __future__ import annotations
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Union, overload
import numpy as np
from ..load_config import user_config
from ..errors import StageChainError
from ..pydantic_schemas import ThresholdingManifest, ThresholdSpec
from ..run_context import Issue, RunContext, report_issue, stage_context
from ..scoring import carve_fraction_threshold, headtail_threshold
from ..carving import carve_above_scores, limit_column_slope
from ..mode_registry import MODES
from ..stage_settings import (
    RunOptions, ThresholdingSettings, applied_smoothing_radius_m, requested_smoothing_radius_m,
)
from ._util import _resolve_cfg, ensure_diag, load_occupancy
from ._stage_io import (
    LoadedManifest, begin_stage, commit_manifest, load_upstream, new_run_id, stored_path,
)
from ._diagnostics import (
    ThresholdingPlotInputs, score_statistics, warn_score_anomalies,
    write_thresholding_diagnostics,
)

# Everything thresholding writes into its folder, besides manifest.json.
_THRESHOLDING_OUTPUTS = (
    "mask.npy", "diagnostics/diagnostic.json", "diagnostics/threshold_histogram.png",
)

@dataclass(frozen=True)
class ThresholdingResult:
    """Immutable record returned by :func:`thresholding`.

    Stores the path to the binary mask, the provenance chain back to the
    upstream preprocessing run (``upstream_run_id`` and ``upstream_manifest``
    path), the resolved threshold, and voxel counts over occupied voxels.
    Implements ``__fspath__`` (returning the manifest path) so it can be
    passed directly as a path-like to :func:`exporting`.
    """
    out_dir: Path
    mask_path: Path
    run_id: str
    upstream_run_id: str
    upstream_manifest: Path
    threshold_method: str = ""
    threshold_value: float = 0.0
    voxels_kept: int = 0
    voxels_removed: int = 0
    retention_pct: float = 0.0
    issues: tuple[Issue, ...] = ()
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

    Returns (scores, applied, radius_m, sigma_voxels), where radius_m is the
    radius after clipping.
    """
    if kind != "weighted_sum":
        return raw, False, 0.0, 0.0

    requested_m = requested_smoothing_radius_m(kind, voxel_size, score_smoothing)
    if requested_m <= 0:
        return raw, False, 0.0, 0.0

    from scipy.ndimage import gaussian_filter
    radius_m = applied_smoothing_radius_m(kind, voxel_size, score_smoothing)
    sigma_voxels = radius_m / voxel_size
    if radius_m != requested_m:
        report_issue(
            "smoothing_radius_clipped",
            f"score_smoothing={requested_m:g} m is {requested_m / voxel_size:.2g} voxels; clipped to "
            f"{sigma_voxels:g} voxels ({radius_m:g} m).",
        )
    if occ is None:
        smoothed = gaussian_filter(raw.astype(np.float32), sigma=sigma_voxels)
        return smoothed, True, radius_m, sigma_voxels
    w = occ.astype(np.float32)
    num = gaussian_filter(np.where(occ, raw, 0.0).astype(np.float32), sigma=sigma_voxels)
    den = gaussian_filter(w, sigma=sigma_voxels)
    smoothed = np.where(occ, num / np.maximum(den, 1e-12), 0.0).astype(np.float32)
    return smoothed, True, radius_m, sigma_voxels


def _resolve_threshold(scores, spec, removal_scores=None):
    """Resolve a validated :class:`ThresholdSpec` into a numeric cutoff.

    *spec* is complete and valid for the mode
    (``ThresholdingSettings.effective_values``), so this only
    dispatches: ``cutoff`` is the value itself; ``headtail`` (Jiang 2013
    head/tail breaks) and ``carve_fraction`` (a score-mass cutoff, not a
    percentile of voxel counts) compute it from *scores*.

    *removal_scores* (same shape as *scores*): the cutoff at which each
    voxel is removed once carve_above runs
    (:func:`~urbansolarcarver.carving.carve_above_scores`).  carve_fraction
    then ranks by it and counts *scores*, so the fraction includes what
    carve_above removes.
    """
    if spec.method == "cutoff":
        return float(spec.value)
    if spec.method == "headtail":
        return float(headtail_threshold(scores, max_iterations=50))
    if spec.method == "carve_fraction":
        if removal_scores is None:
            return carve_fraction_threshold(scores, float(spec.value))
        return carve_fraction_threshold(removal_scores, float(spec.value), mass=scores)
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
    normalizes every accepted spelling into a ``ThresholdSpec``, and
    ``cfg.resolved_threshold()`` fills in the mode default when it is
    unset):

    * ``cutoff`` (shorthand: a bare number): a literal cutoff; voxels with
      ``score <= value`` are kept.
    * ``headtail``: head/tail breaks (Jiang 2013).  The scores are split at
      their mean; while the part above the mean (the head) holds at most
      40 % of the values, the head is split again at its own mean.  The
      last such mean is the cutoff.  Suited to the heavy-tailed score
      distributions common in urban solar access studies.
    * ``carve_fraction`` (default for weighted modes): cumulative-score
      cutoff.  It finds the cutoff at which the removed voxels hold the
      given fraction of the building's total score mass, counting the
      voxels that carve_above removes along with them.

    All threshold statistics, retention counts and smoothing use occupied
    voxels only; the mask is False on empty cells.  With ``carve_above``
    (the default), occupied voxels above a carved run in their column are
    removed as well.  Then, for the score-cutoff methods of the weighted
    modes (or whenever ``max_slope_deg`` is set), columns that rise more
    steeply than ``max_slope_deg`` above their surroundings are cut down
    (:func:`~urbansolarcarver.carving.limit_column_slope`); this removes
    some score beyond the fraction, reported as
    ``obstruction_fraction_carved_by_slope_limit``.  ``mask.npy`` is the
    final mask that gets exported.

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
        ``ThresholdingManifest`` recording a random ``run_id`` (new on every
        run), the mask path, the path and ``run_id`` of the upstream
        preprocessing manifest (paths relative to the manifest's folder), and
        the resolved threshold strategy, score smoothing radius (m) and slope
        limit this run applied.  The
        outputs of an earlier run in *out_dir* are deleted first and the
        manifest is written last, after the diagnostics.
    ``diagnostics/``
        ``diagnostic.json`` (resolved threshold, voxel retention, smoothing
        and carve_above statistics, wall/CPU timings) and, with
        ``cfg.diagnostic_plots``, a score histogram with the threshold line.

    Raises
    ------
    StageChainError
        If the preprocessing manifest cannot be read, the config's mode
        differs from the preprocessing run's, or the scores or the occupancy
        grid it names are missing or do not match its grid shape (a
        ValueError; the message names the stage to re-run).
    ValueError
        If a non-numeric threshold is used with violation-count scores.
    """
    with stage_context("thresholding") as context:
        conf = _resolve_cfg(cfg)
        out_path = begin_stage(out_dir, _THRESHOLDING_OUTPUTS)
        pre = load_upstream(volume, "preprocessing")
        # The threshold defaults and units differ per mode, and the settings
        # model does not carry the mode. A standalone re-thresholding (CLI,
        # daemon, Grasshopper) can pair a config with scores from a run in
        # another mode, so refuse it here instead of carving with the wrong rule.
        if pre.manifest.mode != conf.mode:
            raise StageChainError(
                f"The scores in {pre.resolve(pre.manifest.scores_path)} come from a "
                f"'{pre.manifest.mode}' run, but the config's mode is '{conf.mode}'. "
                f"Re-run preprocessing or use a config with mode '{pre.manifest.mode}'."
            )
        return _run_thresholding(
            ThresholdingSettings.from_config(conf), RunOptions.from_config(conf),
            pre, out_path, context)


def _run_thresholding(settings: ThresholdingSettings, options: RunOptions, upstream: LoadedManifest,
                      out_path: Path, context: RunContext) -> ThresholdingResult:
    """The computation of :func:`thresholding`, from its own settings only.

    *upstream* is the loaded preprocessing manifest: its mode and voxel size
    resolve the settings' defaults.  *out_path* is the stage folder, already
    cleared by :func:`begin_stage`.
    """
    t0_wall = time.perf_counter()
    t0_cpu = time.process_time()
    pre = upstream
    pre_manifest, pre_manifest_path = pre.manifest, pre.manifest_path
    scores_path = pre.resolve(pre_manifest.scores_path)
    grid_shape = tuple(pre_manifest.shape)
    kind = pre_manifest.scores_kind

    # Load scores and check them against the manifest so a stale or mismatched
    # artifact fails here with a clear message instead of deep in numpy.
    if not scores_path.is_file():
        raise StageChainError(
            f"Scores file not found: {scores_path} (referenced by manifest "
            f"{pre_manifest_path}). Re-run preprocessing."
        )
    raw = np.load(scores_path, allow_pickle=False)
    if raw.ndim == 1:
        raw = raw.reshape(grid_shape)
    elif tuple(raw.shape) != grid_shape:
        raise StageChainError(
            f"Scores array shape {tuple(raw.shape)} does not match the grid shape "
            f"{grid_shape} recorded in {pre_manifest_path}; the scores file and "
            f"manifest are from different runs. Re-run preprocessing."
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
    occ = load_occupancy(pre)

    raw, _smooth_applied, _smooth_radius_m, _sigma_voxels = _apply_score_smoothing(
        raw, kind, pre_manifest.voxel_size, settings.score_smoothing, occ=occ
    )

    scores = raw.astype(np.float32, copy=False)
    occ_scores = scores[occ]
    effective = settings.effective_values(pre_manifest.mode, pre_manifest.voxel_size)
    spec = ThresholdSpec.model_validate(effective["threshold"])
    if kind == "violation_count" and spec.method != "cutoff":
        raise ValueError(
            f"Scores in {scores_path} are violation counts (preprocessing mode "
            f"'{pre_manifest.mode}'), but the config requests threshold method "
            f"'{spec.method}'. Use a numeric threshold (a raw-score cutoff) "
            f"or match the config mode to the preprocessing run."
        )
    # With carve_above, each voxel goes at the cutoff of the lowest
    # carved run below it; comparing that value with the cutoff gives the
    # mask after carve_above, and lets carve_fraction count what it removes.
    removal_scores = (carve_above_scores(scores.reshape(grid_shape), occ,
                                         effective["carve_above_min_consecutive"])
                      if effective["carve_above"] else None)
    thr_val = _resolve_threshold(
        occ_scores, spec, None if removal_scores is None else removal_scores[occ])

    # Threshold to mask. Empty cells are False: there is nothing to keep.
    mask = occ & (scores <= thr_val).reshape(grid_shape)
    if mask.sum() == occ.sum():
        report_issue(
            "nothing_carved",
            f"Thresholding produced an all-True mask (nothing carved). "
            f"Threshold value {thr_val:.4g} may be too high.",
        )
    elif not mask.any():
        report_issue(
            "everything_carved",
            f"Thresholding produced an all-False mask (everything carved). "
            f"Threshold value {thr_val:.4g} may be too low.",
        )
    # Column post-processing belongs to the mask, so that mask.npy and the
    # retention reported below describe the envelope that gets exported.
    carve_above_removed = 0
    if effective["carve_above"]:
        kept_before = int(mask.sum())
        mask = occ & (removal_scores <= thr_val)
        carve_above_removed = kept_before - int(mask.sum())
    # Slope limit: turns cliffs and spires left by per-voxel cutoffs into ramps.
    max_slope = effective["max_slope_deg"]
    mask_before_slope = mask
    if max_slope is not None:
        mask = limit_column_slope(mask, occ, max_slope)
    slope_removed = int(mask_before_slope.sum()) - int(mask.sum())

    mask_path = out_path / "mask.npy"
    np.save(mask_path, mask, allow_pickle=False)

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
        "upstream_run_id": pre_manifest.run_id,
        "carve_above_applied": effective["carve_above"],
        "carve_above_min_consecutive": effective["carve_above_min_consecutive"] if effective["carve_above"] else None,
        "carve_above_extra_voxels_removed": carve_above_removed,
        "max_slope_deg": max_slope,
        "slope_limit_extra_voxels_removed": slope_removed,
        "score_smooth_applied": _smooth_applied,
        "score_smoothing_m": _smooth_radius_m,
        "score_smoothing_sigma_voxels": _sigma_voxels,
        # Scores the threshold was compared with: occupied voxels only, after
        # score smoothing when it is applied.
        "occupied_score_stats": score_statistics(nn, detailed=options.diagnostics),
    }
    # Performance reporting, with the score unit from the mode registry
    weight_unit = MODES[pre_manifest.mode].weight_unit
    # Load patch weights if available
    pw_path = pre_manifest.patch_weights_path
    n_samples = pre_manifest.sample_point_count
    if pw_path and pre.resolve(pw_path).is_file():
        patch_weights = np.load(pre.resolve(pw_path), allow_pickle=False)
        total_weight = float(patch_weights.sum())
        summary["total_patch_weight"] = total_weight
        summary["weight_unit"] = weight_unit
        # Obstruction removed: score mass of carved voxels / building score mass
        carved_mask = ~mask[occ]  # aligned with nn (occupied voxels)
        score_mass_carved = float(nn[carved_mask].sum())
        score_mass_total = float(nn.sum())
        if score_mass_total > 0:
            summary["obstruction_fraction_carved"] = round(score_mass_carved / score_mass_total, 4)
            by_slope = float(nn[mask_before_slope[occ] & ~mask[occ]].sum())
            summary["obstruction_fraction_carved_by_slope_limit"] = round(
                by_slope / score_mass_total, 4)
        if n_samples and n_samples > 0:
            # Score mass divided by the number of sample points
            summary["mean_obstruction_per_sample"] = round(score_mass_total / n_samples, 2)
            summary["mean_obstruction_carved_per_sample"] = round(score_mass_carved / n_samples, 2)
            summary["sample_point_count"] = n_samples

    # One diagnostic file per stage; the writer also draws the histogram
    # with the threshold line when diagnostic plots are enabled.
    summary["timings"] = {
        "wall_seconds": float(time.perf_counter() - t0_wall),
        "cpu_seconds": float(time.process_time() - t0_cpu),
    }
    write_thresholding_diagnostics(
        summary, diag_dir,
        ThresholdingPlotInputs(
            occupied_scores=nn, threshold_value=float(thr_val),
            method=threshold_method, weight_unit=weight_unit),
        options.diagnostic_plots,
    )

    # Manifest last (see begin_stage at the start).
    run_id = new_run_id()
    commit_manifest(out_path, ThresholdingManifest(
        run_id=run_id,
        mask_path=stored_path(mask_path, out_path),
        upstream_manifest=stored_path(pre_manifest_path, out_path),
        upstream_run_id=pre_manifest.run_id,
        resolved_threshold=spec,
        score_smoothing_m=_smooth_radius_m,
        max_slope_deg=max_slope,
    ))

    return ThresholdingResult(
        out_dir=out_path,
        mask_path=mask_path,
        run_id=run_id,
        upstream_run_id=pre_manifest.run_id,
        upstream_manifest=pre_manifest_path,
        threshold_method=threshold_method,
        threshold_value=float(thr_val),
        voxels_kept=kept,
        voxels_removed=removed,
        retention_pct=round(100.0 * kept / max(occupied, 1), 2),
        issues=context.issues_of("thresholding"),
    )