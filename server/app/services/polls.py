"""The rules a poll obeys, in one place, so the router stays a thin layer of HTTP.

**The `options`-poll storage rule, restated because it is non-obvious at every call site:**
for `kind = "options"` a member's single choice is stored as *one* `poll_scores` row with
`score = 10` on the chosen option and no rows for the others. **The presence of the row is
the choice.** The stored 10 is an implementation detail and is never displayed as a score;
uniqueness of the choice is enforced here, by deleting the member's other rows for that poll
in the same transaction, because the database's `(option_id, user_id)` unique constraint
cannot express "at most one row across all options of one poll".

The alternative was a `poll_choices` table for one narrow case. Reusing `poll_scores` keeps
one results pipeline, one WebSocket payload and one set of completion rules; the cost is this
paragraph and the two branches below, which is the cheaper trade.

**The voting mode is never assumed.** It is read from `trip_category_settings` for the `poll`
category on every write and every results build (`plan/features/polls/design.md`; PL-4).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    KIND_OPTIONS,
    NOTIFICATION_POLL_NUDGE,
    OPTIONS_POLL_SCORE,
    STATUS_CLOSED,
    STATUS_OPEN,
    SUBJECT_POLL,
    Comment,
    Family,
    FamilyMember,
    Notification,
    Poll,
    PollOption,
    PollScore,
    Trip,
    TripCategorySetting,
    User,
)
from app.schemas.common import ApiError
from app.services.poll_stats import Vote, compute_results

#: PL-10: "Nudging the same poll again is rate-limited to once every few hours, so it cannot
#: become harassment."
NUDGE_WINDOW = timedelta(hours=4)

#: The category whose voting mode governs every poll on the trip. Per category, not per poll
#: (`admin-console` AC-5).
POLL_CATEGORY = "poll"


# --- voting mode ------------------------------------------------------------------------------


async def get_voting_mode(db: AsyncSession, trip_id: uuid.UUID) -> str:
    """The trip's `poll` category mode. **Never assume one.**

    Defaults to `score` only when the row is genuinely absent — which `admin-console`
    guarantees it is not, since it creates all five rows with each trip and self-heals older
    ones. The fallback exists so a missing row degrades to the documented default rather than
    to a 500.
    """
    mode = await db.scalar(
        select(TripCategorySetting.voting_mode).where(
            TripCategorySetting.trip_id == trip_id,
            TripCategorySetting.category == POLL_CATEGORY,
        )
    )
    return mode or "score"


# --- loading -----------------------------------------------------------------------------------


def poll_query():
    """Every poll read goes through this, so the eager loads are decided once."""
    return select(Poll).options(
        selectinload(Poll.options).selectinload(PollOption.scores)
    ).execution_options(populate_existing=True)


async def load_poll(db: AsyncSession, poll_id: uuid.UUID, trip: Trip | None) -> Poll:
    poll = await db.scalar(poll_query().where(Poll.id == poll_id))
    if poll is None or (trip is not None and poll.trip_id != trip.id):
        raise ApiError(404, "not_found", "That poll does not exist.")
    return poll


async def trip_members(db: AsyncSession, trip_id: uuid.UUID) -> list[tuple[User, Family]]:
    """Everyone expected to vote, with their family for the matrix's colour swatch.

    The denominator for "3 of 9 haven't voted" comes from the trip's membership, not from who
    happened to respond — so it is this query, not a count of scores.
    """
    rows = await db.execute(
        select(User, Family)
        .join(FamilyMember, FamilyMember.user_id == User.id)
        .join(Family, Family.id == FamilyMember.family_id)
        .where(Family.trip_id == trip_id)
        .order_by(Family.color, User.display_name)
    )
    return [(row[0], row[1]) for row in rows.all()]


# --- scores ------------------------------------------------------------------------------------


def _wrong_mode(mode: str) -> ApiError:
    return ApiError(
        422,
        "wrong_voting_mode",
        f"This trip is voting by {mode}. Send a {'score' if mode == 'score' else 'thumb'}.",
    )


async def upsert_scores(
    db: AsyncSession,
    poll: Poll,
    user: User,
    entries: list[tuple[uuid.UUID, int | None, str | None]],
    mode: str,
) -> None:
    """Write the caller's own answers. Never anybody else's — there is no parameter for it.

    Validates each entry against the *current* mode before writing anything, so a body that
    is half valid writes nothing rather than half of itself.
    """
    if poll.status == STATUS_CLOSED:
        raise ApiError(409, "poll_closed", "This poll is closed.")

    known = {option.id for option in poll.options}
    for option_id, score, thumb in entries:
        if option_id not in known:
            raise ApiError(404, "not_found", "That option is not on this poll.")
        if mode == "score" and score is None:
            raise _wrong_mode(mode)
        if mode == "thumbs" and thumb is None:
            raise _wrong_mode(mode)

    if poll.is_single_choice:
        if len(entries) != 1:
            raise ApiError(
                422,
                "single_choice_required",
                "This poll takes one choice. Send exactly one option.",
            )
        # The presence of the row *is* the choice, so switching choice means deleting the
        # old row rather than zeroing it — a zeroed row would count as a response in every
        # completion total.
        await db.execute(
            delete(PollScore).where(
                PollScore.poll_id == poll.id, PollScore.user_id == user.id
            )
        )
        option_id, _score, thumb = entries[0]
        db.add(
            PollScore(
                poll_id=poll.id,
                option_id=option_id,
                user_id=user.id,
                # Never displayed. See the module docstring.
                score=OPTIONS_POLL_SCORE if mode == "score" else None,
                thumb=thumb if mode == "thumbs" else None,
            )
        )
        return

    existing = {
        (row.option_id): row
        for row in (
            await db.scalars(
                select(PollScore).where(
                    PollScore.poll_id == poll.id, PollScore.user_id == user.id
                )
            )
        ).all()
    }

    for option_id, score, thumb in entries:
        row = existing.get(option_id)
        if row is None:
            db.add(
                PollScore(
                    poll_id=poll.id,
                    option_id=option_id,
                    user_id=user.id,
                    score=score,
                    thumb=thumb,
                )
            )
            continue
        # Only the column for the active mode is written. The other is left exactly as it
        # was, which is what lets a score survive a switch to thumbs and reappear on the way
        # back (PL-4).
        if mode == "score":
            row.score = score
        else:
            row.thumb = thumb


async def clear_score(
    db: AsyncSession, poll: Poll, user: User, option_id: uuid.UUID
) -> None:
    if poll.status == STATUS_CLOSED:
        raise ApiError(409, "poll_closed", "This poll is closed.")
    await db.execute(
        delete(PollScore).where(
            PollScore.poll_id == poll.id,
            PollScore.user_id == user.id,
            PollScore.option_id == option_id,
        )
    )


# --- results -----------------------------------------------------------------------------------


async def build_results(db: AsyncSession, poll: Poll, trip: Trip) -> dict:
    """Every number every view shows, in one object.

    Two queries: the trip's membership, and the poll's scores. Everything else is the pure
    computation in `poll_stats`, which is what makes the worked example a unit test.
    """
    mode = await get_voting_mode(db, trip.id)
    members = await trip_members(db, trip.id)
    member_by_id = {str(user.id): (user, family) for user, family in members}

    rows = (
        await db.scalars(
            select(PollScore)
            .where(PollScore.poll_id == poll.id)
            .options(selectinload(PollScore.user))
        )
    ).unique().all()

    votes: dict[str, list[Vote]] = {}
    raw: dict[str, list[PollScore]] = {}
    for row in rows:
        key = str(row.option_id)
        votes.setdefault(key, []).append(
            Vote(user_id=str(row.user_id), score=row.score, thumb=row.thumb)
        )
        raw.setdefault(key, []).append(row)

    option_ids = [str(option.id) for option in poll.options]
    labels = {str(option.id): option.label for option in poll.options}

    stats = compute_results(
        option_ids=option_ids,
        labels=labels,
        votes=votes,
        member_ids=[str(user.id) for user, _ in members],
        voting_mode=mode,
        single_choice=poll.is_single_choice,
    )

    by_option = {option.option_id: option for option in stats.options}
    option_by_id = {str(option.id): option for option in poll.options}

    options_out = []
    for option_id in sorted(by_option, key=lambda oid: by_option[oid].rank):
        computed = by_option[option_id]
        option = option_by_id[option_id]
        scores_out = []
        for row in raw.get(option_id, []):
            entry = member_by_id.get(str(row.user_id))
            if entry is None:
                # Scored, then removed from the trip. Their numbers stay in the database
                # (PL-8's edge case) but they are no longer a row in the matrix.
                continue
            user, family = entry
            scores_out.append(
                {
                    "user_id": user.id,
                    "display_name": user.display_name,
                    "family_id": family.id,
                    "family_color": family.color,
            "family_color_custom": family.color_custom,
                    "family_color_custom": family.color_custom,
                    "score": row.score if mode == "score" else None,
                    "thumb": row.thumb if mode == "thumbs" else None,
                }
            )
        options_out.append(
            {
                "option_id": option.id,
                "label": option.label,
                "lat": option.lat,
                "lng": option.lng,
                "average": computed.average,
                "response_count": computed.response_count,
                "spread": computed.spread,
                "is_split": computed.is_split,
                "is_close": computed.is_close,
                "rank": computed.rank,
                "scores": scores_out,
                "up_count": computed.up_count,
                "down_count": computed.down_count,
                "none_count": computed.none_count,
            }
        )

    completion = {m.user_id: m.completion for m in stats.members}
    members_out = [
        {
            "user_id": user.id,
            "display_name": user.display_name,
            "family_id": family.id,
            "family_color": family.color,
            "family_color_custom": family.color_custom,
            "completion": completion.get(str(user.id), "none"),
        }
        for user, family in members
    ]
    outstanding = [m for m in members_out if m["completion"] != "complete"]

    return {
        "poll_id": poll.id,
        "voting_mode": mode,
        "status": poll.status,
        "options": options_out,
        "members": members_out,
        "non_responders": {
            "count": len(outstanding),
            "total": len(members_out),
            "users": [
                {
                    "user_id": m["user_id"],
                    "display_name": m["display_name"],
                    "completion": m["completion"],
                }
                for m in outstanding
            ],
        },
        "insight": stats.insight,
    }


# --- lifecycle ----------------------------------------------------------------------------------


def close_poll(poll: Poll, actor: User) -> None:
    poll.status = STATUS_CLOSED
    poll.closed_at = datetime.now(UTC)
    poll.closed_by = actor.id


def reopen_poll(poll: Poll) -> None:
    """Reopening restores capability rather than removing it, so it needs no confirm — and
    the closed-at record is cleared because the poll is no longer closed."""
    poll.status = STATUS_OPEN
    poll.closed_at = None
    poll.closed_by = None


def set_decision(poll: Poll, option: PollOption, actor: User) -> None:
    poll.decision_option_id = option.id
    poll.decided_by = actor.id
    poll.decided_at = datetime.now(UTC)


def clear_decision(poll: Poll) -> None:
    poll.decision_option_id = None
    poll.decided_by = None
    poll.decided_at = None


# --- nudge ----------------------------------------------------------------------------------------


def next_nudge_at(poll: Poll) -> datetime | None:
    if poll.last_nudge_at is None:
        return None
    last = poll.last_nudge_at
    if last.tzinfo is None:  # a naive value from a raw driver round-trip
        last = last.replace(tzinfo=UTC)
    return last + NUDGE_WINDOW


def can_nudge_now(poll: Poll, *, now: datetime | None = None) -> bool:
    due = next_nudge_at(poll)
    return due is None or due <= (now or datetime.now(UTC))


async def nudge(db: AsyncSession, poll: Poll, actor: User, results: dict) -> int:
    """Write one notification per person who has not finished, and return the count.

    The rows are written even though nothing renders them yet: `notifications` (M6) builds
    the bell, and until then they accumulate and are picked up when it lands. Deferring the
    write would mean the button silently did nothing, which is worse than an unread row.
    """
    if not can_nudge_now(poll):
        raise ApiError(
            429,
            "nudge_too_soon",
            "That poll was nudged recently. Give people a few hours.",
            headers={"Retry-After": str(int(NUDGE_WINDOW.total_seconds()))},
        )

    outstanding = results["non_responders"]["users"]
    if not outstanding:
        # Not an error: everyone has voted, which is the outcome the nudge was for. No rows
        # are written and the window is not consumed.
        return 0

    for person in outstanding:
        db.add(
            Notification(
                recipient_user_id=person["user_id"],
                type=NOTIFICATION_POLL_NUDGE,
                payload_json={
                    "poll_id": str(poll.id),
                    "poll_title": poll.title,
                    "deep_link": f"/polls/{poll.id}",
                },
            )
        )
    poll.last_nudge_at = datetime.now(UTC)
    return len(outstanding)


# --- region seeding ---------------------------------------------------------------------------------


def suggestions_available() -> bool:
    """Whether `map-suggestions` has shipped.

    A capability check rather than a version flag: the module either exists and can create a
    region, or it does not. At M2 it does not, `can_seed_region` reads false, and the button
    is never rendered — so the `501` below is a backstop for a direct call, not a path a user
    can reach through the UI.
    """
    try:  # pragma: no cover - the M3 branch
        import app.services.suggestions  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def seed_region(poll: Poll, option: PollOption) -> uuid.UUID:
    """PL-14. Returns the existing suggestion when already seeded, rather than duplicating."""
    if option.suggestion_id is not None:
        return option.suggestion_id
    if not suggestions_available():
        raise ApiError(
            501,
            "not_available",
            "Map regions arrive with the map feature.",
        )
    raise ApiError(  # pragma: no cover - unreachable until M3 implements the branch above
        501, "not_available", "Map regions arrive with the map feature."
    )


# --- comments ------------------------------------------------------------------------------------


async def comment_count(db: AsyncSession, poll_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(Comment)
            .where(Comment.subject_type == SUBJECT_POLL, Comment.subject_id == poll_id)
        )
    ) or 0


async def delete_poll_comments(db: AsyncSession, poll_id: uuid.UUID) -> None:
    """`comments` is polymorphic and carries no FK to its subject, so the cascade is ours.

    Called in the same transaction as the poll delete — see `models/comment.py`.
    """
    await db.execute(
        delete(Comment).where(
            Comment.subject_type == SUBJECT_POLL, Comment.subject_id == poll_id
        )
    )
