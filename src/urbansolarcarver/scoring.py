"""
UrbanSolarCarver Scoring Module

Provides sky-patch weight computation and threshold selection for voxel carving.

1. get_weights(mode, device, epw_file, hoys, …) → torch.Tensor
   Per-patch weight vector for the specified mode.  Delegates to
   compute_EPW_based_weights (sky_patches.py) for climate-based modes
   and compute_radiative_cooling_weights for radiative_cooling.

2. headtail_threshold(scores) → float
   Head/tail breaks (Jiang 2013): iteratively partitions right-skewed
   score distributions at the arithmetic mean.  Well-suited for solar
   obstruction scores which are typically heavy-tailed.
"""
import numpy as np
import torch
from .sky_patches import fetch_tregenza_patch_directions, compute_EPW_based_weights, compute_radiative_cooling_weights
from typing import Sequence

def get_weights(
    mode: str,
    device: torch.device = torch.device('cuda'),
    epw_file: str = None,
    hoys: Sequence[int] = None,
    dew_point_celsius: float = 10.0,
    bliss_k: float = 1.8,
    ground_reflectance: float = 0.2,
    balance_temperature: float = 15.0,
    balance_offset: float = 2.0,
    north_deg: float = 0.0,
    min_sky_elevation_deg: float = 0.0,
) -> torch.Tensor:
    """
    Build a vector of weights for each sky patch, according to a chosen analysis mode.

    Explanation:
    - We represent the sky as discrete patches. This function assigns a numeric weight to each patch.
    - Modes include simple uniform weighting, solar irradiance, passive solar benefit, daylighting and radiative cooling.
    - Solar irradiance uses EPW data, Passive solar benefit uses Ladybug's method that employs a balance temp and offset.
    - Daylight uses CIE overcast approximation. Radiative cooling uses dew point temperature to estimate cooling potential of a night sky.
    Args:
      mode: Analysis type (e.g., 'time-based', 'irradiance', 'benefit', 'daylight', 'radiative_cooling').
      device: Compute device identifier (e.g., 'cuda' or 'cpu').
      epw_file: Path to weather data file; required for certain modes.
      hoys : Hour-of-year indices for EPW sampling.
      dew_point_celsius: Parameter for radiative cooling estimation.
      bliss_k: Angular-attenuation constant for radiative cooling.
      ground_reflectance: Reflectivity coefficient of ground surface.
      balance_temperature: Indoor-outdoor temperature threshold for comfort benefit.
      balance_offset: Temperature offset for comfort benefit.

    Returns:
      Tensor of length V (number of sky patches) with the computed weight for each patch.
    """
    if not isinstance(mode, str) or not mode.strip():
        raise TypeError(f"get_weights: mode must be a non-empty string, got {mode!r}")
    mode_key = mode.strip().lower()

    # Radiative cooling mode uses dew point to compute cooling potential per patch.
    if mode_key == 'radiative_cooling':
        return compute_radiative_cooling_weights(
            dew_point_celsius, bliss_k, torch.device(device),
            min_elevation_deg=min_sky_elevation_deg,
        )

    # Time-based mode: assign a weight of 1 to every patch (uniform importance). Carving based on user-defined HOYs.
    if mode_key == 'time-based':
        sky_dirs = fetch_tregenza_patch_directions(torch.device(device))
        count_patches = sky_dirs.shape[0]
        return torch.ones(count_patches, dtype=torch.float32, device=device)

    # Daylight mode: CIE overcast sky — geometry only, no EPW needed.
    if mode_key == 'daylight':
        return compute_EPW_based_weights(
            mode_key,
            None,              # epw_path not used by daylight
            None,              # hoys not used by daylight
            torch.device(device),
            ground_reflectance,
            balance_temperature,
            balance_offset,
            north=north_deg,
        )

    # Modes requiring weather data: irradiance, benefit
    if mode_key in {'irradiance', 'benefit'}:
        if not epw_file or not hoys:
            raise ValueError(
                f"get_weights: epw_file and hoys list are required for mode '{mode}'"
            )
        return compute_EPW_based_weights(
            mode_key,
            epw_file,
            hoys,
            torch.device(device),
            ground_reflectance,
            balance_temperature,
            balance_offset,
            north=north_deg,
        )

    # Raise error for unsupported modes
    raise ValueError(f"get_weights: unsupported mode '{mode}'")




