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
  the skin rule; in the sky-patch modes a thread can trace one of several
  jittered sub-rays of a sky patch, whose direction it computes itself
  (see the note above ``_lowbias32``);
* the parity voxelizer used by :func:`voxelization.voxelize_solid_warp`;
* the ground heights of a terrain mesh and the voxel centres on the context's
  surface, used by :mod:`context_geometry`, and the any-hit test of rays
  against the context and terrain meshes (:func:`ray_tracing.mesh_blocks_rays`);
* the mesh visibility kernel of the sun and sky check (:mod:`solar_check`),
  which traces rays against a triangle mesh's BVH (``wp.Mesh``) instead of
  the voxel grid.

All kernels live in this one module on purpose: Warp compiles a Python
module as one unit and caches it on disk by module, so
:func:`warmup_kernels` compiles them all at once.  The kernels exist only
when Warp imports and initializes (``_warp_available``).  Their launch
wrappers are in :mod:`ray_tracing`, :mod:`voxelization` and
:mod:`solar_check`.

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

    # ===================================================================
    # Sky sub-rays
    # With sub_side > 0, each (sample point, sky patch) ray of the sky-patch
    # modes stands for sub = sub_side**2 sub-rays, one thread each: of a
    # launch over n rays, thread tid traces sub-ray k = tid // n of ray
    # r = tid % n, toward a place in cell k of the patch drawn from a hash of
    # the point, the patch and k.  The rays are ordered by patch, so the
    # threads of a warp trace one cell of one patch from neighbouring points
    # and visit nearby voxels, which keeps the voxel arrays in the cache.  A
    # per-sub-ray skip mask is laid out ray by ray (entry r * sub + k).  The
    # weight of the patch is shared equally between its sub-rays, and a
    # sub-ray the surface does not face is skipped.  With sub_side 0 a
    # thread traces the ray's own direction, as the sun and plane rays do.
    # sky_patches.sub_ray_directions is the NumPy reference of the
    # directions; the hash constants are its SUB_RAY_SEED, _HASH_M1, _HASH_M2.
    # ===================================================================

    _SUB_RAY_SEED = wp.constant(wp.uint32(0x5EED1234))
    _HASH_M1 = wp.constant(wp.uint32(0x7FEB352D))
    _HASH_M2 = wp.constant(wp.uint32(0x846CA68B))

    @wp.func
    def _lowbias32(x: wp.uint32) -> wp.uint32:
        """The lowbias32 integer hash (C. Wellons)."""
        x = x ^ (x >> wp.uint32(16))
        x = x * _HASH_M1
        x = x ^ (x >> wp.uint32(15))
        x = x * _HASH_M2
        x = x ^ (x >> wp.uint32(16))
        return x

    @wp.func
    def _sub_ray_count(sub_side: int) -> int:
        """Threads per ray: sub_side**2, or 1 when rays are traced as given."""
        if sub_side > 0:
            return sub_side * sub_side
        return 1

    @wp.func
    def _sky_sub_ray_direction(cell: wp.vec4, sub_side: int, point_id: int,
                               patch_id: int, k: int) -> wp.vec3:
        """Direction of sub-ray *k* of the ray from sample point *point_id*
        toward patch *patch_id*, whose extent *cell* is (sin_alt_low,
        sin_alt_high, az_low, az_high) as in sky_patches.tregenza_patch_cells.
        """
        h = _lowbias32(wp.uint32(point_id) ^ _SUB_RAY_SEED)
        h = _lowbias32(h ^ wp.uint32(patch_id * 256 + k))
        u = float(h >> wp.uint32(8)) * (1.0 / 16777216.0)
        h = _lowbias32(h)
        v = float(h >> wp.uint32(8)) * (1.0 / 16777216.0)
        row = k // sub_side
        col = k - row * sub_side
        sin_alt = cell[0] + (float(row) + u) / float(sub_side) * (cell[1] - cell[0])
        az = cell[2] + (float(col) + v) / float(sub_side) * (cell[3] - cell[2])
        cos_alt = wp.sqrt(wp.max(1.0 - sin_alt * sin_alt, 0.0))
        return wp.vec3(cos_alt * wp.sin(az), cos_alt * wp.cos(az), sin_alt)

    @wp.func
    def _traced_direction(ray_dirs: wp.array(dtype=wp.vec3), r: int, sub_side: int,
                          patch_cells: wp.array(dtype=wp.vec4), point_id: int,
                          patch_id: int, k: int) -> wp.vec3:
        """The direction a thread traces: ray *r*'s own, or its sub-ray *k*."""
        if sub_side > 0:
            return _sky_sub_ray_direction(patch_cells[patch_id], sub_side, point_id, patch_id, k)
        return ray_dirs[r]

    @wp.kernel
    def _sky_sub_ray_directions_kernel(
        ray_point_ids: wp.array(dtype=int),
        ray_patch_ids: wp.array(dtype=int),
        sub_side: int,
        patch_cells: wp.array(dtype=wp.vec4),
        directions: wp.array(dtype=wp.vec3),   # out: [num_rays * sub_side**2]
    ):
        """The sub-ray directions the kernels trace, one thread per sub-ray
        (for callers that want the rays themselves, and for tests)."""
        tid = wp.tid()
        sub = sub_side * sub_side
        r = tid // sub
        pid = ray_patch_ids[r]
        directions[tid] = _sky_sub_ray_direction(patch_cells[pid], sub_side, ray_point_ids[r],
                                                 pid, tid - r * sub)

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
        # Sky sub-rays (see the note above _lowbias32)
        sub_side: int,                          # sub-rays per ray = sub_side**2; 0 = trace ray_dirs
        patch_cells: wp.array(dtype=wp.vec4),   # extent of each patch (placeholder if sub_side == 0)
        use_skip: int,                          # 1 = skip the threads whose skip entry is nonzero
        skip: wp.array(dtype=wp.uint8),         # per thread: blocked by context or facing away
        # Grid parameters
        grid_origin: wp.vec3,
        cell_size: float,
        resolution: int,
        max_t: float,
        # Scoring arrays (modified in place via atomic_add)
        scores: wp.array(dtype=float),         # flat score volume [res^3]
        patch_weights: wp.array(dtype=float),   # weight per patch [num_patches]
    ):
        """Trace one ray (or sky sub-ray) per thread and add its share of its
        sky patch weight to every voxel it visits.

        The DDA visits each voxel at most once per ray, so a voxel's score
        is the sum of the weights of the rays that cross it.  See the note
        above _DDAState on atomic_add with the CPU backend.
        """
        tid = wp.tid()
        sub = _sub_ray_count(sub_side)
        # Sub-ray k of ray r: the threads of a warp trace the same cell of a patch from
        # neighbouring points (rays are ordered by patch), so they visit nearby voxels.
        k = tid // ray_origins.shape[0]
        r = tid - k * ray_origins.shape[0]
        if use_skip == 1:
            if skip[r * sub + k] != wp.uint8(0):
                return
        pid = ray_patch_ids[r]
        pt = ray_point_ids[r]
        w = patch_weights[pid] / float(sub)
        o = ray_origins[r]
        n = wp.vec3(0.0, 0.0, 0.0)
        if front_test == 1:  # the normals array is a 1-element placeholder otherwise
            n = point_normals[pt]
        d = _traced_direction(ray_dirs, r, sub_side, patch_cells, pt, pid, k)
        if sub_side > 0 and wp.dot(n, d) <= 0.0:
            return  # the surface does not face this part of the patch
        res_sq = resolution * resolution
        s = _dda_init(o, d, grid_origin,
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
        # Sky sub-rays, as in _dda_fused_score_kernel
        sub_side: int,
        patch_cells: wp.array(dtype=wp.vec4),
        use_skip: int,
        skip: wp.array(dtype=wp.uint8),
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
        sub = _sub_ray_count(sub_side)
        # Sub-ray k of ray r: the threads of a warp trace the same cell of a patch from
        # neighbouring points (rays are ordered by patch), so they visit nearby voxels.
        k = tid // ray_origins.shape[0]
        r = tid - k * ray_origins.shape[0]
        if use_skip == 1:
            if skip[r * sub + k] != wp.uint8(0):
                return
        pt = ray_point_ids[r]
        pid = ray_patch_ids[r]
        w = patch_weights[pid] * point_weights[pt] / float(sub)
        o = ray_origins[r]
        n = wp.vec3(0.0, 0.0, 0.0)
        if front_test == 1:  # the normals array is a 1-element placeholder otherwise
            n = point_normals[pt]
        d = _traced_direction(ray_dirs, r, sub_side, patch_cells, pt, pid, k)
        if sub_side > 0 and wp.dot(n, d) <= 0.0:
            return
        res_sq = resolution * resolution
        s = _dda_init(o, d, grid_origin,
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
        # Sky sub-rays, as in _dda_fused_score_kernel (no skip mask)
        sub_side: int,
        patch_cells: wp.array(dtype=wp.vec4),
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
        """Trace one ray (or sky sub-ray) per thread until the first occupied
        voxel it visits and add its weight to its point's blocked weight, or,
        when it visits none, to its point's accessible weight.

        Voxels count under the same front-face and skin rules as in the
        scoring kernels, so a point's own skin does not block it.  The skin
        rule reads *skin_occupancy*, the max volume, as scoring does: on a
        carved grid, a facade voxel kept in front of carved mass is still
        the point's own wall, not an obstruction.  The sums
        are float64: a point's total is hundreds of rays, and float32 atomic
        sums in varying order would differ by more than small carves change it.
        """
        tid = wp.tid()
        sub = _sub_ray_count(sub_side)
        # Sub-ray k of ray r: the threads of a warp trace the same cell of a patch from
        # neighbouring points (rays are ordered by patch), so they visit nearby voxels.
        k = tid // ray_origins.shape[0]
        r = tid - k * ray_origins.shape[0]
        pt = ray_point_ids[r]
        pid = ray_patch_ids[r]
        w = patch_weights[pid] / float(sub)
        if use_point_weights == 1:
            w = w * point_weights[pt]
        o = ray_origins[r]
        n = wp.vec3(0.0, 0.0, 0.0)
        if front_test == 1:  # the normals array is a 1-element placeholder otherwise
            n = point_normals[pt]
        d = _traced_direction(ray_dirs, r, sub_side, patch_cells, pt, pid, k)
        if sub_side > 0 and wp.dot(n, d) <= 0.0:
            return  # not a ray of this point: it neither reaches the sky nor is blocked
        res_sq = resolution * resolution
        s = _dda_init(o, d, grid_origin, cell_size, resolution, max_t)
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
        # Sky sub-rays, as in _dda_fused_score_kernel
        ray_patch_ids: wp.array(dtype=int),    # patch per ray (placeholder if sub_side == 0)
        sub_side: int,
        patch_cells: wp.array(dtype=wp.vec4),
        use_skip: int,
        skip: wp.array(dtype=wp.uint8),
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
        sub = _sub_ray_count(sub_side)
        # Sub-ray k of ray r: the threads of a warp trace the same cell of a patch from
        # neighbouring points (rays are ordered by patch), so they visit nearby voxels.
        k = tid // ray_origins.shape[0]
        r = tid - k * ray_origins.shape[0]
        if use_skip == 1:
            if skip[r * sub + k] != wp.uint8(0):
                return
        o = ray_origins[r]
        pt = ray_point_ids[r]
        n = point_normals[pt]
        pid = int(0)
        if sub_side > 0:  # the patch ids are a 1-element placeholder otherwise
            pid = ray_patch_ids[r]
        d = _traced_direction(ray_dirs, r, sub_side, patch_cells, pt, pid, k)
        if sub_side > 0 and wp.dot(n, d) <= 0.0:
            return
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

    @wp.func
    def _mesh_blocks_ray(mesh_id: wp.uint64, o: wp.vec3, d: wp.vec3,
                         min_hit: float, max_t: float) -> wp.uint8:
        """1 if the ray from *o* along *d* hits the mesh between *min_hit*
        and *max_t*, else 0.  Hits closer than *min_hit* are skipped by
        querying again from just beyond them."""
        t_off = float(0.0)
        for _skip in range(16):
            if t_off >= max_t:
                break
            q = wp.mesh_query_ray(mesh_id, o + d * t_off, d, max_t - t_off)
            if not q.result:
                break
            t_hit = t_off + q.t
            if t_hit >= min_hit:
                return wp.uint8(1)
            t_off = t_hit + wp.max(1.0e-5, t_hit * 1.0e-6)
        return wp.uint8(0)

    @wp.kernel
    def _mesh_any_hit_kernel(
        mesh_id: wp.uint64,                       # BVH of the context and terrain
        origins: wp.array(dtype=wp.vec3),         # (R,) ray origins (the test points)
        directions: wp.array(dtype=wp.vec3),      # (R,) unit ray directions
        point_ids: wp.array(dtype=int),           # (R,) test point of each ray
        normals: wp.array(dtype=wp.vec3),         # (P,) outward unit normal of each test point
        origin_offset: float,                     # origin moved this far along the normal (m)
        min_hit: float,                           # hits closer than this to the origin are ignored (m)
        max_t: float,                             # ray length (m)
        blocked: wp.array(dtype=wp.uint8),        # out: 1 where the ray hits the mesh
    ):
        """Whether each ray hits the mesh within *max_t*, one thread per ray.

        The ray starts *origin_offset* off its test surface along the
        surface normal, and hits closer than *min_hit* are ignored, so a
        test surface lying on a context face is not blocked by that face.
        """
        i = wp.tid()
        o = origins[i] + normals[point_ids[i]] * origin_offset
        blocked[i] = _mesh_blocks_ray(mesh_id, o, directions[i], min_hit, max_t)

    @wp.kernel
    def _mesh_any_hit_sky_kernel(
        mesh_id: wp.uint64,                       # BVH of the context and terrain
        origins: wp.array(dtype=wp.vec3),         # (R,) ray origins (the test points)
        patch_ids: wp.array(dtype=int),           # (R,) sky patch of each ray
        point_ids: wp.array(dtype=int),           # (R,) test point of each ray
        normals: wp.array(dtype=wp.vec3),         # (P,) outward unit normal of each test point
        sub_side: int,                            # sub-rays per ray = sub_side**2 (> 0)
        patch_cells: wp.array(dtype=wp.vec4),     # extent of each patch
        patch_weights: wp.array(dtype=float),     # weight per patch
        use_point_weights: int,                   # 1 = multiply by point_weights (edge_taper)
        point_weights: wp.array(dtype=float),     # weight per test point (placeholder otherwise)
        origin_offset: float,
        min_hit: float,
        max_t: float,
        status: wp.array(dtype=wp.uint8),         # out per sub-ray: 0 free, 1 blocked, 2 faces away
        rays_of_point: wp.array(dtype=wp.int32),          # (P,) sub-rays the point faces
        blocked_of_point: wp.array(dtype=wp.int32),       # (P,) of them blocked
        weight_of_point: wp.array(dtype=wp.float64),      # (P,) their weight
        blocked_weight_of_point: wp.array(dtype=wp.float64),  # (P,) weight of the blocked ones
    ):
        """_mesh_any_hit_kernel for the sky sub-rays, one thread per sub-ray
        (see the note above _lowbias32), adding up per test point what the
        mesh blocks."""
        tid = wp.tid()
        sub = sub_side * sub_side
        k = tid // origins.shape[0]   # sub-ray k of ray r, as in _dda_fused_score_kernel
        r = tid - k * origins.shape[0]
        pt = point_ids[r]
        pid = patch_ids[r]
        n = normals[pt]
        d = _sky_sub_ray_direction(patch_cells[pid], sub_side, pt, pid, k)
        if wp.dot(n, d) <= 0.0:
            status[r * sub + k] = wp.uint8(2)
            return
        w = patch_weights[pid] / float(sub)
        if use_point_weights == 1:
            w = w * point_weights[pt]
        hit = _mesh_blocks_ray(mesh_id, origins[r] + n * origin_offset, d, min_hit, max_t)
        status[r * sub + k] = hit
        wp.atomic_add(rays_of_point, pt, 1)
        wp.atomic_add(weight_of_point, pt, wp.float64(w))
        if hit == wp.uint8(1):
            wp.atomic_add(blocked_of_point, pt, 1)
            wp.atomic_add(blocked_weight_of_point, pt, wp.float64(w))

    @wp.kernel
    def _near_mesh_kernel(
        mesh_id: wp.uint64,
        points: wp.array(dtype=wp.vec3),     # (N,) query points
        max_distance: float,
        near: wp.array(dtype=wp.uint8),      # out: 1 where the mesh lies within max_distance of the point
    ):
        """Whether the mesh surface passes within *max_distance* of each point."""
        i = wp.tid()
        q = wp.mesh_query_point_no_sign(mesh_id, points[i], max_distance)
        if q.result:
            near[i] = wp.uint8(1)
        else:
            near[i] = wp.uint8(0)

    # ===================================================================
    # Sun and sky check: visible weight per test point past a mesh
    # ===================================================================
    # A tolerated start inside a solid must leave it within this many
    # surface tolerances along the ray: a low ray from a point under a
    # voxel overhang that runs through the whole building is blocked.  A
    # facade inside a skin of depth delta then loses the rays with
    # cos(incidence) < delta / (10 * tolerance), at most about 1 % of its
    # cosine-weighted sky.
    CHECK_START_REACH = wp.constant(10.0)

    @wp.func
    def _check_next_event(mesh_id: wp.uint64, o: wp.vec3, d: wp.vec3, t_from: float, max_t: float):
        """The next face a ray from *o* along *d* crosses beyond *t_from*:
        its distance and 1.0 when the ray leaves the solid there (the back
        of the face) or 0.0 when it enters; distance -1 when none."""
        if t_from < max_t:
            q = wp.mesh_query_ray(mesh_id, o + d * t_from, d, max_t - t_from)
            if q.result:
                leaving = float(0.0)
                if wp.dot(q.normal, d) > 0.0:
                    leaving = 1.0
                return wp.vec2(t_from + q.t, leaving)
        return wp.vec2(-1.0, 0.0)

    @wp.func
    def _check_step(t: float, min_hit: float):
        """A distance just past *t*: the advance grows with *t*, as in the
        voxelizer, so it stays above float32 rounding far from the origin."""
        return t + wp.max(min_hit, t * 1.0e-6)

    @wp.func
    def _check_near_surface(mesh_id: wp.uint64, o: wp.vec3, n: wp.vec3, tolerance: float):
        """1 when *o* lies within *tolerance* of the mesh's surface, at a
        face that faces the same side as the test normal *n*: the test
        surface then runs along the mesh's surface (a facade in the skin of
        its envelope), rather than looking into the solid (ground under a
        building)."""
        q = wp.mesh_query_point_no_sign(mesh_id, o, tolerance)
        near = int(0)
        if q.result:
            if (wp.length(wp.mesh_eval_position(mesh_id, q.face, q.u, q.v) - o) <= tolerance
                    and wp.dot(wp.mesh_eval_face_normal(mesh_id, q.face), n) > 0.0):
                near = 1
        return near

    @wp.func
    def _check_start(mesh_id: wp.uint64, o: wp.vec3, d: wp.vec3, c: float, max_t: float,
                     min_hit: float, tolerance: float, near_surface: int):
        """Whether a ray starts inside the solid of a mesh, and the next
        event after the start: (inside, distance, leaving).

        Crossings within *min_hit* of the origin are ignored.  A start
        inside counts as outside when the origin is within *tolerance* of
        the mesh's surface at a face turned the test surface's way
        (*near_surface*, :func:`_check_near_surface`) and the ray leaves the solid at
        a height above the test surface's plane (``t * c``) of at most
        *tolerance*, within ``CHECK_START_REACH * tolerance`` along the
        ray: the test point is then in the skin of a mesh that lies a
        little outside its test surface, and that exit is consumed.  A
        point deeper inside is blocked."""
        e = _check_next_event(mesh_id, o, d, 0.0, max_t)
        for _skip in range(8):
            if e[0] < 0.0 or e[0] > min_hit:
                break
            e = _check_next_event(mesh_id, o, d, _check_step(e[0], min_hit), max_t)
        inside = int(0)
        if e[0] >= 0.0 and e[1] > 0.5:
            if near_surface == 1 and e[0] * c <= tolerance and e[0] <= CHECK_START_REACH * tolerance:
                e = _check_next_event(mesh_id, o, d, _check_step(e[0], min_hit), max_t)
            else:
                inside = 1      # the exit stays the next event
        return wp.vec3(float(inside), e[0], e[1])

    @wp.func
    def _check_solid_blocks(mesh_id: wp.uint64, o: wp.vec3, d: wp.vec3, c: float, max_t: float,
                            min_hit: float, tolerance: float, near_surface: int):
        """1 when a solid blocks the ray on its own: the ray starts inside it
        (:func:`_check_start`) or crosses a face of it later."""
        s = _check_start(mesh_id, o, d, c, max_t, min_hit, tolerance, near_surface)
        blocks = int(0)
        if s[0] > 0.5 or s[1] >= 0.0:
            blocks = 1
        return blocks

    @wp.kernel
    def mesh_visible_weight_kernel(
        mesh_id: wp.uint64,                  # BVH of the mesh that blocks
        has_mesh: int,                       # 0: no mesh
        mesh_tolerance: float,               # the mesh's surface tolerance (m), see _check_start
        clip_id: wp.uint64,                  # BVH of a solid the blocking mesh counts inside of only
        has_clip: int,                       # 0: no clip solid
        clip_tolerance: float,
        surroundings_id: wp.uint64,          # BVH of surroundings that block on their own (neighbours, terrain)
        has_surroundings: int,               # 0: none
        surroundings_tolerance: float,
        points: wp.array(dtype=wp.vec3),     # (P,) test points
        normals: wp.array(dtype=wp.vec3),    # (P,) outward unit normals
        directions: wp.array(dtype=wp.vec3),  # (D,) unit vectors toward the sun or sky
        values: wp.array(dtype=float),       # (D,) value each direction carries
        use_cosine: int,                     # 1: a direction counts value * cos(incidence)
        d_start: int,                        # this launch's directions: [d_start, d_end)
        d_end: int,
        origin_offset: float,                # origin moved this far along the normal (m)
        min_hit: float,                      # crossings closer than this to the origin are ignored (m)
        max_t: float,                        # ray length (m)
        out: wp.array(dtype=wp.float64),     # (P,) visible weight, accumulated across launches
    ):
        """Add the value of every direction in [d_start, d_end) that a test
        point faces and sees past the mesh and the surroundings.

        One thread per test point.  A ray is blocked where it is inside the
        mesh's solid and, with a clip solid, inside the clip solid too: the
        blocking mesh then counts only where it overlaps the clip (a carved
        envelope that bulges past the maximum volume blocks nothing outside
        it).  The surroundings block wherever the ray meets them.  Inside
        and outside follow the faces' orientation (closed meshes with
        outward normals); a start inside is judged by :func:`_check_start`,
        with each mesh's own tolerance.
        """
        i = wp.tid()
        n = normals[i]
        o = points[i] + n * origin_offset
        near_mesh = int(0)
        near_clip = int(0)
        near_surroundings = int(0)
        if has_mesh != 0:
            near_mesh = _check_near_surface(mesh_id, o, n, mesh_tolerance)
        if has_clip != 0:
            near_clip = _check_near_surface(clip_id, o, n, clip_tolerance)
        if has_surroundings != 0:
            near_surroundings = _check_near_surface(surroundings_id, o, n, surroundings_tolerance)
        acc = wp.float64(0.0)
        for k in range(d_start, d_end):
            d = directions[k]
            c = wp.dot(n, d)
            if c <= 0.0:
                continue
            visible = int(1)
            if has_mesh != 0:
                sm = _check_start(mesh_id, o, d, c, max_t, min_hit, mesh_tolerance, near_mesh)
                in_mesh = int(sm[0])
                em = wp.vec2(sm[1], sm[2])
                # The clip solid is read only once the ray is inside the
                # mesh: a ray that never enters it costs no clip queries.
                clip_ready = 1 - has_clip
                in_clip = int(1)
                ec = wp.vec2(-1.0, 0.0)
                t_now = float(0.0)
                refresh_mesh = int(0)
                refresh_clip = int(0)
                for _event in range(128):
                    if in_mesh == 1 and clip_ready == 0:
                        sc = _check_start(clip_id, o, d, c, max_t, min_hit, clip_tolerance, near_clip)
                        in_clip = int(sc[0])
                        ec = wp.vec2(sc[1], sc[2])
                        clip_ready = 1
                        for _catch_up in range(64):     # the clip's crossings up to here
                            if ec[0] < 0.0 or ec[0] > t_now:
                                break
                            in_clip = 1 - int(ec[1])
                            ec = _check_next_event(clip_id, o, d, _check_step(ec[0], min_hit), max_t)
                    if in_mesh == 1 and in_clip == 1:
                        visible = 0
                        break
                    if refresh_mesh == 1:
                        em = _check_next_event(mesh_id, o, d, _check_step(em[0], min_hit), max_t)
                        refresh_mesh = 0
                    if refresh_clip == 1:
                        ec = _check_next_event(clip_id, o, d, _check_step(ec[0], min_hit), max_t)
                        refresh_clip = 0
                    # Take the nearer of the next crossings; none left: visible.
                    clip_next = clip_ready == 1 and has_clip != 0 and ec[0] >= 0.0
                    if em[0] >= 0.0 and (not clip_next or em[0] <= ec[0]):
                        t_now = em[0]
                        in_mesh = 1 - int(em[1])
                        refresh_mesh = 1
                    elif clip_next:
                        t_now = ec[0]
                        in_clip = 1 - int(ec[1])
                        refresh_clip = 1
                    else:
                        break
            if visible == 1 and has_surroundings != 0:
                if _check_solid_blocks(surroundings_id, o, d, c, max_t, min_hit, surroundings_tolerance,
                                       near_surroundings) == 1:
                    visible = 0
            if visible == 1:
                w = values[k]
                if use_cosine != 0:
                    w = w * c
                acc = acc + wp.float64(w)
        out[i] = out[i] + acc
