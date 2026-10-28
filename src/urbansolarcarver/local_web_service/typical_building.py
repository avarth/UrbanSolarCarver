"""The typical building of a project: the values of its form, the library it is chosen from, and its hourly weights.

A Solar usefulness criterion that is energy-weighted (``CriterionEntry.energy_weighted``) counts each hour by what its sun
saves this building in heating over the year, instead of the cold hours rule. project.json keeps one building per project
(``TypicalBuildingEntry``): a copy of the values and the library entry they came from. The engine's generator
(simulated_weights.generate_simulated_weights) calculates its weights into WEIGHTS_PATH, which config.yaml names as
simulated_weights_path for every such criterion (criteria.engine_settings).

The values describe one room in the app's words (a schedule, set points, U values, window shares, ...); archetype_of turns them
into the engine's shoebox archetype. The default room ("average") is a square plan of side 4 x depth turned 45° with the same
window share on its four walls (NE, SE, SW, NW), the roof and the floor adiabatic; "box" is the explicit box of width, length and
orientation (the ASHRAE 140 test boxes). An average room equals the box of width and length 4 x depth, orientation 45, whose
north, east, south and west shares are the ne, se, sw and nw ones.

The library is apart from projects: the built-in examples (EXAMPLES, read-only: the KENAK reference building of ΤΟΤΕΕ
20701-1/2017 for an apartment and an office in each of the climate zones Α to Δ, and ASHRAE 140 cases 600 and 900) and one YAML
file per own entry in library_folder(), beside the user preferences file, so the entries serve every projects folder.

The weights are calculated for a key: a hash of the values and of the weather file. A calculation records its key in
``calculated_key``; the weights are out of date when the values or the weather file give another key now, and each
energy-weighted criterion's preprocessing record keeps the key it ran with (stage_records.py). This module does not import torch
or Ladybug: the generator imports Ladybug when it reads the weather file.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import yaml

from ..errors import ConfigError, ConfigFieldError
from ..simulated_weights import HOURS, MASS_CLASSES, ZoneParams, _shading_factors, expand_shoebox, read_simulated_weights
from . import user_preferences
from .api_models import ProjectJson, TypicalBuildingEntry, TypicalBuildingLibraryEntry, TypicalBuildingReply, TypicalBuildingWeightsReply
from .project_names import ProjectError

NO_WEATHER_FILE_MESSAGE = "The project has no weather file: add one in Design (Inputs) to calculate the typical building."
WEIGHTS_PATH = "inputs/typical_building/weights.json"     # relative to the project folder; the heatmap PNG is beside it
STAGE = "typical_building"          # the stage the run's progress events name while the run calculates the weights
COUNTED_WEIGHT = 0.01               # an hour with the sun up whose benefit is above this counts (TypicalBuildingReply.counted_hours)
WEIGHT_DECIMALS = 3                 # of the weights the browser gets
MAX_WINDOW_SHARE = 0.9
MAX_NAME_LENGTH = 80
NOT_CALCULATED_MESSAGE = "The typical building has not been calculated yet: press Calculate."

# The typical cases of use (ΤΟΤΕΕ 20701-1/2017 table 2.1 gives the hours a day and the days a week, not which hours): the hours of
# the day in use (start, end), and whether only Monday to Friday. Internal gains and fresh air apply in these hours only.
SCHEDULES = {
    "apartment": (6, 24, False),    # 6:00 to 24:00 every day, 18 h
    "office": (8, 18, True),        # 8:00 to 18:00 Monday to Friday, 10 h
    "always": (0, 24, False),       # every hour (the ASHRAE 140 boxes)
}
MASS_KINDS = ("iso", "totee")
# ΤΟΤΕΕ 20701-1/2017 table 3.14: thermal capacity per m² of floor of typical constructions, kJ/(m²K), and their description.
# Categories 4 to 6 hold when the insulation is missing or on the outside or in the core of the brickwork; with insulation on the
# inside the zone falls in category 3.
TOTEE_CATEGORIES = {
    1: (80.0, "Light timber frame, infill of plasterboard or timber, insulation on the inside of walls, ceiling and floor"),
    2: (110.0, "Light steel frame, infill of curtain walls or light insulated panels"),
    3: (165.0, "Concrete frame, infill of lightweight concrete blocks or plasterboard, suspended ceilings"),
    4: (230.0, "Load-bearing stone or solid brick walls, timber floors"),
    5: (280.0, "Concrete frame, infill of hollow clay bricks"),
    6: (300.0, "Load-bearing stone or solid brick walls, concrete floors"),
}
ROOMS = ("average", "box")
ROOM_KEYS = {"average": ("depth",), "box": ("width", "length", "orientation")}     # the keys of each room besides the shared ones
WWR_SIDES = {"average": ("ne", "se", "sw", "nw"), "box": ("north", "east", "south", "west")}
AVERAGE_ROOM_SIDES = {"ne": "north", "se": "east", "sw": "south", "nw": "west"}    # the box side each side of the turned room is
AVERAGE_ROOM_TURN = 45.0
# The keys every building has, in the order of the sheet's groups (Use, Fabric, Summer shading, then Room, Roof and floor, Air).
VALUE_KEYS = ("schedule", "t_set_heating", "t_set_cooling", "gains_w_m2", "fresh_air_m3h_m2", "heat_recovery",
              "u_wall", "u_window", "g_value", "mass_kind", "mass_class", "totee_category",
              "shading_factor", "shading_start", "shading_end",
              "room", "height", "wwr",
              "roof_exposed", "u_roof", "floor_exposed", "u_floor",
              "infiltration_m3h_m2_window")
DATE_PATTERN = re.compile(r"^(\d{2})-(\d{2})$")
DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


# ---- The values and the engine's archetype ----

def first_weekday(epw_path: Path | str | None) -> int:
    """The weekday of 1 January in the weather file, 0 for Monday to 6 for Sunday: the start day of its DATA PERIODS line; Monday
    when there is no file or the line gives none."""
    if epw_path is None:
        return 0
    with contextlib.suppress(OSError):
        with open(epw_path, encoding="latin-1") as file:
            for _line_number, line in zip(range(20), file):
                if line.upper().startswith("DATA PERIODS"):
                    fields = [part.strip().lower() for part in line.split(",")]
                    if len(fields) > 4 and fields[4] in DAY_NAMES:
                        return DAY_NAMES.index(fields[4])
                    break
    return 0


def hours_in_use(schedule: str, weekday_of_first_day: int = 0) -> np.ndarray:
    """(8760,) bool: the hours of the year in use by the schedule (SCHEDULES), hour 0 being 1 January 0:00."""
    start, end, weekdays_only = SCHEDULES[schedule]
    hour = np.arange(HOURS)
    in_use = (hour % 24 >= start) & (hour % 24 < end)
    if weekdays_only:
        in_use &= (hour // 24 + weekday_of_first_day) % 7 < 5
    return in_use


def day_of_year(month_day: str) -> int:
    """The day of the year, 1 to 365, of a valid "MM-DD" (a year without 29 February)."""
    month, day = (int(part) for part in month_day.split("-"))
    return date(2001, month, day).timetuple().tm_yday


def room_box(values: dict) -> tuple[float, float, float, dict]:
    """The room as the engine's box: (width, length, orientation, window share by north/east/south/west)."""
    if values["room"] == "average":
        side = 4.0 * values["depth"]
        return side, side, AVERAGE_ROOM_TURN, {AVERAGE_ROOM_SIDES[side_name]: share for side_name, share in values["wwr"].items()}
    return values["width"], values["length"], values["orientation"], dict(values["wwr"])


