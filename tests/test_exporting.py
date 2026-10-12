"""Exporting stage: runs preprocessing and thresholding on a 10 m cube (daylight
mode, no EPW needed), then checks the exported mesh and its diagnostics."""
import json

import numpy as np
import pytest
import trimesh

# Far from the origin with non-round decimals, like a model in UTM
# coordinates.  float32 spacing is 0.03 m at x and 0.5 m at y here.
_UTM_OFFSET = np.array([500_000.37, 4_200_000.81, 50.0])


def _run_to_thresholding(tmp_path, offset):
    from urbansolarcarver import preprocessing, thresholding
    from urbansolarcarver.io import save_mesh
    from urbansolarcarver.load_config import user_config
    volume = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    volume.apply_translation(offset)
    surface = trimesh.Trimesh(
        vertices=np.array([[-3, -3, 0], [3, -3, 0], [3, 3, 0], [-3, 3, 0]], dtype=float) + offset,
        faces=[[0, 1, 2], [0, 2, 3]],
    )
    vol_path, srf_path = tmp_path / "vol.ply", tmp_path / "srf.ply"
    # save_mesh writes double-precision PLY (trimesh's export uses float32).
    save_mesh(volume, str(vol_path))
    save_mesh(surface, str(srf_path))
    cfg = user_config(
        max_volume_path=str(vol_path), test_surface_path=str(srf_path),
        out_dir=str(tmp_path / "run"), mode="daylight",
        voxel_size=1.0, grid_step=1.0, ray_length=50.0,
        min_voxels=1, min_face_count=1, device="cpu",
    )
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
    from urbansolarcarver import exporting
    cfg, thr = _run_to_thresholding(tmp_path, np.zeros(3))
    result = exporting(thr, cfg, tmp_path / "run" / "exporting")

    assert result.export_path.name == "export.ply"
    diag = json.loads((tmp_path / "run" / "exporting" / "diagnostics" / "diagnostic.json")
                      .read_text(encoding="utf-8"))
    assert diag["voxels_original"] == diag["voxels_retained"] + diag["voxels_removed"]
    assert diag["voxels_removed_by_cleanup"] >= 0
    # The run report goes into the run folder when out_dir is <run>/exporting.
    assert (tmp_path / "run" / "run_report.md").is_file()
