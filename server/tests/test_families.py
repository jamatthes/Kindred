"""Phase 5 — the families and members router.

Happy path, permission-denied and stage-guard for every route, plus the guard rails named in
`plan/features/families/design.md`'s edge-case table by their exact codes: `name_taken`,
`color_taken`, `no_color_slots`, `family_not_empty`, `head_required`, `owner_protected`,
`already_has_family`.

Roles here are the revised ones (2026-08-11): owner / organiser at trip level, head of family
/ spouse / member inside one. `test_family_permissions.py` covers the spouse asymmetry.

The codes are asserted rather than the messages: `plan/features/foundation/design.md` makes
`code` the contract and `message` free to reword.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Family, FamilyMember, Trip, User, UserSettings
from app.services.google import FakeGeocoder, GeocodeOutcome, GeocodeResult
from tests.conftest import add_member, login_as, make_family, make_user

FAMILIES = "/api/v1/families"

BRISTOL = GeocodeResult(51.4545, -2.5879, "12 Elm Row, Bristol BS1 4AA, UK", "Bristol")


def code(response: httpx.Response) -> str:
    return response.json()["detail"]["code"]


@pytest.fixture
async def owner(db: AsyncSession, trip: Trip) -> User:
    """The trip's owner by ownership rather than by the platform flag.

    Used deliberately in places, because `require_organiser` accepts either and a test that
    only ever uses `is_platform_admin` would not notice if one of the two stopped working.
    """
    user = await make_user(db, "tripowner")
    trip.owner_user_id = user.id
    await db.commit()
    return user


# --- FM-1: a family is only ever born with a head (revised 2026-08-11) ---------------------
#
# The bare `POST /families` is gone. What it used to test — colour allocation, the duplicate
# name, the ninth family — is tested against `POST /families/mine` in `test_family_setup.py`,
# which is now the only route that creates a family at all. What is tested here is that it is
# the only one.


async def test_the_bare_create_route_is_gone(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, main_admin: User
) -> None:
    """`405`, not `403` or `404`: `GET /families` still answers on this path.

    A `404` would read as "wrong URL, try another one"; `405` says the path is real and this
    verb is not, which is exactly the situation.
    """
    await login_as(client, db, main_admin)
    assert (await client.post(FAMILIES, json={"name": "The Parkers"})).status_code == 405


async def test_the_owner_cannot_create_a_family_either(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, owner: User
) -> None:
    """The capability was withdrawn from the role that had the most of it, on purpose.

    The owner's route to a family of their own is their setup step (FM-13); their route to
    anyone else's is a new-family invite (FM-6). Neither makes a family they are not in.
    """
    await login_as(client, db, owner)
    assert (await client.post(FAMILIES, json={"name": "Owned"})).status_code == 405
    assert await db.scalar(select(func.count()).select_from(Family)) == 0


async def test_no_route_leaves_a_family_with_nobody_in_it(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    main_admin: User,
    family_admin: tuple[User, Family],
) -> None:
    """The invariant, fired at every route that could plausibly break it.

    Three ways a family could end up empty, and each is refused by a different rule: creating
    one without a member (the route is gone), removing the last member (they are the head, and
    a head is handed on rather than removed), and demoting them (the same rule). A fourth —
    deleting a family that still has members — is refused so that the tidy-up click and the
    revoke-a-group's-access click cannot be the same click.
    """
    head, family = family_admin
    await login_as(client, db, main_admin)

    attempts = [
        await client.post(FAMILIES, json={"name": "Nobody's"}),
        await client.delete(f"{FAMILIES}/{family.id}/members/{head.id}"),
        await client.patch(
            f"{FAMILIES}/{family.id}/members/{head.id}", json={"role": "member"}
        ),
        await client.delete(f"{FAMILIES}/{family.id}"),
    ]
    assert all(r.status_code >= 400 for r in attempts), [r.status_code for r in attempts]

    memberless = await db.scalar(
        select(func.count())
        .select_from(Family)
        .where(~select(FamilyMember.id).where(FamilyMember.family_id == Family.id).exists())
    )
    assert memberless == 0


async def test_a_head_cannot_create_a_family(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, _ = family_admin
    await login_as(client, db, user)
    assert (await client.post(FAMILIES, json={"name": "Mine now"})).status_code == 405


# --- FM-4: read ----------------------------------------------------------------------------


async def test_a_member_sees_every_family_on_the_trip(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    user, _ = member
    await make_family(db, trip, "Others", color=5)
    await login_as(client, db, user)
    response = await client.get(FAMILIES)
    assert response.status_code == 200
    assert {f["name"] for f in response.json()} == {"Membersons", "Others"}


async def test_the_list_route_never_carries_an_address_for_anybody(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, family_admin: tuple[User, Family]
) -> None:
    """There is no code path in the list route that could include one, which is the point."""
    user, family = family_admin
    family.home_address = "12 Elm Row, Bristol"
    family.home_locality = "Bristol"
    await db.commit()

    await login_as(client, db, user)
    payload = (await client.get(FAMILIES)).json()[0]
    assert "home_address" not in payload
    assert payload["home_locality"] == "Bristol"


async def test_someone_with_no_family_is_told_they_are_not_on_the_trip(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, outsider: User
) -> None:
    """A distinct code from `forbidden`, so the client can show the right screen."""
    await login_as(client, db, outsider)
    response = await client.get(FAMILIES)
    assert response.status_code == 403
    assert code(response) == "not_on_trip"


async def test_reading_one_family_includes_its_members(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    body = (await client.get(f"{FAMILIES}/{family.id}")).json()
    assert [m["username"] for m in body["members"]] == ["familyadmin"]
    assert body["members"][0]["role"] == "head"
    assert body["members"][0]["initials"] == "F"


async def test_reading_an_unknown_family_is_a_404(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, _ = family_admin
    await login_as(client, db, user)
    assert (await client.get(f"{FAMILIES}/{uuid.uuid4()}")).status_code == 404


# --- FM-2: rename and recolour -------------------------------------------------------------


async def test_a_head_renames_their_own_family(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    response = await client.patch(f"{FAMILIES}/{family.id}", json={"name": "Renamed"})
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


async def test_a_head_cannot_rename_another_family(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    family_admin: tuple[User, Family],
) -> None:
    user, _ = family_admin
    other = await make_family(db, trip, "Theirs", color=7)
    await login_as(client, db, user)
    response = await client.patch(f"{FAMILIES}/{other.id}", json={"name": "Mine now"})
    assert response.status_code == 403


async def test_a_plain_member_cannot_rename_their_own_family(
    client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family]
) -> None:
    user, family = member
    await login_as(client, db, user)
    assert (
        await client.patch(f"{FAMILIES}/{family.id}", json={"name": "Nope"})
    ).status_code == 403


async def test_an_organiser_can_rename_any_family(
    client: httpx.AsyncClient, db: AsyncSession, main_admin: User, member: tuple[User, Family]
) -> None:
    _, family = member
    await login_as(client, db, main_admin)
    response = await client.patch(f"{FAMILIES}/{family.id}", json={"name": "Renamed by boss"})
    assert response.status_code == 200


async def test_renaming_in_the_end_stage_is_refused(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    family_admin: tuple[User, Family],
) -> None:
    user, family = family_admin
    trip.stage = "end"
    await db.commit()
    await login_as(client, db, user)
    response = await client.patch(f"{FAMILIES}/{family.id}", json={"name": "Frozen"})
    assert code(response) == "stage_forbidden"


async def test_keeping_your_own_colour_is_not_a_clash_with_yourself(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    response = await client.patch(f"{FAMILIES}/{family.id}", json={"color": family.color})
    assert response.status_code == 200


# --- FM-3: home address --------------------------------------------------------------------


async def test_setting_a_home_address_places_it(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    geocoder: FakeGeocoder,
) -> None:
    user, family = family_admin
    geocoder.results["12 elm row, bristol"] = BRISTOL
    await login_as(client, db, user)

    response = await client.put(
        f"{FAMILIES}/{family.id}/home", json={"home_address": "12 Elm Row, Bristol"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["geocode_status"] == "ok"
    assert body["home_placed"] is True
    assert body["home_lat"] == pytest.approx(51.4545)
    assert body["home_locality"] == "Bristol"


async def test_resaving_an_identical_placed_address_makes_no_external_call(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    geocoder: FakeGeocoder,
) -> None:
    """FM-3, and the cost rule: the answer cannot have changed and the bill would be real."""
    user, family = family_admin
    geocoder.results["12 elm row, bristol"] = BRISTOL
    await login_as(client, db, user)
    url = f"{FAMILIES}/{family.id}/home"

    await client.put(url, json={"home_address": "12 Elm Row, Bristol"})
    assert len(geocoder.calls) == 1
    again = await client.put(url, json={"home_address": "12 Elm Row, Bristol"})
    assert again.status_code == 200
    assert len(geocoder.calls) == 1


async def test_changing_the_address_clears_the_old_coordinates_and_recalls(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    geocoder: FakeGeocoder,
) -> None:
    """A pin left at the old address would put the family somewhere they no longer live."""
    user, family = family_admin
    geocoder.results["12 elm row, bristol"] = BRISTOL
    await login_as(client, db, user)
    url = f"{FAMILIES}/{family.id}/home"

    await client.put(url, json={"home_address": "12 Elm Row, Bristol"})
    moved = await client.put(url, json={"home_address": "Somewhere unlisted"})
    assert len(geocoder.calls) == 2
    assert moved.json()["geocode_status"] == "not_found"
    assert moved.json()["home_lat"] is None


async def test_an_unplaceable_address_is_still_saved(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
) -> None:
    """FM-3: "the address is still saved, coordinates stay null"."""
    user, family = family_admin
    await login_as(client, db, user)
    body = (
        await client.put(
            f"{FAMILIES}/{family.id}/home", json={"home_address": "Nowhere at all"}
        )
    ).json()
    assert body["geocode_status"] == "not_found"
    assert body["home_address"] == "Nowhere at all"
    assert body["home_placed"] is False


async def test_a_missing_api_key_saves_the_address_and_says_why(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    geocoder: FakeGeocoder,
) -> None:
    """Setting up a key is an admin task, not a user error — so this is a 200, not a 5xx."""
    user, family = family_admin
    geocoder.forced = GeocodeOutcome.failed("no_api_key")
    await login_as(client, db, user)

    response = await client.put(
        f"{FAMILIES}/{family.id}/home", json={"home_address": "12 Elm Row"}
    )
    assert response.status_code == 200
    assert response.json()["geocode_status"] == "error"
    assert response.json()["geocode_error"] == "no_api_key"


async def test_retrying_a_geocode_is_unconditional(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    geocoder: FakeGeocoder,
) -> None:
    """The user is asking *because* it failed; skip-if-unchanged would make the button
    do nothing."""
    user, family = family_admin
    geocoder.forced = GeocodeOutcome.failed("timeout")
    await login_as(client, db, user)
    await client.put(f"{FAMILIES}/{family.id}/home", json={"home_address": "12 Elm Row"})

    geocoder.forced = None
    geocoder.results["12 elm row"] = BRISTOL
    retried = await client.post(f"{FAMILIES}/{family.id}/home/geocode")
    assert retried.json()["geocode_status"] == "ok"
    assert len(geocoder.calls) == 2


async def test_retrying_with_no_address_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    response = await client.post(f"{FAMILIES}/{family.id}/home/geocode")
    assert response.status_code == 409
    assert code(response) == "no_home_address"


async def test_clearing_the_address_returns_the_status_to_pending(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    geocoder: FakeGeocoder,
) -> None:
    """`pending` — never attempted — rather than `not_found`, which would claim we tried and
    failed on an address that no longer exists."""
    user, family = family_admin
    geocoder.results["12 elm row"] = BRISTOL
    await login_as(client, db, user)
    await client.put(f"{FAMILIES}/{family.id}/home", json={"home_address": "12 Elm Row"})

    assert (await client.delete(f"{FAMILIES}/{family.id}/home")).status_code == 204
    body = (await client.get(f"{FAMILIES}/{family.id}")).json()
    assert body["geocode_status"] == "pending"
    assert body["home_address"] is None
    assert body["home_placed"] is False
    assert body["home_locality"] is None


async def test_a_plain_member_cannot_set_the_home_address(
    client: httpx.AsyncClient, db: AsyncSession, member: tuple[User, Family]
) -> None:
    user, family = member
    await login_as(client, db, user)
    response = await client.put(
        f"{FAMILIES}/{family.id}/home", json={"home_address": "Anywhere"}
    )
    assert response.status_code == 403


async def test_setting_a_home_in_the_end_stage_is_refused(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    family_admin: tuple[User, Family],
) -> None:
    user, family = family_admin
    trip.stage = "end"
    await db.commit()
    await login_as(client, db, user)
    response = await client.put(
        f"{FAMILIES}/{family.id}/home", json={"home_address": "Anywhere"}
    )
    assert code(response) == "stage_forbidden"


# --- FM-10: delete -------------------------------------------------------------------------


async def test_an_organiser_deletes_an_empty_family(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, main_admin: User
) -> None:
    empty = await make_family(db, trip, "Nobody", color=6)
    await login_as(client, db, main_admin)
    assert (await client.delete(f"{FAMILIES}/{empty.id}")).status_code == 204
    # A column select, not `db.get`: this session still has the object in its identity map,
    # so `get` would hand back the stale instance without touching the database.
    assert await db.scalar(select(Family.id).where(Family.id == empty.id)) is None


async def test_deleting_a_family_with_members_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, main_admin: User, member: tuple[User, Family]
) -> None:
    """Deliberate: the click that revokes a whole group's access looks identical to the one
    that tidies up an empty row."""
    _, family = member
    await login_as(client, db, main_admin)
    response = await client.delete(f"{FAMILIES}/{family.id}")
    assert response.status_code == 409
    assert code(response) == "family_not_empty"


async def test_a_head_cannot_delete_their_own_family(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, family_admin: tuple[User, Family]
) -> None:
    user, family = family_admin
    await login_as(client, db, user)
    assert (await client.delete(f"{FAMILIES}/{family.id}")).status_code == 403


# --- FM-9: members -------------------------------------------------------------------------


@pytest.fixture
async def household(
    db: AsyncSession, trip: Trip
) -> tuple[Family, User, User]:
    """A family with a head and one ordinary member."""
    family = await make_family(db, trip, "Household", color=4)
    admin = await make_user(db, "houseadmin")
    other = await make_user(db, "houseother")
    await add_member(db, family, admin, role="head")
    await add_member(db, family, other, role="member")
    return family, admin, other


async def test_a_head_promotes_a_member_to_spouse(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    """FM-16 — a second adult with the head's powers over the family."""
    family, admin, other = household
    await login_as(client, db, admin)
    response = await client.patch(
        f"{FAMILIES}/{family.id}/members/{other.id}", json={"role": "spouse"}
    )
    assert response.status_code == 200
    assert response.json()["role"] == "spouse"


