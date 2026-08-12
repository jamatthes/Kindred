"""The write half: the only code in Kindred that may cause a Distance Matrix call.

**This module is never imported by a read path.** `app/services/distances.py` serves every
card, list and panel and imports nothing from here; this module imports
`app/services/distance_matrix.py`, the Google client. That three-way split is what makes
`design.md`'s HARD INVARIANT — "a request serving a page, a list, a card, or a panel never
calls Distance Matrix" — a fact about the import graph rather than a rule somebody has to
remember. `tests/test_service_distances_read.py` asserts it.

**Nothing here may raise into the request that queued it.** A suggestion is the user's work; a
distance is a convenience. Every entry point catches everything, because the alternative is a
quota problem at Google turning into "your suggestion could not be saved".

The trigger list is closed (`design.md` > Trigger list):

======================================  ====================================================
Suggestion created                      one call, all homes -> the new suggestion
Suggestion moved past the 25 m epsilon  one call, all homes -> the moved suggestion
A family's home geocoded or changed     chunked, that home -> every suggestion
An organiser's force-recompute          scoped to a suggestion or the whole trip
======================================  ====================================================

Opening a card, loading the list, sorting, filtering and reconnecting a socket queue **nothing**.

Status mapping, from `design.md`'s Flow, is the part worth reading twice:

* ``ok`` -> the numbers, and `computed_at`.
* ``zero_results`` -> ``no_route``, **cached permanently and never automatically retried**.
  This is the single most important case `distance_cache.status` exists for: without it, a pair
  with genuinely no driving route reads as "not computed" on every render and is re-queued
  forever against a paid endpoint.
* ``not_found`` -> an attempt is spent; at the cap the row settles at ``failed``.
* a whole-request failure (transport, quota, auth) -> every row in the chunk spends an attempt
  and stays ``pending`` until the cap, then settles at ``failed``. The chunk is **not** retried
  inline: retrying into an exhausted quota is how a bad afternoon becomes a bill.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import ws
from app.core.config import settings
from app.core.db import SessionFactory
from app.models import (
    DISTANCE_FAILED,
    DISTANCE_NO_ROUTE,
    DISTANCE_OK,
    DISTANCE_PENDING,
    DistanceCache,
    Family,
    Suggestion,
    Trip,
)
from app.services.distance_matrix import (
    DistanceMatrixServiceProtocol,
    DistanceServiceError,
    ElementResult,
    LatLng,
)

logger = logging.getLogger(__name__)

#: The stage in which no external call is made at all (`design.md`, point 4 of the invariant).
FROZEN_STAGE = "end"


# --- resolving the work set -------------------------------------------------------------------


async def _homes(db: AsyncSession, trip_id: uuid.UUID) -> list[tuple[uuid.UUID, LatLng]]:
    """Every family with a geocoded home. A family without one is **not sent to Google** —
    there is nowhere to measure from, and the read path reports them as `no_home`."""
    rows = await db.execute(
        select(Family.id, Family.home_lat, Family.home_lng)
        .where(
            Family.trip_id == trip_id,
            Family.home_lat.isnot(None),
            Family.home_lng.isnot(None),
        )
        .order_by(Family.created_at)
    )
    return [(row[0], LatLng(lat=row[1], lng=row[2])) for row in rows.all()]


async def _suggestions(
    db: AsyncSession, trip_id: uuid.UUID
) -> list[tuple[uuid.UUID, LatLng]]:
    """Every suggestion, **ordered by `created_at`**, which is what makes chunk boundaries
    deterministic: a retry re-issues the same chunks rather than a fresh random split."""
    rows = await db.execute(
        select(Suggestion.id, Suggestion.lat, Suggestion.lng)
        .where(Suggestion.trip_id == trip_id)
        .order_by(Suggestion.created_at, Suggestion.id)
    )
    return [(row[0], LatLng(lat=row[1], lng=row[2])) for row in rows.all()]


# --- the pending guard ---------------------------------------------------------------------------


async def _claim(
    db: AsyncSession, pairs: list[tuple[uuid.UUID, uuid.UUID]], *, force: bool = False
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Upsert `pending` rows and return the pairs this task actually owns.

    Two jobs in one statement:

    1. **A concurrent read shows "pending" rather than nothing**, so a chip that is about to
       sharpen does not first look like a pair nobody has ever considered.
    2. **The guard against duplicate spend.** `ON CONFLICT DO UPDATE ... WHERE` only touches
       rows that are neither already settled **nor claimed by somebody else within the lease**,
       and `RETURNING` reports what was actually touched — so two overlapping tasks for the same
       suggestion produce one call between them rather than one each. That is the realistic way
       this feature would leak budget, and it is closed here rather than by an advisory lock,
       because the row *is* the lock: it is the thing whose state the second task must not
       duplicate, and unlike a lock it survives the process that took it.

       The lease (`settings.distance_claim_lease_seconds`) is what stops that becoming a
       different bug: a task that dies mid-batch would otherwise strand its pairs as `pending`
       and permanently un-recomputable. Past the lease the claim is treated as abandoned.

    `force=True` (an organiser's recompute) re-claims settled rows too, and resets `attempts` —
    the only path that retries a `no_route` or a `failed`.
    """
    if not pairs:
        return []

    now = datetime.now(UTC)
    statement = pg_insert(DistanceCache).values(
        [
            {
                "family_id": family_id,
                "suggestion_id": suggestion_id,
                "status": DISTANCE_PENDING,
                "attempts": 0,
            }
            for family_id, suggestion_id in pairs
        ]
    )
    if force:
        # A forced re-claim takes every row, settled or not: that is the whole point of the
        # affordance, and it is the only path that revisits a `no_route` or a `failed`.
        upsert = statement.on_conflict_do_update(
            constraint="uq_distance_cache_family_suggestion",
            set_={"status": DISTANCE_PENDING, "attempts": 0, "updated_at": now},
        )
    else:
        # The ordinary path claims only rows nobody has answered and nobody has given up on.
        # An already-`ok` pair costs nothing to skip, and a `no_route` must never be re-asked.
        lease_expired = now - timedelta(seconds=settings.distance_claim_lease_seconds)
        upsert = statement.on_conflict_do_update(
            constraint="uq_distance_cache_family_suggestion",
            set_={"status": DISTANCE_PENDING, "updated_at": now},
            where=and_(
                DistanceCache.status.notin_(
                    (DISTANCE_OK, DISTANCE_NO_ROUTE, DISTANCE_FAILED)
                ),
                DistanceCache.updated_at < lease_expired,
            ),
        )

    rows = await db.execute(
        upsert.returning(DistanceCache.family_id, DistanceCache.suggestion_id)
    )
    claimed = [(row[0], row[1]) for row in rows.all()]
    await db.commit()
    return claimed


