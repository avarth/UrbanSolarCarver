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
hours, and otherwise Tregenza's 145 sky patches.  With ``rays_per_patch``
1 a patch is traced through Ladybug's patch centre; above 1 it is traced as
the carving traces it, through ``rays_per_patch`` jittered sub-rays, one in
each cell of equal solid angle, placed by a hash of the test point's index,
the patch and the cell (:func:`sky_patches.sub_ray_directions`).  A
direction carries a value: an hour share for sun hours, the patch's
radiation for the solar energies (Ladybug sky matrix, Perez), or an
analytic sky weight for the sky metrics, which are normalised by an
unobstructed horizontal surface; a sub-ray carries an equal share of its
patch's value.

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
from typing import TYPE_CHECKING, Dict, NamedTuple, Optional, Union

import numpy as np

from .check_files import EXACT_SURFACE_TOLERANCE, POINTS_FILE, SKY_FILE, SUMMARY_FILE, VALUES_FILE, file_fingerprint, run_geometry_files
from .check_settings import CHECK_METRICS, CheckSettings, settings_digest
from .compute_device import resolve_compute_device, warp_device_name
from .run_context import active_context, report_issue, report_progress

if TYPE_CHECKING:
    import trimesh

# The geometry the other columns are compared with in the summary.
BASELINE = "max_volume"
# The column traced with none of the geometries (the blocking meshes still block).
OPEN_VARIANT = "open"
# The most test points a check samples: more would not fit the memory of the traced values (P points by D directions).
MAX_CHECK_POINTS = 2_000_000
# Rays per kernel launch, about: keeps every launch well under the GPU watchdog's time limit.
_RAYS_PER_LAUNCH = 1 << 25
# Hits closer than this to a ray's origin are ignored (m).
_MIN_HIT = 1e-3
# A quick sun hours study samples the sun on every n-th day, n chosen so that the period gives at most about this many positions.
QUICK_SUN_POSITIONS = 240
# The fewest segments of the ground disc's polygon (ground_disc).
GROUND_DISC_MIN_SEGMENTS = 64
# A face of the surroundings whose normal points this far down (z component) is a bottom, left out of a study's surfaces.
DOWNWARD_NORMAL_Z = -0.9


class CheckDirections(NamedTuple):
    """The directions of a check and what each carries (:func:`check_directions`).

    With ``sub_side`` above 1, direction ``j`` is a slot: sub-ray
    ``j % sub_side**2`` of patch ``patch_ids[j]``, whose direction the kernel
    draws per test point (``directions`` then holds the patch centre)."""
    directions: np.ndarray   # (D, 3) float32 unit vectors toward the sun or the sky, model coordinates
    values: np.ndarray       # (D,) float64 value of each direction
    use_cosine: bool         # a visible direction adds value * cos(incidence), else value
    scale: float             # the visible sum times this is the metric (100 / horizontal sum for %, else 1)
    unit: str
    patch_ids: Optional[np.ndarray] = None   # (D,) int32 sky patch of each direction; None for the sun
    sub_side: int = 1                        # sub-rays per patch = sub_side**2; 1 traces `directions`
    day_step: int = 1                        # sun hours: the sun sampled on every day_step-th day (quick), 1 for every day


