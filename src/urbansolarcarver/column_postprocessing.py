"""
UrbanSolarCarver: column post-processing of the carved grid

Column rules applied by thresholding after the score threshold, so the
kept volume is a buildable height field:

* carve_above_columns / carve_above_scores: carve every occupied voxel
  above the lowest sufficiently-carved region of each (x, y) column
  (``carve_above``, ``carve_above_min_consecutive``), on a boolean carve
  mask or directly on the scores.
* limit_column_slope: cut columns that rise more steeply than
  ``max_slope_deg`` above a median-filtered height map, which turns
  one-voxel spires and tall cliffs into ramps.  It only removes voxels.

The column loops are numba kernels.
"""

import warnings

import numpy as np
from numba import njit


def carve_above_columns(
    mask: "np.ndarray",
    voxel_grid: "np.ndarray",
    min_consecutive: int = 1,
) -> "np.ndarray":
    """Carve occupied voxels above the lowest sufficiently-carved run per column.

    For each (x, y) column, scans bottom-to-top (z=0 upward) for runs of
    consecutive carved voxels (occupied in *voxel_grid*, False in *mask*;
    empty cells break a run and never count as carved):

    * Runs with length >= *min_consecutive* **trigger** carve-above: all
      occupied voxels above the run are carved.  The first (lowest)
      qualifying run triggers; scanning stops for that column.
    * Shorter runs do not trigger, but stay carved: the result only ever
      removes voxels, so it never re-violates the carving constraint.

    Parameters
    ----------
    mask : ndarray (D, D, D) bool
        Thresholding mask.  True = keep, False = carved.  Not mutated.
    voxel_grid : ndarray (D, D, D) bool
        Original envelope occupancy.  True = occupied.
    min_consecutive : int, default 1
        Minimum consecutive carved voxels to trigger carve-above.

    Returns
    -------
    ndarray (D, D, D) bool
        A copy of *mask* with the occupied voxels above qualifying runs
        set to False.
    """
    out = np.ascontiguousarray(mask.astype(bool, copy=True))
    occ = np.ascontiguousarray(voxel_grid.astype(bool, copy=False))
    _carve_above_kernel(out, occ, int(min_consecutive))
    return out


@njit(cache=True)
def _carve_above_kernel(out, voxel_grid, min_consecutive):
    """Numba kernel for :func:`carve_above_columns`; mutates *out* in place.

    Scans each column bottom-to-top: the first run of >= min_consecutive
    carved voxels triggers carve-above for all occupied voxels higher in
    that column; shorter runs are left as they are.
    """
    nx, ny, nz = out.shape
    for x in range(nx):
        for y in range(ny):
            trigger_top = -1
            z = 0
            while z < nz:
                # Only occupied voxels can be carved. Empty cells (pre-existing
                # voids, air under an overhang) neither start nor extend a run,
                # whatever the mask says about them.
                if voxel_grid[x, y, z] and not out[x, y, z]:
                    run_start = z
                    while z < nz and voxel_grid[x, y, z] and not out[x, y, z]:
                        z += 1
                    if z - run_start >= min_consecutive:
                        trigger_top = z - 1
                        break
                    # Short run: too small to trigger, but it stays carved;
                    # refilling it would undo the solar constraint.
                else:
                    z += 1

            if trigger_top >= 0:
                for z_above in range(trigger_top + 1, nz):
                    if voxel_grid[x, y, z_above]:
                        out[x, y, z_above] = False


def carve_above_scores(scores, occupancy, min_consecutive: int = 1) -> np.ndarray:
    """For each voxel, the score cutoff below which carve_above removes it.

    Carving the occupied voxels that score above a cutoff t and then running
    :func:`carve_above_columns` removes exactly the occupied voxels whose
    value here is above t: a voxel goes when it scores above t itself, or
    when some run of *min_consecutive* consecutive occupied voxels below it
    in its column all score above t.  So the value is the larger of the
    voxel's own score and, over those runs below it, the smallest score in
    the run.  Empty cells break runs.

    With these values a score-mass cutoff can count everything carve_above
    removes, not only the voxels the cutoff picks itself.  NaN scores count
    as +inf (always carved).

    Parameters
    ----------
    scores : ndarray (X, Y, Z) float
    occupancy : ndarray (X, Y, Z) bool
    min_consecutive : int, default 1

    Returns
    -------
    ndarray (X, Y, Z) float64
        Values on empty cells are their own score and carry no meaning.
    """
    s = np.ascontiguousarray(np.asarray(scores, dtype=np.float64))
    occ = np.ascontiguousarray(np.asarray(occupancy, dtype=bool))
    out = np.empty_like(s)
    _carve_above_scores_kernel(s, occ, int(min_consecutive), out)
    return out


