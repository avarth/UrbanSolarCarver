"""USC Zone Operation — Setpoints and internal gains.

Feeder for USC_Archetype's 'operation' input. Only wired inputs are
passed on; anything left unconnected keeps the archetype's neutral
default.

Inputs
------
t_set_heating : float, optional
    Heating setpoint, deg C.
t_set_cooling : float, optional
    Cooling setpoint, deg C.
internal_gains : float, optional
    Flat internal gains (occupants, equipment, lighting), W per m2 of
    floor area.

Outputs
-------
operation : USCZoneParams
    Operation family handle. Connect to USC_Archetype's 'operation'
    input.
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
    ghenv.Component.Name = "USC Zone Operation"
    ghenv.Component.NickName = "USC_ZoneOper"
    ghenv.Component.Description = "Operation for USC_Archetype: heating/cooling setpoints and flat internal gains. Unconnected inputs keep the neutral defaults."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("t_set_heating", "Heating setpoint, deg C. Default: 20"),
        ("t_set_cooling", "Cooling setpoint, deg C. Default: 26"),
        ("internal_gains", "Flat internal gains (occupants, equipment, lighting), W per m2 of floor area. Default: 5.0"),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    if len(oo) > 0:
        oo[0].Name, oo[0].Description = "operation", "Operation family handle. Connect to USC_Archetype's 'operation' input."
    if len(oo) > 1:
        oo[1].Name, oo[1].Description = "summary", "The explicitly set values (everything else keeps the archetype defaults)."
except Exception:
    pass


data = {}
for key in ("t_set_heating", "t_set_cooling"):
    value = globals().get(key)
    if value is not None:
        data[key] = float(value)
_gains = globals().get("internal_gains")
if _gains is not None:
    data["internal_gains_w_m2"] = float(_gains)

operation = USCZoneParams("operation", data)
summary = "\n".join(f"{k}: {v}" for k, v in sorted(data.items())) or \
    "(all defaults)"
