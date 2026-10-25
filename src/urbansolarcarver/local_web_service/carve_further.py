"""Carve further: the exported envelope of a project becomes its maximum volume, to be carved again by another criterion.

Chained carving keeps what every criterion in the chain keeps (the intersection of their envelopes, up to the
re-voxelization of each envelope on the next run's grid). The replaced maximum volume files are kept and the chain is
recorded in project.json (see ProjectStore.replace_max_volume_with_envelope), so the current maximum volume can be traced
back to the one the user uploaded.
"""
from __future__ import annotations

from ..mode_registry import canonical_mode_name
from ..pydantic_schemas import ExportingManifest
from .api_models import NEW_PROJECT_MODE, CarvingChainStep
from .project_names import ProjectError
from .projects import RUN_FOLDER, GridOverBudget, ProjectStore
from .score_points import read_stage_manifest, resolve_stored_path
from .stage_records import stage_status

__all__ = ["NEW_PROJECT_MODE", "carve_further"]


def carve_further(store: ProjectStore, name: str) -> CarvingChainStep:
    """Make the project's exported envelope its maximum volume and return its settings to those of a new project.

    ProjectError 409 when the project has more than one criterion (the envelope is the result of the whole chain, and the
    settings to return belong to no single criterion), or when the envelope is missing or out of date (it would not be the
    result of the stored settings); nothing changes then.
    The caller makes sure no run of the project is active. The settings of the criterion return to the starting values of
    NEW_PROJECT_MODE; when that voxel size gives a grid over the budget, the voxel size the envelope was carved with
    stays (its grid held the larger maximum volume before, so it holds the envelope).
    """
    with store.project_lock(name):
        criteria = store.criteria(name)
        if len(criteria) > 1:
            raise ProjectError("Carve further works on a project with one criterion.", status_code=409)
        criterion_id = criteria[0].id if criteria else None
        found = read_stage_manifest(store.open(name) / RUN_FOLDER, "exporting", ExportingManifest)
        if found is None or stage_status(store, name)["exporting"] != "current":
            raise ProjectError("Build the envelope with the current settings before carving further: "
                               "the exported envelope is missing or out of date.", status_code=409)
        manifest, manifest_folder = found
        carved_with = store.read_project_json(name).stage_records["exporting"].config
        chain_step = store.replace_max_volume_with_envelope(
            name, resolve_stored_path(manifest_folder, manifest.mesh_path), canonical_mode_name(carved_with["mode"]), carved_with)
        try:
            store.write_config_from_values(name, {"mode": NEW_PROJECT_MODE}, criterion_id)
        except GridOverBudget:
            store.write_config_from_values(name, {"mode": NEW_PROJECT_MODE, "voxel_size": carved_with["voxel_size"]}, criterion_id)
        return chain_step
