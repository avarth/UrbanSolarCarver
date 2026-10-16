"""
UrbanSolarCarver: voxelization

Rasterizes the maximum volume into a padded cubic occupancy grid. Used by
preprocessing.

Pipeline entry point
--------------------
voxelize(envelope_mesh, settings, device=None)
    voxelize_mesh with the preprocessing settings; raises on an empty grid.

Public API
----------
voxelize_mesh(mesh, voxel_size=1.0, margin_frac=0.2, device=None)
    Rasterize a watertight mesh into a padded cubic occupancy grid. The
    result is cached in the active CarverSession under a key made of the
    mesh arrays, voxel size, margin and device (_voxelize_cache_key).

voxelize_solid_warp(vertices, faces, grid_origin, voxel_size, resolution, device)
    The Warp parity voxelizer voxelize_mesh uses (kernel in warp_kernels);
    None when Warp cannot run on the device.

Data types and units
--------------------
- Voxel grids: torch.Tensor, shape (D, D, D), uint8/bool, 1 = inside.
- voxel_size is in world units.
"""

import logging
from typing import Tuple

import numpy as np
import torch
import trimesh
from scipy import ndimage as ndi

from .errors import InputError
from .grid_planning import check_voxel_grid_budget, plan_voxel_grid
from .session import session_cache
from .stage_settings import PreprocessingSettings
from .warp_kernels import _warp_available, dda_backend_available

if _warp_available:
    import warp as wp
    from .warp_kernels import _parity_voxelize_kernel

_log = logging.getLogger(__name__)


def voxelize(envelope_mesh, settings: PreprocessingSettings, device: torch.device | None = None):
    """
    Rasterize the envelope into a padded cubic voxel grid.

    Parameters
    ----------
    envelope_mesh : trimesh.Trimesh
    settings : PreprocessingSettings
        Supplies ``voxel_size`` and ``margin_frac``.
    device : torch.device or None
        Device for the returned grid; None picks CUDA when available.

    Returns
    -------
    voxel_grid : torch.Tensor (D, D, D), uint8
        1 indicates inside/filled.
    grid_origin : np.ndarray(3,)
        World-space min corner for index (0,0,0).
    grid_extent : float
        Physical cube size (meters).
    grid_resolution : int
        Number of voxels per side (D).

    Raises
    ------
    InputError
        If voxelization returns an empty grid.
    """
    voxel_grid, grid_origin, grid_extent, grid_resolution = voxelize_mesh(
        envelope_mesh,
        voxel_size=settings.voxel_size,
        margin_frac=settings.margin_frac,
        device=device                    
    )

    if voxel_grid.numel() == 0 or voxel_grid.sum() == 0:
        raise InputError("Voxel grid is empty after voxelization")
    
    return voxel_grid, grid_origin, grid_extent, grid_resolution


def _voxelize_cache_key(args, kwargs) -> str:
    """Cache key for voxelize_mesh: SHA-1 of the vertex and face arrays, plus
    voxel_size, margin_frac and device.

    The raw arrays are hashed instead of trimesh's mesh identifier because
    that identifier is rotation-invariant: rotated copies of a mesh would
    share a key but need different grids.
    """
    import hashlib
    mesh = args[0]
    digest = hashlib.sha1(np.ascontiguousarray(mesh.vertices, dtype=np.float64).tobytes()
                          + np.ascontiguousarray(mesh.faces, dtype=np.int64).tobytes()).hexdigest()
    return f"{digest}:{kwargs['voxel_size']}:{kwargs['margin_frac']}:{kwargs.get('device')}"


