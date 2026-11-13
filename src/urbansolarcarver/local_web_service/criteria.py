"""The criteria of a project: palette, default names, the split of mixed settings, and the generated config.yaml.

project.json keeps the criteria (``CriterionEntry``); config.yaml is generated from them and from the shared settings
as the engine's chain file (``criteria:`` form, see ``chain_config.py``), so the project folder is a valid input for
``usc run``. The service never reads criterion settings back from config.yaml, it writes the file again after every change.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..chain_config import CRITERION_KEYS
from ..mode_registry import MODES, canonical_mode_name
from .api_models import CriterionEntry, ProjectJson
from .project_names import ProjectError
from .typical_building import WEIGHTS_PATH

# Colours of the criteria in the 3D view, given in order to the criteria of a project and cycling after the eighth. None is grey,
# which the context is (the eighth was #888780 until 2026-11-13; a criterion keeps the colour it was given).
CRITERION_COLOURS = ("#7F77DD", "#D85A30", "#1D9E75", "#D4537E", "#BA7517", "#378ADD", "#639922", "#8B2F3C")
CONFIG_COMMENT = "# Written by the UrbanSolarCarver app from project.json; change settings in the app."
# The name and id of a criterion are the service's: the browser never sets them through settings.
NOT_FROM_THE_BROWSER = ("name", "id")
COLOUR_PATTERN = re.compile(r"#[0-9A-Fa-f]{6}")

# The paths the service sets in config.yaml, relative to the project folder; epw_path only when a criterion reads a weather file.
SERVICE_PATHS = {
    "max_volume_path": "inputs/joined/max_volume.ply",
    "epw_path": "inputs/weather.epw",
    "out_dir": "run",
}
# The paths of the optional mesh roles, set in config.yaml exactly when the role's joined file exists.
OPTIONAL_SERVICE_PATHS = {
    "context": ("context_path", "inputs/joined/context.ply"),
    "terrain": ("terrain_path", "inputs/joined/terrain.ply"),
}
# The volume the base heights keep (site_input.update_kept_volume), named by a digest of its content so that config.yaml names a
# new path at every change: thresholding then goes out of date, not the analysis. Set in config.yaml exactly when the file exists.
KEPT_VOLUME_PATH = "inputs/joined/kept_volume_{digest}.ply"
KEPT_VOLUME_GLOB = "kept_volume_*.ply"
JOINED_TEST_SURFACES_PATH = "inputs/joined/test_surfaces_{id}.ply"     # the joined test surfaces of one criterion
# The folder of the criteria's stage folders in a run folder: run/criteria/<id>/<stage>, the layout of the engine's run_chain
# (api_core/chain.py, which the service does not import: it pulls in torch).
CRITERIA_FOLDER = "criteria"
# The settings an energy-weighted criterion leaves out of config.yaml: its weights replace the balance temperature, and the engine
# warns when both are given.
BALANCE_POINT_KEYS = ("balance_temperature", "balance_offset")
# The names the app shows for the modes (app/src/mode_tiles.json, which a test compares with this table): a criterion that
# the user did not name is named after them.
MODE_LABELS = {
    "tilted_plane": "Angle rule",
    "time-based": "Sun hours",
    "irradiance": "Solar energy",
    "benefit": "Solar heating",
    "daylight": "Daylight",
    "radiative_cooling": "Night cooling",
}


def colour_of_criterion(position: int) -> str:
    """The palette colour for the criterion with the *position*-th id (1 for the first), cycling."""
    return CRITERION_COLOURS[(position - 1) % len(CRITERION_COLOURS)]


def active_criteria(criteria: list[CriterionEntry]) -> list[CriterionEntry]:
    """The criteria that are on, in chain order: the chain a run carves; a bypassed criterion is not one of them."""
    return [criterion for criterion in criteria if not criterion.bypassed]


def criterion_run_folder(run_folder: Path, criterion_id: str, stage: str | None = None) -> Path:
    """The folder of a criterion's results in a run folder, run/criteria/<id>, or of one of its stages, run/criteria/<id>/<stage>."""
    folder = Path(run_folder) / CRITERIA_FOLDER / criterion_id
    return folder if stage is None else folder / stage


def joined_test_surfaces_path(criterion_id: str) -> str:
    """The joined test surface file of a criterion, relative to the project folder."""
    return JOINED_TEST_SURFACES_PATH.format(id=criterion_id)


