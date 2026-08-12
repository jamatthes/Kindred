"""The service layer's rules, tested against a real database.

These are the four things `tasks.md` Phase 4 names, plus the mode-switch guarantee, because
that one is the reason `poll_scores` has two columns instead of one and would otherwise only
be visible as a comment.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Family,
    Notification,
    Poll,
    PollOption,
    PollScore,
    Suggestion,
    Trip,
    TripCategorySetting,
    User,
)
from app.schemas.common import ApiError
from app.services import polls as service
from tests.conftest import add_member, make_family, make_user

pytestmark = pytest.mark.asyncio


async def _set_mode(db: AsyncSession, trip: Trip, mode: str) -> None:
    row = await db.scalar(
        select(TripCategorySetting).where(
            TripCategorySetting.trip_id == trip.id,
            TripCategorySetting.category == "poll",
        )
    )
    if row is None:
        db.add(TripCategorySetting(trip_id=trip.id, category="poll", voting_mode=mode))
    else:
        row.voting_mode = mode
    await db.commit()


async def _poll(
    db: AsyncSession, trip: Trip, *, kind: str = "score_matrix", labels=("A", "B", "C")
) -> Poll:
    poll = Poll(trip_id=trip.id, title="Where shall we go?", kind=kind)
    db.add(poll)
    await db.flush()
    for index, label in enumerate(labels):
        db.add(PollOption(poll_id=poll.id, label=label, sort=index))
    await db.commit()
    return await service.load_poll(db, poll.id, trip)


async def _household(db: AsyncSession, trip: Trip, count: int = 3) -> list[User]:
    family = await make_family(db, trip, "Voters", color=1)
    people = []
    for index in range(count):
        user = await make_user(db, f"voter{index}")
        await add_member(db, family, user, role="head" if index == 0 else "member")
        people.append(user)
    return people


# --- voting mode --------------------------------------------------------------------------------


async def test_the_mode_is_read_never_assumed(db: AsyncSession, trip: Trip) -> None:
    await _set_mode(db, trip, "thumbs")
    assert await service.get_voting_mode(db, trip.id) == "thumbs"
    await _set_mode(db, trip, "score")
    assert await service.get_voting_mode(db, trip.id) == "score"


async def test_a_missing_row_degrades_to_the_documented_default(
    db: AsyncSession, trip: Trip
) -> None:
    """`admin-console` guarantees the row exists; the fallback stops a missing one being a
    500 rather than the documented default."""
    assert await service.get_voting_mode(db, trip.id) == "score"


# --- the options-poll storage rule ----------------------------------------------------------------


async def test_choosing_again_replaces_rather_than_adds(db: AsyncSession, trip: Trip) -> None:
    """PL-2, and the rule the module docstring exists for: the presence of the row *is* the
    choice, so switching leaves exactly one row."""
    await _set_mode(db, trip, "score")
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip, kind="options", labels=("5 days", "7 days", "10 days"))
    five, _seven, ten = poll.options

    await service.upsert_scores(db, poll, people[0], [(five.id, 10, None)], "score")
    await db.commit()
    await service.upsert_scores(db, poll, people[0], [(ten.id, 10, None)], "score")
    await db.commit()

    rows = (await db.scalars(select(PollScore).where(PollScore.poll_id == poll.id))).all()
    assert len(rows) == 1
    assert rows[0].option_id == ten.id


async def test_an_options_poll_refuses_more_than_one_entry(
    db: AsyncSession, trip: Trip
) -> None:
    await _set_mode(db, trip, "score")
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip, kind="options", labels=("5 days", "7 days"))
    five, seven = poll.options

    with pytest.raises(ApiError) as caught:
        await service.upsert_scores(
            db, poll, people[0], [(five.id, 10, None), (seven.id, 10, None)], "score"
        )
    assert caught.value.detail["code"] == "single_choice_required"


# --- mode mismatch -----------------------------------------------------------------------------


async def test_a_thumb_while_the_mode_is_score_is_refused(
    db: AsyncSession, trip: Trip
) -> None:
    await _set_mode(db, trip, "score")
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip)

    with pytest.raises(ApiError) as caught:
        await service.upsert_scores(
            db, poll, people[0], [(poll.options[0].id, None, "up")], "score"
        )
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "wrong_voting_mode"


async def test_a_score_while_the_mode_is_thumbs_is_refused(
    db: AsyncSession, trip: Trip
) -> None:
    await _set_mode(db, trip, "thumbs")
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip)

    with pytest.raises(ApiError) as caught:
        await service.upsert_scores(
            db, poll, people[0], [(poll.options[0].id, 7, None)], "thumbs"
        )
    assert caught.value.detail["code"] == "wrong_voting_mode"


async def test_a_half_valid_body_writes_nothing(db: AsyncSession, trip: Trip) -> None:
    """Validation happens before any write, so a body that is partly wrong does not leave
    half of itself behind."""
    await _set_mode(db, trip, "score")
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip)
    good, bad = poll.options[0], poll.options[1]

    with pytest.raises(ApiError):
        await service.upsert_scores(
            db, poll, people[0], [(good.id, 8, None), (bad.id, None, "up")], "score"
        )
    await db.rollback()
    assert await db.scalar(select(func.count()).select_from(PollScore)) == 0


# --- the reason there are two columns -------------------------------------------------------------


async def test_a_score_survives_a_switch_to_thumbs_and_comes_back(
    db: AsyncSession, trip: Trip
) -> None:
    """PL-4: "Switching mode does not delete anything already cast; the stored votes remain
    and are shown again if the mode is switched back." This is what the two nullable columns
    buy, and it is invisible without a test."""
    await _set_mode(db, trip, "score")
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip)
    option = poll.options[0]

    await service.upsert_scores(db, poll, people[0], [(option.id, 9, None)], "score")
    await db.commit()

    await _set_mode(db, trip, "thumbs")
    poll = await service.load_poll(db, poll.id, trip)
    await service.upsert_scores(db, poll, people[0], [(option.id, None, "down")], "thumbs")
    await db.commit()

    row = await db.scalar(select(PollScore).where(PollScore.option_id == option.id))
    await db.refresh(row)
    # Both values live in one row; the active mode decides which is read.
    assert (row.score, row.thumb) == (9, "down")

    await _set_mode(db, trip, "score")
    poll = await service.load_poll(db, poll.id, trip)
    results = await service.build_results(db, poll, trip)
    assert results["options"][0]["average"] == 9.0


async def test_results_read_only_the_active_modes_column(
    db: AsyncSession, trip: Trip
) -> None:
    await _set_mode(db, trip, "thumbs")
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip)
    option = poll.options[0]
    db.add(
        PollScore(
            poll_id=poll.id, option_id=option.id, user_id=people[0].id, score=9, thumb="up"
        )
    )
    await db.commit()

    results = await service.build_results(db, poll, trip)
    first = next(o for o in results["options"] if o["option_id"] == option.id)
    assert first["average"] is None
    assert first["up_count"] == 1
    assert first["scores"][0]["score"] is None
    assert first["scores"][0]["thumb"] == "up"


# --- closed polls ---------------------------------------------------------------------------------


async def test_scoring_a_closed_poll_is_refused(db: AsyncSession, trip: Trip) -> None:
    await _set_mode(db, trip, "score")
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip)
    service.close_poll(poll, people[0])
    await db.commit()

    with pytest.raises(ApiError) as caught:
        await service.upsert_scores(
            db, poll, people[0], [(poll.options[0].id, 8, None)], "score"
        )
    assert caught.value.detail["code"] == "poll_closed"


async def test_reopening_clears_the_closed_record(db: AsyncSession, trip: Trip) -> None:
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip)
    service.close_poll(poll, people[0])
    await db.commit()
    assert poll.closed_at is not None

    service.reopen_poll(poll)
    await db.commit()
    assert poll.status == "open"
    assert poll.closed_at is None and poll.closed_by is None


# --- nudge ------------------------------------------------------------------------------------------


async def test_a_nudge_reaches_exactly_the_people_who_have_not_finished(
    db: AsyncSession, trip: Trip
) -> None:
    await _set_mode(db, trip, "score")
    people = await _household(db, trip, 3)
    poll = await _poll(db, trip, labels=("A", "B"))

    # Person 0 finishes; person 1 does half; person 2 does nothing.
    await service.upsert_scores(
        db,
        poll,
        people[0],
        [(poll.options[0].id, 8, None), (poll.options[1].id, 6, None)],
        "score",
    )
    await service.upsert_scores(db, poll, people[1], [(poll.options[0].id, 5, None)], "score")
    await db.commit()

    results = await service.build_results(db, poll, trip)
    count = await service.nudge(db, poll, people[0], results)
    await db.commit()

    assert count == 2
    recipients = set(
        (await db.scalars(select(Notification.recipient_user_id))).all()
    )
    assert recipients == {people[1].id, people[2].id}
    assert people[0].id not in recipients


async def test_the_nudge_payload_deep_links_to_the_poll(
    db: AsyncSession, trip: Trip
) -> None:
    await _set_mode(db, trip, "score")
    people = await _household(db, trip, 2)
    poll = await _poll(db, trip, labels=("A",))

    results = await service.build_results(db, poll, trip)
    await service.nudge(db, poll, people[0], results)
    await db.commit()

    row = await db.scalar(select(Notification))
    assert row.type == "poll.nudge"
    assert row.payload_json["deep_link"] == f"/polls/{poll.id}"
    assert row.payload_json["poll_title"] == poll.title


async def test_a_second_nudge_inside_the_window_is_refused(
    db: AsyncSession, trip: Trip
) -> None:
    await _set_mode(db, trip, "score")
    people = await _household(db, trip, 2)
    poll = await _poll(db, trip, labels=("A",))
    results = await service.build_results(db, poll, trip)

    await service.nudge(db, poll, people[0], results)
    await db.commit()

    with pytest.raises(ApiError) as caught:
        await service.nudge(db, poll, people[0], results)
    assert caught.value.status_code == 429
    assert caught.value.detail["code"] == "nudge_too_soon"


async def test_the_window_expires(db: AsyncSession, trip: Trip) -> None:
    await _set_mode(db, trip, "score")
    people = await _household(db, trip, 2)
    poll = await _poll(db, trip, labels=("A",))
    results = await service.build_results(db, poll, trip)

    await service.nudge(db, poll, people[0], results)
    poll.last_nudge_at = datetime.now(UTC) - service.NUDGE_WINDOW - timedelta(minutes=1)
    await db.commit()

    assert service.can_nudge_now(poll) is True
    # Both are still outstanding — a nudge chases whoever has not finished, and nobody
    # finished in between.
    assert await service.nudge(db, poll, people[0], results) == 2


async def test_a_nudge_with_nobody_outstanding_writes_nothing(
    db: AsyncSession, trip: Trip
) -> None:
    """Not an error — everyone having voted is the outcome the nudge was for. The window is
    not consumed either, so a later straggler can still be chased."""
    await _set_mode(db, trip, "score")
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip, labels=("A",))
    await service.upsert_scores(db, poll, people[0], [(poll.options[0].id, 8, None)], "score")
    await db.commit()

    results = await service.build_results(db, poll, trip)
    assert await service.nudge(db, poll, people[0], results) == 0
    await db.commit()

    assert await db.scalar(select(func.count()).select_from(Notification)) == 0
    assert poll.last_nudge_at is None


# --- region seeding ------------------------------------------------------------------------------


async def test_map_suggestions_shipping_turns_seeding_on_by_itself(db: AsyncSession) -> None:
    """The capability check M3 flips.

    It probes for `app.services.suggestions` by import, so implementing that module is what
    turns `can_seed_region` on — nothing had to be edited in `polls` for the button to appear
    (`plan/features/polls/tasks.md` > Hand-off notes). This test was
    `test_seeding_a_region_is_not_available_at_m2` until `map-suggestions` shipped.
    """
    assert service.suggestions_available() is True


async def test_seeding_creates_a_circular_region_on_the_options_point(
    db: AsyncSession, trip: Trip
) -> None:
    """A circle, not a fabricated outline: the option carries a point, and inventing a boundary
    from one coordinate would claim knowledge nobody has. `proposed`, not `approved`: deciding
    *where* is not deciding what the region's outline should be."""
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip, labels=("Cornwall",))
    poll.options[0].lat, poll.options[0].lng = 50.2660, -5.0527
    await db.commit()

    suggestion_id = await service.seed_region(db, trip, poll, poll.options[0], people[0])
    await db.commit()

    suggestion = await db.get(Suggestion, suggestion_id)
    assert suggestion.type == "region"
    assert suggestion.status == "proposed"
    assert suggestion.title == "Cornwall"
    assert suggestion.geometry_geojson["properties"]["shape"] == "circle"
    assert suggestion.geometry_geojson["geometry"]["coordinates"] == [-5.0527, 50.2660]
    assert poll.options[0].suggestion_id == suggestion_id


