"""Project folders of the local web service: names, layout and project.json.

A project is a folder under the projects folder, named by the user. The
service never takes a path from the browser, so every folder is derived from
a validated name and checked to be a direct child of the projects folder.
"""
from __future__ import annotations

import contextlib
import os
import re
import shutil
import tempfile
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import trimesh
import yaml
from pydantic import ValidationError

from ..cold_period import cold_period_from_weather_file
from ..errors import ConfigError, InputError
from ..grid_planning import MAX_GRID_VOXELS, VoxelGridPlan, check_voxel_grid_budget, plan_voxel_grid
from ..io import load_mesh, save_mesh
from ..load_config import build_config, build_config_from_mode_starting_values
from ..mode_registry import MODES, canonical_mode_name
from ..pydantic_schemas import UserConfig
from .api_models import ColdPeriodDates, ColdPeriodReply, ConfigReply, ExampleProject, GridPlanReply, InputFileInfo, InputFilesReply, ProjectJson, ProjectSummary
from .example_catalog import read_examples
from .project_names import PROJECT_JSON_FILE_NAME, ProjectError, check_not_a_windows_device_name, validate_project_name
from .project_removal import ProjectRemovalRefused, check_project_folder_can_be_removed, move_to_recycle_bin

CONFIG_FILE_NAME = "config.yaml"
INPUT_ROLE_FOLDERS = ("inputs/max_volume", "inputs/test_surfaces", "inputs/joined")
RUN_FOLDER = "run"
MESH_ROLES = ("max_volume", "test_surfaces")
WEATHER_ROLE = "weather"
MESH_EXTENSIONS = (".ply", ".obj", ".stl", ".glb")
WEATHER_EXTENSION = ".epw"
WEATHER_FILE_NAME = "weather.epw"
INPUTS_FOLDER = "inputs"
JOINED_FOLDER = "inputs/joined"
# Settings the service decides, whatever the browser sends: every file location (the service takes no path from
# the browser; simulated_weights_path is never set) and the compute device.
SERVICE_OWNED_SETTINGS = ("max_volume_path", "test_surface_path", "epw_path", "out_dir", "device", "simulated_weights_path")
# Settings the browser does not set, left to the engine's own value: the sample spacing on the test surfaces (half the voxel
# size). One stored by an earlier version, or sent by an older page, is left out when the settings are read and written.
SETTINGS_LEFT_TO_THE_ENGINE = ("grid_step",)
SERVICE_PATHS = {
    "max_volume_path": "inputs/joined/max_volume.ply",
    "test_surface_path": "inputs/joined/test_surfaces.ply",
    "epw_path": "inputs/weather.epw",
    "out_dir": "run",
}   # relative to the project folder; epw_path only for modes that read a weather file
UNWANTED_FILE_NAME_CHARACTERS = re.compile(r"[^A-Za-z0-9_.-]")
FILE_NAME_SEPARATORS = re.compile(r"[\\/]")


class GridOverBudget(ConfigError):
    """The voxel grid of the max volume and voxel size has more voxels than preprocessing can score.

    ``grid_plan`` is the rejected plan, so the app can name the smallest voxel size that fits.
    """

    def __init__(self, message: str, errors, grid_plan: GridPlanReply):
        super().__init__(message, errors)
        self.grid_plan = grid_plan


def is_from_example(project_json: ProjectJson, example: str, example_title: str) -> bool:
    """Whether a project was made from the example named *example* (titled *example_title*).

    project.json records the example, so a renamed project is still found. A project made before the field existed counts
    when its name is exactly the example's title; numbered copies ("Perimeter block 2") stay ordinary projects.
    """
    if project_json.example is None:
        return project_json.name == example_title
    return project_json.example == example


def example_of_project(project_json: ProjectJson) -> ExampleProject | None:
    """The packaged example a project was made from (see is_from_example), None for any other project."""
    return next((example for example in read_examples() if is_from_example(project_json, example.name, example.title)), None)


def sanitize_file_name(name: str) -> str:
    """The last part of an uploaded file name with only letters, digits, '-', '_' and '.' kept.

    Raises ProjectError(422) when nothing usable is left, the name would be hidden (starts with '.') or it is a
    Windows device name (CON, NUL, COM1, ...), also with an extension.
    """
    last_part = FILE_NAME_SEPARATORS.split(name)[-1]
    clean_name = UNWANTED_FILE_NAME_CHARACTERS.sub("", last_part)
    if not clean_name or clean_name.startswith("."):
        raise ProjectError(f"'{name}' has no usable file name: use letters, digits, '-', '_' and '.'.", status_code=422)
    check_not_a_windows_device_name(clean_name)
    return clean_name


def _utc_iso(timestamp_seconds: float) -> str:
    return datetime.fromtimestamp(timestamp_seconds, timezone.utc).isoformat(timespec="seconds")


