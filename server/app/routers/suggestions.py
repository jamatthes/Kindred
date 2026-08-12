"""Map suggestions — the core surface of Kindred.

Permissions and stage guards are dependencies, never handler-body checks (`CLAUDE.md`). The
End stage is read-only because every mutating route carries `require_stage("planning",
"holiday")`, not because anything here mentions `end`.

> NOTE (implementation): `design.md`'s permission column says `require_main_admin`. That
> dependency was renamed `require_organiser` when the role hierarchy was revised
> (`plan/overview.md` > Roles, 2026-08-11) — owner **or** an appointed organiser. Every "main
> admin" permission in this feature's docs means that. Editing and deleting are a different
> matter: a head or spouse *does* have rights over their own family's suggestions, because a
> suggestion belongs to the household that made it (`requirements.md` > Permissions). Both
> rules live in `deps.require_can_edit_suggestion`.

**No route in this module returns Google Place Details, and none ever should.** The Places ToS
permits persisting `place_id` and nothing else; photos, ratings, hours and summaries are
fetched by the browser, from Google, on card-open, and never travel through the server. See
`plan/features/map-suggestions/design.md` > HARD INVARIANT and the module docstring in
`app/schemas/suggestion.py`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import ws
from app.deps import (
    ActiveTrip,
    CurrentUser,
    DbDep,
    can_edit_suggestion,
    enforce_password_change,
    is_organiser,
    load_membership,
    moderated_family_id,
    require_can_edit_suggestion,
    require_member,
    require_organiser,
    require_stage,
)
from app.models import (
    STATUS_PROPOSED,
    STATUS_SCHEDULED,
    STATUS_TRANSITIONS,
    SUBJECT_SUGGESTION,
    TYPE_REGION,
    Suggestion,
    Trip,
    User,
)
from app.schemas.common import ApiError
from app.schemas.suggestion import (
    LinkPreviewIn,
    LinkPreviewOut,
    SuggestionCreate,
    SuggestionDetailOut,
    SuggestionListParams,
    SuggestionOut,
    SuggestionStatusUpdate,
    SuggestionType,
    SuggestionUpdate,
)
from app.services import comments as comment_service
from app.services import distances as distance_service
from app.services import suggestions as service
from app.services import votes as votes_service
from app.services.boundaries import (
    BoundaryResult,
    BoundaryServiceProtocol,
    EllipseFallback,
    get_boundary_service,
)
from app.services.link_preview import LinkPreviewServiceProtocol, get_link_preview_service

router = APIRouter(
    prefix="/suggestions",
    tags=["suggestions"],
    dependencies=[Depends(enforce_password_change)],
)

#: Spread into every mutating route, so adding one without it is a visible omission.
PLANNING_OR_HOLIDAY = Depends(require_stage("planning", "holiday"))


def _require_trip(trip: Trip | None) -> Trip:
    if trip is None:
        raise ApiError(409, "no_trip", "There is no trip yet.")
    return trip


async def _own_family_id(db: AsyncSession, user: User, trip: Trip):
    """The caller's family, for "how far is it from *us*" — the number a card leads with."""
    membership = await load_membership(db, user.id, trip.id)
    return membership[0].id if membership else None


# --- serialisation ---------------------------------------------------------------------------


async def _out(
    db: AsyncSession,
    row: service.SuggestionRow,
    *,
    caller: User,
    trip: Trip,
    organiser: bool,
    modes: dict[str, str],
    distances: dict | None = None,
) -> SuggestionOut:
    """One row, with its capability flags resolved for this caller.

    The flags are computed from the same predicate the dependency enforces
    (`deps.can_edit_suggestion`), so a button the UI renders and a request the server accepts
    can never disagree.

    `modes` and `distances` are both fetched once per request rather than per row: a
    suggestion's voting mode is its `type`'s, and its distances come from one bulk read
    (`app/services/distances.py`, which cannot call Google). Looking either up per row would
    reintroduce the N+1 the service layer exists to avoid.
    """
    children = [
        await _out(
            db,
            child,
            caller=caller,
            trip=trip,
            organiser=organiser,
            modes=modes,
            distances=distances,
        )
        for child in row.children
    ]
    return service.serialise(
        row,
        can_edit=await can_edit_suggestion(db, caller, trip, row.suggestion),
        can_change_status=organiser,
        children=children,
        mode=modes.get(row.suggestion.type, votes_service.DEFAULT_MODE),
        distances=(distances or {}).get(row.suggestion.id, []),
    )


