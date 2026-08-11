"""Phase 3 — the shapes, and the two rules that must not live in the client.

`can_advance_to` / `can_revert_to` / `blockers` are the whole point of this file: they are
computed server-side so the console's disabled button and the server's refusal come from one
implementation of the stage machine. A test that only checked the field existed would miss
that.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from app.models import Trip
from app.schemas.admin import (
    BLOCKER_MISSING_DATES,
    CategorySettingsPutIn,
    InstanceSettingsIn,
    TripPatchIn,
    trip_admin_out,
)


def _trip(**overrides) -> Trip:
    defaults = dict(
        id=uuid.uuid4(),
        name="Cornwall",
        stage="planning",
        start_date=None,
        end_date=None,
        timezone="Europe/London",
        owner_user_id=None,
    )
    return Trip(**{**defaults, **overrides})


# --- stage affordances -------------------------------------------------------------------


def test_planning_without_dates_is_blocked_and_offers_no_forward_target() -> None:
    out = trip_admin_out(_trip())
    assert out.blockers == [BLOCKER_MISSING_DATES]
    # Not "holiday, but disabled" — a target the client is told it can take and then cannot
    # is worse than no target.
    assert out.can_advance_to is None
    assert out.can_revert_to is None


def test_dates_clear_the_blocker() -> None:
    out = trip_admin_out(_trip(start_date=date(2027, 7, 17), end_date=date(2027, 7, 24)))
    assert out.blockers == []
    assert out.can_advance_to == "holiday"


def test_one_date_is_not_enough() -> None:
    out = trip_admin_out(_trip(start_date=date(2027, 7, 17)))
    assert out.blockers == [BLOCKER_MISSING_DATES]


def test_holiday_can_advance_and_revert_with_no_preconditions() -> None:
    out = trip_admin_out(_trip(stage="holiday"))
    # A trip that has happened can always be declared over, dates or not.
    assert out.can_advance_to == "end"
    assert out.can_revert_to == "planning"
    assert out.blockers == []


def test_end_is_a_terminus_that_can_still_be_corrected() -> None:
    out = trip_admin_out(_trip(stage="end"))
    assert out.can_advance_to is None
    assert out.can_revert_to == "holiday"


# --- setup_complete ------------------------------------------------------------------------


def test_setup_complete_needs_a_name() -> None:
    assert trip_admin_out(_trip(name="")).setup_complete is False
    assert trip_admin_out(_trip(name="   ")).setup_complete is False
    assert trip_admin_out(_trip(name="Cornwall")).setup_complete is True


def test_setup_complete_does_not_require_dates() -> None:
    # Deliberate: the dates are what Planning is for, and requiring them would gate the
    # owner on a decision the trip has not made yet.
    assert trip_admin_out(_trip(start_date=None, end_date=None)).setup_complete is True


# --- TripPatchIn ---------------------------------------------------------------------------


def test_an_inverted_date_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TripPatchIn(start_date=date(2027, 7, 24), end_date=date(2027, 7, 17))


def test_equal_dates_are_a_legitimate_one_day_trip() -> None:
    patch = TripPatchIn(start_date=date(2027, 7, 17), end_date=date(2027, 7, 17))
    assert patch.end_date == patch.start_date


def test_an_unknown_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TripPatchIn(timezone="Mars/Olympus_Mons")


def test_a_real_timezone_is_accepted_and_trimmed() -> None:
    assert TripPatchIn(timezone="  America/New_York ").timezone == "America/New_York"


def test_a_blank_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TripPatchIn(name="   ")


def test_an_omitted_field_stays_omitted() -> None:
    # PATCH semantics: not sending `start_date` is not the same as clearing it, and the
    # router relies on `exclude_unset` to tell them apart.
    patch = TripPatchIn(name="Cornwall")
    assert patch.model_dump(exclude_unset=True) == {"name": "Cornwall"}


# --- the rest ------------------------------------------------------------------------------


def test_a_category_cannot_be_sent_twice_in_one_put() -> None:
    with pytest.raises(ValidationError):
        CategorySettingsPutIn(
            settings=[
                {"category": "poll", "voting_mode": "score"},
                {"category": "poll", "voting_mode": "thumbs"},
            ]
        )


def test_an_unknown_category_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CategorySettingsPutIn(settings=[{"category": "weather", "voting_mode": "score"}])


def test_a_blank_instance_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        InstanceSettingsIn(instance_name="  ")
