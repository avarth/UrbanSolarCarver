"""USC Archetype — Describe a typical building for simulated weights.

Builds a single-zone shoebox archetype for USC_SimulateWeights: give the
zone's dimensions and per-facade window-to-wall ratios; floor area,
volume, facade and window areas are derived by the backend. The values
describe a *typical* building of the surrounding stock, not any one
design — source real numbers from TABULA (EU), DOE prototypes (US), or
national code tables. Every input is optional; the defaults are the
neutral example shipped with USC.

Inputs
------
width : float, optional
    Zone east-west dimension (m). Default: 10.0
length : float, optional
    Zone north-south dimension (m). Default: 10.0
height : float, optional
    Storey height (m). Default: 3.0
wwr_south, wwr_east, wwr_west, wwr_north : float, optional
    Window-to-wall ratio per facade, 0-1. Defaults: 0.35 / 0.15 / 0.15 / 0
g_value : float, optional
    Glazing solar transmittance. Default: 0.6
orientation : float, optional
    Rotate the whole box clockwise from north (deg). Default: 0
u_opaque : float, optional
    Opaque envelope U-value, W/m2K. Default: 0.6
u_window : float, optional
    Glazing U-value, W/m2K. Default: 1.6
ach_vent : float, optional
    Ventilation air changes per hour. Default: 0.8
ach_infiltration : float, optional
    Infiltration air changes per hour. Default: 0.3
heat_recovery : float, optional
    Ventilation heat-recovery efficiency, 0-1. Default: 0
mass_class : str, optional
    Thermal mass per ISO 13790 Table 12: very_light | light | medium |
    heavy | very_heavy. Default: medium
t_set_heating : float, optional
    Heating setpoint, deg C. Default: 20
t_set_cooling : float, optional
    Cooling setpoint, deg C. Default: 26
internal_gains : float, optional
    Flat internal gains, W per m2 floor area. Default: 5.0
shading_permanent : float, optional
    Year-round transmission multiplier, 0-1 (fins, context obstructions).
    Default: none (1.0). Per-facade values are possible in YAML archetypes.
shading_hot : float, optional
    Additional transmission multiplier during hot_months (awnings, tents).
    Requires hot_months. Default: none (1.0).
hot_months : str or list, optional
    Calendar months when shading_hot is deployed, e.g. "6,7,8,9".

Outputs
-------
archetype : USCArchetype
    Archetype handle. Connect to USC_SimulateWeights.
summary : str
    The assembled archetype, human-readable.
"""


class USCArchetype:
    """Opaque archetype handle. Not iterable — GH treats it as one item."""
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data

    def __repr__(self):
        d = self.data
        return "USCArchetype({}x{}x{} m, {})".format(
            d.get("width"), d.get("length"), d.get("height"),
            d.get("mass_class"))