@session_cache(_voxelize_cache_key)
def voxelize_mesh(
    mesh: trimesh.Trimesh,
    voxel_size: float = 1.0,
    margin_frac: float = 0.2,
    device: torch.device = None
) -> Tuple[torch.Tensor, np.ndarray, float, int]:
    """
    Rasterize a watertight mesh into a padded binary voxel grid.

    Parameters
    ----------
    mesh : trimesh.Trimesh
    voxel_size : float
        Edge length of one voxel in world units.
    margin_frac : float
        Padding on each side as a fraction of the longest side of the mesh's
        axis-aligned bounding box.
    device : torch.device or None
        Device for the returned tensor and for the Warp voxelizer; None
        picks CUDA when available, else CPU.

    Returns
    -------
    voxels : (D, D, D) uint8 torch.Tensor
        1 where inside/filled, 0 otherwise.
    origin : (3,) np.ndarray
        World-space min corner of the grid.
    grid_extent : float
        Side length of the cubic domain in world units (D * voxel_size).
    resolution : int
        Number of voxels per side (D).

    Raises
    ------
    ValueError
        If voxel_size <= 0, margin_frac < 0, or the grid would have more
        than ``grid_planning.MAX_GRID_VOXELS`` voxels (checked before
        anything is allocated).
    RuntimeError
        If the Warp voxelizer fails (for example out of memory), or the
        trimesh voxelization fails.

    Notes
    -----
    - Uses the Warp parity voxelizer (``voxelize_solid_warp`` below,
      on CUDA or the Warp CPU device); only when Warp cannot run on
      *device* does it use trimesh voxelization plus fill.  Sealed interior
      cavities are then filled with scipy's binary_fill_holes.
    - The grid is axis-aligned, cubic, and centred on the mesh bounding box.
    - Results are cached per session (see `_voxelize_cache_key`).
    """

    if device is None:
        device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')

    # Size the grid and check it against the budget before anything is
    # allocated (the Warp voxelizer alone needs 8 bytes per voxel).
    plan = plan_voxel_grid(mesh.bounds, voxel_size, margin_frac)
    check_voxel_grid_budget(plan)
    resolution, grid_extent, origin = plan.resolution, plan.extent, plan.origin

    # --- Rasterize: Warp parity voxelizer (CUDA or Warp CPU), or the
    # trimesh rasterize-and-fill path when Warp cannot run on *device*.
    # The Warp kernel casts one ray per grid column along each axis and
    # marks a voxel inside when at least 2 of the 3 parities agree.  It is
    # much faster than trimesh's CPU rasterizer and does not need the fill
    # fallbacks used below.  A Warp run that fails (out of memory, a driver
    # error) raises instead of switching to trimesh: trimesh classifies
    # boundary voxels differently, and the session cache would keep that
    # other grid for this geometry.
    grid_np = voxelize_solid_warp(
        mesh.vertices, mesh.faces, origin, voxel_size, resolution, device
    )

    if grid_np is None:
        # Voxelize with trimesh.  The default 'subdivide' method produces
        # surface-only voxels; we then fill the interior.
        try:
            vox = mesh.voxelized(pitch=voxel_size)

            # Try trimesh's orthographic fill first: it fills a voxel when
            # the surface blocks it in all 6 axis directions, so it tolerates
            # small gaps in the surface shell (binary_fill_holes does not).
            try:
                vox = vox.fill(method='orthographic')
            except Exception as exc:
                _log.warning("Orthographic fill failed (%s), trying default fill", exc)
                try:
                    vox = vox.fill()
                except Exception as exc2:
                    _log.warning("Default fill also failed (%s), proceeding with surface-only voxels", exc2)

            raw_grid = vox.matrix  # (Dx, Dy, Dz) bool, tightly cropped to mesh AABB

            # Embed the cropped grid into the padded cubic grid.
            # trimesh's transform maps voxel indices to voxel CENTERS, so
            # vox.transform[:3, 3] is the center of trimesh voxel (0,0,0).
            # Our voxel m has center origin + (m + 0.5) * voxel_size; solve
            # for m to align the two lattices.  (Treating the transform as
            # a corner would bias the embed by half a voxel.)
            vox_center0 = np.asarray(vox.transform[:3, 3])
            offset = np.round((vox_center0 - origin) / voxel_size - 0.5).astype(int)

            grid_np = np.zeros((resolution, resolution, resolution), dtype=bool)
            # Clip insertion to valid bounds
            src_start = np.maximum(-offset, 0)
            dst_start = np.maximum(offset, 0)
            src_end = np.minimum(np.array(raw_grid.shape), np.array(grid_np.shape) - offset)
            copy_shape = np.minimum(src_end - src_start, np.array(grid_np.shape) - dst_start)
            if (copy_shape > 0).all():
                slc_dst = tuple(slice(d, d + s) for d, s in zip(dst_start, copy_shape))
                slc_src = tuple(slice(s, s + sz) for s, sz in zip(src_start, copy_shape))
                grid_np[slc_dst] = raw_grid[slc_src]
        except Exception as e:
            raise RuntimeError(f"voxelize_mesh: trimesh voxelization failed: {e}")

    # --- Cavity fill: skip when the grid has no sealed interior voids ---
    # If all empty voxels form a single connected component (6-connectivity),
    # that component is the exterior, there are no sealed cavities, and
    # binary_fill_holes would change nothing.  Labelling is much cheaper
    # than running the full fill.
    surface_count = int(grid_np.sum())
    if surface_count == 0:
        filled = grid_np
    else:
        empty_space = ~grid_np
        # 6-connectivity: cavities must be fully enclosed (not diagonally
        # connected to the exterior) to count as interior voids.
        _, num_empty_components = ndi.label(empty_space)
        if num_empty_components <= 1:
            _log.debug(
                "voxelize_mesh: no interior cavities detected "
                "(single exterior component); skipping binary_fill_holes"
            )
            filled = grid_np
        else:
            filled = ndi.binary_fill_holes(grid_np)
            cavities_sealed = int(filled.sum()) - surface_count
            _log.debug(
                "voxelize_mesh: binary_fill_holes sealed %d cavity voxels "
                "(%d empty components detected)",
                cavities_sealed, num_empty_components,
            )

    _log.info(
        "voxelize_mesh: watertight=%s voxels_before_fill=%d filled_voxels=%d "
        "fill_ratio=%.1fx",
        mesh.is_watertight, surface_count, int(filled.sum()),
        int(filled.sum()) / max(surface_count, 1),
    )

    voxels = torch.from_numpy(filled.astype(np.uint8)).to(device)
    return voxels, origin, grid_extent, resolution


