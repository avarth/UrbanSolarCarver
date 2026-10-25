"""The run worker: one pipeline run at a time on a background thread, with an event log the browser reads.

``RunWorker.start`` chooses the stages (see ``stage_records``), removes their records, and starts a thread that
calls the engine. The thread appends events to the run's ``RunState``; the WebSocket handler reads them with
``RunState.wait_for_events``, which also serves a reader that connects after the run began or finished.
Importing this module does not import torch: the engine and the compute session are imported when the first run starts.
"""
from __future__ import annotations

import logging
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..errors import ConfigError, RunCancelled, StageChainError
from ..run_context import RunContext
from ..stage_settings import PIPELINE_STAGES
from . import test_surfaces
from .api_models import StartRunReply
from .projects import RUN_FOLDER, ProjectError, ProjectStore
from .stage_records import ANALYSIS_STAGES, RunSettings, StageChoice, choose_stages, forget_stages, missing_inputs, record_stages, run_settings

_log = logging.getLogger(__name__)

STAGE_CHAIN_MESSAGE = "Results are out of date; run again from the start."
EXPORTED_MESH_PATTERN = "export.*"      # the exporting stage writes one mesh, named for its format
MASSING_RESULT_PATTERN = "plates.*"     # plates.json, plates.obj, and the plates in the chosen format when it is not OBJ
RESULT_FILES = ("run_report.md",)
# How the engine's run_chain labels what it reports: the progress of criterion <id>, and an issue noticed by a stage of a criterion.
CRITERION_PROGRESS_LABEL = re.compile(r"criterion ([^\s()]+)")
CRITERION_ISSUE_LABEL = re.compile(r"criterion ([^\s()]+) \((\w+)\)")


class RunConflict(ProjectError):
    """A run is already active; only one runs at a time."""

    def __init__(self, project: str):
        super().__init__(f"A run of project '{project}' is active. Wait for it to finish or cancel it.", status_code=409)


class MissingInputs(ProjectError):
    """The project lacks what a run needs; ``roles`` names it (see missing_inputs) and the message says what to do about each."""

    def __init__(self, roles: list[str], criterion_names: dict[str, str] | None = None):
        super().__init__(_missing_inputs_message(roles, criterion_names or {}), status_code=422)
        self.roles = roles


