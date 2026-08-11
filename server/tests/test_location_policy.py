"""The test that matters most (`plan/features/families/tasks.md`, Phase 11).

The product's headline privacy promise is that **nobody can turn on another person's
live-location sharing** — not their family admin, not the main admin, nobody. `families`
introduced family-level policy alongside that promise, which is exactly the change that could
have quietly broken it.

So this file does not test a route. It enumerates *every* mutating route in the feature that
a family admin or the main admin can reach, fires each one at a member who has consent
switched off, with every body shape that might plausibly flip it, and asserts the column is
unchanged. A new route added without thought will fail here — which is the point, and is why
the enumeration is a list at the top rather than a set of hand-written cases.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    LOCATION_BLOCKED_CONSENT,
    LOCATION_BLOCKED_FAMILY,
    LOCATION_BLOCKED_MEMBER,
    Family,
    Trip,
    User,
    UserSettings,
    location_block_reason,
)
from tests.conftest import add_member, login_as, make_family, make_user


@pytest.fixture
async def household(db: AsyncSession, trip: Trip) -> tuple[Family, User, User]:
    """A family admin, and a member who has **not** consented to share their location."""
    family = await make_family(db, trip, "Household", color=1)
    admin = await make_user(db, "houseadmin")
    quiet = await make_user(db, "quietone")
    await add_member(db, family, admin, role="head")
    await add_member(db, family, quiet, role="member")
    return family, admin, quiet


async def _consent(db: AsyncSession, user: User) -> UserSettings:
    settings = await db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
    await db.refresh(settings)
    return settings


def _mutations(family: Family, target: User) -> list[tuple[str, str, dict | None]]:
    """Every mutating route in this feature, with the most hopeful body for each.

    "Most hopeful" meaning: if any of them *could* be made to write another user's consent,
    this is the request that would do it. Several of the bodies are deliberately not part of
    the route's schema — `live_location_enabled` on a member patch, for instance — because a
    schema that silently accepted an unknown key is one of the ways this could go wrong.
    """
    base = f"/api/v1/families/{family.id}"
    return [
        ("PATCH", base, {"name": "Renamed"}),
        ("PATCH", base, {"color": 4}),
        ("PATCH", f"{base}/location-policy", {"sharing_allowed": True}),
        ("PATCH", f"{base}/location-policy", {"member_default": True}),
        ("PATCH", f"{base}/location-policy", {"sharing_allowed": True, "member_default": True}),
        ("PATCH", f"{base}/members/{target.id}", {"role": "spouse"}),
        ("PATCH", f"{base}/members/{target.id}", {"location_sharing_allowed": True}),
        # Not in `MemberPatchIn`. If one of these ever starts being honoured, this test is
        # where it shows up.
        ("PATCH", f"{base}/members/{target.id}", {"location_sharing_enabled": True}),
        ("PATCH", f"{base}/members/{target.id}", {"live_location_enabled": True}),
        ("PUT", f"{base}/home", {"home_address": "12 Elm Row"}),
        ("POST", f"{base}/home/geocode", None),
    ]


async def _fire(client: httpx.AsyncClient, method: str, url: str, body: dict | None):
    if method == "PATCH":
        return await client.patch(url, json=body)
    if method == "PUT":
        return await client.put(url, json=body)
    return await client.post(url, json=body) if body else await client.post(url)


async def test_no_route_reachable_by_a_family_admin_turns_on_anothers_sharing(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    family, admin, quiet = household
    settings = await _consent(db, quiet)
    assert settings.live_location_enabled is False

    await login_as(client, db, admin)
    for method, url, body in _mutations(family, quiet):
        await _fire(client, method, url, body)
        await db.refresh(settings)
        assert settings.live_location_enabled is False, f"{method} {url} {body} flipped consent"


async def test_no_route_reachable_by_the_main_admin_turns_on_anothers_sharing(
    client: httpx.AsyncClient,
    db: AsyncSession,
    main_admin: User,
    household: tuple[Family, User, User],
) -> None:
    """FM-10 gives the main admin everything a family admin has — including this limit."""
    family, _, quiet = household
    settings = await _consent(db, quiet)

    await login_as(client, db, main_admin)
    for method, url, body in _mutations(family, quiet):
        await _fire(client, method, url, body)
        await db.refresh(settings)
        assert settings.live_location_enabled is False, f"{method} {url} {body} flipped consent"


async def test_an_admin_can_still_take_a_marker_away(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    """The controls are not inert — they can only ever *remove*. Both directions are the
    guarantee: one-way, not no-way."""
    family, admin, quiet = household
    settings = await _consent(db, quiet)
    settings.live_location_enabled = True
    await db.commit()

    await login_as(client, db, admin)
    response = await client.patch(
        f"/api/v1/families/{family.id}/members/{quiet.id}",
        json={"location_sharing_allowed": False},
    )
    assert response.status_code == 200
    assert response.json()["location_sharing_allowed"] is False

    await db.refresh(settings)
    assert settings.live_location_enabled is True  # their choice survives the admin's


async def test_a_member_keeps_their_own_consent_through_a_removal_and_return(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    """FM-15: removing someone deletes the *permission* with the membership row. Their own
    setting is theirs and is not collateral."""
    family, admin, quiet = household
    settings = await _consent(db, quiet)
    settings.live_location_enabled = True
    await db.commit()

    await login_as(client, db, admin)
    await client.patch(
        f"/api/v1/families/{family.id}/members/{quiet.id}",
        json={"location_sharing_allowed": False},
    )
    await client.delete(f"/api/v1/families/{family.id}/members/{quiet.id}")

    await db.refresh(settings)
    assert settings.live_location_enabled is True


# --- the read-time rule -------------------------------------------------------------------


def _member_of(family: Family, user: User):
    return next(m for m in family.members if m.user_id == user.id)


async def test_visibility_needs_all_three_permission_terms(
    db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    """The conjunction, with each term failed in turn.

    .. note::
       `tasks.md` asks this be asserted against `GET /live-locations`. That endpoint belongs
       to `holiday-stage` and does not exist yet, so the rule is asserted against the shared
       helper that feature is required to use — which is the thing that would actually drift.
       The endpoint-level assertion belongs in `holiday-stage`'s own suite, and its hand-off
       note says so.
    """
    family, _, quiet = household
    await db.refresh(family)
    member = _member_of(family, quiet)

    assert location_block_reason(family, member, consented=True) is None

    family.location_sharing_allowed = False
    assert location_block_reason(family, member, consented=True) == LOCATION_BLOCKED_FAMILY

    family.location_sharing_allowed = True
    member.location_sharing_allowed = False
    assert location_block_reason(family, member, consented=True) == LOCATION_BLOCKED_MEMBER

    member.location_sharing_allowed = True
    assert location_block_reason(family, member, consented=False) == LOCATION_BLOCKED_CONSENT


async def test_the_family_switch_is_reported_before_the_member_switch(
    db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    """A single reason, not a set, so the UI can say one true thing rather than three.

    `plan/features/families/design.md`: the result is identical either way; the ordering
    exists for the explanation.
    """
    family, _, quiet = household
    await db.refresh(family)
    member = _member_of(family, quiet)
    family.location_sharing_allowed = False
    member.location_sharing_allowed = False

    assert location_block_reason(family, member, consented=False) == LOCATION_BLOCKED_FAMILY


async def test_turning_the_family_switch_back_on_restores_exactly_who_had_consented(
    db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    """The whole reason the switch is a read-time filter rather than a write."""
    family, admin, quiet = household
    await db.refresh(family)
    consenting, abstaining = _member_of(family, admin), _member_of(family, quiet)

    family.location_sharing_allowed = False
    assert location_block_reason(family, consenting, consented=True) == LOCATION_BLOCKED_FAMILY
    assert location_block_reason(family, abstaining, consented=False) == LOCATION_BLOCKED_FAMILY

    family.location_sharing_allowed = True
    assert location_block_reason(family, consenting, consented=True) is None
    assert (
        location_block_reason(family, abstaining, consented=False) == LOCATION_BLOCKED_CONSENT
    )
