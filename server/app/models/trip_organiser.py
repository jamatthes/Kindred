"""``trip_organisers`` — the owner's delegates (FM-17, roles revised 2026-08-11).

An organiser holds every cross-family power the owner has: confirming suggestions, moving
stages, configuring voting modes, managing any family, inviting anyone anywhere. **Except
one** — an organiser cannot appoint or remove an organiser, including themselves and each
other. A delegate who can unappoint the delegator is not a delegate; without that limit the
owner's choice of who runs the trip lasts until the first organiser disagrees, and there is no
way back.

The role is trip-level and entirely independent of family roles: an organiser is still an
ordinary head, spouse or member of their own family, and holds no family-level powers
elsewhere beyond the cross-family ones this row grants.

**This feature creates and honours the table; `admin-console` owns the endpoints that write
it** (`plan/features/families/design.md`). It lives here rather than there because
`require_organiser` reads it from the very first route `families` ships, and a permission
dependency cannot wait for a later milestone.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class TripOrganiser(UUIDPrimaryKeyMixin, Base):
    """One grant. Deliberately **not** ``TimestampMixin``.

    The row's existence *is* the grant, so there is nothing to mutate and no `updated_at` to
    maintain — revoking is a delete. A grant with a mutable body would invite the question of
    what a half-revoked organiser is.
    """

    __tablename__ = "trip_organisers"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: Who appointed them — always the owner. Nullable so deleting that account does not take
    #: the grant with it; an organiser should not lose their role because the person who
    #: appointed them was removed.
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("trip_id", "user_id", name="uq_trip_organisers_trip_user"),
        Index("ix_trip_organisers_trip_id", "trip_id"),
    )
