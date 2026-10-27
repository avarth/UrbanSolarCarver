"""Request and response models of the local web service.

Pydantic models for the files the service stores and the JSON it exchanges
with the browser app. This module holds no behaviour.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class StageRecord(BaseModel):
    """What one completed pipeline stage of a project was run with."""
    config: dict                # the config.yaml content the stage ran with
    inputs_revision: int        # ProjectJson.inputs_revision at the time of the run
    manifest_run_id: str        # run_id of the manifest the stage wrote
    test_surfaces_fingerprint: str | None = None     # of the criterion's joined test surface file at the time of the run


class CarvingChainStep(BaseModel):
    """One "carve further": the exported envelope of a run became the project's maximum volume.

    The files it replaced are kept in inputs/earlier_max_volumes/<step>/, so the chain can be traced back to the
    maximum volume the user uploaded.
    """
    step: int                           # 1 for the first carve further, then 2, ...
    mode: str                           # the mode the envelope was carved with
    settings: dict                      # the settings the envelope was carved with, without the paths and device the service owns
    carved_on: str                      # ISO 8601, UTC: when the envelope became the maximum volume
    earlier_max_volume_files: list[str] # the maximum volume files it replaced, now in inputs/earlier_max_volumes/<step>/
    max_volume_file: str                # the envelope's file name among the maximum volume files


class CriterionEntry(BaseModel):
    """One criterion of a project's chain, as project.json keeps it. config.yaml is generated from these."""
    # Assigned by the service from ProjectJson.next_criterion_id, never reused; names the run folder, so digits only.
    id: str = Field(pattern=r"^[0-9]+$")
    name: str
    named_by_user: bool = False         # False: the name follows the mode and the first test surface file (see criteria.py)
    colour: str                         # "#RRGGBB", the criterion's colour in the 3D view
    bypassed: bool = False              # left out of config.yaml, and so of every run, but kept in the list
    test_surface_files: list[str] = Field(default_factory=list)     # file names in inputs/test_surfaces/
    settings: dict = Field(default_factory=dict)    # the criterion's own settings as stored, without the paths the service owns


class StudyEntry(BaseModel):
    """One study of the Simulate workspace, as project.json keeps it: a metric on test surfaces over a period, apart from the criteria."""
    # Assigned by the service from ProjectJson.next_study_id, never reused; names the results folder simulate/<id>, so digits only.
    id: str = Field(pattern=r"^[0-9]+$")
    name: str
    named_by_user: bool = False         # False: the name follows the metric and the period (see studies.py)
    colour: str                         # "#RRGGBB", from the criteria palette
    metric: str                         # a key of check_settings.CHECK_METRICS
    settings: dict = Field(default_factory=dict)    # the period and the mode settings the metric reads (studies.STUDY_SETTING_KEYS)
    target: float | None = Field(None, allow_inf_nan=False)     # in the metric's unit
    test_surface_files: list[str] = Field(default_factory=list)     # file names in inputs/test_surfaces/


class ProjectJson(BaseModel):
    """The content of a project's project.json."""
    name: str
    created: str                # ISO 8601, UTC
    inputs_revision: int = 1    # raised by every upload and removal of an input file
    input_files: dict[str, dict[str, int]] = Field(default_factory=dict)  # role -> file name -> triangle count
    # "exporting" / "massing" -> record, run with the settings of the last criterion that is on (the criteria's own: criterion_records)
    stage_records: dict[str, StageRecord] = Field(default_factory=dict)
    example: str | None = None  # the example the project was made from (examples.json name); None for other projects and older ones
    carving_chain: list["CarvingChainStep"] = Field(default_factory=list)  # each "carve further", oldest first
    criteria: list[CriterionEntry] = Field(default_factory=list)   # the chain, in carving order
    next_criterion_id: int = 1  # the id the next criterion gets
    # criterion id -> "preprocessing" / "thresholding" -> record; the stage records of the criteria
    criterion_records: dict[str, dict[str, StageRecord]] = Field(default_factory=dict)
    studies: list[StudyEntry] = Field(default_factory=list)     # the studies of the Simulate workspace, in the order shown
    next_study_id: int = 1      # the id the next study gets


StageState = Literal["current", "out_of_date", "missing"]


class StageStatusReply(BaseModel):
    """Whether each pipeline stage of a project has output that matches the settings and inputs now."""
    stages: dict[str, StageState]   # stage name -> state, in pipeline order; preprocessing and thresholding sum up the criteria
    # criterion id -> "preprocessing" / "thresholding" -> state, for every criterion that is on, in chain order
    criteria: dict[str, dict[str, StageState]] = Field(default_factory=dict)


