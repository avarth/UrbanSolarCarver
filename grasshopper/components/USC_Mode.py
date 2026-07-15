"""USC Mode — Select carving mode.

Provides a validated mode string for the USC pipeline. Each mode
determines how sky-patch weights are computed:

  - time-based:        Traces actual sun-position rays for the selected
                       hours; carves any voxel that shades a test point
                       during those hours. (needs EPW)
  - irradiance:        Cumulative solar irradiance (Wh/m²) from EPW
                       direct + diffuse. (needs EPW)
  - benefit:           Net heating benefit — irradiance weighted by
                       balance-point temperature. (needs EPW + Benefit Params)
  - daylight:          CIE overcast sky luminance — geometry only,
                       no weather data needed.
  - radiative_cooling: Long-wave cooling potential to the sky vault
                       (W/m²). (needs EPW)
  - tilted_plane:      Geometric daylight-envelope sweep — not a
                       weighted evaluation. (needs Tilted Plane params)

Inputs
------
mode : int
    Mode selector (0-5). Right-click for value list.
    0 = time-based, 1 = irradiance, 2 = benefit,
    3 = daylight, 4 = radiative_cooling, 5 = tilted_plane

Outputs
-------
overrides : str
    mode=<value> override string for USC_Config.
description : str
    Human-readable summary of the selected mode.
"""

_MODES = [
    "time-based",
    "irradiance",
    "benefit",
    "daylight",
    "radiative_cooling",
    "tilted_plane",
]

_DESCRIPTIONS = {
    "time-based": (
        "Classical solar envelope: traces actual sun-position rays for the "
        "selected hours of year and carves any voxel that shades a test "
        "point during those hours. Requires EPW + analysis period."
    ),
    "irradiance": (
        "Cumulative solar irradiance (Wh/m\u00b2). Patches weighted by "
        "direct + diffuse radiation from EPW. Requires EPW + analysis period."
    ),
    "benefit": (
        "Net heating benefit (Wh/m\u00b2). Solar gain weighted by outdoor "
        "temperature relative to a balance point (simple weights), or by an "
        "ISO 13790 5R1C building simulation via USC_SimulateWeights "
        "(simulated weights). Requires EPW + analysis period + Benefit Params."
    ),
    "daylight": (
        "CIE overcast sky obstruction score (dimensionless). Geometry-only model "
        "\u2014 no weather data needed. Good for daylight access studies."
    ),
    "radiative_cooling": (
        "Long-wave radiative cooling potential (W/m\u00b2). Patches weighted "
        "by sky temperature depression from dew point. Requires EPW. "
        "[Experimental]"
    ),
    "tilted_plane": (
        "Geometric daylight envelope sweep. Carves voxels below a tilted "
        "plane at user-defined angles. Not a weighted evaluation \u2014 "
        "produces a binary mask. Requires Tilted Plane params."
    ),
}

try:
    ghenv.Component.Name = "USC Mode"
    ghenv.Component.NickName = "USC_Mode"
    ghenv.Component.Description = (
        "Select the carving mode. Determines how sky-patch "
        "weights are computed (irradiance, benefit, daylight, etc.). "
        "Connect the overrides output to USC_Config."
    )
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "mode", (
        "Mode index (0-5). "
        "0=time-based, 1=irradiance, 2=benefit, "
        "3=daylight, 4=radiative_cooling, 5=tilted_plane. "
        "Right-click \u2192 'Set Integer' or use a Value List."
    )
    oo[0].Name, oo[0].Description = "overrides", (
        "mode=<value> override string. Connect to USC_Config or "
        "USC_Config overrides input."
    )
    oo[1].Name, oo[1].Description = "description", (
        "Human-readable summary of the selected mode, including "
        "what inputs it requires."
    )
except Exception:
    pass

overrides = None
description = ""

if mode is None:
    description = "Connect an integer (0-5) to select a mode."
else:
    idx = int(mode)
    if idx < 0 or idx >= len(_MODES):
        description = "Invalid mode index: {}. Use 0-{}.".format(idx, len(_MODES) - 1)
        try:
            from Grasshopper.Kernel import GH_RuntimeMessageLevel
            ghenv.Component.AddRuntimeMessage(
                GH_RuntimeMessageLevel.Warning, description
            )
        except Exception:
            pass
    else:
        mode_name = _MODES[idx]
        overrides = "mode={}".format(mode_name)
        description = "{}: {}".format(mode_name, _DESCRIPTIONS[mode_name])
