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
    Sets the ``diagnostics`` config flag. Currently the core JSON
    diagnostics are always written regardless; this flag is reserved
    for future verbosity control.
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
    ghenv.Component.Description = "Controls diagnostic plot images (histograms, sky dome plots). Core JSON diagnostics (statistics, timings) are always written by each stage. Enable plots for inspection and validation; disable for faster production runs."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    if len(ii) > 0:
        ii[0].Name, ii[0].Description = "enable", "Sets the 'diagnostics' config flag. Core JSON diagnostics (statistics, timings) are currently always written regardless; this flag is reserved for future verbosity control."
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
