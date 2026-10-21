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
from types import MappingProxyType
from typing import Dict, FrozenSet, Literal, Mapping, Set


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
        "weighted_sum": voxel scores are sums of sky-patch weights, each
        times the area its sample point stands for (grid_step²).
        "violation_count": voxel scores come from ray hit counts
        (time-based rescales them to m²·h).
    weight_unit : str
        Unit of the sky-patch weights, for their plots and the run summary.
    score_unit : str
        Unit of a voxel's score, and so of a numeric threshold: the score
        histograms, the run summary and the browser UI show it.  Written
        into the preprocessing manifest, so a reader can tell scores of an
        earlier scale from today's.
    extra_params : frozenset of str
        Mode-specific config fields this mode reads.  Config validation
        warns when a mode-specific field of another mode is set, and the
        CLI ``schema`` command filters parameters by mode with it.
    experimental : bool
        Config validation warns that the mode is experimental.
    description : str
        One-paragraph summary shown by the Grasshopper mode component.
    starting_values : mapping of str to object
        Values that differ from the schema defaults and fill a new config
        for this mode (``configs/config_<mode>.yaml`` carries the same
        values).  Empty when the schema defaults already fit.
    """

    name: str
    needs_epw: bool
    needs_period: bool
    score_kind: Literal["weighted_sum", "violation_count"]
    weight_unit: str
    score_unit: str
    extra_params: FrozenSet[str] = field(default_factory=frozenset)
    experimental: bool = False
    description: str = ""
    starting_values: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self):
        # A read-only copy: the registry is shared by every caller.
        object.__setattr__(self, "starting_values", MappingProxyType(dict(self.starting_values)))


_PERIOD_FIELDS = frozenset({
    "start_month", "start_day", "start_hour",
    "end_month", "end_day", "end_hour",
})

_EPW_AND_PERIOD = frozenset({"epw_path"}) | _PERIOD_FIELDS


def _period_values(start_month, start_day, start_hour, end_month, end_day, end_hour):
    """The six analysis-period fields as a starting-values mapping."""
    return {
        "start_month": start_month, "start_day": start_day, "start_hour": start_hour,
        "end_month": end_month, "end_day": end_day, "end_hour": end_hour,
    }


MODES: Dict[str, ModeSpec] = {
    "time-based": ModeSpec(
        name="time-based",
        needs_epw=True,
        needs_period=True,
        score_kind="violation_count",
        weight_unit="none (sun positions, no sky patches)",
        score_unit="m²·h",
        extra_params=_EPW_AND_PERIOD | {"min_altitude", "sun_steps_per_hour", "time_basis"},
        description=(
            "Classical solar envelope: traces actual sun-position rays for the "
            "selected hours of year and carves any voxel that shades a test "
            "point during those hours. Requires EPW + analysis period."
        ),
        starting_values=_period_values(12, 21, 10, 12, 21, 14),
    ),
    "irradiance": ModeSpec(
        name="irradiance",
        needs_epw=True,
        needs_period=True,
        score_kind="weighted_sum",
        weight_unit="kWh/m²",
        score_unit="kWh",
        extra_params=_EPW_AND_PERIOD,
        description=(
            "Cumulative solar irradiation. Patches weighted by direct + diffuse "
            "radiation from EPW (kWh/m²); a voxel's score is the solar energy it "
            "blocks from the test surfaces over the period (kWh). Requires EPW + "
            "analysis period."
        ),
        starting_values=_period_values(1, 1, 0, 12, 31, 23),
    ),
    "benefit": ModeSpec(
        name="benefit",
        needs_epw=True,
        needs_period=True,
        score_kind="weighted_sum",
        weight_unit="kWh/m² (heating benefit)",
        score_unit="kWh",
        extra_params=_EPW_AND_PERIOD | {"balance_temperature",
                                        "balance_offset", "include_harm",
                                        "simulated_weights_path"},
        description=(
            "Net heating benefit. Solar gain weighted by outdoor temperature "
            "relative to a balance point (simple weights), or by an ISO 13790 "
            "5R1C building simulation via USC_SimulateWeights (simulated "
            "weights); a voxel's score is the heating-useful solar energy it "
            "blocks (kWh). Requires EPW + analysis period; Benefit Params "
            "optional."
        ),
        starting_values=_period_values(10, 15, 7, 4, 15, 19),
    ),
    "daylight": ModeSpec(
        name="daylight",
        needs_epw=False,
        needs_period=False,
        score_kind="weighted_sum",
        weight_unit="share of the CIE overcast sky (sums to 1)",
        score_unit="m²",
        extra_params=frozenset(),
        description=(
            "CIE overcast sky obstruction. A voxel's score is the overcast sky it "
            "hides from the test surfaces, in m² of fully hidden sky. "
            "Geometry-only model: no weather data needed. Good for daylight "
            "access studies."
        ),
    ),
    "radiative_cooling": ModeSpec(
        name="radiative_cooling",
        needs_epw=False,
        needs_period=False,
        score_kind="weighted_sum",
        weight_unit="share of the sky's cooling potential (sums to 1)",
        score_unit="m²",
        extra_params=frozenset({"dew_point_celsius", "bliss_k", "min_sky_elevation_deg"}),
        experimental=True,
        description=(
            "Long-wave radiative cooling potential. Patches weighted by sky "
            "temperature depression from a dew point (no EPW needed); a voxel's "
            "score is the cooling sky it hides, in m² of fully hidden sky. "
            "[Experimental]"
        ),
        starting_values={"carve_fraction": 0.35},
    ),
    "tilted_plane": ModeSpec(
        name="tilted_plane",
        needs_epw=False,
        needs_period=False,
        score_kind="violation_count",
        weight_unit="none (plane rays, no sky patches)",
        score_unit="rays",
        extra_params=frozenset({"tilted_plane_angle_deg"}),
        description=(
            "Geometric daylight envelope sweep. Carves every voxel above a tilted "
            "plane at user-defined angles. Not a weighted evaluation: it "
            "produces a binary mask. Requires Tilted Plane params."
        ),
        starting_values={"tilted_plane_angle_deg": 45.0},
    ),
}

# Alternative spellings accepted for a mode name (after strip and lower).
MODE_ALIASES: Dict[str, str] = {
    "timebased": "time-based", "time_based": "time-based",
    "tiltedplane": "tilted_plane", "tilted-plane": "tilted_plane",
    "radiativecooling": "radiative_cooling", "radiative-cooling": "radiative_cooling",
}


def canonical_mode_name(name: str) -> str:
    """The mode name the config schema accepts for *name*.

    Strips and lower-cases *name*, then maps an alternative spelling to its
    canonical form.  An unknown name comes back stripped and lower-cased.
    """
    text = str(name).strip().lower()
    return MODE_ALIASES.get(text, text)


# ---- Sets derived from MODES ----
ALL_MODE_NAMES: Set[str] = set(MODES)
EXPERIMENTAL_MODES: Set[str] = {k for k, v in MODES.items() if v.experimental}
MODES_NEEDING_EPW: Set[str] = {k for k, v in MODES.items() if v.needs_epw}
MODES_NEEDING_PERIOD: Set[str] = {k for k, v in MODES.items() if v.needs_period}
