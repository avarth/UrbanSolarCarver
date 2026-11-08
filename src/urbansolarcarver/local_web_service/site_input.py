"""A site as the input (design/site-input.md): a project's maximum volume made from its sites in place of mesh files.

A project stores its sites in project.json (closed outlines with the ground's elevation at each vertex, in the input files'
coordinates, and a height each) and whether its maximum volume comes from them or from the mesh files of the max_volume role
(max_volume_source). While it comes from the sites, the joined max volume (inputs/joined/max_volume.ply) is the joined volumes of the
sites (sites.py), built again at every change of the sites; the engine carves it as it carves a joined mesh. Switching the source
builds the joined file from the other input and keeps the data of the one left.

Every change that touches the joined file raises inputs_revision, so the criteria go out of date as they do after an upload.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..io import save_mesh
from ..sites import Site, check_site, sites_volume
from .api_models import MaxVolumeSource, ProjectJson, SiteJson, SitesReply
from .project_names import ProjectError

MAX_VOLUME_ROLE = "max_volume"
# The ground inside a site is computed on points this far apart (finer on a small site, sites.ground_spacing); fixed rather than the
# voxel size, so a change of the voxel size does not build the maximum volume again
SITE_GROUND_SPACING = 1.0


def uses_sites(project_json: ProjectJson) -> bool:
    return project_json.max_volume_source == "sites"


def site_of(entry: SiteJson) -> Site:
    return Site(entry.name, tuple(tuple(point) for point in entry.points), entry.height)


def sites_reply(store, name: str) -> SitesReply:
    project_json = store.read_project_json(name)
    return SitesReply(source=project_json.max_volume_source, sites=project_json.sites, joined_bounds=store.joined_bounds(name),
                      grid_plan=store.stored_grid_plan(name))


def joined_max_volume_path(store, name: str) -> Path:
    """The joined max volume file; ProjectError 404 before there is one."""
    path = store.open(name) / "inputs" / "joined" / "max_volume.ply"
    if not path.is_file():
        raise ProjectError("The project has no maximum volume yet.", status_code=404)
    return path


def refused_sites(entries: list[SiteJson]) -> list[str]:
    """One sentence for each site that cannot make a volume, naming it ("Site 2: the outline crosses itself.")."""
    return [f"{entry.name}: {'; '.join(reasons)}." for entry in entries if (reasons := check_site(site_of(entry)))]


def save_sites(store, name: str, entries: list[SiteJson]) -> SitesReply:
    """Store the whole list of sites; while the project uses them, build the joined max volume again. ProjectError 422 names every
    site that cannot make a volume, and then nothing changes."""
    refused = refused_sites(entries)
    if refused:
        raise ProjectError(" ".join(refused), status_code=422)
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        project_folder = store.open(name)
        if [entry.model_dump() for entry in entries] == [entry.model_dump() for entry in project_json.sites]:
            return sites_reply(store, name)
        project_json.sites = list(entries)
        if uses_sites(project_json):
            _build_joined_from_sites(store, project_folder, project_json)
            project_json.inputs_revision += 1
        store.write_project_json(name, project_json)
    return sites_reply(store, name)


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
        store.write_project_json(name, project_json)
    return sites_reply(store, name)


def refuse_mesh_files_while_sites(project_json: ProjectJson, role: str) -> None:
    """A project that makes its maximum volume from its sites takes no maximum volume file: ProjectError 422."""
    if role == MAX_VOLUME_ROLE and uses_sites(project_json):
        raise ProjectError("This project makes its maximum volume from its sites: choose the maximum volume input first to add files.",
                           status_code=422)


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
            save_mesh(sites_volume([site_of(entry) for entry in project_json.sites], SITE_GROUND_SPACING), str(temporary_path))
        except Exception as error:
            raise ProjectError(f"The maximum volume could not be built from the sites: {error}", status_code=500) from error
        store._replace_joined_file(project_folder, MAX_VOLUME_ROLE, temporary_path)
    finally:
        temporary_path.unlink(missing_ok=True)
