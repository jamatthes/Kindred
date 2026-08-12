"""``polls``, ``poll_options`` and ``poll_scores`` — the feature that replaces the spreadsheet.

The project began with a shared workbook in which each family scored candidate destinations
out of ten. These three tables are that workbook, made honest: every score is attributable,
nothing is silently averaged away, and an option nobody scored is distinguishable from an
option everybody hated.

**Two storage rules here are non-obvious and are written down because they are otherwise
invisible to a reader of the schema alone:**

1. ``score`` and ``thumb`` are two nullable columns rather than one overloaded value. Exactly
   one is populated, according to the trip's `poll` category voting mode at the time of
   casting. That is what makes "switching the mode does not delete anything" (PL-4) true: a
   score and a thumb for the same ``(option, user)`` coexist in one row, and the *active* mode
   decides which is read.
2. For a ``kind = "options"`` poll, a member's single choice is stored as **one row with
   ``score = 10``** on the chosen option and no rows for the others. The presence of the row
   *is* the choice; the stored 10 is an implementation detail and is never displayed as a
   score. Uniqueness of the choice is enforced in the service layer, which deletes the
   member's other rows for that poll in the same transaction
   (`plan/features/polls/design.md`).

Every constraint below is mirrored from `alembic/versions/0001_schema.py`, per `CLAUDE.md`:
the suite builds its schema with ``create_all``, so a constraint declared in only one of the
two would be enforced in production and absent under pytest.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User

#: `polls.kind`. Immutable after creation.
POLL_KINDS = ("score_matrix", "options")
KIND_SCORE_MATRIX = "score_matrix"
KIND_OPTIONS = "options"

#: `polls.status`.
POLL_STATUSES = ("open", "closed")
STATUS_OPEN = "open"
STATUS_CLOSED = "closed"

#: `poll_scores.thumb`.
THUMBS = ("up", "down")

#: The score written for the chosen option of an `options` poll. Never displayed — see the
#: module docstring.
OPTIONS_POLL_SCORE = 10

#: The UI collects 1-10; the column accepts 0-10 so a future "0 = veto" needs no migration
#: (`requirements.md`, NOTE on PL-3).
SCORE_MIN = 0
SCORE_MAX = 10


class Poll(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "polls"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=STATUS_OPEN)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    allow_member_options: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    #: The winning option (PL-13). `ON DELETE SET NULL`, so deleting a decided option clears
    #: the decision as a database guarantee rather than a service-layer promise.
    decision_option_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("poll_options.id", ondelete="SET NULL", name="fk_polls_decision_option_id",
                   use_alter=True),
        nullable=True,
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_nudge_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Eager, and ordered by `sort` then creation: a poll is never useful without its options,
    #: and a lazy load on an `AsyncSession` raises rather than fetching.
    options: Mapped[list[PollOption]] = relationship(
        back_populates="poll",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PollOption.sort, PollOption.created_at",
        foreign_keys="PollOption.poll_id",
    )

    __table_args__ = (
        Index("ix_polls_trip_id", "trip_id"),
        CheckConstraint(f"kind IN {POLL_KINDS}", name="ck_polls_kind"),
        CheckConstraint(f"status IN {POLL_STATUSES}", name="ck_polls_status"),
    )

    @property
    def is_open(self) -> bool:
        return self.status == STATUS_OPEN

    @property
    def is_single_choice(self) -> bool:
        """`options` polls store one row per member, not one per (member, option)."""
        return self.kind == KIND_OPTIONS


class PollOption(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "poll_options"

    poll_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("polls.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Nullable together. An option without coordinates is listed as "not on the map" rather
    #: than dropped from a poll that is otherwise mapped (PL-15).
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    place_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    #: Set when this option was seeded into a map region (PL-14). The foreign key was deferred
    #: at M2 — `suggestions` did not exist yet — and added by `map-suggestions` (Phase 11b).
    #: `use_alter` because `poll_options` is created before `suggestions`, and `ON DELETE SET
    #: NULL` so deleting the seeded region clears the option's link to it rather than leaving a
    #: dangling id the decision banner would render as a broken link.
    suggestion_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "suggestions.id",
            ondelete="SET NULL",
            name="fk_poll_options_suggestion_id",
            use_alter=True,
        ),
        nullable=True,
    )

    poll: Mapped[Poll] = relationship(back_populates="options", foreign_keys=[poll_id])
    scores: Mapped[list[PollScore]] = relationship(
        back_populates="option", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (Index("ix_poll_options_poll_sort", "poll_id", "sort"),)

    @property
    def is_located(self) -> bool:
        """Whether this option can be drawn on the map at all."""
        return self.lat is not None and self.lng is not None


class PollScore(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "poll_scores"

    poll_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("polls.id", ondelete="CASCADE"), nullable=False
    )
    option_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("poll_options.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    thumb: Mapped[str | None] = mapped_column(String(8), nullable=True)

    option: Mapped[PollOption] = relationship(back_populates="scores")
    user: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("option_id", "user_id", name="uq_poll_scores_option_user"),
        CheckConstraint(
            "score IS NOT NULL OR thumb IS NOT NULL", name="ck_poll_scores_not_empty"
        ),
        CheckConstraint(
            f"score IS NULL OR score BETWEEN {SCORE_MIN} AND {SCORE_MAX}",
            name="ck_poll_scores_range",
        ),
        CheckConstraint(f"thumb IS NULL OR thumb IN {THUMBS}", name="ck_poll_scores_thumb"),
        Index("ix_poll_scores_poll_id", "poll_id"),
        Index("ix_poll_scores_user_id", "user_id"),
    )
