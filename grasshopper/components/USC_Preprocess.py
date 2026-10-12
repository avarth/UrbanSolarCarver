"""USC Preprocess: run the ray-tracing stage (stage 1 of 3, the slowest).

Voxelizes the max volume, samples test surfaces, and casts rays through
the grid to compute per-voxel obstruction scores. It re-runs whenever its
inputs change, including the Config, so wire threshold and postprocess
settings into USC Threshold Stage and USC Export instead of Config.

The geometry is written to <out_dir>/incoming/ as PLY files and the
results to <out_dir>/preprocessing/. Connect the pre_result output to
USC Threshold Stage.

Inputs
------
config : USCConfig
    Config handle from USC Config.
max_volume : Mesh or Brep (list)
    Maximum volume envelope geometry.
test_surfaces : Mesh or Brep (list)
    Insolation test surfaces.
run : bool
    True to execute. False to idle.

Outputs
-------
pre_result : str
    Path to preprocessing manifest.json.  Connect to USC Threshold Stage.
diagnostics : str
    Score statistics, grid info, timing.
diag_images : list of str
    Paths to diagnostic images (score histogram, sky patch plots).
    Feed to Ladybug Image Viewer for in-canvas inspection.
    Empty unless plots are enabled (USC_Diagnostics).
test_points : list of Point3d
    Sample points generated from test surfaces during preprocessing.
    Useful for verifying sampling density and surface coverage. Empty
    if the stage wrote no test_points.npy.
"""

import os
import time
from pathlib import Path

# -- GH UI ------------------------------------------------------------------
try:
    ghenv.Component.Name = "USC Preprocess"
    ghenv.Component.NickName = "USC_Preprocess"
    ghenv.Component.Description = "Stage 1/3: Voxelizes the max volume and traces rays from test surfaces through the grid, computing per-voxel obstruction scores. This is the most computationally expensive step; it re-runs whenever its inputs (geometry or Config) change."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "config", "Configuration handle from USC_Config. Contains mode, file paths, and all parameter overrides."
    ii[1].Name, ii[1].Description = "max_volume", "The maximum building envelope: the largest volume the building could occupy before solar carving. Provide as Rhino Mesh or Brep. Multiple objects are joined into one volume."
    ii[2].Name, ii[2].Description = "test_surfaces", "Surfaces that need solar access (neighbouring facades, public spaces, parks). Rays are cast from these surfaces through the max volume. Provide as Rhino Mesh or Brep (one or many). Surfaces are sampled as a uniform point grid at grid_step spacing (set in USC_GridSettings); each sample point casts rays, so a smaller grid_step gives more points, finer results and a slower run. Each surface must be a single flat panel: explode polysurfaces (e.g. extruded block boundaries) into individual faces before connecting. Non-flat pieces are skipped, and preprocessing fails if no piece is flat."
    ii[3].Name, ii[3].Description = "run", "Boolean toggle to execute. Set True to run preprocessing. Set False to prevent computation (useful while adjusting parameters)."
    oo[0].Name, oo[0].Description = "pre_result", "Path to the preprocessing manifest file. Connect this to USC_ThresholdStage's 'pre_result' input to continue the pipeline."
    oo[1].Name, oo[1].Description = "diagnostics", "Text summary: grid dimensions, filled voxels, score range, timing. Check this to verify the preprocessing ran correctly."
    oo[2].Name, oo[2].Description = "diag_images", "Paths to diagnostic images (score histogram, sky patch weight/intensity plots). Feed to Ladybug Image Viewer for in-canvas visualisation. Empty unless plots are enabled (USC_Diagnostics)."
    oo[3].Name, oo[3].Description = "test_points", "Sample points generated from test surfaces at grid_step spacing. Visualise in Rhino to verify sampling density and surface coverage. If too sparse, reduce grid_step in USC_GridSettings."
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


# -- Main logic --------------------------------------------------------------

pre_result = None
diagnostics = ""
diag_images = []
test_points = []

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
    pre_out = out_dir / "preprocessing"
    try:
        vol_path, srf_path = gh.write_input_geometry(max_volume, test_surfaces, out_dir / "incoming")
        overrides = dict(config.overrides, max_volume_path=vol_path, test_surface_path=srf_path)
        reply = gh.call_daemon(config.session, "preprocessing", {
            "config": config.yaml_path,
            "overrides": gh.override_list(overrides),
            "out_dir": str(pre_out),
        })
        pre_result = reply["manifest"]
        if not os.path.isfile(pre_result):
            raise RuntimeError("the daemon reported success but wrote no manifest at " + pre_result)

        data = gh.read_diagnostics(pre_out)
        stats = data.get("score_stats", {})
        lines = [
            "Preprocessing: {:.1f}s".format(time.perf_counter() - t_start),
            "Grid: {}".format(data.get("grid_shape", "?")),
            "Filled voxels: {}".format(data.get("voxels_filled", "?")),
            "Scores: [{:.4g} - {:.4g}]".format(stats.get("min", 0), stats.get("max", 0)),
            "Test points: {}".format(data.get("test_surface_points", "?")),
        ]
        cmp_stats = data.get("sky_patch_comparison_stats")
        if cmp_stats:
            lines.append(
                "Simulated vs simple weights: {:.1f}% of sky-weight mass redistributed "
                "({} of 145 patches changed by >20%)".format(
                    cmp_stats.get("mass_redistributed_pct", 0), cmp_stats.get("patches_over_20pct", 0)))
        diagnostics = "\n".join(lines)
        diag_images = gh.existing_files(data.get("score_histogram"),
                                        *data.get("sky_patch_images", []),
                                        data.get("sky_patch_comparison_image"))
        points_file = pre_out / "test_points.npy"
        if points_file.is_file():
            test_points = gh.read_npy_points(points_file)
    except Exception as e:
        diagnostics = _error(str(e))
