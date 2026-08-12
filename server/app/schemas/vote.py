"""Vote wire shapes.

Three rules are decided here rather than per endpoint:

1. **A vote carries a score or a thumb, never both and never neither.** The database enforces
   `(score IS NULL) <> (thumb IS NULL)`; this enforces the same thing at the edge, so a
   malformed body is a `422` naming the field rather than an `IntegrityError` surfacing as a
   500. Which of the two is *acceptable* depends on the category's configured mode, and that is
   a database question — `services/votes.py` answers it.

2. **"Not yet voted" is never folded into a denominator.** `TallyOut` reports `count`,
   `eligible_count` and an explicit `not_voted` list, because a 10/10 average from one voter
   out of nine must not be able to look like consensus (`design-system.md`'s honesty rules, and
   V3). Every widget consuming this shape gets the outstanding number for free and cannot
   accidentally hide it.

3. **A converted vote says so.** After a mode change, a stored score rendered as a thumb
   carries `converted = true`, and a stored thumb in score mode is reported as *not voted* with
   `has_unusable_vote = true` — never as a fabricated number. See `models/vote.py` for why.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.poll import SCORE_MAX, SCORE_MIN

VotingMode = Literal["score", "thumbs"]
Thumb = Literal["up", "down"]

#: `distribution` is always eleven buckets, 0 through 10 inclusive, even when most are zero:
#: a histogram whose length depends on the data is a histogram whose axis moves under the
#: reader.
DISTRIBUTION_BUCKETS = SCORE_MAX - SCORE_MIN + 1


class VoteIn(BaseModel):
    """**There is no `user_id` here.** The endpoint writes the caller's own vote and has no way
    to express writing somebody else's — the guarantee is a property of the shape rather than a
    check that could be forgotten, exactly as in `ScoresPutIn`."""

    model_config = ConfigDict(extra="forbid")

    score: int | None = Field(default=None, ge=SCORE_MIN, le=SCORE_MAX)
    thumb: Thumb | None = None

    @model_validator(mode="after")
    def _exactly_one_kind_of_answer(self) -> VoteIn:
        if (self.score is None) == (self.thumb is None):
            raise ValueError("give exactly one of score or thumb")
        return self


class MyVoteOut(BaseModel):
    """The caller's own vote. Excluded from every broadcast — it is per recipient, and each
    client already knows its own (`design.md` > WebSocket events)."""

    score: int | None = None
    thumb: Thumb | None = None


class VoterOut(BaseModel):
    """One person's vote, attributed.

    Votes are attributed, not anonymous: this is a family group, and hidden votes would make
    the disagreement view — the whole point of the feature — useless (V4).
    """

    user_id: uuid.UUID
    display_name: str
    family_id: uuid.UUID | None = None
    family_color: int | None = None
    family_color_custom: str | None = None
    score: int | None = None
    thumb: Thumb | None = None
    #: True when what is shown was derived from a vote cast in the other mode. The display must
    #: label it, so a converted score is never passed off as a genuine thumbs vote.
    converted: bool = False
    #: False when the stored vote cannot be read in the active mode at all — a thumb under score
    #: voting. Such a voter also appears in `not_voted`, which is the honest place for them.
    counted: bool = True


class NotVotedOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    family_id: uuid.UUID | None = None
    family_color: int | None = None
    family_color_custom: str | None = None
    #: True when this person *has* voted, but in the other mode, and no number can honestly be
    #: invented from it. Their thumb is preserved in the row and visible in `voters`; the UI
    #: prompts them to re-vote rather than pretending they never did.
    has_unusable_vote: bool = False


class TallyOut(BaseModel):
    """Everything every density of the tally renders, in one object.

    `suggestion.vote.updated` carries this whole thing (minus `my_vote`) rather than a delta,
    for the reason `poll.vote.updated` does: recomputation is one cheap query at this scale, and
    shipping the object removes any possibility of the list row, the popover and the panel
    drifting apart from partially applied deltas.
    """

    suggestion_id: uuid.UUID
    #: Derived from `trip_category_settings` for the suggestion's type on every read. Never
    #: denormalised onto a vote row.
    mode: VotingMode
    #: How many votes are usable in the **active** mode. Not how many rows exist.
    count: int = 0
    #: Everybody on the trip. The denominator "3 of 9 haven't voted" comes from here.
    eligible_count: int = 0
    #: Null when nobody has voted. **Never 0.0** — the same rule as `poll_stats`.
    average: float | None = None
    #: Eleven buckets, 0-10. Score mode only; all zeros in thumbs mode.
    distribution: list[int] = Field(default_factory=lambda: [0] * DISTRIBUTION_BUCKETS)
    up: int = 0
    down: int = 0
    #: Reported as its own proportion, never folded away (V3).
    none: int = 0
    #: Thumbs mode only, and only after a mode change: a stored 5 is neither up nor down, and
    #: rounding it into one camp would invent an opinion the voter did not express.
    unclear: int = 0
    my_vote: MyVoteOut | None = None
    voters: list[VoterOut] = Field(default_factory=list)
    not_voted: list[NotVotedOut] = Field(default_factory=list)
    #: Generated server-side so the list row, the card and the panel carry the same sentence —
    #: and so the chart widgets' `insight` title prop states the finding rather than the metric.
    insight: str = ""

    def without_my_vote(self) -> TallyOut:
        """The broadcast form. `my_vote` is per recipient, so it never goes on the wire to a
        room; clients merge the broadcast tally with the vote they already know they cast."""
        return self.model_copy(update={"my_vote": None})


class PendingVotesOut(BaseModel):
    """V5: "6 need your vote". The ids come back with the count so activating the affordance
    filters the list without a second round trip."""

    count: int = 0
    suggestion_ids: list[uuid.UUID] = Field(default_factory=list)
