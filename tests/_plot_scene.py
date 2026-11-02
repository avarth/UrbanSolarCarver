"""A plot, a street and one neighbour, for the tests of what a mode or a stage carves: the smallest scene that is
still an urban case. The maximum volume (the plot) is a 12 x 12 m box, 18 m high, standing on the ground at the
origin; a 10 m street runs along its north side; across it stands a 12 m high neighbour whose south facade, facing
the plot and the sun, is the protected test surface. The neighbour's mass behind that facade is the context, so the
scene has surroundings.

Carving for that facade takes the plot's north side, toward the neighbour, and from the top down; its south side and
its foot stay. ``PlotScene.voxels`` gives the voxels the maximum volume held, in the site's frame, and the ones a run
kept; ``assert_carves_the_north_side`` checks which side went. With ``north_deg`` the site is turned: model
north points that many degrees clockwise from +Y (the ``north_deg`` setting), and the street and the neighbour lie
on that side."""
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

PLOT_HALF_WIDTH = 6.0           # the plot spans -6 to 6 m across and along north
PLOT_HEIGHT = 18.0
STREET_WIDTH = 10.0
FACADE_NORTHING = PLOT_HALF_WIDTH + STREET_WIDTH    # the neighbour's south facade, 16 m north of the plot's centre
FACADE_HEIGHT = 12.0
FACADE_GAP = 0.05               # the facade quad stands this far in front of the neighbour's mass

# Settings shared by every mode on this scene: 1 m voxels and 1 m sample spacing (the largest a 1 m voxel allows;
# 13 x 13 points on the facade, its edges included).
SCENE_SETTINGS = dict(
    voxel_size=1.0, grid_step=1.0, ray_length=60.0, device="cpu",
    apply_smoothing=False, min_voxels=1, min_face_count=1,
)
# The EPW modes look at one January day, when the sun stays low in the south (Golden, Colorado, 39.7 N).
JANUARY_DAY = dict(start_month=1, start_day=1, start_hour=8, end_month=1, end_day=1, end_hour=16)


@dataclass(frozen=True)
class PlotVoxels:
    """The voxels the maximum volume held and which of them a run kept. ``site`` (N, 3) gives each voxel centre in
    the site's frame: across the plot (toward model east), north of the plot's centre, and height."""
    site: np.ndarray
    kept: np.ndarray

    @property
    def removed(self) -> np.ndarray:
        return ~self.kept

    @property
    def northing(self) -> np.ndarray:
        return self.site[:, 1]

    @property
    def height(self) -> np.ndarray:
        return self.site[:, 2]

    def removed_share(self, where) -> float:
        """The share of the voxels selected by the boolean array *where* that the run removed."""
        return float(self.removed[where].mean())


def assert_carves_the_north_side(voxels: PlotVoxels):
    """The neighbour's facade looks south across the street and up through the plot: the carving takes the plot's
    north side from the top down and keeps its south side and its foot. Measured 2026-11-02 at the scene's settings:
    the removed voxels lie 1.7 (tilted_plane, 30 degrees) to 4.1 m (daylight) further north on average than the kept
    ones; the top-north quarter loses 82 to 100 % of its voxels, the bottom-south quarter 0 to 6 %."""
    north, height = voxels.northing, voxels.height
    assert 0 < voxels.removed.sum() < len(voxels.removed)
    assert north[voxels.removed].mean() > north[voxels.kept].mean() + 1.0
    assert voxels.removed_share((north > 0) & (height > PLOT_HEIGHT / 2)) >= 0.75
    assert voxels.removed_share((north < 0) & (height < PLOT_HEIGHT / 2)) <= 0.15


@dataclass(frozen=True)
class PlotScene:
    volume: Path
    facade: Path
    context: Path
    north_deg: float = 0.0

    def config(self, folder, mode, epw_path=None, **values):
        """A validated config of *mode* on this scene whose run folder is *folder*. With *epw_path* the analysis
        period is ``JANUARY_DAY``; tilted_plane gets 45 degrees; *values* override any setting."""
        from urbansolarcarver.load_config import user_config
        settings = dict(
            max_volume_path=str(self.volume), test_surface_path=str(self.facade), context_path=str(self.context),
            out_dir=str(folder), mode=mode, north_deg=self.north_deg, **SCENE_SETTINGS,
        )
        if epw_path:
            settings.update(epw_path=str(epw_path), **JANUARY_DAY)
        if mode == "tilted_plane":
            settings["tilted_plane_angle_deg"] = 45.0
        settings.update({k: str(v) if isinstance(v, Path) else v for k, v in values.items()})
        return user_config(**settings)

    def voxels(self, thresholding_dir) -> PlotVoxels:
        """The voxels of a run, from its thresholding folder and the preprocessing folder that manifest names."""
        thresholding_dir = Path(thresholding_dir)
        manifest = json.loads((thresholding_dir / "manifest.json").read_text(encoding="utf-8"))
        pre_manifest_path = (thresholding_dir / manifest["upstream_manifest"]).resolve()
        pre = json.loads(pre_manifest_path.read_text(encoding="utf-8"))
        occupancy = np.load(pre_manifest_path.parent / pre["voxel_grid_path"]).astype(bool)
        mask = np.load(thresholding_dir / manifest["mask_path"]).astype(bool)
        centres = np.asarray(pre["origin"], float) + (np.argwhere(occupancy) + 0.5) * float(pre["voxel_size"])
        angle = np.radians(self.north_deg)
        east, north = np.array([np.cos(angle), -np.sin(angle)]), np.array([np.sin(angle), np.cos(angle)])
        site = np.column_stack([centres[:, :2] @ east, centres[:, :2] @ north, centres[:, 2]])
        return PlotVoxels(site, mask[occupancy])


def plot_scene(tmp_path, north_deg=0.0) -> PlotScene:
    """Write the plot, the neighbour's south facade and its mass as PLY files into *tmp_path*. With *north_deg*
    the street and the neighbour lie toward a model north turned that many degrees clockwise from +Y."""
    volume = trimesh.creation.box(extents=(2 * PLOT_HALF_WIDTH, 2 * PLOT_HALF_WIDTH, PLOT_HEIGHT))
    volume.apply_translation([0.0, 0.0, PLOT_HEIGHT / 2])
    x0, x1, y = -PLOT_HALF_WIDTH, PLOT_HALF_WIDTH, FACADE_NORTHING
    # Corners in this order give the normal -Y: the facade faces south, across the street to the plot.
    facade = trimesh.Trimesh([[x0, y, 0], [x1, y, 0], [x1, y, FACADE_HEIGHT], [x0, y, FACADE_HEIGHT]],
                             [[0, 1, 2], [0, 2, 3]])
    depth = 12.0
    neighbour = trimesh.creation.box(extents=(4 * PLOT_HALF_WIDTH, depth, FACADE_HEIGHT))
    neighbour.apply_translation([0.0, y + FACADE_GAP + depth / 2, FACADE_HEIGHT / 2])
    if north_deg:
        # Clockwise in plan is a negative angle about +Z.
        turn = trimesh.transformations.rotation_matrix(-np.radians(north_deg), [0, 0, 1])
        for mesh in (volume, facade, neighbour):
            mesh.apply_transform(turn)
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    paths = {name: Path(tmp_path) / f"{name}.ply" for name in ("volume", "facade", "context")}
    for name, mesh in (("volume", volume), ("facade", facade), ("context", neighbour)):
        mesh.export(paths[name])
    return PlotScene(**paths, north_deg=float(north_deg))
