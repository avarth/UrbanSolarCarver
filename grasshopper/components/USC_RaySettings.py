"""USC Ray Settings: control ray casting parameters and sky model orientation.

Inputs
------
ray_length : float, optional
    Maximum ray cast distance in meters. Default: 300.0
min_altitude : float, optional
    Minimum sun altitude in degrees (time-based mode only). Default: 5.0
north_deg : float, optional
    North direction in degrees clockwise from Y-axis. Default: 0.0
    (Y-up is north). Rotates the sky dome / sun positions to match
    your model's orientation.

Outputs
-------
overrides : str
    Semicolon-joined key=value pairs for the connected inputs.
"""

try:
    ghenv.Component.Name = "USC Ray Settings"
    ghenv.Component.NickName = "USC_Rays"
    ghenv.Component.Description = "Controls ray casting distance, minimum sun altitude, and sky model orientation. Increase ray_length for large sites. Set north_deg to match your model's north."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("ray_length", "Maximum distance each ray travels, in meters. Must be long enough to reach from test surfaces through the entire max volume. Default: 300 m. Increase for very large sites."),
        ("min_altitude", "Minimum sun altitude angle in degrees above the horizon. Sun positions below this angle are skipped. Used by time-based mode only. Default: 5 deg. Typical: 0-20 deg."),
        ("north_deg", "North direction in degrees clockwise from the Y-axis. 0 = Y-up is north (Rhino default). Set this to match your model's orientation. E.g. if your model's north points along +X, set to 90."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    oo[0].Name, oo[0].Description = "overrides", "Ray and sky settings formatted for USC_Config. Connect to Config's 'overrides' input."
except Exception:
    pass

_items = []
for key, val in [
    ("ray_length", ray_length),
    ("min_altitude", min_altitude),
    ("north_deg", north_deg),
]:
    if val is not None:
        _items.append(f"{key}={float(val)}")
overrides = ";".join(_items) if _items else None
