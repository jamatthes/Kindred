"""Reading distances, and the organiser's force-recompute.

**The two `GET`s import only the read service**, which cannot call Google
(`app/services/distances.py`, and the import-graph test that enforces it). That is the HARD
INVARIANT in `plan/features/distances/design.md`: a request serving a page, a list, a card or a
panel never calls Distance Matrix. It reads `distance_cache` and falls back to a haversine
value computed in SQL.

`POST /distances/recompute` is the one route here that *causes* a call, which is why it is the
only one behind `require_organiser` and a stage guard — and why it answers with the number of
API calls it is about to make **before** making them.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.deps import (
    ActiveTrip,
    CurrentUser,
    DbDep,
    enforce_password_change,
    load_membership,
    require_member,
    require_organiser,
    require_stage,
)
from app.models import Suggestion, Trip
from app.schemas.common import ApiError
from app.schemas.distance import (
    BulkDistancesOut,
    RecomputeIn,
    RecomputeOut,
    SuggestionDistancesOut,
)
from app.services import distances as service

router = APIRouter(
    prefix="/distances",
    tags=["distances"],
    dependencies=[Depends(enforce_password_change), Depends(require_member)],
)

#: `GET /suggestions/{id}/distances` hangs off the suggestion, not off `/distances`.
suggestion_router = APIRouter(
    prefix="/suggestions",
    tags=["distances"],
    dependencies=[Depends(enforce_password_change), Depends(require_member)],
)

PLANNING_OR_HOLIDAY = Depends(require_stage("planning", "holiday"))


def _require_trip(trip: Trip | None) -> Trip:
    if trip is None:
        raise ApiError(409, "no_trip", "There is no trip yet.")
    return trip


async def _own_family_id(db, user, trip: Trip) -> uuid.UUID | None:
    membership = await load_membership(db, user.id, trip.id)
    return membership[0].id if membership else None


@suggestion_router.get(
    "/{suggestion_id}/distances",
    response_model=SuggestionDistancesOut,
    summary="Every family's distance to one suggestion",
)
async def read_suggestion_distances(
    suggestion_id: uuid.UUID, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> SuggestionDistancesOut:
    """Available in **every** stage, End included: the archive keeps its numbers.

    Families with no geocoded home appear with `status: no_home` rather than being dropped — a
    household missing from the list with no explanation is worse than one labelled "home address
    not set", which is also the prompt that gets it fixed.
    """
    current = _require_trip(trip)
    suggestion = await db.get(Suggestion, suggestion_id)
    if suggestion is None or suggestion.trip_id != current.id:
        raise ApiError(404, "not_found", "That suggestion does not exist.")

    return SuggestionDistancesOut(
        suggestion_id=suggestion.id,
        distances=await service.get_distances_for_suggestion(
            db,
            suggestion,
            current,
            own_family_id=await _own_family_id(db, user, current),
        ),
    )


@router.get(
    "",
    response_model=BulkDistancesOut,
    summary="Distances for many suggestions at once",
)
async def read_distances(
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
    suggestion_ids: Annotated[list[uuid.UUID] | None, Query()] = None,
    family_id: Annotated[uuid.UUID | None, Query()] = None,
) -> BulkDistancesOut:
    """The list view's form, so rendering fifty rows costs one request.

    `GET /suggestions` already embeds a `distances` array per item; this exists for the case
    where the client needs distances *alone* — switching the sort perspective to another
    family's values, which should not re-request every suggestion to get them.
    """
    if trip is None:
        return BulkDistancesOut()
    return BulkDistancesOut(
        distances=await service.get_distances_bulk(
            db,
            trip,
            suggestion_ids=suggestion_ids,
            family_id=family_id,
            own_family_id=await _own_family_id(db, user, trip),
        )
    )


@router.post(
    "/recompute",
    response_model=RecomputeOut,
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Force a recompute, retrying settled negatives",
)
async def recompute_distances(
    payload: RecomputeIn,
    db: DbDep,
    trip: ActiveTrip,
    background: BackgroundTasks,
) -> RecomputeOut:
    """**The only path that retries a `no_route` or a `failed`.**

    Those two are otherwise permanent, which is exactly what stops the cache re-asking Google
    forever for a pair that will never resolve — so the way back is a deliberate act by somebody
    who has been shown the cost first. The response states `estimated_api_calls` *before* the
    work runs: an organiser pressing this on a trip with sixty suggestions and six families
    should know it is about six calls and not three hundred and sixty.

    The stage guard refuses this in End, per point 4 of the hard invariant: no external call is
    made in a frozen trip, force-recompute included.
    """
    current = _require_trip(trip)
    pairs, suggestions = await service.recompute_scope(
        db, current, suggestion_id=payload.suggestion_id
    )

    # Queued, not awaited: the response is a statement of intent, and the caller must not wait
    # on Google to find out whether their button worked.
    background.add_task(_run_recompute, current.id, payload.suggestion_id)

    return RecomputeOut(
        queued_pairs=pairs,
        estimated_api_calls=service.estimated_api_calls(pairs, suggestions),
    )


async def _run_recompute(trip_id: uuid.UUID, suggestion_id: uuid.UUID | None) -> None:
    """Imported **inside the function**, so this router's module-level import graph stays free
    of the Google client and the read path's structural guarantee is not weakened by living in
    the same file as the one route that does spend money."""
    import logging  # noqa: PLC0415

    from app.core.db import SessionFactory  # noqa: PLC0415
    from app.services import distance_tasks  # noqa: PLC0415

    try:
        async with SessionFactory() as db:
            current = await db.get(Trip, trip_id)
            if current is None:
                return
            await distance_tasks.recompute(db, current, suggestion_id=suggestion_id)
    except Exception:  # noqa: BLE001 - a convenience must not surface as a failed request
        logging.getLogger(__name__).exception("Force-recompute failed for trip %s", trip_id)
