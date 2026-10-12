"""USC Threshold: control how the score volume is binarized.

The threshold determines which voxels are "obstructing" (removed) vs
"kept" (part of the final envelope).

Inputs
------
method : str, optional
    Threshold strategy. One of:
      "protect_share":  keep the highest-weight sky patches that hold the
                        given share of the total weight visible from every
                        test point (whole rays are cleared)
      "carve_fraction": remove the highest-scoring voxels that together
                        hold the given fraction of the total score
      "headtail":       head-tail breaks (for skewed distributions)
      "numeric":        direct raw-score cutoff
    A number typed here is used as a numeric cutoff. If None, the config's
    threshold applies (protect_share in the shipped configs of weighted
    modes, cutoff 0 for time-based and tilted_plane).
value : float, optional
    Meaning depends on method:
      protect_share  → share of the total sky weight to protect (0-1).
      carve_fraction → fraction of total obstruction to remove (0-1).
      headtail       → ignored (algorithm is automatic).
      numeric        → raw score threshold; voxels above are removed.
      no method      → used as protect_share.
score_smoothing : float, optional
    Gaussian blur radius (meters) applied to the score volume before
    thresholding.  Smooths resolution-dependent noise so the carved
    mesh is cleaner at fine voxel sizes.
    None (default) = auto: 1.1 × voxel_size.
    0 = disabled.
    Positive value = explicit radius in meters (1.0–1.2× voxel_size
    recommended; over-smoothing above 2× rounds features).
    Only affects weighted-score modes (irradiance, benefit, daylight,
    radiative_cooling).
carve_above : bool, optional
    If True, carve all occupied voxels above the lowest
    sufficiently-carved region in each (x, y) column.  Removes
    floating mass above carved zones (buildable height field).
    Default: True.
carve_above_min : int, optional
    Minimum consecutive carved voxels in a column before carve_above
    activates for that column.  Higher values (2-3) prevent stray
    single-voxel carvings from triggering aggressive removal;
    shorter runs stay carved.  Default: 1.

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
        "Controls how the carving threshold is determined, optional score smoothing, "
        "and column-based carve-above post-processing. "
        "'protect_share' (default for weighted modes) keeps the highest-weight sky patches visible from "
        "every test point and gives continuous envelopes. "
        "'carve_fraction' removes a fraction of the total obstruction weight; with carve_above it can leave "
        "cliffs and spires. "
        "'headtail' uses head-tail breaks for automatic statistical splitting. "
        "'numeric' applies a direct raw-score cutoff. "
        "score_smoothing applies Gaussian blur to scores before thresholding for cleaner results. "
        "carve_above removes floating occupied voxels above carved zones. "
        "Connect the output to ThresholdStage (re-runs only thresholding and export) or to Config."
    )
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("method", (
            "How to determine the carving threshold. Options: "
            "'protect_share' (keep the highest-weight sky patches holding a share of the total weight "
            "visible from every test point; default for weighted modes), "
            "'carve_fraction' (remove a fraction of the total obstruction weight; can leave cliffs and "
            "spires with carve_above), "
            "'headtail' (automatic heavy-tail distribution split; value is ignored), "
            "'numeric' (direct raw-score cutoff; set the exact threshold via value). "
            "Unset: the config's threshold (protect_share in the shipped configs of weighted modes, "
            "cutoff 0 for time-based and tilted_plane)."
        )),
        ("value", (
            "Threshold parameter whose meaning depends on method:\n"
            "  protect_share → share of the total sky weight to protect (0.0-1.0). "
            "Small values already carve a lot; start with 0.1.\n"
            "  carve_fraction → fraction to carve (0.0-1.0). "
            "0.7 = remove 70% of obstruction weight. Start with 0.5.\n"
            "  headtail → ignored (automatic).\n"
            "  numeric → raw score cutoff. Voxels scoring above this are removed.\n"
            "  no method → used as protect_share."
        )),
        ("score_smoothing", (
            "Gaussian blur radius in meters applied to the score volume before thresholding. "
            "Smooths resolution-dependent noise so the carved mesh is cleaner at fine voxel sizes. "
            "Leave empty (default) = auto: 1.1× voxel_size, recommended for most runs. "
            "Set to 0 to disable smoothing entirely. "
            "Positive value = explicit radius in meters. Rule of thumb: 1.0–1.2× voxel_size works well. "
            "Over-smoothing (above 2× voxel_size) rounds features excessively. "
            "Only affects weighted-score modes (irradiance, benefit, daylight, radiative_cooling)."
        )),
        ("carve_above", (
            "If True, carve all occupied voxels above the lowest sufficiently-carved "
            "region in each (x, y) column, so the envelope is a buildable height field "
            "without floating mass. Default: True."
        )),
        ("carve_above_min", (
            "Minimum number of consecutive carved (empty) voxels in a column before "
            "carve_above activates for that column. Higher values (2-3) prevent stray "
            "single-voxel carvings from triggering aggressive column removal; shorter "
            "runs stay carved. Default: 1."
        )),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    oo[0].Name, oo[0].Description = "overrides", (
        "Threshold, smoothing, and carve-above settings formatted for USC_Config or USC_ThresholdStage. "
        "Connect to ThresholdStage's 'threshold_overrides' for iterative "
        "adjustment without re-running preprocessing."
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
