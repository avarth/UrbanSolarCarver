"""Run context: collects issues, reports progress and carries cancellation.

Standard library only. A :class:`RunContext` is activated for a block with
:func:`run_context`; engine code then calls :func:`report_issue` and
:func:`report_progress` without passing the context around. Without an
active context an issue is emitted as a warning, so direct calls to engine
functions behave as before.
"""
from __future__ import annotations

import contextlib
import contextvars
import threading
import warnings
from dataclasses import dataclass
from typing import Callable, Iterator

from .errors import RunCancelled, UrbanSolarCarverWarning


@dataclass(frozen=True)
class Issue:
    """A user-facing condition noticed during a run (not an error)."""
    stage: str | None
    code: str
    message: str


class RunContext:
    """Issues, progress callback and cancel flag of one run."""

    def __init__(
        self,
        on_progress: Callable[[str | None, int, int], None] | None = None,
        forward_issues_to_warnings: bool = False,
    ):
        self.on_progress = on_progress
        self.forward_issues_to_warnings = forward_issues_to_warnings
        self.issues: list[Issue] = []
        self.current_stage: str | None = None
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        """Ask the run to stop at its next cancellation check."""
        self.cancel_event.set()

    def raise_if_cancelled(self) -> None:
        """Raise :class:`RunCancelled` when :meth:`cancel` has been called."""
        if self.cancel_event.is_set():
            raise RunCancelled("The run was cancelled.")

    def issues_of(self, stage: str) -> tuple[Issue, ...]:
        """The issues reported while *stage* was the current stage."""
        return tuple(issue for issue in self.issues if issue.stage == stage)


_ACTIVE_CONTEXT: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar(
    "urbansolarcarver_run_context", default=None)


@contextlib.contextmanager
def run_context(context: RunContext) -> Iterator[RunContext]:
    """Make *context* the active run context for the block."""
    token = _ACTIVE_CONTEXT.set(context)
    try:
        yield context
    finally:
        _ACTIVE_CONTEXT.reset(token)


def active_context() -> RunContext | None:
    """The run context active in this thread of execution, if any."""
    return _ACTIVE_CONTEXT.get()


def report_issue(code: str, message: str) -> None:
    """Record an issue on the active context, or warn when there is none."""
    context = _ACTIVE_CONTEXT.get()
    if context is not None:
        context.issues.append(Issue(context.current_stage, code, message))
    if context is None or context.forward_issues_to_warnings:
        warnings.warn(message, UrbanSolarCarverWarning, stacklevel=3)


def report_progress(done: int, total: int) -> None:
    """Tell the active context's progress callback how far the stage is."""
    context = _ACTIVE_CONTEXT.get()
    if context is not None and context.on_progress is not None:
        context.on_progress(context.current_stage, done, total)


@contextlib.contextmanager
def stage_context(stage: str) -> Iterator[RunContext]:
    """Run a block as *stage*: yield the active context with its stage set.

    With no context active, a new one that forwards its issues to warnings
    is activated for the block, so a stage called directly still warns.
    """
    context = _ACTIVE_CONTEXT.get()
    if context is None:
        context = RunContext(forward_issues_to_warnings=True)
        token = _ACTIVE_CONTEXT.set(context)
    else:
        token = None
    previous_stage = context.current_stage
    context.current_stage = stage
    try:
        yield context
    finally:
        context.current_stage = previous_stage
        if token is not None:
            _ACTIVE_CONTEXT.reset(token)
