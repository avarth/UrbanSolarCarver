"""Sites imported from DXF and OBJ files, and the terrain's heights for Place on terrain (design/site-import.md).

The service reads a file's closed polylines (the engine's outlines.py), places them in the model and keeps the file in inputs/sites/;
it adds no site: the page adds the outlines it is given with PUT sites, as a drawing adds one, so the sites' checks and the page's undo
stay in one place.

Placing (section 4): the file's elevations are relative heights. Each vertex goes to the drawing level plus its height above the
lowest vertex of all outlines in the file, so outlines keep their levels relative to each other, a flat outline lands flat on the drawing
level, and survey elevations do not move the model. The drawing level is the one drawing uses (app/src/sites/site_drawing.ts): the
lowest vertex of the sites already there; for the first sites the lowest level of the existing surroundings and terrain, else 0.

Nesting (design/site-holes.md): an outline wholly inside another becomes a hole of the smallest outline around it; one inside a hole
is a site again (an island), and so on: outlines inside an even number of others are sites, inside an odd number holes. Outlines
that partly overlap stay separate sites.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Polygon

from ..errors import InputError
from ..outlines import read_outlines
from ..sites import Site, check_site, site_polygon, site_rise
from .api_models import ImportedOutline, OutlinesReply, TerrainHeightsReply
from .project_names import ProjectError

SITES_FOLDER = "inputs/sites"               # the imported outline files, kept so the originals can be traced
JOINED_FOLDER = "inputs/joined"
OUTLINE_EXTENSIONS = (".dxf", ".obj")
FAR_FROM_INPUTS = 1000.0                    # m in plan: outlines further from the other inputs are said to be so


def drawing_level(project_folder: Path, site_points: list[list[list[float]]]) -> float:
    """The drawing level, in the files' coordinates: the lowest vertex of the sites; without sites the lowest level of the joined
    surroundings and terrain, else 0."""
    z = [point[2] for points in site_points for point in points]
    if z:
        return float(min(z))
    lows = [bounds[0][2] for bounds in (_bounds_of(project_folder / JOINED_FOLDER / f"{role}.ply") for role in ("context", "terrain"))
            if bounds is not None]
    return float(min(lows)) if lows else 0.0


def _bounds_of(path: Path):
    return trimesh.load(str(path), force="mesh").bounds if path.is_file() else None


def placed(outline_points_list: list[np.ndarray], level: float) -> list[np.ndarray]:
    """The outlines with each vertex at *level* plus its height above the lowest vertex of them all."""
    lowest = min(float(points[:, 2].min()) for points in outline_points_list)
    return [np.column_stack([points[:, :2], points[:, 2] - lowest + level]) for points in outline_points_list]


def nested(outlines: list[np.ndarray]) -> list[tuple[int, list[int]]]:
    """The sites the outlines make: (index of the outline, indices of its holes), in the order of the outlines. An outline inside an
    odd number of others (strictly: touching is not inside) is a hole of the smallest one around it."""
    polygons = [Polygon(points[:, :2]) for points in outlines]
    around = [[j for j, other in enumerate(polygons) if j != i and other.contains(polygon) and not other.exterior.intersects(polygon.exterior)]
              for i, polygon in enumerate(polygons)]
    holes_of: dict[int, list[int]] = {i: [] for i in range(len(outlines)) if len(around[i]) % 2 == 0}
    for i in range(len(outlines)):
        if len(around[i]) % 2 == 1:
            holes_of[min(around[i], key=lambda j: polygons[j].area)].append(i)
    return [(i, holes_of[i]) for i in sorted(holes_of)]


def _plan_gap(outlines: list[np.ndarray], bounds_list: list[np.ndarray]) -> float | None:
    """How far apart in plan the outlines' box and the other inputs' box are (0 when they overlap); None without other inputs."""
    if not bounds_list:
        return None
    every = np.vstack(outlines)
    low, high = every[:, :2].min(axis=0), every[:, :2].max(axis=0)
    inputs_low = np.min([bounds[0][:2] for bounds in bounds_list], axis=0)
    inputs_high = np.max([bounds[1][:2] for bounds in bounds_list], axis=0)
    gap = np.maximum(0.0, np.maximum(inputs_low - high, low - inputs_high))
    return float(np.hypot(*gap))


def read_outline_file(store, name: str, file_name: str, data: bytes) -> OutlinesReply:
    """Read an uploaded DXF or OBJ file into outlines placed in the model, keep it in inputs/sites/, and say what was left out.

    ProjectError(422) for another file type, a file that cannot be read, or one with no closed polyline that can be a site.
    """
    from .projects import sanitize_file_name
    clean_name = sanitize_file_name(file_name)
    if Path(clean_name).suffix.lower() not in OUTLINE_EXTENSIONS:
        raise ProjectError("Outlines are imported from DXF or OBJ files.", status_code=422)
    project_folder = store.open(name)
    folder = project_folder / SITES_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    descriptor, upload_name = tempfile.mkstemp(dir=folder, prefix="upload", suffix=Path(clean_name).suffix.lower())
    upload_path = Path(upload_name)
    try:
        with os.fdopen(descriptor, "wb") as upload_file:
            upload_file.write(data)
        try:
            found = read_outlines(upload_path)
        except InputError as error:
            raise ProjectError(str(error).replace(upload_path.name, clean_name), status_code=422) from error
        left_out = [text.replace(upload_path.name, clean_name) for text in found.left_out]
        kept = []
        for number, outline in enumerate(found.outlines, start=1):
            points = np.asarray(outline.points, dtype=float)
            # The outline is checked as a site would be, with a max height above its rise, so only its shape can refuse it
            reasons = check_site(Site(outline.name, outline.points, _rise(points) + 10.0))
            if reasons:
                left_out.append(f"{outline.name or f'Outline {number}'}: {'; '.join(reasons)}")
            else:
                kept.append((outline.name, points))
        if not kept:
            raise ProjectError(f"No closed polyline in {clean_name} can be a site: {'; '.join(left_out)}.", status_code=422)
        project_json = store.read_project_json(name)
        level = drawing_level(project_folder, [site.points for site in project_json.sites])
        placed_points = placed([points for _, points in kept], level)
        os.replace(upload_path, folder / clean_name)
    finally:
        upload_path.unlink(missing_ok=True)
    other_bounds = [bounds for bounds in (_bounds_of(project_folder / JOINED_FOLDER / f"{role}.ply")
                                          for role in ("max_volume", "context", "terrain")) if bounds is not None]
    gap = _plan_gap(placed_points, other_bounds)
    outlines = []
    for index, hole_indices in nested(placed_points):
        outline_name, points = kept[index][0], placed_points[index]
        holes = tuple(tuple(map(tuple, placed_points[hole].tolist())) for hole in hole_indices)
        site = Site(outline_name, tuple(map(tuple, points.tolist())), 1.0, holes)
        # Holes that do not fit together (touching each other) are left out, and the outline stays a site without them
        hole_reasons = check_site(Site(site.name, site.points, site_rise(site) + 10.0, site.holes)) if holes else []
        if hole_reasons:
            left_out.append(f"the holes of {outline_name or f'Outline {index + 1}'}: {'; '.join(hole_reasons)}")
            site = Site(outline_name, site.points, 1.0)
        outlines.append(ImportedOutline(name=outline_name, points=points.tolist(), area=float(site_polygon(site).area),
                                        rise=float(site_rise(site)), holes=[[list(point) for point in hole] for hole in site.holes]))
    return OutlinesReply(file=clean_name, unit=found.unit, outlines=outlines, left_out=left_out,
                         distance_from_inputs=gap if gap is not None and gap > FAR_FROM_INPUTS else None)


def _rise(points: np.ndarray) -> float:
    return float(points[:, 2].max() - points[:, 2].min()) if len(points) else 0.0


def terrain_heights(store, name: str, points: list[list[float]]) -> TerrainHeightsReply:
    """The height of the top of the joined terrain under each plan point: the highest surface a vertical line through it meets; None
    where it meets none. ProjectError(404) without terrain."""
    path = store.open(name) / JOINED_FOLDER / "terrain.ply"
    if not path.is_file():
        raise ProjectError("The project has no terrain: add it in the Site step to place sites on it.", status_code=404)
    terrain = trimesh.load(str(path), force="mesh")
    xy = np.asarray(points, dtype=float)
    top = float(terrain.bounds[1][2]) + 1.0
    origins = np.column_stack([xy, np.full(len(xy), top)])
    directions = np.tile([0.0, 0.0, -1.0], (len(xy), 1))
    locations, ray_index, _ = terrain.ray.intersects_location(origins, directions, multiple_hits=True)
    heights: list[float | None] = [None] * len(xy)
    for location, index in zip(locations, ray_index):
        z = float(location[2])
        if heights[index] is None or z > heights[index]:
            heights[index] = z
    return TerrainHeightsReply(heights=heights)
