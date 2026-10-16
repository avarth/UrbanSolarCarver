"""
UrbanSolarCarver: meshing

Cleans the carved occupancy grid and turns it into the output mesh. Used by
exporting.

Overview
--------
Two meshing modes are supported:

1) Cubic (apply_smoothing == False)
   - Clean the binary grid: drop small connected components, then drop
     occupied voxels with fewer than 2 occupied neighbours in their 3×3×3
     neighbourhood.
   - Triangulate with the shared-vertex cubic mesher
     (`_cubic_mesh_from_occupancy`).

2) Smoothed SDF (apply_smoothing == True)
   - Convert occupancy to a signed distance field (SDF) in voxel units.
   - Light Gaussian blur, then edge-preserving Perona–Malik diffusion;
     the result is kept only within 2 voxels of the zero level.
   - Pick an iso value that preserves the original inside volume.
   - Extract a surface with marching cubes (scikit-image).
   - Optionally run a short Taubin polish (0 to 6 iterations) after cleanup.

Pipeline entry point
--------------------
finalize_mesh(carved_grid, grid_origin, settings, voxel_size)
    Clean the carved grid and mesh it with the cubic or smoothed path.

Public API
----------
prune_voxels(voxels, min_voxels)
    Remove 26-connected components smaller than min_voxels.

prune_voxels_morph(voxels, min_voxels)
    Cleanup for the cubic path: component prune, then the neighbour-count
    filter described above. Only removes voxels; no erosion or closing.

mesh_from_voxels(voxels, min_corner, voxel_size)
    Build a blocky mesh from the binary grid. Returns an unprocessed Trimesh.

mesh_from_voxels_smoothed(voxels, min_corner, voxel_size)
    Build a smooth mesh by contouring a smoothed SDF with marching cubes.
    Uses a volume-matched iso to avoid systematic thinning.

cleanup_mesh(mesh, min_face_count=100, light=False)
    Fix winding/normals (unless light), weld vertices, drop small fragments.

polish_mesh_taubin(mesh, iters=2)
    Optional Taubin polish after the SDF + marching cubes path, at most
    6 iterations.

Internal helpers
----------------
_cubic_mesh_from_occupancy(voxels, min_corner, voxel_size)
    Vertex and face arrays for the cubic mesher.

_voxel_presmooth(field_bool)
    SDF build + Gaussian + narrow-band Perona–Malik diffusion.

_pm_anisotropic_diffuse(sdf, iters, k, tau)
    Edge-preserving diffusion stepper used by _voxel_presmooth.

_volume_matched_threshold(sdf, target_inside_voxels)
    Iso selection that matches the original inside count.

_median_edge_length(m)
    Median of unique edge lengths; used to normalize the Taubin polish.

Data types and units
--------------------
- Voxel grids: torch.Tensor, shape (D, D, D), uint8/bool, 1 = inside.
- Meshes: trimesh.Trimesh in world coordinates.
- voxel_size is in world units and is passed to marching cubes as the grid
  spacing.

Notes
-----
- The cubic path gives a blocky "voxel look" that is stable between runs.
  It applies no erosion, so thin volumes are kept.
- The smoothed path operates in SDF space, not on the triangle mesh. This
  removes terracing while keeping the overall form.
- The Taubin step is short and optional. Heavy smoothing belongs in SDF
  space, not on the mesh.
"""

import math
from typing import Tuple

import numpy as np
import torch
import trimesh
from numba import njit, prange
from scipy import ndimage as ndi
from scipy.ndimage import distance_transform_edt, gaussian_filter
from trimesh import repair

from .run_context import report_issue
from .stage_settings import ExportingSettings


