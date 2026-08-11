"""Schemas for the admin console.

Two things in here are load-bearing beyond their shape:

* **`TripAdminOut` computes the stage affordances server-side.** `can_advance_to`,
  `can_revert_to` and `blockers` are answers, not inputs — the frontend disables a control
  because the server said so, and the server refuses the transition for the same reason. A
  client that derived legality itself would be a second implementation of the stage machine,
  and the two would drift on the first change to it.
* **`setup_complete` is not defined here.** It is `Trip.setup_complete`, shared with
  foundation's onboarding gate, so the console and the gate cannot disagree about whether a
  trip has been set up.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import STAGES, VOTING_CATEGORIES, VOTING_MODES, Trip
from app.schemas.family import FamilyOut

Stage = Literal["planning", "holiday", "end"]
VotingCategory = Literal["poll", "region", "accommodation", "activity", "meal"]
VotingMode = Literal["score", "thumbs"]
FamilyRole = Literal["head", "spouse", "member"]

#: The stage machine, stated once. `holiday-stage` executes transitions; this is what the
#: console uses to render the affordances, and both read the same two maps.
FORWARD: dict[str, str] = {"planning": "holiday", "holiday": "end"}
BACKWARD: dict[str, str] = {"holiday": "planning", "end": "holiday"}

#: The one machine-readable reason a forward move can be unavailable in v1.
BLOCKER_MISSING_DATES = "missing_dates"


def blockers_for(trip: Trip) -> list[str]:
    """Why the forward transition is unavailable, in machine-readable terms.

    Only the `planning → holiday` move has a precondition: a trip cannot start on dates
    nobody has set. Moving `holiday → end` has none — a trip that has happened can always be
    declared over.
    """
    if trip.stage == "planning" and (trip.start_date is None or trip.end_date is None):
        return [BLOCKER_MISSING_DATES]
    return []


def validate_timezone(value: str) -> str:
    """An IANA name the server can actually load.

    Checked with `zoneinfo` rather than against a hardcoded list: the list is the operating
    system's, it changes, and a trip in a zone this server cannot resolve would break every
    date calculation downstream rather than failing here where it is fixable.
    """
    candidate = value.strip()
    if not candidate:
        raise ValueError("Choose a timezone.")
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"{candidate!r} is not a timezone name.") from exc
    return candidate


# --- trip ----------------------------------------------------------------------------------


class TripAdminOut(BaseModel):
    """The trip as the console sees it, including what may be done to it next."""

    id: uuid.UUID
    name: str
    stage: Stage
    start_date: date | None
    end_date: date | None
    timezone: str
    owner_user_id: uuid.UUID | None
    #: The single legal forward target, or null when there is none (`end`) or the trip is
    #: blocked from taking it.
    can_advance_to: Stage | None
    #: The single legal backward target, or null (`planning`).
    can_revert_to: Stage | None
    blockers: list[str] = Field(default_factory=list)
    #: AC-0. The same predicate foundation's `next_step` gate reads.
    setup_complete: bool


def trip_admin_out(trip: Trip) -> TripAdminOut:
    blockers = blockers_for(trip)
    forward = FORWARD.get(trip.stage)
    return TripAdminOut(
        id=trip.id,
        name=trip.name,
        stage=trip.stage,
        start_date=trip.start_date,
        end_date=trip.end_date,
        timezone=trip.timezone,
        owner_user_id=trip.owner_user_id,
        # Blocked and impossible are reported the same way — as "you cannot go forward" —
        # with `blockers` carrying the difference in words. A target the client is told it
        # can take and then cannot is worse than no target.
        can_advance_to=None if blockers else forward,
        can_revert_to=BACKWARD.get(trip.stage),
        blockers=blockers,
        setup_complete=trip.setup_complete,
    )


class TripPatchIn(BaseModel):
    """Partial update. An omitted field is left alone; that is not the same as clearing it.

    The cross-field date check here only fires when both dates arrive together. The general
    case — one date sent, the other already stored — is checked in the router against the
    merged values, because that is the only place both are known.
    """

    name: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            # The name is in the app header and on the invite preview. Blanking it would
            # also flip `setup_complete` back to false and re-gate the owner.
            raise ValueError("The trip needs a name.")
        return cleaned

    @field_validator("timezone")
    @classmethod
    def _timezone_is_iana(cls, value: str | None) -> str | None:
        return None if value is None else validate_timezone(value)

    @model_validator(mode="after")
    def _dates_in_order(self) -> TripPatchIn:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("The end date cannot be before the start date.")
        return self


class StageChangeIn(BaseModel):
    """`PATCH /trips/{id}/stage`. `reason` is required for a backward move.

    Requiring the word on the way back is what stops a backward transition being an
    accidental payload: advancing and reverting differ by one field value, and only one of
    them can be typed by mistake.
    """

    stage: Stage
    reason: Literal["revert"] | None = None


class StageActorOut(BaseModel):
    user_id: uuid.UUID | None = None
    display_name: str | None = None


class StageTransitionOut(BaseModel):
    """One row of the history, resolved for display."""

    from_stage: str
    to_stage: str
    direction: Literal["forward", "backward"]
    #: Null when the account has since been deleted — the record outlives the person.
    changed_by: StageActorOut | None = None
    created_at: datetime


class StagePatchOut(BaseModel):
    """The response `holiday-stage` specifies for a stage change."""

    id: uuid.UUID
    stage: Stage
    changed_at: datetime
    changed_by: uuid.UUID | None


# --- category voting modes -------------------------------------------------------------------


class CategorySettingOut(BaseModel):
    category: VotingCategory
    voting_mode: VotingMode
    #: Votes already cast in this category. Drives the confirm in AC-5; reads zero for
    #: features whose tables do not exist yet.
    existing_vote_count: int = 0


class CategorySettingIn(BaseModel):
    category: VotingCategory
    voting_mode: VotingMode


class CategorySettingsPutIn(BaseModel):
    """A whole-list PUT. Sending one row is legal; sending the same category twice is not."""

    settings: list[CategorySettingIn]

    @model_validator(mode="after")
    def _no_duplicate_categories(self) -> CategorySettingsPutIn:
        seen = [row.category for row in self.settings]
        if len(seen) != len(set(seen)):
            raise ValueError("Each category may appear only once.")
        return self


class CategorySettingPublicOut(BaseModel):
    """What every voting UI reads. No vote counts — those are an admin's business."""

    category: VotingCategory
    voting_mode: VotingMode


