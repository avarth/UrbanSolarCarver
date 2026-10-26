"""Requests the engine answers, shared by every transport.

A transport (the pickle daemon today, an HTTP service later) receives a
message; this module turns it into an engine call and a reply:

* :func:`parse_engine_request` validates a message into one of the request
  models, or raises :class:`~urbansolarcarver.errors.MalformedEngineRequest`.
* :func:`config_for_engine_request` builds the request's config: from its
  YAML file with the overrides on top or, without a file, from the starting
  values of the mode the overrides name.
* :func:`handle_engine_request` runs a request inside a run context and
  returns a reply model; engine errors propagate to the caller.
* :func:`error_reply_for` turns an exception into an error reply.
* :func:`answer_engine_message` does all of this for transports that carry
  plain dicts, and never raises.

Stopping a transport is the transport's own business, not a request here.
Importing this module does not import torch: the stage functions are
imported when a request runs.
"""
from __future__ import annotations

import logging
import os
import typing
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from .chain_config import ChainConfig, is_chain_file, load_chain
from .errors import ConfigError, ConfigFieldError, MalformedEngineRequest
from .load_config import (
    build_config_from_mode_starting_values, load_config, parse_overrides, user_config,
)
from .run_context import RunContext, run_context
from .stage_settings import PIPELINE_STAGES, stage_folder

_log = logging.getLogger(__name__)

# What this engine can do that older ones could not, named in the ping reply so a client can tell.
ENGINE_FEATURES = ("run_after",)        # RunRequest.after

# ``key=value`` strings, or a mapping of typed values.
Overrides = Union[List[str], Dict[str, Any]]


# ---- Requests ---------------------------------------------------------------

class _EngineRequest(BaseModel):
    # Keys a request does not use are ignored, as the daemon always did, so
    # clients that send extra keys keep working.
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class PingRequest(_EngineRequest):
    """Is the engine there?  Answered with its process id."""
    cmd: Literal["ping"]


class RunRequest(_EngineRequest):
    """Run the stages needed to produce *produce* in *run_folder*
    (:func:`urbansolarcarver.api.run_pipeline`).  Without *config* (a YAML
    path) the overrides must name the mode.  When *config* is a chain file
    (a ``criteria:`` list) the request runs :func:`urbansolarcarver.api.run_chain`
    and the overrides set shared settings only.  *trace_criteria* (chain only,
    ignored otherwise) lists the criterion ids to trace again when starting
    from preprocessing; the others reuse their existing preprocessing.
    *threshold_from_criterion* (chain only) names the criterion thresholding starts at:
    with *trace_criteria*, one that comes before the first traced one; when starting
    from thresholding, any one, the criteria before it keeping their thresholding.
    *after* (a config without ``criteria:``, a run that starts at thresholding) is the
    previous criterion's thresholding folder or manifest: thresholding then decides only
    among the voxels that criterion kept.  A chain file or an earlier ``start_from``
    refuses it."""
    cmd: Literal["run"]
    produce: List[str]
    run_folder: str
    start_from: str = PIPELINE_STAGES[0]
    config: Optional[str] = None
    overrides: Overrides = Field(default_factory=list)
    trace_criteria: Optional[List[str]] = None
    threshold_from_criterion: Optional[str] = None
    after: Optional[str] = None


class StageRequest(_EngineRequest):
    """Run one stage.  Every stage except preprocessing reads
    *upstream_output*, the upstream stage's folder or manifest, sent under
    the key ``from``.  *out_dir* defaults to ``<config out_dir>/<stage>``.
    *after* (thresholding only) is the previous criterion's thresholding
    folder or manifest: the stage then decides only among the voxels that
    criterion kept."""
    cmd: Literal["preprocessing", "thresholding", "exporting", "massing"]
    config: str
    overrides: Overrides = Field(default_factory=list)
    out_dir: Optional[str] = None
    upstream_output: Optional[str] = Field(None, alias="from")
    after: Optional[str] = None


