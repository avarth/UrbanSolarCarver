"""Project folders of the local web service: names, layout and project.json.

A project is a folder under the projects folder, named by the user. The
service never takes a path from the browser, so every folder is derived from
a validated name and checked to be a direct child of the projects folder.
"""
from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import trimesh
import yaml
from pydantic import ValidationError

from ..errors import InputError
from ..io import load_mesh, save_mesh
from .api_models import InputFileInfo, InputFilesReply, ProjectJson, ProjectSummary

PROJECT_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,63}")
PROJECT_JSON_FILE_NAME = "project.json"
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
UNWANTED_FILE_NAME_CHARACTERS = re.compile(r"[^A-Za-z0-9_.-]")
FILE_NAME_SEPARATORS = re.compile(r"[\\/]")


class ProjectError(Exception):
    """A project request that cannot be served; ``status_code`` is the HTTP status."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def validate_project_name(name: str) -> str:
    """Return the name without surrounding spaces, or raise ProjectError(422)."""
    stripped_name = name.strip(" ")
    if PROJECT_NAME_PATTERN.fullmatch(stripped_name) is None:
        raise ProjectError(
            "A project name has 1 to 64 characters: letters A-Z and a-z, digits, spaces, "
            "'-' and '_', starting with a letter or digit.",
            status_code=422,
        )
    return stripped_name


def sanitize_file_name(name: str) -> str:
    """The last part of an uploaded file name with only letters, digits, '-', '_' and '.' kept.

    Raises ProjectError(422) when nothing usable is left or the name would be hidden (starts with '.').
    """
    last_part = FILE_NAME_SEPARATORS.split(name)[-1]
    clean_name = UNWANTED_FILE_NAME_CHARACTERS.sub("", last_part)
    if not clean_name or clean_name.startswith("."):
        raise ProjectError(f"'{name}' has no usable file name: use letters, digits, '-', '_' and '.'.", status_code=422)
    return clean_name


def _utc_iso(timestamp_seconds: float) -> str:
    return datetime.fromtimestamp(timestamp_seconds, timezone.utc).isoformat(timespec="seconds")


class ProjectStore:
    """The projects under one projects folder."""

    def __init__(self, projects_folder: Path):
        self._projects_folder = Path(projects_folder)

    def _project_folder(self, name: str) -> Path:
        """The folder of a project with a valid name, guaranteed to lie directly in the projects folder."""
        project_folder = (self._projects_folder / validate_project_name(name)).resolve()
        if project_folder.parent != self._projects_folder.resolve():
            raise ProjectError("The project name does not name a folder of the projects folder.", status_code=422)
        return project_folder

    def create(self, name: str, mode: str) -> Path:
        """Make the project folder with its layout, project.json and a minimal config.yaml."""
        project_name = validate_project_name(name)
        project_folder = self._project_folder(project_name)
        try:
            project_folder.mkdir(parents=True)
        except FileExistsError:
            raise ProjectError(f"A project named '{project_name}' already exists.", status_code=409) from None
        for sub_folder in (*INPUT_ROLE_FOLDERS, RUN_FOLDER):
            (project_folder / sub_folder).mkdir(parents=True)
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.write_project_json(project_name, ProjectJson(name=project_name, created=created))
        (project_folder / CONFIG_FILE_NAME).write_text(yaml.safe_dump({"mode": mode}), encoding="utf-8")
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
        """
        if not self._projects_folder.is_dir():
            return []
        summaries = []
        for project_folder in sorted(self._projects_folder.iterdir(), key=lambda folder: folder.name):
            if not (project_folder / PROJECT_JSON_FILE_NAME).is_file():
                continue
            try:
                project_json = self.read_project_json(project_folder.name)
                summaries.append(ProjectSummary(
                    name=project_json.name,
                    created=project_json.created,
                    modified=self._modified(project_folder),
                    mode=self._mode(project_folder),
                ))
            except ProjectError:
                continue
        return summaries

    def read_project_json(self, name: str) -> ProjectJson:
        project_json_path = self.open(name) / PROJECT_JSON_FILE_NAME
        try:
            return ProjectJson.model_validate_json(project_json_path.read_text(encoding="utf-8"))
        except (ValidationError, OSError) as error:
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

    def add_input(self, name: str, role: str, file_name: str, data: bytes) -> InputFilesReply:
        """Store an uploaded file for a role and rebuild the joined file of a mesh role.

        A mesh is checked with the engine's own loader before it is kept, so a file the
        run would refuse is refused at upload. A file with the name of an earlier upload replaces it.
        """
        self._check_role(role)
        clean_name = sanitize_file_name(file_name)
        extension = Path(clean_name).suffix.lower()
        project_json = self.read_project_json(name)
        project_folder = self.open(name)
        if role == WEATHER_ROLE:
            if extension != WEATHER_EXTENSION:
                raise ProjectError(f"The weather file must be an {WEATHER_EXTENSION} file.", status_code=422)
            self._write_bytes_atomically(project_folder / INPUTS_FOLDER / WEATHER_FILE_NAME, data)
            project_json.input_files[role] = {WEATHER_FILE_NAME: 0}
        else:
            if extension not in MESH_EXTENSIONS:
                raise ProjectError(f"A mesh file must be one of {', '.join(MESH_EXTENSIONS)}.", status_code=422)
            role_folder = project_folder / INPUTS_FOLDER / role
            descriptor, temporary_name = tempfile.mkstemp(dir=role_folder, prefix="upload", suffix=extension)
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as temporary_file:
                    temporary_file.write(data)
                try:
                    triangle_count = len(load_mesh(str(temporary_path)).faces)
                except InputError as error:
                    raise ProjectError(str(error), status_code=422) from error
                os.replace(temporary_path, role_folder / clean_name)
            except BaseException:
                temporary_path.unlink(missing_ok=True)
                raise
            project_json.input_files.setdefault(role, {})[clean_name] = triangle_count
            self._rebuild_joined_file(project_folder, role, project_json)
        project_json.inputs_revision += 1
        self.write_project_json(name, project_json)
        return self._reply(name, role, project_json)

    def remove_input(self, name: str, role: str, file_name: str) -> InputFilesReply:
        """Delete an uploaded file and rebuild the joined file of a mesh role; 404 when the file is not there."""
        self._check_role(role)
        project_json = self.read_project_json(name)
        project_folder = self.open(name)
        if file_name not in project_json.input_files.get(role, {}):
            raise ProjectError(f"There is no {role} file named '{file_name}'.", status_code=404)
        del project_json.input_files[role][file_name]
        self._stored_file_path(project_folder, role, file_name).unlink(missing_ok=True)
        if role != WEATHER_ROLE:
            self._rebuild_joined_file(project_folder, role, project_json)
        project_json.inputs_revision += 1
        self.write_project_json(name, project_json)
        return self._reply(name, role, project_json)

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
        """[[xmin, ymin, zmin], [xmax, ymax, zmax]] of the joined max volume, None before any is uploaded."""
        joined_path = self.open(name) / JOINED_FOLDER / "max_volume.ply"
        if not joined_path.is_file():
            return None
        return load_mesh(str(joined_path)).bounds.tolist()

    def weather_location(self, name: str) -> str | None:
        """'<city>, <country>' from the LOCATION line of the weather file; None without a usable file."""
        weather_path = self.open(name) / INPUTS_FOLDER / WEATHER_FILE_NAME
        if not weather_path.is_file():
            return None
        with weather_path.open(encoding="utf-8", errors="replace") as weather_file:
            location_fields = weather_file.readline().strip().split(",")
        if location_fields[0].upper() != "LOCATION" or len(location_fields) < 4:
            return None
        city, country = (" ".join(location_fields[index].split()) for index in (1, 3))
        return f"{city}, {country}"

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
    def _rebuild_joined_file(project_folder: Path, role: str, project_json: ProjectJson) -> None:
        """Join the uploaded meshes of a role as the Grasshopper components do (spec 5.3).

        Max volume files are concatenated and their coincident vertices merged; test surface
        files are only concatenated. The joined file is replaced atomically, or removed when
        the role has no file left.
        """
        joined_path = project_folder / JOINED_FOLDER / f"{role}.ply"
        file_names = sorted(project_json.input_files.get(role, {}))
        if not file_names:
            joined_path.unlink(missing_ok=True)
            return
        meshes = [load_mesh(str(project_folder / INPUTS_FOLDER / role / file_name)) for file_name in file_names]
        joined_mesh = trimesh.util.concatenate(meshes)
        if role == "max_volume":
            joined_mesh.merge_vertices()
        temporary_path = joined_path.with_name(f"{role}.tmp.ply")
        try:
            save_mesh(joined_mesh, str(temporary_path))
            os.replace(temporary_path, joined_path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _modified(project_folder: Path) -> str:
        file_paths = [project_folder / PROJECT_JSON_FILE_NAME, project_folder / CONFIG_FILE_NAME]
        return _utc_iso(max(path.stat().st_mtime for path in file_paths if path.is_file()))

    @staticmethod
    def _mode(project_folder: Path) -> str:
        config_path = project_folder / CONFIG_FILE_NAME
        if not config_path.is_file():
            return ""
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as error:
            raise ProjectError(f"{CONFIG_FILE_NAME} of '{project_folder.name}' cannot be read: {error}", status_code=422) from error
        return str(config.get("mode", "")) if isinstance(config, dict) else ""
