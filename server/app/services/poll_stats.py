"""Everything a poll's numbers mean, computed once.

`plan/features/polls/design.md` > Computed values defines these, and defines them *here*
rather than in each view, because the table, the charts and the map must not be able to
disagree. The frontend never recomputes any of it.

**The rule that matters most: a member who has not scored is excluded from the denominator,
never treated as a zero.** An option nobody has scored has `average = None`, not `0.0`. A zero
is a data point — somebody actively saying "really rather not" — and fabricating one for every
silence would make every average a lie in the direction of whoever voted least. That single
distinction is most of why this feature exists rather than a spreadsheet.

Pure functions over plain values: no database, no ORM, no `async`. That is what makes the
worked example from `requirements.md` a unit test rather than an integration test.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: `spread >= this` marks an option as splitting the group. The threshold at which the Lake
#: District case in the worked example reads as contested. A presentation hint, computed
#: server-side so every view agrees on which options are flagged.
SPLIT_THRESHOLD = 2.5

#: Two averages within this are "neck and neck" rather than a lead (PL-6). Stops the ranking
#: implying a decisive winner over a rounding difference.
CLOSE_THRESHOLD = 0.2

#: Averages and spreads are reported to one decimal place, everywhere.
DECIMALS = 1

Completion = str  # "none" | "partial" | "complete"
COMPLETE = "complete"
PARTIAL = "partial"
NONE = "none"


@dataclass(frozen=True)
class Vote:
    """One person's answer on one option. Exactly one of `score`/`thumb` is meaningful,
    according to the mode being read — both may be stored (see `models/poll.py`)."""

    user_id: str
    score: int | None = None
    thumb: str | None = None


@dataclass(frozen=True)
class OptionStats:
    option_id: str
    label: str
    #: `None` when nobody has scored — never `0.0`.
    average: float | None
    response_count: int
    #: Population standard deviation. `None` below two responses, because the spread of one
    #: number is not zero, it is undefined — and drawing 0.0 would claim perfect agreement.
    spread: float | None
    is_split: bool
    is_close: bool
    rank: int
    up_count: int = 0
    down_count: int = 0
    none_count: int = 0


@dataclass(frozen=True)
class MemberStats:
    user_id: str
    completion: Completion
    scored_count: int


@dataclass(frozen=True)
class PollStats:
    options: list[OptionStats] = field(default_factory=list)
    members: list[MemberStats] = field(default_factory=list)
    insight: str = ""

    @property
    def non_responders(self) -> list[str]:
        """Everyone who has not finished — both "not started" and "partly done"."""
        return [m.user_id for m in self.members if m.completion != COMPLETE]


def _round(value: float) -> float:
    return round(value, DECIMALS)


def population_stdev(values: list[int]) -> float:
    """Population standard deviation, not sample.

    The scores *are* the population: everyone who voted is counted, and there is no larger
    group being estimated from a sample. Using the sample formula would divide by n-1 and
    inflate the spread of small families, which is every family here.
    """
    if len(values) < 2:
        raise ValueError("spread needs at least two values")
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def compute_results(
    *,
    option_ids: list[str],
    labels: dict[str, str],
    votes: dict[str, list[Vote]],
    member_ids: list[str],
    voting_mode: str = "score",
    single_choice: bool = False,
) -> PollStats:
    """Every number a poll view shows, from the raw votes.

    `votes` maps option id → the votes cast on it. `member_ids` is everyone *expected* to
    vote, which is what makes "3 of 9 haven't voted" answerable — the denominator comes from
    the trip's membership, not from who happened to respond.

    `single_choice` is the `options`-poll shape: a member is complete when they have exactly
    one row in the whole poll, not one per option.
    """
    thumbs = voting_mode == "thumbs"
    stats: list[OptionStats] = []

    for option_id in option_ids:
        cast = votes.get(option_id, [])

        if thumbs:
            up = sum(1 for vote in cast if vote.thumb == "up")
            down = sum(1 for vote in cast if vote.thumb == "down")
            stats.append(
                OptionStats(
                    option_id=option_id,
                    label=labels.get(option_id, ""),
                    # No average in thumbs mode: the mean of an up and a down is not a
                    # meaningful number, and printing one would invite it to be compared
                    # with a score.
                    average=None,
                    response_count=up + down,
                    spread=None,
                    is_split=False,
                    is_close=False,
                    rank=0,
                    up_count=up,
                    down_count=down,
                    none_count=max(0, len(member_ids) - up - down),
                )
            )
            continue

        scores = [vote.score for vote in cast if vote.score is not None]
        average = _round(sum(scores) / len(scores)) if scores else None
        spread = _round(population_stdev(scores)) if len(scores) >= 2 else None
        stats.append(
            OptionStats(
                option_id=option_id,
                label=labels.get(option_id, ""),
                average=average,
                response_count=len(scores),
                spread=spread,
                is_split=spread is not None and spread >= SPLIT_THRESHOLD,
                is_close=False,
                rank=0,
                none_count=max(0, len(member_ids) - len(scores)),
            )
        )

    stats = _ranked(stats, thumbs=thumbs)
    members = _completion(member_ids, votes, len(option_ids), single_choice=single_choice)
    return PollStats(options=stats, members=members, insight=insight(stats, thumbs=thumbs))


def _ranked(stats: list[OptionStats], *, thumbs: bool) -> list[OptionStats]:
    """Rank by average (or by ups in thumbs mode), and flag a close-run leader.

    Unscored options sort last rather than as zero — they have no position in a ranking of
    opinions nobody has given.
    """
    if thumbs:
        order = sorted(stats, key=lambda s: (-s.up_count, s.label))
    else:
        order = sorted(
            stats,
            key=lambda s: (s.average is None, -(s.average or 0.0), s.label),
        )

    ranked: list[OptionStats] = []
    for index, item in enumerate(order):
        is_close = False
        if not thumbs and index == 0 and len(order) > 1:
            leader, runner_up = item.average, order[1].average
            if leader is not None and runner_up is not None:
                # Rounded before comparing: both averages are already reported to one
                # decimal, and 8.0 - 7.8 is 0.20000000000000018 in binary floating point,
                # which would put an exactly-two-tenths gap on the wrong side of its own
                # threshold.
                is_close = _round(leader - runner_up) <= CLOSE_THRESHOLD
        ranked.append(
            OptionStats(**{**item.__dict__, "rank": index + 1, "is_close": is_close})
        )
    return ranked


def _completion(
    member_ids: list[str],
    votes: dict[str, list[Vote]],
    option_count: int,
    *,
    single_choice: bool,
) -> list[MemberStats]:
    scored: dict[str, int] = {user_id: 0 for user_id in member_ids}
    for cast in votes.values():
        for vote in cast:
            if vote.user_id in scored:
                scored[vote.user_id] += 1

    #: An `options` poll is complete at one row; a score matrix needs every column.
    needed = 1 if single_choice else option_count

    members: list[MemberStats] = []
    for user_id in member_ids:
        count = scored[user_id]
        if count == 0 or needed == 0:
            completion = NONE if count == 0 else COMPLETE
        elif count >= needed:
            completion = COMPLETE
        else:
            completion = PARTIAL
        members.append(MemberStats(user_id=user_id, completion=completion, scored_count=count))
    return members


def insight(stats: list[OptionStats], *, thumbs: bool = False) -> str:
    """One sentence stating the finding, for every view to share.

    `plan/design-system.md` requires chart titles to state the finding rather than the metric
    ("Cornwall leads; the Lake District splits the group", not "Average score by option").
    Generating it once, server-side, is what stops the table, the charts and the map each
    inventing their own wording.

    The rules, in the order `design.md` gives them.
    """
    scored = [s for s in stats if s.response_count > 0]
    if not scored:
        return "No scores yet"

    if thumbs:
        leader = max(scored, key=lambda s: s.up_count)
        if leader.up_count == 0:
            return "No votes in favour yet"
        return f"{leader.label} is most popular"

    ranked = [s for s in stats if s.average is not None]
    if not ranked:
        return "No scores yet"

    leader = ranked[0]
    head = f"{leader.label} leads"
    if len(ranked) > 1 and leader.is_close:
        head = f"{leader.label} and {ranked[1].label} are neck and neck"

    # The split clause names an option the average alone would hide — which is the entire
    # point of computing spread. The leader is named too when it is the split one, because
    # "Cornwall leads" alone would be a misleading sentence about a contested option.
    split = [s.label for s in ranked if s.is_split]
    if split:
        joined = split[0] if len(split) == 1 else f"{', '.join(split[:-1])} and {split[-1]}"
        verb = "splits" if len(split) == 1 else "split"
        return f"{head}; {joined} {verb} the group"
    return head
