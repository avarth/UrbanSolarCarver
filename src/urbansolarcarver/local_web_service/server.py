"""The HTTP service of the local browser app: security checks, routes, run events and the built front-end.

``create_app`` builds the FastAPI application. One ProjectStore is shared by every route and the run worker,
so their per-project locks serialize requests that touch the same project. Change folder replaces the store and
the worker together (``_ProjectsFolderInUse``); the routes read them from there on every request. The routes are plain functions that
FastAPI runs on its thread pool; only the WebSocket handler is asynchronous, and it waits for events in a thread.
Importing this module does not import torch (the engine is imported when the first run starts).
"""
from __future__ import annotations

import asyncio
import hmac
import os
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, get_args
from urllib.parse import parse_qs

from fastapi import APIRouter, FastAPI, File, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
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
from . import folder_picker, user_preferences
from .api_models import (
    CancelRunReply, ColdPeriodReply, ConfigErrorReply, ConfigReply, ConfigValuesRequest, CreateProjectRequest, ErrorDetailReply,
    ExampleInfo, ExampleProject, FieldErrorReply, HealthReply, InputFileInfo, InputFilesReply, MissingInputsReply, ModeInfo, ProjectDetail,
    ProjectsFolderChoiceReply, ProjectsFolderReply, ProjectsFolderSource, ProjectSummary, RenameProjectRequest, RunSummary, SkyDome, StageStatusReply, StartRunReply, StartRunRequest, SunPath,
)
from .carve_further import carve_further
from .example_catalog import EXAMPLE_PROJECTS_FOLDER, EXAMPLE_WEATHER_FILE_NAME, read_examples
from .folder_picker import FolderPickerUnavailable
from .gpu_warm_up import GpuWarmUp
from .projects import (
    CONFIG_FILE_NAME, MESH_ROLES, RUN_FOLDER, WEATHER_ROLE, GridOverBudget, ProjectError, ProjectStore, example_of_project, validate_project_name,
)
from .run_summary import build_run_summary, build_sky_dome, sun_path_for_config
from .run_worker import MissingInputs, RunConflict, RunWorker
from .score_points import build_score_points
from .stage_records import envelope_voxel_size, stage_status_reply

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
    A WebSocket is refused after the checks and before any event is sent: it is accepted (which sends no data) and closed at once
    with a code the app can tell apart, because a server answers a close before the accept with an HTTP 403 that a browser reports as 1006.
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
            await receive()     # the connect message, which the protocol has the application read before it answers
            await send({"type": "websocket.accept"})
            await send({"type": "websocket.close", "code": websocket_close_code, "reason": message})
        else:
            await JSONResponse({"detail": message}, status_code=status_code)(scope, receive, send)


@dataclass(frozen=True)
class _FolderState:
    store: ProjectStore
    worker: RunWorker
    source: ProjectsFolderSource


class _ProjectsFolderInUse:
    """The store and the run worker of the projects folder in use, and the switch to another folder.

    Routes read ``store`` and ``worker`` from here on every request, so they follow a switch. ``folder_lock`` makes
    starting a run and switching the folder exclusive: a run starts while holding it, and a switch checks for an active
    run and swaps while holding it.
    """

    def __init__(self, store: ProjectStore, worker: RunWorker, source: ProjectsFolderSource, device: str):
        self._current = _FolderState(store, worker, source)     # replaced whole, so a reader never sees a store of one folder with a worker of another
        self._device = device
        self.folder_lock = threading.Lock()
        self.picker_lock = threading.Lock()     # one folder picker at a time

    @property
    def store(self) -> ProjectStore:
        return self._current.store

    @property
    def worker(self) -> RunWorker:
        return self._current.worker

    @property
    def source(self) -> ProjectsFolderSource:
        return self._current.source

    def can_change(self) -> bool:
        current = self._current
        return current.source != "command_line" and current.worker.active_project() is None

    def refuse_unless_changeable(self) -> None:
        """Raises ProjectError (409) when the folder was given on the command line or a run is active."""
        current = self._current
        if current.source == "command_line":
            raise ProjectError("The projects folder was given with --projects-folder; start without it to change the folder here.", status_code=409)
        active_project = current.worker.active_project()
        if active_project is not None:
            raise ProjectError(f"A run of project '{active_project}' is active. Wait for it to finish or cancel it before changing the projects folder.",
                               status_code=409)

    def switch_to(self, folder: Path) -> None:
        """Remember *folder*, then use it: a new store, and a worker that keeps the engine handler and the compute session.

        Raises ProjectError: 409 when a run is active, 422 when the folder cannot be made or remembered. Nothing changes then.
        """
        with self.folder_lock:
            self.refuse_unless_changeable()
            try:
                user_preferences.write_projects_folder_preference(folder)
            except OSError as error:
                raise ProjectError(f"The folder {folder} cannot be used as the projects folder: {error}", status_code=422) from error
            store = ProjectStore(folder, self._device)
            self._current = _FolderState(store, self._current.worker.for_store(store), "preference")


