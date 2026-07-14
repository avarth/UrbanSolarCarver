"""Pydantic schemas for YAML configuration validation and stage manifests.

Defines :class:`user_config` (the main pipeline configuration model),
two stage manifest schemas (:class:`PreprocessingManifest`,
:class:`ThresholdingManifest`), and the project-specific warning class
:class:`UrbanSolarCarverWarning`.

All schemas use ``extra='forbid'`` so that typos in YAML keys are
caught at load time rather than silently ignored.
"""
from __future__ import annotations

import calendar
import os
import warnings
from typing import Annotated, Optional, Union, List, Tuple, Literal
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator
from .mode_registry import ALL_MODE_NAMES, EXPERIMENTAL_MODES, MODES, MODES_NEEDING_EPW


# ---------- Pydantic v2 JSON helpers (public) ----------
def schema_from_json(cls, text: str):
    """Deserialize a JSON string into a Pydantic model instance."""
    return cls.model_validate_json(text)

def schema_to_json(model: BaseModel, *, indent: int = 2) -> str:
    """Serialize a Pydantic model to a JSON string."""
    return model.model_dump_json(indent=indent)

# ---------- Warnings ----------
class UrbanSolarCarverWarning(UserWarning):
    """Non-fatal configuration warning."""

# ---------- Threshold specification ----------
class ThresholdSpec(BaseModel):
    """Canonical thresholding strategy: how per-voxel scores become a mask.

    Every accepted config spelling of ``threshold`` (a bare number, a
    strategy name, or a mapping) is normalized into this one shape at load
    time, so downstream stages never re-interpret raw user input.

    Methods
    -------
    * ``carve_fraction`` — remove voxels accounting for ``value`` of the
        total score mass (0-1).
    * ``headtail`` — head/tail breaks (Jiang 2013); takes no value.
    * ``cutoff`` — carve voxels scoring strictly above ``value``; for the
        violation-count modes this is the tolerated violation count.
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

    * ``None`` — resolved to the mode default later
    * number — ``{method: cutoff, value: n}``
    * ``'headtail'`` / ``'carve_fraction'`` — method name
    * mapping — validated as :class:`ThresholdSpec` directly
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
                "threshold='numeric' requires an explicit number — set "
                "threshold to the raw-score cutoff itself (e.g. threshold: 0.35)."
            )
        if key in ("headtail", "carve_fraction"):
            return {"method": key}
        raise ValueError(
            "threshold must be a number (raw-score cutoff), 'headtail', "
            "'carve_fraction', or a mapping like {method: carve_fraction, value: 0.7}"
        )
    return v


# Ladybug-aligned analysis_period mapping: LB AnalysisPeriod.to_dict() keys
# map onto the six flat period fields; plain start_*/end_* spellings are
# accepted too, and LB's bookkeeping extras are tolerated and ignored.
_PERIOD_KEY_ALIASES = {
    "st_month": "start_month", "st_day": "start_day", "st_hour": "start_hour",
    "start_month": "start_month", "start_day": "start_day", "start_hour": "start_hour",
    "end_month": "end_month", "end_day": "end_day", "end_hour": "end_hour",
}
_PERIOD_IGNORED_KEYS = {"type", "timestep", "is_leap_year"}


# ---------- YAML config schema ----------
class UserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _expand_analysis_period(cls, data):
        """Expand an ``analysis_period`` mapping into the six flat fields.

        Canonical form uses Ladybug's ``AnalysisPeriod.to_dict()`` keys
        (``st_month`` ... ``end_hour``), so a Ladybug period can be pasted
        or passed directly; ``start_month``-style keys work as well.  The
        flat top-level fields remain valid aliases.
        """
        if not isinstance(data, dict) or "analysis_period" not in data:
            return data
        data = dict(data)  # don't mutate the caller's dict
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
                    f"analysis_period: unknown key '{key}' — expected "
                    f"st_month/st_day/st_hour/end_month/end_day/end_hour "
                    f"(or start_* spellings)"
                )
            if target in data and data[target] != raw:
                raise ValueError(
                    f"analysis_period.{key}={raw!r} conflicts with top-level "
                    f"{target}={data[target]!r} — specify the period once"
                )
            data[target] = raw
        return data

    # file paths
    max_volume_path: str = Field(..., description="Path to the maximum volume mesh (PLY)")
    test_surface_path: str = Field(..., description="Path to the insolation sampling surface mesh (PLY)")
    epw_path: Optional[str] = Field(None, description="Path to EPW weather file (required for time-based, irradiance, benefit, radiative_cooling)")
    out_dir: str = Field(..., description="Output directory for carved meshes and diagnostics")
    final_mesh_format: str = Field(
        "ply",
        description="Extension for final mesh. One of {'ply','obj','stl','glb'}",
        pattern=r"^(ply|obj|stl|glb)$",
    )

    # analysis period (required for sun/sky modes, ignored by tilted_plane).
    # Can also be given as one `analysis_period:` mapping with ladybug
    # AnalysisPeriod.to_dict() keys — see _expand_analysis_period above.
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
    dew_point_celsius: float = Field(14.0, description="Night-time dew-point (°C) for radiative_cooling mode")
    bliss_k: float = Field(1.8, gt=0, description=(
        "Bliss (1961) angular-attenuation constant for radiative_cooling. "
        "A physical constant (atmospheric diffusivity factor, ~1.5-2.0) — "
        "leave at 1.8 unless you have a reason not to."
    ))
    min_sky_elevation_deg: float = Field(
        0.0, ge=0.0, le=85.0,
        description=(
            "radiative_cooling only: design-constraint protection cone (degrees). "
            "Sky patches below this elevation are excluded from the cooling "
            "weights (renormalized), declaring that only the dome above the "
            "cutoff is defended — analogous to obstruction-angle rules in "
            "daylight codes. It shapes how steeply the envelope may rise around "
            "protected surfaces. 0 (default) = full hemisphere (pure physical "
            "model)."
        ),
    )

    # sky model parameters
    north_deg: float = Field(0.0, ge=0.0, lt=360.0, description="North direction in degrees clockwise from Y-axis (0 = Y-up is north)")

    # grid & ray parameters
    voxel_size:    float = Field(1.0, ge=0.01, le=100.0, description="Voxel edge length (m), 0.01–100")
    grid_step:     float = Field(1.0, gt=0, description="Surface sampling spacing (m)")
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
    ray_length:    float = Field(300.0, gt=0, description="Max ray cast distance (m)")
    min_altitude:  float = Field(5.0, ge=0, le=90, description="Minimum sun altitude (°)")
    margin_frac:   float = Field(0.01, ge=0, le=1.0, description="Padding fraction around geometry")
    ray_batch_size: int   = Field(0, ge=0, description="Rays per GPU batch. 0 = auto-tune based on available VRAM")

    # score smoothing (pre-threshold)
    score_smoothing: Optional[float] = Field(
        None, ge=0.0, le=20.0,
        description=(
            "Gaussian blur radius (meters) applied to the score volume before thresholding. "
            "Smooths resolution-dependent noise so the carved mesh is cleaner at fine voxel sizes. "
            "None (default) = auto: 1.1 × voxel_size — recommended for most runs. "
            "0 = disabled (no smoothing). "
            "Positive value = explicit radius in meters (rule of thumb: 1.0–1.2× voxel_size; "
            "over-smoothing above 2× voxel_size rounds features excessively). "
            "Only affects weighted-score modes (irradiance, benefit, daylight, radiative_cooling). "
            "Violation-count modes (time-based, tilted_plane) are unaffected."
        ),
    )

    # postprocessing
    apply_smoothing: bool  = Field(False, description="If True, apply SDF smoothing + marching cubes")
    min_voxels:      int   = Field(300, gt=0, description="Minimum voxel cluster size to keep")
    min_face_count:  int   = Field(100, ge=0, description="Minimum faces to keep mesh fragments")
    smooth_iters:    int   = Field(2, ge=0, description="Taubin polish passes (only with apply_smoothing)")

    # column post-processing
    carve_above: bool = Field(
        False,
        description=(
            "If True, carve all occupied voxels above the lowest sufficiently-carved "
            "region in each (x, y) column. Removes structurally implausible floating "
            "mass above already-carved zones. Use carve_above_min_consecutive to "
            "control sensitivity."
        ),
    )
    carve_above_min_consecutive: int = Field(
        1, ge=1,
        description=(
            "Minimum number of consecutive carved (empty) voxels in a column before "
            "carve_above activates for that column. Higher values (2-3) prevent stray "
            "single-voxel carvings from triggering aggressive column removal."
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
            "obstructors. "
            "A bare number (≥ 0): raw-score cutoff — carve voxels scoring above it "
            "(inspect the score histogram first); for time-based/tilted_plane this "
            "is the tolerated violation count. "
            "Unset: mode default (carve_fraction for weighted modes, 0 for "
            "violation-count modes). After validation this field is always a "
            "ThresholdSpec."
        ),
    )
    carve_fraction: float = Field(
        0.7,
        ge=0.0,
        le=1.0,
        description=(
            "How aggressively to carve (0.0-1.0). Controls the fraction of total solar "
            "obstruction to eliminate — NOT the fraction of voxels removed. Because a few "
            "highly-obstructing voxels dominate the score distribution, 0.7 typically removes "
            "far fewer than 70% of voxels. "
            "0.7 = aggressive (protects 70% of solar access, taller/slimmer volumes). "
            "0.3 = conservative (protects 30%, bulkier volumes, more floor area). "
            "Only used when threshold='carve_fraction'."
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
            "Dead-band (°C) below the balance point for benefit mode; hours "
            "warmer than balance_temperature - balance_offset are not "
            "credited. Must be >= 0 (0 = no dead-band)."
        ),
    )
    usefulness_path: Optional[str] = Field(
        None,
        description=(
            "benefit mode only: path to a solar_usefulness.json artifact "
            "(generate with `usc usefulness`). When set, the balance-point "
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
            "benefit mode only, EXPERIMENTAL. False (default): weights use "
            "the documented heating-benefit formula — radiation of cold "
            "hours only; warm hours in the analysis period contribute "
            "nothing (period-stable, recommended). True: reproduce "
            "Ladybug's composite radiation-benefit concept — hot-hour "
            "(T > balance + offset) radiation is subtracted per sky patch "
            "and the result clipped at zero. Results then depend on how "
            "much of the warm season the analysis period includes, and "
            "patches whose summer harm exceeds winter benefit drop to zero "
            "weight (harm never rewards mass: shading value cannot be a "
            "carving force)."
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
            "threshold histogram). When False (default), only JSON diagnostics are written — "
            "no matplotlib overhead."
        ),
    )
    device: str = Field('auto', description="Compute device: 'auto', 'cpu', or 'cuda'")

    # tilted_plane parameter
    tilted_plane_angle_deg: Optional[Union[float, List[float]]] = Field(
        None,
        description=(
            "Plane-method angle specification. Either a single number (deg) applied to all faces, "
            "or a list of 8 numbers [N, NE, E, SE, S, SW, W, NW] in degrees."
        ),
    )

    @field_validator('mode')
    def _validate_mode(cls, v: str) -> str:
        if v not in ALL_MODE_NAMES:
            raise ValueError(f"mode must be one of {sorted(ALL_MODE_NAMES)}")
        if v in EXPERIMENTAL_MODES:
            warnings.warn(
                f"Mode '{v}' is experimental and may change or be removed in future versions.",
                UrbanSolarCarverWarning,
                stacklevel=2,
            )
        return v

    @field_validator('device')
    def _validate_device(cls, v: str) -> str:
        opts = {'auto', 'cpu', 'cuda'}
        if v not in opts:
            raise ValueError(f"device must be one of {opts}")
        return v

    @model_validator(mode='after')
    def _resolve_threshold_spec(self) -> 'UserConfig':
        """Resolve ``threshold`` to a concrete :class:`ThresholdSpec`.

        After this validator the field is never None and never a shorthand:
        the mode default is filled in (carve_fraction for weighted modes,
        cutoff 0 for violation-count modes) and the method is cross-checked
        against the mode's score kind.
        """
        kind = MODES[self.mode].score_kind
        spec = self.threshold

        if kind == "violation_count":
            if spec is None:
                spec = ThresholdSpec(method="cutoff", value=0.0)
            elif spec.method != "cutoff":
                raise ValueError(
                    f"threshold method '{spec.method}' is not valid for mode "
                    f"'{self.mode}': it produces integer violation counts, not "
                    f"continuous scores. Use a non-negative number (0 = strict, "
                    f"1 = allow one violation, ...) or leave threshold unset."
                )
            if self.mode == "tilted_plane" and spec.value != 0.0:
                # tilted_plane is binary: a voxel either protrudes above a
                # plane or it does not — a tolerance has no meaning.
                raise ValueError(
                    "tilted_plane mode is binary — threshold must be unset or 0. "
                    "A voxel either protrudes above the daylight plane (culled) "
                    "or it does not (kept)."
                )
        else:  # weighted_sum
            if spec is None:
                spec = ThresholdSpec(method="carve_fraction", value=self.carve_fraction)
            elif spec.method == "carve_fraction" and spec.value is None:
                spec = ThresholdSpec(method="carve_fraction", value=self.carve_fraction)

        self.threshold = spec
        return self

    @model_validator(mode='after')
    def _check_mode_requirements(self) -> 'UserConfig':
        """Enforce that modes requiring sun/sky data have EPW + analysis period."""
        if self.mode in MODES_NEEDING_EPW:
            if not self.epw_path:
                raise ValueError(f"mode '{self.mode}' requires epw_path")
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
    def _check_usefulness_path(self) -> 'UserConfig':
        if self.usefulness_path is not None:
            if self.mode != "benefit":
                raise ValueError(
                    "usefulness_path is only valid for mode 'benefit' "
                    f"(got mode '{self.mode}')"
                )
            defaults = (self.balance_temperature == 15.0
                        and self.balance_offset == 2.0)
            if not defaults:
                warnings.warn(
                    "balance_temperature/balance_offset are unused when "
                    "usefulness_path is set — the artifact's hourly weights "
                    "replace the balance-point filter.",
                    UrbanSolarCarverWarning,
                    stacklevel=2,
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
        if self.grid_step > self.voxel_size:
            raise ValueError(
                f"grid_step ({self.grid_step:g} m) must be ≤ voxel_size ({self.voxel_size:g} m). "
                "Increase voxel_size or decrease grid_step."
            )
        try:
            safe_max = int(os.environ.get("USC_MAX_RAY_BATCH", "2000000"))
        except ValueError:
            safe_max = 2_000_000
        if self.ray_batch_size > safe_max:
            warnings.warn(
                f"ray_batch_size={self.ray_batch_size} is too large; clamping to {safe_max}.",
                UrbanSolarCarverWarning,
                stacklevel=2,
            )
            self.ray_batch_size = safe_max
        return self


# ---------- Stage manifests ----------
# Only fields that are READ by a downstream stage are kept here.
# Provenance / diagnostics live in diagnostics/summary.json instead.

class PreprocessingManifest(BaseModel):
    """Manifest written by preprocessing, read by thresholding and exporting."""

    hash: str
    scores_path: str
    scores_kind: Literal["weighted_sum", "violation_count"]
    shape: Tuple[int, int, int]
    origin: Tuple[float, float, float]
    suggested_threshold: Optional[float] = None
    voxel_grid_path: Optional[str] = None
    voxel_size: Optional[float] = None
    mode: Optional[str] = None
    patch_weights_path: Optional[str] = None
    sample_point_count: Optional[int] = None

class ThresholdingManifest(BaseModel):
    """Manifest written by thresholding, read by exporting."""

    hash: str
    mask_path: str
    upstream_manifest: str

