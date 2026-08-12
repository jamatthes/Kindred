"""The poll routes: happy path, permission-denied, and the stage guard.

The permission tests matter more than usual here. Polls is the one feature where family
heads and spouses have **no** elevated rights — their role governs their family's membership
and home address, not group decisions — and that is easy to get wrong by pattern-matching on
`families`.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, Family, Poll, PollOption, PollScore, Trip, TripCategorySetting, User
from tests.conftest import add_member, login_as, make_family, make_user

POLLS = "/api/v1/polls"
pytestmark = pytest.mark.asyncio


def code(response: httpx.Response) -> str:
    return response.json()["detail"]["code"]


@pytest.fixture
async def household(db: AsyncSession, trip: Trip) -> tuple[User, User, User]:
    """An owner, a head of family with no trip-level role, and a plain member."""
    owner = await make_user(db, "pollowner")
    head = await make_user(db, "pollhead")
    plain = await make_user(db, "pollmember")

    owners = await make_family(db, trip, "Owners", color=1)
    await add_member(db, owners, owner, role="head")
    family = await make_family(db, trip, "Voters", color=2)
    await add_member(db, family, head, role="head")
    await add_member(db, family, plain, role="member")

    trip.owner_user_id = owner.id
    db.add(TripCategorySetting(trip_id=trip.id, category="poll", voting_mode="score"))
    await db.commit()
    return owner, head, plain


DESTINATIONS = {
    "title": "Where shall we go?",
    "kind": "score_matrix",
    "allow_member_options": False,
    "options": [
        {"label": "York", "lat": 53.9600, "lng": -1.0873},
        {"label": "Cornwall", "lat": 50.2660, "lng": -5.0527},
        {"label": "Somerset"},
    ],
}


async def _create(client: httpx.AsyncClient, body: dict | None = None) -> dict:
    response = await client.post(POLLS, json=body or DESTINATIONS)
    assert response.status_code == 201, response.text
    return response.json()


# --- creating ------------------------------------------------------------------------------------


async def test_an_organiser_creates_a_poll_with_located_options(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, _ = household
    await login_as(client, db, owner)
    poll = await _create(client)

    assert poll["title"] == "Where shall we go?"
    assert poll["status"] == "open"
    assert poll["option_count"] == 3
    assert [o["label"] for o in poll["options"]] == ["York", "Cornwall", "Somerset"]
    assert poll["options"][1]["lat"] == pytest.approx(50.2660)
    # An option with no coordinates is kept, not dropped — it is simply not on the map.
    assert poll["options"][2]["lat"] is None


async def test_the_voting_mode_comes_from_the_trip_not_the_poll(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, household: tuple[User, User, User]
) -> None:
    owner, _, _ = household
    row = await db.scalar(
        select(TripCategorySetting).where(TripCategorySetting.category == "poll")
    )
    row.voting_mode = "thumbs"
    await db.commit()

    await login_as(client, db, owner)
    assert (await _create(client))["voting_mode"] == "thumbs"


async def test_a_member_cannot_create_a_poll(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    _, _, plain = household
    await login_as(client, db, plain)
    assert (await client.post(POLLS, json=DESTINATIONS)).status_code == 403


async def test_a_head_of_family_has_no_elevated_rights_in_polls(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    """Their role governs their family's membership and home address, not group decisions."""
    _, head, _ = household
    await login_as(client, db, head)
    assert (await client.post(POLLS, json=DESTINATIONS)).status_code == 403


