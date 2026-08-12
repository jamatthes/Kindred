"""`VoteIn`'s exactly-one rule, and the tally's honesty rules as pure functions.

`build_tally` is separated from its queries precisely so the mode-change behaviour — the part
of this feature most likely to be got subtly wrong — is testable without a database. These are
those tests.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.models import Family, SuggestionVote, User
from app.schemas.vote import DISTRIBUTION_BUCKETS, TallyOut, VoteIn
from app.services.votes import build_insight, build_tally

SUGGESTION = uuid.uuid4()


def person(name: str, color: int) -> tuple[User, Family]:
    user = User(id=uuid.uuid4(), username=name, password_hash="x", display_name=name.title())
    family = Family(id=uuid.uuid4(), name=f"{name}s", color=color)
    return user, family


def vote(user: User, *, score: int | None = None, thumb: str | None = None) -> SuggestionVote:
    return SuggestionVote(
        suggestion_id=SUGGESTION, user_id=user.id, score=score, thumb=thumb
    )


# --- VoteIn ---------------------------------------------------------------------------------


def test_a_score_alone_is_accepted():
    assert VoteIn(score=8).score == 8


def test_a_thumb_alone_is_accepted():
    assert VoteIn(thumb="up").thumb == "up"


def test_both_together_are_refused():
    with pytest.raises(ValidationError, match="exactly one"):
        VoteIn(score=8, thumb="up")


def test_neither_is_refused():
    with pytest.raises(ValidationError, match="exactly one"):
        VoteIn()


def test_a_score_out_of_range_is_refused():
    with pytest.raises(ValidationError):
        VoteIn(score=11)
    with pytest.raises(ValidationError):
        VoteIn(score=-1)


def test_a_zero_is_a_real_vote_not_an_absence():
    """0 means "I hate it", which is why clearing a vote deletes the row rather than zeroing
    it — a zeroed row would count as a response in every outstanding total."""
    assert VoteIn(score=0).score == 0


def test_there_is_no_way_to_vote_for_somebody_else():
    with pytest.raises(ValidationError):
        VoteIn(score=8, user_id=str(uuid.uuid4()))


# --- score mode ---------------------------------------------------------------------------------


def test_a_score_tally_counts_averages_and_distributes():
    a, fa = person("ann", 1)
    b, fb = person("bob", 2)
    c, fc = person("cat", 3)
    tally = build_tally(
        SUGGESTION, "score", [(a, fa), (b, fb), (c, fc)], [vote(a, score=8), vote(b, score=4)]
    )

    assert tally.count == 2
    assert tally.eligible_count == 3
    assert tally.average == 6.0
    assert len(tally.distribution) == DISTRIBUTION_BUCKETS
    assert tally.distribution[8] == 1
    assert tally.distribution[4] == 1
    assert [n.display_name for n in tally.not_voted] == ["Cat"]


def test_nobody_voting_gives_a_null_average_never_zero():
    """A 0.0 average would read as "the group hated it" when it means "nobody said"."""
    a, fa = person("ann", 1)
    tally = build_tally(SUGGESTION, "score", [(a, fa)], [])

    assert tally.count == 0
    assert tally.average is None
    assert tally.insight == "Nobody has voted yet."


def test_the_outstanding_list_is_reported_not_subtracted():
    """A 10/10 from one voter out of nine must not be able to look like consensus."""
    people = [person(f"p{i}", i + 1) for i in range(9)]
    tally = build_tally(
        SUGGESTION, "score", people, [vote(people[0][0], score=10)]
    )

    assert tally.count == 1
    assert tally.eligible_count == 9
    assert len(tally.not_voted) == 8
    assert "8 still to vote" in tally.insight


def test_my_vote_is_only_present_for_the_caller():
    a, fa = person("ann", 1)
    b, fb = person("bob", 2)
    votes = [vote(a, score=8), vote(b, score=2)]

    mine = build_tally(SUGGESTION, "score", [(a, fa), (b, fb)], votes, caller=a)
    theirs = build_tally(SUGGESTION, "score", [(a, fa), (b, fb)], votes, caller=b)
    anonymous = build_tally(SUGGESTION, "score", [(a, fa), (b, fb)], votes)

    assert mine.my_vote.score == 8
    assert theirs.my_vote.score == 2
    assert anonymous.my_vote is None


def test_the_broadcast_form_drops_my_vote():
    a, fa = person("ann", 1)
    tally = build_tally(SUGGESTION, "score", [(a, fa)], [vote(a, score=8)], caller=a)

    assert tally.my_vote is not None
    assert tally.without_my_vote().my_vote is None
    # And leaves everything else alone.
    assert tally.without_my_vote().count == tally.count


# --- thumbs mode ----------------------------------------------------------------------------------


def test_a_thumbs_tally_reports_up_down_and_none_separately():
    a, fa = person("ann", 1)
    b, fb = person("bob", 2)
    c, fc = person("cat", 3)
    tally = build_tally(
        SUGGESTION,
        "thumbs",
        [(a, fa), (b, fb), (c, fc)],
        [vote(a, thumb="up"), vote(b, thumb="down")],
    )

    assert (tally.up, tally.down, tally.none) == (1, 1, 1)
    assert tally.count == 2
    assert "Splits the group" in tally.insight


# --- the mode change ---------------------------------------------------------------------------------


def test_score_to_thumbs_converts_by_threshold_and_says_so():
    """8 is up, 2 is down, and both are labelled converted so a converted score is never passed
    off as a genuine thumbs vote."""
    a, fa = person("ann", 1)
    b, fb = person("bob", 2)
    tally = build_tally(
        SUGGESTION, "thumbs", [(a, fa), (b, fb)], [vote(a, score=8), vote(b, score=2)]
    )

    assert (tally.up, tally.down) == (1, 1)
    assert all(voter.converted for voter in tally.voters)
    assert tally.not_voted == []


def test_a_stored_five_under_thumbs_voting_is_unclear_not_rounded():
    """Rounding a 5 into a camp would invent an opinion the voter did not express."""
    a, fa = person("ann", 1)
    tally = build_tally(SUGGESTION, "thumbs", [(a, fa)], [vote(a, score=5)])

    assert (tally.up, tally.down, tally.unclear) == (0, 0, 1)
    assert tally.voters[0].thumb is None
    assert tally.voters[0].converted is True
    assert "1 unclear" in tally.insight


def test_thumbs_to_score_fabricates_no_number_and_lists_them_as_outstanding():
    """The load-bearing case. A thumb has no defensible numeric value; inventing one would put
    fabricated data into an average, so the voter is shown as not-yet-voted instead — with the
    thumb preserved and visible in the attribution list, so nothing is hidden."""
    a, fa = person("ann", 1)
    b, fb = person("bob", 2)
    tally = build_tally(
        SUGGESTION, "score", [(a, fa), (b, fb)], [vote(a, thumb="up"), vote(b, score=6)]
    )

    assert tally.count == 1
    assert tally.average == 6.0  # bob's score alone; ann contributes nothing

    outstanding = {n.display_name: n for n in tally.not_voted}
    assert outstanding["Ann"].has_unusable_vote is True

    ann = next(v for v in tally.voters if v.display_name == "Ann")
    assert ann.thumb == "up"
    assert ann.score is None
    assert ann.counted is False


def test_switching_back_restores_the_original_display():
    """Nothing was deleted or converted on disk, so the same rows read the same way again."""
    a, fa = person("ann", 1)
    votes = [vote(a, score=9)]

    as_score = build_tally(SUGGESTION, "score", [(a, fa)], votes)
    as_thumbs = build_tally(SUGGESTION, "thumbs", [(a, fa)], votes)
    back = build_tally(SUGGESTION, "score", [(a, fa)], votes)

    assert as_score.average == 9.0
    assert as_thumbs.up == 1
    assert back.average == 9.0


def test_a_vote_from_somebody_no_longer_on_the_trip_is_not_a_row_in_the_tally():
    """Their vote rows remain — the group's history is real — but the matrix is built from the
    trip's membership, so a departed member is not a line in it."""
    a, fa = person("ann", 1)
    ghost, _ = person("ghost", 9)
    tally = build_tally(
        SUGGESTION, "score", [(a, fa)], [vote(a, score=7), vote(ghost, score=1)]
    )

    assert tally.count == 1
    assert tally.average == 7.0


# --- the insight sentence ---------------------------------------------------------------------------


def test_the_insight_always_names_how_many_have_not_voted():
    assert "3 still to vote" in build_insight("score", 2, 5, 7.0, 0, 0, 0)
    assert "everybody has voted" in build_insight("score", 5, 5, 7.0, 0, 0, 0)


def test_the_insight_states_the_finding_not_the_metric_name():
    assert build_insight("thumbs", 7, 7, None, 4, 3, 0).startswith("Splits the group")
    assert "Averaging" in build_insight("score", 1, 1, 8.0, 0, 0, 0)


def test_a_tally_defaults_to_an_empty_distribution_of_eleven_buckets():
    """A histogram whose length depends on the data is a histogram whose axis moves under the
    reader."""
    assert TallyOut(suggestion_id=SUGGESTION, mode="score").distribution == [0] * 11
