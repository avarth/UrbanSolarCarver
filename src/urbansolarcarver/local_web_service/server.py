"""The HTTP service of the local browser app: security checks, routes, run events and the built front-end.

``create_app`` builds the FastAPI application. One ProjectStore is shared by every route and the run worker,
so their per-project locks serialize requests that touch the same project. The routes are plain functions that
FastAPI runs on its thread pool; only the WebSocket handler is asynchronous, and it waits for events in a thread.
Importing this module does not import torch (the engine is imported when the first run starts).
"""
from __future__ import annotations

import asyncio
import hmac
import os
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, FastAPI, File, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from .. import __version__
from ..errors import ConfigError
from ..mode_registry import MODES
from ..pydantic_schemas import UserConfig
from ..stage_settings import PIPELINE_STAGES
from .api_models import (
    CancelRunReply, ConfigErrorReply, ConfigReply, ConfigValuesRequest, CreateProjectRequest, ErrorDetailReply,
    FieldErrorReply, HealthReply, InputFileInfo, InputFilesReply, MissingInputsReply, ModeInfo, ProjectDetail,
    ProjectSummary, RunSummary, SkyDome, StageStatusReply, StartRunReply, StartRunRequest, SunPath,
)
from .gpu_warm_up import GpuWarmUp
from .projects import MESH_ROLES, RUN_FOLDER, WEATHER_ROLE, GridOverBudget, ProjectError, ProjectStore, validate_project_name
from .run_summary import build_run_summary, build_sky_dome, sun_path_for_config
from .run_worker import MissingInputs, RunConflict, RunWorker
from .score_points import build_score_points
from .stage_records import stage_status

API_PREFIX = "/api"
TOKEN_HEADER = "X-USC-Token"
TOKEN_QUERY_PARAMETER = "token"
WEBSOCKET_CLOSE_UNAUTHORIZED = 4401     # no or wrong token
WEBSOCKET_CLOSE_FORBIDDEN = 4403        # Host header that is not this machine
WEBSOCKET_CLOSE_UNKNOWN_RUN = 4404
LAST_EVENT_TYPES = ("run_finished", "run_failed", "run_cancelled")
EVENT_WAIT_SECONDS = 1.0
DEFAULT_STATIC_FOLDER = Path(__file__).resolve().parent.parent / "ui_static"
NO_CACHE = {"Cache-Control": "no-cache"}    # a result file is rewritten by the next run, so the browser asks each time

_ERROR_RESPONSES = {
    409: {"model": ErrorDetailReply, "description": "A run of this project is active."},
    422: {"model": ErrorDetailReply, "description": "The request cannot be served as sent."},
}


class SecurityMiddleware:
    """Refuses a request whose Host header is not this machine's service address (403), and an API request without the token (401).

    The Host check stops a web page on another site from reaching the service through DNS rebinding; the
    token, which only the launch URL carries, stops other programs and pages from using the API.
    A WebSocket is refused before it is accepted, with a close code the app can tell apart.
    The token travels in a header for HTTP and in the query string for a WebSocket (a browser cannot set a header there).
    """

    def __init__(self, app: ASGIApp, token: str, port: int):
        self._app = app
        self._token = token.encode("utf-8")
        self._allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        if Headers(scope=scope).get("host", "").lower() not in self._allowed_hosts:
            await self._refuse(scope, receive, send, 403, WEBSOCKET_CLOSE_FORBIDDEN, "The Host header is not this service's address.")
        elif self._is_api_path(scope["path"]) and not self._has_token(scope):
            await self._refuse(scope, receive, send, 401, WEBSOCKET_CLOSE_UNAUTHORIZED, "The access token is missing or wrong.")
        else:
            await self._app(scope, receive, send)

    @staticmethod
    def _is_api_path(path: str) -> bool:
        return path == API_PREFIX or path.startswith(API_PREFIX + "/")

    def _has_token(self, scope: Scope) -> bool:
        if scope["type"] == "websocket":
            query = parse_qs(scope["query_string"].decode("latin-1"))
            provided = query.get(TOKEN_QUERY_PARAMETER, [""])[0]
        else:
            provided = Headers(scope=scope).get(TOKEN_HEADER, "")
        return hmac.compare_digest(provided.encode("utf-8"), self._token)

    @staticmethod
    async def _refuse(scope: Scope, receive: Receive, send: Send, status_code: int, websocket_close_code: int, message: str) -> None:
        if scope["type"] == "websocket":
            await receive()     # the connect message, which the protocol has the application read before it closes
            await send({"type": "websocket.close", "code": websocket_close_code, "reason": message})
        else:
            await JSONResponse({"detail": message}, status_code=status_code)(scope, receive, send)


