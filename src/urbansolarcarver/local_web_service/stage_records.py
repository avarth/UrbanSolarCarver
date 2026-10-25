"""Which stages of a project have output that matches its settings and inputs, and which stages a run has to execute.

project.json keeps one record per completed stage: the settings it ran with, the inputs revision and the run_id of its
manifest. Preprocessing and thresholding run once per criterion, so each criterion has its own records of them
(``criterion_records``), with the fingerprint of its joined test surfaces; exporting and massing are built once, from the
last criterion that is on, and their records (``stage_records``) hold that criterion's settings. A stage is ``current``
when its record still matches the project, ``out_of_date`` when it completed but its settings, its inputs or the stage it
read changed since, and ``missing`` when it never completed (or a run that was cut off removed its record). The engine
compares settings only and does not know whether a stage ever ran, so this module is where the service decides that.

What goes out of date: the maximum volume, context, terrain, weather file or a shared setting change every criterion's
settings or the inputs revision, so everything; a criterion's own settings or test surfaces (its fingerprint) date its
preprocessing, and through it the thresholding of every criterion after it; a change of order, a bypass or a deletion
gives a criterion another previous one than its thresholding was decided after, which dates it and every one after it.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from ..errors import ConfigError
from ..mode_registry import MODES
from ..pydantic_schemas import UserConfig, resolve_grid_step
from ..stage_settings import PIPELINE_STAGES, stage_folder, stages_needed_for, stages_to_rerun
from . import test_surfaces
from .api_models import ProjectJson, StageRecord, StageState, StageStatusReply
from .projects import INPUTS_FOLDER, JOINED_FOLDER, REQUIRED_MESH_ROLES, RUN_FOLDER, WEATHER_FILE_NAME, WEATHER_ROLE, ProjectStore

MANIFEST_FILE_NAME = "manifest.json"
# The folder of the criteria's stage folders in a run folder: run/criteria/<id>/<stage>, the layout of the engine's run_chain
# (api_core/chain.py, which this module does not import: it pulls in torch).
CRITERIA_FOLDER = "criteria"
ANALYSIS_STAGES = ("preprocessing", "thresholding")     # the stages every criterion runs, and every result is built on
LEAF_STAGES = ("exporting", "massing")                  # built once, from the last criterion's thresholding
# Preprocessing manifest fields that massing reads; a manifest without them is from before preprocessing recorded
# them, and massing of that run would start and end its floors up to a voxel outside the maximum volume.
MAX_VOLUME_HEIGHT_FIELDS = ("max_volume_lowest_z", "max_volume_highest_z")
# A massing manifest without this field is from before massing wrote its plates in the chosen format: its only mesh
# is plates.obj, so it is out of date for any other format.
MASSING_EXPORT_MESH_FIELD = "export_mesh_path"
# A preprocessing manifest without this field is from before preprocessing recorded its sample spacing, when an unset grid_step
# sampled every GRID_STEP_DEFAULT_BEFORE_IT_FOLLOWED_THE_VOXEL_SIZE meters; now it samples at half the voxel size.
SAMPLE_SPACING_FIELD = "grid_step"
GRID_STEP_DEFAULT_BEFORE_IT_FOLLOWED_THE_VOXEL_SIZE = 1.0
# A preprocessing manifest without this field is from before preprocessing recorded the unit of its scores, when the weighted
# modes summed patch weights without the area each sample point stands for: a score cutoff on those scores means another thing.
SCORE_UNIT_FIELD = "score_unit"


@dataclass(frozen=True)
class StageChoice:
    """The stages a run executes, the stages it asks the engine to produce, and where in the chain it starts."""
    stages: list[str]               # pipeline order; empty when everything asked for is current
    produce_for_engine: list[str]   # the chosen stages that were asked for
    start_from: str | None          # the first of stages (the engine's start_from); None when nothing runs
    trace_criteria: list[str]       # the criteria that are on whose preprocessing is not current, in chain order: traced again
    # Every criterion that is on -> the stages the run executes for it, as run_chain runs them (empty when it runs none).
    criterion_stages: dict[str, list[str]]


@dataclass(frozen=True)
class RunSettings:
    """What a run starts with, which the records of the stages it completes keep."""
    inputs_revision: int
    criteria: dict[str, dict]                       # criterion id -> its settings as one flat mapping (read_stored_config)
    test_surfaces_fingerprints: dict[str, str | None]   # criterion id -> fingerprint of its joined test surface file
    leaf_settings: dict                             # the settings of the last criterion that is on: exporting and massing run with them


@dataclass(frozen=True)
class _ProjectStatus:
    criteria: dict[str, dict[str, StageState]]      # as criterion_status
    stages: dict[str, StageState]                   # as stage_status


def _read_manifest_file(manifest_path: Path) -> dict | None:
    """A manifest as a dict; None when it is not there or cannot be read."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def _read_manifest(run_folder: Path, stage: str) -> dict | None:
    """The manifest of exporting or massing; None when the stage has none or it cannot be read."""
    return _read_manifest_file(stage_folder(run_folder, stage) / MANIFEST_FILE_NAME)


