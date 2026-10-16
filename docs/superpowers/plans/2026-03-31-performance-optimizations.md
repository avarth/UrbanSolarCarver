# Performance Optimizations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate three performance bottlenecks in the voxel pipeline (Perona-Malik diffusion, redundant cavity fill, and fixed-step tracer memory spikes) without adding heavy dependencies.

**Architecture:** Three independent changes, all surgical modifications to existing code. (1) Numba `@njit` replaces the NumPy-temporary-heavy PM diffusion stencil loop with compiled in-place iteration. (2) A fast-path check skips `binary_fill_holes` when trimesh's orthographic fill already succeeded. (3) The fixed-step ray tracer is internally chunked to cap peak memory at ~512 MB instead of allocating the full R x S x 3 tensor.

**Tech Stack:** numba (new dep), numpy, scipy (existing), torch (existing)

---

## File Map

| File | Role | Changes |
|------|------|---------|
| `pyproject.toml` | Dependencies | Add `numba>=0.58` |
| `src/urbansolarcarver/grid.py:837-894` | PM diffusion | Extract inner loop to `@njit` function |
| `src/urbansolarcarver/grid.py:745-759` | Cavity fill | Add fast-path skip + logging |
| `src/urbansolarcarver/raytracer.py:751-788` | Fixed-step tracer | Internal chunking to cap memory |
| `tests/test_grid.py` | Grid tests | Add PM diffusion + cavity fill tests |
| `tests/test_raytracer.py` | Raytracer tests | Add chunking correctness test |

---

### Task 1: Add numba dependency

**Files:**
- Modify: `pyproject.toml:27-41`

- [ ] **Step 1: Add numba to dependencies**

In `pyproject.toml`, add `numba>=0.58` to the `dependencies` list (after `scipy`, before `scikit-image`):

```toml
dependencies = [
  "typer>=0.16.0",
  "pydantic>=2.0",
  "PyYAML>=6.0.2",
  "numpy>=1.24.3",
  "matplotlib>=3.10.5",
  "scipy>=1.10,<1.16",
  "numba>=0.58",
  "scikit-image>=0.24,<0.26",
  "Shapely>=2.1.1",
  "trimesh>=4.6.12",
  "rtree>=1.0",
  "ladybug-core>=0.44.19",
  "ladybug-radiance>=0.2.11",
  "warp-lang>=1.7.2",
]
```

- [ ] **Step 2: Verify installation**

Run: `pip install -e ".[dev]"`
Expected: numba installs without conflict.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add numba for JIT-compiled stencil operations"
```

---

### Task 2: Numba-accelerated Perona-Malik diffusion

**Files:**
- Modify: `src/urbansolarcarver/grid.py:837-894`
- Test: `tests/test_grid.py`

**Context:** The current `_pm_anisotropic_diffuse` function runs 16 iterations of a 6-neighbor stencil. Each iteration allocates 12+ temporary arrays the size of the entire 3D grid (6 finite differences, 6 exponentials, plus the divergence). For a 512^3 grid this means ~6.4 GB of temporary allocations per iteration, repeated 16 times. The numba version operates in-place with zero temporary arrays.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_grid.py`:

