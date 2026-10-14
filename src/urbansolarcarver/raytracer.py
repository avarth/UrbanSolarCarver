"""
UrbanSolarCarver: ray generation and voxel grid traversal
=========================================================

This module builds rays (sample point to sky patch, or sample point to sun,
keeping only directions the surface faces), traces them through the voxel
grid for the carving pipeline, and solid-voxelizes meshes with Warp.

Two traversal backends are available:

* DDA (digital differential analyzer, Amanatides & Woo 1987): Warp kernels
  that run one thread per ray and step from voxel to voxel, visiting every
  voxel the ray crosses exactly once.  The fused kernels
  (:func:`trace_and_score_dda`, :func:`trace_and_count_dda`) add each
  ray's weight or a count of 1 directly into a per-voxel volume, so no
  list of hits is stored.  Used whenever Warp can run on the device
  (CUDA or Warp's CPU backend).

* Fixed-step fallback (:func:`trace_multi_hit_grid`): pure PyTorch, used
  only when Warp is unavailable.  It samples each ray at regular
  distances and returns the list of (ray, voxel) pairs.  It is
  approximate: an oblique ray can cross a voxel corner between two
  samples, so that voxel is missed.

References
----------
Amanatides, J. & Woo, A. (1987). "A Fast Voxel Traversal Algorithm for
Ray Tracing." Eurographics '87, pp. 3-10.

Coordinate conventions
----------------------
* World to grid:  grid_idx = floor((world_pt - origin) / cell_size)
* Cell size:      cell_size = scale / resolution   (meters per voxel)
* Flat index:     x * resolution**2 + y * resolution + z (row-major, C order)
* floor maps a point to the voxel that contains it; rounding would shift
  every index by half a voxel.
"""

import math

import torch
import numpy as np
from typing import Tuple
import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Warp DDA kernel (compiled lazily on first use)
# ---------------------------------------------------------------------------
_warp_available = False
_warp_cpu_ok_cache: "bool | None" = None
try:
    import warp as wp
    wp.init()
    _warp_available = True
except ImportError:
    log.debug("Warp is not installed; using the PyTorch fallback tracer")
except Exception as _warp_err:
    # Installed but unusable (driver, CUDA or compiler problem): say why,
    # since every result then comes from the slower fallback paths.
    log.warning("Warp failed to initialise (%s); using the PyTorch fallback "
                "tracer and the trimesh voxelizer", _warp_err)


def _warp_cpu_ok() -> bool:
    """True if Warp can compile and launch kernels on the CPU device."""
    global _warp_cpu_ok_cache
    if _warp_cpu_ok_cache is None:
        try:
            _warp_cpu_ok_cache = bool(_warp_available and wp.is_cpu_available())
        except Exception:
            _warp_cpu_ok_cache = False
    return _warp_cpu_ok_cache


def warmup_kernels(device=None) -> bool:
    """Compile (or load from the on-disk cache) this module's Warp kernels
    for *device* now instead of on first use.

    Warp compiles all kernels in a module on the first launch.  This costs
    roughly 3-10 s once per machine, device and code version; afterwards
    the compiled binaries load from Warp's disk cache in milliseconds.
    Calling this during installation (``setup_env.py``), at daemon startup,
    or via ``usc warmup`` moves that cost to a moment where the user
    already expects to wait, so the first carving run is not slowed by it.

    Parameters
    ----------
    device : torch.device | str | None
        Target device.  None resolves like ``cfg.device='auto'``:
        CUDA when available, else the Warp CPU backend.

    Returns
    -------
    bool
        True if the kernels are ready on the device (compiled or cached);
        False if Warp is unavailable or compilation failed.  The pipeline
        still works in that case: kernels compile on first use, or the
        fallback tracer is used.
    """
    if not _warp_available:
        return False
    try:
        if device is None:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        elif isinstance(device, str):
            device = torch.device(device)
        if not dda_backend_available(device):
            return False
        device_str = f"cuda:{device.index or 0}" if device.type == "cuda" else "cpu"
        import sys
        wp.load_module(module=sys.modules[__name__], device=device_str)
        return True
    except Exception as exc:
        log.warning("Warp kernel warmup failed (%s); kernels will compile "
                    "on first use instead.", exc)
        return False


def dda_backend_available(device) -> bool:
    """True if the exact Warp DDA backend can run on *device*.

    Callers can use this to know whether trace results come from the exact
    DDA traversal or the approximate fixed-step fallback.
    """
    if not _warp_available:
        return False
    return device.type == "cuda" or _warp_cpu_ok()