def finalize_mesh(carved_grid, grid_origin, settings: ExportingSettings, voxel_size: float):
    """
    Convert carved voxels to a mesh and clean results.

    Behavior
    --------
    • If `apply_smoothing` is False:
        `prune_voxels_morph` (small-component prune + neighbour-count filter),
        cubic meshing, then `cleanup_mesh` in light mode.
    • If `apply_smoothing` is True:
        `prune_voxels` (small-component prune),
        SDF presmooth + marching cubes, vertex weld, then `cleanup_mesh`
        (light mode when the welded mesh is watertight),
        then `polish_mesh_taubin` with ``settings.smooth_iters`` (0 to 6).

    Parameters
    ----------
    carved_grid : torch.Tensor (D, D, D)
        Binary occupancy after carving.
    grid_origin : np.ndarray(3,)
        World-space min corner for index (0,0,0).
    settings : ExportingSettings
        Supplies ``apply_smoothing``, ``min_voxels``, ``min_face_count`` and
        ``smooth_iters``.
    voxel_size : float
        Edge length of a voxel in meters; it belongs to the preprocessing run
        that built the grid, so it is not part of the exporting settings.

    Returns
    -------
    cleaned_voxels : torch.Tensor (D, D, D)
        Post-pruned (and possibly morphologically cleaned) occupancy.
    initial_mesh : trimesh.Trimesh
        Mesh directly from the selected meshing path (pre-cleanup copy).
    final_mesh : trimesh.Trimesh
        Cleaned mesh, Taubin-polished on the smoothed path when smooth_iters > 0.
    """
    use_smooth = bool(settings.apply_smoothing)

    if use_smooth:
        # Smooth path: prune → SDF smooth → marching cubes → cleanup → Taubin
        cleaned_voxels = prune_voxels(carved_grid, settings.min_voxels)
        raw_mesh = mesh_from_voxels_smoothed(cleaned_voxels, grid_origin, voxel_size)
        initial_mesh = raw_mesh.copy()
        # Marching cubes on the padded SDF yields a watertight, consistently
        # wound mesh; the expensive full repair (fill_holes / fix_winding /
        # fix_normals) is only needed if the welded mesh is not watertight.
        # Weld coincident vertices first: marching cubes emits zero-area
        # faces where the iso passes exactly through lattice nodes, and
        # dropping those before welding would open pinholes.
        raw_mesh.merge_vertices()
        light = bool(raw_mesh.is_watertight)
        filtered_mesh = cleanup_mesh(raw_mesh, settings.min_face_count, light=light)
        iters = int(settings.smooth_iters)  # 0-6, validated by the config schema
        final_mesh = polish_mesh_taubin(filtered_mesh, iters=iters)
    else:
        # Cubic path: prune + neighbour-count filter, cubic meshing, then cleanup
        cleaned_voxels = prune_voxels_morph(carved_grid, settings.min_voxels)
        raw_mesh = mesh_from_voxels(cleaned_voxels, grid_origin, voxel_size)
        initial_mesh = raw_mesh.copy()
        final_mesh = cleanup_mesh(raw_mesh, settings.min_face_count, light=True)

    return cleaned_voxels, initial_mesh, final_mesh


def prune_voxels(
    voxels: torch.Tensor,
    min_voxels: int
) -> torch.Tensor:
    """
    Remove connected components smaller than `min_voxels` (26-connectivity).

    Parameters
    ----------
    voxels : (D, D, D) uint8/bool torch.Tensor
    min_voxels : int
        Size threshold; components with fewer voxels are removed.

    Returns
    -------
    cleaned : (D, D, D) uint8 torch.Tensor
        Binary occupancy on the same device as `voxels`.

    Notes
    -----
    - Used on the smoothed path (`apply_smoothing=True`) prior to SDF smoothing.
    """
    arr = voxels.detach().cpu().numpy().astype(bool)
    struct26 = np.ones((3, 3, 3), dtype=bool)
    labeled, num = ndi.label(arr, structure=struct26)
    counts = np.bincount(labeled.ravel())
    small = np.where((counts < int(min_voxels)) & (np.arange(counts.size) != 0))[0]
    if small.size:
        arr[np.isin(labeled, small)] = False
    return torch.from_numpy(arr.astype(np.uint8)).to(voxels.device)

