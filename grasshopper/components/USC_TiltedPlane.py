"""USC Tilted Plane — Set plane angles for daylight envelope carving.

Only used when mode = "tilted_plane".

Provide EITHER:
  - angle: a single number applied uniformly to all 8 octants
  - octants: exactly 8 numbers [N, NE, E, SE, S, SW, W, NW]

If both are connected, octants takes precedence.

Inputs
------
angle : float, optional
    Single plane angle in degrees applied uniformly.
octants : list of 8 floats, optional
    Per-octant angles [N, NE, E, SE, S, SW, W, NW] in degrees.

Outputs
-------
overrides : str
    Semicolon-joined key=value string.
"""

try:
    ghenv.Component.Name = "USC Tilted Plane"
    ghenv.Component.NickName = "USC_Plane"
    ghenv.Component.Description = "Sets the daylight access angle for tilted_plane mode. Provide a single angle (uniform) or 8 per-octant values [N,NE,E,SE,S,SW,W,NW]. The angle defines the slope of the daylight access plane from horizontal."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "angle", "Single daylight access angle in degrees, applied uniformly to all directions. This is the angle between the horizontal ground plane and the daylight access plane. 45 deg means 1:1 height-to-distance ratio. Range: 10-80 deg."
    ii[1].Name, ii[1].Description = "octants", "Eight angles in degrees, one per cardinal/intercardinal direction [N, NE, E, SE, S, SW, W, NW]. Use this instead of 'angle' when different directions need different daylight access. Provide exactly 8 values."
    oo[0].Name, oo[0].Description = "overrides", "Tilted plane settings formatted for USC_Config. Connect to Config's 'overrides' input. Only relevant when mode='tilted_plane'."
    # octants must be List Access so GH collects all 8 values at once
    import Grasshopper
    ii[1].Access = Grasshopper.Kernel.GH_ParamAccess.list
except Exception:
    pass


def _to_float_list(x):
    """Convert whatever GH sends into a flat list of floats."""
    if x is None:
        return []
    if isinstance(x, (int, float)):
        return [float(x)]
    out = []
    for item in x:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            pass
    return out


overrides = None

oct_vals = _to_float_list(octants)
if len(oct_vals) == 8:
    # Per-octant mode
    import json as _json
    overrides = "tilted_plane_angle_deg=" + _json.dumps(oct_vals)
elif len(oct_vals) > 0 and len(oct_vals) != 8:
    overrides = None
    try:
        import Grasshopper as _gh
        ghenv.Component.AddRuntimeMessage(
            _gh.Kernel.GH_RuntimeMessageLevel.Warning,
            "octants needs exactly 8 values, got {}".format(len(oct_vals))
        )
    except Exception:
        pass
elif angle is not None:
    # Uniform angle
    overrides = "tilted_plane_angle_deg={}".format(float(angle))
