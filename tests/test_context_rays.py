"""Rays against the context and terrain meshes: the blocking mesh and the per-ray blocked mask."""
import numpy as np
import pytest
import torch
import trimesh

from urbansolarcarver.context_geometry import build_blocking_mesh
from urbansolarcarver.ray_tracing import mesh_blocks_rays

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
RAY_LENGTH = 3000.0


def _box(lo, hi):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    box = trimesh.creation.box(extents=hi - lo)
    box.apply_translation((lo + hi) / 2)
    return box


def _blocked(meshes, point, normal, directions):
    """The blocked mask of rays from one test point in *directions*."""
    blocking = build_blocking_mesh(meshes, DEVICE)
    directions = np.asarray(directions, dtype=np.float32).reshape(-1, 3)
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    n = len(directions)
    origins = torch.tensor(np.tile(np.asarray(point, np.float32), (n, 1)), device=DEVICE)
    normals = torch.tensor(np.asarray(normal, np.float32).reshape(1, 3), device=DEVICE)
    point_ids = torch.zeros(n, dtype=torch.int64, device=DEVICE)
    mask = mesh_blocks_rays(blocking, origins, torch.tensor(directions, device=DEVICE), point_ids, normals,
                            RAY_LENGTH)
    assert mask.dtype == torch.bool and mask.shape == (n,)
    return mask.cpu().numpy()


def _hemisphere(normal, count=200, seed=0):
    rng = np.random.default_rng(seed)
    directions = rng.normal(size=(count, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    return directions[directions @ np.asarray(normal, float) > 1e-3]


def test_no_meshes_gives_no_blocking_mesh():
    assert build_blocking_mesh([], DEVICE) is None


def test_box_between_point_and_direction_blocks():
    box = _box((5, -1, -1), (6, 1, 1))
    assert _blocked([box], (0, 0, 0), (1, 0, 0), [(1, 0, 0)]).tolist() == [True]


def test_ray_grazing_past_a_box_is_kept():
    box = _box((5, -1, -1), (6, 1, 1))
    # Toward (5, 1.2, 0): passes 0.2 m beside the box's +y face at its near edge.
    assert _blocked([box], (0, 0, 0), (1, 0, 0), [(5, 1.2, 0)]).tolist() == [False]


def test_ray_beyond_the_ray_length_is_kept():
    box = _box((5000, -1, -1), (5001, 1, 1))
    assert _blocked([box], (0, 0, 0), (1, 0, 0), [(1, 0, 0)]).tolist() == [False]


def test_point_on_a_context_face_is_not_blocked_by_that_face():
    box = _box((-10, -5, 0), (0, 5, 10))
    assert not _blocked([box], (0, 0, 5), (1, 0, 0), _hemisphere((1, 0, 0))).any()


def test_point_on_a_shared_face_of_two_bodies_is_not_blocked():
    """A facade on the face of one context body, coincident with a second copy of it (doubled geometry)."""
    box = _box((-10, -5, 0), (0, 5, 10))
    assert not _blocked([box, box.copy()], (0, 0, 5), (1, 0, 0), _hemisphere((1, 0, 0))).any()


def test_second_wing_blocks():
    """An L-shaped building: a ray from the inner facade of one wing toward the other wing is blocked."""
    wing_a = _box((0, 0, 0), (20, 8, 10))
    wing_b = _box((0, 8, 0), (8, 28, 10))
    point, normal = (14, 8, 5), (0, 1, 0)  # inner facade of wing A, facing +y
    blocked = _blocked([wing_a, wing_b], point, normal, [(-1, 1, 0), (0, 1, 0), (1, 1, 0)])
    assert blocked.tolist() == [True, False, False]


def test_open_sheet_blocks():
    sheet = trimesh.Trimesh(vertices=[(-50, -50, 10), (50, -50, 10), (50, 50, 10), (-50, 50, 10)],
                            faces=[[0, 1, 2], [0, 2, 3]], process=False)
    assert _blocked([sheet], (0.3, 0.2, 0), (0, 0, 1), [(0, 0, 1), (1, 0, 0.01)]).tolist() == [True, False]


def test_context_beyond_the_grid_blocks():
    box = _box((500, -20, -20), (520, 20, 20))
    assert _blocked([box], (0, 0, 0), (1, 0, 0), [(1, 0, 0), (1, 1, 0)]).tolist() == [True, False]


def test_many_points_use_their_own_normals():
    """Each ray's origin is offset along the normal of its own test point."""
    box = _box((-10, -5, 0), (0, 5, 10))
    blocking = build_blocking_mesh([box], DEVICE)
    # Point 0 on the box's +x face (normal +x), point 1 inside the box: its rays all hit the box.
    origins = torch.tensor([(0, 0, 5), (-5, 0, 5)], dtype=torch.float32, device=DEVICE)
    normals = torch.tensor([(1, 0, 0), (1, 0, 0)], dtype=torch.float32, device=DEVICE)
    directions = torch.tensor([(1, 0, 0), (1, 0, 0)], dtype=torch.float32, device=DEVICE)
    point_ids = torch.tensor([0, 1], dtype=torch.int64, device=DEVICE)
    mask = mesh_blocks_rays(blocking, origins, directions, point_ids, normals, RAY_LENGTH)
    assert mask.cpu().tolist() == [False, True]


def test_no_rays_gives_an_empty_mask():
    blocking = build_blocking_mesh([_box((0, 0, 0), (1, 1, 1))], DEVICE)
    empty = torch.zeros((0, 3), dtype=torch.float32, device=DEVICE)
    mask = mesh_blocks_rays(blocking, empty, empty, torch.zeros(0, dtype=torch.int64, device=DEVICE),
                            torch.zeros((1, 3), dtype=torch.float32, device=DEVICE), RAY_LENGTH)
    assert mask.shape == (0,) and mask.dtype == torch.bool
