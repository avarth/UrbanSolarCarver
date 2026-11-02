"""Write what the local service gives the app when it starts, for the app tests to import.

    python tools/write_app_test_service_data.py

The app asks the service for the settings schema (GET /api/schema), the modes (GET /api/modes) and the names of the settings
that belong to a criterion (GET /api/criterion-keys), and the settings form reads its bounds, defaults and descriptions from
them. The app tests run without the service, so they read these replies from app/src/api_client/service_data_for_test.json,
which this script writes by calling the functions of those routes (no server is started). Run it after changing UserConfig, a
mode or CRITERION_KEYS, and commit the file; tests/test_local_web_api_types.py fails while the file is out of date.
"""
import json
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from fastapi.routing import APIRoute

from urbansolarcarver.local_web_service.server import create_app

ROOT = Path(__file__).resolve().parents[1]
SERVICE_DATA_FILE = ROOT / "app" / "src" / "api_client" / "service_data_for_test.json"
# The key of each reply in the file and the route that gives it.
ROUTES = {"schema": "/api/schema", "modes": "/api/modes", "criterion_keys": "/api/criterion-keys"}


def _api_routes(routes, prefix: str = ""):
    """The (full path, route) of every API route. FastAPI before 0.140 lists an included router's routes in the app with their
    prefix; later versions list the included router, whose routes carry the path without it."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        elif getattr(route, "original_router", None) is not None:
            yield from _api_routes(route.original_router.routes, prefix + route.include_context.prefix)


def service_data() -> dict:
    """The replies of the routes in ROUTES, as the service sends them (JSON values)."""
    app = create_app(Path("."), "x", 0)
    endpoints = {path: route.endpoint for path, route in _api_routes(app.routes)}
    return {key: jsonable_encoder(endpoints[path]()) for key, path in ROUTES.items()}


def service_data_text() -> str:
    """The text of SERVICE_DATA_FILE as this script writes it."""
    return json.dumps(service_data(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    SERVICE_DATA_FILE.write_text(service_data_text(), encoding="utf-8", newline="\n")
    print(f"Wrote {SERVICE_DATA_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