def _criterion_stage_folder(run_folder: Path, criterion_id: str, stage: str) -> Path:
    return run_folder / CRITERIA_FOLDER / criterion_id / stage


def _read_criterion_manifest(run_folder: Path, criterion_id: str, stage: str) -> dict | None:
    """The manifest of a criterion's preprocessing or thresholding; None when it has none or it cannot be read."""
    return _read_manifest_file(_criterion_stage_folder(run_folder, criterion_id, stage) / MANIFEST_FILE_NAME)


def _active_criterion_ids(project_json: ProjectJson) -> list[str]:
    """The ids of the criteria that are on, in chain order: the chain a run carves."""
    return [criterion.id for criterion in project_json.criteria if not criterion.bypassed]


def criterion_status(store: ProjectStore, name: str) -> dict[str, dict[str, StageState]]:
    """The state of the preprocessing and the thresholding of every criterion that is on, in chain order; a bypassed criterion is
    not listed, and with no criterion on the mapping is empty.

    A criterion's preprocessing is current when its record and manifest exist, the inputs revision and the fingerprint of its
    test surfaces are the recorded ones and its settings would not run it again. Its thresholding is current when its
    preprocessing is current and is the run the thresholding read, its settings would not run it again, and it was decided after
    the thresholding run of the previous criterion that is on (none for the first), which is current.
    """
    return _project_status(store, name).criteria


def stage_status(store: ProjectStore, name: str) -> dict[str, StageState]:
    """The state of every pipeline stage of a project, in pipeline order.

    Preprocessing and thresholding sum up the criteria that are on (criterion_status): missing when one is missing (or no
    criterion is on), else out_of_date when one is, else current. Exporting and massing read the thresholding of the last
    criterion that is on. When the stored settings of a criterion do not validate (a hand-edited config.yaml, or an engine update
    that validates a setting differently), none of its stages can be current, so every completed one is out_of_date; the
    project still opens and the next save or run reports the field.
    """
    return _project_status(store, name).stages


def stage_status_reply(store: ProjectStore, name: str) -> StageStatusReply:
    """stage_status and criterion_status in one reply."""
    status = _project_status(store, name)
    return StageStatusReply(stages=status.stages, criteria=status.criteria)