def _write_ply_with_vertex_normals(meshes: list[trimesh.Trimesh], path: Path) -> None:
    """Write the meshes, concatenated, as one binary PLY with float64 positions and the vertex normals of each mesh.

    The engine reads test surfaces with load_mesh, which merges coincident vertices only when their normals are
    equal too (trimesh merges on position and, when the file has them, vertex normals). Test surface files keep
    panels that share corners apart that way, and each panel is one connected component for the sampling. The
    normals of a mesh as load_mesh returned it are those of its faces, so a vertex of one flat panel carries the
    panel's normal, and panels that met at a corner in the uploaded file stay apart in the joined file. Without
    normals they would merge into one component, which the sampling skips as degenerate or non-planar. Positions
    are float64, as save_mesh writes georeferenced coordinates.
    """
    vertex_offsets = np.cumsum([0] + [len(mesh.vertices) for mesh in meshes[:-1]])
    vertex_rows = np.empty(sum(len(mesh.vertices) for mesh in meshes), dtype=[("position", "<f8", (3,)), ("normal", "<f4", (3,))])
    vertex_rows["position"] = np.vstack([mesh.vertices for mesh in meshes])
    vertex_rows["normal"] = np.vstack([mesh.vertex_normals for mesh in meshes])
    face_rows = np.empty(sum(len(mesh.faces) for mesh in meshes), dtype=[("count", "u1"), ("vertex_indices", "<i4", (3,))])
    face_rows["count"] = 3
    face_rows["vertex_indices"] = np.vstack([mesh.faces + offset for mesh, offset in zip(meshes, vertex_offsets)])
    header = ("ply\nformat binary_little_endian 1.0\n"
              f"element vertex {len(vertex_rows)}\n"
              "property double x\nproperty double y\nproperty double z\n"
              "property float nx\nproperty float ny\nproperty float nz\n"
              f"element face {len(face_rows)}\n"
              "property list uchar int vertex_indices\nend_header\n")
    with open(path, "wb") as ply_file:
        ply_file.write(header.encode("ascii"))
        ply_file.write(vertex_rows.tobytes())
        ply_file.write(face_rows.tobytes())


def _ply_has_vertex_normals(path: Path) -> bool:
    """Whether the header of a PLY file declares the vertex property nx (a PLY header is ASCII in every format)."""
    with open(path, "rb") as ply_file:
        for line in ply_file:
            words = line.split()
            if words == [b"end_header"]:
                return False
            if words[:1] == [b"property"] and words[-1:] == [b"nx"]:
                return True
    return False


