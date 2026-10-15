"""Exporting stage: convert a carved binary mask into a triangle mesh.

Reads the thresholding manifest, builds a mesh from the binary voxel field
(voxel cubes, or a smoothed surface with ``apply_smoothing``), and writes it
to disk (PLY/OBJ/STL/GLB) together with a run report.  This is the final
pipeline stage.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union, overload

import numpy as np

log = logging.getLogger(__name__)
from ..load_config import user_config
from ._util import _resolve_cfg, _ensure_out_dir, ensure_diag, write_json, resolve_device, load_thresholded_grid
from ._reporting import generate_run_report
from ..pydantic_schemas import PreprocessingManifest, ThresholdingManifest, schema_from_json
from ..io import save_mesh
from ..grid import finalize_mesh
import time

@dataclass(frozen=True)
class ExportingResult:
    """Immutable record returned by :func:`exporting`.

    Holds the filesystem path to the exported triangle mesh, the voxel
    retention percentage, and mesh statistics (volume, vertex/face counts).
    Implements ``__fspath__`` so the result can be used directly as a
    path-like pointing to the exported mesh file.
    """
    out_dir: Path
    export_path: Path
    retention_pct: float = 0.0
    mesh_volume_m3: Optional[float] = None
    vertices: int = 0
    faces: int = 0
    def __fspath__(self) -> str:
        return str(self.export_path)

@overload
def exporting(threshold_manifest: "ThresholdingResult", cfg: Union[user_config, str, Path], out_dir: Union[str, Path]) -> ExportingResult: ...
@overload
def exporting(threshold_manifest: Union[str, Path], cfg: Union[user_config, str, Path], out_dir: Union[str, Path]) -> ExportingResult: ...

def exporting(
    threshold_manifest: Union["ThresholdingResult", str, Path],
    cfg: Union[user_config, str, Path],
    out_dir: Union[str, Path]
) -> ExportingResult:
    """Third stage of the 3-stage pipeline: mesh extraction from the binary mask.

    Loads the Boolean voxel mask produced by :func:`thresholding` and the
    occupancy grid persisted during :func:`preprocessing`, combines them
    (logical AND), and converts the resulting carved voxel field into a
    triangle mesh suitable for downstream CAD / BIM / visualisation workflows.

    Mesh extraction proceeds through :func:`~urbansolarcarver.grid.finalize_mesh`,
    which supports two strategies (selected by ``cfg.apply_smoothing``):

    * **cubic** (``apply_smoothing=False``, default): a 3x3x3 neighbour
      filter first drops isolated voxels, then the exposed faces of the
      occupied voxels are emitted; fast, produces the classic voxel look.
    * **smoothed** (``apply_smoothing=True``): the binary field is converted
      to a signed-distance field, smoothed, and iso-surfaced with Marching
      Cubes, then polished with ``cfg.smooth_iters`` Taubin passes (0-6).

    On both paths, connected voxel clusters smaller than ``cfg.min_voxels``
    and mesh fragments with fewer than ``cfg.min_face_count`` faces are
    removed.  The mesh uses the voxel size and origin recorded by
    preprocessing, not the config's ``voxel_size``.

    Parameters
    ----------
    threshold_manifest : ThresholdingResult | str | Path
        Either the :class:`ThresholdingResult` from the previous stage, or a
        path to its output directory / ``manifest.json``.
    cfg : user_config | str | Path
        Validated config or path to config file.
    out_dir : str | Path
        Output directory for this stage; created if it does not exist.
        All artifacts are written directly into it.

    Returns
    -------
    ExportingResult
        Frozen dataclass with the exported mesh path and provenance metadata.

    Persisted artifacts
    -------------------
    ``export.{ply,obj,stl,glb}``
        Triangle mesh in the format specified by ``cfg.final_mesh_format``
        (default ``ply``), in world coordinates.
    ``diagnostics/diagnostic.json``
        Mesh statistics (vertex/face counts, watertightness, volume, bounding
        box), voxel retention percentage, and wall/CPU timings.
    ``run_report.md``
        Markdown summary of all three stages, written to the parent folder
        when *out_dir* is named ``exporting``, otherwise into *out_dir*.

    Raises
    ------
    ValueError
        If a manifest cannot be read or the mask does not match the grid
        shape.
    FileNotFoundError
        If the mask file named in the thresholding manifest is missing.
    """
    _t0_wall = time.perf_counter()
    _t0_cpu = time.process_time()
    conf = _resolve_cfg(cfg)
    out_path = _ensure_out_dir(out_dir, "exporting")

    chain = load_thresholded_grid(threshold_manifest, conf)
    thr_path, thr_manifest, pre_manifest = chain.thr_path, chain.thr_manifest, chain.pre_manifest
    mask = chain.mask

    import torch  # lazy
    resolved_device = resolve_device(conf.device)
    mask_tensor = torch.as_tensor(mask, dtype=torch.bool, device=resolved_device)

    voxel_grid = torch.as_tensor(chain.occupancy, device=resolved_device)
    carve_grid = (voxel_grid.bool() & mask_tensor)
    origin = np.array(pre_manifest.origin, dtype=np.float64)

    # The grid's voxel size is a fact of the preprocessing run, not a setting
    # of this stage: re-exporting with a different config must not rescale it.
    if pre_manifest.voxel_size and pre_manifest.voxel_size != conf.voxel_size:
        import warnings
        warnings.warn(
            f"Config voxel_size={conf.voxel_size:g} differs from the preprocessing "
            f"run's {pre_manifest.voxel_size:g}; meshing with "
            f"{pre_manifest.voxel_size:g}.",
            stacklevel=2,
        )
        conf = conf.model_copy(update={"voxel_size": pre_manifest.voxel_size})

    # Mesh at the grid's own origin, then place it in float64: the mesh
    # builders emit float32 vertices, which cannot hold georeferenced
    # coordinates to better than ~0.5 m.
    cleaned_voxels, _, final_mesh = finalize_mesh(carve_grid, np.zeros(3), conf)
    final_mesh.apply_translation(origin)

    ext = conf.final_mesh_format
    export_path = out_path / f"export.{ext}"

    save_mesh(final_mesh, str(export_path))

    # Per-stage diagnostics
    v_count = int(len(final_mesh.vertices)) if hasattr(final_mesh, "vertices") else None
    f_count = int(len(final_mesh.faces)) if hasattr(final_mesh, "faces") else None
    try:
        watertight = bool(final_mesh.is_watertight)
    except Exception as exc:
        log.warning("Could not determine watertightness: %s", exc)
        watertight = None
    # Mesh volume and bounding box
    try:
        mesh_volume = float(final_mesh.volume) if watertight else None
    except Exception as exc:
        log.warning("Could not compute mesh volume: %s", exc)
        mesh_volume = None
    try:
        bbox = final_mesh.bounds  # None when mesh is empty
    except Exception as exc:
        log.warning("Could not compute mesh bounds: %s", exc)
        bbox = None
    bbox_dims = [float(bbox[1][i] - bbox[0][i]) for i in range(3)] if bbox is not None else None
    # Voxel retention over occupied voxels, counted on the voxels that were
    # actually meshed (after small clusters and isolated voxels are removed).
    kept_by_mask = int(carve_grid.sum().item())
    retained_voxels = int(cleaned_voxels.sum().item())
    original_voxels = int(voxel_grid.sum().item())
    retention_pct = round(100.0 * retained_voxels / max(original_voxels, 1), 2)

    diag_dir = ensure_diag(out_path)
    diagnostic = {
        "mesh_path": str(export_path),
        "vertices": v_count,
        "triangles": f_count,
        "is_watertight": watertight,
        "mesh_volume_m3": mesh_volume,
        "bbox_dimensions_m": bbox_dims,
        "voxels_original": original_voxels,
        "voxels_retained": retained_voxels,
        "voxels_removed": original_voxels - retained_voxels,
        "voxels_removed_by_cleanup": kept_by_mask - retained_voxels,
        "voxel_retention_pct": retention_pct,
    }
    # One diagnostic file per stage.
    diagnostic["timings"] = {
        "wall_seconds": float(time.perf_counter() - _t0_wall),
        "cpu_seconds": float(time.process_time() - _t0_cpu),
    }
    write_json(diag_dir, "diagnostic.json", diagnostic)

    # Generate consolidated run report from all three stages.
    pre_dir = Path(thr_manifest.upstream_manifest).parent
    thr_dir = thr_path.parent
    # The report goes to the run folder in the standard <run>/exporting
    # layout, otherwise next to the export. An old report is removed first
    # so a failed regeneration cannot leave stale numbers behind.
    report_root = out_path.parent if out_path.name == "exporting" else out_path
    (report_root / "run_report.md").unlink(missing_ok=True)
    try:
        generate_run_report(report_root, pre_dir, thr_dir, out_path, conf)
    except Exception as exc:
        log.warning("Could not generate run report: %s", exc)

    return ExportingResult(
        out_dir=out_path,
        export_path=export_path,
        retention_pct=retention_pct,
        mesh_volume_m3=mesh_volume,
        vertices=v_count if v_count is not None else 0,
        faces=f_count if f_count is not None else 0,
    )