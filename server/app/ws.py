"""WebSocket transport (F-8).

One endpoint, `/ws`, authenticated by the same session cookie as the REST API. **The client
never mutates over the socket** — every write goes through REST and the socket is a broadcast
channel only. That is what keeps permission enforcement in one place (`deps.py`) instead of
duplicated across two protocols.

Envelope, server to client::

    {"type": "poll.vote.updated", "trip_id": "...", "seq": 1421, "ts": "...", "payload": {...}}

Client to server in v1: ``{"type": "ping"}`` and ``{"type": "resume", "last_seq": 1400}``.

Sequence numbers are per-trip, monotonic and held in memory. ``resume`` replays nothing —
there is no event log in v1 — so the server answers ``resync`` and the client refetches the
views it has open. This is deliberately honest about the guarantee: at-most-once delivery
with a refetch fallback, not an event log.

.. note::
   The registry is **per-process**. A single API container is assumed. If the deployment ever
   runs multiple API workers, this needs a Redis or Postgres ``LISTEN/NOTIFY`` fan-out;
   broadcasts would otherwise reach only the clients attached to the emitting worker.

Event names reserved in ``plan/architecture.md`` and emitted by later features:

===========================  =========================
``poll.vote.updated``        `polls`
``suggestion.vote.updated``  `voting-comments`
``suggestion.created``       `map-suggestions`
``notification.new``         `notifications`
``location.updated``         `holiday-stage`
``stage.changed``            `admin-console`
``presence.updated``         **foundation** (this module)
===========================  =========================

Vote events are namespaced by domain: polls and suggestions emit distinct types, never a
shared ``vote.updated``. Foundation itself emits ``hello``, ``pong``, ``resync`` and
``presence.updated``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionFactory
from app.core.sessions import load_session
from app.deps import load_membership
from app.models import Trip, User

logger = logging.getLogger(__name__)

router = APIRouter()

#: Policy violation — used for every handshake rejection (F-8).
WS_CLOSE_POLICY_VIOLATION = 1008
#: Going away — used when a socket is closed for being idle.
WS_CLOSE_GOING_AWAY = 1001

#: A socket with no traffic for this long is closed. The client pings well inside it.
#: Module-level so tests can shorten it.
IDLE_TIMEOUT_SECONDS = 90.0

#: Presence is debounced so a page refresh — disconnect immediately followed by reconnect —
#: does not flap the family avatar stack for everyone else.
PRESENCE_DEBOUNCE_SECONDS = 3.0


@dataclass(eq=False)
class Connection:
    """One live socket. Identity is the object, hence ``eq=False`` (usable in a set)."""

    id: uuid.UUID
    websocket: WebSocket
    user_id: uuid.UUID
    trip_id: uuid.UUID | None
    family_id: uuid.UUID | None = None
    last_ack_seq: int = 0


@dataclass
class Registry:
    """In-process connection registry, keyed by trip."""

    rooms: dict[uuid.UUID | None, set[Connection]] = field(default_factory=dict)
    seq: dict[uuid.UUID | None, int] = field(default_factory=lambda: defaultdict(int))
    #: Pending "went offline" tasks, keyed by user, so a reconnect can cancel one.
    pending_offline: dict[uuid.UUID, asyncio.Task] = field(default_factory=dict)

    def add(self, conn: Connection) -> None:
        self.rooms.setdefault(conn.trip_id, set()).add(conn)

    def remove(self, conn: Connection) -> None:
        room = self.rooms.get(conn.trip_id)
        if room is None:
            return
        room.discard(conn)
        if not room:
            # Drop the empty room so the registry does not accumulate one entry per trip
            # that has ever had a visitor.
            del self.rooms[conn.trip_id]

    def connections_for_trip(self, trip_id: uuid.UUID | None) -> set[Connection]:
        return set(self.rooms.get(trip_id, ()))

    def connections_for_user(self, user_id: uuid.UUID) -> list[Connection]:
        return [c for room in self.rooms.values() for c in room if c.user_id == user_id]

    def online_user_ids(self, trip_id: uuid.UUID | None) -> set[uuid.UUID]:
        return {c.user_id for c in self.rooms.get(trip_id, ())}

    def next_seq(self, trip_id: uuid.UUID | None) -> int:
        self.seq[trip_id] += 1
        return self.seq[trip_id]

    def current_seq(self, trip_id: uuid.UUID | None) -> int:
        return self.seq[trip_id]


#: The single process-wide registry.
registry = Registry()


def envelope(
    type_: str, trip_id: uuid.UUID | None, seq: int, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build the standard server-to-client frame."""
    return {
        "type": type_,
        "trip_id": str(trip_id) if trip_id else None,
        "seq": seq,
        "ts": datetime.now(UTC).isoformat(),
        "payload": payload or {},
    }


