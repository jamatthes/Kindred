"""Families and their members (FM-1 to FM-4, FM-9, FM-10, FM-13, FM-15).

Two rules run through every route here and are worth stating once:

**Permissions are dependencies, never handler-body checks** (`CLAUDE.md`). A route declares
`require_family_manager` and `require_stage("planning", "holiday")` and then trusts them.
The End stage is read-only because every mutating route carries the stage guard, not because
anything in this file mentions `end`.

**A head or spouse can only ever narrow visibility.** No request body reachable by any role
in this router writes `user_settings.live_location_enabled` for another user. The single write
to that column in the whole feature is the seed in `POST /families/mine`, where the caller is
setting their own. That invariant is what keeps `holiday-stage`'s promise — "nobody, the
owner included, can turn on another person's live-location sharing" — true now that family
policy exists alongside consent. `tests/test_location_policy.py` enumerates the routes and
asserts it rather than trusting this paragraph.

Geocoding reaches the network through exactly one helper, `_apply_geocode`, and only mutating
handlers call it: `set_home` and `retry_geocode` (the two `design.md` names), plus
`create_family` and `create_my_family`, both of which accept an optional address because FM-1
and FM-13 say they do. **No read path can reach it** — that is the cost rule
(`plan/architecture.md`), and funnelling every call through one helper is what makes it
checkable with a grep rather than by reading the file. Recorded as a NOTE in `design.md`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import ws
from app.deps import (
    ActiveTrip,
    CurrentUser,
    DbDep,
    ViewerDep,
    enforce_password_change,
    is_organiser,
    require_family_manager,
    require_organiser,
    require_member,
    require_pending_family,
    require_stage,
)
from app.models import (
    MAX_COLOR_SLOTS,
    ROLE_HEAD,
    ROLE_MEMBER,
    ROLE_SPOUSE,
    Family,
    FamilyMember,
    Trip,
    TripOrganiser,
    User,
    UserSettings,
    next_free_color,
    spouse_may_act_on,
)
from app.schemas.common import ApiError, forbidden
from app.schemas.family import (
    FAMILY_DETAIL_RESPONSE,
    FAMILY_RESPONSE,
    FamilyCreateIn,
    FamilyDetailOut,
    FamilyMineIn,
    FamilyOut,
    FamilyPatchIn,
    HomeIn,
    LocationPolicyIn,
    MemberOut,
    MemberPatchIn,
    Viewer,
    family_detail_out,
    family_out,
    member_out,
)
from app.services.google import GeocoderProtocol, get_geocoder

router = APIRouter(
    prefix="/families",
    tags=["families"],
    dependencies=[Depends(enforce_password_change)],
)

#: Spread into every mutating route. Written once so that adding a route without it is a
#: visible omission rather than an invisible one.
PLANNING_OR_HOLIDAY = Depends(require_stage("planning", "holiday"))


# --- loading ------------------------------------------------------------------------------


def _family_query():
    """Every family read goes through this, so the eager loads are decided in one place.

    `MemberOut` needs each member's user, their avatar row and their settings row. Left lazy,
    each of those would be a `MissingGreenlet` on an async session — a loud failure, but one
    discovered at runtime by whoever adds the next route.
    """
    return (
        select(Family)
        .options(selectinload(Family.members).selectinload(FamilyMember.user))
        # `populate_existing` because almost every call here is a re-read *after* a write.
        # The session has `expire_on_commit=False`, so without this a `Family` already in the
        # identity map keeps the `members` collection it was loaded with — and a route that
        # had just added a membership row would re-read the family and not find it.
        .execution_options(populate_existing=True)
    )


async def _load_family(db: AsyncSession, family_id: uuid.UUID) -> Family:
    family = await db.scalar(_family_query().where(Family.id == family_id))
    if family is None:
        raise ApiError(404, "not_found", "That family does not exist.")
    return family


def _owner_ids(trip: Trip | None) -> frozenset[uuid.UUID]:
    """The trip's owner, for `MemberOut.is_owner`."""
    if trip is None or trip.owner_user_id is None:
        return frozenset()
    return frozenset({trip.owner_user_id})


