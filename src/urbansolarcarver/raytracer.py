"""
UrbanSolarCarver -- Ray Generation & Voxel Grid Traversal
=========================================================

This module provides ray generation (face-culled sky-patch and sun-vector
rays) and voxel-grid traversal for the carving pipeline.

Two traversal backends are available:

* DDA (Amanatides & Woo 1987) -- a Warp kernel that launches one
  thread per ray and walks through voxels using the standard 3-D DDA
  algorithm. Each voxel is visited exactly once per ray, eliminating
  duplicate hits and reducing VRAM usage by ~10x compared to the
  broadcasting approach. This is the default whenever Warp is available
  (both CUDA and CPU devices).

* Fixed-step (legacy) -- pure-PyTorch tensor broadcasting.
  Materializes the full R x S x 3 sample-point tensor in memory.
  Kept as a last-resort fallback when Warp is not installed.  Note that
  fixed stepping is approximate: oblique rays can skip voxels whose
  intersection segment is shorter than the step, under-counting hits.

References
----------
Amanatides, J. & Woo, A. (1987). "A Fast Voxel Traversal Algorithm for
Ray Tracing." Eurographics '87, pp. 3-10.

Coordinate conventions
----------------------
* World-to-grid:  grid_idx = floor((world_pt - origin) / cell_size)
* Cell size:      cell_size = scale / resolution   (meters per voxel)
* Floor (not round) avoids checkerboard aliasing on planar lattices.
"""

import math

import torch
import numpy as np
from typing import Tuple
from urbansolarcarver.session import session_cache
import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Warp DDA kernel (compiled lazily on first use)
# ---------------------------------------------------------------------------
_warp_available = False
_warp_fallback_warned = False
_warp_cpu_ok_cache: "bool | None" = None
try:
    import warp as wp
    wp.init()
    _warp_available = True
except Exception as _warp_err:
    log.debug("Warp unavailable: %s", _warp_err)


