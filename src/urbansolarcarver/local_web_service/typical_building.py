"""The typical building of a project: the values of its form, the types it can start from, and its hourly weights.

A Solar usefulness criterion that is energy-weighted (``CriterionEntry.energy_weighted``) counts each hour by what its sun
saves this building in heating over the year, instead of the cold hours rule. project.json keeps one building per project
(``TypicalBuildingEntry``); the engine's generator (simulated_weights.generate_simulated_weights) calculates its weights into
WEIGHTS_PATH, which config.yaml names as simulated_weights_path for every such criterion (criteria.engine_settings).

The values are the shoebox form of the engine's archetype (archetype_of turns them into it). The weights are calculated for a
key: a hash of the values and of the weather file. A calculation records its key in ``calculated_key``; the weights are out of
date when the values or the weather file give another key now, and each energy-weighted criterion's preprocessing record keeps
the key it ran with (stage_records.py). This module does not import torch or Ladybug: the generator imports Ladybug when it
reads the weather file.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ConfigError, ConfigFieldError
from ..simulated_weights import MASS_CLASSES, ZoneParams, _shading_factors, expand_shoebox, read_simulated_weights
from .api_models import ProjectJson, TypicalBuildingEntry, TypicalBuildingReply, TypicalBuildingWeightsReply
from .project_names import ProjectError

WEIGHTS_PATH = "inputs/typical_building/weights.json"     # relative to the project folder; the heatmap PNG is beside it
STAGE = "typical_building"          # the stage the run's progress events name while the run calculates the weights
SIDES = ("north", "east", "south", "west")
DAY_HOURS = range(8, 20)            # the hours with the gains by day, 8:00 to 20:00; the gains by night fill the others
COUNTED_WEIGHT = 0.01               # an hour whose benefit is above this counts (TypicalBuildingReply.counted_hours)
WEIGHT_DECIMALS = 3                 # of the weights the browser gets
MAX_WINDOW_SHARE = 0.9
NOT_CALCULATED_MESSAGE = "The typical building has not been calculated yet: press Calculate."
# The keys of the values, in the order of the form's groups (Shape, Windows, Walls and glass, Air, Use, Summer shading).
VALUE_KEYS = ("width", "length", "height", "orientation", "wwr", "g_value", "u_opaque", "u_window", "mass_class", "ach_vent",
              "ach_infiltration", "heat_recovery", "t_set_heating", "t_set_cooling", "gains_day_w_m2", "gains_night_w_m2",
              "shading_permanent", "shading_hot", "hot_months")


@dataclass(frozen=True)
class Preset:
    """A type the building can start from: its label in the app and its values."""
    label: str
    values: dict = field(default_factory=dict)


def _preset_values(width, length, height, wwr, u_opaque, u_window, mass_class, ach_vent, ach_infiltration, heat_recovery,
                   gains_day, gains_night) -> dict:
    """The values of a type: these, with the set points 20 and 26 °C, g 0.6, facing north and no shading."""
    return {"width": width, "length": length, "height": height, "orientation": 0.0,
            "wwr": {side: float(wwr.get(side, 0.0)) for side in SIDES}, "g_value": 0.6,
            "u_opaque": u_opaque, "u_window": u_window, "mass_class": mass_class,
            "ach_vent": ach_vent, "ach_infiltration": ach_infiltration, "heat_recovery": heat_recovery,
            "t_set_heating": 20.0, "t_set_cooling": 26.0, "gains_day_w_m2": gains_day, "gains_night_w_m2": gains_night,
            "shading_permanent": None, "shading_hot": None, "hot_months": [6, 7, 8]}


# The three cases the engine's model was checked on (design/simulated-weights.md), their floor area and volume made a box and
# their window areas window shares. The office keeps the office gains of the checks (250 W by day and 60 W at night on 35 m²);
# the homes get the engine's default 5 W/m².
PRESETS: dict[str, Preset] = {
    "office": Preset("Office, medium mass", _preset_values(
        5.0, 7.0, 3.0, {"south": 0.27, "east": 0.10, "west": 0.10}, 0.5, 1.8, "medium", 1.2, 0.3, 0.0, 7.1, 1.7)),
    "heavy_home": Preset("Older home, heavy masonry", _preset_values(
        5.0, 8.0, 2.75, {"south": 0.15, "east": 0.05, "west": 0.05, "north": 0.07}, 1.2, 2.8, "heavy", 0.8, 0.5, 0.0, 5.0, 5.0)),
    "light_home": Preset("Light, well-insulated home", _preset_values(
        5.0, 6.0, 3.0, {"south": 0.4, "west": 0.22}, 0.25, 1.0, "light", 1.5, 0.2, 0.6, 5.0, 5.0)),
}
DEFAULT_PRESET = "office"           # the type a project's building starts from until it is saved


def building_of(project_json: ProjectJson) -> TypicalBuildingEntry:
    """The project's building; the default type, not calculated, when project.json has none."""
    if project_json.typical_building is not None:
        return project_json.typical_building
    return TypicalBuildingEntry(values=copy.deepcopy(PRESETS[DEFAULT_PRESET].values), start_from=DEFAULT_PRESET)


