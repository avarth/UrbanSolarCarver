"""Jittered sky sub-rays: each sky-patch ray traced as rays_per_patch rays spread over its patch.

One ray per Tregenza patch centre leaves gaps 12° wide between the rays of a
test point, which far from the test surfaces show as bands of unscored voxels.
With rays_per_patch 4, 9 or 16 the kernels trace that many rays per patch, one
at a hashed place in each cell of equal solid angle, with that share of the
patch weight.
"""
import math

import numpy as np
import pytest
import torch
import trimesh

from urbansolarcarver.warp_kernels import dda_backend_available

REQUIRES_WARP_CPU = pytest.mark.skipif(not dda_backend_available(torch.device("cpu")),
                                       reason="Warp CPU unavailable")
CPU = torch.device("cpu")


def _settings(**overrides):
    from urbansolarcarver.load_config import user_config
    from urbansolarcarver.stage_settings import PreprocessingSettings
    values = dict(max_volume_path="unused", test_surface_path="unused", out_dir="unused",
                  mode="daylight", voxel_size=1.0, grid_step=1.0, ray_length=500.0, device="cpu")
    values.update(overrides)
    return PreprocessingSettings.from_config(user_config(**values))


# ------------------------------------------------------------------ the patch cells and directions
def test_patch_cells_hold_their_centres_and_cover_the_sky():
    from urbansolarcarver.sky_patches import (fetch_tregenza_patch_directions, tregenza_patch_cells,
                                              tregenza_solid_angles)
    cells = tregenza_patch_cells()
    centres = fetch_tregenza_patch_directions(CPU).numpy().astype(np.float64)
    az = np.mod(np.arctan2(centres[:, 0], centres[:, 1]) - cells[:, 2], 2 * np.pi)
    assert np.all((cells[:, 0] <= centres[:, 2]) & (centres[:, 2] <= cells[:, 1]))
    assert np.all(az[:-1] <= cells[:-1, 3] - cells[:-1, 2])
    omega = (cells[:, 1] - cells[:, 0]) * (cells[:, 3] - cells[:, 2])
    assert omega.sum() == pytest.approx(2 * np.pi)
    # Ladybug's solid angles are those of the same bands.
    np.testing.assert_allclose(omega, tregenza_solid_angles(), rtol=2e-3)