def check_directions(settings: CheckSettings) -> CheckDirections:
    """The directions and values of *settings*' metric.

    * sun_hours: the sun positions of the period at ``sun_steps_per_hour``,
      above ``min_altitude``, each worth 1 / ``sun_steps_per_hour`` h, no
      cosine.
    * solar_energy, useful_solar_energy: the sky patches, each carrying its
      cumulative radiation (kWh/m², Ladybug sky matrix over the period's
      hours, as in irradiance and benefit carving); with the cosine, a
      visible sum is the energy the surface receives.
    * sky_component: CIE overcast luminance (1 + 2 sin α) / 3 at the patch
      centre times the patch's solid angle; cooling_sky: the solid angle
      times the clear sky's emissivity deficit at the centre
      (:func:`sky_patches.sky_emissivity_deficit`); sky_view: the solid
      angle over π.  These are percentages of an unobstructed horizontal
      surface: ``scale`` is 100 over the cosine-weighted sum of every patch
      for a normal pointing up, the cosine taken at the patch centre for one
      ray per patch and as its mean over the patch for sub-rays, so that
      jittered sub-rays reach 100 on average.

    The sky patches are not turned by ``north_deg``: as in the carving, they
    lie in the model's frame and the radiation of each is computed for the
    turned sky (:func:`sky_patches.compute_EPW_based_weights`).  With
    ``rays_per_patch`` above 1 each patch becomes ``rays_per_patch`` slots
    that share its value equally (``patch_ids``, ``sub_side``).
    """
    spec = CHECK_METRICS[settings.metric]
    if settings.metric == "sun_hours":
        from .sun import get_sun_vectors, sample_period
        datetimes, _hoys = sample_period(settings, steps_per_hour=settings.sun_steps_per_hour)
        # Quick: every day_step-th day of the period, each kept day counting for the days it stands for (the last group may be
        # shorter). The weights go by group, since get_sun_vectors drops the positions below the lowest altitude.
        days = list(dict.fromkeys((moment.month, moment.day) for moment in datetimes))
        day_step = max(1, math.ceil(len(datetimes) / QUICK_SUN_POSITIONS)) if settings.quick else 1
        groups: Dict[int, list] = {}
        for moment in datetimes:
            index = days.index((moment.month, moment.day)) if day_step > 1 else 0
            if index % day_step == 0:
                groups.setdefault(min(day_step, len(days) - index), []).append(moment)
        parts, weights = [], []
        for counted_days, moments in groups.items():
            found = get_sun_vectors(settings.epw_path, moments, settings.min_altitude,
                                    north_deg=settings.north_deg, time_basis=settings.time_basis)
            found = np.asarray(found.cpu().numpy() if hasattr(found, "cpu") else found, dtype=np.float64).reshape(-1, 3)
            parts.append(found)
            weights.append(np.full(len(found), counted_days / settings.sun_steps_per_hour))
        suns = np.concatenate(parts) if parts else np.zeros((0, 3))
        values = np.concatenate(weights) if weights else np.zeros(0)
        if len(suns):
            suns /= np.linalg.norm(suns, axis=1, keepdims=True)
        else:
            report_issue("no_sun_positions",
                         f"No sun position of the check period is above {settings.min_altitude:g}°, "
                         f"so every test point has 0 sun hours.")
        return CheckDirections(suns.astype(np.float32), values, False, 1.0, spec.unit, day_step=day_step)

    from ladybug.viewsphere import view_sphere
    from .sky_patches import tregenza_patch_cells
    side = math.isqrt(settings.rays_per_patch)
    sub = side * side
    centres = np.array([[v.x, v.y, v.z] for v in view_sphere.tregenza_dome_vectors], dtype=np.float64)
    cells = tregenza_patch_cells()
    solid_angles = (cells[:, 1] - cells[:, 0]) * (cells[:, 3] - cells[:, 2])
    sin_alt = centres[:, 2]

    def slots(values, scale):
        patch_ids = np.repeat(np.arange(len(centres), dtype=np.int32), sub)
        return CheckDirections(centres[patch_ids].astype(np.float32), values[patch_ids] / sub, True, scale,
                               spec.unit, patch_ids, side)

    if settings.metric in ("solar_energy", "useful_solar_energy"):
        return slots(_patch_radiation(settings), 1.0)
    if settings.metric == "sky_component":
        values = solid_angles * (1.0 + 2.0 * sin_alt) / 3.0
    elif settings.metric == "cooling_sky":
        from .sky_patches import sky_emissivity_deficit
        values = solid_angles * sky_emissivity_deficit(settings.dew_point_celsius, settings.bliss_k, sin_alt)
    else:   # sky_view
        values = solid_angles / math.pi
    # Sub-rays are uniform in solid angle over their patch, so sin(altitude) averages (low + high) / 2 there.
    horizontal_cosine = sin_alt if side == 1 else (cells[:, 0] + cells[:, 1]) / 2.0
    horizontal = float(np.sum(values * horizontal_cosine))
    return slots(values, 100.0 / horizontal)


def sky_patch_values(directions: CheckDirections) -> Optional[np.ndarray]:
    """The value each sky patch carries (the sum of its slots' values), in the order of Ladybug's Tregenza patches; None when
    the directions are sun positions (sun_hours)."""
    if directions.patch_ids is None:
        return None
    return np.bincount(directions.patch_ids, weights=directions.values, minlength=int(directions.patch_ids.max()) + 1)


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
    ``directions.scale``.  With ``directions.sub_side`` above 1 a sky
    direction is traced as the carving's jittered sub-ray of its patch, the
    hash taking the point's index in *points* as its point id, and the
    cosine is that of the sub-ray.  A ray is blocked where it runs inside the
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
    # Sky sub-rays: the kernel draws each slot's direction from the patch's extent, the point's index here and
    # the slot's place in its patch, as the carving does.  With sub_side 1 the arrays are placeholders.
    sub_side = int(directions.sub_side)
    if sub_side > 1:
        from .sky_patches import tregenza_patch_cells
        cells, patch_ids = tregenza_patch_cells(), directions.patch_ids
    else:
        cells, patch_ids = np.zeros((1, 4)), np.zeros(1)
    wp_cells = wp.array(cells.astype(np.float32), dtype=wp.vec4, device=wp_device)
    wp_patch_ids = wp.array(np.asarray(patch_ids, dtype=np.int32), dtype=int, device=wp_device)
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
                    sub_side, wp_cells, wp_patch_ids,
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


