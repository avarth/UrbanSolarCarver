"""USC Archetype — Assemble a typical building for simulated weights.

Collects the five parameter families into one archetype handle for
USC_SimulateWeights. Wire in only the families you want to customise:
every input is optional, and anything not provided keeps USC's neutral
defaults (a 10 x 10 x 3 m medium-mass shoebox with wwr south 0.35 /
east 0.15 / west 0.15). The archetype describes a *typical* building of
the surrounding stock, not any one design — source real numbers from
TABULA (EU), DOE prototypes (US), or national code tables.

Inputs
------
geometry : USCZoneParams, optional
    From USC_ZoneGeometry: dimensions, orientation, per-facade WWR.
fabric : USCZoneParams, optional
    From USC_ZoneFabric: U-values, g-value, thermal mass class.
ventilation : USCZoneParams, optional
    From USC_ZoneVentilation: air-change rates, heat recovery.
operation : USCZoneParams, optional
    From USC_ZoneOperation: setpoints, internal gains.
shading : USCZoneParams, optional
    From USC_ZoneShading: declared shading coefficients.

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
    ghenv.Component.Description = "Assembles a typical building of the surrounding stock from the five parameter families (geometry, fabric, ventilation, operation, shading). Feed to USC_SimulateWeights to derive when solar gain is thermally useful for that kind of building. All inputs optional — defaults are USC's neutral example; source real values from TABULA / DOE prototypes / national code tables."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("geometry", "Geometry family from USC_ZoneGeometry: shoebox dimensions, orientation, per-facade window-to-wall ratios. Optional."),
        ("fabric", "Fabric family from USC_ZoneFabric: opaque and glazing U-values, g-value, ISO 13790 thermal mass class. Optional."),
        ("ventilation", "Ventilation family from USC_ZoneVentilation: intentional and infiltration air-change rates, heat-recovery efficiency. Optional."),
        ("operation", "Operation family from USC_ZoneOperation: heating/cooling setpoints and flat internal gains. Optional."),
        ("shading", "Shading family from USC_ZoneShading: declared permanent and hot-months transmission multipliers. Optional (no shading by default)."),
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


# Neutral defaults — the single source of truth for unwired families.
_DEFAULTS = {
    "width": 10.0, "length": 10.0, "height": 3.0,
    "g_value": 0.6,
    "u_opaque": 0.6, "u_window": 1.6,
    "ach_vent": 0.8, "ach_infiltration": 0.3, "heat_recovery": 0.0,
    "mass_class": "medium",
    "t_set_heating": 20.0, "t_set_cooling": 26.0,
    "internal_gains_w_m2": 5.0,
}
_WWR_DEFAULTS = {"south": 0.35, "east": 0.15, "west": 0.15, "north": 0.0}
_FAMILIES = ("geometry", "fabric", "ventilation", "operation", "shading")

archetype = None
summary = ""

data = dict(_DEFAULTS)
wwr = dict(_WWR_DEFAULTS)
for name in _FAMILIES:
    handle = globals().get(name)
    if handle is None:
        continue
    family = getattr(handle, "data", None)
    kind = getattr(handle, "kind", None)
    if family is None or kind is None:
        summary = _add_error(
            f"'{name}' input expects the matching USC_Zone* component "
            f"(got {type(handle).__name__})")
        break
    if kind != name:
        summary = _add_error(
            f"'{name}' input received a {kind} family — wire the matching "
            "USC_Zone* component instead")
        break
    family = dict(family)
    wwr.update(family.pop("wwr", {}))
    data.update(family)

if not summary:
    wwr = {side: v for side, v in wwr.items() if v > 0.0}
    if not wwr:
        summary = _add_error("All WWR values are zero — the archetype needs "
                             "at least one window for solar gains to exist.")
    else:
        data["wwr"] = wwr
        if not data.get("orientation"):
            data.pop("orientation", None)
        archetype = USCArchetype(data)
        lines = [f"{k}: {data[k]}" for k in sorted(data)]
        lines.append(
            f"derived floor area: {data['width'] * data['length']:.1f} m2")
        summary = "\n".join(lines)
