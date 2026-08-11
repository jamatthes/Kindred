"""`require_pending_family` and `POST /families/mine` (FM-13).

This is the one hole in `require_member`'s wall, so it gets the treatment a hole deserves:
the allow case and all four denial cases named in `plan/features/families/tasks.md`, plus the
double-submit and colour-exhaustion edges from the design's table.

`plan/architecture.md` is explicit that this route exists as a documented exemption rather
than a quiet one — "a second route in this category is a decision to be documented". The
tests below are what make the exemption checkable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.onboarding import is_pending_family, resolve_next_step
from app.models import Family, FamilyMember, Invite, Trip, User, UserSettings
from app.services.google import FakeGeocoder, GeocodeResult
from tests.conftest import add_member, login_as, make_family, make_user

MINE = "/api/v1/families/mine"


def code(response: httpx.Response) -> str:
    return response.json()["detail"]["code"]


async def _consume_invite(
    db: AsyncSession, trip: Trip, user: User, *, family: Family | None = None
) -> Invite:
    """Mark ``user`` as having accepted an invite, exactly as the accept route will."""
    invite = Invite(
        trip_id=trip.id,
        family_id=family.id if family else None,
        token_hash=f"hash-{user.username}",
        expires_at=datetime.now(UTC) + timedelta(days=7),
        used_by=user.id,
        used_at=datetime.now(UTC),
    )
    db.add(invite)
    await db.commit()
    return invite


@pytest.fixture
async def pending(db: AsyncSession, trip: Trip) -> User:
    """Someone who accepted a new-family invite and has not yet named their family."""
    user = await make_user(db, "newfounder")
    await _consume_invite(db, trip, user)
    return user


# --- the predicate ------------------------------------------------------------------------


async def test_the_allow_case(db: AsyncSession, pending: User) -> None:
    assert await is_pending_family(db, pending) is True


async def test_denied_an_existing_member(
    db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    """There is no path to a second family."""
    user, _ = member
    await _consume_invite(db, trip, user)
    assert await is_pending_family(db, user) is False


async def test_denied_a_removed_member(db: AsyncSession, trip: Trip) -> None:
    """Someone removed from the trip cannot re-admit themselves.

    Their membership row is gone, so the "no family" half passes — the invite half is what
    refuses them, because the invite that let them in was family-scoped.
    """
    family = await make_family(db, trip, "Wasmine", color=1)
    user = await make_user(db, "removed")
    await _consume_invite(db, trip, user, family=family)
    assert await is_pending_family(db, user) is False


async def test_denied_someone_with_no_invite_at_all(db: AsyncSession, trip: Trip) -> None:
    stranger = await make_user(db, "stranger")
    assert await is_pending_family(db, stranger) is False


async def test_denied_when_the_invite_was_family_scoped(
    db: AsyncSession, trip: Trip
) -> None:
    """A join invite is not a licence to found a family."""
    family = await make_family(db, trip, "Existing", color=2)
    user = await make_user(db, "joiner")
    await _consume_invite(db, trip, user, family=family)
    assert await is_pending_family(db, user) is False


async def test_the_platform_admin_is_never_pending(
    db: AsyncSession, trip: Trip, main_admin: User
) -> None:
    """The seeded admin has no family on first boot. Sending them to a family setup screen
    would lock them out of their own instance."""
    assert await is_pending_family(db, main_admin) is False
    assert await resolve_next_step(db, main_admin, trip) == "app"


# --- the gate -----------------------------------------------------------------------------


async def test_a_pending_founder_is_routed_to_the_family_setup_screen(
    db: AsyncSession, trip: Trip, pending: User
) -> None:
    assert await resolve_next_step(db, pending, trip) == "setup_family"


async def test_the_password_change_outranks_the_family_setup(
    db: AsyncSession, trip: Trip, pending: User
) -> None:
    """Order matters: reversing any two of these lets someone past a gate meant to be shut."""
    pending.must_change_password = True
    await db.commit()
    assert await resolve_next_step(db, pending, trip) == "change_password"


async def test_auth_me_reports_the_gate(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, pending: User
) -> None:
    await login_as(client, db, pending)
    body = (await client.get("/api/v1/auth/me")).json()
    assert body["next_step"] == "setup_family"
    assert body["family"] is None


# --- the route ----------------------------------------------------------------------------


async def test_a_pending_founder_creates_exactly_one_family_and_becomes_its_admin(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, pending: User
) -> None:
    await login_as(client, db, pending)
    response = await client.post(MINE, json={"name": "The Newtons"})
    assert response.status_code == 201

    body = response.json()
    assert body["name"] == "The Newtons"
    assert body["color"] == 1
    assert [m["role"] for m in body["members"]] == ["admin"]

    assert await db.scalar(select(func.count()).select_from(Family)) == 1
    assert await db.scalar(select(func.count()).select_from(FamilyMember)) == 1


async def test_the_founders_own_sharing_starts_on(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, pending: User
) -> None:
    """FM-15: "the person organising a family's travel is the one the rest of them expect to
    be able to find". They are setting their own value; two gates still stand after it."""
    await login_as(client, db, pending)
    await client.post(MINE, json={"name": "The Newtons"})

    settings = await db.scalar(
        select(UserSettings).where(UserSettings.user_id == pending.id)
    )
    await db.refresh(settings)
    assert settings.live_location_enabled is True


