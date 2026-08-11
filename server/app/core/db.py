"""Async engine and session factory.

Named ``get_db`` rather than ``get_session``: in this codebase "session" means an
authenticated user session (`core/sessions.py`, the `sessions` table), and `deps.get_session`
is the dependency that loads one from the cookie. The database handle is ``db`` throughout.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=False,
)

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped database session."""
    async with SessionFactory() as db:
        yield db