async def _send(conn: Connection, frame: dict[str, Any]) -> bool:
    """Send one frame. Returns False when the socket is gone (the caller drops it)."""
    try:
        await conn.websocket.send_json(frame)
        return True
    except Exception:  # noqa: BLE001 — a dead socket must not break a broadcast to others
        logger.debug("Dropping dead connection %s", conn.id)
        return False


async def broadcast(
    trip_id: uuid.UUID | None, type_: str, payload: dict[str, Any] | None = None
) -> int:
    """Send an event to every connection in a trip's room. Returns the number reached.

    This is the helper feature code calls; see the module docstring for the reserved event
    names. Emit **after** the database transaction commits, never before — a client that
    refetches on receipt must not be able to read state older than the event announcing it.
    """
    seq = registry.next_seq(trip_id)
    frame = envelope(type_, trip_id, seq, payload)
    delivered = 0
    for conn in registry.connections_for_trip(trip_id):
        if await _send(conn, frame):
            delivered += 1
        else:
            registry.remove(conn)
    return delivered


async def send_user(
    user_id: uuid.UUID, type_: str, payload: dict[str, Any] | None = None
) -> int:
    """Send an event to every connection belonging to one user (e.g. `notification.new`)."""
    delivered = 0
    for conn in registry.connections_for_user(user_id):
        frame = envelope(type_, conn.trip_id, registry.next_seq(conn.trip_id), payload)
        if await _send(conn, frame):
            delivered += 1
        else:
            registry.remove(conn)
    return delivered


async def close_user(user_id: uuid.UUID, code: int = WS_CLOSE_POLICY_VIOLATION) -> int:
    """Close every socket belonging to one user, and forget them.

    Used after a password reset or a removal from the trip (`admin-console` AC-7/AC-8), and
    always *after* the `session.revoked` frame — the client needs to be told why before the
    connection goes away, or the disconnect looks like a network problem and it reconnects.

    Closing is not enough on its own: the session behind the socket has already been revoked
    in the database, so a reconnect fails authentication anyway. This makes the outcome
    immediate rather than waiting for the client's next request.
    """
    closed = 0
    for conn in registry.connections_for_user(user_id):
        registry.remove(conn)
        try:
            await conn.websocket.close(code=code)
        except (RuntimeError, WebSocketDisconnect):
            # Already gone: the outcome we wanted, arrived at by another route.
            pass
        closed += 1
    return closed


# --- presence ----------------------------------------------------------------------------


async def _announce_presence(
    trip_id: uuid.UUID | None, user_id: uuid.UUID, *, online: bool
) -> None:
    await broadcast(trip_id, "presence.updated", {"user_id": str(user_id), "online": online})


async def _on_connected(conn: Connection) -> None:
    """Announce arrival, unless the user was already online elsewhere."""
    pending = registry.pending_offline.pop(conn.user_id, None)
    if pending is not None:
        # A refresh, not a departure. Cancel the queued "offline" and say nothing.
        pending.cancel()
        return
    if len(registry.connections_for_user(conn.user_id)) > 1:
        return  # already online in another tab
    await _announce_presence(conn.trip_id, conn.user_id, online=True)


