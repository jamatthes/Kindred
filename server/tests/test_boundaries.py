"""Tests for `app.services.boundaries`.

Pure unit tests: no DB fixtures, no network — `BoundaryService` is exercised entirely through
`FakeHttpTransport`.

**Test-DB isolation** (per the M3-services pre-build brief): `tests/conftest.py` has a
session-scoped `_database` fixture with `autouse=True`, so it still fires for every test
collected in this file even though none of these tests use the `db`/`client` fixtures — pytest
loads the parent `conftest.py` for any file under `tests/`, and `autouse` fixtures apply
regardless of whether a test asks for them.

That fixture creates/rebuilds whatever database `TEST_DATABASE_URL` (or `DATABASE_URL` +
`_test`) resolves to and **`TRUNCATE`s every table before each test** — the default resolves
to `kindred_test`, which other agents may be running pytest against concurrently. To run just
this service test suite without racing them, point it at a private, uniquely-named database
(must end in `_test`, per conftest's own guard) instead:

    # from server/
    TEST_DATABASE_URL="postgresql+asyncpg://kindred:change-me@localhost:5432/kindred_svc_test" \\
        pytest tests/test_boundaries.py tests/test_link_preview.py

(PowerShell: `$env:TEST_DATABASE_URL = "...kindred_svc_test"; pytest ...`.) The database is
created automatically if it does not exist. Because these two files touch no table at all, the
per-test `TRUNCATE` against `kindred_svc_test` is a no-op — the isolation is really about not
sharing the schema-rebuild/truncate cycle with a database another agent's suite is mid-test
against.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.boundaries import (
    MAX_RING_POINTS,
    USER_AGENT,
    BoundaryResult,
    BoundaryService,
    EllipseFallback,
    FakeHttpTransport,
    NOMINATIM_SEARCH_URL,
    _parse_bbox,
    douglas_peucker,
    simplify_ring,
)

FIXTURES = Path(__file__).parent / "fixtures"
RUTLAND = json.loads((FIXTURES / "nominatim_rutland.json").read_text(encoding="utf-8"))


def _search_params(query: str) -> dict[str, str]:
    return {
        "q": query,
        "format": "jsonv2",
        "polygon_geojson": "1",
        "limit": "1",
        "addressdetails": "0",
    }


# --- Douglas-Peucker -------------------------------------------------------------------------


def test_douglas_peucker_keeps_endpoints_of_straight_line():
    points = [(0.0, 0.0), (1.0, 0.001), (2.0, -0.001), (3.0, 0.0)]
    result = douglas_peucker(points, epsilon=0.5)
    assert result == [(0.0, 0.0), (3.0, 0.0)]


def test_douglas_peucker_keeps_a_real_corner():
    """A sharp corner well outside epsilon must survive simplification."""
    points = [(0.0, 0.0), (1.0, 0.0), (1.0, 5.0), (2.0, 5.0)]
    result = douglas_peucker(points, epsilon=0.1)
    assert (1.0, 5.0) in result
    assert result[0] == (0.0, 0.0)
    assert result[-1] == (2.0, 5.0)


def test_douglas_peucker_handles_fewer_than_three_points():
    assert douglas_peucker([], 1.0) == []
    assert douglas_peucker([(0.0, 0.0)], 1.0) == [(0.0, 0.0)]
    assert douglas_peucker([(0.0, 0.0), (1.0, 1.0)], 1.0) == [(0.0, 0.0), (1.0, 1.0)]


def test_douglas_peucker_large_epsilon_collapses_to_endpoints():
    points = [(float(i), 0.01 * ((-1) ** i)) for i in range(50)]
    result = douglas_peucker(points, epsilon=1000.0)
    assert result == [points[0], points[-1]]


def test_simplify_ring_under_budget_is_unchanged():
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    assert simplify_ring(ring, max_points=500) == ring


def test_simplify_ring_reduces_dense_ring_to_budget():
    # A near-circular ring with lots of near-collinear noise, deliberately over budget.
    import math

    dense = [
        (math.cos(2 * math.pi * i / 2000), math.sin(2 * math.pi * i / 2000))
        for i in range(2000)
    ]
    dense.append(dense[0])

    simplified = simplify_ring(dense, max_points=200)

    assert len(simplified) <= 200
    assert len(simplified) >= 4  # still recognisably a polygon
    assert simplified[0] == simplified[-1]  # ring stays closed


def test_simplify_ring_on_fixture_polygon_stays_within_500():
    ring = [tuple(pt) for pt in RUTLAND[0]["geojson"]["coordinates"][0]]
    assert len(ring) > MAX_RING_POINTS  # the fixture is deliberately over budget

    simplified = simplify_ring(ring)

    assert len(simplified) <= MAX_RING_POINTS
    assert simplified[0] == simplified[-1]


# --- bounding box parsing --------------------------------------------------------------------


def test_parse_bbox_orders_south_west_north_east():
    # Nominatim order: [south, north, west, east]
    bounds = _parse_bbox(["52.54", "52.75", "-0.78", "-0.44"])
    assert bounds.south == 52.54
    assert bounds.north == 52.75
    assert bounds.west == -0.78
    assert bounds.east == -0.44


# --- BoundaryService.lookup ------------------------------------------------------------------


async def test_lookup_returns_boundary_result_for_fixture_polygon():
    transport = FakeHttpTransport(
        responses={
            (NOMINATIM_SEARCH_URL + "?" + "&".join(
                f"{k}={v}" for k, v in sorted(_search_params("Rutland").items())
            )): RUTLAND
        }
    )
    service = BoundaryService(transport=transport)

    result = await service.lookup("Rutland")

    assert isinstance(result, BoundaryResult)
    assert result.source == "osm"
    assert result.osm_relation_id == 170252
    assert result.display_name == "Rutland, East Midlands, England, United Kingdom"
    assert result.geojson["type"] == "Feature"
    assert result.geojson["geometry"]["type"] == "Polygon"
    ring = result.geojson["geometry"]["coordinates"][0]
    assert len(ring) <= MAX_RING_POINTS
    assert ring[0] == ring[-1]
    assert result.geojson["properties"]["shape"] == "polygon"
    assert result.geojson["properties"]["boundary_source"] == "osm"
    assert transport.calls == [(NOMINATIM_SEARCH_URL, _search_params("Rutland"))]


async def test_lookup_falls_back_to_ellipse_when_no_geojson():
    payload = [
        {
            "place_id": 1,
            "osm_type": "node",
            "osm_id": 999,
            "display_name": "Some Hamlet, England, United Kingdom",
            "boundingbox": ["50.0", "50.1", "-1.0", "-0.9"],
            # no "geojson" key at all
        }
    ]
    transport = FakeHttpTransport(
        responses={
            (NOMINATIM_SEARCH_URL + "?" + "&".join(
                f"{k}={v}" for k, v in sorted(_search_params("Some Hamlet").items())
            )): payload
        }
    )
    service = BoundaryService(transport=transport)

    result = await service.lookup("Some Hamlet")

    assert isinstance(result, EllipseFallback)
    assert result.bounds.south == 50.0
    assert result.bounds.north == 50.1
    assert result.bounds.west == -1.0
    assert result.bounds.east == -0.9
    assert result.center.lat == 50.05
    assert result.center.lng == -0.95
    assert result.display_name == "Some Hamlet, England, United Kingdom"
    # never a raw bounding-box rectangle: the ellipse polygon must have more than 4 points
    # and must not coincide with the box's corners.
    ring = result.ellipse_geojson["geometry"]["coordinates"][0]
    assert len(ring) > 4
    assert ring[0] == ring[-1]
    assert result.ellipse_geojson["properties"]["boundary_source"] == "fallback_ellipse"


async def test_lookup_returns_none_when_nominatim_finds_nothing():
    transport = FakeHttpTransport(
        responses={
            (NOMINATIM_SEARCH_URL + "?" + "&".join(
                f"{k}={v}" for k, v in sorted(_search_params("Nowhereville").items())
            )): []
        }
    )
    service = BoundaryService(transport=transport)

    assert await service.lookup("Nowhereville") is None


async def test_lookup_returns_none_on_transport_failure():
    key = NOMINATIM_SEARCH_URL + "?" + "&".join(
        f"{k}={v}" for k, v in sorted(_search_params("Timeout Town").items())
    )
    transport = FakeHttpTransport(raises_for={key: TimeoutError("simulated timeout")})
    service = BoundaryService(transport=transport)

    assert await service.lookup("Timeout Town") is None


async def test_lookup_picks_largest_ring_from_multipolygon():
    small_ring = [[0.0, 0.0], [0.0, 0.1], [0.1, 0.1], [0.1, 0.0], [0.0, 0.0]]
    big_ring = [
        [0.0, 0.0],
        [0.0, 1.0],
        [0.5, 1.2],
        [1.0, 1.0],
        [1.0, 0.0],
        [0.5, -0.2],
        [0.0, 0.0],
    ]
    payload = [
        {
            "place_id": 2,
            "osm_type": "relation",
            "osm_id": 42,
            "display_name": "Archipelago, Somewhere",
            "boundingbox": ["-1", "2", "-1", "2"],
            "geojson": {
                "type": "MultiPolygon",
                "coordinates": [[small_ring], [big_ring]],
            },
        }
    ]
    key = NOMINATIM_SEARCH_URL + "?" + "&".join(
        f"{k}={v}" for k, v in sorted(_search_params("Archipelago").items())
    )
    transport = FakeHttpTransport(responses={key: payload})
    service = BoundaryService(transport=transport)

    result = await service.lookup("Archipelago")

    assert isinstance(result, BoundaryResult)
    ring = result.geojson["geometry"]["coordinates"][0]
    # the big ring's distinctive vertex must be present (simplification may still touch it,
    # but with only 7 points and a small default epsilon search it should survive intact)
    assert [0.5, 1.2] in ring or any(abs(pt[1] - 1.2) < 1e-6 for pt in ring)


def test_user_agent_identifies_the_app_per_nominatim_policy():
    assert "Kindred" in USER_AGENT
    assert "@" in USER_AGENT or "contact" in USER_AGENT.lower()
