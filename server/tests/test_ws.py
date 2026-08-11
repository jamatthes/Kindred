"""Phase 6 verify (`plan/features/foundation/tasks.md`) — the WebSocket skeleton (F-8)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import ws
from app.core.config import settings
from app.core.sessions import create_session, revoke_user_sessions
from app.main import app
from app.models import Family, Trip, User
from tests.conftest import make_user
from tests.wsharness import ASGIWebSocketClient, WebSocketDisconnected


async def _cookie_for(db: AsyncSession, user: User) -> dict[str, str]:
    _, token = await create_session(db, user_id=user.id)
    await db.commit()
    return {settings.session_cookie_name: token}


async def next_frame(client: ASGIWebSocketClient, *, skip_presence: bool = True) -> dict:
    """The next frame, skipping presence chatter.

    A connecting client is itself in the room it just joined, so it receives its own
    `presence.updated` right after `hello`. Tests that care about some other frame should not
    have to encode that ordering.
    """
    while True:
        frame = await client.receive_json()
        if skip_presence and frame["type"] == "presence.updated":
            continue
        return frame


@pytest.fixture(autouse=True)
def _empty_registry():
    """Each test starts and ends with a clean registry — it is process-global state."""
    ws.registry.rooms.clear()
    ws.registry.seq.clear()
    ws.registry.pending_offline.clear()
    yield
    for task in list(ws.registry.pending_offline.values()):
        task.cancel()
    ws.registry.rooms.clear()
    ws.registry.seq.clear()
    ws.registry.pending_offline.clear()


# --- handshake ---------------------------------------------------------------------------


async def test_connection_without_a_cookie_is_closed_1008(trip: Trip) -> None:
    client = ASGIWebSocketClient(app, "/ws")
    with pytest.raises(WebSocketDisconnected) as raised:
        await client.connect()
    assert raised.value.code == 1008


async def test_connection_with_a_revoked_session_is_closed_1008(
    db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    cookies = await _cookie_for(db, user)
    await revoke_user_sessions(db, user.id)
    await db.commit()

    client = ASGIWebSocketClient(app, "/ws", cookies)
    with pytest.raises(WebSocketDisconnected) as raised:
        await client.connect()
    assert raised.value.code == 1008


async def test_connection_while_password_change_is_pending_is_closed_1008(
    db: AsyncSession, trip: Trip
) -> None:
    user = await make_user(db, "mustchange", must_change_password=True)
    cookies = await _cookie_for(db, user)

    client = ASGIWebSocketClient(app, "/ws", cookies)
    with pytest.raises(WebSocketDisconnected) as raised:
        await client.connect()
    assert raised.value.code == 1008


# --- envelope and frames -----------------------------------------------------------------


async def test_authenticated_connection_receives_hello(
    db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, family = member
    cookies = await _cookie_for(db, user)

    async with ASGIWebSocketClient(app, "/ws", cookies) as client:
        hello = await client.receive_json()

    assert hello["type"] == "hello"
    assert hello["trip_id"] == str(trip.id)
    assert set(hello) == {"type", "trip_id", "seq", "ts", "payload"}
    assert hello["payload"]["user_id"] == str(user.id)
    assert hello["payload"]["trip_id"] == str(trip.id)
    assert hello["payload"]["family_id"] == str(family.id)
    assert hello["payload"]["connection_id"]


async def test_ping_returns_pong(
    db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    cookies = await _cookie_for(db, user)

    async with ASGIWebSocketClient(app, "/ws", cookies) as client:
        await client.receive_json()  # hello
        await client.send_json({"type": "ping"})
        pong = await next_frame(client)

    assert pong["type"] == "pong"
    assert pong["trip_id"] == str(trip.id)


async def test_resume_answers_resync_because_there_is_no_event_log(
    db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    cookies = await _cookie_for(db, user)

    async with ASGIWebSocketClient(app, "/ws", cookies) as client:
        await client.receive_json()  # hello
        await client.send_json({"type": "resume", "last_seq": 1400})
        frame = await next_frame(client)

    assert frame["type"] == "resync"


async def test_unknown_frame_types_are_ignored_not_fatal(
    db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    cookies = await _cookie_for(db, user)

    async with ASGIWebSocketClient(app, "/ws", cookies) as client:
        await client.receive_json()  # hello
        await client.send_json({"type": "definitely-not-a-real-frame"})
        # The socket is still usable.
        await client.send_json({"type": "ping"})
        assert (await next_frame(client))["type"] == "pong"


# --- broadcast ---------------------------------------------------------------------------


async def test_broadcast_reaches_a_connected_client_and_increments_seq(
    db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    cookies = await _cookie_for(db, user)

    async with ASGIWebSocketClient(app, "/ws", cookies) as client:
        hello = await client.receive_json()

        delivered = await ws.broadcast(trip.id, "poll.vote.updated", {"poll_id": "abc"})
        assert delivered == 1

        frame = await next_frame(client)

    assert frame["type"] == "poll.vote.updated"
    assert frame["payload"] == {"poll_id": "abc"}
    assert frame["seq"] > hello["seq"]


async def test_send_user_reaches_only_that_user(
    db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    other = await make_user(db, "someoneelse", is_platform_admin=True)

    cookies = await _cookie_for(db, user)
    other_cookies = await _cookie_for(db, other)

    async with ASGIWebSocketClient(app, "/ws", cookies) as client:
        async with ASGIWebSocketClient(app, "/ws", other_cookies) as other_client:
            await client.receive_json()  # hello
            await other_client.receive_json()  # hello

            delivered = await ws.send_user(user.id, "notification.new", {"id": "n1"})
            assert delivered == 1

            frame = await next_frame(client)
            assert frame["type"] == "notification.new"

            # The other user must not have received it; a ping proves the socket is alive
            # and that the next frame in its queue is the pong, not the notification.
            await other_client.send_json({"type": "ping"})
            assert (await next_frame(other_client))["type"] == "pong"


async def test_an_idle_socket_is_closed(
    monkeypatch: pytest.MonkeyPatch, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    monkeypatch.setattr(ws, "IDLE_TIMEOUT_SECONDS", 0.1)
    user, _ = member

    client = ASGIWebSocketClient(app, "/ws", await _cookie_for(db, user))
    await client.connect()
    await client.receive_json()  # hello

    with pytest.raises(WebSocketDisconnected) as raised:
        # Send nothing at all; the server should give up on us.
        while True:
            await client.receive_json(timeout=2)
    assert raised.value.code == 1001
    assert trip.id not in ws.registry.rooms


async def test_broadcast_to_an_empty_room_is_harmless(trip: Trip) -> None:
    assert await ws.broadcast(trip.id, "stage.changed", {"stage": "holiday"}) == 0


# --- registry cleanup --------------------------------------------------------------------


async def test_disconnecting_removes_the_room_entry(
    db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    cookies = await _cookie_for(db, user)

    client = ASGIWebSocketClient(app, "/ws", cookies)
    await client.connect()
    await client.receive_json()  # hello

    assert ws.registry.online_user_ids(trip.id) == {user.id}
    assert trip.id in ws.registry.rooms

    await client.disconnect()

    # The empty room is dropped entirely, not left as an empty set.
    assert trip.id not in ws.registry.rooms
    assert ws.registry.online_user_ids(trip.id) == set()


# --- presence ----------------------------------------------------------------------------


async def test_presence_is_announced_to_others_on_connect(
    db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    watcher = await make_user(db, "watcher", is_platform_admin=True)
    watcher_cookies = await _cookie_for(db, watcher)

    async with ASGIWebSocketClient(app, "/ws", watcher_cookies) as watcher_client:
        await watcher_client.receive_json()  # hello
        # The watcher's own arrival is announced to itself too.
        first = await watcher_client.receive_json()
        assert first["type"] == "presence.updated"
        assert first["payload"] == {"user_id": str(watcher.id), "online": True}

        user, _ = member
        cookies = await _cookie_for(db, user)
        async with ASGIWebSocketClient(app, "/ws", cookies) as client:
            await client.receive_json()  # hello
            frame = await watcher_client.receive_json()

    assert frame["type"] == "presence.updated"
    assert frame["payload"] == {"user_id": str(user.id), "online": True}


async def test_going_offline_is_debounced(
    monkeypatch: pytest.MonkeyPatch, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    # A refresh — disconnect immediately followed by reconnect — must not flap.
    monkeypatch.setattr(ws, "PRESENCE_DEBOUNCE_SECONDS", 0.2)
    user, _ = member

    client = ASGIWebSocketClient(app, "/ws", await _cookie_for(db, user))
    await client.connect()
    await client.receive_json()  # hello
    await client.disconnect()

    assert user.id in ws.registry.pending_offline

    reconnected = ASGIWebSocketClient(app, "/ws", await _cookie_for(db, user))
    await reconnected.connect()
    await reconnected.receive_json()  # hello

    # The queued "offline" was cancelled by the reconnect.
    assert user.id not in ws.registry.pending_offline
    await reconnected.disconnect()

    # A real departure does eventually announce offline.
    await asyncio.sleep(0.4)
    assert user.id not in ws.registry.pending_offline


# --- REST snapshot -----------------------------------------------------------------------


async def test_presence_snapshot_endpoint(
    client, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    from tests.conftest import login_as

    user, _ = member
    await login_as(client, db, user)

    response = await client.get("/api/v1/presence")
    assert response.status_code == 200
    assert response.json()["online_user_ids"] == []

    ws_client = ASGIWebSocketClient(app, "/ws", await _cookie_for(db, user))
    await ws_client.connect()
    await ws_client.receive_json()

    response = await client.get("/api/v1/presence")
    assert response.json()["online_user_ids"] == [str(user.id)]

    await ws_client.disconnect()
