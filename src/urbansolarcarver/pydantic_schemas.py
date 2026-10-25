"""Pydantic schemas for YAML configuration validation and stage manifests.

Defines :class:`UserConfig` (the pipeline configuration model, imported
elsewhere as ``user_config``), :class:`ThresholdSpec` (the normalized
threshold setting), the four stage manifest schemas
(:class:`PreprocessingManifest`, :class:`ThresholdingManifest`,
:class:`ExportingManifest`, :class:`MassingManifest`) and the
project-specific warning class :class:`UrbanSolarCarverWarning`.

The config schemas use ``extra='forbid'`` so that typos in YAML keys are
caught at load time rather than silently ignored. The manifest schemas use
Pydantic's default and ignore unknown keys.
"""
from __future__ import annotations

import calendar
import os
from typing import Annotated, Optional, Union, List, Tuple, Literal
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator
from .errors import UrbanSolarCarverWarning  # noqa: F401 (re-exported)
from .run_context import report_issue
from .mode_registry import (
    ALL_MODE_NAMES, EXPERIMENTAL_MODES, MODES, MODES_NEEDING_EPW, MODES_NEEDING_PERIOD,
)

# Settings that only some modes read (each mode lists its own in the registry).
_MODE_SPECIFIC_FIELDS = frozenset().union(*(spec.extra_params for spec in MODES.values()))


# ---------- Pydantic v2 JSON helpers (public) ----------
def schema_from_json(cls, text: str):
    """Deserialize a JSON string into a Pydantic model instance."""
    return cls.model_validate_json(text)

def schema_to_json(model: BaseModel, *, indent: int = 2) -> str:
    """Serialize a Pydantic model to a JSON string."""
    return model.model_dump_json(indent=indent)

