"""Carving-mode metadata, defined in one place.

Config validation, score-kind routing, CLI parameter filtering and
diagnostics read their mode-specific decisions from this registry instead
of hardcoding mode names.  Two places still name modes directly: a new
weighted-sum mode needs a branch in ``scoring.get_weights``, and a new
violation-count mode needs a carver in
``api_core.preprocessing._compute_raw_scores``.

To add a mode, define its ModeSpec in ``MODES``; the derived sets at the
bottom of this file update automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Literal, Set


@dataclass(frozen=True)
class ModeSpec:
    """Metadata for a single carving mode.

    Attributes
    ----------
    name : str
        Mode name as written in the config.
    needs_epw : bool
        The mode reads an EPW weather file.
    needs_period : bool
        The mode uses the analysis period (start/end month, day, hour).
    score_kind : {"weighted_sum", "violation_count"}
        "weighted_sum": voxel scores are sums of sky-patch weights.
        "violation_count": voxel scores come from ray hit counts
        (time-based rescales them to m²·h).
    weight_unit : str
        Unit label for scores and weights in plots and the run summary.
    extra_params : frozenset of str
        Mode-specific config fields this mode reads.  Config validation
        warns when a mode-specific field of another mode is set, and the
        CLI ``schema`` command filters parameters by mode with it.
    experimental : bool
        Config validation warns that the mode is experimental.
    """

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
        weight_unit="m²·h (shaded test surface x duration)",
        extra_params=_EPW_AND_PERIOD | {"min_altitude", "sun_steps_per_hour"},
    ),
    "irradiance": ModeSpec(
        name="irradiance",
        needs_epw=True,
        needs_period=True,
        score_kind="weighted_sum",
        weight_unit="kWh/m²",
        extra_params=_EPW_AND_PERIOD,
    ),
    "benefit": ModeSpec(
        name="benefit",
        needs_epw=True,
        needs_period=True,
        score_kind="weighted_sum",
        weight_unit="kWh/m² (heating benefit)",
        extra_params=_EPW_AND_PERIOD | {"balance_temperature",
                                        "balance_offset", "include_harm",
                                        "simulated_weights_path"},
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
        needs_epw=False,
        needs_period=False,
        score_kind="weighted_sum",
        weight_unit="cooling potential fraction (dimensionless)",
        extra_params=frozenset({"dew_point_celsius", "bliss_k", "min_sky_elevation_deg"}),
        experimental=True,
    ),
}

# ---- Sets derived from MODES ----
ALL_MODE_NAMES: Set[str] = set(MODES)
EXPERIMENTAL_MODES: Set[str] = {k for k, v in MODES.items() if v.experimental}
MODES_NEEDING_EPW: Set[str] = {k for k, v in MODES.items() if v.needs_epw}
MODES_NEEDING_PERIOD: Set[str] = {k for k, v in MODES.items() if v.needs_period}