# --- writing an answer -----------------------------------------------------------------------------


async def _write(
    db: AsyncSession,
    trip_id: uuid.UUID,
    family_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    element: ElementResult,
) -> None:
    """Map one element onto its row, and announce it.

    Emitted per row rather than per batch (`design.md` > WebSocket events), so a chip swaps
    from estimate to real value as soon as its own answer lands rather than waiting for the
    slowest sibling in the chunk.
    """
    now = datetime.now(UTC)
    if element.status == "ok":
        values = {
            "status": DISTANCE_OK,
            "duration_s": element.duration_s,
            "distance_m": element.distance_m,
            "computed_at": now,
        }
    elif element.status == "zero_results":
        # The answer, cached permanently. Never automatically retried — only an organiser's
        # force-recompute revisits it.
        values = {
            "status": DISTANCE_NO_ROUTE,
            "duration_s": None,
            "distance_m": None,
            "computed_at": now,
        }
    else:
        # `not_found`: bad coordinates, worth one more look. Spends an attempt, and settles at
        # `failed` once the budget is gone.
        await _spend_attempt(db, [(family_id, suggestion_id)])
        return

    result = await db.execute(
        update(DistanceCache)
        .where(
            DistanceCache.family_id == family_id,
            DistanceCache.suggestion_id == suggestion_id,
        )
        .values(**values)
    )
    if not result.rowcount:
        # The suggestion or family was deleted mid-computation. Discard the result rather than
        # resurrecting a row for something that no longer exists.
        return
    await ws.broadcast(
        trip_id,
        "distance.updated",
        {
            "suggestion_id": str(suggestion_id),
            "family_id": str(family_id),
            "status": values["status"],
            "duration_s": values["duration_s"],
            "distance_m": values["distance_m"],
            "is_estimate": False,
            "computed_at": now.isoformat(),
        },
    )


