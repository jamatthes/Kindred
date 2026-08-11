"""Phase 4 — the trip router and the one stage endpoint.

The stage machine is tested exhaustively rather than representatively: there are nine
ordered pairs of stages and each one is either legal or a specific refusal, so enumerating
them costs a few lines and removes the question of which case was forgotten.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Trip, TripStageTransition, User
from tests.conftest import login_as, make_family, add_member, make_user

pytestmark = pytest.mark.asyncio

DATES = {"start_date": "2027-07-17", "end_date": "2027-07-24"}


async def _owner(db: AsyncSession, trip: Trip) -> User:
    """A real owner — `trips.owner_user_id` — rather than the platform-admin bypass."""
    user = await make_user(db, "tripowner")
    family = await make_family(db, trip, "Owners", color=3)
    await add_member(db, family, user, role="head")
    trip.owner_user_id = user.id
    await db.commit()
    return user


async def _set_stage(db: AsyncSession, trip: Trip, stage: str) -> None:
    trip.stage = stage
    await db.commit()


async def _set_dates(db: AsyncSession, trip: Trip) -> None:
    trip.start_date = date(2027, 7, 17)
    trip.end_date = date(2027, 7, 24)
    await db.commit()


# --- reading the trip ----------------------------------------------------------------------


async def test_the_console_reads_the_trip_with_its_affordances(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    body = (await client.get("/api/v1/admin/trip")).json()
    assert body["stage"] == "planning"
    assert body["blockers"] == ["missing_dates"]
    assert body["can_advance_to"] is None
    assert body["setup_complete"] is True


async def test_patching_the_dates_clears_the_blocker(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    body = (await client.patch("/api/v1/admin/trip", json=DATES)).json()
    assert body["blockers"] == []
    assert body["can_advance_to"] == "holiday"


async def test_an_end_date_before_the_stored_start_date_is_refused(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)
    await client.patch("/api/v1/admin/trip", json={"start_date": "2027-07-17"})

    # The schema cannot catch this: only `end_date` is in the payload, and the start date it
    # contradicts is already in the row.
    response = await client.patch("/api/v1/admin/trip", json={"end_date": "2027-07-10"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"


async def test_editing_the_trip_in_end_is_refused(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    await _set_stage(db, trip, "end")
    await login_as(client, db, owner)

    response = await client.patch("/api/v1/admin/trip", json={"name": "Renamed"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stage_forbidden"


# --- the stage machine ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "target"),
    [("planning", "holiday"), ("holiday", "end")],
)
async def test_every_legal_forward_move(
    client, db: AsyncSession, trip: Trip, start: str, target: str
) -> None:
    owner = await _owner(db, trip)
    await _set_dates(db, trip)
    await _set_stage(db, trip, start)
    await login_as(client, db, owner)

    response = await client.patch(
        f"/api/v1/trips/{trip.id}/stage", json={"stage": target}
    )
    assert response.status_code == 200, response.text
    assert response.json()["stage"] == target


@pytest.mark.parametrize(
    ("start", "target"),
    [("holiday", "planning"), ("end", "holiday")],
)
async def test_every_legal_backward_move(
    client, db: AsyncSession, trip: Trip, start: str, target: str
) -> None:
    owner = await _owner(db, trip)
    await _set_dates(db, trip)
    await _set_stage(db, trip, start)
    await login_as(client, db, owner)

    response = await client.patch(
        f"/api/v1/trips/{trip.id}/stage", json={"stage": target, "reason": "revert"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["stage"] == target


@pytest.mark.parametrize(
    ("start", "target"),
    [("planning", "end"), ("end", "planning")],
)
async def test_a_two_step_move_is_illegal_in_both_directions(
    client, db: AsyncSession, trip: Trip, start: str, target: str
) -> None:
    owner = await _owner(db, trip)
    await _set_dates(db, trip)
    await _set_stage(db, trip, start)
    await login_as(client, db, owner)

    response = await client.patch(
        f"/api/v1/trips/{trip.id}/stage", json={"stage": target, "reason": "revert"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "illegal_transition"


async def test_moving_to_the_current_stage_is_a_no_op_not_an_error(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    # Two admins pressing the same button: nothing is wrong, so nothing is reported wrong.
    response = await client.patch(
        f"/api/v1/trips/{trip.id}/stage", json={"stage": "planning"}
    )
    assert response.status_code == 200
    assert await db.scalar(select(TripStageTransition)) is None


async def test_a_backward_move_without_the_reason_is_refused(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    await _set_stage(db, trip, "holiday")
    await login_as(client, db, owner)

    response = await client.patch(
        f"/api/v1/trips/{trip.id}/stage", json={"stage": "planning"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "revert_not_confirmed"


async def test_advancing_without_dates_is_blocked(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    response = await client.patch(
        f"/api/v1/trips/{trip.id}/stage", json={"stage": "holiday"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stage_blocked"
    # And the trip did not move.
    await db.refresh(trip)
    assert trip.stage == "planning"


async def test_the_end_stage_still_lets_the_stage_itself_change(
    client, db: AsyncSession, trip: Trip
) -> None:
    """The carve-out that makes the freeze correctable rather than permanent."""
    owner = await _owner(db, trip)
    await _set_stage(db, trip, "end")
    await login_as(client, db, owner)

    response = await client.patch(
        f"/api/v1/trips/{trip.id}/stage", json={"stage": "holiday", "reason": "revert"}
    )
    assert response.status_code == 200


# --- concurrency and history -------------------------------------------------------------


async def test_two_admins_transitioning_at_once_leaves_one_winner(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    await _set_dates(db, trip)
    await login_as(client, db, owner)

    first = await client.patch(f"/api/v1/trips/{trip.id}/stage", json={"stage": "holiday"})
    assert first.status_code == 200

    # The second caller still believes the trip is in `planning` — which is exactly what the
    # conditional update is for. It matches no row, and they are told so rather than
    # overwriting the first transition.
    second = await client.patch(f"/api/v1/trips/{trip.id}/stage", json={"stage": "holiday"})
    assert second.status_code == 200  # idempotent: the trip is already where they wanted it

    await db.refresh(trip)
    assert trip.stage == "holiday"
    rows = (await db.execute(select(TripStageTransition))).scalars().all()
    assert len(rows) == 1


async def test_the_history_records_direction_and_actor(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    await _set_dates(db, trip)
    await login_as(client, db, owner)

    await client.patch(f"/api/v1/trips/{trip.id}/stage", json={"stage": "holiday"})
    await client.patch(
        f"/api/v1/trips/{trip.id}/stage", json={"stage": "planning", "reason": "revert"}
    )

    history = (await client.get("/api/v1/admin/trip/stage-history")).json()
    assert [(row["from_stage"], row["to_stage"], row["direction"]) for row in history] == [
        ("holiday", "planning", "backward"),  # newest first
        ("planning", "holiday", "forward"),
    ]
    assert history[0]["changed_by"]["display_name"] == owner.display_name


async def test_an_organiser_may_move_the_stage_too(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, object]
) -> None:
    user, _family = organiser
    await _set_dates(db, trip)
    await login_as(client, db, user)

    response = await client.patch(
        f"/api/v1/trips/{trip.id}/stage", json={"stage": "holiday"}
    )
    assert response.status_code == 200


async def test_a_plain_member_may_not(
    client, db: AsyncSession, trip: Trip, member: tuple[User, object]
) -> None:
    user, _family = member
    await _set_dates(db, trip)
    await login_as(client, db, user)

    response = await client.patch(
        f"/api/v1/trips/{trip.id}/stage", json={"stage": "holiday"}
    )
    assert response.status_code == 403
