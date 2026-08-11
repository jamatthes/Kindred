"""Phase 8 — the six family events, and what they are allowed to carry.

Two of these assertions are the whole point of the phase:

* `family.updated` must not carry an address. The socket is joined to the **whole trip room**,
  so a broadcast is delivered to families the REST API refuses to give the address to. A
  client-side filter would make the server's redaction advisory.
* `member.updated` must not carry a consent state. Same reason, one field down.

`plan/features/families/design.md`: "Almost every event fans out to the whole trip room
unfiltered" — which is exactly why the two that carry person-shaped data are serialised for a
stranger rather than for the actor.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sessions import create_session
from app.main import app
from app.models import Family, Invite, Trip, User, UserSettings
from tests.conftest import add_member, login_as, make_family, make_user
from tests.wsharness import ASGIWebSocketClient

FAMILIES = "/api/v1/families"


async def _socket(db: AsyncSession, user: User) -> ASGIWebSocketClient:
    """A connected, authenticated socket for ``user``, past its `hello` frame."""
    from app.core.config import settings  # noqa: PLC0415

    session, token = await create_session(db, user_id=user.id)
    await db.commit()
    client = ASGIWebSocketClient(app, "/ws", cookies={settings.session_cookie_name: token})
    await client.connect()
    await client.receive_json()  # hello
    return client


async def _next(socket: ASGIWebSocketClient, wanted: str, tries: int = 6) -> dict:
    """The next frame of type ``wanted``, skipping presence chatter."""
    for _ in range(tries):
        frame = await socket.receive_json()
        if frame["type"] == wanted:
            return frame
    raise AssertionError(f"never saw {wanted}")


@pytest.fixture
async def watcher(db: AsyncSession, trip: Trip) -> tuple[User, Family]:
    """Someone in a *different* family, watching the room."""
    family = await make_family(db, trip, "Watchers", color=8)
    user = await make_user(db, "watcher")
    await add_member(db, family, user, role="member")
    return user, family


async def test_renaming_a_family_reaches_a_connected_client(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    watcher: tuple[User, Family],
) -> None:
    admin, family = family_admin
    observer, _ = watcher
    socket = await _socket(db, observer)
    try:
        await login_as(client, db, admin)
        await client.patch(f"{FAMILIES}/{family.id}", json={"name": "Renamed"})
        frame = await _next(socket, "family.updated")
        assert frame["payload"]["family"]["name"] == "Renamed"
    finally:
        await socket.disconnect()


async def test_the_family_payload_contains_no_address_field(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    watcher: tuple[User, Family],
    geocoder,
) -> None:
    """The trip room includes other families. A broadcast address would reach them all."""
    from app.services.google import GeocodeResult  # noqa: PLC0415

    admin, family = family_admin
    observer, _ = watcher
    geocoder.results["12 elm row"] = GeocodeResult(51.4, -2.5, "12 Elm Row", "Bristol")

    socket = await _socket(db, observer)
    try:
        await login_as(client, db, admin)
        await client.put(f"{FAMILIES}/{family.id}/home", json={"home_address": "12 Elm Row"})
        payload = (await _next(socket, "family.updated"))["payload"]["family"]

        assert set(payload).isdisjoint(
            {"home_address", "home_lat", "home_lng", "home_geocoded_at"}
        )
        # The coarse label does travel — it is what other families are meant to see.
        assert payload["home_locality"] == "Bristol"
        assert payload["home_placed"] is True
    finally:
        await socket.disconnect()


async def test_recolouring_a_family_reaches_a_connected_client(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    watcher: tuple[User, Family],
) -> None:
    """2026-08-11 palette ruling: `family.updated` fires on a colour change too, so pins,
    badges and cards recolor live everywhere without a reload."""
    admin, family = family_admin
    observer, _ = watcher
    socket = await _socket(db, observer)
    try:
        await login_as(client, db, admin)
        new_slot = 9 if family.color != 9 else 10
        response = await client.patch(f"{FAMILIES}/{family.id}", json={"color": new_slot})
        assert response.status_code == 200
        frame = await _next(socket, "family.updated")
        assert frame["payload"]["family"]["color"] == new_slot
        assert frame["payload"]["family"]["color_custom"] is None
    finally:
        await socket.disconnect()


async def test_creating_a_family_is_announced(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    watcher: tuple[User, Family],
) -> None:
    """Through `POST /families/mine` — the only route that creates a family since 2026-08-11
    (`families` FM-1). The event is unchanged; what changed is that it can no longer announce
    a family with nobody in it, so `member.joined` always follows it."""
    observer, _ = watcher
    founder = await make_user(db, "wsfounder")
    db.add(
        Invite(
            trip_id=trip.id,
            mode="create_family",
            token_hash="hash-wsfounder",
            expires_at=datetime.now(UTC) + timedelta(days=7),
            used_by=founder.id,
            used_at=datetime.now(UTC),
        )
    )
    await db.commit()

    socket = await _socket(db, observer)
    try:
        await login_as(client, db, founder)
        await client.post(f"{FAMILIES}/mine", json={"name": "The Newcomers"})
        frame = await _next(socket, "family.created")
        assert frame["payload"]["family"]["name"] == "The Newcomers"
        joined = await _next(socket, "member.joined")
        assert joined["payload"]["member"]["username"] == "wsfounder"
    finally:
        await socket.disconnect()


async def test_deleting_a_family_is_announced(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    main_admin: User,
    watcher: tuple[User, Family],
) -> None:
    observer, _ = watcher
    empty = await make_family(db, trip, "Nobody", color=6)
    socket = await _socket(db, observer)
    try:
        await login_as(client, db, main_admin)
        await client.delete(f"{FAMILIES}/{empty.id}")
        frame = await _next(socket, "family.deleted")
        assert frame["payload"]["family_id"] == str(empty.id)
    finally:
        await socket.disconnect()


async def test_a_policy_change_is_announced_so_markers_can_vanish_at_once(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    watcher: tuple[User, Family],
) -> None:
    """"A marker that should no longer be visible must not linger for a refresh interval"."""
    admin, family = family_admin
    observer, _ = watcher
    socket = await _socket(db, observer)
    try:
        await login_as(client, db, admin)
        await client.patch(
            f"{FAMILIES}/{family.id}/location-policy", json={"sharing_allowed": False}
        )
        frame = await _next(socket, "family.updated")
        assert frame["payload"]["family"]["location_sharing_allowed"] is False
    finally:
        await socket.disconnect()


async def test_the_member_payload_never_carries_a_consent_state(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    watcher: tuple[User, Family],
) -> None:
    """A member's own consent must never reach the whole trip room."""
    family = await make_family(db, trip, "Sharers", color=3)
    admin = await make_user(db, "sharersadmin")
    sharer = await make_user(db, "sharer")
    await add_member(db, family, admin, role="head")
    await add_member(db, family, sharer, role="member")
    settings = await db.scalar(select(UserSettings).where(UserSettings.user_id == sharer.id))
    settings.live_location_enabled = True
    await db.commit()

    observer, _ = watcher
    socket = await _socket(db, observer)
    try:
        await login_as(client, db, admin)
        await client.patch(
            f"{FAMILIES}/{family.id}/members/{sharer.id}",
            json={"location_sharing_allowed": False},
        )
        member = (await _next(socket, "member.updated"))["payload"]["member"]

        assert member["location_sharing_allowed"] is False  # the permission travels
        assert member["location_sharing_enabled"] is None  # the consent does not
    finally:
        await socket.disconnect()