async def _broadcast(trip: Trip, event: str, payload: dict) -> None:
    """Emitted **after** the commit, never before — a client that refetches on receipt must not
    be able to read state older than the event announcing it (`ws.broadcast`)."""
    await ws.broadcast(trip.id, event, payload)


# --- reading ----------------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[SuggestionOut],
    dependencies=[Depends(require_member)],
    summary="Every suggestion on the trip",
)
async def list_suggestions(
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
    type: Annotated[list[SuggestionType], Query()] = None,  # noqa: A002 - the wire name
    status_: Annotated[list[str], Query(alias="status")] = None,
    family_id: Annotated[list[uuid.UUID], Query()] = None,
    sort: str = "created_desc",
    group: bool = True,
    include_rejected: bool = False,
) -> list[SuggestionOut]:
    """The single source for both the map and the list view (`requirements.md` S1/S2).

    One request renders both, which is what makes "filters apply to map and list
    simultaneously" true by construction rather than by two clients agreeing to behave.
    """
    if trip is None:
        return []
    params = SuggestionListParams(
        type=type or [],
        status=status_ or [],
        family_id=family_id or [],
        sort=sort,
        group=group,
        include_rejected=include_rejected,
    )
    rows = await service.list_suggestions(db, trip, params, caller_id=user.id)
    organiser = await is_organiser(db, user, trip)
    modes = await votes_service.resolve_modes(db, trip.id)
    # The list row shows the caller's own family's distance, so only that family is fetched —
    # a lighter payload than every family's, and the side panel asks
    # `GET /suggestions/{id}/distances` when it wants the rest (`distances/design.md`).
    own_family = await _own_family_id(db, user, trip)
    distances = await distance_service.get_distances_bulk(
        db, trip, family_id=own_family, own_family_id=own_family
    )
    return [
        await _out(
            db,
            row,
            caller=user,
            trip=trip,
            organiser=organiser,
            modes=modes,
            distances=distances,
        )
        for row in rows
    ]


