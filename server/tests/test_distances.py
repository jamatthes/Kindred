"""Tests for `app.services.distances`.

Pure unit tests: no DB fixtures, no network — `DistanceMatrixService` is exercised entirely
through `FakeHttpTransport` and (mostly) the real `InMemoryTtlCache` with an injected clock, so
TTL behaviour is deterministic rather than depending on wall time.

**Test-DB isolation** (per the M3-services pre-build brief, same as `test_boundaries.py` and
`test_link_preview.py`): `tests/conftest.py`'s session-scoped `_database` autouse fixture still
fires for this file even though nothing here touches a table. Point `TEST_DATABASE_URL` at a
private database (must end in `_test`) to run this suite without racing another agent's:

    # from server/
    TEST_DATABASE_URL="postgresql+asyncpg://kindred:change-me@localhost:5432/kindred_dist_test" \\
        pytest tests/test_distances.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.distances import (
    DEFAULT_CACHE_TTL_SECONDS,
    DISTANCE_MATRIX_URL,
    MAX_DESTINATIONS_PER_REQUEST,
    MAX_ORIGINS_PER_REQUEST,
    RETRY_BACKOFF_SECONDS,
    CacheProtocol,
    DistanceMatrixService,
    DistanceServiceAuthError,
    DistanceServiceConfigError,
    DistanceServiceQuotaError,
    DistanceServiceTransportError,
    ElementResult,
    FakeHttpTransport,
    InMemoryTtlCache,
    LatLng,
    _parse_grid,
    cache_key,
)

FIXTURES = Path(__file__).parent / "fixtures"
GRID_2X2 = json.loads((FIXTURES / "distance_matrix_response.json").read_text(encoding="utf-8"))


def _params(origins: list[LatLng], destinations: list[LatLng], mode: str = "driving") -> dict[str, str]:
    return {
        "origins": "|".join(f"{o.lat},{o.lng}" for o in origins),
        "destinations": "|".join(f"{d.lat},{d.lng}" for d in destinations),
        "mode": mode,
        "key": "test-key",
    }


def _ok_body(origins: list[LatLng], destinations: list[LatLng]) -> dict:
    """A body where every element is `OK` with a deterministic, index-derived value, so a test
    can check which cell landed where without hand-writing a grid each time."""
    return {
        "status": "OK",
        "origin_addresses": [f"origin-{i}" for i in range(len(origins))],
        "destination_addresses": [f"dest-{j}" for j in range(len(destinations))],
        "rows": [
            {
                "elements": [
                    {
                        "status": "OK",
                        "duration": {"value": 100 + 10 * i + j, "text": "n/a"},
                        "distance": {"value": 1000 + 100 * i + j, "text": "n/a"},
                    }
                    for j in range(len(destinations))
                ]
            }
            for i in range(len(origins))
        ],
    }


class _FakeSleep:
    """Records every backoff sleep instead of actually waiting, so retry tests are instant
    and assert exactly how many/which delays were requested."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class _StaticClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _service(
    transport: FakeHttpTransport,
    *,
    api_key: str = "test-key",
    cache: CacheProtocol | None = None,
    sleep=None,
) -> DistanceMatrixService:
    return DistanceMatrixService(
        api_key=api_key,
        transport=transport,
        cache=cache,
        sleep=sleep or _FakeSleep(),
    )


LONDON = LatLng(lat=51.5074, lng=-0.1278)
MANCHESTER = LatLng(lat=53.4808, lng=-2.2426)
LEEDS = LatLng(lat=53.8008, lng=-1.5491)
ISLAND = LatLng(lat=59.0, lng=-2.0)


# --- no API key --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda svc: svc.get_distances_one_to_many(LONDON, [LEEDS]),
        lambda svc: svc.get_distances_many_to_one([LONDON], LEEDS),
        lambda svc: svc.get_distances_pairwise([(LONDON, LEEDS)]),
    ],
)
async def test_missing_api_key_raises_immediately_with_no_network_call(call):
    transport = FakeHttpTransport()
    svc = _service(transport, api_key="")

    with pytest.raises(DistanceServiceConfigError):
        await call(svc)

    assert transport.calls == []