# ---------- Threshold specification ----------
class ThresholdSpec(BaseModel):
    """Canonical thresholding strategy: how per-voxel scores become a mask.

    Every accepted config spelling of ``threshold`` (a bare number, a
    strategy name, or a mapping) is normalized into this one shape at load
    time, so downstream stages never re-interpret raw user input.

    Methods
    -------
    * ``carve_fraction``: carve the highest-scoring voxels that together
        hold ``value`` (0-1) of the total score mass.
    * ``headtail``: head/tail breaks (Jiang 2013); takes no value.
    * ``cutoff``: carve voxels scoring strictly above ``value``; for
        time-based this is the tolerated shading in m²·h.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["carve_fraction", "headtail", "cutoff"]
    value: Optional[float] = None

    @model_validator(mode="after")
    def _check_value(self) -> "ThresholdSpec":
        if self.method == "cutoff":
            if self.value is None:
                raise ValueError(
                    "threshold method 'cutoff' requires a value "
                    "(raw-score cutoff, >= 0)"
                )
            if self.value < 0:
                raise ValueError("cutoff threshold must be >= 0")
        elif self.method == "carve_fraction":
            if self.value is not None and not (0.0 <= self.value <= 1.0):
                raise ValueError("carve_fraction threshold value must be in [0, 1]")
        elif self.method == "headtail" and self.value is not None:
            raise ValueError("threshold method 'headtail' takes no value")
        return self

    def __str__(self) -> str:
        return self.method if self.value is None else f"{self.method}={self.value:g}"


def _normalize_threshold(v):
    """Accept threshold shorthands and return the canonical form.

    * ``None``: left as is; :func:`resolve_threshold` gives the mode default.
    * number: ``{method: cutoff, value: n}``. Booleans are rejected.
    * ``'headtail'`` / ``'carve_fraction'``: ``{method: <name>}``.
    * mapping or :class:`ThresholdSpec`: passed on to :class:`ThresholdSpec`
      validation unchanged.
    """
    if v is None or isinstance(v, ThresholdSpec):
        return v
    if isinstance(v, bool):
        raise ValueError("threshold cannot be a boolean")
    if isinstance(v, (int, float)):
        return {"method": "cutoff", "value": float(v)}
    if isinstance(v, str):
        key = v.strip().lower()
        if key == "numeric":
            raise ValueError(
                "threshold='numeric' requires an explicit number: set "
                "threshold to the raw-score cutoff itself (e.g. threshold: 0.35)."
            )
        if key in ("headtail", "carve_fraction"):
            return {"method": key}
        raise ValueError(
            "threshold must be a number (raw-score cutoff), 'headtail', "
            "'carve_fraction', or a mapping like {method: carve_fraction, value: 0.7}"
        )
    return v


def threshold_reads_carve_fraction(threshold) -> bool:
    """Whether a ``threshold``, in any spelling the config accepts, takes its value from ``carve_fraction``.

    It does when unset (in a weighted mode) or when it names the carve_fraction
    method without a value. A spelling the schema refuses reads nothing here;
    validation reports it.
    """
    try:
        spec = _normalize_threshold(threshold)
    except ValueError:
        return False
    if spec is None:
        return True
    if isinstance(spec, ThresholdSpec):
        return spec.method == "carve_fraction" and spec.value is None
    return isinstance(spec, dict) and spec.get("method") == "carve_fraction" and spec.get("value") is None


def resolve_threshold(mode: str, threshold: Optional[ThresholdSpec],
                      carve_fraction: float) -> ThresholdSpec:
    """The complete thresholding strategy for *mode*.

    *threshold* is the config's field as written: None takes the mode
    default (carve_fraction with the *carve_fraction* value for the
    weighted modes, cutoff 0 for the violation-count modes), and
    ``carve_fraction`` without a value takes *carve_fraction*.  Raises
    ValueError for a method the mode cannot use: violation-count scores
    take only a cutoff, and tilted_plane only cutoff 0.
    """
    if MODES[mode].score_kind == "violation_count":
        spec = threshold if threshold is not None else ThresholdSpec(method="cutoff", value=0.0)
        if spec.method != "cutoff":
            raise ValueError(
                f"threshold method '{spec.method}' is not valid for mode "
                f"'{mode}': its scores count blocked rays instead of "
                f"weighting sky patches. Use a non-negative number (for "
                f"time-based, the tolerated shading in m²·h; 0 = none) or "
                f"leave threshold unset."
            )
        if mode == "tilted_plane" and spec.value != 0.0:
            # tilted_plane is binary: a voxel either protrudes above a
            # plane or it does not, so a tolerance has no meaning.
            raise ValueError(
                "tilted_plane mode is binary: threshold must be unset or 0. "
                "A voxel either protrudes above the daylight plane (culled) "
                "or it does not (kept)."
            )
        return spec
    if threshold is None or (threshold.method == "carve_fraction" and threshold.value is None):
        return ThresholdSpec(method="carve_fraction", value=carve_fraction)
    return threshold


def resolve_max_slope_deg(mode: str, max_slope_deg: Optional[float]) -> Optional[float]:
    """The slope limit thresholding applies for *mode*, or None when it is off.

    An explicit *max_slope_deg* applies as given (90 = off).  Unset, it is 75
    degrees for the weighted modes, whose per-voxel score cutoffs can leave
    cliffs and spires, and off for the violation-count modes (time-based,
    tilted_plane), whose results follow the rays exactly.
    """
    if max_slope_deg is not None:
        return None if max_slope_deg >= 90.0 else float(max_slope_deg)
    return 75.0 if MODES[mode].score_kind == "weighted_sum" else None


# An unset grid_step samples the test surfaces at this share of the voxel size.
GRID_STEP_PER_VOXEL_SIZE_WHEN_UNSET = 0.5


def resolve_grid_step(grid_step: Optional[float], voxel_size: float) -> float:
    """The sample spacing on the test surfaces, in meters: *grid_step* as given, or half the voxel size when it is unset.

    Measured on the district example (Solar usefulness, 1 m voxels), half the voxel size keeps the kept voxels within
    about 1 % of a 0.25 m reference at about twice the time of a spacing of one voxel (2 %).
    """
    return float(grid_step) if grid_step is not None else GRID_STEP_PER_VOXEL_SIZE_WHEN_UNSET * float(voxel_size)


# Keys of an analysis_period mapping: Ladybug's AnalysisPeriod.to_dict() keys
# map onto the six flat period fields; plain start_*/end_* spellings are
# accepted too. Ladybug's other keys (type, timestep, is_leap_year) are ignored.
_PERIOD_KEY_ALIASES = {
    "st_month": "start_month", "st_day": "start_day", "st_hour": "start_hour",
    "start_month": "start_month", "start_day": "start_day", "start_hour": "start_hour",
    "end_month": "end_month", "end_day": "end_day", "end_hour": "end_hour",
}
_PERIOD_IGNORED_KEYS = {"type", "timestep", "is_leap_year"}


def expand_analysis_period(data):
    """Expand an ``analysis_period`` mapping into the six flat period fields.

    Canonical form uses Ladybug's ``AnalysisPeriod.to_dict()`` keys
    (``st_month`` ... ``end_hour``), so a Ladybug period can be pasted or
    passed directly; ``start_month``-style keys work as well.  Returns a new
    dict. Raises ValueError if ``analysis_period`` is not a mapping, has an
    unknown key, or disagrees with a flat period field in the same dict.
    """
    if not isinstance(data, dict) or "analysis_period" not in data:
        return data
    data = dict(data)
    period = data.pop("analysis_period")
    if period is None:
        return data
    if not isinstance(period, dict):
        raise ValueError(
            "analysis_period must be a mapping, e.g. "
            "{st_month: 10, st_day: 15, st_hour: 7, "
            "end_month: 4, end_day: 15, end_hour: 19} "
            "(ladybug AnalysisPeriod.to_dict() works directly)"
        )
    for key, raw in period.items():
        if key in _PERIOD_IGNORED_KEYS:
            continue
        target = _PERIOD_KEY_ALIASES.get(key)
        if target is None:
            raise ValueError(
                f"analysis_period: unknown key '{key}'; expected "
                f"st_month/st_day/st_hour/end_month/end_day/end_hour "
                f"(or start_* spellings)"
            )
        if target in data and data[target] != raw:
            raise ValueError(
                f"analysis_period.{key}={raw!r} conflicts with top-level "
                f"{target}={data[target]!r}; specify the period once"
            )
        data[target] = raw
    return data


# ---------- YAML config schema ----------
class UserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _expand_analysis_period(cls, data):
        return expand_analysis_period(data)

    @model_validator(mode="before")
    @classmethod
    def _drop_removed_settings(cls, data):
        """Drop a setting that was removed, with a warning, so configs that still set it load.

        score_rule chose between summed and cost-weighted scores; cost-weighted scoring was removed before a release,
        but configs written meanwhile (the browser UI stored ``score_rule: summed``) may hold it. Scores are summed.
        """
        if isinstance(data, dict) and "score_rule" in data:
            data = {key: value for key, value in data.items() if key != "score_rule"}
            report_issue(
                "setting_removed",
                "score_rule was removed: scores are summed (each blocked ray adds its weight to every voxel it "
                "crosses); the setting is ignored",
            )
        return data

    # file paths
    max_volume_path: str = Field(..., description="Path to the maximum volume mesh (PLY)")
    test_surface_path: str = Field(..., description="Path to the insolation sampling surface mesh (PLY)")
    context_path: Optional[str] = Field(
        None,
        description="Path to a mesh of the existing surroundings that stay (buildings, large trees): it blocks rays, and "
                    "every voxel column of the maximum volume it overlaps is removed. Optional")
    terrain_path: Optional[str] = Field(
        None,
        description="Path to a terrain mesh (an open sheet is fine): it blocks rays, and the voxels below the ground are "
                    "removed. Optional")
    context_blocks_rays: bool = Field(
        True,
        description="Whether rays from the test surfaces that hit the context or the terrain are dropped before scoring "
                    "(ray-based modes). Off: the context and terrain still remove their voxels and count as solid, but "
                    "block no ray, to compare with the carving that ignores them")
    epw_path: Optional[str] = Field(None, description="Path to EPW weather file (required for time-based, irradiance and benefit)")
    out_dir: str = Field(..., description="Output directory for carved meshes and diagnostics")
    final_mesh_format: str = Field(
        "ply",
        description="Extension for the envelope mesh and the massing plates (massing writes plates.obj as well). One of {'ply','obj','stl','glb'}",
        pattern=r"^(ply|obj|stl|glb)$",
    )

    # analysis period (required for time-based, irradiance and benefit; unused
    # by the other modes). Can also be given as one `analysis_period:` mapping
    # with Ladybug AnalysisPeriod.to_dict() keys; see expand_analysis_period.
    start_month: Optional[int] = Field(None, ge=1, le=12, description="Start month (1-12)")
    start_day:   Optional[int] = Field(None, ge=1, le=31, description="Start day of month (1-31)")
    start_hour:  Optional[int] = Field(None, ge=0, le=23, description="Start hour of day (0-23)")
    end_month:   Optional[int] = Field(None, ge=1, le=12, description="End month (1-12)")
    end_day:     Optional[int] = Field(None, ge=1, le=31, description="End day of month (1-31)")
    end_hour:    Optional[int] = Field(None, ge=0, le=23, description="End hour of day (0-23)")

    # carving mode
    mode: str = Field(
        'time-based',
        description="Carving mode: time-based, irradiance, benefit, daylight, tilted_plane, or radiative_cooling [experimental]"
    )

    # radiative cooling options
    dew_point_celsius: float = Field(14.0, description="Dew-point temperature (°C) used to estimate sky emissivity in radiative_cooling mode")
    bliss_k: float = Field(1.8, gt=0, description=(
        "Bliss (1961) angular-attenuation constant for radiative_cooling. "
        "A physical constant (atmospheric diffusivity factor, ~1.5-2.0); "
        "leave at 1.8 unless you have a reason not to."
    ))
    min_sky_elevation_deg: float = Field(
        0.0, ge=0.0, le=85.0,
        description=(
            "radiative_cooling only: lower edge (degrees above the horizon) of "
            "the protected sky. Sky patches below this elevation are excluded "
            "from the cooling weights (the rest are renormalized), so only the "
            "dome above the cutoff is protected, similar to obstruction-angle "
            "rules in daylight codes. It shapes how steeply the envelope may "
            "rise around protected surfaces. 0 (default) = full hemisphere "
            "(pure physical model)."
        ),
    )

    # sky model parameters
    north_deg: float = Field(0.0, ge=0.0, lt=360.0, description="North direction in degrees clockwise from the +Y axis (0 = +Y points north)")

    # grid & ray parameters
    voxel_size:    float = Field(1.0, ge=0.01, le=100.0, description="Voxel edge length (m), 0.01–100")
    grid_step:     Optional[float] = Field(
        None, gt=0,
        description="Surface sampling spacing (m), at most voxel_size. None (default): half the voxel size.",
    )
    edge_taper:    float = Field(
        0.0, ge=0.0,
        description=(
            "Design-constraint taper (meters) on test-surface sample weights: "
            "a point closer than this to its component's boundary counts "
            "proportionally less (linear ramp from 0 at the edge to full "
            "weight at edge_taper). Declares the perimeter strip as outside "
            "the protected program, so edge/corner samples don't force "
            "carving of the directly adjacent volume. 0 (default) = off. "
            "Weighted sky-patch modes only; ignored with a warning by "
            "time-based and tilted_plane. Requires planar test surfaces "
            "(already enforced by sampling)."
        ),
    )
    sun_steps_per_hour: int = Field(
        12,
        description=(
            "time-based only: sun positions sampled per hour of the analysis "
            "period (Ladybug timestep: 1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60). "
            "The sun moves ~15° of azimuth per hour, so sparse sampling leaves "
            "gaps between ray sheets where mass survives while still shading "
            "the protected surface between samples. 12 (5 min) closes the gaps "
            "for 1 m voxels at ~40 m; ray count grows linearly with this value. "
            "Scores are divided by this value, so the m²·h scale (and a numeric "
            "threshold) does not depend on it."
        ),
    )
    time_basis: Literal["standard", "daylight_saving", "solar"] = Field(
        "standard",
        description=(
            "time-based only: the clock the analysis period's hours are read in. "
            "'standard' (default): the EPW's local standard time. "
            "'daylight_saving': standard time plus one hour on every date of the "
            "period (summer clock time; a period that crosses the switch date is "
            "one hour off outside summer time). 'solar': true solar time, in which "
            "the sun crosses the meridian (due south at northern mid-latitudes) at "
            "12:00 every day, as solar-fence rules and the Japanese shadow "
            "regulation define their hours. 'daylight_saving' and 'solar' are refused in irradiance and "
            "benefit, whose hourly EPW records are in standard time."
        ),
    )
    ray_length:    float = Field(
        3000.0, gt=0,
        description=(
            "Max ray cast distance (m). A ray stops where it leaves the voxel grid, "
            "so a length beyond the grid costs nothing; the default reaches across "
            "any grid the voxel budget allows at 1 m voxels."
        ),
    )
    rays_per_patch: Literal[1, 4, 9, 16] = Field(
        4,
        description=(
            "Sky-patch modes (irradiance, benefit, daylight, radiative_cooling): rays traced "
            "per Tregenza sky patch from each test point. 1 = one ray to the patch centre. "
            "4 (default), 9 or 16 = that many rays spread over the patch, one at a random "
            "place in each of its 2 × 2, 3 × 3 or 4 × 4 cells, each carrying that share of "
            "the patch weight; the places are drawn from the test point and the patch, so a "
            "run repeats exactly. Patch centres are 12° apart, so far from the test surfaces "
            "one ray per patch leaves voxels between the rays unscored, which shows as bands; "
            "more rays close the gaps. Tracing time grows about in proportion."
        ),
    )
    min_altitude:  float = Field(5.0, ge=0, le=90, description="Minimum sun altitude (°)")
    margin_frac:   float = Field(0.01, ge=0, le=1.0, description="Grid padding on each side, as a fraction of the max volume's largest bounding-box side")
    ray_batch_size: int   = Field(0, ge=0, description="Rays per batch. 0 = auto: sized from free GPU memory, 300000 on CPU")

    # score smoothing (pre-threshold)
    score_smoothing: Optional[float] = Field(
        None, ge=0.0, le=20.0,
        description=(
            "Radius (meters) of the Gaussian blur applied to the score volume before "
            "thresholding; it is used as the Gaussian sigma and averages over occupied "
            "voxels only. Smooths resolution-dependent noise so the carved mesh is cleaner "
            "at fine voxel sizes. "
            "None (default) = auto: 1.1 × voxel_size, recommended for most runs. "
            "0 = disabled (no smoothing). "
            "Positive value = explicit radius in meters (rule of thumb: 1.0–1.2× voxel_size; "
            "above 2× voxel_size features get noticeably rounded). The radius is clipped "
            "to 0.5-8 voxels. "
            "Only affects weighted-score modes (irradiance, benefit, daylight, radiative_cooling). "
            "Violation-count modes (time-based, tilted_plane) are unaffected."
        ),
    )

    # postprocessing
    apply_smoothing: bool  = Field(False, description="If True, mesh with a smoothed signed-distance field and marching cubes instead of voxel cubes")
    min_voxels:      int   = Field(300, gt=0, description="Connected voxel clusters smaller than this are removed before meshing")
    min_face_count:  int   = Field(100, ge=0, description="Mesh fragments with fewer faces than this are removed")
    smooth_iters:    int   = Field(2, ge=0, le=6, description="Taubin polish passes, 0-6 (only with apply_smoothing)")

    # column post-processing
    carve_above: bool = Field(
        True,
        description=(
            "Carve all occupied voxels above the lowest sufficiently-carved region "
            "in each (x, y) column, so the envelope is a buildable height field "
            "(the classical solar-envelope definition) instead of keeping mass that "
            "floats above carved zones. Set False to keep floating mass that casts "
            "no violating shadow. Use carve_above_min_consecutive to control "
            "sensitivity."
        ),
    )
    carve_above_min_consecutive: int = Field(
        1, ge=1,
        description=(
            "Minimum number of consecutive carved voxels in a column before "
            "carve_above activates for that column. Higher values (2-3) prevent stray "
            "single-voxel carvings from triggering aggressive column removal; "
            "shorter runs stay carved but do not trigger."
        ),
    )
    max_slope_deg: Optional[float] = Field(
        None,
        gt=0.0,
        le=90.0,
        description=(
            "Steepest rise (degrees above horizontal) allowed between neighbouring "
            "columns of the kept volume, applied after carve_above. Taller columns are "
            "cut down until they rise at most this steeply above a median-filtered "
            "height map, which turns one-voxel spires and tall cliffs into ramps. It "
            "only ever removes voxels. None (default): 75 for the weighted modes "
            "(irradiance, benefit, daylight, radiative_cooling), off for time-based "
            "and tilted_plane. 90: off. Lower values give gentler ramps and remove "
            "more volume."
        ),
    )

    # massing (floor plates; see docs/massing.md)
    ground_floor_height: float = Field(
        5.0, gt=0.0, description="Massing: height of the ground floor (m)")
    floor_height: float = Field(
        3.0, gt=0.0, description="Massing: height of every floor above the ground floor (m)")
    min_plate_dimension: float = Field(
        3.0, gt=0.0,
        description="Massing: side of the square module floors are built from, and the minimum width of any floor plate (m)")
    plate_tolerance: float = Field(
        0.2, ge=0.0, le=1.0,
        description=(
            "Massing: largest share (0-1) of a module's volume on a floor that may lie "
            "outside the carved envelope. Plates never leave the maximum volume."
        ),
    )
    plate_stacking: Literal["supported", "free"] = Field(
        "supported",
        description=(
            "Massing: 'supported' builds a module on a floor only where it is built on the "
            "floor below; 'free' decides each floor on its own."
        ),
    )

    # thresholding & classification
    threshold: Annotated[Optional[ThresholdSpec], BeforeValidator(_normalize_threshold)] = Field(
        None,
        description=(
            "How to decide which voxels to carve. Canonical form is a mapping "
            "{method: ..., value: ...}; shorthands are accepted and normalized: "
            "'carve_fraction' (recommended): remove a fraction of the obstructing "
            "score mass (value from the carve_fraction parameter unless given). "
            "'headtail': automatic split biased toward removing only the worst "
            "obstructors. Both are for weighted modes only. "
            "A bare number (≥ 0): score cutoff; carve voxels scoring above it "
            "(inspect the score histogram first). It is in the mode's score unit: "
            "for time-based the tolerated shading in m²·h (shaded test-surface area "
            "x duration), for irradiance and benefit the kWh a voxel may block, for "
            "daylight and radiative_cooling the m² of fully hidden sky. "
            "Unset: mode default (carve_fraction for weighted modes, 0 for "
            "violation-count modes). The field keeps what was written (None or a "
            "ThresholdSpec); UserConfig.resolved_threshold() gives the strategy "
            "applied, which thresholding records in its manifest."
        ),
    )
    carve_fraction: float = Field(
        0.7,
        ge=0.0,
        le=1.0,
        description=(
            "How aggressively to carve (0.0-1.0): the fraction of the building's total "
            "obstruction score to remove, not the fraction of voxels removed. Because a few "
            "highly-obstructing voxels dominate the score distribution, 0.7 typically removes "
            "far fewer than 70% of voxels. "
            "0.7 = aggressive (removes the voxels holding 70% of the obstruction score; "
            "taller, slimmer volumes). "
            "0.3 = conservative (removes 30%; bulkier volumes, more floor area). "
            "Used by the carve_fraction threshold method when the threshold gives no value "
            "of its own, which includes the default for weighted modes; set explicitly "
            "where it is not used (headtail, a numeric cutoff, time-based, tilted_plane), "
            "it gives a warning."
        ),
    )
    # benefit parameters
    balance_temperature: float = Field(
        15.0,
        description=(
            "Free-running balance-point temperature (°C) for benefit mode: "
            "solar gains are credited only in hours with outdoor temperature "
            "below balance_temperature - balance_offset. Default 15 follows "
            "Ladybug (typical range: ~12 commercial to ~18 residential; "
            "older, poorly insulated stock can sit higher). Derive "
            "project-specific values with the Honeybee/E+ balance-point "
            "workflow."
        ),
    )
    balance_offset: float = Field(
        2.0, ge=0.0,
        description=(
            "Half the width (°C) of the dead band for benefit mode, which lies "
            "on both sides of balance_temperature: hours colder than "
            "balance_temperature - balance_offset are credited, and with "
            "include_harm hours warmer than balance_temperature + "
            "balance_offset count against the sun; hours inside the band "
            "count neither way. Must be >= 0 (0 = no dead band)."
        ),
    )
    simulated_weights_path: Optional[str] = Field(
        None,
        description=(
            "benefit mode only: path to a simulated_weights.json artifact "
            "(generate with `usc simulate-weights`). When set, the balance-point "
            "hour filter is replaced by the artifact's physics-derived "
            "hourly weights: each hour's radiation is scaled by benefit[t] "
            "before the sky matrix, and with include_harm the harm[t]-"
            "scaled matrix is subtracted (clipped at zero). "
            "balance_temperature and balance_offset are then unused. "
            "None (default) = the built-in balance-point filter."
        ),
    )
    include_harm: bool = Field(
        False,
        description=(
            "benefit mode only, experimental. False (default): weights use "
            "the heating-benefit formula: radiation of cold hours only; warm "
            "hours in the analysis period contribute nothing, so the result "
            "does not depend on how much warm season the period includes "
            "(recommended). True: follow Ladybug's composite radiation-benefit "
            "concept: hot-hour (T > balance + offset) radiation is subtracted "
            "per sky patch and the result clipped at zero. Results then depend "
            "on how much of the warm season the analysis period includes, and "
            "patches whose summer harm exceeds winter benefit drop to zero "
            "weight. Weights never go negative, so the shading value of mass "
            "in summer never protects it from carving."
        ),
    )

    # misc
    diagnostics: bool = Field(
        False,
        description=(
            "Include detailed score statistics (median, std, percentiles) in the "
            "per-stage diagnostics JSON. Basic statistics (count, min, max, mean) "
            "and timings are always written; the detailed set adds sorting passes "
            "over the full score volume, which is slow on large grids."
        ),
    )
    diagnostic_plots: bool = Field(
        False,
        description=(
            "Generate diagnostic plot images (score histogram, sky patch weight/intensity plots, "
            "threshold histogram). When False (default), only JSON diagnostics are written "
            "and matplotlib is not used."
        ),
    )
    device: str = Field('auto', description="Compute device: 'auto', 'cpu', or 'cuda'")

    # tilted_plane parameter
    tilted_plane_angle_deg: Optional[Union[float, List[float]]] = Field(
        None,
        description=(
            "tilted_plane mode: tilt of the limiting plane above the horizontal, in degrees. "
            "Either a single number applied to all test surfaces, or a list of 8 numbers "
            "[N, NE, E, SE, S, SW, W, NW] chosen by the compass direction each test "
            "surface faces (taking north_deg into account)."
        ),
    )

    @field_validator('mode')
    def _validate_mode(cls, v: str) -> str:
        if v not in ALL_MODE_NAMES:
            raise ValueError(f"mode must be one of {sorted(ALL_MODE_NAMES)}")
        if v in EXPERIMENTAL_MODES:
            report_issue(
                "experimental_mode",
                f"Mode '{v}' is experimental and may change or be removed in future versions.",
            )
        return v

    @field_validator('sun_steps_per_hour')
    def _validate_sun_steps(cls, v: int) -> int:
        allowed = (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60)
        if v not in allowed:
            raise ValueError(f"sun_steps_per_hour must be one of {allowed} (Ladybug timesteps)")
        return v

    @field_validator('device')
    def _validate_device(cls, v: str) -> str:
        opts = {'auto', 'cpu', 'cuda'}
        if v not in opts:
            raise ValueError(f"device must be one of {opts}")
        return v

    def effective_max_slope_deg(self) -> Optional[float]:
        """The slope limit thresholding applies, or None when it is off;
        see :func:`resolve_max_slope_deg`."""
        return resolve_max_slope_deg(self.mode, self.max_slope_deg)

    def resolved_threshold(self) -> ThresholdSpec:
        """The thresholding strategy this config applies; see :func:`resolve_threshold`."""
        return resolve_threshold(self.mode, self.threshold, self.carve_fraction)

    @model_validator(mode='after')
    def _check_threshold(self) -> 'UserConfig':
        """Check ``threshold`` against the mode, and warn about an unused
        ``carve_fraction``.

        ``threshold`` keeps the value as written (None = the mode default),
        so a dumped config loads back with the same meaning; the strategy
        is resolved by :meth:`resolved_threshold`.  An explicit
        ``carve_fraction`` that the resolved strategy does not read gives a
        warning.
        """
        spec = self.resolved_threshold()  # raises for a method the mode cannot use
        reads_carve_fraction = threshold_reads_carve_fraction(self.threshold)
        if (spec.method == "carve_fraction" and not reads_carve_fraction
                and "carve_fraction" in self.model_fields_set
                and spec.value != self.carve_fraction):
            report_issue(
                "threshold_value_disagrees",
                f"threshold value {spec.value} and carve_fraction={self.carve_fraction} "
                f"disagree; using the threshold value {spec.value}.",
            )
        elif spec.method != "carve_fraction" and "carve_fraction" in self.model_fields_set:
            report_issue(
                "carve_fraction_unused",
                f"carve_fraction={self.carve_fraction} is unused: mode '{self.mode}' "
                f"thresholds with '{spec}'.",
            )
        return self

    @model_validator(mode='after')
    def _check_mode_requirements(self) -> 'UserConfig':
        """Require the EPW and the analysis period where the mode uses them."""
        if self.mode in MODES_NEEDING_EPW and not self.epw_path:
            raise ValueError(f"mode '{self.mode}' requires epw_path")
        if self.mode in MODES_NEEDING_PERIOD:
            period_fields = {
                'start_month': self.start_month, 'start_day': self.start_day,
                'start_hour': self.start_hour, 'end_month': self.end_month,
                'end_day': self.end_day, 'end_hour': self.end_hour,
            }
            missing = [k for k, v in period_fields.items() if v is None]
            if missing:
                raise ValueError(
                    f"mode '{self.mode}' requires analysis period fields: {', '.join(missing)}"
                )
        return self

    @model_validator(mode='after')
    def _warn_ignored_fields(self) -> 'UserConfig':
        """Warn about mode-specific settings the chosen mode does not use."""
        used = MODES[self.mode].extra_params
        ignored = sorted((self.model_fields_set & _MODE_SPECIFIC_FIELDS) - used)
        if ignored:
            report_issue(
                "settings_unused_by_mode",
                f"mode '{self.mode}' does not use: {', '.join(ignored)} (ignored)",
            )
        return self

    @model_validator(mode='after')
    def _check_time_basis(self) -> 'UserConfig':
        """Refuse a clock other than standard time in a mode whose analysis hours select EPW records.

        The EPW's hourly records are in local standard time, so irradiance and
        benefit cannot read their period in another clock. The modes with no
        analysis period ignore ``time_basis`` with the usual warning.
        """
        if (self.time_basis != "standard" and self.mode in MODES_NEEDING_PERIOD
                and "time_basis" not in MODES[self.mode].extra_params):
            raise ValueError(
                f"time_basis '{self.time_basis}' is only valid for mode 'time-based' (got mode "
                f"'{self.mode}', whose hourly EPW records are in local standard time)"
            )
        return self

    @model_validator(mode='after')
    def _check_simulated_weights_path(self) -> 'UserConfig':
        if self.simulated_weights_path is not None:
            if self.mode != "benefit":
                raise ValueError(
                    "simulated_weights_path is only valid for mode 'benefit' "
                    f"(got mode '{self.mode}')"
                )
            if {"balance_temperature", "balance_offset"} & self.model_fields_set:
                report_issue(
                    "balance_point_unused",
                    "balance_temperature/balance_offset are unused when "
                    "simulated_weights_path is set; the artifact's hourly weights "
                    "replace the balance-point filter.",
                )
        return self

    @model_validator(mode='after')
    def _check_calendar_dates(self) -> 'UserConfig':
        """Validate that month/day combinations are real calendar dates."""
        for prefix in ("start", "end"):
            month = getattr(self, f"{prefix}_month")
            day = getattr(self, f"{prefix}_day")
            if month is not None and day is not None:
                max_day = calendar.monthrange(2001, month)[1]  # non-leap year
                if day > max_day:
                    raise ValueError(
                        f"{prefix}_day={day} is invalid for month {month} "
                        f"(max {max_day} days)"
                    )
        return self

    @model_validator(mode='after')
    def _check_tilted_plane(self) -> 'UserConfig':
        if self.mode == 'tilted_plane':
            spec = self.tilted_plane_angle_deg
            if spec is None:
                raise ValueError("tilted_plane requires tilted_plane_angle_deg as a float or a list of 8 floats")
            if isinstance(spec, (list, tuple)):
                if len(spec) != 8:
                    raise ValueError("tilted_plane_angle_deg must have length 8 [N, NE, E, SE, S, SW, W, NW]")
                try:
                    self.tilted_plane_angle_deg = [float(x) for x in spec]
                except (TypeError, ValueError):
                    raise ValueError("tilted_plane_angle_deg list must contain numeric values")
            elif not isinstance(spec, (int, float)):
                raise ValueError("tilted_plane_angle_deg must be a number or an 8-length list")
        return self

    @model_validator(mode='after')
    def _check_sampling_and_batches(self) -> 'UserConfig':
        if self.grid_step is not None and self.grid_step > self.voxel_size:
            raise ValueError(
                f"grid_step ({self.grid_step:g} m) must be ≤ voxel_size ({self.voxel_size:g} m). "
                "Increase voxel_size or decrease grid_step."
            )
        try:
            safe_max = int(os.environ.get("USC_MAX_RAY_BATCH", "2000000"))
        except ValueError:
            safe_max = 2_000_000
        if self.ray_batch_size > safe_max:
            report_issue(
                "ray_batch_size_clamped",
                f"ray_batch_size={self.ray_batch_size} is too large; clamping to {safe_max}.",
            )
            self.ray_batch_size = safe_max
        return self


# ---------- Stage manifests ----------
# Manifests hold only the fields a downstream stage reads. Provenance and
# statistics go to each stage's diagnostics/diagnostic.json instead.
#
# Every manifest has a ``run_id`` (random, new on every run of that stage);
# a downstream manifest also records the ``run_id`` of the upstream manifest
# it was built from, so a consumer can tell that the upstream was re-run.
# Paths are stored relative to the manifest's own folder with forward
# slashes (the absolute path when no relative one exists).

class PreprocessingManifest(BaseModel):
    """Manifest written by preprocessing, read by thresholding and exporting."""

    run_id: str
    scores_path: str
    scores_kind: Literal["weighted_sum", "violation_count"]
    shape: Tuple[int, int, int]
    origin: Tuple[float, float, float]
    voxel_size: float
    mode: str
    voxel_grid_path: str
    # Absent in the violation-count modes, which have no sky patches.
    patch_weights_path: Optional[str] = None
    sample_point_count: int
    # The sample spacing on the test surfaces the run used (resolve_grid_step); None in manifests written before
    # preprocessing recorded it.
    grid_step: Optional[float] = None
    # The unit of the scores (mode_registry score_unit: "kWh", "m²", "m²·h"); None in manifests written before preprocessing
    # recorded it, when the weighted modes' scores were sums of patch weights without the area of the sample points.
    score_unit: Optional[str] = None
    # The max volume's plan projection in world xy; massing reads it.
    footprint_path: str
    # The max volume's lowest and highest points (world z): massing starts the
    # ground floor at the lowest and ends the floors at or below the highest.
    # None in manifests written before preprocessing recorded them.
    max_volume_lowest_z: Optional[float] = None
    max_volume_highest_z: Optional[float] = None
    # The optional context and terrain meshes the run used; None when absent (and in manifests written before
    # preprocessing recorded them).
    context_path: Optional[str] = None
    terrain_path: Optional[str] = None

class ThresholdingManifest(BaseModel):
    """Manifest written by thresholding, read by exporting and massing."""

    run_id: str
    mask_path: str
    # The values the cutoff is applied to (float32, the grid shape); None in
    # manifests written before thresholding saved them.
    scores_compared_with_cutoff_path: Optional[str] = None
    upstream_manifest: str
    upstream_run_id: str
    # The settings this run applied after resolving the config's "None =
    # auto" values: the threshold strategy (not the score-dependent
    # cutoff), the score smoothing radius in meters (0 = none) and the
    # slope limit (None = off).
    resolved_threshold: ThresholdSpec
    score_smoothing_m: float
    max_slope_deg: Optional[float]
    # The previous criterion's thresholding manifest (relative to this manifest's folder) and run id when this run
    # decided only among the voxels it kept; None for a first or only criterion.
    after_manifest: Optional[str] = None
    after_run_id: Optional[str] = None

class ExportingManifest(BaseModel):
    """Manifest written by exporting."""

    run_id: str
    mesh_path: str
    upstream_manifest: str
    upstream_run_id: str

class MassingManifest(BaseModel):
    """Manifest written by massing."""

    run_id: str
    plates_path: str
    # The plates as OBJ with one named part per plate, written in every run.
    mesh_path: str
    # The plates in final_mesh_format; the same file as mesh_path for OBJ.
    # None in manifests written before massing wrote that format (their only
    # mesh is mesh_path).
    export_mesh_path: Optional[str] = None
    upstream_manifest: str
    upstream_run_id: str
