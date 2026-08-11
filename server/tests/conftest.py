"""Shared test fixtures.

The suite runs against the dockerized Postgres (`deploy/docker-compose.yml`) but in its own
database, so running tests never touches development data. The database name is the
configured one with a `_test` suffix, or `TEST_DATABASE_URL` if set.

``DATABASE_URL`` is put into the environment **before any app module is imported**, because
`app.core.config` builds its settings singleton at import time and `app.core.db` binds the
engine to it. Environment variables outrank `deploy/.env` in pydantic-settings, so this wins.

No test makes an external network call: the ASGI transport talks to the app object in-process
and there is no Google/NOAA client in M0 at all.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

# --- must happen before `import app.*` ---------------------------------------------------


#: Matches `app.core.config.ENV_FILE`. Read by hand below — see `_base_database_url`.
_ENV_FILE = Path(__file__).resolve().parents[2] / "deploy" / ".env"

_DEFAULT_DATABASE_URL = "postgresql+asyncpg://kindred:change-me@localhost:5432/kindred"


def _base_database_url() -> str:
    """The development database URL, resolved **without importing any app module**.

    Importing `app.core.config` would build its settings singleton right here, from the
    un-overridden environment, and `app.core.db` would then bind the engine to the
    development database — which is how the suite would quietly run against real data.
    """
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].split(" #")[0].strip()
    return _DEFAULT_DATABASE_URL


def _build_test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    parts = urlsplit(_base_database_url())
    return urlunsplit(parts._replace(path=f"{parts.path.rstrip('/')}_test"))


os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-for-anything-real")
TEST_DATABASE_URL = _build_test_database_url()

# A hard stop, because the suite TRUNCATEs every table on every test. If this ever resolves
# to the development database, the failure must be a loud one at collection time.
if not urlsplit(TEST_DATABASE_URL).path.rstrip("/").endswith("_test"):
    raise RuntimeError(
        f"Refusing to run tests against {TEST_DATABASE_URL!r}: the database name must end "
        "in '_test'. Set TEST_DATABASE_URL if you need a different target."
    )

os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.db import SessionFactory, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.sessions import create_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Family, FamilyMember, Trip, User, UserSettings  # noqa: E402
from app.routers.auth import CSRF_COOKIE_NAME  # noqa: E402

#: Every table the suite truncates between tests.
_ALL_TABLES = ", ".join(f'"{name}"' for name in Base.metadata.tables)


async def _create_test_database() -> None:
    """Create the test database if it does not exist (connecting to `postgres`)."""
    import asyncpg

    parts = urlsplit(TEST_DATABASE_URL)
    dbname = parts.path.lstrip("/")
    dsn = urlunsplit(
        parts._replace(scheme="postgresql", path="/postgres", query="", fragment="")
    )
    conn = await asyncpg.connect(dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", dbname)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        await conn.close()


async def _create_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    """Session-scoped, synchronous on purpose.

    Schema setup runs in its own throwaway event loop, and disposes the engine pool *inside*
    that loop — a pooled asyncpg connection is bound to the loop that opened it, and closing
    one from a different loop raises "Event loop is closed".
    """

    async def _setup() -> None:
        await _create_test_database()
        await _create_schema()
        await engine.dispose()

    asyncio.run(_setup())
    yield


@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    """Every test starts from an empty database, and ends with an empty connection pool.

    pytest-asyncio gives each test a fresh event loop, so any connection left in the pool
    would belong to a loop that no longer exists. Disposing per test is cheap here and
    removes a whole category of confusing teardown errors.
    """
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))
    yield
    await engine.dispose()


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """An ASGI client. `https` so the `Secure` cookies are actually stored."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as c:
        yield c


# --- factories ---------------------------------------------------------------------------


@pytest.fixture
async def trip(db: AsyncSession) -> Trip:
    trip = Trip(name="Test trip", stage="planning", timezone="Europe/London")
    db.add(trip)
    await db.commit()
    await db.refresh(trip)
    return trip


async def make_user(
    db: AsyncSession,
    username: str,
    *,
    password: str = "test-password-1234",
    is_platform_admin: bool = False,
    must_change_password: bool = False,
) -> User:
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=username.title(),
        is_platform_admin=is_platform_admin,
        must_change_password=must_change_password,
    )
    db.add(user)
    await db.flush()
    db.add(UserSettings(user_id=user.id))
    await db.commit()
    await db.refresh(user)
    return user


async def make_family(db: AsyncSession, trip: Trip, name: str, color: int = 1) -> Family:
    family = Family(trip_id=trip.id, name=name, color=color)
    db.add(family)
    await db.commit()
    await db.refresh(family)
    return family


async def add_member(
    db: AsyncSession, family: Family, user: User, role: str = "member"
) -> FamilyMember:
    member = FamilyMember(family_id=family.id, user_id=user.id, role=role)
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def login_as(client: httpx.AsyncClient, db: AsyncSession, user: User) -> str:
    """Attach a live session to ``client`` without going through the login route.

    Tests of the *dependencies* should not be able to fail because the login route broke;
    `test_auth.py` is where login itself is tested.

    Returns the CSRF token, and also sets it on the client so unsafe methods pass by default.
    """
    session, token = await create_session(db, user_id=user.id)
    csrf = session.csrf_token
    await db.commit()

    from app.core.config import settings  # noqa: PLC0415

    # No `domain=`: httpx's cookie jar will not return a domain-scoped cookie for the bare
    # host "test", so an explicit domain here silently sends nothing.
    client.cookies.set(settings.session_cookie_name, token)
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    client.headers["X-CSRF-Token"] = csrf
    return csrf


@pytest.fixture
async def main_admin(db: AsyncSession) -> User:
    return await make_user(db, "mainadmin", is_platform_admin=True)


@pytest.fixture
async def family_admin(db: AsyncSession, trip: Trip) -> tuple[User, Family]:
    user = await make_user(db, "familyadmin")
    family = await make_family(db, trip, "Adminsons", color=1)
    await add_member(db, family, user, role="admin")
    return user, family


@pytest.fixture
async def member(db: AsyncSession, trip: Trip) -> tuple[User, Family]:
    user = await make_user(db, "plainmember")
    family = await make_family(db, trip, "Membersons", color=2)
    await add_member(db, family, user, role="member")
    return user, family


@pytest.fixture
async def outsider(db: AsyncSession) -> User:
    """Authenticated, but in no family on the trip."""
    return await make_user(db, "outsider")
