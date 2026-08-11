"""FastAPI application factory and lifespan.

Startup order matters and is asserted by F-1: migrations run to completion **before** the app
accepts traffic, and the seed runs after them. Anything that fails here is fatal — the
lifespan raises, uvicorn exits non-zero, and the container restarts rather than serving
against a half-built database.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.csrf import CSRFMiddleware
from app.core.migrations import run_migrations
from app.core.seed import run_seed
from app.routers import auth, health, me, presence, settings as settings_router
from app import ws
from app.schemas.common import CODE_VALIDATION_ERROR

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

#: Default `code` per status, for exceptions raised without one (including FastAPI's own).
_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "rate_limited",
    500: "internal_error",
    503: "db_unavailable",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=settings.log_level.upper())
    await run_migrations()
    # After migrations, never before: the seed writes rows into tables the migration creates.
    await run_seed()
    yield


def _envelope(status_code: int, code: str, message: str) -> dict:
    return {"detail": {"code": code, "message": message}}


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Render every `HTTPException` as the shared envelope.

    Registered globally so a route that raises a bare `HTTPException` — or a 404 from the
    router itself — still produces `{detail: {code, message}}`. The client can therefore
    branch on `detail.code` unconditionally, with no "sometimes it's a string" special case.
    """
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = {"detail": {"code": detail["code"], "message": detail.get("message", "")}}
    else:
        body = _envelope(
            exc.status_code,
            _STATUS_CODES.get(exc.status_code, "error"),
            str(detail) if detail else "Request failed.",
        )
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422s use the same envelope, with the field errors kept alongside it."""
    body = _envelope(422, CODE_VALIDATION_ERROR, "Some of those values aren't valid.")
    body["detail"]["errors"] = [
        {"field": ".".join(str(part) for part in err["loc"][1:]), "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(status_code=422, content=body)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Kindred",
        version=settings.app_version,
        summary="Self-hosted, map-centric trip planner for groups of families.",
        lifespan=lifespan,
    )

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    if settings.cors_origin_list:
        # Dev only — in production the SPA is served from the same origin behind Caddy and
        # this list is empty.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Added last so it runs outermost (Starlette applies middleware in reverse), ahead of
    # CORS's preflight short-circuit for the requests that reach the app.
    app.add_middleware(CSRFMiddleware)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(settings_router.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(me.router, prefix=API_PREFIX)
    app.include_router(presence.router, prefix=API_PREFIX)

    # Not under API_PREFIX: Caddy proxies `/ws` separately (plan/architecture.md).
    app.include_router(ws.router)

    return app


app = create_app()
