"""Permission and stage dependencies.

Every access rule in Kindred lives here. `CLAUDE.md`: "Permissions + stage guards in FastAPI
dependencies, not in frontend logic." A route declares what it needs and never checks a role
inside the handler body:

    dependencies=[Depends(require_member), Depends(require_stage("planning", "holiday"))]

NOTE (implementation): `get_session` and `current_user` are needed by the auth router, so
they land in Phase 4 and the rest of this module in Phase 5. The file is one unit either way.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.onboarding import is_pending_family
from app.core.sessions import load_session, touch_session
from app.models import (
    FAMILY_MANAGER_ROLES,
    Family,
    FamilyMember,
    Session,
    Suggestion,
    Trip,
    TripOrganiser,
    User,
    is_owner_of,
)
from app.schemas.common import ApiError, forbidden, not_authenticated
from app.schemas.family import Viewer, viewer_from

DbDep = Annotated[AsyncSession, Depends(get_db)]


def client_ip(request: Request) -> str | None:
    """The client address, or ``None`` when there isn't one (ASGI test transports).

    Deliberately ignores ``X-Forwarded-For``: the deployment sits behind Caddy on the same
    host, and trusting a client-settable header would let an attacker sidestep the per-IP
    login limit by rotating it.
    """
    return request.client.host if request.client else None


async def get_session(request: Request, db: DbDep) -> Session | None:
    """Load the caller's session from the cookie, or ``None``.

    Returns ``None`` rather than raising, so unauthenticated access to a public route (such
    as `GET /settings`) is not an error.
    """
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    session = await load_session(db, token)
    if session is None:
        return None
    await touch_session(db, session)
    await db.commit()
    request.state.session = session
    return session


SessionDep = Annotated[Session | None, Depends(get_session)]


async def current_user(db: DbDep, session: SessionDep) -> User:
    """The authenticated user, or `401 not_authenticated`."""
    if session is None:
        raise not_authenticated()
    user = await db.get(User, session.user_id)
    if user is None:
        # The session outlived its user (deleted account). Treat it as no session at all.
        raise not_authenticated()
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def active_trip(db: DbDep) -> Trip | None:
    """The single active trip.

    v1 shows one trip, but the schema is multi-trip (`CLAUDE.md`), so this is the one place
    that resolves "the" trip — oldest first, deterministically. When multi-trip UI arrives,
    this becomes a path parameter and nothing else has to change.
    """
    return await db.scalar(select(Trip).order_by(Trip.created_at).limit(1))


ActiveTrip = Annotated[Trip | None, Depends(active_trip)]


async def load_membership(
    db: AsyncSession, user_id: uuid.UUID, trip_id: uuid.UUID | None
) -> tuple[Family, FamilyMember] | None:
    """The user's family and membership row on a trip, or ``None``."""
    if trip_id is None:
        return None
    stmt = (
        select(Family, FamilyMember)
        .join(FamilyMember, FamilyMember.family_id == Family.id)
        .where(FamilyMember.user_id == user_id, Family.trip_id == trip_id)
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    return (row[0], row[1]) if row else None


async def enforce_password_change(user: CurrentUser) -> User:
    """`403 password_change_required` while the user still has a seeded password.

    Applied as a **router-level** dependency on every router except `auth` and `health`, so a
    new feature router inherits it by default rather than by its author remembering (F-5).
    """
    if user.must_change_password:
        raise ApiError(
            403,
            "password_change_required",
            "Change your password to continue.",
        )
    return user


async def require_member(db: DbDep, user: CurrentUser, trip: ActiveTrip) -> User:
    """Any authenticated user who belongs to a family on the active trip (F-9).

    The platform admin always satisfies this: the seeded admin has no family until the
    `families` feature ships, and locking the admin out of their own instance on first boot
    would be absurd (`plan/features/foundation/design.md` > ordering dependency).
    """
    if user.is_platform_admin:
        return user
    if trip is not None and await load_membership(db, user.id, trip.id) is not None:
        return user
    # A distinct code, not the generic `forbidden`: the client has to tell "you are not on
    # this trip" (show the not-on-the-trip screen, re-read `auth/me`) apart from "you are on
    # it but may not do that" (show nothing; the control should not have been there).
    # `plan/features/families/design.md` names it in the edge-case table and in Phase 6's
    # verify step.
    raise ApiError(
        403, "not_on_trip", "You need an invite to this trip before you can see it."
    )


async def is_owner(user: User, trip: Trip | None) -> bool:
    """The trip's owner. `is_platform_admin` is the bootstrap bypass, unchanged from M0.

    The seeded account has to be able to reach its own instance before any trip exists, so it
    satisfies every trip-level check. That is a property of the *installation*, not of the
    role hierarchy, which is why it sits here rather than in `trip_organisers`.
    """
    return is_owner_of(trip, user)


async def is_organiser(db: AsyncSession, user: User, trip: Trip | None) -> bool:
    """The owner, or someone the owner appointed (`trip_organisers`, FM-17)."""
    if await is_owner(user, trip):
        return True
    if trip is None:
        return False
    return (
        await db.scalar(
            select(TripOrganiser.id).where(
                TripOrganiser.trip_id == trip.id, TripOrganiser.user_id == user.id
            )
        )
    ) is not None


async def require_owner(user: CurrentUser, trip: ActiveTrip) -> User:
    """The owner alone. **Used only by organiser management** (`admin-console`, FM-17).

    Deliberately narrower than `require_organiser`: an organiser who could appoint organisers
    could unappoint the owner's choices, and there would be no way back. This is the one power
    the owner does not delegate, and it is a separate dependency so that fact is visible at
    every route that needs it rather than buried in a role comparison.
    """
    if await is_owner(user, trip):
        return user
    raise ApiError(403, "owner_only", "Only the trip's owner can do that.")


async def require_organiser(db: DbDep, user: CurrentUser, trip: ActiveTrip) -> User:
    """Every cross-family power: the owner, or an organiser they appointed.

    This is what the pre-2026-08-11 docs called `require_main_admin`; every "main admin"
    permission in a feature document means this unless it says otherwise.
    """
    if await is_organiser(db, user, trip):
        return user
    raise forbidden("Only the trip's owner or an organiser can do that.")


def require_family_head_or_spouse(family_id: uuid.UUID):
    """Dependency factory: **head or spouse of that family**, or an organiser.

    The spouse asymmetry is *not* enforced here, and could not be: it depends on the target of
    the action, not on the actor's role, so a spouse is admitted to the route and refused only
    when the person they are acting on is the head (`models.family.spouse_may_act_on`).
    Enforcing it at the door would lock a spouse out of the nine-tenths of the route that is
    theirs to use.
    """

    async def _dep(db: DbDep, user: CurrentUser, trip: ActiveTrip) -> User:
        if await is_organiser(db, user, trip):
            return user
        membership = await db.scalar(
            select(FamilyMember).where(
                FamilyMember.family_id == family_id,
                FamilyMember.user_id == user.id,
                FamilyMember.role.in_(FAMILY_MANAGER_ROLES),
            )
        )
        if membership is None:
            raise forbidden("Only this family's head or spouse can do that.")
        return user

    return _dep


async def require_family_manager(
    family_id: uuid.UUID, db: DbDep, user: CurrentUser, trip: ActiveTrip
) -> User:
    """`require_family_head_or_spouse`, resolving the family from the route's path parameter.

    NOTE (implementation, `families` Phase 5): `plan/features/foundation/design.md` specifies
    this as a factory taking `family_id`, which works when the id is known where the route is
    declared and not when it arrives in the path — a factory is evaluated at import time and
    the request does not exist yet. This is the same rule with the id declared as a dependency
    parameter, which is how FastAPI hands a path value to a dependency. The factory stays for
    callers that do have the id in hand.
    """
    return await require_family_head_or_spouse(family_id)(db, user, trip)


async def require_pending_family(db: DbDep, user: CurrentUser, trip: ActiveTrip) -> User:
    """The single route in the product a user with no family may call (`families` FM-13).

    `require_member` refuses anyone without a family everywhere, which includes someone who
    has accepted a new-family invite but not yet named their family — and, from 2026-08-11, the
    trip's owner, who takes the same setup step without an invite because nobody invited them
    to their own instance. `POST /families/mine` is the one exception, and this is it.
    `plan/architecture.md` states the rule and the reason it is stated at all: "a second route
    in this category is a decision to be documented, not a quiet exemption."

    The predicate itself lives in `app/core/onboarding.py`, shared with the `next_step` gate,
    so the screen a user is sent to and the route that screen calls can never disagree about
    who is allowed to be there. `trip` is passed for the same reason: ownership is a fact about
    a trip, and a dependency that resolved it differently from the gate would send the owner to
    a screen whose only button is refused.
    """
    if await is_pending_family(db, user, trip):
        return user
    raise forbidden("Only someone setting up a new family can do that.")


async def can_edit_suggestion(
    db: AsyncSession, user: User, trip: Trip | None, suggestion: Suggestion
) -> bool:
    """The ownership rule for a suggestion, as a predicate.

    Three ways in (`map-suggestions/requirements.md` > Permissions): the **author**; the **head
    or spouse** of the author's family, who may tidy up after their own household; and an
    **organiser**, who may edit anything. A member of another family may not, whatever their
    role inside it — a family-level role governs a family, never the trip.

    Separate from the dependency below because the same question is asked twice per response:
    once at the door, and once per row when serialising `can_edit`, which the UI renders. One
    predicate means the flag and the enforcement cannot disagree.
    """
    if await is_organiser(db, user, trip):
        return True
    if suggestion.created_by is not None and suggestion.created_by == user.id:
        return True
    if suggestion.created_by is None:
        # Authored by an account that has since been deleted. Nobody inherits it; an organiser
        # (handled above) is the only route left, which is what keeps a stranger's proposal
        # from becoming editable by whoever happens to be reading it.
        return False
    author_family = await db.scalar(
        select(FamilyMember.family_id).where(FamilyMember.user_id == suggestion.created_by)
    )
    if author_family is None:
        return False
    mine = await db.scalar(
        select(FamilyMember).where(
            FamilyMember.family_id == author_family,
            FamilyMember.user_id == user.id,
            FamilyMember.role.in_(FAMILY_MANAGER_ROLES),
        )
    )
    return mine is not None


async def require_can_edit_suggestion(
    suggestion_id: uuid.UUID, db: DbDep, user: CurrentUser, trip: ActiveTrip
) -> Suggestion:
    """Author, head or spouse of the author's family, or an organiser — else `403`.

    Declared with `suggestion_id` as a parameter rather than as a factory taking it, for the
    reason `require_family_manager` records above: a factory is evaluated at import time, and
    the path value does not exist yet. Returns the loaded row so the handler does not fetch it
    a second time.
    """
    suggestion = await db.get(Suggestion, suggestion_id)
    if suggestion is None or (trip is not None and suggestion.trip_id != trip.id):
        # 404 before 403 on a row that is not there at all: a permission error would tell an
        # outsider that an id they guessed exists.
        raise ApiError(404, "not_found", "That suggestion does not exist.")
    if not await can_edit_suggestion(db, user, trip, suggestion):
        raise forbidden("You can only change a suggestion from your own family.")
    return suggestion


async def current_viewer(db: DbDep, user: CurrentUser, trip: ActiveTrip) -> Viewer:
    """The caller reduced to what the family serialisers are allowed to consult.

    Resolved once per request, here, rather than in each route: the address rule and the
    consent rule are privacy guarantees, and a route that assembled its own `Viewer` could
    assemble a more generous one.
    """
    membership = None
    if trip is not None:
        membership = await load_membership(db, user.id, trip.id)
    family, member = membership if membership is not None else (None, None)
    return viewer_from(
        user,
        family_id=family.id if family else None,
        role=member.role if member else None,
        is_owner=await is_owner(user, trip),
        is_organiser=await is_organiser(db, user, trip),
    )


ViewerDep = Annotated[Viewer, Depends(current_viewer)]


def require_stage(*stages: str):
    """Dependency factory: reject `409 stage_forbidden` outside the allowed stages.

    Applied to every mutating route in every feature. That, and only that, is what makes the
    End stage read-only — there is no per-route special-casing anywhere.
    """

    allowed = frozenset(stages)

    async def _dep(trip: ActiveTrip) -> Trip | None:
        if trip is None:
            return None
        if trip.stage not in allowed:
            raise ApiError(
                409,
                "stage_forbidden",
                f"This trip is in the {trip.stage} stage and cannot be changed.",
            )
        return trip

    return _dep
