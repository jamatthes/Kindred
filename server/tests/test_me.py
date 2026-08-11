"""Own-preferences endpoints — F-7.

Theme lives on `users.theme_pref` so it follows the user to any device; that is the whole
reason it is not local storage. These are account operations and carry no stage guard, which
is asserted here because a later feature adding one would be a silent regression.
"""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Family, Trip, User
from tests.conftest import login_as

PREFERENCES = "/api/v1/me/preferences"


async def test_defaults_are_system_and_the_configured_locale(
    client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    await login_as(client, db, user)

    response = await client.get(PREFERENCES)
    assert response.status_code == 200
    assert response.json() == {"theme_pref": "system", "locale": "en-GB"}


async def test_patch_persists_the_theme(
    client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    await login_as(client, db, user)

    response = await client.patch(PREFERENCES, json={"theme_pref": "dark"})
    assert response.status_code == 200
    assert response.json()["theme_pref"] == "dark"

    await db.refresh(user)
    assert user.theme_pref == "dark"
    # And it is durable, not just echoed back.
    assert (await client.get(PREFERENCES)).json()["theme_pref"] == "dark"


async def test_patch_leaves_omitted_fields_alone(
    client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    await login_as(client, db, user)

    await client.patch(PREFERENCES, json={"locale": "fr-FR"})
    response = await client.patch(PREFERENCES, json={"theme_pref": "light"})

    # PATCH, not PUT: setting the theme must not reset the locale to its default.
    assert response.json() == {"theme_pref": "light", "locale": "fr-FR"}


async def test_an_unknown_theme_is_rejected(
    client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    user, _ = member
    await login_as(client, db, user)

    response = await client.patch(PREFERENCES, json={"theme_pref": "midnight"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"

    await db.refresh(user)
    assert user.theme_pref == "system"


async def test_preferences_require_authentication(
    client: httpx.AsyncClient, trip: Trip
) -> None:
    assert (await client.get(PREFERENCES)).status_code == 401


async def test_preferences_still_work_in_the_end_stage(
    client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family], trip: Trip
) -> None:
    """The End stage is read-only for *trip data*. An account setting is not trip data.

    `plan/features/foundation/requirements.md` > Stage availability calls this exemption
    deliberate and says it must be preserved — so it gets a test.
    """
    user, _ = member
    await login_as(client, db, user)

    trip.stage = "end"
    await db.commit()

    response = await client.patch(PREFERENCES, json={"theme_pref": "dark"})
    assert response.status_code == 200
    assert response.json()["theme_pref"] == "dark"