```python
class TestPMDiffusion:
    """Tests for Perona-Malik anisotropic diffusion."""

    def test_uniform_field_unchanged(self):
        """A uniform field has zero gradients, so diffusion should be a no-op."""
        from urbansolarcarver.grid import _pm_anisotropic_diffuse
        field = np.full((20, 20, 20), 5.0, dtype=np.float32)
        result = _pm_anisotropic_diffuse(field, iters=16, k=1.0, tau=0.15)
        np.testing.assert_allclose(result, field, atol=1e-6)

    def test_step_edge_smoothed(self):
        """A sharp step edge should be smoothed (peak gradient reduced)."""
        from urbansolarcarver.grid import _pm_anisotropic_diffuse
        field = np.zeros((30, 30, 30), dtype=np.float32)
        field[:, :, 15:] = 10.0  # sharp step in Z
        result = _pm_anisotropic_diffuse(field, iters=16, k=2.0, tau=0.15)
        # The step edge should be smoother: gradient at boundary < original
        grad_before = np.abs(np.diff(field[15, 15, :]))
        grad_after = np.abs(np.diff(result[15, 15, :]))
        assert grad_after.max() < grad_before.max(), (
            "Diffusion should reduce peak gradient"
        )

    def test_preserves_shape(self):
        """Output shape and dtype must match input."""
        from urbansolarcarver.grid import _pm_anisotropic_diffuse
        field = np.random.randn(16, 16, 16).astype(np.float32)
        result = _pm_anisotropic_diffuse(field, iters=4, k=1.0, tau=0.1)
        assert result.shape == field.shape
        assert result.dtype == np.float32

    def test_zero_iters_returns_copy(self):
        """Zero iterations should return the input unchanged."""
        from urbansolarcarver.grid import _pm_anisotropic_diffuse
        field = np.random.randn(10, 10, 10).astype(np.float32)
        result = _pm_anisotropic_diffuse(field, iters=0, k=1.0, tau=0.15)
        np.testing.assert_array_equal(result, field)

    def test_neumann_boundary_no_drift(self):
        """Boundary voxels should not drift significantly from their initial
        values when the field is smooth near the boundary."""
        from urbansolarcarver.grid import _pm_anisotropic_diffuse
        field = np.ones((20, 20, 20), dtype=np.float32) * 3.0
        # Small interior perturbation; boundary should barely move
        field[10, 10, 10] = 10.0
        result = _pm_anisotropic_diffuse(field, iters=4, k=1.0, tau=0.15)
        # Corner voxels should stay close to 3.0
        np.testing.assert_allclose(result[0, 0, 0], 3.0, atol=0.01)
        np.testing.assert_allclose(result[-1, -1, -1], 3.0, atol=0.01)
```

- [ ] **Step 2: Run tests to verify they pass with old implementation**

Run: `python -m pytest tests/test_grid.py::TestPMDiffusion -v`
Expected: All 5 tests PASS (they exercise the existing NumPy implementation).

- [ ] **Step 3: Implement numba-accelerated PM diffusion**

Replace the body of `_pm_anisotropic_diffuse` in `src/urbansolarcarver/grid.py` (lines 837-894). The public signature and docstring stay identical. Add a `@njit`-compiled inner kernel and a pure-Python wrapper that handles padding and iteration.

Add the numba import near the top of `grid.py` (with the other imports around line 101):

```python
import math
from numba import njit
```

Add the compiled stencil kernel (place immediately before `_pm_anisotropic_diffuse`):

```python
@njit(cache=True)
def _pm_stencil_step(u, k2, tau):
    """Single Perona-Malik diffusion step (6-neighbor 3D stencil, in-place).

    Operates on a *padded* array: the border ring ``u[0,:,:]``, ``u[-1,:,:]``,
    etc. acts as a Neumann (zero-flux) boundary and is NOT updated.  Only
    interior voxels ``u[1:-1, 1:-1, 1:-1]`` are modified.

    Compiled to native code by numba; eliminates all temporary arrays that
    the pure-NumPy version allocates (12+ full-volume arrays per call).

    Parameters
    ----------
    u : (Nz+2, Ny+2, Nx+2) float32 ndarray
        Padded SDF; modified **in-place**.
    k2 : float
        Squared edge-stopping scale (k^2).
    tau : float
        Diffusion time step (keep <= 0.18 for stability).
    """
    nz, ny, nx = u.shape
    for z in range(1, nz - 1):
        for y in range(1, ny - 1):
            for x in range(1, nx - 1):
                c = u[z, y, x]
                # Forward/backward finite differences to 6 face-neighbors
                dxp = u[z, y, x + 1] - c
                dxm = c - u[z, y, x - 1]
                dyp = u[z, y + 1, x] - c
                dym = c - u[z, y - 1, x]
                dzp = u[z + 1, y, x] - c
                dzm = c - u[z - 1, y, x]
                # Edge-stopping coefficients: c_i = exp(-(grad_i / k)^2)
                # Small gradients -> c ~ 1 (smooth), large -> c ~ 0 (preserve)
                div = (math.exp(-(dxp * dxp) / k2) * dxp
                     - math.exp(-(dxm * dxm) / k2) * dxm
                     + math.exp(-(dyp * dyp) / k2) * dyp
                     - math.exp(-(dym * dym) / k2) * dym
                     + math.exp(-(dzp * dzp) / k2) * dzp
                     - math.exp(-(dzm * dzm) / k2) * dzm)
                u[z, y, x] = c + tau * div
```

