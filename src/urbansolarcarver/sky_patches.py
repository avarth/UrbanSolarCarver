"""
UrbanSolarCarver Sky Patch Weighting Module

Generates sky-patch direction vectors, solid angles, and per-patch weight
distributions for the voxel carving pipeline. P = 145 Tregenza patches.

Core Functions
--------------
1. fetch_tregenza_patch_directions(device) → torch.Tensor
   Lazily loads a Ladybug ViewSphere and returns a (P×3) tensor of unit
   vectors for the P Tregenza sky patches.

2. fetch_tregenza_patch_solid_angles(device) → torch.Tensor
   Returns a length-P tensor of solid angles (steradians) per patch.

3. compute_EPW_based_weights(mode, epw_path, hoys, device, ...) → torch.Tensor
   Per-patch weights for the modes time-based (uniform), daylight (CIE
   overcast sky), irradiance and benefit (climate-based, from a Ladybug
   SkyMatrix built with the Perez all-weather model; units kWh/m²).

4. compute_radiative_cooling_weights(dewpoint_celsius, bliss_k, device,
   min_elevation_deg) → torch.Tensor
   Theoretical long-wave radiative cooling potential per patch
   (Martin-Berdahl sky emissivity with Bliss angular variation).
   Assumes a horizontal analysis surface.

The weights are combined with per-voxel sky-patch visibility to accumulate
exposure scores. The Tregenza vectors and solid angles are also usable on
their own for diagnostics or custom weighting schemes.
"""

import numpy as np
import torch
from typing import List, Sequence          
import math
from urbansolarcarver.session import session_cache
from urbansolarcarver.run_context import report_issue

# Ladybug objects are imported on first use, so importing this module does
# not require Ladybug, and are then kept for reuse.
_view_sphere = None  # cached ladybug ViewSphere (sky dome geometry)
_sky_matrix_cls = None  # cached ladybug_radiance SkyMatrix class

def _load_view_sphere() -> "ViewSphere":
    """
    Return the shared Ladybug ViewSphere, creating it on first call.
    """
    global _view_sphere
    if _view_sphere is None:
        from ladybug.viewsphere import ViewSphere
        _view_sphere = ViewSphere()
    return _view_sphere

def _load_sky_matrix() -> type:
    """
    Return the ladybug_radiance SkyMatrix class, importing it on first call.
    """
    global _sky_matrix_cls
    if _sky_matrix_cls is None:
        from ladybug_radiance.skymatrix import SkyMatrix
        _sky_matrix_cls = SkyMatrix
    return _sky_matrix_cls

@session_cache("{args[0]}")
def fetch_tregenza_patch_directions(
    device: torch.device  # compute device for the output tensor
) -> torch.Tensor:
    """
    Return the 145 unit direction vectors of the Tregenza hemisphere
    subdivision (Tregenza, 1987). The dome divides the sky hemisphere
    into 145 patches of approximately equal solid angle, organized in
    7 altitude rings (30, 30, 24, 24, 18, 12 and 6 patches) plus a
    zenith cap.

    Returns a float32 tensor of shape [P, 3] (P = 145) on ``device``, one
    unit vector (x, y, z) per patch centre, with z pointing up (z = cos of
    the zenith angle). Uses Ladybug's ViewSphere; the result is cached
    per device for the session.
    """
    sphere = _load_view_sphere()
    vecs = sphere.tregenza_dome_vectors             # 145 ladybug Vector3D
    coords = np.array([[v.x, v.y, v.z] for v in vecs], dtype=np.float32)
    return torch.from_numpy(coords).to(device)