async def _organiser_ids(db: AsyncSession, trip: Trip | None) -> frozenset[uuid.UUID]:
    """Everyone the owner has appointed (FM-17).

    Fetched once per request rather than per member row: a family list would otherwise issue a
    query per person to answer a question with the same answer every time.
    """
    if trip is None:
        return frozenset()
    rows = await db.scalars(
        select(TripOrganiser.user_id).where(TripOrganiser.trip_id == trip.id)
    )
    return frozenset(rows.all())


async def _detail(
    db: AsyncSession, family: Family, viewer: Viewer, trip: Trip | None
) -> FamilyDetailOut:
    return family_detail_out(
        family,
        viewer,
        owner_ids=_owner_ids(trip),
        organiser_ids=await _organiser_ids(db, trip),
    )


# --- guard rails --------------------------------------------------------------------------


async def _reject_duplicate_name(
    db: AsyncSession, trip_id: uuid.UUID, name: str, *, excluding: uuid.UUID | None = None
) -> None:
    """FM-1: a duplicate name on the trip is refused with a clear message.

    Case-insensitively, matching the unique index — "The Smiths" and "the smiths" are the
    same family to a human. The database would refuse it anyway; this exists so the refusal
    arrives as `409 name_taken` on the right field instead of a 500.
    """
    stmt = select(Family.id).where(
        Family.trip_id == trip_id, func.lower(Family.name) == name.strip().lower()
    )
    if excluding is not None:
        stmt = stmt.where(Family.id != excluding)
    if await db.scalar(stmt) is not None:
        raise ApiError(409, "name_taken", f"A family called “{name.strip()}” is already here.")


async def _claim_color(
    db: AsyncSession,
    trip_id: uuid.UUID,
    requested: int | None,
    *,
    excluding: uuid.UUID | None = None,
) -> int:
    """The requested slot if free, else the lowest free one, else `409 no_color_slots`.

    A requested-but-taken slot is an error rather than a silent substitution: whoever asked
    picked that colour on purpose (FM-1), and quietly giving them a different one would be
    the kind of help nobody asked for. The message names the family holding it.
    """
    if requested is not None:
        stmt = select(Family).where(Family.trip_id == trip_id, Family.color == requested)
        if excluding is not None:
            stmt = stmt.where(Family.id != excluding)
        holder = await db.scalar(stmt)
        if holder is not None:
            raise ApiError(
                409, "color_taken", f"That colour is already used by {holder.name}."
            )
        return requested

    slot = await next_free_color(db, trip_id)
    if slot is None:
        raise ApiError(
            409,
            "no_color_slots",
            f"The palette supports {MAX_COLOR_SLOTS} families, and all "
            f"{MAX_COLOR_SLOTS} colours are in use.",
        )
    return slot


def _reject_touching_the_owner(member: FamilyMember, trip: Trip | None) -> None:
    """FM-9/FM-10: the trip's owner cannot be removed or demoted through this feature."""
    is_trip_owner = member.user.is_platform_admin or (
        trip is not None and trip.owner_user_id == member.user_id
    )
    if is_trip_owner:
        raise ApiError(
            403,
            "owner_protected",
            "The trip's owner cannot be removed or demoted here.",
        )


def _reject_leaving_the_family_headless(member: FamilyMember) -> None:
    """A family always has exactly one head (FM-16).

    So a head is never *demoted* or *removed* — the role is handed on, which is a transfer and
    is offered as one. A family that has just lost its only head is exactly the family least
    able to notice, and only an organiser could repair it.
    """
    if member.role != ROLE_HEAD:
        return
    raise ApiError(
        409,
        "head_required",
        "A family needs a head. Hand the role to someone else first — that will make you a "
        "spouse in the same step.",
    )


async def _reject_spouse_acting_on_head(
    db: AsyncSession, actor: User, family: Family, target: FamilyMember, trip: Trip | None
) -> None:
    """The spouse asymmetry (FM-16), applied against the **target** of the action.

    A spouse holds the head's powers over the family, so they reach this route legitimately;
    the one thing they may not do is act on the head. Enforced here rather than in the
    dependency because a role-level refusal would lock a spouse out of the nine-tenths of the
    route that is theirs.

    Organisers are exempt: they are not spouses, and FM-10 gives them every family's powers.
    """
    if await is_organiser(db, actor, trip):
        return
    actor_membership = next((m for m in family.members if m.user_id == actor.id), None)
    if actor_membership is None:
        return
    if not spouse_may_act_on(actor_membership, target):
        raise ApiError(
            403,
            "head_protected",
            "Only the head of the family, or the trip's organisers, can change that.",
        )


