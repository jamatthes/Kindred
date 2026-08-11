"""The End-stage freeze, feature by feature.

**This file is the shared regression guard.** `plan/features/admin-console/tasks.md`: "Every
feature that adds a mutating route adds a line to it." The freeze is not implemented by any
one route — it is `require_stage` on all of them — so the only way to know it is real is to
enumerate a representative mutation from each shipped feature and watch it be refused.

The single exception is the stage change itself, which must keep working: that carve-out is
what makes a mistaken freeze correctable rather than permanent.

Features covered so far:

* `families` — found a family (the setup route), rename one, change a member's role, remove a
  member, invite.
* `admin-console` — trip settings, voting modes, user removal, organiser appointment.

Still to add, as each lands: `polls` (M2), `map-suggestions` / `voting-comments` (M3),
`itinerary-timeline` (M4), `holiday-stage` check-ins and live locations (M5).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Family, Invite, Trip, TripOrganiser, User
from tests.conftest import add_member, login_as, make_family, make_user

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def frozen(db: AsyncSession, trip: Trip) -> tuple[User, Family, User]:
    """A trip in `end`, its owner, a family, and an ordinary member to act on."""
    owner = await make_user(db, "freezeowner")
    owners = await make_family(db, trip, "Owners", color=3)
    await add_member(db, owners, owner, role="head")

    family = await make_family(db, trip, "Frozens", color=4)
    head = await make_user(db, "frozenhead")
    victim = await make_user(db, "frozenmember")
    await add_member(db, family, head, role="head")
    await add_member(db, family, victim, role="member")

    trip.owner_user_id = owner.id
    trip.stage = "end"
    await db.commit()
    return owner, family, victim


def _stage_forbidden(response) -> bool:
    return (
        response.status_code == 409
        and response.json()["detail"]["code"] == "stage_forbidden"
    )


# --- families ----------------------------------------------------------------------------------


async def test_creating_a_family_is_frozen(client, db, frozen) -> None:
    """Through `POST /families/mine`, which since 2026-08-11 is the only route that creates a
    family at all — the bare `POST /families` was withdrawn with the memberless-family shells
    it produced (`families` FM-1). The caller here is a pending founder, since that is who the
    route admits."""
    _owner, _family, _victim = frozen
    founder = await make_user(db, "latecomer")
    db.add(
        Invite(
            trip_id=(await db.scalar(select(Trip))).id,
            mode="create_family",
            token_hash="hash-latecomer",
            expires_at=datetime.now(UTC) + timedelta(days=7),
            used_by=founder.id,
            used_at=datetime.now(UTC),
        )
    )
    await db.commit()
    await login_as(client, db, founder)
    assert _stage_forbidden(
        await client.post("/api/v1/families/mine", json={"name": "Latecomers"})
    )


async def test_renaming_a_family_is_frozen(client, db, frozen) -> None:
    owner, family, _victim = frozen
    await login_as(client, db, owner)
    assert _stage_forbidden(
        await client.patch(f"/api/v1/families/{family.id}", json={"name": "Renamed"})
    )


async def test_changing_a_members_role_is_frozen(client, db, frozen) -> None:
    owner, family, victim = frozen
    await login_as(client, db, owner)
    assert _stage_forbidden(
        await client.patch(
            f"/api/v1/families/{family.id}/members/{victim.id}", json={"role": "spouse"}
        )
    )


async def test_removing_a_member_through_families_is_frozen(client, db, frozen) -> None:
    owner, family, victim = frozen
    await login_as(client, db, owner)
    assert _stage_forbidden(
        await client.delete(f"/api/v1/families/{family.id}/members/{victim.id}")
    )


async def test_creating_an_invite_is_frozen(client, db, frozen) -> None:
    owner, family, _victim = frozen
    await login_as(client, db, owner)
    assert _stage_forbidden(
        await client.post(
            "/api/v1/invites", json={"family_id": str(family.id), "expires_in_hours": 168}
        )
    )


# --- admin console -------------------------------------------------------------------------------


async def test_editing_the_trip_is_frozen(client, db, frozen) -> None:
    owner, _family, _victim = frozen
    await login_as(client, db, owner)
    assert _stage_forbidden(
        await client.patch("/api/v1/admin/trip", json={"name": "Renamed in the archive"})
    )


async def test_changing_a_voting_mode_is_frozen(client, db, frozen) -> None:
    owner, _family, _victim = frozen
    await login_as(client, db, owner)
    assert _stage_forbidden(
        await client.put(
            "/api/v1/admin/category-settings",
            json={"settings": [{"category": "poll", "voting_mode": "thumbs"}]},
        )
    )


async def test_removing_a_user_is_frozen(client, db, frozen) -> None:
    """It would alter the archived record of who was on the trip."""
    owner, _family, victim = frozen
    await login_as(client, db, owner)
    assert _stage_forbidden(await client.delete(f"/api/v1/admin/users/{victim.id}"))


async def test_appointing_an_organiser_is_frozen(client, db, frozen) -> None:
    owner, _family, victim = frozen
    await login_as(client, db, owner)
    assert _stage_forbidden(
        await client.post("/api/v1/admin/organisers", json={"user_id": str(victim.id)})
    )


async def test_demoting_an_organiser_is_frozen(
    client, db: AsyncSession, trip: Trip, frozen
) -> None:
    owner, _family, victim = frozen
    db.add(TripOrganiser(trip_id=trip.id, user_id=victim.id, granted_by=owner.id))
    await db.commit()

    await login_as(client, db, owner)
    assert _stage_forbidden(await client.delete(f"/api/v1/admin/organisers/{victim.id}"))


# --- the account operations that stay available ---------------------------------------------------


async def test_a_password_reset_still_works_in_end(client, db, frozen) -> None:
    """An account operation, not trip data: someone locked out of an archived trip still
    needs to be able to read it."""
    owner, _family, victim = frozen
    await login_as(client, db, owner)
    response = await client.post(
        f"/api/v1/admin/users/{victim.id}/reset-password", json={"confirm": True}
    )
    assert response.status_code == 200


async def test_instance_settings_still_work_in_end(client, db, frozen) -> None:
    owner, _family, _victim = frozen
    await login_as(client, db, owner)
    assert (
        await client.patch("/api/v1/admin/settings", json={"instance_name": "Still fine"})
    ).status_code == 200


# --- the carve-out ---------------------------------------------------------------------------------


async def test_the_stage_itself_can_still_be_changed(client, db, trip: Trip, frozen) -> None:
    """The one mutation `end` permits. Without it, a mistaken freeze would be permanent."""
    owner, _family, _victim = frozen
    await login_as(client, db, owner)

    response = await client.patch(
        f"/api/v1/trips/{trip.id}/stage", json={"stage": "holiday", "reason": "revert"}
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "holiday"