async def test_missing_api_key_is_whitespace_only_also_rejected():
    transport = FakeHttpTransport()
    svc = _service(transport, api_key="   ")

    with pytest.raises(DistanceServiceConfigError):
        await svc.get_distances_one_to_many(LONDON, [LEEDS])

    assert transport.calls == []


# --- per-element degradation, using the hand-built fixture ------------------------------
#
# The fixture is a full 2x2 grid (two origins x two destinations), which is a shape none of
# the public batching methods ever sends in one request (they only ever shape 1xN or Nx1 —
# see `design.md`'s batching strategy). It exists to exercise `_parse_grid` — the response
# interpreter every chunked call goes through — directly against a response shaped exactly
# like Google's documented schema, independent of which public method built the request.


def test_fixture_grid_degrades_per_element_never_raises_for_the_batch():
    origins = [LONDON, MANCHESTER]
    destinations = [LEEDS, ISLAND]

    grid = _parse_grid(GRID_2X2, origins, destinations, "driving")

    # London->Leeds: OK.
    assert grid[0][0].status == "ok"
    assert grid[0][0].duration_s == 12000
    assert grid[0][0].distance_m == 315000
    # London->Island: ZERO_RESULTS — a real "no route", not a failure, and never a duration.
    assert grid[0][1].status == "zero_results"
    assert grid[0][1].duration_s is None
    assert grid[0][1].distance_m is None
    # Manchester->Leeds: OK.
    assert grid[1][0].status == "ok"
    assert grid[1][0].duration_s == 3600
    # Manchester->Island: NOT_FOUND — one bad element, and parsing the rest didn't raise.
    assert grid[1][1].status == "not_found"
    assert grid[1][1].duration_s is None


async def test_fixture_grid_reachable_through_a_real_one_to_many_call():
    """Same fixture, this time exercised through the public API end-to-end (single origin,
    both destinations — a shape `get_distances_one_to_many` really does send)."""
    row = {"status": "OK", "rows": [GRID_2X2["rows"][0]]}  # London's row only
    destinations = [LEEDS, ISLAND]
    transport = FakeHttpTransport(
        responses={
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], destinations)): [
                (200, row)
            ]
        }
    )
    svc = _service(transport)

    results = await svc.get_distances_one_to_many(LONDON, destinations)

    assert results[0].status == "ok"
    assert results[0].duration_s == 12000
    assert results[1].status == "zero_results"


async def test_element_status_ok_with_missing_values_degrades_to_not_found():
    origins, destinations = [LONDON], [LEEDS]
    malformed = {
        "status": "OK",
        "rows": [{"elements": [{"status": "OK"}]}],  # no duration/distance
    }
    transport = FakeHttpTransport(
        responses={
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params(origins, destinations)): [
                (200, malformed)
            ]
        }
    )
    svc = _service(transport)

    result = await svc.get_distances_one_to_many(LONDON, destinations)
    assert result[0].status == "not_found"


# --- batching math: grid splits -----------------------------------------------------------


async def test_one_to_many_chunks_destinations_at_the_cap():
    destinations = [LatLng(lat=50.0 + i * 0.01, lng=0.0) for i in range(MAX_DESTINATIONS_PER_REQUEST + 5)]
    chunk1 = destinations[:MAX_DESTINATIONS_PER_REQUEST]
    chunk2 = destinations[MAX_DESTINATIONS_PER_REQUEST:]

    transport = FakeHttpTransport(
        responses={
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], chunk1)): [
                (200, _ok_body([LONDON], chunk1))
            ],
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], chunk2)): [
                (200, _ok_body([LONDON], chunk2))
            ],
        }
    )
    svc = _service(transport)

    results = await svc.get_distances_one_to_many(LONDON, destinations)

    assert len(results) == len(destinations)
    assert all(r.status == "ok" for r in results)
    assert len(transport.calls) == 2, "30 destinations at a cap of 25 must be exactly 2 requests"
    # Chunk boundaries are deterministic (input order), not arbitrary.
    assert len(transport.calls[0][1]["destinations"].split("|")) == MAX_DESTINATIONS_PER_REQUEST
    assert len(transport.calls[1][1]["destinations"].split("|")) == 5


