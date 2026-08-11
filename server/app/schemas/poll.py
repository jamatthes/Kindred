"""Poll wire shapes.

Three things are decided here rather than in the router, because each is a rule that would
otherwise be re-implemented per endpoint and drift:

1. **A score entry carries a score or a thumb, never both and never neither.** The database
   enforces "not both null"; this enforces the other half, at the edge, so a malformed body
   is a `422` naming the field rather than an `IntegrityError` surfacing as a 500.
2. **`PollPatchIn` has no `kind` field at all.** `kind` is immutable after creation — a
   `score_matrix` stores one row per (option, member) and an `options` poll one row per
   member, so changing it would orphan every stored vote. Leaving the field out entirely,
   with `extra="forbid"`, means a client that tries is told rather than silently ignored.
3. **Capability flags (`can_delete`, `can_nudge`, `can_seed_region`) are computed
   server-side** and shipped on the response. The frontend renders them; it never derives
   permission. Hiding a control the server would refuse is a courtesy — deriving the rule in
   two places is a bug waiting for the two to disagree.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.poll import SCORE_MAX, SCORE_MIN

PollKind = Literal["score_matrix", "options"]
PollStatus = Literal["open", "closed"]
VotingMode = Literal["score", "thumbs"]
Thumb = Literal["up", "down"]
Completion = Literal["none", "partial", "complete"]


# --- options ---------------------------------------------------------------------------------


class PollOptionOut(BaseModel):
    id: uuid.UUID
    label: str
    lat: float | None = None
    lng: float | None = None
    place_id: str | None = None
    sort: int
    created_by: uuid.UUID | None = None
    #: Set once this option has been seeded into a map region (PL-14). Null until then, and
    #: until `map-suggestions` exists at all.
    suggestion_id: uuid.UUID | None = None
    #: Computed per caller: the author may delete while nobody else has scored it, and an
    #: organiser may always delete.
    can_delete: bool = False


class OptionCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    place_id: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _coordinates_come_as_a_pair(self) -> OptionCreateIn:
        """Half a coordinate is not a location. Accepting one would put an option on the
        equator or the prime meridian and call it the user's choice."""
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat and lng must be given together, or not at all")
        return self


class OptionPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    sort: int | None = None


# --- polls -----------------------------------------------------------------------------------


class GroupCompletion(BaseModel):
    """How the whole group is doing. `total` is the membership, not the respondents — which
    is what makes "3 of 9 haven't voted yet" answerable."""

    complete: int = 0
    partial: int = 0
    none: int = 0
    total: int = 0


class DecisionOut(BaseModel):
    option_id: uuid.UUID
    label: str


class PollSummaryOut(BaseModel):
    """The list row. Deliberately cheap — no options, no scores, no members."""

    id: uuid.UUID
    title: str
    kind: PollKind
    status: PollStatus
    option_count: int
    comment_count: int
    my_completion: Completion
    group_completion: GroupCompletion
    decision: DecisionOut | None = None
    created_at: datetime


class PollOut(PollSummaryOut):
    description: str | None = None
    allow_member_options: bool
    options: list[PollOptionOut] = Field(default_factory=list)
    #: Read from `trip_category_settings`, never assumed (PL-4). All polls on a trip share
    #: the `poll` category's mode.
    voting_mode: VotingMode
    closed_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by: uuid.UUID | None = None
    #: False when nobody is outstanding, when the caller is not an organiser, or while the
    #: four-hour window is still running.
    can_nudge: bool = False
    next_nudge_at: datetime | None = None
    #: False at M2 — `map-suggestions` does not exist, so the action is never rendered.
    can_seed_region: bool = False


class PollCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    kind: PollKind
    allow_member_options: bool = False
    options: list[OptionCreateIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _an_options_poll_needs_options(self) -> PollCreateIn:
        """An `options` poll with nothing to choose between cannot be answered at all. A
        score matrix can legitimately start empty and have options added.
        """
        if self.kind == "options" and len(self.options) < 2:
            raise ValueError("an options poll needs at least two options to choose between")
        return self


class PollPatchIn(BaseModel):
    """No `kind`. See the module docstring — it is immutable, and `extra="forbid"` means a
    client that sends one is told rather than ignored."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    allow_member_options: bool | None = None


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: uuid.UUID


class CloseIn(BaseModel):
    """The confirm is a real one (PL-12) — the count of who has not voted is named on screen,
    so closing a poll out from under people takes a deliberate second action."""

    model_config = ConfigDict(extra="forbid")

    confirm: bool = True


# --- scores ------------------------------------------------------------------------------------


class ScoreEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: uuid.UUID
    score: int | None = Field(default=None, ge=SCORE_MIN, le=SCORE_MAX)
    thumb: Thumb | None = None

    @model_validator(mode="after")
    def _exactly_one_kind_of_answer(self) -> ScoreEntryIn:
        if (self.score is None) == (self.thumb is None):
            raise ValueError("give exactly one of score or thumb")
        return self


class ScoresPutIn(BaseModel):
    """**There is no `user_id` here, anywhere.** The endpoint writes the caller's own scores
    and has no way to express writing somebody else's — which is how "nobody can change
    another person's vote" is guaranteed rather than checked."""

    model_config = ConfigDict(extra="forbid")

    scores: list[ScoreEntryIn] = Field(min_length=1)


# --- results -----------------------------------------------------------------------------------


class ScoreOut(BaseModel):
    """One person's answer, as the matrix renders it. Individual scores are visible to
    everyone on the trip — a deliberate product decision (`requirements.md` > Permissions):
    the feature replaces a shared spreadsheet in which everyone could already see everyone's
    numbers, and hiding them would make the disagreement view impossible."""

    user_id: uuid.UUID
    display_name: str
    family_id: uuid.UUID | None = None
    family_color: int | None = None
    score: int | None = None
    thumb: str | None = None


class OptionResultOut(BaseModel):
    option_id: uuid.UUID
    label: str
    lat: float | None = None
    lng: float | None = None
    #: Null when nobody has scored. **Never 0.0** — see `services/poll_stats.py`.
    average: float | None = None
    response_count: int = 0
    #: Null below two responses.
    spread: float | None = None
    is_split: bool = False
    is_close: bool = False
    rank: int = 0
    scores: list[ScoreOut] = Field(default_factory=list)
    up_count: int = 0
    down_count: int = 0
    none_count: int = 0


class MemberResultOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    family_id: uuid.UUID | None = None
    family_color: int | None = None
    completion: Completion


class NonResponderOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    #: `none` or `partial` — PL-9 shows the two separately, because chasing them is a
    #: different conversation.
    completion: Completion


class NonRespondersOut(BaseModel):
    count: int = 0
    total: int = 0
    users: list[NonResponderOut] = Field(default_factory=list)


class PollResultsOut(BaseModel):
    """Everything every view needs, in one object.

    `poll.vote.updated` carries this whole thing rather than a delta: recomputation is a
    single cheap query at this scale, and shipping the whole object removes any possibility of
    the matrix, the charts and the map drifting apart from partially applied deltas.
    """

    poll_id: uuid.UUID
    voting_mode: VotingMode
    status: PollStatus
    options: list[OptionResultOut] = Field(default_factory=list)
    members: list[MemberResultOut] = Field(default_factory=list)
    non_responders: NonRespondersOut = Field(default_factory=NonRespondersOut)
    #: Generated server-side so the table, the charts and the map carry the same sentence.
    insight: str = ""


class NudgeOut(BaseModel):
    nudged: int
    next_nudge_at: datetime | None = None
    #: Plain words for the zero case — "everyone has voted" is a result, not a failure.
    message: str = ""
