"""USC Zone Geometry — Shoebox dimensions and glazing ratios.

Feeder for USC_Archetype's 'geometry' input. Only wired inputs are
passed on; anything left unconnected keeps the archetype's neutral
default (10 x 10 x 3 m, wwr south 0.35 / east 0.15 / west 0.15).

Inputs
------
width : float, optional
    Zone east-west dimension (m).
length : float, optional
    Zone north-south dimension (m).
height : float, optional
    Storey height (m).
orientation : float, optional
    Rotate the whole box clockwise from north (deg).
wwr_south, wwr_east, wwr_west, wwr_north : float, optional
    Window-to-wall ratio per facade, 0-1 (0 = no windows on that side).

Outputs
-------
geometry : USCZoneParams
    Geometry family handle. Connect to USC_Archetype's 'geometry' input.
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
    ghenv.Component.Name = "USC Zone Geometry"
    ghenv.Component.NickName = "USC_ZoneGeom"
    ghenv.Component.Description = "Shoebox zone geometry for USC_Archetype: dimensions, orientation, and per-facade window-to-wall ratios. Unconnected inputs keep the neutral defaults."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("width", "Zone east-west dimension in metres. Default: 10.0"),
        ("length", "Zone north-south dimension in metres. Default: 10.0"),
        ("height", "Storey height in metres. Default: 3.0"),
        ("orientation", "Rotate the whole box clockwise from north, degrees. Default: 0"),
        ("wwr_south", "South facade window-to-wall ratio, 0-1. Default: 0.35"),
        ("wwr_east", "East facade window-to-wall ratio, 0-1. Default: 0.15"),
        ("wwr_west", "West facade window-to-wall ratio, 0-1. Default: 0.15"),
        ("wwr_north", "North facade window-to-wall ratio, 0-1. Default: 0 (no windows)"),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    if len(oo) > 0:
        oo[0].Name, oo[0].Description = "geometry", "Geometry family handle. Connect to USC_Archetype's 'geometry' input."
    if len(oo) > 1:
        oo[1].Name, oo[1].Description = "summary", "The explicitly set values (everything else keeps the archetype defaults)."
except Exception:
    pass


data = {}
for key in ("width", "length", "height", "orientation"):
    value = globals().get(key)
    if value is not None:
        data[key] = float(value)
wwr = {}
for side in ("south", "east", "west", "north"):
    value = globals().get("wwr_" + side)
    if value is not None:
        wwr[side] = float(value)
if wwr:
    data["wwr"] = wwr

geometry = USCZoneParams("geometry", data)
summary = "\n".join(f"{k}: {v}" for k, v in sorted(data.items())) or \
    "(all defaults)"
