"""What a run reports to the browser besides its meshes: the summary numbers, the sky dome and the sun path.

The numbers come from the diagnostics the stages wrote, the sky dome from the patch weights of
preprocessing, and the sun path from the stored settings alone (it needs no run).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..mode_registry import canonical_mode_name
from ..pydantic_schemas import PreprocessingManifest, UserConfig
from ..stage_settings import stage_folder
from .api_models import CarvingSummary, MassingSummary, RunSummary, SkyDome, SunMarker, SunPath, SunPathDay
from .score_points import read_stage_manifest, resolve_stored_path

DIAGNOSTIC_PATH = Path("diagnostics") / "diagnostic.json"
PLATES_FILE_NAME = "plates.json"
LONG_DAY_HOURS = 8              # a daily period longer than this gets a marker every 3 hours instead of 2
DAY_PATH_STEP_MINUTES = 10
PERIOD_PATH_STEP_MINUTES = 5
HORIZON_SEARCH_MINUTES = 5      # sunrise and sunset are rounded to a minute, which can leave the sun just below the horizon
SUN_PATH_MODE = "time-based"


def build_run_summary(run_folder: Path) -> RunSummary:
    """The numbers of the thresholding and massing stages; each part is None when its stage has no output."""
    return RunSummary(carving=_carving_summary(Path(run_folder)), massing=_massing_summary(Path(run_folder)))


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


def _massing_summary(run_folder: Path) -> MassingSummary | None:
    massing_folder = stage_folder(run_folder, "massing")
    plates = _read_json(massing_folder / PLATES_FILE_NAME)
    diagnostic = _read_json(massing_folder / DIAGNOSTIC_PATH)
    if plates is None or diagnostic is None:
        return None
    return MassingSummary(
        floor_area_m2_per_storey=plates["floor_area_m2_per_floor"],
        total_floor_area_m2=plates["total_floor_area_m2"],
        storeys_built=diagnostic["floors_built"],
        envelope_volume_m3=diagnostic["envelope_volume_m3"],
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
    """The whole hours that get a sun disc: every 2 hours, every 3 hours when the daily period is longer than 8 hours."""
    step = 3 if end_hour - start_hour > LONG_DAY_HOURS else 2
    return list(range(start_hour, end_hour + 1, step))


def sun_path_for_config(config: UserConfig) -> SunPath:
    """The sun path of the first and the last day of the stored analysis period (one day when they are the same).

    Empty unless the mode is time-based and the weather file and the period are set. The vectors point
    toward the sun in model coordinates (the stored ``north_deg`` applied).
    """
    period = (config.start_month, config.start_day, config.start_hour, config.end_month, config.end_day, config.end_hour)
    if canonical_mode_name(config.mode) != SUN_PATH_MODE or None in period:
        return SunPath(days=[])
    if config.epw_path is None or not Path(config.epw_path).is_file():
        return SunPath(days=[])
    first_day = (config.start_month, config.start_day)
    last_day = (config.end_month, config.end_day)
    days = [first_day] if first_day == last_day else [first_day, last_day]
    return SunPath(days=[_sun_path_of_day(config, month, day) for month, day in days])


def _sun_path_of_day(config: UserConfig, month: int, day: int) -> SunPathDay:
    day_path = _sun_vectors(config, _date_times(month, day, range(0, 24 * 60, DAY_PATH_STEP_MINUTES)), min_altitude=0.0)
    sunrise_vector, sunset_vector = _vectors_at_sunrise_and_sunset(config, month, day)
    if sunrise_vector is not None and sunset_vector is not None:
        day_path = [_laid_on_horizon(sunrise_vector), *day_path, _laid_on_horizon(sunset_vector)]

    period_minutes = range(config.start_hour * 60, config.end_hour * 60 + 1, PERIOD_PATH_STEP_MINUTES)
    period_path = _sun_vectors(config, _date_times(month, day, period_minutes), min_altitude=config.min_altitude)
    markers = []
    for hour in sun_marker_hours(config.start_hour, config.end_hour):
        hour_vectors = _sun_vectors(config, _date_times(month, day, [hour * 60]), min_altitude=config.min_altitude)
        if hour_vectors:
            markers.append(SunMarker(hour=hour, vector=hour_vectors[0]))
    return SunPathDay(date=f"{month:02d}-{day:02d}", day_path=day_path, period_path=period_path, markers=markers)


def _vectors_at_sunrise_and_sunset(config: UserConfig, month: int, day: int) -> tuple[list[float] | None, list[float] | None]:
    """The sun directions at Ladybug's sunrise and sunset of the day; None for both on a day the sun does not rise and set.

    Ladybug rounds the two times to a minute, so the sun can be a hair below the horizon at that minute
    and ``get_sun_vectors`` drops it: the first minutes after sunrise and the last minutes before sunset
    are looked up too, and the nearest one that is above the horizon is taken.
    """
    from ladybug.epw import EPW
    from ladybug.sunpath import Sunpath
    sunrise_and_sunset = Sunpath.from_location(EPW(config.epw_path).location).calculate_sunrise_sunset(month, day)
    sunrise, sunset = sunrise_and_sunset["sunrise"], sunrise_and_sunset["sunset"]
    if sunrise is None or sunset is None:
        return None, None       # polar day or polar night
    sunrise_minute = sunrise.hour * 60 + sunrise.minute
    sunset_minute = sunset.hour * 60 + sunset.minute
    after_sunrise = _sun_vectors(
        config, _date_times(month, day, range(sunrise_minute, sunrise_minute + HORIZON_SEARCH_MINUTES + 1)), min_altitude=0.0)
    before_sunset = _sun_vectors(
        config, _date_times(month, day, range(sunset_minute - HORIZON_SEARCH_MINUTES, sunset_minute + 1)), min_altitude=0.0)
    if not after_sunrise or not before_sunset:
        return None, None
    return after_sunrise[0], before_sunset[-1]


def _date_times(month: int, day: int, minutes_of_day):
    from ladybug.dt import DateTime
    return [DateTime(month, day, minute_of_day // 60, minute_of_day % 60) for minute_of_day in minutes_of_day]


def _sun_vectors(config: UserConfig, date_times, min_altitude: float) -> list[list[float]]:
    """The sun directions at the times when the sun is above ``min_altitude``, in time order.

    A time with the sun below it is an ordinary outcome here, so the engine's issue about an empty
    result is collected in a throwaway run context instead of being raised as a warning.
    """
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
