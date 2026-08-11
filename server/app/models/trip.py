"""``trips``.

Foundation seeds one trip in ``planning`` and reads ``stage`` for ``require_stage``. Editing
trips (stage transitions, dates) belongs to `admin-console`.

The schema is multi-trip-ready per `CLAUDE.md`; the v1 shell resolves a single active trip.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: Trip lifecycle. `end` is a frozen archive: every `require_stage`-guarded route rejects it.
STAGES = ("planning", "holiday", "end")


class Trip(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trips"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False, server_default="planning")
    #: Nullable while the trip is in planning — the dates are what the trip is deciding.
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Europe/London")
