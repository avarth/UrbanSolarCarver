"""Exporting stage — convert a carved binary mask into a triangle mesh.

Reads the thresholding manifest, reconstructs a smoothed mesh from the
binary voxel field, and writes it to disk (PLY/OBJ/STL/GLB).  This is
the final pipeline stage.
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
from ._util import _resolve_cfg, _ensure_out_dir, ensure_diag, write_json, resolve_device
from ._reporting import generate_run_report
from ..pydantic_schemas import PreprocessingManifest, ThresholdingManifest, schema_from_json
from ..io import save_mesh
from ..grid import voxelize, finalize_mesh
from ..carving import load_meshes
import time

@dataclass(frozen=True)
class ExportingResult:
    """Immutable record returned by :func:`exporting`.

    Holds the filesystem path to the exported triangle mesh and mesh
    statistics (retention percentage, volume, vertex/face counts).
    Implements ``__fspath__`` so the result can be used directly as a
    path-like pointing to the export directory.
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

    * **cubic** (``apply_smoothing=False``, default) -- axis-aligned cuboid
      faces are emitted for every occupied voxel; fast, produces the classic
      voxel look.
    * **smoothed** (``apply_smoothing=True``) -- the binary field is converted
      to a signed-distance field, smoothed, and iso-surfaced with Marching
      Cubes, then optionally polished with up to ``cfg.smooth_iters`` Taubin
      passes.  Voxel clusters below ``cfg.min_voxels`` and mesh fragments
      below ``cfg.min_face_count`` faces are removed on both paths.

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
        (default ``ply``).
    ``diagnostics/``
        Mesh statistics (vertex/face counts, watertightness, volume, bounding
        box), voxel retention percentage, and wall/CPU timings.
    """
    # Start timers.
    _t0_wall = time.perf_counter()
    _t0_cpu = time.process_time()
    conf = _resolve_cfg(cfg)
    out_path = _ensure_out_dir(out_dir, "exporting")

    thr_path = Path(threshold_manifest)
    if thr_path.is_dir():
        thr_path = thr_path / "manifest.json"
    try:
        thr_manifest = schema_from_json(ThresholdingManifest, thr_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("Unable to load thresholding manifest; pass a ThresholdingResult or a path to its manifest.json") from exc

    mask_path = Path(thr_manifest.mask_path)

    # Load preprocessing manifest for grid metadata
    pre_manifest = schema_from_json(PreprocessingManifest, Path(thr_manifest.upstream_manifest).read_text(encoding="utf-8"))

    mask = np.load(mask_path, allow_pickle=False)
    if mask.ndim == 1:
        mask = mask.reshape(tuple(pre_manifest.shape))

    import torch  # lazy
    resolved_device = resolve_device(conf.device)
    mask_tensor = torch.as_tensor(mask, dtype=torch.bool, device=resolved_device)

    # Reuse persisted voxel grid from preprocessing (avoids expensive re-voxelization).
    if pre_manifest.voxel_grid_path and Path(pre_manifest.voxel_grid_path).is_file():
        voxel_grid_np = np.load(pre_manifest.voxel_grid_path, allow_pickle=False)
        voxel_grid = torch.as_tensor(voxel_grid_np, device=resolved_device)
    else:
        env_mesh, _ = load_meshes(conf)
        voxel_grid, *_ = voxelize(env_mesh, conf, device=resolved_device)

    # Column post-processing: carve occupied voxels above carved runs.
    _carve_above_extra = 0
    if getattr(conf, 'carve_above', False):
        from ..carving import carve_above_columns
        vg_np = voxel_grid.cpu().numpy().astype(bool)
        mask_before = mask.copy()
        mask = carve_above_columns(
            mask, vg_np,
            min_consecutive=getattr(conf, 'carve_above_min_consecutive', 1),
        )
        _carve_above_extra = int(mask_before.sum()) - int(mask.sum())
        mask_tensor = torch.as_tensor(mask, dtype=torch.bool, device=resolved_device)

    carve_grid = (voxel_grid.bool() & mask_tensor)
    origin = np.array(pre_manifest.origin, dtype=float)

    cleaned_voxels, mesh_pre, final_mesh = finalize_mesh(carve_grid, origin, conf)

    ext = getattr(conf, "final_mesh_format", "ply")
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
    # Voxel retention
    carved_voxels = int(carve_grid.sum().item()) if hasattr(carve_grid, 'sum') else None
    original_voxels = int(voxel_grid.sum().item()) if hasattr(voxel_grid, 'sum') else None
    retention_pct = round(100.0 * carved_voxels / max(original_voxels, 1), 2) if carved_voxels is not None and original_voxels is not None else None

    diag_dir = ensure_diag(out_path)
    diagnostic = {
        "mesh_path": str(export_path),
        "vertices": v_count,
        "triangles": f_count,
        "is_watertight": watertight,
        "mesh_volume_m3": mesh_volume,
        "bbox_dimensions_m": bbox_dims,
        "voxels_original": original_voxels,
        "voxels_carved": carved_voxels,
        "voxel_retention_pct": retention_pct,
        "carve_above_applied": getattr(conf, 'carve_above', False),
        "carve_above_min_consecutive": getattr(conf, 'carve_above_min_consecutive', 1) if getattr(conf, 'carve_above', False) else None,
        "carve_above_extra_voxels_removed": _carve_above_extra,
    }
    # Consolidated diagnostic — one file per stage.
    diagnostic["timings"] = {
        "wall_seconds": float(time.perf_counter() - _t0_wall),
        "cpu_seconds": float(time.process_time() - _t0_cpu),
    }
    write_json(diag_dir, "diagnostic.json", diagnostic)

    # Generate consolidated run report from all three stages.
    pre_dir = Path(thr_manifest.upstream_manifest).parent
    thr_dir = thr_path.parent
    # Write report to the common parent of all stages (or exporting dir).
    report_root = out_path.parent if out_path.parent != out_path else out_path
    try:
        generate_run_report(report_root, pre_dir, thr_dir, out_path, conf)
    except Exception as exc:
        log.warning("Could not generate run report: %s", exc)

    return ExportingResult(
        out_dir=out_path,
        export_path=export_path,
        retention_pct=retention_pct if retention_pct is not None else 0.0,
        mesh_volume_m3=mesh_volume,
        vertices=v_count if v_count is not None else 0,
        faces=f_count if f_count is not None else 0,
    )