def tregenza_solid_angles() -> np.ndarray:
    """Solid angle of each of the 145 Tregenza patches in steradians (float64).

    Built from Ladybug's per-band constants rather than its
    ``ViewSphere.tregenza_solid_angles`` property, which (ladybug-core
    0.44) caches its result in the Reinhart attribute and so returns the
    Reinhart list once ``reinhart_solid_angles`` has been read.
    """
    from ladybug.viewsphere import ViewSphere
    counts = ViewSphere.TREGENZA_PATCHES_PER_ROW + (1,)  # + zenith patch
    return np.repeat(np.asarray(ViewSphere.TREGENZA_COEFFICIENTS, dtype=np.float64),
                     counts)


@session_cache("{args[0]}")
def fetch_tregenza_patch_solid_angles(
    device: torch.device  # compute device for the output tensor
) -> torch.Tensor:
    """
    Return a float32 tensor of shape [P] (P = 145) with the solid angle of
    each Tregenza sky patch in steradians, in the same order as
    :func:`fetch_tregenza_patch_directions` (see :func:`tregenza_solid_angles`).
    The result is cached per device for the session.
    """
    arr = tregenza_solid_angles().astype(np.float32)
    return torch.from_numpy(arr).to(device)

def compute_radiative_cooling_weights(
    dewpoint_celsius: float,   # outdoor dew point in °C (input to Eq. 1)
    bliss_k: float,            # Bliss (1961) angular constant k (Eq. 2)
    device: torch.device,      # compute device for output tensor
    min_elevation_deg: float = 0.0,  # protection-cone cutoff (design constraint)
) -> torch.Tensor:
    """
    Return a long-wave "cooling potential" weight for each
    Tregenza sky patch, given an outdoor dew-point temperature.

    Scientific background
    ---------------------
    • Sky (hemispherical) emissivity, εₛky
      The clear-sky emissivity, integrated over the whole long-wave
      (thermal infrared) spectrum and the whole hemisphere, can be
      estimated from near-surface water-vapour content.  Martin & Berdahl
      (1984) fit a quadratic in x = T_dp / 100, with the dew point T_dp
      in °C, to radiometer measurements of clear skies:

          εₛky(x) = 0.758 + 0.521 x + 0.625 x²                (Eq. 1)

      A larger εₛky means the sky behaves more like a blackbody,
      sending more long-wave radiation back to the surface and therefore
      offering less cooling potential.

    • Directional emissivity (ε_dir)
      Sky emissivity also depends on the zenith angle θ.  Looking up,
      the line of sight crosses the thinnest layer of atmosphere, so the
      zenith has the lowest emissivity.  Towards the horizon the path
      through the humid lower air grows like 1/cos θ and the emissivity
      approaches 1 (a blackbody).  Bliss (1961) relates the hemispherical
      value of Eq. 1 to a direction-dependent value:

          ε_dir(θ) = 1 - (1 - εₛky)^(1 /(k · cos θ))          (Eq. 2)

      with k ≈ 1.8 for clear night skies.  The code clamps cos θ to at
      least 1e-3 to avoid division by zero at the horizon (the lowest
      Tregenza patch centre is at 6° elevation, so the clamp does not
      change the result in practice).

    • Radiative cooling potential
      Take a horizontal surface that is nearly black in the long wave and
      at about the air temperature.  Its net long-wave loss towards
      patch p is proportional to the view factor of the patch times the
      emissivity deficit of that patch:

          w_p ∝ (cos θ_p / π) · Ω_p · (1 - ε_dir(θ_p))      (Eq. 3)

      (cos θ_p / π) · Ω_p is the view factor from the horizontal surface
      to a small patch of solid angle Ω_p.  (1 - ε_dir) is the part of
      the surface's own emission that the sky does not return.


    Parameters
    ----------
    dewpoint_celsius : float
        Outdoor dew-point temperature [°C].  Acts as a proxy for
        absolute humidity in Eq. 1.  A warning is issued outside
        [-15, 25] °C, the range treated as valid for the fit.
    bliss_k : float
        Empirical constant k from Bliss (1961) in Eq. 2.  Must be
        positive; 1.8 is typical for clear skies, and values usually lie
        between 1.5 and 2.0.  A larger k lowers the emissivity near the
        zenith, which increases the zenith-to-horizon contrast.
    device : torch.device
        Target compute device for the returned tensor.
    min_elevation_deg : float, default=0.0
        Design-constraint protection cone: sky patches whose centre
        elevation is below this angle are excluded (weight 0) and the
        remaining weights renormalized.  This is not part of the physical
        model.  It declares which portion of the sky dome the design
        protects, similar to obstruction-angle rules in daylight codes.
        0 (default) keeps the full hemisphere (pure physical model).

    Returns
    -------
    torch.Tensor  (shape [P], P = 145 sky patches, dtype float32)
        Cooling weights wᵢ ≥ 0 with Σ wᵢ = 1.

    Raises
    ------
    ValueError
        If ``bliss_k`` is not positive, or if ``min_elevation_deg``
        excludes every sky patch.

    Notes
    -----
    * **Assumes a horizontal analysis surface** (flat roof).  The view
      factor cos(θ)/π in Eq. 3 is only correct for an upward-facing
      horizontal surface.  For tilted or vertical surfaces the cosine is
      taken to the surface normal instead, so applying these weights to
      them over-weights the zenith and under-weights low-altitude patches.
    * Valid for clear nights; clouds would raise εₛky toward unity and
      flatten the weight distribution.
    * The weights are normalized, dimensionless fractions; they can
      multiply any radiative heat-transfer quantity in further
      calculations.

    References
    ----------
    * Bliss, R.W. 1961. "Atmospheric Radiation near the Surface of the
      Ground." *Solar Energy* 5 (3): 103-120.
    * Martin, M. & Berdahl, P. 1984. "Characteristics of Infrared Sky
      Radiation in the United States." Solar Energy 33 (3-4): 321-336.
    """
    
    if bliss_k <= 0.0:
        raise ValueError(
            f"bliss_k must be positive (typical range 1.5–2.0), got {bliss_k}"
        )
    # The Martin-Berdahl fit (Eq. 1) is treated as valid for dew points from
    # -15 to +25 °C; outside that range warn, but still compute the weights.
    if dewpoint_celsius < -15.0 or dewpoint_celsius > 25.0:
        report_issue(
            "dew_point_outside_fit",
            f"Dew point {dewpoint_celsius:.1f} °C is outside the Martin-Berdahl fit "
            f"range [−15, 25] °C; radiative cooling weights may be inaccurate.",
        )
    # Eq. 1: clear-sky hemispherical emissivity, x = T_dp / 100 with T_dp in °C.
    # The upper clamp keeps (1 - eps_global) positive for the power in Eq. 2.
    x = torch.as_tensor(dewpoint_celsius / 100.0, dtype=torch.float32, device=device)
    eps_global = 0.758 + 0.521 * x + 0.625 * x * x
    eps_global = torch.clamp(eps_global, min=0.0, max=0.999)
    dirs = fetch_tregenza_patch_directions(device)  # [145,3]
    solid_angles = fetch_tregenza_patch_solid_angles(device)  # [145]
    cos_zen = dirs[:, 2].clamp(min=1e-3)               # avoid zero division

    # Eq. 2, directional emissivity per Bliss (1961):
    #   eps_dir(theta) = 1 - (1 - eps_global)^(1 / (k * cos_zen))
    # Near the zenith (cos_zen ~ 1) eps_dir is below the hemispherical value;
    # towards the horizon the exponent grows and eps_dir approaches 1, so
    # low patches emit almost like a blackbody and offer little cooling.
    eps_dir = 1.0 - torch.pow((1.0 - eps_global), 1.0 / (bliss_k * cos_zen))

    # Eq. 3: (cos(theta) / pi) * solid_angle is the view factor from a
    # horizontal surface to the patch (horizontal surface assumed);
    # (1 - eps_dir) is the emissivity deficit: the less the atmosphere
    # emits in a direction, the more heat the surface loses towards it.
    view_factor = cos_zen / math.pi                     # [145]
    raw = view_factor * (1.0 - eps_dir) * solid_angles

    # Design-constraint protection cone: exclude patches below the declared
    # elevation.  Applied after the physical weights so that
    # min_elevation_deg=0 gives exactly the unmodified physical model.
    if min_elevation_deg > 0.0:
        elevation_deg = torch.rad2deg(torch.asin(dirs[:, 2].clamp(-1.0, 1.0)))
        raw = torch.where(elevation_deg >= min_elevation_deg, raw,
                          torch.zeros_like(raw))
        if not (raw > 0.0).any():
            raise ValueError(
                f"min_sky_elevation_deg={min_elevation_deg:g} excludes every "
                f"sky patch (highest Tregenza patch center is at 90°). "
                f"Lower the cutoff."
            )

    total = raw.sum()
    if total <= 0.0:
        # Guard only: eps_global <= 0.999 keeps the zenith patch's deficit
        # positive, so this is not expected to run.  Fall back to uniform.
        return torch.full_like(raw, fill_value=1.0 / raw.numel())
    return (raw / total).to(torch.float32)

