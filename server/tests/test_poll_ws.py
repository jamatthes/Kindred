"""The poll events, and specifically what `poll.vote.updated` carries.

The design's decision to broadcast the *whole* recomputed results object rather than a delta
is the thing worth guarding: it exists so the matrix, the charts and the map cannot drift
apart from partially applied deltas, and a well-meaning optimisation to "just send the changed
cell" would undo it silently. The test asserts the payload contains the recomputed averages.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sessions import create_session
from app.main import app
from app.models import Trip, TripCategorySetting, User
from tests.conftest import add_member, login_as, make_family, make_user
from tests.wsharness import ASGIWebSocketClient

POLLS = "/api/v1/polls"
pytestmark = pytest.mark.asyncio


async def _socket(db: AsyncSession, user: User) -> ASGIWebSocketClient:
    from app.core.config import settings

    session, token = await create_session(db, user_id=user.id)
    await db.commit()
    socket = ASGIWebSocketClient(app, "/ws", cookies={settings.session_cookie_name: token})
    await socket.connect()
    await socket.receive_json()  # hello
    return socket


async def _next(socket: ASGIWebSocketClient, wanted: str, tries: int = 8) -> dict:
    for _ in range(tries):
        frame = await socket.receive_json()
        if frame["type"] == wanted:
            return frame
    raise AssertionError(f"never saw {wanted}")


@pytest.fixture
async def household(db: AsyncSession, trip: Trip) -> tuple[User, User]:
    owner = await make_user(db, "wsowner")
    watcher = await make_user(db, "wswatcher")
    family = await make_family(db, trip, "Voters", color=1)
    await add_member(db, family, owner, role="head")
    await add_member(db, family, watcher, role="member")
    trip.owner_user_id = owner.id
    db.add(TripCategorySetting(trip_id=trip.id, category="poll", voting_mode="score"))
    await db.commit()
    return owner, watcher


POLL_BODY = {
    "title": "Where shall we go?",
    "kind": "score_matrix",
    "options": [{"label": "York"}, {"label": "Cornwall"}],
}


async def test_a_score_change_reaches_another_client_with_the_recomputed_averages(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User]
) -> None:
    owner, watcher = household
    await login_as(client, db, owner)
    poll = (await client.post(POLLS, json=POLL_BODY)).json()
    cornwall = poll["options"][1]

    socket = await _socket(db, watcher)
    try:
        await client.put(
            f"{POLLS}/{poll['id']}/scores",
            json={"scores": [{"option_id": cornwall["id"], "score": 9}]},
        )
        frame = await _next(socket, "poll.vote.updated")
        payload = frame["payload"]
        assert payload["poll_id"] == poll["id"]

        # The whole results object, not a delta — the averages are already computed.
        results = payload["results"]
        scored = next(o for o in results["options"] if o["option_id"] == cornwall["id"])
        assert scored["average"] == 9.0
        assert scored["rank"] == 1
        assert results["insight"]
        # Both are still outstanding: the watcher has not started, and the owner scored
        # only Cornwall of two options, so they are partial.
        assert results["non_responders"]["count"] == 2
    finally:
        await socket.disconnect()


async def test_creating_closing_and_deciding_are_announced(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User]
) -> None:
    owner, watcher = household
    socket = await _socket(db, watcher)
    try:
        await login_as(client, db, owner)
        poll = (await client.post(POLLS, json=POLL_BODY)).json()
        created = await _next(socket, "poll.created")
        assert created["payload"]["poll"]["title"] == "Where shall we go?"

        await client.put(
            f"{POLLS}/{poll['id']}/decision", json={"option_id": poll["options"][0]["id"]}
        )
        decided = await _next(socket, "poll.decided")
        assert decided["payload"]["decision"]["label"] == "York"

        await client.post(f"{POLLS}/{poll['id']}/close", json={"confirm": True})
        closed = await _next(socket, "poll.closed")
        assert closed["payload"]["status"] == "closed"
    finally:
        await socket.disconnect()


async def test_adding_an_option_inserts_the_column_live(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User]
) -> None:
    """The design's edge case: existing scores are untouched and the new column reads "not
    scored yet" for everyone."""
    owner, watcher = household
    await login_as(client, db, owner)
    poll = (await client.post(POLLS, json={**POLL_BODY, "allow_member_options": True})).json()
    await client.put(
        f"{POLLS}/{poll['id']}/scores",
        json={"scores": [{"option_id": poll["options"][0]["id"], "score": 8}]},
    )

    socket = await _socket(db, watcher)
    try:
        await client.post(f"{POLLS}/{poll['id']}/options", json={"label": "Northumberland"})
        added = await _next(socket, "poll_option.created")
        assert added["payload"]["option"]["label"] == "Northumberland"

        results = (await _next(socket, "poll.vote.updated"))["payload"]["results"]
        fresh = next(o for o in results["options"] if o["label"] == "Northumberland")
        assert fresh["average"] is None
        # The existing score is untouched.
        existing = next(o for o in results["options"] if o["label"] == "York")
        assert existing["average"] == 8.0
    finally:
        await socket.disconnect()


async def test_deleting_a_poll_is_announced(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User]
) -> None:
    owner, watcher = household
    await login_as(client, db, owner)
    poll = (await client.post(POLLS, json=POLL_BODY)).json()

    socket = await _socket(db, watcher)
    try:
        await client.delete(f"{POLLS}/{poll['id']}")
        frame = await _next(socket, "poll.deleted")
        assert frame["payload"]["poll_id"] == poll["id"]
    finally:
        await socket.disconnect()


async def test_a_comment_reaches_the_room(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User]
) -> None:
    owner, watcher = household
    await login_as(client, db, owner)
    poll = (await client.post(POLLS, json=POLL_BODY)).json()

    socket = await _socket(db, watcher)
    try:
        await client.post(f"{POLLS}/{poll['id']}/comments", json={"body": "Cornwall for me"})
        frame = await _next(socket, "comment.created")
        assert frame["payload"]["subject_type"] == "poll"
        assert frame["payload"]["comment"]["body"] == "Cornwall for me"
    finally:
        await socket.disconnect()


async def test_a_nudge_reaches_only_the_people_who_have_not_finished(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User]
) -> None:
    """PL-10: "Anyone who has completed the poll is never nudged." The owner finishes, so
    only the watcher's own socket should hear about it."""
    owner, watcher = household
    await login_as(client, db, owner)
    poll = (await client.post(POLLS, json=POLL_BODY)).json()
    await client.put(
        f"{POLLS}/{poll['id']}/scores",
        json={"scores": [{"option_id": o["id"], "score": 7} for o in poll["options"]]},
    )

    watcher_socket = await _socket(db, watcher)
    owner_socket = await _socket(db, owner)
    try:
        body = (await client.post(f"{POLLS}/{poll['id']}/nudge")).json()
        assert body["nudged"] == 1

        frame = await _next(watcher_socket, "notification.new")
        assert frame["payload"]["type"] == "poll.nudge"
        assert frame["payload"]["deep_link"] == f"/polls/{poll['id']}"

        # The owner completed it, so nothing addressed to them should arrive. Drain briefly
        # and assert no notification appears.
        with pytest.raises((AssertionError, TimeoutError, asyncio.TimeoutError)):
            await asyncio.wait_for(_next(owner_socket, "notification.new", tries=2), timeout=1.5)
    finally:
        await watcher_socket.disconnect()
        await owner_socket.disconnect()
