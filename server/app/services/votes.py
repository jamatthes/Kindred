"""Voting on suggestions: the upsert, the tally, and the mode-change rules.

**The voting mode is never assumed and never stored on a vote.** It is read from
`trip_category_settings` for the suggestion's `type` on every write and every tally build, so a
settings change never leaves stale mode data behind (`design.md` > Data model).

**The honest-denominator rule governs every number in here.** `count` is how many votes are
usable *in the active mode*; `eligible_count` is everybody on the trip; `not_voted` is a list,
not a subtraction the caller has to do. A 10/10 average from one voter out of nine must never
be able to render as consensus (`plan/design-system.md`, V3).

**Mode changes convert for display and never for storage** (`design.md` > "Voting mode changes
with existing votes"):

* *score → thumbs* — a stored score renders as up at 6+, down at 4-, and as **unclear** at
  exactly 5, each labelled `converted` so it is not passed off as a genuine thumbs vote.
* *thumbs → score* — a stored thumb has **no defensible numeric value**, so none is invented.
  Those voters appear in `not_voted` with `has_unusable_vote`, and their thumb stays visible in
  the attribution list. Fabricating a number would put invented data into an average, which the
  honesty rules forbid; showing them as outstanding is the honest option and prompts a re-vote.

Nothing here is deleted or converted on disk, so switching back restores the original display.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    STATUS_REJECTED,
    THUMB_DOWN,
    THUMB_UP,
    THUMBS_DOWN_FROM_SCORE,
    THUMBS_UP_FROM_SCORE,
    Family,
    FamilyMember,
    Suggestion,
    SuggestionVote,
    Trip,
    TripCategorySetting,
    User,
)
from app.schemas.common import ApiError
from app.schemas.vote import (
    DISTRIBUTION_BUCKETS,
    MyVoteOut,
    NotVotedOut,
    PendingVotesOut,
    TallyOut,
    VoterOut,
)

MODE_SCORE = "score"
MODE_THUMBS = "thumbs"

#: The mode a category falls back to when its settings row is genuinely absent — which
#: `admin-console` guarantees it is not, since it seeds all five rows with each trip and
#: self-heals older ones. The fallback exists so a missing row degrades to the documented
#: default rather than to a 500.
DEFAULT_MODE = MODE_SCORE


# --- voting mode --------------------------------------------------------------------------------


async def resolve_voting_mode(db: AsyncSession, trip_id: uuid.UUID, category: str) -> str:
    """The mode for one category on one trip. **Never assume one.**

    Shared with `polls`, which asks for the `poll` category through the same function, so the
    two features cannot drift on what "the mode" means or where it is read from.
    """
    mode = await db.scalar(
        select(TripCategorySetting.voting_mode).where(
            TripCategorySetting.trip_id == trip_id,
            TripCategorySetting.category == category,
        )
    )
    return mode or DEFAULT_MODE


async def resolve_modes(db: AsyncSession, trip_id: uuid.UUID) -> dict[str, str]:
    """Every category's mode in one query — for the list, which needs all of them at once."""
    rows = await db.execute(
        select(TripCategorySetting.category, TripCategorySetting.voting_mode).where(
            TripCategorySetting.trip_id == trip_id
        )
    )
    return {row[0]: row[1] for row in rows.all()}


# --- writing ------------------------------------------------------------------------------------


def _wrong_mode(mode: str) -> ApiError:
    return ApiError(
        422,
        "wrong_voting_mode",
        f"This category is voting by {mode}. Send a {'score' if mode == MODE_SCORE else 'thumb'}.",
    )


