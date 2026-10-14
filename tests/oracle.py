"""Independent reference implementation for end-to-end carving checks.

Shares no tracing, ray-generation or sun-rotation code with USC: rays are
marched in fixed sub-voxel steps on the CPU, sun positions come straight
from Ladybug's Sunpath at 5-minute resolution, and model north is applied
from first principles. Only the Tregenza patch directions and patch
weights are reused, since those are inputs rather than the code under test.

A voxel counts as an obstruction of sample p only when its centre lies in
front of p's surface plane (n . (c - p) > 0): the voxel a protected
surface sits in is the building itself, not an obstruction of it.

Fixed-step marching can miss voxels a ray only clips at a corner, so the
oracle's hit set is a subset of the exact one. Each ray is also sampled just
past its start, so the voxel it starts in is not missed when the ray leaves
it within half a step. Soundness checks (every
oracle hit must be carved) are therefore exact; tightness checks (every
carve must be explained) use a one-voxel dilation.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_dilation


@dataclass
class Run:
    pre: Path
    thr: Path
    exp: Path
    occ: np.ndarray
    origin: np.ndarray
    vs: float
    scores: np.ndarray
    mask: np.ndarray
    points: np.ndarray
    normals: np.ndarray
    cfg: dict

    @property
    def shape(self):
        return self.occ.shape

    @classmethod
    def load(cls, root: Path, cfg: dict) -> "Run":
        pre, thr, exp = root / "preprocessing", root / "thresholding", root / "exporting"
        man = json.loads((pre / "manifest.json").read_text())
        occ = np.load(pre / "voxel_grid.npy").astype(bool)
        return cls(
            pre=pre, thr=thr, exp=exp, occ=occ,
            origin=np.asarray(man["origin"], float), vs=float(man["voxel_size"]),
            scores=np.load(pre / "scores.npy").reshape(occ.shape),
            mask=np.load(thr / "mask.npy").reshape(occ.shape),
            points=np.load(pre / "test_points.npy").astype(np.float64),
            normals=np.load(pre / "test_normals.npy").astype(np.float64),
            cfg=cfg,
        )

    def diag(self, stage: str) -> dict:
        return json.loads((getattr(self, stage) / "diagnostics" / "diagnostic.json").read_text())


# ----------------------------------------------------------------- marching
def march(run: Run, origins, normals, dirs, weights=None, ray_length=300.0,
          substeps: int = 10, chunk: int = 4096, return_pairs: bool = False):
    """Trace rays and return per-voxel hit counts (or weight sums).

    Each (ray, voxel) pair is counted once. Only voxels in front of the
    ray's source surface are recorded. With *return_pairs*, return the
    (ray index, flat voxel index) pairs instead.
    """
    origins = np.asarray(origins, float)
    normals = np.asarray(normals, float)
    dirs = np.asarray(dirs, float)
    dirs = dirs / np.linalg.norm(dirs, axis=1, keepdims=True)
    shape = np.array(run.shape)
    n_vox = int(np.prod(shape))
    out = np.zeros(n_vox, dtype=np.float64)
    lo = run.origin
    hi = run.origin + shape * run.vs
    step = run.vs / substeps
    diag = float(np.linalg.norm(hi - lo))
    pair_rays, pair_voxels = [], []
    for s in range(0, len(origins), chunk):
        o, n, d = origins[s:s + chunk], normals[s:s + chunk], dirs[s:s + chunk]
        w = None if weights is None else np.asarray(weights[s:s + chunk], float)
        with np.errstate(divide="ignore", invalid="ignore"):
            inv = 1.0 / d
            t1, t2 = (lo - o) * inv, (hi - o) * inv
        t1 = np.where(np.isfinite(t1), t1, -np.inf)
        t2 = np.where(np.isfinite(t2), t2, np.inf)
        par = ~np.isfinite(inv) | (d == 0)
        inside_par = (o >= lo) & (o < hi)
        t_lo = np.where(par, np.where(inside_par, -np.inf, np.inf), np.minimum(t1, t2))
        t_hi = np.where(par, np.where(inside_par, np.inf, -np.inf), np.maximum(t1, t2))
        t_near = np.maximum(t_lo.max(axis=1), 0.0)
        t_far = np.minimum(t_hi.min(axis=1), ray_length)
        live = t_near < t_far
        if not live.any():
            continue
        o, n, d, t_near, t_far = o[live], n[live], d[live], t_near[live], t_far[live]
        if w is not None:
            w = w[live]
        k = np.arange(int(math.ceil(min(diag, ray_length) / step)) + 1)
        # Samples at mid-step, plus one just past the start, so the voxel a
        # ray starts in (or enters the grid through) is seen even when the ray
        # leaves it within half a step.
        t = np.concatenate([t_near[:, None] + 1e-4 * step,
                            t_near[:, None] + (k[None, :] + 0.5) * step], axis=1)
        valid = t < t_far[:, None]
        pos = o[:, None, :] + t[..., None] * d[:, None, :]
        idx = np.floor((pos - lo) / run.vs).astype(np.int64)
        inb = valid & np.all((idx >= 0) & (idx < shape), axis=2)
        centre = lo + (idx + 0.5) * run.vs
        front = np.einsum("rkj,rj->rk", centre - o[:, None, :], n) > 1e-9
        keep = inb & front
        ray_id, kk = np.nonzero(keep)
        if ray_id.size == 0:
            continue
        flat = np.ravel_multi_index(tuple(idx[ray_id, kk].T), tuple(shape))
        pair = np.unique(ray_id.astype(np.int64) * n_vox + flat)
        r, v = np.divmod(pair, n_vox)
        if return_pairs:
            pair_rays.append(np.flatnonzero(live)[r] + s)
            pair_voxels.append(v)
            continue
        np.add.at(out, v, 1.0 if w is None else w[r])
    if return_pairs:
        if not pair_rays:
            return np.zeros(0, np.int64), np.zeros(0, np.int64)
        return np.concatenate(pair_rays), np.concatenate(pair_voxels)
    return out.reshape(tuple(shape))


# ----------------------------------------------------------------- directions
def sun_directions(epw: str, period: dict, north_deg: float, min_altitude: float,
                   minutes: int = 5) -> np.ndarray:
    from ladybug.epw import EPW
    from ladybug.sunpath import Sunpath
    from ladybug.analysisperiod import AnalysisPeriod

    loc = EPW(epw).location
    sp = Sunpath(loc.latitude, loc.longitude, loc.time_zone)
    ap = AnalysisPeriod(period["start_month"], period["start_day"], 0,
                        period["end_month"], period["end_day"], 23)
    days = sorted({(dt.month, dt.day) for dt in ap.datetimes})
    th = math.radians(north_deg)
    out = []
    for month, day in days:
        m = period["start_hour"] * 60
        while m <= period["end_hour"] * 60:
            sun = sp.calculate_sun(month, day, m / 60.0)
            if sun.altitude >= min_altitude:
                alt, az = math.radians(sun.altitude), math.radians(sun.azimuth)
                out.append((math.cos(alt) * math.sin(az + th),
                            math.cos(alt) * math.cos(az + th),
                            math.sin(alt)))
            m += minutes
    return np.asarray(out, float).reshape(-1, 3)


def tilted_directions(normals, angle_deg, north_deg=0.0):
    nxy = normals.copy()
    nxy[:, 2] = 0
    ln = np.linalg.norm(nxy, axis=1, keepdims=True)
    nxy = np.where(ln > 1e-9, nxy / np.maximum(ln, 1e-12), 0.0)
    if np.isscalar(angle_deg):
        a = np.full(len(normals), math.radians(angle_deg))
    else:
        phi = (np.degrees(np.arctan2(nxy[:, 0], nxy[:, 1])) - north_deg) % 360.0
        a = np.radians(np.asarray(angle_deg, float)[np.floor(((phi + 22.5) % 360) / 45).astype(int)])
    d = np.cos(a)[:, None] * nxy
    d[:, 2] += np.sin(a)
    return d


def pairs(points, normals, dirs):
    """All (point, direction) combinations facing the surface."""
    facing = normals @ dirs.T > 0
    pi, di = np.nonzero(facing)
    return points[pi], normals[pi], dirs[di], pi, di


# ----------------------------------------------------------------- references
def column_above(hit: np.ndarray) -> np.ndarray:
    """Everything at or above the lowest hit in each (x, y) column."""
    return np.maximum.accumulate(hit, axis=2)


def time_based_shading(run: Run, epw: str, minutes: int = 5) -> np.ndarray:
    """Per-voxel shading in m²·h: blocked (point, sun) rays x grid_step² x minutes/60."""
    c = run.cfg
    period = {k: c[k] for k in ("start_month", "start_day", "start_hour",
                                "end_month", "end_day", "end_hour")}
    suns = sun_directions(epw, period, c.get("north_deg", 0.0), c.get("min_altitude", 5.0), minutes)
    o, n, d, _, _ = pairs(run.points, run.normals, suns)
    area = float(c.get("grid_step", 1.0)) ** 2
    return march(run, o, n, d, ray_length=c.get("ray_length", 300.0)) * (area * minutes / 60.0)


def time_based_hits(run: Run, epw: str, minutes: int = 5) -> np.ndarray:
    return time_based_shading(run, epw, minutes) > 0


def tilted_hits(run: Run) -> np.ndarray:
    c = run.cfg
    d = tilted_directions(run.normals, c["tilted_plane_angle_deg"], c.get("north_deg", 0.0))
    return march(run, run.points, run.normals, d, ray_length=c.get("ray_length", 300.0)) > 0


def sky_scores(run: Run, substeps: int = 10) -> np.ndarray:
    import torch
    from urbansolarcarver.sky_patches import fetch_tregenza_patch_directions
    dirs = fetch_tregenza_patch_directions(torch.device("cpu")).numpy().astype(float)
    pw = np.load(run.pre / "patch_weights.npy").astype(float)
    o, n, d, _, di = pairs(run.points, run.normals, dirs)
    return march(run, o, n, d, weights=pw[di], ray_length=run.cfg.get("ray_length", 300.0),
                 substeps=substeps)


def protected_hits(run: Run, share: float) -> np.ndarray:
    """Voxels that block one of the patches protect_share=*share* protects.

    The protected patches are the highest-weight ones (ties in patch order)
    whose weights first reach *share* of the total positive weight; the
    ranking is recomputed here rather than taken from USC.
    """
    import torch
    from urbansolarcarver.sky_patches import fetch_tregenza_patch_directions
    dirs = fetch_tregenza_patch_directions(torch.device("cpu")).numpy().astype(float)
    pw = np.load(run.pre / "patch_weights.npy").astype(float)
    ranked = sorted((i for i in range(len(pw)) if pw[i] > 0), key=lambda i: (-pw[i], i))
    total, acc, chosen = sum(pw[i] for i in ranked), 0.0, []
    for i in ranked:
        if share <= 0 or acc >= share * total * (1 - 1e-12):
            break
        chosen.append(i)
        acc += pw[i]
    if not chosen:
        return np.zeros(run.shape, bool)
    o, n, d, _, _ = pairs(run.points, run.normals, dirs[chosen])
    return march(run, o, n, d, ray_length=run.cfg.get("ray_length", 300.0)) > 0


def recovered_share(run: Run, kept: np.ndarray) -> float:
    """Share of the obstructed, cosine-weighted ray weight that *kept* clears.

    A ray (sample point to Tregenza patch centre) is obstructed when it
    crosses an occupied voxel in front of its surface, and clear when none
    of those voxels is kept. Weights are patch weight x cos(incidence) (no
    cosine for radiative_cooling). Corner clips the stepped march misses
    leave rays out of both totals.
    """
    import torch
    from urbansolarcarver.sky_patches import fetch_tregenza_patch_directions
    dirs = fetch_tregenza_patch_directions(torch.device("cpu")).numpy().astype(float)
    pw = np.load(run.pre / "patch_weights.npy").astype(float)
    o, n, d, _, di = pairs(run.points, run.normals, dirs)
    w = pw[di]
    if run.cfg.get("mode") != "radiative_cooling":
        w = w * np.einsum("ij,ij->i", n, d)
    ray, vox = march(run, o, n, d, ray_length=run.cfg.get("ray_length", 300.0),
                     return_pairs=True)
    occ_hit = run.occ.ravel()[vox]
    ray, vox = ray[occ_hit], vox[occ_hit]
    obstructed = np.zeros(len(o), bool)
    obstructed[ray] = True
    blocked = np.zeros(len(o), bool)
    blocked[ray[kept.ravel()[vox]]] = True
    obstructed &= w > 0
    total = w[obstructed].sum()
    return float(w[obstructed & ~blocked].sum() / total) if total > 0 else 0.0


def score_agreement(run: Run) -> dict:
    """Compare USC's raw scores on occupied voxels with the reference.

    shortfall: occupied voxels USC scores below the reference beyond float32
    accumulation error (1e-4 relative), unless a face neighbour (occupied or
    not) holds at least the missing score as extra.  A ray that starts on a
    voxel face and runs parallel to it (a facade on a lattice plane, a patch
    straight along a grid axis) touches both voxels; the reference and the
    DDA may put it on different sides, which moves its weight to the
    neighbour without losing it.  Other shortfalls come only from rays
    passing within rounding of a voxel edge.
    excess: extra score mass, i.e. corner clips the fixed-step reference
    misses. Grazing (low-sun) ray sets can show >10% at 10 sub-steps; it is
    then re-measured at 40, where only genuine over-scoring stays large.
    """
    usc_grid = run.scores.astype(float)
    ref_grid = sky_scores(run)
    usc, ref = usc_grid[run.occ], ref_grid[run.occ]
    out = {"ref_mass": float(ref.sum())}
    if ref.sum() <= 0:
        return out
    tol_grid = 1e-4 * np.maximum(ref_grid, usc_grid) + 1e-9 * ref.max()
    missing = ref_grid - usc_grid
    surplus = np.pad(np.maximum(-missing, 0.0), 1)
    neighbour_surplus = np.zeros_like(missing)
    for axis in range(3):
        for shift in (-1, 1):
            neighbour_surplus = np.maximum(
                neighbour_surplus, np.roll(surplus, shift, axis=axis)[1:-1, 1:-1, 1:-1])
    short = run.occ & (missing > tol_grid) & (neighbour_surplus < missing - tol_grid)
    out["shortfall_voxels"] = int(short.sum())
    out["excess"] = float((usc - ref).sum() / ref.sum())
    if out["excess"] > 0.10:
        fine = sky_scores(run, substeps=40)[run.occ]
        out["excess_fine"] = float((usc - fine).sum() / fine.sum())
    return out


# ----------------------------------------------------------------- checks
def kept_grid(run: Run) -> np.ndarray:
    """Occupied voxels kept after thresholding and carve_above (pre-cleanup)."""
    from urbansolarcarver.carving import carve_above_columns
    m = run.mask
    if run.cfg.get("carve_above", True):
        m = carve_above_columns(m, run.occ, run.cfg.get("carve_above_min_consecutive", 1))
    return run.occ & m


def soundness_violations(run: Run, must_carve: np.ndarray) -> int:
    """Occupied voxels the reference says must go but the run kept."""
    return int((kept_grid(run) & must_carve).sum())


def unexplained_carving(run: Run, explained: np.ndarray) -> tuple[int, int]:
    """(carved voxels not within one voxel of an explained one, total carved)."""
    carved = run.occ & ~run.mask
    near = binary_dilation(explained, structure=np.ones((3, 3, 3), bool))
    return int((carved & ~near).sum()), int(carved.sum())


def floating_voxels(kept: np.ndarray, occ: np.ndarray, min_run: int = 1) -> int:
    """Kept voxels above a run of >= *min_run* removed occupied voxels in their column.

    Empty cells break a run; shorter runs are below carve_above's trigger.
    """
    removed = (occ & ~kept).astype(np.int32)
    run = np.zeros_like(removed)
    for z in range(removed.shape[2]):
        run[:, :, z] = (run[:, :, z - 1] + 1) * removed[:, :, z] if z else removed[:, :, z]
    qualifying = np.maximum.accumulate(run >= min_run, axis=2)
    below = np.concatenate([np.zeros_like(qualifying[:, :, :1]), qualifying[:, :, :-1]], axis=2)
    return int((kept & below).sum())
