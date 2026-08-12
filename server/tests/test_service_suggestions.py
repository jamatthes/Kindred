"""The service layer: grouping, the query budget, and the move epsilon.

Grouping is derived on every read rather than stored, so these tests are the only place the
rule is written down as behaviour — there is no column to inspect and no migration to read.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import engine
from app.models import Family, Suggestion, Trip, User
from app.schemas.suggestion import SuggestionListParams
from app.services import suggestions as service
from tests.conftest import add_member, make_family, make_user


#: A metre of latitude, near enough, for building "100 m away" without arithmetic in the test.
DEGREE_LAT_M = 111_320.0


def north_of(lat: float, metres: float) -> float:
    return lat + metres / DEGREE_LAT_M


BASE_LAT, BASE_LNG = 50.4000, -4.7000


async def make_suggestion(
    db: AsyncSession,
    trip: Trip,
    author: User,
    *,
    type: str = "activity",
    title: str = "Something",
    lat: float = BASE_LAT,
    lng: float = BASE_LNG,
    place_id: str | None = None,
    status: str = "proposed",
    geometry: dict | None = None,
) -> Suggestion:
    suggestion = Suggestion(
        trip_id=trip.id,
        type=type,
        title=title,
        status=status,
        created_by=author.id,
        lat=lat,
        lng=lng,
        place_id=place_id,
        geometry_geojson=geometry,
    )
    db.add(suggestion)
    await db.commit()
    await db.refresh(suggestion)
    return suggestion


@pytest.fixture
async def author(db: AsyncSession, trip: Trip) -> tuple[User, Family]:
    user = await make_user(db, "suggester")
    family = await make_family(db, trip, "Suggestons", color=3)
    await add_member(db, family, user, role="head")
    return user, family


@pytest.fixture
def query_counter() -> Iterator[list[str]]:
    """Every SQL statement the suite issues while the fixture is live.

    Attached to the engine rather than to a session so nothing can hide a lazy load behind a
    second connection.
    """
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    yield statements
    event.remove(engine.sync_engine, "before_cursor_execute", record)


# --- grouping ---------------------------------------------------------------------------------


async def test_an_activity_sharing_a_place_id_nests_under_the_accommodation(
    db: AsyncSession, trip: Trip, author: tuple[User, Family]
) -> None:
    user, _ = author
    hotel = await make_suggestion(
        db, trip, user, type="accommodation", title="The Barn", place_id="place-barn"
    )
    # Deliberately far away in coordinates: an equal `place_id` is the strongest proximity
    # claim there is, and must outrank the distance test rather than being checked after it.
    await make_suggestion(
        db, trip, user, title="Breakfast", type="meal", place_id="place-barn",
        lat=51.5, lng=-0.12,
    )

    rows = await service.list_suggestions(db, trip, SuggestionListParams())

    assert [r.suggestion.id for r in rows] == [hotel.id]
    assert [c.suggestion.title for c in rows[0].children] == ["Breakfast"]


async def test_an_activity_a_hundred_metres_away_nests(
    db: AsyncSession, trip: Trip, author: tuple[User, Family]
) -> None:
    user, _ = author
    await make_suggestion(db, trip, user, type="accommodation", title="The Barn")
    await make_suggestion(
        db, trip, user, title="Cliff walk", lat=north_of(BASE_LAT, 100), lng=BASE_LNG
    )

    rows = await service.list_suggestions(db, trip, SuggestionListParams())

    assert len(rows) == 1
    assert [c.suggestion.title for c in rows[0].children] == ["Cliff walk"]


async def test_an_activity_five_kilometres_away_does_not_nest(
    db: AsyncSession, trip: Trip, author: tuple[User, Family]
) -> None:
    user, _ = author
    await make_suggestion(db, trip, user, type="accommodation", title="The Barn")
    await make_suggestion(
        db, trip, user, title="The beach", lat=north_of(BASE_LAT, 5_000), lng=BASE_LNG
    )

    rows = await service.list_suggestions(db, trip, SuggestionListParams())

    assert len(rows) == 2
    assert all(not r.children for r in rows)


async def test_a_tie_resolves_to_the_nearer_parent(
    db: AsyncSession, trip: Trip, author: tuple[User, Family]
) -> None:
    """Two accommodations within the radius; the child belongs to the nearer one."""
    user, _ = author
    await make_suggestion(db, trip, user, type="accommodation", title="Far inn",
                          lat=north_of(BASE_LAT, 140), lng=BASE_LNG)
    near = await make_suggestion(db, trip, user, type="accommodation", title="Near inn",
                                 lat=north_of(BASE_LAT, 10), lng=BASE_LNG)
    await make_suggestion(db, trip, user, title="Dinner", type="meal")

    rows = await service.list_suggestions(db, trip, SuggestionListParams())

    parents = {r.suggestion.id: r for r in rows}
    assert [c.suggestion.title for c in parents[near.id].children] == ["Dinner"]
    assert not parents[[i for i in parents if i != near.id][0]].children


async def test_grouping_is_off_for_the_map(
    db: AsyncSession, trip: Trip, author: tuple[User, Family]
) -> None:
    """The map draws every child's own pin, offset — so it asks for the flat list."""
    user, _ = author
    await make_suggestion(db, trip, user, type="accommodation", title="The Barn")
    await make_suggestion(db, trip, user, title="Cliff walk")

    rows = await service.list_suggestions(db, trip, SuggestionListParams(group=False))

    assert len(rows) == 2
    assert all(not r.children for r in rows)


