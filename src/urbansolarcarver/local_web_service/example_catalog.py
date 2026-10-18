"""The packaged example projects: where their files are and the list of them in examples.json."""
from __future__ import annotations

import json
from pathlib import Path

from .api_models import ExampleProject

EXAMPLE_PROJECTS_FOLDER = Path(__file__).resolve().parent.parent / "example_projects"
EXAMPLE_WEATHER_FILE_NAME = "USA_CO_Golden-NREL.724666_TMY3.epw"    # in example_projects/weather/


def read_examples() -> list[ExampleProject]:
    """The packaged example projects, in the order of examples.json."""
    entries = json.loads((EXAMPLE_PROJECTS_FOLDER / "examples.json").read_text(encoding="utf-8"))
    return [ExampleProject.model_validate(entry) for entry in entries]