class StartRunReply(BaseModel):
    """The answer to a request to run: a run started, or every stage asked for is already current."""
    status: Literal["started", "up_to_date"]
    run_id: str | None              # None when up to date
    stages: list[str]               # the stages the run executes, in pipeline order; empty when up to date
    # every criterion that is on -> the stages the run executes for it (empty for one the run leaves as it is); empty when up to date
    criterion_stages: dict[str, list[str]] = Field(default_factory=dict)


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
    weather_latitude: float | None            # degrees north, negative in the southern hemisphere; None without a usable weather file


class ProjectSummary(BaseModel):
    """One row of the start screen's project list."""
    name: str
    created: str                # ISO 8601, UTC
    modified: str               # ISO 8601, UTC: newest modification time of project.json and config.yaml
    mode: str
    example: str | None = None  # the example the project came from (examples.json name), None for other projects


class GridPlanReply(BaseModel):
    """The voxel grid a max volume and a voxel size would give, and the engine's limit for it."""
    resolution: int             # voxels per side
    voxel_size: float           # meters
    total_voxels: int
    extent: float               # side of the grid in meters
    budget_voxels: int          # the most voxels preprocessing can score


ProjectsFolderSource = Literal["command_line", "preference", "default"]


class ProjectsFolderReply(BaseModel):
    """The folder the projects live in, where that choice came from, and whether the browser may change it now."""
    path: str
    source: ProjectsFolderSource
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


class CriterionSettingsReply(BaseModel):
    """The settings of one criterion with the shared ones, without the paths and device the service owns."""
    criterion_id: str
    settings: dict


class FieldErrorReply(BaseModel):
    """One invalid setting."""
    field: str | None           # None for a check that involves several settings
    message: str


class ConfigErrorReply(BaseModel):
    """The body of a rejected settings save."""
    field_errors: list[FieldErrorReply]
    grid_plan: GridPlanReply | None     # the rejected plan when the error is the voxel budget
    criterion: str | None = None        # the id of the criterion whose settings are invalid (a run start, a criterion change); None for shared ones


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


class EnvelopeSummary(BaseModel):
    """What exporting left for the envelope part of the envelope and massing screen and for Export."""
    mesh_file: str                      # the mesh in the run's exporting folder, in the format it was built in
    envelope_volume_m3: float | None    # the voxels the mesh was built from, after its cleanup; None when their size is not known


class MassingSummary(BaseModel):
    """The numbers massing reports for the run summary of the envelope and massing screen, and its mesh file for Export."""
    export_mesh_file: str               # the plates in the run's massing folder, in the format they were built in
    floor_area_m2_per_storey: list[float]
    total_floor_area_m2: float
    storeys_built: int


class CriterionCarvingSummary(BaseModel):
    """What one criterion that is on reports for the run summary: its carving, and the volume it started with and kept.

    A criterion whose thresholding has no output is listed too, with its numbers None, so the app can say it has not run yet.
    """
    id: str
    name: str
    colour: str                         # "#RRGGBB"
    mode: str
    carving: CarvingSummary | None      # None without thresholding output
    voxels_at_start: int | None         # the voxels it could carve: the previous criterion's kept voxels, the max volume's filled ones for the first
    volume_kept_m3: float | None        # its kept voxels times the voxel size cubed; None without a thresholding and a preprocessing manifest
    volume_removed_m3: float | None = None      # the voxels it started with minus those it kept, times the voxel size cubed; None when either is unknown


class ChainSummary(BaseModel):
    """What the chain of criteria that are on kept, from the volumes of the criteria."""
    volume_after_each_m3: list[float]       # the volume each criterion kept, in chain order
    # the last criterion's kept volume over the filled volume of the maximum volume; None when that has no filled voxel
    share_of_max_volume_kept: float | None


class RunSummary(BaseModel):
    """What the finished stages of a run report; a part is None when its stage has no output.

    ``carving`` describes the last criterion that is on; ``criteria`` has every criterion that is on, in chain order.
    """
    carving: CarvingSummary | None
    envelope: EnvelopeSummary | None
    massing: MassingSummary | None
    criteria: list[CriterionCarvingSummary] = Field(default_factory=list)
    chain: ChainSummary | None = None   # None until every criterion that is on has thresholding output


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


class ColdPeriodDates(BaseModel):
    """Start and end of the cold period (inclusive); start after end wraps across the new year."""
    start_month: int
    start_day: int
    end_month: int
    end_day: int


class ColdPeriodReply(BaseModel):
    """The cold period of the project's weather file for a base temperature (cold_period.py)."""
    status: Literal["found", "none", "no_weather_file"]     # "none": no day of the year is cold enough
    period: ColdPeriodDates | None = None


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
    weight_unit: str            # of the sky-patch weights
    score_unit: str             # of a voxel's score and of a score cutoff: "kWh", "m²", "m²·h"
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
    context: list[str] = []     # optional: existing surroundings
    terrain: list[str] = []     # optional


class ExampleInfo(BaseModel):
    """One example as the start screen lists it."""
    name: str
    title: str
    description: str
    project: str | None = None  # the existing project made from this example (the most recently modified), None when there is none