def archetype_of(values: dict, epw_path: Path | str | None = None) -> dict:
    """The engine's shoebox archetype for the values of the form; the weather file gives the weekday of 1 January (Monday without it).

    Fresh air (m³/h per m² of floor) over the storey height gives the ventilation in air changes per hour, and infiltration (m³/h per
    m² of window) times the window area over the volume the infiltration's; the gains and the fresh air apply in the hours of the
    schedule (8,760 values each), or as one value when the schedule is every hour. A side without windows is left out; the summer
    shading is the hot shading of the engine over the period of its dates.
    """
    width, length, orientation, wwr = room_box(values)
    height = values["height"]
    volume = width * length * height
    window_area = sum(share * (width if side in ("north", "south") else length) * height for side, share in wwr.items())
    archetype = {"width": width, "length": length, "height": height, "orientation": orientation,
                 "wwr": {side: share for side, share in wwr.items() if share > 0},
                 "g_value": values["g_value"], "u_wall": values["u_wall"], "u_window": values["u_window"],
                 "roof_exposed": values["roof_exposed"], "u_roof": values["u_roof"],
                 "floor_exposed": values["floor_exposed"], "u_floor": values["u_floor"],
                 "ach_infiltration": values["infiltration_m3h_m2_window"] * window_area / volume,
                 "heat_recovery": values["heat_recovery"],
                 "t_set_heating": values["t_set_heating"], "t_set_cooling": values["t_set_cooling"]}
    ach_vent = values["fresh_air_m3h_m2"] / height
    in_use = hours_in_use(values["schedule"], first_weekday(epw_path))
    if in_use.all():
        archetype["ach_vent"] = ach_vent
        archetype["internal_gains_w_m2"] = values["gains_w_m2"]
    else:
        archetype["ach_vent"] = [ach_vent if hour_in_use else 0.0 for hour_in_use in in_use.tolist()]
        archetype["internal_gains_w_m2"] = [values["gains_w_m2"] if hour_in_use else 0.0 for hour_in_use in in_use.tolist()]
    if values["mass_kind"] == "iso":
        archetype["mass_class"] = values["mass_class"]
    else:
        archetype["mass_capacity_kj_m2k"] = TOTEE_CATEGORIES[values["totee_category"]][0]
    if values["shading_factor"] is not None:
        archetype["shading_hot"] = values["shading_factor"]
        archetype["shading_hot_period"] = [day_of_year(values["shading_start"]), day_of_year(values["shading_end"])]
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


