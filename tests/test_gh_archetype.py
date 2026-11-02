"""USC_ZoneOperation and USC_Archetype: how the room is run, outside Rhino.

The component scripts run against a stand-in ghenv; USC_Archetype reads the
engine's defaults through a stand-in usc_gh module.
"""
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from _epw import BUNDLED_EPW
from urbansolarcarver import archetype_defaults
from urbansolarcarver import simulated_weights as sw

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = REPO_ROOT / "grasshopper" / "components"
FAMILIES = ("geometry", "fabric", "ventilation", "operation", "shading")


def _ghenv(inputs):
    ghenv = mock.MagicMock()
    ghenv.Component.Params.Input = [mock.MagicMock(SourceCount=0) for _ in range(inputs)]
    ghenv.Component.Params.Output = [mock.MagicMock() for _ in range(2)]
    return ghenv


def _run(name, inputs, **values):
    scope = {"ghenv": _ghenv(inputs), "__name__": "__main__", **values}
    exec(compile((COMPONENTS / name).read_text(encoding="utf-8"), name, "exec"), scope)
    return scope


@pytest.fixture
def engine(monkeypatch):
    gh = types.SimpleNamespace(__file__=str(REPO_ROOT / "grasshopper" / "usc_gh.py"),
                               engine_module=lambda root, name: archetype_defaults)
    monkeypatch.setitem(sys.modules, "usc_gh", gh)


def _archetype(**families):
    return _run("USC_Archetype.py", len(FAMILIES), **{name: families.get(name) for name in FAMILIES})


def _operation(**values):
    names = ("t_set_heating", "t_set_cooling", "internal_gains", "free_running", "vent_above", "vent_ach")
    return _run("USC_ZoneOperation.py", len(names), **{name: values.get(name) for name in names})


def test_an_unwired_archetype_runs_free_with_the_engine_window_opening(engine):
    data = _archetype()["archetype"].data
    assert data["operation"] == "free_running"
    assert {key: data[key] for key in archetype_defaults.FREE_RUNNING_DEFAULTS} == archetype_defaults.FREE_RUNNING_DEFAULTS


def test_a_heated_and_cooled_room_drops_the_window_opening(engine):
    operation = _operation(free_running=False)["operation"]
    data = _archetype(operation=operation)["archetype"].data
    assert data["operation"] == "conditioned"
    assert not set(archetype_defaults.FREE_RUNNING_DEFAULTS) & set(data)


def test_the_window_opening_passes_to_a_free_running_room(engine):
    operation = _operation(vent_above=24, vent_ach=2)["operation"]
    data = _archetype(operation=operation)["archetype"].data
    assert (data["operation"], data["vent_above"], data["vent_ach"]) == ("free_running", 24.0, 2.0)


def test_a_window_opening_for_a_heated_and_cooled_room_is_refused():
    scope = _operation(free_running=False, vent_ach=2)
    assert scope["operation"] is None and "free-running room only" in scope["summary"]


def test_windows_opening_below_the_comfort_band_are_refused(engine):
    operation = _operation(t_set_heating=22, vent_above=21)["operation"]
    scope = _archetype(operation=operation)
    assert scope["archetype"] is None and "vent_above" in scope["summary"]


@pytest.mark.slow
def test_the_default_archetype_simulates_as_a_free_running_room(engine, tmp_path):
    data = _archetype()["archetype"].data
    path = sw.generate_simulated_weights(str(BUNDLED_EPW), data, tmp_path / "w.json")
    _, _, meta = sw.read_simulated_weights(path)
    assert meta["operation"] == "free_running" and meta["archetype"]["vent_above"] == 25.0