def voxelize_solid_warp(
    vertices: np.ndarray,
    faces: np.ndarray,
    grid_origin,
    voxel_size: float,
    resolution: int,
    device,
) -> "np.ndarray | None":
    """Solid-voxelize a triangle mesh by parity ray casting along x, y and z
    against a Warp BVH (bounding volume hierarchy).

    A voxel is occupied when at least 2 of the 3 axis parity tests find its
    centre inside (a majority vote, so one axis confused by a small hole or
    a grazing ray does not decide the result; trimesh's orthographic fill
    uses the same idea), or when the mesh surface passes through it.  Runs
    on CUDA or the Warp CPU device; voxelization.py uses trimesh's slower
    rasterize-and-fill only when this returns None, and lets anything it
    raises propagate.

    Returns
    -------
    np.ndarray | None
        (resolution, resolution, resolution) bool occupancy array, or None
        when the Warp backend is unavailable on *device*.

    Raises
    ------
    ValueError
        If the mesh has no vertices or no faces.
    """
    if not dda_backend_available(device):
        return None
    if len(vertices) == 0 or len(faces) == 0:
        raise ValueError("voxelize_solid_warp: mesh has no vertices or faces")
    device_str = f"cuda:{device.index or 0}" if device.type == "cuda" else "cpu"

    pts = wp.array(np.ascontiguousarray(vertices, dtype=np.float32), dtype=wp.vec3, device=device_str)
    idx = wp.array(np.ascontiguousarray(faces, dtype=np.int32).ravel(), dtype=wp.int32, device=device_str)
    wp_mesh = wp.Mesh(points=pts, indices=idx)

    n = resolution ** 3
    votes = wp.zeros(n, dtype=wp.int32, device=device_str)
    surface = wp.zeros(n, dtype=wp.int32, device=device_str)
    origin_wp = wp.vec3(float(grid_origin[0]), float(grid_origin[1]), float(grid_origin[2]))

    for axis in (0, 1, 2):
        wp.launch(
            _parity_voxelize_kernel,
            dim=resolution * resolution,
            inputs=[wp_mesh.id, axis, origin_wp, float(voxel_size), int(resolution),
                    votes, surface],
            device=device_str,
        )
    wp.synchronize()

    shape = (resolution, resolution, resolution)
    v = votes.numpy().reshape(shape)
    s = surface.numpy().reshape(shape)
    return (v >= 2) | (s > 0)
