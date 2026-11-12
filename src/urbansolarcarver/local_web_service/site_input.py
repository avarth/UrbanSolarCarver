"""A site as the input (design/site-input.md): a project's maximum volume made from its sites in place of mesh files.

A project stores its sites in project.json (closed outlines with the ground's elevation at each vertex, in the input files'
coordinates, and a height each) and whether its maximum volume comes from them or from the mesh files of the max_volume role
(max_volume_source). While it comes from the sites, the joined max volume (inputs/joined/max_volume.ply) is the joined volumes of the
sites (sites.py), built again at every change of the sites; the engine carves it as it carves a joined mesh. Switching the source
builds the joined file from the other input and keeps the data of the one left.

Every change that touches the joined file raises inputs_revision, so the criteria go out of date as they do after an upload.

The heights (design/base-height.md): a max height and a base height, each one for all sites or each site's own (project.json
``heights``). A base height keeps everything below it: the service writes the kept volume (inputs/joined/kept_volume_<digest>.ply,
the engine's kept_volume_path), named by its content, so a change of the base gives config.yaml a new path and puts thresholding out of
date, not the analysis. With a mesh maximum volume the base height's value is one level above the mesh's lowest point.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from shapely.geometry import Polygon

from ..io import save_mesh
from ..sites import Site, check_site, outline_points, site_base_volume, site_polygon, site_rise, site_volume, sites_volume
from .api_models import HeightsJson, MaxVolumeSource, ProjectJson, SiteJson, SiteOverlap, SitesReply
from .criteria import KEPT_VOLUME_GLOB, KEPT_VOLUME_PATH
from .project_names import ProjectError

MAX_VOLUME_ROLE = "max_volume"
# The ground inside a site is computed on points this far apart (finer on a small site, sites.ground_spacing); fixed rather than the
# voxel size, so a change of the voxel size does not build the maximum volume again
SITE_GROUND_SPACING = 1.0
# The kept volume starts this far below the lowest point of the maximum volume, so it holds the lowest voxels whole.
KEPT_VOLUME_BELOW = 2.0
# The part of the maximum volume below the base heights, for the view (the kept volume itself is a prism reaching below the ground)
BASE_VOLUME_PATH = "inputs/joined/base_volume.ply"


def uses_sites(project_json: ProjectJson) -> bool:
    return project_json.max_volume_source == "sites"


def max_height_of(entry: SiteJson, heights: HeightsJson) -> float:
    """The site's max height: the project's while the max height is one for all sites, else its own."""
    return heights.max.value if heights.max.for_all_sites and heights.max.value is not None else entry.height


def base_height_of(entry: SiteJson, heights: HeightsJson) -> float | None:
    """The site's base height: the project's while the base height is one for all sites, else its own; None for no lower limit
    (none, or 0)."""
    value = heights.base.value if heights.base.for_all_sites else entry.base_height
    return value if value else None


def site_of(entry: SiteJson, heights: HeightsJson | None = None) -> Site:
    """The engine's site of *entry*, with its max height (its own without *heights*)."""
    height = entry.height if heights is None else max_height_of(entry, heights)
    return Site(entry.name, tuple(tuple(point) for point in entry.points), height,
                tuple(tuple(tuple(point) for point in hole) for hole in entry.holes))


def site_reasons(entry: SiteJson, heights: HeightsJson) -> list[str]:
    """Why the site cannot make a volume with *heights*: the outline and max height (check_site) and a base not below the max."""
    reasons = check_site(site_of(entry, heights))
    base, top = base_height_of(entry, heights), max_height_of(entry, heights)
    if base is not None and base >= top:
        reasons.append(f"its base height ({base:g} m) must be less than its max height ({top:g} m)")
    return reasons


def sites_reply(store, name: str) -> SitesReply:
    project_json = store.read_project_json(name)
    return SitesReply(source=project_json.max_volume_source, sites=project_json.sites, joined_bounds=store.joined_bounds(name),
                      grid_plan=store.stored_grid_plan(name), heights=project_json.heights, overlaps=site_overlaps(project_json.sites))


OVERLAP_AREA = 1e-3         # m²: sites sharing less than this (an edge, a vertex, a sliver of rounding) do not overlap


def site_overlaps(entries: list[SiteJson]) -> list[SiteOverlap]:
    """The pairs of sites whose areas in plan (outline minus holes) share more than OVERLAP_AREA; a pair where one site's outline lies
    wholly inside the other's area is reported with that one first and inside true. Sites that cannot make a volume are left out."""
    polygons = []
    for index, entry in enumerate(entries):
        site = site_of(entry)
        if not check_site(Site(site.name, site.points, site_rise(site) + 1.0, site.holes)):
            polygons.append((index, site_polygon(site)))
    overlaps = []
    for position, (first, polygon) in enumerate(polygons):
        for second, other in polygons[position + 1:]:
            if not polygon.intersects(other) or polygon.intersection(other).area <= OVERLAP_AREA:
                continue
            if other.contains(Polygon(polygon.exterior)):
                overlaps.append(SiteOverlap(first=first, second=second, inside=True))
            elif polygon.contains(Polygon(other.exterior)):
                overlaps.append(SiteOverlap(first=second, second=first, inside=True))
            else:
                overlaps.append(SiteOverlap(first=first, second=second, inside=False))
    return overlaps


