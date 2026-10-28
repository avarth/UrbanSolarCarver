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
    pre_manifest = thr_dir / man["upstream_manifest"]
    pre = json.loads(pre_manifest.read_text())
    occ = np.load(pre_manifest.parent / pre["voxel_grid_path"]).astype(bool)
    np.save(thr_dir / man["mask_path"], fn(occ))


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


@pytest.mark.parametrize("mesh_format", ["ply", "stl", "glb"])
def test_massing_writes_the_plates_in_the_chosen_format_besides_the_obj(tmp_path, mesh_format):
    from urbansolarcarver.pydantic_schemas import MassingManifest
    # Georeferenced with fractional coordinates: float32 rounds y near 4 200 000 m to 0.5 m.
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20], center_xy=(500000.37, 4200000.61)))
    _set_mask(thr, lambda occ: occ)
    if mesh_format == "stl":
        with pytest.warns(UserWarning, match="plates.stl: STL stores float32 vertices"):
            res = _massing(cfg, thr, tmp_path / "m", final_mesh_format=mesh_format)
    else:
        res = _massing(cfg, thr, tmp_path / "m", final_mesh_format=mesh_format)
    assert res.mesh_path.name == "plates.obj" and res.mesh_path.is_file()      # the 3D view reads the named parts of the OBJ
    assert res.export_mesh_path == tmp_path / "m" / f"plates.{mesh_format}"
    manifest = MassingManifest.model_validate_json((tmp_path / "m" / "manifest.json").read_text())
    assert (manifest.mesh_path, manifest.export_mesh_path) == ("plates.obj", f"plates.{mesh_format}")
    plates_in_obj = trimesh.load(res.mesh_path, force="mesh", process=False)
    plates_in_export = trimesh.load(res.export_mesh_path, force="mesh", process=False)
    assert len(plates_in_export.faces) == len(plates_in_obj.faces)
    outlines = np.concatenate([plate["outline"] for plate in json.loads(res.plates_path.read_text())["plates"]])
    rounded = [issue for issue in res.issues if issue.code == "float32_coordinates"]
    if mesh_format == "stl":                                                         # float32 only: said so
        assert len(rounded) == 1 and "plates.stl" in rounded[0].message
    else:                                                                            # world coordinates kept
        assert not rounded
        assert np.allclose(plates_in_export.bounds[:, :2], [outlines.min(0), outlines.max(0)], atol=1e-3)
    if mesh_format == "glb":                                                         # a scene: one named part per plate
        assert sorted(trimesh.load(res.export_mesh_path).geometry) == [f"floor_{n}_plate_0" for n in range(6)]


def test_massing_in_obj_writes_one_mesh_file_named_twice_in_the_manifest(tmp_path):
    from urbansolarcarver.pydantic_schemas import MassingManifest
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    _massing(cfg, thr, tmp_path / "m", final_mesh_format="ply")
    res = _massing(cfg, thr, tmp_path / "m", final_mesh_format="obj")
    assert res.export_mesh_path == res.mesh_path
    manifest = MassingManifest.model_validate_json((tmp_path / "m" / "manifest.json").read_text())
    assert manifest.export_mesh_path == manifest.mesh_path == "plates.obj"
    assert sorted(path.name for path in (tmp_path / "m").glob("plates.*")) == ["plates.json", "plates.obj"]   # the PLY is gone


@pytest.mark.parametrize("mesh_format", ["ply", "stl", "glb"])
def test_nothing_buildable_gives_an_empty_mesh_in_the_chosen_format(tmp_path, mesh_format):
    cfg, thr = _run_upstream(tmp_path, _box([30, 2, 20]))
    _set_mask(thr, lambda occ: occ)
    with pytest.warns(UserWarning, match="no floor plates"):
        res = _massing(cfg, thr, tmp_path / "m", final_mesh_format=mesh_format)
    assert res.n_plates == 0 and res.mesh_path.is_file()
    assert len(trimesh.load(res.export_mesh_path, force="mesh").faces) == 0


