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


def _add_error(msg):
    try:
        from Grasshopper.Kernel import GH_RuntimeMessageLevel
        ghenv.Component.AddRuntimeMessage(GH_RuntimeMessageLevel.Error, msg)
    except Exception:
        pass
    return msg


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


weights_path = None
preview = None
summary = ""

if not run:
    summary = "Idle — set run=True"
elif session is None:
    summary = _add_error("Connect a USC Session component")
elif not getattr(session, "daemon_running", False):
    summary = _add_error("Daemon not running — connect USC_Session and set "
                         "start_daemon=True")
elif not epw_path or not os.path.isfile(str(epw_path)):
    summary = _add_error("Provide a valid epw_path")
elif archetype is None:
    summary = _add_error("Connect USC_Archetype or provide an archetype "
                         "YAML path")
else:
    # Accept an USC_Archetype handle or a YAML path string.
    arch_payload = getattr(archetype, "data", None)
    if arch_payload is None:
        arch_str = str(archetype)
        if not os.path.isfile(arch_str):
            summary = _add_error(f"Archetype YAML not found: {arch_str}")
        arch_payload = arch_str
    if not summary:
        out = str(out_path) if out_path else os.path.join(
            str(getattr(session, "root", ".")), "simulated_weights.json")
        try:
            resp = _rpc_call(session, "simulate_weights", {
                "epw": str(epw_path),
                "archetype": arch_payload,
                "out": out,
                "eps": float(eps) if eps is not None else 1.0,
            })
            weights_path = resp.get("artifact")
            png = resp.get("preview")
            if png and os.path.isfile(png):
                preview = png
            summary = ("Wrote {}\nEPW: {}\nWire weights_path into "
                       "USC_BenefitParams.".format(
                           weights_path, os.path.basename(str(epw_path))))
        except Exception as e:
            summary = _add_error(f"simulate_weights failed: {e}")
