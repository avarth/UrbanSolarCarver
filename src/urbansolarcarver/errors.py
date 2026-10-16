"""Exception and warning classes shared across the package.

Standard library only. Configuration, input and stage-chain errors also
derive from ``ValueError`` so callers that already catch ``ValueError`` keep
working.
"""
from __future__ import annotations

from dataclasses import dataclass


class UrbanSolarCarverError(Exception):
    """Base class of every error raised on purpose by this package."""


@dataclass(frozen=True)
class ConfigFieldError:
    """One configuration problem: the field it concerns and what is wrong.

    ``field`` is ``None`` for checks that involve several fields at once.
    """
    field: str | None
    message: str


class ConfigError(UrbanSolarCarverError, ValueError):
    """The configuration is invalid; ``errors`` lists each problem."""

    def __init__(self, message: str, errors: list[ConfigFieldError] | None = None):
        super().__init__(message)
        self.errors: list[ConfigFieldError] = list(errors) if errors else []


class InputError(UrbanSolarCarverError, ValueError):
    """An input file or input data is missing, unreadable or unusable."""


class StageChainError(UrbanSolarCarverError, ValueError):
    """A stage's upstream output is missing, stale or from a different run."""


class MalformedEngineRequest(UrbanSolarCarverError, ValueError):
    """A request to the engine is not a mapping, names an unknown command,
    or lacks or misuses a key (see ``engine_requests``)."""


class RunCancelled(UrbanSolarCarverError):
    """The run was cancelled through its run context."""


class UrbanSolarCarverWarning(UserWarning):
    """Non-fatal configuration warning."""
