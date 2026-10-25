"""A box with two facades to protect, for the tests of chained criteria: the
smallest scene on which two criteria decide about different voxels (daylight
mode on the CPU, no EPW needed)."""
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh


@dataclass(frozen=True)
class ChainScene:
    volume: Path
    south: Path
    east: Path

    def config(self, folder, **values):
        """A daylight config on this scene whose run folder is *folder*."""
        from urbansolarcarver.load_config import user_config
        settings = dict(
            max_volume_path=str(self.volume), test_surface_path=str(self.south),
            out_dir=str(folder), mode="daylight", voxel_size=1.0, grid_step=1.0,
            ray_length=80.0, device="cpu", min_voxels=1, min_face_count=0,
        )
        settings.update({k: str(v) if isinstance(v, Path) else v for k, v in values.items()})
        return user_config(**settings)


def chain_scene(tmp_path) -> ChainScene:
    """A 30 x 12 x 20 m box at the origin, a facade 8 m south of it and one 8 m east
    of it, both 10 m high and facing the box (PLY files in *tmp_path*)."""
    volume = trimesh.creation.box(extents=(30.0, 12.0, 20.0))
    volume.apply_translation([0.0, 0.0, 10.0])
    lo, hi = volume.bounds
    y, x = lo[1] - 8.0, hi[0] + 8.0
    south = trimesh.Trimesh([[lo[0], y, 0], [hi[0], y, 0], [hi[0], y, 10], [lo[0], y, 10]],
                            [[0, 2, 1], [0, 3, 2]])
    east = trimesh.Trimesh([[x, lo[1], 0], [x, hi[1], 0], [x, hi[1], 10], [x, lo[1], 10]],
                           [[0, 2, 1], [0, 3, 2]])
    paths = {name: Path(tmp_path) / f"{name}.ply" for name in ("volume", "south", "east")}
    for name, mesh in (("volume", volume), ("south", south), ("east", east)):
        mesh.export(paths[name])
    return ChainScene(**paths)


def copy_preprocessing_with_occupancy(pre, occupancy, out):
    """Copy the preprocessing folder of *pre* to *out*, with its occupancy grid
    replaced by ``occupancy & original`` (same dtype). The manifest, run id
    included, is kept."""
    out = Path(out)
    shutil.copytree(pre.out_dir, out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    grid_path = out / manifest["voxel_grid_path"]
    original = np.load(grid_path)
    kept = np.asarray(occupancy, dtype=bool) & original.astype(bool)
    np.save(grid_path, kept.astype(original.dtype))
    return out