def _scaled_cumulative_matrix(epw_path: str, hourly_weights, lb_north: float,
                              expected_patches: int) -> np.ndarray:
    """Cumulative Tregenza sky matrix with each hour's direct normal (DNI)
    and diffuse horizontal (DHI) irradiance scaled by ``hourly_weights``
    (length 8760, non-negative).

    Hours outside the analysis period are excluded by giving them weight
    0, so the Wea (Ladybug weather object) keeps its full-year length
    instead of being filtered by hour.

    Returns a float64 array of shape (expected_patches,) with the
    weighted cumulative direct + diffuse irradiance per patch [kWh/m²].
    Raises RuntimeError if Ladybug returns a different patch count.
    """
    from ladybug.wea import Wea

    w = np.asarray(hourly_weights, dtype=np.float64)
    wea = Wea.from_epw_file(str(epw_path))
    dni = wea.direct_normal_irradiance.duplicate()
    dhi = wea.diffuse_horizontal_irradiance.duplicate()
    dni.values = [float(v) * float(s) for v, s in zip(dni.values, w)]
    dhi.values = [float(v) * float(s) for v, s in zip(dhi.values, w)]
    SkyMatrix = _load_sky_matrix()
    sky = SkyMatrix(Wea(wea.location, dni, dhi), north=lb_north,
                    high_density=False)
    d = np.clip(np.asarray(sky.direct_values, dtype=np.float64), 0.0, None)
    f = np.clip(np.asarray(sky.diffuse_values, dtype=np.float64), 0.0, None)
    out = d + f
    if out.shape[0] != expected_patches:
        raise RuntimeError(
            f"SkyMatrix returned {out.shape[0]} patches, "
            f"expected {expected_patches}"
        )
    return out


