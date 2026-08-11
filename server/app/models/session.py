"""``sessions`` and ``login_attempts`` — both PROPOSED ADDITIONs accepted into
`plan/architecture.md`.

`sessions`: server-side sessions were chosen over a signed token because F-5, F-6 and
`admin-console`'s password reset all require revoking a session before its expiry, which a
signed token cannot do. The cookie value itself is never stored — only its sha256.

`login_attempts`: rate limiting is stored rather than held in memory so it survives an API
restart and stays correct if the API is ever run with more than one worker.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class Session(UUIDPrimaryKeyMixin, Base):
    """An authenticated session. Valid when ``revoked_at is null and expires_at > now()``.

    Note there is no ``updated_at``: ``last_seen_at`` is the mutable column and it is touched
    at most once a minute to keep write load off the hot path.
    """

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: sha256 of the opaque cookie value. The raw value exists only in the user's cookie jar.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    #: Issued with the session; echoed by the SPA in ``X-CSRF-Token`` (double-submit).
    csrf_token: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Named explicitly rather than left to SQLAlchemy's default, so the schema built by
        # `create_all` (the test suite) and the one built by the migration are identical down
        # to constraint names — which is what makes them comparable at all.
        UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_expires_at", "expires_at"),
    )


class LoginAttempt(UUIDPrimaryKeyMixin, Base):
    """One login attempt, successful or not. Swept lazily; rows older than an hour are dropped."""

    __tablename__ = "login_attempts"

    #: Lowercased. Recorded even when no such user exists, so a username can be rate-limited
    #: without revealing whether it is real.
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_login_attempts_created_at", "created_at"),
        Index("ix_login_attempts_username_created_at", "username", "created_at"),
        Index("ix_login_attempts_ip_created_at", "ip", "created_at"),
    )
