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


def show_issues(component, reply):
    """Show each issue of a daemon *reply* as a warning on *component*.

    Every issue becomes the message ``"<stage>: <message>"``; an issue that
    belongs to no stage (a configuration check) is labelled "config".
    Returns the list of those lines (empty when the reply has no issues).
    """
    lines = ["{}: {}".format(issue["stage"] or "config", issue["message"])
             for issue in reply.get("issues") or []]
    for line in lines:
        report(component, line, "warning")
    return lines


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
        error = reply.get("error", repr(reply))
        if "Unknown command: 'run'" in str(error):
            raise DaemonError("{}. This daemon was started before the update and does not know "
                              "the 'run' command. Restart the daemon from USC_Session.".format(error))
        raise DaemonError(error)
    return reply


def ping(session, timeout=PING_TIMEOUT_S):
    """True if the daemon answers a ping within *timeout* seconds."""
    try:
        return call_daemon(session, "ping", timeout=timeout).get("status") == "ok"
    except (DaemonError, OSError, EOFError):
        return False


def run_stages(session, config, produce, start_from, extra_overrides=None, after=None):
    """Run pipeline stages through the daemon's ``run`` command and return its reply.

    *config* is a USCConfig.  The run folder is ``config.out_dir``; the YAML
    path is sent only when ``config.yaml_path`` is set, otherwise the daemon
    builds the configuration from the mode's starting values.  The overrides
    sent are ``config.overrides`` with *extra_overrides* (a {key: value}
    dict, or None) on top.  *produce* is a list of stage names and
    *start_from* the first stage to run.  The reply's ``stage_folders`` names
    the folder of each stage that ran, and its ``issues`` go to
    :func:`show_issues`.  *after* (the thresholding manifest of the previous
    criterion, or None) is sent when given: thresholding then keeps only
    voxels that criterion kept.  An engine that does not list ``run_after``
    among the ``features`` of its ping reply would ignore it, so the daemon
    is pinged first and a DaemonError raised for an older one.

    Without a YAML the configuration needs ``max_volume_path`` and
    ``test_surface_path``.  When the overrides lack them, they default to the
    PLY files USC_Preprocess writes to ``<run folder>/incoming`` (stages after
    preprocessing never read them).
    """
    overrides = dict(config.overrides, **(extra_overrides or {}))
    if not config.yaml_path:
        incoming = Path(config.out_dir) / "incoming"
        overrides.setdefault("max_volume_path", str(incoming / "max_volume.ply"))
        overrides.setdefault("test_surface_path", str(incoming / "test_surfaces.ply"))
    payload = {
        "produce": list(produce),
        "start_from": start_from,
        "run_folder": str(config.out_dir),
        "overrides": override_list(overrides),
    }
    if config.yaml_path:
        payload["config"] = str(config.yaml_path)
    if after:
        if "run_after" not in call_daemon(session, "ping", timeout=PING_TIMEOUT_S).get("features", []):
            raise DaemonError("The UrbanSolarCarver engine running now is older than this definition and cannot "
                              "chain criteria. Restart it from USC_Session.")
        payload["after"] = str(after)
    return call_daemon(session, "run", payload)


def stage_folder_mismatch(config, manifest_path, stage):
    """An error message when *manifest_path* is not in the Config run folder's *stage* folder, else None.

    The stage components run against ``<config.out_dir>/<stage>``.  A
    connected result from another folder would be silently ignored, so the
    message names both folders.
    """
    expected = Path(config.out_dir) / stage
    connected = Path(str(manifest_path)).parent
    if os.path.normcase(os.path.abspath(connected)) == os.path.normcase(os.path.abspath(expected)):
        return None
    return ("The connected {0} result is in {1}, but the Config run folder uses {2}. "
            "Connect the {0} result of this run, or change out_dir in USC_Config".format(
                stage, connected, expected))


# ---------------------------------------------------------------- engine modules
def engine_module(root, name):
    """Load ``<root>/src/urbansolarcarver/<name>.py`` by path and return the module.

    Meant for the standard-library-only engine modules (``mode_registry``,
    ``archetype_defaults``); they have no package-relative imports.  The
    module is cached in ``sys.modules`` as ``usc_engine_<name>`` and loaded
    again when the file changes.  It is registered before it runs because
    dataclasses look their module up in ``sys.modules``.
    """
    import importlib.util
    import sys
    path = Path(root) / "src" / "urbansolarcarver" / "{}.py".format(name)
    stamp = (str(path), path.stat().st_mtime)
    key = "usc_engine_{}".format(name)
    mod = sys.modules.get(key)
    if mod is not None and getattr(mod, "_source", None) == stamp:
        return mod
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(key, None)
        raise
    mod._source = stamp
    return mod


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


