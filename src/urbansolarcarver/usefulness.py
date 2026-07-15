"""Physics-derived solar usefulness for benefit mode (ISO 13790 5R1C).

Implements the ISO 13790 Annex C simple hourly method ("5R1C" — five
conductances, one capacitance) and derives, by perturbation, the marginal
usefulness of solar gain at every hour of the year:

    benefit[t] = -dQ_heating / dPhi_sol(t)   in [0, 1]
    harm[t]    = +dQ_cooling / dPhi_sol(t)   in [0, 1]

The two series are written to a ``solar_usefulness.json`` artifact that
benefit mode can consume in place of its balance-point Heaviside filter.

Provenance: this is an independent implementation written directly from
the ISO 13790 Annex C equation set (not a fork or port of an existing
simulator). It is cross-validated against ETH Zurich's RC_BuildingSimulator
(MIT, https://github.com/architecture-building-systems/RC_BuildingSimulator;
Jayathissa et al., Applied Energy 202, 2017) on three archetype scenarios
(medium office, heavy masonry, light insulated) driven by the bundled
Golden TMY3 EPW: annual heating/cooling demand totals to ~1 Wh/year plus
hourly air/mass temperatures and demands at sampled hours, with the
oracle's derived conductances fed in directly so the hourly recurrence is
what is compared. Reference data: ``tests/data/oracle_5r1c_reference.json``;
regression: ``tests/test_usefulness.py``. Design, coefficient provenance,
and declared limitations: ``design/solar-usefulness.md``; user-level
documentation: ``docs/simulated-weights.md``.

This module is deliberately NumPy-only at import time (no torch, no
ladybug) so it stays usable as a standalone generator; the EPW-facing
helper imports Ladybug lazily.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Sequence, Tuple

import numpy as np

HOURS = 8760

# ISO 13790 fixed coupling coefficients (§7.2.2.2, §12.2.2)
H_IS = 3.45      # W/m²K — air ↔ surface node
H_MS = 9.1       # W/m²K — surface ↔ mass node
LAMBDA_AT = 4.5  # A_tot = LAMBDA_AT * floor_area

# ISO 13790 Table 12 — lumped mass classes per m² of floor area
MASS_CLASSES = {
    "very_light": (2.5, 80_000.0),
    "light":      (2.5, 110_000.0),
    "medium":     (2.5, 165_000.0),
    "heavy":      (3.0, 260_000.0),
    "very_heavy": (3.5, 370_000.0),
}


@dataclass(frozen=True)
class ZoneParams:
    """5R1C parameters, all conductances in W/K, capacitance in J/K.

    Use :meth:`from_archetype` to derive them from physical archetype
    inputs per the standard; tests may also construct directly from
    known conductances (e.g. oracle-derived values).
    """
    floor_area: float
    h_tr_em: float
    h_tr_w: float
    h_tr_is: float
    h_tr_ms: float
    h_ve: float
    c_m: float
    a_m: float
    a_t: float
    t_set_heating: float = 20.0
    t_set_cooling: float = 26.0

    @classmethod
    def from_archetype(
        cls,
        floor_area: float,
        volume: float,
        u_opaque: float,
        area_opaque: float,
        u_window: float,
        area_window: float,
        ach_vent: float,
        ach_infiltration: float,
        heat_recovery: float = 0.0,
        mass_class: str = "medium",
        t_set_heating: float = 20.0,
        t_set_cooling: float = 26.0,
    ) -> "ZoneParams":
        """Derive the network from archetype inputs per ISO 13790.

        - A_tot = 4.5 · A_f;  H_tr,is = 3.45 · A_tot
        - (A_m, C_m) from the Table-12 mass class
        - H_tr,ms = 9.1 · A_m
        - H_tr,em = 1 / (1/H_tr,op − 1/H_tr,ms)   (§12.2.2 serial split)
        - H_ve = 1200 · b_ek · V · ACH_tot/3600, with the heat-recovery
          adjustment b_ek = 1 − (ACH_vent/ACH_tot) · η_hr (Annex E).
        """
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
                f"(§12.2.2) — check U-values/areas or pick a heavier "
                f"mass class."
            )
        h_tr_em = 1.0 / (1.0 / h_tr_op - 1.0 / h_tr_ms)
        ach_tot = ach_vent + ach_infiltration
        if ach_tot <= 0:
            raise ValueError("Total air change rate must be positive")
        b_ek = 1.0 - (ach_vent / ach_tot) * heat_recovery
        h_ve = 1200.0 * b_ek * volume * ach_tot / 3600.0
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
    q_heating_wh: float
    q_cooling_wh: float
    t_air: np.ndarray      # (8760,) final air temperature per hour
    t_m: np.ndarray        # (8760,) mass temperature after each hour
    demand_w: np.ndarray   # (8760,) signed Phi_HC (heating +, cooling −)


def _hourly_constants(p: ZoneParams):
    """Precompute state-independent quantities of the C.4–C.11 chain."""
    h1 = 1.0 / (1.0 / p.h_ve + 1.0 / p.h_tr_is)          # C.6
    h2 = h1 + p.h_tr_w                                    # C.7
    h3 = 1.0 / (1.0 / h2 + 1.0 / p.h_tr_ms)               # C.8
    m_frac = p.a_m / p.a_t
    st_frac = 1.0 - m_frac - p.h_tr_w / (H_MS * p.a_t)    # C.2
    c_h = p.c_m / 3600.0
    denom_m = c_h + 0.5 * (h3 + p.h_tr_em)
    coef_prev = c_h - 0.5 * (h3 + p.h_tr_em)
    return h1, h2, h3, m_frac, st_frac, denom_m, coef_prev


def _air_temperature(p, consts, t_m_prev, t_e, phi_int, phi_sol, phi_hc):
    """One evaluation of the Annex C chain for a given HC power.

    Returns (theta_air, theta_m_next). All arguments broadcast; the
    heating/cooling power enters the air node (standard base case).
    """
    h1, h2, h3, m_frac, st_frac, denom_m, coef_prev = consts
    gains = 0.5 * phi_int + phi_sol
    phi_ia = 0.5 * phi_int + phi_hc                       # C.1 (+ HC to air)
    phi_st = st_frac * gains                              # C.2
    phi_m = m_frac * gains                                # C.3
    # C.5 — t_supply = t_e (no preheating)
    phi_m_tot = phi_m + p.h_tr_em * t_e + h3 * (
        phi_st + p.h_tr_w * t_e + h1 * (phi_ia / p.h_ve + t_e)
    ) / h2
    t_m_next = (t_m_prev * coef_prev + phi_m_tot) / denom_m   # C.4
    t_m_avg = 0.5 * (t_m_next + t_m_prev)                     # C.9
    t_s = (
        p.h_tr_ms * t_m_avg + phi_st + p.h_tr_w * t_e
        + h1 * (t_e + phi_ia / p.h_ve)
    ) / (p.h_tr_ms + p.h_tr_w + h1)                           # C.10
    t_air = (p.h_tr_is * t_s + p.h_ve * t_e + phi_ia) / (
        p.h_tr_is + p.h_ve
    )                                                          # C.11
    return t_air, t_m_next


def _march(p, t_out, phi_int, phi_sol_base, *, deltas: float | None = None,
           t_m_init: float = 20.0, record_series: bool = False):
    """March the year. Vectorized over trajectories.

    With ``deltas=None`` runs a single trajectory. With ``deltas=eps``
    runs 1 + 2·8760 trajectories: the base, then for each hour t a pair
    with ``phi_sol[t] ± eps`` (central differences for attribution)
    without materializing an (N, 8760) gain matrix.
    """
    consts = _hourly_constants(p)
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

    Parameters are hourly arrays of length 8760: outdoor dry-bulb [°C],
    internal gains [W], transmitted solar gains [W].
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


def solar_usefulness(p: ZoneParams, t_out, phi_int, phi_sol,
                     eps: float = 1.0,
                     t_m_init: float = 20.0) -> Tuple[np.ndarray, np.ndarray]:
    """Marginal hourly solar usefulness by central-difference perturbation.

    Returns ``(benefit, harm)``, each (8760,) in [0, 1]:
    the fraction of one extra watt-hour of solar gain at hour t that
    offsets heating demand / becomes cooling load over the year.

    Values are marginal at this archetype's operating point; hours at a
    control-regime switch produce subgradients (smoothed by the central
    difference). Small out-of-range values from switching noise are
    clipped; gross violations warn.
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
            warnings.warn(
                f"solar_usefulness: {name} outside [0, 1] beyond switching "
                f"tolerance (min {low:.3f}, max {high:.3f}) — check inputs.",
                stacklevel=2,
            )
    return np.clip(benefit, 0.0, 1.0), np.clip(harm, 0.0, 1.0)


