"""Reading distances. **This module cannot call Google, and that is the point.**

`plan/features/distances/design.md` opens with a HARD INVARIANT: "a request serving a page, a
list, a card, or a panel never calls Distance Matrix". Every render path in the product goes
through this module, and it enforces that rule *structurally* rather than by discipline —

* it imports no Google client, directly or transitively (`app.services.distance_matrix` is the
  only module that talks to Distance Matrix, and `app.services.distance_tasks` is its only
  importer);
* `tests/test_service_distances_read.py` walks this module's import graph and fails if that
  ever stops being true.

A future edit that reaches for a live value from a render path therefore fails a test rather
than quietly spending the API budget every time somebody opens the map.

**What a read does when there is no cached answer** is return a haversine straight line,
computed in SQL in the same query, marked `is_estimate` and carrying **no duration**. An
estimate is a real number and renders immediately; it simply sharpens when Google answers.
Fabricating a driving time from a straight line would be the same dishonesty the chart widgets
refuse, on a card people plan around. Estimates are never written to `distance_cache` — the
cache holds real answers only.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import Float, and_, case, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DISTANCE_NO_HOME,
    DISTANCE_NO_ROUTE,
    DISTANCE_OK,
    DISTANCE_PENDING,
    DistanceCache,
    Family,
    Suggestion,
    Trip,
    haversine_m,
)
from app.schemas.distance import DistanceOut

async def get_distances_for_suggestion(
    db: AsyncSession,
    suggestion: Suggestion,
    trip: Trip,
    *,
    own_family_id: uuid.UUID | None = None,
) -> list[DistanceOut]:
    """Every family's distance to one suggestion, the caller's own family first.

    One query: the trip's families left-joined to their cached row, with the haversine fallback
    computed in SQL beside it. Families with no geocoded home come back as `no_home` rather than
    being dropped — a household missing from the list with no explanation is worse than one
    labelled "home address not set", which is also actionable for that family's head.
    """
    rows = await _rows(db, trip, suggestion_ids=[suggestion.id])
    return _order(rows.get(suggestion.id, []), own_family_id)


async def get_distances_bulk(
    db: AsyncSession,
    trip: Trip,
    *,
    suggestion_ids: Sequence[uuid.UUID] | None = None,
    family_id: uuid.UUID | None = None,
    own_family_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, list[DistanceOut]]:
    """The list view's form: every suggestion's distances in one request, and one query.

    `family_id` narrows the result to one family's values — what the list's distance column
    actually renders, and what switching the sort perspective refetches.
    """
    rows = await _rows(db, trip, suggestion_ids=suggestion_ids, family_id=family_id)
    return {sid: _order(items, own_family_id) for sid, items in rows.items()}


async def _rows(
    db: AsyncSession,
    trip: Trip,
    *,
    suggestion_ids: Sequence[uuid.UUID] | None = None,
    family_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, list[DistanceOut]]:
    """The single query behind both readers.

    A cross join of the trip's suggestions and the trip's families, left-joined to whatever the
    cache holds. The cross join is what makes "every family appears for every suggestion, with
    or without a row" true in SQL rather than in a Python loop that would have to fetch both
    lists and pair them up — and it is bounded by a family group's size, not by anything that
    grows with use.
    """
    suggestions = select(Suggestion.id.label("sid"), Suggestion.lat, Suggestion.lng).where(
        Suggestion.trip_id == trip.id
    )
    if suggestion_ids is not None:
        suggestions = suggestions.where(Suggestion.id.in_(list(suggestion_ids)))
    suggestions = suggestions.subquery()

    families = select(
        Family.id.label("fid"),
        Family.name,
        Family.color,
        Family.color_custom,
        Family.home_lat,
        Family.home_lng,
    ).where(Family.trip_id == trip.id)
    if family_id is not None:
        families = families.where(Family.id == family_id)
    families = families.subquery()

    # The straight line, computed in the database on every read where a real answer is absent
    # (`design.md` > Haversine fallback). `haversine_m` is the shared expression helper from
    # `models/geo.py` — deliberately not a second implementation, so a chip and a sort can never
    # disagree about how far away something is by a rounding difference.
    estimate = case(
        (
            and_(families.c.home_lat.isnot(None), families.c.home_lng.isnot(None)),
            haversine_m(
                families.c.home_lat, families.c.home_lng, suggestions.c.lat, suggestions.c.lng
            ),
        ),
        else_=None,
    ).cast(Float).label("estimate")

    query = (
        select(
            suggestions.c.sid,
            families.c.fid,
            families.c.name,
            families.c.color,
            families.c.color_custom,
            families.c.home_lat,
            DistanceCache.status,
            DistanceCache.duration_s,
            DistanceCache.distance_m,
            DistanceCache.computed_at,
            estimate,
        )
        .select_from(suggestions)
        .join(families, literal(True))
        .outerjoin(
            DistanceCache,
            and_(
                DistanceCache.suggestion_id == suggestions.c.sid,
                DistanceCache.family_id == families.c.fid,
            ),
        )
        .order_by(families.c.color, families.c.name)
    )

    out: dict[uuid.UUID, list[DistanceOut]] = {}
    for row in (await db.execute(query)).all():
        out.setdefault(row.sid, []).append(_to_out(row))
    return out


def _to_out(row) -> DistanceOut:  # noqa: ANN001 - the Row of the query above
    """One row of the cross join, resolved into the state the UI renders.

    The order of these branches is the honesty rule in code form: a family with no home is
    `no_home` before anything else is considered, a real answer wins over an estimate, a
    `no_route` is reported as the answer it is, and everything left over degrades to the
    straight line **without** a duration.
    """
    common = {
        "family_id": row.fid,
        "family_name": row.name,
        "family_color": row.color,
        "family_color_custom": row.color_custom,
    }

    if row.home_lat is None:
        # Not a failure and not a pending computation: there is simply nowhere to measure from.
        return DistanceOut(**common, status=DISTANCE_NO_HOME, is_estimate=False)

    if row.status == DISTANCE_OK and row.distance_m is not None:
        return DistanceOut(
            **common,
            status=DISTANCE_OK,
            duration_s=row.duration_s,
            distance_m=row.distance_m,
            is_estimate=False,
            computed_at=row.computed_at,
        )

    if row.status == DISTANCE_NO_ROUTE:
        # The answer, not a gap in the data — so no estimate is offered underneath it. A
        # straight line across the Channel is not a fact anybody can act on.
        return DistanceOut(
            **common,
            status=DISTANCE_NO_ROUTE,
            is_estimate=False,
            computed_at=row.computed_at,
        )

    # `pending`, `failed`, or no row at all: the straight line, distance only.
    return DistanceOut(
        **common,
        status=row.status or DISTANCE_PENDING,
        distance_m=int(row.estimate) if row.estimate is not None else None,
        is_estimate=True,
    )


def _order(
    items: list[DistanceOut], own_family_id: uuid.UUID | None
) -> list[DistanceOut]:
    """The caller's own family first; the rest keep the query's colour-then-name order.

    Own-family-first because that is the number the reader actually wants — "how far is it from
    *us*" — and putting it anywhere else makes every card a scan.
    """
    if own_family_id is None:
        return items
    return sorted(items, key=lambda d: 0 if d.family_id == own_family_id else 1)


def estimated_api_calls(pair_count: int, suggestion_count: int) -> int:
    """How many Distance Matrix requests a recompute of `pair_count` pairs will cost.

    Stated to the organiser **before** the work runs, per `design.md`: a trip with 60
    suggestions and 6 families is roughly six chunked calls, not 360, and an admin deciding
    whether to press the button deserves the real number rather than the pair count.

    Shaped as "one call per suggestion, all homes at once" — the create/move shape, which is
    what a recompute re-issues.
    """
    return suggestion_count if pair_count else 0


async def recompute_scope(
    db: AsyncSession, trip: Trip, *, suggestion_id: uuid.UUID | None = None
) -> tuple[int, int]:
    """How much work a force-recompute is about to be, as `(pairs, suggestions)`.

    Counted here, in the **read** module, precisely because the number has to be stated to the
    organiser before anything is queued — and counting is a read. Only families with a geocoded
    home count: a family with nowhere to measure from is not a pair anybody can compute, and
    including it would overstate the cost.
    """
    from sqlalchemy import func  # noqa: PLC0415 - one use, and the read path stays lean

    families = (
        await db.scalar(
            select(func.count())
            .select_from(Family)
            .where(
                Family.trip_id == trip.id,
                Family.home_lat.isnot(None),
                Family.home_lng.isnot(None),
            )
        )
    ) or 0

    query = select(func.count()).select_from(Suggestion).where(Suggestion.trip_id == trip.id)
    if suggestion_id is not None:
        query = query.where(Suggestion.id == suggestion_id)
    suggestions = (await db.scalar(query)) or 0

    return families * suggestions, suggestions
