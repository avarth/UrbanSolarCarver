"""USC Export — Convert binary mask to mesh (fast, returns to Rhino).

Takes the thresholding result and reconstructs a triangle mesh from the
carved voxel field. Returns the mesh directly to Grasshopper.

This is fast — runs in 1-3 seconds.

Inputs
------
config : USCConfig
    Config handle from USC Config.
thr_result : str
    Thresholding manifest path from USC Threshold Stage.
postprocess_overrides : str, optional
    Postprocessing parameter overrides from USC Postprocess component.
    Connect DIRECTLY here (not through Config) so that changing smoothing
    or cleanup settings only re-runs Export — not Preprocessing or
    Thresholding.
run : bool
    True to execute. False to idle.

Outputs
-------
mesh : Rhino.Geometry.Mesh
    Carved envelope mesh, ready for display in Rhino.
export_path : str
    Path to the exported mesh file on disk.
report_path : str
    Path to the run_report.md file summarising the full pipeline run.
diagnostics : str
    Mesh stats (vertices, faces, volume), timing.
"""

import os
import time
from pathlib import Path


# -- GH UI ------------------------------------------------------------------
try:
    ghenv.Component.Name = "USC Export"
    ghenv.Component.NickName = "USC_Export"
    ghenv.Component.Description = "Stage 3: Converts the binary voxel mask into a triangle mesh and returns it to the Grasshopper canvas. Also saves the mesh to disk."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "config", "Configuration handle from USC_Config."
    ii[1].Name, ii[1].Description = "thr_result", "Thresholding manifest path from USC_ThresholdStage."
    ii[2].Name, ii[2].Description = "postprocess_overrides", "Override string from USC_Postprocess component. Connect DIRECTLY here (not through Config) so that changing smoothing or cleanup settings only re-runs Export — not the expensive Preprocessing or Thresholding steps."
    ii[3].Name, ii[3].Description = "run", "Boolean toggle. True to extract and return the mesh."
    oo[0].Name, oo[0].Description = "mesh", "The carved envelope as a Rhino Mesh, displayed directly in the viewport. This is the main result -- bake it, export it, or use it in downstream Grasshopper operations."
    oo[1].Name, oo[1].Description = "export_path", "Full path to the mesh file saved on disk (PLY format by default). Useful if you need to open the result in another application."
    oo[2].Name, oo[2].Description = "report_path", "Full path to the run_report.md file. Contains a human-readable summary of the entire pipeline run: configuration, scores, thresholding, mesh stats, and timings."
    oo[3].Name, oo[3].Description = "diagnostics", "Text summary: vertex/face counts, mesh volume, bounding box dimensions, timing."
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
elif thr_result is None:
    diagnostics = _error("Connect thr_result from USC Threshold Stage")
else:
    t_start = time.perf_counter()
    gh = _usc_gh(config.session.root)
    exp_out = Path(config.out_dir) / "exporting"
    # Postprocess settings are merged here, not in Config, so changing them
    # re-runs only Export.
    overrides = dict(config.overrides, **gh.parse_overrides(postprocess_overrides))
    try:
        reply = gh.call_daemon(config.session, "exporting", {
            "from": str(thr_result),
            "config": config.yaml_path,
            "overrides": gh.override_list(overrides),
            "out_dir": str(exp_out),
        })
        export_path = reply["export_path"]
        if not os.path.isfile(export_path):
            raise RuntimeError("the daemon reported success but wrote no mesh at " + export_path)
        if export_path.lower().endswith(".ply"):
            mesh = gh.load_ply_to_rhino(export_path)
        else:
            gh.report(ghenv.Component, "Mesh saved to {}; the canvas preview reads PLY only "
                      "(set final_mesh_format=ply to preview)".format(export_path), "remark")

        data = gh.read_diagnostics(exp_out)
        lines = ["Exporting: {:.1f}s".format(time.perf_counter() - t_start),
                 "Vertices: {}".format(data.get("vertices", "?")),
                 "Triangles: {}".format(data.get("triangles", "?"))]
        if data.get("mesh_volume_m3") is not None:
            lines.append("Volume: {:.1f} m3".format(data["mesh_volume_m3"]))
        bbox = data.get("bbox_dimensions_m")
        if bbox:
            lines.append("BBox: {:.1f} x {:.1f} x {:.1f} m".format(*bbox))
        if data.get("voxel_retention_pct") is not None:
            lines.append("Voxel retention: {}%".format(data["voxel_retention_pct"]))
        diagnostics = "\n".join(lines)
        report = exp_out.parent / "run_report.md"
        report_path = str(report) if report.is_file() else None
    except Exception as e:
        diagnostics = _error(str(e))
