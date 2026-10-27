"""Metrics and settings of the sun and sky check.

The check (:mod:`urbansolarcarver.solar_check`) measures per test point
how much sun, solar energy or sky reaches it past a mesh: the maximum
volume before carving, the carved envelope and the building massing
after.  This module defines the metrics it can show and their settings,
with the standard library and Pydantic only, so the browser service can
list them without importing torch or Warp.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .errors import ConfigError, ConfigFieldError
from .mode_registry import MODES
from .pydantic_schemas import resolve_grid_step


@dataclass(frozen=True)
class CheckMetric:
    """One quantity the check can show per test point.

    Attributes
    ----------
    name : str
        Key used in settings and files.
    label : str
        Plain name for people.
    unit : str
        Unit of the per-point values.
    needs_epw : bool
        The metric reads the weather file.
    needs_period : bool
        The metric sums over an analysis period.
    period_from_mode : str or None
        The carving mode whose starting period the metric takes when the
        carving itself has no period (for example sun hours in a daylight
        project).
    description : str
        One sentence on what a value means.
    """

    name: str
    label: str
    unit: str
    needs_epw: bool
    needs_period: bool
    period_from_mode: Optional[str]
    description: str


CHECK_METRICS: Dict[str, CheckMetric] = {
    "sun_hours": CheckMetric(
        "sun_hours", "Sun hours", "h", True, True, "time-based",
        "Hours of direct sun on the surface in the period, counted at the sun positions of each hour "
        "that are above the lowest sun altitude and in front of the surface.",
    ),
    "solar_energy": CheckMetric(
        "solar_energy", "Solar energy", "kWh/m²", True, True, "irradiance",
        "Direct and diffuse solar energy the surface receives in the period (Perez sky from the weather "
        "file, cosine of incidence included, no ground reflection).",
    ),
    "useful_solar_energy": CheckMetric(
        "useful_solar_energy", "Useful solar energy", "kWh/m²", True, True, "benefit",
        "Solar energy the surface receives in the hours that need heating, with the balance temperature, "
        "dead band and weights of Solar usefulness.",
    ),
    "sky_component": CheckMetric(
        "sky_component", "Overcast sky component", "%", False, False, None,
        "Light from a CIE overcast sky on the surface, as a share of what an unobstructed horizontal "
        "surface receives; on a vertical surface this is the vertical sky component (39.6 % at most).",
    ),
    "cooling_sky": CheckMetric(
        "cooling_sky", "Cooling sky", "%", False, False, None,
        "Long-wave cooling potential toward the clear night sky the surface sees, as a share of an "
        "unobstructed horizontal surface's.",
    ),
    "sky_view": CheckMetric(
        "sky_view", "Sky view factor", "%", False, False, None,
        "Share of the surface's view taken by the sky, cosine-weighted: 100 % for an unobstructed "
        "horizontal surface, 50 % for an unobstructed wall.",
    ),
}

# The metric each carving mode's check shows unless another is chosen.
DEFAULT_CHECK_METRIC: Mapping[str, str] = {
    "time-based": "sun_hours",
    "irradiance": "solar_energy",
    "benefit": "useful_solar_energy",
    "daylight": "sky_component",
    "radiative_cooling": "cooling_sky",
    "tilted_plane": "sky_view",
}

_PERIOD_FIELDS = ("start_month", "start_day", "start_hour", "end_month", "end_day", "end_hour")


class CheckSettings(BaseModel):
    """What the check computes and how finely.

    The mode settings a metric reads (weather file, north, balance
    temperature and the rest) have the meaning and the defaults of the
    config keys of the same name; :meth:`for_config` takes them from a
    run's config, so the check starts from the carving's settings and can
    then differ from them (another metric, another period).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: Literal["sun_hours", "solar_energy", "useful_solar_energy", "sky_component", "cooling_sky", "sky_view"]
    epw_path: Optional[str] = None
    start_month: Optional[int] = Field(None, ge=1, le=12)
    start_day: Optional[int] = Field(None, ge=1, le=31)
    start_hour: Optional[int] = Field(None, ge=0, le=23)
    end_month: Optional[int] = Field(None, ge=1, le=12)
    end_day: Optional[int] = Field(None, ge=1, le=31)
    end_hour: Optional[int] = Field(None, ge=0, le=23)
    sun_steps_per_hour: int = Field(1, description="sun_hours: sun positions per hour (a Ladybug timestep)")
    time_basis: Literal["standard", "daylight_saving", "solar"] = "standard"
    min_altitude: float = Field(5.0, ge=0, le=90, description="sun_hours: lowest sun altitude counted (°)")
    north_deg: float = Field(0.0, ge=0.0, lt=360.0)
    balance_temperature: float = 15.0
    balance_offset: float = Field(2.0, ge=0.0)
    include_harm: bool = False
    simulated_weights_path: Optional[str] = None
    dew_point_celsius: float = 14.0
    bliss_k: float = Field(1.8, gt=0)
    sky_density: Literal["tregenza"] = Field("tregenza", description="Sky subdivision: Tregenza's 145 patches")
    rays_per_patch: Literal[1, 4, 9, 16] = Field(
        4, description="Rays traced to each sky patch (1 = the patch centre), as the config's rays_per_patch")
    sample_spacing: float = Field(0.5, gt=0.0, description="Test points every this many meters on the test surfaces")
    origin_offset: float = Field(0.01, ge=0.0, description="Ray origins move this far along the test normal (m)")
    ray_length: float = Field(3000.0, gt=0.0)

    @field_validator("sun_steps_per_hour")
    @classmethod
    def _ladybug_timestep(cls, value: int) -> int:
        allowed = (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60)
        if value not in allowed:
            raise ValueError(f"sun_steps_per_hour must be one of {allowed} (Ladybug timesteps)")
        return value

    @model_validator(mode="after")
    def _metric_inputs(self) -> "CheckSettings":
        spec = CHECK_METRICS[self.metric]
        if spec.needs_epw and not self.epw_path:
            raise ValueError(f"the check metric '{self.metric}' needs a weather file (epw_path)")
        if spec.needs_period:
            missing = [name for name in _PERIOD_FIELDS if getattr(self, name) is None]
            if missing:
                raise ValueError(f"the check metric '{self.metric}' needs the analysis period: {', '.join(missing)}")
        if self.time_basis != "standard" and self.metric in ("solar_energy", "useful_solar_energy"):
            raise ValueError(
                f"time_basis '{self.time_basis}' is only valid for sun hours: the weather file's hourly "
                f"records are in local standard time")
        return self

    @property
    def spec(self) -> CheckMetric:
        return CHECK_METRICS[self.metric]

    @classmethod
    def for_config(cls, config, metric: Optional[str] = None, **changes) -> "CheckSettings":
        """The check settings of a run's *config* (a UserConfig or any object with its attributes).

        *metric* defaults to the mode's (:data:`DEFAULT_CHECK_METRIC`).  The
        period is the config's when it has one, else the starting period of
        the mode the metric belongs to (sun hours: 21 December, 10 to 14 h;
        the solar energies: the whole year or the heating season).  The
        sample spacing is the analysis's (``grid_step``, or half the voxel
        size when unset), so the check samples the points the carving did.  The
        check samples the sun once an hour unless *changes* say otherwise:
        the config's ``sun_steps_per_hour`` is the carving's and is not
        copied.  *changes* override any field.
        """
        metric = metric or DEFAULT_CHECK_METRIC[config.mode]
        spec = CHECK_METRICS[metric]
        values = {"metric": metric}
        for name in cls.model_fields:
            if name not in ("metric", "sun_steps_per_hour") and hasattr(config, name):
                values[name] = getattr(config, name)
        if spec.needs_period and any(values.get(name) is None for name in _PERIOD_FIELDS):
            starting = MODES[spec.period_from_mode].starting_values
            values.update({name: starting[name] for name in _PERIOD_FIELDS})
        values["sample_spacing"] = resolve_grid_step(getattr(config, "grid_step", None), config.voxel_size)
        if metric != "sun_hours":
            values["time_basis"] = "standard"
        values.update(changes)
        return build_check_settings({name: value for name, value in values.items() if name in cls.model_fields})


