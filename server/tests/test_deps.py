"""Dependency coverage — F-9, plus the CSRF rule from F-10 and the gate from F-5.

Every dependency gets an allow test and a deny test, exercised through the probe routes in
`tests/probeapp.py` so each is tested in isolation rather than through whichever feature
route happens to use it. Those routes were part of the served app in Phase 5 and were
removed in Phase 8; they live in the suite now, mounted onto the real `create_app()` so the
middleware and router-level guards under test are the production ones.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Family, Trip, User
from tests.conftest import add_member, login_as, make_family, make_user
from tests.probeapp import CSRF, MAIN_ADMIN, MEMBER, STAGE


# --- current_user ------------------------------------------------------------------------


async def test_anonymous_is_not_authenticated(probe_client: httpx.AsyncClient, trip: Trip) -> None:
    response = await probe_client.get(MEMBER)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_authenticated"


async def test_expired_or_revoked_session_is_not_authenticated(
    probe_client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    await login_as(probe_client, db, user)
    assert (await probe_client.get(MEMBER)).status_code == 200

    from app.core.sessions import revoke_user_sessions

    await revoke_user_sessions(db, user.id)
    await db.commit()

    response = await probe_client.get(MEMBER)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_authenticated"


# --- require_member ----------------------------------------------------------------------


async def test_require_member_allows_a_family_member(
    probe_client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    await login_as(probe_client, db, user)
    assert (await probe_client.get(MEMBER)).status_code == 200


async def test_require_member_allows_the_platform_admin_with_no_family(
    probe_client: httpx.AsyncClient, db: AsyncSession, main_admin: User, trip: Trip
) -> None:
    # The seeded admin has no family until `families` ships; locking them out of their own
    # instance on first boot would be absurd.
    await login_as(probe_client, db, main_admin)
    assert (await probe_client.get(MEMBER)).status_code == 200


async def test_require_member_denies_a_user_with_no_family(
    probe_client: httpx.AsyncClient, db: AsyncSession, outsider: User, trip: Trip
) -> None:
    await login_as(probe_client, db, outsider)
    response = await probe_client.get(MEMBER)
    assert response.status_code == 403
    # A distinct code from the generic `forbidden`, added by `families`: the client has to
    # tell "you are not on this trip" (show the not-on-the-trip screen) apart from "you are
    # on it but may not do that" (show nothing — the control should not have been there).
    # `plan/features/families/design.md` names it in the edge-case table.
    assert response.json()["detail"]["code"] == "not_on_trip"


# --- require_main_admin ------------------------------------------------------------------


async def test_require_main_admin_allows_the_platform_admin(
    probe_client: httpx.AsyncClient, db: AsyncSession, main_admin: User, trip: Trip
) -> None:
    await login_as(probe_client, db, main_admin)
    assert (await probe_client.get(MAIN_ADMIN)).status_code == 200


async def test_require_main_admin_allows_the_trip_owner(
    probe_client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    owner = await make_user(db, "tripowner")
    trip.owner_user_id = owner.id
    await db.commit()

    await login_as(probe_client, db, owner)
    assert (await probe_client.get(MAIN_ADMIN)).status_code == 200


async def test_require_main_admin_denies_a_family_admin(
    probe_client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family], trip: Trip
) -> None:
    user, _ = family_admin
    await login_as(probe_client, db, user)
    response = await probe_client.get(MAIN_ADMIN)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"


# --- require_family_admin ----------------------------------------------------------------
# A factory taking an id, so it is called directly rather than through a probe route.


async def test_require_family_admin_allows_that_familys_admin(
    db: AsyncSession, family_admin: tuple[User, Family], trip: Trip
) -> None:
    from app.deps import require_family_head_or_spouse

    user, family = family_admin
    assert await require_family_head_or_spouse(family.id)(db, user, trip) is user


async def test_require_family_admin_denies_an_admin_of_another_family(
    db: AsyncSession, family_admin: tuple[User, Family], trip: Trip
) -> None:
    from fastapi import HTTPException

    from app.deps import require_family_head_or_spouse

    user, _ = family_admin
    other = await make_family(db, trip, "Others", color=3)

    with pytest.raises(HTTPException) as raised:
        await require_family_head_or_spouse(other.id)(db, user, trip)
    assert raised.value.status_code == 403
    assert raised.value.detail["code"] == "forbidden"


async def test_require_family_admin_denies_a_plain_member_of_that_family(
    db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    from fastapi import HTTPException

    from app.deps import require_family_head_or_spouse

    user, family = member
    with pytest.raises(HTTPException) as raised:
        await require_family_head_or_spouse(family.id)(db, user, trip)
    assert raised.value.status_code == 403


async def test_require_family_admin_allows_the_main_admin(
    db: AsyncSession, main_admin: User, trip: Trip
) -> None:
    from app.deps import require_family_head_or_spouse

    family = await make_family(db, trip, "Somebodys", color=4)
    assert await require_family_head_or_spouse(family.id)(db, main_admin, trip) is main_admin


# --- require_stage -----------------------------------------------------------------------


async def test_require_stage_allows_an_allowed_stage(
    probe_client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    await login_as(probe_client, db, user)
    assert trip.stage == "planning"
    assert (await probe_client.get(STAGE)).status_code == 200


async def test_require_stage_rejects_the_end_stage_with_409(
    probe_client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    await login_as(probe_client, db, user)

    trip.stage = "end"
    await db.commit()

    response = await probe_client.get(STAGE)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stage_forbidden"


# --- CSRF (F-10) -------------------------------------------------------------------------


async def test_post_without_the_csrf_header_is_rejected(
    probe_client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    await login_as(probe_client, db, user)
    del probe_client.headers["X-CSRF-Token"]

    response = await probe_client.post(CSRF)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "csrf_invalid"


async def test_post_with_a_wrong_csrf_token_is_rejected(
    probe_client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    await login_as(probe_client, db, user)
    probe_client.headers["X-CSRF-Token"] = "not-the-right-token"

    response = await probe_client.post(CSRF)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "csrf_invalid"


async def test_post_with_the_matching_csrf_token_passes(
    probe_client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    await login_as(probe_client, db, user)
    assert (await probe_client.post(CSRF)).status_code == 200


async def test_get_is_exempt_from_csrf(
    probe_client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    await login_as(probe_client, db, user)
    del probe_client.headers["X-CSRF-Token"]
    assert (await probe_client.get(MEMBER)).status_code == 200


async def test_login_is_exempt_from_csrf(probe_client: httpx.AsyncClient, db: AsyncSession) -> None:
    # Login must not require a token: it is what issues one.
    await make_user(db, "loginuser", password="a-long-enough-password")
    response = await probe_client.post(
        "/api/v1/auth/login",
        json={"username": "loginuser", "password": "a-long-enough-password"},
    )
    assert response.status_code == 200


# --- enforce_password_change (F-5) -------------------------------------------------------


async def test_every_non_auth_route_is_blocked_while_password_change_is_pending(
    probe_client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    user = await make_user(db, "seeded", is_platform_admin=True, must_change_password=True)
    family = await make_family(db, trip, "Seededs", color=5)
    await add_member(db, family, user)
    await login_as(probe_client, db, user)

    for path in (MEMBER, MAIN_ADMIN, STAGE, "/api/v1/me/preferences"):
        response = await probe_client.get(path)
        assert response.status_code == 403, path
        assert response.json()["detail"]["code"] == "password_change_required", path


async def test_auth_and_health_stay_reachable_while_password_change_is_pending(
    probe_client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    user = await make_user(db, "seeded2", must_change_password=True)
    await login_as(probe_client, db, user)

    assert (await probe_client.get("/api/v1/health")).status_code == 200
    assert (await probe_client.get("/api/v1/settings")).status_code == 200

    me = await probe_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True

    # And the way out has to work.
    changed = await probe_client.post(
        "/api/v1/auth/password",
        json={
            "current_password": "test-password-1234",
            "new_password": "a-brand-new-password",
        },
    )
    assert changed.status_code == 204
    assert (await probe_client.get("/api/v1/auth/me")).json()["must_change_password"] is False
