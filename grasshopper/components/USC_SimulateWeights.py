"""USC Simulate Weights — Generate simulated benefit weights.

Runs USC's ISO 13790 5R1C hourly building simulation (through the GPU
daemon's Python backend) to derive, for every hour of the year, what
fraction of a marginal joule of solar gain offsets heating (benefit)
and what fraction becomes cooling load (harm). Writes a
simulated_weights.json artifact plus a .png heatmap preview.

Wire the weights_path output into USC_BenefitParams'
simulated_weights_path input to drive a benefit-mode carve with the
simulated weights instead of the balance-point rule.

Inputs
------
session : USCSession
    Session handle from USC_Session (daemon must be running).
epw_path : str
    Path to the EPW weather file.
archetype : USCArchetype or str
    Archetype handle from USC_Archetype, or a path to an archetype YAML
    (see configs/archetype_example.yaml).
out_path : str, optional
    Artifact output path. Default: <session root>/simulated_weights.json
eps : float, optional
    Perturbation size in W (central differences). Default: 1.0
run : bool
    True to execute. False to idle.

Outputs
-------
weights_path : str
    Path to simulated_weights.json. Connect to USC_BenefitParams.
preview : str
    Path to the .png weights preview (day x hour benefit/harm heatmaps).
    Feed to Ladybug Image Viewer for in-canvas inspection.
summary : str
    Status and artifact provenance.
"""

import os
from pathlib import Path

# -- GH UI --------------------------------------------------------------------
try:
    ghenv.Component.Name = "USC Simulate Weights"
    ghenv.Component.NickName = "USC_SimWeights"
    ghenv.Component.Description = "Generates simulated benefit weights: an ISO 13790 5R1C hourly simulation of a typical building (USC_Archetype) derives when a marginal joule of solar gain is thermally useful — thermal lag, mass state, gain saturation. Writes simulated_weights.json + a .png preview. Wire weights_path into USC_BenefitParams to drive a benefit carve."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("session", "Session handle from USC_Session. The daemon must be running (start_daemon=True)."),
        ("epw_path", "Path to the EPW weather file for the site."),
        ("archetype", "Archetype from USC_Archetype, or a path to an archetype YAML file (see configs/archetype_example.yaml)."),
        ("out_path", "Optional output path for the artifact. Default: simulated_weights.json under the session root. The weights are cached by content downstream, so regenerating with a different archetype never yields stale carves."),
        ("eps", "Perturbation size in watts for the central-difference attribution. Default 1.0; rarely needs changing."),
        ("run", "Boolean toggle to execute. The simulation takes a few seconds (17 521 vectorised year-simulations)."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    if len(oo) > 0:
        oo[0].Name, oo[0].Description = "weights_path", "Path to the simulated_weights.json artifact. Connect to USC_BenefitParams' simulated_weights_path input."
    if len(oo) > 1:
        oo[1].Name, oo[1].Description = "preview", "Path to the .png weights preview (benefit and harm as day x hour heatmaps). Feed to Ladybug Image Viewer."
    if len(oo) > 2:
        oo[2].Name, oo[2].Description = "summary", "Status message and artifact provenance."
except Exception:
    pass


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


weights_path = None
preview = None
summary = ""

if not run:
    summary = "Idle: set run=True"
elif session is None:
    summary = _error("Connect a USC Session component")
elif archetype is None:
    summary = _error("Connect USC_Archetype or provide an archetype YAML path")
else:
    gh = _usc_gh(session.root)
    try:
        epw = gh.resolve_path(ghenv.Component, epw_path) if epw_path else None
        if not epw or not os.path.isfile(epw):
            raise ValueError("Provide a valid epw_path")
        # An USC_Archetype handle carries the archetype as a dict; a string is a YAML path.
        arch_payload = getattr(archetype, "data", None)
        if arch_payload is None:
            arch_payload = gh.resolve_path(ghenv.Component, archetype)
            if not os.path.isfile(arch_payload):
                raise ValueError("Archetype YAML not found: " + arch_payload)
        out = gh.resolve_path(ghenv.Component, out_path or "simulated_weights.json")
        reply = gh.call_daemon(session, "simulate_weights", {
            "epw": epw,
            "archetype": arch_payload,
            "out": out,
            "eps": float(eps) if eps is not None else 1.0,
        })
        weights_path = reply["artifact"]
        preview = reply.get("preview")
        summary = "Wrote {}\nEPW: {}\nWire weights_path into USC_BenefitParams.".format(
            weights_path, os.path.basename(epw))
    except Exception as e:
        summary = _error("simulate_weights failed: {}".format(e))