@router.get(
    "/{suggestion_id}",
    response_model=SuggestionDetailOut,
    dependencies=[Depends(require_member)],
    summary="One suggestion, with its comment thread",
)
async def read_suggestion(
    suggestion_id: uuid.UUID, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> SuggestionDetailOut:
    """The list shape plus the thread. **No Google details** — the browser fetches those
    itself on card-open and never sends them back (`design.md` > HARD INVARIANT)."""
    current = _require_trip(trip)
    row = await service.load_suggestion(db, suggestion_id, current, caller_id=user.id)
    organiser = await is_organiser(db, user, current)
    own_family = await _own_family_id(db, user, current)
    base = await _out(
        db,
        row,
        caller=user,
        trip=current,
        organiser=organiser,
        modes=await votes_service.resolve_modes(db, current.id),
        # The detail view carries **every** family's distance: this is the panel, and comparing
        # whose journey is longest is the point of the expander.
        distances={
            row.suggestion.id: await distance_service.get_distances_for_suggestion(
                db, row.suggestion, current, own_family_id=own_family
            )
        },
    )
    return SuggestionDetailOut(
        **base.model_dump(),
        # The thread comes from the shared implementation (`voting-comments`), which is also
        # what serves `/comments` and `/polls/{id}/comments` — so mentions, soft delete and the
        # capability flags behave identically wherever a thread is rendered.
        comments=await comment_service.list_thread(
            db,
            SUBJECT_SUGGESTION,
            suggestion_id,
            current,
            caller=user,
            organiser=organiser,
            moderates_family_id=await moderated_family_id(db, user),
        ),
    )


# --- creating ------------------------------------------------------------------------------------


@router.post(
    "",
    response_model=SuggestionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_member), PLANNING_OR_HOLIDAY],
    summary="Propose something",
)
async def create_suggestion(
    payload: SuggestionCreate,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
    boundaries: Annotated[BoundaryServiceProtocol, Depends(get_boundary_service)],
    background: BackgroundTasks = None,
) -> SuggestionOut:
    """Any member may propose anything (`requirements.md` S3-S6). Confirmation is the
    organiser's, later, through the status route.

    **Only the fields in `SuggestionCreate` are stored**, and that model forbids extras — which
    is how an inflated payload carrying Google's photos or rating becomes a `422` rather than a
    ToS violation. `tests/test_router_suggestions.py` asserts it.
    """
    current = _require_trip(trip)
    geometry = payload.geometry_geojson
    lat, lng = payload.lat, payload.lng

    if payload.type == TYPE_REGION:
        if geometry is None:
            geometry = await _boundary_geometry(boundaries, payload.boundary_query or "")
        # The server recomputes the centroid rather than trusting the client's point: a shape
        # drawn in Cornwall with a point sent in Kent would otherwise sort, select and measure
        # its distance from the wrong place.
        lat, lng = service.resolve_centroid(geometry)

    suggestion = Suggestion(
        trip_id=current.id,
        type=payload.type,
        title=payload.title.strip(),
        notes=(payload.notes or "").strip() or None,
        status=STATUS_PROPOSED,
        created_by=user.id,
        lat=lat,
        lng=lng,
        geometry_geojson=geometry,
        place_id=payload.place_id,
        # User-authored only. Never Google's response — see the module docstring.
        place_snapshot_json=(
            payload.place_snapshot.model_dump(exclude_none=True)
            if payload.place_snapshot
            else None
        ),
        external_url=payload.external_url,
    )
    db.add(suggestion)
    await db.commit()

    row = await service.load_suggestion(db, suggestion.id, current, caller_id=user.id)
    # Queued after the commit and run after the response: `CLAUDE.md`'s "never call Google in a
    # render path" is what the whole caching design rests on, and a suggestion must not wait on
    # a distance — the suggestion is the user's work, the distance is a convenience.
    await service.queue_distance_recompute(db, row.suggestion, background)
    out = await _out(
        db,
        row,
        caller=user,
        trip=current,
        organiser=await is_organiser(db, user, current),
        modes=await votes_service.resolve_modes(db, current.id),
    )
    await _broadcast(current, "suggestion.created", {"suggestion": out.model_dump(mode="json")})
    return out


async def _boundary_geometry(boundaries: BoundaryServiceProtocol, query: str) -> dict:
    """A named locality's real administrative boundary, from OpenStreetMap.

    One fetch, at creation, stored forever (`design.md` > Named-locality regions) — never
    re-fetched on render, per the API-cost rule. When Nominatim geocodes the query but has no
    boundary for it, the fitted ellipse is stored instead, labelled `fallback_ellipse` so the
    UI can mark it approximate and offer "refine the outline". A raw bounding-box rectangle is
    never stored: it would claim a precision the data does not have.
    """
    result = await boundaries.lookup(query)
    if isinstance(result, BoundaryResult):
        return result.geojson
    if isinstance(result, EllipseFallback):
        return result.ellipse_geojson
    raise ApiError(
        404,
        "boundary_not_found",
        f"No place called “{query}” was found. Draw the area instead.",
    )


# --- editing ---------------------------------------------------------------------------------------


