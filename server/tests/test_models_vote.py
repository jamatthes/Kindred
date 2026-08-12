"""The vote and comment models: the constraints, and the default query.

Phase 1's verify step is here rather than in psql — "an attempt to insert two votes for the
same `(suggestion_id, user_id)` fails on the unique constraint, and an insert with both `score`
and `thumb` set fails on the check constraint" — because a constraint asserted by a test stays
asserted when somebody edits the migration.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, Suggestion, SuggestionVote, Trip, User, visible_comments
from app.models.comment import COMMENT_RETENTION
from app.models.vote import THUMBS_DOWN_FROM_SCORE, THUMBS_UP_FROM_SCORE
from tests.conftest import add_member, make_family, make_user


async def _suggestion(db: AsyncSession, trip: Trip, author: User) -> Suggestion:
    suggestion = Suggestion(
        trip_id=trip.id,
        type="accommodation",
        title="The Barn",
        status="proposed",
        created_by=author.id,
        lat=50.4,
        lng=-4.7,
    )
    db.add(suggestion)
    await db.commit()
    await db.refresh(suggestion)
    return suggestion


@pytest.fixture
async def voter(db: AsyncSession, trip: Trip) -> User:
    user = await make_user(db, "modelvoter")
    family = await make_family(db, trip, "Voters", color=4)
    await add_member(db, family, user, role="head")
    return user


# --- the constraints ------------------------------------------------------------------------------


async def test_one_vote_per_person_per_suggestion_is_structural(
    db: AsyncSession, trip: Trip, voter: User
) -> None:
    """The unique constraint is the feature: it is what makes two devices voting at once
    converge instead of producing a row each that every average then double-counts."""
    suggestion = await _suggestion(db, trip, voter)
    db.add(SuggestionVote(suggestion_id=suggestion.id, user_id=voter.id, score=8))
    await db.commit()

    db.add(SuggestionVote(suggestion_id=suggestion.id, user_id=voter.id, score=3))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_a_row_carrying_both_answers_is_refused(
    db: AsyncSession, trip: Trip, voter: User
) -> None:
    """Not "at least one" but *exactly* one: a row with both would be counted by two different
    tallies and there would be no honest way to say which the voter meant."""
    suggestion = await _suggestion(db, trip, voter)
    db.add(
        SuggestionVote(suggestion_id=suggestion.id, user_id=voter.id, score=8, thumb="up")
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_an_empty_row_is_refused(db: AsyncSession, trip: Trip, voter: User) -> None:
    suggestion = await _suggestion(db, trip, voter)
    db.add(SuggestionVote(suggestion_id=suggestion.id, user_id=voter.id))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_a_score_out_of_range_is_refused(
    db: AsyncSession, trip: Trip, voter: User
) -> None:
    suggestion = await _suggestion(db, trip, voter)
    db.add(SuggestionVote(suggestion_id=suggestion.id, user_id=voter.id, score=11))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_deleting_the_suggestion_takes_its_votes(
    db: AsyncSession, trip: Trip, voter: User
) -> None:
    """`suggestion_votes` has a real foreign key, so this cascade is the database's — unlike
    `comments`, which is polymorphic and needs the service layer to do it."""
    from sqlalchemy import func, select

    suggestion = await _suggestion(db, trip, voter)
    db.add(SuggestionVote(suggestion_id=suggestion.id, user_id=voter.id, score=8))
    await db.commit()

    await db.delete(suggestion)
    await db.commit()

    assert await db.scalar(select(func.count()).select_from(SuggestionVote)) == 0


# --- the conversion properties ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0, "down"), (4, "down"), (5, None), (6, "up"), (10, "up")],
)
def test_a_score_reads_as_a_thumb_by_threshold(score: int, expected: str | None) -> None:
    assert SuggestionVote(score=score).as_thumb == expected


def test_the_thresholds_leave_exactly_one_unclear_value() -> None:
    """4 and 6 are the boundaries, so 5 alone is neither — which the tally reports as its own
    count rather than rounding into a camp."""
    assert THUMBS_UP_FROM_SCORE - THUMBS_DOWN_FROM_SCORE == 2


def test_a_thumb_is_itself_and_is_never_converted() -> None:
    assert SuggestionVote(thumb="up").as_thumb == "up"


def test_a_thumb_has_no_score_and_none_is_invented() -> None:
    """The load-bearing refusal: there is no defensible number behind "I liked it"."""
    assert SuggestionVote(thumb="up").as_score is None
    assert SuggestionVote(thumb="down").as_score is None


# --- the comment soft delete ----------------------------------------------------------------------------


async def test_the_default_comment_query_excludes_soft_deleted_rows(
    db: AsyncSession, trip: Trip, voter: User
) -> None:
    """`visible_comments()` is the obvious path so a raw `select(Comment)` is the exception —
    the retention sweep and the undo lookup are the only two, and both say why."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    suggestion = await _suggestion(db, trip, voter)
    kept = Comment(
        subject_type="suggestion", subject_id=suggestion.id, author_id=voter.id, body="Kept"
    )
    gone = Comment(
        subject_type="suggestion",
        subject_id=suggestion.id,
        author_id=voter.id,
        body="Deleted",
        deleted_at=datetime.now(UTC),
        deleted_by=voter.id,
    )
    db.add_all([kept, gone])
    await db.commit()

    visible = (await db.scalars(visible_comments("suggestion", suggestion.id))).unique().all()
    everything = (await db.scalars(select(Comment))).unique().all()

    assert [c.body for c in visible] == ["Kept"]
    assert len(everything) == 2  # the row is still there, which is what makes undo real


async def test_a_soft_deleted_comment_knows_who_deleted_it(
    db: AsyncSession, trip: Trip, voter: User
) -> None:
    """Undo is the deleter's alone, and that question outlives the session that asked it —
    which is why `deleted_by` is a column and not a request-scoped variable."""
    from datetime import UTC, datetime

    suggestion = await _suggestion(db, trip, voter)
    comment = Comment(
        subject_type="suggestion",
        subject_id=suggestion.id,
        author_id=voter.id,
        body="Oops",
        deleted_at=datetime.now(UTC),
        deleted_by=voter.id,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    assert comment.is_deleted is True
    assert comment.deleted_by == voter.id


def test_the_retention_window_is_far_longer_than_the_undo_affordance() -> None:
    """The window exists for safety and support, not as a user-facing feature: a retention
    period that matched the ten-second affordance would make "we can get that back for you"
    untrue the moment the toast faded."""
    from app.services.comments import UNDO_AFFORDANCE

    assert COMMENT_RETENTION.total_seconds() > UNDO_AFFORDANCE.total_seconds() * 1000
