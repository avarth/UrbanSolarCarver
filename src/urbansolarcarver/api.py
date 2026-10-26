"""Public API: the pipeline stages, the ``run_pipeline`` and ``run_chain`` sequencers, and config helpers.

Importing this module imports torch, and Warp if it is installed, through
``api_core``.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Union

from .chain_config import ChainConfig, Criterion, load_chain
from .load_config import build_config, load_config, user_config
from .api_core import (
    preprocessing, thresholding, exporting, massing,
    PreprocessingResult, ThresholdingResult, ExportingResult, MassingResult,
)
from .api_core.chain import ChainResult, run_chain
from .run_context import Issue, RunContext, report_progress, run_context, stage_context
from .stage_settings import PIPELINE_STAGES, stage_folder, stages_needed_for, stages_to_rerun

# The stage whose output each stage reads.
_UPSTREAM_STAGE = {
    "thresholding": "preprocessing",
    "exporting": "thresholding",
    "massing": "thresholding",
}


@dataclass(frozen=True)
class PipelineResult:
    """What one :func:`run_pipeline` call produced.

    Each stage attribute holds the Result of a stage that ran in this call and
    is None for a stage that did not.  ``issues`` are the conditions reported
    during the call, from all stages, in the order they were noticed.
    """
    preprocessing: Optional[PreprocessingResult]
    thresholding: Optional[ThresholdingResult]
    exporting: Optional[ExportingResult]
    massing: Optional[MassingResult]
    issues: tuple[Issue, ...]


def run_pipeline(
    config: Union[user_config, str, Path],
    out_dir: Union[str, Path],
    produce: Iterable[str] = ("exporting",),
    start_from: str = "preprocessing",
    context: Optional[RunContext] = None,
    after: Union[ThresholdingResult, str, Path, None] = None,
) -> PipelineResult:
    """Run the stages needed to produce *produce*, one after the other.

    Each stage writes into ``out_dir/<stage>``.  The sequencer runs
    ``start_from`` and every later stage on the path to a produced stage:
    preprocessing and thresholding come before exporting and massing, and
    producing both exporting and massing thresholds once.  A stage before
    ``start_from`` is not run; the stage after it reads the existing output
    in ``out_dir/<stage>``.

    Parameters
    ----------
    config : user_config | str | Path
        A validated config, or the path of a YAML config file.
    out_dir : str | Path
        The run folder that holds one subfolder per stage.
    produce : iterable of str
        Stages wanted: any of ``"preprocessing"``, ``"thresholding"``,
        ``"exporting"``, ``"massing"``.
    start_from : str
        The first stage to run; it must be on the path to a produced stage.
    context : RunContext | None
        Progress callback and cancel flag for the run.  Without one, a context
        that also forwards issues to ``warnings`` is created.
    after : ThresholdingResult | str | Path | None
        The previous criterion's thresholding result, folder or manifest,
        given to the thresholding stage as its ``after`` (see
        :func:`thresholding`).

    Returns
    -------
    PipelineResult
        The Result of each stage that ran (None for the others) and the issues
        of the call.

    Raises
    ------
    ValueError
        If *produce* is empty or names an unknown stage, or *start_from* is
        not on the path to a produced stage.
    StageChainError
        If the stage before ``start_from`` has no usable output in ``out_dir``.
    RunCancelled
        If the context is cancelled; stages that finished keep their output.
    """
    wanted = [produce] if isinstance(produce, str) else list(produce)
    if not wanted or not set(wanted) <= set(PIPELINE_STAGES):
        raise ValueError(
            f"produce must name at least one of {list(PIPELINE_STAGES)}, got {wanted}")
    path = stages_needed_for(wanted)
    if start_from not in path:
        raise ValueError(
            f"start_from must be one of the stages on the path to {wanted}: "
            f"{list(path)}; got {start_from!r}")
    if context is None:
        context = RunContext(forward_issues_to_warnings=True)

    stage_functions = {
        "preprocessing": lambda upstream, folder: preprocessing(config, folder),
        "thresholding": lambda upstream, folder: thresholding(upstream, config, folder, after=after),
        "exporting": lambda upstream, folder: exporting(upstream, config, folder),
        "massing": lambda upstream, folder: massing(upstream, config, folder),
    }
    results: dict = {}
    issues_before = len(context.issues)
    with run_context(context):
        if not isinstance(config, user_config):
            # Loaded inside the context, so the config validators' issues are
            # part of this call's issues.
            config = load_config(str(config))
        for stage in path[path.index(start_from):]:
            with stage_context(stage):
                report_progress(0, 1)
                context.raise_if_cancelled()
                upstream_stage = _UPSTREAM_STAGE.get(stage)
                upstream = results.get(upstream_stage) or (
                    stage_folder(out_dir, upstream_stage) if upstream_stage else None)
                results[stage] = stage_functions[stage](upstream, stage_folder(out_dir, stage))
                report_progress(1, 1)
    return PipelineResult(
        preprocessing=results.get("preprocessing"),
        thresholding=results.get("thresholding"),
        exporting=results.get("exporting"),
        massing=results.get("massing"),
        issues=tuple(context.issues[issues_before:]),
    )


__all__ = [
    "run_pipeline",
    "PipelineResult",
    "run_chain",
    "ChainResult",
    "stages_to_rerun",
    "preprocessing",
    "thresholding",
    "exporting",
    "massing",
    "PreprocessingResult",
    "ThresholdingResult",
    "ExportingResult",
    "MassingResult",
    "load_config",
    "build_config",
    "user_config",
]
