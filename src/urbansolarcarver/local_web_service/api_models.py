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


class ProjectsFolderReply(BaseModel):
    """The folder the projects live in, where that choice came from, and whether the browser may change it now."""
    path: str
    source: Literal["command_line", "preference", "default"]
    can_change: bool            # false when the folder came from the command line, or while a run is active


class ProjectsFolderChoiceReply(BaseModel):
    """The answer to Change folder: the folder changed, the user cancelled, or the folder picker cannot open here."""
    status: Literal["changed", "cancelled", "unavailable"]
    path: str                   # the projects folder after the request
    problem: str | None         # why the picker is unavailable; None otherwise


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


class WarmUpState(BaseModel):
    """How far the background preparation of the compute device has come."""
    state: Literal["not_started", "running", "ready", "cpu", "failed"]     # "cpu": the CPU is used
    device_name: str | None = None      # the CUDA device as torch names it; None until known and on the CPU
    problem: str | None = None          # why the preparation failed
    # Whether torch sees a CUDA device. In state "cpu", False means there is none and True means the CPU was chosen
    # at launch (``usc ui --device cpu``) on a machine that has one. True when "ready"; None until known and when "failed".
    cuda_available: bool | None = None


class HealthReply(BaseModel):
    """The version of the running service and the state of the device preparation."""
    version: str
    warm_up: WarmUpState


class ModeInfo(BaseModel):
    """One carving mode as the new-project and settings screens describe it."""
    name: str
    description: str
    needs_epw: bool
    needs_period: bool
    experimental: bool
    score_kind: Literal["weighted_sum", "violation_count"]
    weight_unit: str
    starting_values: dict       # the settings a new project of this mode starts with


class ExampleProject(BaseModel):
    """One entry of example_projects/examples.json: an example project and the packaged files it is made of."""
    name: str                   # the folder under example_projects/
    title: str
    description: str            # one plain sentence for the start screen
    mode: str
    max_volume: list[str]       # file names in the example's folder
    test_surfaces: list[str]
    weather: bool               # whether the project gets the packaged weather file


class ExampleInfo(BaseModel):
    """One example as the start screen lists it."""
    name: str
    title: str
    description: str


class CreateProjectRequest(BaseModel):
    """The body of a request to create a project."""
    name: str
    mode: str = "time-based"


class ConfigValuesRequest(BaseModel):
    """The body of a settings save: the settings as the browser holds them."""
    values: dict


class StartRunRequest(BaseModel):
    """The body of a request to run: the stages whose results are wanted."""
    produce: list[str] = Field(default_factory=lambda: ["exporting", "massing"])


class ProjectDetail(BaseModel):
    """Everything the browser needs when it opens a project."""
    name: str
    created: str                # ISO 8601, UTC
    modified: str               # ISO 8601, UTC
    settings: dict              # without the paths and device the service owns
    inputs: dict[str, list[InputFileInfo]]      # role -> files, for every role
    joined_bounds: list[list[float]] | None     # as in InputFilesReply
    weather_location: str | None
    stage_status: StageStatusReply
    grid_plan: GridPlanReply | None             # of the stored settings, as a save would plan it; None without a max volume


class CancelRunReply(BaseModel):
    """Whether the run was stopped by this request; False when it had already ended."""
    cancelled: bool


class ErrorDetailReply(BaseModel):
    """The body of a request the service refuses with a message."""
    detail: str


class MissingInputsReply(ErrorDetailReply):
    """The body of a run request that lacks input files."""
    missing_inputs: list[str]   # the roles: max_volume, test_surfaces, weather