async def _delayed_offline(trip_id: uuid.UUID | None, user_id: uuid.UUID) -> None:
    try:
        await asyncio.sleep(PRESENCE_DEBOUNCE_SECONDS)
        if not registry.connections_for_user(user_id):
            await _announce_presence(trip_id, user_id, online=False)
    except asyncio.CancelledError:  # pragma: no cover — the reconnect path
        raise
    finally:
        registry.pending_offline.pop(user_id, None)


def _on_disconnected(conn: Connection) -> None:
    """Queue a debounced "offline", so a refresh does not flap the avatar stack."""
    if registry.connections_for_user(conn.user_id):
        return  # still online in another tab
    if conn.user_id in registry.pending_offline:
        return
    registry.pending_offline[conn.user_id] = asyncio.create_task(
        _delayed_offline(conn.trip_id, conn.user_id)
    )


# --- handshake ---------------------------------------------------------------------------


@dataclass
class Authenticated:
    user: User
    trip: Trip | None
    family_id: uuid.UUID | None


async def authenticate(websocket: WebSocket) -> Authenticated | None:
    """Resolve the session cookie sent with the handshake, or ``None`` to reject."""
    token = websocket.cookies.get(settings.session_cookie_name)
    if not token:
        return None

    async with SessionFactory() as db:
        session = await load_session(db, token)
        if session is None:
            return None
        user = await db.get(User, session.user_id)
        if user is None:
            return None
        if user.must_change_password:
            # The permissions table in requirements.md puts "Open WebSocket /ws" under the
            # must-change-password interceptor along with every other non-exempt row.
            return None
        trip = await db.scalar(select(Trip).order_by(Trip.created_at).limit(1))
        family_id = None
        if trip is not None:
            membership = await load_membership(db, user.id, trip.id)
            if membership is not None:
                family_id = membership[0].id
        return Authenticated(user=user, trip=trip, family_id=family_id)


async def _handle_frame(conn: Connection, message: dict[str, Any]) -> None:
    kind = message.get("type")
    if kind == "ping":
        await conn.websocket.send_json(
            envelope("pong", conn.trip_id, registry.current_seq(conn.trip_id))
        )
    elif kind == "resume":
        conn.last_ack_seq = int(message.get("last_seq") or 0)
        # No event log in v1: tell the client to refetch rather than pretend to replay.
        await conn.websocket.send_json(
            envelope("resync", conn.trip_id, registry.current_seq(conn.trip_id))
        )
    else:
        logger.debug("Ignoring unknown frame type %r from %s", kind, conn.id)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    auth = await authenticate(websocket)
    if auth is None:
        # Rejected before accept, so the client sees a failed handshake rather than a
        # connection that opens and immediately dies.
        await websocket.close(code=WS_CLOSE_POLICY_VIOLATION)
        return

    await websocket.accept()

    trip_id = auth.trip.id if auth.trip else None
    conn = Connection(
        id=uuid.uuid4(),
        websocket=websocket,
        user_id=auth.user.id,
        trip_id=trip_id,
        family_id=auth.family_id,
    )
    registry.add(conn)

    try:
        await websocket.send_json(
            envelope(
                "hello",
                trip_id,
                registry.current_seq(trip_id),
                {
                    "connection_id": str(conn.id),
                    "user_id": str(auth.user.id),
                    "trip_id": str(trip_id) if trip_id else None,
                    "family_id": str(auth.family_id) if auth.family_id else None,
                },
            )
        )
        await _on_connected(conn)

        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_json(), timeout=IDLE_TIMEOUT_SECONDS
                )
            except TimeoutError:
                logger.info("Closing idle connection %s", conn.id)
                await websocket.close(code=WS_CLOSE_GOING_AWAY)
                break
            await _handle_frame(conn, message)

    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("WebSocket %s failed", conn.id)
    finally:
        # `finally`, so the registry is cleaned up on the exception paths too — a leaked
        # entry would keep broadcasting to a dead socket forever.
        registry.remove(conn)
        _on_disconnected(conn)
