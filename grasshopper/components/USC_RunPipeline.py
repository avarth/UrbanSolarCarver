"""USC Run Pipeline — Execute the full carving pipeline in one step.

Takes Rhino geometry, exports to PLY, runs all three stages
(preprocessing → thresholding → exporting), and returns the
carved mesh directly to Grasshopper.

For finer control (e.g., adjusting threshold without re-carving),
use the individual stage components instead.

Inputs
------
config : USCConfig
    Config handle from USC Config.
max_volume : Mesh or Brep
    Maximum volume envelope geometry.
test_surfaces : Mesh or Brep (list)
    Insolation test surfaces.
run : bool
    True to execute. False to idle (no computation).

Outputs
-------
mesh : Rhino.Geometry.Mesh
    Carved envelope mesh, ready for display in Rhino.
export_path : str
    Path to the exported mesh file on disk.
report_path : str
    Path to the run_report.md file summarising the full pipeline run.
diagnostics : str
    Summary of pipeline results (timings, voxel counts, mesh stats).
"""

import json
import os
import subprocess
import time
from pathlib import Path

import Rhino.Geometry as rg

# -- GH UI rollovers --------------------------------------------------------
try:
    ghenv.Component.Name = "USC Run Pipeline"
    ghenv.Component.NickName = "USC_RunAll"
    ghenv.Component.Description = "Runs the full pipeline (Preprocess + Threshold + Export) in one step. Convenient for quick prototyping. For iterative threshold adjustment, use the decomposed stage components instead."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    ii[0].Name, ii[0].Description = "config", "Configuration handle from USC_Config. Contains all settings for the full pipeline."
    ii[1].Name, ii[1].Description = "max_volume", "Maximum building envelope geometry (Mesh or Brep). Set input to List Access for multiple objects."
    ii[2].Name, ii[2].Description = "test_surfaces", "Surfaces requiring solar access (Mesh or Brep). Set input to List Access."
    ii[3].Name, ii[3].Description = "run", "Boolean toggle. True to run the complete pipeline (preprocessing + thresholding + exporting) in one step."
    oo[0].Name, oo[0].Description = "mesh", "The carved envelope as a Rhino Mesh. Displayed directly in the viewport."
    oo[1].Name, oo[1].Description = "export_path", "Full path to the exported mesh file on disk."
    oo[2].Name, oo[2].Description = "report_path", "Full path to the run_report.md file. Contains a human-readable summary of the entire pipeline run."
    oo[3].Name, oo[3].Description = "diagnostics", "Summary of the full pipeline run: per-stage timings, voxel counts, final mesh statistics."
except Exception:
    pass

# -- Geometry helpers --------------------------------------------------------

def _fine_mesh_params():
    """Meshing parameters that preserve geometry detail for carving."""
    mp = rg.MeshingParameters()
    mp.MaximumEdgeLength = 0
    mp.MinimumEdgeLength = 0.001
    mp.GridAspectRatio = 0
    mp.GridAngle = 0
    mp.GridMaxCount = 0
    mp.RefineGrid = True
    mp.JaggedSeams = False
    mp.SimplePlanes = True
    mp.Tolerance = 0.01
    mp.RelativeTolerance = 0.0
    return mp

def _to_rhino_mesh(geom):
    """Convert Brep or Mesh to a triangulated Rhino Mesh."""
    if isinstance(geom, rg.Mesh):
        m = geom.DuplicateMesh()
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
        geo = item
        if hasattr(geo, "Value"):
            geo = geo.Value
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

    mesh_out = rg.Mesh()

    pt_arr = System.Array.CreateInstance(rg.Point3d, nv)
    for i in range(nv):
        pt_arr[i] = rg.Point3d(verts[i * 3], verts[i * 3 + 1], verts[i * 3 + 2])
    mesh_out.Vertices.AddVertices(pt_arr)

    face_arr = System.Array.CreateInstance(rg.MeshFace, nf)
    for i, idx in enumerate(faces):
        if len(idx) == 3:
            face_arr[i] = rg.MeshFace(idx[0], idx[1], idx[2])
        else:
            face_arr[i] = rg.MeshFace(idx[0], idx[1], idx[2], idx[3])
    mesh_out.Faces.AddFaces(face_arr)

    mesh_out.Normals.ComputeNormals()
    return mesh_out


# -- RPC helper --------------------------------------------------------------

def _rpc_call(session, cmd, payload):
    """Send an RPC command to the daemon and return the response."""
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


