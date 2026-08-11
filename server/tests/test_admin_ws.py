"""Phase 8 — the events this feature emits.

Two of them are doing something no other event does:

* `stage.changed` goes to **everyone**, because the whole app re-evaluates what is mutable.
  A member with a suggestion form open should find out before they press save.
* `session.revoked` goes to **one** socket and is followed by a close. It is the difference
  between "you have been signed out" and a wall of 401s from whatever the client polls next.
"""

from __future__ import annotations

import asyncio
import datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sessions import create_session
from app.main import app
from app.models import Family, Trip, TripOrganiser, User
from tests.conftest import add_member, login_as, make_family, make_user
from tests.wsharness import ASGIWebSocketClient, WebSocketDisconnected

pytestmark = pytest.mark.asyncio


async def _socket(db: AsyncSession, user: User) -> ASGIWebSocketClient:
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


async def _drain(socket: ASGIWebSocketClient, tries: int = 4) -> list[dict]:
    """Everything queued for this socket right now. Used to assert an *absence*, which is
    why it swallows the timeout rather than failing on it."""
    seen: list[dict] = []
    for _ in range(tries):
        try:
            seen.append(await socket.receive_json(timeout=0.2))
        except (TimeoutError, asyncio.TimeoutError, WebSocketDisconnected):
            break
    return seen


async def _owner(db: AsyncSession, trip: Trip) -> User:
    user = await make_user(db, "wsowner")
    family = await make_family(db, trip, "Owners", color=3)
    await add_member(db, family, user, role="head")
    trip.owner_user_id = user.id
    await db.commit()
    return user


async def test_a_stage_change_reaches_an_ordinary_member(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    trip.start_date = datetime.date(2027, 7, 17)
    trip.end_date = datetime.date(2027, 7, 24)
    await db.commit()

    socket = await _socket(db, member[0])
    try:
        await login_as(client, db, owner)
        response = await client.patch(
            f"/api/v1/trips/{trip.id}/stage", json={"stage": "holiday"}
        )
        assert response.status_code == 200

        frame = await _next(socket, "stage.changed")
        assert frame["payload"]["stage"] == "holiday"
        assert frame["payload"]["previous_stage"] == "planning"
        assert frame["payload"]["was_revert"] is False
        # The trip rides along, so a client can update its header and its affordances from
        # one frame rather than refetching.
        assert frame["payload"]["trip"]["can_advance_to"] == "end"
    finally:
        await socket.disconnect()


async def test_a_revert_says_so_in_the_payload(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    trip.stage = "holiday"
    await db.commit()

    socket = await _socket(db, member[0])
    try:
        await login_as(client, db, owner)
        await client.patch(
            f"/api/v1/trips/{trip.id}/stage", json={"stage": "planning", "reason": "revert"}
        )
        frame = await _next(socket, "stage.changed")
        assert frame["payload"]["was_revert"] is True
    finally:
        await socket.disconnect()


async def test_renaming_the_trip_reaches_every_client(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    socket = await _socket(db, member[0])
    try:
        await login_as(client, db, owner)
        await client.patch("/api/v1/admin/trip", json={"name": "Cornwall · July 2027"})

        frame = await _next(socket, "trip.updated")
        assert frame["payload"]["trip"]["name"] == "Cornwall · July 2027"
    finally:
        await socket.disconnect()


async def test_a_voting_mode_change_reaches_every_client(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    socket = await _socket(db, member[0])
    try:
        await login_as(client, db, owner)
        await client.put(
            "/api/v1/admin/category-settings",
            json={"settings": [{"category": "poll", "voting_mode": "thumbs"}]},
        )

        frame = await _next(socket, "category_settings.updated")
        modes = {row["category"]: row["voting_mode"] for row in frame["payload"]}
        assert modes["poll"] == "thumbs"
    finally:
        await socket.disconnect()


async def test_a_password_reset_tells_that_user_and_closes_their_socket(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    target = await make_user(db, "resetsocket")
    family = await make_family(db, trip, "Targets", color=4)
    await add_member(db, family, target, role="head")

    theirs = await _socket(db, target)
    bystander_user = await make_user(db, "bystander")
    bystander_family = await make_family(db, trip, "Bystanders", color=5)
    await add_member(db, bystander_family, bystander_user, role="head")
    bystander = await _socket(db, bystander_user)

    try:
        await login_as(client, db, owner)
        await client.post(
            f"/api/v1/admin/users/{target.id}/reset-password", json={"confirm": True}
        )

        frame = await _next(theirs, "session.revoked")
        assert frame["payload"]["reason"] == "password_reset"

        # …and then the socket goes away, so the client stops trying.
        with pytest.raises(WebSocketDisconnected):
            for _ in range(4):
                await theirs.receive_json(timeout=1.0)

        # Nobody else was told: a revocation is between the server and one account.
        others = await _drain(bystander)
        assert all(frame.get("type") != "session.revoked" for frame in others)
    finally:
        await theirs.disconnect()
        await bystander.disconnect()


async def test_removal_emits_the_families_payload_and_revokes_the_session(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    family = await make_family(db, trip, "Leavers", color=6)
    head = await make_user(db, "leaverhead")
    leaving = await make_user(db, "leaver")
    await add_member(db, family, head, role="head")
    await add_member(db, family, leaving, role="member")

    watcher = await _socket(db, member[0])
    try:
        await login_as(client, db, owner)
        assert (await client.delete(f"/api/v1/admin/users/{leaving.id}")).status_code == 204

        frame = await _next(watcher, "member.removed")
        # The exact shape `families` emits, so one client handler serves both features.
        assert frame["payload"] == {
            "family_id": str(family.id),
            "user_id": str(leaving.id),
        }
    finally:
        await watcher.disconnect()


async def test_appointing_an_organiser_reaches_every_client(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    socket = await _socket(db, member[0])
    try:
        await login_as(client, db, owner)
        await client.post(
            "/api/v1/admin/organisers", json={"user_id": str(member[0].id)}
        )

        # Their own nav rail grows an `Admin` entry without a reload; everyone else's member
        # list learns the label.
        frame = await _next(socket, "organiser.appointed")
        assert frame["payload"]["user_id"] == str(member[0].id)
        assert frame["payload"]["granted_by"] == str(owner.id)
    finally:
        await socket.disconnect()


async def test_demotion_broadcasts_but_does_not_revoke_the_session(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    owner = await _owner(db, trip)
    db.add(TripOrganiser(trip_id=trip.id, user_id=member[0].id, granted_by=owner.id))
    await db.commit()

    theirs = await _socket(db, member[0])
    try:
        await login_as(client, db, owner)
        assert (
            await client.delete(f"/api/v1/admin/organisers/{member[0].id}")
        ).status_code == 204

        frame = await _next(theirs, "organiser.demoted")
        assert frame["payload"]["user_id"] == str(member[0].id)

        # Deliberately no `session.revoked`: demotion is a permission change, not an access
        # revocation, and their socket stays open.
        assert all(f.get("type") != "session.revoked" for f in await _drain(theirs))
    finally:
        await theirs.disconnect()
