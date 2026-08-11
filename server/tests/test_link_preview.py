"""Tests for `app.services.link_preview`.

Pure unit tests: no DB fixtures, no network. Runs fine standalone even though
`tests/conftest.py`'s session-scoped `_database` autouse fixture still fires for this file
(pytest loads the whole parent conftest chain) — see the module docstring in
`app/services/link_preview.py` and the repo-wide note on `TEST_DATABASE_URL` in this file's
sibling `test_boundaries.py` for why that's safe to run concurrently with other agents' suites.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.link_preview import (
    USER_AGENT,
    FakeDnsResolver,
    FakeHttpTransport,
    LinkPreviewService,
    RawResponse,
    SSRFRejected,
    _check_url_is_safe,
    _looks_like_airbnb,
    _TtlLru,
    parse_link_preview,
)

FIXTURES = Path(__file__).parent / "fixtures"
AIRBNB_HTML = (FIXTURES / "airbnb_listing.html").read_text(encoding="utf-8")

PLAIN_HTML = """
<!doctype html>
<html><head>
<title>A Plain Page</title>
<meta property="og:title" content="A Plain Page">
<meta property="og:description" content="Just a website, nothing Airbnb about it.">
<meta property="og:image" content="https://example.com/hero.jpg">
<meta property="og:site_name" content="Example">
</head><body>hello</body></html>
"""

NO_OG_HTML = "<html><head></head><body>nothing to see here</body></html>"


# --- pure parsing ------------------------------------------------------------------------


def test_parse_airbnb_fixture_extracts_facts_locality_coords_capacity():
    result = parse_link_preview(AIRBNB_HTML, is_airbnb=True)

    assert result is not None
    assert result.title == "Home in Dent"
    assert result.facts == "★4.8 · 5 bedrooms · 7 beds · 4.5 bathrooms"
    assert result.locality == "Dent, England, United Kingdom"
    assert result.site_name == "Airbnb"
    assert result.description == "Cosy fell-side farmhouse retreat near the Dales Way"
    assert result.image_url == "https://a0.example-static.com/pictures/hero-720.jpg"
    assert result.lat == pytest.approx(54.2831)
    assert result.lng == pytest.approx(-2.4578)
    assert result.capacity == 10


def test_parse_airbnb_fixture_as_plain_og_when_not_flagged_airbnb():
    """The same HTML, parsed without the Airbnb flag, gets no bonus fields — the flag is
    what gates the best-effort layer, not the content itself."""
    result = parse_link_preview(AIRBNB_HTML, is_airbnb=False)

    assert result is not None
    assert result.title == "Home in Dent · ★4.8 · 5 bedrooms · 7 beds · 4.5 bathrooms"
    assert result.facts is None
    assert result.locality is None
    assert result.lat is None
    assert result.capacity is None


def test_parse_plain_og_page():
    result = parse_link_preview(PLAIN_HTML, is_airbnb=False)

    assert result is not None
    assert result.title == "A Plain Page"
    assert result.description == "Just a website, nothing Airbnb about it."
    assert result.image_url == "https://example.com/hero.jpg"
    assert result.site_name == "Example"


def test_parse_page_with_no_og_and_no_title_returns_none():
    assert parse_link_preview("<html><body>empty</body></html>", is_airbnb=False) is None


def test_parse_garbage_html_never_raises():
    garbage_samples = [
        "\x00\x01\x02 not html at all \xff\xfe",
        "<html><meta property=og:title content=unquoted></html>",
        "<<<>>>broken<<<tags",
        "",
    ]
    for sample in garbage_samples:
        parse_link_preview(sample, is_airbnb=True)  # must not raise


def test_airbnb_extraction_degrades_silently_on_malformed_embedded_json():
    """`design.md`: "any parse failure -> plain OG result". Feed HTML whose og:title has the
    Airbnb separator but whose embedded JSON is garbage; facts still parse, coords do not."""
    html = """
    <html><head>
    <title>Not, A, Real, Locality, String, Too, Many, Commas</title>
    <meta property="og:title" content="Home in Nowhere · ★3.2 · 2 bedrooms">
    <meta property="og:site_name" content="Airbnb">
    </head><body>"latitude": "not-a-number", "personCapacity": "lots"</body></html>
    """
    result = parse_link_preview(html, is_airbnb=True)
    assert result is not None
    assert result.title == "Home in Nowhere"
    assert result.facts == "★3.2 · 2 bedrooms"
    assert result.locality is None  # too many commas to match the locality shape
    assert result.lat is None
    assert result.lng is None
    assert result.capacity is None


def test_looks_like_airbnb_host_matching():
    assert _looks_like_airbnb("https://www.airbnb.com/rooms/123") is True
    assert _looks_like_airbnb("https://airbnb.com/rooms/123") is True
    assert _looks_like_airbnb("https://airbnb.com.evil.example/rooms/123") is False
    assert _looks_like_airbnb("https://example.com") is False


# --- SSRF guard ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",  # resolved via FakeDnsResolver mapping below
        "http://10.0.0.5/",
        "http://169.254.169.254/",  # link-local: cloud metadata endpoint
        "http://[::1]/",  # loopback, IPv6
        "ftp://example.com/",  # disallowed scheme
        "http://",  # no host
    ],
)
async def test_ssrf_guard_rejects_disallowed_targets(url):
    resolver = FakeDnsResolver(hosts={"localhost": ["127.0.0.1"]})
    with pytest.raises(SSRFRejected):
        await _check_url_is_safe(url, resolver)


async def test_ssrf_guard_allows_public_address():
    resolver = FakeDnsResolver(hosts={"example.com": ["93.184.216.34"]})
    await _check_url_is_safe("https://example.com/page", resolver)  # must not raise


async def test_ssrf_guard_rejects_when_any_resolved_address_is_private():
    """A host with mixed public/private A records must be rejected wholesale — trusting the
    "first" address and racing which one gets connected to is exactly the DNS-rebinding
    surface the guard exists to close."""
    resolver = FakeDnsResolver(hosts={"sneaky.example": ["93.184.216.34", "10.0.0.1"]})
    with pytest.raises(SSRFRejected):
        await _check_url_is_safe("https://sneaky.example/", resolver)


# --- service: fetch orchestration -----------------------------------------------------------


def _resp(url: str, *, status=200, body=b"", location=None) -> RawResponse:
    headers = {"content-type": "text/html"}
    if location:
        headers["location"] = location
    return RawResponse(status_code=status, headers=headers, body=body, url=url)


async def test_fetch_happy_path_plain_page():
    transport = FakeHttpTransport(
        responses={"https://example.com/a": _resp("https://example.com/a", body=PLAIN_HTML.encode())}
    )
    resolver = FakeDnsResolver(hosts={"example.com": ["93.184.216.34"]})
    service = LinkPreviewService(transport=transport, resolver=resolver)

    result = await service.fetch("https://example.com/a")

    assert result is not None
    assert result.title == "A Plain Page"
    assert transport.calls == ["https://example.com/a"]


async def test_fetch_airbnb_host_gets_bonus_fields():
    url = "https://www.airbnb.com/rooms/00000000"
    transport = FakeHttpTransport(responses={url: _resp(url, body=AIRBNB_HTML.encode())})
    resolver = FakeDnsResolver(hosts={"www.airbnb.com": ["13.225.1.1"]})
    service = LinkPreviewService(transport=transport, resolver=resolver)

    result = await service.fetch(url)

    assert result is not None
    assert result.facts == "★4.8 · 5 bedrooms · 7 beds · 4.5 bathrooms"
    assert result.capacity == 10


async def test_fetch_returns_none_when_no_preview_available_204_case():
    url = "https://example.com/no-og"
    transport = FakeHttpTransport(responses={url: _resp(url, body=NO_OG_HTML.encode())})
    resolver = FakeDnsResolver(hosts={"example.com": ["93.184.216.34"]})
    service = LinkPreviewService(transport=transport, resolver=resolver)

    assert await service.fetch(url) is None


async def test_fetch_returns_none_on_non_200_status():
    url = "https://example.com/missing"
    transport = FakeHttpTransport(responses={url: _resp(url, status=404, body=b"not found")})
    resolver = FakeDnsResolver(hosts={"example.com": ["93.184.216.34"]})
    service = LinkPreviewService(transport=transport, resolver=resolver)

    assert await service.fetch(url) is None


async def test_fetch_follows_redirect_and_checks_final_target():
    start = "https://short.example/x"
    dest = "https://example.com/real-page"
    transport = FakeHttpTransport(
        responses={
            start: _resp(start, status=302, location=dest),
            dest: _resp(dest, body=PLAIN_HTML.encode()),
        }
    )
    resolver = FakeDnsResolver(
        hosts={"short.example": ["93.184.216.10"], "example.com": ["93.184.216.34"]}
    )
    service = LinkPreviewService(transport=transport, resolver=resolver)

    result = await service.fetch(start)

    assert result is not None
    assert result.title == "A Plain Page"
    assert transport.calls == [start, dest]


async def test_fetch_rejects_redirect_to_private_address():
    start = "https://short.example/x"
    dest = "http://169.254.169.254/latest/meta-data/"
    transport = FakeHttpTransport(
        responses={start: _resp(start, status=301, location=dest)}
    )
    resolver = FakeDnsResolver(hosts={"short.example": ["93.184.216.10"]})
    service = LinkPreviewService(transport=transport, resolver=resolver)

    result = await service.fetch(start)

    assert result is None
    # The redirect target must never have been requested.
    assert dest not in transport.calls


async def test_fetch_gives_up_after_redirect_budget_exhausted():
    urls = [f"https://example.com/hop{i}" for i in range(10)]
    responses = {
        urls[i]: _resp(urls[i], status=302, location=urls[i + 1]) for i in range(len(urls) - 1)
    }
    transport = FakeHttpTransport(responses=responses)
    resolver = FakeDnsResolver(hosts={"example.com": ["93.184.216.34"]})
    service = LinkPreviewService(transport=transport, resolver=resolver)

    result = await service.fetch(urls[0])

    assert result is None


async def test_fetch_handles_transport_timeout_as_no_preview():
    url = "https://slow.example/page"
    transport = FakeHttpTransport(raises_for={url: TimeoutError("simulated timeout")})
    resolver = FakeDnsResolver(hosts={"slow.example": ["93.184.216.10"]})
    service = LinkPreviewService(transport=transport, resolver=resolver)

    assert await service.fetch(url) is None


async def test_fetch_handles_truncated_body_gracefully():
    """Simulates the real transport's 512KB cap having cut a chunk mid-tag: the body handed
    to the parser is truncated HTML. `HTMLParser` tolerates it; nothing raises."""
    url = "https://example.com/huge"
    truncated = PLAIN_HTML.encode()[:60]  # cuts off inside a tag
    transport = FakeHttpTransport(responses={url: _resp(url, body=truncated)})
    resolver = FakeDnsResolver(hosts={"example.com": ["93.184.216.34"]})
    service = LinkPreviewService(transport=transport, resolver=resolver)

    await service.fetch(url)  # must not raise; result content is not asserted


async def test_fetch_ssrf_rejected_initial_url_returns_none_without_transport_call():
    transport = FakeHttpTransport()
    resolver = FakeDnsResolver()
    service = LinkPreviewService(transport=transport, resolver=resolver)

    result = await service.fetch("http://127.0.0.1/admin")

    assert result is None
    assert transport.calls == []


# --- caching ---------------------------------------------------------------------------------


async def test_fetch_uses_cache_on_second_call():
    url = "https://example.com/a"
    transport = FakeHttpTransport(responses={url: _resp(url, body=PLAIN_HTML.encode())})
    resolver = FakeDnsResolver(hosts={"example.com": ["93.184.216.34"]})
    service = LinkPreviewService(transport=transport, resolver=resolver)

    first = await service.fetch(url)
    second = await service.fetch(url)

    assert first == second
    assert transport.calls == [url]  # only fetched once


async def test_fetch_refetches_after_ttl_expiry():
    url = "https://example.com/a"
    transport = FakeHttpTransport(responses={url: _resp(url, body=PLAIN_HTML.encode())})
    resolver = FakeDnsResolver(hosts={"example.com": ["93.184.216.34"]})
    fake_now = [1000.0]
    service = LinkPreviewService(transport=transport, resolver=resolver, clock=lambda: fake_now[0])

    await service.fetch(url)
    fake_now[0] += 301.0  # past CACHE_TTL_SECONDS (300)
    await service.fetch(url)

    assert transport.calls == [url, url]


def test_ttl_lru_evicts_oldest_beyond_capacity():
    cache = _TtlLru(max_entries=2, ttl_seconds=1000)
    cache.set("a", None, now=0)
    cache.set("b", None, now=0)
    cache.set("c", None, now=0)  # evicts "a"

    assert cache.get("a", now=0) == (False, None)
    assert cache.get("b", now=0)[0] is True
    assert cache.get("c", now=0)[0] is True
    assert len(cache) == 2


def test_user_agent_identifies_the_app():
    assert "Kindred" in USER_AGENT
    assert "httpx" not in USER_AGENT.lower()
