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

import json
import os
import time
from pathlib import Path

import Rhino.Geometry as rg

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

# -- PLY loader --------------------------------------------------------------

def _load_ply_to_rhino(path):
    """Load a PLY file into Rhino Mesh using batch array operations.

    Parses binary-LE or ASCII PLY, handling arbitrary vertex property layouts
    (e.g. x/y/z/nx/ny/nz when trimesh exports normals after fix_normals()).
    Uses the actual per-vertex byte stride from the header so that x/y/z are
    read at the correct offsets regardless of how many extra properties exist.

    Uses System.Array-based AddVertices/AddFaces for ~10-50x speedup over
    per-element Add calls.  Face data is read in a single I/O call and
    parsed with struct.unpack_from to avoid 2×nf individual f.read() calls.
    """
    import struct
    import System

    _PLY_SIZES = {
        "char": 1, "uchar": 1, "short": 2, "ushort": 2,
        "int": 4, "uint": 4, "float": 4, "double": 8,
        "int8": 1, "uint8": 1, "int16": 2, "uint16": 2,
        "int32": 4, "uint32": 4, "float32": 4, "float64": 8,
    }

    nv = nf = 0
    is_binary_le = False
    vertex_props = []   # [(name, byte_size), ...]
    in_vertex = False

    with open(path, "rb") as f:
        # Parse header — track vertex property list to compute stride
        first = True
        while True:
            raw_line = f.readline()
            if not raw_line:
                # EOF before end_header: not a PLY (or truncated).  Without
                # this guard, readline() returns b"" forever → infinite loop.
                raise ValueError(
                    "Not a valid PLY file (no end_header found): {}".format(path)
                )
            line = raw_line.decode("ascii", errors="replace").strip()
            if first:
                if line != "ply":
                    raise ValueError(
                        "Not a PLY file (missing 'ply' magic): {}".format(path)
                    )
                first = False
                continue
            if line == "end_header":
                break
            if "binary_little_endian" in line:
                is_binary_le = True
            elif line.startswith("element vertex"):
                nv = int(line.split()[-1])
                in_vertex = True
                vertex_props = []
            elif line.startswith("element"):
                in_vertex = False
                if "face" in line:
                    nf = int(line.split()[-1])
            elif line.startswith("property") and in_vertex:
                parts = line.split()
                if len(parts) >= 3 and parts[1] != "list":
                    vertex_props.append((parts[2], _PLY_SIZES.get(parts[1], 4)))

        # Compute per-vertex byte stride and x/y/z offsets
        stride = sum(sz for _, sz in vertex_props) or 12
        xyz_off = {}
        off = 0
        for pname, psize in vertex_props:
            if pname in ("x", "y", "z"):
                xyz_off[pname] = off
            off += psize
        xo = xyz_off.get("x", 0)
        yo = xyz_off.get("y", 4)
        zo = xyz_off.get("z", 8)

        # Read raw data
        if is_binary_le:
            raw = f.read(nv * stride)
            if stride == 12 and xo == 0 and yo == 4 and zo == 8:
                # Fast path: xyz-only layout (trimesh default, no normals)
                verts = struct.unpack(f"<{nv * 3}f", raw)
            else:
                # General path: extract x/y/z at their actual byte offsets
                verts = []
                for i in range(nv):
                    base = i * stride
                    verts.append(struct.unpack_from("<f", raw, base + xo)[0])
                    verts.append(struct.unpack_from("<f", raw, base + yo)[0])
                    verts.append(struct.unpack_from("<f", raw, base + zo)[0])
            # Bulk-read all face data at once (avoids 2×nf individual reads)
            face_data = f.read()
            faces = []
            foff = 0
            for _ in range(nf):
                count = struct.unpack_from("<B", face_data, foff)[0]
                foff += 1
                faces.append(
                    struct.unpack_from(f"<{count}i", face_data, foff)
                )
                foff += count * 4
        else:
            f.seek(0)
            text = f.read().decode("ascii", errors="replace").split("\n")
            ds = 0
            for i, ln in enumerate(text):
                if ln.strip() == "end_header":
                    ds = i + 1
                    break
            verts = []
            for i in range(nv):
                p = text[ds + i].split()
                verts.extend((float(p[0]), float(p[1]), float(p[2])))
            faces = []
            for i in range(nf):
                p = text[ds + nv + i].split()
                c = int(p[0])
                faces.append(tuple(int(x) for x in p[1:c + 1]))

    # Batch-build Rhino mesh
    mesh_out = rg.Mesh()

    # Vertices: .NET array of Point3f → single AddVertices call
    pt_arr = System.Array.CreateInstance(rg.Point3d, nv)
    for i in range(nv):
        pt_arr[i] = rg.Point3d(verts[i * 3], verts[i * 3 + 1], verts[i * 3 + 2])
    mesh_out.Vertices.AddVertices(pt_arr)

    # Faces: .NET array of MeshFace → single AddFaces call
    face_arr = System.Array.CreateInstance(rg.MeshFace, nf)
    for i, idx in enumerate(faces):
        if len(idx) == 3:
            face_arr[i] = rg.MeshFace(idx[0], idx[1], idx[2])
        else:
            face_arr[i] = rg.MeshFace(idx[0], idx[1], idx[2], idx[3])
    mesh_out.Faces.AddFaces(face_arr)

    mesh_out.Normals.ComputeNormals()
    return mesh_out

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