def _missing_inputs_message(roles: list[str], criterion_names: dict[str, str]) -> str:
    """A sentence for the input files to upload, one when no criterion is on, and one for each criterion without test surfaces."""
    test_surfaces_prefix = f"{test_surfaces.ROLE}:"
    files = [role for role in roles if role != "criteria" and not role.startswith(test_surfaces_prefix)]
    sentences = [f"Upload the missing input files first: {', '.join(files)}."] if files else []
    if "criteria" in roles:
        sentences.append("Turn on a criterion to run.")
    for role in roles:
        if role.startswith(test_surfaces_prefix):
            criterion_id = role.removeprefix(test_surfaces_prefix)
            sentences.append(f"Add test surfaces to {criterion_names.get(criterion_id, criterion_id)}.")
    return " ".join(sentences)


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

    @property
    def store(self) -> ProjectStore:
        """The project store the worker reads; the HTTP service shares it so both use the same per-project locks."""
        return self._store

    def for_store(self, store: ProjectStore) -> RunWorker:
        """A worker for another project store with this worker's engine handler and compute session, which are kept.

        Call it while no run is active (the session is not shared between two runs).
        """
        worker = RunWorker(store, self._device, self._handle_request, self._session_factory)
        worker._session = self._session
        return worker

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
            self._store.rebuild_joined_test_surfaces_without_normals(name)
            config = self._store.load_project_config(name)
            absent_roles = missing_inputs(self._store, name, config)
            if absent_roles:
                raise MissingInputs(absent_roles, {criterion.id: criterion.name for criterion in self._store.criteria(name)})
            choice = choose_stages(self._store, name, produce)
            if not choice.stages:
                return StartRunReply(status="up_to_date", run_id=None, stages=[], criterion_stages={})
            settings = run_settings(self._store, name)
            # Removed before the engine starts: a run that stops without finishing (a crash, a closed service)
            # leaves these stages missing, so the next run completes them.
            forget_stages(self._store, name, choice.stages, choice.criterion_stages)
            state = RunState(uuid.uuid4().hex, name, choice.stages)
            context = RunContext()
            thread = threading.Thread(
                target=self._run, args=(state, context, choice, settings),
                name=f"run-{state.run_id}", daemon=True)
            self._run_states[state.run_id] = state
            self._active = _ActiveRun(state, context, thread)
            thread.start()
            return StartRunReply(status="started", run_id=state.run_id, stages=choice.stages, criterion_stages=choice.criterion_stages)

    def _run(self, state: RunState, context: RunContext, choice: StageChoice, settings: RunSettings) -> None:
        """The thread body: run the engine, record the stages on success, and end the event log with one final event.

        Whatever goes wrong while finishing, the worker is released and the readers get a final event: a run that
        could not end would block every later start.
        """
        issues_forwarder = _IssuesForwarder(state, context)
        context.on_progress = issues_forwarder.forward_progress
        final_event = None
        try:
            final_event = self._final_event_of_run(state, context, choice, settings)
            issues_forwarder.forward_new_issues()
        except Exception as error:
            _log.exception("Finishing a run of project '%s' failed", state.project)
            if final_event is None:
                final_event = _run_failed_event(type(error).__name__, str(error))
        finally:
            self._release_session_memory()
            self._active = None     # before the final event: a reader that sees the run end can start the next one
            state.finish(final_event or _run_failed_event("RunAborted", "The run stopped unexpectedly."))

    def _final_event_of_run(self, state: RunState, context: RunContext, choice: StageChoice, settings: RunSettings) -> dict:
        """Run the engine and give the event that ends the run, whether it finished, was cancelled or failed."""
        try:
            self._call_engine(state, context, choice)
            record_stages(self._store, state.project, choice, settings)
            return {"type": "run_finished", "stages": state.stages,
                    "files": _result_files(self._store.open(state.project) / RUN_FOLDER)}
        except RunCancelled:
            return {"type": "run_cancelled"}
        except StageChainError:
            _log.exception("A run of project '%s' found its earlier stages unusable", state.project)
            forget_stages(self._store, state.project, PIPELINE_STAGES)
            return _run_failed_event("StageChainError", STAGE_CHAIN_MESSAGE)
        except ConfigError as error:
            return _run_failed_event("ConfigError", str(error), [
                {"field": field_error.field, "message": field_error.message} for field_error in error.errors])
        except Exception as error:
            _log.exception("A run of project '%s' failed", state.project)
            return _run_failed_event(type(error).__name__, str(error))

    def _release_session_memory(self) -> None:
        """Free unused compute memory; a failure (a CUDA fault, say) is logged and does not change how the run ended."""
        if self._session is None:
            return
        try:
            self._session.release_memory()
        except Exception:
            _log.exception("Releasing the compute memory after a run failed")

    def _call_engine(self, state: RunState, context: RunContext, choice: StageChoice) -> None:
        from ..engine_requests import RunRequest

        if self._session is None:
            self._session = self._create_session()
        request = RunRequest(
            cmd="run", produce=choice.produce_for_engine, run_folder=str(self._store.open(state.project) / RUN_FOLDER),
            start_from=choice.start_from, config=str(self._store.open(state.project) / "config.yaml"),
            trace_criteria=choice.trace_criteria or None,       # traced again; the others keep their preprocessing
            threshold_from_criterion=choice.threshold_from,     # thresholded again although it comes before the first traced one
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
    """Turns progress callbacks and new run issues into events, issues first.

    The engine reports a chain's progress as ``criterion <id>`` and the issues of a criterion's stage as ``criterion <id> (<stage>)``.
    The first is not forwarded: it sets the criterion that the events of the stages after it name (exporting and massing are built
    from the whole chain and name none). The second becomes the stage and the criterion; an issue of preprocessing or thresholding
    that is not named that way (the engine names a criterion's issues when the criterion is done, and some are sent before) names
    the criterion being run. Any other label is forwarded as it is, with no criterion.
    """

    def __init__(self, state: RunState, context: RunContext):
        self._state = state
        self._context = context
        self._issues_sent = 0
        self._criterion: str | None = None      # the criterion the engine reported progress for last
        self._lock = threading.Lock()   # progress can be reported from the engine's own threads

    def forward_progress(self, stage: str | None, done: int, total: int) -> None:
        with self._lock:
            self._send_new_issues()
            criterion_label = CRITERION_PROGRESS_LABEL.fullmatch(stage) if stage is not None else None
            if criterion_label is not None:
                self._criterion = criterion_label.group(1)
                return
            criterion = self._criterion if stage in ANALYSIS_STAGES else None
            self._state.emit({"type": "stage_progress", "stage": stage, "criterion": criterion, "done": done, "total": total})

    def forward_new_issues(self) -> None:
        with self._lock:
            self._send_new_issues()

    def _send_new_issues(self) -> None:
        for issue in self._context.issues[self._issues_sent:]:
            stage = issue.stage
            criterion_label = CRITERION_ISSUE_LABEL.fullmatch(stage) if stage is not None else None
            if criterion_label is not None:
                criterion, stage = criterion_label.groups()
            else:   # not named by the engine yet (it names a criterion's issues when the criterion is done): the criterion running
                criterion = self._criterion if stage in ANALYSIS_STAGES else None
            self._state.emit({"type": "issue", "stage": stage, "criterion": criterion, "code": issue.code, "message": issue.message})
        self._issues_sent = len(self._context.issues)


def _run_failed_event(error_type: str, message: str, field_errors: list[dict] | None = None) -> dict:
    return {"type": "run_failed", "error_type": error_type, "message": message, "field_errors": field_errors or []}


def _result_files(run_folder: Path) -> list[str]:
    """The result files that exist, as paths relative to the run folder: the exported mesh, the plates and the report."""
    candidates = [*sorted((run_folder / "exporting").glob(EXPORTED_MESH_PATTERN)), *sorted((run_folder / "massing").glob(MASSING_RESULT_PATTERN)),
                  *(run_folder / path for path in RESULT_FILES)]
    return [path.relative_to(run_folder).as_posix() for path in candidates if path.is_file()]
