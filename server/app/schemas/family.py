"""Family and member wire shapes, and the two entitlement rules that govern them.

Two facts in this feature are private, and both are enforced **here**, in the serialiser,
rather than by the frontend choosing what to render:

1. **A family's full home address** — street address, coordinates and the geocode timestamp —
   is for members of that family and the main admin. Everyone else gets the coarse locality
   and nothing more (FM-4).
2. **Whether a person has consented to share their location** is itself private. A member of
   another family sees a marker or no marker, and cannot tell "not sharing" from "app closed"
   (`plan/features/families/design.md`).

Both are decided by :func:`family_detail_out` and :func:`member_out`, which are the only two
functions in the codebase that build these shapes. `plan/features/families/tasks.md` asks for
exactly that — "one function used by every route that returns a family, so it cannot be
forgotten on a new endpoint" — and the same reasoning applies to the WebSocket payloads,
which call the same functions rather than assembling their own dictionaries.

The entitled address fields are **absent** from the response for a caller who may not see
them, not present-and-null. That is why every route returning one of these declares
``**FAMILY_DETAIL_RESPONSE`` (or ``**FAMILY_RESPONSE``) instead of a bare ``response_model``:
the pair carries ``response_model_exclude_unset=True``, which is what turns "we did not set
this field" into "this key does not exist". A null would still say *there is an address here
and you cannot have it*; absence says nothing at all.
"""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Attachment, Family, FamilyMember, User

GeocodeStatus = Literal["pending", "ok", "not_found", "error"]
FamilyRole = Literal["admin", "member"]

#: Where the attachments router serves files from. Kept next to the serialiser because the
#: URL shape and the row it is built from have to agree.
ATTACHMENTS_URL_PREFIX = "/api/v1/attachments"

#: Spelled as an escape rather than typed literally: U+200D is invisible in source, and a
#: reviewer cannot check a character they cannot see.
ZERO_WIDTH_JOINER = "\u200d"


# --- names --------------------------------------------------------------------------------


def _first_grapheme(value: str) -> str:
    """The first user-perceived character of ``value``, or ``""``.

    "Grapheme cluster, not byte and not code point" matters for real names: a Devanagari
    letter followed by a vowel sign, or a Latin letter followed by a combining accent, is one
    character to the person whose name it is. Full UAX #29 segmentation would need a
    dependency; taking the first code point plus any trailing combining marks and
    zero-width joiners covers every case a name field realistically holds, and the shortfall
    is documented rather than silently wrong.
    """
    text = value.strip()
    if not text:
        return ""
    cluster = text[0]
    for char in text[1:]:
        if char == ZERO_WIDTH_JOINER or unicodedata.category(char) in {"Mn", "Mc", "Me"}:
            cluster += char
        elif cluster.endswith(ZERO_WIDTH_JOINER):
            cluster += char  # the far side of a joiner
        else:
            break
    return cluster


def initials(user: User) -> str:
    """The badge string: first letter of the first name, first letter of the last.

    One helper, used by every serialiser that emits a person — `MemberOut` here, and the
    live-location rows in `holiday-stage`. Computing it in two places is how somebody ends up
    with two different badges on two screens
    (`plan/features/families/tasks.md`, Phase 3).

    An empty ``last_name`` gives a one-letter badge. That is the correct answer for a mononym,
    not a degraded case — which is why `users.last_name` is not-null-and-possibly-empty rather
    than nullable.
    """
    first = _first_grapheme(user.first_name)
    last = _first_grapheme(user.last_name)
    return f"{first}{last}".upper()


def derive_display_name(first_name: str, last_name: str) -> str:
    """``"{first} {last}".strip()`` — the seed for `users.display_name` at registration.

    Derived rather than asked for, so nobody meets three name fields before they have seen
    the app (FM-7). It stays separately editable afterwards.
    """
    return f"{first_name.strip()} {last_name.strip()}".strip()


# --- who is asking ------------------------------------------------------------------------