class RunPipelineRequest(_EngineRequest):
    """Run preprocessing, thresholding and exporting into *out_dir* (default:
    the config's ``out_dir``).  Grasshopper definitions saved before the
    ``run`` command existed still send it."""
    cmd: Literal["run_pipeline"]
    config: str
    overrides: Overrides = Field(default_factory=list)
    out_dir: Optional[str] = None


class SimulateWeightsRequest(_EngineRequest):
    """Write a simulated-weights file for benefit mode; *archetype* is a
    mapping or the path of a YAML file holding one."""
    cmd: Literal["simulate_weights"]
    epw: str
    archetype: Union[str, Dict[str, Any]]
    out: str
    internal_gains_w_m2: Optional[float] = None
    eps: float = 1.0


_REQUEST_MODELS = (PingRequest, RunRequest, StageRequest, RunPipelineRequest, SimulateWeightsRequest)
EngineRequest = typing.Annotated[Union[_REQUEST_MODELS], Field(discriminator="cmd")]
_ENGINE_REQUEST_ADAPTER = TypeAdapter(EngineRequest)
_COMMANDS = frozenset(name for model in _REQUEST_MODELS
                      for name in typing.get_args(model.model_fields["cmd"].annotation))


# ---- Replies ----------------------------------------------------------------

class IssueReply(BaseModel):
    """A condition the run reported (see ``run_context.Issue``)."""
    stage: Optional[str]
    code: str
    message: str


class PingReply(BaseModel):
    status: Literal["ok"] = "ok"
    pid: int
    features: List[str] = Field(default_factory=list)


class RunReply(BaseModel):
    """The folders of the stages that ran, the manifest of the last of them,
    the produced files, and the issues of the run."""
    status: Literal["ok"] = "ok"
    stage_folders: Dict[str, str]
    manifest: str
    issues: List[IssueReply]
    export_path: Optional[str] = None
    plates_path: Optional[str] = None
    mesh_path: Optional[str] = None
    export_mesh_path: Optional[str] = None     # the plates in final_mesh_format (mesh_path itself for OBJ)


class StageReply(BaseModel):
    """What one stage (or the legacy ``run_pipeline`` command) produced."""
    status: Literal["ok"] = "ok"
    issues: List[IssueReply]
    manifest: Optional[str] = None
    export_path: Optional[str] = None
    plates_path: Optional[str] = None
    mesh_path: Optional[str] = None
    export_mesh_path: Optional[str] = None     # the plates in final_mesh_format (mesh_path itself for OBJ)


class SimulateWeightsReply(BaseModel):
    status: Literal["ok"] = "ok"
    artifact: str
    preview: Optional[str] = None


class ConfigFieldErrorReply(BaseModel):
    field: Optional[str]
    message: str


class ErrorReply(BaseModel):
    """A failed request: the exception text and class name and, for a
    configuration error, each invalid field."""
    status: Literal["error"] = "error"
    error: str
    error_type: str
    config_errors: Optional[List[ConfigFieldErrorReply]] = None


EngineReply = Union[PingReply, RunReply, StageReply, SimulateWeightsReply, ErrorReply]


# ---- Parsing and config ------------------------------------------------------

def parse_engine_request(message: Any) -> EngineRequest:
    """Validate *message* (a mapping with a ``cmd`` key) into a request model.

    Raises
    ------
    MalformedEngineRequest
        If *message* is not a mapping, names an unknown command, lacks a
        required key or holds a value of the wrong type.
    """
    if not isinstance(message, Mapping):
        raise MalformedEngineRequest("Expected a dict message")
    command = message.get("cmd")
    if command not in _COMMANDS:
        raise MalformedEngineRequest(f"Unknown command: {command!r}")
    try:
        request = _ENGINE_REQUEST_ADAPTER.validate_python(dict(message))
    except ValidationError as exc:
        raise MalformedEngineRequest(_describe_invalid_request(command, exc)) from exc
    if isinstance(request, StageRequest) and request.cmd != "preprocessing" \
            and request.upstream_output is None:
        raise MalformedEngineRequest(f"Missing required keys for {command!r}: ['from']")
    return request


