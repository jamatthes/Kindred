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

NOTE (M3 sequencing): `vote_summary` is now real — `voting-comments` created `suggestion_votes`
and its aggregate is joined into the one query below, mode-converted per
`voting-comments/design.md`. `distances` is still the honest empty list until `distances`
creates `distance_cache`; the call site is marked `NOTE (distances)` and takes the list as a
parameter, so filling it in changes nothing else.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    GROUPABLE_CHILD_TYPES,
    THUMB_DOWN,
    THUMB_UP,
    THUMBS_DOWN_FROM_SCORE,
    THUMBS_UP_FROM_SCORE,
    STATUS_REJECTED,
    STATUS_SCHEDULED,
    SUBJECT_SUGGESTION,
    TYPE_ACCOMMODATION,
    TYPE_REGION,
    Comment,
    Family,
    FamilyMember,
    Suggestion,
    SuggestionVote,
    Trip,
    User,
    centroid,
    haversine_m_py,
)
from app.schemas.common import ApiError
from app.schemas.distance import DistanceOut
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

    __slots__ = ("suggestion", "author", "comment_count", "votes", "children")

    def __init__(
        self,
        suggestion: Suggestion,
        author: AuthorInfo,
        comment_count: int,
        votes: VoteAggregate | None = None,
    ) -> None:
        self.suggestion = suggestion
        self.author = author
        self.comment_count = comment_count
        self.votes = votes or VoteAggregate()
        self.children: list[SuggestionRow] = []


class VoteAggregate:
    """One suggestion's votes, reduced to the six numbers a card renders.

    Deliberately *not* the full `TallyOut`: the list needs the summary, and the panel — which
    also needs attribution and the outstanding list — asks `GET /suggestions/{id}/votes` for it.
    Fetching every voter for every row of a list that shows none of them would be the N+1 this
    module exists to avoid, in aggregate form.
    """

    __slots__ = ("score_count", "score_sum", "score_up", "score_down", "score_mid",
                 "thumb_up", "thumb_down", "my_score", "my_thumb")

    def __init__(
        self,
        *,
        score_count: int = 0,
        score_sum: int = 0,
        score_up: int = 0,
        score_down: int = 0,
        score_mid: int = 0,
        thumb_up: int = 0,
        thumb_down: int = 0,
        my_score: int | None = None,
        my_thumb: str | None = None,
    ) -> None:
        self.score_count = score_count
        self.score_sum = score_sum
        self.score_up = score_up
        self.score_down = score_down
        self.score_mid = score_mid
        self.thumb_up = thumb_up
        self.thumb_down = thumb_down
        self.my_score = my_score
        self.my_thumb = my_thumb

    def summarise(self, mode: str) -> VoteSummaryOut:
        """The summary as the active mode reads it.

        The mode-change rules from `voting-comments/design.md` apply here exactly as they do in
        the full tally, because a list row and a side panel disagreeing about whether somebody
        voted would be worse than either being wrong alone:

        * *score mode* — stored thumbs contribute **nothing**. No number can honestly be
          invented from "I liked it", so those voters are simply not in `count`.
        * *thumbs mode* — stored scores convert by threshold, with a stored 5 counted as
          `unclear` rather than rounded into a camp, and the whole summary flagged `converted`.
        """
        if mode == "thumbs":
            up = self.thumb_up + self.score_up
            down = self.thumb_down + self.score_down
            return VoteSummaryOut(
                mode="thumbs",
                count=up + down + self.score_mid,
                up=up,
                down=down,
                unclear=self.score_mid,
                converted=bool(self.score_count),
                my_vote=self.my_score,
                my_thumb=self.my_thumb,
            )
        return VoteSummaryOut(
            mode="score",
            count=self.score_count,
            # Null, never 0.0, when nobody has scored — the honesty rule `poll_stats` states.
            average=(
                round(self.score_sum / self.score_count, 2) if self.score_count else None
            ),
            converted=False,
            my_vote=self.my_score,
            my_thumb=self.my_thumb,
        )


