"""Phase 4 — the four geocoding outcomes, none of which reaches the network.

`plan/features/families/tasks.md`: "each of the four outcomes produces the right status and
never raises". The real :class:`Geocoder` is exercised through a stubbed transport rather
than a live call, because the interesting part is the interpretation of Google's own status
vocabulary, and that is the part a fake-only test would never check.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.google import (
    ERROR_NO_API_KEY,
    ERROR_TIMEOUT,
    ERROR_TRANSPORT,
    FakeGeocoder,
    GeocodeOutcome,
    GeocodeResult,
    Geocoder,
    _locality_from,
)

BRISTOL = {
    "status": "OK",
    "results": [
        {
            "formatted_address": "12 Elm Row, Bristol BS1 4AA, UK",
            "geometry": {"location": {"lat": 51.4545, "lng": -2.5879}},
            "address_components": [
                {"long_name": "12", "types": ["street_number"]},
                {"long_name": "Elm Row", "types": ["route"]},
                {"long_name": "Bristol", "types": ["postal_town"]},
                {"long_name": "City of Bristol", "types": ["administrative_area_level_2"]},
                {"long_name": "United Kingdom", "types": ["country", "political"]},
            ],
        }
    ],
}


@pytest.fixture
def stub_http(monkeypatch: pytest.MonkeyPatch):
    """Answer the service's one HTTP call from a mock transport.

    Nothing leaves the process (`CLAUDE.md`). The real `Geocoder` is under test rather than
    the fake, because the interesting part is the interpretation of Google's status
    vocabulary — exactly the part a fake-only test would never reach.
    """

    def _install(handler):
        real = httpx.AsyncClient

        def _factory(*_args, **kwargs):
            kwargs.pop("timeout", None)
            return real(transport=httpx.MockTransport(handler))

        monkeypatch.setattr("app.services.google.httpx.AsyncClient", _factory)

    return _install


# --- the four outcomes --------------------------------------------------------------------


async def test_a_missing_key_fails_without_any_network_call(stub_http) -> None:
    """An unconfigured instance must not spend five seconds discovering it is unconfigured."""

    def _explode(_request):  # pragma: no cover — reaching this is the failure
        raise AssertionError("the geocoder called out with no key configured")

    stub_http(_explode)
    outcome = await Geocoder(api_key="").geocode("12 Elm Row")
    assert outcome.status == "error"
    assert outcome.error == ERROR_NO_API_KEY
    assert outcome.result is None


async def test_a_result_is_ok_with_the_locality_derived(stub_http) -> None:
    stub_http(lambda _r: httpx.Response(200, json=BRISTOL))
    outcome = await Geocoder(api_key="k").geocode("12 Elm Row")
    assert outcome.status == "ok"
    assert outcome.result == GeocodeResult(
        lat=51.4545,
        lng=-2.5879,
        formatted_address="12 Elm Row, Bristol BS1 4AA, UK",
        locality="Bristol",
    )


async def test_zero_results_is_not_found_not_an_error(stub_http) -> None:
    """These are different states with different copy: "check the address" vs "try later"."""
    stub_http(lambda _r: httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []}))
    outcome = await Geocoder(api_key="k").geocode("nowhere at all")
    assert outcome.status == "not_found"
    assert outcome.error is None


async def test_a_timeout_is_an_error_and_does_not_raise(stub_http) -> None:
    def _timeout(request):
        raise httpx.ConnectTimeout("too slow", request=request)

    stub_http(_timeout)
    outcome = await Geocoder(api_key="k").geocode("12 Elm Row")
    assert outcome.status == "error"
    assert outcome.error == ERROR_TIMEOUT


async def test_a_transport_failure_is_an_error(stub_http) -> None:
    def _boom(request):
        raise httpx.ConnectError("no route to host", request=request)

    stub_http(_boom)
    outcome = await Geocoder(api_key="k").geocode("12 Elm Row")
    assert outcome.status == "error"
    assert outcome.error == ERROR_TRANSPORT


async def test_a_non_200_is_an_error_naming_the_status(stub_http) -> None:
    stub_http(lambda _r: httpx.Response(502, text="bad gateway"))
    outcome = await Geocoder(api_key="k").geocode("12 Elm Row")
    assert outcome == GeocodeOutcome(status="error", error="http_502")


async def test_an_operator_level_google_status_is_an_error_not_a_bad_address(
    stub_http,
) -> None:
    """`REQUEST_DENIED` means the key is wrong. Telling the user their address is wrong
    would send them off to fix something that is not broken."""
    stub_http(lambda _r: httpx.Response(200, json={"status": "REQUEST_DENIED"}))
    outcome = await Geocoder(api_key="k").geocode("12 Elm Row")
    assert outcome.status == "error"
    assert outcome.error == "request_denied"


async def test_a_malformed_body_is_an_error_rather_than_a_crash(stub_http) -> None:
    stub_http(lambda _r: httpx.Response(200, text="<html>not json</html>"))
    outcome = await Geocoder(api_key="k").geocode("12 Elm Row")
    assert outcome.status == "error"
    assert outcome.error == ERROR_TRANSPORT


async def test_ok_with_no_coordinates_is_an_error(stub_http) -> None:
    stub_http(
        lambda _r: httpx.Response(
            200, json={"status": "OK", "results": [{"formatted_address": "somewhere"}]}
        )
    )
    outcome = await Geocoder(api_key="k").geocode("12 Elm Row")
    assert outcome.status == "error"
    assert outcome.error == "malformed_response"


# --- locality derivation ------------------------------------------------------------------


def test_postal_town_wins_over_locality() -> None:
    """In the UK `locality` is often a village nobody outside it recognises."""
    components = [
        {"long_name": "Clifton", "types": ["locality"]},
        {"long_name": "Bristol", "types": ["postal_town"]},
    ]
    assert _locality_from(components) == "Bristol"


def test_locality_is_used_when_there_is_no_postal_town() -> None:
    assert _locality_from([{"long_name": "Lyon", "types": ["locality"]}]) == "Lyon"


def test_the_county_is_the_last_resort() -> None:
    components = [{"long_name": "Somerset", "types": ["administrative_area_level_2"]}]
    assert _locality_from(components) == "Somerset"


def test_no_recognised_component_gives_no_locality() -> None:
    """A placed home with no town is fine: `home_locality` is nullable, and the pin still
    appears. Inventing a label from the country would be worse than none."""
    assert _locality_from([{"long_name": "United Kingdom", "types": ["country"]}]) is None


# --- the fake -----------------------------------------------------------------------------


async def test_the_fake_records_every_call_it_is_asked_to_make() -> None:
    """The "no external call when the address is unchanged" assertion (FM-3) is a length
    check on this list, so it has to be trustworthy."""
    fake = FakeGeocoder(
        results={
            "12 elm row": GeocodeResult(1.0, 2.0, "12 Elm Row", "Bristol"),
        }
    )
    assert (await fake.geocode("12 Elm Row")).status == "ok"
    assert (await fake.geocode("unknown place")).status == "not_found"
    assert fake.calls == ["12 Elm Row", "unknown place"]


async def test_the_fake_can_force_any_outcome() -> None:
    fake = FakeGeocoder(forced=GeocodeOutcome.failed(ERROR_NO_API_KEY))
    assert (await fake.geocode("anything")).error == ERROR_NO_API_KEY
