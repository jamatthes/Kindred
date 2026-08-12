"""User-facing schemas: ``UserOut`` and the preferences pair.

``UserOut`` is the shape `plan/features/foundation/design.md` sketches. It carries the user's
family and the active trip so the shell knows the stage and the family colour without two
further calls on every load.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ThemePref = Literal["light", "dark", "system"]
Stage = Literal["planning", "holiday", "end"]
#: Family-level roles (revised 2026-08-11). Orthogonal to the trip-level owner/organiser pair.
FamilyRole = Literal["head", "spouse", "member"]
#: The onboarding gate (F-13). Resolved in `app/core/onboarding.py`; the client routes on
#: this field alone and never recomputes the precedence.
NextStep = Literal["change_password", "setup_trip", "setup_family", "app"]


class FamilyBrief(BaseModel):
    """The user's family. ``null`` on ``UserOut`` until the `families` feature ships."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    #: Token slot 1-24, mapping to `--family-1…24`. Not a colour value — the palette belongs to
    #: the design tokens, so DesignSync can retune it without a data migration. Exactly one of
    #: `color` / `color_custom` is set (2026-08-11 palette ruling); resolve with
    #: `familyColor(family)` client-side rather than branching on which.
    color: int | None = None
    color_custom: str | None = None
    role: FamilyRole


class TripBrief(BaseModel):
    """The single active trip. ``null`` only if the instance has no trip at all."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    stage: Stage
    start_date: date | None = None
    end_date: date | None = None
    timezone: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    first_name: str
    last_name: str
    display_name: str
    #: 256px rendition, or null for the initials badge. `families` FM-14.
    avatar_url: str | None = None
    #: 64px rendition — what map markers and member lists load.
    avatar_thumb_url: str | None = None
    #: First letter of the first name plus first letter of the last, uppercased; one letter
    #: for a mononym. Computed server-side so every surface renders the same badge.
    initials: str = ""
    is_platform_admin: bool
    #: Trip-level roles (revised 2026-08-11), carried here because the shell has to decide
    #: which controls to *render* and cannot derive them: the viewer may have no family at
    #: all, so there is no `MemberOut` of themselves to read it from. What they may *do* is
    #: still the server's decision — this only governs what is drawn.
    is_owner: bool = False
    is_organiser: bool = False
    must_change_password: bool
    #: **The onboarding gate.** Which top-level screen this session may see. The client routes
    #: on this and nothing else, so the forced password change and both first-login setup
    #: screens cannot be navigated around (F-13, `plan/architecture.md`).
    next_step: NextStep = "app"
    theme_pref: ThemePref
    locale: str
    family: FamilyBrief | None = None
    trip: TripBrief | None = None


class ProfilePatchIn(BaseModel):
    """`PATCH /me` — my own name (FM-11).

    All three optional, PATCH semantics: an omitted field is left alone. `display_name` is
    seeded from the other two at registration and separately editable afterwards, so a member
    who goes by something other than their given name can say so without breaking their
    initials badge.

    Deliberately absent: `username` (not editable in v1) and anything belonging to another
    user — editing someone else's name is `admin-console`'s, and there is no field here that
    could reach one.
    """

    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    display_name: str | None = Field(default=None, max_length=120)


class PreferencesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    theme_pref: ThemePref
    locale: str


class PreferencesIn(BaseModel):
    """PATCH body. Both fields optional; omitted fields are left unchanged."""

    theme_pref: ThemePref | None = None
    locale: str | None = Field(default=None, min_length=2, max_length=16)