def prune_voxels_morph(
    voxels: torch.Tensor,
    min_voxels: int,
) -> torch.Tensor:
    """
    Light cleanup for the cubic (unsmoothed) path.

    Steps
    -----
    1. Remove connected components (26-connectivity) with fewer than
       `min_voxels` voxels.
    2. Remove occupied voxels whose 3×3×3 neighbourhood (including the
       voxel itself) holds fewer than 3 occupied voxels, i.e. voxels with
       0 or 1 occupied neighbours.  This drops isolated specks and
       one-voxel spurs.

    Only removes voxels, never adds them: adding would undo carving.

    Parameters
    ----------
    voxels : (D, D, D) uint8/bool torch.Tensor
    min_voxels : int
        Size threshold; components with fewer voxels are removed.

    Returns
    -------
    cleaned : (D, D, D) uint8 torch.Tensor
        Binary occupancy on the same device as `voxels`.
    """
    arr = voxels.detach().cpu().numpy().astype(bool)
    # 26-connectivity: voxels touching only at an edge or corner still
    # count as one component, so fewer pieces fall below min_voxels.
    struct26 = np.ones((3, 3, 3), dtype=bool)
    labeled, _ = ndi.label(arr, structure=struct26)
    counts = np.bincount(labeled.ravel())
    # drop small components (ignore label 0 = background)
    small = np.where((counts < int(min_voxels)) & (np.arange(counts.size) != 0))[0]
    if small.size:
        arr[np.isin(labeled, small)] = False

    # Neighbour-count filter: cnt is the number of occupied voxels in each
    # 3×3×3 block, including the centre voxel.  An occupied voxel survives
    # with cnt >= 3 (at least 2 occupied neighbours).  The AND with arr
    # keeps empty voxels empty, so the result never grows beyond the
    # carved volume.
    k = np.ones((3, 3, 3), dtype=np.int16)
    cnt = ndi.convolve(arr.astype(np.int16), k, mode="constant", cval=0)
    arr = arr & (cnt >= 3)

    return torch.from_numpy(arr.astype(np.uint8)).to(voxels.device)

