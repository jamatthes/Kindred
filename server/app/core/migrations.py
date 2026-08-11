"""Run Alembic migrations from inside the API process, before it accepts traffic (F-1).

Two behaviours the deployment depends on (`plan/features/foundation/design.md` > Edge cases):

* the database may not be up yet when the container starts, so the connection is retried with
  backoff for up to 60 seconds before giving up;
* a migration that fails is fatal — the exception propagates, the lifespan aborts and the
  container exits non-zero rather than serving traffic against a half-migrated schema.

Alembic's API is synchronous, so ``upgrade`` runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.db import engine

logger = logging.getLogger(__name__)

# server/app/core/migrations.py -> server/app/core -> server/app -> server
SERVER_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = SERVER_ROOT / "alembic.ini"

#: Total time to keep retrying the initial connection, and the cap on a single backoff step.
CONNECT_TIMEOUT_SECONDS = 60.0
MAX_BACKOFF_SECONDS = 5.0


def alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    return cfg


async def wait_for_database(timeout: float = CONNECT_TIMEOUT_SECONDS) -> None:
    """Block until the database answers, or raise once ``timeout`` has elapsed."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    delay = 0.5
    attempt = 0
    while True:
        attempt += 1
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            if attempt > 1:
                logger.info("Database reachable after %d attempts.", attempt)
            return
        except Exception as exc:  # noqa: BLE001 — any driver error is a "not ready yet"
            if loop.time() + delay >= deadline:
                logger.error("Database unreachable after %.0fs: %s", timeout, exc)
                raise
            logger.warning("Database not ready (attempt %d): %s. Retrying in %.1fs.",
                           attempt, exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)


def _upgrade_head() -> None:
    command.upgrade(alembic_config(), "head")


async def run_migrations() -> None:
    """Wait for the database, then bring it to ``head``. Raises if either step fails."""
    await wait_for_database()
    logger.info("Applying Alembic migrations...")
    await asyncio.to_thread(_upgrade_head)
    logger.info("Migrations applied.")
