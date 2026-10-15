"""USC Massing: stacked floor plates that follow the footprint (stage 4).

Takes the thresholding result and builds floor plates: a ground floor and
equal floors above it, each made of bays cut perpendicular to the facades
and kept where they fit the carved envelope. The daemon writes the plates
to <out_dir>/massing/ and the component returns them as closed Breps.

Inputs
------
config : USCConfig
    Config handle from USC Config.
thr_result : str
    Thresholding manifest path from USC Threshold Stage.
massing_overrides : str, optional
    Settings from USC Massing Settings. Connect them here, not through
    Config, so that changing them re-runs only Massing.
run : bool
    True to execute. False to idle.

Outputs
-------
plates : list of Rhino.Geometry.Brep
    One closed Brep per floor plate.
floor_areas : list of float
    Gross floor area per floor (m2), from the ground floor up.
total_floor_area : float
    Sum of the floor areas (m2).
plates_path : str
    Path to plates.json (outlines in world coordinates).
diagnostics : str
    Floors, plates, floor areas and timing.
report_path : str
    Path to <out_dir>/run_report.md (None if not written).
"""

import time
from pathlib import Path


# -- GH UI ------------------------------------------------------------------
try:
    ghenv.Component.Name = "USC Massing"
    ghenv.Component.NickName = "USC_Massing"
    ghenv.Component.Description = "Stage 4: builds stacked floor plates that follow the footprint, cut into bays perpendicular to the facades, kept where they fit the carved envelope. Returns closed Breps and floor areas."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "config", "Configuration handle from USC_Config."
    ii[1].Name, ii[1].Description = "thr_result", "Thresholding manifest path from USC_ThresholdStage."
    ii[2].Name, ii[2].Description = "massing_overrides", "Override string from USC_MassingSettings. Connect it here, not through Config, so that changing massing settings re-runs only Massing."
    ii[3].Name, ii[3].Description = "run", "Boolean toggle. True to build the floor plates."
    oo[0].Name, oo[0].Description = "plates", "One closed Brep per floor plate, in world coordinates."
    oo[1].Name, oo[1].Description = "floor_areas", "Gross floor area per floor in m2, from the ground floor up."
    oo[2].Name, oo[2].Description = "total_floor_area", "Sum of the floor areas in m2."
    oo[3].Name, oo[3].Description = "plates_path", "Path to plates.json with the plate outlines in world coordinates."
    oo[4].Name, oo[4].Description = "diagnostics", "Text summary: floors, plates, floor areas, timing."
    oo[5].Name, oo[5].Description = "report_path", "Full path to run_report.md, which includes a Massing section."
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


def _plate_brep(plate, tol=0.001):
    """Closed Brep of one plate: its outline and holes extruded between z_bottom and z_top."""
    import Rhino.Geometry as rg
    zb, zt = plate["z_bottom"], plate["z_top"]
    rings = [plate["outline"]] + plate["holes"]
    curves = [rg.PolylineCurve([rg.Point3d(x, y, zb) for x, y in ring]) for ring in rings]
    planar = rg.Brep.CreatePlanarBreps(curves, tol)
    if not planar:
        return None
    path = rg.LineCurve(rg.Point3d(0, 0, zb), rg.Point3d(0, 0, zt))
    return planar[0].Faces[0].CreateExtrusion(path, True)


plates = []
floor_areas = []
total_floor_area = None
plates_path = None
diagnostics = ""
report_path = None

if not run:
    diagnostics = "Idle: set run=True"
elif config is None:
    diagnostics = _error("Connect a USC Config component")
elif thr_result is None:
    diagnostics = _error("Connect thr_result from USC Threshold Stage")
else:
    t_start = time.perf_counter()
    gh = _usc_gh(config.session.root)
    m_out = Path(config.out_dir) / "massing"
    # Massing settings are merged here, not in Config, so changing them
    # re-runs only Massing.
    overrides = dict(config.overrides, **gh.parse_overrides(massing_overrides))
    try:
        reply = gh.call_daemon(config.session, "massing", {
            "from": str(thr_result),
            "config": config.yaml_path,
            "overrides": gh.override_list(overrides),
            "out_dir": str(m_out),
        })
        plates_path = reply["plates_path"]
        for plate in gh.read_plates(plates_path):
            brep = _plate_brep(plate)
            if brep is not None:
                plates.append(brep)
        data = gh.read_diagnostics(m_out)
        floor_areas = data.get("floor_area_m2_per_floor", [])
        total_floor_area = data.get("total_floor_area_m2")
        lines = ["Massing: {:.1f}s".format(time.perf_counter() - t_start),
                 "Floors built: {} of {}".format(data.get("floors_built", "?"), data.get("floors", "?")),
                 "Plates: {}".format(data.get("plates", "?"))]
        if total_floor_area is not None:
            lines.append("Total floor area: {:,.0f} m2".format(total_floor_area))
        if data.get("footprint_source") == "voxels":
            lines.append("Footprint from voxels (the mesh footprint could not be read or does not match the voxels)")
        diagnostics = "\n".join(lines)
        report = m_out.parent / "run_report.md"
        report_path = str(report) if report.is_file() else None
    except Exception as e:
        diagnostics = _error(str(e))