def create_app(projects_folder: Path, token: str, port: int, device: str = "auto", static_folder: Path | None = None,
               worker: RunWorker | None = None, warm_up: GpuWarmUp | None = None, projects_folder_source: ProjectsFolderSource = "default",
               choose_folder_function: Callable[[Path], Path | None] = folder_picker.choose_folder,
               open_folder_function: Callable[[Path], None] = folder_picker.open_in_file_manager) -> FastAPI:
    """The service for the projects under *projects_folder*.

    *worker* defaults to a RunWorker for *device*; a given worker brings its own ProjectStore, which the
    routes then use, so its projects folder is the one that counts. *warm_up* defaults to a GpuWarmUp that
    is never started (the state stays ``not_started``); ``usc ui`` passes one it has started.
    *projects_folder_source* says where the folder came from (``command_line``, ``preference`` or ``default``); a folder
    from the command line cannot be changed in the app. *choose_folder_function* shows the folder picker and *open_folder_function*
    opens a project's folder in the file manager (tests give fakes).
    A *static_folder* without ``index.html`` (the front-end is not built) leaves the app with the API only.
    """
    if projects_folder_source not in get_args(ProjectsFolderSource):
        raise ValueError(f"projects_folder_source is one of {', '.join(get_args(ProjectsFolderSource))}; got {projects_folder_source!r}.")
    store = worker.store if worker is not None else ProjectStore(projects_folder, device)
    worker = worker or RunWorker(store, device)
    folder_in_use = _ProjectsFolderInUse(store, worker, projects_folder_source, device)
    warm_up = warm_up or GpuWarmUp(device)
    app = FastAPI(title="UrbanSolarCarver local service", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None, generate_unique_id_function=lambda route: route.name)
    app.add_middleware(SecurityMiddleware, token=token, port=port)
    _add_exception_handlers(app)
    app.include_router(_build_router(folder_in_use, warm_up, choose_folder_function, open_folder_function), prefix=API_PREFIX)
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


def _example_input_files(example: ExampleProject) -> list[tuple[str, str, bytes]]:
    """The packaged files of an example as (role, file name, content), all read before any project is made from them."""
    example_folder = EXAMPLE_PROJECTS_FOLDER / example.name
    files = [(role, file_name, (example_folder / file_name).read_bytes())
             for role, file_names in (("max_volume", example.max_volume), ("test_surfaces", example.test_surfaces),
                                      ("context", example.context), ("terrain", example.terrain))
             for file_name in file_names]
    if example.weather:
        files.append((WEATHER_ROLE, EXAMPLE_WEATHER_FILE_NAME, (EXAMPLE_PROJECTS_FOLDER / "weather" / EXAMPLE_WEATHER_FILE_NAME).read_bytes()))
    return files


def _same_project(first_name: str, second_name: str) -> bool:
    """Whether two request names address one project folder (Windows folder names ignore letter case)."""
    return validate_project_name(first_name).lower() == validate_project_name(second_name).lower()