def _checked_choice(value, name: str, choices, errors: list[ConfigFieldError]):
    if isinstance(value, bool) or value not in choices:
        errors.append(ConfigFieldError(name, f"Choose one of {', '.join(str(choice) for choice in choices)}."))
        return None
    return value


def _checked_bool(value, name: str, errors: list[ConfigFieldError]) -> bool | None:
    if not isinstance(value, bool):
        errors.append(ConfigFieldError(name, "Give true or false."))
        return None
    return value


def _checked_date(value, name: str, errors: list[ConfigFieldError]) -> str | None:
    """*value* when it is a day of a year without 29 February as "MM-DD"; None otherwise, with an error for the field *name*."""
    match = DATE_PATTERN.match(value) if isinstance(value, str) else None
    if match is not None:
        with contextlib.suppress(ValueError):
            date(2001, int(match[1]), int(match[2]))
            return value
    errors.append(ConfigFieldError(name, "Give a day as MM-DD, for example 05-15 for 15 May (not 02-29)."))
    return None


def validate(values) -> dict:
    """The values checked and in their stored form (numbers as floats, every side of the room in wwr, the ΤΟΤΕΕ category an int).

    Every building has the keys of VALUE_KEYS and those of its room (ROOM_KEYS). Raises ConfigError with an error per field (the
    field is the value's key, "wwr.<side>" for a window share): each value's type and range (window shares 0 to 0.9, factors 0 to
    1, dates "MM-DD", the choices of schedule, mass kind, ISO class, ΤΟΤΕΕ category and room), then the engine's own checks of the
    archetype (expand_shoebox, ZoneParams.from_archetype).
    """
    if not isinstance(values, dict):
        raise ConfigError("The typical building's values must be a mapping.", [ConfigFieldError(None, "The values must be a mapping.")])
    room = values.get("room")
    all_room_keys = {key for keys in ROOM_KEYS.values() for key in keys}
    known_room = isinstance(room, str) and room in ROOMS
    # the keys of the room; with a room that is not known (an error at room below) the keys of either room are not refused
    room_keys = ROOM_KEYS[room] if known_room else ()
    allowed = set(VALUE_KEYS) | (set(room_keys) if known_room else all_room_keys)
    errors = [ConfigFieldError(key, f"Not a value of the {room} room." if key in all_room_keys
                               else "Not a value of the typical building.")
              for key in sorted(set(values) - allowed)]
    errors += [ConfigFieldError(key, "This value is missing.") for key in VALUE_KEYS + room_keys if key not in values]
    if errors:
        raise ConfigError("The typical building's values are not valid.", errors)
    checked = {
        "schedule": _checked_choice(values["schedule"], "schedule", tuple(SCHEDULES), errors),
        "t_set_heating": _checked_number(values["t_set_heating"], "t_set_heating", errors),
        "t_set_cooling": _checked_number(values["t_set_cooling"], "t_set_cooling", errors),
        "gains_w_m2": _checked_number(values["gains_w_m2"], "gains_w_m2", errors, low=0.0),
        "fresh_air_m3h_m2": _checked_number(values["fresh_air_m3h_m2"], "fresh_air_m3h_m2", errors, low=0.0),
        "heat_recovery": _checked_number(values["heat_recovery"], "heat_recovery", errors, 0.0, 1.0),
        "u_wall": _checked_number(values["u_wall"], "u_wall", errors, above=0.0),
        "u_window": _checked_number(values["u_window"], "u_window", errors, above=0.0),
        "g_value": _checked_number(values["g_value"], "g_value", errors, 0.0, 1.0),
        "mass_kind": _checked_choice(values["mass_kind"], "mass_kind", MASS_KINDS, errors),
        "mass_class": _checked_choice(values["mass_class"], "mass_class", tuple(MASS_CLASSES), errors),
        "totee_category": _checked_choice(values["totee_category"], "totee_category", tuple(TOTEE_CATEGORIES), errors),
        "shading_factor": _checked_number(values["shading_factor"], "shading_factor", errors, 0.0, 1.0, optional=True),
        "shading_start": _checked_date(values["shading_start"], "shading_start", errors),
        "shading_end": _checked_date(values["shading_end"], "shading_end", errors),
        "room": _checked_choice(room, "room", ROOMS, errors),
        "height": _checked_number(values["height"], "height", errors, above=0.0),
    }
    if checked["totee_category"] is not None:
        checked["totee_category"] = int(checked["totee_category"])
    for key in room_keys:
        checked[key] = _checked_number(values[key], key, errors, **({} if key == "orientation" else {"above": 0.0}))
    sides = WWR_SIDES.get(checked["room"], ())
    wwr = values["wwr"]
    if checked["room"] is None:
        checked["wwr"] = None
    elif not isinstance(wwr, dict) or set(wwr) - set(sides):
        errors.append(ConfigFieldError("wwr", f"Give a window share for each of {', '.join(sides)}."))
        checked["wwr"] = None
    else:
        # a side left out has no window
        checked["wwr"] = {side: _checked_number(wwr.get(side, 0.0), f"wwr.{side}", errors, 0.0, MAX_WINDOW_SHARE) for side in sides}
    checked.update({
        "roof_exposed": _checked_bool(values["roof_exposed"], "roof_exposed", errors),
        "u_roof": _checked_number(values["u_roof"], "u_roof", errors, above=0.0),
        "floor_exposed": _checked_bool(values["floor_exposed"], "floor_exposed", errors),
        "u_floor": _checked_number(values["u_floor"], "u_floor", errors, above=0.0),
        "infiltration_m3h_m2_window": _checked_number(values["infiltration_m3h_m2_window"], "infiltration_m3h_m2_window", errors,
                                                      low=0.0),
    })
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
                                   if key not in ("internal_gains_w_m2", "shading_hot", "shading_hot_period")})
    except ValueError as error:
        message = "Give at least one side a window share." if "no windows" in str(error) else str(error)
        raise ConfigError(str(error), [ConfigFieldError("wwr", message)]) from error
    windows = expanded.pop("windows")
    try:
        ZoneParams.from_archetype(**expanded)
    except ValueError as error:
        if "H_tr,op" in str(error):
            field_error = ConfigFieldError("u_wall", "The walls, and the roof and floor when exposed, lose too much heat for the "
                                                     "thermal mass: lower their U values or choose a heavier mass.")
        elif "air change" in str(error):
            field_error = ConfigFieldError("infiltration_m3h_m2_window", "Some hours have no air change (no fresh air and no "
                                                                         "infiltration): give the infiltration a value above 0.")
        else:
            field_error = ConfigFieldError(None, str(error))
        raise ConfigError(str(error), [field_error]) from error
    try:
        _shading_factors(windows, None, archetype.get("shading_hot"), None, archetype.get("shading_hot_period"))
    except ValueError as error:
        raise ConfigError(str(error), [ConfigFieldError("shading_factor", str(error))]) from error


