"""``trips`` and its two configuration tables.

Foundation seeds one trip in ``planning`` and reads ``stage`` for ``require_stage``. Editing
trips (name, dates, timezone) belongs to `admin-console`; the stage itself moves through the
single endpoint `holiday-stage` owns, and every move is recorded in
:class:`TripStageTransition`.

The schema is multi-trip-ready per `CLAUDE.md`; the v1 shell resolves a single active trip.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.user import User

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

    @property
    def setup_complete(self) -> bool:
        """Has the owner finished setting this trip up? (`admin-console` AC-0.)

        Defined once, here, because two things read it and must not drift: the console's
        `TripAdminOut.setup_complete`, and foundation's `next_step` gate, which sends the
        owner to the setup screen while it is false.

        Deliberately **not** the dates. They are legitimately unknown during Planning —
        deciding them is what Planning is for — and requiring them to finish setup would
        block the owner on a decision the trip has not made yet. The timezone has a
        defensible default (the container's `TZ`); the name does not, which is why an empty
        name is what keeps the gate closed.
        """
        return bool(self.name and self.name.strip()) and bool(self.timezone)


def is_owner_of(trip: Trip | None, user: User) -> bool:
    """The trip's owner, or the bootstrap platform admin.

    Here rather than in `deps.py` because `core/onboarding.py` needs the same answer and
    cannot import `deps` — `deps` imports *it*. Two implementations of "is this the owner"
    is exactly the kind of drift that ends with one screen shown to someone another screen
    would refuse.
    """
    return bool(user.is_platform_admin) or (
        trip is not None and trip.owner_user_id == user.id
    )


#: `trip_category_settings.category`. Five fixed kinds of thing a group votes on. `poll`
#: governs every poll: the mode is per category, not per poll (see the NOTE on AC-5 in
#: `plan/features/admin-console/requirements.md`).
VOTING_CATEGORIES = ("poll", "region", "accommodation", "activity", "meal")

#: `trip_category_settings.voting_mode`.
VOTING_MODES = ("score", "thumbs")

#: The seeded default per category. Scores where the group is comparing options against each
#: other (the destination matrix is the origin use case); thumbs where the question is really
#: "would you come?" and a 1–10 scale would be false precision.
DEFAULT_VOTING_MODES: dict[str, str] = {
    "poll": "score",
    "region": "score",
    "accommodation": "score",
    "activity": "thumbs",
    "meal": "thumbs",
}

#: `trip_stage_transitions.direction`.
STAGE_DIRECTIONS = ("forward", "backward")


class TripCategorySetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """How one category is voted on, for one trip.

    All five rows exist from the moment a trip is created, so `GET /trip/category-settings`
    is a plain read and a voting UI never has to guess. The self-healing read in
    `admin-console` repairs a trip that predates that rule; the unique constraint below is
    what makes repairing it safe under concurrency.
    """

    __tablename__ = "trip_category_settings"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    voting_mode: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        CheckConstraint(
            f"category IN {VOTING_CATEGORIES}", name="ck_trip_category_settings_category"
        ),
        CheckConstraint(
            f"voting_mode IN {VOTING_MODES}", name="ck_trip_category_settings_voting_mode"
        ),
        UniqueConstraint(
            "trip_id", "category", name="uq_trip_category_settings_trip_category"
        ),
        Index("ix_trip_category_settings_trip_id", "trip_id"),
    )


class TripStageTransition(UUIDPrimaryKeyMixin, Base):
    """One stage change. Append-only, and the only audit trail v1 keeps.

    Deliberately **not** ``TimestampMixin``: a record of something that happened has a time it
    happened at and no time it was last edited, because it is never edited.
    """

    __tablename__ = "trip_stage_transitions"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    from_stage: Mapped[str] = mapped_column(String(16), nullable=False)
    to_stage: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Stored, not derived: reading the history should not require knowing the stage machine
    #: to tell a correction from a normal advance.
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    #: Nullable so removing an account does not delete the record that it moved the stage.
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            f"direction IN {STAGE_DIRECTIONS}", name="ck_trip_stage_transitions_direction"
        ),
        Index("ix_trip_stage_transitions_trip_created", "trip_id", "created_at"),
    )
