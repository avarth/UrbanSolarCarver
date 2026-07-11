# -*- coding: utf-8 -*-
"""Capture RC_BuildingSimulator (ETH, MIT) reference outputs for USC's
5R1C engine regression tests.

Weather: the bundled public-domain NREL TMY3 EPW (Golden, CO). Dry-bulb
and per-scenario transmitted solar are computed here ONCE (Ladybug EPW
parsing + isotropic directional irradiance on the scenario's glazing) and
stored verbatim in the reference JSON, so the engine tests replay the
exact driving arrays with no weather generation and no EPW dependency.

We record the zone's *derived* conductances (including its
h_tr_em = U*A convention) so USC's engine is fed identical H values —
comparing the Annex C recurrence, not parameter derivation.
DirectHeater/DirectCooler + AirConditioning emission keep demand == load
(no COP layer, all HC power to the air node).
"""
import json
import sys
from pathlib import Path

import numpy as np

ORACLE = Path(r"C:\Users\arisv\usc_oracle\rc_simulator")
sys.path.insert(0, str(ORACLE))

import supply_system
import emission_system
from building_physics import Zone

REPO = Path(r"C:\Users\arisv\RESEARCH_CENTER\ACTIVE_PROJECTS\RSBenvelope_generation\UrbanSolarCarver_clean")
EPW_PATH = REPO / "examples" / "weather" / "USA_CO_Golden-NREL.724666_TMY3.epw"
OUT = Path(__file__).parent / "oracle_reference.json"

# ---- Real weather: dry bulb + facade irradiance from the bundled EPW ----
from ladybug.epw import EPW
from ladybug.wea import Wea

epw = EPW(str(EPW_PATH))
t_out = np.asarray(epw.dry_bulb_temperature.values, dtype=np.float64)
wea = Wea.from_epw_file(str(EPW_PATH))

# Vertical facades (altitude 0), Ladybug azimuth: 0=N, 90=E, 180=S, 270=W.
FACADES = {"south": 180, "east": 90, "west": 270, "north": 0}
facade_irr = {}
for name, az in FACADES.items():
    total, _direct, _diff, _refl = wea.directional_irradiance(0, az)
    facade_irr[name] = np.asarray(total.values, dtype=np.float64)

# Office-like internal gains schedule [W], shared by all scenarios.
hod = np.arange(8760) % 24
internal = np.where((hod >= 8) & (hod < 20), 250.0, 60.0)

G_VALUE = 0.6  # glazing solar factor used for all scenarios

SCENARIOS = {
    # window_split: fraction of window_area per facade
    "medium_office": dict(window_area=8.0, walls_area=90.0, floor_area=35.0,
                          room_vol=105.0, total_internal_area=142.0,
                          u_walls=0.5, u_windows=1.8, ach_vent=1.2,
                          ach_infl=0.3, ventilation_efficiency=0.0,
                          thermal_capacitance_per_floor_area=165000,
                          t_set_heating=20.0, t_set_cooling=26.0,
                          window_split={"south": 0.5, "east": 0.25, "west": 0.25}),
    "heavy_masonry": dict(window_area=5.0, walls_area=100.0, floor_area=40.0,
                          room_vol=110.0, total_internal_area=160.0,
                          u_walls=1.2, u_windows=2.8, ach_vent=0.8,
                          ach_infl=0.5, ventilation_efficiency=0.0,
                          thermal_capacitance_per_floor_area=260000,
                          t_set_heating=20.0, t_set_cooling=26.0,
                          window_split={"south": 0.4, "east": 0.2,
                                        "west": 0.2, "north": 0.2}),
    "light_insulated": dict(window_area=10.0, walls_area=70.0, floor_area=30.0,
                            room_vol=90.0, total_internal_area=130.0,
                            u_walls=0.25, u_windows=1.0, ach_vent=1.5,
                            ach_infl=0.2, ventilation_efficiency=0.6,
                            thermal_capacitance_per_floor_area=110000,
                            t_set_heating=20.0, t_set_cooling=26.0,
                            window_split={"south": 0.6, "west": 0.4}),
}

