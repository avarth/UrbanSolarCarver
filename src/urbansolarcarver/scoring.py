"""
UrbanSolarCarver scoring module

Sky-patch weight computation and threshold selection for voxel carving.

1. get_weights(mode, device, epw_file, hoys, …) → torch.Tensor
   Per-patch weight vector for the specified mode.  Delegates to
   compute_EPW_based_weights (sky_patches.py) for irradiance, benefit and
   daylight, and to compute_radiative_cooling_weights for radiative_cooling.
   Inside a CarverSession the result is cached, keyed by every argument
   and by the contents of the EPW and simulated-weights files, so a
   preprocessing run with unchanged weather settings skips the sky matrix.

2. carve_fraction_threshold(scores, fraction) → float
   Score cutoff above which the highest-scoring voxels hold *fraction* of
   the total score.

3. headtail_threshold(scores) → float
   Head/tail breaks (Jiang 2013): repeatedly splits a right-skewed score
   distribution at its arithmetic mean.  Suited to obstruction scores,
   which are usually heavy-tailed.
"""
import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
import torch

from .compute_device import resolve_compute_device
from .session import session_cache
from .sky_patches import compute_EPW_based_weights, compute_radiative_cooling_weights
from typing import Sequence


def _file_contents_digest(path) -> str:
    """SHA-1 of a file's bytes ("none" without a path), so a file rewritten
    at the same path gets a new digest."""
    if not path:
        return "none"
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def _weights_cache_key(args, kwargs) -> str:
    """Session cache key of a get_weights call: every argument, with the
    device resolved, the hour list hashed, and the EPW and simulated-weights
    files replaced by digests of their contents."""
    call = inspect.signature(get_weights).bind(*args, **kwargs)
    call.apply_defaults()
    values = dict(call.arguments)
    values["device"] = str(resolve_compute_device(values["device"]))
    values["epw_file"] = _file_contents_digest(values["epw_file"])
    values["simulated_weights_path"] = _file_contents_digest(values["simulated_weights_path"])
    if values["hoys"] is not None:
        values["hoys"] = hashlib.sha1(np.asarray(values["hoys"], dtype=np.int64).tobytes()).hexdigest()
    return json.dumps(values, sort_keys=True, default=str)