async def _spend_attempt(
    db: AsyncSession, pairs: list[tuple[uuid.UUID, uuid.UUID]]
) -> None:
    """Increment `attempts`, settling at `failed` once the cap is reached.

    A row below the cap stays `pending`, so the next trigger picks it up; at the cap it settles
    and is left alone until an organiser asks for it explicitly. That bound is the difference
    between a bad afternoon at the API and an unbounded retry storm against a paid endpoint.
    """
    for family_id, suggestion_id in pairs:
        await db.execute(
            update(DistanceCache)
            .where(
                DistanceCache.family_id == family_id,
                DistanceCache.suggestion_id == suggestion_id,
            )
            .values(attempts=DistanceCache.attempts + 1, status=_settling_status())
        )


def _settling_status():
    """`failed` once this increment takes `attempts` to the cap, `pending` until then."""
    return case(
        (DistanceCache.attempts + 1 >= settings.distance_max_attempts, DISTANCE_FAILED),
        else_=DISTANCE_PENDING,
    )


# --- the entry points --------------------------------------------------------------------------------


async def queue_for_suggestion(
    db: AsyncSession,
    trip: Trip,
    suggestion: Suggestion,
    *,
    service: DistanceMatrixServiceProtocol | None = None,
    force: bool = False,
) -> int:
    """The create/move shape: **one call**, every geocoded home against this one suggestion.

    Six families is one request producing six cached rows. This is the common case and the one
    the batching is optimised for.

    Returns the number of pairs answered — for tests and for the recompute endpoint's count,
    never for the request that triggered it, which does not wait.
    """
    if trip.stage == FROZEN_STAGE:
        # No external call is made in End, including a force-recompute. The archive is frozen.
        return 0

    homes = await _homes(db, trip.id)
    if not homes:
        return 0

    claimed = await _claim(
        db, [(family_id, suggestion.id) for family_id, _ in homes], force=force
    )
    if not claimed:
        # Everything is already settled, or another task claimed the same pairs first.
        return 0

    owned = {family_id for family_id, _ in claimed}
    origins = [(family_id, point) for family_id, point in homes if family_id in owned]
    destination = LatLng(lat=suggestion.lat, lng=suggestion.lng)

    client = service or _default_service()
    try:
        elements = await client.get_distances_many_to_one(
            [point for _, point in origins], destination
        )
    except DistanceServiceError as exc:
        # Quota, auth, or a transport failure that outlived its retry. The whole chunk spends
        # one attempt; it is not retried inline, because retrying into an exhausted quota is
        # how a bad afternoon becomes a bill.
        logger.warning("Distance Matrix unavailable: %s", exc)
        await _spend_attempt(db, [(family_id, suggestion.id) for family_id, _ in origins])
        await db.commit()
        return 0

    for (family_id, _), element in zip(origins, elements):
        await _write(db, trip.id, family_id, suggestion.id, element)
    await db.commit()
    return len(origins)