mesh = None
export_path = None
report_path = None
diagnostics = ""

if not run:
    diagnostics = "Idle — set run=True"
elif config is None:
    diagnostics = _add_error("Connect a USC Config component")
elif thr_result is None:
    diagnostics = _add_error("Connect thr_result from USC Threshold Stage")
else:
    t_start = time.perf_counter()
    session = config.session
    out_dir = config.out_dir

    # Start with config overrides, then merge postprocess-specific ones on top.
    # This means postprocess_overrides changes do NOT touch config → do NOT
    # trigger Preprocessing or Thresholding to re-run.
    overrides = dict(config.overrides)
    pp_ovr = _parse_overrides(postprocess_overrides)
    overrides.update(pp_ovr)

    try:
        exp_out = str(Path(out_dir) / "exporting")
        if getattr(session, "daemon_running", False):
            resp = _rpc_call(session, "exporting", {
                "from": str(thr_result),
                "config": config.yaml_path,
                "overrides": [f"{k}={v}" for k, v in overrides.items()],
                "out_dir": exp_out,
            })
            result_path = resp.get("export_path", "")
            if result_path and os.path.isfile(result_path):
                export_path = result_path
                if result_path.lower().endswith(".ply"):
                    mesh = _load_ply_to_rhino(result_path)
                else:
                    # Non-PLY export formats (obj/stl/glb) are saved to disk
                    # but not previewed — the in-canvas loader is PLY-only.
                    try:
                        from Grasshopper.Kernel import GH_RuntimeMessageLevel
                        ghenv.Component.AddRuntimeMessage(
                            GH_RuntimeMessageLevel.Remark,
                            "Mesh saved to {} — canvas preview only supports "
                            "PLY (set final_mesh_format=ply to preview)".format(result_path),
                        )
                    except Exception:
                        pass
            # Read diagnostics
            elapsed = time.perf_counter() - t_start
            diag_lines = [f"Exporting: {elapsed:.1f}s"]
            summary_path = Path(exp_out) / "diagnostics" / "diagnostic.json"
            if summary_path.exists():
                data = json.load(open(summary_path))
                diag_lines.append(f"Vertices: {data.get('vertices', '?')}")
                diag_lines.append(f"Triangles: {data.get('triangles', '?')}")
                vol = data.get("mesh_volume_m3")
                if vol is not None:
                    diag_lines.append(f"Volume: {vol:.1f} m3")
                bbox = data.get("bbox_dimensions_m")
                if bbox:
                    diag_lines.append(f"BBox: {bbox[0]:.1f} x {bbox[1]:.1f} x {bbox[2]:.1f} m")
                ret = data.get("voxel_retention_pct")
                if ret is not None:
                    diag_lines.append(f"Voxel retention: {ret}%")
            # Run report
            rpt = Path(exp_out).parent / "run_report.md"
            if rpt.is_file():
                report_path = str(rpt)
            diagnostics = "\n".join(diag_lines)
        else:
            diagnostics = _add_error("Daemon not running — connect USC_Session and set start_daemon=True")
            result_path = None

    except Exception as e:
        diagnostics = _add_error(str(e))