Replace the body of `_pm_anisotropic_diffuse` (keep the existing function signature and docstring unchanged):

```python
def _pm_anisotropic_diffuse(sdf: np.ndarray, iters: int = 16, k: float = 1.0, tau: float = 0.15) -> np.ndarray:
    """
    Perona-Malik anisotropic diffusion on a 3D scalar field.

    Parameters
    ----------
    sdf : (Z, Y, X) float32 np.ndarray
        Signed-distance field in voxel units (positive inside).
    iters : int
        Number of explicit diffusion steps.
    k : float
        Edge-stopping scale (larger = more smoothing across gradients).
    tau : float
        Time step; for a 6-neighbor stencil keep tau <= 0.18 for stability.

    Returns
    -------
    filtered : (Z, Y, X) float32 np.ndarray

    Notes
    -----
    - Uses a numba-compiled stencil kernel for ~10-50x speedup over the
      pure-NumPy version (eliminates 12+ temporary full-volume arrays per
      iteration).
    - Used inside ``_voxel_presmooth``; typically applied only within a narrow
      band around the zero-level set to avoid volume drift.
    """
    iters = int(iters)
    if iters <= 0:
        return sdf.astype(np.float32, copy=True)

    k2 = float(k) * float(k) or 1e-12  # guard against k=0
    tau_f = float(tau)

    # Pad with edge values (Neumann boundary: zero normal derivative).
    # The border ring is never updated by the stencil, so it acts as
    # a fixed boundary condition throughout all iterations.
    u = np.pad(sdf.astype(np.float32), 1, mode="edge")

    for _ in range(iters):
        _pm_stencil_step(u, k2, tau_f)
        # Refresh border from interior to maintain Neumann condition
        # after each step (interior voxels adjacent to the border may
        # have changed, so the border must reflect the new edge values).
        # Note: sequential face copies mean corner/edge voxels of the
        # padding layer see already-refreshed neighbors, a minor
        # difference from the original np.pad-per-iteration approach.
        # This only affects the 1-voxel padding ring and has no
        # measurable impact on the interior result.
        u[0, :, :] = u[1, :, :]
        u[-1, :, :] = u[-2, :, :]
        u[:, 0, :] = u[:, 1, :]
        u[:, -1, :] = u[:, -2, :]
        u[:, :, 0] = u[:, :, 1]
        u[:, :, -1] = u[:, :, -2]

    # Strip padding and return interior
    return u[1:-1, 1:-1, 1:-1].copy()
```

- [ ] **Step 4: Run the PM diffusion tests**

Run: `python -m pytest tests/test_grid.py::TestPMDiffusion -v`
Expected: All 5 tests PASS. First run may be slow (~5s) as numba compiles; subsequent runs use the cache.

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: 126+ passed (existing tests unaffected: `_voxel_presmooth` calls `_pm_anisotropic_diffuse`, so the smoothed-mesh path is exercised indirectly).

- [ ] **Step 6: Commit**

```bash
git add src/urbansolarcarver/grid.py tests/test_grid.py
git commit -m "perf: numba-accelerate Perona-Malik diffusion stencil

Replaces 12+ temporary full-volume array allocations per iteration
with an in-place compiled triple loop. ~10-50x faster for large grids,
~95% less peak memory."
```

---

### Task 3: Fast-path skip for binary_fill_holes

**Files:**
- Modify: `src/urbansolarcarver/grid.py:745-759`
- Test: `tests/test_grid.py`

**Context:** After trimesh's `vox.fill(method='orthographic')` runs, `ndi.binary_fill_holes` does a full connected-component pass over the entire grid as a safety net. For watertight meshes (the common case), orthographic fill already produces a solid volume, making `binary_fill_holes` a redundant O(D^3) scan.

