"""The suggestion routes: happy path, permissions, stage guard, transitions, and the ToS.

The permission tests matter here for the opposite reason they do in `polls`: a family head or
spouse **does** have rights over their own household's suggestions, because a suggestion
belongs to the family that made it — while having none at all over another family's. Both
halves are easy to get wrong by pattern-matching on the other feature.

The last section is the one that must never be deleted: it asserts that no Google Place
Details field can be stored, which is a licensing obligation rather than a preference.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models import Family, Suggestion, Trip, User
from app.services import suggestions as service
from app.services.boundaries import BoundaryResult, EllipseFallback, get_boundary_service
from app.services.link_preview import LinkPreview, get_link_preview_service
from tests.conftest import add_member, login_as, make_family, make_user

SUGGESTIONS = "/api/v1/suggestions"
LINK_PREVIEW = "/api/v1/link-preview"

BASE_LAT, BASE_LNG = 50.4000, -4.7000
DEGREE_LAT_M = 111_320.0


def code(response: httpx.Response) -> str:
    return response.json()["detail"]["code"]


def north_of(lat: float, metres: float) -> float:
    return lat + metres / DEGREE_LAT_M


def circle(lng: float = BASE_LNG, lat: float = BASE_LAT, radius_m: float = 12_000) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": {"shape": "circle", "radius_m": radius_m},
    }


ACCOMMODATION = {
    "type": "accommodation",
    "title": "The Barn",
    "notes": "Sleeps eight",
    "lat": BASE_LAT,
    "lng": BASE_LNG,
}


@pytest.fixture
async def household(db: AsyncSession, trip: Trip) -> dict:
    """One trip with three households and every role that matters to this feature.

    * `owner` — the trip's owner, so `require_organiser` is satisfied by an ordinary account
      rather than by the platform-admin bootstrap bypass, which would let a permission test
      pass for the wrong reason.
    * `head` / `spouse` / `child` — one family. `child` authors; the other two are the people
      who may tidy up after them.
    * `stranger` — a plain member of a different family, who may not.
    """
    owner = await make_user(db, "tripowner")
    owners = await make_family(db, trip, "Owners", color=1)
    await add_member(db, owners, owner, role="head")

    head = await make_user(db, "thehead")
    spouse = await make_user(db, "thespouse")
    child = await make_user(db, "thechild")
    family = await make_family(db, trip, "Suggestons", color=2)
    await add_member(db, family, head, role="head")
    await add_member(db, family, spouse, role="spouse")
    await add_member(db, family, child, role="member")

    stranger = await make_user(db, "stranger")
    others = await make_family(db, trip, "Others", color=3)
    await add_member(db, others, stranger, role="head")

    trip.owner_user_id = owner.id
    await db.commit()
    return {
        "owner": owner,
        "head": head,
        "spouse": spouse,
        "child": child,
        "stranger": stranger,
        "family": family,
    }


async def _create(client: httpx.AsyncClient, body: dict | None = None) -> dict:
    response = await client.post(SUGGESTIONS, json=body or ACCOMMODATION)
    assert response.status_code == 201, response.text
    return response.json()


# --- creating ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        ACCOMMODATION,
        {"type": "activity", "title": "Surfing", "lat": BASE_LAT, "lng": BASE_LNG},
        {"type": "meal", "title": "The chippy", "lat": BASE_LAT, "lng": BASE_LNG},
        {
            "type": "region",
            "title": "Around here",
            "lat": BASE_LAT,
            "lng": BASE_LNG,
            "geometry_geojson": circle(),
        },
    ],
)
async def test_any_member_creates_a_suggestion_of_each_type(
    client: httpx.AsyncClient, db: AsyncSession, household: dict, body: dict
) -> None:
    await login_as(client, db, household["child"])
    created = await _create(client, body)

    assert created["type"] == body["type"]
    assert created["status"] == "proposed"
    assert created["created_by"]["display_name"] == household["child"].display_name
    assert created["created_by"]["family_color"] == 2


async def test_the_server_recomputes_a_regions_centroid_rather_than_trusting_the_client(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    """A shape drawn in Cornwall with a point claimed in London must end up in Cornwall.

    Otherwise the region sorts, selects and measures its distance from wherever the client
    said, which is a place nobody drew.
    """
    await login_as(client, db, household["child"])
    created = await _create(
        client,
        {
            "type": "region",
            "title": "A square",
            "lat": 51.5,  # London — deliberately wrong
            "lng": -0.12,
            "geometry_geojson": {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
                },
                "properties": {"shape": "polygon"},
            },
        },
    )

    assert created["lat"] == pytest.approx(1.0)
    assert created["lng"] == pytest.approx(1.0)


async def test_a_named_locality_region_stores_the_osm_boundary_once(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    """One fetch at creation, stored forever — never re-fetched on render, per the API-cost
    rule. The `boundary_source` is what the UI keys the ODbL attribution off."""
    boundary = BoundaryResult(
        geojson={
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-5.0, 50.0], [-4.0, 50.0], [-4.0, 51.0], [-5.0, 50.0]]],
            },
            "properties": {
                "shape": "polygon",
                "boundary_source": "osm",
                "osm_relation_id": 57537,
            },
        },
        display_name="Cornwall, England, United Kingdom",
        osm_relation_id=57537,
    )

    class _Fake:
        calls = 0

        async def lookup(self, query: str):
            _Fake.calls += 1
            return boundary

    app.dependency_overrides[get_boundary_service] = lambda: _Fake()
    try:
        await login_as(client, db, household["child"])
        created = await _create(
            client,
            {
                "type": "region",
                "title": "Cornwall",
                "lat": 0.0,
                "lng": 0.0,
                "boundary_query": "Cornwall",
            },
        )
        # Reading it back must not fetch again.
        await client.get(f"{SUGGESTIONS}/{created['id']}")
    finally:
        app.dependency_overrides.pop(get_boundary_service, None)

    assert _Fake.calls == 1
    assert created["boundary_source"] == "osm"
    assert created["lat"] == pytest.approx(50.3333)


async def test_a_locality_with_no_boundary_falls_back_to_a_fitted_ellipse(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    """Never a raw bounding-box rectangle: that would claim a precision the data has not got."""
    fallback = EllipseFallback(
        center={"lat": 50.4, "lng": -4.7},
        bounds={"south": 50.0, "west": -5.0, "north": 51.0, "east": -4.0},
        display_name="Somewhere",
        ellipse_geojson={
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-4.5, 50.0], [-4.0, 50.5], [-4.5, 51.0], [-4.5, 50.0]]],
            },
            "properties": {"shape": "polygon", "boundary_source": "fallback_ellipse"},
        },
    )

    class _Fake:
        async def lookup(self, query: str):
            return fallback

    app.dependency_overrides[get_boundary_service] = lambda: _Fake()
    try:
        await login_as(client, db, household["child"])
        created = await _create(
            client,
            {
                "type": "region",
                "title": "Somewhere",
                "lat": 0.0,
                "lng": 0.0,
                "boundary_query": "Somewhere",
            },
        )
    finally:
        app.dependency_overrides.pop(get_boundary_service, None)

    assert created["boundary_source"] == "fallback_ellipse"


async def test_an_unknown_locality_is_a_404_naming_the_alternative(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    class _Fake:
        async def lookup(self, query: str):
            return None

    app.dependency_overrides[get_boundary_service] = lambda: _Fake()
    try:
        await login_as(client, db, household["child"])
        response = await client.post(
            SUGGESTIONS,
            json={
                "type": "region",
                "title": "Atlantis",
                "lat": 0.0,
                "lng": 0.0,
                "boundary_query": "Atlantis",
            },
        )
    finally:
        app.dependency_overrides.pop(get_boundary_service, None)

    assert response.status_code == 404
    assert code(response) == "boundary_not_found"


async def test_an_outsider_with_no_family_cannot_create(
    client: httpx.AsyncClient, db: AsyncSession, household: dict, outsider: User
) -> None:
    await login_as(client, db, outsider)
    response = await client.post(SUGGESTIONS, json=ACCOMMODATION)
    assert response.status_code == 403
    assert code(response) == "not_on_trip"


async def test_creation_broadcasts_to_the_trip_room(
    client: httpx.AsyncClient, db: AsyncSession, household: dict, monkeypatch
) -> None:
    sent: list[tuple] = []

    async def spy(trip_id, type_, payload=None):
        sent.append((type_, payload))
        return 0

    monkeypatch.setattr("app.routers.suggestions.ws.broadcast", spy)
    await login_as(client, db, household["child"])
    await _create(client)

    assert [event for event, _ in sent] == ["suggestion.created"]


# --- reading ---------------------------------------------------------------------------------------


async def test_the_list_and_the_detail_read_agree(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    await login_as(client, db, household["child"])
    created = await _create(client)

    listed = await client.get(SUGGESTIONS)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [created["id"]]

    detail = await client.get(f"{SUGGESTIONS}/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "The Barn"
    assert detail.json()["comments"] == []


async def test_the_list_filters_by_type(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    await login_as(client, db, household["child"])
    await _create(client)
    await _create(
        client, {"type": "activity", "title": "Surfing", "lat": 52.0, "lng": -1.0}
    )

    response = await client.get(SUGGESTIONS, params={"type": "activity"})

    assert [row["title"] for row in response.json()] == ["Surfing"]


async def test_children_are_nested_in_the_list_and_flat_for_the_map(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    await login_as(client, db, household["child"])
    await _create(client)
    await _create(
        client,
        {
            "type": "meal",
            "title": "Breakfast",
            "lat": north_of(BASE_LAT, 50),
            "lng": BASE_LNG,
        },
    )

    nested = (await client.get(SUGGESTIONS)).json()
    assert len(nested) == 1
    assert [c["title"] for c in nested[0]["children"]] == ["Breakfast"]

    flat = (await client.get(SUGGESTIONS, params={"group": "false"})).json()
    assert len(flat) == 2
    assert all(not row["children"] for row in flat)


async def test_a_suggestion_that_does_not_exist_is_a_404(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    await login_as(client, db, household["child"])
    response = await client.get(f"{SUGGESTIONS}/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


# --- editing ----------------------------------------------------------------------------------------


async def test_the_author_edits_their_own(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    await login_as(client, db, household["child"])
    created = await _create(client)

    response = await client.patch(
        f"{SUGGESTIONS}/{created['id']}", json={"title": "The Big Barn"}
    )

    assert response.status_code == 200
    assert response.json()["title"] == "The Big Barn"


@pytest.mark.parametrize("actor", ["head", "spouse", "owner"])
async def test_the_family_head_spouse_and_an_organiser_may_all_edit(
    client: httpx.AsyncClient, db: AsyncSession, household: dict, actor: str
) -> None:
    """A suggestion belongs to the household that made it, and to the trip's organisers."""
    await login_as(client, db, household["child"])
    created = await _create(client)

    await login_as(client, db, household[actor])
    response = await client.patch(f"{SUGGESTIONS}/{created['id']}", json={"title": "Edited"})

    assert response.status_code == 200, response.text


