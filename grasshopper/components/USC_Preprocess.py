"""USC Preprocess — Run the ray-tracing stage (expensive, cache result).

Voxelizes the max volume, samples test surfaces, and casts rays through
the grid to compute per-voxel obstruction scores. This is the most
expensive step — only re-run when geometry, mode, or period changes.

Connect the pre_result output to USC Threshold.

Inputs
------
config : USCConfig
    Config handle from USC Config.
max_volume : Mesh or Brep
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
    Empty when diagnostics are disabled.
test_points : list of Point3d
    Sample points generated from test surfaces during preprocessing.
    Useful for verifying sampling density and surface coverage.
"""

import json
import os
import time
from pathlib import Path

import Rhino.Geometry as rg

# -- GH UI ------------------------------------------------------------------
try:
    ghenv.Component.Name = "USC Preprocess"
    ghenv.Component.NickName = "USC_Preprocess"
    ghenv.Component.Description = "Stage 1/4: Voxelizes the max volume and traces rays from test surfaces through the grid, computing per-voxel obstruction scores. This is the most computationally expensive step. Results are cached — only re-runs when geometry or mode changes."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "config", "Configuration handle from USC_Config. Contains mode, file paths, and all parameter overrides."
    ii[1].Name, ii[1].Description = "max_volume", "The maximum building envelope -- the largest volume the building could occupy before solar carving. Provide as Rhino Mesh or Brep. Multiple objects accepted (set input to List Access)."
    ii[2].Name, ii[2].Description = "test_surfaces", "Surfaces that need solar access (neighbouring facades, public spaces, parks). Rays are cast FROM these surfaces THROUGH the max volume. Provide as Rhino Mesh or Brep. Set input to List Access. Surfaces are subsampled into a uniform point grid at grid_step spacing (set in USC_GridSettings) — each sample point generates rays, so smaller grid_step = more points = finer results but slower. IMPORTANT: each surface must be a single flat panel — explode polysurfaces (e.g. extruded block boundaries) into individual faces before connecting, otherwise preprocessing will fail with a planarity error."
    ii[3].Name, ii[3].Description = "run", "Boolean toggle to execute. Set True to run preprocessing. Set False to prevent computation (useful while adjusting parameters)."
    oo[0].Name, oo[0].Description = "pre_result", "Path to the preprocessing manifest file. Connect this to USC_ThresholdStage's 'pre_result' input to continue the pipeline."
    oo[1].Name, oo[1].Description = "diagnostics", "Text summary: grid dimensions, filled voxels, score range, timing. Check this to verify the preprocessing ran correctly."
    if len(oo) > 2:
        oo[2].Name, oo[2].Description = "diag_images", "Paths to diagnostic images (score histogram, sky patch weight/intensity plots). Feed to Ladybug Image Viewer for in-canvas visualisation. Empty when diagnostics are disabled."
    if len(oo) > 3:
        oo[3].Name, oo[3].Description = "test_points", "Sample points generated from test surfaces at grid_step spacing. Visualise in Rhino to verify sampling density and surface coverage. If too sparse, reduce grid_step in USC_GridSettings."
        # Hide test_points from component preview so they don't clutter the
        # viewport when the user enables geometry preview on the component.
        oo[3].Hidden = True
except Exception:
    pass

# -- Geometry helpers (shared with RunPipeline) ------------------------------

def _fine_mesh_params():
    """Meshing parameters that preserve geometry detail for carving."""
    mp = rg.MeshingParameters()
    mp.MaximumEdgeLength = 0  # no limit
    mp.MinimumEdgeLength = 0.001
    mp.GridAspectRatio = 0
    mp.GridAngle = 0  # refine at curvature
    mp.GridMaxCount = 0
    mp.RefineGrid = True
    mp.JaggedSeams = False
    mp.SimplePlanes = True  # don't over-tessellate flat faces
    mp.Tolerance = 0.01
    mp.RelativeTolerance = 0.0
    return mp

def _to_rhino_mesh(geom):
    """Convert Brep or Mesh to a triangulated Rhino Mesh."""
    if isinstance(geom, rg.Mesh):
        m = geom.DuplicateMesh()
        # Ensure all faces are triangles (trimesh expects this)
        m.Faces.ConvertQuadsToTriangles()
        m.Normals.ComputeNormals()
        m.Compact()
        return m
    if isinstance(geom, rg.Brep):
        meshes = rg.Mesh.CreateFromBrep(geom, _fine_mesh_params())
        if meshes:
            combined = rg.Mesh()
            for m in meshes:
                combined.Append(m)
            combined.Faces.ConvertQuadsToTriangles()
            # Weld seams: CreateFromBrep returns one mesh per Brep face,
            # Append leaves duplicate vertices at shared edges.
            combined.Vertices.CombineIdentical(True, True)
            combined.Faces.CullDegenerateFaces()
            combined.Normals.ComputeNormals()
            combined.Compact()
            return combined
    return None

