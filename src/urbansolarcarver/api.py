"""Public API: the three pipeline stages, ``run_pipeline``, and config helpers.

Importing this module imports torch, and Warp if it is installed, through
``api_core``.
"""
from __future__ import annotations
from pathlib import Path
from typing import Union

from .load_config import load_config, user_config
from .api_core import (
    preprocessing, thresholding, exporting, massing,
    PreprocessingResult, ThresholdingResult, ExportingResult, MassingResult,
)


def run_pipeline(
    cfg: Union[user_config, str, Path],
    out_dir: Union[str, Path],
) -> ExportingResult:
    """Run the full carving pipeline in one call.

    Runs preprocessing, thresholding and exporting in sequence, writing into
    ``out_dir/preprocessing``, ``out_dir/thresholding`` and
    ``out_dir/exporting``. *cfg* may be a validated config or a path to a
    YAML config file. To re-threshold without recomputing scores, call the
    stages directly.

    Returns the ExportingResult with the final mesh path.
    """
    if not isinstance(cfg, user_config):
        cfg = load_config(str(cfg))
    base = Path(out_dir)
    pre = preprocessing(cfg, base / "preprocessing")
    thr = thresholding(pre, cfg, base / "thresholding")
    return exporting(thr, cfg, base / "exporting")


__all__ = [
    "run_pipeline",
    "preprocessing",
    "thresholding",
    "exporting",
    "massing",
    "PreprocessingResult",
    "ThresholdingResult",
    "ExportingResult",
    "MassingResult",
    "load_config",
    "user_config",
]