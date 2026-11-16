"""FastAPI application factory. Refuses to start on invalid config (§6)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from terrapilot import __version__
from terrapilot.api.routers import (
    admin,
    auth,
    behavior,
    chat,
    day,
    fleet,
    live,
    machines,
    maintenance,
    planning,
    training,
    ui,
)
from terrapilot.api.ws import router as ws_router
from terrapilot.core.config import get_config
from terrapilot.core.logging import configure_logging
from terrapilot.core.settings import get_settings
from terrapilot.domain.ws import WsEnvelope


def _with_ws_contract(app: FastAPI) -> dict[str, Any]:
    """Publish the WS message union (§9.3) in OpenAPI components so openapi-typescript emits TS types."""
    if app.openapi_schema:
        return app.openapi_schema
    spec = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schemas = spec.setdefault("components", {}).setdefault("schemas", {})
    ws_schema = WsEnvelope.model_json_schema(ref_template="#/components/schemas/{model}")
    schemas.update(ws_schema.pop("$defs", {}))
    schemas["WsEnvelope"] = ws_schema
    app.openapi_schema = spec
    return spec


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(json_output=settings.tp_env == "prod")
    cfg = get_config()  # raises ConfigError → the process exits with file/key pointers
    app = FastAPI(title=f"{cfg.app.product.name} API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in (
        ui.router,
        auth.router,
        machines.router,
        live.router,
        day.router,
        planning.router,
        maintenance.router,
        behavior.router,
        chat.router,
        training.router,
        fleet.router,
        admin.router,
        ws_router,
    ):
        app.include_router(router)
    app.openapi = lambda: _with_ws_contract(app)  # type: ignore[method-assign]
    return app