def _project_status(store: ProjectStore, name: str) -> _ProjectStatus:
    project_json = store.read_project_json(name)
    project_folder = store.open(name)
    run_folder = project_folder / RUN_FOLDER
    criteria: dict[str, dict[str, StageState]] = {}
    last_config = None
    previous_thresholding: tuple[StageState, StageRecord | None] | None = None   # of the previous criterion that is on
    for criterion_id in _active_criterion_ids(project_json):
        last_config = _criterion_config(store, name, criterion_id)
        records = project_json.criterion_records.get(criterion_id, {})
        preprocessing = _preprocessing_state(
            store, name, project_json, records.get("preprocessing"), _read_criterion_manifest(run_folder, criterion_id, "preprocessing"),
            last_config, test_surfaces.fingerprint(project_folder, criterion_id))
        thresholding = _thresholding_state(
            store, name, project_json, records.get("thresholding"), _read_criterion_manifest(run_folder, criterion_id, "thresholding"),
            last_config, (preprocessing, records.get("preprocessing")), previous_thresholding)
        criteria[criterion_id] = {"preprocessing": preprocessing, "thresholding": thresholding}
        previous_thresholding = (thresholding, records.get("thresholding"))
    stages: dict[str, StageState] = {stage: _sum_of([states[stage] for states in criteria.values()]) for stage in ANALYSIS_STAGES}
    for stage in LEAF_STAGES:
        stages[stage] = _leaf_state(store, name, project_json, stage, _read_manifest(run_folder, stage), last_config,
                                    previous_thresholding or ("missing", None))
    return _ProjectStatus(criteria=criteria, stages=stages)


def _criterion_config(store: ProjectStore, name: str, criterion_id: str) -> UserConfig | None:
    """The validated config of a criterion; None when its stored settings do not validate."""
    try:
        return store.load_project_config(name, criterion_id)
    except ConfigError:
        return None


def _sum_of(states: list[StageState]) -> StageState:
    """One state for a stage of several criteria: missing when one is missing or there is none, else out_of_date when one is."""
    if not states or "missing" in states:
        return "missing"
    return "out_of_date" if "out_of_date" in states else "current"


def _state_from_record(store: ProjectStore, name: str, project_json: ProjectJson, stage: str, record: StageRecord | None,
                       manifest: dict | None, current_config: UserConfig | None) -> StageState | None:
    """The checks every stage starts with: missing without its record or manifest; out_of_date when the current settings do not
    validate, the inputs revision changed or the settings would run the stage again. None when the stage passes them."""
    if record is None or manifest is None:
        return "missing"
    if current_config is None or record.inputs_revision != project_json.inputs_revision:
        return "out_of_date"
    if _settings_changed(store, name, stage, record, current_config):
        return "out_of_date"
    return None


def _preprocessing_state(store: ProjectStore, name: str, project_json: ProjectJson, record: StageRecord | None, manifest: dict | None,
                         current_config: UserConfig | None, fingerprint: str | None) -> StageState:
    """The state of a criterion's preprocessing; *fingerprint* is the one of its joined test surface file now."""
    state = _state_from_record(store, name, project_json, "preprocessing", record, manifest, current_config)
    if state is not None:
        return state
    if record.test_surfaces_fingerprint != fingerprint:
        return "out_of_date"
    if any(manifest.get(field) is None for field in MAX_VOLUME_HEIGHT_FIELDS):
        return "out_of_date"
    if _sampled_at_another_spacing_before_it_was_recorded(record, manifest, current_config):
        return "out_of_date"
    if _scores_in_another_unit_than_the_next_run_writes(manifest, current_config):
        return "out_of_date"
    return "current"


def _thresholding_state(store: ProjectStore, name: str, project_json: ProjectJson, record: StageRecord | None, manifest: dict | None,
                        current_config: UserConfig | None, preprocessing: tuple[StageState, StageRecord | None],
                        previous_thresholding: tuple[StageState, StageRecord | None] | None) -> StageState:
    """The state of a criterion's thresholding; *preprocessing* is the state and record of its preprocessing, *previous_thresholding*
    those of the previous criterion's thresholding (None for the first criterion)."""
    state = _state_from_record(store, name, project_json, "thresholding", record, manifest, current_config)
    if state is not None:
        return state
    if not _reads_current_run(*preprocessing, manifest.get("upstream_run_id")):
        return "out_of_date"
    if previous_thresholding is None:
        return "current" if manifest.get("after_run_id") is None else "out_of_date"
    return "current" if _reads_current_run(*previous_thresholding, manifest.get("after_run_id")) else "out_of_date"