@njit(cache=True)
def _carve_above_scores_kernel(scores, occ, k, out):
    """Column scan for :func:`carve_above_scores`.

    Walking up a column, ``trigger`` is the largest cutoff at which some run
    of k consecutive occupied voxels below the current voxel is entirely
    carved (the smallest score in that run).
    """
    nx, ny, nz = occ.shape
    for x in range(nx):
        for y in range(ny):
            trigger = -np.inf
            run = 0
            for z in range(nz):
                value = scores[x, y, z]
                if value != value:          # NaN: always carved
                    value = np.inf
                if not occ[x, y, z]:
                    out[x, y, z] = value
                    run = 0
                    continue
                out[x, y, z] = max(value, trigger)
                run += 1
                if run >= k:
                    window = value
                    for zz in range(z - k + 1, z):
                        below = scores[x, y, zz]
                        if below != below:
                            below = np.inf
                        window = min(window, below)
                    trigger = max(trigger, window)


def limit_column_slope(mask, occupancy, max_slope_deg: float, median_size: int = 5):
    """Lower columns that rise too steeply above their neighbours.

    Each building column's kept height (one above its highest kept voxel,
    0 if nothing is kept) is capped so that it rises at most
    ``tan(max_slope_deg)`` voxels per voxel of horizontal distance above a
    reference height map, counting the reference at the column itself as
    one voxel away; every kept voxel above the cap is removed.  The result
    only ever removes voxels.

    The reference is the kept height map after a ``median_size`` x
    ``median_size`` median filter over the building's columns, so features
    one or two columns wide are ignored: a single tall column (a spire) is
    measured against its surroundings and ends at most one slope step above
    them, and a single low column (a stub left at a curved edge) or a
    narrow slot does not pull its neighbours down.  Wider differences in
    height, including next to areas carved to the ground, become ramps of
    the given slope, cut from the taller side.  Columns outside the
    building (no occupied voxel) take no part.

    The cap never rises when the input loses voxels, so carving more before
    this step never keeps more after it (a carve_fraction slider stays
    nested).

    Parameters
    ----------
    mask : ndarray (X, Y, Z) bool
        Kept voxels (True), normally after carve_above.  Not mutated.
    occupancy : ndarray (X, Y, Z) bool
        The building's voxels before carving; decides which columns count.
    max_slope_deg : float
        Steepest allowed rise between neighbouring columns, in degrees
        above horizontal (0 < angle < 90; voxels are cubes, so the slope is
        the same in metres).
    median_size : int, default 5
        Width in voxels of the median filter that builds the reference.

    Returns
    -------
    ndarray (X, Y, Z) bool
        A copy of *mask* with the voxels above each column's cap removed.
    """
    from numpy.lib.stride_tricks import sliding_window_view
    if not 0.0 < max_slope_deg < 90.0:
        raise ValueError(f"max_slope_deg must be between 0 and 90, got {max_slope_deg}")
    z = np.arange(mask.shape[2])
    building = np.asarray(occupancy, dtype=bool).any(axis=2)
    top = np.where(mask.any(axis=2), (mask * (z + 1)).max(axis=2), 0).astype(np.float64)
    half = median_size // 2
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # windows with no building column
        windows = sliding_window_view(
            np.pad(np.where(building, top, np.nan), half, constant_values=np.nan),
            (median_size, median_size))
        reference = np.where(building, np.nanmedian(windows, axis=(-2, -1)), 0.0)
    rise = float(np.tan(np.radians(max_slope_deg)))
    cap = _slope_envelope(np.ascontiguousarray(reference), building, rise, rise * np.sqrt(2.0))
    cap = np.minimum(top, cap + rise)
    return mask & (z[None, None, :] < np.floor(cap + 1e-9)[:, :, None])


@njit(cache=True)
def _slope_envelope(h, valid, rise_axis, rise_diag):
    """Lower *h* (in place) to min over neighbours q of h[q] + rise * distance.

    Two raster passes over the 8-neighbourhood (forward, then backward)
    give the chamfer approximation of the Euclidean distance: axis steps
    cost *rise_axis*, diagonal steps *rise_diag*.  Only cells with
    ``valid`` True take part.  Returns *h*.
    """
    nx, ny = h.shape
    for i in range(nx):
        for j in range(ny):
            if not valid[i, j]:
                continue
            for di, dj, r in ((-1, 0, rise_axis), (0, -1, rise_axis),
                              (-1, -1, rise_diag), (-1, 1, rise_diag)):
                a, b = i + di, j + dj
                if 0 <= a < nx and 0 <= b < ny and valid[a, b] and h[a, b] + r < h[i, j]:
                    h[i, j] = h[a, b] + r
    for i in range(nx - 1, -1, -1):
        for j in range(ny - 1, -1, -1):
            if not valid[i, j]:
                continue
            for di, dj, r in ((1, 0, rise_axis), (0, 1, rise_axis),
                              (1, 1, rise_diag), (1, -1, rise_diag)):
                a, b = i + di, j + dj
                if 0 <= a < nx and 0 <= b < ny and valid[a, b] and h[a, b] + r < h[i, j]:
                    h[i, j] = h[a, b] + r
    return h
