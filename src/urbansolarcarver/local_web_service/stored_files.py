"""Input files changed in the project folder from outside the app: found, joined again and told.

The service stores each uploaded file in ``inputs/<role>/`` (the weather file as ``inputs/weather.epw``), and the engine reads the
joined files built from them (``inputs/joined/``). A file replaced in the folder by hand (an export saved over it) changes neither a
joined file nor anything a stage or a study is dated by, so the results built on the old file would stay current. project.json
keeps the size, modification time and content digest of each stored file (``stored_files``). refresh_changed_inputs compares the
folder with them: a file whose content changed builds again the joined files that use it, and a joined file that comes out
different replaces the old one, which dates every result built on it as an upload would. A notice of each such file stays in
project.json (``changed_files``) until the user dismisses it. A file with no record (a project made before the records) is checked
the same way once, by building its joined files and comparing them with those in place.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import trimesh

from . import test_surfaces
from .api_models import ChangedFileNotice, InputFileChange, ProjectJson, StoredFileRecord
from .project_names import ProjectError

# The words a message uses for a role.
ROLE_WORDS = {"max_volume": "maximum volume", "test_surfaces": "test surface", "context": "context", "terrain": "terrain", "weather": "weather"}


def file_record(path: Path) -> StoredFileRecord:
    """The size, modification time and content digest of a stored file."""
    status = path.stat()
    return StoredFileRecord(size=status.st_size, modified_ns=status.st_mtime_ns, digest=test_surfaces.content_digest(path))


def record_stored_file(project_json: ProjectJson, role: str, file_name: str, path: Path) -> None:
    """Keep the record of a file the service has just stored, so refresh_changed_inputs takes it as it is."""
    project_json.stored_files.setdefault(role, {})[file_name] = file_record(path)


def refresh_changed_inputs(store, name: str) -> bool:
    """Find the stored files of project *name* that changed in its folder and build them into the joined files; whether project.json changed.

    A file whose size and time are those recorded is taken as it is. Any other is read again: the same content only renews its
    record. Changed content (or no record) builds again the joined files that use the file: those of the criteria and studies
    that list a test surface file, the role's joined file for the maximum volume, context and terrain. A joined file that comes
    out different replaces the old one and the file gets a notice: a criterion or a study is then out of date by its joined
    file, and for the maximum volume, context and terrain inputs_revision rises. A weather file with changed content raises
    inputs_revision too; one without a record is taken as it is (nothing was built from it to compare). Triangle counts follow.

    A missing file is left to input_changes. A file that cannot be read (a broken export, or one still being copied or locked)
    keeps its old record, so it is tried again; the other roles go ahead and the first error is raised at the end as a
    ProjectError. project.json is written only when something in it changed.
    """
    from .projects import WEATHER_ROLE      # projects.py builds on this module
    with store.project_lock(name):
        project_folder = store.open(name)
        project_json = store.read_project_json(name)
        as_read = project_json.model_dump()
        first_error: ProjectError | None = None
        renewed: dict[tuple[str, str], StoredFileRecord] = {}
        suspects: dict[str, dict[str, tuple[StoredFileRecord | None, StoredFileRecord]]] = {}
        for role, file_names in project_json.input_files.items():
            for file_name in file_names:
                path = store._stored_file_path(project_folder, role, file_name)
                try:
                    status = path.stat()
                except OSError:
                    continue
                old_record = project_json.stored_files.get(role, {}).get(file_name)
                if old_record is not None and (old_record.size, old_record.modified_ns) == (status.st_size, status.st_mtime_ns):
                    continue
                try:
                    new_record = file_record(path)
                except OSError as error:
                    first_error = first_error or _not_read(role, file_name, error)
                    continue
                if old_record is not None and old_record.digest == new_record.digest:
                    renewed[(role, file_name)] = new_record
                else:
                    suspects.setdefault(role, {})[file_name] = (old_record, new_record)
        listed = {(role, file_name) for role, file_names in project_json.input_files.items() for file_name in file_names}
        unlisted = [(role, file_name) for role, records in project_json.stored_files.items() for file_name in records
                    if (role, file_name) not in listed]
        for role, file_name in unlisted:
            del project_json.stored_files[role][file_name]
        noticed: list[tuple[str, str]] = []
        for role, files in sorted(suspects.items()):
            try:
                if role == WEATHER_ROLE:
                    changed_names = [file_name for file_name, (old_record, _) in files.items() if old_record is not None]
                    if changed_names:
                        project_json.inputs_revision += 1
                elif role == test_surfaces.ROLE:
                    changed_names = _join_test_surfaces_again(project_folder, project_json, sorted(files))
                else:
                    changed_names = _join_mesh_role_again(store, name, project_folder, project_json, role, sorted(files))
            except (ProjectError, OSError) as error:
                first_error = first_error or (error if isinstance(error, ProjectError) else _not_read(role, ", ".join(sorted(files)), error))
                continue
            for file_name, (_, new_record) in files.items():
                renewed[(role, file_name)] = new_record
            noticed.extend((role, file_name) for file_name in changed_names)
        for (role, file_name), new_record in renewed.items():
            project_json.stored_files.setdefault(role, {})[file_name] = new_record
        noticed_on = datetime.now(timezone.utc).isoformat(timespec="seconds")
        project_json.changed_files = [notice for notice in project_json.changed_files if (notice.role, notice.file_name) not in noticed]
        project_json.changed_files.extend(ChangedFileNotice(role=role, file_name=file_name, noticed=noticed_on) for role, file_name in noticed)
        changed = project_json.model_dump() != as_read
        if changed:
            store.write_project_json(name, project_json)
        if first_error is not None:
            raise first_error
        return changed


def _not_read(role: str, file_names: str, error: OSError) -> ProjectError:
    """The error of a stored file that could not be read or built in (a file being copied or locked), tried again on the next look."""
    return ProjectError(f"The {ROLE_WORDS.get(role, role)} file '{file_names}' in the project folder could not be read: {error}", status_code=422)


def _join_test_surfaces_again(project_folder: Path, project_json: ProjectJson, file_names: list[str]) -> list[str]:
    """Build again the joined files of the criteria and studies that list any of *file_names*; the names of those files listed by a
    joined file that came out different (only those joined files are replaced)."""
    meshes = test_surfaces.load_stored_meshes(project_folder, file_names)
    for file_name, mesh in meshes.items():
        project_json.input_files[test_surfaces.ROLE][file_name] = len(mesh.faces)
    users = {criterion.id: criterion.test_surface_files for criterion in project_json.criteria}
    users.update({test_surfaces.study_key(study.id): study.test_surface_files for study in project_json.studies})
    file_names_by_key = {key: names for key, names in users.items() if set(names) & set(file_names)}
    joined_files = test_surfaces.build_joined_files(project_folder, file_names_by_key, meshes)
    try:
        different = {key: path for key, path in joined_files.items()
                     if not _same_joined_content(path, test_surfaces.joined_path_of_key(project_folder, key))}
        test_surfaces.install_joined_files(project_folder, different)
    finally:
        test_surfaces.remove_temporary_files(joined_files)
    return sorted({file_name for key in different for file_name in file_names_by_key[key] if file_name in file_names})


def _join_mesh_role_again(store, name: str, project_folder: Path, project_json: ProjectJson, role: str, file_names: list[str]) -> list[str]:
    """Build again the joined file of a maximum volume, context or terrain role; *file_names* when it came out different, else none.

    A different one replaces the old one only once project.json holds the raised inputs_revision: the stages are dated by the
    revision, not by the joined file, so a failure after the replacement must not leave them current on the new file. The
    records are written later; until then the next look builds the file again and finds it in place.
    """
    from .projects import JOINED_FOLDER, OPTIONAL_MESH_ROLES
    meshes = store._load_stored_meshes(project_folder, role, list(project_json.input_files[role]))
    for file_name in file_names:
        project_json.input_files[role][file_name] = len(meshes[file_name].faces)
    joined_temporary_path = store._write_joined_temporary_file(project_folder, role, [meshes[file_name] for file_name in sorted(meshes)])
    try:
        # Nothing reads the orientation of the context and terrain, and an earlier version turned their faces when it joined them.
        if _same_joined_content(joined_temporary_path, project_folder / JOINED_FOLDER / f"{role}.ply", ignore_winding=role in OPTIONAL_MESH_ROLES):
            return []
        project_json.inputs_revision += 1
        store.write_project_json(name, project_json)
        store._replace_joined_file(project_folder, role, joined_temporary_path)
    finally:
        if joined_temporary_path is not None:
            joined_temporary_path.unlink(missing_ok=True)
    return file_names


def _same_joined_content(new_path: Path | None, old_path: Path, ignore_winding: bool = False) -> bool:
    """Whether a joined file built now holds what the one in place holds: the same bytes, or the same faces and vertices (an
    earlier version of the service may have laid the same mesh out otherwise); with *ignore_winding*, a face turned the other
    way is the same face. None is a joined file to be removed."""
    if new_path is None:
        return not old_path.is_file()
    if not old_path.is_file():
        return False
    if os.path.getsize(new_path) == os.path.getsize(old_path) and test_surfaces.content_digest(new_path) == test_surfaces.content_digest(old_path):
        return True
    try:
        new_mesh, old_mesh = (trimesh.load(str(path), force="mesh", process=False) for path in (new_path, old_path))
    except Exception:       # trimesh fails with ValueError, KeyError or others, by what is wrong with the file
        return False
    new_faces, old_faces = ((np.sort(mesh.faces, axis=1) if ignore_winding else mesh.faces) for mesh in (new_mesh, old_mesh))
    return (new_mesh.vertices.shape == old_mesh.vertices.shape and new_faces.shape == old_faces.shape
            and np.array_equal(new_faces, old_faces) and np.allclose(new_mesh.vertices, old_mesh.vertices, rtol=0, atol=1e-9))


def input_changes(store, name: str) -> list[InputFileChange]:
    """The notices of files changed in the folder, by role and name, then the stored files missing from it, by role and name."""
    project_folder = store.open(name)
    project_json = store.read_project_json(name)
    changed = sorted((notice for notice in project_json.changed_files if notice.file_name in project_json.input_files.get(notice.role, {})),
                     key=lambda notice: (notice.role, notice.file_name))
    return [*(InputFileChange(role=notice.role, file_name=notice.file_name, state="changed", noticed=notice.noticed) for notice in changed),
            *(InputFileChange(role=role, file_name=file_name, state="missing") for role, file_name in missing_files(store, project_folder, project_json))]


def missing_files(store, project_folder: Path, project_json: ProjectJson) -> list[tuple[str, str]]:
    """The recorded input files that are not in the project folder, by role and name."""
    return sorted((role, file_name) for role, file_names in project_json.input_files.items() for file_name in file_names
                  if not store._stored_file_path(project_folder, role, file_name).is_file())


def refuse_missing_files(store, name: str, job: str) -> None:
    """ProjectError(422) naming the recorded input files missing from the project folder that a *job* ("run": the criteria that are
    on; "simulation": the studies) reads, so it does not go on with old joined files. A test surface file counts when one of them
    lists it; a file of another role always does."""
    project_json = store.read_project_json(name)
    if job == "run":
        listed = {file_name for criterion in project_json.criteria if not criterion.bypassed for file_name in criterion.test_surface_files}
    else:
        listed = {file_name for study in project_json.studies for file_name in study.test_surface_files}
    missing = [(role, file_name) for role, file_name in missing_files(store, store.open(name), project_json)
               if role != test_surfaces.ROLE or file_name in listed]
    if missing:
        listed = ", ".join(f"the {ROLE_WORDS.get(role, role)} file '{file_name}'" for role, file_name in missing)
        raise ProjectError(f"Missing from the project folder: {listed}. Put it back, or remove it from the project.", status_code=422)


def dismiss_changes(store, name: str) -> None:
    """Forget the notices of files changed in the folder (the user has read them)."""
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        if project_json.changed_files:
            project_json.changed_files = []
            store.write_project_json(name, project_json)
