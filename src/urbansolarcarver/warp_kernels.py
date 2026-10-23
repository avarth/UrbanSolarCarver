"""
UrbanSolarCarver: Warp setup and kernels
========================================

Initializes NVIDIA Warp, tells whether its exact DDA backend can run on a
device (:func:`dda_backend_available`), precompiles the kernels
(:func:`warmup_kernels`), and defines every Warp kernel of the package:

* the DDA traversal (digital differential analyzer, Amanatides & Woo
  1987): one thread per ray, stepping from voxel to voxel and visiting
  every voxel the ray crosses exactly once, with fused kernels that add
  each ray's weight or a count of 1 directly into a per-voxel volume, the
  first-hit kernel of the test point access evaluation and the kernel of
  the skin rule;
* the parity voxelizer used by :func:`voxelization.voxelize_solid_warp`;
* the ground heights of a terrain mesh, used by
  :func:`context_geometry.ground_heights`.

All kernels live in this one module on purpose: Warp compiles a Python
module as one unit and caches it on disk by module, so
:func:`warmup_kernels` compiles them all at once.  The kernels exist only
when Warp imports and initializes (``_warp_available``).  Their launch
wrappers are in :mod:`ray_tracing` and :mod:`voxelization`.

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

import logging
from typing import Any

from .errors import WarpBackendUnavailableError
from .compute_device import resolve_compute_device, warp_device_name

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Warp DDA kernel (compiled lazily on first use)
# ---------------------------------------------------------------------------
_warp_available = False
# Why Warp cannot run, for the error require_dda_backend raises; None when
# Warp imported and initialised.
_warp_unavailable_reason: "str | None" = None
_warp_cpu_ok_cache: "bool | None" = None
try:
    import warp as wp
    wp.init()
    _warp_available = True
except ImportError as _warp_err:
    _warp_unavailable_reason = f"Warp is not installed ({_warp_err})"
    log.warning("%s; ray tracing will not run", _warp_unavailable_reason)
except Exception as _warp_err:
    # Installed but unusable (driver, CUDA or compiler problem).
    _warp_unavailable_reason = f"Warp failed to initialise ({_warp_err})"
    log.warning("%s; ray tracing will not run", _warp_unavailable_reason)


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
        False if Warp is unavailable or compilation failed.  When only the
        precompilation failed, the kernels compile on first use instead.
    """
    if not _warp_available:
        return False
    try:
        device = resolve_compute_device(device)
        if not dda_backend_available(device):
            return False
        import sys
        wp.load_module(module=sys.modules[__name__], device=warp_device_name(device))
        return True
    except Exception as exc:
        log.warning("Warp kernel warmup failed (%s); kernels will compile "
                    "on first use instead.", exc)
        return False


def dda_backend_available(device) -> bool:
    """True if the Warp DDA backend can run on *device*: Warp initialised
    and, for the CPU, Warp's CPU backend can compile kernels."""
    if not _warp_available:
        return False
    return device.type == "cuda" or _warp_cpu_ok()