def _build_router(folder_in_use: _ProjectsFolderInUse, warm_up: GpuWarmUp, choose_folder_function: Callable[[Path], Path | None],
                  open_folder_function: Callable[[Path], None]) -> APIRouter:
    router = APIRouter()

    def refuse_while_running(name: str) -> None:
        """Call with the project lock held: the worker records the settings and inputs it starts with, so they stay fixed during its run."""
        active_project = folder_in_use.worker.active_project()
        if active_project is not None and _same_project(active_project, name):
            raise RunConflict(active_project)

    def project_detail(store: ProjectStore, name: str) -> ProjectDetail:
        with store.project_lock(name):
            summary = store.summary(name)
            return ProjectDetail(
                name=summary.name, created=summary.created, modified=summary.modified, example=summary.example, settings=store.read_settings(name),
                inputs={role: store.input_files(name, role) for role in (*MESH_ROLES, WEATHER_ROLE)},
                joined_bounds=store.joined_bounds(name), weather_location=store.weather_location(name),
                weather_latitude=store.weather_latitude(name),
                stage_status=stage_status_reply(store, name), grid_plan=store.stored_grid_plan(name),
                carving_chain=store.read_project_json(name).carving_chain)

    def run_folder_of(name: str) -> Path:
        return folder_in_use.store.open(name) / RUN_FOLDER

    @router.get("/health")
    def health() -> HealthReply:
        return HealthReply(version=__version__, warm_up=warm_up.state())

    @router.get("/schema")
    def schema() -> dict:
        return UserConfig.model_json_schema()

    @router.get("/modes")
    def modes() -> list[ModeInfo]:
        return [ModeInfo(name=mode.name, description=mode.description, needs_epw=mode.needs_epw, needs_period=mode.needs_period,
                         experimental=mode.experimental, score_kind=mode.score_kind, weight_unit=mode.weight_unit, score_unit=mode.score_unit,
                         starting_values=dict(mode.starting_values)) for mode in MODES.values()]

    @router.get("/projects-folder")
    def projects_folder() -> ProjectsFolderReply:
        return ProjectsFolderReply(path=str(folder_in_use.store.projects_folder), source=folder_in_use.source, can_change=folder_in_use.can_change())

    @router.post("/projects-folder/choose", responses={409: _ERROR_RESPONSES[409], 422: _ERROR_RESPONSES[422]})
    def choose_projects_folder() -> ProjectsFolderChoiceReply:
        """Show the folder picker on this computer and switch to the folder chosen; the browser sends no path."""
        folder_in_use.refuse_unless_changeable()
        if not folder_in_use.picker_lock.acquire(blocking=False):
            raise ProjectError("The folder picker is already open on this computer.", status_code=409)
        try:
            try:
                chosen_folder = choose_folder_function(folder_in_use.store.projects_folder)
            except FolderPickerUnavailable as error:
                return ProjectsFolderChoiceReply(status="unavailable", path=str(folder_in_use.store.projects_folder), problem=str(error))
            if chosen_folder is None:
                return ProjectsFolderChoiceReply(status="cancelled", path=str(folder_in_use.store.projects_folder), problem=None)
            folder_in_use.switch_to(chosen_folder.resolve())
            return ProjectsFolderChoiceReply(status="changed", path=str(folder_in_use.store.projects_folder), problem=None)
        finally:
            folder_in_use.picker_lock.release()

    @router.get("/projects")
    def list_projects() -> list[ProjectSummary]:
        return folder_in_use.store.list()

    @router.post("/projects", responses={409: _ERROR_RESPONSES[409], 422: {"model": ConfigErrorReply}})
    def create_project(request: CreateProjectRequest) -> ProjectDetail:
        store = folder_in_use.store
        store.create(request.name, request.mode)
        return project_detail(store, request.name)

    @router.get("/examples")
    def examples() -> list[ExampleInfo]:
        examples_in_order = read_examples()
        project_of_example = folder_in_use.store.projects_of_examples({example.name: example.title for example in examples_in_order})
        return [ExampleInfo(name=example.name, title=example.title, description=example.description,
                            project=project_of_example[example.name]) for example in examples_in_order]

    @router.post("/projects/{name}/examples/{example}", responses={404: {"model": ErrorDetailReply, "description": "There is no such example."}, **_ERROR_RESPONSES})
    def create_example_project(name: str, example: str) -> ProjectDetail:
        """A new project named *name* with the mode and the input files of a packaged example."""
        store = folder_in_use.store
        chosen = next((candidate for candidate in read_examples() if candidate.name == example), None)
        if chosen is None:
            raise ProjectError(f"There is no example '{example}'.", status_code=404)
        example_files = _example_input_files(chosen)
        store.create_example_project(name, chosen, example_files)
        return project_detail(store, name)

    @router.post("/projects/{name}/rename", responses={404: {"model": ErrorDetailReply, "description": "There is no such project."}, **_ERROR_RESPONSES})
    def rename_project(name: str, request: RenameProjectRequest) -> ProjectDetail:
        """Rename the project and its folder; 409 when the new name exists in any letter case or a run of the project is active."""
        store = folder_in_use.store
        with store.project_locks(name, request.new_name):   # both names in one order: two renames in opposite directions must not deadlock
            refuse_while_running(name)
            store.rename_project(name, request.new_name)
        return project_detail(store, request.new_name)

    @router.delete("/projects/{name}", status_code=204, response_class=Response,
                   responses={404: {"model": ErrorDetailReply, "description": "There is no such project."}, **_ERROR_RESPONSES})
    def delete_project(name: str, confirm_name: str) -> Response:
        """Move the project folder to the recycle bin; *confirm_name* must be the project's name as stored (else 422)."""
        store = folder_in_use.store
        with store.project_lock(name):
            refuse_while_running(name)
            project_name = store.read_project_json(name).name
            if confirm_name != project_name:
                raise ProjectError(f"To delete the project, type its name '{project_name}' to confirm.", status_code=422)
            store.delete_project(name)
        return Response(status_code=204)

    @router.post("/projects/{name}/reset-to-example",
                 responses={404: {"model": ErrorDetailReply, "description": "There is no such project."}, **_ERROR_RESPONSES})
    def reset_project_to_example(name: str) -> ProjectDetail:
        """Replace a project made from an example by a fresh copy of it; the old folder goes to the recycle bin."""
        store = folder_in_use.store
        with store.project_lock(name):
            refuse_while_running(name)
            project_json = store.read_project_json(name)
            example = example_of_project(project_json)
            if example is None:
                raise ProjectError(f"'{project_json.name}' was not made from an example, so there is nothing to reset it to.", status_code=422)
            store.reset_project_to_example(name, example, _example_input_files(example))
            return project_detail(store, project_json.name)

    @router.post("/projects/{name}/open-folder", status_code=204, response_class=Response,
                 responses={404: {"model": ErrorDetailReply, "description": "There is no such project."}, 422: _ERROR_RESPONSES[422]})
    def open_project_folder(name: str) -> Response:
        """Open the project's folder in the file manager of this computer; also while a run of the project is active (it changes nothing)."""
        project_folder = folder_in_use.store.open(name)
        try:
            open_folder_function(project_folder)
        except OSError as error:
            raise ProjectError(f"The folder {project_folder} could not be opened: {error}", status_code=422) from error
        return Response(status_code=204)

    @router.get("/projects/{name}")
    def open_project(name: str) -> ProjectDetail:
        store = folder_in_use.store
        try:
            store.rebuild_joined_test_surfaces_without_normals(name)
        except ProjectError:
            pass    # an uploaded file that cannot be read: the project still opens, so it can be removed; a run reports it
        return project_detail(store, name)

    @router.get("/projects/{name}/stage-status")
    def project_stage_status(name: str) -> StageStatusReply:
        return stage_status_reply(folder_in_use.store, name)

    @router.get("/projects/{name}/sun-path")
    def sun_path(name: str) -> SunPath:
        return sun_path_for_config(folder_in_use.store.load_project_config(name))

    @router.get("/projects/{name}/cold-period", responses=_ERROR_RESPONSES)
    def cold_period(name: str, base_temperature: float = Query(ge=-60, le=60, allow_inf_nan=False)) -> ColdPeriodReply:
        """The cold period of the weather file for a base temperature; the page sends balance_temperature - balance_offset as shown."""
        return folder_in_use.store.cold_period(name, base_temperature)

    @router.post("/projects/{name}/inputs/{role}", responses=_ERROR_RESPONSES)
    def add_input(name: str, role: str, file: UploadFile = File(...)) -> InputFilesReply:
        store = folder_in_use.store
        data = file.file.read()
        with store.project_lock(name):
            refuse_while_running(name)
            return store.add_input(name, role, file.filename or "", data)

    @router.get("/projects/{name}/inputs/{role}")
    def input_files(name: str, role: str) -> list[InputFileInfo]:
        return folder_in_use.store.input_files(name, role)

    @router.get("/projects/{name}/inputs/{role}/{file_name}")
    def input_file(name: str, role: str, file_name: str) -> FileResponse:
        return FileResponse(folder_in_use.store.input_file_path(name, role, file_name), headers=NO_CACHE)

    @router.delete("/projects/{name}/inputs/{role}/{file_name}", responses=_ERROR_RESPONSES)
    def remove_input(name: str, role: str, file_name: str) -> InputFilesReply:
        store = folder_in_use.store
        with store.project_lock(name):
            refuse_while_running(name)
            return store.remove_input(name, role, file_name)

    @router.post("/projects/{name}/carve-further", responses=_ERROR_RESPONSES)
    def carve_project_further(name: str) -> ProjectDetail:
        """Make the exported envelope the maximum volume and return the settings to a new project's (carve_further.py)."""
        store = folder_in_use.store
        with store.project_lock(name):
            refuse_while_running(name)
            carve_further(store, name)
            return project_detail(store, name)

    @router.put("/projects/{name}/config", responses={409: _ERROR_RESPONSES[409], 422: {"model": ConfigErrorReply}})
    def save_config(name: str, request: ConfigValuesRequest) -> ConfigReply:
        store = folder_in_use.store
        with store.project_lock(name):
            refuse_while_running(name)
            return store.write_config_from_values(name, request.values)

    @router.post("/projects/{name}/runs", responses={409: _ERROR_RESPONSES[409], 422: {"model": MissingInputsReply}})
    def start_run(name: str, request: StartRunRequest) -> StartRunReply:
        unknown_stages = [stage for stage in request.produce if stage not in PIPELINE_STAGES]
        if unknown_stages or not request.produce:
            raise ProjectError(f"'produce' names one or more of {', '.join(PIPELINE_STAGES)}; got {request.produce}.", status_code=422)
        with folder_in_use.folder_lock:     # not while the projects folder is being switched
            return folder_in_use.worker.start(name, request.produce)

    @router.post("/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> CancelRunReply:
        if folder_in_use.worker.run_state(run_id) is None:
            raise ProjectError(f"There is no run '{run_id}'.", status_code=404)
        return CancelRunReply(cancelled=folder_in_use.worker.cancel(run_id))

    @router.websocket("/runs/{run_id}/events")
    async def run_events(websocket: WebSocket, run_id: str) -> None:
        """Every event of the run from the first, then new ones as they come; closes after the run's last event."""
        run_state = folder_in_use.worker.run_state(run_id)
        if run_state is None:
            await websocket.accept()    # accepted, then closed: a close before the accept would reach the browser as 1006
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
        return build_run_summary(run_folder_of(name), envelope_voxel_size=envelope_voxel_size(folder_in_use.store, name))

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

    @router.get("/projects/{name}/config.yaml", response_class=FileResponse, responses={200: {"content": {"application/yaml": {}}}})
    def download_config(name: str) -> FileResponse:
        """The project's config.yaml as stored, for the Export step's settings download; 404 when the project has none."""
        config_path = folder_in_use.store.open(name) / CONFIG_FILE_NAME
        if not config_path.is_file():
            raise ProjectError(f"Project '{name}' has no {CONFIG_FILE_NAME}.", status_code=404)
        return FileResponse(config_path, media_type="application/yaml", filename=CONFIG_FILE_NAME, headers=NO_CACHE)

    @router.get("/projects/{name}/download", response_class=FileResponse, responses={200: {"content": {"application/zip": {}}}})
    def download_project(name: str) -> FileResponse:
        project_folder = folder_in_use.store.open(name)
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
