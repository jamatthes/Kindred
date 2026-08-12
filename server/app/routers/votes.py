"""Voting on suggestions.

**Nobody can write another person's vote.** `PUT /suggestions/{id}/vote` takes no `user_id`
anywhere in its request model, so the endpoint cannot express it — the guarantee is a property
of the shape rather than a check that could be forgotten. That is the same construction
`polls`' score endpoint uses, and it is the reason the permissions table's "vote on behalf of
someone else: No / No / No" row needs no dependency to enforce it.

`PUT` rather than `POST` because voting is idempotent: the same body twice leaves the same
state, which is exactly what an unreliable mobile connection needs.

Reads work in **every** stage, including `end` — a frozen trip is an archive, and an archive
whose tallies had disappeared would be a worse record than the spreadsheet this replaced.
Only the mutations carry the stage guard.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app import ws
from app.deps import (
    ActiveTrip,
    CurrentUser,
    DbDep,
    enforce_password_change,
    require_member,
    require_stage,
)
from app.models import Suggestion, Trip
from app.schemas.common import ApiError
from app.schemas.vote import PendingVotesOut, TallyOut, VoteIn
from app.services import votes as service

router = APIRouter(
    prefix="/suggestions",
    tags=["votes"],
    dependencies=[Depends(enforce_password_change), Depends(require_member)],
)

#: `GET /me/pending-votes` is the "needs my vote" count, and belongs to the caller rather than
#: to any one suggestion — hence its own router under `/me` rather than a query parameter on
#: the list.
pending_router = APIRouter(
    prefix="/me",
    tags=["votes"],
    dependencies=[Depends(enforce_password_change), Depends(require_member)],
)

#: Spread into every mutating route, so adding one without it is a visible omission.
PLANNING_OR_HOLIDAY = Depends(require_stage("planning", "holiday"))


def _require_trip(trip: Trip | None) -> Trip:
    if trip is None:
        raise ApiError(409, "no_trip", "There is no trip yet.")
    return trip


async def _load(db, suggestion_id: uuid.UUID, trip: Trip) -> Suggestion:
    suggestion = await db.get(Suggestion, suggestion_id)
    if suggestion is None or suggestion.trip_id != trip.id:
        raise ApiError(404, "not_found", "That suggestion does not exist.")
    return suggestion


async def _tally_and_broadcast(
    db, suggestion: Suggestion, trip: Trip, caller
) -> TallyOut:
    """Recompute, broadcast, return — in that order, after the commit.

    The broadcast carries the whole tally **minus `my_vote`**: that field is per recipient and
    every client already knows the vote it just cast, so putting it on a room-wide frame would
    be both useless and a way for one client to overwrite another's local state.
    """
    tally = await service.get_tally(db, suggestion, trip, caller=caller)
    await ws.broadcast(
        trip.id,
        "suggestion.vote.updated",
        {
            "suggestion_id": str(suggestion.id),
            "tally": tally.without_my_vote().model_dump(mode="json"),
        },
    )
    return tally


@router.get(
    "/{suggestion_id}/votes",
    response_model=TallyOut,
    summary="The tally, with attribution and who has not voted",
)
async def read_tally(
    suggestion_id: uuid.UUID, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> TallyOut:
    """Available in every stage — the End-stage archive keeps its numbers."""
    current = _require_trip(trip)
    suggestion = await _load(db, suggestion_id, current)
    return await service.get_tally(db, suggestion, current, caller=user)


@router.put(
    "/{suggestion_id}/vote",
    response_model=TallyOut,
    dependencies=[PLANNING_OR_HOLIDAY],
    summary="Cast or change my own vote",
)
async def put_vote(
    suggestion_id: uuid.UUID,
    payload: VoteIn,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
) -> TallyOut:
    """Writes **the caller's own** vote. There is no `user_id` in the request model.

    A vote in the wrong mode is a `422` naming the category's actual mode, so the client can
    refetch settings and re-render the right control rather than guessing why it failed.
    """
    current = _require_trip(trip)
    suggestion = await _load(db, suggestion_id, current)
    mode = await service.resolve_voting_mode(db, current.id, suggestion.type)

    await service.upsert_vote(
        db, suggestion, user, score=payload.score, thumb=payload.thumb, mode=mode
    )
    await db.commit()

    return await _tally_and_broadcast(db, suggestion, current, user)


@router.delete(
    "/{suggestion_id}/vote",
    response_model=TallyOut,
    dependencies=[PLANNING_OR_HOLIDAY],
    summary="Clear my own vote",
)
async def delete_vote(
    suggestion_id: uuid.UUID, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> TallyOut:
    """Removes the row, so the caller counts as "not yet voted" again — which is what keeps the
    "needs my vote" affordance honest (V2)."""
    current = _require_trip(trip)
    suggestion = await _load(db, suggestion_id, current)
    await service.clear_vote(db, suggestion, user)
    await db.commit()

    return await _tally_and_broadcast(db, suggestion, current, user)


@pending_router.get(
    "/pending-votes",
    response_model=PendingVotesOut,
    summary="The suggestions still waiting for my vote",
)
async def read_pending_votes(
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
    exclude_own: Annotated[bool, "Count my own suggestions too when false"] = True,
) -> PendingVotesOut:
    """V5's "6 need your vote".

    The ids come back with the count so activating the affordance can filter the list without a
    second round trip — the filter state is shared with `map-suggestions`, and a count with no
    ids would have made the client fetch everything and diff it.
    """
    if trip is None:
        return PendingVotesOut()
    return await service.get_pending_votes(db, user, trip, exclude_own=exclude_own)