async def queue_for_family(
    db: AsyncSession,
    trip: Trip,
    family: Family,
    *,
    service: DistanceMatrixServiceProtocol | None = None,
    force: bool = False,
) -> int:
    """The home-change shape: that one home against every suggestion, chunked by the client.

    Only this family's rows are touched; every other family's cached values are untouched,
    because nothing about them changed.
    """
    if trip.stage == FROZEN_STAGE:
        return 0
    if family.home_lat is None or family.home_lng is None:
        # Nothing to measure from. The read path reports `no_home`, and the first geocode will
        # bring us back here.
        return 0

    destinations = await _suggestions(db, trip.id)
    if not destinations:
        return 0

    claimed = await _claim(
        db, [(family.id, suggestion_id) for suggestion_id, _ in destinations], force=force
    )
    if not claimed:
        return 0

    owned = {suggestion_id for _, suggestion_id in claimed}
    targets = [(sid, point) for sid, point in destinations if sid in owned]
    origin = LatLng(lat=family.home_lat, lng=family.home_lng)

    client = service or _default_service()
    try:
        elements = await client.get_distances_one_to_many(
            origin, [point for _, point in targets]
        )
    except DistanceServiceError as exc:
        logger.warning("Distance Matrix unavailable: %s", exc)
        await _spend_attempt(db, [(family.id, sid) for sid, _ in targets])
        await db.commit()
        return 0

    for (suggestion_id, _), element in zip(targets, elements):
        await _write(db, trip.id, family.id, suggestion_id, element)
    await db.commit()
    return len(targets)


async def recompute(
    db: AsyncSession,
    trip: Trip,
    *,
    suggestion_id: uuid.UUID | None = None,
    service: DistanceMatrixServiceProtocol | None = None,
) -> int:
    """The organiser's force-recompute: one suggestion, or the whole trip.

    **The only path that retries a settled negative.** A `no_route` is otherwise permanent and a
    `failed` is otherwise left alone, which is exactly what stops the cache re-asking Google
    forever — so the way back is a deliberate act by somebody who has been shown the cost.
    """
    if trip.stage == FROZEN_STAGE:
        return 0

    if suggestion_id is not None:
        suggestion = await db.get(Suggestion, suggestion_id)
        if suggestion is None or suggestion.trip_id != trip.id:
            return 0
        return await queue_for_suggestion(db, trip, suggestion, service=service, force=True)

    answered = 0
    for sid, _ in await _suggestions(db, trip.id):
        suggestion = await db.get(Suggestion, sid)
        if suggestion is not None:
            answered += await queue_for_suggestion(
                db, trip, suggestion, service=service, force=True
            )
    return answered


# --- the fire-and-forget wrappers ----------------------------------------------------------------------


async def queue_for_suggestion_safely(
    trip_id: uuid.UUID, suggestion_id: uuid.UUID, force: bool = False
) -> None:
    """What a request handler schedules. **Swallows everything.**

    A failed distance must never fail a suggestion creation: the suggestion is the user's work
    and the distance is a convenience. Runs on its own session, because the request's session is
    closed by the time a background task gets to run.
    """
    try:
        async with SessionFactory() as db:
            trip = await db.get(Trip, trip_id)
            suggestion = await db.get(Suggestion, suggestion_id)
            if trip is None or suggestion is None:
                return
            await queue_for_suggestion(db, trip, suggestion, force=force)
    except Exception:  # noqa: BLE001 - a convenience must not break the thing it decorates
        logger.exception("Distance recompute failed for suggestion %s", suggestion_id)


async def queue_for_family_safely(trip_id: uuid.UUID, family_id: uuid.UUID) -> None:
    """The same, for a family whose home was just geocoded or changed.

    Always a **reset**: every one of this family's cached values is about a house they no longer
    live in, settled ones included. Only theirs — nothing about any other family changed, and
    their values stay exactly as they were.
    """
    try:
        async with SessionFactory() as db:
            trip = await db.get(Trip, trip_id)
            family = await db.get(Family, family_id)
            if trip is None or family is None:
                return
            await queue_for_family(db, trip, family, force=True)
    except Exception:  # noqa: BLE001
        logger.exception("Distance recompute failed for family %s", family_id)


def _default_service() -> DistanceMatrixServiceProtocol:
    from app.services.distance_matrix import DistanceMatrixService  # noqa: PLC0415

    return DistanceMatrixService()
