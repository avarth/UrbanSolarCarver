"""The score layer of the carving screen as one binary blob.

The browser draws the occupied voxels of the grid as points coloured by their score. This
module reads them from the preprocessing and thresholding outputs of one criterion of a run
(run/criteria/<id>/, by default the last criterion that is on) and packs them,
thinned to a point budget, in the layout below (all numbers little-endian):

* ``uint32`` length n of the header in bytes;
* the header as UTF-8 JSON, padded with spaces to a multiple of 4 so the arrays after it start
  on a 4-byte boundary;
* ``uint32`` flat indices of the points into the grid (C order of ``shape``), increasing;
* ``float32`` raw score of each point;
* ``uint8`` 1 for a kept point and 0 for a carved one, present when ``has_mask``;
* ``float32`` the value the cutoff was compared with at each point, present when
  ``has_compared_scores``.

Header keys: ``origin``, ``shape``, ``voxel_size``, ``mode`` (of the analysis), ``scores_kind``, ``weight_unit``, ``score_unit``,
``score_min`` and ``score_max`` (of the finite scores of all occupied voxels, not only the points;
null when there are none), ``compared_score_max`` (the same for the compared scores: the highest cutoff that still carves;
null without compared scores), ``occupied_count``, ``point_count``, ``thinning_step``, ``has_mask``,
``has_compared_scores``.

``build_carved_by_criterion`` packs which criterion removed each voxel, in a blob with the same first two parts (length and
padded JSON header) followed by one ``uint8`` per voxel of the grid in C order: 0 for a voxel the last criterion that is on kept or
that was never occupied, *k* for a voxel removed by the *k*-th criterion that is on (1-based, in chain order). Header keys:
``origin``, ``shape``, ``voxel_size``, ``criterion_ids`` (the criteria that are on, in chain order).

The builders raise ProjectError 404 when what they pack is not there: a criterion without output has no results to show.
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
from .criteria import active_criteria, criterion_run_folder, find_criterion
from .project_names import ProjectError
from .projects import RUN_FOLDER, ProjectStore

SCORE_POINTS_CAP = 1_000_000
MANIFEST_FILE_NAME = "manifest.json"
HEADER_ALIGNMENT_BYTES = 4

NO_SCORES_MESSAGE = "This project has no scores yet: run the analysis first."

StageManifest = TypeVar("StageManifest", bound=BaseModel)


def chosen_criterion_id(store: ProjectStore, name: str, criterion_id: str | None) -> str:
    """*criterion_id* (ProjectError 404 when the project has no such criterion), or the last criterion that is on for None
    (ProjectError 404 when none is on)."""
    if criterion_id is not None:
        return find_criterion(store.read_project_json(name), criterion_id).id
    active = active_criteria(store.criteria(name))
    if not active:
        raise ProjectError(NO_SCORES_MESSAGE, status_code=404)
    return active[-1].id


def read_stage_manifest(run_folder: Path, stage: str, manifest_class: type[StageManifest],
                        criterion_id: str | None = None) -> tuple[StageManifest, Path] | None:
    """The manifest of a stage of the run and the folder it lives in; None when the stage has no readable manifest.

    Preprocessing and thresholding are read from the folder of the criterion *criterion_id* (run/criteria/<id>/<stage>);
    without one, from run/<stage> (exporting and massing).
    """
    stage_folder_path = (stage_folder(run_folder, stage) if criterion_id is None
                         else criterion_run_folder(run_folder, criterion_id, stage))
    try:
        manifest = manifest_class.model_validate_json((stage_folder_path / MANIFEST_FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return manifest, stage_folder_path


def resolve_stored_path(manifest_folder: Path, stored_path: str) -> Path:
    """The file a manifest path points at: relative to the manifest's folder, or absolute."""
    path = Path(stored_path)
    return path if path.is_absolute() else Path(os.path.normpath(manifest_folder / path))


