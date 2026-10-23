"""The optional context and terrain inputs: config keys, path resolution, validation and loading."""
import numpy as np
import pytest
import trimesh
import yaml

from urbansolarcarver.errors import InputError, UrbanSolarCarverWarning
from urbansolarcarver.io import load_optional_mesh, validate_inputs
from urbansolarcarver.load_config import build_config, load_config
from urbansolarcarver.stage_settings import PreprocessingSettings


def _minimal_values(tmp_mesh_files, tmp_path):
    vol, srf = tmp_mesh_files
    return {"max_volume_path": str(vol), "test_surface_path": str(srf), "out_dir": str(tmp_path / "out"),
            "mode": "tilted_plane", "tilted_plane_angle_deg": 45.0}


def test_context_and_terrain_default_to_none(tmp_mesh_files, tmp_path):
    cfg = build_config(_minimal_values(tmp_mesh_files, tmp_path))
    assert cfg.context_path is None and cfg.terrain_path is None
    settings = PreprocessingSettings.from_config(cfg)
    assert settings.context_path is None and settings.terrain_path is None


def test_relative_context_paths_resolve_against_the_yaml_folder(tmp_mesh_files, tmp_path):
    folder = tmp_path / "sub"
    folder.mkdir()
    values = _minimal_values(tmp_mesh_files, tmp_path)
    values.update(context_path="ctx.ply", terrain_path="ground.ply")
    config_path = folder / "config.yaml"
    config_path.write_text(yaml.safe_dump(values), encoding="utf-8")
    cfg = load_config(str(config_path))
    assert cfg.context_path == str(folder / "ctx.ply")
    assert cfg.terrain_path == str(folder / "ground.ply")


@pytest.mark.parametrize("key", ["context_path", "terrain_path"])
def test_missing_context_file_is_an_input_error(tmp_mesh_files, tmp_path, key):
    values = _minimal_values(tmp_mesh_files, tmp_path)
    values[key] = str(tmp_path / "absent.ply")
    settings = PreprocessingSettings.from_config(build_config(values))
    with pytest.raises(InputError, match=key):
        validate_inputs(settings)


def test_empty_context_file_counts_as_absent(tmp_path):
    path = tmp_path / "empty.ply"
    trimesh.Trimesh(vertices=np.zeros((3, 3)), faces=np.zeros((0, 3), dtype=np.int64)).export(str(path))
    with pytest.warns(UrbanSolarCarverWarning, match="context"):
        assert load_optional_mesh(str(path), "context") is None
    assert load_optional_mesh(None, "context") is None


def test_context_mesh_loads(tmp_path):
    path = tmp_path / "ctx.ply"
    trimesh.creation.box(extents=(2, 2, 2)).export(str(path))
    mesh = load_optional_mesh(str(path), "context")
    assert len(mesh.faces) == 12
