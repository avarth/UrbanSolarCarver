"""USC Threshold — Control how the score volume is binarized.

The threshold determines which voxels are "obstructing" (removed) vs
"kept" (part of the final envelope).

Inputs
------
method : str, optional
    Threshold strategy. One of:
      "carve_fraction" — remove voxels accounting for X% of total score
      "headtail"       — head-tail breaks (for skewed distributions)
      "numeric"        — direct raw-score cutoff
    If None, uses the mode default (carve_fraction).
value : float, optional
    Meaning depends on method:
      carve_fraction → fraction of total obstruction to remove (0-1).
      headtail       → ignored (algorithm is automatic).
      numeric        → raw score threshold; voxels above are removed.
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
    structurally implausible floating mass above carved zones.
    Default: False.
carve_above_min : int, optional
    Minimum consecutive carved voxels in a column before carve_above
    activates for that column.  Higher values (2-3) prevent stray
    single-voxel carvings from triggering aggressive removal.
    Default: 1.

Outputs
-------
overrides : str
    Semicolon-joined key=value string for Config.
"""

try:
    ghenv.Component.Name = "USC Threshold"
    ghenv.Component.NickName = "USC_Threshold"
    ghenv.Component.Description = (
        "Controls how the carving threshold is determined, optional score smoothing, "
        "and column-based carve-above post-processing. "
        "'carve_fraction' (default) removes a percentage of total obstruction weight — most intuitive. "
        "'headtail' uses head-tail breaks for automatic statistical splitting. "
        "'numeric' applies a direct raw-score cutoff. "
        "score_smoothing applies Gaussian blur to scores before thresholding for cleaner results. "
        "carve_above removes floating occupied voxels above carved zones. "
        "Connect output to Config or directly to ThresholdStage."
    )
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("method", (
            "How to determine the carving threshold. Options: "
            "'carve_fraction' (default, remove a percentage of total obstruction weight — most intuitive), "
            "'headtail' (automatic heavy-tail distribution split — value is ignored), "
            "'numeric' (direct raw-score cutoff — set the exact threshold via value)."
        )),
        ("value", (
            "Threshold parameter whose meaning depends on method:\n"
            "  carve_fraction → fraction to carve (0.0-1.0). "
            "0.7 = remove 70% of obstruction weight. Start with 0.5.\n"
            "  headtail → ignored (automatic).\n"
            "  numeric → raw score cutoff. Voxels scoring above this are removed."
        )),
        ("score_smoothing", (
            "Gaussian blur radius in meters applied to the score volume before thresholding. "
            "Smooths resolution-dependent noise so the carved mesh is cleaner at fine voxel sizes. "
            "Leave empty (default) = auto: 1.1× voxel_size — recommended for most runs. "
            "Set to 0 to disable smoothing entirely. "
            "Positive value = explicit radius in meters. Rule of thumb: 1.0–1.2× voxel_size works well. "
            "Over-smoothing (above 2× voxel_size) rounds features excessively. "
            "Only affects weighted-score modes (irradiance, benefit, daylight, radiative_cooling)."
        )),
        ("carve_above", (
            "If True, carve all occupied voxels above the lowest sufficiently-carved "
            "region in each (x, y) column. Removes structurally implausible floating mass "
            "above already-carved zones. Default: False (disabled)."
        )),
        ("carve_above_min", (
            "Minimum number of consecutive carved (empty) voxels in a column before "
            "carve_above activates for that column. Higher values (2-3) prevent stray "
            "single-voxel carvings from triggering aggressive column removal. Default: 1."
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


_items = []

_m = str(method).strip().lower() if method is not None else None

if _m == "numeric":
    # 'numeric' is only a UI label — the pipeline needs the actual number.
    # Never emit the bare placeholder (the config schema rejects it).
    if value is not None:
        _items.append(f"threshold={float(value)}")
    else:
        try:
            from Grasshopper.Kernel import GH_RuntimeMessageLevel
            ghenv.Component.AddRuntimeMessage(
                GH_RuntimeMessageLevel.Warning,
                "method='numeric' needs a number in the 'value' input — "
                "no threshold override emitted (mode default will be used).",
            )
        except Exception:
            pass
elif _m in ("headtail", "carve_fraction"):
    _items.append(f"threshold={_m}")
    # carve_fraction: value is the fraction to carve; headtail ignores value.
    if _m == "carve_fraction" and value is not None:
        _items.append(f"carve_fraction={float(value)}")
elif _m is not None:
    # Might be a bare number (legacy shorthand for numeric threshold)
    try:
        float(_m)
        _items.append(f"threshold={_m}")
    except ValueError:
        pass  # invalid, ignore
elif value is not None:
    # No method connected: value maps to carve_fraction (the mode default).
    _items.append(f"carve_fraction={float(value)}")

if score_smoothing is not None:
    _items.append(f"score_smoothing={float(score_smoothing)}")

if carve_above is not None:
    _items.append(f"carve_above={'true' if bool(carve_above) else 'false'}")

if carve_above_min is not None:
    _items.append(f"carve_above_min_consecutive={int(carve_above_min)}")

overrides = ";".join(_items) if _items else None
