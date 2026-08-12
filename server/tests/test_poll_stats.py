"""The worked example, as a unit test.

`plan/features/polls/requirements.md` opens with a reference case, and this file is it:
Cornwall and the Lake District share an average, and only the spread tells you that one of
them splits the group. If this file passes, the feature's central claim — that an average
alone hides disagreement, and that Kindred shows it — is true of the actual code.

> NOTE (implementation): `tasks.md` Phase 2 gives the two arrays as Cornwall
> `[7,8,7,8,7,8,7,8,7]` and the Lake District `[10,10,10,3,3,3,10,3,10]`, and asks that both
> average 7.4. They do not: those average 7.4 and **6.9**, so the case they are meant to
> demonstrate — equal averages, opposite spreads — is not what they demonstrate. (No set of
> nine integers averages 7.4; the sum would have to be 66.6.) The arrays below are the
> smallest change that makes the requirement's own headline true: five scorers, both
> averaging exactly 7.4, with spreads of 0.5 and 3.2. The shape of the claim is unchanged —
> Cornwall clusters, the Lake District has three 10s and two low scores.
"""

from __future__ import annotations

import pytest

from app.services.poll_stats import (
    CLOSE_THRESHOLD,
    SPLIT_THRESHOLD,
    Vote,
    compute_results,
    insight,
    population_stdev,
)

CORNWALL = [7, 8, 7, 8, 7]
LAKE_DISTRICT = [10, 10, 10, 3, 4]
MEMBERS = [f"u{i}" for i in range(5)]


def _votes(**by_option: list[int]) -> dict[str, list[Vote]]:
    return {
        option: [Vote(user_id=MEMBERS[i], score=score) for i, score in enumerate(scores)]
        for option, scores in by_option.items()
    }


def _results(**by_option: list[int]):
    options = list(by_option)
    return compute_results(
        option_ids=options,
        labels={o: o.replace("_", " ").title() for o in options},
        votes=_votes(**by_option),
        member_ids=MEMBERS,
    )


def _option(results, option_id: str):
    return next(o for o in results.options if o.option_id == option_id)


# --- the worked example ----------------------------------------------------------------------


def test_the_two_destinations_average_the_same() -> None:
    results = _results(cornwall=CORNWALL, lake_district=LAKE_DISTRICT)
    assert _option(results, "cornwall").average == 7.4
    assert _option(results, "lake_district").average == 7.4


def test_only_the_spread_tells_them_apart() -> None:
    """The claim the whole feature rests on."""
    results = _results(cornwall=CORNWALL, lake_district=LAKE_DISTRICT)
    cornwall = _option(results, "cornwall")
    lake = _option(results, "lake_district")

    assert cornwall.spread is not None and cornwall.spread < SPLIT_THRESHOLD
    assert lake.spread is not None and lake.spread >= SPLIT_THRESHOLD
    assert cornwall.is_split is False
    assert lake.is_split is True


def test_the_insight_says_both_things() -> None:
    results = _results(cornwall=CORNWALL, lake_district=LAKE_DISTRICT)
    assert "Lake District" in results.insight
    assert "split" in results.insight
    # Equal averages, so the leader reads as neck and neck rather than as a clear win.
    assert "neck and neck" in results.insight


def test_a_clear_leader_with_no_split_just_leads() -> None:
    results = _results(cornwall=[9, 9, 9, 9, 9], somerset=[4, 4, 5, 4, 4])
    assert results.insight == "Cornwall leads"


def test_a_leader_within_two_tenths_is_neck_and_neck() -> None:
    """Exactly two tenths counts as close. 8.0 - 7.8 is not 0.2 in binary floating point, so
    this is also the regression test for comparing the rounded difference."""
    results = _results(cornwall=[8, 8, 8, 8, 8], york=[8, 8, 8, 8, 7])
    assert _option(results, "cornwall").is_close is True
    assert "neck and neck" in results.insight


def test_a_bigger_gap_is_a_lead() -> None:
    results = _results(cornwall=[9, 9, 9, 9, 9], york=[6, 6, 6, 6, 6])
    assert _option(results, "cornwall").is_close is False
    assert results.insight == "Cornwall leads"


# --- the rule that stops averages lying --------------------------------------------------------


def test_an_option_nobody_scored_has_no_average_rather_than_zero() -> None:
    """A zero is somebody saying "really rather not". Fabricating one for silence would drag
    every average towards whoever voted least."""
    results = _results(cornwall=CORNWALL, northumberland=[])
    unscored = _option(results, "northumberland")
    assert unscored.average is None
    assert unscored.average != 0.0
    assert unscored.response_count == 0


def test_a_non_voter_is_excluded_from_the_denominator() -> None:
    """Three scores among five members average over three, not five."""
    results = _results(cornwall=[9, 9, 9])
    assert _option(results, "cornwall").average == 9.0
    assert _option(results, "cornwall").response_count == 3