@router.patch(
    "/{suggestion_id}",
    response_model=SuggestionOut,
    dependencies=[PLANNING_OR_HOLIDAY],
    summary="Edit a suggestion",
)
async def update_suggestion(
    payload: SuggestionUpdate,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
    suggestion: Annotated[Suggestion, Depends(require_can_edit_suggestion)],
    background: BackgroundTasks = None,
) -> SuggestionOut:
    """Author, their family's head or spouse, or an organiser — enforced by the dependency.

    `status` is absent from `SuggestionUpdate` entirely: it has its own route, its own
    permission and its own transition table, so a member cannot approve their own suggestion by
    patching a field.
    """
    current = _require_trip(trip)
    before = (suggestion.lat, suggestion.lng)
    changes = payload.model_dump(exclude_unset=True)

    if "place_snapshot" in changes:
        snapshot = changes.pop("place_snapshot")
        suggestion.place_snapshot_json = snapshot or None
    for field, value in changes.items():
        setattr(suggestion, field, value.strip() if isinstance(value, str) else value)

    if suggestion.type == TYPE_REGION:
        if suggestion.geometry_geojson is None:
            raise ApiError(
                422, "invalid_geometry", "A region needs a shape on the map."
            )
        suggestion.lat, suggestion.lng = service.resolve_centroid(suggestion.geometry_geojson)
    elif suggestion.geometry_geojson is not None:
        # Changing an accommodation into an activity keeps the pin and drops the shape, rather
        # than refusing the edit over a field the user never mentioned.
        suggestion.geometry_geojson = None

    await db.commit()

    row = await service.load_suggestion(db, suggestion.id, current, caller_id=user.id)
    moved = service.moved_beyond_epsilon(*before, row.suggestion.lat, row.suggestion.lng)
    if moved:
        await service.queue_distance_recompute(db, row.suggestion, background, moved=True)

    own_family = await _own_family_id(db, user, current)
    out = await _out(
        db,
        row,
        caller=user,
        trip=current,
        organiser=await is_organiser(db, user, current),
        modes=await votes_service.resolve_modes(db, current.id),
        # Without this, every edit's response (and the suggestion.updated broadcast built
        # from the same `out`) reported `distances: []` regardless of what distance_cache
        # actually holds — `_out`'s own `distances or {}` default, silently taken by every
        # call site that forgets to pass one. Harmless while the client ignored the payload
        # (found once suggestion.updated started actually being applied, M3 integration
        # pass); real once it isn't, most visibly right after a move, where a stale-empty
        # suggestion.updated landing after suggestion.moved would wipe out the "back to
        # pending" placeholder that event exists to show. Mirrors read_suggestion's own
        # per-suggestion distances fetch just above.
        distances={
            row.suggestion.id: await distance_service.get_distances_for_suggestion(
                db, row.suggestion, current, own_family_id=own_family
            )
        },
    )
    await _broadcast(current, "suggestion.updated", {"suggestion": out.model_dump(mode="json")})
    if moved:
        await _broadcast(
            current,
            "suggestion.moved",
            {
                "id": str(row.suggestion.id),
                "lat": row.suggestion.lat,
                "lng": row.suggestion.lng,
                "geometry_geojson": row.suggestion.geometry_geojson,
            },
        )
    return out


