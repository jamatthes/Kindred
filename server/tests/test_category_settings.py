"""Phase 5 — voting modes: who may read them, who may write them, and the self-healing read.

The read is deliberately open to every member and the write is not. That split is the whole
design: a member needs the mode to render the right control, and needs no say in what it is.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Trip, TripCategorySetting, User
from tests.conftest import add_member, login_as, make_family, make_user

pytestmark = pytest.mark.asyncio

ALL_FIVE = {"poll", "region", "accommodation", "activity", "meal"}


async def _owner(db: AsyncSession, trip: Trip) -> User:
    user = await make_user(db, "settingsowner")
    family = await make_family(db, trip, "Owners", color=3)
    await add_member(db, family, user, role="head")
    trip.owner_user_id = user.id
    await db.commit()
    return user


# --- the member-facing read ----------------------------------------------------------------


async def test_any_member_can_read_the_modes(
    client, db: AsyncSession, trip: Trip, member: tuple[User, object]
) -> None:
    user, _ = member
    await login_as(client, db, user)

    rows = (await client.get("/api/v1/trip/category-settings")).json()
    assert {row["category"] for row in rows} == ALL_FIVE
    # No vote counts on this route: how many votes exist is an organiser's business.
    assert all("existing_vote_count" not in row for row in rows)


async def test_the_seeded_defaults_are_the_documented_ones(
    client, db: AsyncSession, trip: Trip, member: tuple[User, object]
) -> None:
    user, _ = member
    await login_as(client, db, user)

    rows = {
        row["category"]: row["voting_mode"]
        for row in (await client.get("/api/v1/trip/category-settings")).json()
    }
    assert rows == {
        "poll": "score",
        "region": "score",
        "accommodation": "score",
        "activity": "thumbs",
        "meal": "thumbs",
    }


async def test_a_member_cannot_write_the_modes(
    client, db: AsyncSession, trip: Trip, member: tuple[User, object]
) -> None:
    user, _ = member
    await login_as(client, db, user)

    response = await client.put(
        "/api/v1/admin/category-settings",
        json={"settings": [{"category": "poll", "voting_mode": "thumbs"}]},
    )
    assert response.status_code == 403


# --- the admin read and write ----------------------------------------------------------------


async def test_the_console_read_carries_the_vote_counts(
    client, db: AsyncSession, trip: Trip
) -> None:
    await login_as(client, db, await _owner(db, trip))

    rows = (await client.get("/api/v1/admin/category-settings")).json()
    # Zero until `polls` and `map-suggestions` exist — returned rather than erroring, so the
    # console works from M1 onward.
    assert all(row["existing_vote_count"] == 0 for row in rows)


async def test_an_organiser_can_change_a_mode(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, object]
) -> None:
    user, _ = organiser
    await login_as(client, db, user)

    rows = (
        await client.put(
            "/api/v1/admin/category-settings",
            json={"settings": [{"category": "activity", "voting_mode": "score"}]},
        )
    ).json()
    assert next(r for r in rows if r["category"] == "activity")["voting_mode"] == "score"
    # The others are untouched by a partial PUT.
    assert next(r for r in rows if r["category"] == "meal")["voting_mode"] == "thumbs"


async def test_changing_a_mode_in_end_is_refused(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    trip.stage = "end"
    await db.commit()
    await login_as(client, db, owner)

    response = await client.put(
        "/api/v1/admin/category-settings",
        json={"settings": [{"category": "poll", "voting_mode": "thumbs"}]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stage_forbidden"


# --- self-healing ------------------------------------------------------------------------------


async def test_a_missing_row_is_recreated_on_read(
    client, db: AsyncSession, trip: Trip
) -> None:
    """A trip that predates the seeding rule must not render a partially blank editor."""
    await login_as(client, db, await _owner(db, trip))
    await db.execute(
        delete(TripCategorySetting).where(TripCategorySetting.category == "meal")
    )
    await db.commit()

    rows = (await client.get("/api/v1/admin/category-settings")).json()
    assert {row["category"] for row in rows} == ALL_FIVE
    assert next(r for r in rows if r["category"] == "meal")["voting_mode"] == "thumbs"

    stored = (
        (await db.execute(select(TripCategorySetting.category))).scalars().all()
    )
    assert set(stored) == ALL_FIVE


async def test_the_healing_read_does_not_overwrite_an_existing_choice(
    client, db: AsyncSession, trip: Trip
) -> None:
    await login_as(client, db, await _owner(db, trip))
    await client.put(
        "/api/v1/admin/category-settings",
        json={"settings": [{"category": "poll", "voting_mode": "thumbs"}]},
    )
    await db.execute(
        delete(TripCategorySetting).where(TripCategorySetting.category == "region")
    )
    await db.commit()

    rows = {
        row["category"]: row["voting_mode"]
        for row in (await client.get("/api/v1/admin/category-settings")).json()
    }
    # The repair inserts what is missing and leaves what is there — including a mode the
    # admin deliberately changed away from its default.
    assert rows["poll"] == "thumbs"
    assert rows["region"] == "score"


async def test_the_same_category_twice_in_one_put_is_refused(
    client, db: AsyncSession, trip: Trip
) -> None:
    await login_as(client, db, await _owner(db, trip))

    response = await client.put(
        "/api/v1/admin/category-settings",
        json={
            "settings": [
                {"category": "poll", "voting_mode": "score"},
                {"category": "poll", "voting_mode": "thumbs"},
            ]
        },
    )
    assert response.status_code == 422