def archetype_of(values: dict) -> dict:
    """The engine's shoebox archetype for the values of the form.

    The gains become a 24-value profile (day gains from 8:00 to 20:00) or one flat value when day and night are equal; a side
    without windows, a shading factor that is not set and the months of an unset summer shading are left out.
    """
    archetype = {key: values[key] for key in ("width", "length", "height", "orientation", "g_value", "u_opaque", "u_window",
                                              "mass_class", "ach_vent", "ach_infiltration", "heat_recovery", "t_set_heating",
                                              "t_set_cooling")}
    archetype["wwr"] = {side: share for side, share in values["wwr"].items() if share > 0}
    day, night = values["gains_day_w_m2"], values["gains_night_w_m2"]
    if day == night:
        archetype["internal_gains_w_m2"] = day
    else:
        archetype["internal_gains_profile_w_m2"] = [day if hour in DAY_HOURS else night for hour in range(24)]
    if values["shading_permanent"] is not None:
        archetype["shading_permanent"] = values["shading_permanent"]
    if values["shading_hot"] is not None:
        archetype["shading_hot"] = values["shading_hot"]
        archetype["hot_months"] = list(values["hot_months"])
    return archetype


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _checked_number(value, name: str, errors: list[ConfigFieldError], low: float | None = None, high: float | None = None,
                    above: float | None = None, optional: bool = False) -> float | None:
    """*value* as a float when it is a number in range; None otherwise, with an error for the field *name*. *low* and *high* are
    allowed, *above* is not; an *optional* value may be None."""
    if value is None and optional:
        return None
    if not _is_number(value):
        errors.append(ConfigFieldError(name, "Give a number."))
        return None
    if above is not None and value <= above:
        errors.append(ConfigFieldError(name, f"Give a number above {above:g}."))
        return None
    if (low is not None and value < low) or (high is not None and value > high):
        bounds = (f"from {low:g} to {high:g}" if low is not None and high is not None
                  else f"of at least {low:g}" if low is not None else f"of at most {high:g}")
        errors.append(ConfigFieldError(name, f"Give a number {bounds}."))
        return None
    return float(value)


