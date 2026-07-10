"""
UrbanSolarCarver Sky Patch Weighting Module

Generates sky-patch direction vectors, solid angles, and per-patch weight
distributions for the voxel carving pipeline.

Core Functions
--------------
1. fetch_tregenza_patch_directions(device) → torch.Tensor
   Lazily loads a Ladybug ViewSphere and returns a (P×3) tensor of unit
   vectors for the P Tregenza sky patches.

2. fetch_tregenza_patch_solid_angles(device) → torch.Tensor
   Returns a length-P tensor of solid angles (steradians) per patch.

3. compute_EPW_based_weights(mode, epw_file, hoys, device, ...) → torch.Tensor
   Climate-based weights via Ladybug SkyMatrix (Perez all-weather model).
   Supports modes: irradiance, benefit, daylight.

4. compute_radiative_cooling_weights(dew_point, bliss_k, device) → torch.Tensor
   Theoretical radiative cooling potential per patch (Martin-Berdahl +
   Bliss angular attenuation).  Assumes horizontal analysis surface.
Compute_weights yields all the sky-patch coefficients necessary to
accumulate per-voxel exposure scores. Tregenza vectors and solid angles
are also available for diagnostics or custom weighting schemes.
"""

import numpy as np
import torch
from typing import List, Sequence          
import math
from urbansolarcarver.session import session_cache

# Lazy-loaded shared instances for efficiency
_view_sphere = None  # caches sky dome geometry
_sky_matrix_cls = None  # caches sky irradiance calculator class

def _load_view_sphere() -> "ViewSphere":
    """
    Internal loader for the sky dome sample directions
    Ensures only one ViewSphere instance is created
    """
    global _view_sphere
    if _view_sphere is None:
        from ladybug.viewsphere import ViewSphere
        _view_sphere = ViewSphere()
    return _view_sphere

def _load_sky_matrix() -> type:
    """
    Internal loader for the sky irradiance model
    Avoids repeated imports of SkyMatrix class
    """
    global _sky_matrix_cls
    if _sky_matrix_cls is None:
        from ladybug_radiance.skymatrix import SkyMatrix
        _sky_matrix_cls = SkyMatrix
    return _sky_matrix_cls

# -----------------------------------------------------------------
#  Cache Tregenza directions once per live CarverSession.
# -----------------------------------------------------------------
@session_cache("tregenza_dirs")               # one-liner decorator
def fetch_tregenza_patch_directions(
    device: torch.device  # compute device for the output tensor
) -> torch.Tensor:
    """
    Returns the 145 unit direction vectors of the Tregenza hemisphere
    subdivision (Tregenza, 1987). The dome divides the sky hemisphere
    into 145 patches of approximately equal solid angle, organized in
    7 altitude rings plus a zenith cap.

    Returns tensor [P, 3] of unit vectors for each Tregenza sky patch.
    Uses ladybug ViewSphere internally.
    """
    sphere = _load_view_sphere()
    vecs = sphere.tregenza_dome_vectors             # list of Vector3 (x,y,z)
    # convert to NumPy then tensor for GPU/CPU transfer
    coords = np.array([[v.x, v.y, v.z] for v in vecs], dtype=np.float32)
    return torch.from_numpy(coords).to(device)

# -----------------------------------------------------------------
#  Cache solid angles the same way.
# -----------------------------------------------------------------
@session_cache("tregenza_solid_angles")
def fetch_tregenza_patch_solid_angles(
    device: torch.device  # compute device for the output tensor
) -> torch.Tensor:
    """
    Returns tensor [P] of solid angles (in steradians) per tregenza sky patch.
    Uses ladybug viewsphere
    """
    sphere = _load_view_sphere()
    angles = sphere.tregenza_solid_angles           # list of floats
    arr = np.array(angles, dtype=np.float32)
    return torch.from_numpy(arr).to(device)

