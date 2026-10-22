"""
UrbanSolarCarver: test point access evaluation
==============================================

How much sun or sky each test point still receives through an occupancy
grid, uncarved or carved: :func:`test_point_access_evaluation` traces the
rays of the mode's preprocessing (sky-patch rays with their patch weights
and edge_taper point weights, or sun rays for time-based) until the first
occupied voxel, and sums per test point the weight of the rays that reach
none (accessible) and of the others (blocked).  Voxels count under the
same front-face and skin rules as in scoring, so a point's own surface
does not block it; on a carved grid, pass the max volume too, which the
skin rule reads as it does in scoring.
"""
from typing import NamedTuple

import numpy as np
import torch

from .carving import (
    _resolve_batch_size, _run_batches, _validate_cubic_resolution, sky_patch_ray_set, sun_ray_set,
)
from .compute_device import resolve_compute_device
from .mode_registry import MODES, MODES_NEEDING_PERIOD
from .ray_tracing import trace_point_access_dda
from .stage_settings import PreprocessingSettings
from .sun import sample_period
from .warp_kernels import require_dda_backend


class PointAccessResult(NamedTuple):
    """Return type of :func:`test_point_access_evaluation`."""
    test_point_accessible_weight: np.ndarray   # (P,) float64 weight of each point's rays that reach no occupied voxel
    test_point_blocked_weight: np.ndarray      # (P,) float64 weight of each point's rays that do
    weight_unit: str                           # unit of both: the mode's patch weight unit, or h for time-based


def test_point_access_evaluation(
    occupancy,
    grid_origin,
    grid_extent,
    grid_resolution,
    sample_points,
    sample_normals,
    settings: PreprocessingSettings,
    point_weights: "np.ndarray | None" = None,
    *,
    max_volume=None,
    device=None,
    ray_batch_size: int = 0,
) -> PointAccessResult:
    """Accessible and blocked weight of every test point through *occupancy*.

    The rays are those of preprocessing for ``settings.mode``:

    * the weighted modes: one ray per sample point and Tregenza patch it
      faces, weighted by the mode's patch weight times the point's
      *point_weights* entry (edge_taper); the weights are in the mode's
      ``weight_unit`` (kWh/m² for irradiance and benefit, a share of the
      sky that sums to 1 over the sphere for daylight and
      radiative_cooling);
    * time-based: one ray per sample point and sun position it faces over
      the analysis period, each worth 1 / ``sun_steps_per_hour`` h, so the
      weights are hours of sun; *point_weights* is ignored, as in
      preprocessing.

    A ray is blocked at the first occupied voxel it visits under the
    front-face and skin rules of scoring.  For every point, accessible +
    blocked is the total weight of its rays, and an empty grid leaves all
    of it accessible.

    Parameters
    ----------
    occupancy : torch.Tensor or np.ndarray, shape (X, Y, Z)
        The grid to evaluate (nonzero = occupied): the max volume, or a
        carved envelope on the same grid.
    grid_origin, grid_extent, grid_resolution
        The grid's minimum corner, cubic extent (m) and voxels per side, in
        the frame of *sample_points*.
    sample_points, sample_normals : np.ndarray, shape (P, 3)
        Test points and their outward unit normals.
    settings : PreprocessingSettings
        Settings of the preprocessing run (mode, weather, period, north,
        ray length, mode parameters).
    point_weights : np.ndarray, shape (P,), optional
        edge_taper weight per point (weighted modes).
    max_volume : torch.Tensor or np.ndarray, shape (X, Y, Z), optional
        The uncarved max volume, which the skin rule reads as in scoring:
        a test point's own facade voxel, kept in front of carved mass, then
        still does not block it.  Default *occupancy*; pass it whenever
        *occupancy* is a carved envelope.
    device : torch.device or str, optional
        Device to trace on; default the device of a *occupancy* tensor, or
        ``'auto'`` for an array.
    ray_batch_size : int, default 0
        Rays per batch (0 = automatic).

    Returns
    -------
    PointAccessResult

    Raises
    ------
    ValueError
        For ``tilted_plane``, whose planes have no rays toward the sky.
    """
    mode = settings.mode
    if mode == "tilted_plane":
        raise ValueError("test_point_access_evaluation: tilted_plane traces planes, not sun or sky rays")
    if device is None:
        device = occupancy.device if isinstance(occupancy, torch.Tensor) else resolve_compute_device("auto")
    device = resolve_compute_device(device)
    require_dda_backend(device)
    _validate_cubic_resolution(grid_resolution, "test_point_access_evaluation")
    res = int(grid_resolution if isinstance(grid_resolution, int) else grid_resolution[0])
    occ = occupancy if isinstance(occupancy, torch.Tensor) else torch.from_numpy(np.asarray(occupancy))
    occ = (occ.to(device).reshape(-1) != 0).to(torch.uint8).contiguous()
    skin_occ = None
    if max_volume is not None:
        skin_occ = max_volume if isinstance(max_volume, torch.Tensor) else torch.from_numpy(np.asarray(max_volume))
        skin_occ = (skin_occ.to(device).reshape(-1) != 0).to(torch.uint8).contiguous()
    num_points = len(sample_points)
    access = torch.zeros(2 * num_points, dtype=torch.float64, device=device)

    datetimes, hoys = [], []
    if mode in MODES_NEEDING_PERIOD:
        steps = settings.sun_steps_per_hour if mode == "time-based" else 1
        datetimes, hoys = sample_period(settings, steps_per_hour=steps)

    if MODES[mode].score_kind == "violation_count":   # time-based
        rays = sun_ray_set(device, sample_points, sample_normals, settings, datetimes)
        if rays is None:
            return PointAccessResult(np.zeros(num_points), np.zeros(num_points), "h")
        origins, directions, point_ids, normals = rays
        patch_ids = torch.zeros(origins.shape[0], dtype=torch.int32, device=device)
        patch_weights = torch.tensor([1.0 / settings.sun_steps_per_hour], dtype=torch.float32, device=device)
        pw, unit = None, "h"
    else:
        rays = sky_patch_ray_set(device, sample_points, sample_normals, settings, hoys, point_weights)
        origins, directions, patch_ids, point_ids = rays.origins, rays.directions, rays.patch_ids, rays.point_ids
        normals, pw, patch_weights = rays.surface_normals, rays.point_weights, rays.patch_weights
        unit = MODES[mode].weight_unit

    min_corner = (float(grid_origin[0]), float(grid_origin[1]), float(grid_origin[2]))
    total_rays = origins.shape[0]
    batch_size = _resolve_batch_size(device, ray_batch_size=ray_batch_size)
    batch_ranges = [(start, min(start + batch_size, total_rays)) for start in range(0, total_rays, batch_size)]

    def _access_batch(start, end, buf):
        trace_point_access_dda(
            min_corner, float(grid_extent), res, origins[start:end], directions[start:end],
            patch_ids[start:end], patch_weights, buf, float(settings.ray_length), occ,
            point_ids[start:end], point_weights=pw, surface_normals=normals, skin_occupancy=skin_occ,
        )

    with torch.no_grad():
        _run_batches(batch_ranges, _access_batch, access, device, parallel=True)
    if device.type == "cuda":
        torch.cuda.synchronize()
    access = access.cpu().numpy()
    return PointAccessResult(access[:num_points], access[num_points:], unit)


# Not a test: pytest would otherwise collect it wherever it is imported into a test module.
test_point_access_evaluation.__test__ = False
