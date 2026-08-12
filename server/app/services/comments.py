"""Comment threads for every subject, and the mentions they generate.

**`comments.subject_id` has no foreign key**, because one thread implementation serves polls,
suggestions and itinerary items. That trade has a security consequence the schema cannot
express: nothing stops a caller naming a subject on somebody else's trip. `verify_subject_access`
is therefore called on **every** path in this module — reads included — and a route that skips
it is a cross-trip data leak with no constraint standing behind it.

**Deletion is soft.** `plan/design-system.md` mandates undo over confirm for deleting your own
comment, and a hard `DELETE` cannot be undone: the window would have to live entirely in the
client, so a closed tab, a crash or a navigation would lose the text irrecoverably, and other
people watching the thread would see it vanish and reappear with no server-side truth. Instead
`deleted_at` is set, `undo_delete` clears it, and `purge_expired` hard-deletes rows past the
retention window so this never becomes an accidental permanent archive of deleted text.

**Undo belongs to whoever pressed delete**, which is why `deleted_by` is a column rather than a
request-scoped variable: an author whose comment an organiser removed must not be able to put
it back, and that question outlives the session that asked it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    COMMENT_RETENTION,
    NOTIFICATION_MENTION,
    SUBJECT_ITINERARY_ITEM,
    SUBJECT_POLL,
    SUBJECT_SUGGESTION,
    Comment,
    Family,
    FamilyMember,
    Notification,
    Poll,
    Suggestion,
    Trip,
    User,
    visible_comments,
)
from app.schemas.comment import CommentOut
from app.schemas.common import ApiError, forbidden
from app.services.mentions import newly_mentioned, parse_mentions

#: How long the *affordance* is offered for. The client counts this down; the server does not
#: enforce it, because a slow network must not be able to eat somebody's undo. The retention
#: window (`COMMENT_RETENTION`) is what the server enforces, and it is far longer on purpose.
UNDO_AFFORDANCE = timedelta(seconds=10)


# --- subject access ------------------------------------------------------------------------------


async def verify_subject_access(
    db: AsyncSession, subject_type: str, subject_id: uuid.UUID, trip: Trip
) -> None:
    """The check that stands in for the missing foreign key. **Call it on every path.**

    Two distinct failures, deliberately given different codes: a subject that does not exist at
    all is `404`, and one that exists on another trip is `403`. Collapsing them into one answer
    would either tell a stranger which ids are real or tell a legitimate caller their own
    subject is missing.
    """
    trip_id = await _subject_trip_id(db, subject_type, subject_id)
    if trip_id is None:
        raise ApiError(404, "not_found", "That item does not exist.")
    if trip_id != trip.id:
        raise forbidden("That item belongs to another trip.")


async def _subject_trip_id(
    db: AsyncSession, subject_type: str, subject_id: uuid.UUID
) -> uuid.UUID | None:
    if subject_type == SUBJECT_SUGGESTION:
        return await db.scalar(select(Suggestion.trip_id).where(Suggestion.id == subject_id))
    if subject_type == SUBJECT_POLL:
        return await db.scalar(select(Poll.trip_id).where(Poll.id == subject_id))
    if subject_type == SUBJECT_ITINERARY_ITEM:
        # `itinerary_items` arrives with `itinerary-timeline` (M4). Until then the subject type
        # is accepted by the schema — the vocabulary is the database's, not this feature's — and
        # resolves to nothing, so a comment cannot be attached to an item that does not exist.
        return None
    return None  # pragma: no cover - the schema's Literal already constrains this


# --- reading ------------------------------------------------------------------------------------


async def list_thread(
    db: AsyncSession,
    subject_type: str,
    subject_id: uuid.UUID,
    trip: Trip,
    *,
    caller: User,
    organiser: bool,
    moderates_family_id: uuid.UUID | None = None,
) -> list[CommentOut]:
    """The flat thread, oldest first, live rows only.

    Flat by design (V6): a family deciding where to eat does not need a reply tree, and one
    level keeps the mobile sheet readable.
    """
    await verify_subject_access(db, subject_type, subject_id, trip)
    rows = (
        (await db.scalars(visible_comments(subject_type, subject_id))).unique().all()
    )
    families = await family_lookup(db, trip)
    members = await trip_member_ids(db, trip)
    return [
        serialise(
            row,
            caller=caller,
            organiser=organiser,
            families=families,
            members=members,
            moderates_family_id=moderates_family_id,
        )
        for row in rows
    ]


async def family_lookup(db: AsyncSession, trip: Trip) -> dict:
    """user_id -> (family_id, colour slot, custom colour), for the thread's colour accents."""
    rows = await db.execute(
        select(FamilyMember.user_id, Family.id, Family.color, Family.color_custom)
        .join(Family, Family.id == FamilyMember.family_id)
        .where(Family.trip_id == trip.id)
    )
    return {row[0]: (row[1], row[2], row[3]) for row in rows.all()}


