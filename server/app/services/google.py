"""Google Maps Platform callers. In M1 that is Geocoding, and only Geocoding.

**The cost rule, which this module exists to make enforceable** (`CLAUDE.md`,
`plan/architecture.md`):

    Never call Google in a render path. Geocode homes once; the result is cached forever in
    `families`.

Concretely, :meth:`Geocoder.geocode` is called from exactly two endpoints —
``PUT /families/{id}/home`` and ``POST /families/{id}/home/geocode`` — and from nowhere else.
A ``GET /families`` must never be able to trigger an external call, no matter what state the
row is in: a list route that repairs a failed geocode would turn one bad address into a
per-page-view bill. `plan/features/families/tasks.md` Phase 4 asks for a grep confirming the
two call sites; keep it true.

Everything here sits behind :class:`GeocoderProtocol` with :class:`FakeGeocoder` alongside,
because `CLAUDE.md` requires that the test suite never reach Google. The fake is not a
convenience — a suite that can make a network call is a suite that fails when the network
does, and one that can spend money when it does not.

The server key (`GOOGLE_MAPS_SERVER_KEY`, IP-restricted) is used, never the browser key
(referrer-restricted). They are two keys on purpose, per the guardrails in
`plan/architecture.md`; using the browser key here would mean a key that works from anywhere.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

#: `plan/features/families/design.md`: "Because geocoding is a synchronous inline call on
#: save, the endpoint has a short timeout (5 seconds) ... Nothing blocks on Google."
GEOCODE_TIMEOUT_SECONDS = 5.0

#: In preference order. `postal_town` is the useful one in the UK, where `locality` is often
#: a village nobody outside it recognises; `administrative_area_level_2` is the county-level
#: last resort. `plan/features/families/design.md` fixes this order.
LOCALITY_COMPONENTS = ("postal_town", "locality", "administrative_area_level_2")

GeocodeStatus = Literal["ok", "not_found", "error"]

#: What the admin console's API health probe can report (AC-10). `unchecked` covers both
#: "never run" and "no key configured"; the detail says which.
ProbeStatus = Literal["ok", "denied", "quota", "unreachable", "unchecked"]

#: `geocode_error` when no server key is configured. Setting one up is an admin task, so the
#: family's address still saves and the main admin's console is where the fix is offered.
ERROR_NO_API_KEY = "no_api_key"
ERROR_TIMEOUT = "timeout"
ERROR_TRANSPORT = "transport_error"


@dataclass(frozen=True)
class GeocodeResult:
    """A placed address. `plan/features/families/design.md`'s contract shape."""

    lat: float
    lng: float
    formatted_address: str
    #: The coarse town shown to members of other families, so the street address never has to
    #: leave the server for them (FM-4).
    locality: str | None


@dataclass(frozen=True)
class GeocodeOutcome:
    """What happened, in the vocabulary `families.geocode_status` is written from.

    .. note::
       `plan/features/families/design.md` sketches the contract as
       ``geocode(address) -> GeocodeResult | None``. That signature cannot carry the third
       outcome the same document requires: `None` would have to mean both "this is not a
       place" (`not_found`, the user should check what they typed) and "we could not reach
       Google" (`error`, the user should retry later), which have different copy and
       different retry semantics. The return type is therefore this three-way value. The
       shape of `GeocodeResult` is unchanged.
    """

    status: GeocodeStatus
    result: GeocodeResult | None = None
    #: A short machine code, never prose and never the address — it is serialised to clients
    #: as `families.geocode_error`.
    error: str | None = None

    @classmethod
    def found(cls, result: GeocodeResult) -> GeocodeOutcome:
        return cls(status="ok", result=result)

    @classmethod
    def not_found(cls) -> GeocodeOutcome:
        return cls(status="not_found")

    @classmethod
    def failed(cls, error: str) -> GeocodeOutcome:
        return cls(status="error", error=error)


class GeocoderProtocol(Protocol):
    async def geocode(self, address: str) -> GeocodeOutcome:  # pragma: no cover - protocol
        ...


def _locality_from(components: list[dict]) -> str | None:
    """The coarse label, by the documented preference order."""
    by_type: dict[str, str] = {}
    for component in components:
        for type_name in component.get("types", ()):
            by_type.setdefault(type_name, component.get("long_name", ""))
    for candidate in LOCALITY_COMPONENTS:
        value = by_type.get(candidate)
        if value:
            return value
    return None