@session_cache(_weights_cache_key)
def get_weights(
    mode: str,
    device: "torch.device | str | None" = None,
    epw_file: str = None,
    hoys: Sequence[int] = None,
    dew_point_celsius: float = 14.0,
    bliss_k: float = 1.8,
    balance_temperature: float = 15.0,
    balance_offset: float = 2.0,
    north_deg: float = 0.0,
    min_sky_elevation_deg: float = 0.0,
    include_harm: bool = False,
    simulated_weights_path: str = None,
) -> torch.Tensor:
    """
    Return one weight per Tregenza sky patch for the given analysis mode.

    - irradiance: cumulative direct + diffuse irradiance per patch over the
      hours in *hoys* (kWh/m²), from the EPW via a Ladybug sky matrix.
    - benefit: the same, counted only in hours below the heating balance
      point (*balance_temperature* minus *balance_offset*); with
      *include_harm*, irradiance in hours above *balance_temperature* plus
      *balance_offset* is subtracted (clipped at 0).
    - daylight: CIE standard overcast sky luminance; needs no EPW.
    - radiative_cooling: long-wave cooling potential from the dew point
      (Martin-Berdahl emissivity, Bliss angular law), normalized to sum to 1.

    'time-based' and 'tilted_plane' do not use sky-patch weights and raise
    ValueError here.

    Inside a CarverSession the weights are cached (see the module notes):
    the returned tensor may be shared, so callers must not modify it.

    Parameters
    ----------
    mode : str
        One of 'irradiance', 'benefit', 'daylight', 'radiative_cooling'
        (case and surrounding spaces are ignored).
    device : torch.device or str, optional
        Device of the returned tensor; default CUDA if available, else CPU.
    epw_file : str, optional
        EPW weather file; required for irradiance and benefit.
    hoys : Sequence[int], optional
        Hour-of-year indices (0..8759); required for irradiance and benefit.
    dew_point_celsius : float, default 14.0
        Dew-point temperature for radiative_cooling (°C).
    bliss_k : float, default 1.8
        Bliss angular-attenuation constant for radiative_cooling.
    balance_temperature : float, default 15.0
        Free-running balance-point temperature for benefit (°C).
    balance_offset : float, default 2.0
        Dead band around the balance point for benefit (°C).
    north_deg : float, default 0.0
        Model north, degrees clockwise from +Y (irradiance, benefit, daylight).
    min_sky_elevation_deg : float, default 0.0
        radiative_cooling only: patches below this elevation get weight 0.
    include_harm : bool, default False
        benefit only: subtract hot-hour irradiance, as described above.
    simulated_weights_path : str, optional
        benefit only: file of simulated hourly benefit/harm weights, read
        with :func:`read_simulated_weights`; each hour's irradiance is
        scaled by its weight instead of the 0/1 temperature filter.

    Returns
    -------
    torch.Tensor
        Shape (P,), one non-negative weight per sky patch (P = 145).

    Raises
    ------
    TypeError
        If *mode* is not a non-empty string.
    ValueError
        If *mode* is not supported, or *epw_file* / *hoys* are missing for
        irradiance or benefit.
    FileNotFoundError
        If *epw_file* is given but does not exist (irradiance, benefit).
    """
    if not isinstance(mode, str) or not mode.strip():
        raise TypeError(f"get_weights: mode must be a non-empty string, got {mode!r}")
    mode_key = mode.strip().lower()
    device = resolve_compute_device(device)

    if mode_key == 'radiative_cooling':
        return compute_radiative_cooling_weights(
            dew_point_celsius, bliss_k, torch.device(device),
            min_elevation_deg=min_sky_elevation_deg,
        )

    # Daylight: the CIE overcast sky depends only on patch geometry, so no EPW.
    if mode_key == 'daylight':
        return compute_EPW_based_weights(
            mode_key,
            None,              # epw_path not used by daylight
            None,              # hoys not used by daylight
            torch.device(device),
            balance_temperature,
            balance_offset,
            north=north_deg,
        )

    if mode_key in {'irradiance', 'benefit'}:
        if not epw_file or hoys is None or len(hoys) == 0:
            raise ValueError(
                f"get_weights: epw_file and hoys list are required for mode '{mode}'"
            )
        sim_weights = None
        if simulated_weights_path and mode_key == 'benefit':
            from .simulated_weights import read_simulated_weights
            benefit_series, harm_series, _meta = read_simulated_weights(simulated_weights_path)
            sim_weights = (benefit_series, harm_series)
        return compute_EPW_based_weights(
            mode_key,
            epw_file,
            hoys,
            torch.device(device),
            balance_temperature,
            balance_offset,
            north=north_deg,
            include_harm=include_harm,
            simulated_weights=sim_weights,
        )

    raise ValueError(f"get_weights: unsupported mode '{mode}'")