def _describe_invalid_request(command: str, exc: ValidationError) -> str:
    missing = [str(error["loc"][-1]) for error in exc.errors() if error["type"] == "missing"]
    if missing:
        return f"Missing required keys for {command!r}: {missing}"
    problems = "; ".join(f"{'.'.join(map(str, error['loc'][1:]))}: {error['msg']}"
                         for error in exc.errors())
    return f"Invalid request for {command!r}: {problems}"


def config_for_engine_request(request: Union[RunRequest, StageRequest, RunPipelineRequest]) -> user_config:
    """The validated config of *request*.

    With ``config`` (a YAML path) the file is loaded with the overrides on
    top; without it, the config is built from the starting values of the
    mode the overrides name.  Raises ConfigError for invalid settings and
    FileNotFoundError for a missing YAML file.
    """
    if request.config is not None:
        return load_config(request.config, request.overrides)
    return build_config_from_mode_starting_values(parse_overrides(request.overrides))


# ---- Handling ------------------------------------------------------------------

def handle_engine_request(request: EngineRequest, session, context: Optional[RunContext] = None) -> EngineReply:
    """Run *request* and return its reply; engine errors propagate.

    *session* is the transport's CarverSession (anything with a
    ``release_memory`` method); unused GPU memory is released after every
    run or stage request, successful or not, while the session cache
    stays.  *context* receives progress, issues and cancellation; a new one
    is used when it is None.
    """
    if isinstance(request, PingRequest):
        return PingReply(pid=os.getpid(), features=list(ENGINE_FEATURES))
    if isinstance(request, SimulateWeightsRequest):
        return _simulate_weights(request)
    context = context if context is not None else RunContext()
    try:
        with run_context(context):
            # The config is built inside the run context, so the issues its
            # validators report reach the reply.
            if isinstance(request, RunRequest) and request.config is not None and is_chain_file(request.config):
                _refuse_after(request, "after cannot be used with a config that has criteria: the chain links its criteria itself.")
                return _run_chain(request, load_chain(request.config, request.overrides), context)
            config = config_for_engine_request(request)
            if isinstance(request, RunRequest):
                if request.start_from != "thresholding":
                    _refuse_after(request, f"after needs a run that starts at thresholding, but this run starts at {request.start_from}.")
                return _run(request, config, context)
            if isinstance(request, RunPipelineRequest):
                return _run_pipeline(request, config, context)
            return _run_stage(request, config, context)
    finally:
        session.release_memory()


def _issue_replies(context: RunContext) -> List[IssueReply]:
    return [IssueReply(stage=issue.stage, code=issue.code, message=issue.message)
            for issue in context.issues]


def _refuse_after(request: RunRequest, message: str) -> None:
    """Raise ConfigError with *message* when *request* carries ``after``; a ``start_from`` that is no stage is left to
    the run, which reports it first."""
    if request.after is not None and request.start_from in PIPELINE_STAGES:
        raise ConfigError(message, [ConfigFieldError("after", message)])


def _run(request: RunRequest, config: user_config, context: RunContext) -> RunReply:
    from . import api
    result = api.run_pipeline(config, request.run_folder, produce=request.produce,
                              start_from=request.start_from, context=context, after=request.after)
    ran = [stage for stage in PIPELINE_STAGES if getattr(result, stage) is not None]
    return _run_reply({stage: stage_folder(request.run_folder, stage) for stage in ran}, result, context)


def _run_chain(request: RunRequest, chain: ChainConfig, context: RunContext) -> RunReply:
    """Run a chain; the reply is a normal run's, filled from the last criterion's folders and the chain's
    exporting and massing."""
    from . import api
    from .api_core.chain import criterion_folder
    result = api.run_chain(chain, request.run_folder, produce=request.produce,
                           start_from=request.start_from, context=context, trace=request.trace_criteria,
                           threshold_from=request.threshold_from_criterion)
    last_id, last = chain.criteria[-1].id, result.criteria[-1]
    folders = {stage: criterion_folder(request.run_folder, last_id, stage)
               for stage in ("preprocessing", "thresholding") if getattr(last, stage) is not None}
    folders.update({stage: stage_folder(request.run_folder, stage)
                    for stage in ("exporting", "massing") if getattr(result, stage) is not None})
    return _run_reply(folders, result, context)