def _leaf_state(store: ProjectStore, name: str, project_json: ProjectJson, stage: str, manifest: dict | None,
                current_config: UserConfig | None, last_thresholding: tuple[StageState, StageRecord | None]) -> StageState:
    """The state of exporting or massing; *current_config* and *last_thresholding* are of the last criterion that is on."""
    state = _state_from_record(store, name, project_json, stage, project_json.stage_records.get(stage), manifest, current_config)
    if state is not None:
        return state
    if stage == "massing" and manifest.get(MASSING_EXPORT_MESH_FIELD) is None and current_config.final_mesh_format != "obj":
        return "out_of_date"
    return "current" if _reads_current_run(*last_thresholding, manifest.get("upstream_run_id")) else "out_of_date"


def _settings_changed(store: ProjectStore, name: str, stage: str, record: StageRecord, current_config: UserConfig) -> bool:
    """Whether the stage would run again with the current settings; a record that no longer builds a valid config counts as changed."""
    try:
        recorded_config = store.config_from_settings(name, record.config)
    except ConfigError:     # e.g. an engine update since the run removed or newly validates a setting
        return True
    return stage in stages_to_rerun(recorded_config, current_config, [stage])


def _sampled_at_another_spacing_before_it_was_recorded(record: StageRecord, manifest: dict, current_config: UserConfig) -> bool:
    """Whether a preprocessing run whose manifest does not record its sample spacing used another spacing than the next run will.

    Such a run sampled at the grid_step of its config, or at the old default of 1 m without one; the settings comparison cannot
    tell, as it reads an unset grid_step as half the voxel size. A manifest that records its spacing is left to that comparison.
    """
    if manifest.get(SAMPLE_SPACING_FIELD) is not None:
        return False
    stored_spacing = record.config.get("grid_step")
    spacing_used = GRID_STEP_DEFAULT_BEFORE_IT_FOLLOWED_THE_VOXEL_SIZE if stored_spacing is None else float(stored_spacing)
    return spacing_used != resolve_grid_step(current_config.grid_step, current_config.voxel_size)


def _scores_in_another_unit_than_the_next_run_writes(manifest: dict, current_config: UserConfig) -> bool:
    """Whether the scores of a preprocessing run are in another unit than a run of the current mode writes.

    A manifest that does not record the unit is from before the weighted modes' scores were scaled by the area of the sample
    points; its time-based and angle rule scores are in the units of today (m²·h, rays). The mode is the current one: a run
    of another mode is already out of date for its settings.
    """
    mode = MODES[current_config.mode]
    recorded_unit = manifest.get(SCORE_UNIT_FIELD)
    if recorded_unit is None:
        return mode.score_kind == "weighted_sum"
    return recorded_unit != mode.score_unit


def _reads_current_run(state: StageState, record: StageRecord | None, run_id_read: str | None) -> bool:
    """Whether a manifest read (as its upstream, or as the thresholding it was decided after) the run that a current stage's record describes."""
    return state == "current" and record is not None and record.manifest_run_id == run_id_read