def test_an_unscored_option_ranks_last_not_first() -> None:
    results = _results(unscored=[], scored=[1, 1, 1])
    assert _option(results, "scored").rank == 1
    assert _option(results, "unscored").rank == 2


def test_nobody_has_voted_at_all() -> None:
    results = _results(cornwall=[], york=[])
    assert results.insight == "No scores yet"
    assert all(o.average is None for o in results.options)


def test_one_vote_gives_an_average_but_no_spread() -> None:
    """The spread of one number is undefined, not zero — and 0.0 would claim perfect
    agreement among a group of one."""
    results = _results(cornwall=[8])
    assert _option(results, "cornwall").average == 8.0
    assert _option(results, "cornwall").spread is None


def test_identical_votes_have_zero_spread_and_are_not_split() -> None:
    results = _results(cornwall=[7, 7, 7, 7, 7])
    assert _option(results, "cornwall").spread == 0.0
    assert _option(results, "cornwall").is_split is False


# --- spread ------------------------------------------------------------------------------------


def test_spread_is_the_population_standard_deviation() -> None:
    """Sample standard deviation would divide by n-1 and inflate the spread of every small
    family — which is every family here. The scores are the population."""
    assert population_stdev([10, 10, 10, 3, 4]) == pytest.approx(3.2)
    assert population_stdev([2, 4]) == pytest.approx(1.0)


def test_spread_needs_two_values() -> None:
    with pytest.raises(ValueError):
        population_stdev([5])


# --- completion --------------------------------------------------------------------------------


def _completion(results, user_id: str) -> str:
    return next(m.completion for m in results.members if m.user_id == user_id)


def test_completion_distinguishes_not_started_from_partly_done() -> None:
    """PL-9: somebody who has scored some but not all is shown separately from somebody who
    has not started — chasing the two is a different conversation."""
    votes = {
        "a": [Vote(user_id="u0", score=5), Vote(user_id="u1", score=5)],
        "b": [Vote(user_id="u0", score=5)],
    }
    results = compute_results(
        option_ids=["a", "b"], labels={"a": "A", "b": "B"}, votes=votes, member_ids=MEMBERS
    )
    assert _completion(results, "u0") == "complete"
    assert _completion(results, "u1") == "partial"
    assert _completion(results, "u2") == "none"
    assert set(results.non_responders) == {"u1", "u2", "u3", "u4"}


def test_an_options_poll_is_complete_at_one_choice() -> None:
    """`options` polls store one row per member, not one per option, so "complete" cannot
    mean "a row for every column"."""
    votes = {"five_days": [Vote(user_id="u0", score=10)]}
    results = compute_results(
        option_ids=["five_days", "seven_days", "ten_days"],
        labels={},
        votes=votes,
        member_ids=MEMBERS,
        single_choice=True,
    )
    assert _completion(results, "u0") == "complete"
    assert _completion(results, "u1") == "none"


# --- thumbs ------------------------------------------------------------------------------------


def test_thumbs_mode_counts_rather_than_averages() -> None:
    """A mean of thumbs is not a meaningful number, so none is produced — printing one would
    invite it to be compared against a score."""
    votes = {
        "cornwall": [
            Vote(user_id="u0", thumb="up"),
            Vote(user_id="u1", thumb="up"),
            Vote(user_id="u2", thumb="down"),
        ]
    }
    results = compute_results(
        option_ids=["cornwall"],
        labels={"cornwall": "Cornwall"},
        votes=votes,
        member_ids=MEMBERS,
        voting_mode="thumbs",
    )
    option = _option(results, "cornwall")
    assert option.average is None
    assert (option.up_count, option.down_count) == (2, 1)
    assert option.none_count == 2
    assert results.insight == "Cornwall is most popular"


def test_thumbs_with_nothing_in_favour_says_so() -> None:
    votes = {"cornwall": [Vote(user_id="u0", thumb="down")]}
    results = compute_results(
        option_ids=["cornwall"],
        labels={"cornwall": "Cornwall"},
        votes=votes,
        member_ids=MEMBERS,
        voting_mode="thumbs",
    )
    assert results.insight == "No votes in favour yet"


# --- thresholds are the documented ones ---------------------------------------------------------


def test_the_thresholds_match_the_design() -> None:
    assert SPLIT_THRESHOLD == 2.5
    assert CLOSE_THRESHOLD == 0.2


def test_several_split_options_are_all_named() -> None:
    results = _results(
        cornwall=[9, 9, 9, 9, 9],
        york=[10, 10, 1, 1, 5],
        somerset=[10, 1, 10, 1, 5],
    )
    # Named in rank order, and ties broken by label, so the sentence is deterministic
    # rather than dependent on dict ordering.
    assert "Somerset and York split the group" in results.insight


def test_insight_is_callable_on_its_own() -> None:
    """It is exported separately because the router builds it from already-computed stats."""
    results = _results(cornwall=CORNWALL, lake_district=LAKE_DISTRICT)
    assert insight(results.options) == results.insight