async def test_many_to_one_chunks_origins_at_the_cap():
    origins = [LatLng(lat=50.0 + i * 0.01, lng=0.0) for i in range(MAX_ORIGINS_PER_REQUEST + 3)]
    chunk1 = origins[:MAX_ORIGINS_PER_REQUEST]
    chunk2 = origins[MAX_ORIGINS_PER_REQUEST:]

    transport = FakeHttpTransport(
        responses={
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params(chunk1, [LEEDS])): [
                (200, _ok_body(chunk1, [LEEDS]))
            ],
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params(chunk2, [LEEDS])): [
                (200, _ok_body(chunk2, [LEEDS]))
            ],
        }
    )
    svc = _service(transport)

    results = await svc.get_distances_many_to_one(origins, LEEDS)

    assert len(results) == len(origins)
    assert all(r.status == "ok" for r in results)
    assert len(transport.calls) == 2, "28 origins at a cap of 25 must be exactly 2 requests"


async def test_single_call_covers_a_whole_trip_of_homes_to_one_suggestion():
    """`design.md`'s headline common case: six families, one new suggestion, one call."""
    origins = [LatLng(lat=50.0 + i, lng=0.0) for i in range(6)]
    transport = FakeHttpTransport(
        responses={
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params(origins, [LEEDS])): [
                (200, _ok_body(origins, [LEEDS]))
            ]
        }
    )
    svc = _service(transport)

    results = await svc.get_distances_many_to_one(origins, LEEDS)

    assert len(results) == 6
    assert len(transport.calls) == 1


async def test_pairwise_never_builds_a_dense_grid_for_unrelated_legs():
    """Three itinerary legs with three distinct origins must cost exactly 3 elements across 3
    requests, never a 3x3 = 9-element grid."""
    a, b, c, d = LONDON, MANCHESTER, LEEDS, ISLAND
    pairs = [(a, b), (b, c), (c, d)]
    transport = FakeHttpTransport(
        responses={
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([a], [b])): [(200, _ok_body([a], [b]))],
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([b], [c])): [(200, _ok_body([b], [c]))],
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([c], [d])): [(200, _ok_body([c], [d]))],
        }
    )
    svc = _service(transport)

    results = await svc.get_distances_pairwise(pairs)

    assert len(results) == 3
    assert all(r.status == "ok" for r in results)
    assert len(transport.calls) == 3
    total_elements = sum(len(url_params[1]["destinations"].split("|")) for url_params in transport.calls)
    assert total_elements == 3, "must not have paid for the unrelated 3x3 grid"


async def test_pairwise_groups_legs_sharing_an_origin_into_one_request():
    origin = LONDON
    pairs = [(origin, MANCHESTER), (origin, LEEDS)]
    transport = FakeHttpTransport(
        responses={
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([origin], [MANCHESTER, LEEDS])): [
                (200, _ok_body([origin], [MANCHESTER, LEEDS]))
            ]
        }
    )
    svc = _service(transport)

    results = await svc.get_distances_pairwise(pairs)

    assert len(results) == 2
    assert len(transport.calls) == 1, "shared origin must be batched into one request"


async def test_pairwise_duplicate_pair_resolved_without_a_second_call():
    pairs = [(LONDON, LEEDS), (LONDON, LEEDS)]
    transport = FakeHttpTransport(
        responses={
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], [LEEDS])): [
                (200, _ok_body([LONDON], [LEEDS]))
            ]
        }
    )
    svc = _service(transport)

    results = await svc.get_distances_pairwise(pairs)

    assert len(results) == 2
    assert results[0] == results[1]
    assert len(transport.calls) == 1


# --- cache hit/miss ------------------------------------------------------------------------


async def test_identical_lookup_across_two_batches_never_re_hits_google():
    clock = _StaticClock(0.0)
    cache = InMemoryTtlCache(clock=clock)
    transport = FakeHttpTransport(
        responses={
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], [LEEDS])): [
                (200, _ok_body([LONDON], [LEEDS]))
            ]
        }
    )
    svc = _service(transport, cache=cache)

    first = await svc.get_distances_one_to_many(LONDON, [LEEDS])
    second = await svc.get_distances_one_to_many(LONDON, [LEEDS])

    assert first[0].status == "ok"
    assert second[0] == first[0]
    assert len(transport.calls) == 1, "second identical lookup must be served from cache"


