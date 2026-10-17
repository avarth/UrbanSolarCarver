"""Project folders of the local web service: names, layout and project.json.

A project is a folder under the projects folder, named by the user. The
service never takes a path from the browser, so every folder is derived from
a validated name and checked to be a direct child of the projects folder.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import ValidationError

from .api_models import ProjectJson, ProjectSummary

PROJECT_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,63}")
PROJECT_JSON_FILE_NAME = "project.json"
CONFIG_FILE_NAME = "config.yaml"
INPUT_ROLE_FOLDERS = ("inputs/max_volume", "inputs/test_surfaces", "inputs/joined")
RUN_FOLDER = "run"


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
        """The projects sorted by name; a folder without project.json is not a project."""
        if not self._projects_folder.is_dir():
            return []
        summaries = []
        for project_folder in sorted(self._projects_folder.iterdir(), key=lambda folder: folder.name):
            if not (project_folder / PROJECT_JSON_FILE_NAME).is_file():
                continue
            project_json = self.read_project_json(project_folder.name)
            summaries.append(ProjectSummary(
                name=project_json.name,
                created=project_json.created,
                modified=self._modified(project_folder),
                mode=self._mode(project_folder),
            ))
        return summaries

    def read_project_json(self, name: str) -> ProjectJson:
        project_json_path = self.open(name) / PROJECT_JSON_FILE_NAME
        try:
            return ProjectJson.model_validate_json(project_json_path.read_text(encoding="utf-8"))
        except (ValidationError, OSError) as error:
            raise ProjectError(f"{PROJECT_JSON_FILE_NAME} of '{name}' cannot be read: {error}", status_code=422) from error

    def write_project_json(self, name: str, data: ProjectJson) -> None:
        project_json_path = self._project_folder(name) / PROJECT_JSON_FILE_NAME
        project_json_path.write_text(data.model_dump_json(indent=1), encoding="utf-8")

    @staticmethod
    def _modified(project_folder: Path) -> str:
        file_paths = [project_folder / PROJECT_JSON_FILE_NAME, project_folder / CONFIG_FILE_NAME]
        return _utc_iso(max(path.stat().st_mtime for path in file_paths if path.is_file()))

    @staticmethod
    def _mode(project_folder: Path) -> str:
        config_path = project_folder / CONFIG_FILE_NAME
        if not config_path.is_file():
            return ""
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return str(config.get("mode", "")) if isinstance(config, dict) else ""
