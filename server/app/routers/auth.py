"""Authentication: login, logout, me, password change (F-3 to F-6).

This router is **exempt** from `enforce_password_change`: a user who must change their
password has to be able to read `me`, change it, and log out. Every other router carries the
guard at router level.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import settings
from app.core.onboarding import resolve_next_step
from app.core.security import (
    check_needs_rehash,
    hash_password,
    verify_dummy,
    verify_password,
)
from app.core.sessions import (
    create_session,
    revoke_session,
    revoke_user_sessions,
    sweep_expired_sessions,
)
from app.deps import ActiveTrip, CurrentUser, DbDep, SessionDep, client_ip, load_membership
from app.models import Trip, User
from app.schemas.auth import LoginIn, LoginOut, PasswordChangeIn
from app.schemas.common import (
    CODE_PASSWORD_UNCHANGED,
    CODE_RATE_LIMITED,
    ApiError,
    invalid_credentials,
    not_authenticated,
)
from app.schemas.family import initials
from app.schemas.family import attachment_url as avatar_url
from app.schemas.user import FamilyBrief, TripBrief, UserOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

#: Read by the SPA and echoed in `X-CSRF-Token`, so it is deliberately NOT httpOnly.
CSRF_COOKIE_NAME = "kindred_csrf"


async def build_user_out(db: AsyncSession, user: User, trip: Trip | None) -> UserOut:
    """`UserOut` with the family, trip and onboarding gate the shell needs, in one call.

    `next_step` is resolved here rather than derived by the client from
    `must_change_password` and friends: the client is told the answer, never the precedence
    (F-13, `app/core/onboarding.py`).
    """
    family_brief = None
    if trip is not None:
        membership = await load_membership(db, user.id, trip.id)
        if membership is not None:
            family, member = membership
            family_brief = FamilyBrief(
                id=family.id, name=family.name, color=family.color, role=member.role
            )
    return UserOut(
        id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        display_name=user.display_name,
        avatar_url=avatar_url(user.avatar, thumb=False),
        avatar_thumb_url=avatar_url(user.avatar, thumb=True),
        initials=initials(user),
        is_platform_admin=user.is_platform_admin,
        must_change_password=user.must_change_password,
        next_step=await resolve_next_step(db, user, trip),
        theme_pref=user.theme_pref,
        locale=user.locale,
        family=family_brief,
        trip=TripBrief.model_validate(trip) if trip is not None else None,
    )


def _set_auth_cookies(response: Response, *, token: str, csrf_token: str) -> None:
    """Set the session and CSRF cookies.

    ``secure=True`` is unconditional: the deployment is HTTPS-only, and browsers treat
    `http://localhost` as a secure context, so dev is unaffected. Making it conditional would
    mean a misconfiguration could silently ship an insecure cookie to production.
    """
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=max_age,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        max_age=max_age,
        httponly=False,  # the SPA must read it to echo it back
        secure=True,
        samesite="lax",
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


@router.post("/login", response_model=LoginOut, summary="Log in")
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: DbDep,
    trip: ActiveTrip,
) -> LoginOut:
    ip = client_ip(request)
    username = ratelimit.normalise_username(payload.username)

    # Lazy sweeps live here because login is the only route that grows either table.
    await sweep_expired_sessions(db)
    await ratelimit.sweep_old_attempts(db)

    if await ratelimit.is_rate_limited(db, username=username, ip=ip):
        await db.commit()
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            CODE_RATE_LIMITED,
            "Too many attempts. Wait a minute and try again.",
            headers={"Retry-After": str(ratelimit.retry_after_seconds())},
        )

    user = await db.scalar(select(User).where(func.lower(User.username) == username))

    if user is None:
        # Burn an equivalent hash verification so "no such user" and "wrong password" cost
        # the same (F-3: the response never reveals whether the username exists).
        verify_dummy(payload.password)
        await ratelimit.record_attempt(db, username=username, ip=ip, succeeded=False)
        await db.commit()
        raise invalid_credentials()

    if not verify_password(user.password_hash, payload.password):
        await ratelimit.record_attempt(db, username=username, ip=ip, succeeded=False)
        await db.commit()
        raise invalid_credentials()

    # --- authenticated from here ---------------------------------------------------------
    if check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    await ratelimit.record_attempt(db, username=username, ip=ip, succeeded=True)
    await ratelimit.clear_failures(db, username)

    # Session fixation: any session the caller already held dies here, so a cookie planted
    # before login cannot survive it.
    await revoke_user_sessions(db, user.id)

    session, token = await create_session(
        db,
        user_id=user.id,
        user_agent=request.headers.get("user-agent"),
        ip=ip,
    )
    result = LoginOut(
        user=await build_user_out(db, user, trip), csrf_token=session.csrf_token
    )
    await db.commit()

    _set_auth_cookies(response, token=token, csrf_token=session.csrf_token)
    return result


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Log out")
async def logout(db: DbDep, session: SessionDep) -> Response:
    if session is not None:
        await revoke_session(db, session.id)
        await db.commit()
    # The cookies are cleared either way: a caller with a stale cookie asking to log out
    # should end up logged out, not with a 401.
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_auth_cookies(response)
    return response


@router.get("/me", response_model=UserOut, summary="The current user")
async def me(db: DbDep, user: CurrentUser, trip: ActiveTrip) -> UserOut:
    return await build_user_out(db, user, trip)


@router.post(
    "/password", status_code=status.HTTP_204_NO_CONTENT, summary="Change my own password"
)
async def change_password(
    payload: PasswordChangeIn,
    db: DbDep,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    if session is None:  # pragma: no cover — current_user already guarantees a session
        raise not_authenticated()

    if not verify_password(user.password_hash, payload.current_password):
        # 400, not 401, per F-6: the caller *is* authenticated; the submitted value is wrong.
        raise ApiError(400, "invalid_credentials", "Your current password is incorrect.")

    if payload.new_password == payload.current_password:
        raise ApiError(
            400, CODE_PASSWORD_UNCHANGED, "Your new password must differ from the current one."
        )

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    # Every other session dies; the caller's survives, so changing a password does not log
    # you out of the tab you are using (F-5/F-6).
    await revoke_user_sessions(db, user.id, except_session_id=session.id)
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