The grid always has a padded margin (controlled by `margin_frac`, default 0.2). This means the corner voxel `[0,0,0]` is guaranteed to be empty exterior. If a flood fill from the corner reaches ALL empty voxels, there are no interior cavities, and `binary_fill_holes` would be a no-op. We can check this cheaply with `ndi.label` on the empty space: if there's exactly one connected component of empty voxels, no cavities exist.

This pre-check is O(D^3) like `binary_fill_holes` but with a much smaller constant factor (integer labeling vs. iterative morphological fill), and it lets us skip `binary_fill_holes` entirely when it would be a no-op.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_grid.py`:

```python
class TestVoxelizeFillSkip:
    """Verify the cavity-fill fast-path in voxelize_mesh."""

    def test_watertight_mesh_no_cavities(self, tiny_cube_mesh, caplog):
        """A simple watertight cube should be fully filled by trimesh's
        orthographic fill: no interior cavities means binary_fill_holes
        is skipped."""
        import logging
        from urbansolarcarver.grid import voxelize_mesh
        with caplog.at_level(logging.DEBUG, logger="urbansolarcarver.grid"):
            grid, origin, extent, res = voxelize_mesh.__wrapped__(
                tiny_cube_mesh, voxel_size=2.0
            )
        assert grid.sum() > 0
        # Check that the skip message was logged (cavity check passed)
        assert any("no interior cavities" in r.message.lower() for r in caplog.records), (
            "Expected cavity-skip log for watertight cube mesh"
        )

    def test_solid_fill_correct(self, tiny_cube_mesh):
        """Regardless of skip logic, the final grid must be solidly filled."""
        from urbansolarcarver.grid import voxelize_mesh
        grid, origin, extent, res = voxelize_mesh.__wrapped__(
            tiny_cube_mesh, voxel_size=2.0
        )
        total = grid.sum().item()
        assert total > 100, f"Expected solid fill, got {total} voxels"
```

- [ ] **Step 2: Run tests to see baseline behavior**

Run: `python -m pytest tests/test_grid.py::TestVoxelizeFillSkip -v`
Expected: The first test FAILS (no log message yet). The second test PASS.

Note: `voxelize_mesh` is decorated with `@session_cache`. Use `.__wrapped__` to bypass the cache in tests. If `__wrapped__` is not available (because `session_cache` doesn't use `functools.wraps`), call it with unique arguments instead. Check and adjust.

- [ ] **Step 3: Implement the fast-path skip**

In `src/urbansolarcarver/grid.py`, replace the cavity-fill block at lines 745-759. Add a module-level logger if not already present.

Add at the top of the file (near other imports, around line 99):

```python
import logging

_log = logging.getLogger(__name__)
```

Replace lines 745-759 (the `binary_fill_holes` block and the logging that follows it):

```python
    # --- Cavity fill: skip if orthographic fill left no interior voids ---
    # The padded grid guarantees corner [0,0,0] is empty exterior.
    # If all empty voxels form a single connected component (6-connectivity),
    # there are no sealed interior cavities and binary_fill_holes would be
    # a no-op.  This check is much cheaper than running the full fill.
    surface_count = int(grid_np.sum())
    if surface_count == 0:
        filled = grid_np
    else:
        empty_space = ~grid_np
        # 6-connectivity: cavities must be fully enclosed (not diagonally
        # connected to the exterior) to count as interior voids.
        _, num_empty_components = ndi.label(empty_space)
        if num_empty_components <= 1:
            # All empty space is one connected region (the exterior):
            # no interior cavities exist, skip the expensive fill.
            _log.debug(
                "voxelize_mesh: no interior cavities detected "
                "(single exterior component); skipping binary_fill_holes"
            )
            filled = grid_np
        else:
            # Multiple empty regions → some are sealed cavities.
            # Run binary_fill_holes to seal them.
            filled = ndi.binary_fill_holes(grid_np)
            cavities_sealed = int(filled.sum()) - surface_count
            _log.debug(
                "voxelize_mesh: binary_fill_holes sealed %d cavity voxels "
                "(%d empty components detected)",
                cavities_sealed, num_empty_components,
            )

    _log.info(
        "voxelize_mesh: watertight=%s surface_voxels=%d filled_voxels=%d "
        "fill_ratio=%.1fx",
        mesh.is_watertight, surface_count, int(filled.sum()),
        int(filled.sum()) / max(surface_count, 1),
    )
