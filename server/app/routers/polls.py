"""Polls — the feature that replaces the family's spreadsheet.

Permissions and stage guards are dependencies, never handler-body checks (`CLAUDE.md`). The
End stage is read-only because every mutating route carries `require_stage("planning",
"holiday")`, not because anything here mentions `end`.

> NOTE (implementation): `design.md`'s permission column says `require_main_admin`. That
> dependency was renamed `require_organiser` when the role hierarchy was revised
> (`plan/overview.md` > Roles, 2026-08-11) — owner **or** an appointed organiser. Every
> "main admin" permission in this feature's docs means that. Family heads and spouses have
> **no** elevated rights in polls: their role governs their family's membership and home
> address, not group decisions.

**Nobody can write another person's vote.** `PUT /polls/{id}/scores` takes no `user_id`
anywhere in its request model, so the endpoint cannot express it — the guarantee is a
property of the shape rather than a check that could be forgotten.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import ws
from app.deps import (
    ActiveTrip,
    CurrentUser,
    DbDep,
    enforce_password_change,
    is_organiser,
    require_member,
    require_organiser,
    require_stage,
)
from app.models import (
    SUBJECT_POLL,
    Comment,
    Family,
    FamilyMember,
    Poll,
    PollOption,
    PollScore,
    Trip,
    User,
)
from app.schemas.comment import CommentIn, CommentOut
from app.schemas.common import ApiError, forbidden
from app.schemas.poll import (
    CloseIn,
    DecisionIn,
    DecisionOut,
    GroupCompletion,
    NudgeOut,
    OptionCreateIn,
    OptionPatchIn,
    PollCreateIn,
    PollOptionOut,
    PollOut,
    PollPatchIn,
    PollResultsOut,
    PollSummaryOut,
    ScoresPutIn,
)
from app.services import polls as service
from app.services import suggestions as suggestion_service

router = APIRouter(
    prefix="/polls",
    tags=["polls"],
    dependencies=[Depends(enforce_password_change)],
)

#: Spread into every mutating route, so adding one without it is a visible omission.
PLANNING_OR_HOLIDAY = Depends(require_stage("planning", "holiday"))


def _require_trip(trip: Trip | None) -> Trip:
    if trip is None:
        raise ApiError(409, "no_trip", "There is no trip yet.")
    return trip


# --- serialisation ---------------------------------------------------------------------------


async def _option_out(
    option: PollOption, *, caller: User, organiser: bool, poll: Poll
) -> PollOptionOut:
    """`can_delete` is computed here and nowhere else.

    The author may delete while nobody *else* has scored it; an organiser may always. The
    frontend renders the flag; it never derives the rule.
    """
    others_scored = any(score.user_id != caller.id for score in option.scores)
    can_delete = organiser or (
        option.created_by == caller.id and not others_scored and poll.is_open
    )
    return PollOptionOut(
        id=option.id,
        label=option.label,
        lat=option.lat,
        lng=option.lng,
        place_id=option.place_id,
        sort=option.sort,
        created_by=option.created_by,
        suggestion_id=option.suggestion_id,
        can_delete=can_delete,
    )


async def _summary(
    db: AsyncSession, poll: Poll, trip: Trip, caller: User
) -> PollSummaryOut:
    results = await service.build_results(db, poll, trip)
    completion = {str(m["user_id"]): m["completion"] for m in results["members"]}
    counts = {"complete": 0, "partial": 0, "none": 0}
    for value in completion.values():
        counts[value] = counts.get(value, 0) + 1

    decision = None
    if poll.decision_option_id is not None:
        won = next((o for o in poll.options if o.id == poll.decision_option_id), None)
        if won is not None:
            decision = DecisionOut(option_id=won.id, label=won.label)

    return PollSummaryOut(
        id=poll.id,
        title=poll.title,
        kind=poll.kind,
        status=poll.status,
        option_count=len(poll.options),
        comment_count=await service.comment_count(db, poll.id),
        my_completion=completion.get(str(caller.id), "none"),
        group_completion=GroupCompletion(
            complete=counts["complete"],
            partial=counts["partial"],
            none=counts["none"],
            total=len(results["members"]),
        ),
        decision=decision,
        created_at=poll.created_at,
    )


async def _poll_out(db: AsyncSession, poll: Poll, trip: Trip, caller: User) -> PollOut:
    summary = await _summary(db, poll, trip, caller)
    organiser = await is_organiser(db, caller, trip)
    results = await service.build_results(db, poll, trip)
    outstanding = results["non_responders"]["count"]

    decided = next(
        (o for o in poll.options if o.id == poll.decision_option_id), None
    )
    return PollOut(
        **summary.model_dump(),
        description=poll.description,
        allow_member_options=poll.allow_member_options,
        options=[
            await _option_out(o, caller=caller, organiser=organiser, poll=poll)
            for o in poll.options
        ],
        voting_mode=await service.get_voting_mode(db, trip.id),
        closed_at=poll.closed_at,
        decided_at=poll.decided_at,
        decided_by=poll.decided_by,
        can_nudge=organiser and poll.is_open and outstanding > 0
        and service.can_nudge_now(poll),
        next_nudge_at=service.next_nudge_at(poll),
        # False at M2: `map-suggestions` has not shipped, so the action is never rendered
        # and `POST .../seed-region` is a backstop rather than a reachable path.
        can_seed_region=(
            organiser
            and decided is not None
            and decided.is_located
            and service.suggestions_available()
        ),
    )


async def _results_out(db: AsyncSession, poll: Poll, trip: Trip) -> PollResultsOut:
    return PollResultsOut.model_validate(await service.build_results(db, poll, trip))


async def _broadcast_results(db: AsyncSession, poll: Poll, trip: Trip) -> None:
    """`poll.vote.updated` carries the **whole** recomputed results object, not a delta.

    Recomputation is one cheap query at this scale, and shipping the entire object removes
    any possibility of the matrix, the charts and the map drifting apart from partially
    applied deltas. Emitted after the commit, never before.
    """
    results = await _results_out(db, poll, trip)
    await ws.broadcast(
        trip.id,
        "poll.vote.updated",
        {"poll_id": str(poll.id), "results": results.model_dump(mode="json")},
    )


# --- polls -----------------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[PollSummaryOut],
    dependencies=[Depends(require_member)],
    summary="Every poll on the trip",
)
async def list_polls(db: DbDep, trip: ActiveTrip, user: CurrentUser) -> list[PollSummaryOut]:
    """PL-16. Ordered so the polls needing *this* caller's attention come first.

    Open-and-not-yet-complete, then open, then everything else — the ordering is a fact about
    the reader, which is why the UI shows a line explaining it rather than leaving it looking
    arbitrary.
    """
    if trip is None:
        return []
    polls = (
        (await db.scalars(service.poll_query().where(Poll.trip_id == trip.id)))
        .unique()
        .all()
    )
    summaries = [await _summary(db, poll, trip, user) for poll in polls]

    def _rank(summary: PollSummaryOut) -> tuple:
        needs_me = summary.status == "open" and summary.my_completion != "complete"
        return (not needs_me, summary.status != "open", -summary.created_at.timestamp())

    return sorted(summaries, key=_rank)


@router.post(
    "",
    response_model=PollOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Create a poll",
)
async def create_poll(
    payload: PollCreateIn, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> PollOut:
    current = _require_trip(trip)
    poll = Poll(
        trip_id=current.id,
        title=payload.title.strip(),
        description=(payload.description or "").strip() or None,
        kind=payload.kind,
        allow_member_options=payload.allow_member_options,
        created_by=user.id,
    )
    db.add(poll)
    await db.flush()
    for index, option in enumerate(payload.options):
        db.add(
            PollOption(
                poll_id=poll.id,
                label=option.label.strip(),
                lat=option.lat,
                lng=option.lng,
                place_id=option.place_id,
                sort=index,
                created_by=user.id,
            )
        )
    await db.commit()

    poll = await service.load_poll(db, poll.id, current)
    out = await _poll_out(db, poll, current, user)
    await ws.broadcast(
        current.id,
        "poll.created",
        {"poll": (await _summary(db, poll, current, user)).model_dump(mode="json")},
    )
    return out


@router.get(
    "/{poll_id}",
    response_model=PollOut,
    dependencies=[Depends(require_member)],
    summary="One poll",
)
async def read_poll(
    poll_id: uuid.UUID, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> PollOut:
    current = _require_trip(trip)
    return await _poll_out(db, await service.load_poll(db, poll_id, current), current, user)


@router.patch(
    "/{poll_id}",
    response_model=PollOut,
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Edit a poll's title, description or member-options setting",
)
async def update_poll(
    poll_id: uuid.UUID,
    payload: PollPatchIn,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
) -> PollOut:
    """`kind` is absent from the request model — it is immutable (see `schemas/poll.py`)."""
    current = _require_trip(trip)
    poll = await service.load_poll(db, poll_id, current)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(poll, field, value.strip() if isinstance(value, str) else value)
    await db.commit()

    poll = await service.load_poll(db, poll_id, current)
    await ws.broadcast(
        current.id,
        "poll.updated",
        {"poll": (await _summary(db, poll, current, user)).model_dump(mode="json")},
    )
    return await _poll_out(db, poll, current, user)


@router.delete(
    "/{poll_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Delete a poll",
)
async def delete_poll(poll_id: uuid.UUID, db: DbDep, trip: ActiveTrip) -> Response:
    current = _require_trip(trip)
    poll = await service.load_poll(db, poll_id, current)
    # `comments` is polymorphic and carries no FK to its subject, so this cascade is ours —
    # in the same transaction as the poll delete.
    await service.delete_poll_comments(db, poll.id)
    await db.delete(poll)
    await db.commit()

    await ws.broadcast(current.id, "poll.deleted", {"poll_id": str(poll_id)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{poll_id}/close",
    response_model=PollOut,
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Close a poll",
)
async def close_poll(
    poll_id: uuid.UUID,
    payload: CloseIn,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
) -> PollOut:
    """PL-12. Closing is not hiding: a closed poll stays fully visible with its results.

    The confirm naming how many people had not voted is the UI's (it has the count from
    `group_completion`); this route trusts that it happened, because a second server-side
    confirmation of a number the client already showed would be ceremony.
    """
    current = _require_trip(trip)
    poll = await service.load_poll(db, poll_id, current)
    service.close_poll(poll, user)
    await db.commit()

    poll = await service.load_poll(db, poll_id, current)
    await ws.broadcast(
        current.id,
        "poll.closed",
        {
            "poll_id": str(poll.id),
            "status": poll.status,
            "closed_at": poll.closed_at.isoformat() if poll.closed_at else None,
        },
    )
    return await _poll_out(db, poll, current, user)


@router.post(
    "/{poll_id}/reopen",
    response_model=PollOut,
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Reopen a poll",
)
async def reopen_poll(
    poll_id: uuid.UUID, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> PollOut:
    """No confirm: reopening restores capability rather than removing it."""
    current = _require_trip(trip)
    poll = await service.load_poll(db, poll_id, current)
    service.reopen_poll(poll)
    await db.commit()

    poll = await service.load_poll(db, poll_id, current)
    await ws.broadcast(
        current.id,
        "poll.closed",
        {"poll_id": str(poll.id), "status": poll.status, "closed_at": None},
    )
    return await _poll_out(db, poll, current, user)


# --- options ---------------------------------------------------------------------------------


@router.post(
    "/{poll_id}/options",
    response_model=PollOptionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_member), PLANNING_OR_HOLIDAY],
    summary="Add an option",
)
async def add_option(
    poll_id: uuid.UUID,
    payload: OptionCreateIn,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
) -> PollOptionOut:
    """PL-5. Members may add only when the poll allows it.

    The check is here rather than in a dependency because it depends on the *poll*, which a
    dependency would have to load a second time.
    """
    current = _require_trip(trip)
    poll = await service.load_poll(db, poll_id, current)
    if not poll.is_open:
        raise ApiError(409, "poll_closed", "This poll is closed.")

    organiser = await is_organiser(db, user, current)
    if not organiser and not poll.allow_member_options:
        raise ApiError(
            403,
            "member_options_disabled",
            "Only the trip's organisers can add options to this poll.",
        )

    highest = max((option.sort for option in poll.options), default=-1)
    option = PollOption(
        poll_id=poll.id,
        label=payload.label.strip(),
        lat=payload.lat,
        lng=payload.lng,
        place_id=payload.place_id,
        sort=highest + 1,
        created_by=user.id,
    )
    db.add(option)
    await db.commit()

    poll = await service.load_poll(db, poll_id, current)
    fresh = next(o for o in poll.options if o.id == option.id)
    out = await _option_out(fresh, caller=user, organiser=organiser, poll=poll)
    # The new column appears live for everyone, unscored — existing scores are untouched.
    await ws.broadcast(
        current.id,
        "poll_option.created",
        {"poll_id": str(poll.id), "option": out.model_dump(mode="json")},
    )
    await _broadcast_results(db, poll, current)
    return out


@router.patch(
    "/{poll_id}/options/{option_id}",
    response_model=PollOptionOut,
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Edit an option",
)
async def update_option(
    poll_id: uuid.UUID,
    option_id: uuid.UUID,
    payload: OptionPatchIn,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
) -> PollOptionOut:
    current = _require_trip(trip)
    poll = await service.load_poll(db, poll_id, current)
    option = _find_option(poll, option_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(option, field, value.strip() if isinstance(value, str) else value)
    await db.commit()

    poll = await service.load_poll(db, poll_id, current)
    fresh = next(o for o in poll.options if o.id == option_id)
    out = await _option_out(fresh, caller=user, organiser=True, poll=poll)
    await ws.broadcast(
        current.id,
        "poll_option.created",
        {"poll_id": str(poll.id), "option": out.model_dump(mode="json")},
    )
    return out


@router.delete(
    "/{poll_id}/options/{option_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_member), PLANNING_OR_HOLIDAY],
    summary="Delete an option",
)
async def delete_option(
    poll_id: uuid.UUID,
    option_id: uuid.UUID,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
) -> Response:
    """The author may delete while nobody else has scored it; an organiser may always.

    An organiser's delete cascades the scores, which is why the UI's confirm names how many
    will be lost. `polls.decision_option_id` is `ON DELETE SET NULL`, so deleting a decided
    option clears the decision without this route having to remember.
    """
    current = _require_trip(trip)
    poll = await service.load_poll(db, poll_id, current)
    option = _find_option(poll, option_id)
    organiser = await is_organiser(db, user, current)

    if not organiser:
        if option.created_by != user.id:
            raise forbidden("You can only remove an option you added.")
        if any(score.user_id != user.id for score in option.scores):
            raise ApiError(
                409,
                "option_has_scores",
                "Somebody has already scored that option, so it can no longer be removed.",
            )

    await db.delete(option)
    await db.commit()

    poll = await service.load_poll(db, poll_id, current)
    await ws.broadcast(
        current.id,
        "poll_option.deleted",
        {"poll_id": str(poll.id), "option_id": str(option_id)},
    )
    await _broadcast_results(db, poll, current)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _find_option(poll: Poll, option_id: uuid.UUID) -> PollOption:
    for option in poll.options:
        if option.id == option_id:
            return option
    raise ApiError(404, "not_found", "That option is not on this poll.")


# --- scores ----------------------------------------------------------------------------------


@router.put(
    "/{poll_id}/scores",
    response_model=PollResultsOut,
    dependencies=[Depends(require_member), PLANNING_OR_HOLIDAY],
    summary="Cast or change my own scores",
)
async def put_scores(
    poll_id: uuid.UUID,
    payload: ScoresPutIn,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
) -> PollResultsOut:
    """Writes **the caller's own** scores. There is no `user_id` in the request model.

    Returns the recomputed results so the client needs no follow-up request, and broadcasts
    the same object so every other open client converges on it.
    """
    current = _require_trip(trip)
    poll = await service.load_poll(db, poll_id, current)
    mode = await service.get_voting_mode(db, current.id)

    await service.upsert_scores(
        db,
        poll,
        user,
        [(entry.option_id, entry.score, entry.thumb) for entry in payload.scores],
        mode,
    )
    await db.commit()

    poll = await service.load_poll(db, poll_id, current)
    results = await _results_out(db, poll, current)
    await ws.broadcast(
        current.id,
        "poll.vote.updated",
        {"poll_id": str(poll.id), "results": results.model_dump(mode="json")},
    )
    return results


@router.delete(
    "/{poll_id}/scores/{option_id}",
    response_model=PollResultsOut,
    dependencies=[Depends(require_member), PLANNING_OR_HOLIDAY],
    summary="Clear my own score on one option",
)
async def clear_score(
    poll_id: uuid.UUID,
    option_id: uuid.UUID,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
) -> PollResultsOut:
    current = _require_trip(trip)
    poll = await service.load_poll(db, poll_id, current)
    await service.clear_score(db, poll, user, option_id)
    await db.commit()

    poll = await service.load_poll(db, poll_id, current)
    results = await _results_out(db, poll, current)
    await ws.broadcast(
        current.id,
        "poll.vote.updated",
        {"poll_id": str(poll.id), "results": results.model_dump(mode="json")},
    )
    return results


@router.get(
    "/{poll_id}/results",
    response_model=PollResultsOut,
    dependencies=[Depends(require_member)],
    summary="Averages, spread, the matrix and who has not voted",
)
async def read_results(
    poll_id: uuid.UUID, db: DbDep, trip: ActiveTrip
) -> PollResultsOut:
    current = _require_trip(trip)
    return await _results_out(db, await service.load_poll(db, poll_id, current), current)


# --- nudge -----------------------------------------------------------------------------------


@router.post(
    "/{poll_id}/nudge",
    response_model=NudgeOut,
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Prompt the people who have not voted",
)
async def nudge(
    poll_id: uuid.UUID, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> NudgeOut:
    """PL-10. Anyone who has completed the poll is never nudged."""
    current = _require_trip(trip)
    poll = await service.load_poll(db, poll_id, current)
    results = await service.build_results(db, poll, current)
    recipients = list(results["non_responders"]["users"])

    count = await service.nudge(db, poll, user, results)
    await db.commit()

    for person in recipients[:count]:
        await ws.send_user(
            person["user_id"],
            "notification.new",
            {
                "type": "poll.nudge",
                "poll_id": str(poll.id),
                "poll_title": poll.title,
                "deep_link": f"/polls/{poll.id}",
            },
        )

    return NudgeOut(
        nudged=count,
        next_nudge_at=service.next_nudge_at(poll),
        message=(
            "Everyone has voted — nobody needed a nudge."
            if count == 0
            else f"Nudged {count} {'person' if count == 1 else 'people'}."
        ),
    )


# --- decision ---------------------------------------------------------------------------------


@router.put(
    "/{poll_id}/decision",
    response_model=PollOut,
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Record the winning option",
)
async def set_decision(
    poll_id: uuid.UUID,
    payload: DecisionIn,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
) -> PollOut:
    """PL-13. The winner need not be the highest average — the group may decide otherwise,
    and the record reflects what was actually decided."""
    current = _require_trip(trip)
    poll = await service.load_poll(db, poll_id, current)
    option = _find_option(poll, payload.option_id)
    service.set_decision(poll, option, user)
    await db.commit()

    poll = await service.load_poll(db, poll_id, current)
    out = await _poll_out(db, poll, current, user)
    await ws.broadcast(
        current.id,
        "poll.decided",
        {
            "poll_id": str(poll.id),
            "decision": {"option_id": str(option.id), "label": option.label},
        },
    )
    return out


@router.delete(
    "/{poll_id}/decision",
    response_model=PollOut,
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Clear the recorded decision",
)
async def clear_decision_route(
    poll_id: uuid.UUID, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> PollOut:
    current = _require_trip(trip)
    poll = await service.load_poll(db, poll_id, current)
    service.clear_decision(poll)
    await db.commit()

    poll = await service.load_poll(db, poll_id, current)
    await ws.broadcast(
        current.id, "poll.decided", {"poll_id": str(poll.id), "decision": None}
    )
    return await _poll_out(db, poll, current, user)


@router.post(
    "/{poll_id}/decision/seed-region",
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Turn the winning option into a region on the map",
)
async def seed_region(
    poll_id: uuid.UUID, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> dict:
    """PL-14, implemented by `map-suggestions` at M3 (its `tasks.md` Phase 11b).

    Idempotent: a second call returns the same `suggestion_id` rather than creating a second
    overlapping region. The rules live in `services/polls.py::seed_region`; this route is the
    HTTP shell plus the broadcast, so a member with the map open watches the region appear.
    """
    current = _require_trip(trip)
    poll = await service.load_poll(db, poll_id, current)
    if poll.decision_option_id is None:
        raise ApiError(409, "no_decision", "Record a winning option first.")
    option = _find_option(poll, poll.decision_option_id)
    if not option.is_located:
        # A `422` rather than a `409`: the request is well-formed and the poll is in the right
        # state — the *option* is the thing that cannot be honoured, which is what
        # `map-suggestions/tasks.md` Phase 11b asks for ("non-geographic option -> 422").
        raise ApiError(
            422, "option_not_located", "That option has no location to put on the map."
        )

    already = option.suggestion_id
    suggestion_id = await service.seed_region(db, current, poll, option, user)
    await db.commit()

    if already is None:
        row = await suggestion_service.load_suggestion(db, suggestion_id, current)
        await ws.broadcast(
            current.id,
            "suggestion.created",
            {
                "suggestion": suggestion_service.serialise(
                    row, can_edit=True, can_change_status=True
                ).model_dump(mode="json")
            },
        )
    return {"suggestion_id": str(suggestion_id)}


# --- comments ----------------------------------------------------------------------------------


def _comment_out(comment: Comment, *, caller: User, organiser: bool, family) -> CommentOut:
    return CommentOut(
        id=comment.id,
        subject_type=comment.subject_type,
        subject_id=comment.subject_id,
        author_id=comment.author_id,
        author_name=(
            comment.author.display_name if comment.author else "Someone who has left"
        ),
        family_id=family[0] if family else None,
        family_color=family[1] if family else None,
        family_color_custom=family[2] if family else None,
        body=comment.body,
        created_at=comment.created_at,
        edited_at=comment.edited_at,
        can_edit=comment.author_id == caller.id,
        can_delete=organiser or comment.author_id == caller.id,
    )


async def _family_lookup(db: AsyncSession, trip: Trip) -> dict:
    rows = await db.execute(
        select(FamilyMember.user_id, Family.id, Family.color, Family.color_custom)
        .join(Family, Family.id == FamilyMember.family_id)
        .where(Family.trip_id == trip.id)
    )
    return {row[0]: (row[1], row[2], row[3]) for row in rows.all()}


@router.get(
    "/{poll_id}/comments",
    response_model=list[CommentOut],
    dependencies=[Depends(require_member)],
    summary="The poll's comment thread",
)
async def list_comments(
    poll_id: uuid.UUID, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> list[CommentOut]:
    current = _require_trip(trip)
    await service.load_poll(db, poll_id, current)
    organiser = await is_organiser(db, user, current)
    families = await _family_lookup(db, current)
    rows = (
        await db.scalars(
            select(Comment)
            .where(Comment.subject_type == SUBJECT_POLL, Comment.subject_id == poll_id)
            .order_by(Comment.created_at)
        )
    ).unique().all()
    return [
        _comment_out(
            row, caller=user, organiser=organiser, family=families.get(row.author_id)
        )
        for row in rows
    ]


@router.post(
    "/{poll_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_member), PLANNING_OR_HOLIDAY],
    summary="Comment on a poll",
)
async def add_comment(
    poll_id: uuid.UUID,
    payload: CommentIn,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
) -> CommentOut:
    """PL-11. A plain thread — @mention parsing belongs to `voting-comments` (M3), which
    upgrades this in place."""
    current = _require_trip(trip)
    await service.load_poll(db, poll_id, current)
    comment = Comment(
        subject_type=SUBJECT_POLL,
        subject_id=poll_id,
        author_id=user.id,
        body=payload.body.strip(),
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    families = await _family_lookup(db, current)
    out = _comment_out(
        comment,
        caller=user,
        organiser=await is_organiser(db, user, current),
        family=families.get(user.id),
    )
    await ws.broadcast(
        current.id,
        "comment.created",
        {
            "subject_type": SUBJECT_POLL,
            "subject_id": str(poll_id),
            "comment": out.model_dump(mode="json"),
        },
    )
    return out


comments_router = APIRouter(
    prefix="/comments",
    tags=["polls"],
    dependencies=[Depends(enforce_password_change), Depends(require_member)],
)


async def _load_comment(db: AsyncSession, comment_id: uuid.UUID) -> Comment:
    comment = await db.scalar(select(Comment).where(Comment.id == comment_id))
    if comment is None:
        raise ApiError(404, "not_found", "That comment does not exist.")
    return comment


@comments_router.patch(
    "/{comment_id}",
    response_model=CommentOut,
    dependencies=[PLANNING_OR_HOLIDAY],
    summary="Edit my own comment",
)
async def edit_comment(
    comment_id: uuid.UUID,
    payload: CommentIn,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
) -> CommentOut:
    """Author only. `edited_at` is set and shown as an "edited" marker — an edit that left no
    trace would falsify the discussion record."""
    current = _require_trip(trip)
    comment = await _load_comment(db, comment_id)
    if comment.author_id != user.id:
        raise forbidden("You can only edit your own comment.")

    comment.body = payload.body.strip()
    comment.edited_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(comment)

    families = await _family_lookup(db, current)
    return _comment_out(
        comment,
        caller=user,
        organiser=await is_organiser(db, user, current),
        family=families.get(user.id),
    )


@comments_router.delete(
    "/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[PLANNING_OR_HOLIDAY],
    summary="Delete a comment",
)
async def delete_comment(
    comment_id: uuid.UUID, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> Response:
    """Own comment, or an organiser deleting anyone's.

    The UI treats the two differently — undo for your own (low stakes, reversible by
    retyping), a real confirm for somebody else's, because it is not your content.
    """
    current = _require_trip(trip)
    comment = await _load_comment(db, comment_id)
    if comment.author_id != user.id and not await is_organiser(db, user, current):
        raise forbidden("You can only delete your own comment.")

    await db.delete(comment)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