# The mode of a new project, and the mode a project's settings return to when it carves further.
NEW_PROJECT_MODE = "time-based"


class CreateProjectRequest(BaseModel):
    """The body of a request to create a project."""
    name: str
    mode: str = NEW_PROJECT_MODE


class RenameProjectRequest(BaseModel):
    """The body of a request to rename a project."""
    new_name: str


class ConfigValuesRequest(BaseModel):
    """The body of a settings save: the settings as the browser holds them."""
    values: dict


class CreateCriterionRequest(BaseModel):
    """The body of a request to add a criterion: its mode, and optionally its name (default: from the mode and its first test surface)."""
    mode: str
    name: str | None = None


class UpdateCriterionRequest(BaseModel):
    """The body of a criterion change: what is not sent (or null) stays as it is."""
    name: str | None = None
    colour: str | None = None           # "#RRGGBB"
    bypassed: bool | None = None
    values: dict | None = None          # the criterion's settings as the browser holds them


class CriterionOrderRequest(BaseModel):
    """The body of a reorder: the id of every criterion once, in the new carving order."""
    ids: list[str]


class AddStudyRequest(BaseModel):
    """The body of a request to add a study: from a metric (its defaults), or like a criterion (its metric, period, mode settings and files)."""
    metric: str | None = None
    from_criterion: str | None = None   # the id of a criterion

    @model_validator(mode="after")
    def _exactly_one(self) -> "AddStudyRequest":
        if (self.metric is None) == (self.from_criterion is None):
            raise ValueError("Give either a metric or a criterion to copy, not both and not neither.")
        return self


class UpdateStudyRequest(BaseModel):
    """The body of a study change: what is not sent stays as it is; target null means no target."""
    name: str | None = None
    metric: str | None = None
    values: dict | None = None          # the metric's settings among studies.STUDY_SETTING_KEYS; they change those keys only
    target: float | None = Field(None, allow_inf_nan=False)


class ReorderStudiesRequest(BaseModel):
    """The body of a reorder of the studies: the id of every study once, in the new order."""
    ids: list[str]


class MetricInfo(BaseModel):
    """One metric the Simulate workspace can show, with what the page needs to offer it."""
    name: str
    label: str
    unit: str
    needs_epw: bool
    available: bool                     # its inputs exist: the weather file when it needs one
    default_settings: dict              # the period and the mode settings a new study of this metric starts with


StudyState = Literal["current", "out_of_date", "not_run", "refused"]


class StudyWithState(BaseModel):
    """A study with the state of its last result (simulation.study_state)."""
    entry: StudyEntry
    # refused: it cannot run (reason says why); not_run: no result; out_of_date: a file or setting it was computed from changed
    state: StudyState
    reason: str | None = None
    geometries: list[str] = Field(default_factory=list)    # the geometries of the last result: max_volume, then envelope, massing when built


class StudiesReply(BaseModel):
    """The studies of a project with their state, and the metrics a study can show."""
    studies: list[StudyWithState]
    metrics: list[MetricInfo]


class StartRunRequest(BaseModel):
    """The body of a request to run: the stages whose results are wanted."""
    produce: list[str] = Field(default_factory=lambda: ["exporting", "massing"])


class ProjectDetail(BaseModel):
    """Everything the browser needs when it opens a project."""
    name: str
    created: str                # ISO 8601, UTC
    modified: str               # ISO 8601, UTC
    example: str | None = None  # as in ProjectSummary: the app offers "Reset to the example" when it is set
    settings: dict              # without the paths and device the service owns; the shared ones and those of one criterion (default: the first)
    inputs: dict[str, list[InputFileInfo]]      # role -> files, for every role
    joined_bounds: list[list[float]] | None     # as in InputFilesReply
    weather_location: str | None
    weather_latitude: float | None              # as in InputFilesReply
    stage_status: StageStatusReply
    grid_plan: GridPlanReply | None             # of the stored settings, as a save would plan it; None without a max volume
    carving_chain: list[CarvingChainStep] = Field(default_factory=list)   # as in ProjectJson
    criteria: list[CriterionEntry] = Field(default_factory=list)          # the chain in carving order, bypassed criteria included
    criterion_status: dict[str, dict[str, StageState]] = Field(default_factory=dict)    # as stage_status.criteria


class CancelRunReply(BaseModel):
    """Whether the run was stopped by this request; False when it had already ended."""
    cancelled: bool


class ErrorDetailReply(BaseModel):
    """The body of a request the service refuses with a message."""
    detail: str


class MissingInputsReply(ErrorDetailReply):
    """The body of a run request that lacks input files."""
    missing_inputs: list[str]   # max_volume, "test_surfaces:<criterion id>" (a criterion that is on protects nothing), "criteria" (none is on), weather; context and terrain are optional