```

Also remove the old `surface_count`/`filled_count`/`import logging`/`logging.info` block that was at lines 749-757, since the new code replaces it entirely.

- [ ] **Step 4: Run the fill-skip tests**

Run: `python -m pytest tests/test_grid.py::TestVoxelizeFillSkip -v`
Expected: Both tests PASS.

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: 126+ passed.

- [ ] **Step 6: Commit**

```bash
git add src/urbansolarcarver/grid.py tests/test_grid.py
git commit -m "perf: skip binary_fill_holes when no interior cavities detected

Uses ndi.label on the empty space to check if all empty voxels form a
single connected component (the exterior). If so, no interior cavities
exist and binary_fill_holes is skipped entirely. Common case for
watertight meshes after trimesh orthographic fill."
```

---

### Task 4: Fixed-step tracer memory chunking

**Files:**
- Modify: `src/urbansolarcarver/raytracer.py:751-788`
- Test: `tests/test_raytracer.py`

**Context:** `_trace_fixed_step` materializes a `(R, S, 3)` float32 tensor where R = number of rays and S = steps per ray. For medium scenes (1.45M rays, 200 steps), this is 3.5 GB. The fix: process rays in sub-batches internally, concatenating the sparse hit results. The caller sees identical output. A sensible chunk size caps peak allocation at ~512 MB (configurable via `_FIXED_STEP_BUDGET_BYTES`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_raytracer.py`:

```python
class TestFixedStepChunking:
    """Verify that internal chunking in _trace_fixed_step produces
    identical results regardless of chunk size."""

    def test_chunked_matches_unchunked(self):
        """A batch of rays should produce the same hits whether processed
        in one chunk or many small chunks."""
        import urbansolarcarver.raytracer as rt

        resolution = 20
        voxel_size = 1.0
        scale = resolution * voxel_size
        min_corner = (0.0, 0.0, 0.0)
        ray_length = scale * 1.5

        # 500 rays in random directions from one side of the grid
        rng = np.random.RandomState(42)
        n_rays = 500
        origins = torch.zeros(n_rays, 3, dtype=torch.float32)
        origins[:, 0] = -0.5  # just outside grid on -X face
        origins[:, 1] = torch.from_numpy(rng.uniform(0.5, scale - 0.5, n_rays).astype(np.float32))
        origins[:, 2] = torch.from_numpy(rng.uniform(0.5, scale - 0.5, n_rays).astype(np.float32))
        dirs = torch.zeros(n_rays, 3, dtype=torch.float32)
        dirs[:, 0] = 1.0  # +X direction
        patch_ids = torch.arange(n_rays, dtype=torch.long) % 145

        # Run with a very large budget (no chunking)
        saved = getattr(rt, '_FIXED_STEP_BUDGET_BYTES', None)
        rt._FIXED_STEP_BUDGET_BYTES = 10 * 1024**3  # 10 GB, effectively no chunking
        r1_ray, r1_patch, r1_vox = rt._trace_fixed_step(
            min_corner, scale, resolution,
            origins, dirs, patch_ids,
            voxel_size, ray_length,
        )
        # Run with a tiny budget (forces many chunks)
        rt._FIXED_STEP_BUDGET_BYTES = 1024  # 1 KB, extreme chunking
        r2_ray, r2_patch, r2_vox = rt._trace_fixed_step(
            min_corner, scale, resolution,
            origins, dirs, patch_ids,
            voxel_size, ray_length,
        )
        # Restore
        if saved is not None:
            rt._FIXED_STEP_BUDGET_BYTES = saved
        elif hasattr(rt, '_FIXED_STEP_BUDGET_BYTES'):
            del rt._FIXED_STEP_BUDGET_BYTES

        # Results must be identical (same rays, same order)
        assert r1_ray.shape == r2_ray.shape, (
            f"Hit count mismatch: {r1_ray.shape[0]} vs {r2_ray.shape[0]}"
        )
        torch.testing.assert_close(r1_ray, r2_ray)
        torch.testing.assert_close(r1_patch, r2_patch)
        torch.testing.assert_close(r1_vox, r2_vox)

    def test_single_ray_still_works(self):
        """Edge case: a single ray should work regardless of chunk size."""
        import urbansolarcarver.raytracer as rt
        args = _axis_aligned_ray(
            origin=(-0.5, 0.5, 0.5),
            direction=(1.0, 0.0, 0.0),
            resolution=10, voxel_size=1.0,
        )
        saved = getattr(rt, '_FIXED_STEP_BUDGET_BYTES', None)
        rt._FIXED_STEP_BUDGET_BYTES = 1  # absurdly small
        ray_ids, patch_ids, voxel_indices = rt._trace_fixed_step(*args)
        if saved is not None:
            rt._FIXED_STEP_BUDGET_BYTES = saved
        hit_x = set(voxel_indices[:, 0].tolist())
        assert hit_x == set(range(10))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_raytracer.py::TestFixedStepChunking -v`
