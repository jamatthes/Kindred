"""`PATCH /api/v1/trips/{trip_id}/stage` — the one endpoint that moves a trip's stage.

> **Ownership NOTE.** This route belongs to `holiday-stage`
> (`plan/features/holiday-stage/design.md` > Stage), not to `admin-console`. It is
> implemented here, now, because the console's stage stepper is unusable without it and
> because the alternative — a second `POST /admin/trip/stage` — is exactly the duplicate the
> 2026-08-11 ruling removed (`plan/features/admin-console/design.md` > Trip): *"Stage
> transitions have exactly one endpoint."*
>
> What is implemented is that document's spec and nothing more: the transition machine, the
> `revert` requirement, the history row and the broadcast. The **side effects of entering
> `end`** that `holiday-stage` specifies — deleting `live_locations` rows and emitting
> `location.cleared` for each — are deliberately absent, because that table does not exist
> until that feature ships. When it lands it owns this file: it adds those side effects, the
> `GET /trips/{trip_id}` read and the now/next route beside them.

Deliberately exempt from `require_stage`: this is the carve-out named in
`plan/architecture.md` ("End stage rejects all mutations except admin stage-change"), and it
is what makes the End freeze correctable rather than permanent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select, update

from app import ws
from app.deps import ActiveTrip, CurrentUser, DbDep, enforce_password_change, require_organiser
from app.models import Trip, TripStageTransition
from app.schemas.admin import (
    BACKWARD,
    FORWARD,
    StageChangeIn,
    StagePatchOut,
    blockers_for,
    trip_admin_out,
)
from app.schemas.common import ApiError

router = APIRouter(
    prefix="/trips",
    tags=["trips"],
    dependencies=[Depends(enforce_password_change), Depends(require_organiser)],
)

#: Codes this route can answer with. Named so the client can branch without parsing prose.
CODE_ILLEGAL_TRANSITION = "illegal_transition"  # 409
CODE_STAGE_BLOCKED = "stage_blocked"  # 409
CODE_REVERT_NOT_CONFIRMED = "revert_not_confirmed"  # 422


@router.patch(
    "/{trip_id}/stage",
    response_model=StagePatchOut,
    summary="Move the trip to another stage",
)
async def change_stage(
    trip_id: uuid.UUID,
    payload: StageChangeIn,
    db: DbDep,
    user: CurrentUser,
    trip: ActiveTrip,
) -> StagePatchOut:
    if trip is None or trip.id != trip_id:
        raise ApiError(404, "not_found", "No such trip.")

    target = payload.stage
    current = trip.stage

    # Idempotent no-op: two admins pressing the same button should not produce an error for
    # the slower one, because nothing is wrong — the trip is already where they wanted it.
    if target == current:
        return StagePatchOut(
            id=trip.id, stage=trip.stage, changed_at=datetime.now(UTC), changed_by=user.id
        )

    if FORWARD.get(current) == target:
        direction = "forward"
        blockers = blockers_for(trip)
        if blockers:
            raise ApiError(
                409,
                CODE_STAGE_BLOCKED,
                "Set the trip's start and end dates before starting the holiday.",
            )
    elif BACKWARD.get(current) == target:
        direction = "backward"
        if payload.reason != "revert":
            # Advancing and reverting differ by one field value, and only one of them can be
            # typed by mistake. Requiring the word is what stops a backward move being an
            # accidental payload.
            raise ApiError(
                422,
                CODE_REVERT_NOT_CONFIRMED,
                'Send reason="revert" to move the trip back a stage.',
            )
    else:
        raise ApiError(
            409,
            CODE_ILLEGAL_TRANSITION,
            f"A trip cannot go from {current} to {target}.",
        )

    # Conditional update: two admins transitioning at once must not both succeed. The second
    # one's `WHERE stage = <what they saw>` matches nothing, and they are told the trip moved
    # under them rather than silently overwriting the first.
    result = await db.execute(
        update(Trip)
        .where(Trip.id == trip.id, Trip.stage == current)
        .values(stage=target)
        .returning(Trip.id)
    )
    if result.first() is None:
        raise ApiError(
            409,
            CODE_ILLEGAL_TRANSITION,
            "Someone else changed the stage first. Reload to see where the trip is now.",
        )

    transition = TripStageTransition(
        trip_id=trip.id,
        from_stage=current,
        to_stage=target,
        direction=direction,
        changed_by=user.id,
    )
    db.add(transition)
    await db.commit()

    refreshed = await db.scalar(select(Trip).where(Trip.id == trip.id))
    assert refreshed is not None  # noqa: S101 - the row was just updated in this transaction

    # Everyone, not just admins: the whole app re-evaluates what is mutable, so a member with
    # a suggestion form open finds out before they press save rather than after.
    await ws.broadcast(
        trip.id,
        "stage.changed",
        {
            "trip_id": str(trip.id),
            "stage": target,
            "previous_stage": current,
            "changed_by": str(user.id),
            "changed_at": transition.created_at.isoformat()
            if transition.created_at
            else datetime.now(UTC).isoformat(),
            "was_revert": direction == "backward",
            "trip": trip_admin_out(refreshed).model_dump(mode="json"),
        },
    )

    return StagePatchOut(
        id=refreshed.id,
        stage=refreshed.stage,
        changed_at=transition.created_at or datetime.now(UTC),
        changed_by=user.id,
    )