def _run_reply(folders: Dict[str, Path], result, context: RunContext) -> RunReply:
    """The reply for the stages that ran (*folders*, in stage order) of a result with ``exporting`` and ``massing``."""
    return RunReply(
        stage_folders={stage: str(folder) for stage, folder in folders.items()},
        manifest=str(list(folders.values())[-1] / "manifest.json"),
        issues=_issue_replies(context),
        export_path=str(result.exporting.export_path) if result.exporting else None,
        plates_path=str(result.massing.plates_path) if result.massing else None,
        mesh_path=str(result.massing.mesh_path) if result.massing else None,
        export_mesh_path=str(result.massing.export_mesh_path) if result.massing else None,
    )


def _run_pipeline(request: RunPipelineRequest, config: user_config, context: RunContext) -> StageReply:
    from . import api
    result = api.run_pipeline(config, request.out_dir or config.out_dir, context=context)
    return StageReply(export_path=str(result.exporting.export_path), issues=_issue_replies(context))


def _run_stage(request: StageRequest, config: user_config, context: RunContext) -> StageReply:
    from . import api
    out_dir = request.out_dir or stage_folder(config.out_dir, request.cmd)
    if request.cmd == "preprocessing":
        result = api.preprocessing(config, out_dir)
        return StageReply(manifest=str(result.out_dir / "manifest.json"), issues=_issue_replies(context))
    if request.cmd == "thresholding":
        result = api.thresholding(request.upstream_output, config, out_dir, after=request.after)
        return StageReply(manifest=str(result.out_dir / "manifest.json"), issues=_issue_replies(context))
    if request.cmd == "massing":
        result = api.massing(request.upstream_output, config, out_dir)
        return StageReply(manifest=str(result.out_dir / "manifest.json"), plates_path=str(result.plates_path),
                          mesh_path=str(result.mesh_path), export_mesh_path=str(result.export_mesh_path),
                          issues=_issue_replies(context))
    result = api.exporting(request.upstream_output, config, out_dir)
    return StageReply(export_path=str(result.export_path), issues=_issue_replies(context))


def _simulate_weights(request: SimulateWeightsRequest) -> SimulateWeightsReply:
    """Generate a simulated-weights file (no config or GPU session needed)."""
    from .simulated_weights import generate_simulated_weights

    archetype = request.archetype
    if isinstance(archetype, str):  # the path of a YAML file holding the mapping
        import yaml
        archetype = yaml.safe_load(Path(archetype).read_text(encoding="utf-8"))
        if not isinstance(archetype, dict):
            raise ValueError(f"archetype file {request.archetype!r} does not contain a mapping")
    path = Path(generate_simulated_weights(
        request.epw, archetype, request.out,
        internal_gains_w_m2=request.internal_gains_w_m2, eps=request.eps,
    ))
    preview = path.with_suffix(".png")
    return SimulateWeightsReply(artifact=str(path), preview=str(preview) if preview.is_file() else None)


# ---- Errors and dict transports --------------------------------------------------

def error_reply_for(exc: BaseException) -> ErrorReply:
    """The error reply for *exc*: its text, its class name and, for a
    ConfigError, the invalid fields."""
    config_errors = None
    if isinstance(exc, ConfigError):
        config_errors = [ConfigFieldErrorReply(field=e.field, message=e.message) for e in exc.errors]
    return ErrorReply(error=f"{type(exc).__name__}: {exc}", error_type=type(exc).__name__,
                      config_errors=config_errors)


def answer_engine_message(message: Any, session) -> Dict[str, Any]:
    """Parse and run *message* and return the reply as a dict; never raises.

    Any failure becomes an error reply; failures other than a malformed
    request are also logged with their traceback.  Reply fields that are
    None are left out.
    """
    try:
        reply = handle_engine_request(parse_engine_request(message), session)
    except MalformedEngineRequest as exc:
        reply = error_reply_for(exc)
    except Exception as exc:
        _log.exception("Engine request failed")
        reply = error_reply_for(exc)
    return reply.model_dump(exclude_none=True)