async def test_an_already_seeded_option_returns_its_existing_region(
    db: AsyncSession, trip: Trip
) -> None:
    """PL-14: "Doing this twice for the same option is prevented; the second attempt links to
    the existing suggestion instead." Checked first, so the idempotent path costs one attribute
    read and cannot produce a second overlapping region nobody asked for."""
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip, labels=("Cornwall",))
    poll.options[0].lat, poll.options[0].lng = 50.2660, -5.0527
    await db.commit()

    first = await service.seed_region(db, trip, poll, poll.options[0], people[0])
    await db.commit()
    second = await service.seed_region(db, trip, poll, poll.options[0], people[0])
    await db.commit()

    assert first == second
    assert await db.scalar(select(func.count()).select_from(Suggestion)) == 1


async def test_deleting_the_seeded_region_clears_the_options_link(
    db: AsyncSession, trip: Trip
) -> None:
    """The FK `map-suggestions` added is `ON DELETE SET NULL`, so this is a database guarantee
    rather than a service-layer promise: the decision banner never renders a broken link."""
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip, labels=("Cornwall",))
    poll.options[0].lat, poll.options[0].lng = 50.2660, -5.0527
    await db.commit()

    suggestion_id = await service.seed_region(db, trip, poll, poll.options[0], people[0])
    await db.commit()

    await db.execute(delete(Suggestion).where(Suggestion.id == suggestion_id))
    await db.commit()
    await db.refresh(poll.options[0])

    assert poll.options[0].suggestion_id is None


