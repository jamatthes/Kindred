"""``comments`` and ``notifications`` — two polymorphic tables, created here by `polls`.

**`comments` is polymorphic and therefore carries no foreign key to its subject.** That is a
deliberate trade: one thread implementation serves polls, suggestions and itinerary items,
at the cost of the database being unable to cascade a delete. Deleting a poll therefore
deletes its comments *in the service layer, in the same transaction* — written down here
because a reader who sees no FK will reasonably wonder whether the cascade was forgotten.

**The same missing FK is a security obligation, not only a housekeeping one.** `subject_id` is
an unconstrained uuid, so nothing in the database stops a comment being posted onto a subject
belonging to another trip, or read from one. **Every read and write path must verify subject
ownership explicitly** — `app/services/comments.py::verify_subject_access` resolves the
subject's trip and confirms the caller is on it, and is called on every path in that module,
including the ones that only read. A route that skips it is a cross-trip data leak with no
constraint standing behind it.

**Deletion is soft** (`voting-comments` V8). `deleted_at` backs the undo pattern
`plan/design-system.md` mandates for low-stakes destructive actions; every read filters
`deleted_at IS NULL`, and `visible_comments()` below is the query helper that does it so a raw
query is the exception rather than the norm.

**`notifications` is written from M2 onward even though nothing renders it yet.** The
`notifications` feature (M6) builds the bell and the centre; until then the poll nudge
(PL-10) writes rows that simply accumulate and are picked up when that feature lands. The
alternative — deferring the write — would mean the nudge silently did nothing, which is worse
than a row nobody has read yet.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User

#: `comments.subject_type`. Polls uses `poll`; the other two arrive with their features.
COMMENT_SUBJECTS = ("poll", "suggestion", "itinerary_item")
SUBJECT_SUGGESTION = "suggestion"
SUBJECT_ITINERARY_ITEM = "itinerary_item"
SUBJECT_POLL = "poll"

#: `notifications.type`. Polls contributes this one; each feature adds its own.
NOTIFICATION_POLL_NUDGE = "poll.nudge"
#: Written by `voting-comments` when a comment mentions somebody (V7).
NOTIFICATION_MENTION = "mention"

#: How long a soft-deleted comment survives before the sweep hard-deletes it.
#:
#: Deliberately far longer than the ~10 second undo *affordance* the UI shows: the window exists
#: for safety and support, not as a user-facing feature, and a retention period that matched the
#: affordance would make "we can get that back for you" untrue the moment the toast faded.
COMMENT_RETENTION = timedelta(days=30)


class Comment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "comments"

    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: Nullable so removing an account does not delete the discussion it took part in. The
    #: comment survives attributed to nobody rather than falsifying the record by vanishing.
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: Set on edit and shown as an "edited" marker — an edit that left no trace would falsify
    #: the discussion record.
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The soft delete. Set by `DELETE /comments/{id}`, cleared by `undo-delete`, and hard-
    #: deleted by the retention sweep once older than `COMMENT_RETENTION`.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Who pressed delete — **not** who wrote it. Undo is the deleter's alone: an author whose
    #: comment an organiser removed must not be able to put it back, and an organiser must not
    #: be able to undo somebody else's undo-able delete. Held in a column rather than in the
    #: request layer because "only the user who performed the delete" is unanswerable from a
    #: request-scoped variable the moment the tab closes.
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    #: Eager: every rendered comment needs its author's name and family colour, and a lazy
    #: load on an `AsyncSession` raises rather than fetching.
    author: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[author_id])

    __table_args__ = (
        Index("ix_comments_subject", "subject_type", "subject_id"),
        Index(
            "ix_comments_thread_live",
            "subject_type",
            "subject_id",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint(f"subject_type IN {COMMENT_SUBJECTS}", name="ck_comments_subject_type"),
    )

    @property
    def is_edited(self) -> bool:
        return self.edited_at is not None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


def visible_comments(subject_type: str | None = None, subject_id: uuid.UUID | None = None):
    """The default comment query: **live rows only**, oldest first.

    Every thread read goes through this, so `deleted_at IS NULL` is applied once rather than
    remembered at each call site. A raw `select(Comment)` is the exception — the retention
    sweep and the undo lookup are the only two, and both say why.
    """
    stmt = select(Comment).where(Comment.deleted_at.is_(None))
    if subject_type is not None:
        stmt = stmt.where(Comment.subject_type == subject_type)
    if subject_id is not None:
        stmt = stmt.where(Comment.subject_id == subject_id)
    return stmt.order_by(Comment.created_at)


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The deep-link target. JSON rather than columns because each `type` carries a different
    #: shape, and a column per type would be mostly nulls.
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The bell's query is "my unread, newest first", so the index matches it.
        Index("ix_notifications_recipient_created", "recipient_user_id", "created_at"),
    )
