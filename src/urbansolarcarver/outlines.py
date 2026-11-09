"""Closed outlines read from DXF and OBJ files, for sites imported in the app, and the faces of a DXF file, for mesh inputs.

design/site-import.md. An outline is a closed polyline: its vertices in metres, not repeated at the end, with a name (the DXF layer, the
OBJ object or group). What a file holds besides closed polylines is counted and said, not dropped silently.

DXF is read with ezdxf, which keeps elevations (trimesh's DXF reader drops them) and reads the drawing's units ($INSUNITS):
millimetres, centimetres, inches and feet become metres, and a drawing without a unit is read as metres, as the meshes are. Entities in
blocks are read with their block's transform. Arcs in a polyline (bulges) become straight segments no more than ARC_TOLERANCE off the arc.

OBJ is read here: ``v`` and ``l`` lines; a line element is closed when its last index repeats its first, as Rhino writes a closed
polyline.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .errors import InputError

ARC_TOLERANCE = 0.05          # m: the most a straight segment of an arc may be off the arc
_SAME_POINT = 1e-9            # m: an end point within this of the start closes the polyline

# What a left-out DXF entity is called in the reason, in the plural
_KIND_NAMES = {"LINE": "lines", "ARC": "arcs", "CIRCLE": "circles", "ELLIPSE": "ellipses", "SPLINE": "splines", "HATCH": "hatches",
               "TEXT": "texts", "MTEXT": "texts", "POINT": "points", "3DFACE": "faces", "MESH": "meshes", "DIMENSION": "dimensions",
               "SOLID": "solids", "3DSOLID": "solids", "INSERT": "blocks"}


@dataclass(frozen=True)
class Outline:
    """A closed polyline: its name ("" for none) and its vertices (x, y, z) in metres, not repeated at the end."""
    name: str
    points: tuple[tuple[float, float, float], ...]


@dataclass
class OutlineFile:
    """The closed outlines of a file, what was left out (one text per kind: "2 open polylines"), and the unit it was read in."""
    outlines: list[Outline]
    left_out: list[str] = field(default_factory=list)
    unit: str = "metres"


def read_outlines(path: str | Path) -> OutlineFile:
    """The closed outlines of the DXF or OBJ file at *path*.

    Raises InputError when the file cannot be read, is of another type, or has no closed polyline.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".dxf":
        found = _dxf_outlines(path)
    elif suffix == ".obj":
        found = _obj_outlines(path)
    else:
        raise InputError(f"Outlines are read from DXF or OBJ files, not {suffix or 'a file without an extension'}.")
    if not found.outlines:
        raise InputError(f"No closed polylines in {path.name}. Close them in your CAD program, or join the lines into polylines.")
    return found


# ---- DXF -------------------------------------------------------------------------------------------------------------------------

def _read_dxf(path: Path):
    import ezdxf
    from ezdxf import recover
    try:
        document, auditor = recover.readfile(str(path))
    except (OSError, ezdxf.DXFStructureError) as error:
        raise InputError(f"{path.name} could not be read as a DXF file ({error}).") from error
    return document


def _dxf_scale(document) -> tuple[float, str]:
    """The factor from the drawing's units to metres, and the units' name ("metres" for a drawing without a unit)."""
    from ezdxf import units
    code = document.header.get("$INSUNITS", 0)
    if code in (0, units.M):
        return 1.0, "metres"
    try:
        factor = units.conversion_factor(code, units.M)
    except (KeyError, ValueError, TypeError):
        return 1.0, "metres"
    return float(factor), _UNIT_NAMES.get(code, str(units.unit_name(code)).lower())


_UNIT_NAMES = {1: "inches", 2: "feet", 4: "millimetres", 5: "centimetres", 6: "metres", 14: "decimetres"}


def _dxf_entities(document):
    """The model space's entities, with those in blocks taken out of their blocks (transformed)."""
    from ezdxf import disassemble
    return disassemble.recursive_decompose(document.modelspace())


def _dxf_outlines(path: Path) -> OutlineFile:
    from ezdxf import path as dxf_path
    document = _read_dxf(path)
    scale, unit = _dxf_scale(document)
    found: list[tuple[str, list[tuple[float, float, float]]]] = []
    left_out: Counter[str] = Counter()
    for entity in _dxf_entities(document):
        kind = entity.dxftype()
        if kind == "POLYLINE" and (entity.is_poly_face_mesh or entity.is_polygon_mesh):
            left_out["meshes"] += 1
            continue
        if kind not in ("LWPOLYLINE", "POLYLINE"):
            left_out[_KIND_NAMES.get(kind, "other entities")] += 1
            continue
        closed_flag = entity.closed if kind == "LWPOLYLINE" else entity.is_closed
        points = [tuple(float(value) * scale for value in vertex) for vertex in dxf_path.make_path(entity).flattening(ARC_TOLERANCE)]
        ring = _closed_ring(points, closed_flag)
        if ring is None:
            left_out["open polylines"] += 1
            continue
        found.append((str(entity.dxf.layer), ring))
    return OutlineFile(_named(found), _left_out_texts(left_out), unit)


# ---- OBJ -------------------------------------------------------------------------------------------------------------------------

