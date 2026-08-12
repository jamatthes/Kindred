"""The rules a suggestion obeys, in one place, so the router stays a thin layer of HTTP.

Three things live here rather than in the router or the model:

1. **Query-time grouping.** An activity or meal sitting at an accommodation is nested inside
   that accommodation's card. There is no column and no join table: the relationship is
   *derived* on every read, from an equal `place_id` or a haversine proximity below
   `settings.suggestion_group_radius_m`. Moving a pin therefore re-groups automatically, which
   a stored parent link would not — it would need a migration and a background fixer to stay
   true. Ties resolve to the nearest accommodation, then to the oldest.

2. **The N+1 budget.** A list read is **two** queries regardless of how many suggestions,
   authors, families or comments are involved: one for the rows with their author and family
   joined, one for the comment counts grouped by subject. `tests/test_service_suggestions.py`
   asserts the count, because "it got slower" is not something a test notices otherwise.

3. **The move epsilon.** `moved_beyond_epsilon` is what protects the Distance Matrix budget
   from a pin dragged two metres: below `settings.suggestion_move_epsilon_m` no recompute is
   queued (`design.md`'s edge-case table).

This module also exists as a **capability check**: `services/polls.py::suggestions_available()`
probes for it by import, so its presence is what flips `can_seed_region` on. That is why it
must never import `services.polls` — the probe would import a module that imports the prober.

NOTE (M3 sequencing): two of `SuggestionOut`'s fields are shaped here and filled by sibling
features. `vote_summary` comes from `suggestion_votes`, created by `voting-comments`;
`distances` come from `distance_cache`, created by `distances`. Neither table exists yet, so
this module emits the honest zero — a zero tally and an empty distance list — rather than
omitting the fields, so the client contract does not change when those features land. Both
places are marked `NOTE (voting-comments)` / `NOTE (distances)` below.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable, Sequence

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    GROUPABLE_CHILD_TYPES,
    STATUS_REJECTED,
    STATUS_SCHEDULED,
    SUBJECT_SUGGESTION,
    TYPE_ACCOMMODATION,
    TYPE_REGION,
    Comment,
    Family,
    FamilyMember,
    Suggestion,
    Trip,
    User,
    centroid,
    haversine_m_py,
)
from app.schemas.common import ApiError
from app.schemas.suggestion import (
    PlaceSnapshot,
    SuggestionAuthorOut,
    SuggestionListParams,
    SuggestionOut,
    VoteSummaryOut,
)

#: The type order `sort=category_*` uses. Not alphabetical: it is the order a trip is planned
#: in — where we are staying, then what we are doing, then where we are eating — which is what
#: a reader means by "sort by category".
CATEGORY_ORDER = (TYPE_REGION, TYPE_ACCOMMODATION, "activity", "meal")


class AuthorInfo:
    """An author reduced to what a card renders: a name and a family colour."""

    __slots__ = ("display_name", "family_id", "family_color", "family_color_custom", "user_id")

    def __init__(
        self,
        *,
        user_id: uuid.UUID | None,
        display_name: str,
        family_id: uuid.UUID | None,
        family_color: int | None,
        family_color_custom: str | None,
    ) -> None:
        self.user_id = user_id
        self.display_name = display_name
        self.family_id = family_id
        self.family_color = family_color
        self.family_color_custom = family_color_custom


class SuggestionRow:
    """One suggestion plus everything a response needs about it, assembled once."""

    __slots__ = ("suggestion", "author", "comment_count", "children")

    def __init__(
        self, suggestion: Suggestion, author: AuthorInfo, comment_count: int
    ) -> None:
        self.suggestion = suggestion
        self.author = author
        self.comment_count = comment_count
        self.children: list[SuggestionRow] = []


# --- loading -----------------------------------------------------------------------------------


def _base_query() -> Select:
    """Every suggestion read goes through this, so the joins are decided once.

    The author's family is resolved by an outer join rather than a per-row lookup: an author
    may have left the trip (`created_by` is `ON DELETE SET NULL`), and a suggestion by nobody
    still has to render.

    **Columns, not entities**, for the author and the family. Selecting a `Family` entity would
    trigger its `members` relationship (`lazy="selectin"`), which is a second query fetching
    every member of every family that authored anything — for a name and a colour swatch. The
    five columns below are the whole of what a card renders.
    """
    return (
        select(
            Suggestion,
            User.id,
            User.display_name,
            Family.id,
            Family.color,
            Family.color_custom,
        )
        .outerjoin(User, User.id == Suggestion.created_by)
        .outerjoin(FamilyMember, FamilyMember.user_id == Suggestion.created_by)
        .outerjoin(
            Family,
            and_(Family.id == FamilyMember.family_id, Family.trip_id == Suggestion.trip_id),
        )
    )


def _author_from(row) -> AuthorInfo:  # noqa: ANN001 - a Row of the five columns above
    _, user_id, display_name, family_id, family_color, family_color_custom = row
    return AuthorInfo(
        user_id=user_id,
        # The same wording `polls` uses for a deleted author, so the two read alike.
        display_name=display_name or "Someone who has left",
        family_id=family_id,
        family_color=family_color,
        family_color_custom=family_color_custom,
    )


async def _comment_counts(
    db: AsyncSession, suggestion_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """One grouped query for every thread, not one per suggestion."""
    if not suggestion_ids:
        return {}
    rows = await db.execute(
        select(Comment.subject_id, func.count())
        .where(
            Comment.subject_type == SUBJECT_SUGGESTION,
            Comment.subject_id.in_(suggestion_ids),
        )
        .group_by(Comment.subject_id)
    )
    return {row[0]: row[1] for row in rows.all()}


async def load_suggestion(
    db: AsyncSession, suggestion_id: uuid.UUID, trip: Trip | None
) -> SuggestionRow:
    """One suggestion, or `404`. Trip-scoped: a suggestion on another trip is not found."""
    result = (
        await db.execute(_base_query().where(Suggestion.id == suggestion_id))
    ).unique().first()
    if result is None:
        raise ApiError(404, "not_found", "That suggestion does not exist.")
    suggestion = result[0]
    if trip is not None and suggestion.trip_id != trip.id:
        raise ApiError(404, "not_found", "That suggestion does not exist.")
    counts = await _comment_counts(db, [suggestion.id])
    return SuggestionRow(suggestion, _author_from(result), counts.get(suggestion.id, 0))


async def list_suggestions(
    db: AsyncSession, trip: Trip, params: SuggestionListParams
) -> list[SuggestionRow]:
    """The single source for both the map and the list view.

    Two queries total, whatever the row count. Filters and sort are applied before grouping,
    then grouping nests what survives — so filtering to "meals only" shows the meals as top
    level rather than hiding them inside accommodations that the filter removed.
    """
    query = _base_query().where(Suggestion.trip_id == trip.id)

    if params.type:
        query = query.where(Suggestion.type.in_(params.type))
    if params.status:
        query = query.where(Suggestion.status.in_(params.status))
    elif not params.include_rejected:
        # A rejection is not a deletion: the row stays in the record and out of the way. An
        # explicit `status` filter always wins, so asking for rejected ones works.
        query = query.where(Suggestion.status != STATUS_REJECTED)
    if params.family_id:
        query = query.where(Family.id.in_(params.family_id))

    query = _apply_sort(query, params.sort)

    results = (await db.execute(query)).unique().all()
    counts = await _comment_counts(db, [row[0].id for row in results])
    rows = [
        SuggestionRow(row[0], _author_from(row), counts.get(row[0].id, 0))
        for row in results
    ]

    return group_rows(rows) if params.group else rows


def _apply_sort(query: Select, sort: str) -> Select:
    """Order the list.

    NOTE (voting-comments / distances): `votes_*` and `distance_*` are accepted and currently
    order by creation, because `suggestion_votes` and `distance_cache` do not exist yet. They
    are accepted rather than rejected so the client's sort control — which is built now, by the
    web agent — has a stable contract, and so the two features can start ordering by their own
    columns without a wire change. A silent fallback is the honest option here: the alternative
    is a `422` on a control the user can see.
    """
    key, _, direction = sort.rpartition("_")
    descending = direction == "desc"

    if key == "category":
        # Ordered by the planning sequence, not alphabetically — see `CATEGORY_ORDER`. A CASE
        # rather than a stored sort column: the order is a property of the product, not of the
        # data, and a column would have to be backfilled every time the list changed.
        rank = case(
            {name: index for index, name in enumerate(CATEGORY_ORDER)},
            value=Suggestion.type,
            else_=len(CATEGORY_ORDER),
        )
        return query.order_by(rank.desc() if descending else rank, Suggestion.created_at)

    column = Suggestion.created_at
    return query.order_by(column.desc() if descending else column)


# --- grouping ----------------------------------------------------------------------------------


def group_rows(rows: list[SuggestionRow]) -> list[SuggestionRow]:
    """Nest activities and meals under the accommodation they sit at.

    The rule, from `design.md`: a child matches an accommodation on an equal non-null
    `place_id`, **or** on a haversine distance below `settings.suggestion_group_radius_m`. When
    more than one accommodation matches, the nearest wins; when two are equally near, the older
    one does, so the nesting is stable across reads rather than depending on row order.

    Returns the top-level rows with `children` populated; nested rows are removed from the top
    level. The map asks for `group=false` and draws every pin, offset, regardless.
    """
    parents = [row for row in rows if row.suggestion.type == TYPE_ACCOMMODATION]
    if not parents:
        return rows

    nested: set[uuid.UUID] = set()
    for row in rows:
        if row.suggestion.type not in GROUPABLE_CHILD_TYPES:
            continue
        parent = _nearest_parent(row, parents)
        if parent is None:
            continue
        parent.children.append(row)
        nested.add(row.suggestion.id)

    return [row for row in rows if row.suggestion.id not in nested]


def _nearest_parent(child: SuggestionRow, parents: Iterable[SuggestionRow]) -> SuggestionRow | None:
    best: SuggestionRow | None = None
    best_key: tuple[float, float] | None = None
    for parent in parents:
        distance = _grouping_distance(child.suggestion, parent.suggestion)
        if distance is None:
            continue
        # Ties resolve to the oldest, so the nesting does not flip between two identical
        # candidates from one read to the next.
        key = (distance, parent.suggestion.created_at.timestamp())
        if best_key is None or key < best_key:
            best, best_key = parent, key
    return best


def _grouping_distance(child: Suggestion, parent: Suggestion) -> float | None:
    """Metres between a child and a candidate parent, or ``None`` when they do not group.

    A shared `place_id` is treated as distance zero rather than as a separate branch: "the same
    place" is the strongest possible proximity claim, and expressing it that way means the
    nearest-wins tie-break covers it for free.
    """
    if child.place_id and parent.place_id and child.place_id == parent.place_id:
        return 0.0
    distance = haversine_m_py(child.lat, child.lng, parent.lat, parent.lng)
    return distance if distance <= settings.suggestion_group_radius_m else None


# --- movement ------------------------------------------------------------------------------------


def moved_beyond_epsilon(
    old_lat: float, old_lng: float, new_lat: float, new_lng: float
) -> bool:
    """Whether a pin moved far enough to be worth asking Google about again.

    Below `settings.suggestion_move_epsilon_m` the move is jitter — a drag of a few pixels at
    street zoom — and recomputing would spend the Distance Matrix budget on a pin that did not
    really move (`design.md`'s edge-case table).
    """
    return (
        haversine_m_py(old_lat, old_lng, new_lat, new_lng)
        > settings.suggestion_move_epsilon_m
    )


async def queue_distance_recompute(db: AsyncSession, suggestion: Suggestion) -> None:
    """Ask `distances` to recompute this pin against every geocoded family home.

    **Deliberately a no-op today.** `distances` (M3, same milestone, separate feature) owns
    `distance_cache` and the background task; this is the single call site
    `map-suggestions` needs, placed and tested now — `tests/test_router_suggestions.py`
    asserts a 5 m move does not reach it and a 500 m move does — so that feature has one
    function to fill in rather than a create path and a patch path to find.

    It takes the session it should eventually write through, so filling it in does not change
    either call site. **It must never call Google inline**: this is reached from a request
    handler, and `CLAUDE.md`'s "never call Google in a render path" is the rule the whole
    caching design rests on.
    """
    return None


# --- serialisation --------------------------------------------------------------------------------


def serialise(
    row: SuggestionRow,
    *,
    can_edit: bool = False,
    can_change_status: bool = False,
    children: list[SuggestionOut] | None = None,
) -> SuggestionOut:
    """One suggestion as the wire sees it.

    Lives in the service rather than the router because two routers need it: `suggestions`
    serves it directly, and `polls`' seed-region route broadcasts the region it created without
    importing another router to do so.

    **Nothing Google-sourced is read here.** `place_snapshot_json` is user-authored, and the
    only other Google value in the row is `place_id`, which the ToS explicitly permits.
    """
    suggestion = row.suggestion
    snapshot = suggestion.place_snapshot_json
    return SuggestionOut(
        id=suggestion.id,
        trip_id=suggestion.trip_id,
        type=suggestion.type,
        title=suggestion.title,
        notes=suggestion.notes,
        status=suggestion.status,
        created_by=SuggestionAuthorOut(
            user_id=row.author.user_id,
            display_name=row.author.display_name,
            family_id=row.author.family_id,
            family_color=row.author.family_color,
            family_color_custom=row.author.family_color_custom,
        ),
        lat=suggestion.lat,
        lng=suggestion.lng,
        geometry_geojson=suggestion.geometry_geojson,
        boundary_source=suggestion.boundary_source,
        place_id=suggestion.place_id,
        place_snapshot=PlaceSnapshot(**snapshot) if isinstance(snapshot, dict) else None,
        external_url=suggestion.external_url,
        # NOTE (voting-comments): the honest zero until `suggestion_votes` exists.
        vote_summary=VoteSummaryOut(),
        comment_count=row.comment_count,
        # NOTE (distances): empty until `distance_cache` exists.
        distances=[],
        children=children or [],
        can_edit=can_edit,
        can_delete=can_edit and suggestion.status != STATUS_SCHEDULED,
        can_change_status=can_change_status,
        created_at=suggestion.created_at,
        updated_at=suggestion.updated_at,
    )


# --- geometry -------------------------------------------------------------------------------------


def resolve_centroid(geometry: dict[str, Any] | None) -> tuple[float, float]:
    """The point a region's geometry reduces to, or `422`.

    The server recomputes this on every write rather than trusting the client's `lat`/`lng`
    (`design.md`: "the server recomputes and overwrites the centroid for regions"). A client
    that drew a shape in Cornwall and sent a point in Kent would otherwise produce a region
    that sorts, selects and measures distance from the wrong place.
    """
    point = centroid(geometry)
    if point is None:
        raise ApiError(
            422,
            "invalid_geometry",
            "That shape could not be reduced to a point on the map.",
        )
    return point


def circle_feature(lat: float, lng: float, radius_m: float) -> dict[str, Any]:
    """A circle region as GeoJSON. Coordinates are `[lng, lat]` — GeoJSON order."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": {"shape": "circle", "radius_m": radius_m},
    }