@dataclass(frozen=True)
class Viewer:
    """The caller, reduced to the four facts the entitlement rules actually depend on.

    A frozen value rather than the `User` row, so a serialiser cannot reach past what it is
    entitled to consult and, say, decide something from `is_platform_admin` directly.
    """

    user_id: uuid.UUID
    #: The family the caller belongs to, or ``None`` mid-onboarding.
    family_id: uuid.UUID | None
    #: Platform admin or the trip's owner. Sees every family's address (FM-10).
    is_main_admin: bool
    #: Admin **of their own family** — not of any family.
    is_family_admin: bool

    def sees_full_address(self, family: Family) -> bool:
        """FM-4: their own family's address, or any if they are the main admin."""
        return self.is_main_admin or self.family_id == family.id

    def sees_consent_of(self, member: FamilyMember) -> bool:
        """The member themselves, their family admin, or the main admin."""
        if self.is_main_admin or member.user_id == self.user_id:
            return True
        return self.is_family_admin and self.family_id == member.family_id


def viewer_from(
    user: User, *, family_id: uuid.UUID | None, role: str | None, is_main_admin: bool
) -> Viewer:
    return Viewer(
        user_id=user.id,
        family_id=family_id,
        is_main_admin=is_main_admin,
        is_family_admin=role == "admin",
    )


# --- avatars ------------------------------------------------------------------------------


def attachment_url(attachment: Attachment | None, *, thumb: bool) -> str | None:
    """The URL for a rendition, or ``None`` when there is no picture.

    The stored filename carries a content hash, so replacing an avatar produces a different
    URL and no cache anywhere has to be invalidated
    (`plan/features/families/design.md` > Serving).
    """
    if attachment is None:
        return None
    stored = attachment.thumb_path if thumb else attachment.path
    if not stored:
        return None
    return f"{ATTACHMENTS_URL_PREFIX}/{attachment.id}/{PurePosixPath(stored).name}"


# --- schemas ------------------------------------------------------------------------------


class MemberOut(BaseModel):
    """One person, as every member list and map marker renders them."""

    user_id: uuid.UUID
    username: str
    first_name: str
    last_name: str
    display_name: str
    #: 256px rendition — the profile page.
    avatar_url: str | None = None
    #: 64px rendition — what member lists and map markers actually load.
    avatar_thumb_url: str | None = None
    #: Computed server-side so the map, the member list, the presence stack and the admin
    #: console cannot drift into showing the same person two ways.
    initials: str
    role: FamilyRole
    joined_at: datetime
    is_main_admin: bool
    #: The family admin's per-member switch. A permission, not a consent.
    location_sharing_allowed: bool
    #: The member's **own** consent. ``None`` unless the caller is that member, their family
    #: admin, or the main admin — whether someone has agreed to share is itself private.
    location_sharing_enabled: bool | None = None


class FamilyOut(BaseModel):
    """The coarse, non-sensitive shape. Safe to broadcast to the whole trip room."""

    id: uuid.UUID
    name: str
    color: int
    member_count: int
    #: The town from the geocode. This is what members of other families are shown, so the
    #: street address never has to leave the server for them.
    home_locality: str | None = None
    home_placed: bool
    geocode_status: GeocodeStatus
    location_sharing_allowed: bool


class FamilyDetailOut(FamilyOut):
    """`FamilyOut` plus the member list, the family's own policy, and — **only for a caller
    entitled to them** — the full address fields.

    The four address keys are absent, not null, for anyone else. See the module docstring for
    why, and `FAMILY_DETAIL_RESPONSE` for the mechanism.
    """

    members: list[MemberOut] = Field(default_factory=list)
    #: A family's internal policy, not something other families need in a list — which is why
    #: it is here and not on `FamilyOut`.
    member_location_default: bool
    #: A short code (`no_api_key`, `timeout`, …), never the address itself, so it is safe to
    #: show to any member: it is what tells them whether to offer a retry.
    geocode_error: str | None = None

    home_address: str | None = None
    home_lat: float | None = None
    home_lng: float | None = None
    home_geocoded_at: datetime | None = None


#: Spread into every route that returns one of these, so the exclude-unset behaviour the
#: address privacy rule depends on cannot be forgotten on a new endpoint.
FAMILY_RESPONSE = {"response_model": FamilyOut, "response_model_exclude_unset": True}
FAMILY_DETAIL_RESPONSE = {
    "response_model": FamilyDetailOut,
    "response_model_exclude_unset": True,
}


class FamilyCreateIn(BaseModel):
    """`POST /families` — the main admin creating a family for someone else (FM-1)."""

    name: str = Field(min_length=1, max_length=120)
    #: Omitted means "assign the lowest free slot". A taken slot is `409 color_taken`.
    color: int | None = Field(default=None, ge=1, le=8)
    home_address: str | None = Field(default=None, max_length=500)