async def test_an_options_poll_needs_two_options(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, _ = household
    await login_as(client, db, owner)
    response = await client.post(
        POLLS,
        json={"title": "How long?", "kind": "options", "options": [{"label": "5 days"}]},
    )
    assert response.status_code == 422


# --- reading -------------------------------------------------------------------------------------


async def test_every_member_can_read_polls(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    await _create(client)

    await login_as(client, db, plain)
    listing = (await client.get(POLLS)).json()
    assert len(listing) == 1
    assert listing[0]["my_completion"] == "none"
    assert listing[0]["group_completion"]["total"] == 3


async def test_polls_needing_my_attention_come_first(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    """PL-16 — the ordering is a fact about the reader."""
    owner, _, plain = household
    await login_as(client, db, owner)
    first = await _create(client)
    second = await _create(client, {**DESTINATIONS, "title": "What shall we do?"})

    # The owner completes the first, so the second should surface above it for them.
    await client.put(
        f"{POLLS}/{first['id']}/scores",
        json={"scores": [{"option_id": o["id"], "score": 7} for o in first["options"]]},
    )
    listing = (await client.get(POLLS)).json()
    assert listing[0]["id"] == second["id"]
    assert listing[0]["my_completion"] == "none"
    assert listing[1]["my_completion"] == "complete"


async def test_reading_an_unknown_poll_is_a_404(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    import uuid

    owner, _, _ = household
    await login_as(client, db, owner)
    assert (await client.get(f"{POLLS}/{uuid.uuid4()}")).status_code == 404


async def test_polls_are_not_public(client: httpx.AsyncClient) -> None:
    assert (await client.get(POLLS)).status_code == 401


# --- scoring -------------------------------------------------------------------------------------


async def test_scoring_returns_the_recomputed_results(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client)
    york, cornwall = poll["options"][0], poll["options"][1]

    await login_as(client, db, plain)
    results = (
        await client.put(
            f"{POLLS}/{poll['id']}/scores",
            json={
                "scores": [
                    {"option_id": york["id"], "score": 4},
                    {"option_id": cornwall["id"], "score": 9},
                ]
            },
        )
    ).json()

    by_id = {o["option_id"]: o for o in results["options"]}
    assert by_id[cornwall["id"]]["average"] == 9.0
    assert by_id[cornwall["id"]]["rank"] == 1
    # Not scored by anyone: null, never 0.0.
    assert by_id[poll["options"][2]["id"]]["average"] is None
    # All three are outstanding: two have not started, and the scorer is *partial* — they
    # left Somerset unscored, and PL-9 counts partly-done as still needing a nudge.
    assert results["non_responders"]["count"] == 3
    assert results["non_responders"]["total"] == 3
    outstanding = {u["user_id"]: u["completion"] for u in results["non_responders"]["users"]}
    assert outstanding[str(plain.id)] == "partial"
    assert "Cornwall leads" in results["insight"]


async def test_a_partial_response_is_partial(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client)

    await login_as(client, db, plain)
    results = (
        await client.put(
            f"{POLLS}/{poll['id']}/scores",
            json={"scores": [{"option_id": poll["options"][0]["id"], "score": 5}]},
        )
    ).json()
    mine = next(m for m in results["members"] if m["user_id"] == str(plain.id))
    assert mine["completion"] == "partial"


async def test_changing_a_score_replaces_it(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client)
    option = poll["options"][0]

    await login_as(client, db, plain)
    for score in (3, 9):
        results = (
            await client.put(
                f"{POLLS}/{poll['id']}/scores",
                json={"scores": [{"option_id": option["id"], "score": score}]},
            )
        ).json()
    assert next(o for o in results["options"] if o["option_id"] == option["id"])["average"] == 9.0
    assert await db.scalar(select(func.count()).select_from(PollScore)) == 1


async def test_clearing_a_score_removes_it(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client)
    option = poll["options"][0]

    await login_as(client, db, plain)
    await client.put(
        f"{POLLS}/{poll['id']}/scores",
        json={"scores": [{"option_id": option["id"], "score": 5}]},
    )
    results = (await client.delete(f"{POLLS}/{poll['id']}/scores/{option['id']}")).json()
    assert next(o for o in results["options"] if o["option_id"] == option["id"])["average"] is None


async def test_a_score_out_of_range_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, _ = household
    await login_as(client, db, owner)
    poll = await _create(client)
    response = await client.put(
        f"{POLLS}/{poll['id']}/scores",
        json={"scores": [{"option_id": poll["options"][0]["id"], "score": 11}]},
    )
    assert response.status_code == 422


async def test_scoring_a_closed_poll_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client)
    await client.post(f"{POLLS}/{poll['id']}/close", json={"confirm": True})

    await login_as(client, db, plain)
    response = await client.put(
        f"{POLLS}/{poll['id']}/scores",
        json={"scores": [{"option_id": poll["options"][0]["id"], "score": 5}]},
    )
    assert response.status_code == 409
    assert code(response) == "poll_closed"


async def test_a_thumb_in_score_mode_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, _ = household
    await login_as(client, db, owner)
    poll = await _create(client)
    response = await client.put(
        f"{POLLS}/{poll['id']}/scores",
        json={"scores": [{"option_id": poll["options"][0]["id"], "thumb": "up"}]},
    )
    assert response.status_code == 422
    assert code(response) == "wrong_voting_mode"


# --- options ---------------------------------------------------------------------------------------


async def test_a_member_cannot_add_an_option_when_it_is_not_allowed(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client)

    await login_as(client, db, plain)
    response = await client.post(
        f"{POLLS}/{poll['id']}/options", json={"label": "Northumberland"}
    )
    assert response.status_code == 403
    assert code(response) == "member_options_disabled"


async def test_a_member_may_add_an_option_when_it_is_allowed(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client, {**DESTINATIONS, "allow_member_options": True})

    await login_as(client, db, plain)
    response = await client.post(
        f"{POLLS}/{poll['id']}/options", json={"label": "Northumberland"}
    )
    assert response.status_code == 201
    assert response.json()["label"] == "Northumberland"
    # Their own, unscored: they may take it back.
    assert response.json()["can_delete"] is True


async def test_a_member_can_delete_their_own_unscored_option(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client, {**DESTINATIONS, "allow_member_options": True})

    await login_as(client, db, plain)
    option = (
        await client.post(f"{POLLS}/{poll['id']}/options", json={"label": "Mine"})
    ).json()
    assert (
        await client.delete(f"{POLLS}/{poll['id']}/options/{option['id']}")
    ).status_code == 204


async def test_a_member_cannot_delete_an_option_somebody_else_scored(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client, {**DESTINATIONS, "allow_member_options": True})

    await login_as(client, db, plain)
    option = (
        await client.post(f"{POLLS}/{poll['id']}/options", json={"label": "Mine"})
    ).json()

    await login_as(client, db, owner)
    await client.put(
        f"{POLLS}/{poll['id']}/scores",
        json={"scores": [{"option_id": option["id"], "score": 6}]},
    )

    await login_as(client, db, plain)
    response = await client.delete(f"{POLLS}/{poll['id']}/options/{option['id']}")
    assert response.status_code == 409
    assert code(response) == "option_has_scores"


async def test_an_organiser_can_always_delete_an_option(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client)
    option = poll["options"][0]
    await client.put(
        f"{POLLS}/{poll['id']}/scores",
        json={"scores": [{"option_id": option["id"], "score": 6}]},
    )

    assert (
        await client.delete(f"{POLLS}/{poll['id']}/options/{option['id']}")
    ).status_code == 204
    # The scores go with it — which is why the UI's confirm names how many will be lost.
    assert await db.scalar(select(func.count()).select_from(PollScore)) == 0


async def test_a_member_cannot_delete_somebody_elses_option(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client, {**DESTINATIONS, "allow_member_options": True})

    await login_as(client, db, plain)
    response = await client.delete(f"{POLLS}/{poll['id']}/options/{poll['options'][0]['id']}")
    assert response.status_code == 403


# --- close, reopen, decide -----------------------------------------------------------------------------


async def test_closing_and_reopening(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, _ = household
    await login_as(client, db, owner)
    poll = await _create(client)

    closed = (await client.post(f"{POLLS}/{poll['id']}/close", json={"confirm": True})).json()
    assert closed["status"] == "closed" and closed["closed_at"] is not None

    reopened = (await client.post(f"{POLLS}/{poll['id']}/reopen")).json()
    assert reopened["status"] == "open" and reopened["closed_at"] is None


async def test_a_member_cannot_close_a_poll(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client)

    await login_as(client, db, plain)
    assert (
        await client.post(f"{POLLS}/{poll['id']}/close", json={"confirm": True})
    ).status_code == 403


async def test_recording_and_clearing_a_decision(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, _ = household
    await login_as(client, db, owner)
    poll = await _create(client)
    cornwall = poll["options"][1]

    decided = (
        await client.put(f"{POLLS}/{poll['id']}/decision", json={"option_id": cornwall["id"]})
    ).json()
    assert decided["decision"]["label"] == "Cornwall"
    assert decided["decided_at"] is not None

    cleared = (await client.delete(f"{POLLS}/{poll['id']}/decision")).json()
    assert cleared["decision"] is None


async def test_the_winner_need_not_be_the_leader(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    """PL-13: the group may decide otherwise, and the record reflects what was decided."""
    owner, _, _ = household
    await login_as(client, db, owner)
    poll = await _create(client)
    york, cornwall = poll["options"][0], poll["options"][1]
    await client.put(
        f"{POLLS}/{poll['id']}/scores",
        json={
            "scores": [
                {"option_id": york["id"], "score": 2},
                {"option_id": cornwall["id"], "score": 10},
            ]
        },
    )
    decided = (
        await client.put(f"{POLLS}/{poll['id']}/decision", json={"option_id": york["id"]})
    ).json()
    assert decided["decision"]["label"] == "York"


async def test_deleting_the_decided_option_clears_the_decision(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, _ = household
    await login_as(client, db, owner)
    poll = await _create(client)
    cornwall = poll["options"][1]
    await client.put(f"{POLLS}/{poll['id']}/decision", json={"option_id": cornwall["id"]})
    await client.delete(f"{POLLS}/{poll['id']}/options/{cornwall['id']}")

    assert (await client.get(f"{POLLS}/{poll['id']}")).json()["decision"] is None


async def test_the_seed_region_action_is_offered_for_a_located_decision(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    """Was `test_seeding_a_region_is_not_available_at_m2` until `map-suggestions` shipped: the
    capability check probes for `app.services.suggestions`, so implementing that module turned
    the action on without an edit here. The route's own behaviour is covered in
    `tests/test_seed_region.py`, which belongs to `map-suggestions`.
    """
    owner, _, _ = household
    await login_as(client, db, owner)
    poll = await _create(client)
    cornwall = poll["options"][1]
    await client.put(f"{POLLS}/{poll['id']}/decision", json={"option_id": cornwall["id"]})

    detail = (await client.get(f"{POLLS}/{poll['id']}")).json()
    assert detail["can_seed_region"] is True

    somerset = poll["options"][2]  # no coordinates — nothing to put on the map
    await client.put(f"{POLLS}/{poll['id']}/decision", json={"option_id": somerset["id"]})
    assert (await client.get(f"{POLLS}/{poll['id']}")).json()["can_seed_region"] is False


# --- nudge ---------------------------------------------------------------------------------------------


async def test_nudging_reports_how_many_were_prompted(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, _ = household
    await login_as(client, db, owner)
    poll = await _create(client)
    body = (await client.post(f"{POLLS}/{poll['id']}/nudge")).json()
    assert body["nudged"] == 3
    assert "3 people" in body["message"]


async def test_a_member_cannot_nudge(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client)

    await login_as(client, db, plain)
    assert (await client.post(f"{POLLS}/{poll['id']}/nudge")).status_code == 403


async def test_a_second_nudge_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, _ = household
    await login_as(client, db, owner)
    poll = await _create(client)
    await client.post(f"{POLLS}/{poll['id']}/nudge")
    response = await client.post(f"{POLLS}/{poll['id']}/nudge")
    assert response.status_code == 429
    assert code(response) == "nudge_too_soon"


# --- comments -------------------------------------------------------------------------------------------


async def test_commenting_and_editing(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client)

    await login_as(client, db, plain)
    comment = (
        await client.post(
            f"{POLLS}/{poll['id']}/comments", json={"body": "Cornwall gets my vote"}
        )
    ).json()
    assert comment["author_name"] == plain.display_name
    assert comment["edited_at"] is None
    assert comment["can_edit"] is True

    edited = (
        await client.patch(f"/api/v1/comments/{comment['id']}", json={"body": "Actually York"})
    ).json()
    assert edited["body"] == "Actually York"
    # An edit that left no trace would falsify the discussion record.
    assert edited["edited_at"] is not None


async def test_a_member_cannot_edit_somebody_elses_comment(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client)
    comment = (
        await client.post(f"{POLLS}/{poll['id']}/comments", json={"body": "Mine"})
    ).json()

    await login_as(client, db, plain)
    assert (
        await client.patch(f"/api/v1/comments/{comment['id']}", json={"body": "Hijacked"})
    ).status_code == 403


async def test_an_organiser_can_delete_anyones_comment(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client)

    await login_as(client, db, plain)
    comment = (
        await client.post(f"{POLLS}/{poll['id']}/comments", json={"body": "Theirs"})
    ).json()

    await login_as(client, db, owner)
    assert (await client.delete(f"/api/v1/comments/{comment['id']}")).status_code == 204


async def test_a_member_cannot_delete_somebody_elses_comment(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, plain = household
    await login_as(client, db, owner)
    poll = await _create(client)
    comment = (
        await client.post(f"{POLLS}/{poll['id']}/comments", json={"body": "Mine"})
    ).json()

    await login_as(client, db, plain)
    assert (await client.delete(f"/api/v1/comments/{comment['id']}")).status_code == 403


async def test_the_comment_count_shows_without_opening_the_thread(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, _ = household
    await login_as(client, db, owner)
    poll = await _create(client)
    await client.post(f"{POLLS}/{poll['id']}/comments", json={"body": "One"})
    await client.post(f"{POLLS}/{poll['id']}/comments", json={"body": "Two"})

    assert (await client.get(f"{POLLS}/{poll['id']}")).json()["comment_count"] == 2


async def test_deleting_a_poll_takes_its_comments(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[User, User, User]
) -> None:
    owner, _, _ = household
    await login_as(client, db, owner)
    poll = await _create(client)
    await client.post(f"{POLLS}/{poll['id']}/comments", json={"body": "One"})

    assert (await client.delete(f"{POLLS}/{poll['id']}")).status_code == 204
    assert await db.scalar(select(func.count()).select_from(Comment)) == 0
    assert await db.scalar(select(func.count()).select_from(Poll)) == 0
