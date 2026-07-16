"""USC Zone Ventilation — Air change rates and heat recovery.

Feeder for USC_Archetype's 'ventilation' input. Only wired inputs are
passed on; anything left unconnected keeps the archetype's neutral
default.

Inputs
------
ach_vent : float, optional
    Intentional ventilation air changes per hour.
ach_infiltration : float, optional
    Infiltration (leakage) air changes per hour.
heat_recovery : float, optional
    Ventilation heat-recovery efficiency, 0-1 (infiltration is never
    recovered).

Outputs
-------
ventilation : USCZoneParams
    Ventilation family handle. Connect to USC_Archetype's 'ventilation'
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
    ghenv.Component.Name = "USC Zone Ventilation"
    ghenv.Component.NickName = "USC_ZoneVent"
    ghenv.Component.Description = "Ventilation for USC_Archetype: intentional and infiltration air-change rates plus heat-recovery efficiency. Unconnected inputs keep the neutral defaults."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("ach_vent", "Intentional ventilation air changes per hour. Default: 0.8"),
        ("ach_infiltration", "Infiltration (leakage) air changes per hour. Default: 0.3"),
        ("heat_recovery", "Ventilation heat-recovery efficiency, 0-1 (infiltration is never recovered). Default: 0"),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    if len(oo) > 0:
        oo[0].Name, oo[0].Description = "ventilation", "Ventilation family handle. Connect to USC_Archetype's 'ventilation' input."
    if len(oo) > 1:
        oo[1].Name, oo[1].Description = "summary", "The explicitly set values (everything else keeps the archetype defaults)."
except Exception:
    pass


data = {}
for key in ("ach_vent", "ach_infiltration", "heat_recovery"):
    value = globals().get(key)
    if value is not None:
        data[key] = float(value)

ventilation = USCZoneParams("ventilation", data)
summary = "\n".join(f"{k}: {v}" for k, v in sorted(data.items())) or \
    "(all defaults)"
