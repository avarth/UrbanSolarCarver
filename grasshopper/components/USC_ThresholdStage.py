"""USC Threshold Stage: apply a threshold to the saved scores (stage 2 of 3).

Takes the preprocessing result and applies a threshold to create a binary
mask. It reads the scores saved by preprocessing, so threshold parameters
can be adjusted and re-run without tracing rays again. Results go to
<out_dir>/thresholding/.

Connect threshold overrides here, not through Config: then changing the
threshold re-runs only this stage and Export, not Preprocessing.

Inputs
------
config : USCConfig
    Config handle from USC Config (carries base settings, out_dir, session).
pre_result : str
    Preprocessing manifest path from USC Preprocess.
threshold_overrides : str, optional
    Threshold parameter overrides from USC Threshold component.
    Merged on top of config overrides; changes here do not make
    Preprocessing re-run.
run : bool
    True to execute. False to idle.
after : str, optional
    thr_result of the previous criterion's USC Threshold Stage. Chains
    this criterion after that one: only voxels it kept are decided here.
    Leave empty for a single criterion.

Outputs
-------
thr_result : str
    Path to thresholding manifest.json.  Connect to USC Export.
threshold_value : float
    The resolved numeric threshold that was applied.
diagnostics : str
    Retention stats, method used, timing.
diag_images : list of str
    Path to threshold histogram image.
    Feed to Ladybug Image Viewer for in-canvas inspection.
    Empty unless plots are enabled (USC_Diagnostics).
"""

import time
from pathlib import Path

# -- GH UI ------------------------------------------------------------------
try:
    ghenv.Component.Name = "USC Threshold Stage"
    ghenv.Component.NickName = "USC_ThrStage"
    ghenv.Component.Description = "Stage 2/3: Applies a threshold to the score volume, producing a binary mask of voxels to keep. Reuses the saved scores, so the threshold can be changed without re-running preprocessing."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "config", "Configuration handle from USC_Config. Carries base settings and output directory."
    ii[1].Name, ii[1].Description = "pre_result", "Preprocessing manifest path from USC_Preprocess. Contains the score volume and grid metadata."
    ii[2].Name, ii[2].Description = "threshold_overrides", "Override string from USC_Threshold component. Connect it here, not through Config, so that changing the threshold re-runs only this stage and Export, not the slower Preprocessing step."
    ii[3].Name, ii[3].Description = "run", "Boolean toggle. True to execute thresholding."
    ii[4].Name, ii[4].Description = "after", "Optional. The thr_result of the previous criterion's USC_ThresholdStage. This criterion then decides only among the voxels that one kept, so the two carvings chain. Leave empty for a single criterion."
    oo[0].Name, oo[0].Description = "thr_result", "Path to the thresholding manifest file. Connect to USC_Export's 'thr_result' input."
    oo[1].Name, oo[1].Description = "threshold_value", "The numeric threshold that was actually applied. Useful for understanding what the algorithm chose (especially with 'headtail' or 'carve_fraction')."
    oo[2].Name, oo[2].Description = "diagnostics", "Text summary: threshold method, value, voxel retention percentage and counts, timing."
    if len(oo) > 3:
        oo[3].Name, oo[3].Description = "diag_images", "Path to the threshold histogram (shows score distribution with the threshold line). Feed to Ladybug Image Viewer. Empty unless plots are enabled (USC_Diagnostics)."
except Exception:
    pass


# -- Helpers ------------------------------------------------------------------

def _usc_gh(root):
    """Shared helpers from <carver_root>/grasshopper/usc_gh.py, reloaded when that file changes."""
    import importlib.util
    import sys
    path = Path(root) / "grasshopper" / "usc_gh.py"
    stamp = (str(path), path.stat().st_mtime)
    mod = sys.modules.get("usc_gh")
    if mod is None or getattr(mod, "_source", None) != stamp:
        spec = importlib.util.spec_from_file_location("usc_gh", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod._source = stamp
        sys.modules["usc_gh"] = mod
    return mod


def _error(msg):
    """Show an error on the component (red) and return msg."""
    from Grasshopper.Kernel import GH_RuntimeMessageLevel
    ghenv.Component.AddRuntimeMessage(GH_RuntimeMessageLevel.Error, msg)
    return msg


thr_result = None
threshold_value = None
diagnostics = ""
diag_images = []

if not run:
    diagnostics = "Idle: set run=True"
elif config is None:
    diagnostics = _error("Connect a USC Config component")
elif pre_result is None:
    diagnostics = _error("Connect pre_result from USC Preprocess")
else:
    t_start = time.perf_counter()
    gh = _usc_gh(config.session.root)
    # Threshold settings are merged here, not in Config, so changing them
    # re-runs only this stage and not Preprocess.
    try:
        mismatch = gh.stage_folder_mismatch(config, pre_result, "preprocessing")
        if mismatch:
            raise ValueError(mismatch)
        reply = gh.run_stages(config.session, config, ["thresholding"], "thresholding",
                              gh.parse_overrides(threshold_overrides), after=after or None)
        gh.show_issues(ghenv.Component, reply)
        thr_out = Path(reply["stage_folders"]["thresholding"])
        thr_result = reply["manifest"]
        if not Path(thr_result).is_file():
            raise RuntimeError("the daemon reported success but wrote no manifest at " + thr_result)
        data = gh.read_diagnostics(thr_out)
        threshold_value = data.get("threshold_value")
        lines = [
            "Thresholding: {:.1f}s".format(time.perf_counter() - t_start),
            "Method: {}".format(data.get("threshold_method", "?")),
            "Threshold: {}".format(threshold_value),
        ]
        if data.get("max_slope_deg") is not None:
            lines.append("Slope limit: {:g} deg (removed {} voxels, {:.1%} of the score)".format(
                data["max_slope_deg"], data.get("slope_limit_extra_voxels_removed", 0),
                data.get("obstruction_fraction_carved_by_slope_limit", 0.0)))
        lines += [
            "Kept: {}%".format(data.get("retention_pct", "?")),
            "Voxels kept: {} / {}".format(data.get("voxels_kept", "?"), data.get("voxels_occupied", "?")),
        ]
        diagnostics = "\n".join(lines)
        diag_images = gh.existing_files(data.get("threshold_histogram"))
    except Exception as e:
        diagnostics = _error(str(e))
