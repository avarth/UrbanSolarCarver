"""USC Zone Fabric — Envelope and glazing properties.

Feeder for USC_Archetype's 'fabric' input. Only wired inputs are passed
on; anything left unconnected keeps the archetype's neutral default.

Inputs
------
u_opaque : float, optional
    Area-weighted opaque envelope U-value (walls + roof), W/m2K.
u_window : float, optional
    Glazing U-value, W/m2K.
g_value : float, optional
    Glazing solar transmittance (g-value / SHGC), applies to all windows.
mass_class : str, optional
    Thermal mass per ISO 13790 Table 12: very_light | light | medium |
    heavy | very_heavy.

Outputs
-------
fabric : USCZoneParams
    Fabric family handle. Connect to USC_Archetype's 'fabric' input.
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
    ghenv.Component.Name = "USC Zone Fabric"
    ghenv.Component.NickName = "USC_ZoneFabric"
    ghenv.Component.Description = "Envelope fabric for USC_Archetype: opaque and glazing U-values, g-value, and ISO 13790 thermal mass class. Unconnected inputs keep the neutral defaults."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("u_opaque", "Area-weighted opaque envelope U-value (walls + roof), W/m2K. Default: 0.6"),
        ("u_window", "Glazing U-value, W/m2K. Default: 1.6"),
        ("g_value", "Glazing solar transmittance (g-value / SHGC), applies to all windows. Default: 0.6"),
        ("mass_class", "Thermal mass class per ISO 13790 Table 12: very_light | light | medium | heavy | very_heavy. Heavier mass stores gains across more hours and flattens the day/night weight contrast. Default: medium"),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    if len(oo) > 0:
        oo[0].Name, oo[0].Description = "fabric", "Fabric family handle. Connect to USC_Archetype's 'fabric' input."
    if len(oo) > 1:
        oo[1].Name, oo[1].Description = "summary", "The explicitly set values (everything else keeps the archetype defaults)."
except Exception:
    pass


def _add_error(msg):
    try:
        from Grasshopper.Kernel import GH_RuntimeMessageLevel
        ghenv.Component.AddRuntimeMessage(GH_RuntimeMessageLevel.Error, msg)
    except Exception:
        pass
    return msg


_MASS_CLASSES = ("very_light", "light", "medium", "heavy", "very_heavy")

fabric = None
summary = ""

data = {}
for key in ("u_opaque", "u_window", "g_value"):
    value = globals().get(key)
    if value is not None:
        data[key] = float(value)
_mass = globals().get("mass_class")
if _mass is not None:
    _mass = str(_mass).strip()
    if _mass not in _MASS_CLASSES:
        summary = _add_error(
            "mass_class must be one of: " + " | ".join(_MASS_CLASSES))
    else:
        data["mass_class"] = _mass

if not summary:
    fabric = USCZoneParams("fabric", data)
    summary = "\n".join(f"{k}: {v}" for k, v in sorted(data.items())) or \
        "(all defaults)"
