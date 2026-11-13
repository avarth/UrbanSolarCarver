"""Drawn context blocks (design/context-blocks.md): outlines on the ground extruded to a height, stored in project.json and joined
into the context with the context files, which they never change. A block's volume is a site's (sites.site_volume)."""
from __future__ import annotations

from ..sites import Site, check_site, site_polygon, site_volume
from .api_models import ContextBlockJson
from .site_input import OVERLAP_AREA, SITE_GROUND_SPACING


def block_site(entry: ContextBlockJson) -> Site:
    """The engine's site of a block: its outline, height and holes."""
    return Site(entry.name, tuple(tuple(point) for point in entry.points), entry.height,
                tuple(tuple(tuple(point) for point in hole) for hole in entry.holes))


def refused_blocks(entries: list[ContextBlockJson]) -> list[str]:
    """One sentence for each problem of the list: a block that cannot make a volume, a name used twice (letter case ignored), and
    each pair of blocks whose plan areas overlap (the engine voxelizes the context in one parity pass, so an overlap would count as
    outside). Touching along an edge or at a vertex is not an overlap. Empty when the list can be stored."""
    sentences = []
    polygons = []
    for index, entry in enumerate(entries):
        reasons = check_site(block_site(entry))
        if reasons:
            sentences.append(f"{entry.name}: {'; '.join(reasons)}.")
        else:
            polygons.append((index, site_polygon(block_site(entry))))
    seen: dict[str, str] = {}
    for entry in entries:
        key = entry.name.casefold()
        if key in seen:
            sentences.append(f"Two blocks are named {entry.name}.")
        seen.setdefault(key, entry.name)
    for position, (first, polygon) in enumerate(polygons):
        for second, other in polygons[position + 1:]:
            if polygon.intersects(other) and polygon.intersection(other).area > OVERLAP_AREA:
                sentences.append(f"{entries[second].name} overlaps {entries[first].name}.")
    return sentences


def block_meshes(entries: list[ContextBlockJson]) -> list:
    """The closed volume (a trimesh) of each block, in order."""
    return [site_volume(block_site(entry), SITE_GROUND_SPACING) for entry in entries]