class FamilyMineIn(BaseModel):
    """`POST /families/mine` — the family setup screen's only write (FM-13).

    No colour: it is assigned automatically, because someone naming their family on their
    first login has no idea which slots are free and should not be asked.
    """

    name: str = Field(min_length=1, max_length=120)
    home_address: str | None = Field(default=None, max_length=500)


class FamilyPatchIn(BaseModel):
    """PATCH semantics: an omitted field is left alone, which is not the same as null."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    color: int | None = Field(default=None, ge=1, le=8)


class LocationPolicyIn(BaseModel):
    """The family admin's two switches (FM-15).

    Neither writes to any `user_settings` row. `sharing_allowed` is a read-time filter, so
    turning it back on restores exactly the members who had consented rather than
    re-enabling people who had turned themselves off.
    """

    sharing_allowed: bool | None = None
    member_default: bool | None = None


class HomeIn(BaseModel):
    home_address: str = Field(min_length=1, max_length=500)


class MemberPatchIn(BaseModel):
    """Role and the family admin's per-member map switch.

    There is deliberately no field here that turns another user's sharing **on**. That
    absence is the invariant the whole location-privacy story rests on
    (`plan/features/families/design.md` > Members).
    """

    role: FamilyRole | None = None
    location_sharing_allowed: bool | None = None


# --- serialisers --------------------------------------------------------------------------


def member_out(
    member: FamilyMember,
    viewer: Viewer,
    *,
    main_admin_ids: frozenset[uuid.UUID] = frozenset(),
) -> MemberOut:
    """One member, with their consent state redacted unless the caller is entitled to it."""
    user = member.user
    return MemberOut(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        display_name=user.display_name,
        avatar_url=attachment_url(user.avatar, thumb=False),
        avatar_thumb_url=attachment_url(user.avatar, thumb=True),
        initials=initials(user),
        role=member.role,
        joined_at=member.created_at,
        is_main_admin=user.is_platform_admin or user.id in main_admin_ids,
        location_sharing_allowed=member.location_sharing_allowed,
        location_sharing_enabled=(
            _consent_of(member) if viewer.sees_consent_of(member) else None
        ),
    )


def _consent_of(member: FamilyMember) -> bool:
    """The member's own `user_settings.live_location_enabled`.

    Read through the eagerly-loaded relationship so the serialiser issues no query of its
    own. A missing row means the user has never had one written and has therefore never
    consented — ``False`` is the honest answer, not an error.
    """
    settings = member.user.settings
    return bool(settings.live_location_enabled) if settings is not None else False


def family_out(family: Family) -> FamilyOut:
    """The coarse shape. Never carries an address — this is what the socket broadcasts."""
    return FamilyOut(
        id=family.id,
        name=family.name,
        color=family.color,
        member_count=len(family.members),
        home_locality=family.home_locality,
        home_placed=family.home_placed,
        geocode_status=family.geocode_status,
        location_sharing_allowed=family.location_sharing_allowed,
    )


def family_detail_out(
    family: Family,
    viewer: Viewer,
    *,
    main_admin_ids: frozenset[uuid.UUID] = frozenset(),
) -> FamilyDetailOut:
    """The full shape, with the address fields present **only** for an entitled caller.

    The conditional is a `dict` spread rather than four assignments so that the four keys are
    either all set or all unset. A serialiser that could set three of them is a serialiser
    that will eventually set three of them.
    """
    private: dict[str, object] = {}
    if viewer.sees_full_address(family):
        private = {
            "home_address": family.home_address,
            "home_lat": family.home_lat,
            "home_lng": family.home_lng,
            "home_geocoded_at": family.home_geocoded_at,
        }

    members = sorted(family.members, key=lambda m: (m.role != "admin", m.created_at))
    return FamilyDetailOut(
        id=family.id,
        name=family.name,
        color=family.color,
        member_count=len(family.members),
        home_locality=family.home_locality,
        home_placed=family.home_placed,
        geocode_status=family.geocode_status,
        geocode_error=family.geocode_error,
        location_sharing_allowed=family.location_sharing_allowed,
        member_location_default=family.member_location_default,
        members=[member_out(m, viewer, main_admin_ids=main_admin_ids) for m in members],
        **private,
    )
