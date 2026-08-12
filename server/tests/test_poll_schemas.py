"""The validation the edge does, so a malformed body is a 422 naming the field rather than
an IntegrityError surfacing as a 500.

Each test below corresponds to a rule stated in `plan/features/polls/design.md`; the point of
asserting them here is that the router then never has to.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.comment import CommentIn, CommentOut
from app.schemas.poll import (
    DecisionIn,
    OptionCreateIn,
    PollCreateIn,
    PollPatchIn,
    ScoreEntryIn,
    ScoresPutIn,
)

OPTION = uuid.uuid4()


# --- scores ------------------------------------------------------------------------------------


@pytest.mark.parametrize("score", [0, 1, 5, 10])
def test_the_stored_range_is_zero_to_ten(score: int) -> None:
    """The UI collects 1-10; the column and the schema accept 0-10, so a future "0 = veto"
    needs no migration (`requirements.md`, NOTE on PL-3)."""
    assert ScoreEntryIn(option_id=OPTION, score=score).score == score


@pytest.mark.parametrize("score", [11, -1, 100])
def test_a_score_outside_the_range_is_refused(score: int) -> None:
    with pytest.raises(ValidationError):
        ScoreEntryIn(option_id=OPTION, score=score)


def test_a_body_carrying_both_a_score_and_a_thumb_is_refused() -> None:
    """The database enforces "not both null"; this enforces the other half."""
    with pytest.raises(ValidationError) as caught:
        ScoreEntryIn(option_id=OPTION, score=7, thumb="up")
    assert "exactly one" in str(caught.value)


def test_a_body_carrying_neither_is_refused() -> None:
    with pytest.raises(ValidationError):
        ScoreEntryIn(option_id=OPTION)


def test_an_unknown_thumb_is_refused() -> None:
    with pytest.raises(ValidationError):
        ScoreEntryIn(option_id=OPTION, thumb="sideways")


def test_there_is_no_way_to_name_another_user_in_a_score_body() -> None:
    """The guarantee behind "nobody can change another person's vote": the request model has
    no `user_id`, so the endpoint cannot express it even by accident."""
    assert "user_id" not in ScoresPutIn.model_fields
    assert "user_id" not in ScoreEntryIn.model_fields

    with pytest.raises(ValidationError):
        ScoresPutIn(
            scores=[{"option_id": str(OPTION), "score": 7, "user_id": str(uuid.uuid4())}]
        )


def test_an_empty_scores_list_is_refused() -> None:
    with pytest.raises(ValidationError):
        ScoresPutIn(scores=[])


# --- polls -------------------------------------------------------------------------------------


def test_the_patch_body_has_no_kind_field_at_all() -> None:
    """`kind` is immutable: a score matrix stores one row per (option, member) and an options
    poll one row per member, so changing it would orphan every stored vote."""
    assert "kind" not in PollPatchIn.model_fields

    with pytest.raises(ValidationError) as caught:
        PollPatchIn(title="Renamed", kind="options")
    assert "kind" in str(caught.value)


def test_a_patch_may_change_the_things_that_are_changeable() -> None:
    patch = PollPatchIn(title="Where shall we go?", allow_member_options=True)
    assert patch.model_dump(exclude_unset=True) == {
        "title": "Where shall we go?",
        "allow_member_options": True,
    }


def test_an_options_poll_needs_something_to_choose_between() -> None:
    with pytest.raises(ValidationError) as caught:
        PollCreateIn(title="How long?", kind="options", options=[{"label": "5 days"}])
    assert "at least two" in str(caught.value)


def test_a_score_matrix_may_start_empty() -> None:
    """Options can be added while it is open, so an empty matrix is a legitimate starting
    point — unlike an options poll, which cannot be answered at all."""
    poll = PollCreateIn(title="What shall we do?", kind="score_matrix")
    assert poll.options == []


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValidationError):
        PollCreateIn(title="Ranked", kind="ranked_choice")


# --- options -----------------------------------------------------------------------------------


def test_an_option_may_carry_a_location() -> None:
    option = OptionCreateIn(label="Cornwall", lat=50.2660, lng=-5.0527)
    assert (option.lat, option.lng) == (50.2660, -5.0527)


def test_an_option_may_carry_no_location() -> None:
    assert OptionCreateIn(label="5 days").lat is None


def test_half_a_coordinate_is_refused() -> None:
    """Accepting one would place an option on the equator or the prime meridian and call it
    the user's choice."""
    with pytest.raises(ValidationError) as caught:
        OptionCreateIn(label="Cornwall", lat=50.2660)
    assert "together" in str(caught.value)


@pytest.mark.parametrize(("lat", "lng"), [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_coordinates_off_the_planet_are_refused(lat: float, lng: float) -> None:
    with pytest.raises(ValidationError):
        OptionCreateIn(label="Nowhere", lat=lat, lng=lng)


def test_an_empty_label_is_refused() -> None:
    with pytest.raises(ValidationError):
        OptionCreateIn(label="")


# --- decision ----------------------------------------------------------------------------------


def test_a_decision_names_exactly_one_option() -> None:
    option = uuid.uuid4()
    assert DecisionIn(option_id=option).option_id == option
    with pytest.raises(ValidationError):
        DecisionIn(option_id=option, also=uuid.uuid4())


# --- comments ----------------------------------------------------------------------------------


def test_a_comment_needs_a_body() -> None:
    with pytest.raises(ValidationError):
        CommentIn(body="")


def test_a_comment_reports_whether_it_was_edited() -> None:
    """The UI shows an "edited" marker — an edit that left no trace would falsify the
    discussion record."""
    import datetime as dt

    base = {
        "id": uuid.uuid4(),
        "subject_type": "poll",
        "subject_id": uuid.uuid4(),
        "body": "Cornwall gets my vote",
        "created_at": dt.datetime.now(dt.UTC),
    }
    assert CommentOut(**base).is_edited is False
    assert CommentOut(**base, edited_at=dt.datetime.now(dt.UTC)).is_edited is True


def test_a_comment_from_a_deleted_account_still_renders() -> None:
    """`author_id` nulls on account deletion; the thread must not lose the message."""
    import datetime as dt

    comment = CommentOut(
        id=uuid.uuid4(),
        subject_type="poll",
        subject_id=uuid.uuid4(),
        body="Still here",
        created_at=dt.datetime.now(dt.UTC),
    )
    assert comment.author_id is None
    assert comment.author_name
