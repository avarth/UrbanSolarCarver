"""Shoebox archetype defaults, defined in one place.

Standard library only, so Grasshopper can load this file by path.  The
``usc archetype`` command, the Grasshopper archetype component and the
simulated-weights generator all read their defaults from here.
"""
from __future__ import annotations

# Scalar shoebox fields used when the user gives none.  Window-to-wall
# ratios are kept apart in WINDOW_TO_WALL_DEFAULTS because they are a mapping.
ARCHETYPE_DEFAULTS = {
    "width": 10.0, "length": 10.0, "height": 3.0,
    "g_value": 0.6, "orientation": 0.0,
    "u_opaque": 0.6, "u_window": 1.6,
    "ach_vent": 0.8, "ach_infiltration": 0.3, "heat_recovery": 0.0,
    "mass_class": "medium",
    "t_set_heating": 20.0, "t_set_cooling": 26.0,
    "internal_gains_w_m2": 5.0,
}

# Window-to-wall ratio per facade; a facade at 0.0 gets no window.
WINDOW_TO_WALL_DEFAULTS = {"south": 0.35, "east": 0.15, "west": 0.15, "north": 0.0}

# How the zone is run (archetype key ``operation``): with ideal heating and
# cooling to its set points, or free running against a comfort band whose
# limits are the two set points.  An archetype without the key is conditioned;
# the Grasshopper archetype component and the browser app's typical building
# run free.
OPERATIONS = ("conditioned", "free_running")

# The window opening of a free-running zone (archetype keys): windows open in
# an hour when the air would be above vent_above [°C] with them closed and
# opening them cools it, as far as needed to bring it to vent_above, up to
# vent_ach extra air changes per hour.  A conditioned zone takes neither.
FREE_RUNNING_DEFAULTS = {"vent_above": 25.0, "vent_ach": 4.0}

# Optional keys with no default (absent = feature off).
ARCHETYPE_OPTIONAL_KEYS = ("shading_permanent", "shading_hot", "hot_months")

# Whether the shoebox's roof and floor lose heat to the outside when the
# archetype does not say: the roof does, the slab on the ground does not.
# The usc archetype command and Grasshopper do not offer these keys; the
# browser app's typical building gives them.
SHOEBOX_EXPOSURE_DEFAULTS = {"roof_exposed": True, "floor_exposed": False}
