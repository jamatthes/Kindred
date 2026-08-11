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
from app.core.sessions import load_session, touch_session
from app.models import Family, FamilyMember, Session, Trip, User
from app.schemas.common import ApiError, forbidden, not_authenticated

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
    raise forbidden("You need an invite to this trip before you can see it.")


def require_family_admin(family_id: uuid.UUID):
    """Dependency factory: admin **of that family**, or the main admin (F-9)."""

    async def _dep(db: DbDep, user: CurrentUser, trip: ActiveTrip) -> User:
        if user.is_platform_admin or (trip is not None and trip.owner_user_id == user.id):
            return user
        membership = await db.scalar(
            select(FamilyMember).where(
                FamilyMember.family_id == family_id,
                FamilyMember.user_id == user.id,
                FamilyMember.role == "admin",
            )
        )
        if membership is None:
            raise forbidden("Only a family admin can do that.")
        return user

    return _dep


async def require_main_admin(user: CurrentUser, trip: ActiveTrip) -> User:
    """The platform admin, or the owner of the active trip (F-9)."""
    if user.is_platform_admin:
        return user
    if trip is not None and trip.owner_user_id == user.id:
        return user
    raise forbidden("Only the main admin can do that.")


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