# ---- The library ----

@dataclass(frozen=True)
class LibraryEntry:
    """A building of the library: an example (read-only, built in) or one of the user's own (a YAML file in library_folder())."""
    id: str
    name: str
    group: str                          # "apartment", "office", "test" (the ASHRAE boxes) or "own"
    values: dict = field(default_factory=dict)
    source: str | None = None           # where an example's values come from; None for an own entry

    @property
    def read_only(self) -> bool:
        return self.group != "own"

    def reply(self) -> TypicalBuildingLibraryEntry:
        return TypicalBuildingLibraryEntry(id=self.id, name=self.name, group=self.group, read_only=self.read_only, source=self.source,
                                           values=copy.deepcopy(self.values))


TOTEE_SOURCE = "ΤΟΤΕΕ 20701-1/2017 (ΦΕΚ Β' 4003/17.11.2017)"
# The KENAK reference building by climate zone (ΤΟΤΕΕ 20701-1/2017 table 3.4α, §4.2.1): U of walls, roof and floor over pilotis
# (both used when exposed), windows, W/m²K; and the zone's cooling period (§2.4.2), the period of the summer shading.
KENAK_ZONES = {
    "a": ("Α", 0.60, 0.50, 3.20, ("05-15", "09-15")),
    "b": ("Β", 0.50, 0.45, 3.00, ("05-15", "09-15")),
    "c": ("Γ", 0.45, 0.40, 2.80, ("06-01", "08-31")),
    "d": ("Δ", 0.40, 0.35, 2.60, ("06-01", "08-31")),
}
# By use: schedule (table 2.1), set points (2.2), fresh air while in use (2.3), heat recovery (§4.4.1, reference ventilation),
# internal gains while in use (people 2.7 + equipment x diversity 2.8 + lighting 2.4, 2.4α: 4 + 2 for an apartment, 8 + 4.5 + 16
# for an office) and the ΤΟΤΕΕ mass category (3.14) with the ISO class nearest to it.
KENAK_USES = {
    "apartment": ("Apartment", "apartment", 0.75, 0.0, 6.0, 5, "heavy"),
    "office": ("Office", "office", 3.0, 0.5, 28.5, 3, "medium"),
}
DEFAULT_LIBRARY_ID = "kenak-apartment-b"    # the building of a new project