# ---------------------------------------------------------------------------
# EPW-facing helper (lazy Ladybug import)
# ---------------------------------------------------------------------------

def transmitted_solar_from_epw(
    epw_path: str,
    windows: Sequence[Tuple[float, float, float]],
) -> np.ndarray:
    """Hourly transmitted solar gain [W] for a set of vertical windows.

    ``windows``: sequence of (azimuth_deg, area_m2, g_value); azimuth in
    Ladybug convention (0 = N, 90 = E, 180 = S, 270 = W). Irradiance from
    the EPW via Ladybug's isotropic directional model.
    """
    from ladybug.wea import Wea
    wea = Wea.from_epw_file(str(epw_path))
    total = np.zeros(HOURS)
    for azimuth, area, g in windows:
        irr, *_ = wea.directional_irradiance(0, float(azimuth))
        total += float(area) * float(g) * np.asarray(irr.values,
                                                     dtype=np.float64)
    return total


# ---------------------------------------------------------------------------
# Artifact I/O — solar_usefulness.json (schema_version 1)
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1


def write_usefulness(path, benefit, harm, meta: dict) -> Path:
    """Write the solar_usefulness.json artifact (schema in the design note)."""
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
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def read_usefulness(path) -> Tuple[np.ndarray, np.ndarray, dict]:
    """Read and validate a solar_usefulness.json artifact.

    Returns (benefit, harm, meta).
    """
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read usefulness artifact {path}: {exc}") from exc
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"{path}: unsupported usefulness schema_version {version!r} "
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

    - ``width``  — east-west dimension (m)
    - ``length`` — north-south dimension (m)
    - ``height`` — storey height (m)
    - ``wwr``    — window-to-wall ratio per facade, keyed by cardinal name
      (``north`` / ``east`` / ``south`` / ``west``); omitted sides get none
    - ``g_value`` — glazing solar transmittance for all windows (default 0.6)
    - ``orientation`` — degrees to rotate the box clockwise from north
      (optional, default 0)

    Derived: floor area = width x length; volume = floor area x height;
    per-facade window areas = wwr x facade area; ``area_opaque`` = opaque
    walls + roof (ground slab excluded); ``area_window`` = sum of windows.
    Archetypes without shoebox keys pass through unchanged.
    """
    keys = set(archetype)
    if not keys & _SHOEBOX_KEYS:
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
    g_value = float(arch.pop("g_value", 0.6))
    orientation = float(arch.pop("orientation", 0.0))

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

    arch["floor_area"] = width * length
    arch["volume"] = width * length * height
    arch["area_window"] = window_area
    # Opaque envelope = walls minus glazing, plus roof (slab-on-grade floor
    # is treated as adiabatic, consistent with the explicit-areas examples).
    arch["area_opaque"] = gross_walls - window_area + width * length
    arch["windows"] = windows
    return arch


def _save_heatmaps(benefit: np.ndarray, harm: np.ndarray, path) -> "Path | None":
    """Save the benefit/harm hourly series as day x hour heatmaps.

    Companion preview for the artifact. Returns the PNG path, or None
    when matplotlib is unavailable.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    days = HOURS // 24
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 3.6), sharey=True)
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
    plt.close(fig)
    return path


