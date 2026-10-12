"""Shared utilities for the three pipeline stages (preprocessing, thresholding, exporting).

Provides config resolution, output-directory setup, device detection,
and diagnostics I/O helpers (JSON writing, directory creation).

Visualization helpers live in ``_diagnostics``, reporting in ``_reporting``.
"""
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

# Lean diagnostics helpers. Keep all tiny and local.
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
    """Resolve a device string to a torch.device with proper CUDA checks."""
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
    """Boolean occupancy grid (numpy) of a preprocessing run.

    Reuses the persisted ``voxel_grid.npy``; re-voxelizes the max volume
    only for manifests written before that file existed.
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
        vg, *_ = voxelize(env_mesh, conf, device=torch.device("cpu"))
        occ = vg.cpu().numpy().astype(bool)
    if tuple(occ.shape) != tuple(pre_manifest.shape):
        raise ValueError(
            f"Voxel grid shape {tuple(occ.shape)} does not match the grid shape "
            f"{tuple(pre_manifest.shape)} recorded in the preprocessing manifest — "
            f"the occupancy grid is from a different run (check voxel_size / "
            f"margin_frac consistency)."
        )
    return occ


def dump_config_snapshot(conf, diag_dir) -> Path:
    """Write the full resolved config to diagnostics for reproducibility."""
    snapshot = conf.model_dump()
    return write_json(diag_dir, "config_snapshot.json", snapshot)