# --- loading -----------------------------------------------------------------------------------


def _base_query(caller_id: uuid.UUID | None = None) -> Select:
    """Every suggestion read goes through this, so the joins are decided once.

    The author's family is resolved by an outer join rather than a per-row lookup: an author
    may have left the trip (`created_by` is `ON DELETE SET NULL`), and a suggestion by nobody
    still has to render.

    **Columns, not entities**, for the author and the family. Selecting a `Family` entity would
    trigger its `members` relationship (`lazy="selectin"`), which is a second query fetching
    every member of every family that authored anything — for a name and a colour swatch.

    **The tally and the comment count arrive as pre-grouped joins**, not as per-row lookups.
    Each is a one-row-per-suggestion derived table, so joining them multiplies nothing, and the
    whole list — rows, authors, families, votes, threads, and the caller's own vote — is one
    query however many suggestions there are.
    """
    votes = (
        select(
            SuggestionVote.suggestion_id.label("sid"),
            func.count(SuggestionVote.score).label("score_count"),
            func.coalesce(func.sum(SuggestionVote.score), 0).label("score_sum"),
            func.count(case((SuggestionVote.score >= THUMBS_UP_FROM_SCORE, 1))).label("score_up"),
            func.count(case((SuggestionVote.score <= THUMBS_DOWN_FROM_SCORE, 1))).label(
                "score_down"
            ),
            func.count(
                case(
                    (
                        and_(
                            SuggestionVote.score > THUMBS_DOWN_FROM_SCORE,
                            SuggestionVote.score < THUMBS_UP_FROM_SCORE,
                        ),
                        1,
                    )
                )
            ).label("score_mid"),
            func.count(case((SuggestionVote.thumb == THUMB_UP, 1))).label("thumb_up"),
            func.count(case((SuggestionVote.thumb == THUMB_DOWN, 1))).label("thumb_down"),
        )
        .group_by(SuggestionVote.suggestion_id)
        .subquery()
    )
    threads = (
        select(Comment.subject_id.label("sid"), func.count().label("comment_count"))
        .where(Comment.subject_type == SUBJECT_SUGGESTION, Comment.deleted_at.is_(None))
        .group_by(Comment.subject_id)
        .subquery()
    )
    mine = (
        select(
            SuggestionVote.suggestion_id.label("sid"),
            SuggestionVote.score.label("my_score"),
            SuggestionVote.thumb.label("my_thumb"),
        )
        .where(SuggestionVote.user_id == caller_id)
        .subquery()
    )

    return (
        select(
            Suggestion,
            User.id,
            User.display_name,
            Family.id,
            Family.color,
            Family.color_custom,
            func.coalesce(threads.c.comment_count, 0),
            func.coalesce(votes.c.score_count, 0),
            func.coalesce(votes.c.score_sum, 0),
            func.coalesce(votes.c.score_up, 0),
            func.coalesce(votes.c.score_down, 0),
            func.coalesce(votes.c.score_mid, 0),
            func.coalesce(votes.c.thumb_up, 0),
            func.coalesce(votes.c.thumb_down, 0),
            mine.c.my_score,
            mine.c.my_thumb,
        )
        .outerjoin(User, User.id == Suggestion.created_by)
        .outerjoin(FamilyMember, FamilyMember.user_id == Suggestion.created_by)
        .outerjoin(
            Family,
            and_(Family.id == FamilyMember.family_id, Family.trip_id == Suggestion.trip_id),
        )
        .outerjoin(threads, threads.c.sid == Suggestion.id)
        .outerjoin(votes, votes.c.sid == Suggestion.id)
        .outerjoin(mine, mine.c.sid == Suggestion.id)
    )


def _author_from(row) -> AuthorInfo:  # noqa: ANN001 - a Row of the columns above
    return AuthorInfo(
        user_id=row[1],
        # The same wording `polls` uses for a deleted author, so the two read alike.
        display_name=row[2] or "Someone who has left",
        family_id=row[3],
        family_color=row[4],
        family_color_custom=row[5],
    )


