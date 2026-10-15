"""The massing stage end to end on small synthetic scenes (CPU)."""
import json
import warnings

import numpy as np
import pytest
import trimesh
import yaml


def _run_upstream(tmp_path, volume, voxel=1.0, **cfg_over):
    """Preprocess and threshold *volume* (daylight mode, CPU); returns (cfg_path, thr_dir)."""
    from urbansolarcarver import preprocessing, thresholding
    from urbansolarcarver.load_config import load_config
    vol_path = tmp_path / "max_volume.ply"
    volume.export(vol_path)
    lo, hi = volume.bounds
    y = lo[1] - 8.0   # a facade 8 m south of the volume, facing it
    srf = trimesh.Trimesh([[lo[0], y, 0], [hi[0], y, 0], [hi[0], y, 10], [lo[0], y, 10]],
                          [[0, 2, 1], [0, 3, 2]])
    srf_path = tmp_path / "surface.ply"
    srf.export(srf_path)
    cfg = dict(max_volume_path=str(vol_path), test_surface_path=str(srf_path),
               out_dir=str(tmp_path / "out"), mode="daylight", voxel_size=voxel,
               grid_step=voxel, ray_length=80.0, device="cpu", min_voxels=1, min_face_count=0)
    cfg.update(cfg_over)
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))
    conf = load_config(str(cfg_path))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = preprocessing(conf, tmp_path / "out" / "preprocessing")
        thr = thresholding(pre, conf, tmp_path / "out" / "thresholding")
    return cfg_path, thr.out_dir


def _set_mask(thr_dir, fn):
    """Replace mask.npy with fn(occupancy) for deterministic tests."""
    man = json.loads((thr_dir / "manifest.json").read_text())
    pre = json.loads(open(man["upstream_manifest"]).read())
    occ = np.load(pre["voxel_grid_path"]).astype(bool)
    np.save(man["mask_path"], fn(occ))


def _box(extents, center_xy=(0.0, 0.0), z0=0.0):
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation([center_xy[0], center_xy[1], z0 + extents[2] / 2])
    return mesh


def _massing(cfg_path, thr_dir, out, **over):
    from urbansolarcarver import massing
    from urbansolarcarver.load_config import load_config
    conf = load_config(str(cfg_path), [f"{k}={v}" for k, v in over.items()])
    return massing(thr_dir, conf, out)


def test_full_envelope_gives_every_floor_the_footprint(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    res = _massing(cfg, thr, tmp_path / "out" / "massing")
    assert len(res.floor_areas) == 6            # 0-5, then five 3 m floors up to 20 m
    assert res.total_floor_area == pytest.approx(6 * 30 * 12, rel=1e-6)
    data = json.loads(res.plates_path.read_text())
    assert len(data["plates"]) == res.n_plates == 6
    # trimesh merges material-less OBJ objects on load: count them in the file,
    # and check each closed body without merging vertices across objects.
    text = res.mesh_path.read_text(encoding="utf-8")
    assert sum(line.startswith("o floor_") for line in text.splitlines()) == 6
    bodies = trimesh.load(res.mesh_path, force="mesh", process=False).split(only_watertight=False)
    assert len(bodies) == 6 and all(b.is_watertight for b in bodies)


def test_georeferenced_outlines_land_on_the_footprint(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20], center_xy=(500000.0, 4200000.0)))
    _set_mask(thr, lambda occ: occ)
    res = _massing(cfg, thr, tmp_path / "out" / "massing")
    outline = np.array(json.loads(res.plates_path.read_text())["plates"][0]["outline"])
    assert np.allclose(outline.min(0), [499985.0, 4199994.0], atol=0.01)
    assert np.allclose(outline.max(0), [500015.0, 4200006.0], atol=0.01)