sample_hours = [0, 12, 100, 500, 1234, 4000, 4380, 5000, 7000, 8759]

result = {
    "provenance": {
        "oracle": "RC_BuildingSimulator (ETH Zurich, MIT license), "
                  "github.com/architecture-building-systems/RC_BuildingSimulator",
        "weather": "USA_CO_Golden-NREL.724666_TMY3.epw (bundled, public domain); "
                   "dry bulb direct from EPW; transmitted solar = g * sum_f A_f * "
                   "I_f(t), I_f = Ladybug Wea.directional_irradiance (isotropic "
                   "sky) on vertical facades; g = 0.6.",
        "note": "h_tr_em uses the oracle's U*A convention; USC engine is fed "
                "these derived H values directly in tests. Driving arrays are "
                "stored verbatim below — tests replay them, never regenerate.",
    },
    "driving": {
        "t_out": [round(float(v), 3) for v in t_out],
        "internal_gains": [round(float(v), 1) for v in internal],
        # per-scenario transmitted solar filled in below
    },
    "scenarios": {},
}

for name, params in SCENARIOS.items():
    split = params.pop("window_split")
    solar = np.zeros(8760)
    for facade, frac in split.items():
        solar += params["window_area"] * frac * G_VALUE * facade_irr[facade]
    solar = solar.round(2)

    zone = Zone(heating_supply_system=supply_system.DirectHeater,
                cooling_supply_system=supply_system.DirectCooler,
                heating_emission_system=emission_system.AirConditioning,
                cooling_emission_system=emission_system.AirConditioning,
                **params)
    t_m_prev = 20.0
    q_h = 0.0
    q_c = 0.0
    hourly_samples = {}
    t_air_series = np.empty(8760)
    for hour in range(8760):
        zone.solve_energy(internal_gains=float(internal[hour]),
                          solar_gains=float(solar[hour]),
                          t_out=float(t_out[hour]),
                          t_m_prev=t_m_prev)
        t_m_prev = zone.t_m_next
        q_h += zone.heating_demand
        q_c += abs(zone.cooling_demand)
        t_air_series[hour] = zone.t_air
        if hour in sample_hours:
            hourly_samples[str(hour)] = {
                "t_air": round(float(zone.t_air), 6),
                "t_m_next": round(float(zone.t_m_next), 6),
                "heating_demand": round(float(zone.heating_demand), 6),
                "cooling_demand": round(float(zone.cooling_demand), 6),
            }
    result["driving"][f"solar_{name}"] = [float(v) for v in solar]
    result["scenarios"][name] = {
        "derived": {
            "h_tr_em": round(zone.h_tr_em, 9),
            "h_tr_w": round(zone.h_tr_w, 9),
            "h_tr_is": round(zone.h_tr_is, 9),
            "h_tr_ms": round(zone.h_tr_ms, 9),
            "h_ve_adj": round(zone.h_ve_adj, 9),
            "c_m": round(zone.c_m, 3),
            "mass_area": round(zone.mass_area, 6),
            "a_t": round(zone.A_t, 6),
            "floor_area": params["floor_area"],
            "t_set_heating": params["t_set_heating"],
            "t_set_cooling": params["t_set_cooling"],
        },
        "annual": {
            "Q_H_Wh": round(q_h, 3),
            "Q_C_Wh": round(q_c, 3),
            "t_air_mean": round(float(t_air_series.mean()), 6),
        },
        "hourly_samples": hourly_samples,
    }
    print(f"{name}: Q_H={q_h/1000:.1f} kWh  Q_C={q_c/1000:.1f} kWh  "
          f"t_air_mean={t_air_series.mean():.2f}")

OUT.write_text(json.dumps(result), encoding="utf-8")
print("wrote", OUT, f"({OUT.stat().st_size/1024:.0f} KB)")