def compute_radiative_cooling_weights(
    dewpoint_celsius: float,   # ambient dew point in °C for emissivity fit
    bliss_k: float,            # empirical angular‐attenuation constant (Bliss 1961)
    device: torch.device,      # compute device for output tensor
    min_elevation_deg: float = 0.0,  # protection-cone cutoff (design constraint)
) -> torch.Tensor:
    """
    Return a long-wave "cooling potential" weight for each
    Tregenza sky patch, given an outdoor dew-point temperature.

    Scientific background
    ---------------------
    • Sky (hemispherical) emissivity, εₛky  
      The clear-sky emissivity in the 8-13 µm thermal-IR window can be
      estimated from near-surface water-vapour content.  Martin & Berdahl
      (1984) fit a quadratic in relative dew-point x = T_dp / 100 °C
      to a wide range of radiometer measurements:

          εₛky(x) = 0.758 + 0.521 x + 0.625 x²                (Eq. 1)

      A larger εₛky means the sky behaves more like a blackbody,
      emitting and absorbing more long-wave radiation and therefore
      offering less potential cooling for a hot surface.

    • Directional emissivity (ε_dir)
      Long-wave exchange also depends on zenith angle θ: the drier,
      higher-altitude air seen near the zenith is usually "blacker" than
      the humid boundary layer near the horizon.  Bliss (1961) proposed
      an exponential attenuation law that relates the hemispherical
      value in Eq. 1 to a direction-dependent value:

          ε_dir(θ) = 1 - (1 - εₛky)^(1 /(k · cos θ))          (Eq. 2)

      with k ≈ 1.8 for clear nocturnal skies.  The code clamps
      cos θ to `1e-3` to avoid division by zero at the horizon.

    • Radiative cooling potential  
      A surface "sees" the sky patch through its solid angle Ω_p.
      Assuming the surface itself is nearly black in the long-wave,
      its net radiative heat *loss* in direction *p* is proportional to

          (1 - ε_dir) · Ω_p                                 (Eq. 3)

      because (1 - ε_dir) is the fraction of the surface's own emission
      not returned by the sky (i.e. the deficit in sky emission).


    Parameters
    ----------
    dewpoint_celsius : float
        Outdoor dew-point temperature [°C].  Acts as a proxy for
        absolute humidity in Eq. 1.
    bliss_k : float, default=1.8
        Empirical constant from Bliss (1961) governing angular variation of atmospheric
        emissivity. Typical clear-sky values range 1.5 - 2.0; larger k increases zenith-horizon contrast.
    device : torch.device
        Target compute device for the returned tensor.
    min_elevation_deg : float, default=0.0
        Design-constraint protection cone: sky patches whose center
        elevation is below this angle are excluded (weight 0) and the
        remaining weights renormalized.  This is NOT part of the physical
        model — it declares which portion of the sky dome the design
        defends, analogous to obstruction-angle rules in daylight codes.
        0 (default) keeps the full hemisphere (pure physical model).

    Returns
    -------
    torch.Tensor  (length = P sky patches, dtype =float32)
        cooling weights wᵢ ≥ 0,  Σ wᵢ = 1.

    Notes
    -----
    * **Assumes horizontal analysis surface** (flat roof).  The view-factor
      weighting cos(θ)/π used in Eq. 3 is only correct for an upward-facing
      horizontal surface.  For tilted or vertical surfaces the angular
      integration bounds change significantly; applying these weights to
      non-horizontal surfaces will over-weight the zenith and under-weight
      low-altitude patches.
    * Valid for clear nights; clouds would raise εₛky toward unity and
      flatten the weight distribution.
    * Units cancel, so the weights are dimensionless fractions that can
      multiply any radiative-heat-transfer coefficient in further
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
    # Martin-Berdahl (1984) quadratic fit for clear-sky emissivity.
    # Validated for dew points roughly −10 °C to +10 °C; extrapolation outside
    # [−15, 25] °C is unreliable — warn but don't crash.
    if dewpoint_celsius < -15.0 or dewpoint_celsius > 25.0:
        import warnings
        warnings.warn(
            f"Dew point {dewpoint_celsius:.1f} °C is outside the Martin-Berdahl fit "
            f"range [−15, 25] °C; radiative cooling weights may be inaccurate.",
            stacklevel=2,
        )
    # Martin-Berdahl (1984) empirical fit for clear-sky hemispherical
    # emissivity: ε_sky = 0.758 + 0.521·x + 0.625·x²  (see docstring Eq. 1)
    # where x = T_dp / 100 °C.  Valid for dew points roughly −15 to +25 °C.
    x = torch.as_tensor(dewpoint_celsius / 100.0, dtype=torch.float32, device=device)
    eps_global = 0.758 + 0.521 * x + 0.625 * x * x
    eps_global = torch.clamp(eps_global, min=0.0, max=0.999)
    dirs = fetch_tregenza_patch_directions(device)  # [145,3]
    solid_angles = fetch_tregenza_patch_solid_angles(device)  # [145]
    cos_zen = dirs[:, 2].clamp(min=1e-3)               # avoid zero division

    # Directional emissivity per Bliss (1961).  The parameter k controls
    # how strongly emissivity drops near the horizon (atmospheric path length).
    #   eps_dir(theta) = 1 - (1 - eps_global)^(1 / (k * cos_zen))
    # Patches near the zenith (cos_zen ~ 1) see nearly the full hemispherical
    # emissivity; patches near the horizon see much less sky emission.
    eps_dir = 1.0 - torch.pow((1.0 - eps_global), 1.0 / (bliss_k * cos_zen))

    # View factor for a horizontal Lambertian surface: cos(theta) / pi.
    # Weights each patch by how much of the surface "sees" it.
    # NOTE: assumes horizontal analysis surface.
    view_factor = cos_zen / math.pi                     # [145]
    # Cooling weight = view_factor * (1 - eps_dir) * solid_angle.
    # (1 - eps_dir) is the emissivity deficit: patches where the atmosphere
    # emits less radiation allow more heat to radiate to deep space.
    raw = view_factor * (1.0 - eps_dir) * solid_angles

    # Design-constraint protection cone: exclude patches below the declared
    # elevation.  Applied AFTER the physical weights so the null case
    # (min_elevation_deg=0) is exactly the unmodified physical model.
    if min_elevation_deg > 0.0:
        elevation_deg = torch.rad2deg(torch.asin(dirs[:, 2].clamp(-1.0, 1.0)))
        raw = torch.where(elevation_deg >= min_elevation_deg, raw,
                          torch.zeros_like(raw))
        if not (raw > 0.0).any():
            raise ValueError(
                f"min_sky_elevation_deg={min_elevation_deg:g} excludes every "
                f"sky patch (highest Tregenza patch center is at 90°) — "
                f"lower the cutoff."
            )

    total = raw.sum()
    if total <= 0.0:
        # No net cooling (e.g., very humid climate). Fall back to uniform.
        return torch.full_like(raw, fill_value=1.0 / raw.numel())
    return (raw / total).to(torch.float32)

# Main function: compute weights per sky patch

def compute_EPW_based_weights(
    mode: str,                                              # weighting mode: 'time-based','daylight','irradiance','benefit'
    epw_path: str,                                          # file path to EPW weather data
    hoys: Sequence[float],                                   # hour-of-year indices
    device: torch.device = None,                               # output tensor device (default: auto-detect)
    ground_reflectance: float = 0.2,                        # reflectivity coefficient
    balance_temperature: float = 15.0,                      # benefit model balance temperature (°C)
    balance_offset: float = 2.0,                            # benefit model +/- offset (°C)
    north: float = 0.0,                                     # north direction (degrees CW from +Y, USC convention)
) -> torch.Tensor:
    """
    Return a vector of sky-patch weights (length P) derived from
    Energy-Plus Weather (EPW) data or CIE overcast sky (for daylight).
    Each weight expresses the relative importance of the
    corresponding Tregenza sky patch for a chosen metric:

        ┌──────────────┬──────────────────────────────────────────────┐
        │ mode         │ physical meaning of the weight wᵢ            │
        ├──────────────┼──────────────────────────────────────────────┤
        │ time-based   │ uniform probability 1/P                      │
        │ daylight     │ CIE overcast luminance Ω·(1+2 cos θ)/3       │
        │ irradiance   │ solar short-wave power (direct+diffuse)      │
        │ benefit      │ net *heating benefit* of solar gains         │
        └──────────────┴──────────────────────────────────────────────┘

    Scientific background
    ---------------------
    * Sky patch geometry — Tregenza subdivides the hemisphere into
      145 quasi-equal solid-angle patches.
      `fetch_tregenza_patch_` returns Ωᵢ and view vector
      d̂ᵢ = (lᵢ, mᵢ, nᵢ)** with nᵢ = cos θ*.

    * time-based — Baseline uninformative prior:  
      wᵢ = 1/P. 
      For time-based carving using traditional time-based solar envelope methods.

    * daylight — The CIE Standard Overcast Sky (Darula & Kittler 2002)
      prescribes relative luminance  
      L(θ) ∝ (1 + 2 cos θ)/3.  

    * irradiance — 'SkyMatrix.from_epw' (Ladybug Tools) builds a
      Perez All-Weather sky for every time step, then integrates the
      selected hours ('hoys') to obtain cumulative short-wave
      energy per patch:

          wᵢ = Σₜ (E_dirᵢₜ + E_difᵢₜ) [J m⁻²]

      where E_dirᵢₜ is direct beam contribution and E_difᵢₜ
      diffuse.

    * benefit — Uses Ladybug's heating-benefit framework
      implemented in 'SkyMatrix.from_components_benefit', whereby only
      solar gains occurring when Tₐ < T_bal - ΔT are credited:

          wᵢ = Σₜ (E_dirᵢₜ + E_difᵢₜ) · H( T_bal - ΔT - Tₐₜ )

      with Heaviside switch H. 'balance_temperature'
      (T_bal) and 'balance_offset' (ΔT) loosely represent the
      building's heating set-point and internal gains.
      A Grasshopper/Ladybug simple E+ workflow is included. It
      can be used to derive project-specific balance temperatures.
      
    Parameters
    ----------
    mode : {'time-based', 'daylight', 'irradiance', 'benefit'}
        Weighting strategy (see table above).
    epw_path : str
        Path to an EPW file.  Required for *irradiance* and *benefit*.
    hoys : Sequence[float]
        Hour-of-year indices to sample.
    device : torch.device, default 'cuda' if available else 'cpu'
        Compute device for the returned tensor.
    ground_reflectance : float, default 0.2
        Lambertian ground albedo used by Perez model.
    balance_temperature : float, default 15 °C
        Base-temperature for the heating-benefit filter.
    balance_offset : float, default 2 °C
        Dead-band between comfort set-point and base temperature.

    Returns
    -------
    torch.Tensor
        Shape (P,), dtype float32, residing on device.
        Weights are non-negative.  Only ``radiative_cooling`` normalises
        to Σwᵢ = 1.  Other modes preserve the physical scale returned
        by Ladybug (Wh/m² for irradiance/benefit) or the CIE luminance
        distribution (daylight).  Threshold methods (carve_fraction,
        headtail) are scale-invariant, so the difference does not affect
        carving results.

    Notes
    -----
    * The EPW-driven modes assume typical meteorology; rare events
      (e.g. > 99th percentile irradiance) may be under-represented.
    * For benefit mode the heating-balance filter is purely
      temperature-based; construction, occupancy and HVAC control logic are not
      considered.

    References
    ----------
    * Perez, R. et al. 1990. "Modeling daylight availability and
      irradiance components from direct and global irradiance."
      *Solar Energy* 44(5): 271-289.
    * Darula, S. & Kittler, R. 2002. "CIE general sky standard defining
      luminance distributions." *Proceedings eSim* 11: 13.
    * Ladybug Tools. "SkyMatrix.from_components_benefit" — heating-benefit
      sky matrix filtering hours by balance-point temperature.
      https://www.ladybug.tools/ladybug/docs/ladybug.skymatrix.html
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
    P = fetch_tregenza_patch_directions(device).shape[0]  # [145]


    # --- 2. mode selection ------------------------------------------------------

    if key == 'time-based':
        # uniform weights
        return torch.ones(P, device=device)

    if key == 'daylight':
        dirs = fetch_tregenza_patch_directions(device)  # [145, 3]
        angles = fetch_tregenza_patch_solid_angles(device) # [145]
        cosz = dirs[:, 2].clamp(min=0.0)
        return angles * (1.0 + 2.0 * cosz) / 3.0  # Ωᵢ · (1 + 2 cos θᵢ) / 3 (CIE overcast luminance)
    
    # Modes that need EPW + hoys — validate before expensive I/O.
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
        if not all(0 <= idx <= 8783 for idx in hoys_list):
            raise ValueError(
                "Hour-of-year indices must lie between 0 and 8783 "
                "(inclusive, allowing leap years)."
            )

    if key == 'irradiance':
        SkyMatrix = _load_sky_matrix()

        # Ladybug's SkyMatrix already integrates solid angles into the
        # Wh/m² values it returns, so we do NOT multiply by Ωᵢ here
        # (unlike daylight mode, which builds weights from raw CIE
        # luminance and must apply solid angles explicitly).
        sky = SkyMatrix.from_epw(
            epw_path,
            hoys=hoys,
            north=lb_north,
            high_density=False,
            ground_reflectance=ground_reflectance
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

        # Same as irradiance: Ladybug's SkyMatrix already includes solid
        # angles in the Wh/m² benefit values — no Ωᵢ multiply needed.

        # 1) Read EPW and sky‐matrix generator
        weather   = EPW(epw_path)
        SkyMatrix = _load_sky_matrix()
 
        # 2) Build the benefit sky matrix (145 patches)
        sky = SkyMatrix.from_components_benefit(
            weather.location,                         # location (lat, lon, tz)
            weather.direct_normal_radiation,          # DNI series (W/m²)
            weather.diffuse_horizontal_radiation,     # DHI series (W/m²)
            weather.dry_bulb_temperature,             # air temp series (°C)
            balance_temperature,                      # balance T for heating (°C)
            balance_offset,                           # dead-band offset (°C)
            hoys=hoys,                                # hours-of-year to include
            north=lb_north,                           # Ladybug convention (CCW from +Y)
            high_density=False,                       # force Tregenza 145-patch grid
            ground_reflectance=ground_reflectance     # ground albedo (0–1)
        )

        # 3) Extract the cleaned per-patch direct and diffuse benefit values
        direct  = np.clip(np.asarray(sky.direct_values,  dtype=np.float32), 0.0, None)
        diffuse = np.clip(np.asarray(sky.diffuse_values, dtype=np.float32), 0.0, None)

        # 4) Sum them to get the total un-normalized weight per patch
        weights_np = direct + diffuse
        if weights_np.shape[0] != P:
            raise RuntimeError(
                f"SkyMatrix returned {weights_np.shape[0]} patches, expected {P}"
            )

        # 5) Convert to a torch tensor on the target device
        return torch.from_numpy(weights_np).to(device)

    raise ValueError(f"Unsupported weighting mode '{mode}' requested.")
