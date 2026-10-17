"""Request and response models of the local web service.

Pydantic models for the files the service stores and the JSON it exchanges
with the browser app. This module holds no behaviour.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class StageRecord(BaseModel):
    """What one completed pipeline stage of a project was run with."""
    config: dict                # the config.yaml content the stage ran with
    inputs_revision: int        # ProjectJson.inputs_revision at the time of the run
    manifest_run_id: str        # run_id of the manifest the stage wrote


class ProjectJson(BaseModel):
    """The content of a project's project.json."""
    name: str
    created: str                # ISO 8601, UTC
    inputs_revision: int = 1    # raised by every upload and removal of an input file
    input_files: dict[str, dict[str, int]] = Field(default_factory=dict)  # role -> file name -> triangle count
    stage_records: dict[str, StageRecord] = Field(default_factory=dict)   # stage name -> record


class InputFileInfo(BaseModel):
    """One uploaded input file as listed in the file lists of the inputs screen."""
    name: str
    triangle_count: int         # 0 for the weather file


class InputFilesReply(BaseModel):
    """The files of one input role after an upload or a removal."""
    role: str
    files: list[InputFileInfo]  # sorted by name
    joined_bounds: list[list[float]] | None   # [[xmin, ymin, zmin], [xmax, ymax, zmax]] of the joined max volume, whatever the role
    weather_location: str | None              # "<city>, <country>" from the weather file, None without one


class ProjectSummary(BaseModel):
    """One row of the start screen's project list."""
    name: str
    created: str                # ISO 8601, UTC
    modified: str               # ISO 8601, UTC: newest modification time of project.json and config.yaml
    mode: str
