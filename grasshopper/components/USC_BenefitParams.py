"""USC Benefit Parameters — Control benefit-mode hour weighting.

Only used when mode = "benefit". Two weightings are available:

Simple weights (default): the balance temperature is the outdoor air
temperature at which a building is 'free-running' — it needs neither
heating nor cooling. Solar gains are credited only in hours colder than
balance_temperature - balance_offset (they offset heating demand);
warmer hours are simply not counted.

Simulated weights: connect a simulated_weights.json artifact (from
USC_SimulateWeights or `usc simulate-weights`) to replace the balance
rule with hourly weights from an ISO 13790 5R1C building simulation
(thermal lag, mass state). balance_* are then unused.

Inputs
------
balance_temperature : float, optional
    Balance-point temperature in degrees Celsius. Default: 15.0
balance_offset : float, optional
    Dead-band below the balance point in degrees Celsius. Default: 2.0
simulated_weights_path : str, optional
    Path to a simulated_weights.json artifact. When set, replaces the
    balance-point rule with the simulated hourly weights.
include_harm : bool, optional
    EXPERIMENTAL. Subtract summer-overheating (harm) contributions per
    sky patch. With simulated weights this uses the artifact's harm
    series; without, Ladybug's hot-hour composite. Default: False.

Outputs
-------
overrides : str
    Semicolon-joined key=value pairs for Config's overrides input.
"""

try:
    ghenv.Component.Name = "USC Benefit Params"
    ghenv.Component.NickName = "USC_Benefit"
    ghenv.Component.Description = "Sets benefit-mode hour weighting. Simple weights: balance-point temperature rule (solar gains credited in hours below balance - offset). Simulated weights: connect a simulated_weights.json artifact (USC_SimulateWeights) to weight hours by an ISO 13790 5R1C building simulation instead — captures thermal lag and mass state."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("balance_temperature", "Balance-point temperature (deg C): the outdoor temperature at which the building is free-running (no heating or cooling needed). Solar gain in hours below balance - offset is credited as heating benefit; warmer hours are not counted. Default 15 (Ladybug); typical range ~12 (commercial) to ~18 (residential), higher for older poorly insulated stock. UNUSED when simulated_weights_path is set."),
        ("balance_offset", "Dead-band (deg C) below the balance point: hours warmer than balance - offset are not credited. Must be >= 0 (0 = no dead-band). Default: 2.0 deg C. UNUSED when simulated_weights_path is set."),
        ("simulated_weights_path", "Optional path to a simulated_weights.json artifact (from USC_SimulateWeights or `usc simulate-weights`). When set, the balance-point rule is replaced by hourly weights from an ISO 13790 5R1C building simulation of a typical building — thermal lag, mass state, gain saturation. A full-year analysis period is then the natural choice."),
        ("include_harm", "EXPERIMENTAL boolean. True = also subtract summer-overheating contributions per sky patch (with simulated weights: the artifact's harm series, otherwise Ladybug's hot-hour composite). The harm channel is conservatively overstated (no operable shading or night ventilation is modelled) — treat as a bracketing scenario, not the default. Default: False."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    oo[0].Name, oo[0].Description = "overrides", "Benefit mode settings formatted for USC_Config. Connect to Config's 'overrides' input. Only relevant when mode='benefit'."
except Exception:
    pass


def _warn(msg):
    try:
        from Grasshopper.Kernel import GH_RuntimeMessageLevel
        ghenv.Component.AddRuntimeMessage(GH_RuntimeMessageLevel.Warning, msg)
    except Exception:
        pass


_items = []
_weights = globals().get("simulated_weights_path")
if _weights:
    _weights = str(_weights)
    if ";" in _weights or "=" in _weights:
        _warn("simulated_weights_path contains ';' or '=' — unsupported in "
              "override strings. Move the artifact to a plainer path.")
    else:
        _items.append(f"simulated_weights_path={_weights}")
        if balance_temperature is not None or balance_offset is not None:
            _warn("Simulated weights are active: balance_temperature / "
                  "balance_offset are unused.")
if balance_temperature is not None:
    _items.append(f"balance_temperature={float(balance_temperature)}")
if balance_offset is not None:
    _items.append(f"balance_offset={float(balance_offset)}")
if globals().get("include_harm"):
    _items.append("include_harm=true")
overrides = ";".join(_items) if _items else None