def _kenak_values(use: str, zone: str) -> dict:
    """The values of the KENAK reference building for a use and a climate zone: as KENAK_ZONES and KENAK_USES, with g 0.55 (glass 0.76
    x 0.9 mean over the angles x 0.8 for a 20 % frame, §4.2.7), infiltration 5.5 m³/h per m² of window (§4.4.1), summer shading 0.77
    (the mean of the reference building's NE, SE, SW and NW factors 0.80, 0.73, 0.73, 0.80, §4.3.1) and the average room 6 m deep
    with a 3 m storey, 40 % windows on each side, roof and floor not exposed."""
    _letter, u_wall, u_roof_and_floor, u_window, (shading_start, shading_end) = KENAK_ZONES[zone]
    _label, schedule, fresh_air, heat_recovery, gains, category, mass_class = KENAK_USES[use]
    return {"schedule": schedule, "t_set_heating": 20.0, "t_set_cooling": 26.0, "gains_w_m2": gains, "fresh_air_m3h_m2": fresh_air,
            "heat_recovery": heat_recovery, "u_wall": u_wall, "u_window": u_window, "g_value": 0.55,
            "mass_kind": "totee", "mass_class": mass_class, "totee_category": category,
            "shading_factor": 0.77, "shading_start": shading_start, "shading_end": shading_end,
            "room": "average", "height": 3.0, "depth": 6.0, "wwr": {side: 0.4 for side in WWR_SIDES["average"]},
            "roof_exposed": False, "u_roof": u_roof_and_floor, "floor_exposed": False, "u_floor": u_roof_and_floor,
            "infiltration_m3h_m2_window": 5.5}


