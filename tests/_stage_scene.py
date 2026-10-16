"""A 10 m cube with a small horizontal test surface under it, in daylight
mode on the CPU (no EPW needed): the smallest scene that runs every stage."""
import numpy as np
import trimesh


def daylight_cube_config(tmp_path, **overrides):
    """Write the scene meshes into *tmp_path* and return a validated config
    whose run folder is ``tmp_path / "run"``."""
    from urbansolarcarver.io import save_mesh
    from urbansolarcarver.load_config import user_config
    volume = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    surface = trimesh.Trimesh(
        vertices=np.array([[-3, -3, 0], [3, -3, 0], [3, 3, 0], [-3, 3, 0]], dtype=float),
        faces=[[0, 1, 2], [0, 2, 3]],
    )
    volume_path, surface_path = tmp_path / "vol.ply", tmp_path / "srf.ply"
    save_mesh(volume, str(volume_path))
    save_mesh(surface, str(surface_path))
    settings = dict(
        max_volume_path=str(volume_path), test_surface_path=str(surface_path),
        out_dir=str(tmp_path / "run"), mode="daylight",
        voxel_size=1.0, grid_step=1.0, ray_length=50.0,
        min_voxels=1, min_face_count=1, device="cpu",
        ground_floor_height=3.0, floor_height=3.0, min_plate_dimension=2.0,
    )
    settings.update(overrides)
    return user_config(**settings)