def _no_points() -> CheckPoints:
    return CheckPoints(np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 4, 3)))


def _joined_points(parts) -> CheckPoints:
    """The points of *parts* (CheckPoints) one after another."""
    parts = [part for part in parts if part is not None and len(part.points)]
    if not parts:
        return _no_points()
    return CheckPoints(*(np.concatenate([getattr(part, name) for part in parts]) for name in ("points", "normals", "quads")))


def sample_triangles(mesh, spacing: float, seed: int = 0) -> CheckPoints:
    """Points spread over the triangles of *mesh*, about one per ``spacing**2`` of area: each triangle gets the whole part of its
    area over ``spacing**2`` and one more point with the chance of the rest, the points uniform in it, from a generator seeded
    with *seed* (a rerun gives the same points).  Each point has its triangle's normal and, for drawing, a square patch of side
    *spacing* in the triangle's plane centred on it.  For meshes whose flat pieces are mostly smaller than the spacing (a
    smoothed envelope), where :func:`sample_test_surfaces` would give almost no point."""
    rng = np.random.default_rng(seed)
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    if not len(triangles):
        return _no_points()
    expected = np.asarray(mesh.area_faces, dtype=np.float64) / (spacing * spacing)
    counts = np.floor(expected).astype(np.int64) + (rng.random(len(expected)) < expected % 1.0)
    owner = np.repeat(np.arange(len(triangles)), counts)
    if not len(owner):
        return _no_points()
    # Uniform in a triangle: fold the unit square's upper half onto the lower one.
    u, v = rng.random(len(owner)), rng.random(len(owner))
    folded = u + v > 1.0
    u[folded], v[folded] = 1.0 - u[folded], 1.0 - v[folded]
    a, b, c = triangles[owner, 0], triangles[owner, 1], triangles[owner, 2]
    points = a + (b - a) * u[:, None] + (c - a) * v[:, None]
    normals = np.asarray(mesh.face_normals, dtype=np.float64)[owner]
    # An axis in the plane: across the normal from up, or from x for a face that faces up or down.
    reference = np.where(np.abs(normals[:, 2:3]) > 0.9, [[1.0, 0.0, 0.0]], [[0.0, 0.0, 1.0]])
    first = np.cross(reference, normals)
    first /= np.linalg.norm(first, axis=1, keepdims=True)
    second = np.cross(normals, first)
    half = spacing / 2.0
    quads = np.stack([points + (sx * first + sy * second) * half
                      for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))], axis=1)
    return CheckPoints(points, normals, quads)


def points_inside(points, mesh, *, on_surface: float = 0.0, frame=None, device=None) -> np.ndarray:
    """Whether each of *points* lies inside the solid of *mesh* (bodies that touch or stack each count as their own solid), by
    the generalised winding number (``warp_kernels.points_inside_mesh_kernel``), or with *on_surface* above 0, within that
    distance of its surface (a point on a face plane, where the solid's edge cannot be told)."""
    import warp as wp
    from .warp_kernels import _near_mesh_kernel, points_inside_mesh_kernel, require_dda_backend
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if not len(points) or mesh is None or not len(mesh.faces):
        return np.zeros(len(points), dtype=bool)
    device = resolve_compute_device(device or "auto")
    require_dda_backend(device)
    wp_device = warp_device_name(device)
    frame = points.min(axis=0) if frame is None else np.asarray(frame, dtype=np.float64)
    bvh = wp.Mesh(points=wp.array((np.asarray(mesh.vertices, dtype=np.float64) - frame).astype(np.float32), dtype=wp.vec3,
                                  device=wp_device),
                  indices=wp.array(np.asarray(mesh.faces, dtype=np.int32).ravel(), dtype=wp.int32, device=wp_device),
                  support_winding_number=True)
    inside = wp.zeros(len(points), dtype=wp.uint8, device=wp_device)
    reach = float(np.linalg.norm(np.ptp(np.vstack([points, mesh.vertices]), axis=0))) * 2.0 + 1.0
    wp_points = wp.array((points - frame).astype(np.float32), dtype=wp.vec3, device=wp_device)
    wp.launch(points_inside_mesh_kernel, dim=len(points), device=wp_device, inputs=[bvh.id, wp_points, reach, inside])
    result = inside.numpy().astype(bool)
    if on_surface > 0.0:
        near = wp.zeros(len(points), dtype=wp.uint8, device=wp_device)
        wp.launch(_near_mesh_kernel, dim=len(points), device=wp_device, inputs=[bvh.id, wp_points, float(on_surface), near])
        result |= near.numpy().astype(bool)
    wp.synchronize_device(wp_device)
    return result