def _warp_cpu_ok() -> bool:
    """True if Warp can compile and launch kernels on the CPU device."""
    global _warp_cpu_ok_cache
    if _warp_cpu_ok_cache is None:
        try:
            _warp_cpu_ok_cache = bool(_warp_available and wp.is_cpu_available())
        except Exception:
            _warp_cpu_ok_cache = False
    return _warp_cpu_ok_cache


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
    # IMPORTANT — PAIRED DDA KERNELS
    # _dda_trace_kernel and _dda_fused_score_kernel share identical DDA
    # traversal logic (ray-AABB intersection, init, step).  Warp kernels
    # cannot call shared helpers, so the code is duplicated.
    #
    # ANY change to the DDA traversal (EPS, clamping, step logic, bounds
    # checks) MUST be applied to BOTH kernels.
    # ===================================================================

    @wp.kernel
    def _dda_trace_kernel(
        # Ray data (one thread per ray)
        ray_origins: wp.array(dtype=wp.vec3),
        ray_dirs: wp.array(dtype=wp.vec3),
        # Grid parameters
        grid_origin: wp.vec3,
        cell_size: float,       # meters per voxel = scale / resolution
        resolution: int,
        max_t: float,           # ray_length in meters
        # Output buffers (pre-allocated to max possible hits)
        out_ray_ids: wp.array(dtype=int),
        out_voxel_x: wp.array(dtype=int),
        out_voxel_y: wp.array(dtype=int),
        out_voxel_z: wp.array(dtype=int),
        hit_counter: wp.array(dtype=int),   # single-element atomic counter
        max_hits: int,
    ):
        """Amanatides & Woo DDA: one GPU thread per ray.

        Each thread computes the ray's entry into the grid via ray-AABB
        intersection, initialises t_max and t_delta per axis, then steps
        through voxels recording each unique cell visited. Traversal
        stops when the ray exits the grid or exceeds max_t.

        Hits are written to flat output arrays using an atomic counter
        to avoid collisions between threads.
        """
        tid = wp.tid()
        o = ray_origins[tid]
        d = ray_dirs[tid]
        inv_cell = 1.0 / cell_size
        res_f = float(resolution)

        # --- Ray-AABB intersection to find entry/exit t -----------------
        # Grid spans [grid_origin, grid_origin + resolution * cell_size]
        t_near = 0.0
        t_far = max_t

        for axis in range(3):
            o_a = o[axis]
            d_a = d[axis]
            lo = grid_origin[axis]
            hi = lo + res_f * cell_size

            if wp.abs(d_a) < 1.0e-12:
                # Ray parallel to slab -- miss if origin outside
                if o_a < lo or o_a >= hi:
                    return
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
                    return

        if t_near < 0.0:
            t_near = 0.0

        # --- Initialise DDA at entry point ------------------------------
        entry = wp.vec3(
            o[0] + d[0] * t_near,
            o[1] + d[1] * t_near,
            o[2] + d[2] * t_near,
        )

        # Current voxel indices
        vx = int(wp.floor((entry[0] - grid_origin[0]) * inv_cell))
        vy = int(wp.floor((entry[1] - grid_origin[1]) * inv_cell))
        vz = int(wp.floor((entry[2] - grid_origin[2]) * inv_cell))

        # Clamp to valid range (entry point may land exactly on far boundary)
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

        # Step direction (+1 or -1) and t_delta (t to cross one cell)
        step_x = 1
        step_y = 1
        step_z = 1

        if d[0] < 0.0:
            step_x = -1
        if d[1] < 0.0:
            step_y = -1
        if d[2] < 0.0:
            step_z = -1

        # t_max: t value at which the ray crosses the next cell boundary
        # t_delta: t increment to traverse one full cell along this axis
        #
        # EPS: threshold to treat a direction component as zero (ray parallel
        # to that axis).  Set far below float32 machine epsilon (~1e-7) so that
        # any ray with a nonzero component is handled by the DDA stepper.
        EPS = 1.0e-20

        abs_dx = wp.abs(d[0])
        abs_dy = wp.abs(d[1])
        abs_dz = wp.abs(d[2])

        if abs_dx > EPS:
            if step_x > 0:
                t_max_x = (grid_origin[0] + float(vx + 1) * cell_size - o[0]) / d[0]
            else:
                t_max_x = (grid_origin[0] + float(vx) * cell_size - o[0]) / d[0]
            t_delta_x = cell_size / abs_dx
        else:
            t_max_x = 1.0e30
            t_delta_x = 1.0e30

        if abs_dy > EPS:
            if step_y > 0:
                t_max_y = (grid_origin[1] + float(vy + 1) * cell_size - o[1]) / d[1]
            else:
                t_max_y = (grid_origin[1] + float(vy) * cell_size - o[1]) / d[1]
            t_delta_y = cell_size / abs_dy
        else:
            t_max_y = 1.0e30
            t_delta_y = 1.0e30

        if abs_dz > EPS:
            if step_z > 0:
                t_max_z = (grid_origin[2] + float(vz + 1) * cell_size - o[2]) / d[2]
            else:
                t_max_z = (grid_origin[2] + float(vz) * cell_size - o[2]) / d[2]
            t_delta_z = cell_size / abs_dz
        else:
            t_max_z = 1.0e30
            t_delta_z = 1.0e30

        # --- Walk through voxels ----------------------------------------
        # Safety bound: a ray can cross at most 3 * resolution voxels
        max_steps = 3 * resolution
        for _step in range(max_steps):
            # Record this voxel
            if vx >= 0 and vx < resolution and vy >= 0 and vy < resolution and vz >= 0 and vz < resolution:
                idx = wp.atomic_add(hit_counter, 0, 1)
                if idx < max_hits:
                    out_ray_ids[idx] = tid
                    out_voxel_x[idx] = vx
                    out_voxel_y[idx] = vy
                    out_voxel_z[idx] = vz

            # Advance to next voxel (smallest t_max wins)
            if t_max_x < t_max_y:
                if t_max_x < t_max_z:
                    if t_max_x > max_t:
                        return
                    vx = vx + step_x
                    t_max_x = t_max_x + t_delta_x
                else:
                    if t_max_z > max_t:
                        return
                    vz = vz + step_z
                    t_max_z = t_max_z + t_delta_z
            else:
                if t_max_y < t_max_z:
                    if t_max_y > max_t:
                        return
                    vy = vy + step_y
                    t_max_y = t_max_y + t_delta_y
                else:
                    if t_max_z > max_t:
                        return
                    vz = vz + step_z
                    t_max_z = t_max_z + t_delta_z

            # Out of grid → done
            if vx < 0 or vx >= resolution or vy < 0 or vy >= resolution or vz < 0 or vz >= resolution:
                return


    # See PAIRED DDA KERNELS note above _dda_trace_kernel.
    @wp.kernel
    def _dda_fused_score_kernel(
        # Ray data
        ray_origins: wp.array(dtype=wp.vec3),
        ray_dirs: wp.array(dtype=wp.vec3),
        ray_patch_ids: wp.array(dtype=int),
        # Grid parameters
        grid_origin: wp.vec3,
        cell_size: float,
        resolution: int,
        max_t: float,
        # Scoring arrays (modified in-place via atomic_add)
        scores: wp.array(dtype=float),         # flat score volume [res^3]
        patch_weights: wp.array(dtype=float),   # weight per patch [num_patches]
    ):
        """Fused DDA + scoring: traverse grid and accumulate weights in-place.

        Combines voxel traversal and score accumulation into a single kernel.
        No output buffer is needed -- each thread atomically adds the patch
        weight to the score volume for every voxel it visits.

        This eliminates:
        - Output buffer allocation (was O(rays * hits_per_ray))
        - Host-side scatter_add_ post-processing
        - Deduplication (DDA visits each voxel exactly once per ray)
        """
        tid = wp.tid()
        o = ray_origins[tid]
        d = ray_dirs[tid]
        pid = ray_patch_ids[tid]
        w = patch_weights[pid]
        inv_cell = 1.0 / cell_size
        res_f = float(resolution)
        res_sq = resolution * resolution

        # --- Ray-AABB intersection ---
        t_near = 0.0
        t_far = max_t
        for axis in range(3):
            o_a = o[axis]
            d_a = d[axis]
            lo = grid_origin[axis]
            hi = lo + res_f * cell_size
            if wp.abs(d_a) < 1.0e-12:
                if o_a < lo or o_a >= hi:
                    return
            else:
                inv_d = 1.0 / d_a
                t1 = (lo - o_a) * inv_d
                t2 = (hi - o_a) * inv_d
                if t1 > t2:
                    tmp = t1; t1 = t2; t2 = tmp
                if t1 > t_near:
                    t_near = t1
                if t2 < t_far:
                    t_far = t2
                if t_near > t_far:
                    return
        if t_near < 0.0:
            t_near = 0.0

        # --- Init DDA ---
        entry = wp.vec3(
            o[0] + d[0] * t_near,
            o[1] + d[1] * t_near,
            o[2] + d[2] * t_near,
        )
        vx = int(wp.floor((entry[0] - grid_origin[0]) * inv_cell))
        vy = int(wp.floor((entry[1] - grid_origin[1]) * inv_cell))
        vz = int(wp.floor((entry[2] - grid_origin[2]) * inv_cell))
        if vx >= resolution: vx = resolution - 1
        if vy >= resolution: vy = resolution - 1
        if vz >= resolution: vz = resolution - 1
        if vx < 0: vx = 0
        if vy < 0: vy = 0
        if vz < 0: vz = 0

        step_x = 1; step_y = 1; step_z = 1
        if d[0] < 0.0: step_x = -1
        if d[1] < 0.0: step_y = -1
        if d[2] < 0.0: step_z = -1

        EPS = 1.0e-20  # parallel-axis threshold (see first DDA kernel)
        abs_dx = wp.abs(d[0]); abs_dy = wp.abs(d[1]); abs_dz = wp.abs(d[2])

        if abs_dx > EPS:
            if step_x > 0: t_max_x = (grid_origin[0] + float(vx + 1) * cell_size - o[0]) / d[0]
            else:           t_max_x = (grid_origin[0] + float(vx) * cell_size - o[0]) / d[0]
            t_delta_x = cell_size / abs_dx
        else:
            t_max_x = 1.0e30; t_delta_x = 1.0e30

        if abs_dy > EPS:
            if step_y > 0: t_max_y = (grid_origin[1] + float(vy + 1) * cell_size - o[1]) / d[1]
            else:           t_max_y = (grid_origin[1] + float(vy) * cell_size - o[1]) / d[1]
            t_delta_y = cell_size / abs_dy
        else:
            t_max_y = 1.0e30; t_delta_y = 1.0e30

        if abs_dz > EPS:
            if step_z > 0: t_max_z = (grid_origin[2] + float(vz + 1) * cell_size - o[2]) / d[2]
            else:           t_max_z = (grid_origin[2] + float(vz) * cell_size - o[2]) / d[2]
            t_delta_z = cell_size / abs_dz
        else:
            t_max_z = 1.0e30; t_delta_z = 1.0e30

        # --- Walk and score ---
        max_steps = 3 * resolution
        for _step in range(max_steps):
            if vx >= 0 and vx < resolution and vy >= 0 and vy < resolution and vz >= 0 and vz < resolution:
                # 3D → 1D index in row-major (C) order: x*(res²) + y*res + z
                flat_idx = vx * res_sq + vy * resolution + vz
                wp.atomic_add(scores, flat_idx, w)

            if t_max_x < t_max_y:
                if t_max_x < t_max_z:
                    if t_max_x > max_t: return
                    vx = vx + step_x; t_max_x = t_max_x + t_delta_x
                else:
                    if t_max_z > max_t: return
                    vz = vz + step_z; t_max_z = t_max_z + t_delta_z
            else:
                if t_max_y < t_max_z:
                    if t_max_y > max_t: return
                    vy = vy + step_y; t_max_y = t_max_y + t_delta_y
                else:
                    if t_max_z > max_t: return
                    vz = vz + step_z; t_max_z = t_max_z + t_delta_z

            if vx < 0 or vx >= resolution or vy < 0 or vy >= resolution or vz < 0 or vz >= resolution:
                return

    # See PAIRED DDA KERNELS note above _dda_trace_kernel.
    @wp.kernel
    def _dda_fused_count_kernel(
        # Ray data
        ray_origins: wp.array(dtype=wp.vec3),
        ray_dirs: wp.array(dtype=wp.vec3),
        # Grid parameters
        grid_origin: wp.vec3,
        cell_size: float,
        resolution: int,
        max_t: float,
        # Hit counter per voxel (modified in-place via atomic_add)
        counts: wp.array(dtype=wp.int32),   # flat count volume [res^3]
    ):
        """Fused DDA + hit counting: traverse the grid and increment each
        visited voxel's counter in-place.

        Used by the binary carving modes (time-based, tilted_plane), where
        the count is the number of violating rays per voxel.  Like the
        fused score kernel, this needs no output buffer — which also means
        no overflow-retry re-tracing.
        """
        tid = wp.tid()
        o = ray_origins[tid]
        d = ray_dirs[tid]
        inv_cell = 1.0 / cell_size
        res_f = float(resolution)
        res_sq = resolution * resolution

        # --- Ray-AABB intersection ---
        t_near = 0.0
        t_far = max_t
        for axis in range(3):
            o_a = o[axis]
            d_a = d[axis]
            lo = grid_origin[axis]
            hi = lo + res_f * cell_size
            if wp.abs(d_a) < 1.0e-12:
                if o_a < lo or o_a >= hi:
                    return
            else:
                inv_d = 1.0 / d_a
                t1 = (lo - o_a) * inv_d
                t2 = (hi - o_a) * inv_d
                if t1 > t2:
                    tmp = t1; t1 = t2; t2 = tmp
                if t1 > t_near:
                    t_near = t1
                if t2 < t_far:
                    t_far = t2
                if t_near > t_far:
                    return
        if t_near < 0.0:
            t_near = 0.0

        # --- Init DDA ---
        entry = wp.vec3(
            o[0] + d[0] * t_near,
            o[1] + d[1] * t_near,
            o[2] + d[2] * t_near,
        )
        vx = int(wp.floor((entry[0] - grid_origin[0]) * inv_cell))
        vy = int(wp.floor((entry[1] - grid_origin[1]) * inv_cell))
        vz = int(wp.floor((entry[2] - grid_origin[2]) * inv_cell))
        if vx >= resolution: vx = resolution - 1
        if vy >= resolution: vy = resolution - 1
        if vz >= resolution: vz = resolution - 1
        if vx < 0: vx = 0
        if vy < 0: vy = 0
        if vz < 0: vz = 0

        step_x = 1; step_y = 1; step_z = 1
        if d[0] < 0.0: step_x = -1
        if d[1] < 0.0: step_y = -1
        if d[2] < 0.0: step_z = -1

        EPS = 1.0e-20  # parallel-axis threshold (see first DDA kernel)
        abs_dx = wp.abs(d[0]); abs_dy = wp.abs(d[1]); abs_dz = wp.abs(d[2])

        if abs_dx > EPS:
            if step_x > 0: t_max_x = (grid_origin[0] + float(vx + 1) * cell_size - o[0]) / d[0]
            else:           t_max_x = (grid_origin[0] + float(vx) * cell_size - o[0]) / d[0]
            t_delta_x = cell_size / abs_dx
        else:
            t_max_x = 1.0e30; t_delta_x = 1.0e30

        if abs_dy > EPS:
            if step_y > 0: t_max_y = (grid_origin[1] + float(vy + 1) * cell_size - o[1]) / d[1]
            else:           t_max_y = (grid_origin[1] + float(vy) * cell_size - o[1]) / d[1]
            t_delta_y = cell_size / abs_dy
        else:
            t_max_y = 1.0e30; t_delta_y = 1.0e30

        if abs_dz > EPS:
            if step_z > 0: t_max_z = (grid_origin[2] + float(vz + 1) * cell_size - o[2]) / d[2]
            else:           t_max_z = (grid_origin[2] + float(vz) * cell_size - o[2]) / d[2]
            t_delta_z = cell_size / abs_dz
        else:
            t_max_z = 1.0e30; t_delta_z = 1.0e30

        # --- Walk and count ---
        max_steps = 3 * resolution
        for _step in range(max_steps):
            if vx >= 0 and vx < resolution and vy >= 0 and vy < resolution and vz >= 0 and vz < resolution:
                flat_idx = vx * res_sq + vy * resolution + vz
                wp.atomic_add(counts, flat_idx, 1)

            if t_max_x < t_max_y:
                if t_max_x < t_max_z:
                    if t_max_x > max_t: return
                    vx = vx + step_x; t_max_x = t_max_x + t_delta_x
                else:
                    if t_max_z > max_t: return
                    vz = vz + step_z; t_max_z = t_max_z + t_delta_z
            else:
                if t_max_y < t_max_z:
                    if t_max_y > max_t: return
                    vy = vy + step_y; t_max_y = t_max_y + t_delta_y
                else:
                    if t_max_z > max_t: return
                    vz = vz + step_z; t_max_z = t_max_z + t_delta_z

            if vx < 0 or vx >= resolution or vy < 0 or vy >= resolution or vz < 0 or vz >= resolution:
                return

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
        """Solid voxelization by parity ray casting: one thread per grid
        column.  The ray starts below the grid and walks successive
        mesh intersections; voxels whose CENTERS lie between an odd and
        even crossing get an inside-vote, and every crossing marks the
        voxel containing the hit point as surface.  Columns are exclusive
        per thread and per-axis launches are serialized, so no atomics
        are needed.
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

            # Mark the surface voxel on the SOLID side of the crossing:
            # nudge the hit point forward when entering, backward when
            # exiting.  Without the nudge, a surface lying exactly on a
            # voxel boundary would be assigned to the outside voxel.
            if inside == 0:
                p = ro + rd * (t_hit + eps)
            else:
                p = ro + rd * (t_hit - eps)
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
            t_off = t_hit + eps


def voxelize_solid_warp(
    vertices: np.ndarray,
    faces: np.ndarray,
    grid_origin,
    voxel_size: float,
    resolution: int,
    device,
) -> "np.ndarray | None":
    """Solid-voxelize a triangle mesh via 3-axis parity ray casting on the
    Warp BVH.  Returns a (res, res, res) bool occupancy array, or None when
    the Warp backend is unavailable on *device*.

    A voxel is occupied when at least 2 of the 3 axis parities agree that
    its center is inside (majority vote — the same robustness idea as
    trimesh's orthographic fill), or when the surface passes through it.
    Runs on CUDA or the Warp CPU device; both are far faster than the
    trimesh rasterize-and-fill path.
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
) -> None:
    """Fused DDA traversal + score accumulation (Warp GPU kernel).

    Atomically adds patch weights to the score volume for every voxel
    each ray visits. No output buffer, no post-processing. Modifies
    ``scores`` in-place.

    Parameters
    ----------
    min_corner : tuple of float
        Grid origin in world space.
    scale : float
        Grid extent in meters.
    resolution : int
        Voxels per axis.
    origins, ray_dirs : torch.Tensor, shape (R, 3)
        Ray start points and unit directions.
    patch_ids : torch.Tensor, shape (R,)
        Sky patch index per ray.
    patch_weights : torch.Tensor, shape (P,)
        Weight per sky patch.
    scores : torch.Tensor, shape (N,)
        Flat score volume, modified in-place.
    ray_length : float
        Maximum march distance.
    """
    num_rays = origins.shape[0]
    if num_rays == 0:
        return
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

    wp.launch(
        _dda_fused_score_kernel,
        dim=num_rays,
        inputs=[
            wp_origins, wp_dirs, wp_patch_ids,
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
) -> None:
    """Fused DDA traversal + per-voxel hit counting (Warp kernel).

    Atomically increments ``counts`` for every voxel each ray visits.
    No output buffer and no overflow-retry re-tracing (unlike the
    buffered :func:`trace_multi_hit_grid` path).  Modifies ``counts``
    in-place.

    Parameters
    ----------
    counts : torch.Tensor, shape (resolution**3,)
        Flat int32 hit-count volume, modified in-place.
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

    wp.launch(
        _dda_fused_count_kernel,
        dim=num_rays,
        inputs=[
            wp_origins, wp_dirs,
            grid_origin_wp, float(cell_size), int(resolution), float(ray_length),
            wp_counts,
        ],
        device=device_str,
    )


def _trace_dda_warp(
    min_corner: Tuple[float, float, float],
    scale: float,
    resolution: int,
    origins: torch.Tensor,
    ray_dirs: torch.Tensor,
    sky_patch_ids: torch.Tensor,
    voxel_size: float,
    ray_length: float,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """DDA traversal via Warp kernel -- zero-copy interop with PyTorch.

    Starts with a conservative buffer estimate (20 hits/ray), launches
    the kernel, then retries with a larger buffer if overflow occurs.
    Typically only one launch is needed.
    """
    num_rays = origins.shape[0]
    # Warp requires explicit device index (e.g. "cuda:0", not just "cuda")
    device_str = f"cuda:{origins.device.index or 0}" if origins.is_cuda else "cpu"
    cell_size = scale / resolution

    wp_origins = wp.from_torch(origins.contiguous().float(), dtype=wp.vec3)
    wp_dirs = wp.from_torch(ray_dirs.contiguous().float(), dtype=wp.vec3)
    grid_origin_wp = wp.vec3(float(min_corner[0]), float(min_corner[1]), float(min_corner[2]))

    # Initial buffer size per ray for DDA output arrays.  Most rays
    # traverse 10–30 voxels in typical urban grids, but large urban scenes
    # with fine voxel grids can produce 100–300 hits/ray.  The kernel retries
    # with a 2× buffer on each overflow, up to 6 attempts
    # (20 → 40 → 80 → 160 → 320 → 640 hits/ray).
    est_hits_per_ray = 20
    for attempt in range(6):
        max_hits = num_rays * est_hits_per_ray

        out_ray_ids = wp.zeros(max_hits, dtype=int, device=device_str)
        out_vx = wp.zeros(max_hits, dtype=int, device=device_str)
        out_vy = wp.zeros(max_hits, dtype=int, device=device_str)
        out_vz = wp.zeros(max_hits, dtype=int, device=device_str)
        hit_counter = wp.zeros(1, dtype=int, device=device_str)

        wp.launch(
            _dda_trace_kernel,
            dim=num_rays,
            inputs=[
                wp_origins, wp_dirs,
                grid_origin_wp,
                float(cell_size), int(resolution), float(ray_length),
                out_ray_ids, out_vx, out_vy, out_vz,
                hit_counter, int(max_hits),
            ],
            device=device_str,
        )
        wp.synchronize()

        actual_count = int(hit_counter.numpy()[0])
        if actual_count <= max_hits:
            break
        # Overflow: double the estimate and retry
        import warnings
        warnings.warn(
            f"DDA buffer overflow ({actual_count} > {max_hits}), "
            f"retrying with {est_hits_per_ray * 2}/ray",
            stacklevel=2,
        )
        est_hits_per_ray *= 2

    actual_hits = min(actual_count, max_hits)
    if actual_count > max_hits:
        import warnings
        warnings.warn(
            f"DDA trace truncated: {actual_count - max_hits} hits lost after 6 retries "
            f"({max_hits} recorded / {actual_count} actual)",
            stacklevel=2,
        )
    if actual_hits == 0:
        empty1 = torch.empty((0,), dtype=torch.long, device=origins.device)
        empty3 = torch.empty((0, 3), dtype=torch.long, device=origins.device)
        return empty1, empty1, empty3

    # Convert Warp → PyTorch (zero-copy on CUDA)
    ray_ids_t = wp.to_torch(out_ray_ids)[:actual_hits].long()
    vx_t = wp.to_torch(out_vx)[:actual_hits].long()
    vy_t = wp.to_torch(out_vy)[:actual_hits].long()
    vz_t = wp.to_torch(out_vz)[:actual_hits].long()

    voxel_indices = torch.stack([vx_t, vy_t, vz_t], dim=1)
    patch_ids = sky_patch_ids.to(origins.device)[ray_ids_t]

    return ray_ids_t, patch_ids, voxel_indices

def generate_sky_patch_rays(
    pts: np.ndarray,           # List of 3D coordinates where rays originate (shape Px3).
    norms: np.ndarray,         # Surface normals at each point (shape Px3).
    patch_dirs: torch.Tensor,  # Unit vectors representing directions of sky patches (shape Vx3).
    device: torch.device,       # Compute device (CPU or GPU).
    *,
    include_normals: bool = False,
    ray_id: str | None = None,
    session: "CarverSession | None" = None,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, "torch.Tensor | None", torch.Tensor]:
    """
    Build rays for each sample point and sky patch direction.
    1. We have P sample locations on a surface and V directions in the sky (divided into patches).
    2. For each surface point, we want to know which sky patches are 'visible' (face-culling) by checking if the normal faces that patch.
    3. We then record an origin (the point) and a direction (the sky patch) for each valid combination.

    ``include_normals`` gates the per-ray normal gather: it is an (R, 3)
    tensor nobody in the pipeline consumes — hundreds of MB of VRAM at
    typical ray counts — so it is only materialized on request.

    Returns:
      origins           : Tensor of 3D positions where rays start (one per valid combination).
      ray_dirs          : Tensor of unit vectors indicating ray directions.
      sky_patch_ids     : Integer index for which sky patch each ray corresponds to.
      normals_per_ray   : Surface normal per ray, or None unless include_normals=True.
      point_idx         : Integer index mapping each ray back to its source sample point.
    """

    if pts.ndim!=2 or pts.shape[1]!=3:
        raise ValueError(f"pts must be Nx3, got {pts.shape}")
    if norms.shape != pts.shape:
        raise ValueError(f"norms shape {norms.shape} must match pts shape {pts.shape}")

    # --- Session cache (keyed on array identity, not just shape) -----------
    # id(pts) is unique per array object within a session generation.
    # bump() clears the cache between runs, so id reuse is not a concern.
    from urbansolarcarver.session import get_active_session
    sess = session or get_active_session()
    if sess is not None:
        cache_key = (
            f"patch_rays:{pts.shape[0]}:{patch_dirs.shape[0]}:{id(pts)}"
            f":n{int(include_normals)}"
        )
        cached = sess.tensors.get(f"{cache_key}|g{sess._gen}")
        if cached is not None:
            return cached

    # Convert input data into PyTorch tensors and move to the chosen compute device.
    point_coords  = torch.from_numpy(pts.astype(np.float32)).to(device)    # (P,3)
    normal_vecs   = torch.from_numpy(norms.astype(np.float32)).to(device)  # (P,3)
    sky_vectors   = patch_dirs.to(dtype=torch.float32, device=device)      # (V,3)

    # Compute a matrix of dot products between each surface normal and each sky patch vector.
    dot_products = normal_vecs @ sky_vectors.t()  # Results in PxV matrix.

    # Identify all combinations where the dot product is greater than zero.
    point_idx, vector_idx = torch.nonzero(dot_products > 0, as_tuple=True)

    origins         = point_coords[point_idx]  # (R,3) where R is number of valid rays.
    ray_dirs        = sky_vectors[vector_idx]   # (R,3)
    sky_patch_ids   = vector_idx                # (R,)
    normals_per_ray = normal_vecs[point_idx] if include_normals else None  # (R,3)

    result = (origins, ray_dirs, sky_patch_ids, normals_per_ray, point_idx)

    # Store in session cache
    if sess is not None:
        sess.tensors[f"{cache_key}|g{sess._gen}"] = result

    return result

def generate_sun_rays(
    points_3d: np.ndarray,
    point_normals: np.ndarray,
    sun_directions: np.ndarray,
    device: torch.device
) -> Tuple[torch.Tensor, torch.Tensor]:
    """
    Build ray origins and directions for direct-beam sampling.

    Steps:
      1) Convert the input arrays (points, normals, sun vectors) to float32 Torch
         tensors on the specified device.
      2) Compute a (P x S) dot-product matrix between each normal and each sun vector.
      3) Mask for entries where dot(normal, sun_direction) > 0 -- these are the facets
         actually facing the sun.
      4) Extract the (point_idx, sun_idx) pairs that satisfy the facing test.
      5) Gather and return the corresponding origin points and direction vectors.

    Args:
      points_3d:    (P,3) NumPy array of sample points on the surface.
      point_normals:(P,3) NumPy array of normals at each sample point.
      sun_directions:(S,3) NumPy array of sun direction vectors (should be unit length).
      device:       Torch device (e.g. `torch.device('cuda')`).

    Returns:
      ray_origins:   (R,3) float32 tensor of ray start points.
      ray_directions:(R,3) float32 tensor of ray direction vectors.
    """
    if points_3d.ndim != 2 or points_3d.shape[1] != 3:
        raise ValueError(f"points_3d must be Nx3, got {points_3d.shape}")
    if point_normals.shape != points_3d.shape:
        raise ValueError(f"point_normals shape {point_normals.shape} must match points_3d shape {points_3d.shape}")
    if sun_directions.ndim != 2 or sun_directions.shape[1] != 3:
        raise ValueError(f"sun_directions must be Sx3, got {sun_directions.shape}")
    # 1) To‐device tensor conversion
    pts_tensor   = torch.from_numpy(points_3d.astype(np.float32)).to(device)
    norms_tensor = torch.from_numpy(point_normals.astype(np.float32)).to(device)
    suns_tensor  = torch.from_numpy(sun_directions.astype(np.float32)).to(device)

    # 2) Dot product per (point, sun) → shape (P, S)
    dot_ps = norms_tensor @ suns_tensor.t()

    # 3) Facing mask (only keep normal*sun > 0)
    facing_mask = dot_ps > 0.0

    # 4) Indices of valid rays
    idx_pts, idx_suns = torch.nonzero(facing_mask, as_tuple=True)

    # 5) Gather origins and directions
    ray_origins    = pts_tensor[idx_pts]    # (R,3)
    ray_directions = suns_tensor[idx_suns]  # (R,3)

    return ray_origins, ray_directions

def trace_multi_hit_grid(
    min_corner: Tuple[float, float, float],
    scale: "float | torch.Tensor",
    resolution: int,
    origins: torch.Tensor,
    ray_dirs: torch.Tensor,
    sky_patch_ids: torch.Tensor,
    voxel_size: float,
    ray_length: float,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Trace rays through a uniform voxel grid, recording every voxel hit.

    Dispatches to the Warp DDA kernel on CUDA (Amanatides & Woo 1987) or
    falls back to fixed-step PyTorch broadcasting on CPU.  Both backends
    guarantee that each (ray, voxel) pair appears at most once in the
    output, so callers can accumulate hits without deduplicating.

    Parameters
    ----------
    min_corner : tuple of float
        World-space (x, y, z) of the grid's lower corner.
    scale : torch.Tensor or float
        Full spatial extent of the grid in meters (grid_extent).
    resolution : int
        Number of voxels per axis (grid is resolution³).
    origins : torch.Tensor, shape (R, 3)
        Ray start points.
    ray_dirs : torch.Tensor, shape (R, 3)
        Unit direction vectors.
    sky_patch_ids : torch.Tensor, shape (R,)
        Sky patch index per ray.
    voxel_size : float
        Physical edge length of one voxel (meters).
    ray_length : float
        Maximum march distance (meters).

    Returns
    -------
    ray_ids : torch.Tensor, shape (H,)
        Which ray produced each hit.
    patch_ids : torch.Tensor, shape (H,)
        Sky patch index for each hit.
    voxel_indices : torch.Tensor, shape (H, 3)
        3-D grid coordinate of each visited voxel.
    """
    num_rays = origins.shape[0]
    if num_rays == 0:
        empty1 = torch.empty((0,), dtype=torch.long, device=origins.device)
        empty3 = torch.empty((0, 3), dtype=torch.long, device=origins.device)
        return empty1, empty1, empty3

    # Extract a single float from scale, which may arrive as:
    #   - a plain int/float (normal case)
    #   - a scalar tensor, e.g. torch.tensor(100.0)
    #   - a 1D/3D tensor, e.g. torch.full((3,), extent)  [legacy callers]
    # The voxel grid is always cubic, so all elements are identical.
    if isinstance(scale, (int, float)):
        scale_f = float(scale)
    elif hasattr(scale, 'item'):
        scale_f = float(scale.ravel()[0].item())
    else:
        scale_f = float(scale)

    # --- DDA backend (Warp, CUDA or CPU) ---
    if dda_backend_available(origins.device):
        return _trace_dda_warp(
            min_corner, scale_f, resolution,
            origins, ray_dirs, sky_patch_ids,
            voxel_size, ray_length,
        )

    # --- Legacy fixed-step fallback (Warp not available) ---
    global _warp_fallback_warned
    if not _warp_fallback_warned:
        import warnings
        warnings.warn(
            "Warp DDA backend is not available — using the fixed-step ray "
            "marcher, which is slower and can miss voxels on oblique rays. "
            "Install NVIDIA Warp for exact DDA tracing.",
            stacklevel=2,
        )
        _warp_fallback_warned = True
    return _trace_fixed_step(
        min_corner, scale_f, resolution,
        origins, ray_dirs, sky_patch_ids,
        voxel_size, ray_length,
    )