@njit(cache=True, parallel=True)
def _pm_stencil_step(src, dst, k2, tau):
    """Single Perona-Malik diffusion step (6-neighbor 3D Jacobi stencil).

    Reads from ``src`` and writes interior voxels of ``dst`` (a Jacobi
    update).  This is safe to parallelize (numba ``prange`` over z-slabs)
    because no cell reads a value written in the same step.  Operates on
    *padded* arrays: the border ring is left unchanged by this kernel;
    the caller refreshes it after each step to maintain the Neumann
    (zero-flux) boundary condition.

    Parameters
    ----------
    src : (Nz+2, Ny+2, Nx+2) float32 ndarray
        Padded SDF read by the stencil (not modified).
    dst : (Nz+2, Ny+2, Nx+2) float32 ndarray
        Output buffer; interior voxels are overwritten.
    k2 : float
        Squared edge-stopping scale (k^2).
    tau : float
        Diffusion time step.  The explicit 6-neighbour scheme is stable for
        tau <= 1/6 (about 0.167).
    """
    nz, ny, nx = src.shape
    for z in prange(1, nz - 1):
        for y in range(1, ny - 1):
            for x in range(1, nx - 1):
                c = src[z, y, x]
                # Forward/backward finite differences to 6 face-neighbors
                dxp = src[z, y, x + 1] - c
                dxm = c - src[z, y, x - 1]
                dyp = src[z, y + 1, x] - c
                dym = c - src[z, y - 1, x]
                dzp = src[z + 1, y, x] - c
                dzm = c - src[z - 1, y, x]
                # Edge-stopping coefficients: c_i = exp(-(grad_i / k)^2)
                # Small gradients -> c ~ 1 (smooth), large -> c ~ 0 (preserve)
                div = (math.exp(-(dxp * dxp) / k2) * dxp
                     - math.exp(-(dxm * dxm) / k2) * dxm
                     + math.exp(-(dyp * dyp) / k2) * dyp
                     - math.exp(-(dym * dym) / k2) * dym
                     + math.exp(-(dzp * dzp) / k2) * dzp
                     - math.exp(-(dzm * dzm) / k2) * dzm)
                dst[z, y, x] = c + tau * div


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
        Time step; the explicit 6-neighbour scheme is stable for
        tau <= 1/6 (about 0.167).

    Returns
    -------
    filtered : (Z, Y, X) float32 np.ndarray

    Notes
    -----
    - Uses a numba-compiled parallel Jacobi stencil: each step reads the
      previous buffer and writes a second one, so z-slabs can run on all
      cores.
    - The whole field is diffused.  ``_voxel_presmooth`` then keeps the
      result only within a narrow band around the zero level, to avoid
      volume drift.
    """
    iters = int(iters)
    if iters <= 0:
        return sdf.astype(np.float32, copy=True)

    k2 = float(k) * float(k)
    if k2 == 0.0:
        k2 = 1e-12  # guard against k=0
    tau_f = float(tau)

    # Pad with edge values (Neumann boundary: zero normal derivative).
    # The stencil does not write the border ring; it is refreshed from
    # the adjacent interior after each step below.
    src = np.pad(sdf.astype(np.float32), 1, mode="edge")
    dst = src.copy()

    for _ in range(iters):
        _pm_stencil_step(src, dst, k2, tau_f)
        # Copy the new edge values into the border so the Neumann
        # condition holds for the next step.
        dst[0, :, :] = dst[1, :, :]
        dst[-1, :, :] = dst[-2, :, :]
        dst[:, 0, :] = dst[:, 1, :]
        dst[:, -1, :] = dst[:, -2, :]
        dst[:, :, 0] = dst[:, :, 1]
        dst[:, :, -1] = dst[:, :, -2]
        src, dst = dst, src  # ping-pong buffers

    # Strip padding and return interior (src holds the latest step)
    return src[1:-1, 1:-1, 1:-1].copy()

def _voxel_presmooth(field_bool: np.ndarray) -> np.ndarray:
    """
    Build a smoothed signed-distance field (SDF) from a boolean occupancy grid.

    Pipeline
    --------
    1) Compute inside/outside Euclidean distance transforms and form SDF = d_in − d_out.
    2) Apply a light Gaussian blur (sigma 0.3 voxels).
    3) Run Perona–Malik diffusion and keep its result where the blurred
       |SDF| < 2 voxels, to reduce terracing while preserving edges.
       Outside that band the unblurred SDF from step 1 is kept.

    Parameters
    ----------
    field_bool : (Z, Y, X) bool/uint8 np.ndarray

    Returns
    -------
    sdf : (Z, Y, X) float32 np.ndarray
        Smoothed SDF in voxel units (positive inside), to be contoured by
        marching cubes.
    """
    occ = field_bool.astype(bool)

    # Step 1: Build a signed distance field via dual distance transforms.
    # d_in  = Euclidean distance from each occupied voxel to the nearest empty one.
    # d_out = distance from each empty voxel to the nearest occupied one.
    # SDF = d_in − d_out is >= 1 at occupied voxels and <= -1 at empty
    # ones, so the zero level lies between the last inside and the first
    # outside voxel centre.  Positive inside is the sign convention the
    # marching-cubes step expects.
    # The two transforms are independent and scipy releases the GIL, so
    # run them concurrently (~1.9x on large grids).
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as _pool:
        _f_in = _pool.submit(distance_transform_edt, occ)
        _f_out = _pool.submit(distance_transform_edt, ~occ)
        d_in, d_out = _f_in.result(), _f_out.result()
    sdf0 = (d_in - d_out).astype(np.float32)

    # Step 2: Light Gaussian blur (σ = 0.3 voxels) to remove voxel-scale
    # staircase artifacts without over-diffusing sharp features.
    sdf = gaussian_filter(sdf0, sigma=0.3, mode="nearest")

    # Step 3: Edge-preserving Perona–Malik (PM) diffusion, kept only in a
    # narrow band of |SDF| < 2 voxels around the zero level.  Limiting the
    # change to the band prevents interior volume drift while smoothing
    # the terraced surface contour.
    band = np.abs(sdf) < 2.0
    if np.any(band):
        # Set the PM edge-stopping scale k to 1.05× the median gradient
        # magnitude within the band.  A distance field changes by about
        # 1 per voxel, so neighbour differences of that size still diffuse,
        # while much larger jumps (features, corners) are damped.
        g = np.gradient(sdf)
        mag = np.sqrt(g[0]**2 + g[1]**2 + g[2]**2)
        k = max(1.05 * float(np.median(mag[band])), 1e-6)
        sdf_band = _pm_anisotropic_diffuse(sdf, iters=16, k=k, tau=0.15)
        # Outside the band keep the unblurred SDF from step 1.
        sdf = np.where(band, sdf_band, sdf0)
    else:
        sdf = sdf0
    return sdf

def _volume_matched_threshold(sdf: np.ndarray, target_inside_voxels: int) -> float:
    """
    Choose an isosurface value so that the number of voxels with SDF >= iso
    equals `target_inside_voxels` (exactly, when there are no ties).

    Parameters
    ----------
    sdf : (Z, Y, X) float32 np.ndarray
        Smoothed signed-distance field.
    target_inside_voxels : int
        Count of 'inside' cells in the original binary occupancy.

    Returns
    -------
    iso : float
        Threshold for marching cubes.

    Notes
    -----
    - Offsets the iso-value away from 0 to compensate for smoothing-induced
      thinning or thickening.
    """
    flat = sdf.ravel()
    n = flat.size
    tgt = int(max(0, min(n, target_inside_voxels)))
    idx = n - tgt
    if idx <= 0:
        # Every cell inside: the lowest value keeps them all.
        return float(np.min(flat))
    if idx >= n:
        # No cell inside: a value just above the highest keeps none.
        return float(np.nextafter(np.max(flat), flat.dtype.type(np.inf)))
    return float(np.partition(flat, idx)[idx])

def _median_edge_length(m: trimesh.Trimesh) -> float:
    """Median edge length of a trimesh, used to normalize Taubin smoothing.

    Returns 1.0 for empty meshes to avoid division by zero.
    """
    el = m.edges_unique_length
    return float(np.median(el)) if len(el) else 1.0

def polish_mesh_taubin(mesh: trimesh.Trimesh, iters: int = 2) -> trimesh.Trimesh:
    """
    Apply a short Taubin smoothing pass to remove small ripples.

    Parameters
    ----------
    mesh : trimesh.Trimesh
        Modified in place.
    iters : int, default 2
        Number of trimesh Taubin steps, capped at 6.  trimesh alternates
        steps (even steps shrink, odd steps inflate), so even values give
        complete shrink/inflate pairs.  If 0 or less, the mesh is returned
        unchanged.

    Returns
    -------
    mesh : trimesh.Trimesh
        The same object, smoothed, with degenerate faces removed.

    Notes
    -----
    - Uses fixed parameters λ = 0.28 and ν = 0.31 (trimesh's sign
      convention; μ = −0.31 in Taubin's notation).
    - Vertices are centred and scaled to unit median edge length during
      smoothing, then restored.
    - Intended only after the SDF + marching cubes path.  Keep the
      iteration count small to avoid shape drift.
    """
    if iters <= 0 or len(mesh.vertices) == 0:
        return mesh

    # Taubin (1995): alternate a shrinking step (lambda) and a slightly larger
    # inflating step (mu = -nu) so the surface is smoothed without shrinking.
    # trimesh.smoothing.filter_taubin subtracts nu * Laplacian, so the
    # inflating step needs a positive nu here.
    lamb, nu = 0.28, 0.31

    # Centre and scale in place (V is a plain view of mesh.vertices).
    V = mesh.vertices.view(np.ndarray)
    c = V.mean(axis=0)
    V -= c
    s = _median_edge_length(mesh)
    if not np.isfinite(s) or s <= 0:
        s = 1.0
    V /= s

    from trimesh.smoothing import filter_taubin
    filter_taubin(mesh, lamb=lamb, nu=nu, iterations=int(min(iters, 6)))

    # Restore original scale and world-space position.
    # Do not call mesh.rezero() here: it moves the bounding-box minimum to
    # (0, 0, 0) and would discard the world-space offset applied in
    # mesh_from_voxels_smoothed.
    mesh.vertices[:] = mesh.vertices * s + c
    mesh.update_faces(mesh.nondegenerate_faces())
    return mesh


def mesh_from_voxels(
    voxels: torch.Tensor,
    min_corner: np.ndarray,
    voxel_size: float
) -> trimesh.Trimesh:
    """
    Construct a blocky (cubic) mesh from a binary occupancy grid.

    Parameters
    ----------
    voxels : (D, D, D) uint8/bool torch.Tensor
    min_corner : (3,) array_like
        World-space origin of the grid (maps index [0,0,0] to this point).
    voxel_size : float
        Size of one voxel in world units.

    Returns
    -------
    mesh : trimesh.Trimesh
        Unprocessed triangle mesh (process=False). Call `cleanup_mesh` next.

    See Also
    --------
    mesh_from_voxels_smoothed
    """
    verts, faces = _cubic_mesh_from_occupancy(voxels, min_corner, voxel_size)
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def _cubic_mesh_from_occupancy(
    voxels: torch.Tensor,
    min_corner: np.ndarray,
    voxel_size: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Emit the exposed faces of occupied voxels as triangles on a shared vertex grid.

    Quad corners are indices into the (D+1)³ lattice of voxel corners, so
    neighbouring faces share vertices and there are no duplicates.  Only
    the corners referenced by faces are returned, re-indexed from 0.

    Parameters
    ----------
    voxels : (D, D, D) uint8/bool torch.Tensor
        Binary occupancy grid.
    min_corner : (3,) array_like
        World-space origin of grid index [0,0,0].
    voxel_size : float
        Edge length of one voxel in world units.

    Returns
    -------
    vertices : (V, 3) float32 ndarray   (only vertices referenced by faces)
    faces : (F, 3) int32 ndarray
    """
    occ = voxels.detach().cpu().numpy().astype(bool)
    D = occ.shape[0]
    s = float(voxel_size)

    # Pad with empty voxels on all sides so neighbor lookups at grid
    # boundaries don't need special-case bounds checking.
    padded = np.pad(occ, 1, mode='constant', constant_values=False)

    # Shared vertex grid: a D³ voxel grid has (D+1)³ corner vertices.
    # Flat index for corner (i,j,k): i*(D+1)² + j*(D+1) + k  (row-major).
    D1 = D + 1
    D1sq = D1 * D1

    # 6 face definitions, one per axis-aligned direction.
    # Each entry: (neighbor offset, 4 corner offsets relative to voxel (i,j,k)).
    # Corner offsets index into the (D+1)³ vertex grid.
    # Winding is counter-clockwise when viewed from outside (outward normal).
    face_defs = [
        # +X face: exposed at (i+1, *, *). Quad corners at i+1 plane.
        ((1, 0, 0), [(1,0,0), (1,1,0), (1,1,1), (1,0,1)]),
        # -X face
        ((-1, 0, 0), [(0,0,1), (0,1,1), (0,1,0), (0,0,0)]),
        # +Y face
        ((0, 1, 0), [(0,1,0), (0,1,1), (1,1,1), (1,1,0)]),
        # -Y face
        ((0, -1, 0), [(1,0,0), (1,0,1), (0,0,1), (0,0,0)]),
        # +Z face
        ((0, 0, 1), [(0,0,1), (1,0,1), (1,1,1), (0,1,1)]),
        # -Z face
        ((0, 0, -1), [(0,0,0), (0,1,0), (1,1,0), (1,0,0)]),
    ]

    all_faces = []

    for (si, sj, sk), corners in face_defs:
        # Find exposed faces: occupied voxels whose neighbor in (si,sj,sk) is empty.
        # Index i in occ is index i+1 in padded, hence the +1 in the slices.
        exposed = occ & ~padded[1+si:D+1+si, 1+sj:D+1+sj, 1+sk:D+1+sk]
        if not exposed.any():
            continue

        # Get voxel indices of exposed faces
        ei, ej, ek = np.nonzero(exposed)  # each (M,)

        # Map 4 quad corners to flat vertex indices in the (D+1)³ grid
        v = np.empty((ei.shape[0], 4), dtype=np.int32)
        for c, (di, dj, dk) in enumerate(corners):
            v[:, c] = (ei + di) * D1sq + (ej + dj) * D1 + (ek + dk)

        # Two triangles per quad: (0,1,2) and (0,2,3)
        tri1 = v[:, [0, 1, 2]]
        tri2 = v[:, [0, 2, 3]]
        all_faces.append(tri1)
        all_faces.append(tri2)

    if not all_faces:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.int32)

    faces_all = np.vstack(all_faces)

    # Only emit vertices that are actually referenced by faces.
    # Most of the (D+1)³ grid corners are interior and never used.
    used = np.unique(faces_all)

    # Convert flat vertex indices back to (i,j,k) grid coordinates,
    # then to world-space positions.
    gi = used // D1sq
    gj = (used % D1sq) // D1
    gk = used % D1
    verts = np.column_stack([
        min_corner[0] + gi * s,
        min_corner[1] + gj * s,
        min_corner[2] + gk * s,
    ]).astype(np.float32)

    # Remap face indices from the sparse (D+1)³ space into a compact
    # [0, len(used)) range so the vertex array has no gaps.
    remap = np.empty(used.max() + 1, dtype=np.int32)
    remap[used] = np.arange(used.size, dtype=np.int32)
    faces_compact = remap[faces_all]

    return verts, faces_compact