def create_app(projects_folder: Path, token: str, port: int, device: str = "auto", static_folder: Path | None = None,
               worker: RunWorker | None = None, warm_up: GpuWarmUp | None = None) -> FastAPI:
    """The service for the projects under *projects_folder*.

    *worker* defaults to a RunWorker for *device*; a given worker brings its own ProjectStore, which the
    routes then use, so its projects folder is the one that counts. *warm_up* defaults to a GpuWarmUp that
    is never started (the state stays ``not_started``); ``usc ui`` passes one it has started.
    A *static_folder* without ``index.html`` (the front-end is not built) leaves the app with the API only.
    """
    store = worker.store if worker is not None else ProjectStore(projects_folder, device)
    worker = worker or RunWorker(store, device)
    warm_up = warm_up or GpuWarmUp(device)
    app = FastAPI(title="UrbanSolarCarver local service", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None, generate_unique_id_function=lambda route: route.name)
    app.add_middleware(SecurityMiddleware, token=token, port=port)
    _add_exception_handlers(app)
    app.include_router(_build_router(store, worker, warm_up), prefix=API_PREFIX)
    static_folder = DEFAULT_STATIC_FOLDER if static_folder is None else Path(static_folder)
    if (static_folder / "index.html").is_file():
        app.mount("/", StaticFiles(directory=static_folder, html=True), name="front_end")
    return app


def openapi_document() -> dict:
    """The OpenAPI document of the service, from which the front-end types are generated."""
    return create_app(Path("."), "x", 0).openapi()


def _add_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(MissingInputs)
    async def missing_inputs_handler(request: Request, error: MissingInputs) -> JSONResponse:
        reply = MissingInputsReply(detail=str(error), missing_inputs=error.roles)
        return JSONResponse(reply.model_dump(mode="json"), status_code=error.status_code)

    @app.exception_handler(ProjectError)    # includes RunConflict (409)
    async def project_error_handler(request: Request, error: ProjectError) -> JSONResponse:
        return JSONResponse(ErrorDetailReply(detail=str(error)).model_dump(mode="json"), status_code=error.status_code)

    @app.exception_handler(ConfigError)
    async def config_error_handler(request: Request, error: ConfigError) -> JSONResponse:
        field_errors = [FieldErrorReply(field=field_error.field, message=field_error.message) for field_error in error.errors]
        reply = ConfigErrorReply(
            field_errors=field_errors or [FieldErrorReply(field=None, message=str(error))],
            grid_plan=error.grid_plan if isinstance(error, GridOverBudget) else None)
        return JSONResponse(reply.model_dump(mode="json"), status_code=422)


def _same_project(first_name: str, second_name: str) -> bool:
    """Whether two request names address one project folder (Windows folder names ignore letter case)."""
    return validate_project_name(first_name).lower() == validate_project_name(second_name).lower()


