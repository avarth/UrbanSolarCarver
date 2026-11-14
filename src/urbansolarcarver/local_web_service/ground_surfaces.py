"""Test surfaces drawn on flat ground (design/test-surfaces-on-ground.md): an outline drawn with the site editor, at one elevation
and with its holes, becomes a stored test surface file facing up. The outline is checked with the site editor's reasons (the app's
siteProblems), so a refusal here reads as one there. A drawn set does not depend on the context and is never rebuilt."""
from __future__ import annotations

import numpy as np
import shapely
import trimesh
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from .api_models import GroundOutline, ProjectJson
from .project_names import ProjectError

GROUND_PREFIX = "ground_"
MIN_AREA = 1.0              # m², as a site and a hole
SAME_LEVEL = 0.001          # m: vertices this close in elevation are on one level


def _refused(reason: str) -> ProjectError:
    return ProjectError(f"Not saved: {reason}.", status_code=422)


def _ring_polygon(points: list[list[float]]) -> Polygon:
    return Polygon([(x, y) for x, y, _ in points])


def checked_polygon(outline: GroundOutline) -> tuple[Polygon, float]:
    """The outline as a plan polygon with its holes, and its elevation; ProjectError 422 with the site editor's reason when it would
    be refused there, or when its vertices are not on one level."""
    every = [*outline.points, *(point for hole in outline.holes for point in hole)]
    z = float(outline.points[0][2])
    if any(abs(point[2] - z) > SAME_LEVEL for point in every):
        raise _refused("a ground surface is flat: its vertices need one elevation")
    shell = _ring_polygon(outline.points)
    if not shell.is_valid:
        raise _refused("the outline crosses itself")
    holes = [_ring_polygon(hole) for hole in outline.holes]
    for number, hole in enumerate(holes, start=1):
        if not hole.is_valid:
            raise _refused(f"hole {number} crosses itself")
        if hole.area < MIN_AREA:
            raise _refused(f"hole {number}'s area is {hole.area:.2f} m², less than 1 m²")
        if not shell.contains(hole) or shell.exterior.intersects(hole.exterior):
            raise _refused(f"hole {number} is not strictly inside the outline")
    for first in range(len(holes)):
        for second in range(first + 1, len(holes)):
            if holes[first].intersects(holes[second]):
                raise _refused(f"hole {first + 1} and hole {second + 1} touch or cross")
    polygon = Polygon(shell.exterior.coords, [hole.exterior.coords for hole in holes])
    if polygon.area < MIN_AREA:
        raise _refused(f"the surface's area is {polygon.area:.2f} m², less than 1 m²")
    return polygon, z


def ground_mesh(outline: GroundOutline) -> trimesh.Trimesh:
    """The flat surface of *outline*: its plan polygon triangulated (shapely's constrained Delaunay, holes left out) at its elevation,
    every triangle facing up."""
    polygon, z = checked_polygon(outline)
    vertices, faces, index = [], [], {}

    def vertex(x: float, y: float) -> int:
        key = (round(x, 6), round(y, 6))
        if key not in index:
            index[key] = len(vertices)
            vertices.append([x, y, z])
        return index[key]

    for triangle in shapely.constrained_delaunay_triangles(orient(polygon, 1.0)).geoms:
        a, b, c = np.asarray(orient(triangle, 1.0).exterior.coords)[:3]      # counter-clockwise in plan: facing up
        faces.append([vertex(*a), vertex(*b), vertex(*c)])
    return trimesh.Trimesh(vertices=np.asarray(vertices), faces=np.asarray(faces), process=True)


def next_ground_file_name(recorded_names) -> str:
    """ground_<n>.ply with the lowest n not stored yet (letter case ignored)."""
    taken = {name.lower() for name in recorded_names}
    number = 1
    while f"{GROUND_PREFIX}{number}.ply" in taken:
        number += 1
    return f"{GROUND_PREFIX}{number}.ply"


def next_ground_name(project_json: ProjectJson) -> str:
    """"Ground n" with the lowest n no set is shown by."""
    from .picked_surfaces import shown_name
    from .test_surfaces import ROLE
    shown = {shown_name(file_name, project_json.surface_sets.get(file_name)).lower() for file_name in project_json.input_files.get(ROLE, {})}
    number = 1
    while f"ground {number}" in shown:
        number += 1
    return f"Ground {number}"
