"""Helpers shared by the USC Grasshopper components.

The component scripts run inside Rhino's own Python, not in the USC virtual
environment, so they cannot import ``urbansolarcarver``.  Code they share
lives here instead and is loaded at run time from ``<carver_root>/grasshopper``
(see ``_usc_gh`` in the components that use it).  Editing this file takes
effect on the next solve; no .ghuser rebuild is needed.

Only the standard library, RhinoCommon and the Grasshopper SDK are used;
the Rhino imports sit inside the functions that need them.
"""

import json
import os
import struct
from pathlib import Path

# Long carves are normal; the timeout only guards against a daemon that hangs.
JOB_TIMEOUT_S = 3600
PING_TIMEOUT_S = 5


# ---------------------------------------------------------------- messages
def report(component, message, level="error"):
    """Show *message* on the component at *level* ("error", "warning" or "remark") and return it."""
    from Grasshopper.Kernel import GH_RuntimeMessageLevel
    levels = {"error": GH_RuntimeMessageLevel.Error,
              "warning": GH_RuntimeMessageLevel.Warning,
              "remark": GH_RuntimeMessageLevel.Remark}
    component.AddRuntimeMessage(levels[level], message)
    return message


# ---------------------------------------------------------------- daemon
class DaemonError(RuntimeError):
    """The daemon could not be reached, or answered with an error."""


def call_daemon(session, cmd, payload=None, timeout=JOB_TIMEOUT_S):
    """Send one command to the daemon and return its reply (a dict).

    *session* needs ``host``, ``port`` and ``authkey`` attributes (a
    USCSession).  Waits up to *timeout* seconds for the reply.  Raises
    DaemonError, with a message meant for the canvas, when the daemon cannot
    be reached, does not answer in time, or replies with a status other
    than "ok".
    """
    from multiprocessing.connection import Client

    authkey = getattr(session, "authkey", None)
    if not authkey:
        raise DaemonError("No daemon key found: start the daemon with USC_Session (start_daemon=True)")
    try:
        conn = Client((session.host, session.port), authkey=authkey)
    except OSError as exc:
        raise DaemonError(
            "Daemon not reachable on {}:{} ({}): start it with USC_Session "
            "(start_daemon=True)".format(session.host, session.port, exc)) from exc
    with conn:
        conn.send(dict(payload or {}, cmd=cmd))
        if not conn.poll(timeout):
            raise DaemonError("No reply from the daemon within {} s for '{}'".format(timeout, cmd))
        reply = conn.recv()
    if not isinstance(reply, dict):
        raise DaemonError("Unexpected daemon reply: {!r}".format(reply))
    if reply.get("status") != "ok":
        raise DaemonError(reply.get("error", repr(reply)))
    return reply


def ping(session, timeout=PING_TIMEOUT_S):
    """True if the daemon answers a ping within *timeout* seconds."""
    try:
        return call_daemon(session, "ping", timeout=timeout).get("status") == "ok"
    except (DaemonError, OSError, EOFError):
        return False


# ---------------------------------------------------------------- overrides
def parse_overrides(value):
    """Turn an overrides input into a {key: value} dict of strings.

    Accepts None, a "key=value;key=value" string, (nested) lists of such
    strings (a list-access input) or a Grasshopper DataTree.  When a key
    appears more than once, the last value wins.  Items without "=" or with
    an empty key are skipped.  Only the first "=" splits, so values may
    contain "=".
    """
    items = []

    def collect(v):
        if v is None:
            return
        if isinstance(v, str):
            items.extend(v.split(";"))
        elif isinstance(v, (list, tuple)):
            for x in v:
                collect(x)
        elif hasattr(v, "AllData"):  # DataTree
            for x in v.AllData():
                collect(x)
        else:
            items.extend(str(v).split(";"))

    collect(value)
    out = {}
    for item in items:
        key, sep, val = item.partition("=")
        if sep and key.strip():
            out[key.strip()] = val.strip()
    return out


def override_list(overrides):
    """Turn a {key: value} dict into the ["key=value", ...] list the daemon expects."""
    return ["{}={}".format(k, v) for k, v in overrides.items()]