def build_score_points(store: ProjectStore, name: str, criterion_id: str | None = None, cap: int = SCORE_POINTS_CAP) -> bytes:
    """The score layer of a criterion of the project's run (layout in the module description); the last criterion that is on
    unless *criterion_id* names one.

    ProjectError 404 without preprocessing output of the criterion (or an unknown criterion, or none that is on).
    More than ``cap`` occupied voxels are thinned to every ``thinning_step``-th one in grid order.
    The kept mask and the compared scores come from thresholding and are left out when thresholding
    has not run on this preprocessing output.
    """
    run_folder = store.open(name) / RUN_FOLDER
    criterion_id = chosen_criterion_id(store, name, criterion_id)
    preprocessing = read_stage_manifest(run_folder, "preprocessing", PreprocessingManifest, criterion_id)
    if preprocessing is None:
        raise ProjectError(NO_SCORES_MESSAGE, status_code=404)
    preprocessing_manifest, preprocessing_folder = preprocessing
    voxel_grid = _load_array(resolve_stored_path(preprocessing_folder, preprocessing_manifest.voxel_grid_path))
    all_scores = _load_array(resolve_stored_path(preprocessing_folder, preprocessing_manifest.scores_path)).ravel()

    occupied_indices = np.flatnonzero(voxel_grid.ravel())
    occupied_count = len(occupied_indices)
    thinning_step = max(1, math.ceil(occupied_count / cap))
    point_indices = occupied_indices[::thinning_step]
    point_scores = all_scores[point_indices].astype("<f4")
    occupied_scores = all_scores[occupied_indices]
    finite_occupied_scores = occupied_scores[np.isfinite(occupied_scores)]     # the engine warns about NaN scores, so they occur

    kept_mask, compared_scores = _thresholding_arrays(run_folder, criterion_id, preprocessing_manifest.run_id)
    finite_occupied_compared = (None if compared_scores is None
                                else compared_scores[occupied_indices][np.isfinite(compared_scores[occupied_indices])])
    header = {
        "origin": list(preprocessing_manifest.origin),
        "shape": list(preprocessing_manifest.shape),
        "voxel_size": preprocessing_manifest.voxel_size,
        "mode": preprocessing_manifest.mode,
        "scores_kind": preprocessing_manifest.scores_kind,
        "weight_unit": MODES[preprocessing_manifest.mode].weight_unit,
        "score_unit": MODES[preprocessing_manifest.mode].score_unit,
        "score_min": float(finite_occupied_scores.min()) if len(finite_occupied_scores) else None,
        "score_max": float(finite_occupied_scores.max()) if len(finite_occupied_scores) else None,
        "compared_score_max": (float(finite_occupied_compared.max())
                               if finite_occupied_compared is not None and len(finite_occupied_compared) else None),
        "occupied_count": occupied_count,
        "point_count": len(point_indices),
        "thinning_step": thinning_step,
        "has_mask": kept_mask is not None,
        "has_compared_scores": compared_scores is not None,
    }
    header_bytes = json.dumps(header, allow_nan=False).encode("utf-8")    # JSON.parse refuses NaN and Infinity
    header_bytes += b" " * (-len(header_bytes) % HEADER_ALIGNMENT_BYTES)

    blob_parts = [struct.pack("<I", len(header_bytes)), header_bytes,
                  point_indices.astype("<u4").tobytes(), point_scores.tobytes()]
    if kept_mask is not None:
        blob_parts.append(kept_mask[point_indices].astype("u1").tobytes())
    if compared_scores is not None:
        blob_parts.append(compared_scores[point_indices].astype("<f4").tobytes())
    return b"".join(blob_parts)


def _thresholding_arrays(run_folder: Path, criterion_id: str,
                         preprocessing_run_id: str) -> tuple[np.ndarray | None, np.ndarray | None]:
    """The flat kept mask and compared scores of the criterion's thresholding run built on this preprocessing run; None for a missing one."""
    thresholding = read_stage_manifest(run_folder, "thresholding", ThresholdingManifest, criterion_id)
    if thresholding is None:
        return None, None
    thresholding_manifest, thresholding_folder = thresholding
    if thresholding_manifest.upstream_run_id != preprocessing_run_id:
        return None, None       # thresholding ran on an earlier preprocessing run
    kept_mask = _load_array(resolve_stored_path(thresholding_folder, thresholding_manifest.mask_path)).ravel()
    compared_path = thresholding_manifest.scores_compared_with_cutoff_path
    compared_scores = None if compared_path is None else _load_array(resolve_stored_path(thresholding_folder, compared_path)).ravel()
    return kept_mask, compared_scores


def build_carved_by_criterion(store: ProjectStore, name: str) -> bytes:
    """Which criterion removed each voxel of the grid (layout in the module description).

    A voxel removed by criterion *k* was kept before it (in the mask of the criterion before it that is on, or occupied in the
    maximum volume's voxel grid for the first) and is not kept in its own mask. ProjectError 404 when no criterion is on, a
    criterion that is on has no thresholding output, or the outputs of the criteria are on grids of different shapes.
    """
    run_folder = store.open(name) / RUN_FOLDER
    active = active_criteria(store.criteria(name))
    preprocessing = (None if not active
                     else read_stage_manifest(run_folder, "preprocessing", PreprocessingManifest, active[0].id))
    if preprocessing is None:
        raise ProjectError(NO_SCORES_MESSAGE, status_code=404)
    preprocessing_manifest, preprocessing_folder = preprocessing
    kept_before = _load_array(resolve_stored_path(preprocessing_folder, preprocessing_manifest.voxel_grid_path)).astype(bool)
    carved_by = np.zeros(kept_before.shape, dtype="u1")
    for position, criterion in enumerate(active, start=1):
        kept = _kept_mask(run_folder, criterion.id)
        if kept.shape != kept_before.shape:
            raise ProjectError("The results of the criteria are on different grids: run the analysis again.", status_code=404)
        carved_by[kept_before & ~kept] = position
        kept_before = kept
    header = {
        "origin": list(preprocessing_manifest.origin),
        "shape": list(preprocessing_manifest.shape),
        "voxel_size": preprocessing_manifest.voxel_size,
        "criterion_ids": [criterion.id for criterion in active],
    }
    header_bytes = json.dumps(header, allow_nan=False).encode("utf-8")
    header_bytes += b" " * (-len(header_bytes) % HEADER_ALIGNMENT_BYTES)
    return b"".join([struct.pack("<I", len(header_bytes)), header_bytes, carved_by.tobytes()])


def _kept_mask(run_folder: Path, criterion_id: str) -> np.ndarray:
    """The kept mask of a criterion's thresholding run; ProjectError 404 when it has none."""
    thresholding = read_stage_manifest(run_folder, "thresholding", ThresholdingManifest, criterion_id)
    if thresholding is None:
        raise ProjectError(f"Criterion {criterion_id} has no results yet: run the analysis first.", status_code=404)
    manifest, manifest_folder = thresholding
    return _load_array(resolve_stored_path(manifest_folder, manifest.mask_path)).astype(bool)


def _load_array(path: Path) -> np.ndarray:
    """An array a stage saved; ProjectError 404 when the file is missing or cannot be read (a run that was cut off, a damaged file)."""
    try:
        return np.load(path, allow_pickle=False)
    except (OSError, ValueError):
        raise ProjectError("The results of this run cannot be read: run the analysis again.", status_code=404) from None