if _warp_available:
    # ===================================================================
    # Shared DDA traversal
    # The three DDA kernels below (score, point-weighted score, count)
    # differ only in what they do at each visited voxel.  The traversal
    # itself (ray/box entry test, DDA state setup, step to the next voxel)
    # lives in the _dda_init and _dda_step device functions, so a change
    # to it applies to all three kernels.
    #
    # Accumulation uses wp.atomic_add.  On CUDA this is atomic.  On the
    # Warp CPU backend a launch runs its threads one after another, so
    # one launch is safe, but atomic_add is not atomic across launches
    # running in parallel OS threads; carving._run_batches therefore
    # gives each worker thread its own output array.
    # ===================================================================

    @wp.struct
    class _DDAState:
        active: int          # 1 while the ray is still traversing the grid
        vx: int
        vy: int
        vz: int
        step_x: int
        step_y: int
        step_z: int
        t_max_x: float
        t_max_y: float
        t_max_z: float
        t_delta_x: float
        t_delta_y: float
        t_delta_z: float

    @wp.func
    def _dda_init(
        o: wp.vec3,
        d: wp.vec3,
        grid_origin: wp.vec3,
        cell_size: float,
        resolution: int,
        max_t: float,
    ) -> _DDAState:
        """Intersect the ray with the grid's bounding box and set up the
        Amanatides & Woo DDA state.

        Returns a state with ``active == 0`` when the ray misses the grid
        within *max_t*; otherwise the state points at the entry voxel
        (clamped into the grid) with per-axis step, t_max and t_delta set.
        """
        s = _DDAState()
        s.active = 0

        # --- Ray/box (slab) intersection: entry and exit distance t ------
        # Grid spans [grid_origin, grid_origin + resolution * cell_size]
        t_near = 0.0
        t_far = max_t
        for axis in range(3):
            o_a = o[axis]
            d_a = d[axis]
            lo = grid_origin[axis]
            hi = lo + float(resolution) * cell_size
            if wp.abs(d_a) < 1.0e-12:
                # Ray parallel to this pair of faces: it misses unless its
                # origin is already between them.
                if o_a < lo or o_a >= hi:
                    return s
            else:
                inv_d = 1.0 / d_a
                t1 = (lo - o_a) * inv_d
                t2 = (hi - o_a) * inv_d
                if t1 > t2:
                    tmp = t1
                    t1 = t2
                    t2 = tmp
                if t1 > t_near:
                    t_near = t1
                if t2 < t_far:
                    t_far = t2
                if t_near > t_far:
                    return s
        if t_near < 0.0:
            t_near = 0.0  # origin inside the grid: start at the origin

        # --- Initialise DDA at entry point ------------------------------
        inv_cell = 1.0 / cell_size
        entry = wp.vec3(
            o[0] + d[0] * t_near,
            o[1] + d[1] * t_near,
            o[2] + d[2] * t_near,
        )
        vx = int(wp.floor((entry[0] - grid_origin[0]) * inv_cell))
        vy = int(wp.floor((entry[1] - grid_origin[1]) * inv_cell))
        vz = int(wp.floor((entry[2] - grid_origin[2]) * inv_cell))

        # Clamp to the grid: an entry point exactly on the far face, or a
        # float32 rounding error, can give an index one outside the range.
        if vx >= resolution:
            vx = resolution - 1
        if vy >= resolution:
            vy = resolution - 1
        if vz >= resolution:
            vz = resolution - 1
        if vx < 0:
            vx = 0
        if vy < 0:
            vy = 0
        if vz < 0:
            vz = 0
        s.vx = vx
        s.vy = vy
        s.vz = vz

        # Step direction (+1 or -1) per axis
        s.step_x = 1
        s.step_y = 1
        s.step_z = 1
        if d[0] < 0.0:
            s.step_x = -1
        if d[1] < 0.0:
            s.step_y = -1
        if d[2] < 0.0:
            s.step_z = -1

        # t_max: distance t at which the ray crosses the next cell boundary
        # t_delta: increase in t to cross one full cell along this axis
        #
        # EPS: a direction component at or below this is treated as zero
        # (ray parallel to that axis; t_max and t_delta set to 1e30 so the
        # axis never steps).  It is far below float32 machine epsilon
        # (~1e-7), so every ray with a nonzero component steps normally.
        EPS = 1.0e-20

        abs_dx = wp.abs(d[0])
        abs_dy = wp.abs(d[1])
        abs_dz = wp.abs(d[2])

        if abs_dx > EPS:
            if s.step_x > 0:
                s.t_max_x = (grid_origin[0] + float(vx + 1) * cell_size - o[0]) / d[0]
            else:
                s.t_max_x = (grid_origin[0] + float(vx) * cell_size - o[0]) / d[0]
            s.t_delta_x = cell_size / abs_dx
        else:
            s.t_max_x = 1.0e30
            s.t_delta_x = 1.0e30

        if abs_dy > EPS:
            if s.step_y > 0:
                s.t_max_y = (grid_origin[1] + float(vy + 1) * cell_size - o[1]) / d[1]
            else:
                s.t_max_y = (grid_origin[1] + float(vy) * cell_size - o[1]) / d[1]
            s.t_delta_y = cell_size / abs_dy
        else:
            s.t_max_y = 1.0e30
            s.t_delta_y = 1.0e30

        if abs_dz > EPS:
            if s.step_z > 0:
                s.t_max_z = (grid_origin[2] + float(vz + 1) * cell_size - o[2]) / d[2]
            else:
                s.t_max_z = (grid_origin[2] + float(vz) * cell_size - o[2]) / d[2]
            s.t_delta_z = cell_size / abs_dz
        else:
            s.t_max_z = 1.0e30
            s.t_delta_z = 1.0e30

        s.active = 1
        return s

    @wp.func
    def _dda_step(s: _DDAState, resolution: int, max_t: float) -> _DDAState:
        """Advance to the next voxel along the axis with the smallest t_max.

        Clears ``active`` when that boundary lies beyond *max_t* or the new
        voxel is outside the grid; callers loop while ``s.active == 1``.
        """
        if s.t_max_x < s.t_max_y:
            if s.t_max_x < s.t_max_z:
                if s.t_max_x > max_t:
                    s.active = 0
                    return s
                s.vx = s.vx + s.step_x
                s.t_max_x = s.t_max_x + s.t_delta_x
            else:
                if s.t_max_z > max_t:
                    s.active = 0
                    return s
                s.vz = s.vz + s.step_z
                s.t_max_z = s.t_max_z + s.t_delta_z
        else:
            if s.t_max_y < s.t_max_z:
                if s.t_max_y > max_t:
                    s.active = 0
                    return s
                s.vy = s.vy + s.step_y
                s.t_max_y = s.t_max_y + s.t_delta_y
            else:
                if s.t_max_z > max_t:
                    s.active = 0
                    return s
                s.vz = s.vz + s.step_z
                s.t_max_z = s.t_max_z + s.t_delta_z

        if (s.vx < 0 or s.vx >= resolution or s.vy < 0 or s.vy >= resolution
                or s.vz < 0 or s.vz >= resolution):
            s.active = 0
        return s

    @wp.func
    def _in_front(s: _DDAState, grid_origin: wp.vec3, cell_size: float,
                  o: wp.vec3, n: wp.vec3) -> int:
        """1 if the whole current voxel lies in front of the ray's source
        surface (the plane through *o* with normal *n*), else 0.

        A voxel the surface's plane passes through is the building's own skin
        (a test surface on a facade sits inside the boundary voxels of its own
        mass), not something that shades it.  The voxel is entirely in front
        when its centre is further in front than its half-extent along *n*.
        """
        c = wp.vec3(
            grid_origin[0] + (float(s.vx) + 0.5) * cell_size,
            grid_origin[1] + (float(s.vy) + 0.5) * cell_size,
            grid_origin[2] + (float(s.vz) + 0.5) * cell_size,
        )
        half_extent = 0.5 * cell_size * (wp.abs(n[0]) + wp.abs(n[1]) + wp.abs(n[2]))
        if wp.dot(n, c - o) > half_extent:
            return 1
        return 0

    @wp.kernel
    def _dda_fused_score_kernel(
        # Ray data
        ray_origins: wp.array(dtype=wp.vec3),
        ray_dirs: wp.array(dtype=wp.vec3),
        ray_patch_ids: wp.array(dtype=int),
        ray_point_ids: wp.array(dtype=int),
        point_normals: wp.array(dtype=wp.vec3),
        front_test: int,                        # 1 = skip voxels behind the source surface
        # Grid parameters
        grid_origin: wp.vec3,
        cell_size: float,
        resolution: int,
        max_t: float,
        # Scoring arrays (modified in place via atomic_add)
        scores: wp.array(dtype=float),         # flat score volume [res^3]
        patch_weights: wp.array(dtype=float),   # weight per patch [num_patches]
    ):
        """Trace one ray per thread and add its sky patch weight to every
        voxel it visits.

        The DDA visits each voxel at most once per ray, so a voxel's score
        is the sum of the weights of the rays that cross it.  See the note
        above _DDAState on atomic_add with the CPU backend.
        """
        tid = wp.tid()
        pid = ray_patch_ids[tid]
        w = patch_weights[pid]
        o = ray_origins[tid]
        n = wp.vec3(0.0, 0.0, 0.0)
        if front_test == 1:  # the normals array is a 1-element placeholder otherwise
            n = point_normals[ray_point_ids[tid]]
        res_sq = resolution * resolution
        s = _dda_init(o, ray_dirs[tid], grid_origin,
                      cell_size, resolution, max_t)

        # --- Walk and score ---
        # A ray crosses at most 3 * resolution - 2 voxels of a cubic grid,
        # so this loop bound never cuts a ray short.
        max_steps = 3 * resolution
        for _step in range(max_steps):
            if s.active == 0:
                return
            if (s.vx >= 0 and s.vx < resolution and s.vy >= 0
                    and s.vy < resolution and s.vz >= 0 and s.vz < resolution
                    and (front_test == 0 or _in_front(s, grid_origin, cell_size, o, n) == 1)):
                # 3D to flat index in row-major (C) order: x*res^2 + y*res + z
                flat_idx = s.vx * res_sq + s.vy * resolution + s.vz
                wp.atomic_add(scores, flat_idx, w)
            s = _dda_step(s, resolution, max_t)

    @wp.kernel
    def _dda_fused_score_pw_kernel(
        # Ray data
        ray_origins: wp.array(dtype=wp.vec3),
        ray_dirs: wp.array(dtype=wp.vec3),
        ray_patch_ids: wp.array(dtype=int),
        ray_point_ids: wp.array(dtype=int),
        point_normals: wp.array(dtype=wp.vec3),
        front_test: int,                        # 1 = skip voxels behind the source surface
        # Grid parameters
        grid_origin: wp.vec3,
        cell_size: float,
        resolution: int,
        max_t: float,
        # Scoring arrays (modified in place via atomic_add)
        scores: wp.array(dtype=float),          # flat score volume [res^3]
        patch_weights: wp.array(dtype=float),   # weight per patch [num_patches]
        point_weights: wp.array(dtype=float),   # weight per sample point [num_points]
    ):
        """Same as _dda_fused_score_kernel, but each ray's weight is
        patch weight × sample-point weight (used by the edge_taper design
        constraint).

        Kept as a separate kernel so the unweighted case does not read a
        point weight for every ray.
        """
        tid = wp.tid()
        pt = ray_point_ids[tid]
        w = patch_weights[ray_patch_ids[tid]] * point_weights[pt]
        o = ray_origins[tid]
        n = wp.vec3(0.0, 0.0, 0.0)
        if front_test == 1:  # the normals array is a 1-element placeholder otherwise
            n = point_normals[pt]
        res_sq = resolution * resolution
        s = _dda_init(o, ray_dirs[tid], grid_origin,
                      cell_size, resolution, max_t)

        # --- Walk and score ---
        max_steps = 3 * resolution
        for _step in range(max_steps):
            if s.active == 0:
                return
            if (s.vx >= 0 and s.vx < resolution and s.vy >= 0
                    and s.vy < resolution and s.vz >= 0 and s.vz < resolution
                    and (front_test == 0 or _in_front(s, grid_origin, cell_size, o, n) == 1)):
                flat_idx = s.vx * res_sq + s.vy * resolution + s.vz
                wp.atomic_add(scores, flat_idx, w)
            s = _dda_step(s, resolution, max_t)

    @wp.kernel
    def _dda_fused_count_kernel(
        # Ray data
        ray_origins: wp.array(dtype=wp.vec3),
        ray_dirs: wp.array(dtype=wp.vec3),
        ray_point_ids: wp.array(dtype=int),
        point_normals: wp.array(dtype=wp.vec3),
        front_test: int,                        # 1 = skip voxels behind the source surface
        # Grid parameters
        grid_origin: wp.vec3,
        cell_size: float,
        resolution: int,
        max_t: float,
        # Hit counter per voxel (modified in place via atomic_add)
        counts: wp.array(dtype=wp.int32),   # flat count volume [res^3]
    ):
        """Trace one ray per thread and add 1 to the counter of every voxel
        it visits.

        Used by the binary carving modes (time-based, tilted_plane), where
        a voxel's count is the number of rays that cross it.
        """
        tid = wp.tid()
        o = ray_origins[tid]
        n = wp.vec3(0.0, 0.0, 0.0)
        if front_test == 1:  # the normals array is a 1-element placeholder otherwise
            n = point_normals[ray_point_ids[tid]]
        res_sq = resolution * resolution
        s = _dda_init(o, ray_dirs[tid], grid_origin,
                      cell_size, resolution, max_t)

        # --- Walk and count ---
        max_steps = 3 * resolution
        for _step in range(max_steps):
            if s.active == 0:
                return
            if (s.vx >= 0 and s.vx < resolution and s.vy >= 0
                    and s.vy < resolution and s.vz >= 0 and s.vz < resolution
                    and (front_test == 0 or _in_front(s, grid_origin, cell_size, o, n) == 1)):
                flat_idx = s.vx * res_sq + s.vy * resolution + s.vz
                wp.atomic_add(counts, flat_idx, 1)
            s = _dda_step(s, resolution, max_t)

    @wp.kernel
    def _parity_voxelize_kernel(
        mesh_id: wp.uint64,
        axis: int,                       # marching axis: 0 (x), 1 (y), or 2 (z)
        grid_origin: wp.vec3,
        cell_size: float,
        resolution: int,
        votes: wp.array(dtype=wp.int32),    # +1 per axis whose parity sees the voxel inside
        surface: wp.array(dtype=wp.int32),  # 1 where a ray/mesh hit falls in the voxel
    ):
        """Solid voxelization by parity ray casting, one thread per grid
        column along *axis*.

        The ray starts one cell before the grid on the marching axis and
        finds successive mesh crossings (at most 256).  Voxels whose centres
        lie between an odd crossing and the next even one get one inside
        vote, and every crossing marks the voxel that contains it as
        surface.  Each thread owns its column and the three per-axis
        launches run one after another, so no atomics are needed.
        """
        tid = wp.tid()
        i = tid // resolution   # index along axis (axis+1) % 3
        j = tid % resolution    # index along axis (axis+2) % 3

        res_sq = resolution * resolution
        ci = (float(i) + 0.5) * cell_size
        cj = (float(j) + 0.5) * cell_size

        # Ray origin (just below the grid on the marching axis) and the
        # flat-index mapping coords[axis]=k, coords[(axis+1)%3]=i,
        # coords[(axis+2)%3]=j with flat = x*res^2 + y*res + z.
        if axis == 0:
            ro = wp.vec3(grid_origin[0] - cell_size, grid_origin[1] + ci, grid_origin[2] + cj)
            rd = wp.vec3(1.0, 0.0, 0.0)
            base = i * resolution + j
            stride = res_sq
        elif axis == 1:
            ro = wp.vec3(grid_origin[0] + cj, grid_origin[1] - cell_size, grid_origin[2] + ci)
            rd = wp.vec3(0.0, 1.0, 0.0)
            base = j * res_sq + i
            stride = resolution
        else:
            ro = wp.vec3(grid_origin[0] + ci, grid_origin[1] + cj, grid_origin[2] - cell_size)
            rd = wp.vec3(0.0, 0.0, 1.0)
            base = i * res_sq + j * resolution
            stride = 1

        span = (float(resolution) + 2.0) * cell_size
        eps = 1.0e-4 * cell_size

        t_off = float(0.0)
        inside = int(0)  # parity state: 1 while between an odd/even crossing pair
        entry_pos = float(0.0)  # axis-coordinate of the entry crossing
        origin_a = grid_origin[axis]

        for _hit in range(256):
            if t_off >= span:
                break
            q = wp.mesh_query_ray(mesh_id, ro + rd * t_off, rd, span - t_off)
            if not q.result:
                break
            t_hit = t_off + q.t
            # The fixed eps is absorbed by float32 rounding once t_hit
            # exceeds ~2000 cells (eps < 0.5 ULP), which would restart the
            # query at the exact hit point and freeze the traversal on one
            # triangle.  Scale the advance with t_hit (1e-6 ~ 8 ULPs) so it
            # always moves past the hit.
            eps_t = wp.max(eps, t_hit * 1.0e-6)

            # Mark the surface voxel on the SOLID side of the crossing:
            # nudge the hit point forward when entering, backward when
            # exiting.  Without the nudge, a surface lying exactly on a
            # voxel boundary would be assigned to the outside voxel.
            if inside == 0:
                p = ro + rd * (t_hit + eps_t)
            else:
                p = ro + rd * (t_hit - eps_t)
            hx = int(wp.floor((p[0] - grid_origin[0]) / cell_size))
            hy = int(wp.floor((p[1] - grid_origin[1]) / cell_size))
            hz = int(wp.floor((p[2] - grid_origin[2]) / cell_size))
            if hx < 0: hx = 0
            if hy < 0: hy = 0
            if hz < 0: hz = 0
            if hx >= resolution: hx = resolution - 1
            if hy >= resolution: hy = resolution - 1
            if hz >= resolution: hz = resolution - 1
            surface[hx * res_sq + hy * resolution + hz] = 1

            pos = ro[axis] + t_hit
            if inside == 1:
                # Vote for voxels with centers in (entry_pos, pos):
                # center_k = origin_a + (k + 0.5) * cell_size
                k0 = int(wp.ceil((entry_pos - origin_a) / cell_size - 0.5))
                k1 = int(wp.floor((pos - origin_a) / cell_size - 0.5))
                if k0 < 0: k0 = 0
                if k1 >= resolution: k1 = resolution - 1
                for k in range(k0, k1 + 1):
                    idx = base + k * stride
                    votes[idx] = votes[idx] + 1
            else:
                entry_pos = pos
            inside = 1 - inside
            t_off = t_hit + eps_t


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
    on CUDA or the Warp CPU device; grid.py falls back to trimesh's slower
    rasterize-and-fill when this returns None or raises.

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


