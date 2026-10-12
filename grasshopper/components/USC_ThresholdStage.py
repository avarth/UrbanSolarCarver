"""USC Threshold Stage — Apply threshold to cached scores (fast, iterative).

Takes the preprocessing result and applies a threshold to create a binary
mask. This is FAST (<1 second) — adjust the threshold parameters and
re-run without waiting for ray tracing again.

IMPORTANT: Connect threshold overrides DIRECTLY here (not through Config).
This way, changing the threshold slider only re-runs this stage + Export,
not Preprocessing.

Inputs
------
config : USCConfig
    Config handle from USC Config (carries base settings, out_dir, session).
pre_result : str
    Preprocessing manifest path from USC Preprocess.
threshold_overrides : str, optional
    Threshold parameter overrides from USC Threshold component.
    Merged on top of config overrides — changes here do NOT trigger
    Preprocessing to re-run.
run : bool
    True to execute. False to idle.

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
    Empty when diagnostics are disabled.
"""

import json
import os
import time
from pathlib import Path

# -- GH UI ------------------------------------------------------------------
try:
    ghenv.Component.Name = "USC Threshold Stage"
    ghenv.Component.NickName = "USC_ThrStage"
    ghenv.Component.Description = "Stage 2/4: Applies a threshold to the score volume, producing a binary mask of voxels to keep. Fast (<1s) — change the threshold without re-running preprocessing."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "config", "Configuration handle from USC_Config. Carries base settings and output directory."
    ii[1].Name, ii[1].Description = "pre_result", "Preprocessing manifest path from USC_Preprocess. Contains the score volume and grid metadata."
    ii[2].Name, ii[2].Description = "threshold_overrides", "Override string from USC_Threshold component. Connect DIRECTLY here (not through Config) so that changing the threshold slider only re-runs this stage and Export -- not the expensive Preprocessing step."
    ii[3].Name, ii[3].Description = "run", "Boolean toggle. True to execute thresholding."
    oo[0].Name, oo[0].Description = "thr_result", "Path to the thresholding manifest file. Connect to USC_Export's 'thr_result' input."
    oo[1].Name, oo[1].Description = "threshold_value", "The numeric threshold that was actually applied. Useful for understanding what the algorithm chose (especially with 'headtail' or 'carve_fraction')."
    oo[2].Name, oo[2].Description = "diagnostics", "Text summary: threshold method, value, voxel retention percentage, timing."
    if len(oo) > 3:
        oo[3].Name, oo[3].Description = "diag_images", "Path to the threshold histogram (shows score distribution with the threshold line). Feed to Ladybug Image Viewer. Empty when diagnostics are disabled."
except Exception:
    pass


# -- Helpers -----------------------------------------------------------------

def _parse_overrides(x):
    """Parse semicolon-joined override string(s) into a dict."""
    if x is None:
        return {}
    items = str(x).split(";") if isinstance(x, str) else []
    result = {}
    for item in items:
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def _rpc_call(session, cmd, payload):
    from multiprocessing.connection import Client as MPClient
    authkey = getattr(session, "authkey", None)
    if authkey is None:
        raise RuntimeError("No daemon authkey — start the daemon first")
    c = MPClient((session.host, session.port), authkey=authkey)
    c.send({"cmd": cmd, **payload})
    resp = c.recv()
    c.close()
    if isinstance(resp, dict) and resp.get("status") == "error":
        raise RuntimeError(resp.get("error", "Unknown error"))
    return resp


# -- Main logic --------------------------------------------------------------

def _add_error(msg):
    """Surface an error on the GH component (turns it red) and return msg."""
    try:
        from Grasshopper.Kernel import GH_RuntimeMessageLevel
        ghenv.Component.AddRuntimeMessage(GH_RuntimeMessageLevel.Error, msg)
    except Exception:
        pass
    return msg


thr_result = None
threshold_value = None
diagnostics = ""
diag_images = []

if not run:
    diagnostics = "Idle — set run=True"
elif config is None:
    diagnostics = _add_error("Connect a USC Config component")
elif pre_result is None:
    diagnostics = _add_error("Connect pre_result from USC Preprocess")
else:
    t_start = time.perf_counter()
    session = config.session
    out_dir = config.out_dir

    # Start with config overrides, then merge threshold-specific ones on top.
    # This means threshold_overrides changes do NOT change config → do NOT
    # trigger Preprocessing to re-run.
    overrides = dict(config.overrides)
    thr_ovr = _parse_overrides(threshold_overrides)
    overrides.update(thr_ovr)

    try:
        thr_out = str(Path(out_dir) / "thresholding")
        if getattr(session, "daemon_running", False):
            resp = _rpc_call(session, "thresholding", {
                "from": str(pre_result),
                "config": config.yaml_path,
                "overrides": [f"{k}={v}" for k, v in overrides.items()],
                "out_dir": thr_out,
            })
            # Use daemon response if available, otherwise construct from known path
            thr_manifest = resp.get("manifest", "")
            if not thr_manifest or not Path(thr_manifest).is_file():
                thr_manifest = str(Path(thr_out) / "manifest.json")
            thr_result = thr_manifest
            # Read diagnostics
            elapsed = time.perf_counter() - t_start
            diag_lines = [f"Thresholding: {elapsed:.1f}s"]
            summary_path = Path(thr_out) / "diagnostics" / "diagnostic.json"
            if summary_path.exists():
                data = json.load(open(summary_path))
                threshold_value = data.get("threshold_value")
                diag_lines.append(f"Method: {data.get('threshold_method', '?')}")
                diag_lines.append(f"Threshold: {threshold_value}")
                diag_lines.append(f"Kept: {data.get('retention_pct', '?')}%")
                diag_lines.append(f"Voxels kept: {data.get('voxels_kept', '?')} / {data.get('voxels_occupied', '?')}")
                # Collect histogram path for LB Image Viewer
                hist = data.get("threshold_histogram")
                if hist and os.path.isfile(hist):
                    diag_images.append(hist)
            diagnostics = "\n".join(diag_lines)
        else:
            diagnostics = _add_error("Daemon not running — connect USC_Session and set start_daemon=True")

    except Exception as e:
        diagnostics = _add_error(str(e))
