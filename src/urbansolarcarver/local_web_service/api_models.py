"""Request and response models of the local web service.

Pydantic models for the files the service stores and the JSON it exchanges
with the browser app. This module holds no behaviour.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StageRecord(BaseModel):
    """What one completed pipeline stage of a project was run with."""
    config: dict                # the config.yaml content the stage ran with
    inputs_revision: int        # ProjectJson.inputs_revision at the time of the run
    manifest_run_id: str        # run_id of the manifest the stage wrote


class ProjectJson(BaseModel):
    """The content of a project's project.json."""
    name: str
    created: str                # ISO 8601, UTC
    inputs_revision: int = 1    # raised by every upload and removal of an input file
    input_files: dict[str, dict[str, int]] = Field(default_factory=dict)  # role -> file name -> triangle count
    stage_records: dict[str, StageRecord] = Field(default_factory=dict)   # stage name -> record


StageState = Literal["current", "out_of_date", "missing"]


class StageStatusReply(BaseModel):
    """Whether each pipeline stage of a project has output that matches the settings and inputs now."""
    stages: dict[str, StageState]   # stage name -> state, in pipeline order


class StartRunReply(BaseModel):
    """The answer to a request to run: a run started, or every stage asked for is already current."""
    status: Literal["started", "up_to_date"]
    run_id: str | None              # None when up to date
    stages: list[str]               # the stages the run executes, in pipeline order; empty when up to date


class InputFileInfo(BaseModel):
    """One uploaded input file as listed in the file lists of the inputs screen."""
    name: str
    triangle_count: int         # 0 for the weather file


class InputFilesReply(BaseModel):
    """The files of one input role after an upload or a removal."""
    role: str
    files: list[InputFileInfo]  # sorted by name
    joined_bounds: list[list[float]] | None   # [[xmin, ymin, zmin], [xmax, ymax, zmax]] of the joined max volume, whatever the role
    weather_location: str | None              # "<city>, <country>" from the weather file, None without one


class ProjectSummary(BaseModel):
    """One row of the start screen's project list."""
    name: str
    created: str                # ISO 8601, UTC
    modified: str               # ISO 8601, UTC: newest modification time of project.json and config.yaml
    mode: str


class GridPlanReply(BaseModel):
    """The voxel grid a max volume and a voxel size would give, and the engine's limit for it."""
    resolution: int             # voxels per side
    voxel_size: float           # meters
    total_voxels: int
    extent: float               # side of the grid in meters
    budget_voxels: int          # the most voxels preprocessing can score


class ConfigReply(BaseModel):
    """The settings of a project after a save, without the paths and device the service owns."""
    settings: dict
    grid_plan: GridPlanReply | None     # None before a max volume is uploaded


class FieldErrorReply(BaseModel):
    """One invalid setting."""
    field: str | None           # None for a check that involves several settings
    message: str


class ConfigErrorReply(BaseModel):
    """The body of a rejected settings save."""
    field_errors: list[FieldErrorReply]
    grid_plan: GridPlanReply | None     # the rejected plan when the error is the voxel budget


class CarvingSummary(BaseModel):
    """The numbers thresholding reports for the run summary of the carving screen."""
    threshold_value: float
    voxels_occupied: int
    voxels_kept: int
    voxels_removed: int
    retention_pct: float
    obstruction_fraction_carved: float | None   # weighted modes only
    carve_above_extra_voxels_removed: int
    slope_limit_extra_voxels_removed: int


class MassingSummary(BaseModel):
    """The numbers massing reports for the run summary of the envelope and massing screen."""
    floor_area_m2_per_storey: list[float]
    total_floor_area_m2: float
    storeys_built: int
    envelope_volume_m3: float


class RunSummary(BaseModel):
    """What the finished stages of a run report; a part is None when its stage has no output."""
    carving: CarvingSummary | None
    massing: MassingSummary | None


class SkyDome(BaseModel):
    """The 145 Tregenza sky patches with the weight the run gave each."""
    directions: list[list[float]]   # unit vectors toward the patch centres, z up
    solid_angles: list[float]       # steradians
    weights: list[float]


class SunMarker(BaseModel):
    """The sun at one whole hour of the analysis period."""
    hour: int
    vector: list[float]             # unit vector toward the sun, in model coordinates


class SunPathDay(BaseModel):
    """The sun path of one day of the analysis period."""
    date: str                       # "12-21": month and day
    day_path: list[list[float]]     # sunrise to sunset every 10 minutes, both ends on the horizon (z = 0)
    period_path: list[list[float]]  # the daily analysis hours every 5 minutes, above the minimum altitude
    markers: list[SunMarker]


class SunPath(BaseModel):
    """The first and the last day of the analysis period; empty when the settings give no sun path."""
    days: list[SunPathDay]
