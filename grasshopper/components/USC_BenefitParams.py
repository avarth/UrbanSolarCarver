"""USC Benefit Parameters — Control benefit-mode balance point.

Only used when mode = "benefit". The balance temperature is the
outdoor air temperature at which a building is 'free-running' —
it needs neither heating nor cooling. Solar gains are credited only
in hours colder than balance_temperature - balance_offset (they
offset heating demand); warmer hours are simply not counted.

Inputs
------
balance_temperature : float, optional
    Balance-point temperature in degrees Celsius. Default: 15.0
balance_offset : float, optional
    Dead-band below the balance point in degrees Celsius. Default: 2.0

Outputs
-------
overrides : str
    Semicolon-joined key=value pairs for Config's overrides input.
"""

try:
    ghenv.Component.Name = "USC Benefit Params"
    ghenv.Component.NickName = "USC_Benefit"
    ghenv.Component.Description = "Sets the balance-point temperature for benefit mode. The balance point is the outdoor temperature at which the building is free-running (no heating or cooling). Solar gains in hours below balance - offset are credited as heating benefit."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("balance_temperature", "Balance-point temperature (deg C): the outdoor temperature at which the building is free-running (no heating or cooling needed). Solar gain in hours below balance - offset is credited as heating benefit; warmer hours are not counted. Default 15 (Ladybug); typical range ~12 (commercial) to ~18 (residential), higher for older poorly insulated stock. Derive project-specific values with the Honeybee/E+ balance-point workflow."),
        ("balance_offset", "Dead-band (deg C) below the balance point: hours warmer than balance - offset are not credited. Must be >= 0 (0 = no dead-band). Default: 2.0 deg C."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    oo[0].Name, oo[0].Description = "overrides", "Benefit mode settings formatted for USC_Config. Connect to Config's 'overrides' input. Only relevant when mode='benefit'."
except Exception:
    pass

_items = []
if balance_temperature is not None:
    _items.append(f"balance_temperature={float(balance_temperature)}")
if balance_offset is not None:
    _items.append(f"balance_offset={float(balance_offset)}")
overrides = ";".join(_items) if _items else None
