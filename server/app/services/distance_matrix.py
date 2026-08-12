"""Google Distance Matrix client — driving time/distance between (origin, destination) pairs.

**This is the only module in the server that talks to Distance Matrix, and it is deliberately
not the one the read path imports.** `plan/features/distances/design.md`'s HARD INVARIANT —
"a request serving a page, a list, a card, or a panel never calls Distance Matrix" — is
enforced here structurally rather than by discipline:

* `app/services/distance_matrix.py` (this file) calls Google. Route-free and DB-free: it never
  imports a model, never opens a session, and never touches `distance_cache`.
* `app/services/distances.py` is the **read** half. It imports neither this module nor any
  other Google client, and `tests/test_service_distances_read.py` asserts that by walking its
  import graph — so a future edit that reaches for a live value from a render path fails a
  test rather than quietly spending the API budget.
* `app/services/distance_tasks.py` is the **write** half, and the only importer of this module.
  It runs from background tasks alone.

The file was named `distances.py` while it was a pre-build (`plan/features/distances/tasks.md`,
M3) and was renamed when the feature landed, so the read module could take that name and the
separation above could be a fact about the import graph.

**HARD INVARIANT — never call Google in a render path** (`CLAUDE.md`,
`plan/architecture.md`, restated in `plan/features/distances/design.md`). This module makes
that structurally easy to honour: nothing in it is imported by a router today, and the class
itself performs no caching-forever or "is this pair worth asking about" policy — it just
answers "what does Google say for these points," cached for a bounded TTL to avoid duplicate
calls within one batch of work. The M3 agent's write-half (`recompute`, `queue_for_*`) is what
turns "asked once" into "cached forever" and "never called outside a background task" into an
enforced invariant with its own render-path test — see the NOTE at the bottom of this
docstring for the one place this module's behaviour and the design doc's semantics diverge.

Contract, per `plan/features/distances/design.md` > "The batching strategy" and > "Background
task":

* Google's Distance Matrix API bills per origin×destination *element*, and caps a single
  request to 25 origins, 25 destinations, and 100 elements. This module never exceeds those
  caps and shapes calls to minimise element count for the two named common cases: one home to
  many suggestions (`get_distances_one_to_many`), many homes to one suggestion
  (`get_distances_many_to_one`), plus a third shape the design doc's future itinerary-legs use
  needs (`get_distances_pairwise`) — arbitrary independent (origin, destination) pairs, batched
  by shared origin only where pairs genuinely share one, never forced into a dense grid (a
  dense grid over N unrelated legs would multiply element count by N instead of using exactly
  N elements).
* Every element result is typed and returned individually — `OK`, `ZERO_RESULTS`, `NOT_FOUND`
  all degrade to an :class:`ElementResult` with a `status`; **a single bad element never raises
  for the whole batch**. What each status *means* for caching/retry policy (e.g. `ZERO_RESULTS`
  cached forever as `no_route`, `NOT_FOUND` retried once, per `design.md`) is a decision this
  module hands back raw, for the DB-backed write-half to apply — this module has no `attempts`
  column to increment.
* Quota/auth failures (`REQUEST_DENIED`, `INVALID_REQUEST`, `OVER_QUERY_LIMIT`,
  `OVER_DAILY_LIMIT`) are whole-request failures, not per-element ones, and raise a typed
  exception (:class:`DistanceServiceAuthError` / :class:`DistanceServiceQuotaError`) so the
  caller can degrade to estimates and show the admin banner `design.md` describes, rather than
  writing 25 phantom `ok` rows for a request Google never actually served.
* A missing API key raises :class:`DistanceServiceConfigError` immediately, before any network
  attempt — matching `app.services.google.Geocoder`'s "no key, no five-second wait" behaviour,
  just as an exception instead of a status value, per this module's brief.
* Transient failures — a transport error/timeout, or an HTTP 5xx — are retried exactly once,
  after a fixed (non-jittered) backoff so test behaviour is deterministic, then raise
  :class:`DistanceServiceTransportError`.
* A `CacheProtocol` (get/set-with-TTL) sits in front of every Google call, keyed on
  (origin, destination, mode) rounded to ~11cm precision, so identical lookups inside — or
  across — a batch never re-hit Google. The default implementation
  (:class:`InMemoryTtlCache`) is a small hand-rolled LRU+TTL, same shape as
  `link_preview.py`'s `_TtlLru`. The protocol is intentionally the only thing the M3 agent has
  to implement to back this with `distance_cache`/`route_cache` — see the NOTE below.

Networking is behind an injectable :class:`HttpTransportProtocol`, with
:class:`FakeHttpTransport` alongside, so tests exercise batching, retries, and error mapping
without ever touching the network (`CLAUDE.md`: "never hit Google/NOAA from the test suite").

.. note::
   **Where this module's cache and `design.md`'s "cache forever" part ways.** `design.md`
   specifies `distance_cache` as a forever-cache with an explicit `status` column so a
   `no_route` answer is a *permanent*, structurally different fact from "not computed yet" —
   deliberately not modellable as "a TTL that happens to be very large," because a forever-fact
   must never silently expire and re-query, which is exactly what a TTL cache does by
   construction. This module's `CacheProtocol` is a plain TTL cache (default
   :data:`DEFAULT_CACHE_TTL_SECONDS`, chosen only to keep one logical batch of work — e.g. all
   25 chunks of a big home-change recompute — from re-asking Google for a pair two chunks
   already resolved) and is *not* meant to be the forever-cache itself. The M3 agent's
   DB-backed `CacheProtocol` implementation should therefore treat every `get()` against
   `distance_cache` rows already `status = ok` or `status = no_route` as an unconditional hit
   (ignore the `ttl_seconds` this module passes to `set()`, or pass through a value larger than
   any plausible run), and reserve real expiry for whatever short-lived layer, if any, sits in
   front of `pending`/`failed` rows. This divergence is flagged here rather than silently
   assumed because "TTL cache in front of a forever-cache" is exactly the kind of decision
   `CLAUDE.md`'s docs-first rule asks to be written down.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, Protocol

from pydantic import BaseModel

from app.core.config import settings

# --- constants -------------------------------------------------------------------------------

DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"

#: `design.md`'s batching strategy: "Distance Matrix caps destinations per request (25 at time
#: of writing) and total elements per request (100)". Origins share the same 25 cap.
#:
#: Read from `core/config.py` rather than hard-coded here (`distances/tasks.md` Phase 2: "keep
#: the limits as named settings in `core/config.py`, not literals scattered through the
#: service"), so a change at Google's end is one edit in one place. Bound at import so the
#: values a test asserts against are the values a request uses.
MAX_ORIGINS_PER_REQUEST = settings.distance_max_origins
MAX_DESTINATIONS_PER_REQUEST = settings.distance_max_destinations
MAX_ELEMENTS_PER_REQUEST = settings.distance_max_elements

REQUEST_TIMEOUT_SECONDS = 8.0

#: "transient 5xx retried once with jitter-free short backoff (keep it deterministic for
#: tests)" — fixed, no jitter, applied identically to a transport-level exception (timeout,
#: connection error) since both are the same "ask Google once more, briefly" case.
RETRY_BACKOFF_SECONDS = 0.25

#: Coordinate rounding for cache keys: 6 decimal places is ~0.11m at the equator, well under
#: the epsilon (`distances/design.md`: 25m) that even triggers a recompute in the first place,
#: so two lookups for "the same point" as far as this feature is concerned always collide.
COORD_ROUND_DP = 6

#: Not "cache forever" — see the module docstring NOTE. Long enough that one logical batch of
#: chunked work (e.g. a big home-change recompute) shares hits across its own chunks; short
#: enough that a long-lived process doesn't quietly serve a very stale in-memory answer once a
#: real forever-cache (`distance_cache`) is what should be answering instead.
DEFAULT_CACHE_TTL_SECONDS = 3600.0
CACHE_MAX_ENTRIES = 4096

DEFAULT_MODE = "driving"

Sleep = Callable[[float], Awaitable[None]]


# --- errors ------------------------------------------------------------------------------------


class DistanceServiceError(Exception):
    """Base for every typed error this module raises for a whole request.

    Never raised for a single bad element (`ZERO_RESULTS` / `NOT_FOUND`) — those degrade to an
    :class:`ElementResult`, per the module contract. Only raised when Google could not answer
    the request *at all*: no key, rejected key, exhausted quota, or a transport failure that
    outlived its one retry.
    """


class DistanceServiceConfigError(DistanceServiceError):
    """No API key configured. Raised before any network attempt is made."""

    def __init__(self) -> None:
        super().__init__(
            "GOOGLE_MAPS_SERVER_KEY is not configured "
            "(admin console > Google APIs is the source of truth for this key)"
        )


class DistanceServiceAuthError(DistanceServiceError):
    """Google rejected the request or the key: `REQUEST_DENIED` / `INVALID_REQUEST`."""

    def __init__(self, google_status: str) -> None:
        self.google_status = google_status
        super().__init__(f"Distance Matrix request rejected: {google_status}")


class DistanceServiceQuotaError(DistanceServiceError):
    """`OVER_QUERY_LIMIT` / `OVER_DAILY_LIMIT` — the key is fine, the budget is not."""

    def __init__(self, google_status: str) -> None:
        self.google_status = google_status
        super().__init__(f"Distance Matrix quota exhausted: {google_status}")


class DistanceServiceTransportError(DistanceServiceError):
    """A transport error, timeout, HTTP 5xx, or unrecognised top-level status that survived
    the one deterministic retry."""


# --- response shapes -------------------------------------------------------------------------


class LatLng(BaseModel):
    lat: float
    lng: float

    def __hash__(self) -> int:  # pragma: no cover - trivial
        return hash((self.lat, self.lng))


ElementStatus = Literal["ok", "not_found", "zero_results"]


class ElementResult(BaseModel):
    """One (origin, destination) answer. Duration/distance are set only when `status == "ok"`
    — never fabricated, per `design.md`'s honesty rule that an estimate (which this module does
    not compute; that is SQL-side haversine, per `design.md`) and a real answer must never be
    confused."""

    origin: LatLng
    destination: LatLng
    mode: str = DEFAULT_MODE
    status: ElementStatus
    duration_s: int | None = None
    distance_m: int | None = None


# --- HTTP transport ------------------------------------------------------------------------


class HttpTransportProtocol(Protocol):
    async def get_json(
        self, url: str, params: dict[str, str]
    ) -> tuple[int, object]:  # pragma: no cover - protocol
        """GET `url` with `params`. Returns `(status_code, parsed_json_body)`.

        Raises only for a transport-level failure (timeout, connection error, DNS failure) —
        never for a non-2xx HTTP status, which the caller needs the status code to classify
        (retryable 5xx vs. a hard failure).
        """
        ...


class HttpxTransport:
    async def get_json(self, url: str, params: dict[str, str]) -> tuple[int, object]:
        import httpx

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
        try:
            body = response.json()
        except ValueError:
            body = None
        return response.status_code, body


@dataclass
class FakeHttpTransport:
    """Test double: `(url, sorted params items)` -> a queue of `(status_code, body)` responses
    (or a configured exception), consumed one per call so a test can script "5xx then OK" for
    the retry path. Records every call so a test can assert exactly which requests were made
    and how many chunks a batch turned into."""

    responses: dict[str, list[tuple[int, object]]] = field(default_factory=dict)
    raises_for: dict[str, list[Exception | None]] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def _key(self, url: str, params: dict[str, str]) -> str:
        return url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))

    async def get_json(self, url: str, params: dict[str, str]) -> tuple[int, object]:
        self.calls.append((url, dict(params)))
        key = self._key(url, params)

        raise_queue = self.raises_for.get(key)
        if raise_queue:
            exc = raise_queue.pop(0)
            if exc is not None:
                raise exc

        queue = self.responses.get(key)
        if not queue:
            raise AssertionError(f"FakeHttpTransport: no response configured for {key!r}")
        return queue.pop(0) if len(queue) > 1 else queue[0]


# --- cache ---------------------------------------------------------------------------------


class CacheProtocol(Protocol):
    async def get(self, key: str) -> ElementResult | None:  # pragma: no cover - protocol
        """`None` means "no value" — expired entries must behave identically to absent ones."""
        ...

    async def set(
        self, key: str, value: ElementResult, *, ttl_seconds: float
    ) -> None:  # pragma: no cover - protocol
        ...


def cache_key(origin: LatLng, destination: LatLng, mode: str) -> str:
    """The identity a (origin, destination, mode) lookup collides on — exported so the M3
    agent's DB-backed cache can compute the same key a `distance_cache` row would be looked up
    by, without duplicating the rounding rule."""
    return (
        f"{round(origin.lat, COORD_ROUND_DP)},{round(origin.lng, COORD_ROUND_DP)}"
        f"->{round(destination.lat, COORD_ROUND_DP)},{round(destination.lng, COORD_ROUND_DP)}"
        f"@{mode}"
    )


@dataclass
class _CacheEntry:
    value: ElementResult
    expires_at: float


class InMemoryTtlCache:
    """Hand-rolled LRU+TTL, same shape as `link_preview.py`'s `_TtlLru` — see the module
    docstring NOTE for why this is *not* the forever-cache `distance_cache` needs to be."""

    def __init__(
        self,
        max_entries: int = CACHE_MAX_ENTRIES,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._max_entries = max_entries
        self._clock = clock or time.monotonic
        self._data: dict[str, _CacheEntry] = {}
        self._order: list[str] = []

    async def get(self, key: str) -> ElementResult | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._evict(key)
            return None
        if key in self._order:
            self._order.remove(key)
        self._order.append(key)
        return entry.value

    async def set(self, key: str, value: ElementResult, *, ttl_seconds: float) -> None:
        self._data[key] = _CacheEntry(value=value, expires_at=self._clock() + ttl_seconds)
        if key in self._order:
            self._order.remove(key)
        self._order.append(key)
        while len(self._order) > self._max_entries:
            self._evict(self._order[0])

    def _evict(self, key: str) -> None:
        self._data.pop(key, None)
        if key in self._order:
            self._order.remove(key)

    def __len__(self) -> int:
        return len(self._data)


# --- request building / response parsing --------------------------------------------------


def _build_params(
    origins: list[LatLng], destinations: list[LatLng], mode: str, api_key: str
) -> dict[str, str]:
    return {
        "origins": "|".join(f"{o.lat},{o.lng}" for o in origins),
        "destinations": "|".join(f"{d.lat},{d.lng}" for d in destinations),
        "mode": mode,
        "key": api_key,
    }


#: Whole-request statuses that mean "the key/request itself is the problem" — never "this
#: particular pair has no route" (that is `ZERO_RESULTS`, a per-*element* status found inside
#: `rows[].elements[]`, handled separately in `_element_from_json`).
_AUTH_STATUSES = {"REQUEST_DENIED", "INVALID_REQUEST"}
_QUOTA_STATUSES = {"OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT"}


def _element_from_json(
    raw: dict, origin: LatLng, destination: LatLng, mode: str
) -> ElementResult:
    status = raw.get("status")
    if status == "OK":
        duration = (raw.get("duration") or {}).get("value")
        distance = (raw.get("distance") or {}).get("value")
        if duration is not None and distance is not None:
            return ElementResult(
                origin=origin,
                destination=destination,
                mode=mode,
                status="ok",
                duration_s=int(duration),
                distance_m=int(distance),
            )
        # `OK` with a missing value is not a documented shape; treat it as the honest
        # equivalent of NOT_FOUND rather than raising on a malformed element.
        return ElementResult(origin=origin, destination=destination, mode=mode, status="not_found")
    if status == "ZERO_RESULTS":
        return ElementResult(origin=origin, destination=destination, mode=mode, status="zero_results")
    # NOT_FOUND, or any unrecognised element status — a single odd element must never raise
    # for the whole batch (module contract, and `design.md`'s "each element is mapped
    # independently").
    return ElementResult(origin=origin, destination=destination, mode=mode, status="not_found")


def _parse_grid(
    body: object, origins: list[LatLng], destinations: list[LatLng], mode: str
) -> list[list[ElementResult]]:
    if not isinstance(body, dict):
        raise DistanceServiceTransportError("malformed response body (not a JSON object)")

    top_status = body.get("status")
    if top_status in _AUTH_STATUSES:
        raise DistanceServiceAuthError(str(top_status))
    if top_status in _QUOTA_STATUSES:
        raise DistanceServiceQuotaError(str(top_status))
    if top_status != "OK":
        raise DistanceServiceTransportError(f"unexpected top-level status: {top_status!r}")

    rows = body.get("rows") or []
    grid: list[list[ElementResult]] = []
    for oi, origin in enumerate(origins):
        row = rows[oi] if oi < len(rows) and isinstance(rows[oi], dict) else {}
        elements = row.get("elements") or []
        grid.append(
            [
                _element_from_json(
                    elements[di] if di < len(elements) and isinstance(elements[di], dict) else {},
                    origin,
                    destination,
                    mode,
                )
                for di, destination in enumerate(destinations)
            ]
        )
    return grid


def _chunks(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# --- the service ---------------------------------------------------------------------------


class DistanceMatrixServiceProtocol(Protocol):
    async def get_distances_one_to_many(
        self, origin: LatLng, destinations: list[LatLng], *, mode: str = DEFAULT_MODE
    ) -> list[ElementResult]:  # pragma: no cover - protocol
        ...

    async def get_distances_many_to_one(
        self, origins: list[LatLng], destination: LatLng, *, mode: str = DEFAULT_MODE
    ) -> list[ElementResult]:  # pragma: no cover - protocol
        ...

    async def get_distances_pairwise(
        self, pairs: list[tuple[LatLng, LatLng]], *, mode: str = DEFAULT_MODE
    ) -> list[ElementResult]:  # pragma: no cover - protocol
        ...


class DistanceMatrixService:
    """The real caller. `transport` and `cache` default to network-touching / in-memory
    implementations; tests inject fakes for both, per `CLAUDE.md`'s "never hit Google from the
    test suite"."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: HttpTransportProtocol | None = None,
        cache: CacheProtocol | None = None,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        sleep: Sleep | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.google_maps_server_key
        # NOTE: deliberately `is None`, not `... or Default()` — `InMemoryTtlCache` (and any
        # sane cache implementation) defines `__len__`, so an empty-but-valid injected cache
        # is falsy and `or` would silently discard it in favour of a fresh default with the
        # wrong clock. Cost a debugging session in this module's own test suite; worth a NOTE.
        self._transport = transport if transport is not None else HttpxTransport()
        self._cache = cache if cache is not None else InMemoryTtlCache()
        self._cache_ttl = cache_ttl_seconds
        self._sleep = sleep if sleep is not None else asyncio.sleep

    # -- public batching shapes -----------------------------------------------------------

    async def get_distances_one_to_many(
        self, origin: LatLng, destinations: list[LatLng], *, mode: str = DEFAULT_MODE
    ) -> list[ElementResult]:
        """`design.md`'s home-change shape: one family's home against every suggestion,
        chunked to `MAX_DESTINATIONS_PER_REQUEST` (element count == destination count here, so
        that is also the binding cap — well under `MAX_ELEMENTS_PER_REQUEST`)."""
        self._require_api_key()
        if not destinations:
            return []
        return await self._fetch_one_origin(origin, destinations, mode)

    async def get_distances_many_to_one(
        self, origins: list[LatLng], destination: LatLng, *, mode: str = DEFAULT_MODE
    ) -> list[ElementResult]:
        """`design.md`'s suggestion-create/move shape: every family's home against the one new
        or moved suggestion, chunked to `MAX_ORIGINS_PER_REQUEST`."""
        self._require_api_key()
        if not origins:
            return []
        return await self._fetch_one_destination(origins, destination, mode)

    async def get_distances_pairwise(
        self, pairs: list[tuple[LatLng, LatLng]], *, mode: str = DEFAULT_MODE
    ) -> list[ElementResult]:
        """Arbitrary independent (origin, destination) pairs — the itinerary-legs shape.
        Never batched into a dense grid (an N-leg itinerary would cost N² elements for N
        needed answers); pairs are deduplicated, then grouped by *exact* shared origin so any
        real sharing (two legs departing the same place) still saves a round trip, and each
        group is chunked like `get_distances_one_to_many`. A chain of legs with no shared
        origin costs exactly one element per leg, which is the minimum possible."""
        self._require_api_key()
        if not pairs:
            return []

        results: list[ElementResult | None] = [None] * len(pairs)
        keys = [cache_key(o, d, mode) for o, d in pairs]
        resolved: dict[str, ElementResult] = {}

        missing: list[int] = []
        for i, key in enumerate(keys):
            if key in resolved:
                results[i] = resolved[key]
                continue
            cached = await self._cache.get(key)
            if cached is not None:
                results[i] = cached
                resolved[key] = cached
            else:
                missing.append(i)

        groups: dict[tuple[float, float], list[int]] = {}
        for i in missing:
            origin = pairs[i][0]
            groups.setdefault((origin.lat, origin.lng), []).append(i)

        for idxs in groups.values():
            origin = pairs[idxs[0]][0]
            # Dedupe destinations within this origin's group, preserving first-seen order so
            # chunk boundaries stay deterministic across retries.
            dest_key_order: list[str] = []
            dest_by_key: dict[str, LatLng] = {}
            idxs_by_dest_key: dict[str, list[int]] = {}
            for i in idxs:
                destination = pairs[i][1]
                dkey = cache_key(origin, destination, mode)
                if dkey not in dest_by_key:
                    dest_key_order.append(dkey)
                    dest_by_key[dkey] = destination
                idxs_by_dest_key.setdefault(dkey, []).append(i)

            unique_destinations = [dest_by_key[k] for k in dest_key_order]
            elements = await self._fetch_one_origin(
                origin, unique_destinations, mode, write_cache=False
            )
            for dkey, element in zip(dest_key_order, elements):
                await self._cache.set(dkey, element, ttl_seconds=self._cache_ttl)
                resolved[dkey] = element
                for i in idxs_by_dest_key[dkey]:
                    results[i] = element

        assert all(r is not None for r in results)  # every pair was either cached or fetched
        return results  # type: ignore[return-value]

    # -- shared engine ----------------------------------------------------------------------

    async def _fetch_one_origin(
        self,
        origin: LatLng,
        destinations: list[LatLng],
        mode: str,
        *,
        write_cache: bool = True,
    ) -> list[ElementResult]:
        results: list[ElementResult | None] = [None] * len(destinations)
        keys = [cache_key(origin, d, mode) for d in destinations]
        to_fetch: list[int] = []
        for i, key in enumerate(keys):
            cached = await self._cache.get(key)
            if cached is None:
                to_fetch.append(i)
            else:
                results[i] = cached

        chunk_size = min(MAX_DESTINATIONS_PER_REQUEST, MAX_ELEMENTS_PER_REQUEST)
        for chunk in _chunks(to_fetch, chunk_size):
            chunk_destinations = [destinations[i] for i in chunk]
            body = await self._request_with_retry(
                _build_params([origin], chunk_destinations, mode, self._api_key)
            )
            grid = _parse_grid(body, [origin], chunk_destinations, mode)
            for local_i, global_i in enumerate(chunk):
                element = grid[0][local_i]
                results[global_i] = element
                if write_cache:
                    await self._cache.set(keys[global_i], element, ttl_seconds=self._cache_ttl)

        assert all(r is not None for r in results)
        return results  # type: ignore[return-value]

    async def _fetch_one_destination(
        self, origins: list[LatLng], destination: LatLng, mode: str
    ) -> list[ElementResult]:
        results: list[ElementResult | None] = [None] * len(origins)
        keys = [cache_key(o, destination, mode) for o in origins]
        to_fetch: list[int] = []
        for i, key in enumerate(keys):
            cached = await self._cache.get(key)
            if cached is None:
                to_fetch.append(i)
            else:
                results[i] = cached

        chunk_size = min(MAX_ORIGINS_PER_REQUEST, MAX_ELEMENTS_PER_REQUEST)
        for chunk in _chunks(to_fetch, chunk_size):
            chunk_origins = [origins[i] for i in chunk]
            body = await self._request_with_retry(
                _build_params(chunk_origins, [destination], mode, self._api_key)
            )
            grid = _parse_grid(body, chunk_origins, [destination], mode)
            for local_i, global_i in enumerate(chunk):
                element = grid[local_i][0]
                results[global_i] = element
                await self._cache.set(keys[global_i], element, ttl_seconds=self._cache_ttl)

        assert all(r is not None for r in results)
        return results  # type: ignore[return-value]

    async def _request_with_retry(self, params: dict[str, str]) -> object:
        """One attempt, then — for a transport exception or a 5xx only — exactly one more,
        after a fixed, non-jittered backoff. Anything else (a 4xx, a malformed body) fails
        immediately; retrying a request Google has already told us is wrong would not change
        the answer."""
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                status_code, body = await self._transport.get_json(DISTANCE_MATRIX_URL, params)
            except Exception as exc:  # noqa: BLE001 - transport/timeout, classified below
                last_exc = exc
                if attempt == 0:
                    await self._sleep(RETRY_BACKOFF_SECONDS)
                    continue
                raise DistanceServiceTransportError(
                    f"transport error after retry: {exc}"
                ) from exc

            if status_code >= 500:
                if attempt == 0:
                    await self._sleep(RETRY_BACKOFF_SECONDS)
                    continue
                raise DistanceServiceTransportError(f"http_{status_code} after retry")

            if status_code != 200:
                raise DistanceServiceTransportError(f"http_{status_code}")

            return body

        # Unreachable: the loop above always returns or raises within its two iterations.
        raise DistanceServiceTransportError(f"exhausted retries: {last_exc}")  # pragma: no cover

    def _require_api_key(self) -> None:
        if not self._api_key.strip():
            raise DistanceServiceConfigError()


def get_distance_matrix_service() -> DistanceMatrixServiceProtocol:
    """FastAPI dependency, for the M3 route/background-task to depend on. Overridden with a
    fake in tests."""
    return DistanceMatrixService()
