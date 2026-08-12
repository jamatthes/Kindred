"""``suggestion_votes`` — one preference per person per suggestion.

**The unique constraint on `(suggestion_id, user_id)` is the feature.** "One vote per user" is
structural rather than an application check that races: voting is an upsert onto that
constraint, so two devices voting at once converge on last-write-wins instead of quietly
producing two rows that every average would then double-count.

**Exactly one of `score` / `thumb` is populated** — `(score IS NULL) <> (thumb IS NULL)`, not
`poll_scores`' weaker "at least one". The two tables differ deliberately:

* a **poll** score and thumb coexist in one row so that switching the trip's voting mode loses
  nothing and switching back restores it (`plan/features/polls/design.md`, PL-4);
* a **suggestion** vote is one answer at a time, because `voting-comments/design.md` handles a
  mode change as a *display* conversion over whatever is stored rather than as a second stored
  value. A stored score renders as a thumb by threshold and is labelled converted; a stored
  thumb has no defensible numeric value and is **never** turned into one — those voters are
  shown as outstanding instead. Storing a fabricated counterpart would put invented data into
  an average, which `plan/design-system.md`'s honesty rules forbid.

**The voting mode is never denormalised onto a row.** It is derived from
`trip_category_settings` for the suggestion's `type` on every read and every write
(`app/services/votes.py::resolve_voting_mode`), so a settings change never leaves stale mode
data behind.

Every constraint below is mirrored from `alembic/versions/0001_schema.py`, per `CLAUDE.md`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.poll import SCORE_MAX, SCORE_MIN, THUMBS

if TYPE_CHECKING:
    from app.models.suggestion import Suggestion
    from app.models.user import User

THUMB_UP = "up"
THUMB_DOWN = "down"

#: `design.md` > "Voting mode changes with existing votes": a stored score renders as up at 6
#: and above, down at 4 and below, and as **unclear** at exactly 5 — which is reported as its
#: own count rather than rounded into one camp or the other.
THUMBS_UP_FROM_SCORE = 6
THUMBS_DOWN_FROM_SCORE = 4


class SuggestionVote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "suggestion_votes"

    suggestion_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("suggestions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    thumb: Mapped[str | None] = mapped_column(String(8), nullable=True)

    suggestion: Mapped[Suggestion] = relationship()
    user: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("suggestion_id", "user_id", name="uq_suggestion_votes_suggestion_user"),
        CheckConstraint(
            f"score IS NULL OR score BETWEEN {SCORE_MIN} AND {SCORE_MAX}",
            name="ck_suggestion_votes_range",
        ),
        CheckConstraint(f"thumb IS NULL OR thumb IN {THUMBS}", name="ck_suggestion_votes_thumb"),
        CheckConstraint(
            "(score IS NULL) <> (thumb IS NULL)", name="ck_suggestion_votes_one_answer"
        ),
        Index("ix_suggestion_votes_suggestion_id", "suggestion_id"),
        Index("ix_suggestion_votes_user_id", "user_id"),
    )

    @property
    def as_thumb(self) -> str | None:
        """This vote read in thumbs mode. ``None`` means "unclear" — a stored 5.

        A stored thumb is itself; a stored score converts by threshold. The caller must label a
        converted value as converted, which is why this is a property on the row and not a
        silent normalisation inside the tally.
        """
        if self.thumb is not None:
            return self.thumb
        if self.score is None:  # pragma: no cover - the check constraint forbids it
            return None
        if self.score >= THUMBS_UP_FROM_SCORE:
            return THUMB_UP
        if self.score <= THUMBS_DOWN_FROM_SCORE:
            return THUMB_DOWN
        return None

    @property
    def as_score(self) -> int | None:
        """This vote read in score mode, or ``None`` when it cannot honestly be read as one.

        A stored thumb returns ``None`` **on purpose**: there is no defensible number behind
        "I liked it", and inventing one would put fabricated data into an average. The voter is
        listed as outstanding instead, with their thumb preserved and visible in the
        attribution list.
        """
        return self.score
