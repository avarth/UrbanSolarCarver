"""USC Radiative Cooling: parameters for the experimental radiative cooling mode.

This experimental mode estimates the directional cooling potential of
the night sky using the Martin-Berdahl (1984) emissivity and Bliss (1961)
angular attenuation models.

Uses a single representative night-time dew point; it reads no weather
file or analysis period.

Inputs
------
dew_point : float, optional
    Night-time dew point temperature in Celsius (passed on as
    dew_point_celsius). Default: 14.0
bliss_k : float, optional
    Bliss angular attenuation constant. Default: 1.8

Outputs
-------
overrides : str
    Semicolon-joined key=value pairs for the connected inputs.
"""

try:
    ghenv.Component.Name = "USC Radiative Cooling"
    ghenv.Component.NickName = "USC_RadCool"
    ghenv.Component.Description = "[Experimental] Sets parameters for radiative cooling mode. Uses the Martin-Berdahl (1984) clear-sky emissivity model and Bliss (1961) directional attenuation."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("dew_point", "Night-time dew point temperature in deg C. Controls the atmospheric emissivity in the Martin-Berdahl (1984) clear-sky model. Higher dew point = more humid air = less radiative cooling potential. Typical values: -5 to 20 deg C; take a typical night-time value from local weather data. Default: 14."),
        ("bliss_k", "Angular attenuation constant from the Bliss (1961) model. Controls how quickly radiative cooling drops off away from zenith. Default: 1.8. Higher values = cooling concentrated near zenith. Rarely needs adjustment."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    oo[0].Name, oo[0].Description = "overrides", "Radiative cooling settings formatted for USC_Config. Connect to Config's 'overrides' input. Only relevant when mode='radiative_cooling' [experimental]."
except Exception:
    pass

_items = []
if dew_point is not None:
    _items.append(f"dew_point_celsius={float(dew_point)}")
if bliss_k is not None:
    _items.append(f"bliss_k={float(bliss_k)}")
overrides = ";".join(_items) if _items else None