# Main function: compute weights per sky patch

def compute_EPW_based_weights(
    mode: str,                                              # weighting mode: 'time-based','daylight','irradiance','benefit'
    epw_path: str,                                          # file path to EPW weather data
    hoys: Sequence[float],                                   # hour-of-year indices
    device: torch.device = None,                               # output tensor device (default: auto-detect)
    balance_temperature: float = 15.0,                      # benefit model balance temperature (°C)
    balance_offset: float = 2.0,                            # benefit model +/- offset (°C)
    north: float = 0.0,                                     # north direction (degrees CW from +Y, USC convention)
    include_harm: bool = False,                             # benefit only: subtract hot-hour radiation (clipped at 0)
    simulated_weights: "tuple | None" = None,               # benefit only: (benefit[8760], harm[8760]) hourly weights
) -> torch.Tensor:
    """
    Return a vector of sky-patch weights (length P = 145) derived from
    EnergyPlus Weather (EPW) data, or from the CIE overcast sky (daylight)
    or a uniform sky (time-based).
    Each weight expresses the relative importance of the
    corresponding Tregenza sky patch for a chosen metric:

        ┌──────────────┬──────────────────────────────────────────────┐
        │ mode         │ physical meaning of the weight wᵢ            │
        ├──────────────┼──────────────────────────────────────────────┤
        │ time-based   │ uniform weight 1 for every patch             │
        │ daylight     │ CIE overcast luminance Ω·(1+2 cos θ)/3       │
        │ irradiance   │ cumulative solar energy (direct+diffuse)     │
        │ benefit      │ net *heating benefit* of solar gains         │
        └──────────────┴──────────────────────────────────────────────┘

    Scientific background
    ---------------------
    * Sky patch geometry: Tregenza subdivides the hemisphere into
      145 patches of nearly equal solid angle.
      `fetch_tregenza_patch_directions` returns the unit vectors
      d̂ᵢ = (xᵢ, yᵢ, zᵢ) with zᵢ = cos θᵢ (θ = zenith angle);
      `fetch_tregenza_patch_solid_angles` returns the solid angles Ωᵢ.

    * time-based: uninformative baseline, wᵢ = 1 for every patch.
      Used for carving with traditional time-based solar envelope
      methods, where every unobstructed sun or sky direction counts
      equally.

    * daylight: the CIE Standard Overcast Sky (see Darula & Kittler
      2002) prescribes a relative luminance L(θ) ∝ (1 + 2 cos θ)/3,
      three times brighter at the zenith than at the horizon.  The
      weight is that luminance times the patch solid angle Ωᵢ.

    * irradiance: 'SkyMatrix.from_epw' (Ladybug Tools) builds a
      Perez all-weather sky for every hour, then sums the selected
      hours ('hoys') to obtain the cumulative short-wave energy per
      patch:

          wᵢ = Σₜ (E_dirᵢₜ + E_difᵢₜ) [kWh m⁻²]

      where E_dirᵢₜ is the direct-beam contribution and E_difᵢₜ the
      diffuse sky contribution of patch i in hour t.

    * benefit: heating-benefit filter.  Only solar gains in hours cold
      enough to offset heating demand are credited,

          wᵢ = Σₜ (E_dirᵢₜ + E_difᵢₜ) · H( T_bal - ΔT - Tₐₜ )

      with the Heaviside step H (1 for a positive argument, else 0) and
      Tₐₜ the outdoor dry-bulb temperature.  The code selects the cold
      hours from the EPW dry-bulb series and builds a plain cumulative
      irradiance SkyMatrix over exactly those hours, so the formula above
      is what is computed.  Warm hours in the analysis period contribute
      nothing, so a longer period does not dilute the result.
      With ``include_harm=True`` (opt-in, experimental) the weights
      instead follow Ladybug's composite radiation-benefit concept:
      hot-hour (Tₐ > T_bal + ΔT) radiation is subtracted per patch and
      the result clipped at zero,

          wᵢ = max( Σ_cold E − Σ_hot E , 0 )

      Results then depend on how much of the warm season the analysis
      period includes.  A patch's weight can drop to zero but not below,
      because a negative weight (the value of shade) cannot be expressed
      as a carving force.
      'balance_temperature' (T_bal) is the building's free-running
      balance point; derive project-specific values with the
      Honeybee/EnergyPlus balance-point workflow.  'balance_offset' (ΔT)
      is the half-width of the dead band around it (hours inside the band
      count for neither side).
      With ``simulated_weights`` the Heaviside step is replaced by hourly
      weights in [0, 1] from an ISO 13790 zone model (see
      :mod:`urbansolarcarver.simulated_weights`): each hour's irradiance
      is scaled by benefit[t] (and, with ``include_harm``, harm[t] is
      subtracted the same way) before the sky matrix is summed.

    Parameters
    ----------
    mode : {'time-based', 'daylight', 'irradiance', 'benefit'}
        Weighting strategy (see table above).  Case and surrounding
        whitespace are ignored.
    epw_path : str
        Path to an EPW file.  Required for *irradiance* and *benefit*.
    hoys : Sequence[float]
        Hour-of-year indices (0 to 8759) to sample.  Required and
        non-empty for *irradiance* and *benefit*; ignored otherwise.  For
        *benefit*, a full-year period is a sensible default: the balance
        filter selects the beneficial hours by itself.
    device : torch.device, default 'cuda' if available else 'cpu'
        Compute device for the returned tensor.
    balance_temperature : float, default 15 °C
        Free-running balance-point temperature T_bal for the benefit
        filter.
    balance_offset : float, default 2 °C
        Dead-band half-width ΔT: cold hours are below T_bal - ΔT; with
        ``include_harm``, hot hours are above T_bal + ΔT.
    north : float, default 0
        North direction in degrees clockwise from +Y (USC convention).
        Converted to Ladybug's counterclockwise convention internally.
    include_harm : bool, default False
        Benefit mode only.  Subtract hot-hour radiation per patch and
        clip at zero (experimental, see above).
    simulated_weights : tuple of two arrays, optional
        Benefit mode only.  ``(benefit, harm)`` hourly series of length
        8760 with values in [0, 1] (the first two items returned by
        :func:`urbansolarcarver.simulated_weights.read_simulated_weights`).
        When given, they replace the balance-point filter and
        ``balance_temperature`` / ``balance_offset`` are not used.

    Returns
    -------
    torch.Tensor
        Shape (P,), dtype float32, on ``device``.
        Weights are non-negative and not normalized (unlike
        :func:`compute_radiative_cooling_weights`, whose weights sum to
        1).  They keep the physical scale returned by Ladybug (kWh/m² for
        irradiance/benefit) or the CIE luminance distribution (daylight).
        The threshold methods (carve_fraction, headtail) are
        scale-invariant, so the scale does not affect carving results.
        In benefit mode an all-zero vector is returned, with a warning,
        when no hour in the period qualifies.

    Raises
    ------
    TypeError
        If ``mode`` is not a non-empty string.
    FileNotFoundError
        If *irradiance* or *benefit* is requested without an existing
        EPW file.
    ValueError
        If ``hoys`` is empty or outside 0 to 8759 for those modes, or if
        ``mode`` is not supported.
    RuntimeError
        If Ladybug's SkyMatrix does not return P patches.

    Notes
    -----
    * The EPW-driven modes assume typical meteorology; rare events
      (e.g. > 99th percentile irradiance) may be under-represented.
    * Without ``simulated_weights``, the benefit filter is purely
      temperature-based; construction, occupancy and HVAC control logic
      are not considered.

    References
    ----------
    * Perez, R. et al. 1990. "Modeling daylight availability and
      irradiance components from direct and global irradiance."
      *Solar Energy* 44(5): 271-289.
    * Darula, S. & Kittler, R. 2002. "CIE general sky standard defining
      luminance distributions." *Proceedings eSim* 11: 13.
    * Ladybug Tools. "SkyMatrix": cumulative Radiance sky matrix
      (gendaymtx / Perez all-weather).
      https://www.ladybug.tools/ladybug-radiance/docs/
    """
    
    # --- 0. resolve device --------------------------------------------------------
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # --- 1. input validation ------------------------------------------------------
    if not isinstance(mode, str) or not mode.strip():
        raise TypeError(f"mode must be a non-empty string, got {mode!r}")

    # USC's north is degrees clockwise from +Y; Ladybug's SkyMatrix north is
    # counterclockwise ("90 is West"), so negate to convert.
    lb_north = -float(north)

    key = mode.strip().lower()
    P = fetch_tregenza_patch_directions(device).shape[0]  # 145 patches


    # --- 2. mode selection ------------------------------------------------------

    if key == 'time-based':
        return torch.ones(P, device=device)

    if key == 'daylight':
        dirs = fetch_tregenza_patch_directions(device)  # [145, 3]
        angles = fetch_tregenza_patch_solid_angles(device) # [145]
        cosz = dirs[:, 2].clamp(min=0.0)
        return angles * (1.0 + 2.0 * cosz) / 3.0  # Ωᵢ · (1 + 2 cos θᵢ) / 3 (CIE overcast luminance)
    
    # Modes that need an EPW file and hoys: validate before the slow file I/O.
    if key in ('irradiance', 'benefit'):
        import os as _os
        if not epw_path or not _os.path.isfile(epw_path):
            raise FileNotFoundError(
                f"compute_EPW_based_weights: EPW file required for mode "
                f"'{key}', got {epw_path!r}"
            )
        hoys_list = list(hoys) if hoys is not None else []
        if not hoys_list:
            raise ValueError(f"mode '{key}' requires a non-empty hoys sequence")
        # EPW files hold 8760 hours; leap-year periods are not supported.
        if not all(0 <= idx <= 8759 for idx in hoys_list):
            raise ValueError("Hour-of-year indices must lie between 0 and 8759.")

    if key == 'irradiance':
        SkyMatrix = _load_sky_matrix()

        # Ladybug's SkyMatrix already integrates solid angles into the
        # kWh/m² values it returns, so we do not multiply by Ωᵢ here
        # (unlike daylight mode, which builds weights from raw CIE
        # luminance and must apply solid angles explicitly).
        sky = SkyMatrix.from_epw(
            epw_path,
            hoys=hoys,
            north=lb_north,
            high_density=False,
        )
        direct  = np.clip(np.asarray(sky.direct_values,  dtype=np.float32), 0.0, None)
        diffuse = np.clip(np.asarray(sky.diffuse_values, dtype=np.float32), 0.0, None)
        weights = direct + diffuse
        if weights.shape[0] != P:
            raise RuntimeError(
                f"SkyMatrix returned {weights.shape[0]} patches, expected {P}"
            )
        return torch.from_numpy(weights).to(device)

    if key == 'benefit':
        from ladybug.epw import EPW

        if simulated_weights is not None:
            # Hourly weights from the zone model (simulated_weights_path
            # artifact): scale each hour's DNI/DHI by benefit[t] before
            # building the cumulative sky matrix.  The sky model then assigns
            # each hour's weight to the patches its sun and sky occupied.
            # The balance-point filter below is the special case where every
            # hourly weight is 0 or 1.  Hours outside the analysis period get
            # weight 0 through period_mask.
            benefit_series, harm_series = simulated_weights
            benefit_series = np.asarray(benefit_series, dtype=np.float64)
            harm_series = np.asarray(harm_series, dtype=np.float64)
            period_mask = np.zeros(8760)
            for h in hoys_list:
                if int(h) < 8760:
                    period_mask[int(h)] = 1.0

            w_ben = benefit_series * period_mask
            if not w_ben.any():
                report_issue(
                    "zero_patch_weights",
                    "benefit mode (simulated_weights_path): the artifact's benefit "
                    "weights are zero everywhere in the analysis period, so "
                    "all patch weights are zero and the carve will be "
                    "degenerate. Widen the period or check the artifact.",
                )
                return torch.zeros(P, device=device)

            weights_np = _scaled_cumulative_matrix(epw_path, w_ben, lb_north, P)
            if include_harm:
                w_harm = harm_series * period_mask
                if w_harm.any():
                    weights_np = np.clip(
                        weights_np
                        - _scaled_cumulative_matrix(epw_path, w_harm,
                                                    lb_north, P),
                        0.0, None,
                    )
                    if not weights_np.any():
                        report_issue(
                            "zero_patch_weights",
                            "benefit mode (simulated_weights_path, include_harm): "
                            "harm exceeds benefit for every sky patch, so all "
                            "weights are zero and the carve will be "
                            "degenerate.",
                        )
            return torch.from_numpy(
                weights_np.astype(np.float32)).to(device)

        # Heating-benefit filter, computed exactly as documented:
        #     wᵢ = Σₜ (E_dirᵢₜ + E_difᵢₜ) · H(T_bal − ΔT − Tₐₜ)
        # The cold hours are selected here from the EPW dry-bulb series; the
        # sky matrix is then a plain cumulative irradiance matrix over those
        # hours.  By default, hot-hour radiation does not enter the weights:
        # a carving force cannot express the value of shade without
        # producing physically meaningless "shade volumes".  Evaluate it as
        # a separate irradiance analysis over hot hours instead.
        weather = EPW(epw_path)
        dry_bulb = weather.dry_bulb_temperature.values  # hourly °C, len 8760
        t_cutoff = float(balance_temperature) - float(balance_offset)
        cold_hoys = [
            h for h in hoys_list
            if int(h) < len(dry_bulb) and dry_bulb[int(h)] < t_cutoff
        ]
        if not cold_hoys:
            # Return here: passing an empty hoys list to Ladybug would not
            # give zeros, because SkyMatrix treats [] as the whole year.
            report_issue(
                "zero_patch_weights",
                f"benefit mode: no hours in the analysis period are below "
                f"balance_temperature - balance_offset = {t_cutoff:g} °C, "
                f"so all patch weights are zero and the carve will be "
                f"degenerate. Widen the analysis period or check "
                f"balance_temperature.",
            )
            return torch.zeros(P, device=device)

        SkyMatrix = _load_sky_matrix()

        def _cumulative_patch_matrix(sel_hoys):
            # Ladybug's SkyMatrix already includes solid angles in the
            # kWh/m² values, no Ωᵢ multiply needed (same as irradiance).
            # Clip guards against small negative values from gendaymtx
            # numerical noise; all physical values are non-negative here.
            sky = SkyMatrix.from_epw(
                epw_path, hoys=sel_hoys, north=lb_north, high_density=False,
            )
            d = np.clip(np.asarray(sky.direct_values,  dtype=np.float32), 0.0, None)
            f = np.clip(np.asarray(sky.diffuse_values, dtype=np.float32), 0.0, None)
            w = d + f
            if w.shape[0] != P:
                raise RuntimeError(
                    f"SkyMatrix returned {w.shape[0]} patches, expected {P}"
                )
            return w

        weights_np = _cumulative_patch_matrix(cold_hoys)

        if include_harm:
            # Opt-in composite (Ladybug's radiation-benefit concept):
            # subtract hot-hour radiation per patch and clip at zero.
            # Experimental, as stated in the config docs:
            #   * results depend on how much of the warm season the
            #     analysis period includes;
            #   * harm lowers a patch's weight to zero at most, never below
            #     (the value of shade cannot be a carving force, see above).
            t_hot = float(balance_temperature) + float(balance_offset)
            hot_hoys = [
                h for h in hoys_list
                if int(h) < len(dry_bulb) and dry_bulb[int(h)] > t_hot
            ]
            if hot_hoys:  # Ladybug would read an empty list as the full year
                weights_np = np.clip(
                    weights_np - _cumulative_patch_matrix(hot_hoys), 0.0, None
                )
                if not weights_np.any():
                    report_issue(
                        "zero_patch_weights",
                        "benefit mode (include_harm=true): hot-hour harm "
                        "exceeds cold-hour benefit for every sky patch, so all "
                        "weights are zero and the carve will be degenerate. "
                        "Narrow the analysis period or use "
                        "include_harm=false.",
                    )

        return torch.from_numpy(weights_np).to(device)

    raise ValueError(f"Unsupported weighting mode '{mode}' requested.")
