"""The comment routes: the permission matrix, mentions, subject ownership, and undo.

Two of these sections are load-bearing beyond their own feature:

* **subject ownership** — `comments.subject_id` has no foreign key, so nothing in the database
  stops a comment being posted onto another trip's subject. The check is the only thing
  standing there, and the test is the only thing standing behind the check.
* **the edit permission** — there is no role at which one person may edit another's words, and
  the test asserts that for the trip's owner too, because "admin can do anything" is the
  default assumption a future change would make.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, Notification, Poll, Suggestion, Trip, User
from tests.conftest import add_member, login_as, make_family, make_user

COMMENTS = "/api/v1/comments"


def code(response: httpx.Response) -> str:
    return response.json()["detail"]["code"]


def mention(user: User) -> str:
    return f"@[{user.display_name}](user:{user.id})"


@pytest.fixture
async def cast(db: AsyncSession, trip: Trip) -> dict:
    """An owner, a household of three, and a stranger in a fourth family."""
    owner = await make_user(db, "commentowner")
    owners = await make_family(db, trip, "Owners", color=1)
    await add_member(db, owners, owner, role="head")

    head = await make_user(db, "thehead")
    spouse = await make_user(db, "thespouse")
    child = await make_user(db, "thechild")
    family = await make_family(db, trip, "Talkers", color=2)
    await add_member(db, family, head, role="head")
    await add_member(db, family, spouse, role="spouse")
    await add_member(db, family, child, role="member")

    stranger = await make_user(db, "stranger")
    others = await make_family(db, trip, "Others", color=3)
    await add_member(db, others, stranger, role="head")

    trip.owner_user_id = owner.id
    await db.commit()
    return {
        "owner": owner,
        "head": head,
        "spouse": spouse,
        "child": child,
        "stranger": stranger,
    }


@pytest.fixture
async def subject(db: AsyncSession, trip: Trip, cast: dict) -> Suggestion:
    suggestion = Suggestion(
        trip_id=trip.id,
        type="accommodation",
        title="The Barn",
        status="proposed",
        created_by=cast["owner"].id,
        lat=50.4,
        lng=-4.7,
    )
    db.add(suggestion)
    await db.commit()
    await db.refresh(suggestion)
    return suggestion


async def _post(client: httpx.AsyncClient, subject: Suggestion, body: str) -> dict:
    response = await client.post(
        COMMENTS,
        json={"subject_type": "suggestion", "subject_id": str(subject.id), "body": body},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _thread(client: httpx.AsyncClient, subject: Suggestion) -> list[dict]:
    response = await client.get(
        COMMENTS, params={"subject_type": "suggestion", "subject_id": str(subject.id)}
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- posting and reading ---------------------------------------------------------------------


async def test_a_member_posts_and_the_thread_reads_back_oldest_first(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    await login_as(client, db, cast["child"])
    await _post(client, subject, "Looks good")
    await _post(client, subject, "Second thought")

    thread = await _thread(client, subject)

    assert [c["body"] for c in thread] == ["Looks good", "Second thought"]
    assert thread[0]["author_name"] == cast["child"].display_name
    assert thread[0]["family_color"] == 2
    assert thread[0]["edited_at"] is None


async def test_posting_broadcasts_to_the_trip_room(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion, monkeypatch
) -> None:
    sent: list[str] = []

    async def spy(trip_id, type_, payload=None):
        sent.append(type_)
        return 0

    monkeypatch.setattr("app.routers.comments.ws.broadcast", spy)
    await login_as(client, db, cast["child"])
    await _post(client, subject, "Live")

    assert sent == ["comment.created"]


async def test_a_thread_is_readable_in_the_end_stage(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, cast: dict, subject: Suggestion
) -> None:
    """An archive with its discussion removed would be a worse record than the group chat this
    replaced."""
    await login_as(client, db, cast["child"])
    await _post(client, subject, "Before the freeze")
    trip.stage = "end"
    await db.commit()

    assert len(await _thread(client, subject)) == 1

    response = await client.post(
        COMMENTS,
        json={"subject_type": "suggestion", "subject_id": str(subject.id), "body": "After"},
    )
    assert response.status_code == 409
    assert code(response) == "stage_forbidden"


async def test_a_body_past_the_length_cap_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    await login_as(client, db, cast["child"])
    response = await client.post(
        COMMENTS,
        json={
            "subject_type": "suggestion",
            "subject_id": str(subject.id),
            "body": "x" * 4001,
        },
    )
    assert response.status_code == 422


# --- subject ownership -------------------------------------------------------------------------


async def test_commenting_on_a_subject_from_another_trip_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, cast: dict
) -> None:
    """The mandatory check: `subject_id` has no foreign key, so this is the only thing standing
    between a caller and another trip's discussion."""
    other = Trip(name="Somebody else's trip", stage="planning", timezone="Europe/London")
    db.add(other)
    await db.flush()
    theirs = Suggestion(
        trip_id=other.id,
        type="activity",
        title="Not yours",
        status="proposed",
        lat=1.0,
        lng=1.0,
    )
    db.add(theirs)
    await db.commit()

    await login_as(client, db, cast["child"])
    response = await client.post(
        COMMENTS,
        json={"subject_type": "suggestion", "subject_id": str(theirs.id), "body": "Hello"},
    )

    assert response.status_code == 403
    assert code(response) == "forbidden"