# --- members and families ----------------------------------------------------------------------


class AdminMemberOut(BaseModel):
    """One person, for the overview table.

    The identity fields come from `families`' shared serialiser, not a second implementation:
    the console must show the same badge and the same name as the map and the member list.

    `is_owner`, `is_organiser` and `family_role` are three independent facts rather than one
    role enum, because the two kinds of role are independent — an organiser who heads their
    family is both, and the table renders "Organiser · Head".
    """

    user_id: uuid.UUID
    username: str
    first_name: str
    last_name: str
    display_name: str
    initials: str
    avatar_thumb_url: str | None = None
    family: FamilyOut | None = None
    family_role: FamilyRole | None = None
    is_owner: bool
    is_organiser: bool
    must_change_password: bool
    #: Null means never — which is the state AC-6 asks about.
    last_login_at: datetime | None = None
    created_at: datetime


class OverviewOut(BaseModel):
    families: list[FamilyOut] = Field(default_factory=list)
    members: list[AdminMemberOut] = Field(default_factory=list)


class ResetPasswordIn(BaseModel):
    """Required, and required to be `true`: a reset invalidates someone's access, so the
    request says so out loud rather than being a bare POST that could be a stray click."""

    confirm: bool

    @field_validator("confirm")
    @classmethod
    def _must_confirm(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Confirm the reset.")
        return value


class ResetPasswordOut(BaseModel):
    """Returned exactly once. Never logged, never stored in plaintext, never re-retrievable."""

    temporary_password: str


# --- organisers --------------------------------------------------------------------------------


class OrganiserGrantIn(BaseModel):
    user_id: uuid.UUID


class OrganiserActorOut(BaseModel):
    user_id: uuid.UUID | None = None
    display_name: str | None = None


class OrganiserOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    initials: str
    avatar_thumb_url: str | None = None
    family: FamilyOut | None = None
    family_role: FamilyRole | None = None
    #: Always the owner. Null if that account has since been deleted — the grant outlives it.
    granted_by: OrganiserActorOut | None = None
    created_at: datetime


# --- instance settings ---------------------------------------------------------------------------


class InstanceSettingsOut(BaseModel):
    instance_name: str
    registration_open: bool
    invite_only: bool


class InstanceSettingsIn(BaseModel):
    instance_name: str | None = Field(default=None, max_length=120)
    registration_open: bool | None = None
    invite_only: bool | None = None

    @field_validator("instance_name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            # The login screen shows this as its heading; there has to be something to show.
            raise ValueError("The instance needs a name.")
        return cleaned


# --- Google API status ------------------------------------------------------------------------------


ApiStatus = Literal["ok", "denied", "quota", "unreachable", "unchecked", "configured"]


class ApiStatusOut(BaseModel):
    name: str
    key_type: Literal["browser", "server"]
    status: ApiStatus
    detail: str | None = None
    #: The one-line "usual cause" shown inline on a failure. Server-side so the explanation
    #: of a `denied` is the same everywhere it appears.
    hint: str | None = None


class GoogleStatusOut(BaseModel):
    checked_at: datetime | None = None
    checked_by: str | None = None
    browser_key_configured: bool
    server_key_configured: bool
    apis: list[ApiStatusOut] = Field(default_factory=list)


# --- stats -------------------------------------------------------------------------------------------


class SuggestionCountsOut(BaseModel):
    proposed: int = 0
    approved: int = 0
    scheduled: int = 0
    rejected: int = 0


class StatsOut(BaseModel):
    """One trip-scoped count per metric. Zeroes are shown, not hidden — and a metric whose
    feature does not exist yet reads zero rather than erroring, so the console works from M1
    onward."""

    families: int = 0
    members: int = 0
    invites_open: int = 0
    polls_open: int = 0
    polls_closed: int = 0
    suggestions_by_status: SuggestionCountsOut = Field(default_factory=SuggestionCountsOut)
    comments: int = 0
    itinerary_items: int = 0
    checkins: int = 0
    notifications_unread: int = 0


__all__ = [
    "BLOCKER_MISSING_DATES",
    "BACKWARD",
    "FORWARD",
    "STAGES",
    "VOTING_CATEGORIES",
    "VOTING_MODES",
    "AdminMemberOut",
    "ApiStatusOut",
    "CategorySettingIn",
    "CategorySettingOut",
    "CategorySettingPublicOut",
    "CategorySettingsPutIn",
    "GoogleStatusOut",
    "InstanceSettingsIn",
    "InstanceSettingsOut",
    "OrganiserGrantIn",
    "OrganiserOut",
    "OverviewOut",
    "ResetPasswordIn",
    "ResetPasswordOut",
    "StageChangeIn",
    "StagePatchOut",
    "StageTransitionOut",
    "StatsOut",
    "SuggestionCountsOut",
    "TripAdminOut",
    "TripPatchIn",
    "blockers_for",
    "trip_admin_out",
    "validate_timezone",
]