def _keep(points: CheckPoints, keep: np.ndarray) -> CheckPoints:
    return CheckPoints(points.points[keep], points.normals[keep], points.quads[keep])


def sample_geometry_faces(mesh, spacing: float, frame, clip=None, origin_offset: float = 0.01, device=None,
                          clip_depth: Optional[float] = None) -> CheckPoints:
    """The test points on the faces of a study's geometry (*mesh*, closed, facing out), in *frame* (see
    :func:`sample_test_surfaces`).

    The faces that face down are left out (:func:`without_downward_faces`: they stand on the ground or face it).  The rest is
    sampled as flat panels (:func:`flat_pieces`, :func:`sample_test_surfaces`) when at least half its area lies in flat
    pieces of at least ``spacing**2``, else triangle by triangle (:func:`sample_triangles`; a smoothed envelope).  A point
    whose position moved *origin_offset* along its normal lies inside *mesh*, or within half that of its surface, is on a
    face covered by another (the top of a floor under the next floor of a massing, or the foot of the wall above it) and is
    dropped; with *clip* (the maximum volume, for the envelope and the massing), so is a point whose position moved *clip_depth*
    (default *origin_offset*) against its normal lies outside *clip* and not within half *origin_offset* of its surface: a face
    further past the maximum volume than that.  A study gives the geometry's surface tolerance (the voxel size), since a voxel
    envelope stands up to a voxel outside the maximum volume along its facades and roofs."""
    faces = without_downward_faces(mesh)
    if not len(faces.faces):
        return _no_points()
    pieces = flat_pieces(faces)
    piece_areas = np.array([part.area for part in pieces.split(only_watertight=False)]) if len(pieces.faces) else np.zeros(0)
    large = float(piece_areas[piece_areas >= spacing * spacing].sum())
    if large >= 0.5 * float(faces.area):
        try:
            points = sample_test_surfaces(pieces, spacing, frame)
        except Exception:      # InputError: no flat panel large enough
            points = _no_points()
    else:
        points = sample_triangles(faces, spacing)
    if not len(points.points):
        return points
    margin = origin_offset / 2.0
    keep = ~points_inside(points.points + points.normals * origin_offset, mesh, on_surface=margin, frame=frame, device=device)
    if clip is not None:
        depth = origin_offset if clip_depth is None else max(float(clip_depth), origin_offset)
        keep &= points_inside(points.points - points.normals * depth, clip, on_surface=margin, frame=frame, device=device)
    return _keep(points, keep)


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