def base_volume_path(store, name: str) -> Path:
    """The part of the maximum volume below the base heights (the view draws it solid); ProjectError 404 without a base height."""
    path = store.open(name) / BASE_VOLUME_PATH
    if not path.is_file():
        raise ProjectError("The project has no base height.", status_code=404)
    return path


def joined_max_volume_path(store, name: str) -> Path:
    """The joined max volume file; ProjectError 404 before there is one."""
    path = store.open(name) / "inputs" / "joined" / "max_volume.ply"
    if not path.is_file():
        raise ProjectError("The project has no maximum volume yet.", status_code=404)
    return path


def refused_sites(entries: list[SiteJson], heights: HeightsJson | None = None) -> list[str]:
    """One sentence for each site that cannot make a volume, naming it ("Site 2: the outline crosses itself.")."""
    heights = HeightsJson() if heights is None else heights
    return [f"{entry.name}: {'; '.join(reasons)}." for entry in entries if (reasons := site_reasons(entry, heights))]


def _volumes_of(entries: list[SiteJson], heights: HeightsJson) -> list[Site]:
    return [site_of(entry, heights) for entry in entries]


def save_sites(store, name: str, entries: list[SiteJson]) -> SitesReply:
    """Store the whole list of sites; while the project uses them, build the joined max volume again when a site's volume changed
    (a change of base heights alone keeps it, and the analysis stays current) and write the kept volume. ProjectError 422 names every
    site that cannot make a volume, and then nothing changes."""
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        refused = refused_sites(entries, project_json.heights)
        if refused:
            raise ProjectError(" ".join(refused), status_code=422)
        project_folder = store.open(name)
        if [entry.model_dump() for entry in entries] == [entry.model_dump() for entry in project_json.sites]:
            return sites_reply(store, name)
        volumes_before = _volumes_of(project_json.sites, project_json.heights)
        project_json.sites = list(entries)
        _apply(store, name, project_folder, project_json, volumes_changed=volumes_before != _volumes_of(entries, project_json.heights))
    return sites_reply(store, name)


def set_heights(store, name: str, heights: HeightsJson) -> SitesReply:
    """Store the max height and the base height of the sites; ProjectError 422 names every site the new heights refuse, and then
    nothing changes. A change of the max height builds the maximum volume again (everything goes out of date); a change of the base
    height writes the kept volume only (thresholding goes out of date)."""
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        if heights.model_dump() == project_json.heights.model_dump():
            return sites_reply(store, name)
        if uses_sites(project_json):
            refused = refused_sites(project_json.sites, heights)
            if refused:
                raise ProjectError(" ".join(refused), status_code=422)
        project_folder = store.open(name)
        volumes_before = _volumes_of(project_json.sites, project_json.heights)
        project_json.heights = heights
        _apply(store, name, project_folder, project_json,
               volumes_changed=volumes_before != _volumes_of(project_json.sites, heights))
    return sites_reply(store, name)


def _apply(store, name: str, project_folder: Path, project_json: ProjectJson, *, volumes_changed: bool) -> None:
    """Build what the stored sites and heights make while the project uses them, and write project.json and config.yaml."""
    if uses_sites(project_json) and volumes_changed:
        _build_joined_from_sites(store, project_folder, project_json)
        project_json.inputs_revision += 1
    update_kept_volume(project_folder, project_json)
    store.write_project_json(name, project_json)
    store._update_optional_paths(project_folder, name)


def set_max_volume_source(store, name: str, source: MaxVolumeSource) -> SitesReply:
    """Make the maximum volume from the sites or from the mesh files, building the joined file from that input (none when it is
    empty); the other input's data stays. Nothing changes when the source is already *source*."""
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        if project_json.max_volume_source == source:
            return sites_reply(store, name)
        project_folder = store.open(name)
        project_json.max_volume_source = source
        if source == "sites":
            _build_joined_from_sites(store, project_folder, project_json)
        else:
            file_names = list(project_json.input_files.get(MAX_VOLUME_ROLE, {}))
            meshes = store._load_stored_meshes(project_folder, MAX_VOLUME_ROLE, file_names)
            temporary_path = store._write_joined_temporary_file(project_folder, MAX_VOLUME_ROLE, [meshes[n] for n in sorted(meshes)])
            try:
                store._replace_joined_file(project_folder, MAX_VOLUME_ROLE, temporary_path)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
        project_json.inputs_revision += 1
        update_kept_volume(project_folder, project_json)
        store.write_project_json(name, project_json)
        store._update_optional_paths(project_folder, name)
    return sites_reply(store, name)


def refuse_mesh_files_while_sites(project_json: ProjectJson, role: str) -> None:
    """A project that makes its maximum volume from its sites takes no maximum volume file: ProjectError 422."""
    if role == MAX_VOLUME_ROLE and uses_sites(project_json):
        raise ProjectError("This project makes its maximum volume from its sites: choose the maximum volume input first to add files.",
                           status_code=422)


