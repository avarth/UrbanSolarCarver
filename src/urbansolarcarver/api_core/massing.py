"""Massing stage: stacked floor plates from the carved envelope.

Reads the thresholding manifest, builds floor plates that follow the
maximum volume's footprint, which preprocessing saved as ``footprint.json``
(``urbansolarcarver.floor_plates``), and writes them
as ``plates.json`` (outlines in world coordinates) and ``plates.obj`` (one
closed prism per plate), with a manifest, diagnostics and the run report.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

import numpy as np
import shapely
import shapely.affinity

from .. import floor_plates as mg
from ..errors import StageChainError
from ..load_config import user_config
from ..pydantic_schemas import MassingManifest
from ..run_context import Issue, RunContext, report_issue, stage_context
from ..stage_settings import MassingSettings, RunOptions
from ._reporting import write_run_report
from ._stage_io import begin_stage, commit_manifest, new_run_id, stored_path
from ._util import ThresholdedGrid, _resolve_cfg, ensure_diag, load_thresholded_grid, write_json

# Everything massing writes into its folder, besides manifest.json.
_MASSING_OUTPUTS = ("plates.json", "plates.obj", "diagnostics/diagnostic.json")

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
    issues: tuple[Issue, ...] = ()

    def __fspath__(self) -> str:
        return str(self.plates_path)


def _read_footprint(pre):
    """The footprint polygons preprocessing saved (world xy); empty when it saved none.

    Raises StageChainError, naming preprocessing as the stage to re-run, when
    the file is missing or cannot be read as a footprint.
    """
    path = pre.resolve(pre.manifest.footprint_path)
    if not path.is_file():
        raise StageChainError(
            f"Footprint file not found: {path} (named by the preprocessing manifest). "
            f"Re-run preprocessing."
        )
    try:
        return mg.footprint_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StageChainError(
            f"Footprint file {path} is damaged ({type(exc).__name__}: {exc}). "
            f"Re-run preprocessing."
        ) from exc


def _footprint(world_polygons, origin, columns, voxel_size):
    """Footprint polygons (local xy) and their source ("mesh" or "voxels").

    *world_polygons* is the plan projection of the maximum volume that
    preprocessing saved, in world xy.  It is used only when it matches the
    voxel grid: at most FOOTPRINT_MISMATCH_SHARE of the occupied columns may
    have their centre more than one voxel outside it.  Otherwise (or when
    preprocessing saved none) the voxel footprint is used, with a warning.
    """
    polygons = [shapely.affinity.translate(p, -origin[0], -origin[1]) for p in world_polygons]
    if not polygons:
        report_issue(
            "footprint_unreadable",
            "massing: the maximum volume's footprint could not be read; "
            "using the voxel footprint",
        )
        return mg.footprint_from_columns(columns, voxel_size), "voxels"
    centres = (np.argwhere(columns) + 0.5) * voxel_size
    grown = shapely.union_all(polygons).buffer(voxel_size)
    outside = 1.0 - shapely.contains_xy(grown, centres[:, 0], centres[:, 1]).mean()
    if outside > FOOTPRINT_MISMATCH_SHARE:
        report_issue(
            "footprint_mismatch",
            f"massing: the maximum volume's footprint does not match the voxel grid "
            f"({100 * outside:.0f}% of the occupied columns lie outside it); "
            f"using the voxel footprint",
        )
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
            report_issue(
                "raised_part",
                f"massing: part {k} starts {base - z0:.2f} m above the lowest point; "
                f"floors count from the lowest point (sloped ground is not supported yet)",
            )


def massing(threshold_manifest, cfg: Union[user_config, str, Path],
            out_dir: Union[str, Path]) -> MassingResult:
    """Fourth stage: floor plates that follow the footprint, from the carved envelope.

    Floors are ``ground_floor_height`` then ``floor_height`` tall, counted
    from the lowest point of the maximum volume.  The footprint (the plan
    projection of the maximum volume that preprocessing saved as
    ``footprint.json``, not the mesh named in *cfg*) is split into faces, one per
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
        ``massing``, otherwise into *out_dir*; it keeps an Export section
        when the run's exporting folder was built from the same
        thresholding run.  The outputs of an earlier run in *out_dir* are
        deleted first and the manifest is written last.

    Raises
    ------
    StageChainError
        If a manifest cannot be read, preprocessing was re-run after the
        thresholding run, or the mask, occupancy grid or footprint is missing
        or damaged (a ValueError; the message names the stage to re-run).
    ValueError
        If a massing size is smaller than the preprocessing run's voxel size.
    """
    with stage_context("massing") as context:
        conf = _resolve_cfg(cfg)
        out_path = begin_stage(out_dir, _MASSING_OUTPUTS)
        chain = load_thresholded_grid(threshold_manifest)
        return _run_massing(
            MassingSettings.from_config(conf), RunOptions.from_config(conf),
            chain, out_path, context)


def _run_massing(settings: MassingSettings, options: RunOptions, upstream: ThresholdedGrid,
                 out_path: Path, context: RunContext) -> MassingResult:
    """The computation of :func:`massing`, from its own settings only.

    *upstream* is the loaded thresholding chain (manifests, mask, occupancy
    grid).  *out_path* is the stage folder, already cleared by
    :func:`begin_stage`.
    """
    t0_wall, t0_cpu = time.perf_counter(), time.process_time()
    chain = upstream
    vs, origin = chain.voxel_size, chain.origin
    for name in ("min_plate_dimension", "ground_floor_height", "floor_height"):
        if getattr(settings, name) < vs - 1e-9:
            raise ValueError(f"{name} ({getattr(settings, name):g} m) is smaller than the voxel "
                             f"size of the preprocessing run ({vs:g} m)")

    occ = chain.occupancy.astype(bool)
    kept = occ & chain.mask.astype(bool)
    columns = occ.any(axis=2)
    cells_ij = np.argwhere(columns)
    xy = (cells_ij + 0.5) * vs
    polygons, footprint_source = _footprint(_read_footprint(chain.pre), origin, columns, vs)
    facades, corners = mg.split_facades(polygons)
    # A facade shorter than two bays (a chamfer, a small step) would get a
    # face of at most one bay; its columns go to the neighbouring facades.
    faces = mg.assign_faces(xy, facades, corners, polygons, vs,
                            min_facade_length=2.0 * settings.min_plate_dimension)
    bay, bay_face = mg.cut_bays(faces, settings.min_plate_dimension, vs)
    bay_shapes = mg.bay_polygons(xy, faces, bay, bay_face, facades, polygons,
                                 settings.min_plate_dimension, vs)
    n_cols = np.bincount(bay)

    layers = np.flatnonzero(occ.any(axis=(0, 1)))
    z0 = origin[2] + layers.min() * vs
    z_top = origin[2] + (layers.max() + 1) * vs
    _warn_raised_parts(polygons, cells_ij, xy, occ, z0, origin[2], vs)
    levels = mg.floor_levels(z0, z_top, settings.ground_floor_height, settings.floor_height)
    floors = mg.build_floors(cells_ij, bay, occ, kept, origin[2], vs, levels,
                             settings.plate_tolerance, settings.plate_stacking, settings.min_plate_dimension)

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
                                          min_dimension=settings.min_plate_dimension,
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

    # The mesh first: plates.json, which clients read for the results, then
    # appears only once the mesh beside it was written.
    mesh_path = out_path / "plates.obj"
    if meshes:
        import trimesh
        scene = trimesh.Scene()
        for name, prism in meshes:
            scene.add_geometry(prism, geom_name=name)
        scene.export(str(mesh_path), file_type="obj")
    else:
        mesh_path.write_text("", encoding="utf-8")
        report_issue(
            "no_plates_fit",
            "massing: no floor plates fit the envelope with these settings",
        )
    plates_path = out_path / "plates.json"
    plates_path.write_text(json.dumps({"plates": plates, "floor_area_m2_per_floor": floor_areas,
                                       "total_floor_area_m2": total}, indent=1), encoding="utf-8")

    plate_volume = sum(q["area_m2"] * (q["z_top"] - q["z_bottom"]) for q in plates)
    inside = sum(q["area_m2"] * (q["z_top"] - q["z_bottom"]) * (1.0 - q["outside_share"]) for q in plates)
    envelope = float(kept.sum()) * vs ** 3
    write_json(ensure_diag(out_path), "diagnostic.json", {
        "floors": len(levels), "floors_built": int(sum(a > 0 for a in floor_areas)),
        "plates": len(plates), "floor_area_m2_per_floor": floor_areas,
        "total_floor_area_m2": total, "envelope_volume_m3": envelope,
        "envelope_share_in_plates": inside / envelope if envelope > 0 else None,
        "volume_outside_envelope_m3": plate_volume - inside,
        "footprint_source": footprint_source, "settings": settings.model_dump(),
        "timings": {"wall_seconds": float(time.perf_counter() - t0_wall),
                    "cpu_seconds": float(time.process_time() - t0_cpu)},
    })
    thr_run_id = chain.thr.manifest.run_id
    write_run_report("massing", out_path, chain.pre.folder, chain.thr.folder, thr_run_id)

    # Manifest last (see begin_stage at the start).
    commit_manifest(out_path, MassingManifest(
        run_id=new_run_id(), plates_path=stored_path(plates_path, out_path),
        mesh_path=stored_path(mesh_path, out_path),
        upstream_manifest=stored_path(chain.thr.manifest_path, out_path),
        upstream_run_id=thr_run_id))

    return MassingResult(out_dir=out_path, plates_path=plates_path, mesh_path=mesh_path,
                         floor_areas=floor_areas, total_floor_area=total, n_plates=len(plates),
                         issues=context.issues_of("massing"))
