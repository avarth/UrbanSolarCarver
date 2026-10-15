"""Massing stage: stacked floor plates from the carved envelope.

Reads the thresholding manifest, builds floor plates that follow the
maximum volume's footprint (``urbansolarcarver.floor_plates``), and writes them
as ``plates.json`` (outlines in world coordinates) and ``plates.obj`` (one
closed prism per plate), with a manifest, diagnostics and the run report.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

import numpy as np
import shapely
import shapely.affinity

from .. import floor_plates as mg
from ..io import load_mesh
from ..load_config import user_config
from ..pydantic_schemas import MassingManifest, schema_to_json
from ._reporting import generate_run_report
from ._util import _ensure_out_dir, _resolve_cfg, ensure_diag, load_thresholded_grid, write_json

log = logging.getLogger(__name__)

# Share of occupied voxel columns allowed to lie more than one voxel outside
# the mesh footprint before the footprint is taken as not matching the voxel
# grid (another mesh, a shifted origin) and the voxel footprint is used.
FOOTPRINT_MISMATCH_SHARE = 0.05


@dataclass(frozen=True)
class MassingResult:
    """Immutable record returned by :func:`massing`; path-like to ``plates.json``."""
    out_dir: Path
    plates_path: Path
    mesh_path: Path
    floor_areas: List[float]
    total_floor_area: float
    n_plates: int

    def __fspath__(self) -> str:
        return str(self.plates_path)


def _footprint(conf, origin, columns, voxel_size):
    """Footprint polygons (local xy) and their source ("mesh" or "voxels").

    The mesh footprint is the maximum volume's plan projection.  It is used
    only when it matches the voxel grid: at most FOOTPRINT_MISMATCH_SHARE
    of the occupied columns may have their centre more than one voxel
    outside it.  Otherwise the voxel footprint is used, with a warning.
    """
    try:
        polygons = mg.footprint_polygons(load_mesh(conf.max_volume_path), origin[:2])
    except Exception as exc:  # unreadable or broken mesh
        log.warning("massing: could not project the maximum volume: %s", exc)
        polygons = []
    if not polygons:
        warnings.warn("massing: the maximum volume's footprint could not be read; "
                      "using the voxel footprint", UserWarning, stacklevel=3)
        return mg.footprint_from_columns(columns, voxel_size), "voxels"
    centres = (np.argwhere(columns) + 0.5) * voxel_size
    grown = shapely.union_all(polygons).buffer(voxel_size)
    outside = 1.0 - shapely.contains_xy(grown, centres[:, 0], centres[:, 1]).mean()
    if outside > FOOTPRINT_MISMATCH_SHARE:
        warnings.warn(f"massing: the maximum volume's footprint does not match the voxel grid "
                      f"({100 * outside:.0f}% of the occupied columns lie outside it); "
                      f"using the voxel footprint", UserWarning, stacklevel=3)
        return mg.footprint_from_columns(columns, voxel_size), "voxels"
    return polygons, "mesh"


def _warn_raised_parts(polygons, cells_ij, xy, occ, z0, origin_z, voxel_size):
    part = mg.part_of_points(shapely.points(xy), polygons)
    lowest = occ.argmax(axis=2)[cells_ij[:, 0], cells_ij[:, 1]]
    for k in range(len(polygons)):
        mine = part == k
        if not mine.any():
            continue
        base = origin_z + lowest[mine].min() * voxel_size
        if base > z0 + 1e-6:
            warnings.warn(f"massing: part {k} starts {base - z0:.2f} m above the lowest point; "
                          f"floors count from the lowest point (sloped ground is not supported yet)",
                          UserWarning, stacklevel=3)


def massing(threshold_manifest, cfg: Union[user_config, str, Path],
            out_dir: Union[str, Path]) -> MassingResult:
    """Fourth stage: floor plates that follow the footprint, from the carved envelope.

    Floors are ``ground_floor_height`` then ``floor_height`` tall, counted
    from the lowest point of the maximum volume.  The footprint (the maximum
    volume's plan projection) is split into faces, one per
    facade, and each face into bays ``min_plate_dimension`` wide, cut
    perpendicular to its facade.  A bay is built on a floor when it stays in
    the maximum volume over the floor's full height, at most
    ``plate_tolerance`` of its volume lies outside the carved envelope, and
    (with ``plate_stacking: supported``) it is built on the floor below.
    See :mod:`urbansolarcarver.floor_plates`.

    Parameters
    ----------
    threshold_manifest : ThresholdingResult | str | Path
        Thresholding result, or a path to its folder or manifest.json.
    cfg : user_config | str | Path
        Validated config or path to config file.
    out_dir : str | Path
        Output directory for this stage; created if it does not exist.

    Returns
    -------
    MassingResult

    Persisted artifacts
    -------------------
    ``plates.json``
        One entry per plate: floor, z bottom and top, outline and holes in
        world coordinates, floor area, bay count and outside share; plus
        floor areas per floor and in total.
    ``plates.obj``
        One closed mesh per plate, named ``floor_<n>_plate_<m>``.
    ``manifest.json``, ``diagnostics/diagnostic.json``, ``run_report.md``
        The report goes to the parent folder when *out_dir* is named
        ``massing``, otherwise into *out_dir*.

    Raises
    ------
    ValueError
        If a manifest cannot be read, or a massing size is smaller than the
        preprocessing run's voxel size.
    """
    t0_wall, t0_cpu = time.perf_counter(), time.process_time()
    conf = _resolve_cfg(cfg)
    out_path = _ensure_out_dir(out_dir, "massing")
    chain = load_thresholded_grid(threshold_manifest, conf)
    vs, origin = chain.voxel_size, chain.origin
    for name in ("min_plate_dimension", "ground_floor_height", "floor_height"):
        if getattr(conf, name) < vs - 1e-9:
            raise ValueError(f"{name} ({getattr(conf, name):g} m) is smaller than the voxel "
                             f"size of the preprocessing run ({vs:g} m)")

    occ = chain.occupancy.astype(bool)
    kept = occ & chain.mask.astype(bool)
    columns = occ.any(axis=2)
    cells_ij = np.argwhere(columns)
    xy = (cells_ij + 0.5) * vs
    polygons, footprint_source = _footprint(conf, origin, columns, vs)
    facades, corners = mg.split_facades(polygons)
    # A facade shorter than two bays (a chamfer, a small step) would get a
    # face of at most one bay; its columns go to the neighbouring facades.
    faces = mg.assign_faces(xy, facades, corners, polygons, vs,
                            min_facade_length=2.0 * conf.min_plate_dimension)
    bay, bay_face = mg.cut_bays(faces, conf.min_plate_dimension, vs)
    bay_shapes = mg.bay_polygons(xy, faces, bay, bay_face, facades, polygons,
                                 conf.min_plate_dimension, vs)
    n_cols = np.bincount(bay)

    layers = np.flatnonzero(occ.any(axis=(0, 1)))
    z0 = origin[2] + layers.min() * vs
    z_top = origin[2] + (layers.max() + 1) * vs
    _warn_raised_parts(polygons, cells_ij, xy, occ, z0, origin[2], vs)
    levels = mg.floor_levels(z0, z_top, conf.ground_floor_height, conf.floor_height)
    floors = mg.build_floors(cells_ij, bay, occ, kept, origin[2], vs, levels,
                             conf.plate_tolerance, conf.plate_stacking, conf.min_plate_dimension)

    footprint = shapely.union_all(polygons)
    plates, meshes, floor_areas = [], [], []
    for n, floor in enumerate(floors):
        area_this_floor, count_this_floor = 0.0, 0
        for p in range(int(floor.plate.max()) + 1):
            in_plate = floor.plate == p
            bays_in = np.unique(bay[in_plate])
            outside = float((floor.outside_share[bays_in] * n_cols[bays_in]).sum()
                            / n_cols[bays_in].sum())
            for poly in mg.plate_polygons(cells_ij, in_plate, ~in_plate, vs, footprint,
                                          min_dimension=conf.min_plate_dimension,
                                          bay=bay, bay_shapes=bay_shapes):
                world = shapely.affinity.translate(poly, origin[0], origin[1])
                plates.append({
                    "floor": n, "plate": count_this_floor,
                    "z_bottom": floor.zb, "z_top": floor.zt, "area_m2": float(poly.area),
                    "bays": int(len(bays_in)), "outside_share": round(outside, 4),
                    "outline": np.asarray(world.exterior.coords).tolist(),
                    "holes": [np.asarray(r.coords).tolist() for r in world.interiors],
                })
                prism = mg.prism_mesh(poly, floor.zb, floor.zt)
                prism.apply_translation([origin[0], origin[1], 0.0])
                meshes.append((f"floor_{n}_plate_{count_this_floor}", prism))
                area_this_floor += float(poly.area)
                count_this_floor += 1
        floor_areas.append(area_this_floor)
    total = float(sum(floor_areas))

    plates_path = out_path / "plates.json"
    plates_path.write_text(json.dumps({"plates": plates, "floor_area_m2_per_floor": floor_areas,
                                       "total_floor_area_m2": total}, indent=1), encoding="utf-8")
    mesh_path = out_path / "plates.obj"
    if meshes:
        import trimesh
        scene = trimesh.Scene()
        for name, prism in meshes:
            scene.add_geometry(prism, geom_name=name)
        scene.export(str(mesh_path), file_type="obj")
    else:
        mesh_path.write_text("", encoding="utf-8")
        warnings.warn("massing: no floor plates fit the envelope with these settings",
                      UserWarning, stacklevel=2)

    settings = {k: getattr(conf, k) for k in ("ground_floor_height", "floor_height",
                                              "min_plate_dimension", "plate_tolerance",
                                              "plate_stacking")}
    upstream = chain.thr_manifest.hash
    stage_hash = hashlib.sha256((json.dumps(settings, sort_keys=True) + upstream).encode()).hexdigest()[:8]
    manifest = MassingManifest(hash=stage_hash, plates_path=str(plates_path),
                               mesh_path=str(mesh_path), upstream_manifest=str(chain.thr_path),
                               upstream_hash=upstream)
    (out_path / "manifest.json").write_text(schema_to_json(manifest), encoding="utf-8")

    plate_volume = sum(q["area_m2"] * (q["z_top"] - q["z_bottom"]) for q in plates)
    inside = sum(q["area_m2"] * (q["z_top"] - q["z_bottom"]) * (1.0 - q["outside_share"]) for q in plates)
    envelope = float(kept.sum()) * vs ** 3
    write_json(ensure_diag(out_path), "diagnostic.json", {
        "floors": len(levels), "floors_built": int(sum(a > 0 for a in floor_areas)),
        "plates": len(plates), "floor_area_m2_per_floor": floor_areas,
        "total_floor_area_m2": total, "envelope_volume_m3": envelope,
        "envelope_share_in_plates": inside / envelope if envelope > 0 else None,
        "volume_outside_envelope_m3": plate_volume - inside,
        "footprint_source": footprint_source, "settings": settings,
        "timings": {"wall_seconds": float(time.perf_counter() - t0_wall),
                    "cpu_seconds": float(time.process_time() - t0_cpu)},
    })
    # The report goes to the run folder in the standard <run>/massing layout,
    # otherwise next to the plates; an old report is removed first.
    report_root = out_path.parent if out_path.name == "massing" else out_path
    (report_root / "run_report.md").unlink(missing_ok=True)
    try:
        generate_run_report(report_root, chain.pre_path.parent, chain.thr_path.parent,
                            report_root / "exporting", conf, massing_dir=out_path)
    except Exception as exc:
        log.warning("Could not generate run report: %s", exc)

    return MassingResult(out_dir=out_path, plates_path=plates_path, mesh_path=mesh_path,
                         floor_areas=floor_areas, total_floor_area=total, n_plates=len(plates))
