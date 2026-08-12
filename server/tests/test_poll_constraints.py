"""The database-level guarantees the poll tables make.

`plan/features/polls/tasks.md` Phase 1 specifies these as psql checks. They are pytest
instead, for the reason every "verify by hand in psql" step eventually deserves: a check run
once at authoring time proves the constraint existed that afternoon, and a check in the suite
proves it still exists. Each one below is a rule the application relies on and does not
re-implement.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Poll, PollOption, PollScore, Trip, User
from tests.conftest import make_user

pytestmark = pytest.mark.asyncio


async def _poll(db: AsyncSession, trip: Trip, kind: str = "score_matrix") -> Poll:
    poll = Poll(trip_id=trip.id, title="Where shall we go?", kind=kind)
    db.add(poll)
    await db.flush()
    return poll


async def _option(db: AsyncSession, poll: Poll, label: str = "Cornwall") -> PollOption:
    option = PollOption(poll_id=poll.id, label=label)
    db.add(option)
    await db.flush()
    return option


async def test_one_vote_per_person_per_option(
    db: AsyncSession, trip: Trip, member: tuple[User, object]
) -> None:
    """The unique constraint is what makes two devices scoring one cell converge on
    last-write-wins instead of silently duplicating."""
    user, _ = member
    poll = await _poll(db, trip)
    option = await _option(db, poll)
    db.add(PollScore(poll_id=poll.id, option_id=option.id, user_id=user.id, score=7))
    await db.commit()

    db.add(PollScore(poll_id=poll.id, option_id=option.id, user_id=user.id, score=9))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_a_row_with_neither_a_score_nor_a_thumb_is_refused(
    db: AsyncSession, trip: Trip, member: tuple[User, object]
) -> None:
    """An empty row is not a vote. Without this, a bug that wrote neither value would look
    like a response in every count."""
    user, _ = member
    poll = await _poll(db, trip)
    option = await _option(db, poll)

    db.add(PollScore(poll_id=poll.id, option_id=option.id, user_id=user.id))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


@pytest.mark.parametrize("score", [11, -1, 100])
async def test_a_score_outside_the_stored_range_is_refused(
    db: AsyncSession, trip: Trip, member: tuple[User, object], score: int
) -> None:
    user, _ = member
    poll = await _poll(db, trip)
    option = await _option(db, poll)

    db.add(PollScore(poll_id=poll.id, option_id=option.id, user_id=user.id, score=score))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_zero_is_storable_even_though_the_ui_offers_one_to_ten(
    db: AsyncSession, trip: Trip, member: tuple[User, object]
) -> None:
    """`requirements.md`, NOTE on PL-3: the column accepts 0-10 so a future "0 = veto"
    affordance needs no migration. The interface collects 1-10."""
    user, _ = member
    poll = await _poll(db, trip)
    option = await _option(db, poll)
    db.add(PollScore(poll_id=poll.id, option_id=option.id, user_id=user.id, score=0))
    await db.commit()


async def test_an_unknown_thumb_is_refused(
    db: AsyncSession, trip: Trip, member: tuple[User, object]
) -> None:
    user, _ = member
    poll = await _poll(db, trip)
    option = await _option(db, poll)

    db.add(PollScore(poll_id=poll.id, option_id=option.id, user_id=user.id, thumb="sideways"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_a_score_and_a_thumb_may_coexist_in_one_row(
    db: AsyncSession, trip: Trip, member: tuple[User, object]
) -> None:
    """This is the whole reason they are two columns: PL-4 requires that switching the voting
    mode does not delete anything already cast."""
    user, _ = member
    poll = await _poll(db, trip)
    option = await _option(db, poll)
    db.add(
        PollScore(poll_id=poll.id, option_id=option.id, user_id=user.id, score=8, thumb="up")
    )
    await db.commit()

    stored = await db.scalar(select(PollScore).where(PollScore.user_id == user.id))
    assert (stored.score, stored.thumb) == (8, "up")


async def test_an_unknown_poll_kind_is_refused(db: AsyncSession, trip: Trip) -> None:
    db.add(Poll(trip_id=trip.id, title="Bad", kind="ranked_choice"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_deleting_the_decided_option_clears_the_decision(
    db: AsyncSession, trip: Trip
) -> None:
    """`ON DELETE SET NULL` on `polls.decision_option_id`.

    The design's edge-case table promises "the delete clears `decision_option_id` in the same
    transaction and the banner disappears". Making it a database guarantee rather than a
    service-layer promise means no route can forget it.
    """
    poll = await _poll(db, trip)
    option = await _option(db, poll)
    poll.decision_option_id = option.id
    await db.commit()

    await db.delete(option)
    await db.commit()

    await db.refresh(poll)
    assert poll.decision_option_id is None


async def test_deleting_a_poll_takes_its_options_and_scores(
    db: AsyncSession, trip: Trip, member: tuple[User, object]
) -> None:
    """Cascade poll -> options -> scores, at the database level."""
    user, _ = member
    poll = await _poll(db, trip)
    option = await _option(db, poll)
    db.add(PollScore(poll_id=poll.id, option_id=option.id, user_id=user.id, score=5))
    await db.commit()

    # A statement delete rather than `db.delete(poll)`, so what is exercised is the
    # database's `ON DELETE CASCADE` and not SQLAlchemy's own in-Python cascade.
    await db.execute(delete(Poll).where(Poll.id == poll.id))
    await db.commit()

    assert await db.scalar(select(func.count()).select_from(PollOption)) == 0
    assert await db.scalar(select(func.count()).select_from(PollScore)) == 0


async def test_removing_a_member_keeps_the_poll_but_takes_their_scores(
    db: AsyncSession, trip: Trip
) -> None:
    """A user row is never deleted in normal operation (`admin-console` removes the
    membership, not the account), so this only fires on a real account deletion — at which
    point their scores going with them is correct."""
    from sqlalchemy import func

    leaver = await make_user(db, "leaver")
    poll = await _poll(db, trip)
    option = await _option(db, poll)
    db.add(PollScore(poll_id=poll.id, option_id=option.id, user_id=leaver.id, score=6))
    await db.commit()

    # Again a statement delete: `db.delete(leaver)` would make SQLAlchemy null out the
    # dependent rows it knows about in Python, which is not the guarantee under test.
    await db.execute(delete(User).where(User.id == leaver.id))
    await db.commit()

    assert await db.scalar(select(func.count()).select_from(PollScore)) == 0
    assert await db.scalar(select(func.count()).select_from(Poll)) == 1
