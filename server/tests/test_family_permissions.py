"""The role hierarchy, exercised from every side (roles revised 2026-08-11).

`plan/features/families/tasks.md` Phase 11 asks for: a head cannot touch another family; a
member cannot mutate anything; the owner and organisers can do everything; the owner cannot be
removed or demoted; an organiser cannot appoint another organiser; and the **spouse
asymmetry** — a spouse can manage every member of their family but is refused on the head, in
every direction.

The asymmetry gets the most attention here because it is the only rule in the feature that
depends on *who is being acted on* rather than on who is acting. That shape is easy to
implement on three routes and forget on a fourth, so the fourth is tested too.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import is_organiser, is_owner
from app.models import Family, FamilyMember, Trip, TripOrganiser, User
from tests.conftest import add_member, login_as, make_family, make_user

FAMILIES = "/api/v1/families"
INVITES = "/api/v1/invites"


def code(response: httpx.Response) -> str:
    return response.json()["detail"]["code"]


# --- the two kinds of role are independent -------------------------------------------------


async def test_an_organiser_is_still_an_ordinary_member_of_their_own_family(
    db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    """Trip roles and family roles do not imply each other."""
    user, family = organiser
    membership = await db.scalar(
        select(FamilyMember).where(FamilyMember.user_id == user.id)
    )
    assert membership.role == "member"
    assert await is_organiser(db, user, trip) is True
    assert await is_owner(user, trip) is False


async def test_a_head_of_family_is_not_an_organiser(
    db: AsyncSession, trip: Trip, family_admin: tuple[User, Family]
) -> None:
    user, _ = family_admin
    assert await is_organiser(db, user, trip) is False


async def test_the_owner_is_an_organiser_without_a_row(
    db: AsyncSession, trip: Trip
) -> None:
    owner = await make_user(db, "theowner")
    trip.owner_user_id = owner.id
    await db.commit()
    assert await is_owner(owner, trip) is True
    assert await is_organiser(db, owner, trip) is True


# --- what an organiser can do --------------------------------------------------------------


async def test_an_organiser_manages_any_family(
    client: httpx.AsyncClient,
    db: AsyncSession,
    organiser: tuple[User, Family],
    family_admin: tuple[User, Family],
) -> None:
    """FM-10: every cross-family power the owner has."""
    user, _ = organiser
    _, other_family = family_admin
    await login_as(client, db, user)

    assert (await client.post(FAMILIES, json={"name": "Made by organiser"})).status_code == 201
    assert (
        await client.patch(f"{FAMILIES}/{other_family.id}", json={"name": "Renamed"})
    ).status_code == 200
    assert (
        await client.patch(
            f"{FAMILIES}/{other_family.id}/location-policy", json={"sharing_allowed": False}
        )
    ).status_code == 200
    assert (
        await client.post(INVITES, json={"family_id": str(other_family.id)})
    ).status_code == 201
    assert (await client.post(INVITES, json={"family_id": None})).status_code == 201


async def test_an_organiser_sees_any_familys_full_address(
    client: httpx.AsyncClient,
    db: AsyncSession,
    organiser: tuple[User, Family],
    family_admin: tuple[User, Family],
) -> None:
    user, _ = organiser
    _, other = family_admin
    other.home_address = "12 Elm Row, Bristol"
    other.home_locality = "Bristol"
    await db.commit()

    await login_as(client, db, user)
    body = (await client.get(f"{FAMILIES}/{other.id}")).json()
    assert body["home_address"] == "12 Elm Row, Bristol"


async def test_an_organiser_cannot_appoint_another_organiser(
    db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    """FM-17, the limit that makes an organiser a delegate rather than a co-owner.

    The *endpoints* belong to `admin-console`, so what is asserted here is the dependency they
    will be built on: `require_owner` refuses an organiser. Without this, the owner's choice
    of who runs the trip lasts until the first organiser disagrees.
    """
    from fastapi import HTTPException  # noqa: PLC0415

    from app.deps import require_owner  # noqa: PLC0415

    user, _ = organiser
    with pytest.raises(HTTPException) as raised:
        await require_owner(user, trip)
    assert raised.value.status_code == 403
    assert raised.value.detail["code"] == "owner_only"


async def test_the_owner_can_appoint_organisers(
    db: AsyncSession, trip: Trip
) -> None:
    from app.deps import require_owner  # noqa: PLC0415

    owner = await make_user(db, "theowner")
    trip.owner_user_id = owner.id
    await db.commit()
    assert await require_owner(owner, trip) is owner


# --- what a plain member cannot do ---------------------------------------------------------


async def test_a_plain_member_cannot_mutate_anything(
    client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family]
) -> None:
    user, family = member
    await login_as(client, db, user)

    refused = [
        await client.post(FAMILIES, json={"name": "Mine"}),
        await client.patch(f"{FAMILIES}/{family.id}", json={"name": "Renamed"}),
        await client.put(f"{FAMILIES}/{family.id}/home", json={"home_address": "Anywhere"}),
        await client.delete(f"{FAMILIES}/{family.id}/home"),
        await client.patch(
            f"{FAMILIES}/{family.id}/location-policy", json={"sharing_allowed": False}
        ),
        await client.patch(
            f"{FAMILIES}/{family.id}/members/{user.id}", json={"role": "spouse"}
        ),
        await client.delete(f"{FAMILIES}/{family.id}/members/{user.id}"),
        await client.post(INVITES, json={"family_id": str(family.id)}),
        await client.delete(f"{FAMILIES}/{family.id}"),
    ]
    assert [r.status_code for r in refused] == [403] * len(refused)


async def test_a_head_cannot_touch_another_family(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    family_admin: tuple[User, Family],
) -> None:
    user, _ = family_admin
    theirs = await make_family(db, trip, "Theirs", color=5)
    stranger = await make_user(db, "stranger")
    await add_member(db, theirs, stranger, role="head")
    await login_as(client, db, user)

    refused = [
        await client.patch(f"{FAMILIES}/{theirs.id}", json={"name": "Mine now"}),
        await client.put(f"{FAMILIES}/{theirs.id}/home", json={"home_address": "Anywhere"}),
        await client.patch(
            f"{FAMILIES}/{theirs.id}/location-policy", json={"sharing_allowed": False}
        ),
        await client.delete(f"{FAMILIES}/{theirs.id}/members/{stranger.id}"),
        await client.post(INVITES, json={"family_id": str(theirs.id)}),
    ]
    assert [r.status_code for r in refused] == [403] * len(refused)


# --- the spouse asymmetry (FM-16) ----------------------------------------------------------


async def test_a_spouse_manages_the_family_like_the_head_does(
    client: httpx.AsyncClient,
    db: AsyncSession,
    spouse_household: tuple[Family, User, User, User],
) -> None:
    """Everything except acting on the head. A spouse who could do nothing would be a member
    with a nicer label."""
    family, _, spouse, child = spouse_household
    await login_as(client, db, spouse)

    assert (
        await client.patch(f"{FAMILIES}/{family.id}", json={"name": "Renamed by spouse"})
    ).status_code == 200
    assert (
        await client.put(f"{FAMILIES}/{family.id}/home", json={"home_address": "Anywhere"})
    ).status_code == 200
    assert (
        await client.patch(
            f"{FAMILIES}/{family.id}/location-policy", json={"sharing_allowed": False}
        )
    ).status_code == 200
    assert (
        await client.patch(
            f"{FAMILIES}/{family.id}/members/{child.id}",
            json={"location_sharing_allowed": False},
        )
    ).status_code == 200
    assert (
        await client.post(INVITES, json={"family_id": str(family.id)})
    ).status_code == 201
    assert (
        await client.delete(f"{FAMILIES}/{family.id}/members/{child.id}")
    ).status_code == 204


async def test_a_spouse_cannot_remove_the_head(
    client: httpx.AsyncClient,
    db: AsyncSession,
    spouse_household: tuple[Family, User, User, User],
) -> None:
    """Two people who can each remove the other is a family that can lock itself out."""
    family, head, spouse, _ = spouse_household
    await login_as(client, db, spouse)
    response = await client.delete(f"{FAMILIES}/{family.id}/members/{head.id}")
    assert response.status_code == 403
    assert code(response) == "head_protected"


async def test_a_spouse_cannot_demote_the_head(
    client: httpx.AsyncClient,
    db: AsyncSession,
    spouse_household: tuple[Family, User, User, User],
) -> None:
    family, head, spouse, _ = spouse_household
    await login_as(client, db, spouse)
    response = await client.patch(
        f"{FAMILIES}/{family.id}/members/{head.id}", json={"role": "member"}
    )
    assert code(response) == "head_protected"


async def test_a_spouse_cannot_switch_the_head_off_the_map(
    client: httpx.AsyncClient,
    db: AsyncSession,
    spouse_household: tuple[Family, User, User, User],
) -> None:
    """The asymmetry covers every field on the route, not only `role`.

    This is the fourth route — the one a per-route implementation forgets.
    """
    family, head, spouse, _ = spouse_household
    await login_as(client, db, spouse)
    response = await client.patch(
        f"{FAMILIES}/{family.id}/members/{head.id}",
        json={"location_sharing_allowed": False},
    )
    assert response.status_code == 403
    assert code(response) == "head_protected"


async def test_a_spouse_cannot_take_the_head_role(
    client: httpx.AsyncClient,
    db: AsyncSession,
    spouse_household: tuple[Family, User, User, User],
) -> None:
    """Taking the role would demote the incumbent as a side effect — the very thing the
    asymmetry forbids, reached by a side door. Refused as a role change, because that is the
    rule that catches it whoever the target happens to be."""
    family, _, spouse, _ = spouse_household
    await login_as(client, db, spouse)
    response = await client.patch(
        f"{FAMILIES}/{family.id}/members/{spouse.id}", json={"role": "head"}
    )
    assert response.status_code == 403
    assert code(response) == "spouse_cannot_promote"


async def test_a_spouse_cannot_promote_someone_else_to_spouse(
    client: httpx.AsyncClient,
    db: AsyncSession,
    spouse_household: tuple[Family, User, User, User],
) -> None:
    """FM-16: promotion is the head's, the owner's, or an organiser's. Otherwise a spouse
    could promote a confederate and outvote the arrangement the head made."""
    family, _, spouse, child = spouse_household
    await login_as(client, db, spouse)
    response = await client.patch(
        f"{FAMILIES}/{family.id}/members/{child.id}", json={"role": "spouse"}
    )
    assert response.status_code == 403
    assert code(response) == "spouse_cannot_promote"


async def test_the_head_can_do_all_of_it_to_the_spouse(
    client: httpx.AsyncClient,
    db: AsyncSession,
    spouse_household: tuple[Family, User, User, User],
) -> None:
    """The asymmetry is one-directional, and this is the other direction."""
    family, head, spouse, _ = spouse_household
    await login_as(client, db, head)

    assert (
        await client.patch(
            f"{FAMILIES}/{family.id}/members/{spouse.id}",
            json={"location_sharing_allowed": False},
        )
    ).status_code == 200
    assert (
        await client.patch(
            f"{FAMILIES}/{family.id}/members/{spouse.id}", json={"role": "member"}
        )
    ).status_code == 200
    assert (
        await client.delete(f"{FAMILIES}/{family.id}/members/{spouse.id}")
    ).status_code == 204


async def test_an_organiser_is_not_bound_by_the_spouse_asymmetry(
    client: httpx.AsyncClient,
    db: AsyncSession,
    organiser: tuple[User, Family],
    spouse_household: tuple[Family, User, User, User],
) -> None:
    """FM-10 gives an organiser every family's powers, and they are not a spouse of it."""
    user, _ = organiser
    family, head, _, _ = spouse_household
    await login_as(client, db, user)
    response = await client.patch(
        f"{FAMILIES}/{family.id}/members/{head.id}",
        json={"location_sharing_allowed": False},
    )
    assert response.status_code == 200


async def test_a_family_cannot_end_up_with_two_heads(
    db: AsyncSession, trip: Trip, spouse_household: tuple[Family, User, User, User]
) -> None:
    """The partial unique index, exercised directly — the last line of defence under the
    transfer logic."""
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

    family, _, _, child = spouse_household
    membership = await db.scalar(
        select(FamilyMember).where(FamilyMember.user_id == child.id)
    )
    membership.role = "head"
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_an_unknown_role_is_refused_by_the_database(
    db: AsyncSession, trip: Trip, family_admin: tuple[User, Family]
) -> None:
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

    user, _ = family_admin
    membership = await db.scalar(
        select(FamilyMember).where(FamilyMember.user_id == user.id)
    )
    membership.role = "regent"
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
