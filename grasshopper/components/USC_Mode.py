"""USC Mode: select the carving mode.

Turns a mode index into the mode name USC_Config expects. Each mode
determines how voxels are scored:

  - time-based:        Traces actual sun-position rays for the selected
                       hours; carves any voxel that shades a test point
                       during those hours. (needs EPW + analysis period)
  - irradiance:        Cumulative solar irradiation (kWh/m²) from EPW
                       direct + diffuse. (needs EPW + analysis period)
  - benefit:           Net heating benefit: irradiance weighted by
                       balance-point temperature or simulated weights.
                       (needs EPW + analysis period; Benefit Params optional)
  - daylight:          CIE overcast sky luminance; geometry only,
                       no weather data needed.
  - radiative_cooling: Long-wave cooling potential to the sky vault,
                       as relative patch weights. (uses one dew point
                       value, no EPW)
  - tilted_plane:      Geometric daylight-envelope sweep, not a
                       weighted evaluation. (needs Tilted Plane params)

Inputs
------
mode : int
    Mode selector (0-5). Set it with right-click > Set Integer, or wire
    a Value List or slider.
    0 = time-based, 1 = irradiance, 2 = benefit,
    3 = daylight, 4 = radiative_cooling, 5 = tilted_plane

Outputs
-------
mode_name : str
    Mode name for USC_Config's 'mode' input.
description : str
    Human-readable summary of the selected mode.
"""

try:
    ghenv.Component.Name = "USC Mode"
    ghenv.Component.NickName = "USC_Mode"
    ghenv.Component.Description = (
        "Select the carving mode. Determines how voxels are scored "
        "(time-based, irradiance, benefit, daylight, etc.). "
        "Connect mode_name to USC_Config's mode input."
    )
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "mode", (
        "Mode index (0-5). "
        "0=time-based, 1=irradiance, 2=benefit, "
        "3=daylight, 4=radiative_cooling, 5=tilted_plane. "
        "Right-click \u2192 'Set Integer' or use a Value List."
    )
    oo[0].Name, oo[0].Description = "mode_name", (
        "Mode name. Connect to USC_Config's 'mode' input."
    )
    oo[1].Name, oo[1].Description = "description", (
        "Human-readable summary of the selected mode, including "
        "what inputs it requires."
    )
except Exception:
    pass

def _mode_registry():
    """The engine's mode registry, or None while no USC component has loaded usc_gh.

    This component has no session input. USC_Session loads usc_gh.py from the
    carver root, and the root is taken from there.
    """
    import sys
    from pathlib import Path
    gh = sys.modules.get("usc_gh")
    if gh is None:
        return None
    return gh.engine_module(Path(gh.__file__).resolve().parent.parent, "mode_registry")


def _warn(msg):
    """Show a warning on the component and return msg."""
    try:
        from Grasshopper.Kernel import GH_RuntimeMessageLevel
        ghenv.Component.AddRuntimeMessage(GH_RuntimeMessageLevel.Warning, msg)
    except Exception:
        pass
    return msg


def _solve_again_once(engine_found):
    """Schedule one more solve of this component after the current solution.

    A saved file opened in a fresh Rhino session can solve this component before
    USC_Session has loaded usc_gh.py; USC_Session solves in the same solution, so
    one more solve afterwards finds the engine.  The re-solve is scheduled once
    per component until the engine is found, so a canvas without a USC_Session
    does not re-solve forever.
    """
    try:
        import scriptcontext as sc
        from Grasshopper.Kernel import GH_Document
        component = ghenv.Component
        key = "usc_resolve_scheduled_" + str(component.InstanceGuid)
        if engine_found:
            sc.sticky.pop(key, None)
            return
        doc = component.OnPingDocument()
        if doc is None or sc.sticky.get(key):
            return
        sc.sticky[key] = True
        doc.ScheduleSolution(1, GH_Document.GH_ScheduleDelegate(
            lambda d: component.ExpireSolution(False)))
    except Exception:
        pass


mode_name = None
description = ""

if mode is None:
    description = "Connect an integer (0-5) to select a mode."
else:
    registry = _mode_registry()
    _solve_again_once(registry is not None)
    if registry is None:
        description = _warn("The mode list comes from the engine: solve USC_Session first, "
                            "then this component again")
    else:
        names = list(registry.MODES)
        idx = int(mode)
        if idx < 0 or idx >= len(names):
            description = _warn("Invalid mode index: {}. Use 0-{}.".format(idx, len(names) - 1))
        else:
            mode_name = names[idx]
            description = "{}: {}".format(mode_name, registry.MODES[mode_name].description)
