"""What a run reports to the browser besides its meshes: the summary numbers, the sky dome and the sun path.

The numbers come from the diagnostics the stages wrote, the sky dome from the patch weights of
preprocessing, and the sun path from the stored settings alone (it needs no run).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..mode_registry import canonical_mode_name
from ..pydantic_schemas import ExportingManifest, MassingManifest, PreprocessingManifest, UserConfig
from ..stage_settings import stage_folder
from .api_models import CarvingSummary, EnvelopeSummary, MassingSummary, RunSummary, SkyDome, SunMarker, SunPath, SunPathDay
from .score_points import read_stage_manifest, resolve_stored_path

DIAGNOSTIC_PATH = Path("diagnostics") / "diagnostic.json"
PLATES_FILE_NAME = "plates.json"
HOURS_PER_DAY = 24
MINUTES_PER_DAY = 24 * 60
MINUTES_PER_YEAR = 365 * MINUTES_PER_DAY
LONG_DAY_HOURS = 8              # a daily period longer than this gets a marker every 3 hours instead of 2
DAY_PATH_STEP_MINUTES = 10
STEPS_PER_HOUR_OF_PERIOD_PATH = 12      # one point every 5 minutes
HORIZON_SEARCH_MINUTES = 5      # sunrise and sunset are rounded to a minute, which can leave the sun just below the horizon
SUN_PATH_MODE = "time-based"


def build_run_summary(run_folder: Path, envelope_voxel_size: float | None = None) -> RunSummary:
    """The numbers of the thresholding, exporting and massing stages; each part is None when its stage has no output.

    *envelope_voxel_size* is the voxel size of the grid exporting meshed (stage_records.envelope_voxel_size); without it the
    envelope part is None, since the exporting diagnostic counts voxels only.
    """
    run_folder = Path(run_folder)
    return RunSummary(carving=_carving_summary(run_folder), envelope=_envelope_summary(run_folder, envelope_voxel_size),
                      massing=_massing_summary(run_folder))


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _carving_summary(run_folder: Path) -> CarvingSummary | None:
    diagnostic = _read_json(stage_folder(run_folder, "thresholding") / DIAGNOSTIC_PATH)
    if diagnostic is None:
        return None
    return CarvingSummary(
        threshold_value=diagnostic["threshold_value"],
        voxels_occupied=diagnostic["voxels_occupied"],
        voxels_kept=diagnostic["voxels_kept"],
        voxels_removed=diagnostic["voxels_removed"],
        retention_pct=diagnostic["retention_pct"],
        obstruction_fraction_carved=diagnostic.get("obstruction_fraction_carved"),
        carve_above_extra_voxels_removed=diagnostic["carve_above_extra_voxels_removed"],
        slope_limit_extra_voxels_removed=diagnostic["slope_limit_extra_voxels_removed"],
    )


def _envelope_summary(run_folder: Path, voxel_size: float | None) -> EnvelopeSummary | None:
    """The envelope mesh exporting wrote, named by its manifest (a format chosen since does not rename it), and its volume."""
    manifest = read_stage_manifest(run_folder, "exporting", ExportingManifest)
    if manifest is None:
        return None
    diagnostic = _read_json(stage_folder(run_folder, "exporting") / DIAGNOSTIC_PATH)
    volume = None if diagnostic is None or voxel_size is None else diagnostic["voxels_retained"] * voxel_size ** 3
    return EnvelopeSummary(mesh_file=Path(manifest[0].mesh_path).name, envelope_volume_m3=volume)


def _massing_summary(run_folder: Path) -> MassingSummary | None:
    """The floor areas massing wrote and its mesh in the chosen format, named by its manifest (plates.obj for a manifest from
    before massing wrote that format)."""
    manifest = read_stage_manifest(run_folder, "massing", MassingManifest)
    massing_folder = stage_folder(run_folder, "massing")
    plates = _read_json(massing_folder / PLATES_FILE_NAME)
    diagnostic = _read_json(massing_folder / DIAGNOSTIC_PATH)
    if manifest is None or plates is None or diagnostic is None:
        return None
    return MassingSummary(
        export_mesh_file=Path(manifest[0].export_mesh_path or manifest[0].mesh_path).name,
        floor_area_m2_per_storey=plates["floor_area_m2_per_floor"],
        total_floor_area_m2=plates["total_floor_area_m2"],
        storeys_built=diagnostic["floors_built"],
    )


def build_sky_dome(run_folder: Path) -> SkyDome | None:
    """The 145 Tregenza patches with the weights of preprocessing; None for a run without patch weights."""
    preprocessing = read_stage_manifest(Path(run_folder), "preprocessing", PreprocessingManifest)
    if preprocessing is None or preprocessing[0].patch_weights_path is None:
        return None
    manifest, manifest_folder = preprocessing
    import torch
    from ..sky_patches import fetch_tregenza_patch_directions, tregenza_solid_angles
    patch_weights = np.load(resolve_stored_path(manifest_folder, manifest.patch_weights_path))
    return SkyDome(
        directions=fetch_tregenza_patch_directions(torch.device("cpu")).numpy().tolist(),
        solid_angles=tregenza_solid_angles().tolist(),
        weights=patch_weights.ravel().tolist(),
    )


def sun_marker_hours(start_hour: int, end_hour: int) -> list[int]:
    """The whole hours that get a sun disc: every 2 hours, every 3 hours when the daily period is longer than 8 hours.

    A period whose end hour is before its start hour runs over midnight, as in the engine
    (20 to 4 is 20, 22, 0, 2, 4).
    """
    hours_in_period = (end_hour - start_hour) % HOURS_PER_DAY
    step = 3 if hours_in_period > LONG_DAY_HOURS else 2
    return [(start_hour + hours_after_start) % HOURS_PER_DAY for hours_after_start in range(0, hours_in_period + 1, step)]


def sun_path_for_config(config: UserConfig) -> SunPath:
    """The sun path of the first and the last day of the stored analysis period (one day when they are the same).

    Empty unless the mode is time-based and the weather file and the period are set. The vectors point
    toward the sun in model coordinates (the stored ``north_deg`` applied). The analysis hours drawn
    are the engine's own: the times of its analysis period that fall on the day.
    """
    period = (config.start_month, config.start_day, config.start_hour, config.end_month, config.end_day, config.end_hour)
    if canonical_mode_name(config.mode) != SUN_PATH_MODE or None in period:
        return SunPath(days=[])
    if config.epw_path is None or not Path(config.epw_path).is_file():
        return SunPath(days=[])
    first_day = (config.start_month, config.start_day)
    last_day = (config.end_month, config.end_day)
    days = [first_day] if first_day == last_day else [first_day, last_day]
    period_date_times = _analysis_period_date_times(config)
    return SunPath(days=[_sun_path_of_day(config, month, day, period_date_times) for month, day in days])


def _analysis_period_date_times(config: UserConfig) -> list:
    """The times of the engine's analysis period every 5 minutes (it handles a period that runs over midnight)."""
    from ..sun import sample_period
    from ..stage_settings import PreprocessingSettings
    date_times, _ = sample_period(PreprocessingSettings.from_config(config), STEPS_PER_HOUR_OF_PERIOD_PATH)
    return date_times