async def _reject_spouse_changing_a_role(
    db: AsyncSession, actor: User, family: Family, trip: Trip | None
) -> None:
    """FM-16: a spouse may run the family, but not change who runs it.

    Separate from :func:`_reject_spouse_acting_on_head` because it is a different rule with a
    different reason: that one protects the head *as a target*, this one keeps the composition
    of the family's leadership in the head's hands whoever the target is. A spouse promoting a
    third adult would let them outvote the arrangement the head made.
    """
    if await is_organiser(db, actor, trip):
        return
    actor_membership = next((m for m in family.members if m.user_id == actor.id), None)
    if actor_membership is not None and actor_membership.role == ROLE_SPOUSE:
        raise ApiError(
            403,
            "spouse_cannot_promote",
            "Only the head of the family, or the trip's organisers, can change roles.",
        )


# --- reads --------------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[FamilyOut],
    dependencies=[Depends(require_member)],
    summary="Every family on the trip",
)
async def list_families(db: DbDep, trip: ActiveTrip) -> list[FamilyOut]:
    """FM-4. The coarse shape only — no address reaches this route, for anybody.

    Returning `FamilyOut` for every caller rather than branching on entitlement keeps the
    list route incapable of leaking: there is no code path here that could include an
    address, so no future edit can forget to exclude one. A caller who *is* entitled reads
    `GET /families/{id}`.
    """
    if trip is None:
        return []
    families = (
        (await db.scalars(_family_query().where(Family.trip_id == trip.id).order_by(Family.color)))
        .unique()
        .all()
    )
    return [family_out(f) for f in families]


@router.get(
    "/{family_id}",
    **FAMILY_DETAIL_RESPONSE,
    dependencies=[Depends(require_member)],
    summary="One family, with its members",
)
async def read_family(
    family_id: uuid.UUID, db: DbDep, viewer: ViewerDep, trip: ActiveTrip
) -> FamilyDetailOut:
    return await _detail(db, await _load_family(db, family_id), viewer, trip)


@router.get(
    "/{family_id}/members",
    response_model=list[MemberOut],
    dependencies=[Depends(require_member)],
    summary="A family's members",
)
async def list_members(
    family_id: uuid.UUID, db: DbDep, viewer: ViewerDep, trip: ActiveTrip
) -> list[MemberOut]:
    family = await _load_family(db, family_id)
    return (await _detail(db, family, viewer, trip)).members


# --- writes -------------------------------------------------------------------------------


@router.post(
    "",
    **FAMILY_DETAIL_RESPONSE,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Create a family (main admin)",
)
async def create_family(
    payload: FamilyCreateIn,
    db: DbDep,
    viewer: ViewerDep,
    trip: ActiveTrip,
    geocoder: GeocoderProtocol = Depends(get_geocoder),
) -> FamilyDetailOut:
    """FM-1. The main admin creates a family so they can invite its members."""
    if trip is None:
        raise ApiError(409, "no_trip", "There is no trip to add a family to yet.")

    await _reject_duplicate_name(db, trip.id, payload.name)
    color = await _claim_color(db, trip.id, payload.color)

    family = Family(trip_id=trip.id, name=payload.name.strip(), color=color)
    db.add(family)
    await db.flush()

    if payload.home_address:
        await _apply_geocode(family, payload.home_address, geocoder)

    await db.commit()
    family = await _load_family(db, family.id)
    await ws.broadcast(trip.id, "family.created", {"family": _wire(family)})
    return await _detail(db, family, viewer, trip)