def solar_check(
    test_surfaces,
    geometries,
    settings: CheckSettings,
    *,
    blocking=None,
    sampling_frame=None,
    out_dir: Union[str, Path, None] = None,
    device=None,
    summary_extra: Optional[dict] = None,
    geometry_points: Optional[CheckPoints] = None,
    reuse_points: Optional[tuple] = None,
) -> SolarCheckResult:
    """The check's metric per test point for each of *geometries*, and with none of them ("open").

    Samples *test_surfaces* (a mesh or a mesh file) every
    ``settings.sample_spacing`` meters (:func:`sample_test_surfaces`, in
    *sampling_frame*; None for none) and appends *geometry_points* (the points on a geometry's faces,
    :func:`sample_geometry_faces`) after them (or takes *reuse_points*, ``(points, geometry point count)`` read back from an
    earlier run whose surfaces and spacing were the same, and keeps its points file), then
    traces each geometry with :func:`evaluate_test_points`, clipped by its
    ``clip`` mesh and with its own surface tolerance.  *blocking* (meshes or
    mesh files, or None: the context and terrain), joined into one mesh,
    blocks in every column, "open" included.  The summary compares the
    other columns with the geometry named ``max_volume``.

    With *out_dir*, writes there ``check_points.npz`` (the points, normals
    and the corner quads of their patches, float32 relative to ``frame``),
    ``check_values.npz`` (one float32 array per column), for a sky
    metric ``check_sky.json`` (the value of each sky patch,
    :func:`sky_patch_values`; removed for sun hours) and last
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
    summary_extra : dict, optional
        Keys added to the summary as they are (see :func:`simulate_study`).
    """
    geometries = list(geometries)
    names = [geometry.name for geometry in geometries]
    if len(set(names)) != len(names) or OPEN_VARIANT in names:
        raise ValueError(f"solar_check: geometry names must be unique and not {OPEN_VARIANT!r}, got {names}")
    test_surface_path = str(test_surfaces) if isinstance(test_surfaces, (str, Path)) else None
    blocking_mesh, blocking_paths = join_blocking(blocking)
    device = resolve_compute_device(device or "auto")
    if reuse_points is not None:
        check_points, geometry_count = reuse_points
    else:
        geometry_points = geometry_points if geometry_points is not None else _no_points()
        surface_points = (sample_test_surfaces(test_surfaces, settings.sample_spacing, sampling_frame)
                          if test_surfaces is not None else _no_points())
        check_points = _joined_points([surface_points, geometry_points])
        geometry_count = len(geometry_points.points)
    if not len(check_points.points):
        from .errors import InputError
        raise InputError(f"No test points were sampled at a spacing of {settings.sample_spacing:g} m.")
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
        "geometry_point_count": int(geometry_count),
        "points_reused": reuse_points is not None,
        "sun_day_step": int(directions.day_step),
        "sample_spacing_m": float(settings.sample_spacing),
        "direction_count": int(len(directions.directions)),
        "device": str(device),
        "inputs": {
            "test_surfaces": file_fingerprint(test_surface_path),
            "blocking": [file_fingerprint(path) for path in blocking_paths],
            "weather": file_fingerprint(settings.epw_path) if settings.spec.needs_epw else None,
        },
        "blocking_triangles": int(len(blocking_mesh.faces)) if blocking_mesh is not None else 0,
        "columns": column_summaries,
        **(summary_extra or {}),
    }

    folder = None
    if out_dir is not None:
        folder = Path(out_dir)
        folder.mkdir(parents=True, exist_ok=True)
        summary_path = folder / SUMMARY_FILE
        summary_path.unlink(missing_ok=True)    # written last: a failed check leaves no summary
        if reuse_points is None:        # kept points are in the file already
            np.savez_compressed(
                folder / POINTS_FILE, frame=frame,
                points=(check_points.points - frame).astype(np.float32),
                normals=check_points.normals.astype(np.float32),
                quads=(check_points.quads - frame).astype(np.float32),
                geometry_point_count=np.int64(geometry_count))
        # Uncompressed: two float32 columns write in a fraction of the time compressing them takes (1.3 s on 1.5 million points).
        np.savez(folder / VALUES_FILE, **{name: array.astype(np.float32) for name, array in values.items()})
        patch_values = sky_patch_values(directions)
        if patch_values is None:
            (folder / SKY_FILE).unlink(missing_ok=True)
        else:
            (folder / SKY_FILE).write_text(json.dumps({"weights": patch_values.tolist()}), encoding="utf-8")
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

def run_geometries(max_volume_path, run_folder=None, fallback_voxel_size: float = 1.0, only: Optional[str] = None) -> list:
    """The geometries of a run to check: the maximum volume, and the carved envelope and the building massing of
    *run_folder* when they were built (none without a run folder); with *only* ("envelope" or "massing"), the maximum volume
    and that one alone, the others not read; with any other *only*, the maximum volume alone.

    The envelope and the massing are clipped by the maximum volume, with the voxel size of the analysis they were
    built from as their surface tolerance (*fallback_voxel_size* when the chain of manifests does not tell it;
    :func:`check_files.run_geometry_files`, which the service reads too).
    """
    from .io import load_mesh
    max_volume = load_mesh(str(max_volume_path))
    geometries = [CheckGeometry("max_volume", "Maximum volume", max_volume, path=str(max_volume_path))]
    if only is not None and only not in ("envelope", "massing"):
        return geometries
    for found in run_geometry_files(run_folder, fallback_voxel_size, report_unusable=only is None, only=only):
        geometries.append(CheckGeometry(found.name, found.label, load_mesh(str(found.path)), clip=max_volume,
                                        surface_tolerance=found.surface_tolerance, path=str(found.path)))
    return geometries


# --- one study of Simulate -----------------------------------------------------------------------------------------