def validate(values) -> dict:
    """The values checked and in their stored form (numbers as floats, every side in wwr, the months sorted once each).

    Raises ConfigError with an error per field (the field is the value's key, "wwr.<side>" for a window share): each value's
    type and range (window shares 0 to 0.9, factors 0 to 1, months 1 to 12), then the engine's own checks of the archetype
    (expand_shoebox, ZoneParams.from_archetype, _shading_factors).
    """
    if not isinstance(values, dict):
        raise ConfigError("The typical building's values must be a mapping.", [ConfigFieldError(None, "The values must be a mapping.")])
    errors = [ConfigFieldError(key, "Not a value of the typical building.") for key in sorted(set(values) - set(VALUE_KEYS))]
    errors += [ConfigFieldError(key, "This value is missing.") for key in VALUE_KEYS if key not in values]
    if errors:
        raise ConfigError("The typical building's values are not valid.", errors)
    checked = {
        "width": _checked_number(values["width"], "width", errors, above=0.0),
        "length": _checked_number(values["length"], "length", errors, above=0.0),
        "height": _checked_number(values["height"], "height", errors, above=0.0),
        "orientation": _checked_number(values["orientation"], "orientation", errors),
    }
    wwr = values["wwr"]
    if not isinstance(wwr, dict) or set(wwr) - set(SIDES):
        errors.append(ConfigFieldError("wwr", f"Give a window share for each of {', '.join(SIDES)}."))
        checked["wwr"] = None
    else:
        # a side left out has no window
        checked["wwr"] = {side: _checked_number(wwr.get(side, 0.0), f"wwr.{side}", errors, 0.0, MAX_WINDOW_SHARE) for side in SIDES}
    checked.update({
        "g_value": _checked_number(values["g_value"], "g_value", errors, 0.0, 1.0),
        "u_opaque": _checked_number(values["u_opaque"], "u_opaque", errors, above=0.0),
        "u_window": _checked_number(values["u_window"], "u_window", errors, above=0.0),
        "ach_vent": _checked_number(values["ach_vent"], "ach_vent", errors, low=0.0),
        "ach_infiltration": _checked_number(values["ach_infiltration"], "ach_infiltration", errors, low=0.0),
        "heat_recovery": _checked_number(values["heat_recovery"], "heat_recovery", errors, 0.0, 1.0),
        "t_set_heating": _checked_number(values["t_set_heating"], "t_set_heating", errors),
        "t_set_cooling": _checked_number(values["t_set_cooling"], "t_set_cooling", errors),
        "gains_day_w_m2": _checked_number(values["gains_day_w_m2"], "gains_day_w_m2", errors, low=0.0),
        "gains_night_w_m2": _checked_number(values["gains_night_w_m2"], "gains_night_w_m2", errors, low=0.0),
        "shading_permanent": _checked_number(values["shading_permanent"], "shading_permanent", errors, 0.0, 1.0, optional=True),
        "shading_hot": _checked_number(values["shading_hot"], "shading_hot", errors, 0.0, 1.0, optional=True),
    })
    mass_class = values["mass_class"]
    if not isinstance(mass_class, str) or mass_class not in MASS_CLASSES:
        errors.append(ConfigFieldError("mass_class", f"Choose one of {', '.join(MASS_CLASSES)}."))
    checked["mass_class"] = mass_class
    months = values["hot_months"]
    if not isinstance(months, list) or not all(isinstance(month, int) and not isinstance(month, bool) and 1 <= month <= 12 for month in months):
        errors.append(ConfigFieldError("hot_months", "Give the months as numbers from 1 to 12."))
        checked["hot_months"] = None
    else:
        checked["hot_months"] = sorted(set(months))
        if values["shading_hot"] is not None and not months:
            errors.append(ConfigFieldError("hot_months", "Choose the months of the summer shading."))
    if None not in (checked["t_set_heating"], checked["t_set_cooling"]) and checked["t_set_cooling"] <= checked["t_set_heating"]:
        errors.append(ConfigFieldError("t_set_cooling", "The cooling set point must be above the heating set point."))
    if errors:
        raise ConfigError("The typical building's values are not valid.", errors)
    _check_with_the_engine(checked)
    return checked


def _check_with_the_engine(values: dict) -> None:
    """The engine's checks of the archetype, each error at the value it concerns; ConfigError."""
    archetype = archetype_of(values)
    try:
        expanded = expand_shoebox({key: value for key, value in archetype.items()
                                   if key not in ("internal_gains_w_m2", "internal_gains_profile_w_m2", "shading_permanent",
                                                  "shading_hot", "hot_months")})
    except ValueError as error:
        message = "Give at least one side a window share." if "no windows" in str(error) else str(error)
        raise ConfigError(str(error), [ConfigFieldError("wwr", message)]) from error
    windows = expanded.pop("windows")
    try:
        ZoneParams.from_archetype(**expanded)
    except ValueError as error:
        if "H_tr,op" in str(error):
            field_error = ConfigFieldError("u_opaque", "The walls and roof lose too much heat for the thermal mass: lower their U value "
                                                       "or choose a heavier mass.")
        elif "air change" in str(error):
            field_error = ConfigFieldError("ach_vent", "Ventilation and infiltration together must be above 0.")
        else:
            field_error = ConfigFieldError("mass_class" if "mass_class" in str(error) else None, str(error))
        raise ConfigError(str(error), [field_error]) from error
    try:
        _shading_factors(windows, archetype.get("shading_permanent"), archetype.get("shading_hot"), archetype.get("hot_months"))
    except ValueError as error:
        field_name = next((key for key in ("hot_months", "shading_hot", "shading_permanent") if key in str(error)), None)
        raise ConfigError(str(error), [ConfigFieldError(field_name, str(error))]) from error


def checked_start_from(start_from: str | None) -> str | None:
    """*start_from* when it names a type or is None; ConfigError at the field start_from otherwise."""
    if start_from is not None and start_from not in PRESETS:
        raise ConfigError(f"'{start_from}' is not a type to start from.",
                          [ConfigFieldError("start_from", f"Choose one of {', '.join(PRESETS)}.")])
    return start_from


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def weights_key(values: dict, weather_path: Path | str | None) -> str:
    """The key of the weights these values and this weather file give: the sha256 of the values as sorted JSON and of the
    weather file's bytes (a project without a weather file has a key of its own, which no calculation gives)."""
    digest = hashlib.sha256(json.dumps(values, sort_keys=True).encode("utf-8"))
    digest.update(b"\0weather:")
    digest.update(_file_digest(Path(weather_path)).encode("ascii") if weather_path is not None else b"none")
    return digest.hexdigest()