ASHRAE_SOURCE = ("ANSI/ASHRAE Standard 140 (BESTEST), case {case}: 8 x 6 x 2.7 m box, 12 m² of double clear glass on the south wall, "
                 "U walls {u_wall}, roof 0.318, floor 0.039 (over outdoor air), window 3.0 W/m²K, glass SHGC 0.787 x 0.9 mean over the "
                 "angles, 200 W constant gains, infiltration 0.5 ach, 20 / 27 °C. {construction}. Layers from the Modelica Buildings "
                 "library's BESTEST data (LBNL); the U values computed from them with the standard's surface coefficients; the window U "
                 "and SHGC are not checked against the standard's text.")


def _ashrae_values(u_wall: float, mass_class: str, category: int) -> dict:
    """The values of an ASHRAE 140 box: as ASHRAE_SOURCE, the gains 200 W over 48 m², the infiltration 0.5 ach as 5.4 m³/h per m² of
    its 12 m² of window (0.5 x 129.6 m³ / 12), no fresh air, no shading, the thermal mass an ISO class (the ΤΟΤΕΕ category nearest
    to it kept for a switch)."""
    return {"schedule": "always", "t_set_heating": 20.0, "t_set_cooling": 27.0, "gains_w_m2": round(200.0 / 48.0, 4),
            "fresh_air_m3h_m2": 0.0, "heat_recovery": 0.0, "u_wall": u_wall, "u_window": 3.0, "g_value": 0.71,
            "mass_kind": "iso", "mass_class": mass_class, "totee_category": category,
            "shading_factor": None, "shading_start": "06-01", "shading_end": "08-31",
            "room": "box", "height": 2.7, "width": 8.0, "length": 6.0, "orientation": 0.0,
            "wwr": {"north": 0.0, "east": 0.0, "south": round(12.0 / 21.6, 4), "west": 0.0},
            "roof_exposed": True, "u_roof": 0.318, "floor_exposed": True, "u_floor": 0.039,
            "infiltration_m3h_m2_window": 5.4}


def _examples() -> dict[str, LibraryEntry]:
    examples = {}
    for use, (label, *_rest) in KENAK_USES.items():
        for zone, (letter, *_zone_rest) in KENAK_ZONES.items():
            examples[f"kenak-{use}-{zone}"] = LibraryEntry(
                f"kenak-{use}-{zone}", f"{label}, zone {letter}", use, validate(_kenak_values(use, zone)),
                f"{TOTEE_SOURCE}, reference building, zone {letter}")
    examples["ashrae140-600"] = LibraryEntry(
        "ashrae140-600", "ASHRAE 140 case 600 (light)", "test", validate(_ashrae_values(0.514, "very_light", 1)),
        ASHRAE_SOURCE.format(case=600, u_wall=0.514, construction="Lightweight: timber siding, glass fibre, plasterboard; about "
                                                                   "40 kJ/m²K, so the lightest ISO class (very light, 80)"))
    examples["ashrae140-900"] = LibraryEntry(
        "ashrae140-900", "ASHRAE 140 case 900 (heavy)", "test", validate(_ashrae_values(0.512, "heavy", 5)),
        ASHRAE_SOURCE.format(case=900, u_wall=0.512, construction="Heavyweight: 100 mm concrete block walls and an 80 mm concrete "
                                                                   "floor inside the insulation; about 305 kJ/m²K, so the ISO class "
                                                                   "nearest to it (heavy, 260)"))
    return examples


EXAMPLES: dict[str, LibraryEntry] = _examples()
OWN_ID_PATTERN = re.compile(r"^own-[0-9a-f]{12}$")
_library_lock = threading.Lock()        # one change of the own entries at a time


def library_folder() -> Path:
    """The folder of the user's own entries, beside the user preferences file (user_preferences.preferences_file)."""
    return user_preferences.preferences_file().parent / "typical_buildings"


