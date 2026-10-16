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

# Optional keys with no default (absent = feature off).
ARCHETYPE_OPTIONAL_KEYS = ("shading_permanent", "shading_hot", "hot_months")
