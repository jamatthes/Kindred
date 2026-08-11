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
`setup_family`     `families` (FM-13) — a new family's head names their family, and so does
                   the trip's owner, without an invite (revised 2026-08-11)
`app`              nobody; it is the absence of the other three
===============  ===============================================================

Each feature owns its *screen* and its *condition*; none of them owns the precedence, which
is the whole point.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    INVITE_MODE_CREATE_FAMILY,
    FamilyMember,
    Invite,
    Trip,
    User,
    is_owner_of,
)

NextStep = Literal["change_password", "setup_trip", "setup_family", "app"]


async def is_pending_family(
    db: AsyncSession, user: User, trip: Trip | None = None
) -> bool:
    """True for someone who still owes the family setup step (FM-13).

    The predicate, stated once, because two things depend on it agreeing with itself: this
    gate, and `require_pending_family` — the single dependency that lets such a caller reach
    `POST /families/mine` while `require_member` refuses them everywhere else
    (`plan/architecture.md`; `plan/features/families/design.md`).

    **Being in no family is necessary for everybody**, so a member can never acquire a second
    family this way and the owner's admission is not a standing licence to found them. On top
    of that, one of two things must be true:

    * **an invited founder** — an invite records them in `used_by` (so someone removed from the
      trip cannot re-admit themselves: their membership row is gone, but no invite names them)
      and that invite has `mode = 'create_family'` (so a join invite is not a licence to found
      a family);
    * **the trip's owner** — revised 2026-08-11 per the user's ruling. Nobody invites the owner
      to their own instance, so ownership is the evidence that stands in for the invite. This
      function previously returned `False` for the platform admin outright, on the grounds that
      a family setup screen "would lock them out of their own instance on first boot" — which
      was true only while `POST /families/mine` also refused them. Admitting them to the route
      is the other half, and without it the owner reached the app with no family and no
      legitimate way to get one.

    The invite half keys on `mode`, not on `family_id is null`. Those stopped being the same
    question when `family_id` became `ON DELETE SET NULL`: deleting a family nulls the column
    on the consumed join invites of everyone who was in it, which under the old test would have
    handed each of them a licence to found a family — issued by an unrelated deletion.
    """
    has_family = await db.scalar(
        select(exists().where(FamilyMember.user_id == user.id))
    )
    if has_family:
        return False

    if is_owner_of(trip, user):
        return True

    return bool(
        await db.scalar(
            select(
                exists().where(
                    Invite.used_by == user.id,
                    Invite.mode == INVITE_MODE_CREATE_FAMILY,
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

    The owner of a fresh install now owes three of the four in turn — `change_password`,
    `setup_trip`, `setup_family`, then `app` — and `setup_trip` precedes `setup_family` for a
    reason stronger than taste: a family is created *on* a trip, and `POST /families/mine`
    answers `409 no_trip` without one. Sending the owner to family setup first would be a
    screen that cannot be completed.

    `app` is the absence of the other three, and as of 2026-08-11 it is reached family-less by
    exactly one kind of session: someone **removed** from their family, or whose family was
    deleted. They are not sent to family setup — they were never invited to found a family, and
    a setup screen there would let anyone removed from the trip re-admit themselves.
    `require_member` refuses them every route and the app renders "you are not on this trip".
    """
    if user.must_change_password:
        return "change_password"
    if await needs_trip_setup(db, user, trip):
        return "setup_trip"
    if await is_pending_family(db, user, trip):
        return "setup_family"
    return "app"