@REQUIRES_WARP_CPU
@pytest.mark.parametrize("side", [2, 3, 4])
def test_kernel_directions_match_the_numpy_definition_and_stay_in_their_cells(side):
    from urbansolarcarver.ray_tracing import SkySubRays, sky_sub_ray_directions
    from urbansolarcarver.sky_patches import fetch_tregenza_patch_cells, sub_ray_directions, tregenza_patch_cells
    cells = tregenza_patch_cells()
    point_ids = np.repeat(np.array([0, 1, 7, 123456]), 145)
    patch_ids = np.tile(np.arange(145), 4)
    reference = sub_ray_directions(point_ids, patch_ids, side, cells)
    kernel = sky_sub_ray_directions(torch.from_numpy(point_ids), torch.from_numpy(patch_ids),
                                    SkySubRays(side, fetch_tregenza_patch_cells(CPU))).numpy()
    np.testing.assert_allclose(kernel, reference, atol=2e-6)
    np.testing.assert_allclose(np.linalg.norm(kernel, axis=1), 1.0, atol=1e-6)

    count = side * side
    k = np.tile(np.arange(count), len(point_ids))
    c = cells[np.repeat(patch_ids, count)]
    u = (reference[:, 2] - c[:, 0]) / (c[:, 1] - c[:, 0]) * side
    v = np.mod(np.arctan2(reference[:, 0], reference[:, 1]) - c[:, 2], 2 * np.pi) / (c[:, 3] - c[:, 2]) * side
    assert np.all(np.floor(u) == k // side)
    assert np.all(np.floor(v) == k % side)


def test_directions_repeat_for_a_point_and_differ_between_points():
    from urbansolarcarver.sky_patches import sub_ray_directions, tregenza_patch_cells
    cells = tregenza_patch_cells()
    a = sub_ray_directions([5] * 145, np.arange(145), 2, cells)
    np.testing.assert_array_equal(a, sub_ray_directions([5] * 145, np.arange(145), 2, cells))
    b = sub_ray_directions([6] * 145, np.arange(145), 2, cells)
    assert np.all(np.linalg.norm(a - b, axis=1) > 1e-4)


def test_every_patch_a_surface_faces_in_part_keeps_its_ray():
    from urbansolarcarver.carving import _tregenza_facing_margin
    from urbansolarcarver.ray_tracing import generate_sky_patch_rays
    from urbansolarcarver.sky_patches import (fetch_tregenza_patch_directions, sub_ray_directions,
                                              tregenza_patch_cells)
    rng = np.random.default_rng(3)
    normals = rng.normal(size=(200, 3))
    normals[:, 2] = np.abs(normals[:, 2]) * rng.choice([-1, 0, 1], size=200)
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    dirs = fetch_tregenza_patch_directions(CPU)
    _, _, patch_ids, point_ids = generate_sky_patch_rays(np.zeros_like(normals), normals, dirs, CPU,
                                                         facing_margin=_tregenza_facing_margin())
    kept = set(zip(point_ids.tolist(), patch_ids.tolist()))
    # 64 directions per patch, regularly spread: any the surface faces must belong to a kept patch.
    dense = sub_ray_directions(np.zeros(145, int), np.arange(145), 8, tregenza_patch_cells())
    faced = (normals @ dense.T > 0).reshape(200, 145, 64).any(axis=2)
    assert set(zip(*np.nonzero(faced))) <= kept


# ------------------------------------------------------------------ settings
def test_rays_per_patch_defaults_to_4_and_accepts_square_counts():
    from pydantic import ValidationError
    assert _settings().rays_per_patch == 4
    for count in (1, 9, 16):
        assert _settings(rays_per_patch=count).rays_per_patch == count
    for count in (2, 0, 25):
        with pytest.raises(ValidationError):
            _settings(rays_per_patch=count)


def test_rays_per_patch_is_read_only_by_the_sky_patch_modes():
    from urbansolarcarver.mode_registry import MODES
    readers = {name for name, spec in MODES.items() if "rays_per_patch" in spec.extra_params}
    assert readers == {"irradiance", "benefit", "daylight", "radiative_cooling"}
    assert "rays_per_patch" in _settings().effective_values()
    assert "rays_per_patch" not in _settings(mode="tilted_plane", tilted_plane_angle_deg=45.0).effective_values()


# ------------------------------------------------------------------ what the sub-rays trace
def _access(points, normals, settings, occupancy=None, res=8, extent=8.0):
    from urbansolarcarver.access_evaluation import test_point_access_evaluation as evaluate
    occ = np.zeros((res,) * 3, bool) if occupancy is None else occupancy
    return evaluate(torch.from_numpy(occ), (0.0, 0.0, 0.0), extent, res,
                    np.asarray(points, np.float32), np.asarray(normals, np.float32), settings, device="cpu")


@REQUIRES_WARP_CPU
@pytest.mark.parametrize("count", [4, 16])
def test_a_wall_sees_exactly_half_of_the_overcast_sky(count):
    """The overcast sky depends on altitude only, so a wall faces half of it.
    The patches its plane cuts are split on their cell edges for even sides,
    so their sub-rays give exactly half; centre rays cannot split a patch."""
    roof, east, north = [4.0, 4.0, 0.5], [4.0, 4.0, 4.0], [4.0, 4.0, 4.0]
    normals = [[0, 0, 1], [1, 0, 0], [0, 1, 0]]
    accessible = _access([roof, east, north], normals, _settings(rays_per_patch=count)).test_point_accessible_weight
    assert accessible[0] == pytest.approx(1.0, abs=1e-5)
    np.testing.assert_allclose(accessible[1:], 0.5, atol=1e-5)
    centre = _access([roof, east, north], normals, _settings(rays_per_patch=1)).test_point_accessible_weight
    assert np.all(np.abs(centre[1:] - 0.5) > 0.01)


@REQUIRES_WARP_CPU
def test_sub_rays_close_the_gaps_between_patch_centres_far_away():
    """A strip of test points 40 m long and 2 m high looks at a 1 m thick
    wall 60 m away. Its patch-centre rays reach the wall in rows 12° apart,
    about 13 m at 60 m, while the strip's height spreads each row over only
    2 m, so the voxels between the rows score 0; 2 x 2 sub-rays per patch
    leave none in the wall's section facing the strip's middle."""
    from urbansolarcarver.carving import carve_with_sky_patch_rays
    from urbansolarcarver.voxelization import voxelize
    wall = trimesh.creation.box(extents=(1.0, 40.0, 60.0))
    wall.apply_translation([60.5, 0.0, 30.0])
    points = np.array([[0.0, y, z] for y in np.arange(-20.0, 20.01, 0.5) for z in np.arange(0.0, 2.01, 0.5)],
                      np.float32)
    normals = np.tile(np.array([[1.0, 0.0, 0.0]], np.float32), (len(points), 1))
    zero_counts = {}
    for count in (1, 4):
        settings = _settings(rays_per_patch=count)
        grid, origin, extent, res = voxelize(wall, settings, device=CPU)
        result = carve_with_sky_patch_rays(grid, origin, extent, res, points, normals, settings, None,
                                           ray_batch_size=0)
        scores = result.raw_voxel_scores.reshape(grid.shape)
        occupied = grid.numpy().astype(bool)
        cell = extent / res
        j = int(np.floor((0.0 - origin[1]) / cell))
        column = scores[:, j][occupied[:, j]]           # the wall's voxels in the plane y = 0, z from 0 to 60 m
        zero_counts[count] = int((column == 0).sum())
    assert zero_counts[1] > 10
    assert zero_counts[4] == 0


@REQUIRES_WARP_CPU
def test_scores_do_not_depend_on_the_batch_size():
    from urbansolarcarver.carving import carve_with_sky_patch_rays
    from urbansolarcarver.voxelization import voxelize
    box = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    box.apply_translation([20.0, 0.0, 5.0])
    points = np.array([[0.0, y, 1.0] for y in np.arange(-3.0, 3.01, 1.0)], np.float32)
    normals = np.tile(np.array([[1.0, 0.0, 0.0]], np.float32), (len(points), 1))
    settings = _settings(rays_per_patch=9)
    grid, origin, extent, res = voxelize(box, settings, device=CPU)
    runs = [carve_with_sky_patch_rays(grid, origin, extent, res, points, normals, settings, None,
                                      ray_batch_size=size).raw_voxel_scores for size in (0, 50, 777)]
    assert runs[0].sum() > 0
    np.testing.assert_allclose(runs[1], runs[0], rtol=1e-5, atol=1e-9)
    np.testing.assert_allclose(runs[2], runs[0], rtol=1e-5, atol=1e-9)


@REQUIRES_WARP_CPU
def test_return_rays_gives_the_traced_sub_rays():
    from urbansolarcarver.carving import carve_with_sky_patch_rays
    from urbansolarcarver.voxelization import voxelize
    box = trimesh.creation.box(extents=(4.0, 4.0, 4.0))
    box.apply_translation([10.0, 0.0, 2.0])
    points = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 1.0]], np.float32)
    normals = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]], np.float32)
    settings = _settings(rays_per_patch=4)
    grid, origin, extent, res = voxelize(box, settings, device=CPU)
    result = carve_with_sky_patch_rays(grid, origin, extent, res, points, normals, settings, None,
                                       return_rays=True, ray_batch_size=0)
    roof = result.ray_origins[:, 1] == 1.0
    assert roof.sum() == 145 * 4                         # a roof point faces every sub-ray
    wall = result.ray_directions[~roof]
    assert np.all(wall[:, 0] > 0) and 145 * 4 // 2 - 40 < len(wall) < 145 * 4 // 2 + 40


