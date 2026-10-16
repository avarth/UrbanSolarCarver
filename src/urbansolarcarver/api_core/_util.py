"""Shared utilities for the pipeline stages (preprocessing, thresholding, exporting, massing).

Provides config resolution, device selection, occupancy-grid and
thresholding-chain loading, and diagnostics I/O helpers (JSON writing,
directory creation, config snapshot).  Stage folders and manifests are
handled by ``_stage_io``.

Visualization helpers live in ``_diagnostics``, reporting in ``_reporting``.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import json

from ..errors import StageChainError
from ..load_config import load_config, user_config
from ._stage_io import LoadedManifest, load_upstream


def _resolve_cfg(cfg: Union[user_config, str, Path]) -> user_config:
    """Coerce *cfg* to a :class:`user_config`, loading from path if needed."""
    return load_config(str(cfg)) if not isinstance(cfg, user_config) else cfg


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

def load_occupancy(pre):
    """Return the boolean occupancy grid (numpy) of a preprocessing run.

    *pre* is the :class:`LoadedManifest` of the preprocessing run.  Loads
    the persisted ``voxel_grid.npy``.  Raises StageChainError if the file is
    gone (the grid is not rebuilt from a config, which may describe other
    geometry) or its shape differs from the manifest's; the message names
    the stage to re-run.
    """
    import numpy as np
    vg_path = pre.resolve(pre.manifest.voxel_grid_path)
    if not vg_path.is_file():
        raise StageChainError(
            f"Occupancy grid not found: {vg_path} (named by the preprocessing "
            f"manifest). Re-run preprocessing."
        )
    occ = np.load(vg_path, allow_pickle=False).astype(bool)
    if tuple(occ.shape) != tuple(pre.manifest.shape):
        raise StageChainError(
            f"Voxel grid shape {tuple(occ.shape)} does not match the grid shape "
            f"{tuple(pre.manifest.shape)} recorded in the preprocessing manifest; "
            f"the occupancy grid is from a different run. Re-run preprocessing."
        )
    return occ


def dump_config_snapshot(conf, diag_dir) -> Path:
    """Write the full config to diagnostics for reproducibility.

    "None = auto" settings stay unset, so the snapshot loads back with the
    same meaning; the thresholding manifest records what they resolved to.
    """
    snapshot = conf.model_dump()
    return write_json(diag_dir, "config_snapshot.json", snapshot)


@dataclass(frozen=True)
class ThresholdedGrid:
    """The thresholding chain of a run: manifests, mask and occupancy grid."""
    thr: LoadedManifest
    pre: LoadedManifest
    mask: "np.ndarray"
    occupancy: "np.ndarray"
    origin: "np.ndarray"
    voxel_size: float


def load_thresholded_grid(threshold_manifest) -> ThresholdedGrid:
    """Load a thresholding manifest, its preprocessing manifest, the mask and
    the occupancy grid.  *threshold_manifest* is a ThresholdingResult or a
    path to its folder or manifest.json.

    Raises StageChainError if a manifest cannot be read, preprocessing was
    re-run after this thresholding run, or the mask or occupancy grid is
    missing or does not match the grid shape.
    """
    import numpy as np
    thr = load_upstream(threshold_manifest, "thresholding")
    pre = load_upstream(thr.resolve(thr.manifest.upstream_manifest), "preprocessing")
    grid_shape = tuple(pre.manifest.shape)
    mask_path = thr.resolve(thr.manifest.mask_path)
    if not mask_path.is_file():
        raise StageChainError(
            f"Mask file not found: {mask_path} (referenced by {thr.manifest_path}). "
            f"Re-run thresholding."
        )
    mask = np.load(mask_path, allow_pickle=False)
    if mask.ndim == 1:
        mask = mask.reshape(grid_shape)
    elif tuple(mask.shape) != grid_shape:
        raise StageChainError(
            f"Mask shape {tuple(mask.shape)} does not match the grid shape "
            f"{grid_shape} recorded in {pre.manifest_path}; the mask and manifest "
            f"are from different runs. Re-run thresholding."
        )
    return ThresholdedGrid(
        thr=thr, pre=pre, mask=mask, occupancy=load_occupancy(pre),
        origin=np.asarray(pre.manifest.origin, dtype=np.float64),
        voxel_size=float(pre.manifest.voxel_size),
    )
