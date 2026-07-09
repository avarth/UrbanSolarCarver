"""Smoke tests: every carving mode runs without crashing on a tiny mesh."""
import pytest
import yaml
from pathlib import Path


def _write_config(tmp_path, vol_path, srf_path, epw_path, mode, **extra):
    """Write a minimal YAML config and return loaded UserConfig."""
    from urbansolarcarver import load_config
    cfg_dict = {
        "max_volume_path": str(vol_path),
        "test_surface_path": str(srf_path),
        "out_dir": str(tmp_path / "out"),
        "mode": mode,
        "voxel_size": 2.0,
        "grid_step": 2.0,
        "ray_length": 50.0,
        "ray_batch_size": 50000,
        "threshold": 0.5,
        "apply_smoothing": False,
        "min_voxels": 1,
        "min_face_count": 1,
        "device": "cpu",
    }
    if epw_path:
        cfg_dict["epw_path"] = str(epw_path)
        cfg_dict.update(start_month=1, start_day=1, start_hour=8,
                        end_month=1, end_day=1, end_hour=16)
    cfg_dict.update(extra)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg_dict), encoding="utf-8")
    return load_config(str(cfg_path))


def _run_mode(tmp_path, vol_path, srf_path, epw_path, mode, **extra):
    """Run full pipeline for a mode and return export result."""
    from urbansolarcarver import run_pipeline
    cfg = _write_config(tmp_path, vol_path, srf_path, epw_path, mode, **extra)
    return run_pipeline(cfg, tmp_path / "pipeline_out")


# --- tilted_plane: no EPW needed, always runs ---

def test_smoke_tilted_plane(tmp_path, tmp_mesh_files):
    vol_path, srf_path = tmp_mesh_files
    result = _run_mode(
        tmp_path, vol_path, srf_path, epw_path=None,
        mode="tilted_plane", tilted_plane_angle_deg=45.0,
        threshold=None,
    )
    assert result.export_path.exists()
    import trimesh
    mesh = trimesh.load(str(result.export_path))
    assert len(mesh.vertices) > 0


# --- EPW-dependent modes ---

# Weighted modes use the relative carve_fraction threshold: a raw numeric
# cutoff like 0.5 is meaningless against cumulative Wh/m² scores (it would
# carve every voxel any ray touched, producing an empty envelope).
@pytest.mark.parametrize("mode,extra", [
    ("time-based", {}),
    ("irradiance", {"threshold": "carve_fraction", "carve_fraction": 0.7}),
    ("benefit", {"threshold": "carve_fraction", "carve_fraction": 0.7}),
    ("daylight", {"threshold": "carve_fraction", "carve_fraction": 0.7}),
])
def test_smoke_epw_modes(tmp_path, tmp_mesh_files, example_epw_path, mode, extra):
    vol_path, srf_path = tmp_mesh_files
    result = _run_mode(
        tmp_path, vol_path, srf_path, example_epw_path,
        mode=mode, **extra,
    )
    assert result.export_path.exists()
    import trimesh
    mesh = trimesh.load(str(result.export_path))
    assert len(mesh.vertices) > 0