def _build_router(store: ProjectStore, worker: RunWorker, warm_up: GpuWarmUp) -> APIRouter:
    router = APIRouter()

    def refuse_while_running(name: str) -> None:
        """Call with the project lock held: the worker records the settings and inputs it starts with, so they stay fixed during its run."""
        active_project = worker.active_project()
        if active_project is not None and _same_project(active_project, name):
            raise RunConflict(active_project)

    def project_detail(name: str) -> ProjectDetail:
        with store.project_lock(name):
            summary = store.summary(name)
            return ProjectDetail(
                name=summary.name, created=summary.created, modified=summary.modified, settings=store.read_settings(name),
                inputs={role: store.input_files(name, role) for role in (*MESH_ROLES, WEATHER_ROLE)},
                joined_bounds=store.joined_bounds(name), weather_location=store.weather_location(name),
                stage_status=StageStatusReply(stages=stage_status(store, name)))

    def run_folder_of(name: str) -> Path:
        return store.open(name) / RUN_FOLDER

    @router.get("/health")
    def health() -> HealthReply:
        return HealthReply(version=__version__, warm_up=warm_up.state())

    @router.get("/schema")
    def schema() -> dict:
        return UserConfig.model_json_schema()

    @router.get("/modes")
    def modes() -> list[ModeInfo]:
        return [ModeInfo(name=mode.name, description=mode.description, needs_epw=mode.needs_epw, needs_period=mode.needs_period,
                         experimental=mode.experimental, score_kind=mode.score_kind, weight_unit=mode.weight_unit,
                         starting_values=dict(mode.starting_values)) for mode in MODES.values()]

    @router.get("/projects")
    def list_projects() -> list[ProjectSummary]:
        return store.list()

    @router.post("/projects", responses={409: _ERROR_RESPONSES[409], 422: {"model": ConfigErrorReply}})
    def create_project(request: CreateProjectRequest) -> ProjectDetail:
        store.create(request.name, request.mode)
        return project_detail(request.name)

    @router.get("/projects/{name}")
    def open_project(name: str) -> ProjectDetail:
        return project_detail(name)

    @router.get("/projects/{name}/stage-status")
    def project_stage_status(name: str) -> StageStatusReply:
        return StageStatusReply(stages=stage_status(store, name))

    @router.get("/projects/{name}/sun-path")
    def sun_path(name: str) -> SunPath:
        return sun_path_for_config(store.load_project_config(name))

    @router.post("/projects/{name}/inputs/{role}", responses=_ERROR_RESPONSES)
    def add_input(name: str, role: str, file: UploadFile = File(...)) -> InputFilesReply:
        data = file.file.read()
        with store.project_lock(name):
            refuse_while_running(name)
            return store.add_input(name, role, file.filename or "", data)

    @router.get("/projects/{name}/inputs/{role}")
    def input_files(name: str, role: str) -> list[InputFileInfo]:
        return store.input_files(name, role)

    @router.get("/projects/{name}/inputs/{role}/{file_name}")
    def input_file(name: str, role: str, file_name: str) -> FileResponse:
        return FileResponse(store.input_file_path(name, role, file_name), headers=NO_CACHE)

    @router.delete("/projects/{name}/inputs/{role}/{file_name}", responses=_ERROR_RESPONSES)
    def remove_input(name: str, role: str, file_name: str) -> InputFilesReply:
        with store.project_lock(name):
            refuse_while_running(name)
            return store.remove_input(name, role, file_name)

    @router.put("/projects/{name}/config", responses={409: _ERROR_RESPONSES[409], 422: {"model": ConfigErrorReply}})
    def save_config(name: str, request: ConfigValuesRequest) -> ConfigReply:
        with store.project_lock(name):
            refuse_while_running(name)
            return store.write_config_from_values(name, request.values)

    @router.post("/projects/{name}/runs", responses={409: _ERROR_RESPONSES[409], 422: {"model": MissingInputsReply}})
    def start_run(name: str, request: StartRunRequest) -> StartRunReply:
        unknown_stages = [stage for stage in request.produce if stage not in PIPELINE_STAGES]
        if unknown_stages or not request.produce:
            raise ProjectError(f"'produce' names one or more of {', '.join(PIPELINE_STAGES)}; got {request.produce}.", status_code=422)
        return worker.start(name, request.produce)

    @router.post("/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> CancelRunReply:
        if worker.run_state(run_id) is None:
            raise ProjectError(f"There is no run '{run_id}'.", status_code=404)
        return CancelRunReply(cancelled=worker.cancel(run_id))

    @router.websocket("/runs/{run_id}/events")
    async def run_events(websocket: WebSocket, run_id: str) -> None:
        """Every event of the run from the first, then new ones as they come; closes after the run's last event."""
        run_state = worker.run_state(run_id)
        if run_state is None:
            await websocket.close(code=WEBSOCKET_CLOSE_UNKNOWN_RUN)
            return
        await websocket.accept()
        events_sent = 0
        try:
            while True:
                new_events = await asyncio.to_thread(run_state.wait_for_events, events_sent, EVENT_WAIT_SECONDS)
                for event in new_events:
                    await websocket.send_json(event)
                events_sent += len(new_events)
                if any(event["type"] in LAST_EVENT_TYPES for event in new_events):
                    break
            await websocket.close()
        except WebSocketDisconnect:
            return      # the browser left; the run goes on and a new connection reads its events from the start

    @router.get("/projects/{name}/run/summary")
    def run_summary(name: str) -> RunSummary:
        return build_run_summary(run_folder_of(name))

    @router.get("/projects/{name}/run/sky-patches")
    def run_sky_patches(name: str) -> SkyDome:
        sky_dome = build_sky_dome(run_folder_of(name))
        if sky_dome is None:
            raise ProjectError("This run has no sky patch weights (time-based and tilted plane runs have none).", status_code=404)
        return sky_dome

    @router.get("/projects/{name}/run/score-points", response_class=Response, responses={200: {"content": {"application/octet-stream": {}}}})
    def run_score_points(name: str) -> Response:
        score_points = build_score_points(run_folder_of(name))
        if score_points is None:
            raise ProjectError("This project has no scores yet: run the analysis first.", status_code=404)
        return Response(score_points, media_type="application/octet-stream", headers=NO_CACHE)

    @router.get("/projects/{name}/run/files/{path:path}")
    def run_file(name: str, path: str) -> FileResponse:
        run_folder = run_folder_of(name).resolve()
        try:
            file_path = (run_folder / path).resolve()    # an absolute or '..' path ends up outside the run folder
            inside_run_folder = file_path.is_relative_to(run_folder) and file_path.is_file()
        except (OSError, ValueError):
            inside_run_folder = False
        if not inside_run_folder:
            raise ProjectError(f"There is no result file '{path}'.", status_code=404)
        return FileResponse(file_path, headers=NO_CACHE)

    @router.get("/projects/{name}/download", response_class=FileResponse, responses={200: {"content": {"application/zip": {}}}})
    def download_project(name: str) -> FileResponse:
        project_folder = store.open(name)
        descriptor, archive_name = tempfile.mkstemp(prefix="usc-download-", suffix=".zip")
        os.close(descriptor)
        try:
            with zipfile.ZipFile(archive_name, "w", zipfile.ZIP_DEFLATED) as archive:
                for file_path in sorted(project_folder.rglob("*")):
                    if file_path.is_file():
                        archive.write(file_path, Path(project_folder.name) / file_path.relative_to(project_folder))
        except BaseException:
            Path(archive_name).unlink(missing_ok=True)
            raise
        return FileResponse(archive_name, media_type="application/zip", filename=f"{project_folder.name}.zip",
                            background=BackgroundTask(Path(archive_name).unlink, missing_ok=True))

    return router
