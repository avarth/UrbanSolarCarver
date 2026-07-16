"""USC Zone Shading — Declared shading coefficients.

Feeder for USC_Archetype's 'shading' input. Pure transmission
multipliers, no device geometry is modelled. Leaving everything
unconnected means no shading.

Inputs
------
shading_permanent : float, optional
    Year-round transmission multiplier, 0-1 (fins, context
    obstructions): 1 = none. Per-facade values are possible in YAML
    archetypes.
shading_hot : float, optional
    Additional transmission multiplier during hot_months (awnings,
    tents, seasonal vegetation). Stacks with shading_permanent.
    Requires hot_months.
hot_months : str or list, optional
    Calendar months when shading_hot is deployed, e.g. "6,7,8,9".

Outputs
-------
shading : USCZoneParams
    Shading family handle. Connect to USC_Archetype's 'shading' input.
summary : str
    The explicitly set values.
"""


class USCZoneParams:
    """Opaque family handle for USC_Archetype inputs."""
    __slots__ = ("kind", "data")

    def __init__(self, kind, data):
        self.kind = kind
        self.data = data

    def __repr__(self):
        return "USCZoneParams({}: {} set)".format(self.kind, len(self.data))


try:
    ghenv.Component.Name = "USC Zone Shading"
    ghenv.Component.NickName = "USC_ZoneShade"
    ghenv.Component.Description = "Declared shading coefficients for USC_Archetype: a year-round transmission multiplier (fins, context) and a hot-months multiplier (awnings, tents). No device geometry is modelled. Declaring seasonal shading makes the harm channel far less overstated."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("shading_permanent", "Year-round solar transmission multiplier in [0, 1] for fixed local shading (fins, context obstructions): 1 = none, 0.85 = 15% of solar blocked. No device geometry is modelled — this is a declared coefficient. Per-facade values are possible in YAML archetypes."),
        ("shading_hot", "Additional transmission multiplier in [0, 1] applied only during hot_months (awnings, tents, seasonal vegetation). Stacks with shading_permanent. Requires hot_months."),
        ("hot_months", "Calendar months when shading_hot is deployed, as text like '6,7,8,9' (or a list of integers 1-12)."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    if len(oo) > 0:
        oo[0].Name, oo[0].Description = "shading", "Shading family handle. Connect to USC_Archetype's 'shading' input."
    if len(oo) > 1:
        oo[1].Name, oo[1].Description = "summary", "The explicitly set values."
except Exception:
    pass


def _add_error(msg):
    try:
        from Grasshopper.Kernel import GH_RuntimeMessageLevel
        ghenv.Component.AddRuntimeMessage(GH_RuntimeMessageLevel.Error, msg)
    except Exception:
        pass
    return msg


shading = None
summary = ""

data = {}
_perm = globals().get("shading_permanent")
_hot = globals().get("shading_hot")
_months = globals().get("hot_months")
if _perm is not None:
    data["shading_permanent"] = float(_perm)
if _hot is not None:
    data["shading_hot"] = float(_hot)
if _months is not None:
    if isinstance(_months, str):
        _months = [int(m) for m in _months.split(",") if m.strip()]
    else:
        try:
            _months = [int(m) for m in _months]
        except TypeError:
            _months = [int(_months)]
    data["hot_months"] = _months

if _hot is not None and _months is None:
    summary = _add_error("shading_hot requires hot_months (e.g. '6,7,8,9')")
elif _months is not None and _hot is None:
    summary = _add_error("hot_months has no effect without shading_hot")
else:
    shading = USCZoneParams("shading", data)
    summary = "\n".join(f"{k}: {v}" for k, v in sorted(data.items())) or \
        "(no shading declared)"
