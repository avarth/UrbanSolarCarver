"""USC Diagnostics — Control diagnostic output for all pipeline stages.

Each stage always writes core JSON diagnostics (score statistics and
wall/CPU timings) to a ``diagnostics/`` subdirectory alongside the stage
artifacts.

The ``plots`` toggle additionally generates plot images (score
histograms, sky patch weight/intensity plots, threshold histograms).
These add matplotlib overhead, so they are off by default.  Image paths
are surfaced by the Preprocess and ThresholdStage components via their
``diag_images`` output, which can be fed directly to Ladybug's Image
Viewer component.

Inputs
------
enable : bool
    True = include detailed score statistics (median, std, percentiles)
    in the per-stage diagnostics JSON. Basic statistics (count, min,
    max, mean) and timings are always written. The detailed set adds
    sorting passes over the full score volume — slow on large grids.
    Default: False.
plots : bool, optional
    True = generate diagnostic plot images (score histograms, sky patch
    weight/intensity plots, threshold histograms).
    Default: False (no matplotlib overhead).

Outputs
-------
overrides : str
    Override string for USC Config.
    Connect to the ``overrides`` input of USC Config.
"""

try:
    ghenv.Component.Name = "USC Diagnostics"
    ghenv.Component.NickName = "USC_Diag"
    ghenv.Component.Description = "Controls diagnostic depth: detailed score statistics (enable) and plot images (plots). Basic JSON diagnostics (score range, timings) are always written by each stage. Enable for inspection and validation; disable for faster production runs."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    if len(ii) > 0:
        ii[0].Name, ii[0].Description = "enable", "True = include detailed score statistics (median, std, percentiles) in each stage's diagnostics JSON. Basic stats (count, min, max, mean) and timings are always written. Detailed stats add sorting passes over the full score volume — slow on large grids. Default: False."
    if len(ii) > 1:
        ii[1].Name, ii[1].Description = "plots", "True = generate diagnostic plot images (score histograms, sky dome plots) in each stage's diagnostics folder. Adds matplotlib overhead. Default: False."
    if len(oo) > 0:
        oo[0].Name, oo[0].Description = "overrides", "Diagnostics toggle formatted for USC_Config. Connect to Config's 'overrides' input."
except Exception:
    pass

parts = []
if enable is not None:
    parts.append(f"diagnostics={'true' if bool(enable) else 'false'}")
if plots is not None:
    parts.append(f"diagnostic_plots={'true' if bool(plots) else 'false'}")
elif enable is not None:
    # When plots is not connected, follow the enable toggle
    parts.append(f"diagnostic_plots={'true' if bool(enable) else 'false'}")

overrides = ";".join(parts) if parts else None