def _read_own_entry(path: Path) -> LibraryEntry | None:
    """The own entry in *path*; None when the file cannot be read or does not hold a name and valid values."""
    try:
        stored = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return None
    if not isinstance(stored, dict) or not isinstance(stored.get("name"), str):
        return None
    try:
        values = validate(stored.get("values"))
    except ConfigError:
        return None
    return LibraryEntry(path.stem, stored["name"], "own", values)


def own_entries() -> list[LibraryEntry]:
    """The user's own entries by name; a file that cannot be read or holds values that are not valid is left out."""
    folder = library_folder()
    paths = sorted(folder.glob("own-*.yaml")) if folder.is_dir() else []
    entries = [entry for entry in (_read_own_entry(path) for path in paths if OWN_ID_PATTERN.match(path.stem)) if entry is not None]
    return sorted(entries, key=lambda entry: (entry.name.casefold(), entry.id))


def library() -> list[LibraryEntry]:
    """The examples (apartments, offices, test boxes, in that order) and then the user's own entries by name."""
    return list(EXAMPLES.values()) + own_entries()


def library_entry(entry_id: str | None) -> LibraryEntry | None:
    """The entry with this id, None when there is none."""
    if entry_id is None:
        return None
    if entry_id in EXAMPLES:
        return EXAMPLES[entry_id]
    if not OWN_ID_PATTERN.match(entry_id):
        return None
    return _read_own_entry(library_folder() / f"{entry_id}.yaml")


def _checked_name(name, entry_id: str | None = None) -> str:
    """*name* without the spaces around it; ConfigError at the field name when empty or too long, ProjectError 409 when another entry
    has it (letter case aside)."""
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("The building has no name.", [ConfigFieldError("name", "Give the building a name.")])
    name = name.strip()
    if len(name) > MAX_NAME_LENGTH:
        raise ConfigError("The name is too long.", [ConfigFieldError("name", f"Give a name of at most {MAX_NAME_LENGTH} characters.")])
    if any(entry.name.casefold() == name.casefold() and entry.id != entry_id for entry in library()):
        raise ProjectError(f"A building named '{name}' is already in the library: choose another name.", status_code=409)
    return name


def _write_own_entry(entry_id: str, name: str, values: dict) -> None:
    """Write the entry's file as a whole, through a temporary file in the same folder."""
    folder = library_folder()
    folder.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix="writing-", suffix=".yaml.tmp", dir=folder)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            yaml.safe_dump({"name": name, "values": values}, temporary_file, allow_unicode=True, sort_keys=False)
        os.replace(temporary_name, folder / f"{entry_id}.yaml")
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _own_entry_to_change(entry_id: str, verb: str) -> LibraryEntry:
    entry = library_entry(entry_id)
    if entry is None:
        raise ProjectError(f"There is no building '{entry_id}' in the library.", status_code=404)
    if entry.read_only:
        raise ProjectError(f"'{entry.name}' is an example and cannot be {verb}: save a copy of it with Save as new.", status_code=409)
    return entry


def add_entry(name, values) -> LibraryEntry:
    """Save a new own entry (Save as new); ConfigError for a value or the name, ProjectError 409 for a name in use."""
    checked = validate(values)
    with _library_lock:
        name = _checked_name(name)
        entry_id = f"own-{secrets.token_hex(6)}"
        _write_own_entry(entry_id, name, checked)
    return LibraryEntry(entry_id, name, "own", checked)


def update_entry(entry_id: str, name=None, values=None) -> LibraryEntry:
    """Rename an own entry, change its values (Save to library), or both; ProjectError 404 for no such entry, 409 for an example or a
    name in use, ConfigError for a value or the name. Nothing changes on an error."""
    checked = validate(values) if values is not None else None
    with _library_lock:
        entry = _own_entry_to_change(entry_id, "changed")
        name = _checked_name(name, entry_id) if name is not None else entry.name
        checked = checked if checked is not None else entry.values
        _write_own_entry(entry_id, name, checked)
    return LibraryEntry(entry_id, name, "own", checked)


def delete_entry(entry_id: str) -> None:
    """Delete an own entry; ProjectError 404 for no such entry, 409 for an example. A project that copied it keeps its copy."""
    with _library_lock:
        _own_entry_to_change(entry_id, "deleted")
        (library_folder() / f"{entry_id}.yaml").unlink(missing_ok=True)