async def test_demoting_the_head_is_refused_because_a_family_needs_one(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    """A family always has exactly one head, so the answer is a transfer, not a vacancy."""
    family, admin, _ = household
    await login_as(client, db, admin)
    response = await client.patch(
        f"{FAMILIES}/{family.id}/members/{admin.id}", json={"role": "member"}
    )
    assert response.status_code == 409
    assert code(response) == "head_required"


async def test_handing_the_head_role_on_is_one_action(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    """The incoming head takes the role and the outgoing one becomes a spouse, together.

    Two statements would leave a window with two heads or none — and the partial unique index
    would reject the first of them anyway.
    """
    family, admin, other = household
    await login_as(client, db, admin)
    response = await client.patch(
        f"{FAMILIES}/{family.id}/members/{other.id}", json={"role": "head"}
    )
    assert response.status_code == 200
    assert response.json()["role"] == "head"

    roles = {
        m["username"]: m["role"]
        for m in (await client.get(f"{FAMILIES}/{family.id}")).json()["members"]
    }
    assert roles == {"houseother": "head", "houseadmin": "spouse"}


async def test_removing_the_head_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    family, admin, _ = household
    await login_as(client, db, admin)
    response = await client.delete(f"{FAMILIES}/{family.id}/members/{admin.id}")
    assert response.status_code == 409
    assert code(response) == "head_required"


async def test_a_head_removes_a_member(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    family, admin, other = household
    await login_as(client, db, admin)
    assert (
        await client.delete(f"{FAMILIES}/{family.id}/members/{other.id}")
    ).status_code == 204
    assert await db.scalar(
        select(FamilyMember).where(FamilyMember.user_id == other.id)
    ) is None


async def test_a_removed_members_account_survives(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    """FM-9: "their account still exists but has no family". Their past contributions stay
    attributed to them."""
    family, admin, other = household
    await login_as(client, db, admin)
    await client.delete(f"{FAMILIES}/{family.id}/members/{other.id}")
    assert await db.get(User, other.id) is not None


async def test_the_owner_cannot_be_removed(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    main_admin: User,
) -> None:
    """FM-9/FM-10. Their family role here is `spouse`, so it is the owner protection doing
    the refusing rather than the head-required rule."""
    family = await make_family(db, trip, "Bosses", color=3)
    helper = await make_user(db, "helper")
    await add_member(db, family, helper, role="head")
    await add_member(db, family, main_admin, role="spouse")
    await login_as(client, db, main_admin)

    response = await client.delete(f"{FAMILIES}/{family.id}/members/{main_admin.id}")
    assert response.status_code == 403
    assert code(response) == "owner_protected"


async def test_the_owner_cannot_be_demoted(
    client: httpx.AsyncClient, db: AsyncSession, trip: Trip, main_admin: User
) -> None:
    family = await make_family(db, trip, "Bosses", color=3)
    helper = await make_user(db, "helper")
    await add_member(db, family, helper, role="head")
    await add_member(db, family, main_admin, role="spouse")
    await login_as(client, db, main_admin)

    response = await client.patch(
        f"{FAMILIES}/{family.id}/members/{main_admin.id}", json={"role": "member"}
    )
    assert code(response) == "owner_protected"


async def test_a_head_cannot_touch_another_familys_members(
    client: httpx.AsyncClient,
    db: AsyncSession,
    household: tuple[Family, User, User],
    family_admin: tuple[User, Family],
) -> None:
    family, _, other = household
    intruder, _ = family_admin
    await login_as(client, db, intruder)
    response = await client.delete(f"{FAMILIES}/{family.id}/members/{other.id}")
    assert response.status_code == 403


async def test_removing_a_member_in_the_end_stage_is_refused(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    household: tuple[Family, User, User],
) -> None:
    family, admin, other = household
    trip.stage = "end"
    await db.commit()
    await login_as(client, db, admin)
    response = await client.delete(f"{FAMILIES}/{family.id}/members/{other.id}")
    assert code(response) == "stage_forbidden"


async def test_listing_members_is_open_to_any_member_of_the_trip(
    client: httpx.AsyncClient,
    db: AsyncSession,
    household: tuple[Family, User, User],
    member: tuple[User, Family],
) -> None:
    family, _, _ = household
    outsider_member, _ = member
    await login_as(client, db, outsider_member)
    response = await client.get(f"{FAMILIES}/{family.id}/members")
    assert response.status_code == 200
    assert len(response.json()) == 2
    # ...but not their consent state.
    assert all(m["location_sharing_enabled"] is None for m in response.json())


# --- FM-15: the location policy ------------------------------------------------------------


async def test_the_family_switch_is_written_and_nothing_else_is(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    """The invariant the whole privacy story rests on, at its most direct."""
    family, admin, other = household
    settings = await db.scalar(select(UserSettings).where(UserSettings.user_id == other.id))
    settings.live_location_enabled = True
    await db.commit()

    await login_as(client, db, admin)
    response = await client.patch(
        f"{FAMILIES}/{family.id}/location-policy",
        json={"sharing_allowed": False, "member_default": True},
    )
    assert response.status_code == 200
    assert response.json()["location_sharing_allowed"] is False
    assert response.json()["member_location_default"] is True

    await db.refresh(settings)
    assert settings.live_location_enabled is True  # untouched


async def test_turning_the_family_switch_back_on_restores_the_previous_sharers(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    """Because it never wrote to anyone's consent, there is nothing to restore *from*."""
    family, admin, other = household
    settings = await db.scalar(select(UserSettings).where(UserSettings.user_id == other.id))
    settings.live_location_enabled = True
    await db.commit()

    await login_as(client, db, admin)
    url = f"{FAMILIES}/{family.id}/location-policy"
    await client.patch(url, json={"sharing_allowed": False})
    await client.patch(url, json={"sharing_allowed": True})

    await db.refresh(settings)
    assert settings.live_location_enabled is True


async def test_the_per_member_switch_is_a_permission_not_a_consent(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    family, admin, other = household
    settings = await db.scalar(select(UserSettings).where(UserSettings.user_id == other.id))
    settings.live_location_enabled = True
    await db.commit()

    await login_as(client, db, admin)
    response = await client.patch(
        f"{FAMILIES}/{family.id}/members/{other.id}",
        json={"location_sharing_allowed": False},
    )
    assert response.json()["location_sharing_allowed"] is False
    assert response.json()["location_sharing_enabled"] is True  # their own choice, unchanged

    await db.refresh(settings)
    assert settings.live_location_enabled is True


async def test_a_plain_member_cannot_change_the_family_policy(
    client: httpx.AsyncClient, db: AsyncSession, household: tuple[Family, User, User]
) -> None:
    family, _, other = household
    await login_as(client, db, other)
    response = await client.patch(
        f"{FAMILIES}/{family.id}/location-policy", json={"sharing_allowed": False}
    )
    assert response.status_code == 403


async def test_the_policy_is_frozen_in_the_end_stage(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    household: tuple[Family, User, User],
) -> None:
    family, admin, _ = household
    trip.stage = "end"
    await db.commit()
    await login_as(client, db, admin)
    response = await client.patch(
        f"{FAMILIES}/{family.id}/location-policy", json={"sharing_allowed": False}
    )
    assert code(response) == "stage_forbidden"


# --- unauthenticated -----------------------------------------------------------------------


async def test_none_of_this_is_public(client: httpx.AsyncClient) -> None:
    assert (await client.get(FAMILIES)).status_code == 401