def test_a_massing_manifest_from_before_the_export_mesh_reads_without_it():
    from urbansolarcarver.pydantic_schemas import MassingManifest
    manifest = MassingManifest.model_validate({
        "run_id": "r", "plates_path": "plates.json", "mesh_path": "plates.obj",
        "upstream_manifest": "../thresholding/manifest.json", "upstream_run_id": "t"})
    assert manifest.export_mesh_path is None


def test_georeferenced_outlines_land_on_the_footprint(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20], center_xy=(500000.0, 4200000.0)))
    _set_mask(thr, lambda occ: occ)
    res = _massing(cfg, thr, tmp_path / "out" / "massing")
    outline = np.array(json.loads(res.plates_path.read_text())["plates"][0]["outline"])
    assert np.allclose(outline.min(0), [499985.0, 4199994.0], atol=0.01)
    assert np.allclose(outline.max(0), [500015.0, 4200006.0], atol=0.01)


def test_the_straight_tolerance_follows_the_precision_of_the_footprint_coordinates():
    from shapely.geometry import box
    from urbansolarcarver.api_core.massing import _straight_tolerance
    footprint = [box(0.0, 0.0, 30.0, 12.0)]
    assert _straight_tolerance(footprint, (0.0, 0.0, 0.0), 1.0) == 0.01        # micrometre noise, not a real bend
    # float32 rounds coordinates near 500 000 m to 6 cm: four steps of it, at most half a voxel
    assert _straight_tolerance(footprint, (500000.0, 0.0, 0.0), 1.0) == pytest.approx(4 * 500030.0 * 2.0 ** -23)
    assert _straight_tolerance(footprint, (500000.0, 4200000.0, 0.0), 1.0) == 0.5


def test_a_six_degree_bend_in_a_facade_near_the_origin_stays_a_bend():
    from shapely.geometry import Polygon
    from urbansolarcarver import floor_plates as mg
    from urbansolarcarver.api_core.massing import _straight_tolerance
    turn = np.radians(6.0)
    bent = Polygon([(0, 0), (20, 0), (20, 15), (12.3, 15),
                    (12.3 - 7.7 * np.cos(turn), 15 - 7.7 * np.sin(turn)), (0, 15 - 7.7 * np.sin(turn))])
    facades, _ = mg.split_facades([bent], straight_tolerance=_straight_tolerance([bent], (0.0, 0.0, 0.0), 1.0))
    assert sum(not f.straight for f in facades) == 1     # 0.4 m off its chord over 15.4 m: below half a voxel, but real


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


def _sloped_terrain(tmp_path, rise):
    """A terrain rising *rise* m northward across the 12 m depth of a volume centred on y = 0 (0 m at its south edge)."""
    terrain = trimesh.Trimesh([[-40, -6, 0], [40, -6, 0], [40, 6, rise], [-40, 6, rise]], [[0, 1, 2], [0, 2, 3]])
    terrain_path = tmp_path / "terrain.ply"
    terrain.export(terrain_path)
    return str(terrain_path)


def test_on_sloped_ground_a_partly_buried_ground_floor_is_built_with_its_whole_plate(tmp_path):
    # User, 2026-10-28: "partly buried floor plates should be ok because logically this happens". The ground rises 3 m under the
    # 5 m ground floor: before, no module reaching into the ground was built, and stacked, nothing above: no plates at all.
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]), terrain_path=_sloped_terrain(tmp_path, 3.0))
    _set_mask(thr, lambda occ: occ)
    with warnings.catch_warnings():
        warnings.simplefilter("error")          # no "no floor plates fit", no "raised part"
        res = _massing(cfg, thr, tmp_path / "m")
    assert len(res.floor_areas) == 6
    assert res.floor_areas[0] == pytest.approx(30 * 12, rel=1e-6)          # the whole footprint, partly buried
    assert res.total_floor_area == pytest.approx(6 * 30 * 12, rel=1e-6)


