"""Run USC end-to-end on a typology scene and load the artifacts."""
from __future__ import annotations

import warnings
from pathlib import Path

from oracle import Run
from typologies import Scene

PERIODS = {
    "winter_noon": dict(start_month=12, start_day=21, start_hour=10, end_month=12, end_day=21, end_hour=14),
    "equinox_day": dict(start_month=3, start_day=21, start_hour=8, end_month=3, end_day=21, end_hour=16),
    "heating_season": dict(start_month=11, start_day=1, start_hour=8, end_month=2, end_day=28, end_hour=17),
}

MODE_DEFAULTS = {
    "tilted_plane": dict(mode="tilted_plane", tilted_plane_angle_deg=45.0),
    "time-based": dict(mode="time-based", threshold=0, **PERIODS["winter_noon"]),
    "benefit": dict(mode="benefit", threshold="carve_fraction", carve_fraction=0.6,
                    balance_temperature=18.0, balance_offset=2.0, **PERIODS["heating_season"]),
    "irradiance": dict(mode="irradiance", threshold="carve_fraction", carve_fraction=0.6,
                       **PERIODS["equinox_day"]),
    "daylight": dict(mode="daylight", threshold="carve_fraction", carve_fraction=0.5),
}


def config(scene_files, out: Path, epw: str, mode: str, voxel: float = 2.0, **over) -> dict:
    vol, srf = scene_files
    cfg = dict(
        max_volume_path=str(vol), test_surface_path=str(srf), out_dir=str(out),
        voxel_size=voxel, grid_step=voxel, ray_length=200.0, min_altitude=5.0,
        min_voxels=1, min_face_count=0, diagnostics=False, diagnostic_plots=False,
        device="cpu",
        # Off unless a check asks for it: the export then equals the thresholded mask.
        carve_above=False,
    )
    cfg.update(MODE_DEFAULTS[mode])
    if MODE_DEFAULTS[mode].get("mode") not in ("tilted_plane", "daylight"):
        cfg["epw_path"] = epw
    cfg.update(over)
    return cfg


def run(scene: Scene, root: Path, epw: str, mode: str, **over) -> Run:
    from urbansolarcarver import exporting, preprocessing, thresholding
    from urbansolarcarver.load_config import user_config

    files = scene.write(root / "scene")
    cfg = config(files, root / "out", epw, mode, **over)
    conf = user_config(**cfg)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = preprocessing(conf, root / "out" / "preprocessing")
        thr = thresholding(pre, conf, root / "out" / "thresholding")
        exporting(thr, conf, root / "out" / "exporting")
    return Run.load(root / "out", cfg)
