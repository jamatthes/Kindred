"""The admin console's API (AC-1 to AC-13).

Every route here is `require_organiser` — the owner or someone they appointed — except the
Organisers section, which is `require_owner`, and `PATCH /admin/settings`, which is
`require_owner` because instance settings are platform-level rather than trip-level
(rulings, 2026-08-11). Mutating trip data additionally carries
`require_stage("planning", "holiday")`, which is the whole of what makes the End stage a
freeze; nothing in this file mentions `end`.

**Stage transitions are not here.** They have exactly one endpoint,
`PATCH /api/v1/trips/{trip_id}/stage`, owned by `holiday-stage` and implemented in
`routers/trips.py`. This router computes the affordances (`can_advance_to`, `blockers`) that
the console's stepper renders; it does not execute the change.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import aliased, selectinload

from app import ws
from app.deps import (
    ActiveTrip,
    CurrentUser,
    DbDep,
    enforce_password_change,
    is_owner,
    require_member,
    require_organiser,
    require_owner,
    require_stage,
)
from app.core import ratelimit
from app.core.config import settings
from app.core.security import hash_password
from app.core.seed import seed_category_settings
from app.core.settings_store import get_setting, set_setting
from app.core.sessions import revoke_user_sessions
from app.core.wordlist import generate_temporary_password
from app.models import (
    SETTING_INSTANCE_NAME,
    SETTING_INVITE_ONLY,
    SETTING_REGISTRATION_OPEN,
    VOTING_CATEGORIES,
    Family,
    FamilyMember,
    Invite,
    Trip,
    TripCategorySetting,
    TripOrganiser,
    TripStageTransition,
    User,
)
from app.routers.families import (
    reject_leaving_the_family_headless,
    reject_touching_the_owner,
)
from app.services.google import (
    ERROR_NO_API_KEY,
    PROBE_HINTS,
    ProbeProtocol,
    get_probe,
)
from app.schemas.admin import (
    AdminMemberOut,
    ApiStatusOut,
    CategorySettingOut,
    CategorySettingPublicOut,
    CategorySettingsPutIn,
    OrganiserActorOut,
    OrganiserGrantIn,
    OrganiserOut,
    GoogleStatusOut,
    InstanceSettingsIn,
    InstanceSettingsOut,
    OverviewOut,
    ResetPasswordIn,
    ResetPasswordOut,
    StatsOut,
    StageActorOut,
    StageTransitionOut,
    TripAdminOut,
    TripPatchIn,
    trip_admin_out,
)
from app.schemas.common import CODE_RATE_LIMITED, ApiError
from app.schemas.family import attachment_url, family_out, initials

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(enforce_password_change), Depends(require_organiser)],
)

#: Raised when a PATCH would leave the trip with an end date before its start date. Checked
#: against the *merged* values, because a partial update can send either one alone.
CODE_VALIDATION_ERROR = "validation_error"


def _require_trip(trip: Trip | None) -> Trip:
    if trip is None:
        raise ApiError(404, "not_found", "There is no trip yet.")
    return trip


# --- Section 1: the trip ---------------------------------------------------------------------


@router.get("/trip", response_model=TripAdminOut, summary="The trip and its affordances")
async def read_trip(trip: ActiveTrip) -> TripAdminOut:
    return trip_admin_out(_require_trip(trip))


@router.patch(
    "/trip",
    response_model=TripAdminOut,
    summary="Edit the trip's name, dates or timezone",
    dependencies=[Depends(require_stage("planning", "holiday"))],
)
async def patch_trip(
    payload: TripPatchIn, db: DbDep, trip: ActiveTrip
) -> TripAdminOut:
    """AC-2, and the write behind the AC-0 setup screen.

    The setup screen uses this route rather than a parallel one: a second endpoint for the
    first save would be a second place for the same validation to drift. A trip that has
    never been set up is by definition in Planning, so the stage guard is already satisfied
    and needs no exemption.
    """
    current = _require_trip(trip)
    changes = payload.model_dump(exclude_unset=True)

    # The cross-field rule has to be checked against what the row will *become*: a PATCH
    # carrying only `end_date` is the ordinary way to make the range invalid, and the schema
    # cannot see the stored start date.
    start = changes.get("start_date", current.start_date)
    end = changes.get("end_date", current.end_date)
    if start and end and end < start:
        raise ApiError(
            422,
            CODE_VALIDATION_ERROR,
            "The end date cannot be before the start date.",
        )

    for field, value in changes.items():
        setattr(current, field, value)
    await db.commit()
    await db.refresh(current)

    if changes:
        # The name is in every header and on the invite preview; the dates drive the
        # timeline. A client holding a stale copy would show yesterday's trip.
        await ws.broadcast(
            current.id,
            "trip.updated",
            {
                "trip": {
                    "id": str(current.id),
                    "name": current.name,
                    "stage": current.stage,
                    "start_date": current.start_date.isoformat()
                    if current.start_date
                    else None,
                    "end_date": current.end_date.isoformat() if current.end_date else None,
                    "timezone": current.timezone,
                }
            },
        )

    return trip_admin_out(current)


@router.get(
    "/trip/stage-history",
    response_model=list[StageTransitionOut],
    summary="Who moved the trip between stages, and when",
)
async def read_stage_history(db: DbDep, trip: ActiveTrip) -> list[StageTransitionOut]:
    """AC-3/AC-4's record. Newest first — the last thing that happened is the thing being
    checked, nine times in ten."""
    current = _require_trip(trip)
    rows = (
        (
            await db.execute(
                select(TripStageTransition, User)
                .outerjoin(User, User.id == TripStageTransition.changed_by)
                .where(TripStageTransition.trip_id == current.id)
                .order_by(TripStageTransition.created_at.desc())
            )
        )
        .tuples()
        .all()
    )
    return [
        StageTransitionOut(
            from_stage=row.from_stage,
            to_stage=row.to_stage,
            direction=row.direction,
            # Null rather than absent when the account is gone: the transition still
            # happened, and "someone who has since left" is the honest rendering.
            changed_by=(
                StageActorOut(user_id=actor.id, display_name=actor.display_name)
                if actor is not None
                else None
            ),
            created_at=row.created_at,
        )
        for row, actor in rows
    ]


# --- Section 3: category voting modes ----------------------------------------------------------


async def _ensure_category_rows(db: DbDep, trip: Trip) -> list[TripCategorySetting]:
    """Read the five rows, creating any that are missing first.

    Self-healing rather than trusting the seed (AC-5's edge case): a trip created before the
    seeding rule existed would otherwise render a partially blank editor, and "the row is
    missing" is not a state any UI should have to have an opinion about. The insert is
    `ON CONFLICT DO NOTHING` against the unique `(trip_id, category)`, so two readers racing
    produce one row, not an error for the loser.
    """
    rows = (
        (
            await db.execute(
                select(TripCategorySetting).where(TripCategorySetting.trip_id == trip.id)
            )
        )
        .scalars()
        .all()
    )
    if len(rows) < len(VOTING_CATEGORIES):
        await seed_category_settings(db, trip)
        await db.commit()
        rows = (
            (
                await db.execute(
                    select(TripCategorySetting).where(TripCategorySetting.trip_id == trip.id)
                )
            )
            .scalars()
            .all()
        )
    order = {category: index for index, category in enumerate(VOTING_CATEGORIES)}
    return sorted(rows, key=lambda row: order.get(row.category, len(order)))


async def _existing_vote_count(db: DbDep, trip: Trip, category: str) -> int:
    """How many votes already exist in a category — the number AC-5's confirm names.

    Every source table belongs to a feature that has not shipped: `poll_scores` arrives with
    `polls` (M2) and `suggestion_votes` with `map-suggestions` (M3). Zero is the honest
    answer until then, and it is returned rather than the endpoint erroring, so the console
    works from M1 onward. Each feature replaces its own branch here as part of its tasks.
    """
    return 0


@router.get(
    "/category-settings",
    response_model=list[CategorySettingOut],
    summary="How each category is voted on, with the vote counts behind the warning",
)
async def read_category_settings(db: DbDep, trip: ActiveTrip) -> list[CategorySettingOut]:
    current = _require_trip(trip)
    rows = await _ensure_category_rows(db, current)
    return [
        CategorySettingOut(
            category=row.category,
            voting_mode=row.voting_mode,
            existing_vote_count=await _existing_vote_count(db, current, row.category),
        )
        for row in rows
    ]


@router.put(
    "/category-settings",
    response_model=list[CategorySettingOut],
    summary="Set the voting mode for one or more categories",
    dependencies=[Depends(require_stage("planning", "holiday"))],
)
async def put_category_settings(
    payload: CategorySettingsPutIn, db: DbDep, trip: ActiveTrip
) -> list[CategorySettingOut]:
    """AC-5. Existing votes are kept, never deleted — the confirm the UI shows says so, and
    this route is what makes that promise true."""
    current = _require_trip(trip)
    rows = {row.category: row for row in await _ensure_category_rows(db, current)}

    changed = False
    for wanted in payload.settings:
        row = rows[wanted.category]
        if row.voting_mode != wanted.voting_mode:
            row.voting_mode = wanted.voting_mode
            changed = True
    await db.commit()

    result = await read_category_settings(db, current)
    if changed:
        # Every voting UI in the product renders from this; a client holding the old mode
        # would offer a control the server will reject.
        await ws.broadcast(
            current.id,
            "category_settings.updated",
            [
                {"category": row.category, "voting_mode": row.voting_mode}
                for row in result
            ],
        )
    return result


# --- the non-admin read every voting UI needs ----------------------------------------------


#: Owned by this feature, but not gated by it: **every** role needs to know whether they are
#: being shown a 1–10 scale or a thumbs control. Reading the mode is not an admin power — it
#: is the difference between rendering the right control and the wrong one — so it lives on
#: its own router with `require_member` rather than inside the `/admin` prefix.
public_router = APIRouter(
    prefix="/trip",
    tags=["trip"],
    dependencies=[Depends(enforce_password_change), Depends(require_member)],
)


@public_router.get(
    "/category-settings",
    response_model=list[CategorySettingPublicOut],
    summary="How each category is voted on",
)
async def read_public_category_settings(
    db: DbDep, trip: ActiveTrip
) -> list[CategorySettingPublicOut]:
    """No vote counts: how many votes exist is an organiser's business, and a member does not
    need it to render a control."""
    current = _require_trip(trip)
    rows = await _ensure_category_rows(db, current)
    return [
        CategorySettingPublicOut(category=row.category, voting_mode=row.voting_mode)
        for row in rows
    ]


# --- Section 4: families and members ---------------------------------------------------------


async def _organiser_ids(db: DbDep, trip: Trip) -> frozenset[uuid.UUID]:
    return frozenset(
        (
            await db.execute(
                select(TripOrganiser.user_id).where(TripOrganiser.trip_id == trip.id)
            )
        )
        .scalars()
        .all()
    )


def _owner_ids(trip: Trip) -> frozenset[uuid.UUID]:
    return frozenset({trip.owner_user_id}) if trip.owner_user_id else frozenset()


async def _load_members(
    db: DbDep, trip: Trip
) -> list[tuple[User, FamilyMember | None, Family | None]]:
    """Every account on the trip, with its membership and family if it has one.

    An outer join, deliberately: someone whose membership was removed still has an account
    and still authored things, and the overview is the one place that has to be able to show
    them. Ordered by display name, which is the column the table sorts by first.
    """
    rows = (
        (
            await db.execute(
                select(User, FamilyMember, Family)
                .outerjoin(FamilyMember, FamilyMember.user_id == User.id)
                .outerjoin(
                    Family,
                    (Family.id == FamilyMember.family_id) & (Family.trip_id == trip.id),
                )
                .order_by(User.display_name)
            )
        )
        .tuples()
        .all()
    )
    return [(user, member, family) for user, member, family in rows]


def _matches_text(query: str, *values: str | None) -> bool:
    """One search box over both tables (AC-6). Case-insensitive substring and nothing
    cleverer: the universe is a few dozen people, and a fuzzy match would surprise more than
    it helps."""
    needle = query.strip().lower()
    if not needle:
        return True
    return any(needle in (value or "").lower() for value in values)


@router.get("/overview", response_model=OverviewOut, summary="Every family and member")
async def read_overview(db: DbDep, trip: ActiveTrip, q: str = "") -> OverviewOut:
    """AC-6. Families come from `families`' own serialiser, so the console shows the same
    colour, name and counts as the map and the member list."""
    current = _require_trip(trip)
    owner_ids = _owner_ids(current)
    organiser_ids = await _organiser_ids(db, current)

    families = (
        (
            await db.execute(
                select(Family)
                .where(Family.trip_id == current.id)
                .options(selectinload(Family.members))
                .order_by(Family.name)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    family_wire = {family.id: family_out(family) for family in families}

    members: list[AdminMemberOut] = []
    for user, membership, family in await _load_members(db, current):
        if not _matches_text(
            q,
            user.display_name,
            user.username,
            user.first_name,
            user.last_name,
            family.name if family else None,
        ):
            continue
        is_trip_owner = bool(user.is_platform_admin) or user.id in owner_ids
        members.append(
            AdminMemberOut(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                display_name=user.display_name,
                initials=initials(user),
                avatar_thumb_url=attachment_url(user.avatar, thumb=True),
                family=family_wire.get(family.id) if family else None,
                family_role=membership.role if membership else None,
                # Three independent facts, not one enum: the owner is also an ordinary head
                # or member of their own family, and the table renders every label that
                # applies ("Organiser · Head").
                is_owner=is_trip_owner,
                is_organiser=is_trip_owner or user.id in organiser_ids,
                must_change_password=user.must_change_password,
                last_login_at=user.last_login_at,
                created_at=user.created_at,
            )
        )

    return OverviewOut(
        families=[
            family_wire[family.id]
            for family in families
            if _matches_text(q, family.name)
        ],
        members=members,
    )


# --- account actions -------------------------------------------------------------------------


async def _load_target(db: DbDep, user_id: uuid.UUID) -> User:
    target = await db.scalar(select(User).where(User.id == user_id))
    if target is None:
        raise ApiError(404, "not_found", "No such user.")
    return target


async def _reject_protected_target(
    db: DbDep, actor: User, target: User, trip: Trip
) -> None:
    """The protected-target rule (ruling, 2026-08-11).

    `require_organiser` gets you through the door; it does not get you at another organiser.
    Resetting a fellow organiser's password or removing them from the trip is the same kind
    of power as demoting them, and that is the owner's alone — otherwise the owner's choice
    of who runs the trip lasts until the first organiser disagrees, which is the exact
    failure `trip_organisers` was shaped to prevent.

    The owner is not a target here for anyone, themselves included: there is one owner per
    trip and the role does not move through this screen.
    """
    if target.id == actor.id:
        raise ApiError(
            409, "cannot_target_self", "Use your profile page for your own account."
        )

    if bool(target.is_platform_admin) or trip.owner_user_id == target.id:
        raise ApiError(
            409, "cannot_target_owner", "The trip's owner cannot be reset or removed here."
        )

    if not await is_owner(actor, trip):
        if target.id in await _organiser_ids(db, trip):
            raise ApiError(
                403,
                "target_protected",
                "Only the trip's owner can do that to another organiser.",
            )


async def _end_their_session(user_id: uuid.UUID, reason: str) -> None:
    """Tell the target their session is gone, then close their socket.

    Without this, their client discovers the revocation as a wall of `401`s from whatever it
    polls next. With it they get one plain message and the login screen.
    """
    await ws.send_user(user_id, "session.revoked", {"reason": reason})
    await ws.close_user(user_id)


@router.post(
    "/users/{user_id}/reset-password",
    response_model=ResetPasswordOut,
    summary="Generate a temporary password for someone who is locked out",
)
async def reset_password(
    user_id: uuid.UUID,
    payload: ResetPasswordIn,
    db: DbDep,
    user: CurrentUser,
    trip: ActiveTrip,
) -> ResetPasswordOut:
    """AC-7. Available in every stage: this is an account operation, not trip data.

    Every one of that user's sessions dies here. A reset happens because someone has lost
    control of an account, and leaving a live session attached to it would defeat the point.
    """
    del payload  # its presence is the confirmation; there is nothing else in it
    current = _require_trip(trip)
    target = await _load_target(db, user_id)
    await _reject_protected_target(db, user, target, current)

    temporary = generate_temporary_password()
    target.password_hash = hash_password(temporary)
    target.must_change_password = True
    await revoke_user_sessions(db, target.id)
    await db.commit()

    await _end_their_session(target.id, "password_reset")
    # The plaintext exists in this response body and nowhere else: not in a log line, not in
    # a column, not retrievable a second time.
    return ResetPasswordOut(temporary_password=temporary)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove someone from the trip",
    dependencies=[Depends(require_stage("planning", "holiday"))],
)
async def remove_user(
    user_id: uuid.UUID, db: DbDep, user: CurrentUser, trip: ActiveTrip
) -> Response:
    """AC-8. Their access ends; their content stays, attributed to them.

    The `users` row survives — votes, comments and suggestions reference it, and deleting it
    would falsify the record of how decisions were made. What goes is the membership.

    Refused in End by the stage guard, because it would alter the archived record of who was
    on the trip.
    """
    current = _require_trip(trip)
    target = await _load_target(db, user_id)
    await _reject_protected_target(db, user, target, current)

    membership = await db.scalar(
        select(FamilyMember)
        .where(FamilyMember.user_id == target.id)
        .options(selectinload(FamilyMember.user))
    )
    family_id = membership.family_id if membership is not None else None
    if membership is not None:
        # The same two checks `families` applies, imported rather than reimplemented: both
        # features must refuse the same person for the same reason.
        reject_touching_the_owner(membership, current)
        reject_leaving_the_family_headless(membership)
        await db.delete(membership)

    await revoke_user_sessions(db, target.id)
    await db.commit()

    if family_id is not None:
        payload = {"family_id": str(family_id), "user_id": str(target.id)}
        # The exact payload `families` emits, so one client handler serves both.
        await ws.broadcast(current.id, "member.removed", payload)
        await ws.send_user(target.id, "member.removed", payload)
    await _end_their_session(target.id, "removed_from_trip")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Section 8: organisers (AC-13, owner only) ------------------------------------------------


def _organiser_out(
    user: User,
    membership: FamilyMember | None,
    family: Family | None,
    granted_by: User | None,
    created_at,
) -> OrganiserOut:
    return OrganiserOut(
        user_id=user.id,
        display_name=user.display_name,
        initials=initials(user),
        avatar_thumb_url=attachment_url(user.avatar, thumb=True),
        family=family_out(family) if family is not None else None,
        family_role=membership.role if membership is not None else None,
        granted_by=(
            OrganiserActorOut(user_id=granted_by.id, display_name=granted_by.display_name)
            if granted_by is not None
            else None
        ),
        created_at=created_at,
    )


async def _load_organisers(db: DbDep, trip: Trip) -> list[OrganiserOut]:
    granter = aliased(User)
    rows = (
        (
            await db.execute(
                select(TripOrganiser, User, FamilyMember, Family, granter)
                .join(User, User.id == TripOrganiser.user_id)
                .outerjoin(FamilyMember, FamilyMember.user_id == User.id)
                .outerjoin(Family, Family.id == FamilyMember.family_id)
                .outerjoin(granter, granter.id == TripOrganiser.granted_by)
                .where(TripOrganiser.trip_id == trip.id)
                .order_by(TripOrganiser.created_at)
            )
        )
        .tuples()
        .all()
    )
    return [
        _organiser_out(user, membership, family, granted_by, grant.created_at)
        for grant, user, membership, family, granted_by in rows
    ]


@router.get(
    "/organisers",
    response_model=list[OrganiserOut],
    summary="Who else can do what an organiser can do",
)
async def read_organisers(db: DbDep, trip: ActiveTrip) -> list[OrganiserOut]:
    """Readable by any organiser, not just the owner.

    Seeing who else holds the role is not itself a power — an organiser who could not see the
    list would still be working alongside them, just less able to tell who to ask. Appointing
    and demoting are the owner's, and those are the next two routes.
    """
    return await _load_organisers(db, _require_trip(trip))


@router.post(
    "/organisers",
    response_model=OrganiserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Appoint an organiser",
    dependencies=[Depends(require_owner), Depends(require_stage("planning", "holiday"))],
)
async def appoint_organiser(
    payload: OrganiserGrantIn, response: Response, db: DbDep, user: CurrentUser, trip: ActiveTrip
) -> OrganiserOut:
    """AC-13. Owner only — there is no organiser-facing path to this route anywhere.

    Idempotent: appointing someone who is already an organiser returns the existing row with
    `200`. A `409` would be a worse answer to a request whose desired end state already holds,
    and the console's search list is built from the member universe, which a second admin may
    have changed under the caller a second ago.
    """
    current = _require_trip(trip)
    target = await _load_target(db, payload.user_id)

    if bool(target.is_platform_admin) or current.owner_user_id == target.id:
        # The owner already holds every organiser power; a row would imply the role could be
        # taken away from them, which it cannot.
        raise ApiError(
            409, "cannot_appoint_owner", "The trip's owner already has every organiser power."
        )

    membership = await db.scalar(
        select(FamilyMember).where(FamilyMember.user_id == target.id)
    )
    if membership is None:
        # The appointment list is drawn from the trip's members; someone with no family has
        # not been invited onto this trip, and there would be nobody to search for.
        raise ApiError(
            422, "not_on_trip", "Only someone already on the trip can be made an organiser."
        )

    existing = await db.scalar(
        select(TripOrganiser).where(
            TripOrganiser.trip_id == current.id, TripOrganiser.user_id == target.id
        )
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return (await _one_organiser(db, current, target.id)) or _organiser_out(
            target, membership, None, None, existing.created_at
        )

    db.add(
        TripOrganiser(trip_id=current.id, user_id=target.id, granted_by=user.id)
    )
    await db.commit()

    out = await _one_organiser(db, current, target.id)
    assert out is not None  # noqa: S101 - just inserted in this transaction
    # Every client: the appointee's own nav rail grows an `Admin` entry without a reload, and
    # everyone else's member list learns the label.
    await ws.broadcast(
        current.id,
        "organiser.appointed",
        {"user_id": str(target.id), "granted_by": str(user.id)},
    )
    return out


async def _one_organiser(db: DbDep, trip: Trip, user_id: uuid.UUID) -> OrganiserOut | None:
    for row in await _load_organisers(db, trip):
        if row.user_id == user_id:
            return row
    return None


@router.delete(
    "/organisers/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Demote an organiser",
    dependencies=[Depends(require_owner), Depends(require_stage("planning", "holiday"))],
)
async def demote_organiser(
    user_id: uuid.UUID, db: DbDep, trip: ActiveTrip
) -> Response:
    """AC-13. Deliberately narrow: this writes one row and nothing else.

    It does **not** touch `family_members.role`, and it does **not** revoke sessions or emit
    `session.revoked`. A demoted organiser keeps their family role, keeps their session, and
    simply stops passing `require_organiser` on their next request — because this is a
    permission change, not an access revocation. Forcing a re-login would tell them they had
    been thrown out of the trip, which is not what happened.
    """
    current = _require_trip(trip)

    if current.owner_user_id == user_id:
        # The owner is never a row here, so there is nothing to delete and the request is a
        # misunderstanding worth naming rather than a 404.
        raise ApiError(
            409, "cannot_demote_owner", "The trip's owner is not an organiser to remove."
        )

    grant = await db.scalar(
        select(TripOrganiser).where(
            TripOrganiser.trip_id == current.id, TripOrganiser.user_id == user_id
        )
    )
    if grant is None:
        raise ApiError(404, "not_found", "That person is not an organiser.")

    await db.delete(grant)
    await db.commit()

    # Every client, and the demoted user's own especially: their `Admin` nav entry and any
    # open console tab go away live rather than on their next 403.
    await ws.broadcast(current.id, "organiser.demoted", {"user_id": str(user_id)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Section 5: instance settings --------------------------------------------------------------


#: `settings` keys this feature owns. The public read (`GET /settings`) exposes the same three
#: without a session; this is the editor.
async def _instance_settings(db: DbDep) -> InstanceSettingsOut:
    return InstanceSettingsOut(
        instance_name=str(await get_setting(db, SETTING_INSTANCE_NAME, "Kindred")),
        registration_open=bool(await get_setting(db, SETTING_REGISTRATION_OPEN, False)),
        invite_only=bool(await get_setting(db, SETTING_INVITE_ONLY, True)),
    )


@router.get("/settings", response_model=InstanceSettingsOut, summary="Instance settings")
async def read_instance_settings(db: DbDep) -> InstanceSettingsOut:
    """Readable by any organiser; writing is the owner's (see below)."""
    return await _instance_settings(db)


@router.patch(
    "/settings",
    response_model=InstanceSettingsOut,
    summary="Edit instance settings",
    dependencies=[Depends(require_owner)],
)
async def patch_instance_settings(
    payload: InstanceSettingsIn, db: DbDep
) -> InstanceSettingsOut:
    """Owner only (ruling, 2026-08-11).

    These are platform-level values, not trip data: the instance name is what the login
    screen shows before anyone has a trip, and the registration policy decides who can exist
    at all. That sits outside the cross-family *trip* powers an organiser holds, so the
    console renders this section read-only for them with an explanatory caption.

    No stage guard, for the same reason: an archived trip does not make the instance
    unnameable.
    """
    changes = payload.model_dump(exclude_unset=True)

    if changes.get("invite_only") is False:
        # The field exists so the policy can widen later without a migration; the widening
        # itself is not built, and pretending otherwise would leave an instance believing it
        # accepts open registration when nothing implements it.
        raise ApiError(
            422,
            "not_implemented",
            "Open registration is not available in this version.",
        )

    for key, value in changes.items():
        await set_setting(db, key, value)
    await db.commit()
    return await _instance_settings(db)


# --- Section 6: Google API status ----------------------------------------------------------------


#: The `settings` key holding the last probe result. A singleton blob, which is what
#: `settings` is for.
SETTING_GOOGLE_STATUS = "google_api_status"

#: Rate-limit bucket for the probe. A fixed string rather than a username: the limit is one
#: press per minute **per instance**, not per admin, because the cost it protects is Google's
#: bill and that is shared.
PROBE_RATE_KEY = "__google_probe__"
PROBE_RATE_LIMIT = 1

#: Display order and labels. Maps JS is first because it is the one a user notices missing.
PROBE_LABELS: list[tuple[str, str, str]] = [
    ("maps_js", "Maps JavaScript", "browser"),
    ("places", "Places", "server"),
    ("geocoding", "Geocoding", "server"),
    ("distance_matrix", "Distance Matrix", "server"),
    ("directions", "Directions", "server"),
]


def _google_status_out(blob: dict | None) -> GoogleStatusOut:
    """Render the stored blob, or the never-checked state.

    A corrupt or absent value is treated as "never checked" rather than as an error: the
    section's job is to tell an admin what is working, and failing to render because a
    previous result was malformed would be the least useful possible response.
    """
    stored = blob if isinstance(blob, dict) else {}
    apis_blob = stored.get("apis") if isinstance(stored.get("apis"), dict) else {}

    browser_key = bool(settings.google_maps_browser_key.strip())
    server_key = bool(settings.google_maps_server_key.strip())

    apis: list[ApiStatusOut] = []
    for key, label, key_type in PROBE_LABELS:
        if key == "maps_js":
            # Not probed, and said so plainly: it is a browser-side loader restricted by HTTP
            # referrer, and no server-side request can tell you whether it works.
            apis.append(
                ApiStatusOut(
                    name=label,
                    key_type="browser",
                    status="configured" if browser_key else "unchecked",
                    detail=None if browser_key else ERROR_NO_API_KEY,
                    hint=None
                    if browser_key
                    else PROBE_HINTS.get(ERROR_NO_API_KEY),
                )
            )
            continue

        entry = apis_blob.get(key) if isinstance(apis_blob.get(key), dict) else {}
        status_value = entry.get("status")
        detail = entry.get("detail")
        if status_value not in ("ok", "denied", "quota", "unreachable", "unchecked"):
            status_value = "unchecked"
            detail = None if server_key else ERROR_NO_API_KEY
        apis.append(
            ApiStatusOut(
                name=label,
                key_type=key_type,
                status=status_value,
                detail=detail,
                hint=PROBE_HINTS.get(detail or "") or PROBE_HINTS.get(status_value),
            )
        )

    checked_at = stored.get("checked_at")
    return GoogleStatusOut(
        checked_at=checked_at,
        checked_by=stored.get("checked_by"),
        browser_key_configured=browser_key,
        server_key_configured=server_key,
        apis=apis,
    )


@router.get(
    "/google-status", response_model=GoogleStatusOut, summary="The last Google API check"
)
async def read_google_status(db: DbDep) -> GoogleStatusOut:
    """Reads the stored result and makes **no** external call.

    That is the whole point of storing it: the section is useful on every page load without
    spending an API call, and the only thing that spends one is the button below.
    """
    return _google_status_out(await get_setting(db, SETTING_GOOGLE_STATUS, None))


@router.post(
    "/google-status/check",
    response_model=GoogleStatusOut,
    summary="Run the Google API check (makes real API calls)",
)
async def run_google_check(
    db: DbDep, user: CurrentUser, probe: ProbeProtocol = Depends(get_probe)
) -> GoogleStatusOut:
    """AC-10. The one deliberate call to Google outside a caching path, behind a button.

    Rate-limited to one press a minute for the whole instance, reusing foundation's limiter
    with a fixed key: the cost being protected is the project's Google bill, which is shared,
    so a per-admin limit would multiply by the number of admins.
    """
    if await ratelimit.count_recent_failures(db, username=PROBE_RATE_KEY) >= PROBE_RATE_LIMIT:
        raise ApiError(
            429,
            CODE_RATE_LIMITED,
            "The check can run once a minute. Try again shortly.",
            headers={"Retry-After": str(ratelimit.retry_after_seconds())},
        )
    # Recorded as a "failure" because that is the column the limiter counts; the row means
    # "a press happened", not "a press went wrong".
    await ratelimit.record_attempt(db, username=PROBE_RATE_KEY, ip=None, succeeded=False)

    results = await probe.probe()
    blob = {
        "checked_at": datetime.now(UTC).isoformat(),
        "checked_by": str(user.id),
        "apis": {
            name: {"status": result.status, "detail": result.detail}
            for name, result in results.items()
        },
    }
    await set_setting(db, SETTING_GOOGLE_STATUS, blob)
    await db.commit()
    return _google_status_out(blob)


# --- Section 7: stats ----------------------------------------------------------------------------


@router.get("/stats", response_model=StatsOut, summary="Counts for this trip")
async def read_stats(db: DbDep, trip: ActiveTrip) -> StatsOut:
    """AC-11. One trip-scoped count per metric.

    Metrics whose feature has not shipped read zero rather than erroring, so the console
    works from M1 onward. Each is named with the feature that will replace it — the stub is
    a to-do with an owner, not a permanent lie.
    """
    current = _require_trip(trip)

    families = await db.scalar(
        select(func.count()).select_from(Family).where(Family.trip_id == current.id)
    )
    members = await db.scalar(
        select(func.count())
        .select_from(FamilyMember)
        .join(Family, Family.id == FamilyMember.family_id)
        .where(Family.trip_id == current.id)
    )
    invites_open = await db.scalar(
        select(func.count())
        .select_from(Invite)
        .where(
            Invite.trip_id == current.id,
            Invite.used_by.is_(None),
            Invite.revoked_at.is_(None),
            Invite.expires_at > datetime.now(UTC),
        )
    )

    return StatsOut(
        families=families or 0,
        members=members or 0,
        invites_open=invites_open or 0,
        # polls_open / polls_closed        -> `polls` (M2)
        # suggestions_by_status, comments  -> `map-suggestions` / `voting-comments` (M3)
        # itinerary_items                  -> `itinerary-timeline` (M4)
        # checkins                         -> `holiday-stage` (M5)
        # notifications_unread             -> `notifications` (M5)
    )