# ---- The project's building and its weights ----

def default_building() -> TypicalBuildingEntry:
    entry = EXAMPLES[DEFAULT_LIBRARY_ID]
    return TypicalBuildingEntry(values=copy.deepcopy(entry.values), library_id=entry.id, library_name=entry.name)


def building_of(project_json: ProjectJson) -> TypicalBuildingEntry:
    """The project's building; a copy of the default entry (DEFAULT_LIBRARY_ID), not calculated, when project.json has none or holds
    the values of the first build of this form (with no schedule)."""
    building = project_json.typical_building
    if building is None or "schedule" not in building.values:
        return default_building()
    return building


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


def _sun_up(meta: dict) -> np.ndarray:
    """The meta's hours with the sun up as a bool array; every hour for a file written before the meta held them."""
    sun_up = np.asarray(meta.get("sun_up", ()), dtype=bool)
    return sun_up if sun_up.shape == (HOURS,) else np.ones(HOURS, dtype=bool)


def reply(store, name: str) -> TypicalBuildingReply:
    """The building, the library entry it came from (changed when the copy differs from the entry; the entry's name now, or the name
    the project kept when the entry is gone), the state of its weights and, when the weights file exists, the numbers it holds."""
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
                counted = int(((benefit > COUNTED_WEIGHT) & _sun_up(meta)).sum())
    entry = library_entry(building.library_id)
    return TypicalBuildingReply(values=building.values, library_id=building.library_id,
                                library_name=entry.name if entry is not None else building.library_name,
                                changed=entry is not None and entry.values != building.values, state=state,
                                heating_kwh_m2=heating, cooling_kwh_m2=cooling, counted_hours=counted)


def weights_reply(store, name: str) -> TypicalBuildingWeightsReply:
    """The hourly weights of the weights file, to WEIGHT_DECIMALS decimals, and its hours with the sun up; ProjectError 404 when there
    is none."""
    path = weights_file(store.open(name))
    try:
        benefit, harm, meta = read_simulated_weights(path)
    except ValueError as error:
        raise ProjectError(NOT_CALCULATED_MESSAGE, status_code=404) from error
    return TypicalBuildingWeightsReply(benefit=[round(float(value), WEIGHT_DECIMALS) for value in benefit],
                                       harm=[round(float(value), WEIGHT_DECIMALS) for value in harm],
                                       sun_up=[int(value) for value in _sun_up(meta)])


_KEEP = object()        # save(): keep the library entry the building came from


def save(store, name: str, values, library_id=_KEEP) -> TypicalBuildingReply:
    """Store the building's values (validate) and, when *library_id* is given, the library entry they came from (None: from none);
    the key of its last calculation stays. ConfigError, and nothing changes, when a value is not valid or *library_id* names no
    entry (field library_id)."""
    checked = validate(values)
    entry = None
    if library_id is not _KEEP and library_id is not None:
        entry = library_entry(library_id)
        if entry is None:
            raise ConfigError(f"'{library_id}' is not a building in the library.",
                              [ConfigFieldError("library_id", "Not a building in the library.")])
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        building = building_of(project_json)
        if library_id is _KEEP:
            origin = {"library_id": building.library_id, "library_name": building.library_name}
        else:
            origin = {"library_id": entry.id if entry else None, "library_name": entry.name if entry else None}
        project_json.typical_building = TypicalBuildingEntry(values=checked, calculated_key=building.calculated_key, **origin)
        store.write_project_json(name, project_json)
    return reply(store, name)


def calculate(store, name: str, values: dict | None = None) -> str:
    """Calculate the weights of *values* (default: the stored building) with the project's weather file into WEIGHTS_PATH and record
    their key in project.json; the key.

    The generator writes into a new folder beside WEIGHTS_PATH, and the files replace the earlier ones together with the record of the
    key, under the project lock, so the file and its key always belong together. The lock is not held while the generator runs (about
    7 s). ProjectError: 404 without a weather file (NO_WEATHER_FILE_MESSAGE), 422 when the generator fails.
    """
    from ..simulated_weights import generate_simulated_weights
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
            written = Path(generate_simulated_weights(str(weather_path), archetype_of(values, weather_path), work_folder / target.name))
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
