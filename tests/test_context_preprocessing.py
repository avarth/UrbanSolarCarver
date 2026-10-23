"""Context and terrain in preprocessing: the reduced occupancy, the ray drop, the footprint and the report."""
import json
import warnings

import numpy as np
import pytest
import trimesh

from urbansolarcarver import preprocessing, thresholding
from urbansolarcarver.errors import InputError
from urbansolarcarver.io import save_mesh
from urbansolarcarver.load_config import build_config

GEOREFERENCED = np.array([500_000.0, 4_500_000.0, 0.0])


def _box(lo, hi, offset=(0.0, 0.0, 0.0)):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    box = trimesh.creation.box(extents=hi - lo)
    box.apply_translation((lo + hi) / 2 + np.asarray(offset, float))
    return box


def _quad(corners, offset=(0.0, 0.0, 0.0)):
    """One flat panel, its normal by the right-hand rule over the corners in order."""
    return trimesh.Trimesh(vertices=np.asarray(corners, float) + np.asarray(offset, float),
                           faces=[[0, 1, 2], [0, 2, 3]], process=False)


def _ground_north(offset=(0.0, 0.0, 0.0)):
    """A horizontal test surface north of the volume, facing up."""
    return _quad([(0, 12, 0), (10, 12, 0), (10, 18, 0), (0, 18, 0)], offset)


def _south_neighbour(offset=(0.0, 0.0, 0.0)):
    """A tall, wide neighbour 20 m south of the volume, outside the grid: it hides the low southern sun and sky."""
    return _box((-60, -40, 0), (70, -20, 40), offset)