def settings_digest(settings: CheckSettings) -> str:
    """The sha256 of the settings' JSON (sorted keys) without the weather file's path, which a result records apart (with its
    size and time), so moving the project's folder leaves the digest as it was."""
    values = settings.model_dump(exclude={"epw_path"})
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode("utf-8")).hexdigest()


def build_check_settings(values: Mapping[str, object]) -> CheckSettings:
    """Validate *values* into CheckSettings; raises ConfigError with one ConfigFieldError per problem, as
    ``load_config.build_config`` does for a config."""
    try:
        return CheckSettings(**dict(values))
    except ValidationError as exc:
        field_errors = [ConfigFieldError(".".join(map(str, error["loc"])) or None, error["msg"].removeprefix("Value error, "))
                        for error in exc.errors()]
        lines = [f"{error.field}: {error.message}" if error.field else error.message for error in field_errors]
        raise ConfigError("Check settings are not valid:\n  " + "\n  ".join(lines), field_errors) from exc


def metrics_available(mode: str, has_weather_file: bool) -> list[str]:
    """The check metrics a project in *mode* can show, the mode's default first."""
    default = DEFAULT_CHECK_METRIC[mode]
    names = [default] + [name for name in CHECK_METRICS if name != default]
    return [name for name in names if has_weather_file or not CHECK_METRICS[name].needs_epw]
