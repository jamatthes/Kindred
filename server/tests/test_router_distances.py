"""The distance routes, the triggers, and the render-path enforcement.

**`test_no_render_path_ever_calls_google` is the enforcement of the hard invariant** at the
HTTP level, complementing the import-graph check in `tests/test_service_distances_read.py`: it
drives every read endpoint in the product against a Distance Matrix client that fails the test
if it is called at all.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DistanceCache, Family, Suggestion, Trip, TripOrganiser, User
from app.services import distance_tasks as tasks
from tests.conftest import add_member, login_as, make_family, make_user
from tests.test_service_distances_write import FakeMatrix

DISTANCES = "/api/v1/distances"
SUGGESTIONS = "/api/v1/suggestions"

LONDON = (51.5074, -0.1278)
PARIS = (48.8566, 2.3522)


def code(response: httpx.Response) -> str:
    return response.json()["detail"]["code"]


class ExplodingMatrix:
    """A Distance Matrix client that fails the test if anything calls it.

    Used to assert the hard invariant, so its failure message says what the invariant is.
    """

    def _never(self) -> None:
        raise AssertionError(
            "a render path called Distance Matrix — see the HARD INVARIANT in "
            "plan/features/distances/design.md"
        )

    async def get_distances_many_to_one(self, *a, **k):
        self._never()

    async def get_distances_one_to_many(self, *a, **k):
        self._never()

    async def get_distances_pairwise(self, *a, **k):
        self._never()


@pytest.fixture
async def crew(db: AsyncSession, trip: Trip) -> dict:
    owner = await make_user(db, "distowner")
    owners = await make_family(db, trip, "Owners", color=1)
    await add_member(db, owners, owner, role="head")
    owners.home_lat, owners.home_lng = LONDON
    owners.geocode_status = "ok"

    member = await make_user(db, "distmember")
    theirs = await make_family(db, trip, "Members", color=2)
    await add_member(db, theirs, member, role="head")
    theirs.home_lat, theirs.home_lng = (53.4808, -2.2426)  # Manchester
    theirs.geocode_status = "ok"

    trip.owner_user_id = owner.id
    await db.commit()
    await db.refresh(owners)
    await db.refresh(theirs)
    return {"owner": owner, "member": member, "owner_family": owners, "family": theirs}


async def _suggestion(db: AsyncSession, trip: Trip, author: User) -> Suggestion:
    suggestion = Suggestion(
        trip_id=trip.id,
        type="accommodation",
        title="The Barn",
        status="proposed",
        created_by=author.id,
        lat=PARIS[0],
        lng=PARIS[1],
    )
    db.add(suggestion)
    await db.commit()
    await db.refresh(suggestion)
    return suggestion


# --- THE HARD INVARIANT -----------------------------------------------------------------------


async def test_no_render_path_ever_calls_google(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict, monkeypatch
) -> None:
    """**This test is the enforcement of the hard invariant.**

    `design.md`: "A request serving a page, a list, a card, or a panel **never** calls Distance
    Matrix. It reads `distance_cache`, and falls back to a haversine value computed in SQL."

    Every read endpoint that renders a distance is driven here against a client that raises on
    any call. If this fails, the fix is never to relax the assertion — it is to move whatever
    needs Google into `app/services/distance_tasks.py`, which runs from background tasks alone.
    """
    monkeypatch.setattr(tasks, "_default_service", lambda: ExplodingMatrix())
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["member"])

    for response in (
        await client.get(SUGGESTIONS),
        await client.get(f"{SUGGESTIONS}/{suggestion.id}"),
        await client.get(f"{SUGGESTIONS}/{suggestion.id}/distances"),
        await client.get(DISTANCES),
        await client.get(DISTANCES, params={"family_id": str(crew["family"].id)}),
        await client.get(DISTANCES, params={"suggestion_ids": str(suggestion.id)}),
    ):
        assert response.status_code == 200, response.text


# --- reading -----------------------------------------------------------------------------------


async def test_a_new_suggestion_reads_as_estimates_for_every_family(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["member"])

    body = (await client.get(f"{SUGGESTIONS}/{suggestion.id}/distances")).json()

    assert body["suggestion_id"] == str(suggestion.id)
    assert len(body["distances"]) == 2
    assert all(d["is_estimate"] for d in body["distances"])
    assert all(d["duration_s"] is None for d in body["distances"])
    assert all(d["distance_m"] > 0 for d in body["distances"])


async def test_the_callers_own_family_is_first(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["member"])

    body = (await client.get(f"{SUGGESTIONS}/{suggestion.id}/distances")).json()

    assert body["distances"][0]["family_id"] == str(crew["family"].id)


async def test_a_computed_pair_reads_as_a_real_value(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    suggestion = await _suggestion(db, trip, crew["owner"])
    await tasks.queue_for_suggestion(db, trip, suggestion, service=FakeMatrix())
    await login_as(client, db, crew["member"])

    body = (await client.get(f"{SUGGESTIONS}/{suggestion.id}/distances")).json()

    assert all(d["status"] == "ok" for d in body["distances"])
    assert all(d["is_estimate"] is False for d in body["distances"])
    assert all(d["duration_s"] == 17_400 for d in body["distances"])


async def test_a_family_without_a_home_reads_as_no_home(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    nomads = await make_family(db, trip, "Nomads", color=3)
    await db.commit()
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["member"])

    body = (await client.get(f"{SUGGESTIONS}/{suggestion.id}/distances")).json()

    theirs = next(d for d in body["distances"] if d["family_id"] == str(nomads.id))
    assert theirs["status"] == "no_home"
    assert theirs["distance_m"] is None


async def test_the_bulk_form_serves_the_whole_list_in_one_request(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    first = await _suggestion(db, trip, crew["owner"])
    second = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["member"])

    body = (await client.get(DISTANCES)).json()["distances"]

    assert set(body) == {str(first.id), str(second.id)}
    assert len(body[str(first.id)]) == 2


async def test_the_bulk_form_narrows_to_one_familys_perspective(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """What switching the list's sort perspective refetches, without re-requesting every
    suggestion to get it."""
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["member"])

    body = (
        await client.get(DISTANCES, params={"family_id": str(crew["owner_family"].id)})
    ).json()["distances"]

    assert [d["family_id"] for d in body[str(suggestion.id)]] == [
        str(crew["owner_family"].id)
    ]


async def test_every_member_may_read_every_familys_distances(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """Distances are not private: the whole point of the panel's expander is comparing whose
    journey is longest."""
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["member"])

    body = (await client.get(f"{SUGGESTIONS}/{suggestion.id}/distances")).json()

    assert {d["family_id"] for d in body["distances"]} == {
        str(crew["family"].id),
        str(crew["owner_family"].id),
    }


async def test_an_outsider_cannot_read_distances(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict, outsider: User
) -> None:
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, outsider)

    assert (await client.get(f"{SUGGESTIONS}/{suggestion.id}/distances")).status_code == 403


async def test_a_suggestion_from_another_trip_is_a_404(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    await login_as(client, db, crew["member"])
    response = await client.get(
        f"{SUGGESTIONS}/00000000-0000-0000-0000-000000000000/distances"
    )
    assert response.status_code == 404


# --- the embedded array on the suggestion list -----------------------------------------------------


async def test_the_suggestion_list_embeds_the_callers_own_distance(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """`GET /suggestions` embeds distances so the list renders in one request — the reason the
    bulk endpoint exists only for the refetch case."""
    await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["member"])

    row = (await client.get(SUGGESTIONS)).json()[0]

    assert len(row["distances"]) == 1
    assert row["distances"][0]["family_id"] == str(crew["family"].id)
    assert row["distances"][0]["is_estimate"] is True


# --- the triggers -------------------------------------------------------------------------------------


async def test_creating_a_suggestion_queues_one_call(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict, monkeypatch
) -> None:
    matrix = FakeMatrix()
    monkeypatch.setattr(tasks, "_default_service", lambda: matrix)
    await login_as(client, db, crew["member"])

    await client.post(
        SUGGESTIONS,
        json={"type": "activity", "title": "Surfing", "lat": PARIS[0], "lng": PARIS[1]},
    )

    assert matrix.calls == 1
    assert len((await db.scalars(select(DistanceCache))).unique().all()) == 2


async def test_a_five_metre_move_queues_nothing(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict, monkeypatch
) -> None:
    """Shared with `map-suggestions`, which owns the epsilon check. This is the Distance Matrix
    budget's only protection from a pin dragged a few pixels."""
    matrix = FakeMatrix()
    monkeypatch.setattr(tasks, "_default_service", lambda: matrix)
    await login_as(client, db, crew["member"])
    created = (
        await client.post(
            SUGGESTIONS,
            json={"type": "activity", "title": "Surfing", "lat": PARIS[0], "lng": PARIS[1]},
        )
    ).json()
    calls_after_create = matrix.calls

    await client.patch(
        f"{SUGGESTIONS}/{created['id']}",
        json={"lat": PARIS[0] + 0.000045, "lng": PARIS[1]},  # about five metres
    )

    assert matrix.calls == calls_after_create