async def test_reading_a_thread_from_another_trip_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, cast: dict
) -> None:
    """Reads are checked too — a leak is a leak whichever verb it arrives under."""
    other = Trip(name="Somebody else's trip", stage="planning", timezone="Europe/London")
    db.add(other)
    await db.flush()
    theirs = Suggestion(
        trip_id=other.id, type="activity", title="Not yours", status="proposed", lat=1.0, lng=1.0
    )
    db.add(theirs)
    await db.commit()

    await login_as(client, db, cast["child"])
    response = await client.get(
        COMMENTS, params={"subject_type": "suggestion", "subject_id": str(theirs.id)}
    )

    assert response.status_code == 403


async def test_a_subject_that_does_not_exist_is_a_404_not_a_403(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict
) -> None:
    """Distinct codes on purpose: collapsing them would either tell a stranger which ids are
    real or tell a legitimate caller their own subject is missing."""
    await login_as(client, db, cast["child"])
    response = await client.post(
        COMMENTS,
        json={
            "subject_type": "suggestion",
            "subject_id": "00000000-0000-0000-0000-000000000000",
            "body": "Hello",
        },
    )

    assert response.status_code == 404


async def test_a_poll_thread_uses_the_same_routes(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, cast: dict
) -> None:
    """One implementation serves all three subjects, which is what `architecture.md` promised
    when `polls` shipped the first thread."""
    poll = Poll(trip_id=trip.id, title="Where?", kind="score_matrix")
    db.add(poll)
    await db.commit()
    await db.refresh(poll)

    await login_as(client, db, cast["child"])
    response = await client.post(
        COMMENTS,
        json={"subject_type": "poll", "subject_id": str(poll.id), "body": "Cornwall"},
    )

    assert response.status_code == 201
    thread = (
        await client.get(
            COMMENTS, params={"subject_type": "poll", "subject_id": str(poll.id)}
        )
    ).json()
    assert [c["body"] for c in thread] == ["Cornwall"]


# --- editing -----------------------------------------------------------------------------------


async def test_the_author_edits_and_the_edit_leaves_a_trace(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, "Frist")

    response = await client.patch(f"{COMMENTS}/{comment['id']}", json={"body": "First"})

    assert response.status_code == 200
    assert response.json()["body"] == "First"
    assert response.json()["edited_at"] is not None


@pytest.mark.parametrize("actor", ["owner", "head", "spouse", "stranger"])
async def test_nobody_edits_another_persons_words_at_any_role(
    client: httpx.AsyncClient,
    db: AsyncSession,
    cast: dict,
    subject: Suggestion,
    actor: str,
) -> None:
    """Including the trip's owner. The permission does not exist rather than being withheld —
    an organiser who objects deletes the comment, under their own name, which is a different
    act with a different record."""
    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, "Mine")

    await login_as(client, db, cast[actor])
    response = await client.patch(f"{COMMENTS}/{comment['id']}", json={"body": "Hijacked"})

    assert response.status_code == 403


async def test_can_edit_is_true_only_for_the_author(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    await login_as(client, db, cast["child"])
    mine = await _post(client, subject, "Mine")
    assert mine["can_edit"] is True

    await login_as(client, db, cast["owner"])
    assert (await _thread(client, subject))[0]["can_edit"] is False


# --- deleting ------------------------------------------------------------------------------------


async def test_the_author_deletes_their_own(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, "Oops")

    assert (await client.delete(f"{COMMENTS}/{comment['id']}")).status_code == 204
    assert await _thread(client, subject) == []


async def test_the_delete_is_soft_so_the_row_survives_for_undo(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    """A hard delete could not be undone, so the window would have to live in the client — and
    a closed tab would lose the text irrecoverably."""
    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, "Oops")
    await client.delete(f"{COMMENTS}/{comment['id']}")

    row = await db.scalar(select(Comment).where(Comment.id == uuid.UUID(comment["id"])))
    assert row is not None
    assert row.deleted_at is not None
    assert row.deleted_by == cast["child"].id


@pytest.mark.parametrize("actor", ["head", "spouse"])
async def test_a_head_or_spouse_moderates_their_own_family(
    client: httpx.AsyncClient,
    db: AsyncSession,
    cast: dict,
    subject: Suggestion,
    actor: str,
) -> None:
    """A lightweight moderation path that does not require pulling in an organiser."""
    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, "Something regrettable")

    await login_as(client, db, cast[actor])
    assert (await client.delete(f"{COMMENTS}/{comment['id']}")).status_code == 204


