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
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # `user` imports this module for nothing, so the runtime import would cycle
    from app.models.user import User

#: `family_members.role`. The per-family admin is distinct from the platform/main admin.
FAMILY_ROLES = ("admin", "member")

#: `families.geocode_status`. `pending` means never attempted, which is why a family that has
#: had its address cleared goes back to it rather than to `not_found`.
GEOCODE_STATUSES = ("pending", "ok", "not_found", "error")

#: The palette defines eight slots (`--family-1…8`); a ninth family is refused rather than
#: silently reusing a colour.
MAX_COLOR_SLOTS = 8

#: Allowed invite lifetimes, in hours: 24 hours, 7 days, 30 days.
INVITE_EXPIRY_CHOICES = (24, 168, 720)


class Family(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "families"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("trips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Token slot 1-8, mapping to `--family-1…8`. A smallint rather than a hex colour so the
    #: design system can retune the palette without a data migration.
    color: Mapped[int] = mapped_column(SmallInteger, nullable=False)

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
            f"color BETWEEN 1 AND {MAX_COLOR_SLOTS}", name="ck_families_color_range"
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
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class Invite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "invites"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("trips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Null means "this invite creates a new family" (FM-6). `ON DELETE SET NULL`, so a
    #: deleted family leaves the invite reportable rather than vanishing with it.
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

    __table_args__ = (UniqueConstraint("token_hash", name="uq_invites_token_hash"),)

    @property
    def creates_family(self) -> bool:
        """A new-family invite (FM-6) rather than a join-this-family one (FM-5)."""
        return self.family_id is None


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


async def next_free_color(db: AsyncSession, trip_id: uuid.UUID) -> int | None:
    """The lowest colour slot 1-8 not in use on this trip, or ``None`` when all are taken.

    Lowest-first rather than random so a trip's first family is always `--family-1`: it makes
    a fresh install look deliberate, and it makes tests deterministic.
    """
    taken = set(
        (await db.execute(select(Family.color).where(Family.trip_id == trip_id)))
        .scalars()
        .all()
    )
    for slot in range(1, MAX_COLOR_SLOTS + 1):
        if slot not in taken:
            return slot
    return None