def choose_stages(store: ProjectStore, name: str, produce: list[str]) -> StageChoice:
    """The stages to execute to bring *produce* up to date, and the criteria they run for.

    When the preprocessing of a criterion that is on is not current (as far as *produce* needs it), the run starts at
    preprocessing and traces those criteria again (trace_criteria); run_chain then thresholds every criterion from the first
    traced one on. Else, when the thresholding of one is not current, it starts at thresholding and thresholds the whole chain
    again. Either way it runs every stage of *produce* that follows: those read the new thresholding, so they cannot stay.
    Otherwise it runs each stage of *produce* that is not current. Raises ValueError for a stage name the pipeline does not have.
    """
    needed = stages_needed_for(produce)
    status = _project_status(store, name)
    analysis_stages = [stage for stage in ANALYSIS_STAGES if stage in needed]
    leaves = [stage for stage in needed if stage in LEAF_STAGES]
    trace = [criterion_id for criterion_id, states in status.criteria.items() if states["preprocessing"] != "current"]
    if trace and "preprocessing" in analysis_stages:
        chosen = {*analysis_stages, *leaves}
    elif "thresholding" in analysis_stages and any(states["thresholding"] != "current" for states in status.criteria.values()):
        trace, chosen = [], {"thresholding", *leaves}
    else:
        trace, chosen = [], {stage for stage in leaves if status.stages[stage] != "current"}
    stages = [stage for stage in PIPELINE_STAGES if stage in chosen]
    return StageChoice(stages=stages, produce_for_engine=[stage for stage in stages if stage in produce],
                       start_from=stages[0] if stages else None, trace_criteria=trace,
                       criterion_stages=_criterion_stages(list(status.criteria), stages, trace))


def _criterion_stages(criterion_ids: list[str], stages: list[str], trace: list[str]) -> dict[str, list[str]]:
    """The analysis stages a run of *stages* executes for each criterion, as run_chain runs them: from preprocessing it traces the
    criteria of *trace* and thresholds every criterion from the first of them on; from thresholding it thresholds every criterion."""
    thresholds = "thresholding" in stages
    if "preprocessing" in stages:
        first_traced = criterion_ids.index(trace[0])
        return {criterion_id: [*(["preprocessing"] if criterion_id in trace else []),
                               *(["thresholding"] if thresholds and position >= first_traced else [])]
                for position, criterion_id in enumerate(criterion_ids)}
    return {criterion_id: ["thresholding"] if thresholds else [] for criterion_id in criterion_ids}


def envelope_voxel_size(store: ProjectStore, name: str) -> float | None:
    """The voxel size of the grid the envelope mesh on disk was built from.

    It is the one of the settings exporting last completed with. Without that record (a run that redoes exporting removed
    it when it began, or a run was cut off) it is the one of the manifest chain: the preprocessing run that the thresholding
    run exporting read was built on, found through the upstream manifest each names (in the chain layout, exporting names the
    last criterion's thresholding). None when that chain is broken (a later run replaced one of them) or the recorded
    settings no longer validate.
    """
    record = store.read_project_json(name).stage_records.get("exporting")
    if record is None:
        return _voxel_size_of_the_exporting_chain(store.open(name) / RUN_FOLDER)
    try:
        return store.config_from_settings(name, record.config).voxel_size
    except ConfigError:
        return None


def _voxel_size_of_the_exporting_chain(run_folder: Path) -> float | None:
    """The preprocessing manifest's voxel size when exporting read the thresholding run on disk, and it the preprocessing run."""
    exporting_folder = stage_folder(run_folder, "exporting")
    exporting = _read_manifest_file(exporting_folder / MANIFEST_FILE_NAME)
    thresholding = _upstream_of(exporting_folder, exporting)
    preprocessing = _upstream_of(*thresholding) if thresholding is not None else None
    if preprocessing is None:
        return None
    voxel_size = preprocessing[1].get("voxel_size")
    return float(voxel_size) if isinstance(voxel_size, (int, float)) else None


def _upstream_of(manifest_folder: Path, manifest: dict | None) -> tuple[Path, dict] | None:
    """The folder and the manifest that a manifest names as its upstream, when it is there and is the run that manifest read."""
    stored_path = manifest.get("upstream_manifest") if manifest is not None else None
    if not isinstance(stored_path, str):
        return None
    path = Path(stored_path)
    upstream_path = path if path.is_absolute() else Path(os.path.normpath(manifest_folder / path))
    upstream = _read_manifest_file(upstream_path)
    if upstream is None or upstream.get("run_id") != manifest.get("upstream_run_id"):
        return None
    return upstream_path.parent, upstream