# -- GH UI --------------------------------------------------------------------
try:
    ghenv.Component.Name = "USC Archetype"
    ghenv.Component.NickName = "USC_Archetype"
    ghenv.Component.Description = "Describes a typical building of the surrounding stock as a single-zone shoebox (dimensions, per-facade window-to-wall ratios, fabric, thermal mass, setpoints). Feed to USC_SimulateWeights to derive when solar gain is thermally useful for that kind of building. All inputs optional — defaults are USC's neutral example; source real values from TABULA / DOE prototypes / national code tables."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("width", "Zone east-west dimension in metres. Default: 10.0"),
        ("length", "Zone north-south dimension in metres. Default: 10.0"),
        ("height", "Storey height in metres. Default: 3.0"),
        ("wwr_south", "South facade window-to-wall ratio, 0-1. Default: 0.35"),
        ("wwr_east", "East facade window-to-wall ratio, 0-1. Default: 0.15"),
        ("wwr_west", "West facade window-to-wall ratio, 0-1. Default: 0.15"),
        ("wwr_north", "North facade window-to-wall ratio, 0-1. Default: 0 (no windows)"),
        ("g_value", "Glazing solar transmittance (g-value / SHGC), applies to all windows. Default: 0.6"),
        ("orientation", "Rotate the whole box clockwise from north, degrees. Default: 0"),
        ("u_opaque", "Area-weighted opaque envelope U-value (walls + roof), W/m2K. Default: 0.6"),
        ("u_window", "Glazing U-value, W/m2K. Default: 1.6"),
        ("ach_vent", "Intentional ventilation air changes per hour. Default: 0.8"),
        ("ach_infiltration", "Infiltration (leakage) air changes per hour. Default: 0.3"),
        ("heat_recovery", "Ventilation heat-recovery efficiency, 0-1 (infiltration is never recovered). Default: 0"),
        ("mass_class", "Thermal mass class per ISO 13790 Table 12: very_light | light | medium | heavy | very_heavy. Heavier mass stores gains across more hours and flattens the day/night weight contrast. Default: medium"),
        ("t_set_heating", "Heating setpoint, deg C. Default: 20"),
        ("t_set_cooling", "Cooling setpoint, deg C. Default: 26"),
        ("internal_gains", "Flat internal gains (occupants, equipment, lighting), W per m2 of floor area. Default: 5.0"),
        ("shading_permanent", "Year-round solar transmission multiplier in [0, 1] for fixed local shading (fins, context obstructions): 1 = none, 0.85 = 15% of solar blocked. No device geometry is modelled — this is a declared coefficient. Per-facade values are possible in YAML archetypes."),
        ("shading_hot", "Additional transmission multiplier in [0, 1] applied only during hot_months (awnings, tents, seasonal vegetation). Stacks with shading_permanent. Requires hot_months. Declaring this makes the harm channel far less overstated."),
        ("hot_months", "Calendar months when shading_hot is deployed, as text like '6,7,8,9' (or a list of integers 1-12)."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    if len(oo) > 0:
        oo[0].Name, oo[0].Description = "archetype", "Archetype handle. Connect to USC_SimulateWeights' 'archetype' input."
    if len(oo) > 1:
        oo[1].Name, oo[1].Description = "summary", "Human-readable dump of the assembled archetype for verification."
except Exception:
    pass


def _add_error(msg):
    try:
        from Grasshopper.Kernel import GH_RuntimeMessageLevel
        ghenv.Component.AddRuntimeMessage(GH_RuntimeMessageLevel.Error, msg)
    except Exception:
        pass
    return msg


_DEFAULTS = {
    "width": 10.0, "length": 10.0, "height": 3.0,
    "g_value": 0.6, "orientation": 0.0,
    "u_opaque": 0.6, "u_window": 1.6,
    "ach_vent": 0.8, "ach_infiltration": 0.3, "heat_recovery": 0.0,
    "mass_class": "medium",
    "t_set_heating": 20.0, "t_set_cooling": 26.0,
}
_WWR_DEFAULTS = {"south": 0.35, "east": 0.15, "west": 0.15, "north": 0.0}
_MASS_CLASSES = ("very_light", "light", "medium", "heavy", "very_heavy")

archetype = None
summary = ""

data = {}
for key, default in _DEFAULTS.items():
    value = globals().get(key)
    if value is None:
        value = default
    data[key] = str(value).strip() if key == "mass_class" else float(value)

wwr = {}
for side, default in _WWR_DEFAULTS.items():
    value = globals().get("wwr_" + side)
    ratio = float(value) if value is not None else default
    if not 0.0 <= ratio < 1.0:
        summary = _add_error(f"wwr_{side} must be in [0, 1), got {ratio}")
        ratio = 0.0
    if ratio > 0.0:
        wwr[side] = ratio

if data["mass_class"] not in _MASS_CLASSES:
    summary = _add_error(
        "mass_class must be one of: " + " | ".join(_MASS_CLASSES))
elif not wwr:
    summary = _add_error("All WWR inputs are zero — the archetype needs at "
                         "least one window for solar gains to exist.")
else:
    data["wwr"] = wwr
    if not data["orientation"]:
        data.pop("orientation")
    gains = globals().get("internal_gains")
    data["internal_gains_w_m2"] = float(gains) if gains is not None else 5.0

    # Declared shading coefficients (validated fully in the backend).
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
        summary = _add_error("shading_hot requires hot_months "
                             "(e.g. '6,7,8,9')")
    if _months is not None and _hot is None:
        summary = _add_error("hot_months has no effect without shading_hot")

    if not summary:
        archetype = USCArchetype(data)
        lines = [f"{k}: {data[k]}" for k in sorted(data)]
        lines.append(
            f"derived floor area: {data['width'] * data['length']:.1f} m2")
        summary = "\n".join(lines)