def read_diagnostics(stage_dir):
    """Return <stage_dir>/diagnostics/diagnostic.json as a dict ({} if the file is missing)."""
    path = Path(stage_dir) / "diagnostics" / "diagnostic.json"
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def existing_files(*paths):
    """Return the given paths that are existing files, as strings; None entries are skipped."""
    return [str(p) for p in paths if p and os.path.isfile(str(p))]


def resolve_path(component, path_str):
    """Return *path_str* as an absolute path, resolving a relative one against the .gh file.

    Rhino and the daemon run in different working directories, so a
    relative path would name a different place for each of them.  Raises
    ValueError for a relative path when the .gh file has not been saved.
    """
    p = Path(str(path_str).strip())
    if p.is_absolute():
        return str(p)
    doc = component.OnPingDocument()
    gh_file = doc.FilePath if doc is not None else None
    if not gh_file:
        raise ValueError("relative path '{}' needs a saved .gh file to resolve against; "
                         "save the file or use an absolute path".format(path_str))
    return str((Path(gh_file).parent / p).resolve())


# ---------------------------------------------------------------- daemon process
def daemon_log_path():
    """Where start_daemon writes the daemon's output when no console is shown."""
    return Path.home() / ".urbansolarcarver" / "daemon.log"


def start_daemon(python, root, host, port, visible_console=False):
    """Launch the daemon with the *python* interpreter; returns the Popen object.

    *root* is the carver root: its ``src`` folder is put on PYTHONPATH and it
    is the daemon's working directory.  With *visible_console* the daemon
    gets its own console window; otherwise it runs detached and its output
    replaces the contents of ~/.urbansolarcarver/daemon.log.
    """
    import subprocess
    cmd = [str(python), "-m", "urbansolarcarver.daemon", "--host", host, "--port", str(port)]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(root) / "src") + os.pathsep + env.get("PYTHONPATH", "")
    kwargs = {"env": env, "cwd": str(root)}
    if visible_console:
        if os.name == "nt":
            kwargs["creationflags"] = 0x00000010  # CREATE_NEW_CONSOLE
        return subprocess.Popen(cmd, **kwargs)
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000200 | 0x00000008  # NEW_PROCESS_GROUP | DETACHED_PROCESS
    log = daemon_log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    # Closing our handle is safe: the child process holds its own copy.
    with open(log, "w", encoding="utf-8") as log_file:
        return subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, **kwargs)


# ---------------------------------------------------------------- geometry in
def _fine_mesh_params():
    """Meshing parameters that keep Brep detail (Grasshopper's default meshing is coarse)."""
    import Rhino.Geometry as rg
    mp = rg.MeshingParameters()
    mp.MaximumEdgeLength = 0
    mp.MinimumEdgeLength = 0.001
    mp.GridAspectRatio = 0
    mp.GridAngle = 0
    mp.GridMaxCount = 0
    mp.RefineGrid = True
    mp.JaggedSeams = False
    mp.SimplePlanes = True  # flat faces stay two triangles
    mp.Tolerance = 0.01
    mp.RelativeTolerance = 0.0
    return mp


def _to_rhino_mesh(geom):
    """A triangulated copy of a Mesh, Brep or Extrusion (bare or GH-wrapped); None otherwise."""
    import Rhino.Geometry as rg
    if hasattr(geom, "Value"):  # GH_ObjectWrapper and goo
        geom = geom.Value
    if isinstance(geom, rg.Extrusion):
        geom = geom.ToBrep()
    if isinstance(geom, rg.Mesh):
        m = geom.DuplicateMesh()
    elif isinstance(geom, rg.Brep):
        parts = rg.Mesh.CreateFromBrep(geom, _fine_mesh_params())
        if not parts:
            return None
        m = rg.Mesh()
        for p in parts:
            m.Append(p)
        # CreateFromBrep gives one mesh per Brep face: weld the seams.
        m.Vertices.CombineIdentical(True, True)
        m.Faces.CullDegenerateFaces()
    else:
        return None
    m.Faces.ConvertQuadsToTriangles()
    m.Normals.ComputeNormals()
    m.Compact()
    return m


def meshes_from_input(items):
    """Rhino Meshes from a GH geometry input (one item or a list); unusable items are dropped."""
    if items is None:
        return []
    if not isinstance(items, (list, tuple)):
        items = [items]
    meshes = [_to_rhino_mesh(item) for item in items]
    return [m for m in meshes if m is not None]