def test_raised_part_warns_and_follows_stacking(tmp_path):
    low = _box([12, 12, 20], center_xy=(-10.0, 0.0))
    high = _box([12, 12, 20], center_xy=(10.0, 0.0), z0=2.0)
    cfg, thr = _run_upstream(tmp_path, trimesh.util.concatenate([low, high]))
    _set_mask(thr, lambda occ: occ)
    with pytest.warns(UserWarning, match="above the lowest point"):
        supported = _massing(cfg, thr, tmp_path / "s")
    plates = json.loads(supported.plates_path.read_text())["plates"]
    assert all(np.array(p["outline"])[:, 0].max() < 0 for p in plates)    # only the low block
    with pytest.warns(UserWarning, match="above the lowest point"):
        free = _massing(cfg, thr, tmp_path / "f", plate_stacking="free")
    plates = json.loads(free.plates_path.read_text())["plates"]
    assert any(np.array(p["outline"])[:, 0].min() > 0 for p in plates)    # high block too


def test_unreadable_outline_falls_back_to_voxels(tmp_path, monkeypatch):
    from urbansolarcarver import floor_plates as mg
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    monkeypatch.setattr(mg, "footprint_polygons", lambda mesh, offset_xy: [])
    with pytest.warns(UserWarning, match="voxel footprint"):
        res = _massing(cfg, thr, tmp_path / "m")
    assert res.n_plates == 6
    # The voxel footprint covers every column the box touches: between the
    # true 30 x 12 m and one voxel more on each axis (31 x 13 m).
    assert 30 * 12 - 1e-6 <= res.floor_areas[0] <= 31 * 13 + 1e-6


def test_nothing_buildable_gives_valid_empty_outputs(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))

    def low_only(occ):
        z = np.flatnonzero(occ.any(axis=(0, 1)))
        mask = occ.copy()
        mask[:, :, z.min() + 3:] = False      # 3 m left: lower than the 5 m ground floor
        return mask
    _set_mask(thr, low_only)
    with pytest.warns(UserWarning, match="no floor plates"):
        res = _massing(cfg, thr, tmp_path / "m", plate_tolerance=0.0)
    assert res.n_plates == 0 and res.total_floor_area == 0.0
    assert json.loads(res.plates_path.read_text())["plates"] == []
    assert res.mesh_path.is_file()


def test_part_thinner_than_the_minimum_builds_nothing(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 2, 20]))
    _set_mask(thr, lambda occ: occ)
    with pytest.warns(UserWarning, match="no floor plates"):
        res = _massing(cfg, thr, tmp_path / "m")
    assert res.n_plates == 0


def test_uses_the_preprocessing_voxel_size(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    a = _massing(cfg, thr, tmp_path / "a")
    b = _massing(cfg, thr, tmp_path / "b", voxel_size=2.0)       # config differs from the run
    assert a.floor_areas == pytest.approx(b.floor_areas)
    with pytest.raises(ValueError, match="min_plate_dimension"):
        _massing(cfg, thr, tmp_path / "c", voxel_size=0.5, grid_step=0.5, min_plate_dimension=0.5)


def test_run_report_has_a_massing_section(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    _massing(cfg, thr, tmp_path / "out" / "massing")
    report = (tmp_path / "out" / "run_report.md").read_text(encoding="utf-8")
    assert "## Massing" in report and "Total floor area" in report


def test_uneven_base_still_builds_plates(tmp_path):
    vol = _box([30, 12, 20])
    v = vol.vertices.copy()
    low = v[:, 2] < 1e-9
    v[low, 2] -= 0.01 * (v[low, 0] + 15)          # 0.3 m over 30 m
    vol.vertices = v
    cfg, thr = _run_upstream(tmp_path, vol)
    _set_mask(thr, lambda occ: occ)
    res = _massing(cfg, thr, tmp_path / "m")
    assert res.floor_areas[0] == pytest.approx(30 * 12, rel=0.02)


def test_outline_not_matching_the_voxels_falls_back(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    other = tmp_path / "other.ply"
    _box([30, 12, 20], center_xy=(25.0, 0.0)).export(other)    # a different, shifted volume
    with pytest.warns(UserWarning, match="does not match"):
        res = _massing(cfg, thr, tmp_path / "m", max_volume_path=str(other))
    assert res.n_plates == 6