def _sun_path_of_day(config: UserConfig, month: int, day: int, period_date_times: list) -> SunPathDay:
    sunrise_and_sunset_minutes = _sunrise_and_sunset_minutes_of_year(config, month, day)
    if sunrise_and_sunset_minutes is None:      # polar day or polar night: the calendar day, with no ends on the horizon
        first_minute = _date_times(month, day, 0)[0].moy
        day_path = _sun_vectors(config, _date_times_of_minutes(range(first_minute, first_minute + MINUTES_PER_DAY, DAY_PATH_STEP_MINUTES)),
                                min_altitude=0.0)
    else:
        sunrise_minute, sunset_minute = sunrise_and_sunset_minutes
        day_path = _sun_vectors(
            config, _date_times_of_minutes(range(sunrise_minute, sunset_minute + 1, DAY_PATH_STEP_MINUTES)), min_altitude=0.0)
        # Ladybug rounds sunrise and sunset to a minute, so the sun can be a hair below the horizon at that minute
        # and get_sun_vectors drops it: the minutes after sunrise and before sunset are looked up too, and the
        # nearest one above the horizon is taken.
        after_sunrise = _sun_vectors(
            config, _date_times_of_minutes(range(sunrise_minute, min(sunrise_minute + HORIZON_SEARCH_MINUTES, sunset_minute) + 1)),
            min_altitude=0.0)
        before_sunset = _sun_vectors(
            config, _date_times_of_minutes(range(max(sunset_minute - HORIZON_SEARCH_MINUTES, sunrise_minute), sunset_minute + 1)),
            min_altitude=0.0)
        if after_sunrise and before_sunset:
            day_path = [_laid_on_horizon(after_sunrise[0]), *day_path, _laid_on_horizon(before_sunset[-1])]

    period_date_times_of_day = [date_time for date_time in period_date_times if (date_time.month, date_time.day) == (month, day)]
    period_path = _sun_vectors(config, period_date_times_of_day, min_altitude=config.min_altitude)
    markers = []
    for hour in sun_marker_hours(config.start_hour, config.end_hour):
        hour_vectors = _sun_vectors(config, _date_times(month, day, hour * 60), min_altitude=config.min_altitude)
        if hour_vectors:
            markers.append(SunMarker(hour=hour, vector=hour_vectors[0]))
    return SunPathDay(date=f"{month:02d}-{day:02d}", day_path=day_path, period_path=period_path, markers=markers)