@router.post(
    "/mine",
    **FAMILY_DETAIL_RESPONSE,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_pending_family), PLANNING_OR_HOLIDAY],
    summary="Name my new family (first-login setup)",
)
async def create_my_family(
    payload: FamilyMineIn,
    db: DbDep,
    user: CurrentUser,
    trip: ActiveTrip,
    geocoder: GeocoderProtocol = Depends(get_geocoder),
) -> FamilyDetailOut:
    """FM-13 — the family setup screen's only write, and this feature's only route a user
    with no family may call.

    One transaction: create the family on the trip with the lowest free colour, write the
    membership as `admin`, seed **that caller's own** `live_location_enabled = true`, and
    geocode the home address if one was supplied.

    The seed is the single point in this feature where a value reaches
    `user_settings.live_location_enabled`, and the caller is setting their own — the person
    organising a family's travel is the one the rest of them expect to be able to find
    (FM-15). Two gates still stand between it and a marker: the browser's permission prompt,
    and `holiday-stage`'s one-time disclosure.
    """
    if trip is None:
        raise ApiError(409, "no_trip", "There is no trip to join yet.")

    # A double submit — a double-tap, or a retry after a timeout whose first attempt
    # succeeded — must not create a second family. `require_pending_family` already refuses a
    # caller who has one, so reaching here with a membership means the race was lost between
    # the dependency and now; the client treats this as success and re-reads `auth/me`.
    existing = await db.scalar(select(FamilyMember).where(FamilyMember.user_id == user.id))
    if existing is not None:
        raise ApiError(409, "already_has_family", "You are already in a family.")

    await _reject_duplicate_name(db, trip.id, payload.name)
    color = await _claim_color(db, trip.id, None)

    family = Family(trip_id=trip.id, name=payload.name.strip(), color=color)
    db.add(family)
    await db.flush()
    db.add(FamilyMember(family_id=family.id, user_id=user.id, role=ROLE_HEAD))

    settings = await db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
    if settings is None:
        settings = UserSettings(user_id=user.id)
        db.add(settings)
    settings.live_location_enabled = True

    if payload.home_address:
        await _apply_geocode(family, payload.home_address, geocoder)

    await db.commit()
    family = await _load_family(db, family.id)
    viewer = Viewer(
        user_id=user.id,
        family_id=family.id,
        is_owner=False,
        is_organiser=False,
        manages_own_family=True,
    )
    detail = await _detail(db, family, viewer, trip)
    await ws.broadcast(trip.id, "family.created", {"family": _wire(family)})
    await broadcast_member_joined(db, family.id, user.id, trip)
    return detail


@router.patch(
    "/{family_id}",
    **FAMILY_DETAIL_RESPONSE,
    dependencies=[Depends(require_family_manager), PLANNING_OR_HOLIDAY],
    summary="Rename or recolour a family",
)
async def update_family(
    family_id: uuid.UUID,
    payload: FamilyPatchIn,
    db: DbDep,
    viewer: ViewerDep,
    trip: ActiveTrip,
) -> FamilyDetailOut:
    """FM-2. A family admin edits their own; the main admin edits any."""
    family = await _load_family(db, family_id)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)

    if "name" in changes:
        await _reject_duplicate_name(db, family.trip_id, changes["name"], excluding=family.id)
        family.name = changes["name"].strip()
    if "color" in changes:
        family.color = await _claim_color(
            db, family.trip_id, changes["color"], excluding=family.id
        )

    await db.commit()
    family = await _load_family(db, family_id)
    await ws.broadcast(family.trip_id, "family.updated", {"family": _wire(family)})
    return await _detail(db, family, viewer, trip)


@router.patch(
    "/{family_id}/location-policy",
    **FAMILY_DETAIL_RESPONSE,
    dependencies=[Depends(require_family_manager), PLANNING_OR_HOLIDAY],
    summary="Who in this family may appear on the map",
)
async def update_location_policy(
    family_id: uuid.UUID,
    payload: LocationPolicyIn,
    db: DbDep,
    viewer: ViewerDep,
    trip: ActiveTrip,
) -> FamilyDetailOut:
    """FM-15, the family admin's two switches.

    **Writes nothing to any `user_settings` row**, deliberately. `sharing_allowed` is applied
    as a read-time filter, so turning it back on restores exactly the members who had
    consented rather than re-enabling people who had turned themselves off; and
    `member_default` is read once, when a membership row is created, never again.
    """
    family = await _load_family(db, family_id)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "sharing_allowed" in changes:
        family.location_sharing_allowed = changes["sharing_allowed"]
    if "member_default" in changes:
        family.member_location_default = changes["member_default"]

    await db.commit()
    family = await _load_family(db, family_id)
    # `family.updated` is what makes a policy change take effect without a reload: a marker
    # that should no longer be visible must not linger for a refresh interval.
    await ws.broadcast(family.trip_id, "family.updated", {"family": _wire(family)})
    return await _detail(db, family, viewer, trip)