def _refuse_too_many_points(test_surfaces, spacing: float, extra_area: float = 0.0) -> None:
    """Raise InputError when sampling *test_surfaces* (None for none) and *extra_area* m² more (a geometry's faces) every
    *spacing* m would give more than :data:`MAX_CHECK_POINTS` points (estimated from their area), naming the spacing that
    fits."""
    from .errors import InputError
    area = (float(test_surfaces.area) if test_surfaces is not None else 0.0) + float(extra_area)
    estimate = area / (spacing * spacing)
    if estimate <= MAX_CHECK_POINTS:
        return
    fitting = math.ceil(math.sqrt(area / MAX_CHECK_POINTS) * 100.0) / 100.0
    raise InputError(
        f"The test surfaces ({area:,.0f} m²) would need about {estimate:,.0f} test points at a spacing of "
        f"{spacing:g} m; a check takes at most {MAX_CHECK_POINTS:,}. A spacing of {fitting:g} m or more fits.")


def _paths_of(value) -> list:
    """A mesh path or a list of them as a list of strings; none for None."""
    if value is None:
        return []
    return [str(path) for path in value] if isinstance(value, (list, tuple)) else [str(value)]


def flat_pieces(mesh):
    """*mesh* with no vertex shared between its flat pieces (trimesh's facets, the adjacent coplanar faces, and each other face
    alone), the faces wound as they were.  :func:`sample_test_surfaces` samples each connected part that is flat and skips the
    others, so a closed body or a terrain gives points only once its pieces are apart."""
    import trimesh
    piece = np.full(len(mesh.faces), -1, dtype=np.int64)
    for index, facet in enumerate(mesh.facets):
        piece[facet] = index
    alone = piece < 0
    piece[alone] = len(mesh.facets) + np.arange(int(alone.sum()))
    keys = np.stack([np.repeat(piece, 3), np.asarray(mesh.faces).ravel()], axis=1)
    unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    return trimesh.Trimesh(vertices=np.asarray(mesh.vertices)[unique[:, 1]], faces=np.asarray(inverse).reshape(-1, 3),
                           process=False)


def without_downward_faces(mesh):
    """*mesh* without the faces that face down (the bottoms of the surroundings' bodies, which stand on the ground and would read
    no sun or sky, pulling a study's statistics down)."""
    keep = mesh.face_normals[:, 2] > DOWNWARD_NORMAL_Z
    return mesh.submesh([np.flatnonzero(keep)], append=True, repair=False) if not keep.all() else mesh


def ground_disc(centre_xy, radius: float, z: float, spacing: float):
    """A flat disc facing up at height *z*: a polygon inscribed in the circle of *radius* around *centre_xy*, with enough
    segments (at least :data:`GROUND_DISC_MIN_SEGMENTS`) that its edge lies within *spacing* of the circle.  The service gives
    it the compass ring's centre and radius, so the ground a study samples is the one the view draws."""
    import trimesh
    radius = float(radius)
    sagitta = min(max(float(spacing), 1e-6), radius)
    segments = max(GROUND_DISC_MIN_SEGMENTS, math.ceil(math.pi / math.acos(1.0 - sagitta / radius)))
    angles = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
    cx, cy = float(centre_xy[0]), float(centre_xy[1])
    rim = np.column_stack([cx + radius * np.cos(angles), cy + radius * np.sin(angles), np.full(segments, float(z))])
    vertices = np.vstack([[cx, cy, float(z)], rim])
    faces = np.column_stack([np.zeros(segments, dtype=np.int64), 1 + np.arange(segments), 1 + (np.arange(segments) + 1) % segments])
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def study_surfaces(test_surface_path, surfaces_from, max_volume, *, context_path=None, terrain_path=None, disc=None,
                   spacing: float = 0.5):
    """The surfaces a Simulate study samples, joined into one mesh: its test surface file when it has one, and each source of
    *surfaces_from*: ``"context"`` the context files, their closed bodies turned to face out and without the faces that face
    down (:func:`without_downward_faces`); ``"terrain"`` the terrain file,
    turned to face up when most of its area faces down; ``"ground"`` the disc *disc* (centre x, centre y, radius;
    :func:`ground_disc`, its edge within *spacing*) at the lowest z of *max_volume* (a mesh).  The
    context and the terrain are cut into their flat pieces (:func:`flat_pieces`).

    Raises
    ------
    InputError
        When a source has no file (or the ground no disc), or there is nothing to sample.
    """
    import trimesh
    from .errors import InputError
    from .io import load_mesh
    meshes = [] if test_surface_path is None else [load_mesh(str(test_surface_path))]
    for source in surfaces_from:
        if source == "context":
            paths = _paths_of(context_path)
            if not paths:
                raise InputError("The study samples the surroundings, but there is no surroundings file.")
            meshes += [flat_pieces(without_downward_faces(load_mesh(path, fix_normals=True))) for path in paths]
        elif source == "terrain":
            if terrain_path is None:
                raise InputError("The study samples the terrain, but there is no terrain file.")
            terrain = load_mesh(str(terrain_path))
            if float((terrain.face_normals[:, 2] * terrain.area_faces).sum()) < 0.0:
                terrain.invert()
            meshes.append(flat_pieces(terrain))
        elif source == "ground":
            if disc is None:
                raise InputError("The study samples the ground around the site, but it was given no ground disc.")
            cx, cy, radius = disc
            meshes.append(ground_disc((cx, cy), radius, float(max_volume.bounds[0][2]), spacing))
        else:
            raise InputError(f"'{source}' is not a surface a study can sample: use context, terrain or ground.")
    if not meshes:
        raise InputError("The study has no surface to sample: add study surface files, or choose the surroundings, the "
                         "terrain or the ground.")
    return meshes[0] if len(meshes) == 1 else trimesh.util.concatenate(meshes)