def reads_weather_file(mode) -> bool:
    """Whether a criterion of this mode needs the weather file (a mode the engine does not know counts as one that does,
    so its error is reported by the engine's own validation)."""
    mode_settings = MODES.get(canonical_mode_name(mode))
    return mode_settings is None or mode_settings.needs_epw


def uses_typical_building(entry: CriterionEntry) -> bool:
    """Whether a criterion counts its hours by the typical building: energy-weighted and of the mode benefit (Solar heating)."""
    return entry.energy_weighted and canonical_mode_name(entry.settings.get("mode")) == "benefit"


# Settings a criterion stored before they became shared by the chain (rays_per_patch, 2026-11-09). A project that has one in a
# criterion gives the chain the value of its first criterion that is on (the first when none is), the one Simulate read; the criteria's
# copies are left out of what is read and written, and the next save of a criterion drops them.
LIFTED_TO_SHARED = ("rays_per_patch",)


def criterion_own(settings: Mapping[str, Any]) -> dict:
    """A criterion's stored settings without those now shared by the chain (LIFTED_TO_SHARED)."""
    return {key: value for key, value in settings.items() if key not in LIFTED_TO_SHARED}


def with_lifted_settings(shared: Mapping[str, Any], criteria: list[CriterionEntry]) -> dict:
    """*shared* with each LIFTED_TO_SHARED setting it lacks taken from the first criterion that is on (the first when none is), when
    that criterion stored one."""
    lifted = dict(shared)
    source = (active_criteria(criteria) or criteria)[:1]
    for key in LIFTED_TO_SHARED:
        if key not in lifted and source and key in source[0].settings:
            lifted[key] = source[0].settings[key]
    return lifted


def lifted_from_config(stored_config: Mapping[str, Any]) -> dict:
    """The top of a config.yaml with each LIFTED_TO_SHARED setting it lacks taken from its first criterion entry (the first that is on,
    as an earlier version wrote them), so the value a project ran with is kept whatever happens to the criteria before the next write."""
    top = {key: value for key, value in stored_config.items() if key != "criteria"}
    entries = stored_config.get("criteria")
    first = entries[0] if isinstance(entries, list) and entries and isinstance(entries[0], Mapping) else {}
    for key in LIFTED_TO_SHARED:
        if key not in top and key in first:
            top[key] = first[key]
    return top


def engine_settings(entry: CriterionEntry) -> dict:
    """A criterion's settings as config.yaml gives them to the engine: for one that uses the typical building, the weights file as
    simulated_weights_path and no balance temperature or offset (its stored settings keep them, so switching back restores them)."""
    if not uses_typical_building(entry):
        return criterion_own(entry.settings)
    settings = {key: value for key, value in criterion_own(entry.settings).items() if key not in BALANCE_POINT_KEYS}
    settings["simulated_weights_path"] = WEIGHTS_PATH
    return settings


def mode_label(mode) -> str:
    """The name the app shows for a mode (MODE_LABELS); a mode the engine does not know is named as it is."""
    mode_name = canonical_mode_name(mode)
    return MODE_LABELS.get(mode_name, str(mode_name))


def default_criterion_name(mode, test_surface_files) -> str:
    """The name a criterion has until the user names it: the mode's label (mode_label), or "<label> on <first file name without
    extension>"."""
    mode_name = mode_label(mode)
    if not test_surface_files:
        return mode_name
    return f"{mode_name} on {Path(test_surface_files[0]).stem}"


def checked_criterion_name(name: str) -> str:
    """The name without surrounding spaces; ProjectError(422) when nothing is left."""
    if not name.strip():
        raise ProjectError("A criterion needs a name.", status_code=422)
    return name.strip()


def checked_colour(colour: str) -> str:
    """The colour when it is "#RRGGBB"; ProjectError(422) otherwise."""
    if COLOUR_PATTERN.fullmatch(colour) is None:
        raise ProjectError(f"'{colour}' is not a colour: use #RRGGBB.", status_code=422)
    return colour


def find_criterion(project_json: ProjectJson, criterion_id: str | None) -> CriterionEntry:
    """The criterion with this id, the first one for None; ProjectError(404) when there is none."""
    if criterion_id is None and project_json.criteria:
        return project_json.criteria[0]
    for criterion in project_json.criteria:
        if criterion.id == criterion_id:
            return criterion
    raise ProjectError(f"There is no criterion '{criterion_id}'.", status_code=404)


