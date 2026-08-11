"""``comments`` and ``notifications`` — two polymorphic tables, created here by `polls`.

**`comments` is polymorphic and therefore carries no foreign key to its subject.** That is a
deliberate trade: one thread implementation serves polls, suggestions and itinerary items,
at the cost of the database being unable to cascade a delete. Deleting a poll therefore
deletes its comments *in the service layer, in the same transaction* — written down here
because a reader who sees no FK will reasonably wonder whether the cascade was forgotten.

**`notifications` is written from M2 onward even though nothing renders it yet.** The
`notifications` feature (M6) builds the bell and the centre; until then the poll nudge
(PL-10) writes rows that simply accumulate and are picked up when that feature lands. The
alternative — deferring the write — would mean the nudge silently did nothing, which is worse
than a row nobody has read yet.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User

#: `comments.subject_type`. Polls uses `poll`; the other two arrive with their features.
COMMENT_SUBJECTS = ("poll", "suggestion", "itinerary_item")
SUBJECT_POLL = "poll"

#: `notifications.type`. Polls contributes this one; each feature adds its own.
NOTIFICATION_POLL_NUDGE = "poll.nudge"


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

    #: Eager: every rendered comment needs its author's name and family colour, and a lazy
    #: load on an `AsyncSession` raises rather than fetching.
    author: Mapped[User | None] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_comments_subject", "subject_type", "subject_id"),
        CheckConstraint(f"subject_type IN {COMMENT_SUBJECTS}", name="ck_comments_subject_type"),
    )

    @property
    def is_edited(self) -> bool:
        return self.edited_at is not None


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
