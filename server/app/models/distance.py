"""``distance_cache`` — one driving distance per (family home, suggestion) pair, cached forever.

**Forever is not an approximation.** A driving distance between two fixed points does not
change, so nothing here is expired by age and `computed_at` is a record rather than a
freshness check. Exactly two things invalidate a row: the pin moving past the 25 m epsilon, and
the family's home address changing. `plan/architecture.md`'s cost rule depends on that being
true — a TTL here would turn "asked Google once" into "asks Google every hour, forever".

**`status` is the column this table exists for.** With only a nullable `duration_s`, a pair
that genuinely has no driving route — a home in the UK and a suggestion on a Greek island — is
indistinguishable from a pair nobody has computed yet. Every render would read the null,
conclude "not computed", and re-queue a paid API call for a pair that will never resolve.
`no_route` makes the negative result an *answer*: it is cached permanently and never
automatically retried. The four values are:

============  ==========================================================================
``pending``   queued, not yet answered. Reads fall back to the haversine estimate.
``ok``        a real Distance Matrix answer; `duration_s` and `distance_m` are both set.
``no_route``  Google says there is no driving route. **Permanent.** Both values null.
``failed``    the attempt cap was reached. Cleared only by an organiser's force-recompute.
============  ==========================================================================

**`no_home` is not in that list**, and must never be added to the check constraint: it is a
*presentation* state derived from a family having no geocoded coordinates, and such a family
has no row here at all (`app/schemas/distance.py` says the same thing where a reader of the
API would look).

Every constraint below is mirrored from `alembic/versions/0001_schema.py`, per `CLAUDE.md`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.family import Family
    from app.models.suggestion import Suggestion

#: `distance_cache.status`. Mirrors the check constraint; `no_home` is deliberately absent.
DISTANCE_STATUSES = ("pending", "ok", "no_route", "failed")
DISTANCE_PENDING = "pending"
DISTANCE_OK = "ok"
DISTANCE_NO_ROUTE = "no_route"
DISTANCE_FAILED = "failed"

#: The presentation-only fifth state. Lives here so the schema and the service agree on the
#: spelling, and pointedly **not** in `DISTANCE_STATUSES`.
DISTANCE_NO_HOME = "no_home"

#: The statuses a read may serve as a real answer. Everything else falls back to the estimate.
DISTANCE_SETTLED = (DISTANCE_OK, DISTANCE_NO_ROUTE)

DEFAULT_MODE = "driving"


class DistanceCache(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "distance_cache"

    family_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False
    )
    suggestion_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("suggestions.id", ondelete="CASCADE"), nullable=False
    )
    #: Both null unless `status = 'ok'`. A `no_route` row has no duration because there is no
    #: route, which is a different fact from "nobody has looked yet".
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=DISTANCE_PENDING
    )
    #: Bounds the retry loop. Without it, one bad afternoon at the API becomes an unbounded
    #: retry storm against a paid endpoint.
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default=DEFAULT_MODE)
    computed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    family: Mapped[Family] = relationship()
    suggestion: Mapped[Suggestion] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "family_id", "suggestion_id", name="uq_distance_cache_family_suggestion"
        ),
        CheckConstraint(f"status IN {DISTANCE_STATUSES}", name="ck_distance_cache_status"),
        Index("ix_distance_cache_suggestion_status", "suggestion_id", "status"),
        Index("ix_distance_cache_family_id", "family_id"),
    )

    @property
    def is_settled(self) -> bool:
        """Whether this row is a final answer. `no_route` counts: it is the answer."""
        return self.status in DISTANCE_SETTLED