def generate_usefulness(
    epw_path: str,
    archetype: dict,
    out_path,
    internal_gains_w_m2: "float | Sequence[float]" = 5.0,
    eps: float = 1.0,
) -> Path:
    """Run the full 5R1C usefulness pipeline: EPW + archetype → artifact.

    ``archetype`` holds the :meth:`ZoneParams.from_archetype` keyword
    arguments plus ``windows``: a list of [azimuth_deg, area_m2, g_value].

    ``internal_gains_w_m2`` is either a single flat value or a 24-value
    daily occupancy profile [W/m² per hour of day], tiled over the year.
    """
    arch = expand_shoebox(archetype)
    windows = arch.pop("windows", None)
    if not windows:
        raise ValueError(
            "archetype must define 'windows' ([azimuth_deg, area_m2, g_value] "
            "entries) or shoebox geometry (width/length/height/wwr)"
        )
    params = ZoneParams.from_archetype(**arch)

    from ladybug.epw import EPW  # lazy
    epw = EPW(str(epw_path))
    t_out = np.asarray(epw.dry_bulb_temperature.values, dtype=np.float64)
    phi_sol = transmitted_solar_from_epw(epw_path, windows)

    gains = np.asarray(internal_gains_w_m2, dtype=np.float64)
    if gains.ndim == 0:
        phi_int = np.full(HOURS, float(gains) * params.floor_area)
    elif gains.shape == (24,):
        phi_int = np.tile(gains, HOURS // 24) * params.floor_area
    else:
        raise ValueError(
            "internal_gains_w_m2 must be a single value or a 24-value "
            f"daily profile, got shape {gains.shape}"
        )

    benefit, harm = solar_usefulness(params, t_out, phi_int, phi_sol, eps=eps)

    from datetime import datetime, timezone
    gains_meta = (float(gains) if gains.ndim == 0
                  else [float(v) for v in gains])
    meta = {
        "method": "iso13790-5r1c-perturbation",
        "epw": str(epw_path),
        "archetype": {**arch, "windows": [list(w) for w in windows],
                      "internal_gains_w_m2": gains_meta},
        "eps_w": eps,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "usc usefulness (iso13790-5r1c)",
    }
    artifact = write_usefulness(out_path, benefit, harm, meta)
    # Companion preview so users can inspect the weights without writing code.
    _save_heatmaps(benefit, harm, artifact.with_suffix(".png"))
    return artifact


# Backwards-compatible alias (original internal name)
generate_tier15 = generate_usefulness
