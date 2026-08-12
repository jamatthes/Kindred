"""The vote routes: both modes, the mode change, the guard, and "needs my vote".

The mode-change section is the one to read first. It is the only place in Kindred where the
honest answer is "we are not going to show you a number", and the tests say so out loud because
the tempting alternative — turning a thumbs-up into a 7 — would be invisible in every chart
that then averaged it.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Suggestion, SuggestionVote, Trip, TripCategorySetting, User
from tests.conftest import add_member, login_as, make_family, make_user

SUGGESTIONS = "/api/v1/suggestions"
PENDING = "/api/v1/me/pending-votes"


def code(response: httpx.Response) -> str:
    return response.json()["detail"]["code"]


@pytest.fixture
async def crew(db: AsyncSession, trip: Trip) -> dict:
    """An owner and two ordinary members in two families — three eligible voters."""
    owner = await make_user(db, "voteowner")
    owners = await make_family(db, trip, "Owners", color=1)
    await add_member(db, owners, owner, role="head")

    ann = await make_user(db, "ann")
    bob = await make_user(db, "bob")
    family = await make_family(db, trip, "Voters", color=2)
    await add_member(db, family, ann, role="head")
    await add_member(db, family, bob, role="member")

    trip.owner_user_id = owner.id
    for category in ("poll", "region", "accommodation", "activity", "meal"):
        db.add(
            TripCategorySetting(trip_id=trip.id, category=category, voting_mode="score")
        )
    await db.commit()
    return {"owner": owner, "ann": ann, "bob": bob}


async def _set_mode(db: AsyncSession, trip: Trip, category: str, mode: str) -> None:
    row = await db.scalar(
        select(TripCategorySetting).where(
            TripCategorySetting.trip_id == trip.id,
            TripCategorySetting.category == category,
        )
    )
    row.voting_mode = mode
    await db.commit()


async def _suggestion(
    db: AsyncSession, trip: Trip, author: User, *, type: str = "accommodation"
) -> Suggestion:
    suggestion = Suggestion(
        trip_id=trip.id,
        type=type,
        title="The Barn",
        status="proposed",
        created_by=author.id,
        lat=50.4,
        lng=-4.7,
    )
    db.add(suggestion)
    await db.commit()
    await db.refresh(suggestion)
    return suggestion


# --- score mode -------------------------------------------------------------------------------


async def test_a_member_casts_a_score_and_sees_the_tally(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])

    response = await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "score"
    assert body["count"] == 1
    assert body["eligible_count"] == 3
    assert body["average"] == 8.0
    assert body["my_vote"] == {"score": 8, "thumb": None}
    assert len(body["not_voted"]) == 2


async def test_voting_again_replaces_rather_than_adds(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """The unique constraint makes this structural: there is no way to end up with two rows."""
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])

    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8})
    body = (
        await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 3})
    ).json()

    assert body["count"] == 1
    assert body["average"] == 3.0
    rows = (await db.scalars(select(SuggestionVote))).unique().all()
    assert len(rows) == 1


async def test_clearing_a_vote_puts_me_back_in_the_outstanding_list(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """Which is what keeps the "needs my vote" affordance honest."""
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8})

    body = (await client.delete(f"{SUGGESTIONS}/{suggestion.id}/vote")).json()

    assert body["count"] == 0
    assert body["average"] is None
    assert body["my_vote"] is None
    assert {n["display_name"] for n in body["not_voted"]} == {"Ann", "Bob", "Voteowner"}


async def test_the_tally_attributes_every_vote(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """Votes are attributed, not anonymous: hidden votes would make the disagreement view — the
    whole point of the feature — useless."""
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 9})
    await login_as(client, db, crew["bob"])
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 1})

    body = (await client.get(f"{SUGGESTIONS}/{suggestion.id}/votes")).json()

    by_name = {v["display_name"]: v for v in body["voters"]}
    assert by_name["Ann"]["score"] == 9
    assert by_name["Bob"]["score"] == 1
    assert by_name["Ann"]["family_color"] == 2
    assert body["distribution"][9] == 1


async def test_a_tally_with_no_votes_is_zeroed_not_misleading(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])

    body = (await client.get(f"{SUGGESTIONS}/{suggestion.id}/votes")).json()

    assert body["count"] == 0
    assert body["average"] is None
    assert len(body["not_voted"]) == 3
    assert body["insight"] == "Nobody has voted yet."


# --- thumbs mode ------------------------------------------------------------------------------------


async def test_a_thumbs_category_takes_thumbs(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    await _set_mode(db, trip, "accommodation", "thumbs")
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])

    body = (
        await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"thumb": "up"})
    ).json()

    assert body["mode"] == "thumbs"
    assert (body["up"], body["down"], body["none"]) == (1, 0, 2)


async def test_the_mode_is_per_category_not_per_trip(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """A trip can score its accommodations and thumb its meals; the suggestion's `type` decides."""
    await _set_mode(db, trip, "meal", "thumbs")
    hotel = await _suggestion(db, trip, crew["owner"], type="accommodation")
    dinner = await _suggestion(db, trip, crew["owner"], type="meal")
    await login_as(client, db, crew["ann"])

    assert (await client.get(f"{SUGGESTIONS}/{hotel.id}/votes")).json()["mode"] == "score"
    assert (await client.get(f"{SUGGESTIONS}/{dinner.id}/votes")).json()["mode"] == "thumbs"