def require_dda_backend(device) -> None:
    """Raise WarpBackendUnavailableError unless the Warp DDA backend can run
    on *device*.  Ray tracing has no other backend; the error says why
    Warp cannot run and how to repair the installation."""
    if dda_backend_available(device):
        return
    reason = _warp_unavailable_reason or "Warp's CPU backend cannot compile kernels on this machine"
    raise WarpBackendUnavailableError(
        f"Ray tracing needs NVIDIA Warp, which cannot run on device {str(device)!r}: {reason}. "
        f"Repair the environment with `python setup_env.py` (or reinstall warp-lang)."
    )

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

        A voxel the surface's plane passes through is skin (a test surface on
        a facade sits inside the boundary voxels of its own mass); see
        `_skin_without_mass_behind` for when skin still counts.  The voxel is
        entirely in front when its centre is further in front than its
        half-extent along *n*.
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

    @wp.func
    def _voxel_behind_skin(vx: int, vy: int, vz: int, grid_origin: wp.vec3,
                           cell_size: float, resolution: int,
                           o: wp.vec3, n: wp.vec3) -> int:
        """Flat index of the voxel behind skin voxel (vx, vy, vz) of the
        surface through *o* with unit normal *n*, or -1 if it is outside
        the grid.

        Steps from the skin voxel's centre one cell length at a time
        against *n* and takes the first voxel containing the stepped point
        that lies wholly behind the plane (centre at least its half-extent
        behind).  A skin voxel's centre is within one half-extent of the
        plane, so the third step always qualifies.
        """
        c = wp.vec3(
            grid_origin[0] + (float(vx) + 0.5) * cell_size,
            grid_origin[1] + (float(vy) + 0.5) * cell_size,
            grid_origin[2] + (float(vz) + 0.5) * cell_size,
        )
        half_extent = 0.5 * cell_size * (wp.abs(n[0]) + wp.abs(n[1]) + wp.abs(n[2]))
        bx = int(0)
        by = int(0)
        bz = int(0)
        for k in range(1, 4):
            q = c - n * (float(k) * cell_size)
            bx = int(wp.floor((q[0] - grid_origin[0]) / cell_size))
            by = int(wp.floor((q[1] - grid_origin[1]) / cell_size))
            bz = int(wp.floor((q[2] - grid_origin[2]) / cell_size))
            bc = wp.vec3(
                grid_origin[0] + (float(bx) + 0.5) * cell_size,
                grid_origin[1] + (float(by) + 0.5) * cell_size,
                grid_origin[2] + (float(bz) + 0.5) * cell_size,
            )
            if wp.dot(n, bc - o) <= -half_extent:
                break
        if (bx < 0 or bx >= resolution or by < 0 or by >= resolution
                or bz < 0 or bz >= resolution):
            return -1
        return bx * resolution * resolution + by * resolution + bz

    @wp.func
    def _skin_without_mass_behind(s: _DDAState, grid_origin: wp.vec3, cell_size: float,
                                  resolution: int, o: wp.vec3, n: wp.vec3,
                                  skin_rule: int, occupancy: wp.array(dtype=wp.uint8)) -> int:
        """1 if the current voxel is occupied skin of the ray's source
        surface (its plane passes through the voxel) and the voxel behind it
        is outside the grid or empty, else 0.

        Such a voxel is not the surface's own mass: the building behind the
        surface is not part of the max volume, so the voxel obstructs the
        surface like any voxel in front of it.  Empty skin obstructs nothing
        and is not counted (in tilted_plane a count would also carve the
        column above it).  Always 0 when *skin_rule* is 0 (no occupancy
        grid given).
        """
        if skin_rule == 0:
            return 0
        if occupancy[s.vx * resolution * resolution + s.vy * resolution + s.vz] == wp.uint8(0):
            return 0
        c = wp.vec3(
            grid_origin[0] + (float(s.vx) + 0.5) * cell_size,
            grid_origin[1] + (float(s.vy) + 0.5) * cell_size,
            grid_origin[2] + (float(s.vz) + 0.5) * cell_size,
        )
        half_extent = 0.5 * cell_size * (wp.abs(n[0]) + wp.abs(n[1]) + wp.abs(n[2]))
        dist = wp.dot(n, c - o)
        if dist > half_extent or dist <= -half_extent:
            return 0
        b = _voxel_behind_skin(s.vx, s.vy, s.vz, grid_origin, cell_size, resolution, o, n)
        if b < 0:
            return 1
        if occupancy[b] == wp.uint8(0):
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
        skin_rule: int,                         # 1 = count skin voxels with no mass behind them
        occupancy: wp.array(dtype=wp.uint8),    # max volume occupancy [res^3] (placeholder if skin_rule == 0)
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
                    and (front_test == 0 or _in_front(s, grid_origin, cell_size, o, n) == 1
                         or _skin_without_mass_behind(s, grid_origin, cell_size, resolution,
                                                      o, n, skin_rule, occupancy) == 1)):
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
        skin_rule: int,                         # 1 = count skin voxels with no mass behind them
        occupancy: wp.array(dtype=wp.uint8),    # max volume occupancy [res^3] (placeholder if skin_rule == 0)
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
                    and (front_test == 0 or _in_front(s, grid_origin, cell_size, o, n) == 1
                         or _skin_without_mass_behind(s, grid_origin, cell_size, resolution,
                                                      o, n, skin_rule, occupancy) == 1)):
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
        skin_rule: int,                         # 1 = count skin voxels with no mass behind them
        occupancy: wp.array(dtype=wp.uint8),    # max volume occupancy [res^3] (placeholder if skin_rule == 0)
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
                    and (front_test == 0 or _in_front(s, grid_origin, cell_size, o, n) == 1
                         or _skin_without_mass_behind(s, grid_origin, cell_size, resolution,
                                                      o, n, skin_rule, occupancy) == 1)):
                flat_idx = s.vx * res_sq + s.vy * resolution + s.vz
                wp.atomic_add(counts, flat_idx, 1)
            s = _dda_step(s, resolution, max_t)

    @wp.kernel
    def _dda_first_hit_access_kernel(
        # Ray data
        ray_origins: wp.array(dtype=wp.vec3),
        ray_dirs: wp.array(dtype=wp.vec3),
        ray_patch_ids: wp.array(dtype=int),
        ray_point_ids: wp.array(dtype=int),
        point_normals: wp.array(dtype=wp.vec3),
        front_test: int,                        # 1 = skip voxels behind the source surface
        skin_rule: int,                         # 1 = count skin voxels with no mass behind them
        occupancy: wp.array(dtype=wp.uint8),    # occupancy grid to evaluate [res^3]
        skin_occupancy: wp.array(dtype=wp.uint8),  # max volume the skin rule reads [res^3]
        # Grid parameters
        grid_origin: wp.vec3,
        cell_size: float,
        resolution: int,
        max_t: float,
        # Output (modified in place via atomic_add)
        access: wp.array(dtype=wp.float64),     # [num_points] accessible, then [num_points] blocked
        num_points: int,
        patch_weights: wp.array(dtype=float),   # weight per patch [num_patches]
        use_point_weights: int,                 # 1 = multiply by point_weights (edge_taper)
        point_weights: wp.array(dtype=float),   # weight per sample point (placeholder otherwise)
    ):
        """Trace one ray per thread until the first occupied voxel it visits
        and add its weight to its point's blocked weight, or, when it visits
        none, to its point's accessible weight.

        Voxels count under the same front-face and skin rules as in the
        scoring kernels, so a point's own skin does not block it.  The skin
        rule reads *skin_occupancy*, the max volume, as scoring does: on a
        carved grid, a facade voxel kept in front of carved mass is still
        the point's own wall, not an obstruction.  The sums
        are float64: a point's total is hundreds of rays, and float32 atomic
        sums in varying order would differ by more than small carves change it.
        """
        tid = wp.tid()
        pt = ray_point_ids[tid]
        w = patch_weights[ray_patch_ids[tid]]
        if use_point_weights == 1:
            w = w * point_weights[pt]
        o = ray_origins[tid]
        n = wp.vec3(0.0, 0.0, 0.0)
        if front_test == 1:  # the normals array is a 1-element placeholder otherwise
            n = point_normals[pt]
        res_sq = resolution * resolution
        s = _dda_init(o, ray_dirs[tid], grid_origin, cell_size, resolution, max_t)
        max_steps = 3 * resolution
        for _step in range(max_steps):
            if s.active == 0:
                break
            if occupancy[s.vx * res_sq + s.vy * resolution + s.vz] != wp.uint8(0):
                if (front_test == 0 or _in_front(s, grid_origin, cell_size, o, n) == 1
                        or _skin_without_mass_behind(s, grid_origin, cell_size, resolution,
                                                     o, n, skin_rule, skin_occupancy) == 1):
                    wp.atomic_add(access, num_points + pt, wp.float64(w))
                    return
            s = _dda_step(s, resolution, max_t)
        wp.atomic_add(access, pt, wp.float64(w))

    @wp.kernel
    def _skin_follows_mass_behind_kernel(
        # Ray data
        ray_origins: wp.array(dtype=wp.vec3),
        ray_dirs: wp.array(dtype=wp.vec3),
        ray_point_ids: wp.array(dtype=int),
        point_normals: wp.array(dtype=wp.vec3),
        # Grid parameters
        grid_origin: wp.vec3,
        cell_size: float,
        resolution: int,
        max_t: float,
        occupancy: wp.array(dtype=wp.uint8),   # max volume occupancy [res^3]
        values_in: wp.array(dtype=Any),        # finished counts or scores [res^3], read only
        values_out: wp.array(dtype=Any),       # starts as a copy of values_in; raised in place
    ):
        """Raise each own-skin voxel a ray visits to the value of the voxel
        behind it.

        An occupied skin voxel (the source surface's plane passes through
        it) whose voxel behind is occupied is the surface's own mass and is not
        counted by the surface's rays; it should go when that mass goes.
        Taking the maximum of its value and the value behind it does that
        for counts (removed when non-zero) and for scores (removed when
        above the threshold).

        The point at parameter t lies t * (n . d) in front of the plane, and
        a voxel can be skin only if one of its points lies within twice its
        half-extent of it.  Voxel centre distances along a ray are not
        monotone (an oblique ray can step back toward the plane), so the
        walk stops only once the current voxel's exit parameter puts every
        later voxel beyond that bound.
        """
        tid = wp.tid()
        o = ray_origins[tid]
        d = ray_dirs[tid]
        n = point_normals[ray_point_ids[tid]]
        res_sq = resolution * resolution
        half_extent = 0.5 * cell_size * (wp.abs(n[0]) + wp.abs(n[1]) + wp.abs(n[2]))
        rise_per_t = wp.dot(n, d)
        s = _dda_init(o, d, grid_origin, cell_size, resolution, max_t)
        max_steps = 3 * resolution
        for _step in range(max_steps):
            if s.active == 0:
                return
            c = wp.vec3(
                grid_origin[0] + (float(s.vx) + 0.5) * cell_size,
                grid_origin[1] + (float(s.vy) + 0.5) * cell_size,
                grid_origin[2] + (float(s.vz) + 0.5) * cell_size,
            )
            dist = wp.dot(n, c - o)
            if dist > half_extent:
                t_exit = wp.min(s.t_max_x, wp.min(s.t_max_y, s.t_max_z))
                if t_exit * rise_per_t > 2.0 * half_extent + 1.0e-4 * cell_size:
                    return
            elif dist > -half_extent:
                flat = s.vx * res_sq + s.vy * resolution + s.vz
                if occupancy[flat] != wp.uint8(0):
                    b = _voxel_behind_skin(s.vx, s.vy, s.vz, grid_origin, cell_size,
                                           resolution, o, n)
                    if b >= 0:
                        if occupancy[b] != wp.uint8(0):
                            wp.atomic_max(values_out, flat, values_in[b])
            s = _dda_step(s, resolution, max_t)

    for _dtype in (wp.int32, wp.float32):
        wp.overload(_skin_follows_mass_behind_kernel,
                    {"values_in": wp.array(dtype=_dtype), "values_out": wp.array(dtype=_dtype)})

    @wp.kernel
    def _parity_voxelize_kernel(
        mesh_id: wp.uint64,
        axis: int,                       # marching axis: 0 (x), 1 (y), or 2 (z)
        grid_origin: wp.vec3,
        cell_size: float,
        resolution: int,
        start_before: wp.vec3,           # extra distance before the grid where the rays start, per axis (>= 0)
        end_after: wp.vec3,              # extra distance after the grid where the rays end, per axis (>= 0)
        votes: wp.array(dtype=wp.int32),    # +1 per axis whose parity sees the voxel inside
        surface: wp.array(dtype=wp.int32),  # 1 where a ray/mesh hit falls in the voxel
    ):
        """Solid voxelization by parity ray casting, one thread per grid
        column along *axis*.

        The ray starts one cell (plus *start_before*) before the grid on the
        marching axis and runs to one cell (plus *end_after*) beyond it, so a
        mesh reaching beyond the grid keeps a correct parity inside it; it
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
            ro = wp.vec3(grid_origin[0] - cell_size - start_before[0], grid_origin[1] + ci, grid_origin[2] + cj)
            rd = wp.vec3(1.0, 0.0, 0.0)
            base = i * resolution + j
            stride = res_sq
        elif axis == 1:
            ro = wp.vec3(grid_origin[0] + cj, grid_origin[1] - cell_size - start_before[1], grid_origin[2] + ci)
            rd = wp.vec3(0.0, 1.0, 0.0)
            base = j * res_sq + i
            stride = resolution
        else:
            ro = wp.vec3(grid_origin[0] + ci, grid_origin[1] + cj, grid_origin[2] - cell_size - start_before[2])
            rd = wp.vec3(0.0, 0.0, 1.0)
            base = i * res_sq + j * resolution
            stride = 1

        span = (float(resolution) + 2.0) * cell_size + start_before[axis] + end_after[axis]
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

    @wp.kernel
    def _ground_height_kernel(
        mesh_id: wp.uint64,
        grid_origin: wp.vec3,
        cell_size: float,
        resolution: int,
        start_z: float,                       # above the terrain's top
        max_t: float,                         # how far down the rays run
        heights: wp.array(dtype=wp.float32),  # out: ground z per column (x * res + y), NaN where none
    ):
        """Ground height per grid column: one downward ray along the column's
        vertical centre line from above the terrain; its first hit is the
        highest crossing of the terrain with that line."""
        tid = wp.tid()
        i = tid // resolution
        j = tid % resolution
        ro = wp.vec3(grid_origin[0] + (float(i) + 0.5) * cell_size,
                     grid_origin[1] + (float(j) + 0.5) * cell_size, start_z)
        q = wp.mesh_query_ray(mesh_id, ro, wp.vec3(0.0, 0.0, -1.0), max_t)
        if q.result:
            heights[tid] = start_z - q.t
        else:
            heights[tid] = wp.nan