async def test_a_head_of_another_family_cannot_moderate(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    """`stranger` is a head — of the wrong family. A family-level role governs a family, never
    the trip."""
    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, "Mine")

    await login_as(client, db, cast["stranger"])
    response = await client.delete(f"{COMMENTS}/{comment['id']}")

    assert response.status_code == 403


async def test_an_organiser_deletes_anybodys(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    await login_as(client, db, cast["stranger"])
    comment = await _post(client, subject, "Theirs")

    await login_as(client, db, cast["owner"])
    assert (await client.delete(f"{COMMENTS}/{comment['id']}")).status_code == 204


async def test_a_plain_member_cannot_delete_a_family_members_comment(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    """Moderation is the head's and the spouse's, not everybody in the household's."""
    await login_as(client, db, cast["head"])
    comment = await _post(client, subject, "The head's own")

    await login_as(client, db, cast["child"])
    assert (await client.delete(f"{COMMENTS}/{comment['id']}")).status_code == 403


async def test_can_delete_matches_what_the_server_will_accept(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    await login_as(client, db, cast["child"])
    await _post(client, subject, "Mine")

    await login_as(client, db, cast["head"])
    assert (await _thread(client, subject))[0]["can_delete"] is True
    await login_as(client, db, cast["stranger"])
    assert (await _thread(client, subject))[0]["can_delete"] is False
    await login_as(client, db, cast["owner"])
    assert (await _thread(client, subject))[0]["can_delete"] is True


# --- undo ------------------------------------------------------------------------------------------


async def test_undo_restores_the_comment_in_place(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    await login_as(client, db, cast["child"])
    first = await _post(client, subject, "First")
    second = await _post(client, subject, "Second")
    third = await _post(client, subject, "Third")
    await client.delete(f"{COMMENTS}/{second['id']}")

    response = await client.post(f"{COMMENTS}/{second['id']}/undo-delete")

    assert response.status_code == 200
    thread = await _thread(client, subject)
    # Ordered by `created_at`, so it lands back where it was rather than at the end.
    assert [c["id"] for c in thread] == [first["id"], second["id"], third["id"]]


async def test_undo_broadcasts_a_create_so_clients_reconcile_by_id(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion, monkeypatch
) -> None:
    """A restore is indistinguishable from a create for a consumer reconciling by `id`, and a
    sixth event would give every client a branch to get wrong."""
    sent: list[str] = []

    async def spy(trip_id, type_, payload=None):
        sent.append(type_)
        return 0

    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, "Oops")
    await client.delete(f"{COMMENTS}/{comment['id']}")
    monkeypatch.setattr("app.routers.comments.ws.broadcast", spy)

    await client.post(f"{COMMENTS}/{comment['id']}/undo-delete")

    assert sent == ["comment.created"]


async def test_only_the_person_who_deleted_it_may_undo(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    """An author whose comment an organiser removed must not be able to put it back."""
    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, "Mine")
    await login_as(client, db, cast["owner"])
    await client.delete(f"{COMMENTS}/{comment['id']}")

    await login_as(client, db, cast["child"])
    response = await client.post(f"{COMMENTS}/{comment['id']}/undo-delete")

    assert response.status_code == 404


async def test_undo_after_the_retention_window_is_too_late(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, "Oops")
    await client.delete(f"{COMMENTS}/{comment['id']}")

    row = await db.scalar(select(Comment).where(Comment.id == uuid.UUID(comment["id"])))
    row.deleted_at = datetime.now(UTC) - timedelta(days=31)
    await db.commit()

    response = await client.post(f"{COMMENTS}/{comment['id']}/undo-delete")

    assert response.status_code == 404


async def test_undo_pressed_twice_is_a_no_op_404(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, "Oops")
    await client.delete(f"{COMMENTS}/{comment['id']}")

    assert (await client.post(f"{COMMENTS}/{comment['id']}/undo-delete")).status_code == 200
    assert (await client.post(f"{COMMENTS}/{comment['id']}/undo-delete")).status_code == 404


async def test_the_retention_sweep_hard_deletes_what_is_past_the_window(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    """So this never becomes an accidental permanent archive of deleted text."""
    from sqlalchemy import func

    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, "Long gone")
    await client.delete(f"{COMMENTS}/{comment['id']}")

    row = await db.scalar(select(Comment).where(Comment.id == uuid.UUID(comment["id"])))
    row.deleted_at = datetime.now(UTC) - timedelta(days=31)
    await db.commit()

    await _thread(client, subject)  # the sweep runs from the thread read

    assert await db.scalar(select(func.count()).select_from(Comment)) == 0


# --- mentions -----------------------------------------------------------------------------------------


async def test_a_mention_notifies_the_person_mentioned(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, f"What do you think {mention(cast['head'])}?")

    rows = (await db.scalars(select(Notification))).unique().all()

    assert len(rows) == 1
    assert rows[0].recipient_user_id == cast["head"].id
    assert rows[0].type == "mention"
    assert rows[0].payload_json["comment_id"] == comment["id"]
    assert rows[0].payload_json["subject_type"] == "suggestion"
    assert comment["mentions"] == [str(cast["head"].id)]


async def test_mentioning_myself_notifies_nobody(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    """You know what you just wrote."""
    from sqlalchemy import func

    await login_as(client, db, cast["child"])
    await _post(client, subject, f"As {mention(cast['child'])} said earlier")

    assert await db.scalar(select(func.count()).select_from(Notification)) == 0


async def test_mentioning_somebody_not_on_the_trip_notifies_nobody(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    """Rendered as plain text — and absent from `mentions`, so the UI does not draw a link to
    somebody the reader cannot see."""
    from sqlalchemy import func

    offtrip = await make_user(db, "notinvited")
    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, f"Hello {mention(offtrip)}")

    assert await db.scalar(select(func.count()).select_from(Notification)) == 0
    assert comment["mentions"] == []


async def test_a_mention_of_a_uuid_that_is_nobody_notifies_nobody(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    from sqlalchemy import func

    await login_as(client, db, cast["child"])
    await _post(client, subject, f"Hello @[Ghost](user:{uuid.uuid4()})")

    assert await db.scalar(select(func.count()).select_from(Notification)) == 0


async def test_an_edit_notifies_only_the_newly_mentioned(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    """Re-pinging everyone on a typo fix would train the group to ignore the bell."""
    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, f"Hi {mention(cast['head'])}")

    await client.patch(
        f"{COMMENTS}/{comment['id']}",
        json={"body": f"Hi {mention(cast['head'])} and {mention(cast['spouse'])}"},
    )

    rows = (await db.scalars(select(Notification))).unique().all()
    assert [r.recipient_user_id for r in rows] == [cast["head"].id, cast["spouse"].id]


async def test_editing_without_changing_the_mentions_notifies_nobody_again(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    from sqlalchemy import func

    await login_as(client, db, cast["child"])
    comment = await _post(client, subject, f"Hi {mention(cast['head'])}, teh barn?")
    await client.patch(
        f"{COMMENTS}/{comment['id']}",
        json={"body": f"Hi {mention(cast['head'])}, the barn?"},
    )

    assert await db.scalar(select(func.count()).select_from(Notification)) == 1


async def test_a_mention_is_sent_to_that_person_alone_not_the_room(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion, monkeypatch
) -> None:
    """Broadcasting it would tell everybody who was pinged about what."""
    direct: list[tuple] = []

    async def spy(user_id, type_, payload=None):
        direct.append((user_id, type_))
        return 0

    monkeypatch.setattr("app.routers.comments.ws.send_user", spy)
    await login_as(client, db, cast["child"])
    await _post(client, subject, f"Hi {mention(cast['head'])}")

    assert direct == [(cast["head"].id, "notification.new")]


# --- the comment count ---------------------------------------------------------------------------------


async def test_a_soft_deleted_comment_stops_counting_towards_the_badge(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    await login_as(client, db, cast["child"])
    first = await _post(client, subject, "One")
    await _post(client, subject, "Two")

    before = (await client.get(f"/api/v1/suggestions/{subject.id}")).json()["comment_count"]
    await client.delete(f"{COMMENTS}/{first['id']}")
    after = (await client.get(f"/api/v1/suggestions/{subject.id}")).json()["comment_count"]

    assert (before, after) == (2, 1)


async def test_deleting_the_subject_takes_its_thread_for_good(
    client: httpx.AsyncClient, db: AsyncSession, cast: dict, subject: Suggestion
) -> None:
    """A hard delete, not the soft one: the thing being discussed is gone, so there is nothing
    for an undo to restore the discussion to."""
    from sqlalchemy import func

    await login_as(client, db, cast["owner"])
    await _post(client, subject, "About the barn")

    assert (await client.delete(f"/api/v1/suggestions/{subject.id}")).status_code == 204
    assert await db.scalar(select(func.count()).select_from(Comment)) == 0