async def test_a_name_change_reaches_the_room(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    watcher: tuple[User, Family],
) -> None:
    """FM-12: a badge that only updates for the person who changed it is worse than one that
    never updates at all."""
    admin, _ = family_admin
    observer, _ = watcher
    socket = await _socket(db, observer)
    try:
        await login_as(client, db, admin)
        await client.patch("/api/v1/me", json={"first_name": "Ada", "last_name": "Lovelace"})
        member = (await _next(socket, "member.updated"))["payload"]["member"]
        # The display name is separately editable, so it is untouched — but the badge the
        # map draws follows the name parts immediately.
        assert member["display_name"] == "Familyadmin"
        assert member["initials"] == "AL"
    finally:
        await socket.disconnect()


async def test_removing_a_member_reaches_the_room_and_that_person(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    watcher: tuple[User, Family],
) -> None:
    """The removed user's own socket gets it too, so their client refetches `auth/me` and
    shows "you are no longer on this trip" rather than erroring its way through a screen it
    can no longer load."""
    family = await make_family(db, trip, "Leavers", color=4)
    admin = await make_user(db, "leaveradmin")
    leaver = await make_user(db, "leaver")
    await add_member(db, family, admin, role="head")
    await add_member(db, family, leaver, role="member")

    observer, _ = watcher
    room_socket = await _socket(db, observer)
    own_socket = await _socket(db, leaver)
    try:
        await login_as(client, db, admin)
        await client.delete(f"{FAMILIES}/{family.id}/members/{leaver.id}")

        room, mine = await asyncio.gather(
            _next(room_socket, "member.removed"), _next(own_socket, "member.removed")
        )
        assert room["payload"]["user_id"] == str(leaver.id)
        assert mine["payload"]["user_id"] == str(leaver.id)
    finally:
        await room_socket.disconnect()
        await own_socket.disconnect()


async def test_finishing_family_setup_announces_both_the_family_and_its_head(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    watcher: tuple[User, Family],
) -> None:
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from app.models import Invite  # noqa: PLC0415

    founder = await make_user(db, "founder")
    db.add(
        Invite(
            trip_id=trip.id,
            mode="create_family",
            token_hash="hash-founder",
            expires_at=datetime.now(UTC) + timedelta(days=7),
            used_by=founder.id,
            used_at=datetime.now(UTC),
        )
    )
    await db.commit()

    observer, _ = watcher
    socket = await _socket(db, observer)
    try:
        await login_as(client, db, founder)
        response = await client.post(f"{FAMILIES}/mine", json={"name": "The Founders"})
        assert response.status_code == 201

        created = await _next(socket, "family.created")
        assert created["payload"]["family"]["name"] == "The Founders"
        joined = await _next(socket, "member.joined")
        assert joined["payload"]["member"]["username"] == "founder"
        assert joined["payload"]["member"]["role"] == "head"
    finally:
        await socket.disconnect()
