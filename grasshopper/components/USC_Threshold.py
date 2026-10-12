"""USC Threshold: how much to carve, and the column clean-up.

Sky modes (irradiance, benefit, daylight, radiative_cooling): connect only
value, the fraction (0-1) of the building's obstruction score to remove
(carve_fraction). time-based: set method to "numeric" and value to the
tolerated shading in m²·h. tilted_plane: leave this component unconnected
(the plane angle decides).

Inputs
------
method : str, optional
    Leave unconnected for carve_fraction. "numeric" makes value a cutoff:
    for time-based, the tolerated shading in m²·h. Other sky-mode methods:
    "protect_share" (value = share of the sky weight whose patch directions
    stay clear from every test point) and "headtail" (value ignored).
value : float, optional
    Sky modes: fraction of the obstruction score to remove (0-1); 0.7 is
    aggressive, 0.3 conservative. With method "numeric": the cutoff
    (time-based: m²·h). With "protect_share": the share to protect.
score_smoothing : float, optional
    Score-cutoff methods only: Gaussian blur radius (m) of the scores
    before the cutoff. Empty = auto (1.1 x voxel_size), 0 = off.
carve_above : bool, optional
    If True, carve all occupied voxels above the lowest carved region in
    each (x, y) column, so the envelope is a buildable height field
    without floating mass. Default: True.
carve_above_min : int, optional
    Minimum consecutive carved voxels in a column before carve_above
    activates for that column. Higher values (2-3) keep stray single
    carved voxels from removing whole columns; shorter runs stay carved.
    Default: 1.
max_slope : float, optional
    Steepest rise in degrees allowed between neighbouring columns after
    carve_above; taller columns are cut into ramps, which removes cliffs
    and spires. Empty = 75 for the score-cutoff methods of the sky modes,
    off otherwise. 90 = off.

Outputs
-------
overrides : str
    Semicolon-joined key=value string. Connect to USC Threshold Stage's
    threshold_overrides (or to Config, which also re-runs Preprocess on
    every change).
"""

try:
    ghenv.Component.Name = "USC Threshold"
    ghenv.Component.NickName = "USC_Threshold"
    ghenv.Component.Description = (
        "How much to carve. Sky modes: connect only 'value', the fraction (0-1) of the building's "
        "obstruction score to remove (carve_fraction). time-based: set method to 'numeric' and "
        "value to the tolerated shading in m²·h. Also controls carve_above (removes floating mass "
        "above carved zones) and max_slope (turns cliffs and spires into ramps). Connect the output "
        "to ThresholdStage, which re-runs only thresholding and export."
    )
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("method", (
            "Leave unconnected for carve_fraction. 'numeric' makes value a cutoff: for time-based, "
            "the tolerated shading in m²·h. Other sky-mode methods: 'protect_share' (value = share "
            "of the sky weight whose patch directions stay clear from every test point) and "
            "'headtail' (value ignored)."
        )),
        ("value", (
            "Sky modes: fraction of the obstruction score to remove (0-1); 0.7 is aggressive, "
            "0.3 conservative. With method 'numeric': the cutoff (time-based: tolerated shading "
            "in m²·h). With 'protect_share': the share to protect."
        )),
        ("score_smoothing", (
            "Score-cutoff methods only: Gaussian blur radius in meters applied to the scores "
            "before the cutoff. Empty = auto (1.1x voxel_size), 0 = off."
        )),
        ("carve_above", (
            "If True, carve all occupied voxels above the lowest carved region in each (x, y) "
            "column, so the envelope is a buildable height field without floating mass. "
            "Default: True."
        )),
        ("carve_above_min", (
            "Minimum number of consecutive carved voxels in a column before carve_above "
            "activates for that column. Higher values (2-3) keep stray single carved voxels "
            "from removing whole columns; shorter runs stay carved. Default: 1."
        )),
        ("max_slope", (
            "Steepest rise in degrees allowed between neighbouring columns after carve_above; "
            "taller columns are cut into ramps, which removes cliffs and spires. Empty = 75 for "
            "the score-cutoff methods of the sky modes, off otherwise. 90 = off."
        )),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    oo[0].Name, oo[0].Description = "overrides", (
        "Settings formatted for USC_ThresholdStage's 'threshold_overrides' (or USC_Config). "
        "Through ThresholdStage, a change re-runs only thresholding and export."
    )
except Exception:
    pass


def _warn(text):
    try:
        from Grasshopper.Kernel import GH_RuntimeMessageLevel
        ghenv.Component.AddRuntimeMessage(GH_RuntimeMessageLevel.Warning, text)
    except Exception:
        pass


_items = []

_m = str(method).strip().lower() if method is not None else None

if _m == "numeric":
    # 'numeric' is only a UI label: the pipeline needs the actual number,
    # and the config schema rejects the bare word.
    if value is not None:
        _items.append(f"threshold={float(value)}")
    else:
        _warn("method='numeric' needs a number in the 'value' input; "
              "no threshold override emitted (the mode default is used).")
elif _m in ("protect_share", "carve_fraction", "headtail"):
    _items.append(f"threshold={_m}")
    # protect_share and carve_fraction take value as their parameter;
    # headtail ignores it.
    if _m != "headtail" and value is not None:
        _items.append(f"{_m}={float(value)}")
elif _m is not None:
    # A number typed straight into 'method' is accepted as a numeric threshold.
    try:
        float(_m)
        _items.append(f"threshold={_m}")
    except ValueError:
        _warn(f"Unknown method {method!r}: use protect_share, carve_fraction, headtail or numeric. "
              "No threshold override emitted.")
elif value is not None:
    # No method connected: value is the parameter of the default method.
    _items.append(f"carve_fraction={float(value)}")

if score_smoothing is not None:
    _items.append(f"score_smoothing={float(score_smoothing)}")

if carve_above is not None:
    _items.append(f"carve_above={'true' if bool(carve_above) else 'false'}")

if carve_above_min is not None:
    _items.append(f"carve_above_min_consecutive={int(carve_above_min)}")

if max_slope is not None:
    _items.append(f"max_slope_deg={float(max_slope)}")

overrides = ";".join(_items) if _items else None