def write_input_geometry(max_volume, test_surfaces, folder):
    """Write the max volume and test surfaces as PLY files for the daemon.

    Each input's meshes are joined into one mesh and written to *folder* as
    max_volume.ply and test_surfaces.ply.  Returns (max_volume_path,
    test_surface_path).  Raises ValueError when an input holds no Mesh or
    Brep geometry.
    """
    import Rhino.Geometry as rg

    vol_meshes = meshes_from_input(max_volume)
    srf_meshes = meshes_from_input(test_surfaces)
    if not vol_meshes:
        raise ValueError("max_volume contains no Mesh or Brep geometry")
    if not srf_meshes:
        raise ValueError("test_surfaces contains no Mesh or Brep geometry")

    volume = rg.Mesh()
    for m in vol_meshes:
        volume.Append(m)
    # Weld so the volume is one closed manifold; otherwise the voxelizer
    # sees open seams and fills only a shell.
    volume.Vertices.CombineIdentical(True, True)
    volume.Faces.CullDegenerateFaces()
    volume.UnifyNormals()
    volume.Compact()

    surfaces = rg.Mesh()
    for m in srf_meshes:
        surfaces.Append(m)
    # Test surfaces are not welded: merging vertices across neighbouring
    # panels averages their normals, which flips some panels on reload.

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    vol_path, srf_path = folder / "max_volume.ply", folder / "test_surfaces.ply"
    export_mesh_to_ply(volume, vol_path, include_normals=False)
    export_mesh_to_ply(surfaces, srf_path, include_normals=True)
    return str(vol_path), str(srf_path)


def export_mesh_to_ply(mesh, path, include_normals=True):
    """Write a Rhino Mesh as binary little-endian PLY with double-precision vertices.

    float32 keeps about 7 significant digits, which is a 0.5 m step at UTM
    northings (millions of metres), so vertex positions are written as
    doubles (ToPoint3dArray gives Rhino's double vertices when the mesh has
    them; meshes from Breps do).  Normals are written as float32.

    include_normals: True for test surfaces (open sheets: the normals tell
    which side faces out); False for the max volume, whose closed winding
    already defines inside and outside and which explicit normals can upset.

    Modifies *mesh* in place: quads are split into triangles and vertex
    normals are recomputed.
    """
    mesh.Faces.ConvertQuadsToTriangles()
    mesh.Normals.ComputeNormals()
    nv, nf = mesh.Vertices.Count, mesh.Faces.Count
    props = "property double x\nproperty double y\nproperty double z\n"
    if include_normals:
        props += "property float nx\nproperty float ny\nproperty float nz\n"
    header = ("ply\nformat binary_little_endian 1.0\n"
              "element vertex {}\n{}element face {}\n"
              "property list uchar int vertex_indices\nend_header\n").format(nv, props, nf)

    pts = mesh.Vertices.ToPoint3dArray()
    if include_normals:
        normals = mesh.Normals
        vbuf = bytearray(nv * 36)
        for i in range(nv):
            p, n = pts[i], normals[i]
            struct.pack_into("<dddfff", vbuf, i * 36, p.X, p.Y, p.Z, n.X, n.Y, n.Z)
    else:
        vbuf = struct.pack("<{}d".format(nv * 3), *[c for p in pts for c in (p.X, p.Y, p.Z)])

    fbuf = bytearray(nf * 13)  # count byte + three int32 indices
    faces = mesh.Faces
    for i in range(nf):
        face = faces[i]
        struct.pack_into("<Biii", fbuf, i * 13, 3, face.A, face.B, face.C)

    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(vbuf)
        f.write(fbuf)


# ---------------------------------------------------------------- geometry out
_PLY_SIZES = {
    "char": 1, "uchar": 1, "short": 2, "ushort": 2, "int": 4, "uint": 4,
    "float": 4, "double": 8, "int8": 1, "uint8": 1, "int16": 2, "uint16": 2,
    "int32": 4, "uint32": 4, "float32": 4, "float64": 8,
}