def carve_fraction_threshold(scores: np.ndarray, fraction: float) -> float:
    """Score-mass cutoff: the threshold above which voxels collectively
    account for *fraction* of the total score mass.

    Equivalent to sorting all scores descending and walking the cumulative
    sum until it reaches ``fraction * total`` — but a full argsort of a
    large grid is O(N log N) with a heavy constant (seconds to minutes at
    300³+).  This implementation makes two O(N) passes instead:

    1. A weighted histogram locates the bin containing the cutoff.
    2. Only the scores inside that single bin (N / n_bins expected) are
       sorted exactly, reproducing the argsort result.

    Parameters
    ----------
    scores : np.ndarray
        Array of non-negative voxel scores (any shape).
    fraction : float
        Fraction of the total score mass to carve, in [0, 1].

    Returns
    -------
    float
        Threshold value; voxels scoring strictly above it are carved.
    """
    flat = scores.ravel()
    if flat.size == 0:
        return 0.0
    finite = np.isfinite(flat)
    if not finite.all():
        # Non-finite scores (NaN/Inf) are always carved by the downstream
        # `score <= threshold` comparison, so exclude them from the mass
        # calculation instead of letting max()/np.histogram raise on a
        # non-finite range.
        flat = flat[finite]
        if flat.size == 0:
            return 0.0
    vmax = float(flat.max())
    if vmax <= 0.0:
        return 0.0
    # float64 accumulation: float32 cumsum over many elements loses mass
    total = float(flat.sum(dtype=np.float64))
    target = float(fraction) * total
    if target <= 0.0:
        return vmax  # carve nothing: only scores above the max qualify

    # Pass 1: weighted histogram → mass contributed by each score bin.
    n_bins = 8192
    hist, edges = np.histogram(flat, bins=n_bins, range=(0.0, vmax),
                               weights=flat.astype(np.float64, copy=False))
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
        in_bin = flat[flat >= lo_edge]  # last bin includes vmax
    else:
        in_bin = flat[(flat >= lo_edge) & (flat < edges[b + 1])]
    if in_bin.size == 0:
        return float(lo_edge)
    desc = np.sort(in_bin)[::-1]
    csum = mass_above[b] + np.cumsum(desc.astype(np.float64))
    idx = int(np.searchsorted(csum, target, side="right"))
    if idx < desc.size:
        return float(desc[idx])
    # Cutoff falls just below this bin: threshold is the largest lower score.
    below = flat[flat < lo_edge]
    return float(below.max()) if below.size else float(desc[-1])


def headtail_threshold(
    scores: np.ndarray,
    max_iterations: int = 10
) -> float:
    """
    Head-tail breaks (Jiang, 2013): iteratively partition scores into 'head'
    (above mean) and 'tail' (below mean). Each iteration re-computes the mean
    of the head subset. The process stops when the head mean drops below the
    overall mean, indicating the distribution's heavy tail has been isolated.
    This is well-suited for right-skewed score distributions typical of solar
    exposure data.

    Parameters
    ----------
    scores : np.ndarray
        1-D array of non-negative voxel scores.
    max_iterations : int
        Safety cap on recursion depth.

    Returns
    -------
    float
        Threshold value (the last computed mean).
    """
    if scores.size == 0:
        return 0.0
    current_set = scores.ravel()
    for _ in range(max_iterations):
        mean_val = float(current_set.mean())
        head_set = current_set[current_set > mean_val]
        if head_set.size == 0:
            return mean_val
        # Jiang (2013): stop when the head proportion drops below 40%,
        # meaning the heavy tail has been isolated from the bulk.
        head_pct = head_set.size / current_set.size
        if head_pct <= 0.40:
            return mean_val
        current_set = head_set
    return float(current_set.mean())