def _run(tmp_path, mode="daylight", surface=None, context=None, terrain=None, offset=(0.0, 0.0, 0.0),
         threshold=False, **over):
    """Preprocess the 10 m cube scene (CPU) and return (result, diagnostics summary, config)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, mesh in (("max_volume", _box((0, 0, 0), (10, 10, 10), offset)),
                       ("test_surface", surface if surface is not None else _ground_north(offset)),
                       ("context", context), ("terrain", terrain)):
        if mesh is not None:
            paths[name] = tmp_path / f"{name}.ply"
            save_mesh(mesh, str(paths[name]))
    values = dict(max_volume_path=str(paths["max_volume"]), test_surface_path=str(paths["test_surface"]),
                  out_dir=str(tmp_path / "run"), mode=mode, voxel_size=1.0, grid_step=1.0, ray_length=200.0,
                  margin_frac=0.2, device="cpu", min_voxels=1, min_face_count=1)  # voxel faces on whole metres
    if "context" in paths:
        values["context_path"] = str(paths["context"])
    if "terrain" in paths:
        values["terrain_path"] = str(paths["terrain"])
    if mode == "tilted_plane":
        values["tilted_plane_angle_deg"] = 45.0
    if mode == "time-based":
        values.update(start_month=12, start_day=21, start_hour=9, end_month=12, end_day=21, end_hour=15)
    values.update(over)
    conf = build_config(values)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = preprocessing(conf, tmp_path / "run" / "preprocessing")
        thr = thresholding(pre, conf, tmp_path / "run" / "thresholding") if threshold else None
    summary = json.loads((pre.out_dir / "diagnostics" / "diagnostic.json").read_text(encoding="utf-8"))
    return pre, summary, thr


def _scores(pre):
    return np.load(pre.out_dir / "scores.npy")


def _occupancy(pre):
    return np.load(pre.out_dir / "voxel_grid.npy")


def test_no_context_is_bit_for_bit_unchanged(tmp_path):
    plain, plain_summary, _ = _run(tmp_path / "plain")
    explicit, explicit_summary, _ = _run(tmp_path / "explicit", context_path=None, terrain_path=None)
    for name in ("scores.npy", "voxel_grid.npy", "footprint.json"):
        assert (plain.out_dir / name).read_bytes() == (explicit.out_dir / name).read_bytes(), name
    assert "context" not in plain_summary and "context" not in explicit_summary
    manifest = json.loads((plain.out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["context_path"] is None and manifest["terrain_path"] is None


def test_context_neighbour_drops_rays_and_lowers_scores(tmp_path):
    plain, _, _ = _run(tmp_path / "plain")
    shaded, summary, _ = _run(tmp_path / "shaded", context=_south_neighbour())
    report = summary["context"]
    assert report["context_used"] and not report["terrain_used"] and report["context_closed"]
    assert 0 < report["rays_dropped"] < report["rays_total"]
    assert 0.0 < report["weight_dropped_share"] < 1.0
    assert report["voxels_removed_by_context"] == 0 and report["voxels_removed_below_ground"] == 0
    assert report["test_points_fully_blocked"] == 0
    before, after = _scores(plain), _scores(shaded)
    assert (after <= before * (1 + 1e-5) + 1e-9).all()
    assert after.sum() < before.sum()
    np.testing.assert_array_equal(_occupancy(plain), _occupancy(shaded))
    manifest = json.loads((shaded.out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["context_path"].endswith("context.ply")


def test_time_based_drops_sun_rays(tmp_path, example_epw_path):
    plain, _, _ = _run(tmp_path / "plain", mode="time-based", epw_path=str(example_epw_path))
    shaded, summary, _ = _run(tmp_path / "shaded", mode="time-based", epw_path=str(example_epw_path),
                              context=_south_neighbour())
    assert summary["context"]["rays_dropped"] > 0
    assert (_scores(shaded) <= _scores(plain)).all()
    assert _scores(shaded).sum() < _scores(plain).sum()


def test_tilted_plane_only_loses_context_columns(tmp_path):
    chimney = _box((4, 4, 4), (6, 6, 6))
    _, _, plain_thr = _run(tmp_path / "plain", mode="tilted_plane", threshold=True)
    pre, summary, thr = _run(tmp_path / "chimney", mode="tilted_plane", context=chimney, threshold=True)
    plain_mask = np.load(plain_thr.out_dir / "mask.npy").astype(bool)
    mask = np.load(thr.out_dir / "mask.npy").astype(bool)
    occupancy = _occupancy(pre).astype(bool)
    removed_columns = ~occupancy.any(axis=2) & _occupancy_of_plain(tmp_path).any(axis=2)
    assert removed_columns.sum() == 4
    expected = plain_mask.copy()
    expected[removed_columns, :] = False
    np.testing.assert_array_equal(mask, expected)
    assert summary["context"]["rays_total"] == 0 and summary["context"]["rays_dropped"] == 0


def _occupancy_of_plain(tmp_path):
    return np.load(tmp_path / "plain" / "run" / "preprocessing" / "voxel_grid.npy").astype(bool)


def test_reduced_occupancy_is_saved(tmp_path):
    chimney = _box((4, 4, 4), (6, 6, 6))
    ground = _quad([(-100, -100, 2), (100, -100, 2), (100, 100, 2), (-100, 100, 2)])
    plain, _, _ = _run(tmp_path / "plain")
    pre, summary, _ = _run(tmp_path / "both", context=chimney, terrain=ground)
    before, after = _occupancy(plain).astype(bool), _occupancy(pre).astype(bool)
    report = summary["context"]
    assert report["voxels_removed_by_context"] == 4 * 10
    assert report["voxels_removed_below_ground"] == (100 - 4) * 2
    assert int(before.sum() - after.sum()) == 40 + 192
    assert report["volume_removed_m3"] == pytest.approx(232.0)
    assert report["share_of_max_volume_removed"] == pytest.approx(232 / 1000)
    assert summary["voxels_filled"] == 1000 - 232
    assert report["terrain_used"] and report["context_used"]
    assert (after <= before).all()
    footprint = json.loads((pre.out_dir / "footprint.json").read_text(encoding="utf-8"))
    import shapely
    from urbansolarcarver.floor_plates import footprint_from_dict
    area = shapely.union_all(footprint_from_dict(footprint)).area
    assert area == pytest.approx(100 - 4)


def test_context_covering_everything_is_an_input_error(tmp_path):
    with pytest.raises(InputError, match="context"):
        _run(tmp_path, context=_box((-5, -5, -5), (15, 15, 15)))


def test_terrain_covering_everything_is_an_input_error(tmp_path):
    with pytest.raises(InputError, match="terrain"):
        _run(tmp_path, terrain=_quad([(-100, -100, 20), (100, -100, 20), (100, 100, 20), (-100, 100, 20)]))


def test_inward_facing_test_surface_is_counted_fully_blocked(tmp_path):
    """A test panel on the west face of a neighbour, its normal pointing into the neighbour."""
    neighbour = _box((20, 0, 0), (30, 10, 10))
    panel = _quad([(20, 2, 2), (20, 8, 2), (20, 8, 8), (20, 2, 8)])  # normal +x, into the neighbour
    assert panel.face_normals[0][0] > 0.99
    _, summary, _ = _run(tmp_path, surface=panel, context=neighbour)
    report = summary["context"]
    assert report["test_points_fully_blocked"] == summary["test_surface_points"] > 0
    assert report["rays_dropped"] == report["rays_total"] > 0


def test_facade_on_its_own_context_building_is_not_blocked(tmp_path):
    """A test panel on the west face of a neighbour, facing out (west), toward the max volume."""
    neighbour = _box((20, 0, 0), (30, 10, 10))
    panel = _quad([(20, 8, 2), (20, 2, 2), (20, 2, 8), (20, 8, 8)])  # normal -x, out of the neighbour
    assert panel.face_normals[0][0] < -0.99
    _, summary, _ = _run(tmp_path, surface=panel, context=neighbour)
    assert summary["context"]["test_points_fully_blocked"] == 0
    assert summary["context"]["rays_dropped"] == 0


def test_georeferenced_scene_matches_the_scene_at_origin(tmp_path):
    at_origin, _, _ = _run(tmp_path / "origin", context=_south_neighbour(),
                           terrain=_quad([(-100, -100, 2), (100, -100, 2), (100, 100, 2), (-100, 100, 2)]))
    far, summary, _ = _run(tmp_path / "far", context=_south_neighbour(GEOREFERENCED),
                           surface=_ground_north(GEOREFERENCED), offset=GEOREFERENCED,
                           terrain=_quad([(-100, -100, 2), (100, -100, 2), (100, 100, 2), (-100, 100, 2)],
                                         GEOREFERENCED))
    np.testing.assert_array_equal(_occupancy(at_origin), _occupancy(far))
    near, moved = _scores(at_origin), _scores(far)
    np.testing.assert_allclose(moved, near, rtol=1e-4, atol=1e-6 * float(near.max()))
    assert summary["context"]["rays_dropped"] > 0


def test_open_context_warns_context_not_closed(tmp_path):
    open_box = _south_neighbour()
    open_box.update_faces(np.arange(len(open_box.faces)) >= 2)  # one side removed
    assert not open_box.is_watertight
    pre, summary, _ = _run(tmp_path, context=open_box)
    assert "context_not_closed" in [issue.code for issue in pre.issues]
    assert summary["context"]["context_closed"] is False


def test_run_report_has_a_context_block(tmp_path):
    from urbansolarcarver.api_core._reporting import generate_run_report
    pre, _, thr = _run(tmp_path, context=_south_neighbour(), threshold=True)
    (tmp_path / "report").mkdir()
    text = generate_run_report(tmp_path / "report", pre.out_dir, thr.out_dir).read_text(encoding="utf-8")
    assert "Context and terrain" in text
    assert "Rays dropped" in text


def test_run_report_without_context_has_no_context_block(tmp_path):
    from urbansolarcarver.api_core._reporting import generate_run_report
    pre, _, thr = _run(tmp_path, threshold=True)
    (tmp_path / "report").mkdir()
    text = generate_run_report(tmp_path / "report", pre.out_dir, thr.out_dir).read_text(encoding="utf-8")
    assert "Context and terrain" not in text