def read_plates(path):
    """The plate list of a massing run's plates.json (outlines in world coordinates)."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)["plates"]


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
    """A triangulated copy of a Mesh, Brep or Extrusion (bare, GH-wrapped, or a
    document object id); None otherwise."""
    import Rhino.Geometry as rg
    import System
    if hasattr(geom, "Value"):  # GH_ObjectWrapper and goo
        geom = geom.Value
    if isinstance(geom, System.Guid):
        # Components placed with the older "ghdoc Object" input hint receive
        # geometry as ids of the script's document.
        import rhinoscriptsyntax as rs
        geom = rs.coercegeometry(geom)
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


def write_optional_geometry(items, folder, name):
    """Write an optional mesh input (context, terrain) as <folder>/<name>.ply for the daemon.

    Returns the path, or None when nothing is connected (an earlier file of
    that name is removed, so a disconnected input is not used again).  The
    input's meshes are joined and welded like the max volume: the column rule
    of the context needs closed bodies.  Raises ValueError when the input
    holds items but no Mesh or Brep geometry.
    """
    path = Path(folder) / (name + ".ply")
    if not items:
        path.unlink(missing_ok=True)
        return None
    import Rhino.Geometry as rg

    meshes = meshes_from_input(items)
    if not meshes:
        raise ValueError(name + " contains no Mesh or Brep geometry")
    joined = rg.Mesh()
    for m in meshes:
        joined.Append(m)
    joined.Vertices.CombineIdentical(True, True)
    joined.Faces.CullDegenerateFaces()
    joined.Compact()
    path.parent.mkdir(parents=True, exist_ok=True)
    export_mesh_to_ply(joined, path, include_normals=False)
    return str(path)


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
# PLY property type -> struct format character (little-endian).
_PLY_STRUCT = {
    "char": "b", "uchar": "B", "short": "h", "ushort": "H", "int": "i", "uint": "I",
    "float": "f", "double": "d", "int8": "b", "uint8": "B", "int16": "h",
    "uint16": "H", "int32": "i", "uint32": "I", "float32": "f", "float64": "d",
}


def read_ply(path):
    """Read vertices and faces from a PLY file (binary little-endian or ASCII).

    Vertex properties may come in any order and type; only x, y, z are
    read.  Faces may have any number of corners and any list count and
    index types.  Returns ``(verts, faces)``: a list of (x, y, z) floats and
    a list of index tuples.  Raises ValueError for anything else (big-endian
    files, missing x/y/z, no end_header).
    """
    binary = False
    elements = []  # [name, count, [(prop_name, struct_char or (count_char, index_char))]]
    with open(path, "rb") as f:
        if f.readline().strip() != b"ply":
            raise ValueError("Not a PLY file: {}".format(path))
        while True:
            raw = f.readline()
            if not raw:
                raise ValueError("Not a valid PLY file (no end_header): {}".format(path))
            parts = raw.decode("ascii", errors="replace").split()
            if not parts:
                continue
            if parts[0] == "end_header":
                break
            if parts[0] == "format":
                if parts[1] == "binary_big_endian":
                    raise ValueError("Big-endian PLY is not supported: {}".format(path))
                binary = parts[1] == "binary_little_endian"
            elif parts[0] == "element":
                elements.append([parts[1], int(parts[2]), []])
            elif parts[0] == "property" and elements:
                if parts[1] == "list":
                    elements[-1][2].append((parts[4], (_PLY_STRUCT[parts[2]], _PLY_STRUCT[parts[3]])))
                else:
                    elements[-1][2].append((parts[2], _PLY_STRUCT[parts[1]]))
        body = f.read()

    verts, faces = [], []
    if binary:
        pos = 0
        for name, count, props in elements:
            fixed = all(not isinstance(t, tuple) for _, t in props)
            if fixed:  # one struct call per row
                row = struct.Struct("<" + "".join(t for _, t in props))
                names = [n for n, _ in props]
                rows = [row.unpack_from(body, pos + i * row.size) for i in range(count)]
                pos += count * row.size
                if name == "vertex":
                    ix, iy, iz = names.index("x"), names.index("y"), names.index("z")
                    verts = [(r[ix], r[iy], r[iz]) for r in rows]
                continue
            for _ in range(count):
                for prop, t in props:
                    if isinstance(t, tuple):
                        (n,) = struct.unpack_from("<" + t[0], body, pos)
                        pos += struct.calcsize(t[0])
                        idx = struct.unpack_from("<{}{}".format(n, t[1]), body, pos)
                        pos += n * struct.calcsize(t[1])
                        if name == "face" and prop in ("vertex_indices", "vertex_index"):
                            faces.append(idx)
                    else:
                        pos += struct.calcsize(t)
    else:
        tokens = body.decode("ascii", errors="replace").split()
        pos = 0
        for name, count, props in elements:
            for _ in range(count):
                values = {}
                for prop, t in props:
                    if isinstance(t, tuple):
                        n = int(tokens[pos])
                        values[prop] = tuple(int(x) for x in tokens[pos + 1:pos + 1 + n])
                        pos += 1 + n
                    else:
                        values[prop] = tokens[pos]
                        pos += 1
                if name == "vertex":
                    verts.append((float(values["x"]), float(values["y"]), float(values["z"])))
                elif name == "face":
                    faces.append(values.get("vertex_indices", values.get("vertex_index", ())))
    return verts, faces


def load_ply_to_rhino(path):
    """Read a PLY file (see :func:`read_ply`) into a Rhino Mesh.

    Faces with more than four corners are split into triangles around their
    first corner.  The mesh keeps double-precision vertices.
    """
    import System
    import Rhino.Geometry as rg

    verts, faces = read_ply(path)
    mesh = rg.Mesh()
    # Without this Rhino stores float32 vertices: 0.5 m steps at UTM coordinates.
    mesh.Vertices.UseDoublePrecisionVertices = True
    pts = System.Array.CreateInstance(rg.Point3d, len(verts))
    for i, (x, y, z) in enumerate(verts):
        pts[i] = rg.Point3d(x, y, z)
    mesh.Vertices.AddVertices(pts)
    mesh_faces = []
    for idx in faces:
        if len(idx) == 3:
            mesh_faces.append(rg.MeshFace(idx[0], idx[1], idx[2]))
        elif len(idx) == 4:
            mesh_faces.append(rg.MeshFace(idx[0], idx[1], idx[2], idx[3]))
        else:
            mesh_faces.extend(rg.MeshFace(idx[0], idx[k], idx[k + 1])
                              for k in range(1, len(idx) - 1))
    face_arr = System.Array.CreateInstance(rg.MeshFace, len(mesh_faces))
    for i, face in enumerate(mesh_faces):
        face_arr[i] = face
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