def simulate_study(
    test_surface_path,
    max_volume_path,
    settings: CheckSettings,
    *,
    run_folder=None,
    context_path=None,
    terrain_path=None,
    ground_disc=None,
    out_dir,
    voxel_size: float = 1.0,
    device=None,
    base_volume_path=None,
) -> SolarCheckResult:
    """Run one Simulate study: the check of its surfaces against a project's geometries, written to *out_dir*.

    The surfaces sampled are the test surface file (None for none) and the sources of ``settings.surfaces_from``
    (:func:`study_surfaces`: the context, the terrain, the ground around the maximum volume); the summary lists those
    sources under ``surfaces_from``; *ground_disc* (centre x, centre y, radius) is the ground's disc.  The columns are "open"
    and the geometry of ``settings.geometry``: ``max_volume``, ``base_volume`` (*base_volume_path*, the part of the maximum volume
    a base height keeps, design/base-height.md), or the carved ``envelope`` or ``massing`` of *run_folder*
    (:func:`run_geometries`; *voxel_size* is their surface tolerance when the manifests do not record it); "open" alone for
    ``none``.  The context and terrain files block in both columns.  The test points are sampled in the maximum volume's
    frame, its minimum corner rounded to 1 µm, as preprocessing samples
    them.

    The summary also records under ``fingerprints`` what the result was
    computed from, so the service can tell when it is out of date:
    ``test_surface``, ``max_volume``, ``geometries`` (the envelope's and
    massing's meshes, only those built), ``weather``, ``context``,
    ``terrain`` (each :func:`file_fingerprint`, None when absent), ``ground_disc`` (the disc rounded to a millimetre when the
    ground is sampled, else None) and
    ``settings_digest`` (:func:`check_settings.settings_digest`: the
    settings without the weather file's path, which ``weather`` records).

    Raises
    ------
    InputError
        When the surfaces would need more than :data:`MAX_CHECK_POINTS` points at the settings' spacing, when a source of
        ``surfaces_from`` has no file, when there is no surface to sample, or when ``settings.geometry`` is the envelope or the
        massing and *run_folder* has not built it.
    """
    from .errors import InputError
    from .io import load_optional_mesh
    built = run_geometries(max_volume_path, run_folder, voxel_size, only=settings.geometry)
    if settings.geometry == "base_volume":
        if base_volume_path is None or not Path(base_volume_path).is_file():
            raise InputError("The study traces the base volume, but the project has no base height.")
        from .io import load_mesh
        built.append(CheckGeometry("base_volume", "Base volume", load_mesh(str(base_volume_path)), path=str(base_volume_path)))
    max_volume = built[0]
    geometries = [geometry for geometry in built if geometry.name == settings.geometry]
    if settings.geometry in ("envelope", "massing") and not geometries:
        raise InputError(f"The study traces the {settings.geometry}, but Carve has not built the {settings.geometry}.")
    frame = np.round(max_volume.mesh.bounds[0], 6)
    sampled = geometries[0] if settings.sample_geometry and geometries else None
    points_key = _points_key(settings, test_surface_path, max_volume_path, context_path, terrain_path, ground_disc, sampled)
    reuse = _kept_points(out_dir, points_key)
    has_other = test_surface_path is not None or bool(settings.surfaces_from)
    test_surfaces = (study_surfaces(test_surface_path, settings.surfaces_from, max_volume.mesh, context_path=context_path,
                                    terrain_path=terrain_path, disc=ground_disc, spacing=settings.sample_spacing)
                     if has_other or sampled is None else None)
    # The geometry's faces that face down are not sampled, so they do not count toward the estimate either.
    _refuse_too_many_points(test_surfaces, settings.sample_spacing,
                            extra_area=float(without_downward_faces(sampled.mesh).area) if sampled is not None else 0.0)
    geometry_points = (sample_geometry_faces(sampled.mesh, settings.sample_spacing, frame, clip=sampled.clip,
                                             origin_offset=settings.origin_offset, device=device,
                                             clip_depth=sampled.surface_tolerance)
                       if sampled is not None and reuse is None else None)
    loaded = [(path, load_optional_mesh(path, name)) for path, name in ((context_path, "context"), (terrain_path, "terrain"))]
    blocking = [mesh for _path, mesh in loaded if mesh is not None]
    digest = settings_digest(settings)
    fingerprints = {
        "test_surface": file_fingerprint(test_surface_path),
        "max_volume": file_fingerprint(max_volume_path),
        "geometries": {geometry.name: file_fingerprint(geometry.path) for geometry in geometries if geometry.name != "max_volume"},
        "weather": file_fingerprint(settings.epw_path) if settings.spec.needs_epw else None,
        "context": file_fingerprint(context_path),
        "terrain": file_fingerprint(terrain_path),
        "ground_disc": ([round(float(value), 3) for value in ground_disc]
                        if ground_disc is not None and "ground" in settings.surfaces_from else None),
        "settings_digest": digest,
    }
    # The meshes are passed loaded, so the summary's inputs are named here: the files read, those with triangles only.
    inputs = {"test_surfaces": fingerprints["test_surface"],
              "blocking": [file_fingerprint(path) for path, mesh in loaded if mesh is not None],
              "weather": fingerprints["weather"]}
    return solar_check(test_surfaces, geometries, settings, blocking=blocking, sampling_frame=frame, out_dir=out_dir,
                       device=device, summary_extra={"inputs": inputs, "fingerprints": fingerprints,
                                                     "surfaces_from": list(settings.surfaces_from),
                                                     "geometry": settings.geometry, "points_key": points_key},
                       geometry_points=geometry_points, reuse_points=reuse)


