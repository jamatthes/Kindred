"""The read half: estimates, `no_home`, the query budget — and the hard invariant.

**`test_the_read_module_cannot_reach_google` is the enforcement of the HARD INVARIANT** in
`plan/features/distances/design.md`: "a request serving a page, a list, a card, or a panel never
calls Distance Matrix". It walks the read module's transitive import graph rather than trusting
a comment, so a future edit that reaches for a live value from a render path fails here instead
of quietly spending the API budget every time somebody opens the map.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import engine
from app.models import DistanceCache, Family, Suggestion, Trip, User
from app.services import distances as read_service
from tests.conftest import add_member, make_family, make_user

# London to Paris, roughly 343 km straight line.
LONDON = (51.5074, -0.1278)
PARIS = (48.8566, 2.3522)


@pytest.fixture
def query_counter() -> Iterator[list[str]]:
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    yield statements
    event.remove(engine.sync_engine, "before_cursor_execute", record)


async def _family(
    db: AsyncSession, trip: Trip, name: str, color: int, home: tuple[float, float] | None
) -> Family:
    family = await make_family(db, trip, name, color=color)
    if home is not None:
        family.home_lat, family.home_lng = home
        family.geocode_status = "ok"
        family.home_geocoded_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(family)
    return family


async def _suggestion(db: AsyncSession, trip: Trip, author: User | None = None) -> Suggestion:
    suggestion = Suggestion(
        trip_id=trip.id,
        type="accommodation",
        title="The Barn",
        status="proposed",
        created_by=author.id if author else None,
        lat=PARIS[0],
        lng=PARIS[1],
    )
    db.add(suggestion)
    await db.commit()
    await db.refresh(suggestion)
    return suggestion


# --- THE HARD INVARIANT ---------------------------------------------------------------------


def test_the_read_module_cannot_reach_google() -> None:
    """**This test is the enforcement of the hard invariant.**

    `design.md`: "A request serving a page, a list, a card, or a panel **never** calls Distance
    Matrix." Every render path goes through `app.services.distances`, so the guarantee is that
    module's import graph containing no Google client — checked here transitively, because an
    indirect import spends money just as effectively as a direct one.

    If this fails, do not relax it. Move whatever needs Google into
    `app/services/distance_tasks.py`, which is the only module allowed to import
    `app/services/distance_matrix.py` and runs from background tasks alone.
    """
    seen: set[str] = set()
    forbidden = {"app.services.distance_matrix", "app.services.distance_tasks"}

    def walk(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        module = sys.modules.get(name)
        if module is None:
            return
        for attribute in vars(module).values():
            candidate = getattr(attribute, "__module__", None) or getattr(
                attribute, "__name__", None
            )
            if isinstance(candidate, str) and candidate.startswith("app."):
                walk(candidate)

    walk(read_service.__name__)

    assert not (seen & forbidden), (
        f"{read_service.__name__} can reach {sorted(seen & forbidden)} — a render path must "
        "not be able to call Distance Matrix"
    )
    # And no import statement anywhere in the module names it — the form a reviewer checks,
    # including the lazy in-function imports the rest of the codebase uses to break cycles,
    # which is exactly where such a call would be smuggled in.
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(read_service))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not any(
        "distance_matrix" in name or "distance_tasks" in name or "google" in name
        for name in imported
    ), sorted(imported)


# --- estimates -------------------------------------------------------------------------------


async def test_a_pair_with_no_row_falls_back_to_a_haversine_estimate(
    db: AsyncSession, trip: Trip
) -> None:
    """An estimate is a real number and renders immediately; it simply sharpens later."""
    family = await _family(db, trip, "Londoners", 1, LONDON)
    suggestion = await _suggestion(db, trip)

    [distance] = await read_service.get_distances_for_suggestion(db, suggestion, trip)

    assert distance.family_id == family.id
    assert distance.is_estimate is True
    assert distance.distance_m == pytest.approx(343_500, abs=2_000)
    # The load-bearing half: no fabricated driving time.
    assert distance.duration_s is None
    assert distance.computed_at is None


async def test_a_pending_pair_also_returns_an_estimate(
    db: AsyncSession, trip: Trip
) -> None:
    """`pending` means "queued, not answered" — the chip shows a number rather than a spinner."""
    family = await _family(db, trip, "Londoners", 1, LONDON)
    suggestion = await _suggestion(db, trip)
    db.add(
        DistanceCache(family_id=family.id, suggestion_id=suggestion.id, status="pending")
    )
    await db.commit()

    [distance] = await read_service.get_distances_for_suggestion(db, suggestion, trip)

    assert distance.status == "pending"
    assert distance.is_estimate is True
    assert distance.duration_s is None


async def test_a_failed_pair_returns_an_estimate_too(
    db: AsyncSession, trip: Trip
) -> None:
    """The trip stays fully usable when the distance service is not: distances are an
    enhancement, not a dependency."""
    family = await _family(db, trip, "Londoners", 1, LONDON)
    suggestion = await _suggestion(db, trip)
    db.add(
        DistanceCache(
            family_id=family.id, suggestion_id=suggestion.id, status="failed", attempts=3
        )
    )
    await db.commit()

    [distance] = await read_service.get_distances_for_suggestion(db, suggestion, trip)

    assert distance.status == "failed"
    assert distance.is_estimate is True
    assert distance.distance_m is not None


# --- real answers -------------------------------------------------------------------------------


async def test_a_cached_answer_wins_over_the_estimate(
    db: AsyncSession, trip: Trip
) -> None:
    family = await _family(db, trip, "Londoners", 1, LONDON)
    suggestion = await _suggestion(db, trip)
    db.add(
        DistanceCache(
            family_id=family.id,
            suggestion_id=suggestion.id,
            status="ok",
            duration_s=17_400,
            distance_m=459_000,
            computed_at=datetime.now(UTC),
        )
    )
    await db.commit()

    [distance] = await read_service.get_distances_for_suggestion(db, suggestion, trip)

    assert distance.status == "ok"
    assert distance.is_estimate is False
    assert (distance.duration_s, distance.distance_m) == (17_400, 459_000)
    assert distance.computed_at is not None


async def test_no_route_is_reported_as_the_answer_not_as_a_gap(
    db: AsyncSession, trip: Trip
) -> None:
    """No estimate is offered underneath it: a straight line across the Channel is not a fact
    anybody can act on, and showing one would imply a drive that does not exist."""
    family = await _family(db, trip, "Londoners", 1, LONDON)
    suggestion = await _suggestion(db, trip)
    db.add(
        DistanceCache(
            family_id=family.id,
            suggestion_id=suggestion.id,
            status="no_route",
            computed_at=datetime.now(UTC),
        )
    )
    await db.commit()

    [distance] = await read_service.get_distances_for_suggestion(db, suggestion, trip)

    assert distance.status == "no_route"
    assert distance.is_estimate is False
    assert distance.distance_m is None
    assert distance.duration_s is None


# --- no_home ----------------------------------------------------------------------------------------


async def test_a_family_without_a_home_is_present_and_labelled(
    db: AsyncSession, trip: Trip
) -> None:
    """Never omitted: a household missing from the list with no explanation is worse than one
    labelled "home address not set", which is also the prompt that gets it fixed."""
    await _family(db, trip, "Londoners", 1, LONDON)
    homeless = await _family(db, trip, "Nomads", 2, None)
    suggestion = await _suggestion(db, trip)

    distances = await read_service.get_distances_for_suggestion(db, suggestion, trip)

    by_family = {d.family_id: d for d in distances}
    assert by_family[homeless.id].status == "no_home"
    assert by_family[homeless.id].distance_m is None
    assert by_family[homeless.id].is_estimate is False


# --- ordering ---------------------------------------------------------------------------------------


async def test_the_callers_own_family_comes_first(
    db: AsyncSession, trip: Trip
) -> None:
    """"How far is it from *us*" is the number the reader wants; putting it anywhere else makes
    every card a scan."""
    first = await _family(db, trip, "Aardvarks", 1, LONDON)
    mine = await _family(db, trip, "Zebras", 9, LONDON)
    suggestion = await _suggestion(db, trip)

    distances = await read_service.get_distances_for_suggestion(
        db, suggestion, trip, own_family_id=mine.id
    )

    assert [d.family_id for d in distances] == [mine.id, first.id]


# --- the query budget ---------------------------------------------------------------------------------


async def test_the_bulk_read_costs_one_query_however_many_suggestions(
    db: AsyncSession, trip: Trip, query_counter: list[str]
) -> None:
    """One cross join, not one query per suggestion and certainly not one per pair."""
    for i in range(3):
        await _family(db, trip, f"Family {i}", i + 1, LONDON)
    for _ in range(10):
        await _suggestion(db, trip)

    trip.id  # noqa: B018 - refresh the expired attribute before counting
    query_counter.clear()
    result = await read_service.get_distances_bulk(db, trip)

    assert len(result) == 10
    assert all(len(v) == 3 for v in result.values())
    selects = [s for s in query_counter if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1, "\n---\n".join(s[:200] for s in selects)


async def test_the_bulk_read_can_narrow_to_one_family(
    db: AsyncSession, trip: Trip
) -> None:
    """What the list's distance column actually renders, and what switching the sort
    perspective refetches — without re-requesting every suggestion."""
    mine = await _family(db, trip, "Mine", 1, LONDON)
    await _family(db, trip, "Theirs", 2, LONDON)
    suggestion = await _suggestion(db, trip)

    result = await read_service.get_distances_bulk(db, trip, family_id=mine.id)

    assert [d.family_id for d in result[suggestion.id]] == [mine.id]


async def test_the_bulk_read_can_narrow_to_named_suggestions(
    db: AsyncSession, trip: Trip
) -> None:
    await _family(db, trip, "Mine", 1, LONDON)
    wanted = await _suggestion(db, trip)
    await _suggestion(db, trip)

    result = await read_service.get_distances_bulk(db, trip, suggestion_ids=[wanted.id])

    assert list(result) == [wanted.id]


# --- the recompute estimate ------------------------------------------------------------------------------


async def test_the_recompute_scope_counts_pairs_and_calls_before_any_work(
    db: AsyncSession, trip: Trip
) -> None:
    """A trip with 60 suggestions and 6 families is roughly six chunked calls, not 360 — and
    the organiser deserves the real number before pressing the button."""
    for i in range(6):
        await _family(db, trip, f"Family {i}", i + 1, LONDON)
    for _ in range(60):
        await _suggestion(db, trip)

    pairs, suggestions = await read_service.recompute_scope(db, trip)

    assert pairs == 360
    assert suggestions == 60
    assert read_service.estimated_api_calls(pairs, suggestions) == 60


async def test_a_family_without_a_home_is_not_counted_as_work(
    db: AsyncSession, trip: Trip
) -> None:
    """It is not a pair anybody can compute, and counting it would overstate the cost."""
    await _family(db, trip, "Londoners", 1, LONDON)
    await _family(db, trip, "Nomads", 2, None)
    await _suggestion(db, trip)

    pairs, _ = await read_service.recompute_scope(db, trip)

    assert pairs == 1


async def test_recompute_scope_can_be_narrowed_to_one_suggestion(
    db: AsyncSession, trip: Trip
) -> None:
    await _family(db, trip, "Londoners", 1, LONDON)
    one = await _suggestion(db, trip)
    await _suggestion(db, trip)

    pairs, suggestions = await read_service.recompute_scope(db, trip, suggestion_id=one.id)

    assert (pairs, suggestions) == (1, 1)
