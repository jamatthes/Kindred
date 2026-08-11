"""Login rate limiting, backed by the `login_attempts` table.

Stored rather than in-process so the limit survives an API restart and stays correct if the
deployment ever grows a second worker (`plan/features/foundation/design.md`). A login is
refused when **either** the username or the client IP has reached
``RATE_LIMIT_LOGIN_PER_MINUTE`` failures in the trailing 60 seconds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import LoginAttempt

#: The trailing window failures are counted over.
WINDOW = timedelta(seconds=60)

#: Attempt rows older than this are dropped by the lazy sweep on login.
RETENTION = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(UTC)


def normalise_username(username: str) -> str:
    """Usernames are compared and rate-limited case-insensitively."""
    return username.strip().lower()


async def record_attempt(
    db: AsyncSession, *, username: str, ip: str | None, succeeded: bool
) -> None:
    """Record one login attempt. Recorded even when the username does not exist."""
    db.add(
        LoginAttempt(username=normalise_username(username), ip=ip, succeeded=succeeded)
    )
    await db.flush()


async def count_recent_failures(
    db: AsyncSession, *, username: str | None = None, ip: str | None = None
) -> int:
    """Count failures in the trailing :data:`WINDOW` for a username or an IP."""
    stmt = select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.succeeded.is_(False),
        LoginAttempt.created_at > _now() - WINDOW,
    )
    if username is not None:
        stmt = stmt.where(LoginAttempt.username == normalise_username(username))
    if ip is not None:
        stmt = stmt.where(LoginAttempt.ip == ip)
    return (await db.execute(stmt)).scalar_one()


async def is_rate_limited(db: AsyncSession, *, username: str, ip: str | None) -> bool:
    """True when this username **or** this IP has hit the limit."""
    limit = settings.rate_limit_login_per_minute
    if await count_recent_failures(db, username=username) >= limit:
        return True
    if ip is not None and await count_recent_failures(db, ip=ip) >= limit:
        return True
    return False


def retry_after_seconds() -> int:
    """Value for the ``Retry-After`` header on a `429`.

    The whole window: the oldest failure in the window is what has to age out, and telling
    the client the worst case is honest and cheap. A precise value would need the timestamp
    of the oldest counted row and would still be a guess by the time the client acts on it.
    """
    return int(WINDOW.total_seconds())


async def clear_failures(db: AsyncSession, username: str) -> int:
    """Delete a username's recent failures after a successful login."""
    result = await db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.username == normalise_username(username),
            LoginAttempt.succeeded.is_(False),
        )
    )
    return result.rowcount or 0


async def sweep_old_attempts(db: AsyncSession) -> int:
    """Delete attempt rows older than :data:`RETENTION`. Called lazily from login."""
    result = await db.execute(
        delete(LoginAttempt).where(LoginAttempt.created_at < _now() - RETENTION)
    )
    return result.rowcount or 0
