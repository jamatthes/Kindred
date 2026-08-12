"""`POST /polls/{id}/decision/seed-region` — the poll → map hand-off (PL-14).

The route is owned by `polls`, which shipped it at M2 returning `501 not_available`, and
implemented by `map-suggestions` at M3 (`plan/features/map-suggestions/tasks.md` Phase 11b).
This file is the M3 half: the real create, the idempotence, the two refusals, and the
`ON DELETE SET NULL` that keeps the poll's decision banner from linking to a region somebody
deleted.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Suggestion, Trip, TripCategorySetting, User
from tests.conftest import add_member, login_as, make_family, make_user

POLLS = "/api/v1/polls"
SUGGESTIONS = "/api/v1/suggestions"


def code(response: httpx.Response) -> str:
    return response.json()["detail"]["code"]


DESTINATIONS = {
    "title": "Where shall we go?",
    "kind": "score_matrix",
    "options": [
        {"label": "Cornwall", "lat": 50.2660, "lng": -5.0527},
        {"label": "Somerset"},
    ],
}


@pytest.fixture
async def owner(db: AsyncSession, trip: Trip) -> User:
    user = await make_user(db, "seedowner")
    family = await make_family(db, trip, "Owners", color=1)
    await add_member(db, family, user, role="head")
    trip.owner_user_id = user.id
    db.add(TripCategorySetting(trip_id=trip.id, category="poll", voting_mode="score"))
    await db.commit()
    return user


async def _decided_poll(client: httpx.AsyncClient, *, option: int = 0) -> dict:
    poll = (await client.post(POLLS, json=DESTINATIONS)).json()
    chosen = poll["options"][option]
    await client.put(f"{POLLS}/{poll['id']}/decision", json={"option_id": chosen["id"]})
    return poll


# --- the happy path ---------------------------------------------------------------------------


async def test_the_seed_action_is_offered_now_that_map_suggestions_has_shipped(
    client: httpx.AsyncClient, db: AsyncSession, owner: User
) -> None:
    """`can_seed_region` was false at M2 and the button was never rendered. The capability
    check flipped by itself when `app.services.suggestions` came into existence."""
    await login_as(client, db, owner)
    poll = await _decided_poll(client)

    detail = (await client.get(f"{POLLS}/{poll['id']}")).json()

    assert detail["can_seed_region"] is True


async def test_seeding_creates_a_region_and_links_the_option_to_it(
    client: httpx.AsyncClient, db: AsyncSession, owner: User
) -> None:
    await login_as(client, db, owner)
    poll = await _decided_poll(client)

    response = await client.post(f"{POLLS}/{poll['id']}/decision/seed-region")

    assert response.status_code == 200, response.text
    suggestion_id = response.json()["suggestion_id"]

    # It is an ordinary region: same list, same rendering path, same everything.
    listed = (await client.get(SUGGESTIONS)).json()
    assert [row["id"] for row in listed] == [suggestion_id]
    assert listed[0]["type"] == "region"
    assert listed[0]["title"] == "Cornwall"
    assert listed[0]["status"] == "proposed"
    assert listed[0]["lat"] == pytest.approx(50.2660)

    # And the poll option now links to it, which is what the decision banner renders.
    detail = (await client.get(f"{POLLS}/{poll['id']}")).json()
    assert detail["options"][0]["suggestion_id"] == suggestion_id


async def test_seeding_broadcasts_the_new_region(
    client: httpx.AsyncClient, db: AsyncSession, owner: User, monkeypatch
) -> None:
    """A member with the map open watches the region appear, without a refresh."""
    sent: list[str] = []

    async def spy(trip_id, type_, payload=None):
        sent.append(type_)
        return 0

    await login_as(client, db, owner)
    poll = await _decided_poll(client)
    monkeypatch.setattr("app.routers.polls.ws.broadcast", spy)

    await client.post(f"{POLLS}/{poll['id']}/decision/seed-region")

    assert "suggestion.created" in sent


async def test_a_second_call_returns_the_same_region(
    client: httpx.AsyncClient, db: AsyncSession, owner: User, monkeypatch
) -> None:
    """The button becomes a link once pressed, so a double-click — or two organisers at once —
    must not produce a second overlapping region nobody asked for."""
    sent: list[str] = []

    async def spy(trip_id, type_, payload=None):
        sent.append(type_)
        return 0

    await login_as(client, db, owner)
    poll = await _decided_poll(client)
    monkeypatch.setattr("app.routers.polls.ws.broadcast", spy)

    first = (await client.post(f"{POLLS}/{poll['id']}/decision/seed-region")).json()
    second = (await client.post(f"{POLLS}/{poll['id']}/decision/seed-region")).json()

    assert first == second
    assert await db.scalar(select(func.count()).select_from(Suggestion)) == 1
    # The second call announces nothing: nothing happened.
    assert sent.count("suggestion.created") == 1


# --- the refusals -------------------------------------------------------------------------------


async def test_an_undecided_poll_is_a_409(
    client: httpx.AsyncClient, db: AsyncSession, owner: User
) -> None:
    await login_as(client, db, owner)
    poll = (await client.post(POLLS, json=DESTINATIONS)).json()

    response = await client.post(f"{POLLS}/{poll['id']}/decision/seed-region")

    assert response.status_code == 409
    assert code(response) == "no_decision"


async def test_a_non_geographic_option_is_a_422(
    client: httpx.AsyncClient, db: AsyncSession, owner: User
) -> None:
    """"Somerset" was added without coordinates. The request is well-formed and the poll is in
    the right state — the *option* is what cannot be honoured, so it is a `422` rather than a
    conflict."""
    await login_as(client, db, owner)
    poll = await _decided_poll(client, option=1)

    response = await client.post(f"{POLLS}/{poll['id']}/decision/seed-region")

    assert response.status_code == 422
    assert code(response) == "option_not_located"


async def test_only_an_organiser_may_seed(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, owner: User
) -> None:
    await login_as(client, db, owner)
    poll = await _decided_poll(client)

    plain = await make_user(db, "plainvoter")
    family = await make_family(db, trip, "Voters", color=2)
    await add_member(db, family, plain, role="head")
    await login_as(client, db, plain)

    response = await client.post(f"{POLLS}/{poll['id']}/decision/seed-region")

    assert response.status_code == 403


async def test_seeding_is_refused_in_the_end_stage(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, owner: User
) -> None:
    await login_as(client, db, owner)
    poll = await _decided_poll(client)
    trip.stage = "end"
    await db.commit()

    response = await client.post(f"{POLLS}/{poll['id']}/decision/seed-region")

    assert response.status_code == 409
    assert code(response) == "stage_forbidden"


# --- the deferred foreign key -----------------------------------------------------------------------


async def test_deleting_the_region_clears_the_polls_link_to_it(
    client: httpx.AsyncClient, db: AsyncSession, owner: User
) -> None:
    """The constraint `polls` deferred at M2 and `map-suggestions` added at M3:
    `poll_options.suggestion_id -> suggestions.id ON DELETE SET NULL`. Without it the decision
    banner would keep linking to a region that no longer exists."""
    await login_as(client, db, owner)
    poll = await _decided_poll(client)
    seeded = (await client.post(f"{POLLS}/{poll['id']}/decision/seed-region")).json()

    assert (await client.delete(f"{SUGGESTIONS}/{seeded['suggestion_id']}")).status_code == 204

    detail = (await client.get(f"{POLLS}/{poll['id']}")).json()
    assert detail["options"][0]["suggestion_id"] is None
    assert detail["can_seed_region"] is True  # and it can be seeded again