async def test_a_region_never_becomes_a_child(
    db: AsyncSession, trip: Trip, author: tuple[User, Family]
) -> None:
    """Only activities and meals group. A region sitting over an accommodation is the area the
    accommodation is *in*, not a thing happening at it."""
    user, _ = author
    await make_suggestion(db, trip, user, type="accommodation", title="The Barn")
    await make_suggestion(
        db,
        trip,
        user,
        type="region",
        title="Around here",
        geometry=service.circle_feature(BASE_LAT, BASE_LNG, 5_000),
    )

    rows = await service.list_suggestions(db, trip, SuggestionListParams())

    assert len(rows) == 2


# --- filters and sort ---------------------------------------------------------------------------


async def test_rejected_suggestions_are_hidden_unless_asked_for(
    db: AsyncSession, trip: Trip, author: tuple[User, Family]
) -> None:
    user, _ = author
    await make_suggestion(db, trip, user, title="Kept")
    await make_suggestion(db, trip, user, title="Turned down", status="rejected")

    assert len(await service.list_suggestions(db, trip, SuggestionListParams())) == 1
    assert (
        len(
            await service.list_suggestions(
                db, trip, SuggestionListParams(include_rejected=True)
            )
        )
        == 2
    )


async def test_an_explicit_status_filter_outranks_include_rejected(
    db: AsyncSession, trip: Trip, author: tuple[User, Family]
) -> None:
    user, _ = author
    await make_suggestion(db, trip, user, title="Turned down", status="rejected")

    rows = await service.list_suggestions(
        db, trip, SuggestionListParams(status=["rejected"])
    )

    assert [r.suggestion.title for r in rows] == ["Turned down"]


async def test_sorting_by_category_follows_the_planning_order_not_the_alphabet(
    db: AsyncSession, trip: Trip, author: tuple[User, Family]
) -> None:
    user, _ = author
    await make_suggestion(db, trip, user, type="meal", title="Dinner", lat=52.0)
    await make_suggestion(db, trip, user, type="accommodation", title="The Barn", lat=53.0)
    await make_suggestion(
        db,
        trip,
        user,
        type="region",
        title="Around here",
        lat=54.0,
        geometry=service.circle_feature(54.0, BASE_LNG, 5_000),
    )

    rows = await service.list_suggestions(
        db, trip, SuggestionListParams(sort="category_asc", group=False)
    )

    assert [r.suggestion.type for r in rows] == ["region", "accommodation", "meal"]


