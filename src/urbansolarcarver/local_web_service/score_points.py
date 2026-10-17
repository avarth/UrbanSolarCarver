"""The score layer of the carving screen as one binary blob.

The browser draws the occupied voxels of the grid as points coloured by their score. This
module reads them from the preprocessing and thresholding outputs of a run and packs them,
thinned to a point budget, in the layout below (all numbers little-endian):

* ``uint32`` length n of the header in bytes;
* the header as UTF-8 JSON, padded with spaces to a multiple of 4 so the arrays after it start
  on a 4-byte boundary;
* ``uint32`` flat indices of the points into the grid (C order of ``shape``), increasing;
* ``float32`` raw score of each point;
* ``uint8`` 1 for a kept point and 0 for a carved one, present when ``has_mask``;
* ``float32`` the value the cutoff was compared with at each point, present when
  ``has_compared_scores``.

Header keys: ``origin``, ``shape``, ``voxel_size``, ``scores_kind``, ``weight_unit``,
``score_min`` and ``score_max`` (of all occupied voxels, not only the points), ``occupied_count``,
``point_count``, ``thinning_step``, ``has_mask``, ``has_compared_scores``.
"""
from __future__ import annotations

import json
import math
import os
import struct
from pathlib import Path
from typing import TypeVar

import numpy as np
from pydantic import BaseModel

from ..mode_registry import MODES
from ..pydantic_schemas import PreprocessingManifest, ThresholdingManifest
from ..stage_settings import stage_folder

SCORE_POINTS_CAP = 1_000_000
MANIFEST_FILE_NAME = "manifest.json"
HEADER_ALIGNMENT_BYTES = 4

StageManifest = TypeVar("StageManifest", bound=BaseModel)


def read_stage_manifest(run_folder: Path, stage: str, manifest_class: type[StageManifest]) -> tuple[StageManifest, Path] | None:
    """The manifest of a stage of the run and the folder it lives in; None when the stage has no readable manifest."""
    stage_folder_path = stage_folder(run_folder, stage)
    try:
        manifest = manifest_class.model_validate_json((stage_folder_path / MANIFEST_FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return manifest, stage_folder_path


def resolve_stored_path(manifest_folder: Path, stored_path: str) -> Path:
    """The file a manifest path points at: relative to the manifest's folder, or absolute."""
    path = Path(stored_path)
    return path if path.is_absolute() else Path(os.path.normpath(manifest_folder / path))


def build_score_points(run_folder: Path, cap: int = SCORE_POINTS_CAP) -> bytes | None:
    """The score layer of a run (layout in the module description); None without preprocessing output.

    More than ``cap`` occupied voxels are thinned to every ``thinning_step``-th one in grid order.
    The kept mask and the compared scores come from thresholding and are left out when thresholding
    has not run on this preprocessing output.
    """
    run_folder = Path(run_folder)
    preprocessing = read_stage_manifest(run_folder, "preprocessing", PreprocessingManifest)
    if preprocessing is None:
        return None
    preprocessing_manifest, preprocessing_folder = preprocessing
    voxel_grid = np.load(resolve_stored_path(preprocessing_folder, preprocessing_manifest.voxel_grid_path))
    all_scores = np.load(resolve_stored_path(preprocessing_folder, preprocessing_manifest.scores_path)).ravel()

    occupied_indices = np.flatnonzero(voxel_grid.ravel())
    occupied_count = len(occupied_indices)
    thinning_step = max(1, math.ceil(occupied_count / cap))
    point_indices = occupied_indices[::thinning_step]
    point_scores = all_scores[point_indices].astype("<f4")
    occupied_scores = all_scores[occupied_indices]

    kept_mask, compared_scores = _thresholding_arrays(run_folder, preprocessing_manifest.run_id)
    header = {
        "origin": list(preprocessing_manifest.origin),
        "shape": list(preprocessing_manifest.shape),
        "voxel_size": preprocessing_manifest.voxel_size,
        "scores_kind": preprocessing_manifest.scores_kind,
        "weight_unit": MODES[preprocessing_manifest.mode].weight_unit,
        "score_min": float(occupied_scores.min()) if occupied_count else None,
        "score_max": float(occupied_scores.max()) if occupied_count else None,
        "occupied_count": occupied_count,
        "point_count": len(point_indices),
        "thinning_step": thinning_step,
        "has_mask": kept_mask is not None,
        "has_compared_scores": compared_scores is not None,
    }
    header_bytes = json.dumps(header).encode("utf-8")
    header_bytes += b" " * (-len(header_bytes) % HEADER_ALIGNMENT_BYTES)

    blob_parts = [struct.pack("<I", len(header_bytes)), header_bytes,
                  point_indices.astype("<u4").tobytes(), point_scores.tobytes()]
    if kept_mask is not None:
        blob_parts.append(kept_mask[point_indices].astype("u1").tobytes())
    if compared_scores is not None:
        blob_parts.append(compared_scores[point_indices].astype("<f4").tobytes())
    return b"".join(blob_parts)


def _thresholding_arrays(run_folder: Path, preprocessing_run_id: str) -> tuple[np.ndarray | None, np.ndarray | None]:
    """The flat kept mask and compared scores of the thresholding run built on this preprocessing run; None for a missing one."""
    thresholding = read_stage_manifest(run_folder, "thresholding", ThresholdingManifest)
    if thresholding is None:
        return None, None
    thresholding_manifest, thresholding_folder = thresholding
    if thresholding_manifest.upstream_run_id != preprocessing_run_id:
        return None, None       # thresholding ran on an earlier preprocessing run
    kept_mask = np.load(resolve_stored_path(thresholding_folder, thresholding_manifest.mask_path)).ravel()
    compared_path = thresholding_manifest.scores_compared_with_cutoff_path
    compared_scores = None if compared_path is None else np.load(resolve_stored_path(thresholding_folder, compared_path)).ravel()
    return kept_mask, compared_scores
