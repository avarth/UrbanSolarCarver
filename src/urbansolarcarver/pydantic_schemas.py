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
from typing import Optional, Union, List, Tuple, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .mode_registry import ALL_MODE_NAMES, EXPERIMENTAL_MODES, MODES_NEEDING_EPW


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

# ---------- YAML config schema ----------
class UserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

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

    # analysis period (required for sun/sky modes, ignored by tilted_plane)
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

    # radiative cooling option
    dew_point_celsius: float = Field(14.0, description="Night-time dew-point (°C) for radiative_cooling mode")
    bliss_k: float = Field(1.8, gt=0, description="Bliss (1961) angular-attenuation constant for radiative_cooling")

    # sky model parameters
    north_deg: float = Field(0.0, ge=0.0, lt=360.0, description="North direction in degrees clockwise from Y-axis (0 = Y-up is north)")
    ground_reflectance: float = Field(0.2, ge=0.0, le=1.0, description="Ground surface reflectance for sky model (0-1)")

    # grid & ray parameters
    voxel_size:    float = Field(1.0, ge=0.01, le=100.0, description="Voxel edge length (m), 0.01–100")
    grid_step:     float = Field(1.0, gt=0, description="Surface sampling spacing (m)")
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
    threshold: Union[float, str, None] = Field(
        None,
        description=(
            "How to decide which voxels to carve. "
            "'carve_fraction' (recommended): remove a percentage of obstructing volume, "
            "controlled by carve_fraction parameter. "
            "'headtail': automatic split biased toward removing only the worst obstructors. "
            "A numeric value (≥ 0): manual threshold on raw scores — "
            "carve voxels scoring above this value (inspect the score histogram first). "
            "None: use mode default (carve_fraction)."
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
    balance_temperature: float = Field(20.0, description="Balance temperature for benefit mode (°C)")
    balance_offset:      float = Field( 2.0, description="Balance offset for benefit mode (°C)")

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

    @field_validator('threshold')
    def _validate_threshold(cls, v: Union[float, str, None]) -> Union[float, str, None]:
        if v is None:
            return v
        if isinstance(v, str):
            if v == 'numeric':
                # 'numeric' is a UI-side placeholder (Grasshopper Threshold
                # component); the pipeline needs the actual number.
                raise ValueError(
                    "threshold='numeric' requires an explicit value — "
                    "set threshold to the raw-score cutoff number itself "
                    "(in Grasshopper, connect a number to the 'value' input)."
                )
            if v not in {'headtail', 'carve_fraction'}:
                raise ValueError("threshold must be one of {'headtail','carve_fraction'} or a number")
            return v
        if v < 0:
            raise ValueError("numeric threshold must be >= 0")
        return float(v)

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
            # tilted_plane is binary: a voxel either protrudes above a plane or it does not.
            # threshold > 0 or a string method has no architectural meaning here.
            thr = self.threshold
            if thr is not None:
                if isinstance(thr, str) or float(thr) > 0:
                    raise ValueError(
                        "tilted_plane mode is binary — threshold must be None or 0. "
                        "A voxel either protrudes above the daylight plane (culled) or it does not (kept). "
                        "String methods and tolerance values > 0 are not applicable."
                    )
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

