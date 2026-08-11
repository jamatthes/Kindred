"""The one server-owned onboarding gate (foundation F-13).

`plan/architecture.md`:

    Which top-level screen a session may see is decided server-side and returned as
    `auth/me`'s `next_step` (`change_password` | `setup_trip` | `setup_family` | `app`).
    The web shell routes on that field alone and never recomputes the gate from individual
    flags, so the forced password change and both first-login setup screens cannot be
    navigated around.

The value of putting it here is precisely that there is *one* of it. The client cannot be
wrong about the order, because it is never told the order — only the answer. And a feature
that adds a step adds it to :func:`resolve_next_step` rather than to a `useEffect` somewhere.

Ownership, which is deliberately split three ways:

===============  ===============================================================
`change_password`  foundation (F-5) — the seeded password must be replaced
`setup_trip`       `admin-console` (AC-0) — the main admin names the trip
`setup_family`     `families` (FM-13) — a new family's admin names their family
`app`              nobody; it is the absence of the other three
===============  ===============================================================

Each feature owns its *screen* and its *condition*; none of them owns the precedence, which
is the whole point.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FamilyMember, Invite, Trip, User, is_owner_of

NextStep = Literal["change_password", "setup_trip", "setup_family", "app"]


async def is_pending_family(db: AsyncSession, user: User) -> bool:
    """True for someone who accepted a `create_family` invite and has not finished setup.

    The predicate, stated once, because two things depend on it agreeing with itself: this
    gate, and `require_pending_family` — the single dependency that lets such a caller reach
    `POST /families/mine` while `require_member` refuses them everywhere else
    (`plan/architecture.md`; `plan/features/families/design.md`).

    Three conditions, all required:

    * they are in no family (so a member cannot acquire a second one this way);
    * an invite records them in `used_by` (so someone removed from the trip cannot re-admit
      themselves — their old membership row is gone, but no invite names them as unused);
    * that invite has `family_id is null` (so a family-scoped invite does not become a
      licence to found a family).
    """
    if user.is_platform_admin:
        # The seeded admin has no family and never accepted an invite. Sending them to a
        # family setup screen would lock them out of their own instance on first boot.
        return False

    has_family = await db.scalar(
        select(exists().where(FamilyMember.user_id == user.id))
    )
    if has_family:
        return False

    return bool(
        await db.scalar(
            select(
                exists().where(
                    Invite.used_by == user.id,
                    Invite.family_id.is_(None),
                )
            )
        )
    )


async def needs_trip_setup(db: AsyncSession, user: User, trip: Trip | None) -> bool:
    """Whether the **owner** still has to set the trip up (`admin-console` AC-0).

    Two conditions, and both matter:

    * the trip is not set up — `Trip.setup_complete`, which is `admin-console`'s predicate
      and lives on the model so this gate and `TripAdminOut.setup_complete` cannot disagree
      about what "set up" means;
    * the caller is the owner. Organisers never see this screen, per AC-0: they inherit a
      trip somebody else is expected to name, and sending them to a form the owner owns
      would hand them a decision that is not theirs.

    A missing trip is the fresh-install case, where only the seeded platform admin can do
    anything about it.

    .. note::
       The *slot in the precedence* is foundation's; the *condition* is `admin-console`'s.
       Only the body of this function changed when that feature landed — the client, the
       ordering, and `resolve_next_step` are all untouched, which is what the split was for.
    """
    if trip is None:
        return bool(user.is_platform_admin)
    return is_owner_of(trip, user) and not trip.setup_complete


async def resolve_next_step(
    db: AsyncSession, user: User, trip: Trip | None
) -> NextStep:
    """Which of the four top-level screens this session may see.

    Order matters and is asserted by tests: a user who must change their password sees that
    and nothing else, even if they would otherwise owe a setup step. Reversing any two of
    these would let someone past a gate the product means to be closed.
    """
    if user.must_change_password:
        return "change_password"
    if await needs_trip_setup(db, user, trip):
        return "setup_trip"
    if await is_pending_family(db, user):
        return "setup_family"
    return "app"
