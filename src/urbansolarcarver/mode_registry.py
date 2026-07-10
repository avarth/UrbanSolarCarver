"""Single source of truth for carving-mode metadata.

Every mode-specific branch in the codebase (validation, weight dispatch,
score-kind routing, CLI parameter filtering, diagnostics) should derive
its decisions from this registry instead of hardcoding mode names.

To add a 7th mode, define its ModeSpec here — the derived sets propagate
automatically to all consumers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Literal, Set


@dataclass(frozen=True)
class ModeSpec:
    """Declarative metadata for a single carving mode."""

    name: str
    needs_epw: bool
    needs_period: bool
    score_kind: Literal["weighted_sum", "violation_count"]
    weight_unit: str
    extra_params: FrozenSet[str] = field(default_factory=frozenset)
    experimental: bool = False


_PERIOD_FIELDS = frozenset({
    "start_month", "start_day", "start_hour",
    "end_month", "end_day", "end_hour",
})

_EPW_AND_PERIOD = frozenset({"epw_path"}) | _PERIOD_FIELDS

MODES: Dict[str, ModeSpec] = {
    "time-based": ModeSpec(
        name="time-based",
        needs_epw=True,
        needs_period=True,
        score_kind="violation_count",
        weight_unit="hours",
        extra_params=_EPW_AND_PERIOD | {"min_altitude"},
    ),
    "irradiance": ModeSpec(
        name="irradiance",
        needs_epw=True,
        needs_period=True,
        score_kind="weighted_sum",
        weight_unit="Wh/m²",
        extra_params=_EPW_AND_PERIOD | {"min_altitude"},
    ),
    "benefit": ModeSpec(
        name="benefit",
        needs_epw=True,
        needs_period=True,
        score_kind="weighted_sum",
        weight_unit="Wh/m² (heating benefit)",
        extra_params=_EPW_AND_PERIOD | {"min_altitude",
                                        "balance_temperature", "balance_offset"},
    ),
    "daylight": ModeSpec(
        name="daylight",
        needs_epw=False,
        needs_period=False,
        score_kind="weighted_sum",
        weight_unit="CIE overcast sky obstruction score (dimensionless)",
        extra_params=frozenset(),
    ),
    "tilted_plane": ModeSpec(
        name="tilted_plane",
        needs_epw=False,
        needs_period=False,
        score_kind="violation_count",
        weight_unit="intersections",
        extra_params=frozenset({"tilted_plane_angle_deg"}),
    ),
    "radiative_cooling": ModeSpec(
        name="radiative_cooling",
        needs_epw=True,
        needs_period=True,
        score_kind="weighted_sum",
        weight_unit="W/m² (cooling potential)",
        extra_params=_EPW_AND_PERIOD | {"dew_point_celsius", "bliss_k",
                                        "min_sky_elevation_deg"},
        experimental=True,
    ),
}

# ---- Derived convenience sets (auto-generated from MODES) ----
ALL_MODE_NAMES: Set[str] = set(MODES)
EXPERIMENTAL_MODES: Set[str] = {k for k, v in MODES.items() if v.experimental}
MODES_NEEDING_EPW: Set[str] = {k for k, v in MODES.items() if v.needs_epw}
MODES_NEEDING_PERIOD: Set[str] = {k for k, v in MODES.items() if v.needs_period}
