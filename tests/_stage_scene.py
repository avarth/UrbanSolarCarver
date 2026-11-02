"""A 10 m cube (z -5 to 5) with a small horizontal test surface 1 m under it,
facing up into it, on the CPU: the smallest scene that runs every stage and
carves the columns above the surface. conftest.py's tiny_cube_mesh and
tiny_surface_mesh are these two meshes."""
import numpy as np
import trimesh


def cube_volume(offset=(0.0, 0.0, 0.0)):
    """The 10 m cube, moved by *offset*."""
    volume = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    volume.apply_translation(offset)
    return volume


def surface_under_cube(offset=(0.0, 0.0, 0.0)):
    """The 6 m test surface 1 m under the cube, facing up into it, moved by *offset*."""
    return trimesh.Trimesh(
        vertices=np.array([[-3, -3, -6], [3, -3, -6], [3, 3, -6], [-3, 3, -6]], dtype=float) + np.asarray(offset, float),
        faces=[[0, 1, 2], [0, 2, 3]],
    )


def cube_config(folder, offset=(0.0, 0.0, 0.0), **settings):
    """Write the scene meshes, moved by *offset*, into *folder* (vol.ply, srf.ply) and return a validated config on them:
    daylight, 1 m voxels and sample spacing, the CPU, the run folder ``folder / "run"``. *settings* change any of it."""
    from urbansolarcarver.io import save_mesh
    from urbansolarcarver.load_config import user_config
    volume_path, surface_path = folder / "vol.ply", folder / "srf.ply"
    # save_mesh writes double-precision PLY far from the origin (trimesh's export uses float32).
    save_mesh(cube_volume(offset), str(volume_path))
    save_mesh(surface_under_cube(offset), str(surface_path))
    values = dict(
        max_volume_path=str(volume_path), test_surface_path=str(surface_path),
        out_dir=str(folder / "run"), mode="daylight",
        voxel_size=1.0, grid_step=1.0, ray_length=50.0,
        min_voxels=1, min_face_count=1, device="cpu",
    )
    values.update(settings)
    return user_config(**values)


def daylight_cube_config(tmp_path, **overrides):
    """cube_config with the massing settings of the stage tests: a 3 m ground floor, 3 m floors and 2 m plate modules."""
    return cube_config(tmp_path, **{"ground_floor_height": 3.0, "floor_height": 3.0, "min_plate_dimension": 2.0, **overrides})
