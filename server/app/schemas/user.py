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
FamilyRole = Literal["admin", "member"]


class FamilyBrief(BaseModel):
    """The user's family. ``null`` on ``UserOut`` until the `families` feature ships."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    #: Token slot 1-8, mapping to `--family-1…8`. Not a colour value — the palette belongs to
    #: the design tokens, so DesignSync can retune it without a data migration.
    color: int | None = None
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
    display_name: str
    is_platform_admin: bool
    must_change_password: bool
    theme_pref: ThemePref
    locale: str
    family: FamilyBrief | None = None
    trip: TripBrief | None = None


class PreferencesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    theme_pref: ThemePref
    locale: str


class PreferencesIn(BaseModel):
    """PATCH body. Both fields optional; omitted fields are left unchanged."""

    theme_pref: ThemePref | None = None
    locale: str | None = Field(default=None, min_length=2, max_length=16)