class Geocoder:
    """The real caller. One request, five seconds, no retries.

    No retry loop on purpose: the user is watching a spinner on a save button, and the
    endpoint already offers an explicit retry action. A silent second attempt would double
    the worst-case wait and hide the failure the UI is designed to explain.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key if api_key is not None else settings.google_maps_server_key

    async def geocode(self, address: str) -> GeocodeOutcome:
        if not self._api_key.strip():
            # No network call at all. An unconfigured instance must not spend five seconds
            # per save discovering that it is unconfigured.
            return GeocodeOutcome.failed(ERROR_NO_API_KEY)

        params = {"address": address, "key": self._api_key}
        try:
            async with httpx.AsyncClient(timeout=GEOCODE_TIMEOUT_SECONDS) as client:
                response = await client.get(GEOCODE_URL, params=params)
        except httpx.TimeoutException:
            logger.warning("Geocoding timed out after %ss", GEOCODE_TIMEOUT_SECONDS)
            return GeocodeOutcome.failed(ERROR_TIMEOUT)
        except httpx.HTTPError:
            logger.warning("Geocoding transport failure", exc_info=True)
            return GeocodeOutcome.failed(ERROR_TRANSPORT)

        if response.status_code != 200:
            return GeocodeOutcome.failed(f"http_{response.status_code}")

        try:
            body = response.json()
        except ValueError:
            return GeocodeOutcome.failed(ERROR_TRANSPORT)

        return self._interpret(body)

    @staticmethod
    def _interpret(body: dict) -> GeocodeOutcome:
        """Map Google's own status vocabulary onto ours.

        `ZERO_RESULTS` is the only non-`OK` status that means "the address is not a place";
        the rest — `REQUEST_DENIED`, `OVER_QUERY_LIMIT`, `INVALID_REQUEST`, `UNKNOWN_ERROR` —
        are all conditions the *operator* has to fix, so they map to `error` and keep the
        retry action on screen rather than telling the user their address is wrong.
        """
        status = body.get("status")
        if status == "ZERO_RESULTS":
            return GeocodeOutcome.not_found()
        if status != "OK":
            return GeocodeOutcome.failed(str(status or "unknown_status").lower())

        results = body.get("results") or []
        if not results:
            # `OK` with nothing in it is not a documented response; treat it as the honest
            # equivalent of ZERO_RESULTS rather than raising on a malformed body.
            return GeocodeOutcome.not_found()

        first = results[0]
        location = (first.get("geometry") or {}).get("location") or {}
        try:
            lat = float(location["lat"])
            lng = float(location["lng"])
        except (KeyError, TypeError, ValueError):
            return GeocodeOutcome.failed("malformed_response")

        return GeocodeOutcome.found(
            GeocodeResult(
                lat=lat,
                lng=lng,
                formatted_address=first.get("formatted_address") or "",
                locality=_locality_from(first.get("address_components") or []),
            )
        )


@dataclass
class FakeGeocoder:
    """The test double. Deterministic, and incapable of touching the network.

    Wired in by `tests/conftest.py` through the app's dependency override, so a test that
    forgets to configure it still cannot reach Google — it gets `not_found`.
    """

    #: Address (lowercased, stripped) -> result. Anything not listed is `not_found`.
    results: dict[str, GeocodeResult] = field(default_factory=dict)
    #: When set, every call returns this outcome regardless of the address. Used for the
    #: timeout / no-key / transport cases.
    forced: GeocodeOutcome | None = None
    #: Every address this instance was asked about, in order. The assertion behind "re-saving
    #: an identical address makes no external call" (FM-3) is a length check on this.
    calls: list[str] = field(default_factory=list)

    async def geocode(self, address: str) -> GeocodeOutcome:
        self.calls.append(address)
        if self.forced is not None:
            return self.forced
        found = self.results.get(address.strip().lower())
        return GeocodeOutcome.found(found) if found else GeocodeOutcome.not_found()


def get_geocoder() -> GeocoderProtocol:
    """FastAPI dependency. Overridden with :class:`FakeGeocoder` in tests."""
    return Geocoder()


# --- the admin console's API health probe (AC-10) ---------------------------------------------

#: The four server-key APIs, each probed with the cheapest request that still proves the key
#: is accepted and the API is enabled. Fixed inputs, so a probe costs the same every time and
#: cannot be turned into a lookup service.
PROBE_URLS: dict[str, tuple[str, dict[str, str]]] = {
    "geocoding": (GEOCODE_URL, {"address": "10 Downing Street, London"}),
    "distance_matrix": (
        "https://maps.googleapis.com/maps/api/distancematrix/json",
        {"origins": "51.5074,-0.1278", "destinations": "50.2660,-5.0527"},
    ),
    "directions": (
        "https://maps.googleapis.com/maps/api/directions/json",
        {"origin": "51.5074,-0.1278", "destination": "50.2660,-5.0527"},
    ),
    "places": (
        "https://maps.googleapis.com/maps/api/place/details/json",
        # A stable, well-known place id, and only the cheapest field.
        {"place_id": "ChIJdd4hrwug2EcRmSrV3Vo6llI", "fields": "name"},
    ),
}

#: Google's own status strings, mapped onto the five the console shows. `ZERO_RESULTS` is a
#: working API that found nothing, which is a successful probe: the question is whether the
#: key is accepted, not whether Downing Street exists.
PROBE_STATUS_MAP: dict[str, ProbeStatus] = {
    "OK": "ok",
    "ZERO_RESULTS": "ok",
    "REQUEST_DENIED": "denied",
    "OVER_QUERY_LIMIT": "quota",
    "OVER_DAILY_LIMIT": "quota",
}

#: The "usual cause" line shown inline under a failing row. Written once, server-side, so the
#: explanation of a `denied` is the same wherever it appears.
PROBE_HINTS: dict[str, str] = {
    "denied": (
        "The API may not be enabled in your Google Cloud project, or the key restriction "
        "may exclude this server's IP."
    ),
    "quota": "The daily cap has been reached. Check the quota limits in Cloud Console.",
    "unreachable": "The server could not reach Google. Check the container's network access.",
    ERROR_NO_API_KEY: "No key is configured in `.env`.",
}

PROBE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ProbeResult:
    """One API's answer. `detail` is Google's own status string where there is one, so a
    surprising failure can be looked up rather than guessed at."""

    status: ProbeStatus
    detail: str | None = None

    @property
    def hint(self) -> str | None:
        return PROBE_HINTS.get(self.detail or "") or PROBE_HINTS.get(self.status)


class ProbeProtocol(Protocol):
    async def probe(self) -> dict[str, ProbeResult]:  # pragma: no cover - protocol
        ...


class GoogleProbe:
    """The real prober. Four requests, five seconds each, no retries.

    This is the one place in the product that calls Google outside a caching path, and it is
    behind an explicit button press for exactly that reason (`plan/architecture.md`'s cost
    rules; AC-10's NOTE). It is rate-limited to one press a minute by the router.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = (
            api_key if api_key is not None else settings.google_maps_server_key
        )

    async def probe(self) -> dict[str, ProbeResult]:
        if not self._api_key.strip():
            # No key, no calls. An unconfigured instance must not spend twenty seconds
            # discovering that it is unconfigured.
            return {
                name: ProbeResult("unchecked", ERROR_NO_API_KEY) for name in PROBE_URLS
            }

        results: dict[str, ProbeResult] = {}
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
            for name, (url, params) in PROBE_URLS.items():
                # Each API is classified independently: one failure never masks another's
                # success, and the whole press stays bounded at four × five seconds.
                results[name] = await self._probe_one(client, url, params)
        return results

    async def _probe_one(
        self, client: httpx.AsyncClient, url: str, params: dict[str, str]
    ) -> ProbeResult:
        try:
            response = await client.get(url, params={**params, "key": self._api_key})
        except httpx.TimeoutException:
            return ProbeResult("unreachable", ERROR_TIMEOUT)
        except httpx.HTTPError:
            return ProbeResult("unreachable", ERROR_TRANSPORT)

        if response.status_code != 200:
            return ProbeResult("unreachable", f"http_{response.status_code}")

        try:
            payload = response.json()
        except ValueError:
            return ProbeResult("unreachable", "bad_response")

        google_status = str(payload.get("status", "")) or "UNKNOWN"
        # Classified from the status field rather than the payload: whether the key works is
        # a different question from whether the answer was useful.
        return ProbeResult(
            PROBE_STATUS_MAP.get(google_status, "unreachable"), google_status
        )


@dataclass
class FakeProbe:
    """The test double. Returns whatever it was told to, and touches no network."""

    results: dict[str, ProbeResult] = field(default_factory=dict)
    calls: int = 0

    async def probe(self) -> dict[str, ProbeResult]:
        self.calls += 1
        return self.results or {
            name: ProbeResult("unchecked", ERROR_NO_API_KEY) for name in PROBE_URLS
        }


def get_probe() -> ProbeProtocol:
    """FastAPI dependency. Overridden with :class:`FakeProbe` in tests."""
    return GoogleProbe()