async def test_a_thumb_in_a_score_category_is_a_422_naming_the_real_mode(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """So the client can refetch settings and re-render the right control rather than guessing."""
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])

    response = await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"thumb": "up"})

    assert response.status_code == 422
    assert code(response) == "wrong_voting_mode"
    assert "score" in response.json()["detail"]["message"]


async def test_a_score_in_a_thumbs_category_is_a_422(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    await _set_mode(db, trip, "accommodation", "thumbs")
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])

    response = await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8})

    assert response.status_code == 422
    assert code(response) == "wrong_voting_mode"


async def test_a_body_with_both_answers_is_refused_at_the_edge(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])

    response = await client.put(
        f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8, "thumb": "up"}
    )

    assert response.status_code == 422


# --- changing the mode with votes already cast -------------------------------------------------------


async def test_score_to_thumbs_converts_for_display_and_deletes_nothing(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8})
    await login_as(client, db, crew["bob"])
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 2})

    await _set_mode(db, trip, "accommodation", "thumbs")
    body = (await client.get(f"{SUGGESTIONS}/{suggestion.id}/votes")).json()

    assert (body["up"], body["down"]) == (1, 1)
    assert all(v["converted"] for v in body["voters"])
    # And the rows are untouched, which is what makes switching back lossless.
    assert {v.score for v in (await db.scalars(select(SuggestionVote))).unique().all()} == {8, 2}


async def test_thumbs_to_score_never_fabricates_a_number(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """**The rule this whole feature is judged by.** A thumbs-up carries no defensible numeric
    value, so no number is invented: the voter is listed as outstanding, with their thumb
    preserved and visible in the attribution list, and the average is computed without them."""
    await _set_mode(db, trip, "accommodation", "thumbs")
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"thumb": "up"})

    await _set_mode(db, trip, "accommodation", "score")
    body = (await client.get(f"{SUGGESTIONS}/{suggestion.id}/votes")).json()

    assert body["count"] == 0
    assert body["average"] is None
    outstanding = {n["display_name"]: n for n in body["not_voted"]}
    assert outstanding["Ann"]["has_unusable_vote"] is True
    ann = next(v for v in body["voters"] if v["display_name"] == "Ann")
    assert ann["thumb"] == "up"
    assert ann["score"] is None
    assert ann["counted"] is False


async def test_re_voting_after_a_mode_change_clears_the_other_column(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """The upsert writes the new mode's column and clears the old one in the same statement, so
    `(score IS NULL) <> (thumb IS NULL)` holds — the row never carries both and means neither."""
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8})

    await _set_mode(db, trip, "accommodation", "thumbs")
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"thumb": "down"})

    row = await db.scalar(select(SuggestionVote).where(SuggestionVote.user_id == crew["ann"].id))
    await db.refresh(row)
    assert row.thumb == "down"
    assert row.score is None


# --- the broadcast --------------------------------------------------------------------------------------


async def test_voting_broadcasts_the_tally_without_my_vote(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict, monkeypatch
) -> None:
    """`my_vote` is per recipient: putting it on a room-wide frame would let one client
    overwrite another's local state with a vote that is not theirs."""
    sent: list[tuple] = []

    async def spy(trip_id, type_, payload=None):
        sent.append((type_, payload))
        return 0

    monkeypatch.setattr("app.routers.votes.ws.broadcast", spy)
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8})

    assert [event for event, _ in sent] == ["suggestion.vote.updated"]
    payload = sent[0][1]
    assert payload["suggestion_id"] == str(suggestion.id)
    assert payload["tally"]["my_vote"] is None
    assert payload["tally"]["average"] == 8.0


# --- what needs my vote --------------------------------------------------------------------------------