def _surface_args(num_rays, point_ids, surface_normals, device_str, who):
    """Warp inputs for the behind-surface voxel filter.

    Returns ``(point_ids, normals, front_test)``.  Without *surface_normals*
    the normals are a 1-element placeholder and ``front_test`` is 0, so the
    kernels skip the filter; missing *point_ids* become zeros.
    """
    if surface_normals is not None and point_ids is None:
        raise ValueError(f"{who}: surface_normals and point_ids must be provided together")
    ids = (wp.from_torch(point_ids.contiguous().int()) if point_ids is not None
           else wp.zeros(num_rays, dtype=int, device=device_str))
    if surface_normals is None:
        return ids, wp.zeros(1, dtype=wp.vec3, device=device_str), 0
    return ids, wp.from_torch(surface_normals.contiguous().float(), dtype=wp.vec3), 1


def trace_and_score_dda(
    min_corner: Tuple[float, float, float],
    scale: float,
    resolution: int,
    origins: torch.Tensor,
    ray_dirs: torch.Tensor,
    patch_ids: torch.Tensor,
    patch_weights: torch.Tensor,
    scores: torch.Tensor,
    ray_length: float,
    point_ids: "torch.Tensor | None" = None,
    point_weights: "torch.Tensor | None" = None,
    surface_normals: "torch.Tensor | None" = None,
) -> None:
    """Trace rays with the Warp DDA kernel and add each ray's weight to every
    voxel it visits, directly into ``scores``.

    Runs on CUDA or the Warp CPU backend.  On CPU, do not let parallel
    calls write into the same ``scores`` tensor (see the note above
    ``_DDAState``).

    Parameters
    ----------
    min_corner : tuple of float
        World-space (x, y, z) of the grid's lower corner.
    scale : float
        Edge length of the cubic grid in meters.
    resolution : int
        Voxels per axis.
    origins, ray_dirs : torch.Tensor, shape (R, 3)
        Ray start points and unit directions.
    patch_ids : torch.Tensor, shape (R,)
        Sky patch index per ray.
    patch_weights : torch.Tensor, shape (P,)
        Weight per sky patch.
    scores : torch.Tensor, shape (resolution**3,)
        Flat contiguous float32 score volume, modified in place.
    ray_length : float
        Maximum distance traced along each ray, in meters (directions must
        be unit length for this to be a distance).
    point_ids : torch.Tensor, shape (R,), optional
        Sample-point index per ray; required by ``point_weights`` and
        ``surface_normals``.
    point_weights : torch.Tensor, shape (num_points,), optional
        Weight per sample point in [0, 1] (per-ray weight =
        patch_weight × point_weight; edge_taper design constraint).
    surface_normals : torch.Tensor, shape (num_points, 3), optional
        Normal of each ray's source surface.  When given, only voxels that
        lie entirely in front of that surface are scored; voxels behind it
        or crossed by its plane (the surface's own mass and skin) are not.

    Raises
    ------
    ValueError
        If ``scores`` is not a contiguous float32 tensor (Warp would then
        write into a copy), if ``point_ids`` is given with neither
        ``point_weights`` nor ``surface_normals``, or if either of those
        is given without ``point_ids``.
    """
    num_rays = origins.shape[0]
    if num_rays == 0:
        return
    if point_ids is not None and point_weights is None and surface_normals is None:
        raise ValueError(
            "trace_and_score_dda: point_ids must be provided together with "
            "point_weights or surface_normals"
        )
    if point_weights is not None and point_ids is None:
        raise ValueError(
            "trace_and_score_dda: point_ids and point_weights must be "
            "provided together"
        )
    # Warp requires explicit device index (e.g. "cuda:0", not just "cuda")
    device_str = f"cuda:{origins.device.index or 0}" if origins.is_cuda else "cpu"
    cell_size = scale / resolution

    if not scores.is_contiguous() or scores.dtype != torch.float32:
        raise ValueError(
            "trace_and_score_dda: scores must be a contiguous float32 tensor "
            "(in-place update would silently fail on a copy)"
        )
    wp_origins = wp.from_torch(origins.contiguous().float(), dtype=wp.vec3)
    wp_dirs = wp.from_torch(ray_dirs.contiguous().float(), dtype=wp.vec3)
    wp_patch_ids = wp.from_torch(patch_ids.contiguous().int())
    wp_scores = wp.from_torch(scores)
    wp_weights = wp.from_torch(patch_weights.contiguous().float())
    grid_origin_wp = wp.vec3(float(min_corner[0]), float(min_corner[1]), float(min_corner[2]))
    wp_point_ids, wp_normals, front = _surface_args(
        num_rays, point_ids, surface_normals, device_str, "trace_and_score_dda")

    if point_weights is not None:
        wp_point_weights = wp.from_torch(point_weights.contiguous().float())
        wp.launch(
            _dda_fused_score_pw_kernel,
            dim=num_rays,
            inputs=[
                wp_origins, wp_dirs, wp_patch_ids, wp_point_ids, wp_normals, front,
                grid_origin_wp, float(cell_size), int(resolution), float(ray_length),
                wp_scores, wp_weights, wp_point_weights,
            ],
            device=device_str,
        )
        return

    wp.launch(
        _dda_fused_score_kernel,
        dim=num_rays,
        inputs=[
            wp_origins, wp_dirs, wp_patch_ids, wp_point_ids, wp_normals, front,
            grid_origin_wp, float(cell_size), int(resolution), float(ray_length),
            wp_scores, wp_weights,
        ],
        device=device_str,
    )


