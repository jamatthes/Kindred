"""Server-side session lifecycle (the `sessions` table).

The cookie carries an opaque token; only its sha256 is stored, so a database dump does not
hand over live sessions. A session is valid when ``revoked_at is null and expires_at > now()``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import generate_token, hash_token
from app.models import Session

#: `last_seen_at` is touched at most this often, to keep a write off every request.
TOUCH_INTERVAL = timedelta(minutes=1)

#: Expired rows are deleted this long after they expired, by the lazy sweep on login.
SWEEP_GRACE = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(UTC)


async def create_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[Session, str]:
    """Create a session and return it with the **raw** cookie token.

    The raw token is returned once and never again — it is not recoverable from the row.
    """
    token = generate_token()
    session = Session(
        user_id=user_id,
        token_hash=hash_token(token),
        csrf_token=generate_token(),
        expires_at=_now() + timedelta(hours=settings.session_ttl_hours),
        user_agent=user_agent,
        ip=ip,
    )
    db.add(session)
    await db.flush()
    return session, token


async def load_session(db: AsyncSession, token: str) -> Session | None:
    """Load a valid session by its raw cookie value, or ``None``.

    An expired or revoked session returns ``None`` — indistinguishable to the caller from no
    session at all, which is what F-4 requires.
    """
    if not token:
        return None
    stmt = select(Session).where(
        Session.token_hash == hash_token(token),
        Session.revoked_at.is_(None),
        Session.expires_at > _now(),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def touch_session(db: AsyncSession, session: Session) -> None:
    """Update ``last_seen_at``, but at most once per :data:`TOUCH_INTERVAL`."""
    now = _now()
    last_seen = session.last_seen_at
    if last_seen is not None and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    if last_seen is not None and now - last_seen < TOUCH_INTERVAL:
        return
    session.last_seen_at = now
    await db.flush()


async def revoke_session(db: AsyncSession, session_id: uuid.UUID) -> None:
    """Revoke one session (logout)."""
    await db.execute(
        update(Session)
        .where(Session.id == session_id, Session.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def revoke_user_sessions(
    db: AsyncSession, user_id: uuid.UUID, *, except_session_id: uuid.UUID | None = None
) -> int:
    """Revoke every live session for a user, optionally sparing the current one.

    Used two ways: on password change, sparing the caller's session (F-5/F-6), and on login,
    sparing nothing — the old session dies so a fixated cookie cannot survive a login.
    Returns the number of sessions revoked.
    """
    stmt = update(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
    if except_session_id is not None:
        stmt = stmt.where(Session.id != except_session_id)
    result = await db.execute(stmt.values(revoked_at=_now()))
    return result.rowcount or 0


async def sweep_expired_sessions(db: AsyncSession) -> int:
    """Delete sessions that expired more than :data:`SWEEP_GRACE` ago.

    Called lazily from login rather than by a scheduler: the table only grows on login, so
    login is exactly where it is worth cleaning, and the deployment gains no cron dependency.
    """
    result = await db.execute(delete(Session).where(Session.expires_at < _now() - SWEEP_GRACE))
    return result.rowcount or 0
