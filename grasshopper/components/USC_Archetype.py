"""USC Archetype: assemble a typical building for simulated weights.

Collects the five parameter families into one archetype handle for
USC_SimulateWeights. Wire in only the families you want to customise:
every input is optional, and anything not provided keeps USC's neutral
defaults (a 10 x 10 x 3 m medium-mass shoebox with window-to-wall ratios
(WWR) south 0.35 / east 0.15 / west 0.15, no shading). The archetype
describes a *typical* building of the surrounding stock, not any one
design; take real numbers from TABULA (EU), DOE prototypes (US), or
national code tables.

Inputs
------
geometry : USCZoneParams, optional
    From USC_ZoneGeometry: dimensions, orientation, per-facade WWR.
fabric : USCZoneParams, optional
    From USC_ZoneFabric: U-values, g-value, thermal mass class.
ventilation : USCZoneParams, optional
    From USC_ZoneVent: air-change rates, heat recovery.
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
    """Opaque archetype handle. Not iterable, so Grasshopper passes it as one item."""
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
    ghenv.Component.Description = "Assembles a typical building of the surrounding stock from the five parameter families (geometry, fabric, ventilation, operation, shading). Feed to USC_SimulateWeights to derive when solar gain is thermally useful for that kind of building. All inputs are optional; unwired families keep USC's neutral defaults. Take real values from TABULA, DOE prototypes or national code tables."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("geometry", "Geometry family from USC_ZoneGeometry: shoebox dimensions, orientation, per-facade window-to-wall ratios. Optional."),
        ("fabric", "Fabric family from USC_ZoneFabric: opaque and glazing U-values, g-value, ISO 13790 thermal mass class. Optional."),
        ("ventilation", "Ventilation family from USC_ZoneVent: intentional and infiltration air-change rates, heat-recovery efficiency. Optional."),
        ("operation", "Operation family from USC_ZoneOperation: heating/cooling setpoints and flat internal gains. Optional."),
        ("shading", "Shading family from USC_ZoneShading: declared permanent and hot-months transmission multipliers. Optional (no shading by default)."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    if len(oo) > 0:
        oo[0].Name, oo[0].Description = "archetype", "Archetype handle. Connect to USC_SimulateWeights' 'archetype' input."
    if len(oo) > 1:
        oo[1].Name, oo[1].Description = "summary", "Every value of the assembled archetype, one per line, plus the derived floor area. Use it to check the inputs."
except Exception:
    pass


def _add_error(msg):
    try:
        from Grasshopper.Kernel import GH_RuntimeMessageLevel
        ghenv.Component.AddRuntimeMessage(GH_RuntimeMessageLevel.Error, msg)
    except Exception:
        pass
    return msg


def _archetype_defaults():
    """The engine's archetype defaults module, or None while no USC component has loaded usc_gh.

    This component has no session input. USC_Session loads usc_gh.py from the
    carver root, and the root is taken from there.
    """
    import sys
    from pathlib import Path
    gh = sys.modules.get("usc_gh")
    if gh is None:
        return None
    return gh.engine_module(Path(gh.__file__).resolve().parent.parent, "archetype_defaults")


_FAMILIES = ("geometry", "fabric", "ventilation", "operation", "shading")

archetype = None
summary = ""

engine_defaults = _archetype_defaults()
if engine_defaults is None:
    summary = _add_error("The archetype defaults come from the engine: solve USC_Session "
                         "first, then this component again")
    data, wwr = {}, {}
else:
    # Values used for every family that is not wired.
    data = dict(engine_defaults.ARCHETYPE_DEFAULTS)
    wwr = dict(engine_defaults.WINDOW_TO_WALL_DEFAULTS)
for index, name in enumerate(() if summary else _FAMILIES):
    handle = globals().get(name)
    if handle is None:
        # Wired but empty means the upstream USC_Zone* component failed;
        # falling back to defaults would hide that.
        if ghenv.Component.Params.Input[index].SourceCount > 0:
            summary = _add_error(
                f"'{name}' is connected but received nothing; fix the upstream "
                "USC_Zone* component (it shows the error)")
            break
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
            f"'{name}' input received a {kind} family; wire the matching "
            "USC_Zone* component instead")
        break
    family = dict(family)
    wwr.update(family.pop("wwr", {}))
    data.update(family)

if not summary:
    wwr = {side: v for side, v in wwr.items() if v > 0.0}
    if not wwr:
        summary = _add_error("All WWR values are zero: the archetype needs "
                             "at least one window to receive solar gains.")
    else:
        data["wwr"] = wwr
        if not data.get("orientation"):
            data.pop("orientation", None)
        archetype = USCArchetype(data)
        lines = [f"{k}: {data[k]}" for k in sorted(data)]
        lines.append(
            f"derived floor area: {data['width'] * data['length']:.1f} m2")
        summary = "\n".join(lines)