def _points_key(settings: CheckSettings, test_surface_path, max_volume_path, context_path, terrain_path, ground_disc, sampled) -> str:
    """A digest of what a study's test points are sampled from: the files (size and time, not path), the sources and the ground
    disc, the geometry whose faces are sampled with its clip and tolerance, the spacing and the origin offset. Equal keys give
    equal points, so a run can read them back (_kept_points) rather than sample again."""
    import hashlib

    def state(path):
        found = file_fingerprint(path) if path is not None else None
        return None if found is None else [found["size"], found["modified_ns"]]

    sources = list(settings.surfaces_from)
    key = {
        "test_surface": state(test_surface_path),
        "max_volume": state(max_volume_path),
        "sources": sources,
        "context": [state(path) for path in _paths_of(context_path)] if "context" in sources else None,
        "terrain": state(terrain_path) if "terrain" in sources else None,
        "ground_disc": [round(float(value), 3) for value in ground_disc] if "ground" in sources and ground_disc is not None else None,
        "geometry": None if sampled is None else [sampled.name, state(sampled.path), float(sampled.surface_tolerance)],
        "spacing": float(settings.sample_spacing),
        "origin_offset": float(settings.origin_offset),
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode("utf-8")).hexdigest()


def _kept_points(out_dir, points_key: str):
    """The points of the last run in *out_dir*, ``(CheckPoints, geometry point count)``, when its summary records *points_key*;
    None otherwise (no run, other surfaces or spacing, or a file that cannot be read)."""
    if out_dir is None:
        return None
    folder = Path(out_dir)
    try:
        summary = json.loads((folder / SUMMARY_FILE).read_text(encoding="utf-8"))
        if summary.get("points_key") != points_key:
            return None
        with np.load(folder / POINTS_FILE) as stored:
            frame = stored["frame"]
            points = CheckPoints(stored["points"].astype(np.float64) + frame, stored["normals"].astype(np.float64),
                                 stored["quads"].astype(np.float64) + frame)
            count = int(stored["geometry_point_count"]) if "geometry_point_count" in stored.files else 0
    except (OSError, ValueError, KeyError):
        return None
    return points, count
