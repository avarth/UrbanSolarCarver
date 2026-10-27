"""The studies of a project: names, defaults, settings and the results folder.

A study (``StudyEntry``) is a metric of the sun and sky check on test surfaces, over a period; project.json keeps the
list beside the criteria and never mixes with them. The functions here change a ``ProjectJson`` in memory; the store
(``ProjectStore.add_study`` and the others) reads and writes it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from ..check_settings import CHECK_METRICS, DEFAULT_CHECK_METRIC, CheckSettings, build_check_settings
from ..errors import ConfigError
from ..mode_registry import MODES, canonical_mode_name
from .api_models import CriterionEntry, MetricInfo, ProjectJson, StudyEntry
from .criteria import colour_of_criterion
from .project_names import ProjectError

SIMULATE_FOLDER = "simulate"        # in the project folder; the results of a study are in simulate/<id>
JOINED_STUDY_SURFACES_PATH = "inputs/joined/study_surfaces_{id}.ply"     # beside the criteria's test_surfaces_<id>.ply, never the same name
PERIOD_KEYS = ("start_month", "start_day", "start_hour", "end_month", "end_day", "end_hour")
# The mode settings each metric reads besides the period; a metric not listed reads none.
METRIC_MODE_SETTING_KEYS: Mapping[str, tuple[str, ...]] = {
    "useful_solar_energy": ("balance_temperature", "balance_offset", "include_harm"),
    "cooling_sky": ("dew_point_celsius", "bliss_k"),
}
# The settings of a metric that sums over a period: the period and the clock its hours are read in (a stored study without
# time_basis reads it as "standard", the CheckSettings default).
PERIOD_SETTING_KEYS = (*PERIOD_KEYS, "time_basis")
# Every key a study's settings can hold.
STUDY_SETTING_KEYS = (*PERIOD_SETTING_KEYS, "balance_temperature", "balance_offset", "include_harm", "dew_point_celsius", "bliss_k")
MONTH_ABBREVIATIONS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
NOT_SENT = object()     # an update that does not mention the target (None means: no target)
# A weather file name for the validation of settings, which does not read the file.
_VALIDATION_WEATHER_FILE = "weather.epw"


def study_folder(project_folder: Path, study_id: str) -> Path:
    """The folder of a study's results, <project>/simulate/<id>."""
    return Path(project_folder) / SIMULATE_FOLDER / study_id


def joined_study_surfaces_path(study_id: str) -> str:
    """The joined test surface file of a study, relative to the project folder."""
    return JOINED_STUDY_SURFACES_PATH.format(id=study_id)


def checked_metric(metric: str) -> str:
    """The metric when the check knows it; ProjectError(422) otherwise."""
    if metric not in CHECK_METRICS:
        raise ProjectError(f"'{metric}' is not a metric: use one of {', '.join(CHECK_METRICS)}.", status_code=422)
    return metric


def checked_study_name(name: str) -> str:
    """The name without surrounding spaces; ProjectError(422) when nothing is left."""
    if not name.strip():
        raise ProjectError("A study needs a name.", status_code=422)
    return name.strip()


def settings_keys_of(metric: str) -> tuple[str, ...]:
    """The keys of the settings of a study of this metric: the period and its time basis when the metric needs a period, and its
    mode settings."""
    spec = CHECK_METRICS[metric]
    return (*(PERIOD_SETTING_KEYS if spec.needs_period else ()), *METRIC_MODE_SETTING_KEYS.get(metric, ()))


def default_study_settings(metric: str) -> dict:
    """The settings a new study of this metric starts with: the starting period of the mode the metric takes it from with the
    standard time basis, and the defaults of the mode settings it reads (the field defaults of CheckSettings)."""
    spec = CHECK_METRICS[metric]
    settings: dict = {}
    if spec.needs_period:
        starting = MODES[spec.period_from_mode].starting_values
        settings.update({key: starting[key] for key in PERIOD_KEYS})
        settings["time_basis"] = CheckSettings.model_fields["time_basis"].default
    for key in METRIC_MODE_SETTING_KEYS.get(metric, ()):
        settings[key] = CheckSettings.model_fields[key].default
    return settings


def metric_infos(has_weather_file: bool) -> list[MetricInfo]:
    """Every metric with whether its inputs exist and the settings a new study of it starts with."""
    return [MetricInfo(name=spec.name, label=spec.label, unit=spec.unit, needs_epw=spec.needs_epw,
                       available=has_weather_file or not spec.needs_epw, default_settings=default_study_settings(spec.name))
            for spec in CHECK_METRICS.values()]


def _day_and_month(month: int, day: int) -> str:
    return f"{day} {MONTH_ABBREVIATIONS[month - 1]}"


