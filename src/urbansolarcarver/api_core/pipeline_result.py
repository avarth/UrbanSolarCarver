"""``PipelineResult``: what one ``run_pipeline`` call produced, and what ``run_chain`` holds per criterion.

It lives here, below ``api``, because both ``api.run_pipeline`` and ``api_core.chain.run_chain`` build it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..run_context import Issue
from .exporting import ExportingResult
from .massing import MassingResult
from .preprocessing import PreprocessingResult
from .thresholding import ThresholdingResult


@dataclass(frozen=True)
class PipelineResult:
    """What one :func:`~urbansolarcarver.run_pipeline` call produced.

    Each stage attribute holds the Result of a stage that ran in this call and
    is None for a stage that did not.  ``issues`` are the conditions reported
    during the call, from all stages, in the order they were noticed.
    """
    preprocessing: Optional[PreprocessingResult]
    thresholding: Optional[ThresholdingResult]
    exporting: Optional[ExportingResult]
    massing: Optional[MassingResult]
    issues: tuple[Issue, ...]
