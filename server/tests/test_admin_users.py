"""Phase 6 — the overview, the password reset and the removal.

The reset and the removal are the two routes in this feature that take something away from
somebody, so the tests are mostly about who may aim them at whom. The protected-target rule
is the interesting part: `require_organiser` opens the door, and does not reach another
organiser.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.wordlist import WORDS
from app.models import Family, FamilyMember, Session, Trip, TripOrganiser, User
from tests.conftest import add_member, login_as, make_family, make_user

pytestmark = pytest.mark.asyncio


async def _owner(db: AsyncSession, trip: Trip) -> User:
    user = await make_user(db, "theowner")
    family = await make_family(db, trip, "Owners", color=3)
    await add_member(db, family, user, role="head")
    trip.owner_user_id = user.id
    await db.commit()
    return user


async def _plain(db: AsyncSession, trip: Trip, username: str, role: str = "member") -> User:
    user = await make_user(db, username)
    family = await make_family(db, trip, f"{username.title()}s", color=4)
    await add_member(db, family, user, role="head" if role == "head" else role)
    return user


# --- overview ---------------------------------------------------------------------------------


async def test_the_overview_lists_families_and_members(
    client, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    body = (await client.get("/api/v1/admin/overview")).json()
    names = {row["display_name"] for row in body["members"]}
    assert owner.display_name in names
    assert member[0].display_name in names
    assert {family["name"] for family in body["families"]} >= {"Owners", "Membersons"}


async def test_the_role_flags_are_independent(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    body = (await client.get("/api/v1/admin/overview")).json()
    rows = {row["username"]: row for row in body["members"]}

    # The organiser fixture is deliberately a plain *member* of their own family: an
    # organiser who is also a head would let this pass for the wrong reason.
    assert rows["organiser"]["is_organiser"] is True
    assert rows["organiser"]["is_owner"] is False
    assert rows["organiser"]["family_role"] == "member"

    assert rows["theowner"]["is_owner"] is True
    assert rows["theowner"]["is_organiser"] is True  # the owner has every organiser power
    assert rows["theowner"]["family_role"] == "head"


async def test_never_logged_in_and_must_change_password_are_visible(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    locked = await make_user(db, "lockedout", must_change_password=True)
    family = await make_family(db, trip, "Lockedouts", color=5)
    await add_member(db, family, locked, role="head")
    await login_as(client, db, owner)

    rows = {
        row["username"]: row
        for row in (await client.get("/api/v1/admin/overview")).json()["members"]
    }
    assert rows["lockedout"]["must_change_password"] is True
    assert rows["lockedout"]["last_login_at"] is None  # AC-6: never got in


async def test_the_search_filters_both_tables(
    client, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    body = (await client.get("/api/v1/admin/overview?q=members")).json()
    assert {family["name"] for family in body["families"]} == {"Membersons"}
    assert {row["username"] for row in body["members"]} == {"plainmember"}


async def test_a_member_cannot_read_the_overview(
    client, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    await login_as(client, db, member[0])
    assert (await client.get("/api/v1/admin/overview")).status_code == 403


# --- reset password ------------------------------------------------------------------------------


async def test_a_reset_returns_a_readable_password_and_forces_a_change(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    target = await _plain(db, trip, "resetme")
    await login_as(client, db, owner)

    response = await client.post(
        f"/api/v1/admin/users/{target.id}/reset-password", json={"confirm": True}
    )
    assert response.status_code == 200
    temporary = response.json()["temporary_password"]

    words = temporary.split("-")
    assert len(words) == 4
    assert all(word in WORDS for word in words)

    await db.refresh(target)
    assert target.must_change_password is True


async def test_a_reset_revokes_every_session_the_target_held(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    target = await _plain(db, trip, "sessionholder")

    # The target is signed in elsewhere. A reset exists because someone has lost control of
    # an account; leaving a live session attached would defeat the point.
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415

    from app.main import create_app  # noqa: PLC0415

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as theirs:
        await login_as(theirs, db, target)
        assert (await theirs.get("/api/v1/auth/me")).status_code == 200

        await login_as(client, db, owner)
        await client.post(
            f"/api/v1/admin/users/{target.id}/reset-password", json={"confirm": True}
        )

        assert (await theirs.get("/api/v1/auth/me")).status_code == 401

    live = (
        (
            await db.execute(
                select(Session).where(
                    Session.user_id == target.id, Session.revoked_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    assert live == []


async def test_the_temporary_password_actually_logs_in(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    target = await _plain(db, trip, "willlogin")
    await login_as(client, db, owner)

    temporary = (
        await client.post(
            f"/api/v1/admin/users/{target.id}/reset-password", json={"confirm": True}
        )
    ).json()["temporary_password"]

    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415

    from app.main import create_app  # noqa: PLC0415

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as theirs:
        response = await theirs.post(
            "/api/v1/auth/login",
            json={"username": "willlogin", "password": temporary},
        )
        assert response.status_code == 200
        # And lands on the forced-change screen rather than the app: the gate reads
        # `must_change_password`, which the reset set.
        assert response.json()["user"]["next_step"] == "change_password"


async def test_resetting_yourself_is_refused(client, db: AsyncSession, trip: Trip) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    response = await client.post(
        f"/api/v1/admin/users/{owner.id}/reset-password", json={"confirm": True}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cannot_target_self"


async def test_a_reset_still_works_in_the_end_stage(
    client, db: AsyncSession, trip: Trip
) -> None:
    """An account operation, not trip data — the same principle foundation applies to
    password and theme changes."""
    owner = await _owner(db, trip)
    target = await _plain(db, trip, "lockedinend")
    trip.stage = "end"
    await db.commit()
    await login_as(client, db, owner)

    response = await client.post(
        f"/api/v1/admin/users/{target.id}/reset-password", json={"confirm": True}
    )
    assert response.status_code == 200


# --- the protected-target rule --------------------------------------------------------------------


async def test_an_organiser_cannot_reset_another_organiser(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    await _owner(db, trip)
    other = await _plain(db, trip, "secondorganiser")
    db.add(TripOrganiser(trip_id=trip.id, user_id=other.id))
    await db.commit()
    await login_as(client, db, organiser[0])

    response = await client.post(
        f"/api/v1/admin/users/{other.id}/reset-password", json={"confirm": True}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "target_protected"


async def test_the_owner_can_reset_an_organiser(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    response = await client.post(
        f"/api/v1/admin/users/{organiser[0].id}/reset-password", json={"confirm": True}
    )
    assert response.status_code == 200


async def test_nobody_can_reset_the_owner(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, organiser[0])

    response = await client.post(
        f"/api/v1/admin/users/{owner.id}/reset-password", json={"confirm": True}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cannot_target_owner"


async def test_an_organiser_can_still_reset_an_ordinary_member(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    await _owner(db, trip)
    target = await _plain(db, trip, "ordinary")
    await login_as(client, db, organiser[0])

    response = await client.post(
        f"/api/v1/admin/users/{target.id}/reset-password", json={"confirm": True}
    )
    assert response.status_code == 200


# --- removal -------------------------------------------------------------------------------------


async def test_removal_takes_the_membership_and_keeps_the_account(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    family = await make_family(db, trip, "Bigfamily", color=6)
    head = await make_user(db, "thehead2")
    leaving = await make_user(db, "leaving")
    await add_member(db, family, head, role="head")
    await add_member(db, family, leaving, role="member")
    await login_as(client, db, owner)

    assert (await client.delete(f"/api/v1/admin/users/{leaving.id}")).status_code == 204

    # The account survives: votes, comments and suggestions reference it, and deleting it
    # would falsify the record of how decisions were made.
    assert await db.scalar(select(User).where(User.id == leaving.id)) is not None
    assert (
        await db.scalar(select(FamilyMember).where(FamilyMember.user_id == leaving.id))
        is None
    )


async def test_removing_the_last_head_is_refused(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    lonely = await _plain(db, trip, "onlyhead", role="head")
    await login_as(client, db, owner)

    response = await client.delete(f"/api/v1/admin/users/{lonely.id}")
    assert response.status_code == 409
    # The same code `families` raises: one implementation, imported, so the two features
    # cannot start refusing for different reasons.
    assert response.json()["detail"]["code"] == "head_required"


async def test_removing_yourself_is_refused(client, db: AsyncSession, trip: Trip) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    response = await client.delete(f"/api/v1/admin/users/{owner.id}")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cannot_target_self"


async def test_removal_is_refused_in_the_end_stage(
    client, db: AsyncSession, trip: Trip
) -> None:
    """It would alter the archived record of who was on the trip."""
    owner = await _owner(db, trip)
    target = await _plain(db, trip, "archived")
    trip.stage = "end"
    await db.commit()
    await login_as(client, db, owner)

    response = await client.delete(f"/api/v1/admin/users/{target.id}")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stage_forbidden"


async def test_an_organiser_cannot_remove_another_organiser(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    await _owner(db, trip)
    other = await _plain(db, trip, "colleague")
    db.add(TripOrganiser(trip_id=trip.id, user_id=other.id))
    await db.commit()
    await login_as(client, db, organiser[0])

    response = await client.delete(f"/api/v1/admin/users/{other.id}")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "target_protected"