# ------------------------------------------------------------------ context
def _blocking(mesh):
    from urbansolarcarver.context_geometry import build_blocking_mesh
    return build_blocking_mesh([mesh], CPU)


@REQUIRES_WARP_CPU
def test_context_blocks_sub_rays_one_by_one():
    """A context wall east of a roof point hides the eastern sky up to about
    45°; with sub-rays the drop counts every sub-ray the point faces, and
    a closed context box around a second point blocks all of its."""
    from urbansolarcarver.carving import carve_with_sky_patch_rays
    from urbansolarcarver.voxelization import voxelize
    wall = trimesh.creation.box(extents=(2.0, 400.0, 10.0))
    wall.apply_translation([11.0, 0.0, 5.0])
    enclosure = trimesh.creation.box(extents=(4.0, 4.0, 4.0))
    enclosure.apply_translation([0.0, 40.0, 1.0])
    box = trimesh.creation.box(extents=(4.0, 4.0, 4.0))
    box.apply_translation([-20.0, 0.0, 2.0])
    points = np.array([[0.0, 0.0, 0.0], [0.0, 40.0, 0.0]], np.float32)
    normals = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]], np.float32)
    settings = _settings(rays_per_patch=4)
    grid, origin, extent, res = voxelize(box, settings, device=CPU)
    result = carve_with_sky_patch_rays(grid, origin, extent, res, points, normals, settings, None,
                                       ray_batch_size=0, blocking_mesh=_blocking(trimesh.util.concatenate([wall, enclosure])))
    drop = result.ray_drop
    assert drop.rays_total == 2 * 145 * 4
    assert drop.test_points_fully_blocked == 1
    # The enclosed point loses its whole sky (weight 1); the other the part behind the wall, about 45° high.
    lost_to_wall = drop.weight_dropped - 1.0
    assert drop.weight_total == pytest.approx(2.0, abs=1e-4)
    assert 0.08 < lost_to_wall < 0.2