@router.delete(
    "/{family_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Delete an empty family (main admin)",
)
async def delete_family(family_id: uuid.UUID, db: DbDep) -> Response:
    """FM-10. Refused while anyone is still in it — deliberately.

    Deleting a family with members would revoke a whole group's access in one click, and the
    click that does it looks identical to the one that tidies up an empty row.
    """
    family = await _load_family(db, family_id)
    if family.members:
        raise ApiError(
            409,
            "family_not_empty",
            "Remove this family's members before deleting it.",
        )
    trip_id = family.trip_id
    await db.delete(family)
    await db.commit()
    await ws.broadcast(trip_id, "family.deleted", {"family_id": str(family_id)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- home address -------------------------------------------------------------------------


async def _apply_geocode(
    family: Family, address: str, geocoder: GeocoderProtocol
) -> None:
    """Geocode `address` onto `family`. **One of the only two call sites** (cost rule).

    The address is saved whatever happens. A geocoding failure is not a reason to lose what
    the user typed — FM-3 is explicit that the address stays and a retry is offered.
    """
    family.home_address = address.strip()
    # The old coordinates belong to the old address; keeping them through a failed re-geocode
    # would leave a pin on the map at a place the family no longer lives.
    family.home_lat = None
    family.home_lng = None
    family.home_locality = None
    family.home_geocoded_at = None

    outcome = await geocoder.geocode(family.home_address)
    family.geocode_status = outcome.status
    family.geocode_error = outcome.error
    if outcome.result is not None:
        family.home_lat = outcome.result.lat
        family.home_lng = outcome.result.lng
        family.home_locality = outcome.result.locality
        family.home_geocoded_at = datetime.now(UTC)


@router.put(
    "/{family_id}/home",
    **FAMILY_DETAIL_RESPONSE,
    dependencies=[Depends(require_family_manager), PLANNING_OR_HOLIDAY],
    summary="Set this family's home address",
)
async def set_home(
    family_id: uuid.UUID,
    payload: HomeIn,
    db: DbDep,
    viewer: ViewerDep,
    trip: ActiveTrip,
    geocoder: GeocoderProtocol = Depends(get_geocoder),
) -> FamilyDetailOut:
    """FM-3. Geocoded inline so the result can be confirmed on screen.

    Re-saving a byte-identical address that is already placed makes **no external call**
    (FM-3, and the cost rule): the answer cannot have changed and the bill would be real.
    """
    family = await _load_family(db, family_id)
    address = payload.home_address.strip()

    unchanged = family.home_address == address and family.geocode_status == "ok"
    if not unchanged:
        await _apply_geocode(family, address, geocoder)
        await db.commit()
        family = await _load_family(db, family_id)
        await ws.broadcast(family.trip_id, "family.updated", {"family": _wire(family)})

    return await _detail(db, family, viewer, trip)


@router.post(
    "/{family_id}/home/geocode",
    **FAMILY_DETAIL_RESPONSE,
    dependencies=[Depends(require_family_manager), PLANNING_OR_HOLIDAY],
    summary="Try placing this family's home again",
)
async def retry_geocode(
    family_id: uuid.UUID,
    db: DbDep,
    viewer: ViewerDep,
    trip: ActiveTrip,
    geocoder: GeocoderProtocol = Depends(get_geocoder),
) -> FamilyDetailOut:
    """FM-3's explicit retry — the second and last place `geocode` is called.

    Unconditional, unlike `PUT .../home`: the user is asking *because* the last attempt
    failed, so the skip-if-unchanged rule would make the button do nothing.
    """
    family = await _load_family(db, family_id)
    if not family.home_address:
        raise ApiError(409, "no_home_address", "There is no address to place yet.")

    await _apply_geocode(family, family.home_address, geocoder)
    await db.commit()
    family = await _load_family(db, family_id)
    await ws.broadcast(family.trip_id, "family.updated", {"family": _wire(family)})
    return await _detail(db, family, viewer, trip)


@router.delete(
    "/{family_id}/home",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_family_manager), PLANNING_OR_HOLIDAY],
    summary="Clear this family's home address",
)
async def clear_home(family_id: uuid.UUID, db: DbDep) -> Response:
    """Everything goes, and the status returns to `pending` — never attempted, rather than
    `not_found`, which would claim we tried and failed on an address that no longer exists."""
    family = await _load_family(db, family_id)
    family.home_address = None
    family.home_lat = None
    family.home_lng = None
    family.home_locality = None
    family.home_geocoded_at = None
    family.geocode_status = "pending"
    family.geocode_error = None
    await db.commit()

    family = await _load_family(db, family_id)
    await ws.broadcast(family.trip_id, "family.updated", {"family": _wire(family)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- members ------------------------------------------------------------------------------


def _find_member(family: Family, user_id: uuid.UUID) -> FamilyMember:
    for member in family.members:
        if member.user_id == user_id:
            return member
    raise ApiError(404, "not_found", "That person is not in this family.")


@router.patch(
    "/{family_id}/members/{user_id}",
    response_model=MemberOut,
    dependencies=[Depends(require_family_manager), PLANNING_OR_HOLIDAY],
    summary="Change a member's role or map visibility",
)
async def update_member(
    family_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MemberPatchIn,
    db: DbDep,
    user: CurrentUser,
    viewer: ViewerDep,
    trip: ActiveTrip,
) -> MemberOut:
    """FM-9, FM-16, and the per-member half of FM-15.

    `location_sharing_allowed` here is the head or spouse's **permission**; it never touches
    `user_settings.live_location_enabled`, which is the member's **consent**. Collapsing the
    two would let them revoke someone's own choice by flipping a switch twice.

    `role` does three things, and only one of them is a plain assignment:

    * `member` ⇄ `spouse` — promotion and demotion (FM-16);
    * `head` — a **transfer**: the incoming head takes the role and the outgoing one becomes a
      spouse, in one transaction. Two statements would leave a window with two heads or none,
      and the partial unique index would reject the first of them anyway;
    * demoting the head directly — refused. A family always has exactly one head, so the
      answer is to hand the role on, and the message says so.
    """
    family = await _load_family(db, family_id)
    member = _find_member(family, user_id)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)

    # The spouse asymmetry covers *every* field on this route, not just `role`: a spouse must
    # not be able to switch the head off the map either.
    await _reject_spouse_acting_on_head(db, user, family, member, trip)

    if "role" in changes and changes["role"] != member.role:
        # FM-16: promotion and demotion belong to the head, the owner, or an organiser. A
        # spouse who could promote would be able to appoint a confederate and outvote the
        # arrangement the head made — and one who could take the head role would be demoting
        # the head by a side door, which is the very thing the asymmetry forbids.
        await _reject_spouse_changing_a_role(db, user, family, trip)
        requested = changes["role"]
        if requested == ROLE_HEAD:
            outgoing = next((m for m in family.members if m.role == ROLE_HEAD), None)
            # Order matters against the partial unique index: vacate the role before filling
            # it, in one transaction, so there is never a moment with two heads.
            if outgoing is not None:
                outgoing.role = ROLE_SPOUSE
                await db.flush()
            member.role = ROLE_HEAD
        else:
            _reject_touching_the_owner(member, trip)
            _reject_leaving_the_family_headless(member)
            member.role = requested

    if "location_sharing_allowed" in changes:
        member.location_sharing_allowed = changes["location_sharing_allowed"]

    await db.commit()
    family = await _load_family(db, family_id)
    detail = await _detail(db, family, viewer, trip)
    out = next(m for m in detail.members if m.user_id == user_id)

    # Broadcast the *room's* view of this member, not the caller's: `member.updated` reaches
    # the whole trip, and `location_sharing_enabled` is nobody else's business.
    await ws.broadcast(
        family.trip_id,
        "member.updated",
        {
            "family_id": str(family_id),
            "member": _member_wire(family, user_id, trip, await _organiser_ids(db, trip)),
        },
    )
    return out


@router.delete(
    "/{family_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_family_manager), PLANNING_OR_HOLIDAY],
    summary="Remove someone from a family",
)
async def remove_member(
    family_id: uuid.UUID,
    user_id: uuid.UUID,
    db: DbDep,
    user: CurrentUser,
    trip: ActiveTrip,
) -> Response:
    """FM-9. Their account survives; their votes, comments and suggestions stay attributed.

    The per-member visibility switch goes with the membership row, which is why it lives
    there: re-inviting someone starts from the family's current default, not from a decision
    made about a membership that no longer exists.
    """
    family = await _load_family(db, family_id)
    member = _find_member(family, user_id)
    await _reject_spouse_acting_on_head(db, user, family, member, trip)
    _reject_touching_the_owner(member, trip)
    _reject_leaving_the_family_headless(member)

    trip_id = family.trip_id
    await db.delete(member)
    await db.commit()

    payload = {"family_id": str(family_id), "user_id": str(user_id)}
    await ws.broadcast(trip_id, "member.removed", payload)
    # Also to the removed user's own socket: their client refetches `auth/me`, which now
    # returns `family: null`, and shows "you are no longer on this trip" rather than erroring
    # its way through a screen it can no longer load.
    await ws.send_user(user_id, "member.removed", payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- broadcast payloads -------------------------------------------------------------------


def _wire(family: Family) -> dict:
    """The socket payload for a family: the coarse shape, always.

    The trip room contains other families, so a broadcast carrying an address would deliver
    it to people the REST API refuses to give it to. A client entitled to the full record
    refetches `GET /families/{id}`.
    """
    return family_out(family).model_dump(mode="json")


async def broadcast_member_updated(
    db: AsyncSession, user_id: uuid.UUID, trip: Trip | None
) -> None:
    """Announce that a person changed — a name, an avatar, or a visibility switch.

    Exported because the profile routes (`routers/me.py`) change the same person the member
    lists and map labels render, and a badge that only updates for the person who changed it
    is worse than one that never updates at all. They must not build the payload themselves:
    `member.updated` reaches the whole trip room, and the redaction lives in `_member_wire`.

    Silent when the user is in no family — there is no room to announce to, and someone
    mid-onboarding editing their name is not an event anybody is waiting for.
    """
    if trip is None:
        return
    member = await db.scalar(
        select(FamilyMember)
        .where(FamilyMember.user_id == user_id)
        .options(selectinload(FamilyMember.family).selectinload(Family.members))
    )
    if member is None:
        return
    await ws.broadcast(
        trip.id,
        "member.updated",
        {
            "family_id": str(member.family_id),
            "member": _member_wire(
                member.family, user_id, trip, await _organiser_ids(db, trip)
            ),
        },
    )


async def broadcast_member_joined(
    db: AsyncSession, family_id: uuid.UUID, user_id: uuid.UUID, trip: Trip | None
) -> None:
    """Announce a new member, so lists and counts update without a reload (FM-12)."""
    if trip is None:
        return
    family = await _load_family(db, family_id)
    await ws.broadcast(
        trip.id,
        "member.joined",
        {
            "family_id": str(family_id),
            "member": _member_wire(family, user_id, trip, await _organiser_ids(db, trip)),
        },
    )


def _member_wire(
    family: Family,
    user_id: uuid.UUID,
    trip: Trip | None,
    organiser_ids: frozenset[uuid.UUID] = frozenset(),
) -> dict:
    """The socket payload for a member, with consent redacted for the room.

    Built with a viewer entitled to nothing, so `location_sharing_enabled` is null. A
    member's own consent state must never reach the whole trip room, and the way to
    guarantee that is to serialise it as a stranger rather than to remember to delete a key.
    """
    stranger = Viewer(
        user_id=uuid.UUID(int=0),
        family_id=None,
        is_owner=False,
        is_organiser=False,
        manages_own_family=False,
    )
    member = _find_member(family, user_id)
    return member_out(
        member, stranger, owner_ids=_owner_ids(trip), organiser_ids=organiser_ids
    ).model_dump(mode="json")