def _row_from(row) -> SuggestionRow:  # noqa: ANN001 - a Row of the columns above
    return SuggestionRow(
        row[0],
        _author_from(row),
        comment_count=row[6],
        votes=VoteAggregate(
            score_count=row[7],
            score_sum=row[8],
            score_up=row[9],
            score_down=row[10],
            score_mid=row[11],
            thumb_up=row[12],
            thumb_down=row[13],
            my_score=row[14],
            my_thumb=row[15],
        ),
    )


async def load_suggestion(
    db: AsyncSession,
    suggestion_id: uuid.UUID,
    trip: Trip | None,
    *,
    caller_id: uuid.UUID | None = None,
) -> SuggestionRow:
    """One suggestion, or `404`. Trip-scoped: a suggestion on another trip is not found."""
    result = (
        await db.execute(_base_query(caller_id).where(Suggestion.id == suggestion_id))
    ).unique().first()
    if result is None:
        raise ApiError(404, "not_found", "That suggestion does not exist.")
    if trip is not None and result[0].trip_id != trip.id:
        raise ApiError(404, "not_found", "That suggestion does not exist.")
    return _row_from(result)


async def list_suggestions(
    db: AsyncSession,
    trip: Trip,
    params: SuggestionListParams,
    *,
    caller_id: uuid.UUID | None = None,
) -> list[SuggestionRow]:
    """The single source for both the map and the list view.

    **One query**, whatever the row count. Filters and sort are applied before grouping,
    then grouping nests what survives — so filtering to "meals only" shows the meals as top
    level rather than hiding them inside accommodations that the filter removed.
    """
    query = _base_query(caller_id).where(Suggestion.trip_id == trip.id)

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

    rows = [_row_from(row) for row in (await db.execute(query)).unique().all()]

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


async def queue_distance_recompute(
    db: AsyncSession, suggestion: Suggestion, background=None, *, moved: bool = False
) -> None:
    """Ask `distances` to recompute this pin against every geocoded family home.

    The single call site `map-suggestions` owns — reached on create, and on a move past
    `settings.suggestion_move_epsilon_m` and not otherwise. It was a placed no-op until
    `distances` landed; `tests/test_router_suggestions.py` asserted the epsilon behaviour
    through it before there was anything behind it, and asserts the same thing now.

    **This does not call Google inline.** It hands off to
    `app/services/distance_tasks.py`, which owns every Distance Matrix call in the product and
    is never imported by a read path — `CLAUDE.md`'s "never call Google in a render path" is
    the rule the whole caching design rests on, and the import graph is what enforces it. The
    import is local for the same reason: this module *is* a read path.
    """
    from app.services.distance_tasks import queue_for_suggestion_safely  # noqa: PLC0415

    # A **move** is an invalidation, not a first computation: every cached value for this pin
    # is now about a place it no longer is, including the settled ones. `design.md`: "existing
    # rows for that suggestion reset to `pending`; chips revert to estimates; one call re-fills
    # them." A create has nothing to reset.
    if background is not None:
        # Runs after the response is sent, so creating a suggestion never waits on Google.
        background.add_task(
            queue_for_suggestion_safely, suggestion.trip_id, suggestion.id, moved
        )
        return
    await queue_for_suggestion_safely(suggestion.trip_id, suggestion.id, moved)


# --- serialisation --------------------------------------------------------------------------------


def serialise(
    row: SuggestionRow,
    *,
    can_edit: bool = False,
    can_change_status: bool = False,
    children: list[SuggestionOut] | None = None,
    mode: str = "score",
    distances: list[DistanceOut] | None = None,
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
        vote_summary=row.votes.summarise(mode),
        comment_count=row.comment_count,
        # NOTE (distances): empty until `distance_cache` exists.
        distances=distances or [],
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