async def trip_member_ids(db: AsyncSession, trip: Trip) -> set[uuid.UUID]:
    """Everyone on the trip. A mention of anybody else renders as plain text (V7)."""
    rows = await db.scalars(
        select(FamilyMember.user_id)
        .join(Family, Family.id == FamilyMember.family_id)
        .where(Family.trip_id == trip.id)
    )
    return set(rows.all())


def serialise(
    comment: Comment,
    *,
    caller: User,
    organiser: bool,
    families: dict,
    members: set[uuid.UUID],
    moderates_family_id: uuid.UUID | None = None,
) -> CommentOut:
    """One comment as the wire sees it, with its capability flags resolved for this caller.

    `can_edit` is **author only, at every role including the owner's**: editing someone else's
    words under their name is never appropriate, so the permission does not exist rather than
    being withheld (`requirements.md`'s NOTE under the permissions table).

    `can_delete` adds two: an organiser may delete anyone's, and the head or spouse of the
    author's family may delete theirs — a lightweight moderation path that does not require
    pulling in an organiser, and a deliberate extension of "a family head manages their own
    family". `moderates_family_id` is the family the caller may moderate, or ``None``.
    """
    family = families.get(comment.author_id)
    is_author = comment.author_id is not None and comment.author_id == caller.id
    can_delete = (
        is_author
        or organiser
        or (moderates_family_id is not None and family is not None and family[0] == moderates_family_id)
    )
    return CommentOut(
        id=comment.id,
        subject_type=comment.subject_type,
        subject_id=comment.subject_id,
        author_id=comment.author_id,
        author_name=(
            comment.author.display_name if comment.author else "Someone who has left"
        ),
        family_id=family[0] if family else None,
        family_color=family[1] if family else None,
        family_color_custom=family[2] if family else None,
        body=comment.body,
        # Only on-trip mentions are reported: an off-trip or unknown uuid renders as plain text
        # and notified nobody, so listing it here would describe a link the UI must not draw.
        mentions=[uid for uid in parse_mentions(comment.body) if uid in members],
        created_at=comment.created_at,
        edited_at=comment.edited_at,
        can_edit=is_author,
        can_delete=can_delete,
    )


async def load(db: AsyncSession, comment_id: uuid.UUID, *, include_deleted: bool = False) -> Comment:
    """One comment. Soft-deleted rows are invisible unless explicitly asked for — the undo
    lookup is the only caller that asks."""
    comment = await db.scalar(select(Comment).where(Comment.id == comment_id))
    if comment is None or (comment.deleted_at is not None and not include_deleted):
        raise ApiError(404, "not_found", "That comment does not exist.")
    return comment


# --- writing ------------------------------------------------------------------------------------


async def create(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: uuid.UUID,
    body: str,
    author: User,
    trip: Trip,
) -> tuple[Comment, list[uuid.UUID]]:
    """Post a comment, and return it with the users who should be notified.

    The notification rows are written here, in the same transaction as the comment, so a mention
    can never exist in text without the corresponding row — and the *delivery* (the bell, the
    push) belongs to `notifications` (M6), which reads what this writes.
    """
    await verify_subject_access(db, subject_type, subject_id, trip)
    comment = Comment(
        subject_type=subject_type,
        subject_id=subject_id,
        author_id=author.id,
        body=body.strip(),
    )
    db.add(comment)
    await db.flush()

    recipients = await _notify_mentions(
        db, parse_mentions(comment.body), comment=comment, author=author, trip=trip
    )
    return comment, recipients


async def update(
    db: AsyncSession, comment: Comment, *, body: str, author: User, trip: Trip
) -> list[uuid.UUID]:
    """Edit, setting `edited_at`, and notify **only newly added** mentions.

    Re-pinging everyone on a typo fix would train the group to ignore the bell, and the mention
    they already received still deep-links to the comment they would be told about again — so
    the second notification carries no information.
    """
    await verify_subject_access(db, comment.subject_type, comment.subject_id, trip)
    added = newly_mentioned(comment.body, body)
    comment.body = body.strip()
    comment.edited_at = datetime.now(UTC)
    await db.flush()
    return await _notify_mentions(db, added, comment=comment, author=author, trip=trip)