def carve_fraction_threshold(scores: np.ndarray, fraction: float,
                             mass: "np.ndarray | None" = None) -> float:
    """Score-mass cutoff: the threshold above which voxels collectively
    account for *fraction* of the total score mass.

    Equivalent to sorting all scores descending and walking the cumulative
    sum until it reaches ``fraction * total``.  With *mass*, the voxels are
    ranked by *scores* but the sum counts *mass* (thresholding ranks by the
    cutoff at which carve_above removes a voxel and counts each voxel's own
    score, so the fraction includes what carve_above removes).  A full sort of a large grid
    is O(N log N) and takes seconds to minutes at 300³ voxels and above, so
    this implementation makes two O(N) passes instead:

    1. A weighted histogram locates the bin containing the cutoff.
    2. Only the scores inside that single bin (N / n_bins expected) are
       sorted exactly, reproducing the argsort result.

    Parameters
    ----------
    scores : np.ndarray
        Array of non-negative voxel scores (any shape).
    fraction : float
        Fraction of the total score mass to carve, in [0, 1].
    mass : np.ndarray, optional
        Non-negative mass of each voxel, same shape as *scores*; default
        *scores* itself.

    Returns
    -------
    float
        Threshold value; voxels scoring strictly above it are carved.
    """
    flat = scores.ravel()
    weight = flat if mass is None else np.asarray(mass).ravel()
    if flat.size == 0:
        return 0.0
    finite = np.isfinite(flat) & np.isfinite(weight)
    if not finite.all():
        # NaN and +Inf scores are always carved by the downstream
        # `score <= threshold` comparison, so exclude them from the mass
        # calculation instead of letting max()/np.histogram raise on a
        # non-finite range.
        flat, weight = flat[finite], weight[finite]
        if flat.size == 0:
            return 0.0
    vmax = float(flat.max())
    if vmax <= 0.0:
        return 0.0
    # float64 accumulation: float32 cumsum over many elements loses mass
    total = float(weight.sum(dtype=np.float64))
    target = float(fraction) * total
    if target <= 0.0:
        return vmax  # carve nothing: only scores above the max qualify

    # Pass 1: weighted histogram → mass contributed by each score bin.
    n_bins = 8192
    hist, edges = np.histogram(flat, bins=n_bins, range=(0.0, vmax),
                               weights=weight.astype(np.float64, copy=False))
    # Cumulative mass from the top bin downward; mass_above[b] is the mass
    # in bins strictly above b.
    mass_from_top = np.cumsum(hist[::-1])[::-1]
    mass_above = np.concatenate([mass_from_top[1:], [0.0]])
    # Boundary bin: highest bin where including it reaches the target.
    candidates = np.nonzero(mass_from_top >= target)[0]
    if candidates.size == 0:
        return float(flat.min())  # target exceeds all mass (fraction ~ 1)
    b = int(candidates[-1])

    # Pass 2: exact resolution inside the boundary bin only.
    lo_edge = edges[b]
    if b == n_bins - 1:
        in_bin = flat >= lo_edge  # last bin includes vmax
    else:
        in_bin = (flat >= lo_edge) & (flat < edges[b + 1])
    if not in_bin.any():
        return float(lo_edge)
    order = np.argsort(flat[in_bin], kind="stable")[::-1]
    desc = flat[in_bin][order]
    csum = mass_above[b] + np.cumsum(weight[in_bin][order].astype(np.float64))
    idx = int(np.searchsorted(csum, target, side="right"))
    if idx < desc.size:
        return float(desc[idx])
    # Cutoff falls just below this bin: threshold is the largest lower score.
    below = flat[flat < lo_edge]
    return float(below.max()) if below.size else float(desc[-1])


def headtail_threshold(
    scores: np.ndarray,
    max_iterations: int = 50,
    head_limit: float = 0.40,
) -> float:
    """Head/tail breaks cutoff (Jiang, 2013).

    Split the scores at their mean.  If the part above the mean (the head)
    is a minority (at most *head_limit* of the values), the mean is a valid
    break; split the head again at its own mean, and so on.  Stop when the
    head is no longer a minority (or is empty).

    Returns the last valid break, so only the heaviest obstructors score
    above it.  If even the first split has a majority head (no heavy tail),
    the overall mean is returned.

    Example: 80 values of 1, 16 of 10 and 4 of 100 give breaks 6.4 (head
    20 %) and 28 (head 20 %), then an empty head: the cutoff is 28.
    """
    current = np.asarray(scores, dtype=np.float64).ravel()
    current = current[np.isfinite(current)]
    if current.size == 0:
        return 0.0
    threshold = float(current.mean())
    for _ in range(max_iterations):
        mean_val = float(current.mean())
        head = current[current > mean_val]
        if head.size == 0 or head.size / current.size > head_limit:
            break
        threshold = mean_val
        current = head
    return threshold