def forget_stages(store: ProjectStore, name: str, stages, criterion_stages: dict[str, list[str]] | None = None) -> None:
    """Remove the records of *stages*, so they count as missing until a run completes them again.

    *criterion_stages* names the preprocessing and thresholding records to remove per criterion (StageChoice.criterion_stages);
    without it those of *stages* are removed for every criterion.
    """
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        for stage in stages:
            if stage not in ANALYSIS_STAGES:
                project_json.stage_records.pop(stage, None)
                continue
            for criterion_id, records in project_json.criterion_records.items():
                if criterion_stages is None or stage in criterion_stages.get(criterion_id, ()):
                    records.pop(stage, None)
        store.write_project_json(name, project_json)


def run_settings(store: ProjectStore, name: str) -> RunSettings:
    """The settings, inputs revision and test surface fingerprints a run starting now runs with, for record_stages."""
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        project_folder = store.open(name)
        active_ids = _active_criterion_ids(project_json)
        criteria = {criterion_id: store.read_stored_config(name, criterion_id) for criterion_id in active_ids}
        return RunSettings(
            inputs_revision=project_json.inputs_revision, criteria=criteria,
            test_surfaces_fingerprints={criterion_id: test_surfaces.fingerprint(project_folder, criterion_id) for criterion_id in active_ids},
            leaf_settings=criteria[active_ids[-1]] if active_ids else store.read_stored_config(name))


def record_stages(store: ProjectStore, name: str, choice: StageChoice, settings: RunSettings) -> None:
    """Record the stages of *choice* as completed with *settings* (taken when the run started) and the manifest each wrote:
    each criterion's preprocessing and thresholding that ran, with its settings and test surface fingerprint, and exporting and
    massing, with the settings of the last criterion."""
    run_folder = store.open(name) / RUN_FOLDER
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        for criterion_id, stages in choice.criterion_stages.items():
            for stage in stages:
                project_json.criterion_records.setdefault(criterion_id, {})[stage] = StageRecord(
                    config=settings.criteria[criterion_id], inputs_revision=settings.inputs_revision,
                    manifest_run_id=_read_criterion_manifest(run_folder, criterion_id, stage)["run_id"],
                    test_surfaces_fingerprint=settings.test_surfaces_fingerprints[criterion_id])
        for stage in choice.stages:
            if stage in LEAF_STAGES:
                project_json.stage_records[stage] = StageRecord(
                    config=settings.leaf_settings, inputs_revision=settings.inputs_revision,
                    manifest_run_id=_read_manifest(run_folder, stage)["run_id"])
        store.write_project_json(name, project_json)


def missing_inputs(store: ProjectStore, name: str, config: UserConfig) -> list[str]:
    """What a run of this config still lacks: the required meshes without a joined file (the role), a criterion that is on and
    protects nothing ("test_surfaces:<id>"), "criteria" when no criterion is on, and the weather file when the mode reads one.
    Context and terrain are optional."""
    project_folder = store.open(name)
    absent = [role for role in REQUIRED_MESH_ROLES if not (project_folder / JOINED_FOLDER / f"{role}.ply").is_file()]
    active = [criterion for criterion in store.criteria(name) if not criterion.bypassed]
    if not active:
        absent.append("criteria")
    absent += [f"{test_surfaces.ROLE}:{criterion.id}" for criterion in active
               if not criterion.test_surface_files or not test_surfaces.joined_path(project_folder, criterion.id).is_file()]
    if MODES[config.mode].needs_epw and not (project_folder / INPUTS_FOLDER / WEATHER_FILE_NAME).is_file():
        absent.append(WEATHER_ROLE)
    return absent