async def test_filtering_by_family_uses_the_authors_family(
    db: AsyncSession, trip: Trip, author: tuple[User, Family]
) -> None:
    mine, my_family = author
    theirs = await make_user(db, "otherhouse")
    other_family = await make_family(db, trip, "Others", color=4)
    await add_member(db, other_family, theirs, role="head")

    await make_suggestion(db, trip, mine, title="Ours")
    await make_suggestion(db, trip, theirs, title="Theirs", lat=52.0)

    rows = await service.list_suggestions(
        db, trip, SuggestionListParams(family_id=[my_family.id])
    )

    assert [r.suggestion.title for r in rows] == ["Ours"]


# --- the query budget ----------------------------------------------------------------------------


async def test_the_list_costs_two_queries_however_many_rows_there_are(
    db: AsyncSession, trip: Trip, author: tuple[User, Family], query_counter: list[str]
) -> None:
    """One query for the rows with their author and family joined, one for the comment counts.

    Asserted rather than assumed: "it got slower" is not something a test notices otherwise,
    and the obvious way to add a field to this response is a per-row lookup.
    """
    user, _ = author
    for i in range(12):
        await make_suggestion(db, trip, user, title=f"Thing {i}", lat=50.0 + i)

    trip.id  # noqa: B018 - the commits above expired it; refresh it before counting
    query_counter.clear()
    rows = await service.list_suggestions(db, trip, SuggestionListParams())

    assert len(rows) == 12
    selects = [s for s in query_counter if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 2, "\n---\n".join(s[:200] for s in selects)


async def test_serialising_the_list_adds_no_queries_of_its_own(
    db: AsyncSession, trip: Trip, author: tuple[User, Family], query_counter: list[str]
) -> None:
    """The author's name and family colour are already on the row, so building the response
    touches the database not at all."""
    user, _ = author
    for i in range(5):
        await make_suggestion(db, trip, user, title=f"Thing {i}", lat=50.0 + i)
    rows = await service.list_suggestions(db, trip, SuggestionListParams())

    query_counter.clear()
    out = [service.serialise(row) for row in rows]

    assert len(out) == 5
    assert query_counter == []
    assert out[0].created_by.display_name == user.display_name
    assert out[0].created_by.family_color == 3


async def test_an_author_who_has_left_still_renders(
    db: AsyncSession, trip: Trip, author: tuple[User, Family]
) -> None:
    """`created_by` is `ON DELETE SET NULL`: the proposal the group voted on survives,
    attributed to nobody, rather than vanishing with the account."""
    user, _ = author
    await make_suggestion(db, trip, user, title="Orphaned")
    # Deleted in SQL rather than through the ORM: the account's other rows cascade in the
    # database, which is the behaviour the `ON DELETE SET NULL` on `created_by` belongs to.
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()

    rows = await service.list_suggestions(db, trip, SuggestionListParams())

    assert service.serialise(rows[0]).created_by.display_name == "Someone who has left"


# --- the move epsilon ------------------------------------------------------------------------------


def test_a_trivial_drag_is_below_the_epsilon():
    """Five metres is jitter. Recomputing would spend the Distance Matrix budget on a pin that
    did not really move."""
    assert not service.moved_beyond_epsilon(
        BASE_LAT, BASE_LNG, north_of(BASE_LAT, 5), BASE_LNG
    )


def test_a_real_move_is_above_the_epsilon():
    assert service.moved_beyond_epsilon(
        BASE_LAT, BASE_LNG, north_of(BASE_LAT, 500), BASE_LNG
    )


def test_the_epsilon_is_a_setting_not_a_literal():
    """`tasks.md` Phase 4: the threshold lives in `core/config.py`, so it is tuned in one
    place rather than in whichever query was edited last."""
    assert settings.suggestion_move_epsilon_m == 25.0
    assert settings.suggestion_group_radius_m == 150.0