def mesh_from_voxels_smoothed(
    voxels: torch.Tensor,
    min_corner: np.ndarray,
    voxel_size: float
) -> trimesh.Trimesh:
    """
    Construct a smooth mesh by contouring a smoothed SDF with marching cubes.

    Parameters
    ----------
    voxels : (D, D, D) uint8/bool torch.Tensor
        Binary occupancy (1 = inside).
    min_corner : (3,) array_like
        World-space grid origin.
    voxel_size : float
        World units per voxel (passed as `spacing` to marching cubes).

    Returns
    -------
    mesh : trimesh.Trimesh
        Unprocessed triangle mesh (process=False) in world coordinates;
        an empty Trimesh if the grid is empty or the field is constant.

    Notes
    -----
    - Internally calls `_voxel_presmooth` and chooses an iso-value via
      `_volume_matched_threshold` to preserve volume.
    - Marching cubes runs directly on the continuous SDF so the surface
      interpolates smoothly between voxel centers.  (trimesh's
      ``matrix_to_marching_cubes(threshold=...)`` would binarize the field
      first, throwing the smoothing away.)
    """
    occ = voxels.detach().to('cpu').numpy().astype(bool)
    if not occ.any():
        return trimesh.Trimesh()  # otherwise the iso-surface outlines the whole grid
    field = _voxel_presmooth(occ)  # smoothed SDF
    # pick iso to match original volume so medium-thick parts don't disappear
    iso = _volume_matched_threshold(field, int(occ.sum()))

    s = float(voxel_size)
    # Pad with a strongly-outside value so surfaces touching the grid
    # boundary are closed rather than left open.
    pad_val = float(field.min()) - 1.0
    padded = np.pad(field, 1, mode="constant", constant_values=pad_val)
    # skimage requires the level to lie strictly inside the data range.
    lo, hi = float(padded.min()), float(padded.max())
    if hi <= lo:
        return trimesh.Trimesh()  # constant field: nothing to mesh
    iso = float(np.clip(iso, lo + 1e-6 * max(abs(lo), 1.0), hi - 1e-6 * max(abs(hi), 1.0)))

    from skimage import measure
    verts, faces, _normals, _values = measure.marching_cubes(
        padded, level=iso, spacing=(s, s, s),
    )
    # Index i samples the SDF at the voxel CENTER, which sits at
    # min_corner + (i + 0.5) * s in world space.  Remove the 1-voxel pad
    # (-s) and add the half-voxel center offset (+0.5 s).
    verts = verts - 0.5 * s
    # skimage's winding points normals inward for a positive-inside field;
    # reverse each face so normals face outward (positive enclosed volume).
    faces = faces[:, ::-1]
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    mesh.apply_translation(min_corner)
    return mesh