def _flatten_geometry(items):
    """Extract Rhino Meshes from GH input (handles trees, wrappers, goo)."""
    if items is None:
        return []
    if not isinstance(items, (list, tuple)):
        items = [items]
    meshes = []
    for item in items:
        # Unwrap GH object wrappers (GH_ObjectWrapper, GH_MeshGoo, etc.)
        geo = item
        # Try .Value (GH_ObjectWrapper)
        if hasattr(geo, "Value"):
            geo = geo.Value
        # Try .CastTo for IGH_GeometricGoo
        if hasattr(geo, "CastToMesh"):
            m = rg.Mesh()
            if geo.CastToMesh(m):
                geo = m
        elif hasattr(geo, "CastTo"):
            try:
                success, result = geo.CastTo[rg.Mesh]()
                if success:
                    geo = result
            except Exception:
                pass
        m = _to_rhino_mesh(geo)
        if m is not None:
            meshes.append(m)
    return meshes

def _export_mesh_to_ply(mesh, path, include_normals=True):
    """Write a triangulated Rhino Mesh to binary PLY (little-endian).

    Uses .NET bulk array operations (ToFloatArray + Buffer.BlockCopy) to
    bypass per-vertex Python loops.  GhPython loops are significantly slower
    than C++/.NET bulk paths; this eliminates the vertex serialization
    bottleneck for large meshes.

    Parameters
    ----------
    include_normals : bool
        True for test surfaces (open/non-watertight) — normals let trimesh
        correctly orient faces via fix_normals().  False for max_volume
        (watertight) — explicit normals can cause trimesh to flip face winding
        during process=True loading, breaking inside/outside for voxelization
        (produces hollow shell instead of solid fill).
    """
    import struct
    import System

    mesh.Faces.ConvertQuadsToTriangles()
    mesh.Normals.ComputeNormals()
    nv = mesh.Vertices.Count
    nf = mesh.Faces.Count

    with open(path, "wb") as f:
        # -- Header --------------------------------------------------------
        props = "property float x\nproperty float y\nproperty float z\n"
        if include_normals:
            props += (
                "property float nx\nproperty float ny\nproperty float nz\n"
            )
        header = (
            "ply\nformat binary_little_endian 1.0\n"
            f"element vertex {nv}\n"
            f"{props}"
            f"element face {nf}\n"
            "property list uchar int vertex_indices\n"
            "end_header\n"
        )
        f.write(header.encode("ascii"))

        # -- Vertices (bulk .NET path) -------------------------------------
        # ToFloatArray() is a single C++ call returning float[nv*3]
        pos = mesh.Vertices.ToFloatArray()

        if include_normals:
            # Bulk normal extraction; fall back to per-element if the method
            # is unavailable in this Rhino version.
            try:
                nrm = mesh.Normals.ToFloatArray()
            except (AttributeError, TypeError):
                nrm = System.Array.CreateInstance(System.Single, nv * 3)
                norms_list = mesh.Normals
                for i in range(nv):
                    n = norms_list[i]
                    nrm[i * 3] = n.X
                    nrm[i * 3 + 1] = n.Y
                    nrm[i * 3 + 2] = n.Z

            # Interleave [x,y,z, nx,ny,nz] per vertex via .NET Array.Copy
            combined = System.Array.CreateInstance(System.Single, nv * 6)
            for i in range(nv):
                System.Array.Copy(pos, i * 3, combined, i * 6, 3)
                System.Array.Copy(nrm, i * 3, combined, i * 6 + 3, 3)

            nbytes = nv * 24
            vbuf = System.Array.CreateInstance(System.Byte, nbytes)
            System.Buffer.BlockCopy(combined, 0, vbuf, 0, nbytes)
            f.write(bytes(bytearray(vbuf)))
        else:
            # Zero Python loops: bulk extract → byte copy → write
            nbytes = nv * 12
            vbuf = System.Array.CreateInstance(System.Byte, nbytes)
            System.Buffer.BlockCopy(pos, 0, vbuf, 0, nbytes)
            f.write(bytes(bytearray(vbuf)))

        # -- Faces (all triangles after ConvertQuadsToTriangles) -----------
        faces = mesh.Faces
        fbuf = bytearray(nf * 13)  # 1 byte count + 3×4 byte indices
        for i in range(nf):
            face = faces[i]
            struct.pack_into("<Biii", fbuf, i * 13, 3, face.A, face.B, face.C)
        f.write(fbuf)

# -- RPC helper --------------------------------------------------------------

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


pre_result = None
diagnostics = ""
diag_images = []
test_points = []

if not run:
    diagnostics = "Idle — set run=True"
elif config is None:
    diagnostics = _add_error("Connect a USC Config component")