def trace_and_count_dda(
    min_corner: Tuple[float, float, float],
    scale: float,
    resolution: int,
    origins: torch.Tensor,
    ray_dirs: torch.Tensor,
    counts: torch.Tensor,
    ray_length: float,
    point_ids: "torch.Tensor | None" = None,
    surface_normals: "torch.Tensor | None" = None,
) -> None:
    """Trace rays with the Warp DDA kernel and add 1 to ``counts`` for every
    voxel each ray visits, in place.

    The grid and ray arguments are the same as in
    :func:`trace_and_score_dda`, including the note on parallel CPU calls.

    Parameters
    ----------
    counts : torch.Tensor, shape (resolution**3,)
        Flat contiguous int32 hit-count volume, modified in place.
    point_ids, surface_normals : optional
        Per-ray sample-point index and per-point surface normal; when both
        are given, voxels behind the ray's source surface are not counted.
        ``point_ids`` alone is accepted and ignored.

    Raises
    ------
    ValueError
        If ``counts`` is not a contiguous int32 tensor, or
        ``surface_normals`` is given without ``point_ids``.
    """
    num_rays = origins.shape[0]
    if num_rays == 0:
        return
    device_str = f"cuda:{origins.device.index or 0}" if origins.is_cuda else "cpu"
    cell_size = scale / resolution

    if not counts.is_contiguous() or counts.dtype != torch.int32:
        raise ValueError(
            "trace_and_count_dda: counts must be a contiguous int32 tensor "
            "(in-place update would silently fail on a copy)"
        )
    wp_origins = wp.from_torch(origins.contiguous().float(), dtype=wp.vec3)
    wp_dirs = wp.from_torch(ray_dirs.contiguous().float(), dtype=wp.vec3)
    wp_counts = wp.from_torch(counts)
    grid_origin_wp = wp.vec3(float(min_corner[0]), float(min_corner[1]), float(min_corner[2]))
    wp_point_ids, wp_normals, front = _surface_args(
        num_rays, point_ids, surface_normals, device_str, "trace_and_count_dda")

    wp.launch(
        _dda_fused_count_kernel,
        dim=num_rays,
        inputs=[
            wp_origins, wp_dirs, wp_point_ids, wp_normals, front,
            grid_origin_wp, float(cell_size), int(resolution), float(ray_length),
            wp_counts,
        ],
        device=device_str,
    )