def _obj_outlines(path: Path) -> OutlineFile:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise InputError(f"{path.name} could not be read ({error}).") from error
    vertices: list[tuple[float, float, float]] = []
    found: list[tuple[str, list[tuple[float, float, float]]]] = []
    left_out: Counter[str] = Counter()
    name = ""
    has_faces = False
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        key = parts[0]
        if key == "v" and len(parts) >= 4:
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif key in ("o", "g"):
            name = " ".join(parts[1:])
        elif key == "f":
            has_faces = True
        elif key == "l":
            indices = [_obj_index(part, len(vertices)) for part in parts[1:]]
            closed = len(indices) > 3 and indices[0] == indices[-1]
            ring = _closed_ring([vertices[index] for index in indices], closed)
            if ring is None:
                left_out["open polylines"] += 1
            else:
                found.append((name, ring))
    texts = _left_out_texts(left_out)
    if has_faces:
        texts.append(f"{path.name} has faces: it was read for its polylines only")
    return OutlineFile(_named(found), texts)


def _obj_index(part: str, count: int) -> int:
    """The 0-based vertex index of an OBJ index ("3", "3/1", "-1")."""
    index = int(part.split("/")[0])
    return index - 1 if index > 0 else count + index


# ---- Shared ----------------------------------------------------------------------------------------------------------------------

def _closed_ring(points: list[tuple[float, ...]], closed_flag: bool) -> list[tuple[float, float, float]] | None:
    """The polyline's vertices without the repeated end point when it is closed (by its flag, or by ending on its start); None when
    it is open or has fewer than three vertices."""
    ring = [(float(point[0]), float(point[1]), float(point[2]) if len(point) > 2 else 0.0) for point in points]
    ends_on_start = len(ring) > 1 and np.allclose(ring[0], ring[-1], atol=_SAME_POINT)
    if ends_on_start:
        ring = ring[:-1]
    if not (closed_flag or ends_on_start) or len(ring) < 3:
        return None
    return ring


def _named(found: list[tuple[str, list[tuple[float, float, float]]]]) -> list[Outline]:
    """The outlines, named after their layer or object; outlines that share a name are numbered ("Plots 1", "Plots 2")."""
    counts = Counter(name for name, _ in found)
    numbers: Counter[str] = Counter()
    outlines = []
    for name, ring in found:
        if name and counts[name] > 1:
            numbers[name] += 1
            shown = f"{name} {numbers[name]}"
        else:
            shown = name
        outlines.append(Outline(shown, tuple(ring)))
    return outlines


_SINGULAR = {"hatches": "hatch", "meshes": "mesh", "ellipses": "ellipse", "other entities": "other entity"}


def _left_out_texts(left_out: Counter[str]) -> list[str]:
    """One text per kind left out: "2 open polylines", "1 circle"."""
    texts = []
    for kind, count in left_out.items():
        shown = kind if count != 1 else _SINGULAR.get(kind, kind[:-1] if kind.endswith("s") else kind)
        texts.append(f"{count} {shown}")
    return texts


# ---- DXF faces, for mesh inputs -------------------------------------------------------------------------------------------------

def dxf_faces(path: str | Path):
    """The triangles of the DXF file at *path* (3DFACE, polyface and polygon-mesh POLYLINEs, MESH), in metres, as one trimesh; None
    when it has none.

    Raises InputError when it cannot be read, and when it has closed polylines but no faces (outlines, not a mesh).
    """
    import trimesh
    from ezdxf.render import MeshBuilder
    path = Path(path)
    document = _read_dxf(path)
    scale, _ = _dxf_scale(document)
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    polylines = 0

    def add_face(corners) -> None:
        corners = [tuple(float(value) * scale for value in corner) for corner in corners]
        unique = [corner for at, corner in enumerate(corners) if at == 0 or corner != corners[at - 1]]
        if len(unique) > 1 and unique[0] == unique[-1]:
            unique = unique[:-1]
        if len(unique) < 3:
            return
        start = len(vertices)
        vertices.extend(unique)
        triangles.extend((start, start + at, start + at + 1) for at in range(1, len(unique) - 1))

    for entity in _dxf_entities(document):
        kind = entity.dxftype()
        if kind == "3DFACE":
            add_face([entity.dxf.vtx0, entity.dxf.vtx1, entity.dxf.vtx2, entity.dxf.vtx3])
        elif kind == "POLYLINE" and (entity.is_poly_face_mesh or entity.is_polygon_mesh):
            mesh = MeshBuilder.from_polyface(entity)
            for face in mesh.faces_as_vertices():
                add_face(face)
        elif kind == "MESH":
            mesh = MeshBuilder.from_mesh(entity)
            for face in mesh.faces_as_vertices():
                add_face(face)
        elif kind in ("LWPOLYLINE", "POLYLINE"):
            polylines += 1
    if not triangles:
        if polylines:
            raise InputError(f"{path.name} has polylines but no faces (3DFACE, polyface or MESH): a mesh input needs faces.")
        return None
    return trimesh.Trimesh(vertices=np.asarray(vertices, dtype=float), faces=np.asarray(triangles, dtype=np.int64), process=True)
