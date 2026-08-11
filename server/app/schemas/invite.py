"""Invite wire shapes.

Every account on a Kindred instance is created through one of these. There is no open sign-up
in v1, regardless of the `registration_open` setting (FM-7).

An invite is a **bearer credential**, and these schemas are shaped by that:

* the raw token appears exactly once, inside `InviteCreatedOut.url`, and is never stored —
  only its sha256 is, exactly as foundation does for session cookies;
* `InviteOut`, the listing shape, carries no token at all, raw or hashed;
* `InvitePreviewOut` is public, so an invalid token must reveal nothing. Every field except
  `instance_name` is null when `valid` is false — a probe cannot learn the trip's name, or
  even tell an unknown token from an expired one.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.family import INVITE_EXPIRY_CHOICES
from app.schemas.user import NextStep, UserOut

InviteMode = Literal["join", "create_family"]
InviteStatus = Literal["active", "used", "revoked", "expired"]
InviteInvalidReason = Literal[
    "expired", "used", "revoked", "unknown", "trip_ended", "family_missing"
]

#: 24 hours, 7 days, 30 days. A short list rather than a free number, so the UI is a select
#: and an operator cannot mint a ten-year invite by accident (FM-5).
ExpiryHours = Literal[24, 168, 720]

assert set(INVITE_EXPIRY_CHOICES) == {24, 168, 720}, "expiry choices drifted from the model"


class FamilyBriefOut(BaseModel):
    """Just enough of a family to name it on an invite. Never carries an address."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: int | None
    color_custom: str | None = None


class InviteCreateIn(BaseModel):
    """`family_id` null means "this invite creates a new family" (FM-6, main admin only)."""

    family_id: uuid.UUID | None = None
    expires_in_hours: ExpiryHours = 168


class InviteCreatedOut(BaseModel):
    """Returned **once**. `url` contains the raw token and cannot be recovered afterwards."""

    id: uuid.UUID
    #: `PUBLIC_BASE_URL` + `/join/<raw-token>`.
    url: str
    expires_at: datetime
    family: FamilyBriefOut | None = None


class InviteOut(BaseModel):
    """The listing shape. Deliberately tokenless — there is nothing here to leak."""

    id: uuid.UUID
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    created_at: datetime
    expires_at: datetime
    used_by: uuid.UUID | None = None
    used_by_name: str | None = None
    used_at: datetime | None = None
    revoked_at: datetime | None = None
    family: FamilyBriefOut | None = None
    status: InviteStatus


class InvitePreviewOut(BaseModel):
    """Public. Shown before the visitor is asked for anything at all.

    When `valid` is false every field except `instance_name` is null, so an invalid token
    reveals nothing about the trip or its families (FM-7). `instance_name` survives because
    it is already public on `GET /settings`.
    """

    instance_name: str
    valid: bool
    reason: InviteInvalidReason | None = None
    trip_name: str | None = None
    trip_stage: str | None = None
    mode: InviteMode | None = None
    family_name: str | None = None

    @model_validator(mode="after")
    def _invalid_reveals_nothing(self) -> InvitePreviewOut:
        """A belt-and-braces check on the rule the route is supposed to follow.

        The route builds the invalid case from a single constructor, so this should never
        fire; it exists because "reveals nothing" is the sort of guarantee that erodes when
        somebody adds a field later and forgets one branch.
        """
        if not self.valid:
            leaked = [
                name
                for name in ("trip_name", "trip_stage", "mode", "family_name")
                if getattr(self, name) is not None
            ]
            if leaked:
                raise ValueError(
                    f"an invalid invite preview must reveal nothing; leaked {leaked}"
                )
        return self


class InviteAcceptIn(BaseModel):
    """The registration form (FM-7).

    Accepts **no** `family_name` — the family is named on the setup screen that follows
    (FM-13) — and **no** `display_name`, which is derived server-side from the two name
    fields. Three name fields in front of someone who has not yet seen the app is a worse
    form than two screens.

    `extra="forbid"` so a client that sends either gets a `422` naming the field, rather than
    having it silently ignored and wondering why the family was not created.
    """

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    first_name: str = Field(min_length=1, max_length=80)
    #: The one optional field, labelled as such on screen rather than silently accepting an
    #: empty value. An empty last name gives a one-letter initials badge, which is correct.
    last_name: str = Field(default="", max_length=80)
    #: No minimum length, matching foundation's password rule (F-5). Non-empty only.
    password: str = Field(min_length=1, max_length=1024)
    password_confirm: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def _passwords_match(self) -> InviteAcceptIn:
        if self.password != self.password_confirm:
            raise ValueError("Those passwords do not match.")
        return self


class InviteAcceptOut(BaseModel):
    """Login's shape plus `next_step`, so the join screen routes without a second round trip.

    `next_step` is foundation's field (F-13) and its precedence rules are foundation's; this
    response only reports it. It is also on the `user` payload — carried at the top level as
    well purely so the join screen does not have to reach into a nested object to decide
    where to send someone.
    """

    user: UserOut
    csrf_token: str
    next_step: NextStep
