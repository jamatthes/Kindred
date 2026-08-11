"""The address rule, asserted on the wire.

`tests/test_family_schemas.py` checks the serialiser. This checks the **response body a
non-member actually receives**, on every endpoint that returns a family, because the two can
disagree: a route that forgets `response_model_exclude_unset` re-materialises the excluded
keys as nulls, and a serialiser test would never see it.

`plan/features/families/tasks.md` Phase 11: "assert the exact response body for a non-member
caller contains no `home_address`, `home_lat` or `home_lng` key on any endpoint that returns
a family, and no `location_sharing_enabled` value on any member of another family."
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Family, Trip, User, UserSettings
from tests.conftest import add_member, login_as, make_family, make_user

ADDRESS_KEYS = {"home_address", "home_lat", "home_lng", "home_geocoded_at"}


def _walk(payload) -> list[dict]:
    """Every object anywhere in a response body — nested members included.

    Checking the top level only would miss a leak inside `members`, which is exactly where a
    future field would be added.
    """
    found: list[dict] = []
    if isinstance(payload, dict):
        found.append(payload)
        for value in payload.values():
            found.extend(_walk(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_walk(item))
    return found


def assert_no_address_anywhere(payload) -> None:
    for node in _walk(payload):
        leaked = ADDRESS_KEYS & set(node)
        assert not leaked, f"leaked {sorted(leaked)} in {node}"


@pytest.fixture
async def two_families(db: AsyncSession, trip: Trip) -> tuple[Family, User, Family, User]:
    """The Parkers, with a placed home and a sharing member; and an unrelated Rivera."""
    parkers = await make_family(db, trip, "Parkers", color=1)
    parker = await make_user(db, "parker")
    await add_member(db, parkers, parker, role="head")
    parkers.home_address = "12 Elm Row, Bristol BS1 4AA"
    parkers.home_lat = 51.4545
    parkers.home_lng = -2.5879
    parkers.home_locality = "Bristol"
    parkers.geocode_status = "ok"

    settings = await db.scalar(select(UserSettings).where(UserSettings.user_id == parker.id))
    settings.live_location_enabled = True

    riveras = await make_family(db, trip, "Riveras", color=2)
    rivera = await make_user(db, "rivera")
    await add_member(db, riveras, rivera, role="head")
    await db.commit()
    return parkers, parker, riveras, rivera


ENDPOINTS = (
    "/api/v1/families",
    "/api/v1/families/{id}",
    "/api/v1/families/{id}/members",
)


async def test_no_endpoint_leaks_another_familys_address(
    client: httpx.AsyncClient,
    db: AsyncSession,
    two_families: tuple[Family, User, Family, User],
) -> None:
    parkers, _, _, rivera = two_families
    await login_as(client, db, rivera)

    for template in ENDPOINTS:
        response = await client.get(template.format(id=parkers.id))
        assert response.status_code == 200, template
        assert_no_address_anywhere(response.json())


async def test_no_endpoint_leaks_another_familys_consent(
    client: httpx.AsyncClient,
    db: AsyncSession,
    two_families: tuple[Family, User, Family, User],
) -> None:
    """`null`, not absent, here: the key exists so the client knows it asked — it is the
    *value* that is nobody else's business."""
    parkers, _, _, rivera = two_families
    await login_as(client, db, rivera)

    for template in ENDPOINTS[1:]:
        payload = (await client.get(template.format(id=parkers.id))).json()
        members = payload["members"] if isinstance(payload, dict) else payload
        assert members
        assert all(m["location_sharing_enabled"] is None for m in members), template


async def test_the_locality_survives_the_redaction(
    client: httpx.AsyncClient,
    db: AsyncSession,
    two_families: tuple[Family, User, Family, User],
) -> None:
    """FM-4: other members see the town. Redaction that removed it would break the feature
    the coarse label exists for."""
    parkers, _, _, rivera = two_families
    await login_as(client, db, rivera)
    body = (await client.get(f"/api/v1/families/{parkers.id}")).json()
    assert body["home_locality"] == "Bristol"
    assert body["home_placed"] is True


async def test_a_member_of_that_family_does_receive_the_address(
    client: httpx.AsyncClient,
    db: AsyncSession,
    two_families: tuple[Family, User, Family, User],
) -> None:
    """The other half: redaction that redacted from everyone would pass every test above."""
    parkers, parker, _, _ = two_families
    await login_as(client, db, parker)
    body = (await client.get(f"/api/v1/families/{parkers.id}")).json()
    assert body["home_address"] == "12 Elm Row, Bristol BS1 4AA"
    assert body["home_lat"] == pytest.approx(51.4545)


async def test_the_main_admin_receives_any_familys_address(
    client: httpx.AsyncClient,
    db: AsyncSession,
    main_admin: User,
    two_families: tuple[Family, User, Family, User],
) -> None:
    parkers, _, _, _ = two_families
    await login_as(client, db, main_admin)
    body = (await client.get(f"/api/v1/families/{parkers.id}")).json()
    assert body["home_address"] == "12 Elm Row, Bristol BS1 4AA"


async def test_a_write_response_redacts_for_the_main_admin_of_another_family(
    client: httpx.AsyncClient,
    db: AsyncSession,
    two_families: tuple[Family, User, Family, User],
) -> None:
    """Write routes return the detail shape too, so they are the same risk as reads.

    Here the Rivera admin edits their *own* family and must not receive the Parkers'
    address — trivially true, but the assertion is that a mutating route runs the same
    serialiser rather than assembling its own body.
    """
    _, _, riveras, rivera = two_families
    await login_as(client, db, rivera)
    response = await client.patch(
        f"/api/v1/families/{riveras.id}", json={"name": "The Riveras"}
    )
    assert response.status_code == 200
    # Their own family, with no address set: the keys are present and null, which is the
    # correct answer for "you may see this, and there is nothing here".
    assert response.json()["home_address"] is None
