"""USC Analysis Period: define the time window for sun/sky analysis.

Required for: time-based, irradiance, benefit modes.
Not used by: daylight, radiative_cooling, tilted_plane (the config warns
that the period is ignored).

Inputs
------
start_month : int (1-12)
start_day : int (1-31)
start_hour : int (0-23)
end_month : int (1-12)
end_day : int (1-31)
end_hour : int (0-23)
solar_time : bool, optional
    time-based only: True reads the hours in true solar time (12:00 = solar
    noon), False in the EPW's local standard time. Sets ``time_basis``.
    Default: False. Irradiance and benefit refuse True.

Outputs
-------
overrides : str
    Semicolon-joined key=value pairs for the connected inputs (None if
    none is connected).
"""

try:
    ghenv.Component.Name = "USC Analysis Period"
    ghenv.Component.NickName = "USC_Period"
    ghenv.Component.Description = "Defines the time window for solar analysis. Required for time-based, irradiance and benefit modes. Not used by daylight, radiative_cooling or tilted_plane."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("start_month", "First month of the analysis window (1=January, 12=December). For heating-season studies, try 10 (October)."),
        ("start_day", "First day of the start month (1-31). Use 1 for the beginning of the month."),
        ("start_hour", "First hour of day to include (0-23, where 0=midnight, 12=noon). For daytime-only analysis, use 7 or 8."),
        ("end_month", "Last month of the analysis window (1-12). For heating-season studies, try 3 (March) or 4 (April)."),
        ("end_day", "Last day of the end month (1-31). Use 31 for the end of the month."),
        ("end_hour", "Last hour of day to include (0-23). For daytime-only analysis, use 17 or 18."),
        ("solar_time", "Time-based mode only (config key time_basis). True: the hours are true solar time, so 12:00 is solar noon, as solar-fence rules and the Japanese shadow regulation define them. False: the EPW's local standard time. Default: False. Irradiance and benefit refuse True, as their hourly weather data are in standard time."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    oo[0].Name, oo[0].Description = "overrides", "Time period settings formatted for USC_Config. Connect to Config's 'overrides' input."
except Exception:
    pass

# One semicolon-joined string, not a list, so Grasshopper passes it on as a
# single item instead of looping downstream components over each pair.
_items = []
for key, val in [
    ("start_month", start_month), ("start_day", start_day),
    ("start_hour", start_hour), ("end_month", end_month),
    ("end_day", end_day), ("end_hour", end_hour),
]:
    if val is not None:
        _items.append(f"{key}={int(val)}")
# False is the default, so it is left out: the modes that do not read
# time_basis would otherwise warn that it is unused.
if solar_time is not None and bool(solar_time):
    _items.append("time_basis=solar")
overrides = ";".join(_items) if _items else None