async def test_pending_votes_lists_what_i_have_not_voted_on(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    first = await _suggestion(db, trip, crew["owner"])
    await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])

    before = (await client.get(PENDING)).json()
    await client.put(f"{SUGGESTIONS}/{first.id}/vote", json={"score": 8})
    after = (await client.get(PENDING)).json()

    assert before["count"] == 2
    assert after["count"] == 1
    assert str(first.id) not in after["suggestion_ids"]


async def test_pending_votes_excludes_rejected_suggestions(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """Chasing a vote on something the group has already turned down is noise."""
    rejected = await _suggestion(db, trip, crew["owner"])
    rejected.status = "rejected"
    await db.commit()
    await login_as(client, db, crew["ann"])

    assert (await client.get(PENDING)).json()["count"] == 0


async def test_pending_votes_excludes_my_own_suggestions_by_default(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """"6 need your vote" should not be partly your own proposals — but the person who does
    want to record a preference on their own can ask for them."""
    await _suggestion(db, trip, crew["ann"])
    await login_as(client, db, crew["ann"])

    assert (await client.get(PENDING)).json()["count"] == 0
    assert (await client.get(PENDING, params={"exclude_own": "false"})).json()["count"] == 1


# --- the list summary ------------------------------------------------------------------------------------


async def test_the_suggestion_list_carries_the_tally_summary(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """The list row renders a tally without a second request per row — which is why the
    aggregate is joined into the one list query rather than fetched per suggestion."""
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8})

    row = (await client.get(SUGGESTIONS)).json()[0]

    assert row["vote_summary"]["mode"] == "score"
    assert row["vote_summary"]["count"] == 1
    assert row["vote_summary"]["average"] == 8.0
    assert row["vote_summary"]["my_vote"] == 8


async def test_the_list_summary_converts_with_the_mode_exactly_as_the_panel_does(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """A list row and a side panel disagreeing about whether somebody voted would be worse than
    either being wrong alone."""
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8})
    await login_as(client, db, crew["bob"])
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 5})

    await _set_mode(db, trip, "accommodation", "thumbs")
    row = (await client.get(SUGGESTIONS)).json()[0]
    panel = (await client.get(f"{SUGGESTIONS}/{suggestion.id}/votes")).json()

    assert row["vote_summary"]["mode"] == "thumbs"
    assert row["vote_summary"]["up"] == panel["up"] == 1
    assert row["vote_summary"]["unclear"] == panel["unclear"] == 1
    assert row["vote_summary"]["converted"] is True


async def test_a_thumbs_vote_contributes_nothing_to_a_score_summary(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    await _set_mode(db, trip, "accommodation", "thumbs")
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"thumb": "up"})

    await _set_mode(db, trip, "accommodation", "score")
    row = (await client.get(SUGGESTIONS)).json()[0]

    assert row["vote_summary"]["count"] == 0
    assert row["vote_summary"]["average"] is None


# --- the stage guard ---------------------------------------------------------------------------------------


async def test_the_end_stage_freezes_voting_but_not_reading(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """A frozen trip is an archive, and an archive whose tallies had disappeared would be a
    worse record than the spreadsheet this replaced."""
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])
    await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8})

    trip.stage = "end"
    await db.commit()

    assert (await client.get(f"{SUGGESTIONS}/{suggestion.id}/votes")).json()["count"] == 1
    assert (await client.get(PENDING)).status_code == 200

    for response in (
        await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 2}),
        await client.delete(f"{SUGGESTIONS}/{suggestion.id}/vote"),
    ):
        assert response.status_code == 409
        assert code(response) == "stage_forbidden"


async def test_voting_works_in_the_holiday_stage(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    trip.stage = "holiday"
    await db.commit()
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, crew["ann"])

    assert (
        await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8})
    ).status_code == 200


async def test_a_vote_on_a_rejected_suggestion_is_allowed(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict
) -> None:
    """Discouraged rather than blocked: rejected items are filtered out by default, so this only
    happens via a deep link — and a rejection may be reopened, so the record stays honest about
    how the group felt."""
    suggestion = await _suggestion(db, trip, crew["owner"])
    suggestion.status = "rejected"
    await db.commit()
    await login_as(client, db, crew["ann"])

    assert (
        await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8})
    ).status_code == 200


async def test_an_outsider_cannot_vote(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, crew: dict, outsider: User
) -> None:
    suggestion = await _suggestion(db, trip, crew["owner"])
    await login_as(client, db, outsider)

    response = await client.put(f"{SUGGESTIONS}/{suggestion.id}/vote", json={"score": 8})

    assert response.status_code == 403
    assert code(response) == "not_on_trip"