def _sunrise_and_sunset_minutes_of_year(config: UserConfig, month: int, day: int) -> tuple[int, int] | None:
    """Ladybug's sunrise and sunset of the day as minutes of the year; None on a day the sun does not rise and set.

    Sunset can fall after midnight, on the next calendar day, which the minute of the year keeps.
    """
    from ladybug.epw import EPW
    from ladybug.sunpath import Sunpath
    sunrise_and_sunset = Sunpath.from_location(EPW(config.epw_path).location).calculate_sunrise_sunset(month, day)
    sunrise, sunset = sunrise_and_sunset["sunrise"], sunrise_and_sunset["sunset"]
    if sunrise is None or sunset is None:
        return None
    return sunrise.moy, sunset.moy


def _date_times(month: int, day: int, minute_of_day: int):
    """A one-element list with the Ladybug DateTime at a minute of the day."""
    from ladybug.dt import DateTime
    return [DateTime(month, day, minute_of_day // 60, minute_of_day % 60)]


def _date_times_of_minutes(minutes_of_year):
    """Ladybug DateTimes for minutes of the year, wrapping past the end of the year."""
    from ladybug.dt import DateTime
    return [DateTime.from_moy(minute % MINUTES_PER_YEAR) for minute in minutes_of_year]


def _sun_vectors(config: UserConfig, date_times, min_altitude: float) -> list[list[float]]:
    """The sun directions at the times when the sun is above ``min_altitude``, in time order.

    A time with the sun below it is an ordinary outcome here, so the engine's issue about an empty
    result is collected in a throwaway run context instead of being raised as a warning.
    """
    if not date_times:
        return []
    import torch
    from ..run_context import RunContext, run_context
    from ..sun import get_sun_vectors
    with run_context(RunContext()):
        vectors = get_sun_vectors(config.epw_path, date_times, min_altitude, torch.device("cpu"), config.north_deg)
    return vectors.tolist()


def _laid_on_horizon(sun_vector: list[float]) -> list[float]:
    """A sun direction with its height set to 0, as a unit vector."""
    x, y, _ = sun_vector
    horizontal_length = (x * x + y * y) ** 0.5
    return [x / horizontal_length, y / horizontal_length, 0.0]
