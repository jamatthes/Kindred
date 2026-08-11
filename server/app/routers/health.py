"""`GET /api/v1/health` (F-1).

The database check is a real query, not a "did the pool get created" guess: the point of the
endpoint is to tell a restarting compose stack whether the API can actually serve.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.db import get_db
from app.schemas.auth import HealthOut

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut, summary="Liveness and database connectivity")
async def health() -> HealthOut:
    db_status = "down"
    # Its own session, not the `get_db` dependency: if the database is unreachable, acquiring
    # a dependency-injected session would fail the request before the handler could report it.
    try:
        async for db in get_db():
            await db.execute(text("SELECT 1"))
            db_status = "ok"
            break
    except Exception:  # noqa: BLE001 — any failure means "down"; the detail goes to the log
        logger.exception("Health check database ping failed.")

    return HealthOut(
        status="ok" if db_status == "ok" else "degraded",
        version=settings.app_version,
        db=db_status,
    )