@router.delete(
    "/{suggestion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[PLANNING_OR_HOLIDAY],
    summary="Delete a suggestion",
)
async def delete_suggestion(
    db: DbDep,
    trip: ActiveTrip,
    suggestion: Annotated[Suggestion, Depends(require_can_edit_suggestion)],
) -> Response:
    """Refused with `409` once the suggestion is on the itinerary.

    Deleting something the group has already scheduled would remove a day's plan from under
    everyone; the organiser unschedules it first. `poll_options.suggestion_id` is `ON DELETE
    SET NULL`, so a poll whose decision seeded this region has its link cleared by the database
    rather than by this handler remembering to.
    """
    current = _require_trip(trip)
    if suggestion.status == STATUS_SCHEDULED:
        # NOTE (itinerary-timeline, M4): `design.md` also wants the *day* named in this
        # message, from the `itinerary_items` row referencing the suggestion. That table does
        # not exist until M4, so the check is on `status` alone for now and the message says
        # what to do instead of when. M4 adds the row lookup and the day.
        raise ApiError(
            409,
            "suggestion_scheduled",
            "That is on the itinerary. Ask an organiser to unschedule it first.",
        )

    # `comments` is polymorphic and carries no FK to its subject, so this cascade is ours — in
    # the same transaction as the delete (`models/comment.py`). Hard, not soft: the thing being
    # discussed is gone, so there is nothing for an undo to restore the discussion to.
    # `suggestion_votes` needs no such help — it has a real FK and cascades in the database.
    await comment_service.delete_for_subject(db, SUBJECT_SUGGESTION, suggestion.id)
    suggestion_id = suggestion.id
    await db.delete(suggestion)
    await db.commit()

    await _broadcast(current, "suggestion.deleted", {"id": str(suggestion_id)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/{suggestion_id}/status",
    response_model=SuggestionOut,
    dependencies=[Depends(require_organiser), PLANNING_OR_HOLIDAY],
    summary="Shortlist, approve, reject, or send back to proposed",
)
async def update_status(
    suggestion_id: uuid.UUID,
    payload: SuggestionStatusUpdate,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
) -> SuggestionOut:
    """The transitions are validated against `models.suggestion.STATUS_TRANSITIONS`.

    `scheduled` is refused with `422`: it is `itinerary-timeline`'s to set, when the suggestion
    is placed on a day. A suggestion that *is* scheduled has no move available here at all —
    the itinerary is the only thing that may take it back out, which is what stops the two
    features from disagreeing about what is happening on Tuesday.
    """
    current = _require_trip(trip)
    row = await service.load_suggestion(db, suggestion_id, current, caller_id=user.id)
    suggestion = row.suggestion

    if (
        payload.expected_status is not None
        and payload.expected_status != suggestion.status
    ):
        # The other organiser committed first. Their decision stands, and this one is told what
        # it now is rather than overwriting a change it was never shown.
        raise ApiError(
            409,
            "status_changed",
            f"Somebody else already moved this to {suggestion.status}.",
        )

    allowed = STATUS_TRANSITIONS.get(suggestion.status, ())
    if payload.status == suggestion.status:
        pass  # idempotent: re-sending the current status is a no-op, not an error
    elif payload.status not in allowed:
        raise ApiError(
            422,
            "invalid_transition",
            f"A {suggestion.status} suggestion cannot become {payload.status}.",
        )
    else:
        suggestion.status = payload.status
        await db.commit()

    row = await service.load_suggestion(db, suggestion_id, current, caller_id=user.id)
    out = await _out(
        db,
        row,
        caller=user,
        trip=current,
        organiser=True,
        modes=await votes_service.resolve_modes(db, current.id),
    )
    await _broadcast(
        current,
        "suggestion.status_changed",
        {
            "id": str(suggestion_id),
            "status": row.suggestion.status,
            "changed_by": str(user.id),
        },
    )
    return out


# --- link preview -------------------------------------------------------------------------------

link_preview_router = APIRouter(
    prefix="/link-preview",
    tags=["suggestions"],
    dependencies=[Depends(enforce_password_change), Depends(require_member)],
)


@link_preview_router.post(
    "",
    response_model=LinkPreviewOut,
    responses={204: {"description": "No preview available — the normal outcome for many sites."}},
    dependencies=[PLANNING_OR_HOLIDAY],
    summary="Best-effort OpenGraph preview of a pasted URL",
)
async def read_link_preview(
    payload: LinkPreviewIn,
    previews: Annotated[LinkPreviewServiceProtocol, Depends(get_link_preview_service)],
) -> Response | LinkPreviewOut:
    """`204` is a normal outcome, not an error (`requirements.md` S6).

    Sites block scrapers, time out, and redirect into places the SSRF guard refuses; in every
    one of those cases the user simply types the title, and the UI shows nothing at all. That
    is why this returns "no content" rather than a `4xx` the client would have to suppress.

    The fetch itself — scheme check, DNS resolution, private-address rejection, timeout,
    redirect budget, size cap, parsing, in-memory cache — is
    `app/services/link_preview.py`'s, and **nothing is persisted**: there is deliberately no
    `link_preview_cache` table in v1.
    """
    preview = await previews.fetch(payload.url)
    if preview is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return LinkPreviewOut(**preview.model_dump())
