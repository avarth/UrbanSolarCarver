"""USC Ray Settings: control ray casting parameters and sky model orientation.

Inputs
------
ray_length : float, optional
    Maximum ray cast distance in meters. Default: 3000.0
min_altitude : float, optional
    Minimum sun altitude in degrees (time-based mode only). Default: 5.0
north_deg : float, optional
    North direction in degrees clockwise from Y-axis. Default: 0.0
    (Y-up is north). Rotates the sky dome / sun positions to match
    your model's orientation.
context_blocks_rays : bool, optional
    With context or terrain connected to USC Preprocess: drop the rays
    that hit them before scoring. Default: True. False keeps the voxels
    they remove, but drops no ray, to compare the carvings.

Outputs
-------
overrides : str
    Semicolon-joined key=value pairs for the connected inputs.
"""

try:
    ghenv.Component.Name = "USC Ray Settings"
    ghenv.Component.NickName = "USC_Rays"
    ghenv.Component.Description = "Controls ray casting distance, minimum sun altitude, and sky model orientation. Set north_deg to match your model's north."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("ray_length", "Maximum distance each ray travels, in meters. A ray stops where it leaves the voxel grid, so a length beyond the grid costs nothing. Default: 3000 m, enough for any grid at 1 m voxels."),
        ("min_altitude", "Minimum sun altitude angle in degrees above the horizon. Sun positions below this angle are skipped. Used by time-based mode only. Default: 5 deg. Typical: 0-20 deg."),
        ("north_deg", "North direction in degrees clockwise from the Y-axis. 0 = Y-up is north (Rhino default). Set this to match your model's orientation. E.g. if your model's north points along +X, set to 90."),
        ("context_blocks_rays", "Account for context blocking. With context or terrain connected to USC_Preprocess (ray-based modes): True drops the rays that hit them before scoring, so the carving keeps more where they shade; False keeps the voxels they remove but drops no ray, to compare the two carvings. Default: True."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    oo[0].Name, oo[0].Description = "overrides", "Ray, sky and context settings formatted for USC_Config. Connect to Config's 'overrides' input."
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
if context_blocks_rays is not None:
    _items.append("context_blocks_rays=" + ("true" if context_blocks_rays else "false"))
overrides = ";".join(_items) if _items else None
