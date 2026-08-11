"""Phase 11 — who may call what, route by route.

Enumerated rather than sampled. The console is the feature with the most cross-family power
in the product, and "which route did we forget to guard" is exactly the question a
representative test cannot answer.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Family, Trip, User
from tests.conftest import add_member, login_as, make_family, make_user

pytestmark = pytest.mark.asyncio

#: Every route this feature owns, as (method, path, body). `{user}` is filled per test.
READ_ROUTES = [
    ("GET", "/api/v1/admin/trip", None),
    ("GET", "/api/v1/admin/trip/stage-history", None),
    ("GET", "/api/v1/admin/category-settings", None),
    ("GET", "/api/v1/admin/overview", None),
    ("GET", "/api/v1/admin/settings", None),
    ("GET", "/api/v1/admin/google-status", None),
    ("GET", "/api/v1/admin/stats", None),
    ("GET", "/api/v1/admin/organisers", None),
]

WRITE_ROUTES = [
    ("PATCH", "/api/v1/admin/trip", {"name": "Renamed by someone"}),
    (
        "PUT",
        "/api/v1/admin/category-settings",
        {"settings": [{"category": "poll", "voting_mode": "thumbs"}]},
    ),
    ("PATCH", "/api/v1/admin/settings", {"instance_name": "Renamed"}),
    ("POST", "/api/v1/admin/google-status/check", None),
]


async def _owner(db: AsyncSession, trip: Trip) -> User:
    user = await make_user(db, "permsowner")
    family = await make_family(db, trip, "Owners", color=3)
    await add_member(db, family, user, role="head")
    trip.owner_user_id = user.id
    await db.commit()
    return user


async def _call(client, method: str, path: str, body):
    if method == "GET":
        return await client.get(path)
    if method == "PATCH":
        return await client.patch(path, json=body)
    if method == "PUT":
        return await client.put(path, json=body)
    if method == "POST":
        return await client.post(path, json=body) if body else await client.post(path)
    if method == "DELETE":
        return await client.delete(path)
    raise AssertionError(method)


@pytest.mark.parametrize(("method", "path", "body"), READ_ROUTES + WRITE_ROUTES)
async def test_a_plain_member_is_refused_everywhere(
    client, db: AsyncSession, trip: Trip, member: tuple[User, Family], method, path, body
) -> None:
    await _owner(db, trip)
    await login_as(client, db, member[0])

    response = await _call(client, method, path, body)
    assert response.status_code == 403, f"{method} {path} let a member through"


@pytest.mark.parametrize(("method", "path", "body"), READ_ROUTES + WRITE_ROUTES)
async def test_a_head_of_family_is_refused_everywhere(
    client,
    db: AsyncSession,
    trip: Trip,
    family_admin: tuple[User, Family],
    method,
    path,
    body,
) -> None:
    """A family-level role grants nothing across families — that is the whole point of the
    two kinds being independent."""
    await _owner(db, trip)
    await login_as(client, db, family_admin[0])

    response = await _call(client, method, path, body)
    assert response.status_code == 403, f"{method} {path} let a head through"


@pytest.mark.parametrize(("method", "path", "body"), READ_ROUTES)
async def test_an_organiser_may_read_everything(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family], method, path, body
) -> None:
    await _owner(db, trip)
    await login_as(client, db, organiser[0])

    response = await _call(client, method, path, body)
    assert response.status_code == 200, f"{method} {path} refused an organiser"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [route for route in WRITE_ROUTES if route[1] != "/api/v1/admin/settings"],
)
async def test_an_organiser_may_write_trip_data(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family], method, path, body
) -> None:
    await _owner(db, trip)
    await login_as(client, db, organiser[0])

    response = await _call(client, method, path, body)
    assert response.status_code == 200, f"{method} {path} refused an organiser"


async def test_instance_settings_are_the_one_write_an_organiser_cannot_make(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    """Platform-level, not trip-level — outside the cross-family powers an organiser holds."""
    await _owner(db, trip)
    await login_as(client, db, organiser[0])

    response = await client.patch("/api/v1/admin/settings", json={"instance_name": "Nope"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "owner_only"


async def test_an_organiser_reads_the_organiser_list_but_cannot_change_it(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    await _owner(db, trip)
    target = await make_user(db, "appointable")
    family = await make_family(db, trip, "Appointables", color=4)
    await add_member(db, family, target, role="head")
    await login_as(client, db, organiser[0])

    assert (await client.get("/api/v1/admin/organisers")).status_code == 200
    assert (
        await client.post("/api/v1/admin/organisers", json={"user_id": str(target.id)})
    ).status_code == 403
    assert (
        await client.delete(f"/api/v1/admin/organisers/{target.id}")
    ).status_code == 403


async def test_the_stage_endpoint_follows_the_same_rule(
    client, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    """It belongs to `holiday-stage`, but it is the console's forward action, so it is
    checked here too — a route nobody's permission test covers is a route with no guard."""
    await _owner(db, trip)
    await login_as(client, db, member[0])

    response = await client.patch(
        f"/api/v1/trips/{trip.id}/stage", json={"stage": "holiday"}
    )
    assert response.status_code == 403


async def test_the_category_read_is_deliberately_open_to_members(
    client, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    """The one route in this feature that is not organiser-gated, and the reason it exists:
    a member needs the mode to render the right control."""
    await login_as(client, db, member[0])
    assert (await client.get("/api/v1/trip/category-settings")).status_code == 200


async def test_an_outsider_gets_nothing(
    client, db: AsyncSession, trip: Trip, outsider: User
) -> None:
    await _owner(db, trip)
    await login_as(client, db, outsider)

    for method, path, body in READ_ROUTES:
        response = await _call(client, method, path, body)
        assert response.status_code == 403, f"{method} {path} let an outsider through"


async def test_signed_out_callers_get_401_not_403(client, db: AsyncSession, trip: Trip) -> None:
    """Different questions, different answers: the client shows a login screen for one and
    an access screen for the other."""
    await _owner(db, trip)
    response = await client.get("/api/v1/admin/trip")
    assert response.status_code == 401
