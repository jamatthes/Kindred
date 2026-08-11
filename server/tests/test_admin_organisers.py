"""Phase 6a — organiser management (AC-13).

The one power the owner does not delegate. Most of these tests are about the *absence* of
side effects: demotion writes one row and touches nothing else, and proving that takes more
assertions than proving the row went away.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Family, FamilyMember, Session, Trip, TripOrganiser, User
from tests.conftest import add_member, login_as, make_family, make_user

pytestmark = pytest.mark.asyncio


async def _owner(db: AsyncSession, trip: Trip) -> User:
    user = await make_user(db, "orgowner")
    family = await make_family(db, trip, "Owners", color=3)
    await add_member(db, family, user, role="head")
    trip.owner_user_id = user.id
    await db.commit()
    return user


async def _member_of(db: AsyncSession, trip: Trip, username: str, role: str = "member") -> User:
    user = await make_user(db, username)
    family = await make_family(db, trip, f"{username.title()}s", color=5)
    await add_member(db, family, user, role=role)
    return user


# --- reading -----------------------------------------------------------------------------------


async def test_an_organiser_may_read_the_list(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    """Seeing who else holds the role is not itself a power."""
    await _owner(db, trip)
    await login_as(client, db, organiser[0])

    rows = (await client.get("/api/v1/admin/organisers")).json()
    assert [row["display_name"] for row in rows] == [organiser[0].display_name]


async def test_the_owner_is_not_in_the_list(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    rows = (await client.get("/api/v1/admin/organisers")).json()
    # The owner is never a row here: the role does not move through this screen.
    assert owner.display_name not in {row["display_name"] for row in rows}


async def test_a_plain_member_cannot_read_the_list(
    client, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    await _owner(db, trip)
    await login_as(client, db, member[0])
    assert (await client.get("/api/v1/admin/organisers")).status_code == 403


# --- appointing ----------------------------------------------------------------------------------


async def test_the_owner_appoints_and_the_grant_records_who_did_it(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    target = await _member_of(db, trip, "newhelper")
    await login_as(client, db, owner)

    response = await client.post(
        "/api/v1/admin/organisers", json={"user_id": str(target.id)}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == str(target.id)
    assert body["granted_by"]["display_name"] == owner.display_name
    assert body["family"]["name"] == "Newhelpers"


async def test_appointing_twice_is_idempotent(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    target = await _member_of(db, trip, "twice")
    await login_as(client, db, owner)

    first = await client.post("/api/v1/admin/organisers", json={"user_id": str(target.id)})
    second = await client.post("/api/v1/admin/organisers", json={"user_id": str(target.id)})

    assert first.status_code == 201
    # The desired end state already holds; a 409 would be a worse answer than saying so.
    assert second.status_code == 200

    grants = (
        (
            await db.execute(
                select(TripOrganiser).where(TripOrganiser.user_id == target.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(grants) == 1


async def test_an_organiser_cannot_appoint(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    """The decision log's line, enforced: organisers cannot promote organisers, including
    each other."""
    await _owner(db, trip)
    target = await _member_of(db, trip, "wouldbe")
    await login_as(client, db, organiser[0])

    response = await client.post(
        "/api/v1/admin/organisers", json={"user_id": str(target.id)}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "owner_only"


async def test_appointing_the_owner_is_refused(client, db: AsyncSession, trip: Trip) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    response = await client.post("/api/v1/admin/organisers", json={"user_id": str(owner.id)})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cannot_appoint_owner"


async def test_appointing_someone_not_on_the_trip_is_refused(
    client, db: AsyncSession, trip: Trip, outsider: User
) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    response = await client.post(
        "/api/v1/admin/organisers", json={"user_id": str(outsider.id)}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "not_on_trip"


async def test_a_head_of_family_can_also_be_an_organiser(
    client, db: AsyncSession, trip: Trip
) -> None:
    """The two kinds of role are independent; this route does not touch the family one."""
    owner = await _owner(db, trip)
    head = await _member_of(db, trip, "bothroles", role="head")
    await login_as(client, db, owner)

    body = (
        await client.post("/api/v1/admin/organisers", json={"user_id": str(head.id)})
    ).json()
    assert body["family_role"] == "head"


# --- demoting ------------------------------------------------------------------------------------


async def test_demotion_removes_the_grant_and_nothing_else(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    target = await _member_of(db, trip, "demoteme", role="head")
    db.add(TripOrganiser(trip_id=trip.id, user_id=target.id, granted_by=owner.id))
    await db.commit()

    # They are signed in, and stay signed in: this is a permission change, not an access
    # revocation.
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415

    from app.main import create_app  # noqa: PLC0415

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as theirs:
        await login_as(theirs, db, target)
        assert (await theirs.get("/api/v1/admin/organisers")).status_code == 200

        await login_as(client, db, owner)
        assert (
            await client.delete(f"/api/v1/admin/organisers/{target.id}")
        ).status_code == 204

        # Same session, still valid for everything a member may do…
        assert (await theirs.get("/api/v1/auth/me")).status_code == 200
        # …and refused by `require_organiser` on the very next request.
        assert (await theirs.get("/api/v1/admin/organisers")).status_code == 403

    membership = await db.scalar(
        select(FamilyMember).where(FamilyMember.user_id == target.id)
    )
    assert membership is not None
    assert membership.role == "head"  # their family role is untouched

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
    assert live != []  # no session revocation, and therefore no `session.revoked`


async def test_demoting_the_owner_is_refused(client, db: AsyncSession, trip: Trip) -> None:
    owner = await _owner(db, trip)
    await login_as(client, db, owner)

    response = await client.delete(f"/api/v1/admin/organisers/{owner.id}")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cannot_demote_owner"


async def test_demoting_someone_who_is_not_an_organiser_is_a_404(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    target = await _member_of(db, trip, "notone")
    await login_as(client, db, owner)

    assert (
        await client.delete(f"/api/v1/admin/organisers/{target.id}")
    ).status_code == 404


async def test_an_organiser_cannot_demote(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    other = await _member_of(db, trip, "colleague")
    db.add(TripOrganiser(trip_id=trip.id, user_id=other.id, granted_by=owner.id))
    await db.commit()
    await login_as(client, db, organiser[0])

    response = await client.delete(f"/api/v1/admin/organisers/{other.id}")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "owner_only"


async def test_appointing_and_demoting_are_refused_in_the_end_stage(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    target = await _member_of(db, trip, "frozen")
    trip.stage = "end"
    await db.commit()
    await login_as(client, db, owner)

    appoint = await client.post(
        "/api/v1/admin/organisers", json={"user_id": str(target.id)}
    )
    demote = await client.delete(f"/api/v1/admin/organisers/{target.id}")
    assert appoint.status_code == 409
    assert appoint.json()["detail"]["code"] == "stage_forbidden"
    assert demote.status_code == 409
    assert demote.json()["detail"]["code"] == "stage_forbidden"
