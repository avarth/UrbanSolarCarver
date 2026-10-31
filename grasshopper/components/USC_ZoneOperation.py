"""USC Zone Operation: how the room is run, setpoints and internal gains.

Feeder for USC_Archetype's 'operation' input. Only wired inputs are
passed on; anything left unconnected keeps the archetype's neutral
default.

By default the room runs free: no heating or cooling, windows opened for
natural ventilation, and the two setpoints are the comfort band. A
marginal joule of sun counts by the degree-hours below the band it
removes (benefit) and above the band it adds (harm). Set free_running to
False for a room heated and cooled to its setpoints, whose sun counts by
the heating it saves and the cooling it adds.

Inputs
------
t_set_heating : float, optional
    Lower edge of the comfort band (free running) or heating setpoint,
    deg C.
t_set_cooling : float, optional
    Upper edge of the comfort band (free running) or cooling setpoint,
    deg C.
internal_gains : float, optional
    Flat internal gains (occupants, equipment, lighting), W per m2 of
    floor area.
free_running : bool, optional
    True for a free-running room, False for a heated and cooled one.
vent_above : float, optional
    Free running only: the windows open when the room would be warmer
    than this with them closed and the outdoor air is cooler, deg C.
vent_ach : float, optional
    Free running only: the most air changes per hour that open windows
    add.

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
    ghenv.Component.Description = "Operation for USC_Archetype: a free-running room (default) or a heated and cooled one, its comfort band or setpoints, flat internal gains and, free running, the window opening. Unconnected inputs keep the defaults."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("t_set_heating", "Lower edge of the comfort band (free running) or heating setpoint, deg C. Default: 20"),
        ("t_set_cooling", "Upper edge of the comfort band (free running) or cooling setpoint, deg C. Default: 26"),
        ("internal_gains", "Flat internal gains (occupants, equipment, lighting), W per m2 of floor area. Default: 5.0"),
        ("free_running", "True: no heating or cooling, windows opened for natural ventilation, the setpoints are the comfort band. False: heated and cooled to the setpoints. Default: True"),
        ("vent_above", "Free running only: the windows open when the room would be warmer than this with them closed and the outdoor air is cooler, deg C. Default: 25"),
        ("vent_ach", "Free running only: the most air changes per hour that open windows add. Default: 4"),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    if len(oo) > 0:
        oo[0].Name, oo[0].Description = "operation", "Operation family handle. Connect to USC_Archetype's 'operation' input."
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


data = {}
_free = globals().get("free_running")
if _free is not None:
    data["operation"] = "free_running" if _free else "conditioned"
for key in ("t_set_heating", "t_set_cooling", "vent_above", "vent_ach"):
    value = globals().get(key)
    if value is not None:
        data[key] = float(value)
_gains = globals().get("internal_gains")
if _gains is not None:
    data["internal_gains_w_m2"] = float(_gains)

operation = None
_window = sorted(key for key in ("vent_above", "vent_ach") if key in data)
if data.get("operation") == "conditioned" and _window:
    summary = _add_error(f"{', '.join(_window)} apply to a free-running room only: "
                         "set free_running to True or disconnect them")
elif data.get("vent_ach", 0.0) < 0.0:
    summary = _add_error("vent_ach must not be negative")
else:
    operation = USCZoneParams("operation", data)
    summary = "\n".join(f"{k}: {v}" for k, v in sorted(data.items())) or \
        "(all defaults)"