async def test_a_five_hundred_metre_move_queues_one_call(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict, monkeypatch
) -> None:
    matrix = FakeMatrix()
    monkeypatch.setattr(tasks, "_default_service", lambda: matrix)
    await login_as(client, db, crew["member"])
    created = (
        await client.post(
            SUGGESTIONS,
            json={"type": "activity", "title": "Surfing", "lat": PARIS[0], "lng": PARIS[1]},
        )
    ).json()
    calls_after_create = matrix.calls

    await client.patch(
        f"{SUGGESTIONS}/{created['id']}",
        json={"lat": PARIS[0] + 0.0045, "lng": PARIS[1]},  # about 500 metres
    )

    assert matrix.calls == calls_after_create + 1


async def test_setting_a_family_home_queues_that_familys_pairs(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    crew: dict,
    geocoder,
    monkeypatch,
) -> None:
    """The home-change trigger: a family that just got coordinates has every pair backfilled."""
    from app.services.google import GeocodeResult

    geocoder.results["1 test street"] = GeocodeResult(
        lat=52.4862, lng=-1.8904, formatted_address="1 Test Street", locality="Birmingham"
    )
    matrix = FakeMatrix()
    monkeypatch.setattr(tasks, "_default_service", lambda: matrix)
    nomads = await make_family(db, trip, "Nomads", color=3)
    newcomer = await make_user(db, "newcomer")
    await add_member(db, nomads, newcomer, role="head")
    await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, newcomer)

    response = await client.put(
        f"/api/v1/families/{nomads.id}/home", json={"home_address": "1 Test Street"}
    )

    assert response.status_code == 200, response.text
    assert matrix.one_to_many_calls, "a geocoded home backfills that family's pairs"


