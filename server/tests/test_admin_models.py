"""Phase 2 — the login timestamp, the settings accessor, and the constraints the migration
promised for this feature's two tables.

The constraint tests exist because the schema is written twice — once in
`0001_schema.py` and once in `__table_args__` — and the suite builds from the second. A
constraint present in only the migration would pass every test here and fail in production;
these assert the models carry it too.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings_store import get_setting, set_setting
from app.models import Trip, TripCategorySetting, TripStageTransition, User
from tests.conftest import make_user

pytestmark = pytest.mark.asyncio


# --- last_login_at -------------------------------------------------------------------------


async def test_a_new_account_has_never_logged_in(db: AsyncSession) -> None:
    user = await make_user(db, "neverlogged")
    # Null, not the creation time: "invited but never used" is exactly the state AC-6 asks
    # about, and a defaulted timestamp would erase it.
    assert user.last_login_at is None


async def test_logging_in_records_the_timestamp(
    client, db: AsyncSession, trip: Trip
) -> None:
    await make_user(db, "loginstamp", password="a-real-password")

    response = await client.post(
        "/api/v1/auth/login", json={"username": "loginstamp", "password": "a-real-password"}
    )
    assert response.status_code == 200

    user = await db.scalar(select(User).where(User.username == "loginstamp"))
    assert user.last_login_at is not None


async def test_a_failed_login_does_not_record_a_timestamp(
    client, db: AsyncSession, trip: Trip
) -> None:
    await make_user(db, "wrongpw", password="the-right-one")

    response = await client.post(
        "/api/v1/auth/login", json={"username": "wrongpw", "password": "the-wrong-one"}
    )
    assert response.status_code == 401

    user = await db.scalar(select(User).where(User.username == "wrongpw"))
    assert user.last_login_at is None


# --- settings accessor ---------------------------------------------------------------------


async def test_a_missing_key_returns_the_default(db: AsyncSession) -> None:
    assert await get_setting(db, "never_written", "fallback") == "fallback"
    assert await get_setting(db, "never_written", None) is None


async def test_set_setting_round_trips_a_dict(db: AsyncSession) -> None:
    blob = {"checked_at": "2026-08-11T12:00:00Z", "apis": {"geocoding": {"status": "ok"}}}
    await set_setting(db, "google_api_status", blob)
    await db.commit()

    assert await get_setting(db, "google_api_status", None) == blob


async def test_set_setting_overwrites_rather_than_failing_twice(db: AsyncSession) -> None:
    await set_setting(db, "instance_name", "First")
    await set_setting(db, "instance_name", "Second")
    await db.commit()

    # Upsert, not insert: two admins saving at once must leave one of the two values, not a
    # unique violation for whichever lost.
    assert await get_setting(db, "instance_name", None) == "Second"


# --- the constraints -------------------------------------------------------------------------


async def test_a_category_outside_the_five_is_rejected(db: AsyncSession, trip: Trip) -> None:
    db.add(TripCategorySetting(trip_id=trip.id, category="weather", voting_mode="score"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_a_voting_mode_outside_the_two_is_rejected(
    db: AsyncSession, trip: Trip
) -> None:
    db.add(TripCategorySetting(trip_id=trip.id, category="poll", voting_mode="stars"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_one_row_per_category_per_trip(db: AsyncSession, trip: Trip) -> None:
    db.add(TripCategorySetting(trip_id=trip.id, category="poll", voting_mode="score"))
    await db.commit()
    db.add(TripCategorySetting(trip_id=trip.id, category="poll", voting_mode="thumbs"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_a_stage_direction_outside_the_two_is_rejected(
    db: AsyncSession, trip: Trip
) -> None:
    db.add(
        TripStageTransition(
            trip_id=trip.id, from_stage="planning", to_stage="holiday", direction="sideways"
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_history_survives_the_account_that_wrote_it(
    db: AsyncSession, trip: Trip
) -> None:
    user = await make_user(db, "stagemover")
    db.add(
        TripStageTransition(
            trip_id=trip.id,
            from_stage="planning",
            to_stage="holiday",
            direction="forward",
            changed_by=user.id,
        )
    )
    await db.commit()

    # Core DELETE, so the database's own ON DELETE rules decide what happens to the rows
    # that reference this user — which is the behaviour production gets. The ORM would
    # instead try to null out `user_settings.user_id` before deleting, and fail.
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()

    row = await db.scalar(select(TripStageTransition))
    # The history is about the trip, not about the person still existing.
    assert row is not None
    assert row.changed_by is None