# --- comments ------------------------------------------------------------------------------------


async def test_deleting_a_poll_takes_its_comments(db: AsyncSession, trip: Trip) -> None:
    """`comments` is polymorphic and has no FK to its subject, so this cascade is the service
    layer's job and would otherwise be silently missing."""
    from app.models import Comment

    people = await _household(db, trip, 1)
    poll = await _poll(db, trip)
    db.add(
        Comment(
            subject_type="poll",
            subject_id=poll.id,
            author_id=people[0].id,
            body="Cornwall gets my vote",
        )
    )
    await db.commit()
    assert await service.comment_count(db, poll.id) == 1

    await service.delete_poll_comments(db, poll.id)
    await db.commit()
    assert await service.comment_count(db, poll.id) == 0


# --- results shape ----------------------------------------------------------------------------------


async def test_results_carry_the_family_colour_for_the_matrix(
    db: AsyncSession, trip: Trip
) -> None:
    """PL-8: family membership is visible in the matrix, so patterns along family lines are
    legible."""
    await _set_mode(db, trip, "score")
    people = await _household(db, trip, 1)
    poll = await _poll(db, trip, labels=("A",))
    await service.upsert_scores(db, poll, people[0], [(poll.options[0].id, 7, None)], "score")
    await db.commit()

    results = await service.build_results(db, poll, trip)
    assert results["options"][0]["scores"][0]["family_color"] == 1
    assert results["members"][0]["family_color"] == 1


async def test_the_denominator_is_the_membership_not_the_respondents(
    db: AsyncSession, trip: Trip
) -> None:
    await _set_mode(db, trip, "score")
    people = await _household(db, trip, 3)
    poll = await _poll(db, trip, labels=("A",))
    await service.upsert_scores(db, poll, people[0], [(poll.options[0].id, 7, None)], "score")
    await db.commit()

    results = await service.build_results(db, poll, trip)
    assert results["non_responders"]["total"] == 3
    assert results["non_responders"]["count"] == 2