def _run_subprocess(session, config_dict):
    """Run the pipeline as a subprocess (fallback when no daemon)."""
    py = session.python_path
    root = session.root
    script = (
        "import sys; sys.path.insert(0, r'{root}/src'); "
        "from urbansolarcarver import load_config, run_pipeline; "
        "cfg = load_config(r'{yaml}', {overrides}); "
        "r = run_pipeline(cfg, r'{out_dir}'); "
        "print(r.export_path)"
    ).format(
        root=root,
        yaml=config_dict["yaml_path"],
        overrides=repr(["{0}={1}".format(k, v) for k, v in config_dict["overrides"].items()]),
        out_dir=config_dict["out_dir"],
    )

    result = subprocess.run(
        [py, "-c", script],
        capture_output=True,
        text=True,
        cwd=root,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Pipeline failed:\n{result.stderr}")
    return result.stdout.strip()


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
    diagnostics = "Idle — set run=True to execute"
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
        diagnostics = _add_error("max_volume contains no valid geometry")
    elif not srf_meshes:
        diagnostics = _add_error("test_surfaces contains no valid geometry")
    else:
        # Combine into single meshes and weld seams left by Append:
        # merge duplicate vertices at Brep face boundaries so trimesh
        # sees a manifold watertight mesh for solid voxelization.
        vol_combined = rg.Mesh()
        for m in vol_meshes:
            vol_combined.Append(m)
        vol_combined.Vertices.CombineIdentical(True, True)
        vol_combined.Faces.CullDegenerateFaces()
        vol_combined.UnifyNormals()
        vol_combined.Compact()

        srf_combined = rg.Mesh()
        for m in srf_meshes:
            srf_combined.Append(m)
        # Do NOT weld test surfaces — see USC_Preprocess comment.

        # Write to temp PLY files in out_dir
        os.makedirs(out_dir, exist_ok=True)
        incoming = Path(out_dir) / "incoming"
        incoming.mkdir(exist_ok=True)

        vol_path = str(incoming / "max_volume.ply")
        srf_path = str(incoming / "test_surfaces.ply")
        _export_mesh_to_ply(vol_combined, vol_path, include_normals=False)
        _export_mesh_to_ply(srf_combined, srf_path, include_normals=True)

        # Inject geometry paths
        overrides["max_volume_path"] = vol_path
        overrides["test_surface_path"] = srf_path

        config_for_run = {"yaml_path": config.yaml_path, "overrides": overrides, "out_dir": out_dir}

        try:
            if getattr(session, "daemon_running", False):
                resp = _rpc_call(session, "run_pipeline", {
                    "config": config.yaml_path,
                    "overrides": [f"{k}={v}" for k, v in overrides.items()],
                    "out_dir": out_dir,
                })
                result_path = resp.get("export_path", "")
            else:
                result_path = _run_subprocess(session, config_for_run)

            # Load result mesh (canvas preview is PLY-only; other formats
            # are saved to disk without preview)
            export_path = result_path
            if os.path.isfile(result_path):
                if result_path.lower().endswith(".ply"):
                    mesh = _load_ply_to_rhino(result_path)
                else:
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
            diag_lines = [f"Total time: {elapsed:.1f}s"]

            # Try reading stage summaries
            for stage in ["preprocessing", "thresholding", "exporting"]:
                summary_path = Path(out_dir) / stage / "diagnostics" / "diagnostic.json"
                if summary_path.exists():
                    with open(summary_path) as f:
                        data = json.load(f)
                    if stage == "preprocessing":
                        dev = data.get("device")
                        if dev:
                            diag_lines.append(f"Device: {dev}")
                        stats = data.get("score_stats", {})
                        diag_lines.append(
                            f"Preprocessing: {data.get('voxels_filled', '?')} voxels, "
                            f"scores [{stats.get('min', 0):.1f} - {stats.get('max', 0):.1f}]"
                        )
                    elif stage == "thresholding":
                        diag_lines.append(
                            f"Thresholding: {data.get('threshold_method', '?')} "
                            f"(value={data.get('threshold_value', '?')}), "
                            f"kept {data.get('retention_pct', '?')}%"
                        )
                    elif stage == "exporting":
                        vol = data.get("mesh_volume_m3")
                        vol_str = f", vol={vol:.1f} m³" if vol is not None else ""
                        ret = data.get("voxel_retention_pct")
                        ret_str = f", retention={ret}%" if ret is not None else ""
                        diag_lines.append(
                            f"Exporting: {data.get('vertices', '?')} verts, "
                            f"{data.get('triangles', '?')} faces{vol_str}{ret_str}"
                        )

            # Run report
            rpt = Path(out_dir) / "run_report.md"
            if rpt.is_file():
                report_path = str(rpt)

            diagnostics = "\n".join(diag_lines)

        except Exception as e:
            diagnostics = _add_error(str(e))