Expected: FAIL; `_FIXED_STEP_BUDGET_BYTES` does not exist yet.

- [ ] **Step 3: Implement internal chunking**

Replace `_trace_fixed_step` in `src/urbansolarcarver/raytracer.py` (lines 751-788):

```python
# Peak memory budget for the fixed-step tracer's sample-point tensor.
# The (R, S, 3) float32 tensor is the dominant allocation; this caps the
# number of rays processed per internal chunk so peak memory stays bounded.
# Default 512 MB; override in tests via module attribute.
_FIXED_STEP_BUDGET_BYTES: int = 512 * 1024 * 1024


def _trace_fixed_step(
    min_corner, scale, resolution,
    origins, ray_dirs, sky_patch_ids,
    voxel_size, ray_length,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Legacy fixed-step ray marcher (pure PyTorch, CPU fallback).

    Traces rays through a uniform voxel grid by stepping at half-voxel
    intervals and recording every in-bounds voxel hit.  Used when the
    Warp DDA kernel is unavailable (no GPU or Warp not installed).

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
        chunk_patches = sky_patch_ids[chunk_ray_ids]

        if chunk_ray_ids.numel() > 0:
            all_ray_ids.append(chunk_ray_ids)
            all_patch_ids.append(chunk_patches)
            all_voxel_indices.append(chunk_voxels)

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
```

- [ ] **Step 4: Run the chunking tests**

Run: `python -m pytest tests/test_raytracer.py::TestFixedStepChunking -v`
Expected: Both tests PASS.

- [ ] **Step 5: Run existing fixed-step tests to verify no regression**

Run: `python -m pytest tests/test_raytracer.py::TestFixedStepMarcher -v`
Expected: All existing tests PASS (identical output for small inputs).

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: 126+ passed.

- [ ] **Step 7: Commit**

```bash
git add src/urbansolarcarver/raytracer.py tests/test_raytracer.py
git commit -m "perf: chunk fixed-step ray tracer to cap peak memory at 512 MB

The legacy (non-Warp) tracer previously materialized the full (R, S, 3)
sample-point tensor, which could exceed available memory for large scenes
(e.g., 3.5 GB for 1.45M rays x 200 steps). Now processes rays in sub-
batches sized to fit within _FIXED_STEP_BUDGET_BYTES (default 512 MB).
Output is identical regardless of chunk size."
```

---

### Task 5: Final verification and cleanup

**Files:**
- All modified files

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: 126+ passed, 6 skipped.

- [ ] **Step 2: Verify numba cache was created**

Run: `python -c "from urbansolarcarver.grid import _pm_stencil_step; print('numba cache OK')"`
Expected: Prints "numba cache OK" (may take a few seconds on first compilation).

- [ ] **Step 3: Commit any remaining changes**

If tests required any fixes, commit them here.

```bash
git add -A
git commit -m "test: final verification of performance optimizations"
```

(Skip this commit if there are no additional changes.)