async def _notify_mentions(
    db: AsyncSession,
    mentioned: list[uuid.UUID],
    *,
    comment: Comment,
    author: User,
    trip: Trip,
) -> list[uuid.UUID]:
    """One `notifications` row per mentioned person who is on the trip and is not the author.

    Three exclusions, each from `design.md`'s edge-case table: a uuid that is not a trip member
    (rendered as plain text, notifies nobody), a uuid that is not an account at all (same), and
    the author themselves (you know what you just wrote).
    """
    if not mentioned:
        return []
    members = await trip_member_ids(db, trip)
    recipients = [uid for uid in mentioned if uid in members and uid != author.id]
    for user_id in recipients:
        db.add(
            Notification(
                recipient_user_id=user_id,
                type=NOTIFICATION_MENTION,
                payload_json={
                    "subject_type": comment.subject_type,
                    "subject_id": str(comment.subject_id),
                    "comment_id": str(comment.id),
                    "author_name": author.display_name,
                    "deep_link": deep_link(comment),
                },
            )
        )
    return recipients


def deep_link(comment: Comment) -> str:
    if comment.subject_type == SUBJECT_POLL:
        return f"/polls/{comment.subject_id}#comment-{comment.id}"
    return f"/map/{comment.subject_id}#comment-{comment.id}"


async def soft_delete(db: AsyncSession, comment: Comment, actor: User) -> None:
    """Set `deleted_at` and record who did it. The row survives for the retention window."""
    comment.deleted_at = datetime.now(UTC)
    comment.deleted_by = actor.id


async def undo_delete(db: AsyncSession, comment_id: uuid.UUID, actor: User) -> Comment:
    """Restore a comment the **caller** deleted, if it is still inside the retention window.

    Every other case is a `404` rather than a `403`, and deliberately so: "that undo is not
    yours" and "that undo has expired" are both, from the client's point of view, "the
    affordance is gone" — and a `403` would confirm to somebody guessing ids that a deleted
    comment exists there.
    """
    comment = await db.scalar(select(Comment).where(Comment.id == comment_id))
    if comment is None or comment.deleted_at is None:
        raise ApiError(404, "not_found", "There is nothing to undo.")
    if comment.deleted_by != actor.id:
        raise ApiError(404, "not_found", "There is nothing to undo.")
    if _expired(comment.deleted_at):
        raise ApiError(404, "not_found", "That is too old to undo.")
    comment.deleted_at = None
    comment.deleted_by = None
    return comment


def _expired(deleted_at: datetime, *, now: datetime | None = None) -> bool:
    if deleted_at.tzinfo is None:  # a naive value from a raw driver round-trip
        deleted_at = deleted_at.replace(tzinfo=UTC)
    return deleted_at + COMMENT_RETENTION <= (now or datetime.now(UTC))


async def purge_expired(db: AsyncSession) -> int:
    """Hard-delete soft-deleted rows past the retention window. Returns how many went.

    Swept lazily from the thread read rather than by a scheduler, which is the pattern
    `foundation` already uses for expired sessions and login attempts: this deployment is one
    container on a home server, and a cron entry that has to be installed separately is a cron
    entry that will not exist on somebody's machine. The cost is one cheap `DELETE` on a thread
    read; the benefit is that the retention promise cannot quietly stop being true.
    """
    cutoff = datetime.now(UTC) - COMMENT_RETENTION
    result = await db.execute(
        sql_delete(Comment).where(
            Comment.deleted_at.isnot(None), Comment.deleted_at < cutoff
        )
    )
    return result.rowcount or 0


async def delete_for_subject(db: AsyncSession, subject_type: str, subject_id: uuid.UUID) -> None:
    """Hard-delete every comment on a subject that is itself being deleted.

    `comments` is polymorphic and carries no FK, so this cascade is the service layer's — called
    in the same transaction as the subject's delete. A *soft* delete would be wrong here: the
    thing being discussed is gone, so there is nothing for an undo to restore the discussion to.
    """
    await db.execute(
        sql_delete(Comment).where(
            Comment.subject_type == subject_type, Comment.subject_id == subject_id
        )
    )


async def count_for_subject(db: AsyncSession, subject_type: str, subject_id: uuid.UUID) -> int:
    from sqlalchemy import func  # noqa: PLC0415 - local, single use

    return (
        await db.scalar(
            select(func.count())
            .select_from(Comment)
            .where(
                Comment.subject_type == subject_type,
                Comment.subject_id == subject_id,
                Comment.deleted_at.is_(None),
            )
        )
    ) or 0
