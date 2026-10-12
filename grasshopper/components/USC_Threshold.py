"""USC Threshold: how much to carve, and the column clean-up.

Sky modes (irradiance, benefit, daylight, radiative_cooling): connect only
value, the share (0-1) of the sky's weight to protect: the rays from every
test point to the centres of the highest-weight sky patches holding that
share are kept clear (protect_share). time-based: set method to "numeric" and
value to the tolerated shading in m²·h. tilted_plane: leave this
component unconnected (the plane angle decides).

Inputs
------
method : str, optional
    Leave unconnected for the sky modes. "numeric" makes value a cutoff:
    for time-based, the tolerated shading in m²·h. Legacy sky-mode methods,
    kept so older definitions still work: "carve_fraction" (value = fraction
    of the obstruction score to remove), "headtail" (value ignored), and
    "protect_share" written out. The legacy methods cut on voxel scores,
    which does not return a predictable share of the sky and can leave
    cliffs and spires.
value : float, optional
    Sky modes: share of the sky's weight (0-1) to protect; the rays to the
    protected sky patches stay clear from every test point. Small values
    already carve a lot; start at 0.1.
    With method "numeric": the cutoff (time-based: m²·h). With
    "carve_fraction": the fraction to remove.
score_smoothing : float, optional
    Legacy sky-mode methods only: Gaussian blur radius (m) of the scores
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
        "How much to carve. Sky modes: connect only 'value', the share (0-1) of the sky's weight "
        "to protect (the rays to the top sky patches stay clear); start at 0.1. time-based: set method to "
        "'numeric' and value to the tolerated shading in m²·h. Also controls carve_above "
        "(removes floating mass above carved zones). Connect the output to ThresholdStage, which "
        "re-runs only thresholding and export."
    )
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("method", (
            "Leave unconnected for the sky modes. 'numeric' makes value a cutoff: for time-based, "
            "the tolerated shading in m²·h. Legacy sky-mode methods, kept for older definitions: "
            "'carve_fraction' (value = fraction of the obstruction score to remove) and 'headtail' "
            "(value ignored). They cut on voxel scores and can leave cliffs and spires."
        )),
        ("value", (
            "Sky modes: share of the sky's weight (0-1) to protect; the rays to the protected sky "
            "patches stay clear from every test point. "
            "Small values already carve a lot; start at 0.1. "
            "With method 'numeric': the cutoff (time-based: tolerated shading in m²·h). "
            "With 'carve_fraction': the fraction to remove."
        )),
        ("score_smoothing", (
            "Legacy sky-mode methods only: Gaussian blur radius in meters applied to the scores "
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
    _items.append(f"protect_share={float(value)}")

if score_smoothing is not None:
    _items.append(f"score_smoothing={float(score_smoothing)}")

if carve_above is not None:
    _items.append(f"carve_above={'true' if bool(carve_above) else 'false'}")

if carve_above_min is not None:
    _items.append(f"carve_above_min_consecutive={int(carve_above_min)}")

overrides = ";".join(_items) if _items else None
