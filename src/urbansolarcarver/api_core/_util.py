"""Shared utilities for the three pipeline stages (preprocessing, thresholding, exporting).

Provides config resolution, output-directory setup, device selection,
occupancy-grid loading, and diagnostics I/O helpers (JSON writing,
directory creation, config snapshot).

Visualization helpers live in ``_diagnostics``, reporting in ``_reporting``.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import json

from ..load_config import load_config, user_config


def _resolve_cfg(cfg: Union[user_config, str, Path]) -> user_config:
    """Coerce *cfg* to a :class:`user_config`, loading from path if needed."""
    return load_config(str(cfg)) if not isinstance(cfg, user_config) else cfg


def _ensure_out_dir(out_dir: Union[str, Path], stage: str) -> Path:
    """Create *out_dir* and return it as a :class:`Path`.  *stage* is used only in the error message."""
    if out_dir is None:
        raise ValueError(f"An explicit out_dir must be provided for {stage}")
    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path

def ensure_diag(base_out_dir: Union[str, Path]) -> Path:
    """Return <base_out_dir>/diagnostics/ path and ensure it exists."""
    p = Path(base_out_dir) / "diagnostics"
    p.mkdir(parents=True, exist_ok=True)
    return p

def write_json(dirpath: Union[str, Path], filename: str, obj: dict) -> Path:
    """Write obj to dirpath/filename as pretty JSON and return the path."""
    d = Path(dirpath); d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    return p

def resolve_device(device_str: str = "auto"):
    """Turn 'auto', 'cpu' or 'cuda' into a torch.device.

    'auto' picks CUDA when available, else CPU.  Raises RuntimeError if
    'cuda' is requested but not available.
    """
    import torch
    pref = device_str.lower() if isinstance(device_str, str) else "auto"
    if pref == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if pref == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("cfg.device='cuda' but CUDA is not available")
    return torch.device(pref)

def device_summary(device) -> str:
    """Human-readable device string, e.g. 'CUDA (NVIDIA RTX 3080, 10.0 GB)' or 'CPU'."""
    import torch
    if device.type == "cuda":
        try:
            name = torch.cuda.get_device_name(device)
            mem = torch.cuda.get_device_properties(device).total_memory / (1024**3)
            return f"CUDA ({name}, {mem:.1f} GB)"
        except Exception:
            return "CUDA"
    return "CPU"

def load_occupancy(pre_manifest, conf: user_config):
    """Return the boolean occupancy grid (numpy) of a preprocessing run.

    Loads the persisted ``voxel_grid.npy``.  If the manifest has no
    ``voxel_grid_path`` or the file is gone, the max volume is voxelized
    again with the manifest's ``voxel_size`` and *conf*'s ``margin_frac``.  Raises
    ValueError if the grid shape differs from the manifest's.
    """
    import numpy as np
    vg_path = pre_manifest.voxel_grid_path
    if vg_path and Path(vg_path).is_file():
        occ = np.load(vg_path, allow_pickle=False).astype(bool)
    else:
        import torch
        from ..carving import load_meshes
        from ..grid import voxelize
        env_mesh, _ = load_meshes(conf)
        env_mesh = env_mesh.copy()  # same local frame as preprocessing
        env_mesh.vertices = np.round(env_mesh.vertices - env_mesh.bounds[0], 6)
        same_grid = conf.model_copy(update={"voxel_size": pre_manifest.voxel_size})
        vg, *_ = voxelize(env_mesh, same_grid, device=torch.device("cpu"))
        occ = vg.cpu().numpy().astype(bool)
    if tuple(occ.shape) != tuple(pre_manifest.shape):
        raise ValueError(
            f"Voxel grid shape {tuple(occ.shape)} does not match the grid shape "
            f"{tuple(pre_manifest.shape)} recorded in the preprocessing manifest; "
            f"the occupancy grid is from a different run (check voxel_size / "
            f"margin_frac consistency)."
        )
    return occ


def dump_config_snapshot(conf, diag_dir) -> Path:
    """Write the full resolved config to diagnostics for reproducibility."""
    snapshot = conf.model_dump()
    return write_json(diag_dir, "config_snapshot.json", snapshot)


@dataclass(frozen=True)
class ThresholdedGrid:
    """The thresholding chain of a run: manifests, mask and occupancy grid."""
    thr_path: Path
    thr_manifest: object
    pre_path: Path
    pre_manifest: object
    mask: "np.ndarray"
    occupancy: "np.ndarray"
    origin: "np.ndarray"
    voxel_size: float


def load_thresholded_grid(threshold_manifest, conf) -> ThresholdedGrid:
    """Load a thresholding manifest, its preprocessing manifest, the mask and
    the occupancy grid.  *threshold_manifest* is a ThresholdingResult or a
    path to its folder or manifest.json."""
    import numpy as np
    from ..pydantic_schemas import PreprocessingManifest, ThresholdingManifest, schema_from_json
    thr_path = Path(threshold_manifest)
    if thr_path.is_dir():
        thr_path = thr_path / "manifest.json"
    try:
        thr_manifest = schema_from_json(ThresholdingManifest, thr_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("Unable to load thresholding manifest; pass a ThresholdingResult or a path to its manifest.json") from exc
    pre_path = Path(thr_manifest.upstream_manifest)
    try:
        pre_manifest = schema_from_json(PreprocessingManifest, pre_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(
            f"Unable to load the preprocessing manifest referenced by the "
            f"thresholding manifest ({pre_path}). Re-run preprocessing, "
            f"or fix the manifest chain."
        ) from exc
    grid_shape = tuple(pre_manifest.shape)
    mask_path = Path(thr_manifest.mask_path)
    if not mask_path.is_file():
        raise FileNotFoundError(
            f"Mask file not found: {mask_path} (referenced by {thr_path}). "
            f"Re-run thresholding."
        )
    mask = np.load(mask_path, allow_pickle=False)
    if mask.ndim == 1:
        mask = mask.reshape(grid_shape)
    elif tuple(mask.shape) != grid_shape:
        raise ValueError(
            f"Mask shape {tuple(mask.shape)} does not match the grid shape "
            f"{grid_shape} recorded in {pre_path}; the mask and manifest "
            f"are from different runs."
        )
    return ThresholdedGrid(
        thr_path=thr_path, thr_manifest=thr_manifest, pre_path=pre_path,
        pre_manifest=pre_manifest, mask=mask,
        occupancy=load_occupancy(pre_manifest, conf),
        origin=np.asarray(pre_manifest.origin, dtype=np.float64),
        voxel_size=float(pre_manifest.voxel_size or conf.voxel_size),
    )
