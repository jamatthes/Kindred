"""Comment threads, for every subject.

**One set of routes serves polls, suggestions and itinerary items.** `plan/architecture.md`
said so when `polls` shipped the first thread: "`/comments/{id}` is deliberately not under
`/polls`: the table is polymorphic, and `voting-comments` (M3) will serve suggestion and
itinerary threads from the same routes rather than duplicating them per subject." This module
is that promise kept — `polls`' own `/polls/{id}/comments` endpoints now delegate to the same
service, so mentions, soft delete and undo work identically on a poll thread.

**Nobody edits another person's words.** `PATCH` is behind `require_comment_author`, with no
organiser override and no owner override. That is a permission which does not exist, rather
than one that is withheld — an organiser who objects to a comment deletes it, under their own
name, which is a different act with a different record.

**Deleting is soft, and undo is a real server operation.** See `services/comments.py` for why
a client-side undo timer was rejected.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import ws
from app.deps import (
    ActiveTrip,
    CurrentUser,
    DbDep,
    enforce_password_change,
    is_organiser,
    moderated_family_id,
    require_can_delete_comment,
    require_comment_author,
    require_member,
    require_stage,
)
from app.models import Comment, Trip
from app.schemas.comment import CommentCreate, CommentOut, CommentUpdate, SubjectType
from app.schemas.common import ApiError
from app.services import comments as service

router = APIRouter(
    prefix="/comments",
    tags=["comments"],
    dependencies=[Depends(enforce_password_change), Depends(require_member)],
)

#: Spread into every mutating route, so adding one without it is a visible omission.
PLANNING_OR_HOLIDAY = Depends(require_stage("planning", "holiday"))


def _require_trip(trip: Trip | None) -> Trip:
    if trip is None:
        raise ApiError(409, "no_trip", "There is no trip yet.")
    return trip


async def _serialise(
    db: AsyncSession, comment: Comment, *, caller, trip: Trip
) -> CommentOut:
    return service.serialise(
        comment,
        caller=caller,
        organiser=await is_organiser(db, caller, trip),
        families=await service.family_lookup(db, trip),
        members=await service.trip_member_ids(db, trip),
        moderates_family_id=await moderated_family_id(db, caller),
    )


async def _broadcast(trip: Trip, event: str, payload: dict) -> None:
    await ws.broadcast(trip.id, event, payload)


# --- reading -----------------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[CommentOut],
    summary="The thread on one subject",
)
async def list_comments(
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
    subject_type: Annotated[SubjectType, Query()],
    subject_id: Annotated[uuid.UUID, Query()],
) -> list[CommentOut]:
    """Flat, oldest first, soft-deleted rows excluded.

    Available in every stage: a frozen trip is an archive, and an archive with its discussion
    removed would be a worse record than the group chat this replaced.

    The retention sweep runs from here rather than from a scheduler — see
    `services/comments.py::purge_expired` for why a home-server deployment sweeps lazily.
    """
    current = _require_trip(trip)
    purged = await service.purge_expired(db)
    if purged:
        await db.commit()
    return await service.list_thread(
        db,
        subject_type,
        subject_id,
        current,
        caller=user,
        organiser=await is_organiser(db, user, current),
        moderates_family_id=await moderated_family_id(db, user),
    )


# --- writing -----------------------------------------------------------------------------------


@router.post(
    "",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[PLANNING_OR_HOLIDAY],
    summary="Post a comment",
)
async def create_comment(
    payload: CommentCreate, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> CommentOut:
    """The subject is validated against the database, not trusted.

    `subject_id` has no foreign key — that is the cost of one thread implementation serving
    three subjects — so "does this exist, and is it on your trip" is a mandatory check. A
    subject on another trip is a `403`; one that does not exist is a `404`.
    """
    current = _require_trip(trip)
    comment, mentioned = await service.create(
        db,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        body=payload.body,
        author=user,
        trip=current,
    )
    await db.commit()
    await db.refresh(comment)

    out = await _serialise(db, comment, caller=user, trip=current)
    await _broadcast(
        current,
        "comment.created",
        {
            "subject_type": payload.subject_type,
            "subject_id": str(payload.subject_id),
            "comment": out.model_dump(mode="json"),
        },
    )
    await _notify(mentioned, comment, user)
    return out


async def _notify(recipients: list[uuid.UUID], comment: Comment, author) -> None:
    """`notification.new` per mentioned user, to that user's own sockets only.

    Per recipient rather than to the trip room, for the reason `architecture.md` gives: a
    mention is addressed to one person, and broadcasting it would tell everybody who was
    pinged about what.
    """
    for user_id in recipients:
        await ws.send_user(
            user_id,
            "notification.new",
            {
                "type": "mention",
                "subject_type": comment.subject_type,
                "subject_id": str(comment.subject_id),
                "comment_id": str(comment.id),
                "author_name": author.display_name,
                "deep_link": service.deep_link(comment),
            },
        )


@router.patch(
    "/{comment_id}",
    response_model=CommentOut,
    dependencies=[PLANNING_OR_HOLIDAY],
    summary="Edit my own comment",
)
async def update_comment(
    payload: CommentUpdate,
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
    comment: Annotated[Comment, Depends(require_comment_author)],
) -> CommentOut:
    """Author only, at every role. `edited_at` is set and shown as an "edited" marker — an edit
    that left no trace would falsify the discussion record.

    Only **newly added** mentions notify; the previous mention set is diffed, so fixing a typo
    does not re-ping everybody named in the sentence.
    """
    current = _require_trip(trip)
    mentioned = await service.update(
        db, comment, body=payload.body, author=user, trip=current
    )
    await db.commit()
    await db.refresh(comment)

    out = await _serialise(db, comment, caller=user, trip=current)
    await _broadcast(
        current,
        "comment.updated",
        {
            "subject_type": comment.subject_type,
            "subject_id": str(comment.subject_id),
            "comment": out.model_dump(mode="json"),
        },
    )
    await _notify(mentioned, comment, user)
    return out


@router.delete(
    "/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[PLANNING_OR_HOLIDAY],
    summary="Delete a comment",
)
async def delete_comment(
    db: DbDep,
    trip: ActiveTrip,
    user: CurrentUser,
    comment: Annotated[Comment, Depends(require_can_delete_comment)],
) -> Response:
    """A **soft** delete: the row survives for the retention window so undo is real.

    The UI treats the two cases differently — undo for your own (low stakes, and the text is
    yours to retype anyway), a real confirm plus a "comment removed" tombstone for somebody
    else's, because it is not your content to make vanish quietly.
    """
    current = _require_trip(trip)
    await service.soft_delete(db, comment, user)
    await db.commit()

    await _broadcast(
        current,
        "comment.deleted",
        {
            "id": str(comment.id),
            "subject_type": comment.subject_type,
            "subject_id": str(comment.subject_id),
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{comment_id}/undo-delete",
    response_model=CommentOut,
    dependencies=[PLANNING_OR_HOLIDAY],
    summary="Undo my own delete",
)
async def undo_delete_comment(
    comment_id: uuid.UUID, db: DbDep, trip: ActiveTrip, user: CurrentUser
) -> CommentOut:
    """Restores the comment in place, preserving its position in the thread.

    Permitted only to whoever pressed delete, and only inside the retention window; every other
    case is `404`. Broadcasts `comment.created`, not a restore-specific event: a restore is
    indistinguishable from a create for a consumer reconciling by `id`, and inventing a sixth
    event would give every client a branch to get wrong.
    """
    current = _require_trip(trip)
    comment = await service.undo_delete(db, comment_id, user)
    # Only after the row is back does the caller's right to see it become checkable in the
    # ordinary way; a comment restored onto another trip's subject would be the same leak the
    # create path guards against.
    await service.verify_subject_access(
        db, comment.subject_type, comment.subject_id, current
    )
    await db.commit()
    await db.refresh(comment)

    out = await _serialise(db, comment, caller=user, trip=current)
    await _broadcast(
        current,
        "comment.created",
        {
            "subject_type": comment.subject_type,
            "subject_id": str(comment.subject_id),
            "comment": out.model_dump(mode="json"),
        },
    )
    return out
