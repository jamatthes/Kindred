"""The admin console's API (AC-1 to AC-13).

Every route here is `require_organiser` — the owner or someone they appointed — except the
Organisers section, which is `require_owner`, and `PATCH /admin/settings`, which is
`require_owner` because instance settings are platform-level rather than trip-level
(rulings, 2026-08-11). Mutating trip data additionally carries
`require_stage("planning", "holiday")`, which is the whole of what makes the End stage a
freeze; nothing in this file mentions `end`.

**Stage transitions are not here.** They have exactly one endpoint,
`PATCH /api/v1/trips/{trip_id}/stage`, owned by `holiday-stage` and implemented in
`routers/trips.py`. This router computes the affordances (`can_advance_to`, `blockers`) that
the console's stepper renders; it does not execute the change.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import ws
from app.deps import (
    ActiveTrip,
    CurrentUser,
    DbDep,
    enforce_password_change,
    require_organiser,
    require_stage,
)
from app.models import Trip, TripStageTransition, User
from app.schemas.admin import (
    StageActorOut,
    StageTransitionOut,
    TripAdminOut,
    TripPatchIn,
    trip_admin_out,
)
from app.schemas.common import ApiError

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(enforce_password_change), Depends(require_organiser)],
)

#: Raised when a PATCH would leave the trip with an end date before its start date. Checked
#: against the *merged* values, because a partial update can send either one alone.
CODE_VALIDATION_ERROR = "validation_error"


def _require_trip(trip: Trip | None) -> Trip:
    if trip is None:
        raise ApiError(404, "not_found", "There is no trip yet.")
    return trip


# --- Section 1: the trip ---------------------------------------------------------------------


@router.get("/trip", response_model=TripAdminOut, summary="The trip and its affordances")
async def read_trip(trip: ActiveTrip) -> TripAdminOut:
    return trip_admin_out(_require_trip(trip))


@router.patch(
    "/trip",
    response_model=TripAdminOut,
    summary="Edit the trip's name, dates or timezone",
    dependencies=[Depends(require_stage("planning", "holiday"))],
)
async def patch_trip(
    payload: TripPatchIn, db: DbDep, trip: ActiveTrip
) -> TripAdminOut:
    """AC-2, and the write behind the AC-0 setup screen.

    The setup screen uses this route rather than a parallel one: a second endpoint for the
    first save would be a second place for the same validation to drift. A trip that has
    never been set up is by definition in Planning, so the stage guard is already satisfied
    and needs no exemption.
    """
    current = _require_trip(trip)
    changes = payload.model_dump(exclude_unset=True)

    # The cross-field rule has to be checked against what the row will *become*: a PATCH
    # carrying only `end_date` is the ordinary way to make the range invalid, and the schema
    # cannot see the stored start date.
    start = changes.get("start_date", current.start_date)
    end = changes.get("end_date", current.end_date)
    if start and end and end < start:
        raise ApiError(
            422,
            CODE_VALIDATION_ERROR,
            "The end date cannot be before the start date.",
        )

    for field, value in changes.items():
        setattr(current, field, value)
    await db.commit()
    await db.refresh(current)

    if changes:
        # The name is in every header and on the invite preview; the dates drive the
        # timeline. A client holding a stale copy would show yesterday's trip.
        await ws.broadcast(
            current.id,
            "trip.updated",
            {
                "trip": {
                    "id": str(current.id),
                    "name": current.name,
                    "stage": current.stage,
                    "start_date": current.start_date.isoformat()
                    if current.start_date
                    else None,
                    "end_date": current.end_date.isoformat() if current.end_date else None,
                    "timezone": current.timezone,
                }
            },
        )

    return trip_admin_out(current)


@router.get(
    "/trip/stage-history",
    response_model=list[StageTransitionOut],
    summary="Who moved the trip between stages, and when",
)
async def read_stage_history(db: DbDep, trip: ActiveTrip) -> list[StageTransitionOut]:
    """AC-3/AC-4's record. Newest first — the last thing that happened is the thing being
    checked, nine times in ten."""
    current = _require_trip(trip)
    rows = (
        (
            await db.execute(
                select(TripStageTransition, User)
                .outerjoin(User, User.id == TripStageTransition.changed_by)
                .where(TripStageTransition.trip_id == current.id)
                .order_by(TripStageTransition.created_at.desc())
            )
        )
        .tuples()
        .all()
    )
    return [
        StageTransitionOut(
            from_stage=row.from_stage,
            to_stage=row.to_stage,
            direction=row.direction,
            # Null rather than absent when the account is gone: the transition still
            # happened, and "someone who has since left" is the honest rendering.
            changed_by=(
                StageActorOut(user_id=actor.id, display_name=actor.display_name)
                if actor is not None
                else None
            ),
            created_at=row.created_at,
        )
        for row, actor in rows
    ]
