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

from fastapi import FastAPI

from app.core.config import settings
from app.core.migrations import run_migrations
from app.core.seed import run_seed

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=settings.log_level.upper())
    await run_migrations()
    # After migrations, never before: the seed writes rows into tables the migration creates.
    await run_seed()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Kindred",
        version=settings.app_version,
        summary="Self-hosted, map-centric trip planner for groups of families.",
        lifespan=lifespan,
    )
    return app


app = create_app()
