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
    weights_key: str | None = None      # preprocessing of an energy-weighted criterion: the typical building's key at the start of the run


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
    # Solar usefulness only (other modes ignore it): the hours count by the typical building's weights, not by the cold hours rule.
    # config.yaml then names the weights file and leaves out the balance temperature, which settings keep (criteria.engine_settings).
    energy_weighted: bool = False


class TypicalBuildingEntry(BaseModel):
    """The typical building of a project, which the energy-weighted criteria share (typical_building.py): a copy of its values and
    the library entry they came from."""
    values: dict                        # the form's values (typical_building.VALUE_KEYS and the keys of the room)
    library_id: str | None = None       # the library entry it came from (typical_building.library_entry); None for none
    library_name: str | None = None     # that entry's name when it was chosen, kept when the entry is renamed or deleted
    calculated_key: str | None = None   # the key of the weights in inputs/typical_building/weights.json; None before a calculation


class StudyEntry(BaseModel):
    """One study of the Simulate workspace, as project.json keeps it: a metric on test surfaces over a period, apart from the criteria."""
    # Assigned by the service from ProjectJson.next_study_id, never reused; names the results folder simulate/<id>, so digits only.
    id: str = Field(pattern=r"^[0-9]+$")
    name: str
    named_by_user: bool = False         # False: the name follows the metric and the period (see studies.py)
    colour: str                         # "#RRGGBB", from the criteria palette
    metric: str                         # a key of check_settings.CHECK_METRICS
    settings: dict = Field(default_factory=dict)    # the period and the mode settings the metric reads (studies.STUDY_SETTING_KEYS)
    target: float | None = Field(None, allow_inf_nan=False)     # in the metric's unit; the low end of the colour scale by value
    target_max: float | None = Field(None, allow_inf_nan=False)     # in the metric's unit; the high end of the colour scale by value
    test_surface_files: list[str] = Field(default_factory=list)     # file names in inputs/test_surfaces/


class StoredFileRecord(BaseModel):
    """A stored input file as it was when the service last read it (stored_files.py tells a file changed in the folder by it)."""
    size: int                   # bytes
    modified_ns: int            # modification time, nanoseconds since the epoch
    digest: str                 # sha256 of the content, hex


class ChangedFileNotice(BaseModel):
    """A stored input file whose change in the project folder the service found and built into the joined files; shown until dismissed."""
    role: str
    file_name: str
    noticed: str                # ISO 8601, UTC: when the service found the change


class ProjectJson(BaseModel):
    """The content of a project's project.json."""
    name: str
    created: str                # ISO 8601, UTC
    inputs_revision: int = 1    # raised by every upload and removal of an input file, and a change in the folder (stored_files.py)
    input_files: dict[str, dict[str, int]] = Field(default_factory=dict)  # role -> file name -> triangle count
    stored_files: dict[str, dict[str, StoredFileRecord]] = Field(default_factory=dict)  # role -> file name -> record
    changed_files: list[ChangedFileNotice] = Field(default_factory=list)  # the changes found in the folder, not dismissed yet
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
    typical_building: TypicalBuildingEntry | None = None    # None: the default entry (typical_building.DEFAULT_LIBRARY_ID), not calculated


StageState = Literal["current", "out_of_date", "missing"]


class InputFileChange(BaseModel):
    """A stored input file changed in the project folder (a notice not dismissed yet) or missing from it."""
    role: str
    file_name: str
    state: Literal["changed", "missing"]
    noticed: str | None = None      # a changed one: when the service found the change (a later change of the file is another notice)


class InspectedFile(BaseModel):
    """What the Inspect workspace shows of one input mesh file (inspection.py)."""
    role: str
    file_name: str
    triangle_count: int
    area_m2: float
    bounds: list[list[float]]           # [[xmin, ymin, zmin], [xmax, ymax, zmax]]
    body_count: int                     # the groups of triangles joined by shared edges
    closed_body_count: int              # the bodies with no open edge
    surface_count: int | None = None    # the same groups for a test surface file; None for other roles
    flippable: bool = False             # a test surface file that is open somewhere; False when closed as a whole and for other roles
    original_kept: bool = False         # a test surface file whose original from before a flip is kept
    problem: str | None = None          # why the file cannot be read (the counts are then zero); None for a file that is read
    # The sha256 of the stored file's bytes as Inspect read it: a turn or a restore names it, and is refused when the file stored
    # now is another. Empty when the file's bytes could not be read.
    version: str = ""


class TurnSurfacesRequest(BaseModel):
    """The surfaces of a test surface file to turn the other way and save (their numbers in the geometry of the file), and the
    version of the file they were turned on (InspectedFile.version)."""
    surfaces: list[int] = Field(min_length=1)
    version: str = Field(min_length=1)


class RestoreOriginalRequest(BaseModel):
    """The version of the stored test surface file (InspectedFile.version) that the kept original is to replace."""
    version: str = Field(min_length=1)