def test_a_module_wholly_below_the_ground_is_not_built_and_the_ground_supports_the_floor_above(tmp_path):
    # The ground rises 9 m: the north part of the 0 to 5 m ground floor lies wholly below it, and the floors above stand on it.
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]), terrain_path=_sloped_terrain(tmp_path, 9.0))
    _set_mask(thr, lambda occ: occ)
    res = _massing(cfg, thr, tmp_path / "m")
    plates = json.loads(res.plates_path.read_text())["plates"]
    northmost = lambda floor: max(np.array(p["outline"])[:, 1].max() for p in plates if p["floor"] == floor)
    assert 0 < res.floor_areas[0] < 30 * 12                 # the buried north part is not built
    assert northmost(0) < northmost(2)
    assert res.floor_areas[2] == pytest.approx(30 * 12, rel=1e-6)       # supported by the ground, not by a plate below

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


def test_ground_floor_starts_at_the_lowest_point_of_a_volume_not_aligned_with_the_grid(tmp_path):
    """A box turned 30 degrees in plan: columns along its facades are filled only where a wall passes through them.

    At 19.5 m high, the lowest occupied voxel layer spans z -0.75..0.25: it lies mostly below the box's base and is
    filled only where rays hit the base, which they miss in those facade columns. The ground floor starts at the base
    (z 0), and that layer does not count against it.
    """
    volume = _box([30, 12, 19.5])
    volume.apply_transform(trimesh.transformations.rotation_matrix(np.radians(30.0), [0, 0, 1]))
    cfg, thr = _run_upstream(tmp_path, volume)
    preprocessing_folder = tmp_path / "out" / "preprocessing"
    pre_manifest = json.loads((preprocessing_folder / "manifest.json").read_text(encoding="utf-8"))
    occupancy = np.load(preprocessing_folder / pre_manifest["voxel_grid_path"]).astype(bool)
    lowest_layer = np.flatnonzero(occupancy.any(axis=(0, 1))).min()
    assert pre_manifest["origin"][2] + (lowest_layer + 0.5) * pre_manifest["voxel_size"] < 0.0    # the scene this test is about
    assert (occupancy.any(axis=2) & ~occupancy[:, :, lowest_layer]).any()
    _set_mask(thr, lambda occ: occ)
    res = _massing(cfg, thr, tmp_path / "m")
    ground_floor_plates = [p for p in json.loads(res.plates_path.read_text())["plates"] if p["floor"] == 0]
    assert ground_floor_plates and all(p["z_bottom"] == pytest.approx(0.0) for p in ground_floor_plates)
    assert res.floor_areas[0] == pytest.approx(30 * 12, rel=1e-6)


def test_the_top_floor_ends_at_or_below_the_highest_point_of_the_volume(tmp_path):
    """A 19.5 m box: the highest occupied voxel layer spans 19.25..20.25, and every column has it (rays hit the roof).

    Floors of 5 m, then 3 m, from z 0 end at 5, 8, 11, 14, 17 and 20 m; the floor 17..20 would stand 0.5 m above the box.
    """
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 19.5]))
    _set_mask(thr, lambda occ: occ)
    res = _massing(cfg, thr, tmp_path / "m")
    plates = json.loads(res.plates_path.read_text())["plates"]
    assert len(res.floor_areas) == 5 and all(area == pytest.approx(30 * 12, rel=1e-6) for area in res.floor_areas)
    assert max(p["z_top"] for p in plates) == pytest.approx(17.0)