# Peak memory budget for the fixed-step tracer's sample-point tensor.
# The (R, S, 3) float32 tensor is the dominant allocation; this caps the
# number of rays processed per internal chunk so peak memory stays bounded.
# Default 512 MB -- override in tests via module attribute.
_FIXED_STEP_BUDGET_BYTES: int = 512 * 1024 * 1024


def _trace_fixed_step(
    min_corner, scale, resolution,
    origins, ray_dirs, sky_patch_ids,
    voxel_size, ray_length,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Legacy fixed-step ray marcher (pure PyTorch, CPU fallback).

    Traces rays through a uniform voxel grid by sampling at cell-center
    offsets ``(k + 0.5) * voxel_size`` and recording every in-bounds voxel
    hit.  Each (ray, voxel) pair is reported at most once, matching the
    DDA backend's contract.  Used when the Warp DDA kernel is unavailable
    (no GPU or Warp not installed).

    Note: with a step of one voxel, oblique rays can skip voxels whose
    intersection segment is short.  The Warp DDA backend is exact; prefer
    it when Warp is installed.

    To avoid materializing a single massive ``(R, S, 3)`` tensor that can
    exceed available memory, rays are processed in sub-batches whose size
    is derived from ``_FIXED_STEP_BUDGET_BYTES`` (default 512 MB).  The
    caller sees identical output regardless of chunk size.

    Parameters
    ----------
    min_corner : tuple of float
        World-space (x, y, z) of the grid's lower corner.
    scale : float
        Full spatial extent of the cubic grid in meters.
    resolution : int
        Number of voxels per axis.
    origins : (R, 3) torch.Tensor
        Ray start positions.
    ray_dirs : (R, 3) torch.Tensor
        Unit direction vectors.
    sky_patch_ids : (R,) torch.Tensor
        Sky-patch index per ray.
    voxel_size : float
        Physical edge length of one voxel (meters).
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

    # Determine chunk size: each ray needs (num_steps * 3 * 4) bytes for
    # the sample-point tensor, plus roughly the same for voxel indices.
    bytes_per_ray = num_steps * 3 * 4 * 2  # sample_pts + voxel_idxs
    budget = _FIXED_STEP_BUDGET_BYTES
    chunk_size = max(budget // max(bytes_per_ray, 1), 1)

    # Pre-compute values shared across all chunks
    distances = (
        (torch.arange(num_steps, dtype=torch.float32, device=device) + 0.5)
        * voxel_size
    )
    grid_origin = torch.tensor(min_corner, dtype=torch.float32, device=device)

    # Accumulate sparse hit results from each chunk
    all_ray_ids = []
    all_patch_ids = []
    all_voxel_indices = []

    for start in range(0, num_rays, chunk_size):
        end = min(start + chunk_size, num_rays)
        o = origins[start:end]             # (C, 3)
        d = ray_dirs[start:end]            # (C, 3)
        c = end - start

        # Materialize sample points for this chunk only
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
            # Deduplicate (ray, voxel) pairs: discrete stepping can sample
            # the same voxel more than once per ray, which would inflate
            # scores and violation counts downstream.  The DDA backend
            # visits each voxel exactly once per ray; enforce the same
            # contract here.  Duplicates only arise within a single ray,
            # and a ray is never split across chunks, so per-chunk dedup
            # is exact.  torch.unique sorts keys, making the output order
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

        # Free chunk tensors eagerly (matters on GPU)
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
    """Compute an optimal ray batch size based on available GPU memory.

    For the DDA backend, each ray needs ~4 output ints (ray_id, vx, vy, vz)
    times an estimated hits-per-ray. We size the batch so that output
    buffers fit within ``vram_fraction`` of free VRAM.

    For the legacy fixed-step backend, the dominant cost is the R x S x 3
    sample-point tensor (12 bytes per element at float32). We size the
    batch so this tensor fits within the VRAM budget.

    Falls back to ``fallback`` on CPU or if VRAM cannot be queried.

    Parameters
    ----------
    resolution : int
        Voxel grid resolution (used to estimate hits-per-ray).
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
        # DDA: output = 4 int arrays x est_hits_per_ray per ray x 4 bytes
        est_hits = 20  # modest initial; kernel retries on overflow
        bytes_per_ray = 4 * est_hits * 4  # 4 arrays, 4 bytes per int
        batch = max(budget_bytes // max(bytes_per_ray, 1), 10_000)
    else:
        # Fixed-step: R x S x 3 x 4 bytes (float32)
        num_steps = max(resolution, 50)  # rough estimate
        bytes_per_ray = num_steps * 3 * 4
        batch = max(budget_bytes // max(bytes_per_ray, 1), 10_000)

    # Cap at 5M rays (diminishing returns beyond this)
    batch = min(batch, 5_000_000)

    log.info("auto_batch_size: free=%.0f MB, budget=%.0f MB, batch=%d",
             free / 1e6, budget_bytes / 1e6, batch)
    return batch

