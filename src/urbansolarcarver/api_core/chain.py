"""``run_chain``: criteria carved in sequence on one voxel grid, then exporting and massing from the last."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Collection, Iterable, Optional, Union

from ..chain_config import ChainConfig, load_chain
from ..run_context import Issue, RunContext, report_progress, run_context, stage_context
from ..stage_settings import PIPELINE_STAGES, stage_folder, stages_needed_for
from ._stage_io import load_upstream
from .exporting import ExportingResult, exporting
from .massing import MassingResult, massing
from .preprocessing import preprocessing
from .thresholding import thresholding

if TYPE_CHECKING:  # api.py imports this module, so PipelineResult is imported where it is used
    from ..api import PipelineResult

# The stages that run once per criterion, and the folder under the run folder that holds each criterion's folders.
_CRITERION_STAGES = ("preprocessing", "thresholding")
CRITERIA_FOLDER = "criteria"
CHAIN_FILE = "chain.json"


@dataclass(frozen=True)
class ChainResult:
    """What one :func:`run_chain` call produced.

    ``criteria`` has one :class:`~urbansolarcarver.PipelineResult` per criterion, in order, holding the
    preprocessing and thresholding Results of the stages that ran in this call (None for a stage that did not) and the
    issues reported while that criterion ran. ``exporting`` and ``massing`` are built from the last criterion and are
    None when they were not produced. ``issues`` are all the issues of the call, in the order they were noticed.
    """
    criteria: tuple["PipelineResult", ...]
    exporting: Optional[ExportingResult]
    massing: Optional[MassingResult]
    issues: tuple[Issue, ...]


def criterion_folder(run_folder: Union[Path, str], criterion_id: str, stage: str) -> Path:
    """The folder of *stage* for one criterion: ``<run_folder>/criteria/<id>/<stage>``."""
    return Path(run_folder) / CRITERIA_FOLDER / criterion_id / stage


def _name_the_criterion(context: RunContext, first_new_issue: int, criterion_id: str) -> None:
    """Re-label the issues the stages of one criterion reported, which carry only the stage's name, so that
    ``criterion 2 (thresholding)`` tells which of the criteria the issue is about."""
    for index in range(first_new_issue, len(context.issues)):
        issue = context.issues[index]
        if issue.stage in _CRITERION_STAGES:
            context.issues[index] = replace(issue, stage=f"criterion {criterion_id} ({issue.stage})")


def run_chain(
    chain: Union[ChainConfig, str, Path],
    out_dir: Union[str, Path, None] = None,
    produce: Iterable[str] = ("exporting",),
    start_from: str = "preprocessing",
    context: Optional[RunContext] = None,
    trace: Optional[Collection[str]] = None,
    threshold_from: Optional[str] = None,
) -> ChainResult:
    """Carve the criteria of *chain* one after the other on one voxel grid, then build from the last.

    Criterion ``<id>`` runs preprocessing into ``out_dir/criteria/<id>/preprocessing`` and thresholding into
    ``out_dir/criteria/<id>/thresholding``, deciding only among the voxels the previous criterion kept. Exporting and
    massing read the last criterion's thresholding and write ``out_dir/exporting`` and ``out_dir/massing``, with the
    settings the criteria share. ``out_dir/criteria/chain.json`` lists the criteria and the thresholding run of each,
    and the run report has a "Criteria" section.

    Parameters
    ----------
    chain : ChainConfig | str | Path
        A loaded chain, or the path of a YAML file with a ``criteria:`` list.
    out_dir : str | Path | None
        The run folder. Default: the ``out_dir`` of the chain's shared settings.
    produce : iterable of str
        Stages wanted, as for :func:`~urbansolarcarver.run_pipeline`.
    start_from : str
        ``"preprocessing"`` traces every criterion. ``"thresholding"`` reads each criterion's existing preprocessing
        folder and thresholds the chain again. ``"exporting"`` and ``"massing"`` read the last criterion's existing
        thresholding folder.
    context : RunContext | None
        Progress callback and cancel flag for the run. Progress is reported under ``criterion <id>`` for the
        criteria, and the issues of a criterion's stages are named ``criterion <id> (<stage>)``. Without a context,
        one that also forwards issues to ``warnings`` is created.
    trace : collection of str | None
        With ``start_from="preprocessing"``: the ids of the criteria to trace again. The others read their existing
        ``criteria/<id>/preprocessing`` folder, and every criterion from the first traced one on is thresholded
        again (the ones before it keep their thresholding, which the first thresholded one decides after).
        Default: trace every criterion. Ignored for the other values of *start_from*.
    threshold_from : str | None
        With ``start_from="preprocessing"``: the id of a criterion to threshold again even when it comes before the first
        traced one (its preprocessing, which was not traced, is read as it is). Thresholding then starts at the earlier of
        this criterion and the first traced one. Default: start at the first traced criterion. Ignored for the other
        values of *start_from*.

    Returns
    -------
    ChainResult
        The Results of each stage that ran (None for the others) and the issues of the call.

    Raises
    ------
    ValueError
        If *produce* is empty or names an unknown stage, *start_from* is not on the path to a produced stage, or
        *trace* names no criterion of the chain, or *threshold_from* names none.
    StageChainError
        If a folder to read before ``start_from`` (or the preprocessing folder of a criterion that *trace* leaves
        out) has no usable output; the message names the stage to re-run.
    RunCancelled
        If the context is cancelled; stages that finished keep their output.
    """
    from ..api import PipelineResult  # here, not at the top: api.py imports this module

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

    issues_before = len(context.issues)
    criteria_results = []
    exporting_result = massing_result = None
    with run_context(context):
        if not isinstance(chain, ChainConfig):
            # Loaded inside the context, so the config validators' issues are part of this call's issues.
            chain = load_chain(str(chain))
        run_folder = Path(out_dir) if out_dir is not None else Path(chain.shared.out_dir)
        criteria = chain.criteria
        stages_to_run = path[path.index(start_from):]
        ran = [stage for stage in _CRITERION_STAGES if stage in stages_to_run]
        if trace is not None and start_from == "preprocessing" and not {c.id for c in criteria} & set(trace):
            raise ValueError(f"trace names no criterion of the chain (ids {[c.id for c in criteria]}): {sorted(trace)}")
        if threshold_from is not None and start_from == "preprocessing" and threshold_from not in {c.id for c in criteria}:
            raise ValueError(f"threshold_from names no criterion of the chain (ids {[c.id for c in criteria]}): {threshold_from!r}")
        if "thresholding" in ran:
            # A run that stops before the last criterion must not leave a list that names the earlier run.
            (run_folder / CRITERIA_FOLDER / CHAIN_FILE).unlink(missing_ok=True)

        previous = None
        thresholding_run_ids = []
        thresholding_started = False
        for position, criterion in enumerate(criteria, start=1):
            with stage_context(f"criterion {criterion.id}"):
                context.raise_if_cancelled()
                report_progress(position - 1, len(criteria))
                first_new_issue = len(context.issues)
                pre = thr = None
                pre_folder = criterion_folder(run_folder, criterion.id, "preprocessing")
                thr_folder = criterion_folder(run_folder, criterion.id, "thresholding")
                if "preprocessing" in ran and (trace is None or criterion.id in trace):
                    pre = preprocessing(criterion.config, pre_folder)
                    thresholding_started = True
                if criterion.id == threshold_from:
                    thresholding_started = True
                if "thresholding" in ran and (thresholding_started or "preprocessing" not in ran):
                    thr = thresholding(pre if pre is not None else pre_folder, criterion.config, thr_folder,
                                       after=previous)
                # A criterion that is not thresholded keeps its thresholding folder, which the next one reads.
                previous = thr if thr is not None else thr_folder
                if "thresholding" in ran:
                    thresholding_run_ids.append(
                        thr.run_id if thr is not None else load_upstream(thr_folder, "thresholding").manifest.run_id)
                _name_the_criterion(context, first_new_issue, criterion.id)
                report_progress(position, len(criteria))
            criteria_results.append(PipelineResult(
                preprocessing=pre, thresholding=thr, exporting=None, massing=None,
                issues=tuple(context.issues[first_new_issue:])))

        if "thresholding" in ran:
            _write_chain_file(run_folder, chain, thresholding_run_ids)

        last = previous
        for stage, function in (("exporting", exporting), ("massing", massing)):
            if stage not in stages_to_run:
                continue
            with stage_context(stage):
                report_progress(0, 1)
                context.raise_if_cancelled()
                result = function(last, chain.shared, stage_folder(run_folder, stage))
                report_progress(1, 1)
            if stage == "exporting":
                exporting_result = result
            else:
                massing_result = result
    return ChainResult(
        criteria=tuple(criteria_results),
        exporting=exporting_result,
        massing=massing_result,
        issues=tuple(context.issues[issues_before:]),
    )


def _write_chain_file(run_folder: Path, chain: ChainConfig, thresholding_run_ids) -> None:
    """``criteria/chain.json``: each criterion's id, display name, mode and thresholding run, for the run report."""
    listed = [{"id": criterion.id, "name": criterion.name, "mode": criterion.config.mode,
               "thresholding_run_id": run_id}
              for criterion, run_id in zip(chain.criteria, thresholding_run_ids)]
    folder = run_folder / CRITERIA_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    (folder / CHAIN_FILE).write_text(json.dumps({"criteria": listed}, indent=2), encoding="utf-8")
