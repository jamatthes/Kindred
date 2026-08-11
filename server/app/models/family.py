"""``families`` and ``family_members`` — created bare by foundation, owned by `families`.

Ordering dependency, resolved in `plan/features/foundation/design.md`: `require_member` and
`require_family_admin` resolve membership through `family_members`, so the table must exist
before the `families` feature ships. Foundation therefore creates both tables with the
columns listed in `plan/architecture.md` and nothing more — no endpoints, no behaviour, and
no rows (the seed creates no family). The `families` feature adds its own columns
(`home_locality`, `geocode_status`, `geocode_error`), its unique indexes and its API on top.

Because the seeded admin has no family until `families` ships, `require_member` treats the
platform admin as always satisfying membership.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import DateTime

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: `family_members.role`. The per-family admin is distinct from the platform/main admin.
FAMILY_ROLES = ("admin", "member")


class Family(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "families"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("trips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Token slot 1-8, mapping to `--family-1…8`. Per `plan/features/families/design.md` this
    #: is a smallint, not a hex colour — the palette is owned by the design tokens.
    color: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    home_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    home_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_geocoded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FamilyMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "family_members"

    family_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default="member")