async def test_a_member_of_another_family_may_not_edit(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    await login_as(client, db, household["child"])
    created = await _create(client)

    await login_as(client, db, household["stranger"])
    response = await client.patch(f"{SUGGESTIONS}/{created['id']}", json={"title": "Mine now"})

    assert response.status_code == 403
    assert code(response) == "forbidden"


async def test_the_head_of_another_family_may_not_edit_either(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    """`stranger` is a head — of the wrong family. A family-level role governs a family, never
    the trip."""
    await login_as(client, db, household["stranger"])
    theirs = await _create(client, {**ACCOMMODATION, "title": "Their barn"})

    await login_as(client, db, household["head"])
    response = await client.patch(f"{SUGGESTIONS}/{theirs['id']}", json={"title": "No"})

    assert response.status_code == 403


async def test_the_capability_flags_match_what_the_server_will_accept(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    """A button the UI renders and a request the server accepts come from one predicate."""
    await login_as(client, db, household["child"])
    created = await _create(client)
    assert created["can_edit"] is True
    assert created["can_delete"] is True
    assert created["can_change_status"] is False

    await login_as(client, db, household["stranger"])
    listed = (await client.get(SUGGESTIONS)).json()[0]
    assert listed["can_edit"] is False
    assert listed["can_delete"] is False

    await login_as(client, db, household["owner"])
    listed = (await client.get(SUGGESTIONS)).json()[0]
    assert listed["can_change_status"] is True


async def test_status_cannot_be_changed_through_the_general_patch(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    """The field is absent from the model entirely, so a member cannot approve their own."""
    await login_as(client, db, household["child"])
    created = await _create(client)

    response = await client.patch(
        f"{SUGGESTIONS}/{created['id']}", json={"status": "approved"}
    )

    assert response.status_code == 422


async def test_moving_a_region_recomputes_its_centroid(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    await login_as(client, db, household["child"])
    created = await _create(
        client,
        {
            "type": "region",
            "title": "Around here",
            "lat": BASE_LAT,
            "lng": BASE_LNG,
            "geometry_geojson": circle(),
        },
    )

    response = await client.patch(
        f"{SUGGESTIONS}/{created['id']}",
        json={"geometry_geojson": circle(lng=-1.0, lat=52.0, radius_m=5_000)},
    )

    assert response.json()["lat"] == pytest.approx(52.0)
    assert response.json()["lng"] == pytest.approx(-1.0)


# --- the move epsilon ----------------------------------------------------------------------------


async def test_a_five_metre_move_queues_no_distance_work(
    client: httpx.AsyncClient, db: AsyncSession, household: dict, monkeypatch
) -> None:
    """This is the Distance Matrix budget's only protection from a pin dragged a few pixels."""
    queued: list = []

    async def spy(db_, suggestion):
        queued.append(suggestion.id)

    await login_as(client, db, household["child"])
    created = await _create(client)
    monkeypatch.setattr(service, "queue_distance_recompute", spy)

    await client.patch(
        f"{SUGGESTIONS}/{created['id']}",
        json={"lat": north_of(BASE_LAT, 5), "lng": BASE_LNG},
    )

    assert queued == []


async def test_a_five_hundred_metre_move_queues_distance_work_and_broadcasts(
    client: httpx.AsyncClient, db: AsyncSession, household: dict, monkeypatch
) -> None:
    queued: list = []
    sent: list[str] = []

    async def spy(db_, suggestion):
        queued.append(suggestion.id)

    async def broadcast_spy(trip_id, type_, payload=None):
        sent.append(type_)
        return 0

    await login_as(client, db, household["child"])
    created = await _create(client)
    monkeypatch.setattr(service, "queue_distance_recompute", spy)
    monkeypatch.setattr("app.routers.suggestions.ws.broadcast", broadcast_spy)

    await client.patch(
        f"{SUGGESTIONS}/{created['id']}",
        json={"lat": north_of(BASE_LAT, 500), "lng": BASE_LNG},
    )

    assert len(queued) == 1
    assert sent == ["suggestion.updated", "suggestion.moved"]


async def test_creating_queues_distance_work(
    client: httpx.AsyncClient, db: AsyncSession, household: dict, monkeypatch
) -> None:
    queued: list = []

    async def spy(db_, suggestion):
        queued.append(suggestion.id)

    monkeypatch.setattr(service, "queue_distance_recompute", spy)
    await login_as(client, db, household["child"])
    await _create(client)

    assert len(queued) == 1


# --- status transitions ----------------------------------------------------------------------------


async def _with_status(db: AsyncSession, suggestion_id: str, status: str) -> None:
    """Set a status directly, for the transitions that no route can reach (`scheduled`)."""
    await db.execute(
        text("UPDATE suggestions SET status = :s WHERE id = :i"),
        {"s": status, "i": suggestion_id},
    )
    await db.commit()


@pytest.mark.parametrize(
    ("start", "target"),
    [
        ("proposed", "shortlisted"),
        ("proposed", "approved"),
        ("proposed", "rejected"),
        ("shortlisted", "approved"),
        ("shortlisted", "rejected"),
        ("shortlisted", "proposed"),
        ("approved", "shortlisted"),
        ("approved", "rejected"),
        ("approved", "proposed"),
        ("rejected", "proposed"),
    ],
)
async def test_every_allowed_transition_is_allowed(
    client: httpx.AsyncClient, db: AsyncSession, household: dict, start: str, target: str
) -> None:
    await login_as(client, db, household["child"])
    created = await _create(client)
    await _with_status(db, created["id"], start)

    await login_as(client, db, household["owner"])
    response = await client.patch(
        f"{SUGGESTIONS}/{created['id']}/status", json={"status": target}
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == target


@pytest.mark.parametrize(
    ("start", "target"),
    [
        ("rejected", "approved"),
        ("rejected", "shortlisted"),
        ("scheduled", "proposed"),
        ("scheduled", "rejected"),
        ("scheduled", "approved"),
    ],
)
async def test_every_forbidden_transition_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, household: dict, start: str, target: str
) -> None:
    """A scheduled suggestion has no move available here at all: the itinerary is the only
    thing that may take it back out, which is what stops the two features disagreeing about
    what is happening on Tuesday."""
    await login_as(client, db, household["child"])
    created = await _create(client)
    await _with_status(db, created["id"], start)

    await login_as(client, db, household["owner"])
    response = await client.patch(
        f"{SUGGESTIONS}/{created['id']}/status", json={"status": target}
    )

    assert response.status_code == 422
    assert code(response) == "invalid_transition"


async def test_scheduled_cannot_be_set_through_this_route_at_all(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    """`scheduled` is `itinerary-timeline`'s to set. It is not even in the accepted enum."""
    await login_as(client, db, household["child"])
    created = await _create(client)

    await login_as(client, db, household["owner"])
    response = await client.patch(
        f"{SUGGESTIONS}/{created['id']}/status", json={"status": "scheduled"}
    )

    assert response.status_code == 422


async def test_re_sending_the_current_status_is_a_no_op_not_an_error(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    """Two organisers pressing "shortlist" at once must not produce an error for the loser."""
    await login_as(client, db, household["child"])
    created = await _create(client)

    await login_as(client, db, household["owner"])
    response = await client.patch(
        f"{SUGGESTIONS}/{created['id']}/status", json={"status": "proposed"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "proposed"


@pytest.mark.parametrize("actor", ["child", "head", "spouse"])
async def test_only_an_organiser_changes_status(
    client: httpx.AsyncClient, db: AsyncSession, household: dict, actor: str
) -> None:
    """The one place a head or spouse has no more power than a member: confirming into the
    itinerary is a trip-level decision, not a family one."""
    await login_as(client, db, household["child"])
    created = await _create(client)

    await login_as(client, db, household[actor])
    response = await client.patch(
        f"{SUGGESTIONS}/{created['id']}/status", json={"status": "approved"}
    )

    assert response.status_code == 403


# --- deleting -----------------------------------------------------------------------------------------


async def test_the_author_deletes_their_own_and_its_thread(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    await login_as(client, db, household["child"])
    created = await _create(client)

    response = await client.delete(f"{SUGGESTIONS}/{created['id']}")

    assert response.status_code == 204
    assert (await db.scalar(select(Suggestion).where(Suggestion.id == created["id"]))) is None


async def test_a_scheduled_suggestion_cannot_be_deleted(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    """Deleting something already on the itinerary would remove a day's plan from under
    everybody. The organiser unschedules it first."""
    await login_as(client, db, household["child"])
    created = await _create(client)
    await _with_status(db, created["id"], "scheduled")

    response = await client.delete(f"{SUGGESTIONS}/{created['id']}")

    assert response.status_code == 409
    assert code(response) == "suggestion_scheduled"


async def test_a_stranger_cannot_delete(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    await login_as(client, db, household["child"])
    created = await _create(client)

    await login_as(client, db, household["stranger"])
    response = await client.delete(f"{SUGGESTIONS}/{created['id']}")

    assert response.status_code == 403


# --- the stage guard ------------------------------------------------------------------------------------


async def test_every_mutation_is_refused_in_the_end_stage_while_reads_still_work(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, household: dict
) -> None:
    """The End stage is read-only because every mutating route carries the guard — not because
    anything in the router mentions `end`."""
    await login_as(client, db, household["owner"])
    created = await _create(client)

    trip.stage = "end"
    await db.commit()

    assert (await client.get(SUGGESTIONS)).status_code == 200
    assert (await client.get(f"{SUGGESTIONS}/{created['id']}")).status_code == 200

    for response in (
        await client.post(SUGGESTIONS, json=ACCOMMODATION),
        await client.patch(f"{SUGGESTIONS}/{created['id']}", json={"title": "Nope"}),
        await client.patch(
            f"{SUGGESTIONS}/{created['id']}/status", json={"status": "approved"}
        ),
        await client.delete(f"{SUGGESTIONS}/{created['id']}"),
        await client.post(LINK_PREVIEW, json={"url": "https://example.com/"}),
    ):
        assert response.status_code == 409, response.text
        assert code(response) == "stage_forbidden"


async def test_suggestions_still_work_in_the_holiday_stage(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, household: dict
) -> None:
    """Unchanged in Holiday: people still propose things once the trip has started."""
    trip.stage = "holiday"
    await db.commit()
    await login_as(client, db, household["child"])

    assert (await client.post(SUGGESTIONS, json=ACCOMMODATION)).status_code == 201


# --- link preview ---------------------------------------------------------------------------------------


async def test_a_preview_that_resolves_returns_two_hundred(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    class _Fake:
        async def fetch(self, url: str):
            return LinkPreview(
                title="Home in Dent",
                facts="★4.8 · 5 bedrooms",
                locality="Dent, England, United Kingdom",
                lat=54.2831,
                lng=-2.4578,
                capacity=8,
            )

    app.dependency_overrides[get_link_preview_service] = lambda: _Fake()
    try:
        await login_as(client, db, household["child"])
        response = await client.post(
            LINK_PREVIEW, json={"url": "https://www.airbnb.co.uk/rooms/1"}
        )
    finally:
        app.dependency_overrides.pop(get_link_preview_service, None)

    assert response.status_code == 200
    assert response.json()["facts"] == "★4.8 · 5 bedrooms"
    assert response.json()["capacity"] == 8


async def test_no_preview_is_a_204_not_an_error(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    """Blocked, timed out, or refused by the SSRF guard — all of them are "the user types the
    title themselves", which is a normal outcome and not a failure to report."""

    class _Fake:
        async def fetch(self, url: str):
            return None

    app.dependency_overrides[get_link_preview_service] = lambda: _Fake()
    try:
        await login_as(client, db, household["child"])
        response = await client.post(LINK_PREVIEW, json={"url": "http://127.0.0.1/"})
    finally:
        app.dependency_overrides.pop(get_link_preview_service, None)

    assert response.status_code == 204
    assert response.content == b""


async def test_the_link_preview_needs_a_member(
    client: httpx.AsyncClient, db: AsyncSession, household: dict, outsider: User
) -> None:
    await login_as(client, db, outsider)
    response = await client.post(LINK_PREVIEW, json={"url": "https://example.com/"})
    assert response.status_code == 403


# --- the Places Terms of Service -------------------------------------------------------------------------


async def test_no_google_detail_field_is_ever_persisted(
    client: httpx.AsyncClient, db: AsyncSession, household: dict
) -> None:
    """Create with an inflated payload; confirm only `place_id` and user-authored fields land.

    This is a licensing obligation, not a preference: Google's Places Terms of Service forbid
    persisting Place Details content. `place_id` alone may be cached indefinitely.
    """
    await login_as(client, db, household["child"])
    inflated = {
        **ACCOMMODATION,
        "place_id": "ChIJ-the-only-google-value-we-keep",
        "place_snapshot": {"name": "The Barn", "address": "Dent, Cumbria"},
        "rating": 4.8,
        "user_ratings_total": 214,
        "photos": [{"photo_reference": "abc123"}],
        "opening_hours": {"open_now": True},
        "formatted_phone_number": "015396 00000",
        "website": "https://example.com/",
        "editorial_summary": "A lovely spot",
        "price_level": 3,
        "business_status": "OPERATIONAL",
        "reviews": [{"text": "Wonderful"}],
    }

    refused = await client.post(SUGGESTIONS, json=inflated)
    # `extra="forbid"` on the request model: the payload is refused outright rather than
    # silently trimmed, so a client sending Google's response is told to stop.
    assert refused.status_code == 422

    permitted = {
        **ACCOMMODATION,
        "place_id": "ChIJ-the-only-google-value-we-keep",
        "place_snapshot": {"name": "The Barn", "address": "Dent, Cumbria"},
    }
    created = await _create(client, permitted)

    row = await db.scalar(select(Suggestion).where(Suggestion.id == created["id"]))
    assert row.place_id == "ChIJ-the-only-google-value-we-keep"
    # The snapshot is the two user-authored fields and nothing else.
    assert row.place_snapshot_json == {"name": "The Barn", "address": "Dent, Cumbria"}

    stored = " ".join(
        str(getattr(row, column.name)) for column in Suggestion.__table__.columns
    )
    for smuggled in ("4.8", "214", "abc123", "open_now", "015396", "OPERATIONAL", "Wonderful"):
        assert smuggled not in stored


async def test_the_suggestions_table_has_no_column_for_a_google_detail(
    db: AsyncSession,
) -> None:
    """A guard against the column being *added*: the ToS violation would be a schema change
    nobody flagged, so the schema is what the test reads."""
    columns = {column.name for column in Suggestion.__table__.columns}
    forbidden = {
        "photos",
        "photo_reference",
        "photo_references",
        "rating",
        "user_ratings_total",
        "reviews",
        "opening_hours",
        "formatted_phone_number",
        "phone_number",
        "website",
        "editorial_summary",
        "price_level",
        "business_status",
    }
    assert not (columns & forbidden)
    # And exactly one Google-derived value survives.
    assert "place_id" in columns


async def test_no_server_route_returns_google_place_details() -> None:
    """"There is no server endpoint that returns Google place details" (`design.md`).

    Asserted against the generated OpenAPI schema rather than against the source, so a route
    added later — in this feature or another — is covered by the same test.
    """
    spec = app.openapi()
    forbidden = {"rating", "photos", "opening_hours", "editorial_summary", "price_level"}
    for name, schema in spec["components"]["schemas"].items():
        if "Suggestion" in name or "Place" in name:
            assert not (set(schema.get("properties", {})) & forbidden), name
