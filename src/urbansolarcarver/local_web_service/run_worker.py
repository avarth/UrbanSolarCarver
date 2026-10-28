"""The run worker: one job at a time, a pipeline run or a simulation, on a background thread, with an event log the browser reads.

``RunWorker.start`` chooses the stages (see ``stage_records``), removes their records, and starts a thread that
calls the engine, after it calculates the typical building's weights when a criterion it preprocesses needs them and they are
missing or out of date (``typical_building.py``). ``RunWorker.start_simulation`` starts a thread that runs the studies that can
run (simulation.py); it never reads or writes a stage record. Either thread appends events to the job's ``RunState``; the
WebSocket handler reads them with ``RunState.wait_for_events``, which also serves a reader that connects after the run began or
finished.
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

from ..errors import ConfigError, InputError, RunCancelled, StageChainError
from ..run_context import RunContext
from ..stage_settings import PIPELINE_STAGES
from . import simulation, stored_files, test_surfaces, typical_building
from .api_models import StartRunReply
from .projects import RUN_FOLDER, ProjectError, ProjectStore, naming_criterion
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


class NoStudyCanRun(ProjectError):
    """A simulation has no study that can run; the message names each study and why it cannot."""

    def __init__(self, message: str):
        super().__init__(message, status_code=422)


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
    """Runs one job at a time, a pipeline run or a simulation, of any project; the compute session is created at the first job and
    kept. ``_start_lock`` makes the check of ``_active`` and its setting one step; the job's thread clears ``_active`` when it ends."""

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

        Raises RunConflict when a run is active, MissingInputs when the project lacks input files, CriterionConfigError (a ConfigError
        naming the criterion) when the stored settings of a criterion that is on are not valid (a bypassed one takes no part),
        ValueError for an unknown stage name in *produce*.
        """
        with self._store.project_lock(name), self._start_lock:
            if self._active is not None:
                raise RunConflict(self._active.state.project)
            self._store.migrate_to_criteria(name)
            self._store.rebuild_joined_test_surfaces_without_normals(name)
            self._store.refresh_changed_inputs(name)      # a file changed in the folder is run with, and dates what was built on the old one
            stored_files.refuse_missing_files(self._store, name, "run")
            settings = run_settings(self._store, name)
            for criterion_id, criterion_settings in settings.criteria.items():
                with naming_criterion(criterion_id):    # the refusal says whose settings it is
                    self._store.config_from_settings(name, criterion_settings)
            absent_roles = missing_inputs(self._store, name)
            if absent_roles:
                raise MissingInputs(absent_roles, {criterion.id: criterion.name for criterion in self._store.criteria(name)})
            choice = choose_stages(self._store, name, produce)
            if not choice.stages:
                return StartRunReply(status="up_to_date", run_id=None, stages=[], criterion_stages={})
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

    def start_simulation(self, name: str) -> RunState:
        """Start a simulation of the project's studies that can run (simulation.refusal_of), one engine request each, in list order.

        Raises RunConflict when any job is active, NoStudyCanRun (422) when no study can run, ProjectError 404 for an unknown project.
        """
        with self._store.project_lock(name), self._start_lock:
            if self._active is not None:
                raise RunConflict(self._active.state.project)
            self._store.migrate_to_criteria(name)      # a project of an earlier version becomes a chain first, as before a pipeline run
            self._store.refresh_changed_inputs(name)
            stored_files.refuse_missing_files(self._store, name, "simulation")
            requests, refusals = [], []
            for study in self._store.studies(name):
                reason = simulation.refusal_of(self._store, name, study)
                if reason is None:
                    requests.append((study.id, simulation.study_request(self._store, name, study, self._device)))
                else:
                    refusals.append((study, reason))
            if not requests:
                raise NoStudyCanRun(simulation.no_study_can_run_message(refusals))
            state = RunState(uuid.uuid4().hex, name, [simulation.SIMULATE_STAGE])
            context = RunContext()
            forwarder = _StudyEventsForwarder(state, context)
            thread = threading.Thread(
                target=self._run_job, args=(state, context, forwarder, lambda: self._final_event_of_simulation(context, requests, forwarder)),
                name=f"simulate-{state.run_id}", daemon=True)
            self._run_states[state.run_id] = state
            self._active = _ActiveRun(state, context, thread)
            thread.start()
            return state

    def _run(self, state: RunState, context: RunContext, choice: StageChoice, settings: RunSettings) -> None:
        """The thread body of a pipeline run: run the engine and record the stages on success (see _run_job)."""
        self._run_job(state, context, _IssuesForwarder(state, context), lambda: self._final_event_of_run(state, context, choice, settings))

    def _run_job(self, state: RunState, context: RunContext, forwarder, final_event_of_job: Callable[[], dict]) -> None:
        """The thread body of a job: run it, forward its progress and issues as events, and end the event log with one final event.

        Whatever goes wrong while finishing, the worker is released and the readers get a final event: a job that
        could not end would block every later start.
        """
        context.on_progress = forwarder.forward_progress
        final_event = None
        try:
            final_event = final_event_of_job()
            forwarder.forward_new_issues()
        except Exception as error:
            _log.exception("Finishing a job of project '%s' failed", state.project)
            if final_event is None:
                final_event = _run_failed_event(type(error).__name__, str(error))
        finally:
            self._release_session_memory()
            self._active = None     # before the final event: a reader that sees the run end can start the next one
            state.finish(final_event or _run_failed_event("RunAborted", "The run stopped unexpectedly."))

    def _final_event_of_run(self, state: RunState, context: RunContext, choice: StageChoice, settings: RunSettings) -> dict:
        """Run the engine and give the event that ends the run, whether it finished, was cancelled or failed."""
        try:
            self._calculate_typical_building(state, context, choice, settings)
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

    def _final_event_of_simulation(self, context: RunContext, requests: list, forwarder: _StudyEventsForwarder) -> dict:
        """Run each study's request and give the event that ends the simulation. A study the engine refuses (too many test points,
        settings it does not accept) becomes an issue of that study and is kept as its refusal (simulation.record_refusal), and the
        others still run; a study that runs loses an earlier refusal. A cancel or another error ends the simulation."""
        try:
            if self._session is None:
                self._session = self._create_session()
            handler = self._handler()
            for study_id, request in requests:
                forwarder.start_study(study_id)
                try:
                    handler(request, self._session, context)
                except (InputError, ConfigError) as error:
                    forwarder.refused_by_the_engine(type(error).__name__, str(error))
                    simulation.record_refusal(request, str(error))
                else:
                    simulation.forget_refusal(request)
            return {"type": "run_finished", "stages": [simulation.SIMULATE_STAGE], "files": []}
        except RunCancelled:
            return {"type": "run_cancelled"}
        except Exception as error:
            _log.exception("A simulation failed")
            return _run_failed_event(type(error).__name__, str(error))

    def _calculate_typical_building(self, state: RunState, context: RunContext, choice: StageChoice, settings: RunSettings) -> None:
        """Calculate the typical building's weights, as they were when the run started, when a criterion the run preprocesses uses them
        and the weights file is missing or was calculated for another key; the progress is the stage typical_building, of no
        criterion. The engine reads the file only in preprocessing. An error of the calculation ends the run as any error does."""
        keys = {settings.weights_keys[criterion_id] for criterion_id, stages in choice.criterion_stages.items()
                if "preprocessing" in stages and criterion_id in settings.weights_keys}
        if not keys or not typical_building.needs_calculation(self._store, state.project, next(iter(keys))):
            return
        state.emit({"type": "stage_progress", "stage": typical_building.STAGE, "criterion": None, "done": 0, "total": 1})
        typical_building.calculate(self._store, state.project, settings.typical_building_values)
        state.emit({"type": "stage_progress", "stage": typical_building.STAGE, "criterion": None, "done": 1, "total": 1})
        context.raise_if_cancelled()

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


class _StudyEventsForwarder:
    """Turns the progress and issues of a simulation's engine requests into events that name the study being run.

    The engine reports a study's progress and issues under the stage ``check``; the events name the stage ``simulate`` and the
    study, and no criterion (``criterion`` is None, as in the events of a pipeline stage that belongs to none).
    """

    def __init__(self, state: RunState, context: RunContext):
        self._state = state
        self._context = context
        self._issues_sent = 0
        self._study: str | None = None
        self._lock = threading.Lock()   # progress can be reported from the engine's own threads

    def start_study(self, study_id: str) -> None:
        with self._lock:
            self._send_new_issues()
            self._study = study_id

    def forward_progress(self, _stage: str | None, done: int, total: int) -> None:
        with self._lock:
            self._send_new_issues()
            self._state.emit({"type": "stage_progress", "stage": simulation.SIMULATE_STAGE, "criterion": None, "study": self._study,
                              "done": done, "total": total})

    def forward_new_issues(self) -> None:
        with self._lock:
            self._send_new_issues()

    def refused_by_the_engine(self, code: str, message: str) -> None:
        with self._lock:
            self._send_new_issues()
            self._emit_issue(code, message)

    def _send_new_issues(self) -> None:
        for issue in self._context.issues[self._issues_sent:]:
            self._emit_issue(issue.code, issue.message)
        self._issues_sent = len(self._context.issues)

    def _emit_issue(self, code: str, message: str) -> None:
        self._state.emit({"type": "issue", "stage": simulation.SIMULATE_STAGE, "criterion": None, "study": self._study,
                          "code": code, "message": message})


def _run_failed_event(error_type: str, message: str, field_errors: list[dict] | None = None) -> dict:
    return {"type": "run_failed", "error_type": error_type, "message": message, "field_errors": field_errors or []}


def _result_files(run_folder: Path) -> list[str]:
    """The result files that exist, as paths relative to the run folder: the exported mesh, the plates and the report."""
    candidates = [*sorted((run_folder / "exporting").glob(EXPORTED_MESH_PATTERN)), *sorted((run_folder / "massing").glob(MASSING_RESULT_PATTERN)),
                  *(run_folder / path for path in RESULT_FILES)]
    return [path.relative_to(run_folder).as_posix() for path in candidates if path.is_file()]