def _remove_from_preprocessing_manifest(tmp_path, *field_names):
    """The preprocessing manifest as preprocessing wrote it before it recorded *field_names*; returns the manifest."""
    manifest_path = tmp_path / "out" / "preprocessing" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for field_name in field_names:
        del manifest[field_name]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_a_preprocessing_manifest_without_the_highest_point_keeps_the_top_of_the_highest_layer(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 19.5]))
    _set_mask(thr, lambda occ: occ)
    manifest = json.loads((tmp_path / "out" / "preprocessing" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["max_volume_highest_z"] == 19.5
    _remove_from_preprocessing_manifest(tmp_path, "max_volume_highest_z")
    res = _massing(cfg, thr, tmp_path / "m")
    plates = json.loads(res.plates_path.read_text())["plates"]
    assert len(res.floor_areas) == 6 and max(p["z_top"] for p in plates) == pytest.approx(20.0)


def test_a_preprocessing_manifest_without_the_lowest_point_starts_the_ground_floor_at_the_lowest_layer(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    preprocessing_folder = tmp_path / "out" / "preprocessing"
    assert json.loads((preprocessing_folder / "manifest.json").read_text(encoding="utf-8"))["max_volume_lowest_z"] == 0.0
    manifest = _remove_from_preprocessing_manifest(tmp_path, "max_volume_lowest_z", "max_volume_highest_z")
    occupancy = np.load(preprocessing_folder / manifest["voxel_grid_path"]).astype(bool)
    lowest_layer_bottom = manifest["origin"][2] + np.flatnonzero(occupancy.any(axis=(0, 1))).min() * manifest["voxel_size"]
    res = _massing(cfg, thr, tmp_path / "m")
    ground_floor_plates = [p for p in json.loads(res.plates_path.read_text())["plates"] if p["floor"] == 0]
    assert ground_floor_plates and all(p["z_bottom"] == pytest.approx(lowest_layer_bottom) for p in ground_floor_plates)


def _join_keeping_panels(mesh_paths, joined_path):
    """One PLY of several test surface files with vertex normals, so load_mesh keeps their panels apart."""
    meshes = [trimesh.load(path, force="mesh", process=False) for path in mesh_paths]
    joined = trimesh.Trimesh(np.vstack([mesh.vertices for mesh in meshes]),
                             np.vstack([mesh.faces + offset for mesh, offset in
                                        zip(meshes, np.cumsum([0] + [len(mesh.vertices) for mesh in meshes[:-1]]))]),
                             vertex_normals=np.vstack([mesh.vertex_normals for mesh in meshes]), process=False)
    joined.export(joined_path, vertex_normal=True)


@pytest.mark.slow
def test_new_building_example_builds_a_ground_floor_with_supported_stacking(tmp_path):
    """The packaged new_building example with the irradiance starting values (full year) and massing defaults."""
    from pathlib import Path
    from urbansolarcarver import api
    from urbansolarcarver.load_config import build_config_from_mode_starting_values
    from urbansolarcarver.run_context import RunContext
    example_folder = Path(__file__).resolve().parent.parent / "src" / "urbansolarcarver" / "example_projects"
    _join_keeping_panels([example_folder / "new_building" / "neighbor_roofs.ply",
                          example_folder / "new_building" / "neighbor_windows.ply"], tmp_path / "test_surfaces.ply")
    cfg = build_config_from_mode_starting_values({
        "mode": "irradiance", "max_volume_path": str(example_folder / "new_building" / "max_volume.ply"),
        "test_surface_path": str(tmp_path / "test_surfaces.ply"),
        "epw_path": str(example_folder / "weather" / "USA_CO_Golden-NREL.724666_TMY3.epw"), "out_dir": str(tmp_path / "run")})
    assert cfg.plate_stacking == "supported"
    api.run_pipeline(cfg, tmp_path / "run", produce=["massing"], context=RunContext())
    plates = json.loads((tmp_path / "run" / "massing" / "plates.json").read_text(encoding="utf-8"))
    ground_floor_plates = [plate for plate in plates["plates"] if plate["floor"] == 0]
    assert ground_floor_plates and all(plate["z_bottom"] == pytest.approx(0.0) for plate in ground_floor_plates)
    assert plates["floor_area_m2_per_floor"][0] > 0
    highest_z = json.loads((tmp_path / "run" / "preprocessing" / "manifest.json").read_text(encoding="utf-8"))["max_volume_highest_z"]
    assert max(plate["z_top"] for plate in plates["plates"]) <= highest_z + 1e-6


def test_massing_ignores_a_max_volume_file_edited_after_preprocessing(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    _box([36, 18, 20]).export(tmp_path / "max_volume.ply")      # edited in place
    res = _massing(cfg, thr, tmp_path / "m")
    assert res.floor_areas[0] == pytest.approx(30 * 12, rel=1e-6)


def test_preprocessing_saves_the_footprint_in_world_coordinates(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20], center_xy=(500000.0, 4200000.0)))
    saved = json.loads((tmp_path / "out" / "preprocessing" / "footprint.json").read_text(encoding="utf-8"))
    assert len(saved["polygons"]) == 1
    polygon = saved["polygons"][0]
    exterior = np.array(polygon["exterior"])
    assert polygon["holes"] == []
    assert np.allclose(exterior.min(0), [499985.0, 4199994.0], atol=1e-6)
    assert np.allclose(exterior.max(0), [500015.0, 4200006.0], atol=1e-6)
    manifest = json.loads((tmp_path / "out" / "preprocessing" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["footprint_path"] == "footprint.json"
    assert "max_volume_path" not in manifest


def test_footprint_not_matching_the_voxels_falls_back(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    # The saved footprint is replaced by a shifted one, as if from another volume.
    path = tmp_path / "out" / "preprocessing" / "footprint.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    for polygon in saved["polygons"]:
        polygon["exterior"] = [[x + 25.0, y] for x, y in polygon["exterior"]]
    path.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.warns(UserWarning, match="does not match"):
        res = _massing(cfg, thr, tmp_path / "m")
    assert res.n_plates == 6


def test_empty_footprint_falls_back_to_voxels(tmp_path, monkeypatch):
    from urbansolarcarver import floor_plates as mg
    monkeypatch.setattr(mg, "footprint_polygons", lambda mesh, offset_xy: [])
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))     # preprocessing writes []
    saved = json.loads((tmp_path / "out" / "preprocessing" / "footprint.json").read_text(encoding="utf-8"))
    assert saved == {"polygons": []}
    _set_mask(thr, lambda occ: occ)
    with pytest.warns(UserWarning, match="voxel footprint"):
        res = _massing(cfg, thr, tmp_path / "m")
    assert res.n_plates == 6
    # The voxel footprint covers every column the box touches: between the
    # true 30 x 12 m and one voxel more on each axis (31 x 13 m).
    assert 30 * 12 - 1e-6 <= res.floor_areas[0] <= 31 * 13 + 1e-6


def test_plates_avoid_removed_columns(tmp_path):
    """A chimney kept as context inside the max volume: no plate stands in the columns it took."""
    import shapely
    from shapely.geometry import Polygon, box
    chimney = _box([3, 3, 30], center_xy=(2.0, 0.5), z0=-5.0)
    context_path = tmp_path / "context.ply"
    chimney.export(context_path)
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]), context_path=str(context_path))
    _set_mask(thr, lambda occ: occ)
    res = _massing(cfg, thr, tmp_path / "out" / "massing")
    plates = json.loads(res.plates_path.read_text())["plates"]
    assert plates
    manifest = json.loads((tmp_path / "out" / "preprocessing" / "manifest.json").read_text())
    occ = np.load(tmp_path / "out" / "preprocessing" / manifest["voxel_grid_path"]).astype(bool)
    ox, oy = manifest["origin"][:2]
    size = manifest["voxel_size"]
    lo, hi = chimney.bounds
    taken = [box(ox + i * size, oy + j * size, ox + (i + 1) * size, oy + (j + 1) * size)
             for i, j in np.argwhere(~occ.any(axis=2))
             if lo[0] <= ox + (i + 0.5) * size <= hi[0] and lo[1] <= oy + (j + 0.5) * size <= hi[1]]
    assert len(taken) >= 6   # the columns whose centre lies inside the chimney (or on its faces)
    removed = shapely.union_all(taken)
    for plate in plates:
        assert Polygon(plate["outline"], plate["holes"]).intersection(removed).area < 1e-6