async def test_the_gate_opens_once_setup_is_finished(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, pending: User
) -> None:
    await login_as(client, db, pending)
    await client.post(MINE, json={"name": "The Newtons"})

    me = (await client.get("/api/v1/auth/me")).json()
    assert me["next_step"] == "app"
    assert me["family"]["name"] == "The Newtons"
    assert me["family"]["role"] == "admin"
    assert (await client.get("/api/v1/families")).status_code == 200


async def test_a_home_address_may_be_supplied_during_setup(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    pending: User,
    geocoder: FakeGeocoder,
) -> None:
    geocoder.results["12 elm row"] = GeocodeResult(51.4, -2.5, "12 Elm Row", "Bristol")
    await login_as(client, db, pending)
    body = (
        await client.post(MINE, json={"name": "The Newtons", "home_address": "12 Elm Row"})
    ).json()
    assert body["geocode_status"] == "ok"
    assert body["home_locality"] == "Bristol"


async def test_setup_without_an_address_is_complete(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, pending: User
) -> None:
    """Requiring a geocode to finish registration would make an external service a gate on
    getting into the app."""
    await login_as(client, db, pending)
    body = (await client.post(MINE, json={"name": "The Newtons"})).json()
    assert body["geocode_status"] == "pending"


async def test_a_double_submit_creates_no_second_family(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, pending: User
) -> None:
    """A double-tap, or a retry after a timeout whose first attempt actually succeeded."""
    await login_as(client, db, pending)
    first = await client.post(MINE, json={"name": "The Newtons"})
    second = await client.post(MINE, json={"name": "The Newtons"})

    assert first.status_code == 201
    assert second.status_code in (403, 409)
    assert await db.scalar(select(func.count()).select_from(Family)) == 1


async def test_someone_who_already_has_a_family_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    user, _ = member
    await _consume_invite(db, trip, user)
    await login_as(client, db, user)
    response = await client.post(MINE, json={"name": "A second one"})
    assert response.status_code == 403
    assert code(response) == "forbidden"
    assert await db.scalar(select(func.count()).select_from(Family)) == 1


async def test_a_stranger_cannot_found_a_family(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, outsider: User
) -> None:
    await login_as(client, db, outsider)
    assert (await client.post(MINE, json={"name": "Uninvited"})).status_code == 403


async def test_a_duplicate_name_is_refused_on_the_field(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, pending: User
) -> None:
    await make_family(db, trip, "The Newtons", color=1)
    await login_as(client, db, pending)
    response = await client.post(MINE, json={"name": "the newtons"})
    assert response.status_code == 409
    assert code(response) == "name_taken"


async def test_all_eight_colours_taken_leaves_a_clear_message(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, pending: User
) -> None:
    """The user is stuck through no fault of their own, so the message points at the
    organiser rather than blaming them."""
    for slot in range(1, 9):
        await make_family(db, trip, f"Family {slot}", color=slot)
    await login_as(client, db, pending)
    response = await client.post(MINE, json={"name": "The Ninth"})
    assert response.status_code == 409
    assert code(response) == "no_color_slots"


async def test_setup_is_refused_once_the_trip_has_ended(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, pending: User
) -> None:
    trip.stage = "end"
    await db.commit()
    await login_as(client, db, pending)
    response = await client.post(MINE, json={"name": "Too late"})
    assert code(response) == "stage_forbidden"


async def test_abandoning_the_screen_leaves_nothing_half_created(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, pending: User
) -> None:
    """Nothing is written until submit, so logging back in lands on the same screen with
    nothing stale to reconcile."""
    await login_as(client, db, pending)
    assert (await client.get("/api/v1/auth/me")).json()["next_step"] == "setup_family"
    assert await db.scalar(select(func.count()).select_from(Family)) == 0

    fresh = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=client._transport.app), base_url="https://test"
    )
    async with fresh:
        await login_as(fresh, db, pending)
        assert (await fresh.get("/api/v1/auth/me")).json()["next_step"] == "setup_family"


async def test_every_other_route_stays_shut_until_setup_finishes(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, pending: User
) -> None:
    """Not because the UI hides it — because the server refuses (FM-13)."""
    await login_as(client, db, pending)
    response = await client.get("/api/v1/families")
    assert response.status_code == 403
    assert code(response) == "not_on_trip"
