"""The background task: batching, status mapping, the attempt cap, and the pending guard.

Every test here runs against a fake Distance Matrix client. Nothing in this file touches the
network, per `plan/architecture.md`'s testing strategy — and the assertions about *how many
calls were made* are as load-bearing as the ones about what was stored, because this is the one
module in the product that can spend money.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import DistanceCache, Family, Suggestion, Trip
from app.services import distance_tasks as tasks
from app.services.distance_matrix import (
    DistanceServiceQuotaError,
    ElementResult,
    LatLng,
)
from tests.conftest import make_family

LONDON = (51.5074, -0.1278)
PARIS = (48.8566, 2.3522)


@dataclass
class FakeMatrix:
    """A scripted Distance Matrix. Records every call so a test can assert the *shape* of the
    batching, not merely its result."""

    status: str = "ok"
    duration_s: int = 17_400
    distance_m: int = 459_000
    raises: Exception | None = None
    many_to_one_calls: list[tuple[int, LatLng]] = field(default_factory=list)
    one_to_many_calls: list[tuple[LatLng, int]] = field(default_factory=list)

    @property
    def calls(self) -> int:
        return len(self.many_to_one_calls) + len(self.one_to_many_calls)

    def _element(self, origin: LatLng, destination: LatLng) -> ElementResult:
        if self.status == "ok":
            return ElementResult(
                origin=origin,
                destination=destination,
                status="ok",
                duration_s=self.duration_s,
                distance_m=self.distance_m,
            )
        return ElementResult(origin=origin, destination=destination, status=self.status)

    async def get_distances_many_to_one(self, origins, destination, *, mode="driving"):
        if self.raises is not None:
            raise self.raises
        self.many_to_one_calls.append((len(origins), destination))
        return [self._element(o, destination) for o in origins]

    async def get_distances_one_to_many(self, origin, destinations, *, mode="driving"):
        if self.raises is not None:
            raise self.raises
        self.one_to_many_calls.append((origin, len(destinations)))
        return [self._element(origin, d) for d in destinations]

    async def get_distances_pairwise(self, pairs, *, mode="driving"):  # pragma: no cover
        raise AssertionError("this feature never uses the pairwise shape")


async def _family(
    db: AsyncSession, trip: Trip, name: str, color: int, home: tuple[float, float] | None = LONDON
) -> Family:
    family = await make_family(db, trip, name, color=color)
    if home is not None:
        family.home_lat, family.home_lng = home
        family.geocode_status = "ok"
    await db.commit()
    await db.refresh(family)
    return family


async def _suggestion(db: AsyncSession, trip: Trip, title: str = "The Barn") -> Suggestion:
    suggestion = Suggestion(
        trip_id=trip.id,
        type="accommodation",
        title=title,
        status="proposed",
        lat=PARIS[0],
        lng=PARIS[1],
    )
    db.add(suggestion)
    await db.commit()
    await db.refresh(suggestion)
    return suggestion


async def _rows(db: AsyncSession) -> list[DistanceCache]:
    return list((await db.scalars(select(DistanceCache))).unique().all())


async def _expire_the_lease(db: AsyncSession) -> None:
    """Age every claim past `settings.distance_claim_lease_seconds`.

    Stands in for the passage of time between one trigger and the next: within the lease a pair
    belongs to the task that claimed it, so a test simulating a *later* retry has to say so.
    """
    from sqlalchemy import update

    await db.execute(
        update(DistanceCache).values(
            updated_at=datetime.now(UTC)
            - timedelta(seconds=settings.distance_claim_lease_seconds * 2)
        )
    )
    await db.commit()


# --- the create/move shape --------------------------------------------------------------------


async def test_six_families_cost_exactly_one_call(db: AsyncSession, trip: Trip) -> None:
    """The common case, and the one the batching is optimised for: one request, six rows."""
    for i in range(6):
        await _family(db, trip, f"Family {i}", i + 1)
    suggestion = await _suggestion(db, trip)
    matrix = FakeMatrix()

    answered = await tasks.queue_for_suggestion(db, trip, suggestion, service=matrix)

    assert answered == 6
    assert matrix.calls == 1
    assert matrix.many_to_one_calls[0][0] == 6
    rows = await _rows(db)
    assert len(rows) == 6
    assert all(r.status == "ok" and r.duration_s == 17_400 for r in rows)
    assert all(r.computed_at is not None for r in rows)


async def test_a_family_without_a_home_is_never_sent_to_google(
    db: AsyncSession, trip: Trip
) -> None:
    """There is nowhere to measure from, so there is no element to pay for."""
    await _family(db, trip, "Londoners", 1)
    homeless = await _family(db, trip, "Nomads", 2, home=None)
    suggestion = await _suggestion(db, trip)
    matrix = FakeMatrix()

    await tasks.queue_for_suggestion(db, trip, suggestion, service=matrix)

    assert matrix.many_to_one_calls[0][0] == 1
    rows = await _rows(db)
    assert [r.family_id for r in rows] != [homeless.id]
    assert homeless.id not in {r.family_id for r in rows}


async def test_nothing_happens_when_no_family_has_a_home(
    db: AsyncSession, trip: Trip
) -> None:
    """A suggestion created before anybody has an address makes no call; the first geocoded
    home backfills every pair."""
    await _family(db, trip, "Nomads", 1, home=None)
    suggestion = await _suggestion(db, trip)
    matrix = FakeMatrix()

    assert await tasks.queue_for_suggestion(db, trip, suggestion, service=matrix) == 0
    assert matrix.calls == 0
    assert await _rows(db) == []


# --- the home-change shape -----------------------------------------------------------------------


async def test_a_home_change_measures_that_family_against_every_suggestion(
    db: AsyncSession, trip: Trip
) -> None:
    family = await _family(db, trip, "Londoners", 1)
    for i in range(60):
        await _suggestion(db, trip, f"Thing {i}")
    matrix = FakeMatrix()

    answered = await tasks.queue_for_family(db, trip, family, service=matrix)

    assert answered == 60
    # One call from this module's point of view; the client chunks it internally at 25
    # destinations per request, which `tests/test_distance_matrix.py` covers.
    assert matrix.calls == 1
    assert matrix.one_to_many_calls[0][1] == 60
    assert len(await _rows(db)) == 60


async def test_a_home_change_leaves_other_families_values_alone(
    db: AsyncSession, trip: Trip
) -> None:
    """Nothing about the other households changed, so nothing of theirs is invalidated."""
    mine = await _family(db, trip, "Mine", 1)
    theirs = await _family(db, trip, "Theirs", 2)
    suggestion = await _suggestion(db, trip)
    await tasks.queue_for_suggestion(db, trip, suggestion, service=FakeMatrix())

    before = {
        r.family_id: r.computed_at for r in await _rows(db)
    }
    fresh = FakeMatrix(duration_s=999, distance_m=888)
    await tasks.queue_for_family(db, trip, mine, service=fresh, force=True)

    rows = {r.family_id: r for r in await _rows(db)}
    assert rows[mine.id].duration_s == 999
    assert rows[theirs.id].duration_s == 17_400
    assert rows[theirs.id].computed_at == before[theirs.id]


async def test_a_family_with_no_coordinates_queues_nothing(
    db: AsyncSession, trip: Trip
) -> None:
    family = await _family(db, trip, "Nomads", 1, home=None)
    await _suggestion(db, trip)
    matrix = FakeMatrix()

    assert await tasks.queue_for_family(db, trip, family, service=matrix) == 0
    assert matrix.calls == 0


# --- status mapping ----------------------------------------------------------------------------------


async def test_zero_results_is_cached_permanently_as_no_route(
    db: AsyncSession, trip: Trip
) -> None:
    """**The single most important case `status` exists for.** Without it, a pair with genuinely
    no driving route reads as "not computed" on every render and is re-queued forever against a
    paid endpoint."""
    await _family(db, trip, "Londoners", 1)
    suggestion = await _suggestion(db, trip)
    matrix = FakeMatrix(status="zero_results")

    await tasks.queue_for_suggestion(db, trip, suggestion, service=matrix)

    [row] = await _rows(db)
    assert row.status == "no_route"
    assert row.duration_s is None
    assert row.distance_m is None
    assert row.computed_at is not None


async def test_a_no_route_pair_is_never_re_queued(db: AsyncSession, trip: Trip) -> None:
    """The assertion that matters is the call count: a second trigger must cost nothing."""
    await _family(db, trip, "Londoners", 1)
    suggestion = await _suggestion(db, trip)
    matrix = FakeMatrix(status="zero_results")
    await tasks.queue_for_suggestion(db, trip, suggestion, service=matrix)
    calls_after_first = matrix.calls

    await tasks.queue_for_suggestion(db, trip, suggestion, service=matrix)

    assert matrix.calls == calls_after_first
    [row] = await _rows(db)
    assert row.status == "no_route"


async def test_an_ok_pair_is_never_recomputed_by_an_ordinary_trigger(
    db: AsyncSession, trip: Trip
) -> None:
    await _family(db, trip, "Londoners", 1)
    suggestion = await _suggestion(db, trip)
    matrix = FakeMatrix()
    await tasks.queue_for_suggestion(db, trip, suggestion, service=matrix)

    await tasks.queue_for_suggestion(db, trip, suggestion, service=matrix)

    assert matrix.calls == 1


async def test_not_found_spends_an_attempt_and_settles_at_the_cap(
    db: AsyncSession, trip: Trip
) -> None:
    """Bad coordinates are worth another look, but not an unbounded number of them.

    The lease is expired by hand between attempts because a real retry arrives on a *later*
    trigger, minutes apart — within the lease the pair is still owned by the task that claimed
    it, which is the guard `test_two_overlapping_queues_produce_one_call` covers.
    """
    await _family(db, trip, "Londoners", 1)
    suggestion = await _suggestion(db, trip)
    matrix = FakeMatrix(status="not_found")

    for expected in range(1, settings.distance_max_attempts + 1):
        await _expire_the_lease(db)
        await tasks.queue_for_suggestion(db, trip, suggestion, service=matrix)
        [row] = await _rows(db)
        await db.refresh(row)
        assert row.attempts == expected

    [row] = await _rows(db)
    assert row.status == "failed"
    assert row.attempts == settings.distance_max_attempts

    # And a settled `failed` row is left alone by ordinary triggers.
    calls = matrix.calls
    await tasks.queue_for_suggestion(db, trip, suggestion, service=matrix)
    assert matrix.calls == calls


# --- whole-request failures -----------------------------------------------------------------------------


async def test_a_quota_failure_spends_one_attempt_and_raises_nothing(
    db: AsyncSession, trip: Trip
) -> None:
    """A distance failure must never fail the thing it decorates, and retrying into an
    exhausted quota is how a bad afternoon becomes a bill."""
    await _family(db, trip, "Londoners", 1)
    suggestion = await _suggestion(db, trip)
    matrix = FakeMatrix(raises=DistanceServiceQuotaError("OVER_QUERY_LIMIT"))

    answered = await tasks.queue_for_suggestion(db, trip, suggestion, service=matrix)

    assert answered == 0
    [row] = await _rows(db)
    await db.refresh(row)
    assert row.attempts == 1
    # Below the cap, so a later trigger will try again — once the claim lease has expired.
    assert row.status == "pending"


async def test_the_fire_and_forget_wrapper_swallows_everything(
    db: AsyncSession, trip: Trip
) -> None:
    """The wrapper a request handler schedules. If this can raise, a quota problem at Google
    becomes "your suggestion could not be saved"."""
    await _family(db, trip, "Londoners", 1)
    suggestion = await _suggestion(db, trip)

    # A trip id that no longer exists is the bluntest possible failure; nothing may escape.
    await tasks.queue_for_suggestion_safely(trip.id, suggestion.id)
    await tasks.queue_for_family_safely(trip.id, suggestion.id)


# --- the pending guard ------------------------------------------------------------------------------------


async def test_two_overlapping_queues_produce_one_call(
    db: AsyncSession, trip: Trip
) -> None:
    """The realistic way this feature would leak budget. The row *is* the lock: the second
    claim finds nothing unclaimed and returns without calling."""
    import asyncio

    from app.core.db import SessionFactory

    await _family(db, trip, "Londoners", 1)
    suggestion = await _suggestion(db, trip)
    matrix = FakeMatrix()

    async def run() -> None:
        async with SessionFactory() as session:
            current = await session.get(Trip, trip.id)
            target = await session.get(Suggestion, suggestion.id)
            await tasks.queue_for_suggestion(session, current, target, service=matrix)

    await asyncio.gather(run(), run())

    assert matrix.calls == 1
    assert len(await _rows(db)) == 1


async def test_a_claim_leaves_a_pending_row_so_a_concurrent_read_shows_pending(
    db: AsyncSession, trip: Trip
) -> None:
    """A chip about to sharpen should not first look like a pair nobody has considered."""
    family = await _family(db, trip, "Londoners", 1)
    suggestion = await _suggestion(db, trip)

    claimed = await tasks._claim(db, [(family.id, suggestion.id)])

    assert claimed == [(family.id, suggestion.id)]
    [row] = await _rows(db)
    assert row.status == "pending"


# --- the force-recompute --------------------------------------------------------------------------------------


async def test_recompute_is_the_only_path_that_revisits_a_no_route(
    db: AsyncSession, trip: Trip
) -> None:
    await _family(db, trip, "Londoners", 1)
    suggestion = await _suggestion(db, trip)
    await tasks.queue_for_suggestion(db, trip, suggestion, service=FakeMatrix(status="zero_results"))

    matrix = FakeMatrix()
    await tasks.recompute(db, trip, suggestion_id=suggestion.id, service=matrix)

    assert matrix.calls == 1
    [row] = await _rows(db)
    await db.refresh(row)
    assert row.status == "ok"
    assert row.attempts == 0


async def test_recompute_resets_a_failed_rows_attempts(
    db: AsyncSession, trip: Trip
) -> None:
    await _family(db, trip, "Londoners", 1)
    suggestion = await _suggestion(db, trip)
    exhausted = FakeMatrix(status="not_found")
    for _ in range(settings.distance_max_attempts):
        await tasks.queue_for_suggestion(db, trip, suggestion, service=exhausted)

    await tasks.recompute(db, trip, suggestion_id=suggestion.id, service=FakeMatrix())

    [row] = await _rows(db)
    await db.refresh(row)
    assert row.status == "ok"
    assert row.attempts == 0


async def test_recompute_across_the_whole_trip_is_one_call_per_suggestion(
    db: AsyncSession, trip: Trip
) -> None:
    for i in range(3):
        await _family(db, trip, f"Family {i}", i + 1)
    for i in range(4):
        await _suggestion(db, trip, f"Thing {i}")
    matrix = FakeMatrix()

    answered = await tasks.recompute(db, trip, service=matrix)

    assert matrix.calls == 4  # not 12
    assert answered == 12


# --- the frozen stage ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("entry", ["suggestion", "family", "recompute"])
async def test_no_external_call_is_made_in_the_end_stage(
    db: AsyncSession, trip: Trip, entry: str
) -> None:
    """Point 4 of the hard invariant, force-recompute included."""
    family = await _family(db, trip, "Londoners", 1)
    suggestion = await _suggestion(db, trip)
    trip.stage = "end"
    await db.commit()
    matrix = FakeMatrix()

    if entry == "suggestion":
        await tasks.queue_for_suggestion(db, trip, suggestion, service=matrix)
    elif entry == "family":
        await tasks.queue_for_family(db, trip, family, service=matrix)
    else:
        await tasks.recompute(db, trip, service=matrix)

    assert matrix.calls == 0
    assert await _rows(db) == []


# --- the broadcast ----------------------------------------------------------------------------------------------


async def test_each_row_is_announced_as_it_lands(
    db: AsyncSession, trip: Trip, monkeypatch
) -> None:
    """Per row, not per batch, so a chip sharpens as soon as its own answer arrives rather than
    waiting for the slowest sibling in the chunk."""
    sent: list[tuple] = []

    async def spy(trip_id, type_, payload=None):
        sent.append((type_, payload))
        return 0

    monkeypatch.setattr("app.services.distance_tasks.ws.broadcast", spy)
    for i in range(3):
        await _family(db, trip, f"Family {i}", i + 1)
    suggestion = await _suggestion(db, trip)

    await tasks.queue_for_suggestion(db, trip, suggestion, service=FakeMatrix())

    assert [event for event, _ in sent] == ["distance.updated"] * 3
    payload = sent[0][1]
    assert payload["suggestion_id"] == str(suggestion.id)
    assert payload["status"] == "ok"
    assert payload["is_estimate"] is False
    assert payload["duration_s"] == 17_400


async def test_a_suggestion_deleted_mid_computation_writes_nothing(
    db: AsyncSession, trip: Trip
) -> None:
    """The upsert finds no row and discards the result rather than resurrecting one for
    something that no longer exists."""
    family = await _family(db, trip, "Londoners", 1)
    suggestion = await _suggestion(db, trip)
    await tasks._claim(db, [(family.id, suggestion.id)])
    await db.delete(suggestion)
    await db.commit()

    await tasks._write(
        db,
        trip.id,
        family.id,
        suggestion.id,
        ElementResult(
            origin=LatLng(lat=0, lng=0),
            destination=LatLng(lat=1, lng=1),
            status="ok",
            duration_s=1,
            distance_m=1,
        ),
    )

    assert await _rows(db) == []
