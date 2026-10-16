"""USC Run Pipeline: run the full carving pipeline in one step.

Takes Rhino geometry, has the daemon run all three stages
(preprocessing, thresholding, exporting), and returns the carved mesh
to Grasshopper.  Needs a running daemon (USC_Session).

For finer control (e.g., adjusting the threshold without re-running
the ray tracing), use the individual stage components instead.

Inputs
------
config : USCConfig
    Config handle from USC Config.
max_volume : Mesh or Brep (list)
    Maximum volume envelope geometry.
test_surfaces : Mesh or Brep (list)
    Insolation test surfaces.
run : bool
    True to execute. False to idle (no computation).

Outputs
-------
mesh : Rhino.Geometry.Mesh
    Carved envelope mesh, ready for display in Rhino. None when the
    mesh format is not PLY (only PLY is loaded onto the canvas).
export_path : str
    Path to the exported mesh file on disk.
report_path : str
    Path to <out_dir>/run_report.md summarising the pipeline run (None
    if the file was not written).
diagnostics : str
    Summary of pipeline results (total time, voxel counts, threshold,
    mesh stats).
"""

import os
import time
from pathlib import Path

# -- GH UI rollovers --------------------------------------------------------
try:
    ghenv.Component.Name = "USC Run Pipeline"
    ghenv.Component.NickName = "USC_RunAll"
    ghenv.Component.Description = "Runs the full pipeline (Preprocess + Threshold + Export) in one step. Convenient for quick prototyping. For iterative threshold adjustment, use the decomposed stage components instead."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "config", "Configuration handle from USC_Config. Contains all settings for the full pipeline."
    ii[1].Name, ii[1].Description = "max_volume", "Maximum building envelope geometry (Mesh or Brep). Multiple objects are joined into one volume."
    ii[2].Name, ii[2].Description = "test_surfaces", "Surfaces requiring solar access (Mesh or Brep), one or many. Each must be a single flat panel; explode polysurfaces first."
    ii[3].Name, ii[3].Description = "run", "Boolean toggle. True to run the complete pipeline (preprocessing + thresholding + exporting) in one step."
    oo[0].Name, oo[0].Description = "mesh", "The carved envelope as a Rhino Mesh. Displayed directly in the viewport. Empty when final_mesh_format is not ply."
    oo[1].Name, oo[1].Description = "export_path", "Full path to the exported mesh file on disk."
    oo[2].Name, oo[2].Description = "report_path", "Full path to the run_report.md file. Contains a human-readable summary of the entire pipeline run."
    oo[3].Name, oo[3].Description = "diagnostics", "Summary of the full pipeline run: total time, filled voxels and score range, threshold and retention, final mesh statistics."
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


mesh = None
export_path = None
report_path = None
diagnostics = ""

if not run:
    diagnostics = "Idle: set run=True"
elif config is None:
    diagnostics = _error("Connect a USC Config component")
elif max_volume is None:
    diagnostics = _error("Connect max_volume geometry")
elif test_surfaces is None:
    diagnostics = _error("Connect test_surfaces geometry")
else:
    t_start = time.perf_counter()
    gh = _usc_gh(config.session.root)
    out_dir = Path(config.out_dir)
    try:
        vol_path, srf_path = gh.write_input_geometry(max_volume, test_surfaces, out_dir / "incoming")
        reply = gh.run_stages(config.session, config, ["exporting"], "preprocessing",
                              {"max_volume_path": vol_path, "test_surface_path": srf_path})
        gh.show_issues(ghenv.Component, reply)
        folders = reply["stage_folders"]
        export_path = reply["export_path"]
        if not os.path.isfile(export_path):
            raise RuntimeError("the daemon reported success but wrote no mesh at " + export_path)
        if export_path.lower().endswith(".ply"):
            mesh = gh.load_ply_to_rhino(export_path)
        else:
            gh.report(ghenv.Component, "Mesh saved to {}; the canvas preview reads PLY only "
                      "(set final_mesh_format=ply to preview)".format(export_path), "remark")

        lines = ["Total time: {:.1f}s".format(time.perf_counter() - t_start)]
        pre = gh.read_diagnostics(folders["preprocessing"])
        if pre:
            stats = pre.get("score_stats", {})
            lines.append("Preprocessing: {} voxels, scores [{:.4g} - {:.4g}]".format(
                pre.get("voxels_filled", "?"), stats.get("min", 0), stats.get("max", 0)))
        thr = gh.read_diagnostics(folders["thresholding"])
        if thr:
            lines.append("Thresholding: {} (value={}), kept {}%".format(
                thr.get("threshold_method", "?"), thr.get("threshold_value", "?"),
                thr.get("retention_pct", "?")))
        exp = gh.read_diagnostics(folders["exporting"])
        if exp:
            vol = exp.get("mesh_volume_m3")
            lines.append("Exporting: {} verts, {} faces{}".format(
                exp.get("vertices", "?"), exp.get("triangles", "?"),
                ", vol={:.1f} m3".format(vol) if vol is not None else ""))
        diagnostics = "\n".join(lines)
        report = out_dir / "run_report.md"
        report_path = str(report) if report.is_file() else None
    except Exception as e:
        diagnostics = _error(str(e))