def load_ply_to_rhino(path):
    """Read a PLY file (binary little-endian or ASCII) into a Rhino Mesh.

    Binary files may use any vertex property layout (x/y/z need not come
    first) and float or double coordinates; ASCII files must list x, y, z
    first.  Faces must be triangles or quads stored as a uchar count plus
    int32 indices.  The mesh keeps double-precision vertices.
    """
    import System
    import Rhino.Geometry as rg

    nv = nf = 0
    binary = False
    vertex_props = []  # (name, byte size) in file order
    in_vertex = False
    with open(path, "rb") as f:
        if f.readline().strip() != b"ply":
            raise ValueError("Not a PLY file: {}".format(path))
        while True:
            raw = f.readline()
            if not raw:
                raise ValueError("Not a valid PLY file (no end_header): {}".format(path))
            line = raw.decode("ascii", errors="replace").strip()
            if line == "end_header":
                break
            if "binary_little_endian" in line:
                binary = True
            elif line.startswith("element vertex"):
                nv, in_vertex, vertex_props = int(line.split()[-1]), True, []
            elif line.startswith("element"):
                in_vertex = False
                if "face" in line:
                    nf = int(line.split()[-1])
            elif line.startswith("property") and in_vertex:
                parts = line.split()
                if len(parts) >= 3 and parts[1] != "list":
                    vertex_props.append((parts[2], _PLY_SIZES.get(parts[1], 4)))

        sizes = dict(vertex_props)
        offsets, off = {}, 0
        for name, size in vertex_props:
            offsets[name] = off
            off += size
        stride = off or 12
        fmt = "<d" if sizes.get("x", 4) == 8 else "<f"

        if binary:
            raw = f.read(nv * stride)
            verts = [struct.unpack_from(fmt, raw, i * stride + offsets[axis])[0]
                     for i in range(nv) for axis in ("x", "y", "z")]
            face_data = f.read()
            faces, pos = [], 0
            for _ in range(nf):
                count = face_data[pos]
                faces.append(struct.unpack_from("<{}i".format(count), face_data, pos + 1))
                pos += 1 + 4 * count
        else:
            lines = f.read().decode("ascii", errors="replace").split("\n")
            verts = [float(v) for ln in lines[:nv] for v in ln.split()[:3]]
            faces = []
            for ln in lines[nv:nv + nf]:
                parts = ln.split()
                faces.append(tuple(int(x) for x in parts[1:int(parts[0]) + 1]))

    mesh = rg.Mesh()
    # Without this Rhino stores float32 vertices: 0.5 m steps at UTM coordinates.
    mesh.Vertices.UseDoublePrecisionVertices = True
    pts = System.Array.CreateInstance(rg.Point3d, nv)
    for i in range(nv):
        pts[i] = rg.Point3d(verts[3 * i], verts[3 * i + 1], verts[3 * i + 2])
    mesh.Vertices.AddVertices(pts)
    face_arr = System.Array.CreateInstance(rg.MeshFace, nf)
    for i, idx in enumerate(faces):
        face_arr[i] = (rg.MeshFace(idx[0], idx[1], idx[2]) if len(idx) == 3
                       else rg.MeshFace(idx[0], idx[1], idx[2], idx[3]))
    mesh.Faces.AddFaces(face_arr)
    mesh.Normals.ComputeNormals()
    return mesh


def read_npy_points(path):
    """Rhino Point3d list from a C-order (N, 3) little-endian float32/float64 .npy file.

    Parses the .npy format directly because numpy may not be installed in
    Rhino's Python.  Raises ValueError for any other file layout.
    """
    import ast
    import Rhino.Geometry as rg

    with open(path, "rb") as f:
        if f.read(6) != b"\x93NUMPY":
            raise ValueError("Not a .npy file: {}".format(path))
        major = f.read(2)[0]
        header_len = struct.unpack("<H" if major == 1 else "<I", f.read(2 if major == 1 else 4))[0]
        header = ast.literal_eval(f.read(header_len).decode("latin1"))
        data = f.read()
    descr, shape = header["descr"], header["shape"]
    if header.get("fortran_order") or len(shape) != 2 or shape[1] != 3 or descr not in ("<f4", "<f8"):
        raise ValueError("Expected a C-order (N, 3) float array in {}".format(path))
    fmt = "<{}{}".format(shape[0] * 3, "f" if descr == "<f4" else "d")
    flat = struct.unpack(fmt, data[:struct.calcsize(fmt)])
    return [rg.Point3d(flat[3 * i], flat[3 * i + 1], flat[3 * i + 2]) for i in range(shape[0])]
