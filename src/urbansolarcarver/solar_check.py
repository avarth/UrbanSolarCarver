"""
UrbanSolarCarver: sun and shade check
=====================================

Per test point, how much sun, solar energy or sky reaches it past each of
several geometries: the maximum volume before carving, the carved
envelope and the building massing after, and none of them ("open").  The
blocking meshes (context and terrain) block in every column.  The check
needs no carving run: it samples the test surfaces itself.  The meshes
are traced, not voxels, because voxel stair-steps and voxels up to one
edge beyond the true surface bias the values.

The metrics and their settings are in :mod:`check_settings`.  Directions
(:func:`check_directions`) are the sun positions of the period for sun
hours, and otherwise cells of Tregenza's 145 sky patches, each split into
``n x n`` cells of equal solid angle (``n`` the square root of
``rays_per_patch``) with one ray through each cell centre.  A direction carries a value: an
hour share for sun hours, the patch's radiation share for the solar
energies (Ladybug sky matrix, Perez), or an analytic sky weight for the
sky metrics, which are normalised by an unobstructed horizontal surface.

:func:`evaluate_test_points` traces every direction a test point faces
against a mesh with Warp's BVH ray queries
(``warp_kernels.mesh_visible_weight_kernel``) and sums the values of the
visible ones, times the cosine of incidence except for sun hours.  A
carved envelope and massing are clipped by the maximum volume: they block
only inside it.  :func:`solar_check` does this for a list of
:class:`CheckGeometry` and writes ``check_points.npz``,
``check_values.npz`` and ``check_summary.json``.  :func:`run_geometries` lists
a run's maximum volume, envelope and massing.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, NamedTuple, Optional, Union

import numpy as np

from .check_settings import CHECK_METRICS, CheckSettings
from .compute_device import resolve_compute_device, warp_device_name
from .run_context import active_context, report_issue, report_progress
from .stage_settings import stage_folder

CHECK_FOLDER = "check"
POINTS_FILE = "check_points.npz"
VALUES_FILE = "check_values.npz"
SUMMARY_FILE = "check_summary.json"
# The geometry the other columns are compared with in the summary.
BASELINE = "max_volume"
# The column traced with none of the geometries (the blocking meshes still block).
OPEN_VARIANT = "open"
# The surface tolerance of drawn geometry (maximum volume, the blocking meshes), in meters: test surfaces drawn
# on it within this distance count as on its surface.
EXACT_SURFACE_TOLERANCE = 0.05
# Rays per kernel launch, about: keeps every launch well under the GPU watchdog's time limit.
_RAYS_PER_LAUNCH = 1 << 25
# Hits closer than this to a ray's origin are ignored (m).
_MIN_HIT = 1e-3


class SkyCells(NamedTuple):
    """Directions through the cells of a sky subdivision (:func:`sky_cells`)."""
    directions: np.ndarray           # (C, 3) float64 unit vectors, z up, +Y north before north_deg
    solid_angles: np.ndarray         # (C,) float64 solid angle of each cell (sr); they sum to 2 pi
    patch_index: np.ndarray          # (C,) int, the patch each cell belongs to
    patch_solid_angles: np.ndarray   # (patches,) float64


def sky_cells(density: str = "tregenza", cells_per_side: int = 2) -> SkyCells:
    """Split each patch of the Tregenza sky into ``cells_per_side**2`` cells of equal solid angle.

    The patches are those of Ladybug's ViewSphere, in its order: rows of
    equal altitude from the horizon up (bands of 12°), the patches of a row starting at azimuth 0 (+Y)
    clockwise, then the zenith cap.  A patch spans its row's band and
    360° / count of azimuth around its centre; it is split in equal steps
    of sin(altitude) and of azimuth, so its cells have equal solid angles,
    and the zenith cap in rings of equal solid angle, each in equal
    azimuth sectors.  With ``cells_per_side`` 1 the directions are
    Ladybug's patch centres, so a check with one ray per patch matches
    Ladybug's incident radiation for the same sky matrix.
    """
    from ladybug.viewsphere import ViewSphere, view_sphere
    if density != "tregenza":
        raise ValueError(f"sky_cells: density must be 'tregenza', got {density!r}")
    rows, band_deg = ViewSphere.TREGENZA_PATCHES_PER_ROW, 90.0 / 7.5
    centres = view_sphere.tregenza_dome_vectors
    n = int(cells_per_side)
    if n < 1:
        raise ValueError(f"sky_cells: cells_per_side must be at least 1, got {cells_per_side}")
    band = math.radians(band_deg)
    steps = (np.arange(n) + 0.5) / n
    directions, omegas, patches, patch_omegas = [], [], [], []
    patch = 0
    for row, count in enumerate(rows):
        s0, s1 = math.sin(row * band), math.sin((row + 1) * band)
        width = 2.0 * math.pi / count
        patch_omegas.extend([width * (s1 - s0)] * count)
        sin_alt = s0 + steps * (s1 - s0)                                    # (n,)
        centre_az = np.arange(count) * width                                 # (count,)
        az = centre_az[:, None] + (steps - 0.5)[None, :] * width             # (count, n)
        alt_grid = np.broadcast_to(np.arcsin(sin_alt)[None, :, None], (count, n, n))
        az_grid = np.broadcast_to(az[:, None, :], (count, n, n))
        directions.append(np.stack([np.cos(alt_grid) * np.sin(az_grid), np.cos(alt_grid) * np.cos(az_grid),
                                    np.sin(alt_grid)], axis=-1).reshape(-1, 3))
        omegas.append(np.full(count * n * n, width * (s1 - s0) / (n * n)))
        patches.append(np.repeat(np.arange(patch, patch + count), n * n))
        patch += count
    s0 = math.sin(len(rows) * band)
    cap_omega = 2.0 * math.pi * (1.0 - s0)
    patch_omegas.append(cap_omega)
    sin_alt = s0 + steps * (1.0 - s0)
    alt_grid, az_grid = np.meshgrid(np.arcsin(sin_alt), steps * 2.0 * math.pi, indexing="ij")
    directions.append(np.stack([np.cos(alt_grid) * np.sin(az_grid), np.cos(alt_grid) * np.cos(az_grid),
                                np.sin(alt_grid)], axis=-1).reshape(-1, 3))
    omegas.append(np.full(n * n, cap_omega / (n * n)))
    patches.append(np.full(n * n, patch))
    directions = np.concatenate(directions)
    if n == 1:
        directions = np.array([[v.x, v.y, v.z] for v in centres], dtype=np.float64)
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    return SkyCells(directions, np.concatenate(omegas), np.concatenate(patches), np.asarray(patch_omegas))


class CheckDirections(NamedTuple):
    """The directions of a check and what each carries (:func:`check_directions`)."""
    directions: np.ndarray   # (D, 3) float32 unit vectors toward the sun or the sky, model coordinates
    values: np.ndarray       # (D,) float64 value of each direction
    use_cosine: bool         # a visible direction adds value * cos(incidence), else value
    scale: float             # the visible sum times this is the metric (100 / horizontal sum for %, else 1)
    unit: str


def check_directions(settings: CheckSettings) -> CheckDirections:
    """The directions and values of *settings*' metric.

    * sun_hours: the sun positions of the period at ``sun_steps_per_hour``,
      above ``min_altitude``, each worth 1 / ``sun_steps_per_hour`` h, no
      cosine.
    * solar_energy, useful_solar_energy: the sky cells, each carrying its
      patch's cumulative radiation (kWh/m², Ladybug sky matrix over the
      period's hours, as in irradiance and benefit carving) times its share
      of the patch's solid angle; with the cosine, a visible sum is the
      energy the surface receives.
    * sky_component: CIE overcast luminance (1 + 2 sin α) / 3 times the
      cell's solid angle; cooling_sky: the cell's solid angle times the
      clear sky's emissivity deficit (:func:`sky_patches.sky_emissivity_deficit`);
      sky_view: the solid angle over π.  These are percentages of an
      unobstructed horizontal surface: ``scale`` is 100 over the cosine-
      weighted sum of every cell for a normal pointing up.
    """
    spec = CHECK_METRICS[settings.metric]
    if settings.metric == "sun_hours":
        from .sun import get_sun_vectors, sample_period
        datetimes, _hoys = sample_period(settings, steps_per_hour=settings.sun_steps_per_hour)
        suns = get_sun_vectors(settings.epw_path, datetimes, settings.min_altitude,
                               north_deg=settings.north_deg, time_basis=settings.time_basis)
        suns = np.asarray(suns.cpu().numpy() if hasattr(suns, "cpu") else suns, dtype=np.float64).reshape(-1, 3)
        if len(suns):
            suns /= np.linalg.norm(suns, axis=1, keepdims=True)
        else:
            report_issue("no_sun_positions",
                         f"No sun position of the check period is above {settings.min_altitude:g}°, "
                         f"so every test point has 0 sun hours.")
        values = np.full(len(suns), 1.0 / settings.sun_steps_per_hour)
        return CheckDirections(suns.astype(np.float32), values, False, 1.0, spec.unit)

    cells = sky_cells(settings.sky_density, math.isqrt(settings.rays_per_patch))
    sin_alt = cells.directions[:, 2]
    if settings.metric in ("solar_energy", "useful_solar_energy"):
        values = _patch_radiation(settings)[cells.patch_index] * (
            cells.solid_angles / cells.patch_solid_angles[cells.patch_index])
        return CheckDirections(cells.directions.astype(np.float32), values, True, 1.0, spec.unit)
    if settings.metric == "sky_component":
        values = cells.solid_angles * (1.0 + 2.0 * sin_alt) / 3.0
    elif settings.metric == "cooling_sky":
        from .sky_patches import sky_emissivity_deficit
        values = cells.solid_angles * sky_emissivity_deficit(settings.dew_point_celsius, settings.bliss_k, sin_alt)
    else:   # sky_view
        values = cells.solid_angles / math.pi
    horizontal = float(np.sum(values * np.clip(sin_alt, 0.0, None)))
    return CheckDirections(cells.directions.astype(np.float32), values, True, 100.0 / horizontal, spec.unit)


def _patch_radiation(settings: CheckSettings) -> np.ndarray:
    """Cumulative radiation per sky patch (kWh/m²) for the solar energy metrics."""
    import torch
    from .sky_patches import compute_EPW_based_weights
    from .sun import sample_period
    _datetimes, hoys = sample_period(settings, steps_per_hour=1)
    simulated = None
    if settings.metric == "useful_solar_energy" and settings.simulated_weights_path:
        from .simulated_weights import read_simulated_weights
        benefit, harm, _meta = read_simulated_weights(settings.simulated_weights_path)
        simulated = (benefit, harm)
    weights = compute_EPW_based_weights(
        "irradiance" if settings.metric == "solar_energy" else "benefit",
        settings.epw_path, hoys, device=torch.device("cpu"),
        balance_temperature=settings.balance_temperature, balance_offset=settings.balance_offset,
        north=settings.north_deg, include_harm=settings.include_harm, simulated_weights=simulated,
    )
    return weights.cpu().numpy().astype(np.float64)


def evaluate_test_points(
    points,
    normals,
    directions: CheckDirections,
    mesh=None,
    *,
    clip_mesh=None,
    blocking=None,
    surface_tolerance: float = EXACT_SURFACE_TOLERANCE,
    clip_tolerance: float = EXACT_SURFACE_TOLERANCE,
    blocking_tolerance: float = EXACT_SURFACE_TOLERANCE,
    origin_offset: float = 0.01,
    ray_length: float = 3000.0,
    frame=None,
    device=None,
    progress=None,
) -> np.ndarray:
    """The metric at every test point past *mesh* and *blocking* (either may be None).

    Every direction in front of a point (positive cosine to its normal)
    that nothing blocks adds its value, times the cosine when
    ``directions.use_cosine``; the sum is multiplied by
    ``directions.scale``.  A ray is blocked where it runs inside the
    mesh's solid and, with *clip_mesh*, inside that solid too: a carved
    envelope or massing is clipped by the maximum volume this way, so the
    part of a voxel or smoothed surface that lies past the maximum volume
    blocks nothing.  The blocking meshes block wherever the ray meets them.
    Ray origins move ``origin_offset`` along the normal and crossings
    within 1 mm of the origin are ignored.  A ray from an origin inside a
    solid but within the solid's tolerance of a face of it that faces the
    test surface's way, which leaves the solid at a height of at most that
    tolerance above the test surface's plane and within ten times that
    distance along the ray, starts outside it: the mesh then lies a little
    outside its own test surface, as a smoothed or voxel envelope does
    around the facades it was carved for.  A test surface deeper in a
    solid is blocked.

    Parameters
    ----------
    points, normals : array, shape (P, 3)
        Test points (world coordinates) and outward unit normals.
    directions : CheckDirections
    mesh : trimesh.Trimesh or None
        Closed triangle mesh with outward normals, in the frame of *points*.
    clip_mesh : trimesh.Trimesh or None
        Closed mesh that *mesh* blocks inside of only.
    blocking : trimesh.Trimesh, path, or a list of them, or None
        Geometry that blocks on its own (context, terrain): meshes or mesh
        files, joined into one mesh.
    surface_tolerance, clip_tolerance, blocking_tolerance : float
        Each mesh's tolerance in meters: the run's voxel size suits a
        carved envelope, :data:`EXACT_SURFACE_TOLERANCE` drawn geometry.
    frame : array of 3 floats, optional
        Subtracted from every coordinate before the float32 tracing; default
        the points' minimum corner.
    device : torch.device or str, optional
        ``'auto'`` (default), ``'cpu'`` or ``'cuda'``; Warp traces on it.
    progress : callable(int), optional
        Called with the number of launches done, after each launch.

    Returns
    -------
    np.ndarray, shape (P,), float64
    """
    import warp as wp
    from .warp_kernels import mesh_visible_weight_kernel, require_dda_backend
    device = resolve_compute_device(device or "auto")
    require_dda_backend(device)
    wp_device = warp_device_name(device)
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    normals = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
    num_points = len(points)
    num_dirs = len(directions.directions)
    if num_points == 0 or num_dirs == 0:
        return np.zeros(num_points)
    frame = points.min(axis=0) if frame is None else np.asarray(frame, dtype=np.float64)
    normals = normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    wp_points = wp.array((points - frame).astype(np.float32), dtype=wp.vec3, device=wp_device)
    wp_normals = wp.array(normals.astype(np.float32), dtype=wp.vec3, device=wp_device)
    wp_dirs = wp.array(np.ascontiguousarray(directions.directions, dtype=np.float32), dtype=wp.vec3, device=wp_device)
    wp_values = wp.array(np.asarray(directions.values, dtype=np.float32), dtype=float, device=wp_device)
    out = wp.zeros(num_points, dtype=wp.float64, device=wp_device)

    def _bvh(trimesh_mesh):
        if trimesh_mesh is None or not len(trimesh_mesh.faces):
            return None
        arrays = dict(
            points=wp.array((np.asarray(trimesh_mesh.vertices, dtype=np.float64) - frame).astype(np.float32),
                            dtype=wp.vec3, device=wp_device),
            indices=wp.array(np.asarray(trimesh_mesh.faces, dtype=np.int32).ravel(), dtype=wp.int32,
                             device=wp_device),
        )
        try:
            # A surface-area-heuristic BVH traces a 267k-triangle smoothed envelope about twice as fast as the
            # default one (District example, 2308 directions: 3.1 s against 7.4 s on an RTX 3060).
            return wp.Mesh(**arrays, bvh_constructor="sah")
        except TypeError:   # a Warp without the option
            return wp.Mesh(**arrays)

    # The BVHs stay referenced here until the launches are done.
    blocking_mesh, _blocking_paths = join_blocking(blocking)
    bvhs = [(_bvh(mesh), surface_tolerance), (_bvh(clip_mesh), clip_tolerance), (_bvh(blocking_mesh), blocking_tolerance)]
    mesh_args = [value for bvh, tolerance in bvhs
                 for value in (bvh.id if bvh else 0, int(bvh is not None), float(tolerance))]
    chunk = max(1, _RAYS_PER_LAUNCH // num_points)
    context = active_context()
    for launch, start in enumerate(range(0, num_dirs, chunk)):
        if context is not None:
            context.raise_if_cancelled()
        wp.launch(
            mesh_visible_weight_kernel, dim=num_points, device=wp_device,
            inputs=[*mesh_args, wp_points, wp_normals, wp_dirs, wp_values, int(directions.use_cosine),
                    start, min(start + chunk, num_dirs), float(origin_offset), _MIN_HIT, float(ray_length), out],
        )
        wp.synchronize_device(wp_device)
        if progress is not None:
            progress(launch + 1)
    return out.numpy() * directions.scale


def join_blocking(blocking):
    """The blocking meshes (context, terrain) as one mesh, and the paths they were read from.

    *blocking* is None, a mesh, a mesh file path, or a list of them; the
    meshes are joined into one (``None`` when there are no triangles).
    """
    import trimesh
    from .io import load_mesh
    items = [] if blocking is None else (list(blocking) if isinstance(blocking, (list, tuple)) else [blocking])
    meshes, paths = [], []
    for item in items:
        if isinstance(item, (str, Path)):
            paths.append(str(item))
            item = load_mesh(str(item))
        if item is not None and len(item.faces):
            meshes.append(item)
    if not meshes:
        return None, paths
    return (meshes[0] if len(meshes) == 1 else trimesh.util.concatenate(meshes)), paths


def launch_count(num_points: int, num_directions: int) -> int:
    """How many kernel launches :func:`evaluate_test_points` makes, for progress totals."""
    if num_points == 0 or num_directions == 0:
        return 0
    chunk = max(1, _RAYS_PER_LAUNCH // num_points)
    return -(-num_directions // chunk)


# --- test points ---------------------------------------------------------------------------------------------------

class CheckPoints(NamedTuple):
    """The test points of a check (:func:`sample_test_surfaces`)."""
    points: np.ndarray    # (P, 3) float64 world coordinates
    normals: np.ndarray   # (P, 3) float64 outward unit normals
    quads: np.ndarray     # (P, 4, 3) float64 corners of the patch of test surface each point stands for


def sample_test_surfaces(test_surfaces, spacing: float, frame=None) -> CheckPoints:
    """Sample the test surfaces every *spacing* meters, as preprocessing samples them.

    Uses :func:`surface_sampling.discretize_surface_with_normals` in a local
    frame anchored at *frame* (default the surfaces' minimum corner) and
    rounded to 1 µm, as preprocessing does; with the maximum volume's
    minimum corner as *frame*, the points equal an analysis's at the same
    spacing.  *test_surfaces* is a trimesh.Trimesh or a mesh file path.

    Raises
    ------
    InputError
        When no point is sampled.
    """
    from .errors import InputError
    from .io import load_mesh
    from .surface_sampling import discretize_surface_with_normals
    mesh = load_mesh(str(test_surfaces)) if isinstance(test_surfaces, (str, Path)) else test_surfaces
    frame = np.asarray(mesh.bounds[0] if frame is None else frame, dtype=np.float64)
    local = mesh.copy()
    local.vertices = np.round(local.vertices - frame, 6)
    points, normals, analysis_mesh, _weights, _taper = discretize_surface_with_normals(local, spacing)
    if len(points) == 0 or analysis_mesh is None:
        raise InputError(
            f"No test points were sampled from the test surfaces at a spacing of {spacing:g} m: check that they are "
            f"flat panels larger than the spacing.")
    quads = np.asarray(analysis_mesh.vertices, dtype=np.float64)[np.asarray(analysis_mesh.faces)] + frame
    return CheckPoints(np.asarray(points, dtype=np.float64) + frame, np.asarray(normals, dtype=np.float64), quads)


# --- the check -----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class CheckGeometry:
    """One geometry a check compares: a column of its results."""
    name: str                       # key in the values and the summary: "max_volume", "envelope", "massing"
    label: str                      # for people
    mesh: "trimesh.Trimesh"
    clip: "Optional[trimesh.Trimesh]" = None    # the maximum volume, for a carved envelope or massing
    surface_tolerance: float = EXACT_SURFACE_TOLERANCE
    path: Optional[str] = None      # the file it was read from, recorded with its size and time


class SolarCheckResult(NamedTuple):
    """What :func:`solar_check` computed and wrote."""
    settings: CheckSettings
    unit: str
    points: CheckPoints
    values: Dict[str, np.ndarray]   # "open" and each geometry's name -> (P,) float64 per test point
    summary: dict                   # the contents of check_summary.json
    folder: Optional[Path]          # where the files were written, None when not written


def _statistics(values: np.ndarray, baseline: Optional[np.ndarray], tolerance: float) -> dict:
    """Minimum, 10th percentile, mean and maximum of *values*; with *baseline*, the mean change and the shares of
    test points better and worse by more than *tolerance*.  Every point stands for about the same test area, so a
    share of points is a share of test area."""
    stats = {
        "min": float(np.min(values)),
        "p10": float(np.percentile(values, 10)),
        "mean": float(np.mean(values)),
        "max": float(np.max(values)),
    }
    if baseline is not None:
        change = values - baseline
        stats["mean_change"] = float(np.mean(change))
        stats["share_improved"] = float(np.mean(change > tolerance))
        stats["share_worse"] = float(np.mean(change < -tolerance))
    return stats


def file_fingerprint(path) -> Optional[dict]:
    """The path, size and modification time of a file, which the summary records for each file the check read;
    None for no path."""
    if path is None:
        return None
    status = Path(path).stat()
    return {"path": str(path), "size": status.st_size, "modified_ns": status.st_mtime_ns}


def solar_check(
    test_surfaces,
    geometries,
    settings: CheckSettings,
    *,
    blocking=None,
    sampling_frame=None,
    out_dir: Union[str, Path, None] = None,
    device=None,
) -> SolarCheckResult:
    """The check's metric per test point for each of *geometries*, and with none of them ("open").

    Samples *test_surfaces* (a mesh or a mesh file) every
    ``settings.sample_spacing`` meters (:func:`sample_test_surfaces`, in
    *sampling_frame*) and
    traces each geometry with :func:`evaluate_test_points`, clipped by its
    ``clip`` mesh and with its own surface tolerance.  *blocking* (meshes or
    mesh files, or None: the context and terrain), joined into one mesh,
    blocks in every column, "open" included.  The summary compares the
    other columns with the geometry named ``max_volume``.

    With *out_dir*, writes there ``check_points.npz`` (the points, normals
    and the corner quads of their patches, float32 relative to ``frame``),
    ``check_values.npz`` (one float32 array per column) and last
    ``check_summary.json``: the metric, its unit, the settings, the columns
    with their meshes, times and statistics, and the size and time of every
    file read.

    Parameters
    ----------
    test_surfaces : trimesh.Trimesh or path
    geometries : sequence of CheckGeometry
    settings : CheckSettings
    blocking : trimesh.Trimesh, path, a list of them, or None
    sampling_frame : array of 3 floats, optional
        The frame the test surfaces are sampled in (see :func:`sample_test_surfaces`).
    out_dir : path, optional
    device : optional
        ``'auto'`` (default), ``'cpu'`` or ``'cuda'``.
    """
    geometries = list(geometries)
    names = [geometry.name for geometry in geometries]
    if len(set(names)) != len(names) or OPEN_VARIANT in names:
        raise ValueError(f"solar_check: geometry names must be unique and not {OPEN_VARIANT!r}, got {names}")
    test_surface_path = str(test_surfaces) if isinstance(test_surfaces, (str, Path)) else None
    blocking_mesh, blocking_paths = join_blocking(blocking)
    device = resolve_compute_device(device or "auto")
    check_points = sample_test_surfaces(test_surfaces, settings.sample_spacing, sampling_frame)
    frame = check_points.points.min(axis=0)
    directions = check_directions(settings)

    columns = [(OPEN_VARIANT, None)] + [(geometry.name, geometry) for geometry in geometries]
    per_column = launch_count(len(check_points.points), len(directions.directions))
    total = per_column * len(columns)
    values: Dict[str, np.ndarray] = {}
    timings: Dict[str, float] = {}
    for index, (name, geometry) in enumerate(columns):
        started = time.perf_counter()
        done_before = index * per_column
        values[name] = evaluate_test_points(
            check_points.points, check_points.normals, directions,
            geometry.mesh if geometry else None,
            clip_mesh=geometry.clip if geometry else None, blocking=blocking_mesh,
            surface_tolerance=geometry.surface_tolerance if geometry else EXACT_SURFACE_TOLERANCE,
            origin_offset=settings.origin_offset, ray_length=settings.ray_length, frame=frame, device=device,
            progress=lambda launch, done_before=done_before: report_progress(done_before + launch, total),
        )
        timings[name] = time.perf_counter() - started

    open_values = values[OPEN_VARIANT]
    change_tolerance = 1e-3 * max(float(np.max(open_values)) if len(open_values) else 0.0, 1e-9)
    column_summaries = {}
    for name, geometry in columns:
        compared = values[BASELINE] if BASELINE in values and name not in (OPEN_VARIANT, BASELINE) else None
        column_summaries[name] = {
            "label": geometry.label if geometry else "Without the building",
            "mesh": file_fingerprint(geometry.path) if geometry else None,
            "clipped": bool(geometry is not None and geometry.clip is not None),
            "surface_tolerance_m": geometry.surface_tolerance if geometry else None,
            "triangles": int(len(geometry.mesh.faces)) if geometry else 0,
            "seconds": round(timings[name], 3),
            "statistics": _statistics(values[name], compared, change_tolerance),
        }
    summary = {
        "metric": settings.metric,
        "label": settings.spec.label,
        "unit": directions.unit,
        "settings": settings.model_dump(),
        "baseline": BASELINE,
        "point_count": int(len(check_points.points)),
        "direction_count": int(len(directions.directions)),
        "device": str(device),
        "inputs": {
            "test_surfaces": file_fingerprint(test_surface_path),
            "blocking": [file_fingerprint(path) for path in blocking_paths],
            "weather": file_fingerprint(settings.epw_path) if settings.spec.needs_epw else None,
        },
        "blocking_triangles": int(len(blocking_mesh.faces)) if blocking_mesh is not None else 0,
        "columns": column_summaries,
    }

    folder = None
    if out_dir is not None:
        folder = Path(out_dir)
        folder.mkdir(parents=True, exist_ok=True)
        summary_path = folder / SUMMARY_FILE
        summary_path.unlink(missing_ok=True)    # written last: a failed check leaves no summary
        np.savez_compressed(
            folder / POINTS_FILE, frame=frame,
            points=(check_points.points - frame).astype(np.float32),
            normals=check_points.normals.astype(np.float32),
            quads=(check_points.quads - frame).astype(np.float32))
        np.savez_compressed(folder / VALUES_FILE, **{name: array.astype(np.float32) for name, array in values.items()})
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return SolarCheckResult(settings, directions.unit, check_points, values, summary, folder)


def load_solar_check(folder: Union[str, Path]) -> Optional[SolarCheckResult]:
    """The check written in *folder* by :func:`solar_check`, or None when there is none."""
    folder = Path(folder)
    summary_path = folder / SUMMARY_FILE
    if not (summary_path.is_file() and (folder / VALUES_FILE).is_file() and (folder / POINTS_FILE).is_file()):
        return None
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    with np.load(folder / VALUES_FILE) as stored:
        values = {name: stored[name].astype(np.float64) for name in stored.files}
    with np.load(folder / POINTS_FILE) as stored:
        frame = stored["frame"]
        points = CheckPoints(stored["points"].astype(np.float64) + frame, stored["normals"].astype(np.float64),
                             stored["quads"].astype(np.float64) + frame)
    return SolarCheckResult(CheckSettings(**summary["settings"]), summary["unit"], points, values, summary, folder)


# --- the geometries of a run ---------------------------------------------------------------------------------------

def _read_manifest(folder: Path) -> Optional[dict]:
    path = folder / "manifest.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _voxel_size_of(run_folder: Path, stage_manifest: dict) -> Optional[float]:
    """The voxel size of the preprocessing run a result was built on, through its thresholding run; None when the
    chain is broken (a later run replaced one of them)."""
    thresholding = _read_manifest(stage_folder(run_folder, "thresholding"))
    preprocessing = _read_manifest(stage_folder(run_folder, "preprocessing"))
    if (thresholding is None or preprocessing is None or stage_manifest.get("upstream_run_id") != thresholding.get("run_id")
            or thresholding.get("upstream_run_id") != preprocessing.get("run_id")):
        return None
    return float(preprocessing["voxel_size"])


def run_geometries(max_volume_path, run_folder=None, fallback_voxel_size: float = 1.0) -> list:
    """The geometries of a run to check: the maximum volume, and the carved envelope and the building massing of
    *run_folder* when they were built (none without a run folder).

    The envelope and the massing are clipped by the maximum volume, with the voxel size of the analysis they were
    built from as their surface tolerance (*fallback_voxel_size* when the chain of manifests is broken).
    """
    from .io import load_mesh
    max_volume = load_mesh(str(max_volume_path))
    geometries = [CheckGeometry("max_volume", "Maximum volume", max_volume, path=str(max_volume_path))]
    if run_folder is None:
        return geometries
    run_folder = Path(run_folder)
    for name, label, stage in (("envelope", "Carved envelope", "exporting"), ("massing", "Building massing", "massing")):
        folder = stage_folder(run_folder, stage)
        manifest = _read_manifest(folder)
        if manifest is None or not (folder / manifest["mesh_path"]).is_file():
            continue
        mesh_path = folder / manifest["mesh_path"]
        voxel_size = _voxel_size_of(run_folder, manifest) or float(fallback_voxel_size)
        geometries.append(CheckGeometry(name, label, load_mesh(str(mesh_path)), clip=max_volume,
                                        surface_tolerance=voxel_size, path=str(mesh_path)))
    return geometries
