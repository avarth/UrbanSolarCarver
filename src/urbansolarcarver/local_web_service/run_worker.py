"""The run worker: one pipeline run at a time on a background thread, with an event log the browser reads.

``RunWorker.start`` chooses the stages (see ``stage_records``), removes their records, and starts a thread that
calls the engine. The thread appends events to the run's ``RunState``; the WebSocket handler reads them with
``RunState.wait_for_events``, which also serves a reader that connects after the run began or finished.
Importing this module does not import torch: the engine and the compute session are imported when the first run starts.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..errors import ConfigError, RunCancelled, StageChainError
from ..run_context import RunContext
from ..stage_settings import PIPELINE_STAGES
from .api_models import StartRunReply
from .projects import RUN_FOLDER, ProjectError, ProjectStore
from .stage_records import choose_stages, forget_stages, missing_inputs, record_stages

_log = logging.getLogger(__name__)

STAGE_CHAIN_MESSAGE = "Results are out of date; run again from the start."
EXPORTED_MESH_PATTERN = "export.*"      # the exporting stage writes one mesh, named for its format
RESULT_FILES = ("massing/plates.json", "massing/plates.obj", "run_report.md")


class RunConflict(ProjectError):
    """A run is already active; only one runs at a time."""

    def __init__(self, project: str):
        super().__init__(f"A run of project '{project}' is active. Wait for it to finish or cancel it.", status_code=409)


class MissingInputs(ProjectError):
    """The project lacks files its mode needs; ``roles`` names them."""

    def __init__(self, roles: list[str]):
        super().__init__(f"Upload the missing input files first: {', '.join(roles)}.", status_code=422)
        self.roles = roles


class RunState:
    """The events of one run, readable while it runs and after it finished."""

    def __init__(self, run_id: str, project: str, stages: list[str]):
        self.run_id = run_id
        self.project = project
        self.stages = stages
        self.events: list[dict] = []
        self.finished = False
        self._changed = threading.Condition()

    def emit(self, event: dict) -> None:
        with self._changed:
            self.events.append(event)
            self._changed.notify_all()

    def finish(self, final_event: dict) -> None:
        """Append the last event and mark the run finished, in one step readers see together."""
        with self._changed:
            self.events.append(final_event)
            self.finished = True
            self._changed.notify_all()

    def wait_for_events(self, after: int, timeout: float) -> list[dict]:
        """The events from index *after* on (the number of events the reader has seen).

        Blocks until there is at least one, the run is finished, or *timeout* seconds pass; returns an
        empty list when nothing new came.
        """
        with self._changed:
            self._changed.wait_for(lambda: len(self.events) > after or self.finished, timeout)
            return list(self.events[after:])


@dataclass
class _ActiveRun:
    state: RunState
    context: RunContext
    thread: threading.Thread


class RunWorker:
    """Runs the pipeline for one project at a time; the compute session is created at the first run and kept."""

    def __init__(self, store: ProjectStore, device: str, handle_request: Callable | None = None,
                 session_factory: Callable[[str], object] | None = None):
        self._store = store
        self._device = device
        self._handle_request = handle_request
        self._session_factory = session_factory
        self._session = None
        self._start_lock = threading.Lock()
        self._active: _ActiveRun | None = None
        self._run_states: dict[str, RunState] = {}

    def active_project(self) -> str | None:
        """The project a run is active for, None when idle. Takes no lock, so a caller holding a project lock may ask."""
        active = self._active
        return active.state.project if active is not None else None

    def run_state(self, run_id: str) -> RunState | None:
        return self._run_states.get(run_id)

    def cancel(self, run_id: str) -> bool:
        """Ask the active run with this id to stop; False when it is not the active run."""
        active = self._active
        if active is None or active.state.run_id != run_id:
            return False
        active.context.cancel()
        return True

    def start(self, name: str, produce: list[str]) -> StartRunReply:
        """Start a run that brings *produce* up to date, or reply that nothing needs to run.

        Raises RunConflict when a run is active, MissingInputs when the project lacks input files,
        ConfigError when config.yaml is not valid, ValueError for an unknown stage name in *produce*.
        """
        with self._store.project_lock(name), self._start_lock:
            if self._active is not None:
                raise RunConflict(self._active.state.project)
            config = self._store.load_project_config(name)
            absent_roles = missing_inputs(self._store, name, config)
            if absent_roles:
                raise MissingInputs(absent_roles)
            choice = choose_stages(self._store, name, produce)
            if not choice.stages:
                return StartRunReply(status="up_to_date", run_id=None, stages=[])
            settings = self._store.read_stored_config(name)
            inputs_revision = self._store.read_project_json(name).inputs_revision
            # Removed before the engine starts: a run that stops without finishing (a crash, a closed service)
            # leaves these stages missing, so the next run completes them.
            forget_stages(self._store, name, choice.stages)
            state = RunState(uuid.uuid4().hex, name, choice.stages)
            context = RunContext()
            thread = threading.Thread(
                target=self._run, args=(state, context, choice.produce_for_engine, settings, inputs_revision),
                name=f"run-{state.run_id}", daemon=True)
            self._run_states[state.run_id] = state
            self._active = _ActiveRun(state, context, thread)
            thread.start()
            return StartRunReply(status="started", run_id=state.run_id, stages=choice.stages)

    def _run(self, state: RunState, context: RunContext, produce_for_engine: list[str], settings: dict, inputs_revision: int) -> None:
        """The thread body: run the engine, record the stages on success, and end the event log with one final event."""
        issues_forwarder = _IssuesForwarder(state, context)
        context.on_progress = issues_forwarder.forward_progress
        try:
            self._call_engine(state, context, produce_for_engine)
            record_stages(self._store, state.project, state.stages, settings, inputs_revision)
            final_event = {"type": "run_finished", "stages": state.stages,
                           "files": _result_files(self._store.open(state.project) / RUN_FOLDER)}
        except RunCancelled:
            final_event = {"type": "run_cancelled"}
        except StageChainError:
            _log.exception("A run of project '%s' found its earlier stages unusable", state.project)
            forget_stages(self._store, state.project, PIPELINE_STAGES)
            final_event = _run_failed_event("StageChainError", STAGE_CHAIN_MESSAGE)
        except ConfigError as error:
            final_event = _run_failed_event("ConfigError", str(error), [
                {"field": field_error.field, "message": field_error.message} for field_error in error.errors])
        except Exception as error:
            _log.exception("A run of project '%s' failed", state.project)
            final_event = _run_failed_event(type(error).__name__, str(error))
        finally:
            if self._session is not None:
                self._session.release_memory()
        issues_forwarder.forward_new_issues()
        self._active = None     # before the final event: a reader that sees the run end can start the next one
        state.finish(final_event)

    def _call_engine(self, state: RunState, context: RunContext, produce_for_engine: list[str]) -> None:
        from ..engine_requests import RunRequest

        if self._session is None:
            self._session = self._create_session()
        request = RunRequest(
            cmd="run", produce=produce_for_engine, run_folder=str(self._store.open(state.project) / RUN_FOLDER),
            start_from=state.stages[0], config=str(self._store.open(state.project) / "config.yaml"),
            overrides={"device": self._device})     # the device of this service, not the one stored at the last save
        self._handler()(request, self._session, context)

    def _create_session(self):
        if self._session_factory is not None:
            return self._session_factory(self._device)
        from ..session import CarverSession
        return CarverSession(self._device)

    def _handler(self) -> Callable:
        if self._handle_request is not None:
            return self._handle_request
        from ..engine_requests import handle_engine_request
        return handle_engine_request


class _IssuesForwarder:
    """Turns progress callbacks and new run issues into events, issues first."""

    def __init__(self, state: RunState, context: RunContext):
        self._state = state
        self._context = context
        self._issues_sent = 0
        self._lock = threading.Lock()   # progress can be reported from the engine's own threads

    def forward_progress(self, stage: str | None, done: int, total: int) -> None:
        with self._lock:
            self._send_new_issues()
            self._state.emit({"type": "stage_progress", "stage": stage, "done": done, "total": total})

    def forward_new_issues(self) -> None:
        with self._lock:
            self._send_new_issues()

    def _send_new_issues(self) -> None:
        for issue in self._context.issues[self._issues_sent:]:
            self._state.emit({"type": "issue", "stage": issue.stage, "code": issue.code, "message": issue.message})
        self._issues_sent = len(self._context.issues)


def _run_failed_event(error_type: str, message: str, field_errors: list[dict] | None = None) -> dict:
    return {"type": "run_failed", "error_type": error_type, "message": message, "field_errors": field_errors or []}


def _result_files(run_folder: Path) -> list[str]:
    """The result files that exist, as paths relative to the run folder: the exported mesh, the plates and the report."""
    candidates = [*sorted((run_folder / "exporting").glob(EXPORTED_MESH_PATTERN)), *(run_folder / path for path in RESULT_FILES)]
    return [path.relative_to(run_folder).as_posix() for path in candidates if path.is_file()]
