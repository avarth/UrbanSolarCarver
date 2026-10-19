"""Which stages of a project have output that matches its settings and inputs, and which stages a run has to execute.

project.json keeps one record per completed stage: the settings it ran with, the inputs revision and the
run_id of its manifest. A stage is ``current`` when its record still matches the project, ``out_of_date``
when it completed but its settings, its inputs or the stage it read changed since, and ``missing`` when it
never completed (or a run that was cut off removed its record). The engine compares settings only and does
not know whether a stage ever ran, so this module is where the service decides that.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..errors import ConfigError
from ..mode_registry import MODES
from ..pydantic_schemas import UserConfig, resolve_grid_step
from ..stage_settings import PIPELINE_STAGES, stage_folder, stages_needed_for, stages_to_rerun
from .api_models import StageRecord, StageState
from .projects import INPUTS_FOLDER, JOINED_FOLDER, MESH_ROLES, RUN_FOLDER, WEATHER_FILE_NAME, WEATHER_ROLE, ProjectStore

MANIFEST_FILE_NAME = "manifest.json"
# The stage whose manifest each of these stages names as its upstream (the engine's chain).
UPSTREAM_STAGE = {"thresholding": "preprocessing", "exporting": "thresholding", "massing": "thresholding"}
ANALYSIS_STAGES = ("preprocessing", "thresholding")     # the stages every result is built on
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


@dataclass(frozen=True)
class StageChoice:
    """The stages a run executes and the stages it asks the engine to produce."""
    stages: list[str]               # pipeline order; empty when everything asked for is current
    produce_for_engine: list[str]   # the chosen stages that were asked for


def _read_manifest(run_folder: Path, stage: str) -> dict | None:
    """The manifest of a stage as a dict; None when the stage has none or it cannot be read."""
    try:
        manifest = json.loads((stage_folder(run_folder, stage) / MANIFEST_FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def stage_status(store: ProjectStore, name: str) -> dict[str, StageState]:
    """The state of every pipeline stage of a project, in pipeline order.

    When the stored settings do not validate (a hand-edited config.yaml, or an engine update that validates a
    setting differently), no stage can be current, so every completed stage is out_of_date; the project still
    opens and the next save or run reports the field.
    """
    project_json = store.read_project_json(name)
    run_folder = store.open(name) / RUN_FOLDER
    try:
        current_config = store.load_project_config(name)
    except ConfigError:
        current_config = None
    status: dict[str, StageState] = {}
    for stage in PIPELINE_STAGES:
        record = project_json.stage_records.get(stage)
        manifest = _read_manifest(run_folder, stage)
        if record is None or manifest is None:
            status[stage] = "missing"
        elif current_config is None or record.inputs_revision != project_json.inputs_revision:
            status[stage] = "out_of_date"
        elif _settings_changed(store, name, stage, record, current_config):
            status[stage] = "out_of_date"
        elif stage == "preprocessing" and any(manifest.get(field) is None for field in MAX_VOLUME_HEIGHT_FIELDS):
            status[stage] = "out_of_date"
        elif stage == "preprocessing" and _sampled_at_another_spacing_before_it_was_recorded(record, manifest, current_config):
            status[stage] = "out_of_date"
        elif stage == "massing" and manifest.get(MASSING_EXPORT_MESH_FIELD) is None and current_config.final_mesh_format != "obj":
            status[stage] = "out_of_date"
        elif stage in UPSTREAM_STAGE and not _reads_current_upstream(
                status[UPSTREAM_STAGE[stage]], project_json.stage_records.get(UPSTREAM_STAGE[stage]), manifest):
            status[stage] = "out_of_date"
        else:
            status[stage] = "current"
    return status


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


def _reads_current_upstream(upstream_state: StageState, upstream_record: StageRecord | None, manifest: dict) -> bool:
    """Whether the stage's manifest was built from the run the upstream stage's record describes."""
    return (upstream_state == "current" and upstream_record is not None
            and upstream_record.manifest_run_id == manifest.get("upstream_run_id"))


def choose_stages(store: ProjectStore, name: str, produce: list[str]) -> StageChoice:
    """The stages to execute to bring *produce* up to date.

    When preprocessing or thresholding (as far as *produce* needs them) is not current, the run starts at the
    first of them, goes through thresholding and then runs every stage of *produce* that follows: those read
    the new thresholding, so they cannot stay. Otherwise it runs each stage of *produce* that is not current.
    Raises ValueError for a stage name the pipeline does not have.
    """
    needed = stages_needed_for(produce)
    status = stage_status(store, name)
    analysis_stages = [stage for stage in ANALYSIS_STAGES if stage in needed]
    first_stale_analysis = next((index for index, stage in enumerate(analysis_stages) if status[stage] != "current"), None)
    if first_stale_analysis is None:
        chosen = {stage for stage in needed if status[stage] != "current"}
    else:
        chosen = {*analysis_stages[first_stale_analysis:], *(stage for stage in needed if stage not in ANALYSIS_STAGES)}
    stages = [stage for stage in PIPELINE_STAGES if stage in chosen]
    return StageChoice(stages=stages, produce_for_engine=[stage for stage in stages if stage in produce])


def envelope_voxel_size(store: ProjectStore, name: str) -> float | None:
    """The voxel size of the grid the envelope mesh on disk was built from.

    It is the one of the settings exporting last completed with. Without that record (a run that redoes exporting removed
    it when it began, or a run was cut off) it is the one of the manifest chain: the preprocessing run that the thresholding
    run exporting read was built on. None when that chain is broken (a later run replaced one of them) or the recorded
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
    exporting, thresholding, preprocessing = (_read_manifest(run_folder, stage) for stage in ("exporting", "thresholding", "preprocessing"))
    if exporting is None or thresholding is None or preprocessing is None:
        return None
    if exporting.get("upstream_run_id") != thresholding.get("run_id") or thresholding.get("upstream_run_id") != preprocessing.get("run_id"):
        return None
    voxel_size = preprocessing.get("voxel_size")
    return float(voxel_size) if isinstance(voxel_size, (int, float)) else None


def forget_stages(store: ProjectStore, name: str, stages) -> None:
    """Remove the records of *stages*, so they count as missing until a run completes them again."""
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        for stage in stages:
            project_json.stage_records.pop(stage, None)
        store.write_project_json(name, project_json)


def record_stages(store: ProjectStore, name: str, stages, settings: dict, inputs_revision: int) -> None:
    """Record *stages* as completed with *settings* (the config.yaml content) and the manifest each wrote."""
    run_folder = store.open(name) / RUN_FOLDER
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        for stage in stages:
            project_json.stage_records[stage] = StageRecord(
                config=settings, inputs_revision=inputs_revision, manifest_run_id=_read_manifest(run_folder, stage)["run_id"])
        store.write_project_json(name, project_json)


def missing_inputs(store: ProjectStore, name: str, config: UserConfig) -> list[str]:
    """The input roles a run of this config still lacks: meshes without a joined file, and the weather file when the mode reads one."""
    project_folder = store.open(name)
    absent = [role for role in MESH_ROLES if not (project_folder / JOINED_FOLDER / f"{role}.ply").is_file()]
    if MODES[config.mode].needs_epw and not (project_folder / INPUTS_FOLDER / WEATHER_FILE_NAME).is_file():
        absent.append(WEATHER_ROLE)
    return absent