class InspectReply(BaseModel):
    """The mesh files of a project in the order max volume, test surfaces, context, terrain, then by file name."""
    files: list[InspectedFile]


class StageStatusReply(BaseModel):
    """Whether each pipeline stage of a project has output that matches the settings and inputs now."""
    stages: dict[str, StageState]   # stage name -> state, in pipeline order; preprocessing and thresholding sum up the criteria
    # criterion id -> "preprocessing" / "thresholding" -> state, for every criterion that is on, in chain order
    criteria: dict[str, dict[str, StageState]] = Field(default_factory=dict)
    input_changes: list[InputFileChange] = Field(default_factory=list)  # the changed ones first, then the missing ones, by role and name


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


class SunChartDay(BaseModel):
    """The sun's arc over one day of Simulate's sun path, above the horizon."""
    date: str                           # "06-21": month and day
    runs: list[list[list[float]]]       # unbroken stretches of unit vectors toward the sun, every 5 minutes


class SunHourLine(BaseModel):
    """Where the sun stands at one whole hour of local standard time through the year (its analemma), above the horizon."""
    hour: int
    runs: list[list[list[float]]]       # unbroken stretches, one point a week


class SunChart(BaseModel):
    """Simulate's sun path: the arcs of the equinox and the solstices, the hour lines, and the arc of the chosen day."""
    key_days: list[SunChartDay]
    hour_lines: list[SunHourLine]
    day: SunChartDay


class SunPosition(BaseModel):
    """The sun at one time, above the horizon."""
    date: str                           # "MM-DD"
    minute: int                         # of the day, local standard time
    vector: list[float]                 # unit vector toward the sun, model coordinates
    altitude: float                     # degrees above the horizon
    azimuth: float                      # degrees clockwise from true north


class SunPositions(BaseModel):
    """The sun above the horizon at the times of a range; a long range is sampled on every *day_step*-th day."""
    positions: list[SunPosition]
    days_sampled: int
    day_step: int
    step_minutes: int


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
    energy_weighted: bool | None = None     # Solar usefulness: count the hours by the typical building (CriterionEntry.energy_weighted)


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
    """The body of a study change: what is not sent stays as it is; target (or target_max) null means none."""
    name: str | None = None
    metric: str | None = None
    values: dict | None = None          # the metric's settings among studies.STUDY_SETTING_KEYS; they change those keys only
    target: float | None = Field(None, allow_inf_nan=False)
    target_max: float | None = Field(None, allow_inf_nan=False)


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


class TypicalBuildingLibraryEntry(BaseModel):
    """A building of the typical building library: a built-in example (read-only) or one of the user's own."""
    id: str
    name: str
    group: Literal["apartment", "office", "test", "own"]    # test: the ASHRAE 140 boxes
    read_only: bool                     # true for the examples
    source: str | None                  # where an example's values come from; None for an own entry
    values: dict


class NewLibraryEntryRequest(BaseModel):
    """The body of Save as new: the name of the new own entry and its values."""
    name: str
    values: dict


class UpdateLibraryEntryRequest(BaseModel):
    """The body of a change of an own entry: a new name (rename), new values (Save to library), or both; an absent one stays."""
    name: str | None = None
    values: dict | None = None


class TypicalBuildingRequest(BaseModel):
    """The body of a save of the project's typical building: its values and, when given, the library entry they came from (null:
    from none). Left out, the entry the building came from stays."""
    values: dict
    library_id: str | None = None


class TypicalBuildingReply(BaseModel):
    """The typical building and the state of its weights; the numbers come from the weights file and are None without one."""
    values: dict
    library_id: str | None              # the library entry the building came from
    library_name: str | None            # its name now, or the name kept when it is gone
    changed: bool                       # the values differ from the entry's; false when there is no entry
    # current: calculated for these values and weather file; out_of_date: for others; missing: never calculated
    state: StageState
    heating_kwh_m2: float | None = None     # the building's heating demand in a year, kWh per m² of floor
    cooling_kwh_m2: float | None = None     # its cooling demand
    counted_hours: int | None = None        # the hours with the sun up whose benefit weight is above 0.01


class TypicalBuildingWeightsReply(BaseModel):
    """The hourly weights of the typical building, 8,760 each from 1 January 0:00, to 3 decimals."""
    benefit: list[float]                # the share of an hour's sun that saves heating, 0 to 1
    harm: list[float]                   # the share that becomes cooling load, 0 to 1
    sun_up: list[int]                   # 1 for the hours with the sun above the horizon, 0 for the others


class ErrorDetailReply(BaseModel):
    """The body of a request the service refuses with a message."""
    detail: str


class StoredFileChangedReply(ErrorDetailReply):
    """The body of a turn or a restore refused because the stored file is no longer the version Inspect read (409)."""
    stored_file_changed: Literal[True] = True


class MissingInputsReply(ErrorDetailReply):
    """The body of a run request that lacks input files."""
    missing_inputs: list[str]   # max_volume, "test_surfaces:<criterion id>" (a criterion that is on protects nothing), "criteria" (none is on), weather; context and terrain are optional