async def test_cache_expiry_after_ttl_causes_a_fresh_call():
    clock = _StaticClock(0.0)
    cache = InMemoryTtlCache(clock=clock)
    transport = FakeHttpTransport(
        responses={
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], [LEEDS])): [
                (200, _ok_body([LONDON], [LEEDS])),
                (200, _ok_body([LONDON], [LEEDS])),
            ]
        }
    )
    svc = _service(transport, cache=cache)

    await svc.get_distances_one_to_many(LONDON, [LEEDS])
    clock.now += DEFAULT_CACHE_TTL_SECONDS + 1
    await svc.get_distances_one_to_many(LONDON, [LEEDS])

    assert len(transport.calls) == 2


async def test_cache_key_is_stable_for_the_same_rounded_point_and_mode():
    a = LatLng(lat=51.50740001, lng=-0.12780001)
    b = LatLng(lat=51.5074, lng=-0.1278)
    assert cache_key(a, LEEDS, "driving") == cache_key(b, LEEDS, "driving")
    assert cache_key(a, LEEDS, "driving") != cache_key(a, LEEDS, "walking")


async def test_cache_protocol_can_be_swapped_for_a_custom_implementation():
    """The M3 agent wires a DB-backed cache; this proves the protocol boundary is real by
    using a trivial dict-backed one instead of `InMemoryTtlCache`."""

    class DictCache:
        def __init__(self) -> None:
            self.store: dict[str, ElementResult] = {}

        async def get(self, key: str) -> ElementResult | None:
            return self.store.get(key)

        async def set(self, key: str, value: ElementResult, *, ttl_seconds: float) -> None:
            self.store[key] = value

    cache = DictCache()
    transport = FakeHttpTransport(
        responses={
            FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], [LEEDS])): [
                (200, _ok_body([LONDON], [LEEDS]))
            ]
        }
    )
    svc = _service(transport, cache=cache)

    await svc.get_distances_one_to_many(LONDON, [LEEDS])
    await svc.get_distances_one_to_many(LONDON, [LEEDS])

    assert len(transport.calls) == 1
    assert len(cache.store) == 1


# --- retry-once behaviour ------------------------------------------------------------------


async def test_5xx_is_retried_once_then_succeeds():
    key = FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], [LEEDS]))
    transport = FakeHttpTransport(
        responses={key: [(503, None), (200, _ok_body([LONDON], [LEEDS]))]}
    )
    sleep = _FakeSleep()
    svc = _service(transport, sleep=sleep)

    results = await svc.get_distances_one_to_many(LONDON, [LEEDS])

    assert results[0].status == "ok"
    assert len(transport.calls) == 2
    assert sleep.calls == [RETRY_BACKOFF_SECONDS], "exactly one deterministic backoff, no jitter"


async def test_5xx_persists_past_the_retry_and_raises_typed_error():
    key = FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], [LEEDS]))
    transport = FakeHttpTransport(responses={key: [(500, None), (500, None)]})
    sleep = _FakeSleep()
    svc = _service(transport, sleep=sleep)

    with pytest.raises(DistanceServiceTransportError):
        await svc.get_distances_one_to_many(LONDON, [LEEDS])

    assert len(transport.calls) == 2
    assert sleep.calls == [RETRY_BACKOFF_SECONDS]


async def test_transport_exception_is_retried_once_then_succeeds():
    key = FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], [LEEDS]))
    transport = FakeHttpTransport(
        responses={key: [(200, _ok_body([LONDON], [LEEDS]))]},
        raises_for={key: [TimeoutError("simulated timeout")]},
    )
    sleep = _FakeSleep()
    svc = _service(transport, sleep=sleep)

    results = await svc.get_distances_one_to_many(LONDON, [LEEDS])

    assert results[0].status == "ok"
    assert sleep.calls == [RETRY_BACKOFF_SECONDS]


