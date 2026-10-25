"""Projects of an earlier version of the service made into a chain of one criterion, with their results kept current.

An earlier version kept one criterion: config.yaml held its settings in the flat form, its test surface files were joined in
``inputs/joined/test_surfaces.ply``, its runs wrote ``run/preprocessing`` and ``run/thresholding``, and project.json kept the
records of every stage in ``stage_records``. The migration makes that criterion "1": the run folders move to
``run/criteria/1/``, the joined file becomes criterion 1's, the manifests that name a moved run name its new place, and the
records move to ``criterion_records["1"]``, so each stage is as current as it was. A project carved further keeps its
``carving_chain`` and ``inputs/earlier_max_volumes/``; nothing but the files named here changes.

Files are only moved, never deleted, and every change is undone when a later one fails, so a project that cannot be migrated
stays as it was. project.json is written last: its criteria tell that the project is migrated.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..mode_registry import canonical_mode_name
from . import test_surfaces
from .api_models import ProjectJson, StageRecord
from .criteria import append_criterion, joined_test_surfaces_path, split_settings
from .project_names import ProjectError
from .projects import CONFIG_FILE_NAME, RUN_FOLDER, SETTINGS_LEFT_TO_THE_ENGINE, ProjectStore

EARLIER_JOINED_TEST_SURFACES = "inputs/joined/test_surfaces.ply"     # the joined test surfaces of an earlier version
CRITERION_ID = "1"
MOVED_STAGES = ("preprocessing", "thresholding")      # run once per criterion, so they move to run/criteria/1/
LEAF_STAGES = ("exporting", "massing")                # stay where they are; their manifests name the moved thresholding
MANIFEST_FILE_NAME = "manifest.json"
CHAIN_FILE = "criteria/chain.json"                    # as run_chain writes it, under the run folder


class _Undo:
    """The changes made so far, undone in reverse order when the migration fails."""

    def __init__(self):
        self._steps = []

    def add(self, step) -> None:
        self._steps.append(step)

    def run(self) -> list[str]:
        """Undo every change, newest first; the errors of the steps that could not be undone."""
        errors = []
        for step in reversed(self._steps):
            try:
                step()
            except OSError as error:
                errors.append(str(error))
        return errors


def is_earlier_version_project(project_json: ProjectJson, stored_config: dict | None) -> bool:
    """Whether a project is from an earlier version: no criterion was ever made, and config.yaml holds settings in the flat form."""
    return (not project_json.criteria and project_json.next_criterion_id == 1
            and stored_config is not None and "criteria" not in stored_config)


def migrate_to_criteria(store: ProjectStore, name: str) -> bool:
    """Make an earlier version's project a chain of one criterion (see the module docstring); whether it was one.

    Criterion "1" gets the criterion settings of config.yaml, the plain mode name, the first palette colour and every stored test
    surface file. Raises when a file cannot be moved or written (ProjectError when the new layout is in the way); the project is
    then as it was.
    """
    with store.project_lock(name):
        project_folder = store.open(name)
        project_json = store.read_project_json(name)
        config_path = project_folder / CONFIG_FILE_NAME
        stored_config = store._parse_config_file(config_path, name) if config_path.is_file() else None
        if not is_earlier_version_project(project_json, stored_config):
            return False
        _check_the_new_layout_is_free(project_folder)
        run_folder = project_folder / RUN_FOLDER
        settings = {key: value for key, value in store._without_service_owned(stored_config).items()
                    if key not in SETTINGS_LEFT_TO_THE_ENGINE}
        shared, criterion_settings = split_settings(settings)
        entry = append_criterion(project_json, criterion_settings)     # id "1", named after its mode, the first palette colour
        entry.test_surface_files = sorted(project_json.input_files.get(test_surfaces.ROLE, {}))
        undo = _Undo()
        try:
            _move_joined_test_surfaces(project_folder, entry.test_surface_files, undo)
            moved = _move_criterion_stages(run_folder, undo)
            _name_the_moved_runs(run_folder, moved, undo)
            _write_chain_file(run_folder, entry.name, criterion_settings.get("mode", ""), undo)
            _move_records(project_json, project_folder)
            if stored_config:   # a config.yaml that holds no settings (a hand edit with a YAML error) stays for the next save to replace
                config_text = store._chain_config_text(project_folder, project_json, shared)
                earlier_config = config_path.read_bytes()
                store._write_bytes_atomically(config_path, config_text.encode("utf-8"))
                undo.add(lambda: store._write_bytes_atomically(config_path, earlier_config))
            store.write_project_json(name, project_json)
        except BaseException as error:
            undo_errors = undo.run()
            if undo_errors:
                raise ProjectError(f"'{name}' could not be opened as a chain of one criterion ({error}), and some of its files could "
                                   f"not be put back: {'; '.join(undo_errors)}.", status_code=500) from error
            raise
        return True


def _check_the_new_layout_is_free(project_folder: Path) -> None:
    """ProjectError(409) when a file of the new layout exists already: the migration moves nothing over another file."""
    for relative_path in (joined_test_surfaces_path(CRITERION_ID), f"{RUN_FOLDER}/criteria"):
        if (project_folder / relative_path).exists():
            raise ProjectError(f"The project cannot be opened as a chain of one criterion: {relative_path} exists already.",
                               status_code=409)


def _move_joined_test_surfaces(project_folder: Path, file_names: list[str], undo: _Undo) -> None:
    """Make the earlier joined test surface file criterion 1's (the same bytes, which the earlier runs read), or build it from the
    stored files when it is missing."""
    earlier_path = project_folder / EARLIER_JOINED_TEST_SURFACES
    new_path = test_surfaces.joined_path(project_folder, CRITERION_ID)
    if earlier_path.is_file():
        _move(earlier_path, new_path, undo)
        return
    if not file_names:
        return
    joined_files = test_surfaces.build_joined_files(project_folder, {CRITERION_ID: file_names})
    try:
        test_surfaces.install_joined_files(project_folder, joined_files)
    finally:
        test_surfaces.remove_temporary_files(joined_files)
    undo.add(lambda: new_path.unlink(missing_ok=True))


def _move_criterion_stages(run_folder: Path, undo: _Undo) -> dict[Path, Path]:
    """Move run/preprocessing and run/thresholding, those that exist, to run/criteria/1/; the old folder -> the new folder."""
    moved = {}
    for stage in MOVED_STAGES:
        earlier_folder = run_folder / stage
        if earlier_folder.is_dir():
            new_folder = run_folder / "criteria" / CRITERION_ID / stage
            _make_folders(new_folder.parent, undo)
            _move(earlier_folder, new_folder, undo)
            moved[earlier_folder] = new_folder
    return moved


def _name_the_moved_runs(run_folder: Path, moved: dict[Path, Path], undo: _Undo) -> None:
    """Rewrite the upstream_manifest of the moved thresholding manifest, and of exporting's and massing's, to the place its run
    moved to, as the engine stores it (stored_path in api_core/_stage_io.py: relative to the manifest's folder with forward
    slashes, absolute when no relative path exists); the run ids stay."""
    earlier_folders = {new_folder: earlier_folder for earlier_folder, new_folder in moved.items()}
    manifest_folders = [new_folder for new_folder in moved.values() if new_folder.name == "thresholding"]
    manifest_folders += [run_folder / stage for stage in LEAF_STAGES]
    for folder in manifest_folders:
        manifest_path = folder / MANIFEST_FILE_NAME
        manifest = _read_manifest(manifest_path)
        if manifest is None or not isinstance(manifest.get("upstream_manifest"), str):
            continue    # no manifest, or one the engine refuses anyway: the stage is missing or out of date as before
        upstream = _resolved(earlier_folders.get(folder, folder), manifest["upstream_manifest"])
        new_upstream = _moved_path(upstream, moved)
        if new_upstream is None:
            continue
        stored = _stored_path(new_upstream, folder)
        if stored == manifest["upstream_manifest"]:
            continue
        earlier_bytes = manifest_path.read_bytes()
        _write_manifest(manifest_path, {**manifest, "upstream_manifest": stored})
        undo.add(lambda path=manifest_path, data=earlier_bytes: path.write_bytes(data))


def _write_chain_file(run_folder: Path, criterion_name: str, mode: str, undo: _Undo) -> None:
    """run/criteria/chain.json as run_chain writes it once the criteria are thresholded, when the moved thresholding has a run id."""
    thresholding = _read_manifest(run_folder / "criteria" / CRITERION_ID / "thresholding" / MANIFEST_FILE_NAME)
    if thresholding is None or not isinstance(thresholding.get("run_id"), str):
        return
    chain_path = run_folder / CHAIN_FILE
    listed = [{"id": CRITERION_ID, "name": criterion_name, "mode": canonical_mode_name(mode), "thresholding_run_id": thresholding["run_id"]}]
    chain_path.write_text(json.dumps({"criteria": listed}, indent=2), encoding="utf-8")
    undo.add(lambda: chain_path.unlink(missing_ok=True))


def _move_records(project_json: ProjectJson, project_folder: Path) -> None:
    """Move the records of preprocessing and thresholding to criterion 1, with the fingerprint of its joined test surface file, and
    give every record the joined file of criterion 1 as test_surface_path, so its settings compare as they did."""
    fingerprint = test_surfaces.fingerprint(project_folder, CRITERION_ID)
    for stage in MOVED_STAGES:
        record = project_json.stage_records.pop(stage, None)
        if record is not None:
            project_json.criterion_records.setdefault(CRITERION_ID, {})[stage] = _in_the_new_layout(record, fingerprint)
    for stage, record in list(project_json.stage_records.items()):
        project_json.stage_records[stage] = _in_the_new_layout(record, record.test_surfaces_fingerprint)


def _in_the_new_layout(record: StageRecord, fingerprint: str | None) -> StageRecord:
    config = dict(record.config)
    if "test_surface_path" in config:
        config["test_surface_path"] = joined_test_surfaces_path(CRITERION_ID)
    return record.model_copy(update={"config": config, "test_surfaces_fingerprint": fingerprint})


def _move(source: Path, target: Path, undo: _Undo) -> None:
    os.replace(source, target)
    undo.add(lambda: os.replace(target, source))


def _make_folders(folder: Path, undo: _Undo) -> None:
    """Make *folder* and its missing parents; undo removes those it made (they are empty again by then)."""
    missing = []
    while not folder.exists():
        missing.append(folder)
        folder = folder.parent
    for made in reversed(missing):
        made.mkdir()
        undo.add(made.rmdir)


def _read_manifest(manifest_path: Path) -> dict | None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def _write_manifest(manifest_path: Path, manifest: dict) -> None:
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _resolved(manifest_folder: Path, stored: str) -> Path:
    """The file a stored manifest path names, as the engine's LoadedManifest.resolve reads it."""
    path = Path(stored)
    return path if path.is_absolute() else Path(os.path.normpath(manifest_folder / path))


def _moved_path(path: Path, moved: dict[Path, Path]) -> Path | None:
    """Where *path* is now, when it was inside a moved folder (letter case ignored where the file system ignores it); None when it
    did not move."""
    for earlier_folder, new_folder in moved.items():
        try:
            relative = Path(os.path.normcase(path)).relative_to(os.path.normcase(earlier_folder))
        except ValueError:
            continue
        return new_folder.joinpath(*path.parts[len(path.parts) - len(relative.parts):])
    return None


def _stored_path(path: Path, manifest_folder: Path) -> str:
    """The text a manifest stores for *path*, as the engine's stored_path writes it (api_core/_stage_io.py; not imported, it pulls
    in torch)."""
    try:
        return Path(os.path.relpath(path, manifest_folder)).as_posix()
    except ValueError:
        return Path(os.path.abspath(path)).as_posix()