class ProjectStore:
    """The projects under one projects folder."""

    def __init__(self, projects_folder: Path, device: str = "auto"):
        self._projects_folder = Path(projects_folder)
        self._device = device
        self._project_locks: dict[str, threading.RLock] = {}
        self._project_locks_guard = threading.Lock()

    @property
    def projects_folder(self) -> Path:
        return self._projects_folder

    def project_lock(self, name: str) -> threading.RLock:
        """The lock that serializes changes to one project.

        The HTTP layer runs requests in a thread pool, so two requests can change the same project
        at once. Every read-modify-write of project.json (and the files it describes) holds this
        lock; it is re-entrant, so a caller may hold it around several store calls.
        """
        lock_key = validate_project_name(name).lower()   # Windows folder names ignore letter case
        with self._project_locks_guard:
            return self._project_locks.setdefault(lock_key, threading.RLock())

    @contextlib.contextmanager
    def project_locks(self, *names: str):
        """Hold the locks of several projects at once, taken in one order (by lower-case name, each once).

        A request that needs two projects (a rename needs the old and the new name) must take them through this, so that
        two requests that name the same projects in opposite order cannot each hold one lock and wait for the other.
        """
        with contextlib.ExitStack() as held_locks:
            for lock_key in sorted({validate_project_name(name).lower() for name in names}):
                held_locks.enter_context(self.project_lock(lock_key))
            yield

    def _project_folder(self, name: str) -> Path:
        """The folder of a project with a valid name, guaranteed to lie directly in the projects folder."""
        project_folder = (self._projects_folder / validate_project_name(name)).resolve()
        if project_folder.parent != self._projects_folder.resolve():
            raise ProjectError("The project name does not name a folder of the projects folder.", status_code=422)
        return project_folder

    def create(self, name: str, mode: str, example: str | None = None) -> Path:
        """Make the project folder with its layout, project.json (recording the *example* it comes from) and the first config.yaml of the mode.

        Raises ConfigError, and leaves no folder behind, when the mode is not one the engine knows.
        """
        project_name = validate_project_name(name)
        project_folder = self._project_folder(project_name)
        try:
            project_folder.mkdir(parents=True)
        except FileExistsError:
            raise ProjectError(f"A project named '{project_name}' already exists.", status_code=409) from None
        for sub_folder in (*INPUT_ROLE_FOLDERS, RUN_FOLDER):
            (project_folder / sub_folder).mkdir(parents=True)
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.write_project_json(project_name, ProjectJson(name=project_name, created=created, example=example))
        try:
            self.write_config_from_values(project_name, {"mode": mode})
        except BaseException:
            shutil.rmtree(project_folder, ignore_errors=True)   # the folder was made by this call, so no earlier project is lost
            raise
        return project_folder

    def open(self, name: str) -> Path:
        """The folder of an existing project."""
        project_folder = self._project_folder(name)
        if not (project_folder / PROJECT_JSON_FILE_NAME).is_file():
            raise ProjectError(f"There is no project named '{name.strip(' ')}'.", status_code=404)
        return project_folder

    def list(self) -> list[ProjectSummary]:
        """The projects sorted by name.

        A folder is skipped, not reported as an error, when it is not a project this service
        could have made: no project.json, a name the service would not accept, or a project.json
        or config.yaml that cannot be read. One bad folder must not hide the other projects.
        A config.yaml with a YAML syntax error is read as holding no settings, so its project is listed without a mode.
        """
        if not self._projects_folder.is_dir():
            return []
        summaries = []
        for project_folder in sorted(self._projects_folder.iterdir(), key=lambda folder: folder.name):
            if not (project_folder / PROJECT_JSON_FILE_NAME).is_file():
                continue
            try:
                summaries.append(self.summary(project_folder.name))
            except ProjectError:
                continue
        return summaries

    def summary(self, name: str) -> ProjectSummary:
        """The list row of one existing project."""
        with self.project_lock(name):   # config.yaml is read here too, and a save replaces it
            project_json = self.read_project_json(name)
            project_folder = self.open(name)
            example = example_of_project(project_json)
            return ProjectSummary(
                name=project_json.name,
                created=project_json.created,
                modified=self._modified(project_folder),
                mode=self._mode(project_folder),
                example=example.name if example is not None else None,
            )

    def create_example_project(self, name: str, example: ExampleProject, example_files: list[tuple[str, str, bytes]]) -> Path:
        """Make the project *name* with the mode and the input files (role, file name, content) of *example*, and record the example.

        The project is complete before another request can reach it. A folder made by this call is removed again when it fails.
        """
        with self.project_lock(name):
            project_folder = self.create(name, example.mode, example.name)
            try:
                for role, file_name, data in example_files:
                    self.add_input(name, role, file_name, data)
            except BaseException:
                shutil.rmtree(project_folder, ignore_errors=True)   # the folder was made by this call, so no earlier project is lost
                raise
            return project_folder

    def rename_project(self, name: str, new_name: str) -> Path:
        """Rename the project folder and the name in its project.json; the new folder.

        ProjectError: 422 for a bad new name, 404 for an unknown project, 409 when a project (or any folder) already has the
        new name, also in another letter case (folder names ignore it on Windows), with its own message when the new name
        differs from the old one only in letter case, and 422 when the folder cannot be moved (a program has a file of it
        open). Nothing changes then.

        A project made before project.json recorded the example counts as from an example only while its name is the
        example's title (see is_from_example), so the example is recorded with the new name and the link survives the rename.
        """
        old_name, new_name = validate_project_name(name), validate_project_name(new_name)
        with self.project_locks(old_name, new_name):
            old_folder = self.open(old_name)
            if new_name != old_name and new_name.lower() == old_name.lower():
                raise ProjectError(f"'{new_name}' differs from '{old_name}' only in letter case. Names that differ only in letter case "
                                   "are the same project, so choose a name that differs in more than letter case.", status_code=409)
            if any(folder.name.lower() == new_name.lower() for folder in self._projects_folder.iterdir()):
                raise ProjectError(f"A project named '{new_name}' already exists (project names ignore letter case).", status_code=409)
            project_json = self.read_project_json(old_name)
            if project_json.example is None:
                example = example_of_project(project_json)
                project_json.example = example.name if example is not None else None
            new_folder = self._project_folder(new_name)
            try:
                os.replace(old_folder, new_folder)
            except OSError as error:
                raise ProjectError(f"'{old_name}' cannot be renamed: {error}. Close any program that has one of its files open.", status_code=422) from error
            project_json.name = new_name
            try:
                self.write_project_json(new_name, project_json)
            except BaseException as error:
                try:
                    os.replace(new_folder, old_folder)
                except OSError as rollback_error:
                    raise ProjectError(f"'{old_name}' was renamed to '{new_name}', but its {PROJECT_JSON_FILE_NAME} could not be updated ({error}) "
                                       f"and the folder could not be moved back ({rollback_error}). The folder is now {new_folder}.",
                                       status_code=500) from error
                raise
            return new_folder

    def delete_project(self, name: str) -> None:
        """Move the project folder to the recycle bin when the guardrails of project_removal allow it; ProjectError otherwise, and nothing changes.

        The caller makes sure no run of the project is active.
        """
        with self.project_lock(name):
            move_to_recycle_bin(check_project_folder_can_be_removed(self._projects_folder, name))

    def reset_project_to_example(self, name: str, example: ExampleProject, example_files: list[tuple[str, str, bytes]]) -> None:
        """Replace a project made from *example* by a fresh copy of it under the same name; the old folder goes to the recycle bin.

        ProjectError 422 when the project is not from *example* or the guardrails refuse (see delete_project); nothing changes then.
        When the move succeeds but the new project cannot be made, the error (500) says the old content is in the recycle bin.
        """
        with self.project_lock(name):
            project_json = self.read_project_json(name)
            project_name = project_json.name
            if project_name.lower() != validate_project_name(name).lower():
                # a hand-edited project.json: removing and making "project_name" would take the lock of a second project
                raise ProjectRemovalRefused(f"{PROJECT_JSON_FILE_NAME} in the folder '{name}' names the project '{project_name}', so it is left as it is.")
            if not is_from_example(project_json, example.name, example.title):
                raise ProjectError(f"'{project_name}' was not made from the example '{example.title}', so it cannot be reset to it.", status_code=422)
            self.delete_project(project_name)
            try:
                self.create_example_project(project_name, example, example_files)
            except Exception as error:
                raise ProjectError(f"'{project_name}' could not be made again from the example ({error}). Its old content is in the recycle bin.",
                                   status_code=500) from error

    def projects_of_examples(self, example_titles: dict[str, str]) -> dict[str, str | None]:
        """For each example (name -> title) the project made from it (see is_from_example), in one pass over the projects.

        When several projects come from one example the most recently modified one is named; None when there is none.
        """
        newest_by_example: dict[str, ProjectSummary] = {}
        for summary in self.list():
            try:
                project_json = self.read_project_json(summary.name)
            except ProjectError:
                continue
            for example, example_title in example_titles.items():
                newest = newest_by_example.get(example)
                if is_from_example(project_json, example, example_title) and (newest is None or summary.modified > newest.modified):
                    newest_by_example[example] = summary
        return {example: newest_by_example[example].name if example in newest_by_example else None for example in example_titles}

    def project_of_example(self, example: str, example_title: str) -> str | None:
        """The name of the project made from one example (see projects_of_examples), None when there is none."""
        return self.projects_of_examples({example: example_title})[example]

    def read_project_json(self, name: str) -> ProjectJson:
        """project.json of a project, read under the project lock.

        On Windows a file that is open cannot be replaced, so a read without the lock can make a concurrent
        write_project_json fail with PermissionError (for example the record a finished run writes).
        """
        with self.project_lock(name):
            project_json_path = self.open(name) / PROJECT_JSON_FILE_NAME
            try:
                return ProjectJson.model_validate_json(project_json_path.read_text(encoding="utf-8"))
            except (ValidationError, OSError, UnicodeDecodeError) as error:
                raise ProjectError(f"{PROJECT_JSON_FILE_NAME} of '{name}' cannot be read: {error}", status_code=422) from error

    def write_project_json(self, name: str, data: ProjectJson) -> None:
        """Write project.json through a temporary file in the same folder, so a reader never sees a partial file."""
        project_folder = self._project_folder(name)
        descriptor, temporary_path = tempfile.mkstemp(dir=project_folder, prefix=PROJECT_JSON_FILE_NAME, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
                temporary_file.write(data.model_dump_json(indent=1))
            os.replace(temporary_path, project_folder / PROJECT_JSON_FILE_NAME)
        except BaseException:
            Path(temporary_path).unlink(missing_ok=True)
            raise

    def write_config_from_values(self, name: str, values: dict) -> ConfigReply:
        """Validate settings from the browser on top of the starting values of their mode and store them as config.yaml.

        The paths and the device are the service's: any the browser sends are dropped and the
        project's own are put in. When the joined max volume exists, the voxel grid it and the
        voxel size give is planned, and a grid over the engine's budget raises GridOverBudget.
        Nothing is stored unless the settings are valid. ConfigError propagates.
        """
        with self.project_lock(name):
            project_folder = self.open(name)
            browser_values = {key: value for key, value in values.items()
                              if key not in SERVICE_OWNED_SETTINGS and key not in SETTINGS_LEFT_TO_THE_ENGINE}
            service_paths = self._service_paths_for_mode(values.get("mode"))
            config = build_config_from_mode_starting_values(
                {**browser_values, **service_paths, "device": self._device}, base_folder=project_folder)
            grid_plan = self._plan_and_check_grid(name, config)
            # Only the settings that were given: the engine warns when a config file sets a setting the mode does not
            # use, and loading it back sets exactly the stored ones, so a full dump would warn at every load.
            stored_config = {**config.model_dump(mode="json", exclude_unset=True), **service_paths}
            self._write_bytes_atomically(
                project_folder / CONFIG_FILE_NAME, yaml.safe_dump(stored_config, sort_keys=False).encode("utf-8"))
            return ConfigReply(settings=self._without_service_owned(stored_config), grid_plan=grid_plan)

    def read_stored_config(self, name: str) -> dict:
        """The content of config.yaml as stored, service paths and device included (see _parse_config_file), without the
        settings left to the engine (SETTINGS_LEFT_TO_THE_ENGINE): the next save writes the file without them."""
        with self.project_lock(name):
            stored_config = self._parse_config_file(self.open(name) / CONFIG_FILE_NAME, name)
            return {key: value for key, value in stored_config.items() if key not in SETTINGS_LEFT_TO_THE_ENGINE}

    def read_settings(self, name: str) -> dict:
        """The stored settings of a project without the paths and device the service owns."""
        return self._without_service_owned(self.read_stored_config(name))

    def config_from_settings(self, name: str, settings: dict) -> UserConfig:
        """The engine's validated config for a stored settings dict, with its paths resolved inside the project folder.

        Raises ConfigError when the settings are not valid.
        """
        return build_config(settings, base_folder=self.open(name))

    def load_project_config(self, name: str) -> UserConfig:
        """The stored config.yaml as the engine's validated config, with its paths resolved inside the project folder."""
        return self.config_from_settings(name, self.read_stored_config(name))

    def stored_grid_plan(self, name: str) -> GridPlanReply | None:
        """The grid the stored settings and the joined max volume give, None before a max volume exists.

        Planned as a save plans it, without writing anything; a grid over the budget is returned as it is (a larger
        max volume uploaded after the settings were saved can give one), so the app can say so when the project opens.
        None as well when the stored settings do not validate (a hand-edited config.yaml): the project still opens,
        and the next save reports the field.
        """
        bounds = self.joined_bounds(name)
        if bounds is None:
            return None
        try:
            config = self.load_project_config(name)
        except ConfigError:
            return None
        return self._grid_plan_reply(plan_voxel_grid(bounds, config.voxel_size, config.margin_frac))

    def _plan_and_check_grid(self, name: str, config: UserConfig) -> GridPlanReply | None:
        """The grid plan of the joined max volume, None before one exists; GridOverBudget when it is too large."""
        bounds = self.joined_bounds(name)
        if bounds is None:
            return None
        plan = plan_voxel_grid(bounds, config.voxel_size, config.margin_frac)
        plan_reply = self._grid_plan_reply(plan)
        try:
            check_voxel_grid_budget(plan)
        except ConfigError as error:
            raise GridOverBudget(str(error), error.errors, plan_reply) from error
        return plan_reply

    @staticmethod
    def _service_paths_for_mode(mode) -> dict:
        """SERVICE_PATHS, without the weather file for a mode that does not read one (the engine warns about an unused epw_path)."""
        mode_settings = MODES.get(canonical_mode_name(mode))
        if mode_settings is not None and not mode_settings.needs_epw:
            return {key: path for key, path in SERVICE_PATHS.items() if key != "epw_path"}
        return dict(SERVICE_PATHS)

    @staticmethod
    def _grid_plan_reply(plan: VoxelGridPlan) -> GridPlanReply:
        return GridPlanReply(resolution=plan.resolution, voxel_size=plan.voxel_size, total_voxels=plan.total_voxels,
                             extent=plan.extent, budget_voxels=MAX_GRID_VOXELS)

    @staticmethod
    def _without_service_owned(stored_config: dict) -> dict:
        return {key: value for key, value in stored_config.items() if key not in SERVICE_OWNED_SETTINGS}

    def add_input(self, name: str, role: str, file_name: str, data: bytes) -> InputFilesReply:
        """Store an uploaded file for a role and rebuild the joined file of a mesh role.

        A mesh is checked with the engine's own loader and a weather file is read as an EPW with Ladybug's reader
        before it is kept, so a file the run would refuse is refused at upload. A file with the name of an earlier upload
        replaces it, also when the names differ only in letter case (one name, one file on Windows).
        Nothing on disk or in project.json changes unless the whole upload, joined file included, succeeds.
        """
        self._check_role(role)
        clean_name = sanitize_file_name(file_name)
        extension = Path(clean_name).suffix.lower()
        with self.project_lock(name):
            project_json = self.read_project_json(name)
            project_folder = self.open(name)
            if role == WEATHER_ROLE:
                if extension != WEATHER_EXTENSION:
                    raise ProjectError(f"The weather file must be an {WEATHER_EXTENSION} file.", status_code=422)
                self._store_weather_file(project_folder, clean_name, data)
                project_json.input_files[role] = {WEATHER_FILE_NAME: 0}
            else:
                if extension not in MESH_EXTENSIONS:
                    raise ProjectError(f"A mesh file must be one of {', '.join(MESH_EXTENSIONS)}.", status_code=422)
                self._add_mesh_file(project_folder, project_json, role, clean_name, data)
            project_json.inputs_revision += 1
            self.write_project_json(name, project_json)
            return self._reply(name, role, project_json)

    def remove_input(self, name: str, role: str, file_name: str) -> InputFilesReply:
        """Delete an uploaded file and rebuild the joined file of a mesh role; 404 when the file is not there.

        Nothing is deleted unless the joined file of the remaining files could be built.
        """
        self._check_role(role)
        with self.project_lock(name):
            project_json = self.read_project_json(name)
            project_folder = self.open(name)
            if file_name not in project_json.input_files.get(role, {}):
                raise ProjectError(f"There is no {role} file named '{file_name}'.", status_code=404)
            remaining_names = [other for other in project_json.input_files[role] if other != file_name]
            joined_temporary_path = None
            try:
                if role != WEATHER_ROLE:
                    joined_temporary_path = self._write_joined_temporary_file(
                        project_folder, role, list(self._load_stored_meshes(project_folder, role, remaining_names).values()))
                self._stored_file_path(project_folder, role, file_name).unlink(missing_ok=True)
                if role != WEATHER_ROLE:
                    self._replace_joined_file(project_folder, role, joined_temporary_path)
            finally:
                if joined_temporary_path is not None:
                    joined_temporary_path.unlink(missing_ok=True)
            del project_json.input_files[role][file_name]
            project_json.inputs_revision += 1
            self.write_project_json(name, project_json)
            return self._reply(name, role, project_json)

    def rebuild_joined_test_surfaces_without_normals(self, name: str) -> bool:
        """Rebuild the joined test surface file when it has no vertex normals and raise inputs_revision; whether it did.

        The service wrote that file with positions only before it kept the vertex normals, so the engine welded
        panels that share corners (see _write_ply_with_vertex_normals). Rebuilt from the uploaded files, with
        inputs_revision raised, every stage built on the old file is out of date. Called when a project is opened
        and when a run starts; raises ProjectError when an uploaded file cannot be read.
        """
        with self.project_lock(name):
            project_folder = self.open(name)
            joined_path = project_folder / JOINED_FOLDER / "test_surfaces.ply"
            if not joined_path.is_file() or _ply_has_vertex_normals(joined_path):
                return False
            project_json = self.read_project_json(name)
            file_names = list(project_json.input_files.get("test_surfaces", {}))
            joined_temporary_path = self._write_joined_temporary_file(
                project_folder, "test_surfaces", list(self._load_stored_meshes(project_folder, "test_surfaces", file_names).values()))
            try:
                self._replace_joined_file(project_folder, "test_surfaces", joined_temporary_path)
            finally:
                if joined_temporary_path is not None:
                    joined_temporary_path.unlink(missing_ok=True)
            project_json.inputs_revision += 1
            self.write_project_json(name, project_json)
            return True

    def input_files(self, name: str, role: str) -> list[InputFileInfo]:
        """The uploaded files of a role sorted by name, with their triangle counts."""
        self._check_role(role)
        return self._file_infos(self.read_project_json(name), role)

    def input_file_path(self, name: str, role: str, file_name: str) -> Path:
        """The stored file of an upload; 404 when no such upload is recorded."""
        self._check_role(role)
        if file_name not in self.read_project_json(name).input_files.get(role, {}):
            raise ProjectError(f"There is no {role} file named '{file_name}'.", status_code=404)
        return self._stored_file_path(self.open(name), role, file_name)

    def joined_bounds(self, name: str) -> list[list[float]] | None:
        """[[xmin, ymin, zmin], [xmax, ymax, zmax]] of the joined max volume, None before any is uploaded.

        Read with trimesh's own loader, which keeps the vertices load_mesh keeps: load_mesh then only reorders
        faces (fix_normals), which takes about 80 times longer than the read and does not move the bounds.
        """
        joined_path = self.open(name) / JOINED_FOLDER / "max_volume.ply"
        if not joined_path.is_file():
            return None
        return trimesh.load(str(joined_path), force="mesh").bounds.tolist()

    def weather_file_path(self, name: str) -> Path | None:
        """The project's weather file; None when none was added."""
        weather_path = self.open(name) / INPUTS_FOLDER / WEATHER_FILE_NAME
        return weather_path if weather_path.is_file() else None

    def cold_period(self, name: str, base_temperature: float) -> ColdPeriodReply:
        """The cold period of the project's weather file for *base_temperature* (cold_period.py)."""
        weather_path = self.weather_file_path(name)
        if weather_path is None:
            return ColdPeriodReply(status="no_weather_file")
        try:
            period = cold_period_from_weather_file(str(weather_path), base_temperature)
        except Exception as error:      # Ladybug's reader fails with AssertionError, IndexError or ValueError, by what is wrong
            raise ProjectError(f"The weather file cannot be read: {error}", status_code=422) from error
        if period is None:
            return ColdPeriodReply(status="none")
        return ColdPeriodReply(status="found", period=ColdPeriodDates(**asdict(period)))

    def _weather_location_fields(self, name: str) -> list[str] | None:
        """The comma-separated fields of the weather file's LOCATION line; None without a file or that line."""
        weather_path = self.weather_file_path(name)
        if weather_path is None:
            return None
        with weather_path.open(encoding="utf-8", errors="replace") as weather_file:
            location_fields = weather_file.readline().strip().split(",")
        return location_fields if location_fields[0].upper() == "LOCATION" else None

    def weather_location(self, name: str) -> str | None:
        """'<city>, <country>' from the LOCATION line of the weather file; None without a usable file."""
        location_fields = self._weather_location_fields(name)
        if location_fields is None or len(location_fields) < 4:
            return None
        city, country = (" ".join(location_fields[index].split()) for index in (1, 3))
        return f"{city}, {country}"

    def weather_latitude(self, name: str) -> float | None:
        """Degrees north (negative south) from field 6 of the LOCATION line; None without a usable file or number."""
        location_fields = self._weather_location_fields(name)
        if location_fields is None or len(location_fields) < 7:
            return None
        try:
            latitude = float(location_fields[6])
        except ValueError:
            return None
        return latitude if -90.0 <= latitude <= 90.0 else None

    @staticmethod
    def _check_role(role: str) -> None:
        if role not in (*MESH_ROLES, WEATHER_ROLE):
            raise ProjectError(f"'{role}' is not an input role.", status_code=422)

    @staticmethod
    def _stored_file_path(project_folder: Path, role: str, file_name: str) -> Path:
        if role == WEATHER_ROLE:
            return project_folder / INPUTS_FOLDER / WEATHER_FILE_NAME
        return project_folder / INPUTS_FOLDER / role / file_name

    @staticmethod
    def _file_infos(project_json: ProjectJson, role: str) -> list[InputFileInfo]:
        triangle_counts = project_json.input_files.get(role, {})
        return [InputFileInfo(name=file_name, triangle_count=triangle_counts[file_name]) for file_name in sorted(triangle_counts)]

    def _reply(self, name: str, role: str, project_json: ProjectJson) -> InputFilesReply:
        return InputFilesReply(
            role=role,
            files=self._file_infos(project_json, role),
            joined_bounds=self.joined_bounds(name),
            weather_location=self.weather_location(name),
            weather_latitude=self.weather_latitude(name),
        )

    @staticmethod
    def _write_bytes_atomically(target_path: Path, data: bytes) -> None:
        descriptor, temporary_path = tempfile.mkstemp(dir=target_path.parent, prefix=target_path.stem, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(data)
            os.replace(temporary_path, target_path)
        except BaseException:
            Path(temporary_path).unlink(missing_ok=True)
            raise

    @staticmethod
    def _store_weather_file(project_folder: Path, clean_name: str, data: bytes) -> None:
        """Check an uploaded weather file by reading it as an EPW, then move it over the earlier one.

        Ladybug's reader, which the engine uses for the same file, needs a LOCATION line, the eight header
        lines and the hourly rows of a whole year. The earlier weather file stays when the new one is refused.
        """
        from ladybug.epw import EPW
        inputs_folder = project_folder / INPUTS_FOLDER
        descriptor, upload_name = tempfile.mkstemp(dir=inputs_folder, prefix="upload", suffix=WEATHER_EXTENSION)
        upload_path = Path(upload_name)
        try:
            with os.fdopen(descriptor, "wb") as upload_file:
                upload_file.write(data)
            try:
                EPW(str(upload_path)).dry_bulb_temperature      # the first hourly field loads, and so checks, the whole body
            except Exception as error:      # the reader fails with AssertionError, IndexError or ValueError, by what is wrong
                reason = "its LOCATION line, header lines or fields are missing" if isinstance(error, IndexError) else str(error)
                raise ProjectError(f"'{clean_name}' cannot be read as an EPW weather file: {reason or type(error).__name__}",
                                   status_code=422) from error
            os.replace(upload_path, inputs_folder / WEATHER_FILE_NAME)
        finally:
            upload_path.unlink(missing_ok=True)

    def _add_mesh_file(self, project_folder: Path, project_json: ProjectJson, role: str, clean_name: str, data: bytes) -> None:
        """Check an uploaded mesh, build the joined file with it, then move both into place."""
        role_folder = project_folder / INPUTS_FOLDER / role
        recorded_names = project_json.input_files.setdefault(role, {})
        stored_name = next((recorded for recorded in recorded_names if recorded.lower() == clean_name.lower()), clean_name)
        descriptor, upload_name = tempfile.mkstemp(dir=role_folder, prefix="upload", suffix=Path(clean_name).suffix.lower())
        upload_path = Path(upload_name)
        joined_temporary_path = None
        try:
            with os.fdopen(descriptor, "wb") as upload_file:
                upload_file.write(data)
            try:
                uploaded_mesh = load_mesh(str(upload_path))
            except InputError as error:
                # the engine message names the temporary file; the person knows the file by its own name
                message = str(error).removeprefix("load_mesh: ")
                raise ProjectError(message.replace(repr(str(upload_path)), repr(clean_name)).replace(str(upload_path), clean_name),
                                   status_code=422) from error
            other_names = [recorded for recorded in recorded_names if recorded != stored_name]
            meshes_by_name = self._load_stored_meshes(project_folder, role, other_names)
            meshes_by_name[stored_name] = uploaded_mesh
            joined_temporary_path = self._write_joined_temporary_file(
                project_folder, role, [meshes_by_name[mesh_name] for mesh_name in sorted(meshes_by_name)])
            os.replace(upload_path, role_folder / stored_name)
            self._replace_joined_file(project_folder, role, joined_temporary_path)
        finally:
            upload_path.unlink(missing_ok=True)
            if joined_temporary_path is not None:
                joined_temporary_path.unlink(missing_ok=True)
        recorded_names[stored_name] = len(uploaded_mesh.faces)

    @staticmethod
    def _load_stored_meshes(project_folder: Path, role: str, file_names: list[str]) -> dict[str, trimesh.Trimesh]:
        """The meshes of recorded files by file name, in name order, or ProjectError when one cannot be read."""
        meshes = {}
        for file_name in sorted(file_names):
            try:
                meshes[file_name] = load_mesh(str(project_folder / INPUTS_FOLDER / role / file_name))
            except InputError as error:
                raise ProjectError(f"The {role} file '{file_name}' cannot be read, so the joined file was not rebuilt: {error}",
                                   status_code=422) from error
        return meshes

    @staticmethod
    def _write_joined_temporary_file(project_folder: Path, role: str, meshes: list[trimesh.Trimesh]) -> Path | None:
        """Join the meshes of a role as the Grasshopper components do (spec 5.3) into a new temporary file.

        Max volume meshes are concatenated and their coincident vertices merged; test surface
        meshes are only concatenated, and written with their vertex normals (see
        _write_ply_with_vertex_normals). Returns None for no meshes (the joined file is then removed).
        The temporary name is unique, so concurrent builds never share a file.
        """
        if not meshes:
            return None
        descriptor, temporary_name = tempfile.mkstemp(dir=project_folder / JOINED_FOLDER, prefix=f"{role}-", suffix=".tmp.ply")
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            if role == "max_volume":
                joined_mesh = trimesh.util.concatenate(meshes)
                joined_mesh.merge_vertices()
                save_mesh(joined_mesh, str(temporary_path))
            else:
                _write_ply_with_vertex_normals(meshes, temporary_path)
        except Exception as error:
            temporary_path.unlink(missing_ok=True)
            raise ProjectError(f"The joined {role} file could not be built: {error}", status_code=500) from error
        return temporary_path

    @staticmethod
    def _replace_joined_file(project_folder: Path, role: str, joined_temporary_path: Path | None) -> None:
        """Move the new joined file into place, or remove the joined file when the role has no mesh left."""
        joined_path = project_folder / JOINED_FOLDER / f"{role}.ply"
        if joined_temporary_path is None:
            joined_path.unlink(missing_ok=True)
        else:
            os.replace(joined_temporary_path, joined_path)

    @staticmethod
    def _modified(project_folder: Path) -> str:
        file_paths = [project_folder / PROJECT_JSON_FILE_NAME, project_folder / CONFIG_FILE_NAME]
        return _utc_iso(max(path.stat().st_mtime for path in file_paths if path.is_file()))

    @classmethod
    def _mode(cls, project_folder: Path) -> str:
        config_path = project_folder / CONFIG_FILE_NAME
        if not config_path.is_file():
            return ""
        return str(cls._parse_config_file(config_path, project_folder.name).get("mode", ""))

    @staticmethod
    def _parse_config_file(config_path: Path, name: str) -> dict:
        """The settings a config.yaml holds as a dict; ProjectError(422) when the file cannot be read or is not UTF-8.

        An empty file, one that holds no mapping, or one with a YAML syntax error (a hand edit) gives an empty
        dict: it sets no setting, so it fails validation like any other config without a mode, the project
        still opens with every completed stage out of date, and the next save replaces the file.
        """
        try:
            config_text = config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ProjectError(f"{CONFIG_FILE_NAME} of '{name}' cannot be read: {error}", status_code=422) from error
        try:
            stored_config = yaml.safe_load(config_text)
        except yaml.YAMLError:
            return {}
        return stored_config if isinstance(stored_config, dict) else {}
