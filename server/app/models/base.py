"""Declarative base and the mixins every table shares.

`plan/architecture.md`: "All tables `id` (uuid pk), `created_at`, `updated_at` unless noted."
Both the uuid and the timestamps are *server* defaults, so a row inserted by a migration, a
seed or a raw SQL statement is as well-formed as one inserted through the ORM.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base. Alembic autogenerate reads ``Base.metadata``."""


class UUIDPrimaryKeyMixin:
    """A uuid primary key defaulted by Postgres itself (``gen_random_uuid()``)."""

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """``created_at`` / ``updated_at``, both maintained by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