def cleanup_mesh(
    mesh: trimesh.Trimesh,
    min_face_count: int = 100,
    light: bool = False,
) -> trimesh.Trimesh:
    """
    Repair and prune small fragments from a mesh.

    Parameters
    ----------
    mesh : trimesh.Trimesh
        Modified in place.
    min_face_count : int, default 100
        Fragments with fewer faces than this are discarded.
    light : bool, default False
        If True, skip the repair steps (fix_winding, fix_normals,
        fix_inversion, fill_holes, merge_vertices).  Use for meshes that
        already have shared vertices and consistent outward winding: the
        cubic mesher's output and watertight marching-cubes output.
        Roughly 10x faster on large meshes.

    Returns
    -------
    mesh : trimesh.Trimesh
        Concatenation of the components with at least `min_face_count`
        faces.  If no component is that large, only the largest one is
        returned and a UserWarning is issued.
    """
    if light:
        # The input already has consistent winding; only remove
        # degenerate/duplicate faces and prune small fragments.
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.update_faces(mesh.unique_faces())
        mesh.remove_unreferenced_vertices()
    else:
        # Full repair, for marching-cubes output that is not watertight
        repair.fix_winding(mesh)
        repair.fix_normals(mesh, multibody=True)
        repair.fix_inversion(mesh, multibody=True)
        repair.fill_holes(mesh)
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.update_faces(mesh.unique_faces())
        mesh.merge_vertices()
        mesh.remove_unreferenced_vertices()
    parts = mesh.split(only_watertight=False)
    large = [p for p in parts if len(p.faces) >= min_face_count]
    if not large and parts:
        # Every part is below min_face_count: keep the largest one rather
        # than everything (which would ignore the setting) or nothing.
        largest = max(parts, key=lambda p: len(p.faces))
        report_issue(
            "mesh_cleanup_kept_largest_part",
            f"cleanup_mesh: no mesh part has min_face_count={min_face_count} faces; "
            f"keeping only the largest ({len(largest.faces)} faces) of {len(parts)}.",
        )
        return largest
    return trimesh.util.concatenate(large) if large else mesh
