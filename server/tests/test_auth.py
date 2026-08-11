"""Authentication behaviour — F-3, F-4, F-5, F-6, F-10.

Login is tested through the real route here (unlike `test_deps.py`, which attaches sessions
directly so a broken login cannot masquerade as a broken dependency).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Session, Trip, User
from app.routers.auth import CSRF_COOKIE_NAME
from tests.conftest import make_user

PASSWORD = "test-password-1234"

LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
PASSWORD_URL = "/api/v1/auth/password"


async def login(
    client: httpx.AsyncClient, username: str, password: str = PASSWORD
) -> httpx.Response:
    """Log in through the route and arm the client's CSRF header on success."""
    response = await client.post(LOGIN, json={"username": username, "password": password})
    if response.status_code == 200:
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


# --- F-3: logging in ---------------------------------------------------------------------


async def test_login_succeeds_and_sets_both_cookies(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    user = await make_user(db, "alice")

    response = await login(client, "alice")

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == "alice"
    assert body["user"]["trip"]["id"] == str(trip.id)
    assert body["csrf_token"]

    assert settings.session_cookie_name in client.cookies
    assert CSRF_COOKIE_NAME in client.cookies

    raw = " ".join(response.headers.get_list("set-cookie"))
    # The session cookie must not be readable by script; the CSRF cookie must be.
    assert "HttpOnly" in raw and "Secure" in raw and "SameSite=lax" in raw.replace("Lax", "lax")

    assert (await client.get(ME)).json()["username"] == "alice"


async def test_username_is_case_insensitive(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    await make_user(db, "alice")
    assert (await login(client, "ALICE")).status_code == 200


async def test_wrong_password_and_unknown_user_are_indistinguishable(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    await make_user(db, "alice")

    wrong = await client.post(LOGIN, json={"username": "alice", "password": "not-it-at-all"})
    unknown = await client.post(LOGIN, json={"username": "nobody", "password": "not-it-at-all"})

    assert wrong.status_code == unknown.status_code == 401
    # F-3: the response never reveals whether the username exists — same code, same prose.
    assert wrong.json() == unknown.json()
    assert wrong.json()["detail"]["code"] == "invalid_credentials"
    assert wrong.json()["detail"]["message"] == "Incorrect username or password"


async def test_password_is_not_echoed_anywhere(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    await make_user(db, "alice")
    response = await login(client, "alice")
    assert PASSWORD not in response.text
    assert "password_hash" not in response.text


# --- F-3: rate limiting ------------------------------------------------------------------


async def test_rate_limit_trips_after_the_configured_number_of_failures(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    await make_user(db, "alice")
    limit = settings.rate_limit_login_per_minute

    for attempt in range(limit):
        response = await client.post(LOGIN, json={"username": "alice", "password": "wrong"})
        assert response.status_code == 401, f"attempt {attempt + 1}"

    blocked = await client.post(LOGIN, json={"username": "alice", "password": "wrong"})
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "rate_limited"
    assert blocked.headers["Retry-After"] == "60"


async def test_rate_limit_blocks_even_the_correct_password(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    # Otherwise the limit would be trivially bypassable by an attacker who guesses correctly
    # on their sixth try.
    await make_user(db, "alice")
    for _ in range(settings.rate_limit_login_per_minute):
        await client.post(LOGIN, json={"username": "alice", "password": "wrong"})

    assert (await client.post(LOGIN, json={"username": "alice", "password": PASSWORD})).status_code == 429


async def test_a_successful_login_clears_that_usernames_failures(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    await make_user(db, "alice")
    for _ in range(settings.rate_limit_login_per_minute - 1):
        await client.post(LOGIN, json={"username": "alice", "password": "wrong"})

    assert (await login(client, "alice")).status_code == 200

    # The counter is back to zero, so a fresh run of failures is needed to trip it again.
    for _ in range(settings.rate_limit_login_per_minute - 1):
        response = await client.post(LOGIN, json={"username": "alice", "password": "wrong"})
        assert response.status_code == 401


async def test_the_limit_also_applies_per_client_ip(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    """F-3: "The same limit applies per client IP."

    Spreading the failures across distinct usernames keeps every per-username counter at 1,
    so only the IP dimension can trip — including for a user who has never failed once.
    """
    limit = settings.rate_limit_login_per_minute
    for index in range(limit):
        await make_user(db, f"victim{index}")
        response = await client.post(
            LOGIN, json={"username": f"victim{index}", "password": "wrong"}
        )
        assert response.status_code == 401

    await make_user(db, "innocent")
    blocked = await client.post(LOGIN, json={"username": "innocent", "password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "rate_limited"


async def test_the_limit_applies_per_username_not_globally(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    # The IP limit is checked too, so this test asserts the username dimension exists by
    # keeping total failures under the shared IP limit.
    await make_user(db, "alice")
    await make_user(db, "bob")

    for _ in range(2):
        await client.post(LOGIN, json={"username": "alice", "password": "wrong"})
    for _ in range(2):
        await client.post(LOGIN, json={"username": "bob", "password": "wrong"})

    assert (await login(client, "bob")).status_code == 200


# --- F-4: sessions -----------------------------------------------------------------------


async def test_me_returns_401_without_a_session(client: httpx.AsyncClient, trip: Trip) -> None:
    response = await client.get(ME)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_authenticated"


async def test_logout_revokes_the_session_and_clears_the_cookies(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    user = await make_user(db, "alice")
    await login(client, "alice")

    logout = await client.post(LOGOUT)
    assert logout.status_code == 204

    stored = (await db.execute(select(Session).where(Session.user_id == user.id))).scalars().all()
    assert len(stored) == 1
    await db.refresh(stored[0])
    assert stored[0].revoked_at is not None

    assert (await client.get(ME)).status_code == 401


async def test_a_revoked_cookie_is_rejected_even_if_replayed(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    await make_user(db, "alice")
    await login(client, "alice")
    cookie = client.cookies[settings.session_cookie_name]

    await client.post(LOGOUT)

    # Logout clears the client's cookies; put the old value back by hand. Revocation is
    # server-side, so replaying it must still fail.
    client.cookies.set(settings.session_cookie_name, cookie)
    assert (await client.get(ME)).status_code == 401


async def test_an_expired_session_behaves_exactly_like_no_session(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    user = await make_user(db, "alice")
    await login(client, "alice")
    assert (await client.get(ME)).status_code == 200

    await db.execute(
        update(Session)
        .where(Session.user_id == user.id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db.commit()

    response = await client.get(ME)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_authenticated"


async def test_logging_in_again_revokes_the_previous_session(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    """Session fixation: a cookie planted before login must not survive it."""
    user = await make_user(db, "alice")
    await login(client, "alice")
    first_cookie = client.cookies[settings.session_cookie_name]

    await login(client, "alice")
    second_cookie = client.cookies[settings.session_cookie_name]

    assert first_cookie != second_cookie

    live = await db.scalar(
        select(func.count())
        .select_from(Session)
        .where(Session.user_id == user.id, Session.revoked_at.is_(None))
    )
    assert live == 1

    client.cookies.set(settings.session_cookie_name, first_cookie)
    assert (await client.get(ME)).status_code == 401


async def test_login_issues_a_fresh_csrf_token_and_logout_invalidates_it(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    """F-10: "Login itself issues a fresh token; logout invalidates it."."""
    await make_user(db, "alice")

    first = await login(client, "alice")
    first_token = first.json()["csrf_token"]

    second = await login(client, "alice")
    assert second.json()["csrf_token"] != first_token, "token must not be reused across logins"

    cookie = client.cookies[settings.session_cookie_name]
    await client.post(LOGOUT)

    # The CSRF token lives on the session, so revoking the session retires the token with it.
    # Replay both together against a guarded mutation: the pair used to work seconds ago.
    client.cookies.set(settings.session_cookie_name, cookie)
    client.headers["X-CSRF-Token"] = second.json()["csrf_token"]

    replayed = await client.patch("/api/v1/me/preferences", json={"theme_pref": "dark"})
    assert replayed.status_code == 401
    assert replayed.json()["detail"]["code"] == "not_authenticated"


# --- F-5 / F-6: changing a password ------------------------------------------------------


async def test_password_change_clears_the_flag_and_keeps_the_current_session(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    user = await make_user(db, "alice", must_change_password=True)
    await login(client, "alice")

    response = await client.post(
        PASSWORD_URL,
        json={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
    )
    assert response.status_code == 204

    me = await client.get(ME)
    assert me.status_code == 200, "the caller's own session must survive the change"
    assert me.json()["must_change_password"] is False

    await db.refresh(user)
    assert user.must_change_password is False


async def test_password_change_revokes_every_other_session(
    db: AsyncSession, trip: Trip
) -> None:
    from app.main import app

    user = await make_user(db, "alice")

    # Two devices. `login` on the second would revoke the first (fixation defence), so the
    # other session is attached directly — this is about the password change, not login.
    from app.core.sessions import create_session

    other_session, other_token = await create_session(db, user_id=user.id)
    await db.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
        await login(client, "alice")
        response = await client.post(
            PASSWORD_URL,
            json={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
        )
        assert response.status_code == 204

        # The caller keeps working...
        assert (await client.get(ME)).status_code == 200

        # ...and the other device is logged out.
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as other:
            other.cookies.set(settings.session_cookie_name, other_token)
            assert (await other.get(ME)).status_code == 401

    await db.refresh(other_session)
    assert other_session.revoked_at is not None


async def test_the_new_password_works_and_the_old_one_does_not(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    await make_user(db, "alice")
    await login(client, "alice")
    await client.post(
        PASSWORD_URL,
        json={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
    )
    await client.post(LOGOUT)

    assert (await login(client, "alice", PASSWORD)).status_code == 401
    assert (await login(client, "alice", "a-brand-new-password")).status_code == 200


async def test_wrong_current_password_changes_nothing(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    user = await make_user(db, "alice")
    original = user.password_hash
    await login(client, "alice")

    response = await client.post(
        PASSWORD_URL,
        json={"current_password": "not-my-password", "new_password": "a-brand-new-password"},
    )
    assert response.status_code == 400

    await db.refresh(user)
    assert user.password_hash == original


async def test_new_password_must_differ_from_the_current_one(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip
) -> None:
    await make_user(db, "alice")
    await login(client, "alice")

    response = await client.post(
        PASSWORD_URL, json={"current_password": PASSWORD, "new_password": PASSWORD}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "password_unchanged"


@pytest.mark.parametrize("candidate", ["short", "123456789"])
async def test_new_password_must_be_at_least_ten_characters(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, candidate: str
) -> None:
    await make_user(db, "alice")
    await login(client, "alice")

    response = await client.post(
        PASSWORD_URL, json={"current_password": PASSWORD, "new_password": candidate}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "validation_error"
    # The field is named, so the web client can put the message beneath the right input.
    assert any(err["field"] == "new_password" for err in body["detail"]["errors"])


async def test_changing_a_password_requires_authentication(
    client: httpx.AsyncClient, trip: Trip
) -> None:
    response = await client.post(
        PASSWORD_URL,
        json={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
    )
    assert response.status_code == 401


# --- F-12 / public surface ---------------------------------------------------------------


async def test_settings_and_health_are_readable_logged_out(
    client: httpx.AsyncClient, trip: Trip
) -> None:
    settings_response = await client.get("/api/v1/settings")
    assert settings_response.status_code == 200
    assert set(settings_response.json()) == {
        "instance_name",
        "registration_open",
        "invite_only",
    }

    health = await client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["db"] == "ok"