elif max_volume is None:
    diagnostics = _add_error("Connect max_volume geometry")
elif test_surfaces is None:
    diagnostics = _add_error("Connect test_surfaces geometry")
else:
    t_start = time.perf_counter()
    session = config.session
    out_dir = config.out_dir
    overrides = dict(config.overrides)

    # Export geometry to PLY
    vol_meshes = _flatten_geometry(max_volume)
    srf_meshes = _flatten_geometry(test_surfaces)

    if not vol_meshes:
        diagnostics = "ERROR: max_volume has no valid geometry"
    elif not srf_meshes:
        diagnostics = "ERROR: test_surfaces has no valid geometry"
    else:
        vol_combined = rg.Mesh()
        for m in vol_meshes:
            vol_combined.Append(m)
        # Weld seams left by Append: merge duplicate vertices at Brep face
        # boundaries so trimesh sees a manifold watertight mesh for solid
        # voxelization.  Without this, seams leave gaps → surface-only voxels
        # → binary_fill_holes fails → hollow volume.
        vol_combined.Vertices.CombineIdentical(True, True)
        vol_combined.Faces.CullDegenerateFaces()
        vol_combined.UnifyNormals()
        vol_combined.Compact()

        srf_combined = rg.Mesh()
        for m in srf_meshes:
            srf_combined.Append(m)
        # Do NOT weld test surfaces: CombineIdentical merges vertices
        # across different surfaces, corrupting vertex normals at shared
        # edges.  Trimesh's fix_normals() then flips faces wrong → rays
        # cast inward → partial carving.

        os.makedirs(out_dir, exist_ok=True)
        incoming = Path(out_dir) / "incoming"
        incoming.mkdir(exist_ok=True)

        vol_path = str(incoming / "max_volume.ply")
        srf_path = str(incoming / "test_surfaces.ply")
        _export_mesh_to_ply(vol_combined, vol_path, include_normals=False)
        _export_mesh_to_ply(srf_combined, srf_path, include_normals=True)

        overrides["max_volume_path"] = vol_path
        overrides["test_surface_path"] = srf_path

        try:
            pre_out = str(Path(out_dir) / "preprocessing")
            if getattr(session, "daemon_running", False):
                resp = _rpc_call(session, "preprocessing", {
                    "config": config.yaml_path,
                    "overrides": [f"{k}={v}" for k, v in overrides.items()],
                    "out_dir": pre_out,
                })
                pre_result = resp.get("manifest", "")
                # Read diagnostics
                elapsed = time.perf_counter() - t_start
                diag_lines = [f"Preprocessing: {elapsed:.1f}s"]
                summary_path = Path(pre_out) / "diagnostics" / "diagnostic.json"
                if summary_path.exists():
                    data = json.load(open(summary_path))
                    dev = data.get("device")
                    if dev:
                        diag_lines.append(f"Device: {dev}")
                    stats = data.get("score_stats", {})
                    diag_lines.append(f"Grid: {data.get('grid_shape', '?')}")
                    diag_lines.append(f"Filled voxels: {data.get('voxels_filled', '?')}")
                    diag_lines.append(f"Scores: [{stats.get('min', 0):.1f} - {stats.get('max', 0):.1f}]")
                    diag_lines.append(f"Test points: {data.get('test_surface_points', '?')}")
                    # Collect image paths for LB Image Viewer
                    hist = data.get("score_histogram")
                    if hist and os.path.isfile(hist):
                        diag_images.append(hist)
                    for p in data.get("sky_patch_images", []):
                        if os.path.isfile(p):
                            diag_images.append(p)
                    # Simulated-weights runs also record how the weights
                    # shifted the sky vs the simple balance-point rule.
                    cmp_img = data.get("sky_patch_comparison_image")
                    if cmp_img and os.path.isfile(cmp_img):
                        diag_images.append(cmp_img)
                    cmp_stats = data.get("sky_patch_comparison_stats")
                    if cmp_stats:
                        diag_lines.append(
                            "Simulated vs simple weights: "
                            f"{cmp_stats.get('mass_redistributed_pct', 0):.1f}% "
                            "of sky-weight mass redistributed "
                            f"({cmp_stats.get('patches_over_20pct', 0)} of 145 "
                            "patches changed by >20%)")
                diagnostics = "\n".join(diag_lines)
                # Load test points for GH output
                tp_path = Path(pre_out) / "test_points.npy"
                if tp_path.exists():
                    import numpy as _np
                    pts_arr = _np.load(str(tp_path))
                    test_points = [rg.Point3d(float(r[0]), float(r[1]), float(r[2])) for r in pts_arr]
            else:
                diagnostics = _add_error("Daemon not running — connect USC_Session and set start_daemon=True")

        except Exception as e:
            diagnostics = _add_error(str(e))
