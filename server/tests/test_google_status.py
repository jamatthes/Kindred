"""Phase 7 — instance settings, the Google probe, and the stats.

The probe is the one place the product deliberately calls Google outside a caching path, so
the tests care about two things above all: that the *read* never calls anything, and that the
button cannot be used as a call generator.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.models import Family, Trip, User
from app.services.google import FakeProbe, ProbeResult, get_probe
from tests.conftest import add_member, login_as, make_family, make_user

pytestmark = pytest.mark.asyncio


@pytest.fixture
def probe() -> FakeProbe:
    """A prober that cannot reach the network, wired in through the app's own override."""
    return FakeProbe()


@pytest.fixture
async def probe_client(probe: FakeProbe):
    import httpx  # noqa: PLC0415

    app = create_app()
    app.dependency_overrides[get_probe] = lambda: probe
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _owner(db: AsyncSession, trip: Trip) -> User:
    user = await make_user(db, "statusowner")
    family = await make_family(db, trip, "Owners", color=3)
    await add_member(db, family, user, role="head")
    trip.owner_user_id = user.id
    await db.commit()
    return user


# --- instance settings ------------------------------------------------------------------------


async def test_an_organiser_reads_but_cannot_write_instance_settings(
    client, db: AsyncSession, trip: Trip, organiser: tuple[User, Family]
) -> None:
    """Platform-level values sit outside the cross-family *trip* powers an organiser holds."""
    await _owner(db, trip)
    await login_as(client, db, organiser[0])

    assert (await client.get("/api/v1/admin/settings")).status_code == 200
    response = await client.patch(
        "/api/v1/admin/settings", json={"instance_name": "Hijacked"}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "owner_only"


async def test_the_owner_can_rename_the_instance(
    client, db: AsyncSession, trip: Trip
) -> None:
    await login_as(client, db, await _owner(db, trip))

    body = (
        await client.patch(
            "/api/v1/admin/settings", json={"instance_name": "The Cornwall Crew"}
        )
    ).json()
    assert body["instance_name"] == "The Cornwall Crew"

    # And the public read the login screen uses agrees, because both go through one store.
    public = (await client.get("/api/v1/settings")).json()
    assert public["instance_name"] == "The Cornwall Crew"


async def test_open_registration_is_refused_with_an_explanation(
    client, db: AsyncSession, trip: Trip
) -> None:
    await login_as(client, db, await _owner(db, trip))

    response = await client.patch("/api/v1/admin/settings", json={"invite_only": False})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "not_implemented"


async def test_instance_settings_stay_editable_in_the_end_stage(
    client, db: AsyncSession, trip: Trip
) -> None:
    owner = await _owner(db, trip)
    trip.stage = "end"
    await db.commit()
    await login_as(client, db, owner)

    # Not trip data: an archived trip does not make the instance unnameable.
    response = await client.patch("/api/v1/admin/settings", json={"instance_name": "Still"})
    assert response.status_code == 200


# --- the Google probe --------------------------------------------------------------------------


async def test_the_read_never_calls_google(
    probe_client, db: AsyncSession, trip: Trip, probe: FakeProbe
) -> None:
    await login_as(probe_client, db, await _owner(db, trip))

    body = (await probe_client.get("/api/v1/admin/google-status")).json()
    assert probe.calls == 0
    # Never checked: every row says so rather than the section rendering blank.
    assert {row["status"] for row in body["apis"]} == {"unchecked"}
    assert body["checked_at"] is None


@pytest.mark.parametrize(
    ("status", "detail"),
    [
        ("ok", "OK"),
        ("denied", "REQUEST_DENIED"),
        ("quota", "OVER_QUERY_LIMIT"),
        ("unreachable", "timeout"),
        ("unchecked", "no_api_key"),
    ],
)
async def test_every_classification_is_reported_with_its_hint(
    probe_client, db: AsyncSession, trip: Trip, probe: FakeProbe, status: str, detail: str
) -> None:
    probe.results = {
        name: ProbeResult(status, detail)
        for name in ("geocoding", "distance_matrix", "directions", "places")
    }
    await login_as(probe_client, db, await _owner(db, trip))

    body = (await probe_client.post("/api/v1/admin/google-status/check")).json()
    server_rows = [row for row in body["apis"] if row["key_type"] == "server"]
    assert {row["status"] for row in server_rows} == {status}
    if status in ("denied", "quota", "unreachable") or detail == "no_api_key":
        # Colour is never the only carrier: a failure explains its usual cause in words.
        assert all(row["hint"] for row in server_rows)


async def test_a_partial_failure_does_not_mask_the_successes(
    probe_client, db: AsyncSession, trip: Trip, probe: FakeProbe
) -> None:
    probe.results = {
        "geocoding": ProbeResult("ok", "OK"),
        "distance_matrix": ProbeResult("denied", "REQUEST_DENIED"),
        "directions": ProbeResult("ok", "OK"),
        "places": ProbeResult("quota", "OVER_QUERY_LIMIT"),
    }
    await login_as(probe_client, db, await _owner(db, trip))

    body = (await probe_client.post("/api/v1/admin/google-status/check")).json()
    by_name = {row["name"]: row["status"] for row in body["apis"]}
    assert by_name["Geocoding"] == "ok"
    assert by_name["Distance Matrix"] == "denied"
    assert by_name["Places"] == "quota"


async def test_maps_js_is_reported_without_being_probed(
    probe_client, db: AsyncSession, trip: Trip, probe: FakeProbe
) -> None:
    await login_as(probe_client, db, await _owner(db, trip))

    body = (await probe_client.post("/api/v1/admin/google-status/check")).json()
    maps_js = next(row for row in body["apis"] if row["name"] == "Maps JavaScript")
    # It is a browser-side loader restricted by referrer; no server request can verify it,
    # and claiming otherwise would be a lie the UI then has to maintain.
    assert maps_js["key_type"] == "browser"
    assert maps_js["status"] in ("configured", "unchecked")


async def test_the_result_is_stored_and_survives_the_next_read(
    probe_client, db: AsyncSession, trip: Trip, probe: FakeProbe
) -> None:
    probe.results = {
        name: ProbeResult("ok", "OK")
        for name in ("geocoding", "distance_matrix", "directions", "places")
    }
    owner = await _owner(db, trip)
    await login_as(probe_client, db, owner)

    await probe_client.post("/api/v1/admin/google-status/check")
    body = (await probe_client.get("/api/v1/admin/google-status")).json()

    assert body["checked_at"] is not None
    assert body["checked_by"] == str(owner.id)
    assert {row["status"] for row in body["apis"] if row["key_type"] == "server"} == {"ok"}
    assert probe.calls == 1  # the read did not run it again


async def test_pressing_twice_inside_a_minute_is_rate_limited(
    probe_client, db: AsyncSession, trip: Trip, probe: FakeProbe
) -> None:
    await login_as(probe_client, db, await _owner(db, trip))

    first = await probe_client.post("/api/v1/admin/google-status/check")
    second = await probe_client.post("/api/v1/admin/google-status/check")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "rate_limited"
    assert second.headers["Retry-After"] == "60"
    # And the second press cost nothing: the limiter runs before the prober.
    assert probe.calls == 1


async def test_a_corrupt_stored_value_reads_as_never_checked(
    probe_client, db: AsyncSession, trip: Trip
) -> None:
    from app.core.settings_store import set_setting  # noqa: PLC0415

    await set_setting(db, "google_api_status", "not-a-dict")
    await db.commit()
    await login_as(probe_client, db, await _owner(db, trip))

    body = (await probe_client.get("/api/v1/admin/google-status")).json()
    # Failing to render because a previous result was malformed would be the least useful
    # possible response.
    assert body["checked_at"] is None
    assert {row["status"] for row in body["apis"]} == {"unchecked"}


# --- stats -------------------------------------------------------------------------------------


async def test_stats_are_complete_with_zeroes_for_unbuilt_features(
    client, db: AsyncSession, trip: Trip, member: tuple[User, Family]
) -> None:
    await login_as(client, db, await _owner(db, trip))

    body = (await client.get("/api/v1/admin/stats")).json()
    assert body["families"] >= 2
    assert body["members"] >= 2
    # Zero rather than an error, so the console works before `polls` exists.
    assert body["polls_open"] == 0
    assert body["comments"] == 0
    assert body["suggestions_by_status"] == {
        "proposed": 0,
        "approved": 0,
        "scheduled": 0,
        "rejected": 0,
    }
