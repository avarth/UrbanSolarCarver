"""Drawn context blocks (design/context-blocks.md): outlines on the ground extruded to a height, stored in project.json and joined
into the context with the context files, which they never change. A block's volume is a site's (sites.site_volume)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import trimesh

from ..io import save_mesh
from ..sites import Site, check_site, site_polygon, site_volume
from .api_models import ContextBlockJson, ContextBlocksReply
from .project_names import ProjectError
from .site_input import OVERLAP_AREA, SITE_GROUND_SPACING

CONTEXT_ROLE = "context"
BLOCKS_MESH_PATH = "inputs/joined/context_blocks.ply"     # the blocks alone, for the 3D view


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


def blocks_mesh_path(store, name: str) -> Path:
    """The blocks' mesh the view draws; ProjectError 404 without blocks."""
    path = store.open(name) / BLOCKS_MESH_PATH
    if not path.is_file():
        raise ProjectError("The project has no drawn blocks.", status_code=404)
    return path


def blocks_reply(store, name: str) -> ContextBlocksReply:
    return ContextBlocksReply(blocks=store.read_project_json(name).context_blocks,
                              has_mesh=(store.open(name) / BLOCKS_MESH_PATH).is_file())


def save_context_blocks(store, name: str, entries: list[ContextBlockJson]) -> ContextBlocksReply:
    """Store the whole list of blocks and build the joined context again from the context files and the blocks (the files are
    never written). ProjectError 422 names every problem (refused_blocks), and then nothing changes. A joined context that came out
    different raises inputs_revision (the criteria and studies go out of date) and rebuilds the picked surface sets."""
    with store.project_lock(name):
        refused = refused_blocks(entries)
        if refused:
            raise ProjectError(" ".join(refused), status_code=422)
        project_json = store.read_project_json(name)
        if [entry.model_dump() for entry in entries] == [entry.model_dump() for entry in project_json.context_blocks]:
            return blocks_reply(store, name)
        project_folder = store.open(name)
        project_json.context_blocks = list(entries)
        file_meshes = store._load_stored_meshes(project_folder, CONTEXT_ROLE, list(project_json.input_files.get(CONTEXT_ROLE, {})))
        joined_temporary_path = store._write_joined_temporary_file(
            project_folder, CONTEXT_ROLE, store._role_meshes(project_json, CONTEXT_ROLE, list(file_meshes.values())))
        blocks_temporary_path = _write_blocks_temporary_file(project_folder, entries)
        try:
            from .stored_files import _same_joined_content
            changed = not _same_joined_content(joined_temporary_path, project_folder / "inputs" / "joined" / f"{CONTEXT_ROLE}.ply")
            if changed:
                project_json.inputs_revision += 1
            store.write_project_json(name, project_json)
            store._replace_joined_file(project_folder, CONTEXT_ROLE, joined_temporary_path)
            _replace_blocks_file(project_folder, blocks_temporary_path)
            if changed:
                store.rebuild_picked_sets(project_folder, project_json)
                store.write_project_json(name, project_json)
            store._update_optional_paths(project_folder, name)
        finally:
            for path in (joined_temporary_path, blocks_temporary_path):
                if path is not None:
                    path.unlink(missing_ok=True)
    return blocks_reply(store, name)


def _write_blocks_temporary_file(project_folder: Path, entries: list[ContextBlockJson]) -> Path | None:
    """The blocks' volumes joined into a new temporary PLY beside the joined files; None without blocks."""
    if not entries:
        return None
    descriptor, temporary_name = tempfile.mkstemp(dir=project_folder / "inputs" / "joined", prefix="context_blocks-", suffix=".tmp.ply")
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        save_mesh(trimesh.util.concatenate(block_meshes(entries)), str(temporary_path))
    except Exception as error:
        temporary_path.unlink(missing_ok=True)
        raise ProjectError(f"The drawn blocks could not be built: {error}", status_code=500) from error
    return temporary_path


def _replace_blocks_file(project_folder: Path, temporary_path: Path | None) -> None:
    target = project_folder / BLOCKS_MESH_PATH
    if temporary_path is None:
        target.unlink(missing_ok=True)
    else:
        os.replace(temporary_path, target)