def current_key(store, name: str, project_json: ProjectJson | None = None) -> str:
    """The key of the project's building and weather file now."""
    project_json = store.read_project_json(name) if project_json is None else project_json
    return weights_key(building_of(project_json).values, store.weather_file_path(name))


def weights_file(project_folder: Path) -> Path:
    return Path(project_folder) / WEIGHTS_PATH


def needs_calculation(store, name: str, key: str) -> bool:
    """Whether the weights file is missing or was calculated for another key than *key*."""
    building = building_of(store.read_project_json(name))
    return building.calculated_key != key or not weights_file(store.open(name)).is_file()


def reply(store, name: str) -> TypicalBuildingReply:
    """The building with the state of its weights and, when the weights file exists, the numbers it holds."""
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        building = building_of(project_json)
        path = weights_file(store.open(name))
        heating = cooling = counted = None
        if not path.is_file():
            state = "missing"
        else:
            state = "current" if building.calculated_key == current_key(store, name, project_json) else "out_of_date"
            try:
                benefit, _harm, meta = read_simulated_weights(path)
            except ValueError:
                state = "missing"
            else:
                heating, cooling = meta.get("heating_kwh_m2"), meta.get("cooling_kwh_m2")
                counted = int((benefit > COUNTED_WEIGHT).sum())
        return TypicalBuildingReply(values=building.values, start_from=building.start_from, state=state, heating_kwh_m2=heating,
                                    cooling_kwh_m2=cooling, counted_hours=counted)


def weights_reply(store, name: str) -> TypicalBuildingWeightsReply:
    """The hourly weights of the weights file, to WEIGHT_DECIMALS decimals; ProjectError 404 when there is none."""
    path = weights_file(store.open(name))
    try:
        benefit, harm, _meta = read_simulated_weights(path)
    except ValueError as error:
        raise ProjectError(NOT_CALCULATED_MESSAGE, status_code=404) from error
    return TypicalBuildingWeightsReply(benefit=[round(float(value), WEIGHT_DECIMALS) for value in benefit],
                                       harm=[round(float(value), WEIGHT_DECIMALS) for value in harm])


def save(store, name: str, values, start_from: str | None) -> TypicalBuildingReply:
    """Store the building's values (validate) and the type it started from; the key of its last calculation stays. ConfigError, and
    nothing changes, when a value is not valid."""
    checked = validate(values)
    start_from = checked_start_from(start_from)
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        calculated_key = building_of(project_json).calculated_key
        project_json.typical_building = TypicalBuildingEntry(values=checked, start_from=start_from, calculated_key=calculated_key)
        store.write_project_json(name, project_json)
    return reply(store, name)


def calculate(store, name: str, values: dict | None = None) -> str:
    """Calculate the weights of *values* (default: the stored building) with the project's weather file into WEIGHTS_PATH and record
    their key in project.json; the key.

    The generator writes into a new folder beside WEIGHTS_PATH, and the files replace the earlier ones together with the record of the
    key, under the project lock, so the file and its key always belong together. The lock is not held while the generator runs (about
    9 s). ProjectError: 404 without a weather file (sun_study.NO_WEATHER_FILE_MESSAGE), 422 when the generator fails.
    """
    from ..simulated_weights import generate_simulated_weights
    from .sun_study import NO_WEATHER_FILE_MESSAGE
    if values is None:
        values = building_of(store.read_project_json(name)).values
    weather_path = store.weather_file_path(name)
    if weather_path is None:
        raise ProjectError(NO_WEATHER_FILE_MESSAGE, status_code=404)
    key = weights_key(values, weather_path)
    target = weights_file(store.open(name))
    target.parent.mkdir(parents=True, exist_ok=True)
    work_folder = Path(tempfile.mkdtemp(dir=target.parent, prefix="calculating-"))
    try:
        try:
            written = Path(generate_simulated_weights(str(weather_path), archetype_of(values), work_folder / target.name))
        except Exception as error:      # the weather file cannot be read, or the generator refuses the archetype
            raise ProjectError(f"The typical building could not be calculated: {error}", status_code=422) from error
        with store.project_lock(name):
            project_json = store.read_project_json(name)
            building = building_of(project_json)
            os.replace(written, target)
            picture = written.with_suffix(".png")
            if picture.is_file():
                os.replace(picture, target.with_suffix(".png"))
            project_json.typical_building = building.model_copy(update={"calculated_key": key})
            store.write_project_json(name, project_json)
    finally:
        with contextlib.suppress(OSError):
            shutil.rmtree(work_folder)
    return key