def _kept_volume_mesh(project_folder: Path, project_json: ProjectJson):
    """The volume the base heights keep (a trimesh), or None when there is no base height or nothing to keep it on."""
    import trimesh

    heights = project_json.heights
    if uses_sites(project_json):
        entries = [(entry, base) for entry in project_json.sites if (base := base_height_of(entry, heights)) is not None]
        if not entries:
            return None
        bottom = min(float(outline_points(site_of(entry))[:, 2].min()) for entry in project_json.sites) - KEPT_VOLUME_BELOW
        return trimesh.util.concatenate([site_base_volume(site_of(entry, heights), base, bottom) for entry, base in entries])
    base = heights.base.value
    joined = project_folder / "inputs" / "joined" / "max_volume.ply"
    if not base or not joined.is_file():
        return None
    low, high = trimesh.load(str(joined), force="mesh").bounds
    box = trimesh.creation.box(bounds=[[low[0] - 1.0, low[1] - 1.0, low[2] - KEPT_VOLUME_BELOW], [high[0] + 1.0, high[1] + 1.0, low[2] + base]])
    return box


def _base_volume_mesh(project_folder: Path, project_json: ProjectJson):
    """The maximum volume cut at the base levels, capped (a trimesh), or None without a base height."""
    import trimesh

    heights = project_json.heights
    if uses_sites(project_json):
        parts = []
        for entry in project_json.sites:
            base = base_height_of(entry, heights)
            if base is None or check_site(site_of(entry, heights)):
                continue
            site = site_of(entry, heights)
            level = float(outline_points(site)[:, 2].min()) + base
            parts.append(site_volume(site, SITE_GROUND_SPACING).slice_plane([0.0, 0.0, level], [0.0, 0.0, -1.0], cap=True))
        parts = [part for part in parts if len(part.faces)]
        return trimesh.util.concatenate(parts) if parts else None
    joined = project_folder / "inputs" / "joined" / "max_volume.ply"
    if not heights.base.value or not joined.is_file():
        return None
    mesh = trimesh.load(str(joined), force="mesh")
    cut = mesh.slice_plane([0.0, 0.0, float(mesh.bounds[0][2]) + heights.base.value], [0.0, 0.0, -1.0], cap=True)
    return cut if len(cut.faces) else None


def _write_base_volume(project_folder: Path, project_json: ProjectJson) -> None:
    """Write the base volume for the view, or remove it; a cut that fails leaves none (the view then draws the maximum volume alone)."""
    path = project_folder / BASE_VOLUME_PATH
    try:
        mesh = _base_volume_mesh(project_folder, project_json)
    except Exception:       # noqa: BLE001 - only the view's picture depends on it; the kept volume is what the engine reads
        mesh = None
    if mesh is None:
        path.unlink(missing_ok=True)
        return
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix="base-", suffix=".tmp.ply")
    os.close(descriptor)
    try:
        save_mesh(mesh, temporary_name)
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def update_kept_volume(project_folder: Path, project_json: ProjectJson) -> bool:
    """Write the kept volume of *project_json* (named by a digest of its content) and remove any other, or remove it when there is
    none, and the base volume the view draws; whether the file the config names changed. The caller writes config.yaml
    (ProjectStore._update_optional_paths)."""
    joined_folder = project_folder / "inputs" / "joined"
    if joined_folder.is_dir():
        _write_base_volume(project_folder, project_json)
    earlier = sorted(joined_folder.glob(KEPT_VOLUME_GLOB))
    mesh = _kept_volume_mesh(project_folder, project_json)
    if mesh is None:
        for path in earlier:
            path.unlink(missing_ok=True)
        return bool(earlier)
    joined_folder.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=joined_folder, prefix="kept-", suffix=".tmp.ply")
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        save_mesh(mesh, str(temporary_path))
        digest = hashlib.sha256(temporary_path.read_bytes()).hexdigest()[:12]
        target = project_folder / KEPT_VOLUME_PATH.format(digest=digest)
        if target in earlier:
            return False
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)
    for path in earlier:
        path.unlink(missing_ok=True)
    return True


def _build_joined_from_sites(store, project_folder: Path, project_json: ProjectJson) -> None:
    """Write the joined max volume from the sites, or remove it when there is none; ProjectError 500 when it cannot be built."""
    joined_folder = project_folder / "inputs" / "joined"
    if not project_json.sites:
        store._replace_joined_file(project_folder, MAX_VOLUME_ROLE, None)
        return
    descriptor, temporary_name = tempfile.mkstemp(dir=joined_folder, prefix=f"{MAX_VOLUME_ROLE}-", suffix=".tmp.ply")
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        try:
            save_mesh(sites_volume(_volumes_of(project_json.sites, project_json.heights), SITE_GROUND_SPACING), str(temporary_path))
        except Exception as error:
            raise ProjectError(f"The maximum volume could not be built from the sites: {error}", status_code=500) from error
        store._replace_joined_file(project_folder, MAX_VOLUME_ROLE, temporary_path)
    finally:
        temporary_path.unlink(missing_ok=True)