async def upsert_vote(
    db: AsyncSession,
    suggestion: Suggestion,
    user: User,
    *,
    score: int | None,
    thumb: str | None,
    mode: str,
) -> None:
    """Write the caller's own vote. Never anybody else's — there is no parameter for it.

    A real `INSERT ... ON CONFLICT DO UPDATE` on `(suggestion_id, user_id)`, not a
    read-then-write: two devices voting at once converge on last-write-wins rather than racing
    to produce a row each. **The opposite column is cleared in the same statement**, which is
    what keeps `(score IS NULL) <> (thumb IS NULL)` true across a mode change — a voter who
    scored 8 and later gives a thumbs-up ends with a thumb and no score, not a row carrying
    both and meaning neither.
    """
    if mode == MODE_SCORE and score is None:
        raise _wrong_mode(mode)
    if mode == MODE_THUMBS and thumb is None:
        raise _wrong_mode(mode)

    values = {
        "suggestion_id": suggestion.id,
        "user_id": user.id,
        "score": score if mode == MODE_SCORE else None,
        "thumb": thumb if mode == MODE_THUMBS else None,
    }
    statement = pg_insert(SuggestionVote).values(**values)
    await db.execute(
        statement.on_conflict_do_update(
            constraint="uq_suggestion_votes_suggestion_user",
            set_={"score": statement.excluded.score, "thumb": statement.excluded.thumb},
        )
    )


async def clear_vote(db: AsyncSession, suggestion: Suggestion, user: User) -> None:
    """Remove the row, so the caller counts as "not yet voted" again.

    A deletion rather than a zeroed row, for the reason `polls` deletes an options-poll choice:
    a stored 0 is a real opinion ("I hate it"), and using it to mean "no opinion" would make
    every outstanding count and every average wrong at once.
    """
    await db.execute(
        delete(SuggestionVote).where(
            SuggestionVote.suggestion_id == suggestion.id,
            SuggestionVote.user_id == user.id,
        )
    )


# --- the tally ----------------------------------------------------------------------------------


async def _trip_members(db: AsyncSession, trip_id: uuid.UUID) -> list[tuple[User, Family]]:
    """Everyone expected to vote, with their family for the colour swatch.

    The denominator comes from the trip's membership, not from who happened to respond — which
    is what makes "3 of 9 haven't voted" answerable at all.
    """
    rows = await db.execute(
        select(User, Family)
        .join(FamilyMember, FamilyMember.user_id == User.id)
        .join(Family, Family.id == FamilyMember.family_id)
        .where(Family.trip_id == trip_id)
        .order_by(Family.color, User.display_name)
    )
    return [(row[0], row[1]) for row in rows.all()]


async def get_tally(
    db: AsyncSession,
    suggestion: Suggestion,
    trip: Trip,
    *,
    caller: User | None = None,
    mode: str | None = None,
) -> TallyOut:
    """Every number every density of the tally shows, in one object.

    Three queries: the mode, the trip's membership, and this suggestion's votes. Everything
    else is arithmetic over those.
    """
    active = mode or await resolve_voting_mode(db, trip.id, suggestion.type)
    members = await _trip_members(db, trip.id)
    votes = (
        (await db.scalars(select(SuggestionVote).where(SuggestionVote.suggestion_id == suggestion.id)))
        .unique()
        .all()
    )
    return build_tally(suggestion.id, active, members, votes, caller=caller)


def build_tally(
    suggestion_id: uuid.UUID,
    mode: str,
    members: Sequence[tuple[User, Family]],
    votes: Sequence[SuggestionVote],
    *,
    caller: User | None = None,
) -> TallyOut:
    """The pure half: given members and vote rows, produce the tally.

    Separated from the queries so the mode-change rules — the part of this feature most likely
    to be got subtly wrong — are testable without a database.
    """
    by_user = {vote.user_id: vote for vote in votes}
    member_by_id = {user.id: (user, family) for user, family in members}

    voters: list[VoterOut] = []
    not_voted: list[NotVotedOut] = []
    distribution = [0] * DISTRIBUTION_BUCKETS
    scores: list[int] = []
    up = down = unclear = 0

    for user, family in members:
        vote = by_user.get(user.id)
        if vote is None:
            not_voted.append(_not_voted(user, family))
            continue

        if mode == MODE_SCORE:
            value = vote.as_score
            if value is None:
                # A thumb under score voting. No number can honestly be invented from it, so
                # this person is outstanding — with their thumb still visible below.
                not_voted.append(_not_voted(user, family, has_unusable_vote=True))
                voters.append(_voter(user, family, thumb=vote.thumb, counted=False))
                continue
            scores.append(value)
            distribution[value] += 1
            voters.append(_voter(user, family, score=value))
            continue

        thumb = vote.as_thumb
        converted = vote.thumb is None
        if thumb == THUMB_UP:
            up += 1
        elif thumb == THUMB_DOWN:
            down += 1
        else:
            # A stored 5 under thumbs voting: neither camp, and rounding it into one would
            # invent an opinion the voter did not express.
            unclear += 1
        voters.append(_voter(user, family, thumb=thumb, score=vote.score, converted=converted))

    # Votes from people no longer on the trip stay in the database — the group's history is
    # real — but they are not rows in this tally, exactly as `polls` handles the same case.
    count = len(scores) if mode == MODE_SCORE else up + down + unclear
    eligible = len(members)
    average = round(sum(scores) / len(scores), 2) if scores else None
    none_count = eligible - count

    my_vote = None
    if caller is not None:
        mine = by_user.get(caller.id)
        if mine is not None:
            my_vote = MyVoteOut(score=mine.score, thumb=mine.thumb)

    return TallyOut(
        suggestion_id=suggestion_id,
        mode=mode,
        count=count,
        eligible_count=eligible,
        average=average,
        distribution=distribution,
        up=up,
        down=down,
        none=max(none_count, 0),
        unclear=unclear,
        my_vote=my_vote,
        voters=voters,
        not_voted=not_voted,
        insight=build_insight(mode, count, eligible, average, up, down, unclear),
    )