async def test_transport_exception_persists_past_the_retry_and_raises_typed_error():
    key = FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], [LEEDS]))
    transport = FakeHttpTransport(
        raises_for={key: [TimeoutError("first"), TimeoutError("second")]},
    )
    sleep = _FakeSleep()
    svc = _service(transport, sleep=sleep)

    with pytest.raises(DistanceServiceTransportError):
        await svc.get_distances_one_to_many(LONDON, [LEEDS])

    assert sleep.calls == [RETRY_BACKOFF_SECONDS]


async def test_a_4xx_is_not_retried():
    key = FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], [LEEDS]))
    transport = FakeHttpTransport(responses={key: [(400, {"status": "INVALID_REQUEST"})]})
    sleep = _FakeSleep()
    svc = _service(transport, sleep=sleep)

    with pytest.raises(DistanceServiceTransportError):
        await svc.get_distances_one_to_many(LONDON, [LEEDS])

    assert len(transport.calls) == 1, "a hard 4xx must not be retried"
    assert sleep.calls == []


# --- quota / auth (whole-request, never per-element) --------------------------------------


@pytest.mark.parametrize("google_status", ["REQUEST_DENIED", "INVALID_REQUEST"])
async def test_auth_failure_raises_typed_error_without_retry(google_status):
    key = FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], [LEEDS]))
    transport = FakeHttpTransport(responses={key: [(200, {"status": google_status})]})
    sleep = _FakeSleep()
    svc = _service(transport, sleep=sleep)

    with pytest.raises(DistanceServiceAuthError):
        await svc.get_distances_one_to_many(LONDON, [LEEDS])

    assert len(transport.calls) == 1
    assert sleep.calls == []


@pytest.mark.parametrize("google_status", ["OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT"])
async def test_quota_failure_raises_typed_error_without_retry(google_status):
    key = FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], [LEEDS]))
    transport = FakeHttpTransport(responses={key: [(200, {"status": google_status})]})
    sleep = _FakeSleep()
    svc = _service(transport, sleep=sleep)

    with pytest.raises(DistanceServiceQuotaError):
        await svc.get_distances_one_to_many(LONDON, [LEEDS])

    assert len(transport.calls) == 1
    assert sleep.calls == []


# --- FakeHttpTransport records exactly the requests expected ------------------------------


async def test_fake_transport_records_exact_url_and_params():
    key = FakeHttpTransport()._key(DISTANCE_MATRIX_URL, _params([LONDON], [LEEDS]))
    transport = FakeHttpTransport(responses={key: [(200, _ok_body([LONDON], [LEEDS]))]})
    svc = _service(transport)

    await svc.get_distances_one_to_many(LONDON, [LEEDS])

    assert transport.calls == [(DISTANCE_MATRIX_URL, _params([LONDON], [LEEDS]))]


async def test_fake_transport_raises_on_unconfigured_request():
    """An unconfigured fake call is a transport-level failure like any other — it gets the
    same one deterministic retry, then surfaces as the module's own typed error rather than
    leaking `FakeHttpTransport`'s internal `AssertionError` to the caller."""
    transport = FakeHttpTransport()
    sleep = _FakeSleep()
    svc = _service(transport, sleep=sleep)

    with pytest.raises(DistanceServiceTransportError):
        await svc.get_distances_one_to_many(LONDON, [LEEDS])

    assert len(transport.calls) == 2
    assert sleep.calls == [RETRY_BACKOFF_SECONDS]


# --- empty input shortcuts (no network call for nothing to ask) ---------------------------


async def test_empty_destinations_short_circuits_with_no_call():
    transport = FakeHttpTransport()
    svc = _service(transport)

    result = await svc.get_distances_one_to_many(LONDON, [])

    assert result == []
    assert transport.calls == []


async def test_empty_origins_short_circuits_with_no_call():
    transport = FakeHttpTransport()
    svc = _service(transport)

    result = await svc.get_distances_many_to_one([], LEEDS)

    assert result == []
    assert transport.calls == []


async def test_empty_pairs_short_circuits_with_no_call():
    transport = FakeHttpTransport()
    svc = _service(transport)

    result = await svc.get_distances_pairwise([])

    assert result == []
    assert transport.calls == []
