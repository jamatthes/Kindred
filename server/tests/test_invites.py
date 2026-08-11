"""Phase 6 — invites and the registration that consumes them.

Both variants, expiry, revocation, single-use under concurrency, an invalid preview leaking
nothing, and registration creating the right role and the right seeded consent.

The concurrency test is the one to keep: a single-use link pasted into a family group chat and
opened by two people at once is not a hypothetical, and a read-then-write would let both
through.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_token
from app.main import app
from app.models import Family, FamilyMember, Invite, Trip, User, UserSettings
from tests.conftest import add_member, login_as, make_family, make_user

INVITES = "/api/v1/invites"


def code(response: httpx.Response) -> str:
    return response.json()["detail"]["code"]


def token_from(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def registration(username: str = "newcomer", **overrides) -> dict:
    body = {
        "username": username,
        "first_name": "New",
        "last_name": "Comer",
        "password": "chosen-just-now",
        "password_confirm": "chosen-just-now",
    }
    body.update(overrides)
    return body


@pytest.fixture
def anon() -> httpx.AsyncClient:
    """A client with no session — a visitor holding a link."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    )


# --- creating -------------------------------------------------------------------------------


async def test_a_family_admin_creates_an_invite_into_their_own_family(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    response = await client.post(INVITES, json={"family_id": str(family.id)})
    assert response.status_code == 201

    body = response.json()
    assert body["family"]["name"] == family.name
    assert "/join/" in body["url"]


async def test_the_raw_token_is_never_stored(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    """Only the sha256, exactly as foundation stores session cookies."""
    user, family = family_admin
    await login_as(client, db, user)
    url = (await client.post(INVITES, json={"family_id": str(family.id)})).json()["url"]
    raw = token_from(url)

    stored = await db.scalar(select(Invite.token_hash))
    assert stored != raw
    assert stored == hash_token(raw)


async def test_the_default_expiry_is_seven_days(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    body = (await client.post(INVITES, json={"family_id": str(family.id)})).json()
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(days=6, hours=23) < expires - datetime.now(UTC) < timedelta(days=7)


async def test_an_expiry_outside_the_short_list_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    """A select, not a free number — nobody mints a ten-year invite by accident."""
    user, family = family_admin
    await login_as(client, db, user)
    response = await client.post(
        INVITES, json={"family_id": str(family.id), "expires_in_hours": 87600}
    )
    assert response.status_code == 422


async def test_a_family_admin_cannot_invite_into_another_family(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    family_admin: tuple[User, Family],
) -> None:
    user, _ = family_admin
    other = await make_family(db, trip, "Theirs", color=7)
    await login_as(client, db, user)
    assert (
        await client.post(INVITES, json={"family_id": str(other.id)})
    ).status_code == 403


async def test_a_family_admin_cannot_mint_a_new_family_invite(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    """FM-6: only the main admin. The same rule as the one above, seen from the other side."""
    user, _ = family_admin
    await login_as(client, db, user)
    response = await client.post(INVITES, json={"family_id": None})
    assert response.status_code == 403


async def test_the_main_admin_creates_a_new_family_invite(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, main_admin: User
) -> None:
    await login_as(client, db, main_admin)
    response = await client.post(INVITES, json={"family_id": None})
    assert response.status_code == 201
    assert response.json()["family"] is None


async def test_a_plain_member_cannot_invite_anyone(
    client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family]
) -> None:
    user, family = member
    await login_as(client, db, user)
    assert (
        await client.post(INVITES, json={"family_id": str(family.id)})
    ).status_code == 403


async def test_invites_cannot_be_created_in_the_end_stage(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    family_admin: tuple[User, Family],
) -> None:
    user, family = family_admin
    trip.stage = "end"
    await db.commit()
    await login_as(client, db, user)
    response = await client.post(INVITES, json={"family_id": str(family.id)})
    assert code(response) == "stage_forbidden"


# --- listing and revoking ---------------------------------------------------------------------


async def test_the_listing_carries_no_token(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    await client.post(INVITES, json={"family_id": str(family.id)})

    listed = (await client.get(INVITES)).json()
    assert len(listed) == 1
    assert "token" not in listed[0] and "token_hash" not in listed[0]
    assert listed[0]["status"] == "active"
    assert listed[0]["created_by_name"] == user.display_name


async def test_a_family_admin_sees_only_their_own_familys_invites(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    main_admin: User,
    family_admin: tuple[User, Family],
) -> None:
    admin_user, family = family_admin
    other = await make_family(db, trip, "Theirs", color=7)

    await login_as(client, db, main_admin)
    await client.post(INVITES, json={"family_id": str(family.id)})
    await client.post(INVITES, json={"family_id": str(other.id)})
    assert len((await client.get(INVITES)).json()) == 2

    await login_as(client, db, admin_user)
    mine = (await client.get(INVITES)).json()
    assert len(mine) == 1
    assert mine[0]["family"]["id"] == str(family.id)


async def test_a_family_admin_asking_for_another_familys_list_is_refused(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    family_admin: tuple[User, Family],
) -> None:
    user, _ = family_admin
    other = await make_family(db, trip, "Theirs", color=7)
    await login_as(client, db, user)
    response = await client.get(INVITES, params={"family_id": str(other.id)})
    assert response.status_code == 403


async def test_revoking_makes_the_link_unusable(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    created = (await client.post(INVITES, json={"family_id": str(family.id)})).json()

    assert (
        await client.post(f"{INVITES}/{created['id']}/revoke")
    ).status_code == 204

    async with anon:
        preview = (await anon.get(f"{INVITES}/token/{token_from(created['url'])}")).json()
        assert preview["valid"] is False
        assert preview["reason"] == "revoked"


async def test_revoking_an_already_used_invite_is_refused(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
) -> None:
    """Revoking an accepted invite would imply it could un-create the account it created."""
    user, family = family_admin
    await login_as(client, db, user)
    created = (await client.post(INVITES, json={"family_id": str(family.id)})).json()

    async with anon:
        await anon.post(
            f"{INVITES}/token/{token_from(created['url'])}/accept", json=registration()
        )

    response = await client.post(f"{INVITES}/{created['id']}/revoke")
    assert response.status_code == 409
    assert code(response) == "invite_already_used"


# --- the public preview -----------------------------------------------------------------------


async def test_a_valid_preview_names_the_family_being_joined(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    created = (await client.post(INVITES, json={"family_id": str(family.id)})).json()

    async with anon:
        preview = (await anon.get(f"{INVITES}/token/{token_from(created['url'])}")).json()
    assert preview["valid"] is True
    assert preview["mode"] == "join"
    assert preview["family_name"] == family.name
    assert preview["trip_name"] == "Test trip"


async def test_a_new_family_preview_says_so_and_names_no_family(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    main_admin: User,
) -> None:
    await login_as(client, db, main_admin)
    created = (await client.post(INVITES, json={"family_id": None})).json()

    async with anon:
        preview = (await anon.get(f"{INVITES}/token/{token_from(created['url'])}")).json()
    assert preview["mode"] == "create_family"
    assert preview["family_name"] is None


async def test_an_unknown_token_is_200_not_404(
    anon: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    """A 404 for unknown and a 200 for expired would let a prober tell them apart."""
    async with anon:
        response = await anon.get(f"{INVITES}/token/completely-made-up")
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["reason"] == "unknown"


async def test_an_invalid_preview_reveals_nothing_but_the_instance_name(
    anon: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    async with anon:
        body = (await anon.get(f"{INVITES}/token/made-up")).json()
    assert body["instance_name"]  # already public on GET /settings
    assert body["trip_name"] is None
    assert body["trip_stage"] is None
    assert body["mode"] is None
    assert body["family_name"] is None


async def test_an_expired_invite_previews_as_expired(
    anon: httpx.AsyncClient, db: AsyncSession, trip: Trip, family_admin: tuple[User, Family]
) -> None:
    user, family = family_admin
    invite = Invite(
        trip_id=trip.id,
        family_id=family.id,
        token_hash=hash_token("stale-token"),
        expires_at=datetime.now(UTC) - timedelta(hours=1),
        created_by=user.id,
    )
    db.add(invite)
    await db.commit()

    async with anon:
        body = (await anon.get(f"{INVITES}/token/stale-token")).json()
    assert body["valid"] is False
    assert body["reason"] == "expired"


async def test_a_finished_trip_previews_as_finished_with_no_form(
    anon: httpx.AsyncClient, db: AsyncSession, trip: Trip, family_admin: tuple[User, Family]
) -> None:
    """A person should learn the trip is over before filling in a registration form."""
    user, family = family_admin
    db.add(
        Invite(
            trip_id=trip.id,
            family_id=family.id,
            token_hash=hash_token("ended-token"),
            expires_at=datetime.now(UTC) + timedelta(days=7),
            created_by=user.id,
        )
    )
    trip.stage = "end"
    await db.commit()

    async with anon:
        body = (await anon.get(f"{INVITES}/token/ended-token")).json()
    assert body["valid"] is False
    assert body["reason"] == "trip_ended"


# --- accepting ---------------------------------------------------------------------------------


async def test_accepting_a_join_invite_creates_a_member_of_that_family(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    created = (await client.post(INVITES, json={"family_id": str(family.id)})).json()

    async with anon:
        response = await anon.post(
            f"{INVITES}/token/{token_from(created['url'])}/accept", json=registration()
        )
        assert response.status_code == 201
        body = response.json()
        assert body["next_step"] == "app"
        assert body["user"]["display_name"] == "New Comer"
        assert body["user"]["initials"] == "NC"
        assert body["user"]["family"]["name"] == family.name
        assert body["user"]["family"]["role"] == "member"
        # Logged in on the spot: the session cookie came back with the response.
        assert (await anon.get("/api/v1/auth/me")).status_code == 200


async def test_accepting_a_new_family_invite_writes_no_membership(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    main_admin: User,
) -> None:
    """FM-7: "no family membership is written, because no family exists yet"."""
    await login_as(client, db, main_admin)
    created = (await client.post(INVITES, json={"family_id": None})).json()

    async with anon:
        body = (
            await anon.post(
                f"{INVITES}/token/{token_from(created['url'])}/accept",
                json=registration("founder"),
            )
        ).json()
        assert body["next_step"] == "setup_family"
        assert body["user"]["family"] is None
        # They are genuinely not on the trip yet, and the server says so.
        refused = await anon.get("/api/v1/families")
        assert refused.status_code == 403
        assert code(refused) == "not_on_trip"

    # Only what the fixtures made: the acceptor added neither a family nor a membership.
    assert await db.scalar(select(func.count()).select_from(FamilyMember)) == 1
    assert await db.scalar(select(func.count()).select_from(Family)) == 1


async def test_a_mononym_registers_with_a_one_letter_badge(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    created = (await client.post(INVITES, json={"family_id": str(family.id)})).json()

    async with anon:
        body = (
            await anon.post(
                f"{INVITES}/token/{token_from(created['url'])}/accept",
                json=registration("mum", first_name="Mum", last_name=""),
            )
        ).json()
    assert body["user"]["display_name"] == "Mum"
    assert body["user"]["initials"] == "M"


async def test_a_taken_username_is_refused_on_that_field(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    created = (await client.post(INVITES, json={"family_id": str(family.id)})).json()

    async with anon:
        response = await anon.post(
            f"{INVITES}/token/{token_from(created['url'])}/accept",
            json=registration("familyadmin"),
        )
    assert response.status_code == 409
    assert code(response) == "username_taken"


async def test_a_failed_registration_leaves_the_invite_usable(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
) -> None:
    """A username clash must not burn the link — the visitor tries again with another name."""
    user, family = family_admin
    await login_as(client, db, user)
    created = (await client.post(INVITES, json={"family_id": str(family.id)})).json()
    token = token_from(created["url"])

    async with anon:
        await anon.post(f"{INVITES}/token/{token}/accept", json=registration("familyadmin"))
        second = await anon.post(f"{INVITES}/token/{token}/accept", json=registration())
    assert second.status_code == 201


async def test_the_seeded_default_is_read_when_it_is_on(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
) -> None:
    """FM-15's one-time seed. Two gates still stand between this and a marker on the map."""
    user, family = family_admin
    family.member_location_default = True
    await db.commit()
    await login_as(client, db, user)
    created = (await client.post(INVITES, json={"family_id": str(family.id)})).json()

    async with anon:
        body = (
            await anon.post(
                f"{INVITES}/token/{token_from(created['url'])}/accept", json=registration()
            )
        ).json()

    settings = await db.scalar(
        select(UserSettings).where(UserSettings.user_id == body["user"]["id"])
    )
    assert settings.live_location_enabled is True


async def test_the_seeded_default_is_off_by_default(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
) -> None:
    user, family = family_admin
    assert family.member_location_default is False
    await login_as(client, db, user)
    created = (await client.post(INVITES, json={"family_id": str(family.id)})).json()

    async with anon:
        body = (
            await anon.post(
                f"{INVITES}/token/{token_from(created['url'])}/accept", json=registration()
            )
        ).json()

    settings = await db.scalar(
        select(UserSettings).where(UserSettings.user_id == body["user"]["id"])
    )
    assert settings.live_location_enabled is False


async def test_a_new_family_acceptor_starts_with_sharing_off(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    main_admin: User,
) -> None:
    """There is no family to take a default from yet; `POST /families/mine` sets it on."""
    await login_as(client, db, main_admin)
    created = (await client.post(INVITES, json={"family_id": None})).json()

    async with anon:
        body = (
            await anon.post(
                f"{INVITES}/token/{token_from(created['url'])}/accept",
                json=registration("founder"),
            )
        ).json()

    settings = await db.scalar(
        select(UserSettings).where(UserSettings.user_id == body["user"]["id"])
    )
    assert settings.live_location_enabled is False


async def test_a_used_invite_cannot_be_used_again(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    created = (await client.post(INVITES, json={"family_id": str(family.id)})).json()
    token = token_from(created["url"])

    async with anon:
        assert (
            await anon.post(f"{INVITES}/token/{token}/accept", json=registration("first"))
        ).status_code == 201

    second = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    )
    async with second:
        response = await second.post(
            f"{INVITES}/token/{token}/accept", json=registration("second")
        )
    assert response.status_code == 409
    assert code(response) == "invite_invalid"


async def test_two_simultaneous_accepts_yield_exactly_one_account(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    """The link pasted into a family group chat and opened by two people at once.

    A read-then-write would let both through; the conditional update on `used_by IS NULL` is
    what does not.
    """
    user, family = family_admin
    await login_as(client, db, user)
    created = (await client.post(INVITES, json={"family_id": str(family.id)})).json()
    token = token_from(created["url"])

    async def _accept(username: str) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://test"
        ) as visitor:
            return await visitor.post(
                f"{INVITES}/token/{token}/accept", json=registration(username)
            )

    first, second = await asyncio.gather(_accept("alpha"), _accept("beta"))
    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [201, 409]

    # Exactly one new account, and exactly one new membership.
    assert await db.scalar(select(func.count()).select_from(FamilyMember)) == 2
    created_names = set(
        (await db.scalars(select(User.username))).all()
    )
    assert len(created_names & {"alpha", "beta"}) == 1


async def test_a_logged_in_visitor_is_told_rather_than_switched(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    """FM-8: say what will happen rather than silently switching accounts."""
    user, family = family_admin
    await login_as(client, db, user)
    created = (await client.post(INVITES, json={"family_id": str(family.id)})).json()

    response = await client.post(
        f"{INVITES}/token/{token_from(created['url'])}/accept", json=registration()
    )
    assert response.status_code == 409
    assert code(response) == "already_member"


async def test_accepting_into_a_deleted_family_is_a_distinct_failure(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    main_admin: User,
) -> None:
    """`invites.family_id` is ON DELETE SET NULL, so the row survives — but it must not be
    mistaken for a new-family invite."""
    doomed = await make_family(db, trip, "Doomed", color=8)
    await login_as(client, db, main_admin)
    created = (await client.post(INVITES, json={"family_id": str(doomed.id)})).json()

    assert (
        await client.delete(f"/api/v1/families/{doomed.id}")
    ).status_code == 204

    async with anon:
        response = await anon.post(
            f"{INVITES}/token/{token_from(created['url'])}/accept", json=registration()
        )
    assert response.status_code == 409
    assert code(response) == "invite_family_missing"


async def test_registering_while_the_trip_has_ended_is_refused(
    client: httpx.AsyncClient,
    anon: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    family_admin: tuple[User, Family],
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    created = (await client.post(INVITES, json={"family_id": str(family.id)})).json()
    trip.stage = "end"
    await db.commit()

    async with anon:
        response = await anon.post(
            f"{INVITES}/token/{token_from(created['url'])}/accept", json=registration()
        )
    assert code(response) == "stage_forbidden"


async def test_registration_is_impossible_without_an_invite(
    anon: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    """FM-7: "Registration is possible only through a valid invite. There is no open
    sign-up form in v1, regardless of the `registration_open` setting"."""
    async with anon:
        response = await anon.post(
            f"{INVITES}/token/not-a-real-token/accept", json=registration()
        )
    assert response.status_code == 409
    assert await db.scalar(select(func.count()).select_from(User)) == 0
