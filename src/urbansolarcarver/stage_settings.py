"""Per-stage settings projected from the flat configuration.

Each stage reads only its own settings model; ``RunOptions`` holds what
does not affect results.  ``effective_values`` gives the values a stage will
apply (defaults resolved, fields its mode does not read left out), so two
configs that mean the same compare equal, and :func:`stages_to_rerun` turns
those comparisons into the list of stages to run.

This module must not import ``api_core`` (it pulls in torch).
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Union

import numpy as np
from pydantic import BaseModel, ConfigDict

from .mode_registry import MODES
from .pydantic_schemas import (
    _MODE_SPECIFIC_FIELDS, ThresholdSpec, UserConfig, resolve_max_slope_deg, resolve_threshold,
)

PIPELINE_STAGES = ("preprocessing", "thresholding", "exporting", "massing")


def stage_folder(run_folder: Union[Path, str], stage: str) -> Path:
    """The folder of *stage* in a run folder: ``<run_folder>/<stage>``."""
    return Path(run_folder) / stage

# The stages nothing else reads: they are what a run produces for the user.
_LEAF_STAGES = ("exporting", "massing")

# Stages that have to be current before each stage can run, itself included.
_STAGES_NEEDED_BY = {
    "preprocessing": ("preprocessing",),
    "thresholding": ("preprocessing", "thresholding"),
    "exporting": ("preprocessing", "thresholding", "exporting"),
    "massing": ("preprocessing", "thresholding", "massing"),
}


def stages_needed_for(produce: Iterable[str]) -> List[str]:
    """The stages that have to be current to produce *produce*, in pipeline order.

    Each produced stage brings the stages it reads (exporting and massing
    read thresholding, which reads preprocessing).  Raises ValueError for a
    name that is not in :data:`PIPELINE_STAGES`.
    """
    produced = set(produce)
    unknown = produced - set(PIPELINE_STAGES)
    if unknown:
        raise ValueError(
            f"unknown stage(s) {sorted(unknown)}; expected names from {list(PIPELINE_STAGES)}")
    needed = set().union(*(_STAGES_NEEDED_BY[name] for name in produced)) if produced else set()
    return [name for name in PIPELINE_STAGES if name in needed]


def requested_smoothing_radius_m(kind: str, voxel_size: float, score_smoothing: Optional[float]) -> float:
    """The Gaussian radius in meters that was asked for, before clipping; 0 when off.

    Violation-count scores are never smoothed.  For weighted-sum scores,
    ``score_smoothing`` None means 1.1 x ``voxel_size``, 0 means off and a
    positive value is the radius in meters.  With no usable ``voxel_size``
    the radius cannot be converted to voxels and nothing is requested.
    """
    if kind != "weighted_sum" or not voxel_size or voxel_size <= 0:
        return 0.0
    if score_smoothing is None:
        return 1.1 * voxel_size
    if score_smoothing > 0:
        return float(score_smoothing)
    return 0.0


def applied_smoothing_radius_m(kind: str, voxel_size: float, score_smoothing: Optional[float]) -> float:
    """The Gaussian radius in meters that score smoothing applies, 0 when off.

    This is :func:`requested_smoothing_radius_m` with its radius in voxels
    clipped to 0.5 to 8 and converted back to meters.
    """
    requested_m = requested_smoothing_radius_m(kind, voxel_size, score_smoothing)
    if requested_m <= 0:
        return 0.0
    requested_voxels = requested_m / voxel_size
    clipped_voxels = float(np.clip(requested_voxels, 0.5, 8.0))
    if clipped_voxels == requested_voxels:
        return requested_m
    return clipped_voxels * voxel_size


class _StageSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @classmethod
    def from_config(cls, config: UserConfig):
        return cls(**{name: getattr(config, name) for name in cls.model_fields})


class PreprocessingSettings(_StageSettings):
    max_volume_path: str
    test_surface_path: str
    epw_path: Optional[str]
    start_month: Optional[int]
    start_day: Optional[int]
    start_hour: Optional[int]
    end_month: Optional[int]
    end_day: Optional[int]
    end_hour: Optional[int]
    mode: str
    voxel_size: float
    grid_step: float
    margin_frac: float
    edge_taper: float
    ray_length: float
    min_altitude: float
    sun_steps_per_hour: int
    north_deg: float
    dew_point_celsius: float
    bliss_k: float
    min_sky_elevation_deg: float
    balance_temperature: float
    balance_offset: float
    simulated_weights_path: Optional[str]
    include_harm: bool
    tilted_plane_angle_deg: Optional[Union[float, List[float]]]

    def effective_values(self) -> dict:
        """Every field except the mode-specific ones this mode does not read."""
        unread = _MODE_SPECIFIC_FIELDS - MODES[self.mode].extra_params
        return {name: value for name, value in self.model_dump().items() if name not in unread}


class ThresholdingSettings(_StageSettings):
    threshold: Optional[ThresholdSpec]
    carve_fraction: float
    score_smoothing: Optional[float]
    carve_above: bool
    carve_above_min_consecutive: int
    max_slope_deg: Optional[float]

    def effective_values(self, mode: str, voxel_size: float) -> dict:
        """What thresholding applies for *mode* and *voxel_size*: the resolved
        threshold, the smoothing radius in meters after clipping and the
        resolved slope limit."""
        return {
            "threshold": resolve_threshold(mode, self.threshold, self.carve_fraction).model_dump(),
            "score_smoothing_m": applied_smoothing_radius_m(
                MODES[mode].score_kind, voxel_size, self.score_smoothing),
            "max_slope_deg": resolve_max_slope_deg(mode, self.max_slope_deg),
            "carve_above": self.carve_above,
            "carve_above_min_consecutive": self.carve_above_min_consecutive,
        }


class ExportingSettings(_StageSettings):
    final_mesh_format: str
    apply_smoothing: bool
    min_voxels: int
    min_face_count: int
    smooth_iters: int

    def effective_values(self) -> dict:
        """Every field, without ``smooth_iters`` when smoothing is off."""
        values = self.model_dump()
        if not self.apply_smoothing:
            del values["smooth_iters"]
        return values


class MassingSettings(_StageSettings):
    ground_floor_height: float
    floor_height: float
    min_plate_dimension: float
    plate_tolerance: float
    plate_stacking: str

    def effective_values(self) -> dict:
        return self.model_dump()


class RunOptions(_StageSettings):
    """How a run executes. Never compared: none of it changes the results
    (device and batch size are recorded in diagnostics instead)."""
    out_dir: str
    device: str
    ray_batch_size: int
    diagnostics: bool
    diagnostic_plots: bool


def stages_to_rerun(previous_config: Optional[UserConfig], new_config: UserConfig,
                    produce: Iterable[str]) -> List[str]:
    """The stages to run, in pipeline order, to bring *produce* up to date.

    Compares settings only; whether an input file changed, or whether a stage
    was ever run, is for the caller to decide.

    * Preprocessing effective values differ: preprocessing, thresholding and
      the produced leaves (exporting, massing).
    * Else thresholding differs: thresholding and the produced leaves.
    * Else each produced leaf whose own effective values differ.

    Only stages that *produce* needs are listed, so producing "preprocessing"
    alone stops the list there.  With no *previous_config*, every stage
    needed for *produce* is listed.  Raises ValueError for a name that is not
    in :data:`PIPELINE_STAGES`.
    """
    produced = set(produce)
    needed = set(stages_needed_for(produced))
    leaves = [name for name in _LEAF_STAGES if name in produced]

    if previous_config is None:
        to_run = needed
    else:
        previous, new = (_effective_values_by_stage(c) for c in (previous_config, new_config))
        if previous["preprocessing"] != new["preprocessing"]:
            to_run = {"preprocessing", "thresholding", *leaves}
        elif previous["thresholding"] != new["thresholding"]:
            to_run = {"thresholding", *leaves}
        else:
            to_run = {name for name in leaves if previous[name] != new[name]}
    return [name for name in PIPELINE_STAGES if name in to_run and name in needed]


def _effective_values_by_stage(config: UserConfig) -> dict:
    return {
        "preprocessing": PreprocessingSettings.from_config(config).effective_values(),
        "thresholding": ThresholdingSettings.from_config(config).effective_values(
            config.mode, config.voxel_size),
        "exporting": ExportingSettings.from_config(config).effective_values(),
        "massing": MassingSettings.from_config(config).effective_values(),
    }