def append_criterion(project_json: ProjectJson, settings: dict, criterion_name: str | None = None) -> CriterionEntry:
    """Add a criterion with these settings at the end of the chain of *project_json*, with the next id and the next palette colour.

    It is named after its mode (and its name follows the mode) unless *criterion_name* is given.
    """
    number = project_json.next_criterion_id
    entry = CriterionEntry(
        id=str(number), name=default_criterion_name(settings.get("mode"), []) if criterion_name is None else checked_criterion_name(criterion_name),
        named_by_user=criterion_name is not None, colour=colour_of_criterion(number), settings=settings)
    project_json.criteria.append(entry)
    project_json.next_criterion_id = number + 1
    return entry


def set_criterion_settings(entry: CriterionEntry, settings: dict) -> None:
    """Replace a criterion's settings; a name the user did not give follows the mode when the mode changes."""
    old_mode = entry.settings.get("mode")
    entry.settings = settings
    if not entry.named_by_user and canonical_mode_name(settings.get("mode")) != canonical_mode_name(old_mode):
        entry.name = default_criterion_name(settings.get("mode"), entry.test_surface_files)


def flat_settings(shared_and_paths: dict, entry: CriterionEntry | None, for_engine: bool = True) -> dict:
    """The top of a chain config.yaml and one criterion as the flat mapping of a single-criterion config.

    The weather file is in it exactly when the criterion's mode reads one, as the engine's chain loader does. The criterion's settings
    are those config.yaml gives the engine (engine_settings), or with *for_engine* false those it stores (the browser's).
    """
    flat = dict(shared_and_paths)
    if entry is not None:
        flat.update(engine_settings(entry) if for_engine else criterion_own(entry.settings))
        flat["test_surface_path"] = joined_test_surfaces_path(entry.id)
        if reads_weather_file(entry.settings.get("mode")):
            flat.setdefault("epw_path", SERVICE_PATHS["epw_path"])
        else:
            flat.pop("epw_path", None)
        # A shared mode setting the criterion's mode does not read is left out, as the engine's chain loader does (no warning about it)
        spec = MODES.get(canonical_mode_name(entry.settings.get("mode")))
        if spec is not None:
            for key in LIFTED_TO_SHARED:
                if key not in spec.extra_params:
                    flat.pop(key, None)
    return flat


def split_settings(values: Mapping[str, Any]) -> tuple[dict, dict]:
    """The settings split into (shared, criterion) by the engine's CRITERION_KEYS. A name or id is dropped."""
    shared, criterion = {}, {}
    for key, value in values.items():
        if key in NOT_FROM_THE_BROWSER:
            continue
        (criterion if key in CRITERION_KEYS else shared)[key] = value
    return shared, criterion


def kept_volume_service_path(project_folder: Path) -> dict:
    """{"kept_volume_path": <relative path>} when the project has a kept volume file, else {}."""
    found = sorted((project_folder / "inputs" / "joined").glob(KEPT_VOLUME_GLOB))
    return {"kept_volume_path": found[0].relative_to(project_folder).as_posix()} if found else {}


def chain_config_document(shared: dict, criteria: list[CriterionEntry], project_folder: Path) -> dict:
    """The config.yaml mapping: the service paths and *shared* settings at the top, then one entry per criterion that is on.

    *shared* holds the shared settings (and the device); the paths are the service's, so any path in it is replaced. The
    weather file is named at the top when a criterion that is on reads one, and an optional mesh path when its joined file
    exists in *project_folder*. A criterion entry is its id, name and settings (engine_settings), and the joined file of its test
    surfaces.
    """
    active = active_criteria(criteria)
    shared = with_lifted_settings(shared, criteria)
    paths = {key: path for key, path in SERVICE_PATHS.items()
             if key != "epw_path" or any(reads_weather_file(criterion.settings.get("mode")) for criterion in active)}
    paths.update({key: path for key, path in OPTIONAL_SERVICE_PATHS.values() if (project_folder / path).is_file()})
    paths.update(kept_volume_service_path(project_folder))
    path_keys = {*SERVICE_PATHS, *(key for key, _path in OPTIONAL_SERVICE_PATHS.values()), "kept_volume_path"}
    document = {**paths, **{key: value for key, value in shared.items() if key not in path_keys}}
    document["criteria"] = [
        {"id": criterion.id, "name": criterion.name, **engine_settings(criterion),
         "test_surface_path": joined_test_surfaces_path(criterion.id)} for criterion in active]
    return document


def chain_config_text(document: dict) -> str:
    """The content of config.yaml for *document*: the comment line that says the app writes it, then the YAML."""
    return f"{CONFIG_COMMENT}\n{yaml.safe_dump(document, sort_keys=False)}"
