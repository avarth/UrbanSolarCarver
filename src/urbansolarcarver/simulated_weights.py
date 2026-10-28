"""Simulated benefit weights for benefit mode (ISO 13790 5R1C).

Implements the ISO 13790 Annex C simple hourly method ("5R1C": five
thermal conductances and one heat capacity, as an electrical-circuit
analogue of a single building zone) and derives, by perturbation, the
marginal benefit and harm of solar gain at every hour of the year:

    benefit[t] = -dQ_heating / dPhi_sol(t)   in [0, 1]
    harm[t]    = +dQ_cooling / dPhi_sol(t)   in [0, 1]

Q_heating and Q_cooling are the annual demands [Wh] and Phi_sol(t) is the
solar gain entering the zone in hour t [W].  The two series are written to
a ``simulated_weights.json`` artifact that benefit mode can use in place of
its balance-point Heaviside filter.

Provenance: this is an independent implementation written directly from
the ISO 13790 Annex C equation set (not a fork or port of an existing
simulator). It is cross-validated against ETH Zurich's RC_BuildingSimulator
(MIT, https://github.com/architecture-building-systems/RC_BuildingSimulator;
Jayathissa et al., Applied Energy 202, 2017) on three archetype scenarios
(medium office, heavy masonry, light insulated) driven by the bundled
Golden TMY3 EPW.  The reference simulator's derived conductances are fed
in directly, so the comparison tests the hourly recurrence: annual heating
and cooling demands agree within 1 Wh (or a relative 1e-6), and hourly air
and mass temperatures and demands agree at sampled hours.
Reference data: ``tests/data/oracle_5r1c_reference.json``;
regression: ``tests/test_simulated_weights.py``. Design, coefficient provenance,
and declared limitations: ``design/simulated-weights.md``; user-level
documentation: ``docs/simulated-weights.md``.

This module is deliberately NumPy-only at import time (no torch, no
ladybug) so it stays usable as a standalone generator; the EPW-facing
helper imports Ladybug lazily.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Sequence, Tuple

import numpy as np

from .archetype_defaults import ARCHETYPE_DEFAULTS, SHOEBOX_EXPOSURE_DEFAULTS
from .weather_file import read_weather_file

log = logging.getLogger(__name__)

HOURS = 8760

# ISO 13790 fixed coupling coefficients (§7.2.2.2, §12.2.2)
H_IS = 3.45      # W/m²K, air node to internal-surface node
H_MS = 9.1       # W/m²K, internal-surface node to mass node
LAMBDA_AT = 4.5  # A_tot = LAMBDA_AT * floor_area (area of all internal surfaces)

# ISO 13790 Table 12 mass classes: (A_m per m² floor area [m²/m²],
# C_m per m² floor area [J/(m²K)]), where A_m is the effective mass area and
# C_m the internal heat capacity.
MASS_CLASSES = {
    "very_light": (2.5, 80_000.0),
    "light":      (2.5, 110_000.0),
    "medium":     (2.5, 165_000.0),
    "heavy":      (3.0, 260_000.0),
    "very_heavy": (3.5, 370_000.0),
}


def nearest_mass_class(capacity_kj_m2k: float) -> str:
    """The Table-12 class whose C_m per m² floor is nearest to the given
    capacity [kJ/(m²K)]; on a tie the lighter class."""
    return min(MASS_CLASSES, key=lambda name: abs(
        MASS_CLASSES[name][1] / 1000.0 - float(capacity_kj_m2k)))


@dataclass(frozen=True)
class ZoneParams:
    """5R1C parameters: conductances (``h_*``) in W/K, ``c_m`` in J/K,
    areas (``floor_area``, ``a_m``, ``a_t``) in m², set-points in °C.

    ``h_tr_em`` is exterior to mass, ``h_tr_w`` windows, ``h_tr_is`` air to
    internal surfaces, ``h_tr_ms`` surfaces to mass, ``h_ve`` ventilation:
    one value, or an (8760,) array of one value per hour when the
    ventilation follows a schedule.

    Use :meth:`from_archetype` to derive them from physical archetype
    inputs per the standard; tests may also construct directly from
    known conductances (e.g. values from the reference simulator).
    """
    floor_area: float
    h_tr_em: float
    h_tr_w: float
    h_tr_is: float
    h_tr_ms: float
    h_ve: "float | np.ndarray"
    c_m: float
    a_m: float
    a_t: float
    t_set_heating: float = ARCHETYPE_DEFAULTS["t_set_heating"]
    t_set_cooling: float = ARCHETYPE_DEFAULTS["t_set_cooling"]

    @classmethod
    def from_archetype(
        cls,
        floor_area: float,
        volume: float,
        u_opaque: float,
        area_opaque: float,
        u_window: float,
        area_window: float,
        ach_vent: "float | Sequence[float]",
        ach_infiltration: float,
        heat_recovery: float = ARCHETYPE_DEFAULTS["heat_recovery"],
        mass_class: "str | None" = None,
        t_set_heating: float = ARCHETYPE_DEFAULTS["t_set_heating"],
        t_set_cooling: float = ARCHETYPE_DEFAULTS["t_set_cooling"],
        mass_capacity_kj_m2k: "float | None" = None,
    ) -> "ZoneParams":
        """Derive the network from archetype inputs per ISO 13790.

        - A_tot = 4.5 · A_f;  H_tr,is = 3.45 · A_tot
        - (A_m, C_m) from the Table-12 mass class, or, with
          ``mass_capacity_kj_m2k``, C_m = capacity · 1000 · A_f and A_m of
          the class nearest in capacity (the lighter one on a tie)
        - H_tr,ms = 9.1 · A_m
        - H_tr,op = U_opaque · A_opaque;  H_tr,w = U_window · A_window
        - H_tr,em = 1 / (1/H_tr,op − 1/H_tr,ms)   (§12.2.2 serial split)
        - H_ve = 1200 · b_ek · V · ACH_tot/3600, with 1200 J/(m³K) the
          volumetric heat capacity of air and the heat-recovery
          adjustment b_ek = 1 − (ACH_vent/ACH_tot) · η_hr (Annex E).

        Units: areas in m², ``volume`` in m³, U-values in W/(m²K), air
        change rates in 1/h, ``heat_recovery`` (η_hr) as a fraction 0-1,
        set-points in °C, ``mass_capacity_kj_m2k`` in kJ/(m²K) of floor.
        ``ach_vent`` is one value or 8760 hourly values (a ventilation
        schedule); then ``h_ve`` is hourly too, heat recovery applying to
        the ventilation part of each hour. ``mass_class`` defaults to the
        archetype default ("medium") when no capacity is given.

        Raises ValueError for an unknown ``mass_class``, for both
        ``mass_class`` and ``mass_capacity_kj_m2k``, for a capacity that
        is not positive, when H_tr,op >= H_tr,ms (the serial split would
        be negative or infinite), for an ``ach_vent`` that is neither one
        value nor 8760, or when the total air change rate is not positive
        (in any hour).
        """
        if mass_capacity_kj_m2k is not None:
            if mass_class is not None:
                raise ValueError("give either mass_class or "
                                 "mass_capacity_kj_m2k, not both")
            capacity = float(mass_capacity_kj_m2k)
            if not capacity > 0:
                raise ValueError(f"mass_capacity_kj_m2k must be positive, "
                                 f"got {mass_capacity_kj_m2k!r}")
            am_factor = MASS_CLASSES[nearest_mass_class(capacity)][0]
            cm_per_m2 = capacity * 1000.0
        else:
            if mass_class is None:
                mass_class = ARCHETYPE_DEFAULTS["mass_class"]
            if mass_class not in MASS_CLASSES:
                raise ValueError(
                    f"mass_class must be one of {sorted(MASS_CLASSES)}, "
                    f"got {mass_class!r}"
                )
            am_factor, cm_per_m2 = MASS_CLASSES[mass_class]
        a_t = LAMBDA_AT * floor_area
        a_m = am_factor * floor_area
        c_m = cm_per_m2 * floor_area
        h_tr_ms = H_MS * a_m
        h_tr_op = u_opaque * area_opaque
        if h_tr_op >= h_tr_ms:
            raise ValueError(
                f"Opaque conductance H_tr,op = {h_tr_op:g} W/K must be "
                f"below H_tr,ms = {h_tr_ms:g} W/K for the serial split "
                f"(§12.2.2). Check U-values/areas or pick a heavier "
                f"mass class."
            )
        h_tr_em = 1.0 / (1.0 / h_tr_op - 1.0 / h_tr_ms)
        vent = np.asarray(ach_vent, dtype=np.float64)
        if vent.ndim == 0:
            ach_vent = float(vent)
            ach_tot = ach_vent + ach_infiltration
            if ach_tot <= 0:
                raise ValueError("Total air change rate must be positive")
            b_ek = 1.0 - (ach_vent / ach_tot) * heat_recovery
            h_ve = 1200.0 * b_ek * volume * ach_tot / 3600.0
        elif vent.shape == (HOURS,):
            # The same formula hour by hour: infiltration is constant, the
            # ventilation follows its schedule.
            ach_tot = vent + ach_infiltration
            if (ach_tot <= 0).any():
                raise ValueError("Total air change rate must be positive "
                                 "in every hour")
            b_ek = 1.0 - (vent / ach_tot) * heat_recovery
            h_ve = 1200.0 * b_ek * volume * ach_tot / 3600.0
        else:
            raise ValueError(f"ach_vent must be a single value or {HOURS} "
                             f"hourly values, got shape {vent.shape}")
        return cls(
            floor_area=floor_area,
            h_tr_em=h_tr_em,
            h_tr_w=u_window * area_window,
            h_tr_is=H_IS * a_t,
            h_tr_ms=h_tr_ms,
            h_ve=h_ve,
            c_m=c_m,
            a_m=a_m,
            a_t=a_t,
            t_set_heating=t_set_heating,
            t_set_cooling=t_set_cooling,
        )


@dataclass
class SimulationResult:
    """Annual outcome of :func:`simulate` (single trajectory)."""
    q_heating_wh: float    # annual heating demand [Wh]
    q_cooling_wh: float    # annual cooling demand [Wh]
    t_air: np.ndarray      # (8760,) air temperature with heating/cooling applied [°C]
    t_m: np.ndarray        # (8760,) mass temperature at the end of each hour [°C]
    demand_w: np.ndarray   # (8760,) signed Phi_HC [W] (heating +, cooling −)


def _hourly_constants(p: ZoneParams):
    """Precompute the state-independent quantities of equations C.2-C.11.

    Returns (H_ve, H_tr,1, H_tr,2, H_tr,3, A_m/A_t, the surface-node share
    of the gains from C.2, and the two coefficients of the mass update
    C.4). With an hourly ``h_ve`` the ones that depend on it are (8760,)
    arrays; :func:`_constants_by_hour` gives the values of each hour.
    """
    h_ve = p.h_ve
    h1 = 1.0 / (1.0 / h_ve + 1.0 / p.h_tr_is)            # C.6
    h2 = h1 + p.h_tr_w                                    # C.7
    h3 = 1.0 / (1.0 / h2 + 1.0 / p.h_tr_ms)               # C.8
    m_frac = p.a_m / p.a_t
    st_frac = 1.0 - m_frac - p.h_tr_w / (H_MS * p.a_t)    # C.2
    c_h = p.c_m / 3600.0
    denom_m = c_h + 0.5 * (h3 + p.h_tr_em)
    coef_prev = c_h - 0.5 * (h3 + p.h_tr_em)
    return h_ve, h1, h2, h3, m_frac, st_frac, denom_m, coef_prev


def _constants_by_hour(consts):
    """The constants of :func:`_hourly_constants` hour by hour: a list of
    8760 tuples of floats, or None when none of them changes by the hour."""
    if not any(np.ndim(c) for c in consts):
        return None
    columns = [np.broadcast_to(np.asarray(c, dtype=np.float64), (HOURS,)).tolist()
               for c in consts]
    return list(zip(*columns))


def _air_temperature(p, consts, t_m_prev, t_e, phi_int, phi_sol, phi_hc):
    """One evaluation of the Annex C chain for a given heating/cooling power.

    Temperatures in °C, powers in W: ``t_m_prev`` is the mass temperature
    at the start of the hour, ``t_e`` the outdoor temperature, ``phi_int``
    the internal gains, ``phi_sol`` the solar gains and ``phi_hc`` the
    heating (+) or cooling (−) power.  ``consts`` are the constants of the
    hour (:func:`_constants_by_hour`).  Returns (theta_air, theta_m_next).
    All arguments broadcast; the heating/cooling power enters the air node
    (the standard's base case).
    """
    h_ve, h1, h2, h3, m_frac, st_frac, denom_m, coef_prev = consts
    gains = 0.5 * phi_int + phi_sol
    phi_ia = 0.5 * phi_int + phi_hc                       # C.1 (+ HC to air)
    phi_st = st_frac * gains                              # C.2
    phi_m = m_frac * gains                                # C.3
    # C.5, with supply-air temperature = t_e (no preheating)
    phi_m_tot = phi_m + p.h_tr_em * t_e + h3 * (
        phi_st + p.h_tr_w * t_e + h1 * (phi_ia / h_ve + t_e)
    ) / h2
    t_m_next = (t_m_prev * coef_prev + phi_m_tot) / denom_m   # C.4
    t_m_avg = 0.5 * (t_m_next + t_m_prev)                     # C.9
    t_s = (
        p.h_tr_ms * t_m_avg + phi_st + p.h_tr_w * t_e
        + h1 * (t_e + phi_ia / h_ve)
    ) / (p.h_tr_ms + p.h_tr_w + h1)                           # C.10
    t_air = (p.h_tr_is * t_s + h_ve * t_e + phi_ia) / (
        p.h_tr_is + h_ve
    )                                                          # C.11
    return t_air, t_m_next


def _march(p, t_out, phi_int, phi_sol_base, *, deltas: float | None = None,
           t_m_init: float = 20.0, record_series: bool = False):
    """Step through the 8760 hours of the year, vectorized over trajectories.

    With ``deltas=None`` runs a single trajectory. With ``deltas=eps`` [W]
    runs 1 + 2·8760 trajectories: row 0 is the base case, and for each
    hour t row 1 + 2t has ``phi_sol[t] + eps`` and row 2 + 2t has
    ``phi_sol[t] - eps`` (central differences for attribution).  The
    perturbed gains are built one hour at a time, so no (N, 8760) gain
    matrix is stored.

    Returns (q_h, q_c, series_air, series_tm, series_demand): annual
    heating and cooling demand [Wh] per trajectory (shape (N,)), and,
    when ``record_series`` is true, hourly air temperature, mass
    temperature and signed demand of row 0 (otherwise None).
    """
    consts = _hourly_constants(p)
    consts_by_hour = _constants_by_hour(consts)
    phi_10 = 10.0 * p.floor_area  # C.4.2 test load

    if deltas is None:
        n = 1
    else:
        n = 1 + 2 * HOURS
    t_m = np.full(n, float(t_m_init))
    q_h = np.zeros(n)
    q_c = np.zeros(n)
    series_air = np.empty(HOURS) if record_series else None
    series_tm = np.empty(HOURS) if record_series else None
    series_demand = np.empty(HOURS) if record_series else None

    for h in range(HOURS):
        if consts_by_hour is not None:
            consts = consts_by_hour[h]
        t_e = float(t_out[h])
        p_int = float(phi_int[h])
        if deltas is None:
            phi_sol = float(phi_sol_base[h])
        else:
            phi_sol = np.full(n, float(phi_sol_base[h]))
            phi_sol[1 + 2 * h] += deltas
            phi_sol[2 + 2 * h] -= deltas

        # Step 1: free-float (C.4.2)
        t_air_0, _ = _air_temperature(p, consts, t_m, t_e, p_int, phi_sol, 0.0)
        heat = t_air_0 < p.t_set_heating
        cool = t_air_0 > p.t_set_cooling

        # Step 2: 10 W/m² test load and linear interpolation to set-point.
        # The system is affine in phi_hc, so the interpolation is exact.
        # Heating and cooling power is unlimited (no maximum-capacity check).
        t_air_10, _ = _air_temperature(p, consts, t_m, t_e, p_int, phi_sol,
                                       phi_10)
        slope = t_air_10 - t_air_0
        t_set = np.where(heat, p.t_set_heating, p.t_set_cooling)
        with np.errstate(divide="ignore", invalid="ignore"):
            phi_nd = phi_10 * (t_set - t_air_0) / slope
        phi_nd = np.where(heat | cool, phi_nd, 0.0)

        # Final evaluation with the applied power advances the state.
        t_air, t_m = _air_temperature(p, consts, t_m, t_e, p_int, phi_sol,
                                      phi_nd)
        q_h += np.maximum(phi_nd, 0.0)
        q_c += np.maximum(-phi_nd, 0.0)
        if record_series:
            series_air[h] = t_air if np.isscalar(t_air) else t_air[0]
            series_tm[h] = t_m if np.isscalar(t_m) else t_m[0]
            series_demand[h] = phi_nd if np.isscalar(phi_nd) else phi_nd[0]

    return q_h, q_c, series_air, series_tm, series_demand


def simulate(p: ZoneParams, t_out, phi_int, phi_sol,
             t_m_init: float = 20.0) -> SimulationResult:
    """Annual 5R1C simulation of a single zone (Wh demands, °C series).

    ``t_out``, ``phi_int`` and ``phi_sol`` are hourly arrays of length
    8760: outdoor dry-bulb [°C], internal gains [W], transmitted solar
    gains [W].  ``t_m_init`` is the mass temperature at the start of the
    year [°C].  Raises ValueError if an array does not have shape (8760,).
    """
    t_out = np.asarray(t_out, dtype=np.float64)
    phi_int = np.asarray(phi_int, dtype=np.float64)
    phi_sol = np.asarray(phi_sol, dtype=np.float64)
    for name, arr in (("t_out", t_out), ("phi_int", phi_int),
                      ("phi_sol", phi_sol)):
        if arr.shape != (HOURS,):
            raise ValueError(f"{name} must have shape ({HOURS},), "
                             f"got {arr.shape}")
    q_h, q_c, s_air, s_tm, s_dem = _march(
        p, t_out, phi_int, phi_sol, t_m_init=t_m_init, record_series=True
    )
    return SimulationResult(
        q_heating_wh=float(q_h[0]),
        q_cooling_wh=float(q_c[0]),
        t_air=s_air, t_m=s_tm, demand_w=s_dem,
    )


def attribute_solar_gains(p: ZoneParams, t_out, phi_int, phi_sol,
                     eps: float = 1.0,
                     t_m_init: float = 20.0) -> Tuple[np.ndarray, np.ndarray]:
    """Marginal hourly benefit/harm of solar gain by central-difference perturbation.

    Returns ``(benefit, harm)``, each (8760,) in [0, 1]:
    the fraction of one extra watt-hour of solar gain at hour t that
    offsets heating demand / becomes cooling load over the year.
    ``eps`` is the perturbation size [W]; the other arguments are as in
    :func:`simulate`.

    Values are marginal at this archetype's operating point.  At hours
    where the control switches between heating, free-floating and
    cooling, the derivative is not defined and the central difference
    gives an average of the one-sided slopes.  Out-of-range values up to
    0.02 from such switching are clipped silently; larger ones are also
    clipped but trigger a warning.
    """
    t_out = np.asarray(t_out, dtype=np.float64)
    phi_int = np.asarray(phi_int, dtype=np.float64)
    phi_sol = np.asarray(phi_sol, dtype=np.float64)
    q_h, q_c, *_ = _march(p, t_out, phi_int, phi_sol, deltas=float(eps),
                          t_m_init=t_m_init)
    d_qh = (q_h[1::2] - q_h[2::2]) / (2.0 * eps)   # +eps rows minus −eps rows
    d_qc = (q_c[1::2] - q_c[2::2]) / (2.0 * eps)
    benefit = -d_qh
    harm = d_qc
    tol = 0.02
    for name, arr in (("benefit", benefit), ("harm", harm)):
        low, high = float(arr.min()), float(arr.max())
        if low < -tol or high > 1.0 + tol:
            log.warning(
                "attribute_solar_gains: %s outside [0, 1] beyond switching "
                "tolerance (min %.3f, max %.3f); check inputs.", name, low, high,
            )
    return np.clip(benefit, 0.0, 1.0), np.clip(harm, 0.0, 1.0)


# ---------------------------------------------------------------------------
# EPW-facing helper (lazy Ladybug import)
# ---------------------------------------------------------------------------

def transmitted_solar_from_epw(
    epw_path: str,
    windows: Sequence[Tuple[float, float, float]],
    hourly_factors: "Sequence[np.ndarray] | None" = None,
) -> np.ndarray:
    """Hourly transmitted solar gain [W] for a set of vertical windows.

    ``windows``: sequence of (azimuth_deg, area_m2, g_value); azimuth in
    Ladybug convention (0 = N, 90 = E, 180 = S, 270 = W); g_value is the
    glazing's total solar energy transmittance (0-1).  The irradiance on
    each window plane [W/m²] comes from Ladybug's
    ``Wea.directional_irradiance`` for a vertical surface (isotropic sky,
    ground reflectance 0.2, no obstructions); it is multiplied by
    area and g_value.

    ``hourly_factors``: optional per-window hourly transmission multipliers
    (one (8760,) array per window, e.g. shading coefficients); default 1.

    Returns an (8760,) array of the summed gain over all windows [W].
    """
    return _summed_gains(_window_gains(epw_path, windows), hourly_factors)


def _window_gains(epw_path: str, windows) -> list:
    """The unshaded hourly gain of each window [W]: area x g x irradiance on
    its plane, one (8760,) array per window (see transmitted_solar_from_epw)."""
    wea = read_weather_file(epw_path).solar_irradiance_wea()
    gains = []
    for azimuth, area, g in windows:
        irr, *_ = wea.directional_irradiance(0, float(azimuth))
        gains.append(float(area) * float(g) * np.asarray(
            irr.values, dtype=np.float64))
    return gains


def _summed_gains(window_gains, hourly_factors=None) -> np.ndarray:
    """The sum of the windows' gains, each times its hourly factors if any."""
    total = np.zeros(HOURS)
    for i, contribution in enumerate(window_gains):
        if hourly_factors is not None:
            contribution = contribution * hourly_factors[i]
        total += contribution
    return total


def sun_up_hours(epw_path: str) -> np.ndarray:
    """(8760,) array of 0 and 1: 1 for the hours with the sun above the
    horizon at the weather file's site.

    The sun is placed as :func:`transmitted_solar_from_epw` places it: by a
    Ladybug Sunpath at the middle of each hour (the Wea's datetimes).
    """
    from ladybug.sunpath import Sunpath
    wea = read_weather_file(epw_path).solar_irradiance_wea()
    sunpath = Sunpath.from_location(wea.location)
    sunpath.is_leap_year = wea.is_leap_year
    return np.array([1 if sunpath.calculate_sun_from_date_time(moment).altitude > 0 else 0
                     for moment in wea.datetimes], dtype=np.int8)


# ---------------------------------------------------------------------------
# Shading coefficients (declared multipliers; no shading-device geometry is modelled)
# ---------------------------------------------------------------------------

# Zero-based day of year on which each month starts (non-leap TMY year).
_MONTH_START_DAY = np.cumsum([0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30])

_CARDINALS = ("north", "east", "south", "west")


def _nearest_cardinal(azimuth_deg: float) -> str:
    """Bin an azimuth to the nearest cardinal facade name."""
    a = float(azimuth_deg) % 360.0
    return _CARDINALS[int(((a + 45.0) % 360.0) // 90.0)]


def _normalize_shading(value, name: str) -> dict:
    """Normalize a shading coefficient (scalar or per-facade mapping).

    Returns a full {north/east/south/west: float} mapping; facades absent
    from a mapping default to 1.0 (no shading). Values are transmission
    multipliers in [0, 1].
    """
    if isinstance(value, dict):
        unknown = set(value) - set(_CARDINALS)
        if unknown:
            raise ValueError(f"{name}: facade keys must be one of "
                             f"{list(_CARDINALS)}, got {sorted(unknown)}")
        out = {side: float(value.get(side, 1.0)) for side in _CARDINALS}
    else:
        out = {side: float(value) for side in _CARDINALS}
    for side, v in out.items():
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"{name}[{side}] must be a transmission "
                             f"multiplier in [0, 1], got {v}")
    return out


def _hot_months_mask(hot_months: Sequence[int]) -> np.ndarray:
    """(8760,) bool mask: True during the given calendar months (1-12)."""
    months = sorted({int(m) for m in hot_months})
    if not months or not all(1 <= m <= 12 for m in months):
        raise ValueError(f"hot_months must be month numbers 1-12, "
                         f"got {list(hot_months)}")
    day_of_year = np.arange(HOURS) // 24
    month_of_day = np.searchsorted(_MONTH_START_DAY[1:], day_of_year,
                                   side="right") + 1
    return np.isin(month_of_day, months)


def _hot_period_mask(period: Sequence[int]) -> np.ndarray:
    """(8760,) bool mask: True from the first to the last day of the period.

    ``period`` is [first_day, last_day], days of the year 1-365, both
    included; a first day after the last wraps the new year (e.g.
    [335, 59] is 1 December to 28 February).
    """
    try:
        first, last = period
    except (TypeError, ValueError):
        raise ValueError(f"shading_hot_period must be [first_day, last_day], "
                         f"got {period!r}") from None
    if not all(isinstance(day, (int, np.integer)) and not isinstance(day, bool)
               and 1 <= day <= HOURS // 24 for day in (first, last)):
        raise ValueError(f"shading_hot_period days must be whole days of the "
                         f"year 1-{HOURS // 24}, got {list(period)}")
    day_of_year = np.arange(HOURS) // 24 + 1
    if first <= last:
        return (day_of_year >= first) & (day_of_year <= last)
    return (day_of_year >= first) | (day_of_year <= last)


def _shading_factors(windows, shading_permanent, shading_hot, hot_months,
                     hot_period=None):
    """Per-window hourly transmission factors from the declared coefficients.

    Each window is binned to its nearest cardinal facade. The permanent
    factor applies to all hours; during ``hot_months``, or during the days
    of ``hot_period`` ([first_day, last_day], see :func:`_hot_period_mask`),
    the hot factor multiplies on top of it. Returns a list of (8760,)
    arrays, or None when no shading is declared.
    """
    if hot_months is not None and hot_period is not None:
        raise ValueError("give either hot_months or shading_hot_period, "
                         "not both")
    if shading_hot is not None and hot_months is None and hot_period is None:
        raise ValueError("shading_hot requires hot_months (the calendar "
                         "months when the seasonal shading is deployed) or "
                         "shading_hot_period (its first and last day)")
    if hot_months is not None and shading_hot is None:
        raise ValueError("hot_months has no effect without shading_hot")
    if hot_period is not None and shading_hot is None:
        raise ValueError("shading_hot_period has no effect without "
                         "shading_hot")
    if shading_permanent is None and shading_hot is None:
        return None

    permanent = _normalize_shading(
        shading_permanent if shading_permanent is not None else 1.0,
        "shading_permanent")
    factors = []
    hot_mask = None
    if shading_hot is not None:
        hot_mask = (_hot_months_mask(hot_months) if hot_months is not None
                    else _hot_period_mask(hot_period))
    hot = (_normalize_shading(shading_hot, "shading_hot")
           if shading_hot is not None else None)
    for azimuth, _area, _g in windows:
        side = _nearest_cardinal(azimuth)
        series = np.full(HOURS, permanent[side])
        if hot is not None:
            series = np.where(hot_mask, series * hot[side], series)
        factors.append(series)
    return factors


# ---------------------------------------------------------------------------
# Artifact I/O: simulated_weights.json (schema_version 1)
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1


def write_simulated_weights(path, benefit, harm, meta: dict) -> Path:
    """Write the simulated_weights.json artifact and return its path.

    The schema is described in ``design/simulated-weights.md``.  Values are
    rounded to 6 decimals.  Raises ValueError if either series is not 8760
    finite values in [0, 1].
    """
    benefit = np.asarray(benefit, dtype=np.float64)
    harm = np.asarray(harm, dtype=np.float64)
    _validate_series("benefit", benefit)
    _validate_series("harm", harm)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "meta": meta,
        "hourly": {
            "benefit": [round(float(v), 6) for v in benefit],
            "harm": [round(float(v), 6) for v in harm],
        },
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def read_simulated_weights(path) -> Tuple[np.ndarray, np.ndarray, dict]:
    """Read and validate a simulated_weights.json artifact.

    Returns (benefit, harm, meta): two (8760,) float64 arrays and the
    metadata dict.  Raises ValueError if the file cannot be read or parsed,
    has an unsupported schema_version, or holds invalid series.
    """
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read simulated-weights artifact {path}: {exc}") from exc
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"{path}: unsupported simulated-weights schema_version {version!r} "
            f"(expected {SCHEMA_VERSION})"
        )
    hourly = payload.get("hourly") or {}
    benefit = np.asarray(hourly.get("benefit", ()), dtype=np.float64)
    harm = np.asarray(hourly.get("harm", ()), dtype=np.float64)
    _validate_series(f"{path}: benefit", benefit)
    _validate_series(f"{path}: harm", harm)
    return benefit, harm, dict(payload.get("meta") or {})


def _validate_series(name: str, arr: np.ndarray) -> None:
    if arr.shape != (HOURS,):
        raise ValueError(f"{name}: expected {HOURS} hourly values, "
                         f"got shape {arr.shape}")
    if not np.isfinite(arr).all():
        raise ValueError(f"{name}: contains non-finite values")
    if arr.min() < 0.0 or arr.max() > 1.0:
        raise ValueError(f"{name}: values must lie in [0, 1] "
                         f"(min {arr.min():.4f}, max {arr.max():.4f})")


# ---------------------------------------------------------------------------
# Generator orchestration
# ---------------------------------------------------------------------------

_SHOEBOX_KEYS = frozenset({"width", "length", "height"})
# Keys that only the shoebox form takes besides its dimensions.
_SHOEBOX_EXTRA_KEYS = frozenset({"wwr", "g_value", "orientation", "u_wall",
                                 "u_roof", "u_floor", "roof_exposed",
                                 "floor_exposed"})
_EXPLICIT_KEYS = frozenset({"floor_area", "volume", "area_opaque",
                            "area_window", "windows"})
_FACADES = {  # cardinal name -> (azimuth_deg, horizontal-extent key)
    "north": (0.0, "width"),
    "east": (90.0, "length"),
    "south": (180.0, "width"),
    "west": (270.0, "length"),
}


def expand_shoebox(archetype: dict) -> dict:
    """Expand the shoebox geometry shorthand into explicit archetype areas.

    Instead of ``floor_area`` / ``volume`` / ``area_opaque`` / ``area_window``
    / ``windows``, an archetype may describe a rectangular single-zone box:

    - ``width``: east-west dimension (m)
    - ``length``: north-south dimension (m)
    - ``height``: storey height (m)
    - ``wwr``: window-to-wall ratio per facade in [0, 1), keyed by cardinal
      name (``north`` / ``east`` / ``south`` / ``west``); omitted sides get
      no window
    - ``g_value``: glazing solar transmittance for all windows (default 0.6)
    - ``orientation``: degrees to rotate the box clockwise from north
      (optional, default 0)
    - ``roof_exposed`` (default true) and ``floor_exposed`` (default
      false): whether the roof and the floor lose heat to the outside; a
      roof or floor that is not exposed is adiabatic (a storey between
      others, or a slab whose ground loss is left out)
    - the opaque U values: either ``u_opaque``, one U for the walls and
      the exposed roof and floor, or ``u_wall`` with ``u_roof`` (needed
      when the roof is exposed) and ``u_floor`` (needed when the floor is
      exposed)

    Derived: floor area = width x length; volume = floor area x height;
    per-facade window areas = wwr x facade area; ``area_opaque`` = opaque
    walls + the exposed roof and floor; ``area_window`` = sum of windows.
    With ``u_wall``, ``u_opaque`` is the area-weighted U of that opaque
    area, so H_tr,op = u_wall x opaque walls + u_roof x roof (if exposed)
    + u_floor x floor (if exposed).
    Archetypes without any of the shoebox keys above are returned as an
    unchanged copy.

    Raises ValueError if the shoebox keys are incomplete, mixed with
    explicit-area keys, non-positive, or define no window; for both
    ``u_opaque`` and ``u_wall``, for ``u_roof``/``u_floor`` without
    ``u_wall``, for a missing U of an exposed roof or floor, or for an
    exposure that is not true or false.
    """
    keys = set(archetype)
    if not keys & (_SHOEBOX_KEYS | _SHOEBOX_EXTRA_KEYS):
        return dict(archetype)
    if not keys >= _SHOEBOX_KEYS:
        missing = sorted(_SHOEBOX_KEYS - keys)
        raise ValueError(f"shoebox archetype is missing {missing}")
    if keys & _EXPLICIT_KEYS:
        raise ValueError(
            "give either shoebox geometry (width/length/height/wwr) or "
            f"explicit areas ({sorted(keys & _EXPLICIT_KEYS)}), not both"
        )

    arch = dict(archetype)
    width = float(arch.pop("width"))
    length = float(arch.pop("length"))
    height = float(arch.pop("height"))
    if min(width, length, height) <= 0:
        raise ValueError("shoebox width, length and height must be positive")
    wwr = arch.pop("wwr", None) or {}
    g_value = float(arch.pop("g_value", ARCHETYPE_DEFAULTS["g_value"]))
    orientation = float(arch.pop("orientation", ARCHETYPE_DEFAULTS["orientation"]))
    exposed = {}
    for part in ("roof", "floor"):
        value = arch.pop(f"{part}_exposed", SHOEBOX_EXPOSURE_DEFAULTS[f"{part}_exposed"])
        if not isinstance(value, bool):
            raise ValueError(f"{part}_exposed must be true or false, got {value!r}")
        exposed[part] = value
    u_wall = arch.pop("u_wall", None)
    u_roof = arch.pop("u_roof", None)
    u_floor = arch.pop("u_floor", None)
    if u_wall is not None and "u_opaque" in arch:
        raise ValueError("give either u_opaque (one U for walls, roof and "
                         "floor) or u_wall with u_roof and u_floor, not both")
    if u_wall is None and (u_roof is not None or u_floor is not None):
        raise ValueError("u_roof and u_floor go with u_wall (use u_opaque "
                         "for one U of the whole opaque envelope)")
    if u_wall is not None:
        for part, value in (("roof", u_roof), ("floor", u_floor)):
            if exposed[part] and value is None:
                raise ValueError(f"u_{part} is needed when {part}_exposed is "
                                 f"true (or set {part}_exposed: false)")
        for name, value in (("u_wall", u_wall), ("u_roof", u_roof), ("u_floor", u_floor)):
            if value is not None and not float(value) > 0:
                raise ValueError(f"{name} must be positive, got {value!r}")

    unknown = set(wwr) - set(_FACADES)
    if unknown:
        raise ValueError(f"wwr keys must be one of {sorted(_FACADES)}, "
                         f"got {sorted(unknown)}")

    dims = {"width": width, "length": length}
    windows, window_area, gross_walls = [], 0.0, 0.0
    for name, (azimuth, extent_key) in _FACADES.items():
        facade_area = dims[extent_key] * height
        gross_walls += facade_area
        ratio = float(wwr.get(name, 0.0))
        if not 0.0 <= ratio < 1.0:
            raise ValueError(f"wwr[{name}] must be in [0, 1), got {ratio}")
        if ratio > 0.0:
            area = ratio * facade_area
            windows.append([(azimuth + orientation) % 360.0, area, g_value])
            window_area += area
    if not windows:
        raise ValueError("shoebox archetype has no windows: set wwr for at "
                         "least one facade")

    floor_area = width * length
    arch["floor_area"] = floor_area
    arch["volume"] = floor_area * height
    arch["area_window"] = window_area
    # Opaque envelope = walls minus glazing, plus the roof and the floor
    # when exposed (by default the roof is and the slab-on-grade floor is
    # adiabatic, consistent with the explicit-areas examples).
    opaque_walls = gross_walls - window_area
    arch["area_opaque"] = (opaque_walls
                           + (floor_area if exposed["roof"] else 0.0)
                           + (floor_area if exposed["floor"] else 0.0))
    if u_wall is not None:
        h_tr_op = (float(u_wall) * opaque_walls
                   + (float(u_roof) * floor_area if exposed["roof"] else 0.0)
                   + (float(u_floor) * floor_area if exposed["floor"] else 0.0))
        arch["u_opaque"] = h_tr_op / arch["area_opaque"]
    arch["windows"] = windows
    return arch


def _save_heatmaps(benefit: np.ndarray, harm: np.ndarray, path) -> "Path | None":
    """Save the benefit/harm hourly series as day x hour heatmaps.

    Companion preview for the artifact. Returns the PNG path, or None
    when matplotlib is unavailable.

    Uses the object-oriented Figure API rather than pyplot: rendering to a
    PNG must never trigger interactive-backend resolution (a broken or
    display-less GUI toolkit would make artifact generation fail).
    """
    try:
        from matplotlib.figure import Figure
    except ImportError:
        return None
    days = HOURS // 24
    fig = Figure(figsize=(13, 3.6))
    ax1, ax2 = fig.subplots(1, 2, sharey=True)
    for ax, series, title, cmap in (
        (ax1, benefit, "benefit: marginal solar offsets HEATING", "YlOrRd"),
        (ax2, harm, "harm: marginal solar becomes COOLING load", "PuBu"),
    ):
        im = ax.imshow(series.reshape(days, 24).T, aspect="auto",
                       origin="lower", cmap=cmap, vmin=0.0, vmax=1.0)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("day of year")
        fig.colorbar(im, ax=ax)
    ax1.set_ylabel("hour of day")
    fig.tight_layout()
    path = Path(path)
    fig.savefig(str(path), bbox_inches="tight", dpi=120)
    return path


def generate_simulated_weights(
    epw_path: str,
    archetype: dict,
    out_path,
    internal_gains_w_m2: "float | Sequence[float] | None" = None,
    eps: float = 1.0,
) -> Path:
    """Run the full 5R1C weights pipeline: EPW + archetype → artifact.

    ``archetype`` holds the :meth:`ZoneParams.from_archetype` keyword
    arguments plus ``windows``: a list of [azimuth_deg, area_m2, g_value]
    (or the shoebox geometry shorthand, see :func:`expand_shoebox`).
    Optional keys: ``shading_permanent``, ``shading_hot`` and
    ``hot_months`` or ``shading_hot_period`` (transmission multipliers,
    see :func:`_shading_factors`), and the internal-gain keys below.
    ``ach_vent`` may be 8760 hourly values (see
    :meth:`ZoneParams.from_archetype`).

    Internal gains are either a single flat value [W/m²], a 24-value
    daily occupancy profile [W/m² per hour of day], tiled over the year,
    or 8760 hourly values from 1 January 0:00.
    They may come from the ``internal_gains_w_m2`` /
    ``internal_gains_profile_w_m2`` archetype keys, or be passed as the
    ``internal_gains_w_m2`` argument (which takes precedence). Default 5.0.

    ``eps`` is the solar-gain perturbation [W] used by
    :func:`attribute_solar_gains`.  Writes the JSON artifact to
    ``out_path`` and, if matplotlib is installed, a heatmap PNG next to it
    with the same name; returns the artifact path.  The artifact's meta
    also holds the zone's annual heating and cooling demand per m² of floor
    (``heating_kwh_m2``, ``cooling_kwh_m2``, in kWh/m²), from
    :func:`simulate` with the same gains, and ``sun_up``, 8760 values of
    0 or 1 marking the hours with the sun above the horizon
    (:func:`sun_up_hours`).
    """
    arch = expand_shoebox(archetype)
    profile = arch.pop("internal_gains_profile_w_m2", None)
    flat = arch.pop("internal_gains_w_m2", None)
    if internal_gains_w_m2 is None:
        if profile is not None and flat is not None:
            raise ValueError(
                "archetype: specify either internal_gains_w_m2 or "
                "internal_gains_profile_w_m2, not both"
            )
        internal_gains_w_m2 = (profile if profile is not None
                               else flat if flat is not None
                               else ARCHETYPE_DEFAULTS["internal_gains_w_m2"])
    shading_permanent = arch.pop("shading_permanent", None)
    shading_hot = arch.pop("shading_hot", None)
    hot_months = arch.pop("hot_months", None)
    hot_period = arch.pop("shading_hot_period", None)
    windows = arch.pop("windows", None)
    if not windows:
        raise ValueError(
            "archetype must define 'windows' ([azimuth_deg, area_m2, g_value] "
            "entries) or shoebox geometry (width/length/height/wwr)"
        )
    shading = _shading_factors(windows, shading_permanent, shading_hot,
                               hot_months, hot_period)
    params = ZoneParams.from_archetype(**arch)

    t_out = read_weather_file(epw_path).dry_bulb_temperature()
    # The irradiance of each window is computed once (Ladybug's transposition
    # takes about 0.25 s a window) for the shaded and the unshaded sums.
    window_gains = _window_gains(epw_path, windows)
    phi_sol = _summed_gains(window_gains, shading)
    if shading is not None:
        # Effective shading factor per hour (shaded / unshaded gain).  Benefit
        # mode applies the weights to unshaded sky irradiance, so the weight
        # per transmitted watt-hour must be reduced by the same shading.
        unshaded = _summed_gains(window_gains)
        f_eff = np.divide(phi_sol, unshaded,
                          out=np.ones(HOURS), where=unshaded > 0.0)

    gains = np.asarray(internal_gains_w_m2, dtype=np.float64)
    if gains.ndim == 0:
        phi_int = np.full(HOURS, float(gains) * params.floor_area)
    elif gains.shape == (24,):
        phi_int = np.tile(gains, HOURS // 24) * params.floor_area
    elif gains.shape == (HOURS,):
        phi_int = gains * params.floor_area
    else:
        raise ValueError(
            "internal_gains_w_m2 must be a single value, a 24-value "
            f"daily profile or {HOURS} hourly values, got shape {gains.shape}"
        )

    benefit, harm = attribute_solar_gains(params, t_out, phi_int, phi_sol, eps=eps)
    # The annual demand of the zone as given (shaded solar and internal gains),
    # recorded so a reader need not simulate again.
    base = simulate(params, t_out, phi_int, phi_sol)
    if shading is not None:
        # Only the fraction f_eff of an extra unshaded watt-hour reaches the
        # zone; scale the attribution accordingly (f_eff <= 1, so the
        # [0, 1] bounds are preserved).
        benefit = benefit * f_eff
        harm = harm * f_eff

    from datetime import datetime, timezone
    gains_meta = (float(gains) if gains.ndim == 0
                  else [float(v) for v in gains])
    arch_meta = {**arch, "windows": [list(w) for w in windows],
                 "internal_gains_w_m2": gains_meta}
    if np.ndim(arch.get("ach_vent")):
        arch_meta["ach_vent"] = [float(v) for v in arch["ach_vent"]]
    if shading_permanent is not None:
        arch_meta["shading_permanent"] = shading_permanent
    if shading_hot is not None:
        arch_meta["shading_hot"] = shading_hot
        if hot_months is not None:
            arch_meta["hot_months"] = [int(m) for m in hot_months]
        else:
            arch_meta["shading_hot_period"] = [int(d) for d in hot_period]
    meta = {
        "method": "iso13790-5r1c-perturbation",
        "epw": str(epw_path),
        "archetype": arch_meta,
        "eps_w": eps,
        "heating_kwh_m2": base.q_heating_wh / 1000.0 / params.floor_area,
        "cooling_kwh_m2": base.q_cooling_wh / 1000.0 / params.floor_area,
        "sun_up": [int(v) for v in sun_up_hours(epw_path)],
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "usc simulate-weights (iso13790-5r1c)",
    }
    artifact = write_simulated_weights(out_path, benefit, harm, meta)
    # Companion preview so users can inspect the weights without writing code.
    _save_heatmaps(benefit, harm, artifact.with_suffix(".png"))
    return artifact

