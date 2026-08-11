"""Link preview fetching for `POST /api/v1/link-preview` (`plan/features/map-suggestions`).

**Pre-built ahead of the route** (`plan/features/map-suggestions/tasks.md`, M3): this module
is deliberately route-free. The M3 feature agent wires :func:`get_link_preview_service` into
the endpoint; this file owns only the fetch/parse/cache behaviour so it can be reviewed and
tested in isolation.

Contract, per `plan/features/map-suggestions/design.md` > `POST /api/v1/link-preview`:

* Server-side fetch, http/https only, 4s timeout, 512KB body cap, bounded redirects.
* **SSRF guard**: the URL's host is DNS-resolved and every resolved address is checked against
  private/loopback/link-local/reserved/multicast ranges *before* any request is sent, and the
  same check runs again on every redirect target — a URL that resolves safely but redirects to
  `http://169.254.169.254/` must not be followed.
* OpenGraph tags parsed first, plain `<title>` as a fallback.
* **Airbnb-aware extraction** layered on top, best-effort: `og:title` carries structured facts
  ("Home in Dent · ★4.8 · 5 bedrooms · 7 beds · 4.5 bathrooms"), `<title>` carries the locality
  ("Dent, England, United Kingdom"), and best-effort embedded page JSON may carry fuzzed
  `latitude`/`longitude` and `personCapacity`. Any failure in this layer must degrade silently
  to the plain OG result — it is reading undocumented, redesign-prone page internals.
* In-memory LRU with a short TTL. Nothing is persisted (no DB table, per the design doc's NOTE).
* 204-is-normal: callers treat `None` as "no preview available", not an error.

Networking is behind two small protocols — :class:`DnsResolverProtocol` and
:class:`HttpTransportProtocol` — so tests exercise the SSRF guard, the redirect loop, the
parsers, and the cache without ever touching a socket. `CLAUDE.md`: "never hit Google/NOAA
[or, here, the open internet] from the test suite."
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable, Protocol
from urllib.parse import urljoin, urlsplit

from pydantic import BaseModel

# --- constants -------------------------------------------------------------------------------

#: `design.md`: "a short timeout (target 4 s)".
FETCH_TIMEOUT_SECONDS = 4.0

#: `design.md`: "a size cap (target 512 KB)".
MAX_BODY_BYTES = 512 * 1024

#: `design.md`: "a redirect limit". Kept small — a legitimate OG target does not need a chain.
MAX_REDIRECTS = 5

ALLOWED_SCHEMES = ("http", "https")

#: `design.md`: "held in an in-memory LRU with a short TTL". Five minutes matches the client
#: Places cache TTL target elsewhere in the same feature, for consistency of "how stale can a
#: preview be" across the feature.
CACHE_TTL_SECONDS = 300.0
CACHE_MAX_ENTRIES = 256

USER_AGENT = "KindredLinkPreview/1.0 (+self-hosted trip planner; contact: admin@example.org)"


class SSRFRejected(Exception):
    """Raised internally when a URL (initial or a redirect target) resolves to a disallowed
    address. Never escapes :func:`LinkPreviewService.fetch` — callers only see ``None``."""


# --- response shape ----------------------------------------------------------------------------


class LinkPreview(BaseModel):
    """`design.md`'s `200` response shape, plus the Airbnb-aware optional fields.

    All fields are optional: a plain page may only yield a title, and the Airbnb bonus layer
    (`facts`, `locality`, `lat`, `lng`, `capacity`) is explicitly best-effort.
    """

    title: str | None = None
    description: str | None = None
    image_url: str | None = None
    site_name: str | None = None
    #: e.g. "★4.8 · 5 bedrooms · 7 beds · 4.5 bathrooms" — parsed out of `og:title` when it
    #: carries Airbnb's structured-facts format.
    facts: str | None = None
    #: e.g. "Dent, England, United Kingdom" — from `<title>` when it reads as a locality.
    locality: str | None = None
    lat: float | None = None
    lng: float | None = None
    capacity: int | None = None


# --- DNS resolution / SSRF guard ----------------------------------------------------------------


class DnsResolverProtocol(Protocol):
    async def resolve(self, host: str) -> list[str]:  # pragma: no cover - protocol
        """Return every IP address `host` resolves to, as strings. Raises on lookup failure."""
        ...


class SystemDnsResolver:
    """The real resolver: `socket.getaddrinfo`, both address families."""

    async def resolve(self, host: str) -> list[str]:
        import asyncio

        loop = asyncio.get_event_loop()
        infos = await loop.run_in_executor(
            None, lambda: socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        )
        return sorted({info[4][0] for info in infos})


@dataclass
class FakeDnsResolver:
    """Test double: a fixed hostname -> IP-list map, plus IP literals resolve to themselves.

    No test needs a real DNS lookup — SSRF cases are expressed as "this hostname maps to this
    private address" or as literal IPs in the URL, both of which this fixture covers.
    """

    hosts: dict[str, list[str]] = field(default_factory=dict)

    async def resolve(self, host: str) -> list[str]:
        try:
            ipaddress.ip_address(host)
            return [host]
        except ValueError:
            pass
        if host in self.hosts:
            return self.hosts[host]
        raise OSError(f"FakeDnsResolver: no mapping for {host!r}")


def _is_disallowed_address(address: str) -> bool:
    """True when `address` must never be fetched from: private, loopback, link-local,
    reserved, multicast, or unspecified — the SSRF-relevant `ipaddress` predicates."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True  # not even a valid address; refuse rather than guess
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _check_url_is_safe(url: str, resolver: DnsResolverProtocol) -> None:
    """Scheme + DNS-resolve-then-range-check. Raises :class:`SSRFRejected` on any problem.

    Called once for the initial URL and once per redirect hop — `design.md` is explicit that
    a URL which resolves safely but redirects to a private address must still be refused.
    """
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise SSRFRejected(f"disallowed scheme: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise SSRFRejected("no host in URL")

    try:
        addresses = await resolver.resolve(host)
    except OSError as exc:
        raise SSRFRejected(f"DNS resolution failed for {host!r}") from exc

    if not addresses:
        raise SSRFRejected(f"DNS resolution returned no addresses for {host!r}")
    if any(_is_disallowed_address(addr) for addr in addresses):
        raise SSRFRejected(f"{host!r} resolves to a disallowed address")


# --- HTTP transport ------------------------------------------------------------------------


@dataclass(frozen=True)
class RawResponse:
    """One hop's response: status, a `Location` header for redirects, and a body already
    truncated to :data:`MAX_BODY_BYTES`."""

    status_code: int
    headers: dict[str, str]
    body: bytes
    url: str  # the URL actually requested for this hop

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


class HttpTransportProtocol(Protocol):
    async def get(self, url: str) -> RawResponse:  # pragma: no cover - protocol
        """A single, non-redirect-following GET. Body is capped by the implementation."""
        ...


class HttpxTransport:
    """The real transport: `httpx`, streamed and cut off at :data:`MAX_BODY_BYTES`,
    redirects disabled (the service loop drives redirects itself so each hop passes back
    through the SSRF guard)."""

    async def get(self, url: str) -> RawResponse:
        import httpx

        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            async with client.stream("GET", url) as response:
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= MAX_BODY_BYTES:
                        break
                body = b"".join(chunks)[:MAX_BODY_BYTES]
                return RawResponse(
                    status_code=response.status_code,
                    headers={k.lower(): v for k, v in response.headers.items()},
                    body=body,
                    url=str(response.url),
                )


@dataclass
class FakeHttpTransport:
    """Test double. Maps a URL to a canned :class:`RawResponse`, or raises the configured
    exception (to simulate a timeout / transport error) when the URL matches `raises_for`."""

    responses: dict[str, RawResponse] = field(default_factory=dict)
    raises_for: dict[str, Exception] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    async def get(self, url: str) -> RawResponse:
        self.calls.append(url)
        if url in self.raises_for:
            raise self.raises_for[url]
        if url not in self.responses:
            raise OSError(f"FakeHttpTransport: no response configured for {url!r}")
        return self.responses[url]


# --- HTML / OpenGraph parsing ----------------------------------------------------------------


class _OpenGraphParser(HTMLParser):
    """Collects `<meta property="og:*">` / `<meta name="og:*">` content and `<title>` text.

    A hand-rolled `HTMLParser` subclass rather than a third-party HTML library: OG tags live in
    `<head>`, are well-formed in practice (they exist for link-preview bots), and pulling in a
    parsing dependency for this one job is not worth it.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og: dict[str, str] = {}
        self.title: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            attr_map = {k: (v or "") for k, v in attrs}
            key = attr_map.get("property") or attr_map.get("name") or ""
            if key.startswith("og:") and "content" in attr_map:
                self.og.setdefault(key, attr_map["content"])
        elif tag == "title" and self.title is None:
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title = (self.title or "") + data


def _parse_og(html: str) -> tuple[dict[str, str], str | None]:
    parser = _OpenGraphParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed HTML must never raise past this point
        return parser.og, (parser.title.strip() if parser.title else None)
    return parser.og, (parser.title.strip() if parser.title else None)


def _base_link_preview(html: str) -> LinkPreview | None:
    """OG-then-`<title>` parsing. Returns `None` when nothing usable was found at all."""
    og, page_title = _parse_og(html)
    title = og.get("og:title") or page_title
    description = og.get("og:description")
    image_url = og.get("og:image")
    site_name = og.get("og:site_name")
    if not any((title, description, image_url, site_name)):
        return None
    return LinkPreview(
        title=title, description=description, image_url=image_url, site_name=site_name
    )


# --- Airbnb-aware extraction (best-effort) ----------------------------------------------------

#: `og:title` shape: "Home in Dent · ★4.8 · 5 bedrooms · 7 beds · 4.5 bathrooms". The listing
#: name is everything before the first separator; the rest are the "facts".
_FACT_SEPARATOR = re.compile(r"\s*·\s*")

#: `<title>` shape for a locality: "Dent, England, United Kingdom" — at least one comma, no
#: separators that would suggest it's something else (a search results title, an error page).
_LOCALITY_RE = re.compile(r"^[^,]+,[^,]+(?:,[^,]+)?$")

#: Best-effort embedded-JSON scrape. Deliberately loose (no HTML/JS parser): any Airbnb
#: redesign that changes the surrounding structure still leaves these key/value pairs
#: findable by regex, and a full JSON parse of an entire page's inline script blobs is far
#: more likely to break outright than a targeted key search is to false-positive.
_LAT_RE = re.compile(r'"latitude"\s*:\s*(-?\d{1,3}\.\d+)')
_LNG_RE = re.compile(r'"longitude"\s*:\s*(-?\d{1,3}\.\d+)')
_CAPACITY_RE = re.compile(r'"personCapacity"\s*:\s*(\d{1,3})')


def _apply_airbnb_extraction(base: LinkPreview, html: str) -> LinkPreview:
    """Layers Airbnb's structured facts + best-effort coordinates onto `base`.

    Never raises: `design.md` requires "any parse failure -> plain OG result", so every step
    here is wrapped defensively and a failure at any point just leaves that field unset.
    """
    facts: str | None = None
    title = base.title
    try:
        if base.title and "·" in base.title:
            parts = _FACT_SEPARATOR.split(base.title)
            if len(parts) >= 2:
                title = parts[0].strip() or base.title
                facts = " · ".join(p.strip() for p in parts[1:] if p.strip()) or None
    except Exception:  # noqa: BLE001
        title, facts = base.title, None

    locality: str | None = None
    try:
        _, page_title = _parse_og(html)
        if page_title and _LOCALITY_RE.match(page_title):
            locality = page_title
    except Exception:  # noqa: BLE001
        locality = None

    lat = lng = None
    try:
        lat_match, lng_match = _LAT_RE.search(html), _LNG_RE.search(html)
        if lat_match and lng_match:
            lat, lng = float(lat_match.group(1)), float(lng_match.group(1))
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
                lat = lng = None
    except Exception:  # noqa: BLE001
        lat = lng = None

    capacity = None
    try:
        cap_match = _CAPACITY_RE.search(html)
        if cap_match:
            capacity = int(cap_match.group(1))
    except Exception:  # noqa: BLE001
        capacity = None

    return base.model_copy(
        update={
            "title": title,
            "facts": facts,
            "locality": locality,
            "lat": lat,
            "lng": lng,
            "capacity": capacity,
        }
    )


def parse_link_preview(html: str, *, is_airbnb: bool) -> LinkPreview | None:
    """Pure parsing entry point (no I/O) — kept separate from :meth:`LinkPreviewService.fetch`
    so the parser logic is directly unit-testable against fixture HTML."""
    base = _base_link_preview(html)
    if base is None:
        return None
    if not is_airbnb:
        return base
    try:
        return _apply_airbnb_extraction(base, html)
    except Exception:  # noqa: BLE001 - the whole point of this layer being best-effort
        return base


def _looks_like_airbnb(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "airbnb.com" or host.endswith(".airbnb.com")


# --- in-memory LRU + TTL cache -----------------------------------------------------------------


@dataclass
class _CacheEntry:
    value: LinkPreview | None
    expires_at: float


class _TtlLru:
    """Small hand-rolled LRU with a TTL, since the design explicitly rules out a DB table for
    this cache — pulling in a caching library for ~250 lines of behaviour isn't worth it."""

    def __init__(self, max_entries: int, ttl_seconds: float) -> None:
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._data: dict[str, _CacheEntry] = {}
        self._order: list[str] = []

    def get(self, key: str, *, now: float) -> tuple[bool, LinkPreview | None]:
        entry = self._data.get(key)
        if entry is None:
            return False, None
        if entry.expires_at <= now:
            self._data.pop(key, None)
            if key in self._order:
                self._order.remove(key)
            return False, None
        if key in self._order:
            self._order.remove(key)
        self._order.append(key)
        return True, entry.value

    def set(self, key: str, value: LinkPreview | None, *, now: float) -> None:
        self._data[key] = _CacheEntry(value=value, expires_at=now + self._ttl)
        if key in self._order:
            self._order.remove(key)
        self._order.append(key)
        while len(self._order) > self._max_entries:
            oldest = self._order.pop(0)
            self._data.pop(oldest, None)

    def __len__(self) -> int:
        return len(self._data)


# --- the service ---------------------------------------------------------------------------


class LinkPreviewServiceProtocol(Protocol):
    async def fetch(self, url: str) -> LinkPreview | None:  # pragma: no cover - protocol
        ...


class LinkPreviewService:
    """Orchestrates SSRF-checked fetch (with bounded redirect-following), OG/Airbnb parsing,
    and the LRU/TTL cache. `transport` and `resolver` default to the real network-touching
    implementations; tests inject fakes."""

    def __init__(
        self,
        *,
        transport: HttpTransportProtocol | None = None,
        resolver: DnsResolverProtocol | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._transport = transport or HttpxTransport()
        self._resolver = resolver or SystemDnsResolver()
        self._clock = clock or time.monotonic
        self._cache = _TtlLru(CACHE_MAX_ENTRIES, CACHE_TTL_SECONDS)

    async def fetch(self, url: str) -> LinkPreview | None:
        now = self._clock()
        hit, cached = self._cache.get(url, now=now)
        if hit:
            return cached

        result = await self._fetch_uncached(url)
        self._cache.set(url, result, now=now)
        return result

    async def _fetch_uncached(self, url: str) -> LinkPreview | None:
        current_url = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                await _check_url_is_safe(current_url, self._resolver)
            except SSRFRejected:
                return None

            try:
                response = await self._transport.get(current_url)
            except Exception:  # noqa: BLE001 - timeout/transport error -> "no preview"
                return None

            if response.status_code in (301, 302, 303, 307, 308):
                location = response.header("location")
                if not location:
                    return None
                current_url = urljoin(current_url, location)
                continue

            if response.status_code != 200:
                return None

            try:
                html = response.body.decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                return None

            return parse_link_preview(html, is_airbnb=_looks_like_airbnb(response.url))

        return None  # redirect budget exhausted


def get_link_preview_service() -> LinkPreviewServiceProtocol:
    """FastAPI dependency, for the M3 route to depend on. Overridden with a fake in tests."""
    return LinkPreviewService()
