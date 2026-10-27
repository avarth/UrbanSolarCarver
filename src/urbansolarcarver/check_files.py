"""The files of the sun and sky check: its result files, the fingerprint of a file it read, and the meshes of a run it traces.

Kept apart from :mod:`solar_check` (which imports torch and Warp) so the browser service can tell from the files alone whether a
study's result is out of date, with the same lookup the check makes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple, Optional

from .stage_settings import stage_folder

POINTS_FILE = "check_points.npz"
VALUES_FILE = "check_values.npz"
SUMMARY_FILE = "check_summary.json"
MANIFEST_FILE = "manifest.json"
# The geometries a run builds: name, label, and the stage whose manifest names the mesh.
RUN_GEOMETRY_STAGES = (("envelope", "Carved envelope", "exporting"), ("massing", "Building massing", "massing"))


def file_fingerprint(path) -> Optional[dict]:
    """The path, size and modification time of a file, which the summary records for each file the check read;
    None for no path."""
    if path is None:
        return None
    status = Path(path).stat()
    return {"path": str(path), "size": status.st_size, "modified_ns": status.st_mtime_ns}


def read_manifest(folder: Path) -> Optional[dict]:
    """The manifest of a stage folder; None when it has none or it cannot be read."""
    try:
        manifest = json.loads((Path(folder) / MANIFEST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def voxel_size_of(run_folder: Path, stage_manifest: dict) -> Optional[float]:
    """The voxel size of the preprocessing run a result was built on, through its thresholding run in *run_folder*
    (``thresholding``, ``preprocessing``); None when the chain is broken (a later run replaced one of them) or absent."""
    thresholding = read_manifest(stage_folder(run_folder, "thresholding"))
    preprocessing = read_manifest(stage_folder(run_folder, "preprocessing"))
    if (thresholding is None or preprocessing is None or stage_manifest.get("upstream_run_id") != thresholding.get("run_id")
            or thresholding.get("upstream_run_id") != preprocessing.get("run_id")):
        return None
    voxel_size = preprocessing.get("voxel_size")
    return float(voxel_size) if isinstance(voxel_size, (int, float)) else None


class RunGeometryFile(NamedTuple):
    """The mesh file of a geometry a run built, and the surface tolerance the check traces it with."""
    name: str
    label: str
    path: Path
    surface_tolerance: float


def run_geometry_files(run_folder, fallback_voxel_size: float = 1.0) -> list[RunGeometryFile]:
    """The carved envelope and the building massing of *run_folder* that were built (their manifest and mesh exist), in that
    order; none without a run folder. The surface tolerance is the voxel size of the analysis they were built from
    (:func:`voxel_size_of`), *fallback_voxel_size* when the chain of manifests does not tell it."""
    if run_folder is None:
        return []
    run_folder = Path(run_folder)
    found = []
    for name, label, stage in RUN_GEOMETRY_STAGES:
        folder = stage_folder(run_folder, stage)
        manifest = read_manifest(folder)
        mesh_name = manifest.get("mesh_path") if manifest is not None else None
        if not isinstance(mesh_name, str) or not (folder / mesh_name).is_file():
            continue
        tolerance = voxel_size_of(run_folder, manifest) or float(fallback_voxel_size)
        found.append(RunGeometryFile(name, label, folder / mesh_name, tolerance))
    return found