# --- the force-recompute ------------------------------------------------------------------------------------


async def test_recompute_states_the_cost_before_doing_the_work(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict, monkeypatch
) -> None:
    """An organiser deserves the real number — about one call per suggestion, not one per
    pair — before pressing the button."""
    matrix = FakeMatrix()
    monkeypatch.setattr(tasks, "_default_service", lambda: matrix)
    for _ in range(4):
        await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["owner"])

    body = (await client.post(f"{DISTANCES}/recompute", json={})).json()

    assert body["queued_pairs"] == 8  # two families x four suggestions
    assert body["estimated_api_calls"] == 4


async def test_recompute_revisits_a_settled_no_route(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict, monkeypatch
) -> None:
    """The only path that does. Everything else leaves a `no_route` alone forever, which is
    what stops the cache re-asking Google about a pair that will never resolve."""
    suggestion = await _suggestion(db, trip, crew["owner"])
    await tasks.queue_for_suggestion(
        db, trip, suggestion, service=FakeMatrix(status="zero_results")
    )
    matrix = FakeMatrix()
    monkeypatch.setattr(tasks, "_default_service", lambda: matrix)
    await login_as(client, db, crew["owner"])

    await client.post(f"{DISTANCES}/recompute", json={"suggestion_id": str(suggestion.id)})

    rows = (await db.scalars(select(DistanceCache))).unique().all()
    for row in rows:
        await db.refresh(row)
    assert {r.status for r in rows} == {"ok"}


async def test_a_member_cannot_force_a_recompute(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """It spends money, so it is the one route here behind `require_organiser`."""
    await login_as(client, db, crew["member"])

    response = await client.post(f"{DISTANCES}/recompute", json={})

    assert response.status_code == 403


async def test_an_appointed_organiser_may_force_a_recompute(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict, monkeypatch
) -> None:
    monkeypatch.setattr(tasks, "_default_service", lambda: FakeMatrix())
    db.add(TripOrganiser(trip_id=trip.id, user_id=crew["member"].id))
    await db.commit()
    await login_as(client, db, crew["member"])

    assert (await client.post(f"{DISTANCES}/recompute", json={})).status_code == 200


# --- the stage guard -----------------------------------------------------------------------------------------


async def test_the_end_stage_freezes_recompute_but_not_reading(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """Point 4 of the hard invariant: no external call is made in End, force-recompute
    included. Reads keep working, because the archive keeps its numbers."""
    suggestion = await _suggestion(db, trip, crew["owner"])
    trip.stage = "end"
    await db.commit()
    await login_as(client, db, crew["owner"])

    assert (
        await client.get(f"{SUGGESTIONS}/{suggestion.id}/distances")
    ).status_code == 200
    assert (await client.get(DISTANCES)).status_code == 200

    response = await client.post(f"{DISTANCES}/recompute", json={})
    assert response.status_code == 409
    assert code(response) == "stage_forbidden"