def generate_sky_patch_rays(
    pts: np.ndarray,
    norms: np.ndarray,
    patch_dirs: torch.Tensor,
    device: torch.device,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """One ray per (sample point, sky patch) pair whose patch the surface faces.

    Parameters
    ----------
    pts, norms : np.ndarray (P, 3)
        Sample points and their outward unit normals.
    patch_dirs : torch.Tensor (V, 3)
        Unit directions of the sky patches.
    device : torch.device
        Device for the returned tensors.

    A ray is kept only where dot(normal, patch direction) > 0.

    Returns
    -------
    origins : (R, 3)      ray start points (the sample points)
    ray_dirs : (R, 3)     unit ray directions
    patch_ids : (R,)      sky patch index of each ray
    point_idx : (R,)      sample point index of each ray
    """
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(f"pts must be Nx3, got {pts.shape}")
    if norms.shape != pts.shape:
        raise ValueError(f"norms shape {norms.shape} must match pts shape {pts.shape}")

    point_coords = torch.from_numpy(pts.astype(np.float32)).to(device)
    normal_vecs = torch.from_numpy(norms.astype(np.float32)).to(device)
    sky_vectors = patch_dirs.to(dtype=torch.float32, device=device)

    point_idx, patch_ids = torch.nonzero(normal_vecs @ sky_vectors.t() > 0, as_tuple=True)
    return point_coords[point_idx], sky_vectors[patch_ids], patch_ids, point_idx

def generate_sun_rays(
    points_3d: np.ndarray,
    point_normals: np.ndarray,
    sun_directions: np.ndarray,
    device: torch.device,
    return_point_idx: bool = False,
):
    """
    Build one ray per (sample point, sun direction) pair that the surface
    faces, i.e. where dot(normal, sun direction) > 0.

    Args:
      points_3d:    (P,3) NumPy array of sample points on the surface.
      point_normals:(P,3) NumPy array of normals at each sample point.
      sun_directions:(S,3) NumPy array of unit vectors pointing toward the
                     sun.  They are used as ray directions unchanged, so
                     they must be unit length for ray_length to be a distance.
      device:       Torch device for the returned tensors.
      return_point_idx: also return the source sample-point index per ray.

    Returns:
      ray_origins:   (R,3) float32 tensor of ray start points.
      ray_directions:(R,3) float32 tensor of ray direction vectors.
      point_idx:     (R,) int64 source sample-point index per ray, only when
                     return_point_idx is True.

    Raises:
      ValueError: if the arrays are not (N,3) or the normals do not match
                  the points.
    """
    if points_3d.ndim != 2 or points_3d.shape[1] != 3:
        raise ValueError(f"points_3d must be Nx3, got {points_3d.shape}")
    if point_normals.shape != points_3d.shape:
        raise ValueError(f"point_normals shape {point_normals.shape} must match points_3d shape {points_3d.shape}")
    if sun_directions.ndim != 2 or sun_directions.shape[1] != 3:
        raise ValueError(f"sun_directions must be Sx3, got {sun_directions.shape}")
    pts_tensor   = torch.from_numpy(points_3d.astype(np.float32)).to(device)
    norms_tensor = torch.from_numpy(point_normals.astype(np.float32)).to(device)
    suns_tensor  = torch.from_numpy(sun_directions.astype(np.float32)).to(device)

    dot_ps = norms_tensor @ suns_tensor.t()  # (P, S)

    facing_mask = dot_ps > 0.0

    idx_pts, idx_suns = torch.nonzero(facing_mask, as_tuple=True)

    ray_origins    = pts_tensor[idx_pts]    # (R,3)
    ray_directions = suns_tensor[idx_suns]  # (R,3)

    if return_point_idx:
        return ray_origins, ray_directions, idx_pts
    return ray_origins, ray_directions

def trace_multi_hit_grid(
    min_corner: Tuple[float, float, float],
    scale: float,
    resolution: int,
    origins: torch.Tensor,
    ray_dirs: torch.Tensor,
    sky_patch_ids: torch.Tensor,
    voxel_size: float,
    ray_length: float,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Fallback tracer for when Warp cannot run: list the voxels each ray visits.

    Fixed-step PyTorch marching (see :func:`_trace_fixed_step` for the
    parameters); when Warp is available the pipeline uses the exact fused
    DDA kernels instead.  Each (ray, voxel) pair appears at most once.
    Every call with at least one ray emits a UserWarning.

    Returns
    -------
    ray_ids : (H,)        index of the ray that made each hit
    patch_ids : (H,)      sky patch of that ray
    voxel_indices : (H, 3) grid index of each visited voxel
    """
    if origins.shape[0] == 0:
        empty1 = torch.empty((0,), dtype=torch.long, device=origins.device)
        return empty1, empty1, torch.empty((0, 3), dtype=torch.long, device=origins.device)
    import warnings
    warnings.warn(
        "Warp is not available: using the fixed-step ray marcher, which is "
        "slower and can miss voxels that oblique rays only clip.",
        stacklevel=2,
    )
    return _trace_fixed_step(min_corner, float(scale), resolution, origins, ray_dirs,
                             sky_patch_ids, voxel_size, ray_length)


# Memory budget that sets how many rays _trace_fixed_step processes per
# chunk (R rays x S steps per chunk).  Tests lower it by assigning to this
# module attribute.
_FIXED_STEP_BUDGET_BYTES: int = 512 * 1024 * 1024


def _trace_fixed_step(
    min_corner, scale, resolution,
    origins, ray_dirs, sky_patch_ids,
    voxel_size, ray_length,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Fixed-step ray marcher in pure PyTorch (runs on any torch device).

    Samples each ray at distances ``(k + 0.5) * voxel_size`` for
    ``k = 0 .. ceil(ray_length / voxel_size) - 1`` and records the voxel
    containing each in-bounds sample.  Each (ray, voxel) pair is reported
    at most once, as with the DDA kernels.  Used only when Warp is not
    installed or cannot run on the device.

    With a step of one voxel, an oblique ray can cross a voxel corner
    between two samples and miss that voxel; the Warp DDA kernels do not
    have this problem.

    Rays are processed in chunks sized from ``_FIXED_STEP_BUDGET_BYTES``
    (512 MB by default) so the ``(R, S, 3)`` sample tensor never covers
    all rays at once.  The output is identical for any chunk size.

    Parameters
    ----------
    min_corner : tuple of float
        World-space (x, y, z) of the grid's lower corner.
    scale : float
        Edge length of the cubic grid in meters.
    resolution : int
        Number of voxels per axis.
    origins : (R, 3) torch.Tensor
        Ray start positions.
    ray_dirs : (R, 3) torch.Tensor
        Unit direction vectors.
    sky_patch_ids : (R,) torch.Tensor
        Sky-patch index per ray.
    voxel_size : float
        Step length along the ray (meters); callers pass the voxel edge
        length.  Must be positive.
    ray_length : float
        Maximum march distance (meters).

    Returns
    -------
    ray_ids : (H,) torch.Tensor
        Which ray produced each hit (indices into the *full* input batch).
    patch_ids : (H,) torch.Tensor
        Sky-patch index for each hit.
    voxel_indices : (H, 3) torch.Tensor
        3-D grid coordinates of each visited voxel.

    Raises
    ------
    ValueError
        If ``voxel_size`` is not positive.
    """
    device = origins.device
    num_rays = origins.shape[0]

    if voxel_size <= 0:
        raise ValueError(
            f"_trace_fixed_step: voxel_size must be positive, got {voxel_size}"
        )
    num_steps = math.ceil(ray_length / voxel_size)
    if num_steps <= 0 or num_rays == 0:
        empty1 = torch.empty((0,), dtype=torch.long, device=device)
        empty3 = torch.empty((0, 3), dtype=torch.long, device=device)
        return empty1, empty1, empty3

    # Chunk size from the tensors held per sample: sample_pts and voxel_rel
    # (3 x float32 each, 24 bytes), voxel_idxs (3 x int64, 24 bytes) and
    # in_bounds (1 byte) make 49 bytes; 64 leaves room for the selections.
    bytes_per_ray = num_steps * 64
    budget = _FIXED_STEP_BUDGET_BYTES
    chunk_size = max(budget // max(bytes_per_ray, 1), 1)

    distances = (
        (torch.arange(num_steps, dtype=torch.float32, device=device) + 0.5)
        * voxel_size
    )
    grid_origin = torch.tensor(min_corner, dtype=torch.float32, device=device)

    all_ray_ids = []
    all_patch_ids = []
    all_voxel_indices = []

    for start in range(0, num_rays, chunk_size):
        end = min(start + chunk_size, num_rays)
        o = origins[start:end]             # (C, 3)
        d = ray_dirs[start:end]            # (C, 3)
        c = end - start

        sample_pts = o[:, None, :] + d[:, None, :] * distances[None, :, None]
        voxel_rel = (sample_pts - grid_origin) / scale * resolution
        voxel_idxs = torch.floor(voxel_rel).long()

        in_bounds = (
            (voxel_idxs[..., 0] >= 0) & (voxel_idxs[..., 0] < resolution) &
            (voxel_idxs[..., 1] >= 0) & (voxel_idxs[..., 1] < resolution) &
            (voxel_idxs[..., 2] >= 0) & (voxel_idxs[..., 2] < resolution)
        )

        ray_indices = torch.arange(c, device=device)[:, None].expand_as(in_bounds)
        chunk_ray_ids = ray_indices[in_bounds] + start  # offset to global index
        chunk_voxels = voxel_idxs[in_bounds]

        if chunk_ray_ids.numel() > 0:
            # Deduplicate (ray, voxel) pairs: two samples of one ray can fall
            # in the same voxel, which would count that ray twice for the
            # voxel.  Duplicates only arise within a single ray, and a ray
            # is never split across chunks, so per-chunk deduplication is
            # exact.  torch.unique sorts the keys, so the output order is
            # deterministic and independent of chunk size.
            res_sq = resolution * resolution
            n_vox = res_sq * resolution
            flat_vox = (
                chunk_voxels[:, 0] * res_sq
                + chunk_voxels[:, 1] * resolution
                + chunk_voxels[:, 2]
            )
            ukey = torch.unique(chunk_ray_ids * n_vox + flat_vox)
            uray = ukey // n_vox
            uflat = ukey - uray * n_vox
            uvox = torch.stack(
                (uflat // res_sq, (uflat % res_sq) // resolution, uflat % resolution),
                dim=1,
            )
            all_ray_ids.append(uray)
            all_patch_ids.append(sky_patch_ids[uray])
            all_voxel_indices.append(uvox)

        # Free this chunk's tensors before the next chunk allocates its own.
        del sample_pts, voxel_rel, voxel_idxs, in_bounds

    if not all_ray_ids:
        empty1 = torch.empty((0,), dtype=torch.long, device=device)
        empty3 = torch.empty((0, 3), dtype=torch.long, device=device)
        return empty1, empty1, empty3

    return (
        torch.cat(all_ray_ids),
        torch.cat(all_patch_ids),
        torch.cat(all_voxel_indices),
    )


def auto_batch_size(
    resolution: int,
    device: torch.device,
    *,
    vram_fraction: float = 0.6,
    fallback: int = 300_000,
) -> int:
    """Choose a ray batch size from the free GPU memory.

    The budget is ``vram_fraction`` of free VRAM (video memory).  With Warp,
    the fused DDA kernels accumulate into the voxel grid and keep no hit
    lists, so a batch only adds its slice of the ray inputs: 96 bytes per
    ray (see the comment in the code).  Without Warp, the fixed-step tracer
    returns one hit record of 40 bytes per visited voxel, estimated as
    ``max(resolution, 50)`` per ray; its sample points are already limited
    by ``_FIXED_STEP_BUDGET_BYTES``.  The result is at least 10,000 and at
    most 5,000,000 rays.

    Returns ``fallback`` on CPU or if VRAM cannot be queried.

    Parameters
    ----------
    resolution : int
        Voxel grid resolution (used only for the no-Warp step estimate).
    device : torch.device
        Target compute device.
    vram_fraction : float
        Fraction of free VRAM to budget for ray tracing (default 0.6).
    fallback : int
        Batch size when VRAM cannot be queried (default 300K).

    Returns
    -------
    int
        Recommended ray batch size.
    """
    if device.type != "cuda":
        return fallback

    try:
        free, total = torch.cuda.mem_get_info(device)
    except Exception:
        return fallback

    budget_bytes = int(free * vram_fraction)

    if _warp_available:
        # Per ray: origin and direction (2 x 12 bytes), patch id and point
        # id (2 x 8 bytes, int64) = 40 bytes, rounded up to 48; doubled for
        # the copies made when a slice is not contiguous or needs int32 ids.
        bytes_per_ray = 96
        batch = max(budget_bytes // bytes_per_ray, 10_000)
    else:
        # Hit records: ray id, patch id (int64) and voxel index (3 x int64)
        # = 40 bytes per visited voxel.
        num_steps = max(resolution, 50)  # rough estimate of voxels per ray
        bytes_per_ray = num_steps * 40
        batch = max(budget_bytes // bytes_per_ray, 10_000)

    batch = min(batch, 5_000_000)

    log.info("auto_batch_size: free=%.0f MB, budget=%.0f MB, batch=%d",
             free / 1e6, budget_bytes / 1e6, batch)
    return batch