def default_study_name(metric: str, settings: Mapping) -> str:
    """The name a study has until the user names it: the metric's label, then the period when the metric needs one
    ("Sun hours, 21 Dec" for one day, "Sun hours, 1 Sep to 31 May" for a range)."""
    spec = CHECK_METRICS[metric]
    if not spec.needs_period or any(settings.get(key) is None for key in ("start_month", "start_day", "end_month", "end_day")):
        return spec.label
    start = _day_and_month(settings["start_month"], settings["start_day"])
    end = _day_and_month(settings["end_month"], settings["end_day"])
    return f"{spec.label}, {end if start == end else f'{start} to {end}'}"


def study_from_criterion(entry: CriterionEntry) -> tuple[str, dict, list[str]]:
    """The metric, settings and test surface file names of a study like this criterion: the mode's default metric, the metric's
    defaults with the criterion's own values for the keys the metric reads, and a copy of its file names. No link is kept."""
    metric = DEFAULT_CHECK_METRIC[canonical_mode_name(entry.settings.get("mode"))]
    settings = default_study_settings(metric)
    settings.update({key: entry.settings[key] for key in settings if entry.settings.get(key) is not None})
    return metric, settings, list(entry.test_surface_files)


def checked_study_settings(metric: str, settings: Mapping) -> dict:
    """The settings as the check reads them (numbers of the right type); ProjectError(422), naming the fields, when one is not valid
    or not a setting of this metric."""
    allowed = settings_keys_of(metric)
    foreign = [key for key in settings if key not in allowed]
    if foreign:
        raise ProjectError(f"{', '.join(foreign)}: not a setting of {CHECK_METRICS[metric].label}; it has {', '.join(allowed) or 'none'}.",
                           status_code=422)
    try:
        check = build_check_settings({"metric": metric, "epw_path": _VALIDATION_WEATHER_FILE, **settings})
    except ConfigError as error:
        raise ProjectError(str(error), status_code=422) from error
    return {key: getattr(check, key) for key in settings}


def _takes_time_basis(metric: str, time_basis) -> bool:
    """Whether the check accepts *time_basis* for *metric* (with the metric's default settings otherwise)."""
    try:
        build_check_settings({"metric": metric, "epw_path": _VALIDATION_WEATHER_FILE, **default_study_settings(metric), "time_basis": time_basis})
    except ConfigError:
        return False
    return True


def append_study(project_json: ProjectJson, metric: str, settings: dict, files: list[str]) -> StudyEntry:
    """Add a study at the end of the list of *project_json*, with the next id and the palette colour of that number, named by default."""
    checked_metric(metric)
    number = project_json.next_study_id
    entry = StudyEntry(id=str(number), name=default_study_name(metric, settings), colour=colour_of_criterion(number), metric=metric,
                       settings=checked_study_settings(metric, settings), test_surface_files=list(files))
    project_json.studies.append(entry)
    project_json.next_study_id = number + 1
    return entry


def find_study(project_json: ProjectJson, study_id: str) -> StudyEntry:
    """The study with this id; ProjectError(404) when there is none."""
    for study in project_json.studies:
        if study.id == study_id:
            return study
    raise ProjectError(f"There is no study '{study_id}'.", status_code=404)


def change_study(entry: StudyEntry, *, name: str | None = None, metric: str | None = None, values: Mapping | None = None,
                 target: object = NOT_SENT) -> None:
    """Change a study in place; what is not given stays. A ProjectError(422) leaves it as it was.

    A new metric resets the settings to its defaults, keeping the values of the keys both metrics have, except a time basis the new
    metric does not take (only sun hours reads another clock than standard time), which becomes the default. *values* then change
    those keys. The settings are checked after a metric change or with *values*, so no study is stored with settings its metric
    refuses. A study the user did not name is named again by its metric and period.
    """
    new_name = None if name is None else checked_study_name(name)
    new_metric = entry.metric if metric is None else checked_metric(metric)
    settings = dict(entry.settings)
    if new_metric != entry.metric:
        defaults = default_study_settings(new_metric)
        settings = {key: settings.get(key, default) for key, default in defaults.items()}
        if "time_basis" in settings and not _takes_time_basis(new_metric, settings["time_basis"]):
            settings["time_basis"] = defaults["time_basis"]
    if new_metric != entry.metric or values is not None:
        settings = checked_study_settings(new_metric, {**settings, **(values or {})})
    entry.metric, entry.settings = new_metric, settings
    if new_name is not None:
        entry.name, entry.named_by_user = new_name, True
    elif not entry.named_by_user:
        entry.name = default_study_name(new_metric, settings)
    if target is not NOT_SENT:
        entry.target = target