def _voter(
    user: User,
    family: Family | None,
    *,
    score: int | None = None,
    thumb: str | None = None,
    converted: bool = False,
    counted: bool = True,
) -> VoterOut:
    return VoterOut(
        user_id=user.id,
        display_name=user.display_name,
        family_id=family.id if family else None,
        family_color=family.color if family else None,
        family_color_custom=family.color_custom if family else None,
        score=score,
        thumb=thumb,
        converted=converted,
        counted=counted,
    )


def _not_voted(
    user: User, family: Family | None, *, has_unusable_vote: bool = False
) -> NotVotedOut:
    return NotVotedOut(
        user_id=user.id,
        display_name=user.display_name,
        family_id=family.id if family else None,
        family_color=family.color if family else None,
        family_color_custom=family.color_custom if family else None,
        has_unusable_vote=has_unusable_vote,
    )


def build_insight(
    mode: str,
    count: int,
    eligible: int,
    average: float | None,
    up: int,
    down: int,
    unclear: int,
) -> str:
    """The sentence the tally widgets use as their title.

    States the finding rather than the metric name (`design-system.md`), and **always names how
    many have not voted** when anybody has not — an average from two people out of nine is a
    different fact from the same average out of nine, and the title is where a reader who never
    expands the tally finds that out.
    """
    outstanding = max(eligible - count, 0)
    if count == 0:
        return "Nobody has voted yet."

    if mode == MODE_SCORE:
        lead = f"Averaging {average:g} out of 10 from {count} of {eligible}"
    elif up and down:
        lead = f"Splits the group — {up} for, {down} against"
    elif up:
        lead = f"{up} for, nobody against"
    elif down:
        lead = f"{down} against, nobody for"
    else:
        lead = "Nobody has come down either way"

    if mode == MODE_THUMBS and unclear:
        lead += f", {unclear} unclear"
    if outstanding:
        return f"{lead} — {outstanding} still to vote."
    return f"{lead} — everybody has voted."


# --- what needs my vote ----------------------------------------------------------------------------


async def get_pending_votes(
    db: AsyncSession, user: User, trip: Trip, *, exclude_own: bool = True
) -> PendingVotesOut:
    """V5: the suggestions this caller has not voted on.

    Rejected ones are excluded always — chasing a vote on something the group has already turned
    down is noise. The caller's own are excluded by default, because "6 need your vote" should
    not be partly your own proposals; `exclude_own=false` is there for the person who does want
    to record a preference on their own suggestion.
    """
    mine = select(SuggestionVote.suggestion_id).where(SuggestionVote.user_id == user.id)
    query = (
        select(Suggestion.id)
        .where(
            Suggestion.trip_id == trip.id,
            Suggestion.status != STATUS_REJECTED,
            Suggestion.id.notin_(mine),
        )
        .order_by(Suggestion.created_at)
    )
    if exclude_own:
        query = query.where(
            (Suggestion.created_by.is_(None)) | (Suggestion.created_by != user.id)
        )
    ids = list((await db.scalars(query)).all())
    return PendingVotesOut(count=len(ids), suggestion_ids=ids)
