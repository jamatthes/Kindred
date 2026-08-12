"""``families``, ``family_members`` and ``invites``.

Foundation created the first two bare so `require_member` could resolve membership before
this feature existed; migration `0002` gave them their real shape and added `invites`.

The three location columns here are two thirds of the visibility rule in
`plan/features/families/design.md`:

    visible(user) = families.location_sharing_allowed        -- family admin's master switch
                AND family_members.location_sharing_allowed  -- family admin's per-member switch
                AND user_settings.live_location_enabled      -- the member's own consent
                AND <a fresh live_locations row exists>      -- they are sharing right now

The first two live on this module and are written only by a family admin. The third lives on
`user_settings` and is written only by the member themselves. Nothing in this feature may
write it — a permission and a consent are different things.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # `user` imports this module for nothing, so the runtime import would cycle
    from app.models.user import User

#: `family_members.role` (revised 2026-08-11). Family-level roles, entirely independent of the
#: trip-level ones — the trip's owner and its organisers are also an ordinary head, spouse or
#: member of their own family, and hold no family powers elsewhere except the cross-family
#: ones their trip role gives them.
FAMILY_ROLES = ("head", "spouse", "member")

#: A spouse holds the head's powers over the family. The single exception is evaluated against
#: the **target** of an action rather than the actor's role — see :func:`spouse_may_act_on`.
ROLE_HEAD = "head"
ROLE_SPOUSE = "spouse"
ROLE_MEMBER = "member"

#: Roles that may manage the family they belong to.
FAMILY_MANAGER_ROLES = (ROLE_HEAD, ROLE_SPOUSE)

#: `families.geocode_status`. `pending` means never attempted, which is why a family that has
#: had its address cleared goes back to it rather than to `not_found`.
GEOCODE_STATUSES = ("pending", "ok", "not_found", "error")

#: The curated palette defines 24 slots (`--family-1…24`; grown from 8 on 2026-08-11, slots
#: 1-8 unchanged). Once every slot on a trip is taken, the 25th and later families get a
#: free-choice colour wheel (`Family.color_custom`) instead of a refusal — see
#: `plan/features/families/design.md` > Family colour palette.
MAX_COLOR_SLOTS = 24

#: `#RRGGBB` — the only shape `Family.color_custom` accepts.
HEX_COLOR_RE = r"^#[0-9A-Fa-f]{6}$"

#: Allowed invite lifetimes, in hours: 24 hours, 7 days, 30 days.
INVITE_EXPIRY_CHOICES = (24, 168, 720)

#: `invites.mode`. What the invite is *for*, stated rather than inferred — see migration
#: `0003` for why a nullable `family_id` could not carry it.
#:
#: Named rather than spelled out at each site because the onboarding gate now asks the same
#: question (`app/core/onboarding.py`), and a typo there would silently refuse every founder.
INVITE_MODE_CREATE_FAMILY = "create_family"
INVITE_MODES = ("join", INVITE_MODE_CREATE_FAMILY)


class Family(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "families"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("trips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Token slot 1-24, mapping to `--family-1…24`. A smallint rather than a hex colour so the
    #: design system can retune the palette without a data migration. Nullable since
    #: 2026-08-11: exactly one of `color` / `color_custom` is ever set, enforced by
    #: `ck_families_color_xor`.
    color: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    #: The overflow colour wheel's `#RRGGBB` value, set only when every palette slot on the
    #: trip was taken at pick time. Escapes the palette's tuning and distinguishability
    #: guarantees by design — accepted because it only occurs from the 25th family on.
    color_custom: Mapped[str | None] = mapped_column(String(7), nullable=True)

    home_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    home_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_geocoded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: The coarse town/locality from the geocode. This is what members of *other* families
    #: are shown, so the full street address never has to leave the server for them.
    home_locality: Mapped[str | None] = mapped_column(Text, nullable=True)
    geocode_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    geocode_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: The family admin's master switch. Read on every map query; turning it off removes the
    #: whole family from the map without touching anyone's own setting.
    location_sharing_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    #: Copied into `user_settings.live_location_enabled` exactly once, when a member joins.
    #: Never re-read afterwards — changing it does not rewrite an existing member.
    member_location_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    #: Eager by default: a family is almost never useful without its members, and a lazy
    #: load on an `AsyncSession` raises `MissingGreenlet` rather than quietly working.
    members: Mapped[list[FamilyMember]] = relationship(
        back_populates="family",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Mirrors migration `0002` exactly. The models are what `Base.metadata.create_all`
    # builds the test schema from, so a constraint declared only in the migration would be
    # enforced in production and absent under pytest — the one place it most needs to hold.
    __table_args__ = (
        # Case-insensitive per trip: "The Smiths" and "the smiths" are the same family to a
        # human, so they must be to the database.
        Index("uq_families_trip_name_lower", "trip_id", func.lower(name), unique=True),
        Index("uq_families_trip_color", "trip_id", "color", unique=True),
        CheckConstraint(
            f"geocode_status IN {GEOCODE_STATUSES}", name="ck_families_geocode_status"
        ),
        CheckConstraint(
            f"color IS NULL OR color BETWEEN 1 AND {MAX_COLOR_SLOTS}",
            name="ck_families_color_range",
        ),
        CheckConstraint(
            "(color IS NOT NULL AND color_custom IS NULL) OR "
            "(color IS NULL AND color_custom IS NOT NULL)",
            name="ck_families_color_xor",
        ),
    )

    @property
    def home_placed(self) -> bool:
        """True when the home has coordinates and can be drawn on the map."""
        return self.home_lat is not None and self.home_lng is not None


class FamilyMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "family_members"

    family_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Unique — a user belongs to exactly one family (`plan/overview.md`).
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default="member")
    #: The family admin's per-member switch. Lives here rather than on `users` because it is
    #: a fact about a person's place in a family, and must disappear with the membership.
    location_sharing_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    #: Deliberately **not** eager. `Family.members` is `selectin` and this is the other end of
    #: the same edge; making both eager would have every family load its members and every
    #: member load its family back. Callers that need it ask with `selectinload`.
    family: Mapped[Family] = relationship(back_populates="members")
    #: Eager: a membership row without the person it describes cannot be serialised, and
    #: every `MemberOut` needs the name, initials and avatar off `users`.
    user: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (
        # One family per user (`plan/overview.md`). A second membership row would corrupt
        # every permission check, which is why this is a database constraint and not a
        # convention.
        Index("uq_family_members_user_id", "user_id", unique=True),
        # **Exactly one head per family.** Two heads, neither able to act on the other under
        # the spouse asymmetry, is a deadlock nobody inside the family can unpick; zero heads
        # can only be repaired by an organiser. Both states are unreachable from here.
        Index(
            "uq_family_members_one_head",
            "family_id",
            unique=True,
            postgresql_where=text("role = 'head'"),
        ),
        CheckConstraint(f"role IN {FAMILY_ROLES}", name="ck_family_members_role"),
    )

    @property
    def is_head(self) -> bool:
        return self.role == ROLE_HEAD

    @property
    def manages_family(self) -> bool:
        """Head or spouse — the two roles that run a family (FM-9, FM-16)."""
        return self.role in FAMILY_MANAGER_ROLES


def spouse_may_act_on(actor: FamilyMember, target: FamilyMember) -> bool:
    """The spouse asymmetry, in one place (`plan/features/families/design.md`).

    A spouse has the head's powers over their family, with one exception: they may not remove
    the head, change the head's role, or change the head's visibility switches. Two people who
    can each remove the other is a family that can lock itself out in one click.

    Expressed against the **target** rather than the actor's role, and as a single predicate,
    because the alternative is three route-specific checks and a fourth route that forgets.
    A spouse acting on any other member — or on themselves — is unaffected.
    """
    return not (actor.role == ROLE_SPOUSE and target.role == ROLE_HEAD)


class Invite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "invites"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("trips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: `join` (FM-5) or `create_family` (FM-6). Stated rather than inferred from
    #: `family_id is null`, because `ON DELETE SET NULL` would otherwise turn a join invite
    #: into a family-founding one the moment its family was deleted — see migration `0003`.
    mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="join")
    #: The family being joined. Null for a `create_family` invite (there is none yet), and
    #: also null for a `join` invite whose family has since been deleted — which is why
    #: `mode` exists to tell those two apart.
    family_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("families.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: sha256 of the raw token, exactly as foundation stores session cookies. The raw value
    #: is returned once at creation and is not recoverable from this row.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    used_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    family: Mapped[Family | None] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_invites_token_hash"),
        CheckConstraint(f"mode IN {INVITE_MODES}", name="ck_invites_mode"),
    )

    @property
    def creates_family(self) -> bool:
        """A new-family invite (FM-6) rather than a join-this-family one (FM-5)."""
        return self.mode == INVITE_MODE_CREATE_FAMILY

    @property
    def family_missing(self) -> bool:
        """A `join` invite whose family has been deleted (`invite_family_missing`)."""
        return self.mode == "join" and self.family_id is None


def is_invite_usable(invite: Invite | None, *, now: datetime | None = None) -> bool:
    """`used_by is null and revoked_at is null and expires_at > now()`.

    A single predicate rather than four checks scattered across the preview, accept and
    revoke routes — those three must never disagree about what "usable" means.
    """
    if invite is None:
        return False
    if invite.used_by is not None or invite.revoked_at is not None:
        return False
    moment = now or datetime.now(UTC)
    expires = invite.expires_at
    if expires.tzinfo is None:  # a naive value from a raw driver round-trip
        expires = expires.replace(tzinfo=UTC)
    return expires > moment


def invite_status(invite: Invite, *, now: datetime | None = None) -> str:
    """`active` / `used` / `revoked` / `expired`, for the listing's status chip.

    Order matters: a revoked invite that has also expired reads as `revoked`, because that
    is the fact the admin acted on.
    """
    if invite.used_by is not None:
        return "used"
    if invite.revoked_at is not None:
        return "revoked"
    return "active" if is_invite_usable(invite, now=now) else "expired"


#: Why a member is not on the map, in the order the terms are checked. `None` means the three
#: terms all pass — which is *permission*, not a marker: a marker also needs a fresh
#: `live_locations` row, and that is `holiday-stage`'s to know about.
LOCATION_BLOCKED_FAMILY = "family_off"
LOCATION_BLOCKED_MEMBER = "member_off"
LOCATION_BLOCKED_CONSENT = "no_consent"


def location_block_reason(
    family: Family, member: FamilyMember, *, consented: bool
) -> str | None:
    """Which of the three terms stops this member appearing on the map, if any.

    ``visible(user)`` in `plan/features/families/design.md` is a conjunction of four facts;
    this evaluates the three that `families` owns and leaves the fourth — a fresh
    `live_locations` row — to `holiday-stage`, which owns the location data.

    Provided rather than left to the consumer because the hand-off note is explicit: that
    feature "must compute visibility from those terms rather than from `user_settings`
    alone". A rule re-derived at the point of use is a rule that will be derived differently.

    The order is fixed so the API can answer "why is nobody from this family on the map" with
    a single reason rather than a set. The boolean result is identical either way; the
    ordering exists for the explanation, not for correctness.
    """
    if not family.location_sharing_allowed:
        return LOCATION_BLOCKED_FAMILY
    if not member.location_sharing_allowed:
        return LOCATION_BLOCKED_MEMBER
    if not consented:
        return LOCATION_BLOCKED_CONSENT
    return None


async def next_free_color(db: AsyncSession, trip_id: uuid.UUID) -> int | None:
    """The lowest colour slot 1-24 not in use on this trip, or ``None`` when all are taken.

    Lowest-first rather than random so a trip's first family is always `--family-1`: it makes
    a fresh install look deliberate, and it makes tests deterministic. Only ``color`` is
    consulted — a family holding a `color_custom` overflow value never occupies or frees a
    slot, since it never held one.
    """
    taken = await taken_colors(db, trip_id)
    for slot in range(1, MAX_COLOR_SLOTS + 1):
        if slot not in taken:
            return slot
    return None


async def taken_colors(db: AsyncSession, trip_id: uuid.UUID) -> set[int]:
    """Every palette slot currently claimed on this trip.

    Shared by `next_free_color` and `GET /families/palette` (`routers/families.py`), so the
    exhaustion check the picker relies on and the check the create/patch routes enforce can
    never disagree about what "taken" means.
    """
    rows = await db.execute(
        select(Family.color).where(Family.trip_id == trip_id, Family.color.isnot(None))
    )
    return set(rows.scalars().all())
