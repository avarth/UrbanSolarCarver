"""Exporting stage: runs preprocessing and thresholding on a 10 m cube (daylight
mode, no EPW needed), then checks the exported mesh and its diagnostics."""
import json

import numpy as np
import pytest
import trimesh

# Far from the origin with non-round decimals, like a model in UTM
# coordinates.  float32 spacing is 0.03 m at x and 0.5 m at y here.
_UTM_OFFSET = np.array([500_000.37, 4_200_000.81, 50.0])


def _run_to_thresholding(tmp_path, offset, grid_step=1.0):
    from _stage_scene import cube_config
    from urbansolarcarver import preprocessing, thresholding
    cfg = cube_config(tmp_path, offset, grid_step=grid_step)
    pre = preprocessing(cfg, tmp_path / "run" / "preprocessing")
    thr = thresholding(pre, cfg, tmp_path / "run" / "thresholding")
    return cfg, thr


@pytest.mark.parametrize("offset", [np.zeros(3), _UTM_OFFSET], ids=["origin", "utm"])
def test_full_mask_exports_the_voxelized_volume_in_place(tmp_path, offset):
    """With every voxel kept, the mesh is the voxelized max volume: its bounds
    match the 10 m cube to within one voxel, also far from the origin."""
    from urbansolarcarver import exporting
    cfg, thr = _run_to_thresholding(tmp_path, offset)
    np.save(thr.mask_path, np.ones_like(np.load(thr.mask_path), dtype=bool))

    result = exporting(thr, cfg, tmp_path / "run" / "exporting")
    mesh = trimesh.load(result.export_path, force="mesh")
    expected = np.array([offset - 5.0, offset + 5.0])
    assert np.abs(mesh.bounds - expected).max() <= 1.0 + 1e-6
    # Corners lie on the 1 m voxel lattice, which (with the default margin)
    # starts half a voxel outside the cube.  float32 rounding would move
    # them off it by up to 0.25 m.
    rel = mesh.vertices - (offset - 5.5)
    assert np.abs(rel - np.round(rel)).max() < 1e-6


def test_diagnostics_and_report(tmp_path):
    """The diagnostics count the voxels the mesh is made of: a lone voxel added to the mask is removed by the cleanup,
    counted as such, and missing from the mesh volume and the report."""
    from scipy import ndimage
    from urbansolarcarver import exporting
    cfg, thr = _run_to_thresholding(tmp_path, np.zeros(3))
    occupancy = np.load(tmp_path / "run" / "preprocessing" / "voxel_grid.npy").astype(bool)
    mask = np.load(thr.mask_path)
    # A voxel none of whose 26 neighbours is kept: the cubic path's cleanup drops it (fewer than 2 neighbours).
    lone = tuple(np.argwhere(~ndimage.binary_dilation(mask, structure=np.ones((3, 3, 3))) & occupancy)[0])
    mask[lone] = True
    np.save(thr.mask_path, mask)
    kept_by_mask = int((mask & occupancy).sum())

    result = exporting(thr, cfg, tmp_path / "run" / "exporting")

    assert result.export_path.name == "export.ply"
    diag = json.loads((tmp_path / "run" / "exporting" / "diagnostics" / "diagnostic.json")
                      .read_text(encoding="utf-8"))
    assert diag["voxels_original"] == int(occupancy.sum())
    assert diag["voxels_removed_by_cleanup"] == 1
    assert diag["voxels_retained"] == kept_by_mask - 1
    assert diag["voxels_removed"] == diag["voxels_original"] - diag["voxels_retained"]
    # 1 m voxels: the closed mesh holds one cubic metre per retained voxel.
    mesh = trimesh.load(result.export_path, force="mesh")
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(diag["voxels_retained"] * 1.0 ** 3)
    assert diag["mesh_volume_m3"] == pytest.approx(mesh.volume)
    # The run report goes into the run folder when out_dir is <run>/exporting.
    report = (tmp_path / "run" / "run_report.md").read_text(encoding="utf-8")
    assert f"- **Mesh volume:** {diag['voxels_retained']:,.1f} m³" in report


def test_the_report_gives_the_sample_spacing_used_for_an_unset_grid_step(tmp_path):
    from urbansolarcarver import exporting
    cfg, thr = _run_to_thresholding(tmp_path, np.zeros(3), grid_step=None)       # half the 1 m voxel size
    exporting(thr, cfg, tmp_path / "run" / "exporting")
    assert "| Grid step | 0.5 m |" in (tmp_path / "run" / "run_report.md").read_text(encoding="utf-8")
