"""Invites, and the registration that consumes them (FM-5 to FM-8).

**Every account on a Kindred instance is created here.** There is no open sign-up in v1,
regardless of the `registration_open` setting — that setting exists so the policy can widen
later without a migration, and `admin-console` shows it as such (`requirements.md` NOTE).

The token is a bearer credential and is treated exactly as foundation treats session cookies:
`secrets.token_urlsafe(32)`, only the sha256 stored, the raw value returned once inside the
created invite's URL and never recoverable afterwards. Nothing in the listing shape carries a
token, raw or hashed.

Two routes are **public**, and that shapes them:

* `GET /invites/token/{token}` always answers `200`, never `404`. A `404` for an unknown token
  and a `200 {valid: false}` for an expired one would let a prober tell them apart; an invalid
  token reveals only the instance name, which `GET /settings` already gives away.
* `POST /invites/token/{token}/accept` is rate-limited by IP, because it creates accounts.

The router therefore cannot carry `enforce_password_change` at router level the way every
other feature router does — a logged-out visitor has no password to change. It is applied to
the three authenticated routes individually, which is the exception `foundation`'s composition
rule anticipates for a router with public members.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import settings
from app.core.security import generate_token, hash_password, hash_token
from app.core.sessions import create_session
from app.deps import (
    ActiveTrip,
    CurrentUser,
    DbDep,
    SessionDep,
    client_ip,
    enforce_password_change,
    is_organiser,
    load_membership,
    require_family_head_or_spouse,
    require_organiser,
    require_stage,
)
from app.models import (
    FAMILY_MANAGER_ROLES,
    ROLE_MEMBER,
    SETTING_INSTANCE_NAME,
    Family,
    FamilyMember,
    Invite,
    Setting,
    Trip,
    User,
    UserSettings,
    invite_status,
    is_invite_usable,
)
from app.routers.auth import _set_auth_cookies, build_user_out
from app.routers.families import broadcast_member_joined
from app.schemas.common import ApiError, forbidden
from app.schemas.family import derive_display_name
from app.schemas.invite import (
    FamilyBriefOut,
    InviteAcceptIn,
    InviteAcceptOut,
    InviteCreatedOut,
    InviteCreateIn,
    InviteOut,
    InvitePreviewOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invites", tags=["invites"])

#: The username recorded against a failed invite acceptance, so the shared `login_attempts`
#: limiter can count them without a failed registration silently rate-limiting *logins* for
#: whatever username the visitor was trying to claim. Not a valid username, on purpose.
INVITE_RATE_KEY = "@invite-accept"


# --- helpers ------------------------------------------------------------------------------


async def _instance_name(db: AsyncSession) -> str:
    """Already public on `GET /settings`, which is why an invalid preview may still say it."""
    value = await db.scalar(select(Setting.value).where(Setting.key == SETTING_INSTANCE_NAME))
    return value if isinstance(value, str) and value else "Kindred"


def _brief(family: Family | None) -> FamilyBriefOut | None:
    if family is None:
        return None
    return FamilyBriefOut(
        id=family.id, name=family.name, color=family.color, color_custom=family.color_custom
    )


async def _load_invite(db: AsyncSession, invite_id: uuid.UUID) -> Invite:
    invite = await db.scalar(select(Invite).where(Invite.id == invite_id))
    if invite is None:
        raise ApiError(404, "not_found", "That invite does not exist.")
    return invite


async def _name_of(db: AsyncSession, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    return await db.scalar(select(User.display_name).where(User.id == user_id))


async def _to_out(db: AsyncSession, invite: Invite) -> InviteOut:
    return InviteOut(
        id=invite.id,
        created_by=invite.created_by,
        created_by_name=await _name_of(db, invite.created_by),
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        used_by=invite.used_by,
        used_by_name=await _name_of(db, invite.used_by),
        used_at=invite.used_at,
        revoked_at=invite.revoked_at,
        family=_brief(invite.family),
        status=invite_status(invite),
    )


# --- authenticated routes -------------------------------------------------------------------


@router.get(
    "",
    response_model=list[InviteOut],
    dependencies=[Depends(enforce_password_change)],
    summary="Outstanding invites",
)
async def list_invites(
    db: DbDep,
    user: CurrentUser,
    trip: ActiveTrip,
    family_id: uuid.UUID | None = None,
) -> list[InviteOut]:
    """FM-5: a head or spouse sees their own family's invites; an organiser sees them all.

    The scope is *narrowed for the caller* rather than refused, because "list invites" means
    something different depending on who is asking, and a 403 for a head who omitted the query
    parameter would be an obstacle rather than a protection. A head asking for another
    family's list explicitly still gets a 403.
    """
    if trip is None:
        return []

    organiser = await is_organiser(db, user, trip)
    membership = await load_membership(db, user.id, trip.id)
    own_family_id = membership[0].id if membership else None
    manages_family = membership is not None and membership[1].role in FAMILY_MANAGER_ROLES

    if family_id is not None and not organiser:
        if not manages_family or family_id != own_family_id:
            raise forbidden("You can only see your own family's invites.")
    elif family_id is None and not organiser:
        if not manages_family:
            raise forbidden("Only a family's head or spouse can see invites.")
        family_id = own_family_id

    stmt = select(Invite).where(Invite.trip_id == trip.id).order_by(Invite.created_at.desc())
    if family_id is not None:
        stmt = stmt.where(Invite.family_id == family_id)

    invites = (await db.scalars(stmt)).unique().all()
    return [await _to_out(db, invite) for invite in invites]


@router.post(
    "",
    response_model=InviteCreatedOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(enforce_password_change),
        Depends(require_stage("planning", "holiday")),
    ],
    summary="Create an invite link",
)
async def create_invite(
    payload: InviteCreateIn, db: DbDep, user: CurrentUser, trip: ActiveTrip
) -> InviteCreatedOut:
    """FM-5 and FM-6. The permission depends on the body, which is why it is resolved here.

    `family_id` non-null is "join my family" and needs
    `require_family_head_or_spouse(family_id)`. `family_id` null is "create a new family" and
    needs `require_organiser` — **neither a head nor a spouse can ever invite into another
    family, nor mint a family-founding link**, and those are the same rule seen from two
    sides.

    A dependency cannot make this choice, because it does not see the body. The check is
    therefore in the handler, but it is still the same two dependency functions doing the
    deciding rather than a hand-rolled role comparison.
    """
    if trip is None:
        raise ApiError(409, "no_trip", "There is no trip to invite anyone to yet.")

    family: Family | None = None
    if payload.family_id is None:
        await require_organiser(db, user, trip)
    else:
        family = await db.get(Family, payload.family_id)
        if family is None or family.trip_id != trip.id:
            raise ApiError(404, "not_found", "That family does not exist.")
        await require_family_head_or_spouse(payload.family_id)(db, user, trip)

    raw = generate_token()
    invite = Invite(
        trip_id=trip.id,
        mode="create_family" if payload.family_id is None else "join",
        family_id=payload.family_id,
        token_hash=hash_token(raw),
        expires_at=datetime.now(UTC) + timedelta(hours=payload.expires_in_hours),
        created_by=user.id,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    return InviteCreatedOut(
        id=invite.id,
        # The one and only time the raw token is emitted. It is not stored and cannot be
        # recovered from the row; the UI says so next to the copy button.
        url=f"{settings.public_base_url.rstrip('/')}/join/{raw}",
        expires_at=invite.expires_at,
        family=_brief(family),
    )


@router.post(
    "/{invite_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        Depends(enforce_password_change),
        Depends(require_stage("planning", "holiday")),
    ],
    summary="Revoke an invite",
)
async def revoke_invite(
    invite_id: uuid.UUID, db: DbDep, user: CurrentUser, trip: ActiveTrip
) -> Response:
    """FM-5. Reversible by reissuing, so the UI uses undo rather than a confirm dialog."""
    invite = await _load_invite(db, invite_id)

    if invite.family_id is None:
        # Covers both a `create_family` invite and a `join` invite orphaned by a family
        # deletion. Only an organiser can delete a family, so they are the right person to
        # tidy up after one either way.
        await require_organiser(db, user, trip)
    else:
        await require_family_head_or_spouse(invite.family_id)(db, user, trip)

    if invite.used_by is not None:
        # Revoking an accepted invite would imply it could un-create the account it created.
        raise ApiError(
            409, "invite_already_used", "That invite has already been used."
        )

    if invite.revoked_at is None:
        invite.revoked_at = datetime.now(UTC)
        await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- public routes ---------------------------------------------------------------------------


@router.get(
    "/token/{token}",
    response_model=InvitePreviewOut,
    summary="What this invite link is for (public)",
)
async def preview_invite(token: str, db: DbDep) -> InvitePreviewOut:
    """FM-7. Shown before the visitor is asked for anything at all.

    Always `200`. An unknown token and an expired one produce the same shape with a different
    `reason`, so probing cannot distinguish them by status code, and neither reveals the trip
    or its families.
    """
    instance = await _instance_name(db)
    invite = await db.scalar(select(Invite).where(Invite.token_hash == hash_token(token)))

    if invite is None:
        return InvitePreviewOut(instance_name=instance, valid=False, reason="unknown")
    if invite.used_by is not None:
        return InvitePreviewOut(instance_name=instance, valid=False, reason="used")
    if invite.revoked_at is not None:
        return InvitePreviewOut(instance_name=instance, valid=False, reason="revoked")
    if not is_invite_usable(invite):
        return InvitePreviewOut(instance_name=instance, valid=False, reason="expired")

    trip = await db.get(Trip, invite.trip_id)
    if trip is not None and trip.stage == "end":
        # The trip is closed. The preview says so and the form is not rendered — a person
        # should learn this before filling in a registration form, not after submitting one.
        return InvitePreviewOut(instance_name=instance, valid=False, reason="trip_ended")

    if invite.family_missing:
        # The family this was for has been deleted. Say so before the form, not after — and
        # do not let it masquerade as an invitation to found a family.
        return InvitePreviewOut(
            instance_name=instance, valid=False, reason="family_missing"
        )

    return InvitePreviewOut(
        instance_name=instance,
        valid=True,
        trip_name=trip.name if trip else None,
        trip_stage=trip.stage if trip else None,
        mode="create_family" if invite.creates_family else "join",
        family_name=invite.family.name if invite.family else None,
    )


@router.post(
    "/token/{token}/accept",
    response_model=InviteAcceptOut,
    status_code=status.HTTP_201_CREATED,
    summary="Accept an invite and create an account (public)",
)
async def accept_invite(
    token: str,
    payload: InviteAcceptIn,
    request: Request,
    response: Response,
    db: DbDep,
    session: SessionDep,
) -> InviteAcceptOut:
    """FM-7. The only route in the product that creates a user.

    Everything below happens in one transaction, and the invite is claimed with a
    **conditional update** (`WHERE used_by IS NULL`) rather than a read-then-write. Two people
    opening the same single-use link and submitting together is not a hypothetical — it is
    what happens when a link is pasted into a family group chat — and a read-then-write would
    let both through.
    """
    ip = client_ip(request)

    if session is not None:
        # FM-8: say what will happen rather than silently switching accounts. The join screen
        # offers "Log out and continue" before it gets here.
        raise ApiError(
            409,
            "already_member",
            "You are already signed in. Log out first to accept this invite.",
        )

    limit = settings.rate_limit_login_per_minute
    if ip is not None and await ratelimit.count_recent_failures(db, ip=ip) >= limit:
        raise ApiError(
            429,
            "rate_limited",
            "Too many attempts. Wait a minute and try again.",
            headers={"Retry-After": str(ratelimit.retry_after_seconds())},
        )

    async def _refuse(status_code: int, code: str, message: str) -> ApiError:
        await ratelimit.record_attempt(
            db, username=INVITE_RATE_KEY, ip=ip, succeeded=False
        )
        await db.commit()
        return ApiError(status_code, code, message)

    invite = await db.scalar(select(Invite).where(Invite.token_hash == hash_token(token)))
    if not is_invite_usable(invite):
        raise await _refuse(
            409, "invite_invalid", "This invite link is no longer valid."
        )
    assert invite is not None  # narrowed by is_invite_usable

    trip = await db.get(Trip, invite.trip_id)
    if trip is not None and trip.stage == "end":
        raise await _refuse(409, "stage_forbidden", "This trip has finished.")

    family: Family | None = None
    if not invite.creates_family:
        family = await db.get(Family, invite.family_id) if invite.family_id else None
        if family is None:
            # `invites.family_id` is ON DELETE SET NULL, so a deleted family leaves the row
            # reportable rather than vanishing with it. `mode` is what stops this being
            # mistaken for a new-family invite and quietly sending the visitor to a family
            # setup screen they were never invited to.
            raise await _refuse(
                409,
                "invite_family_missing",
                "The family this invite was for no longer exists. Ask for a new link.",
            )

    username = payload.username.strip()
    taken = await db.scalar(
        select(User.id).where(func.lower(User.username) == username.lower())
    )
    if taken is not None:
        raise await _refuse(409, "username_taken", "That username is already in use.")

    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        display_name=derive_display_name(payload.first_name, payload.last_name),
        # Not a seeded password — they chose it a moment ago.
        must_change_password=False,
    )
    db.add(user)
    await db.flush()

    user_settings = UserSettings(user_id=user.id)
    if family is not None:
        db.add(FamilyMember(family_id=family.id, user_id=user.id, role=ROLE_MEMBER))
        # The one-time seed (FM-15). Read here and never again: changing the family default
        # later does not rewrite this person. Two gates still stand between it and a marker —
        # the browser's permission prompt and `holiday-stage`'s one-time disclosure.
        user_settings.live_location_enabled = family.member_location_default
    else:
        # No family exists yet, so there is no default to take. `POST /families/mine` sets
        # this to true when they finish setup, because by then they are its admin.
        user_settings.live_location_enabled = False
    db.add(user_settings)

    claimed = await db.execute(
        update(Invite)
        .where(Invite.id == invite.id, Invite.used_by.is_(None))
        .values(used_by=user.id, used_at=datetime.now(UTC))
    )
    if (claimed.rowcount or 0) != 1:
        # Somebody else claimed it between our check and now. Roll the whole thing back — a
        # half-registered account with no invite behind it is worse than a clear refusal.
        await db.rollback()
        raise ApiError(409, "invite_already_used", "That invite has already been used.")

    auth_session, raw_session = await create_session(
        db, user_id=user.id, user_agent=request.headers.get("user-agent"), ip=ip
    )
    result = InviteAcceptOut(
        user=await build_user_out(db, user, trip),
        csrf_token=auth_session.csrf_token,
        next_step="app" if family is not None else "setup_family",
    )
    await db.commit()

    if family is not None:
        # FM-12: member lists and counts update without a reload. Emitted after the commit,
        # never before — a client that refetches on receipt must not be able to read state
        # older than the event announcing it (`app/ws.py`).
        await broadcast_member_joined(db, family.id, user.id, trip)

    _set_auth_cookies(response, token=raw_session, csrf_token=auth_session.csrf_token)
    return result
