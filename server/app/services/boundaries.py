"""Named-locality region boundaries, via OpenStreetMap/Nominatim.

**Pre-built ahead of the route** (`plan/features/map-suggestions/tasks.md`, M3), same as
`app.services.link_preview` — this module is route-free; the M3 feature agent calls
:func:`get_boundary_service` from the region-creation endpoint.

Contract, per `plan/features/map-suggestions/design.md` > "Named-locality regions":

* One server-side Nominatim fetch (`polygon_geojson=1`) per created region, with a proper
  identifying `User-Agent` per Nominatim's usage policy — never the bare default `httpx`
  agent. Callers are expected to cache the result forever (`geometry_geojson`); this module
  does not cache internally, it is called once per region creation.
* The returned ring is simplified with Douglas-Peucker to a vertex budget (target ≤ 500
  points) before being handed back — full-resolution OSM admin boundaries are far denser
  than a map overlay needs.
* Boundary rendering carries an ODbL attribution requirement ("boundary © OpenStreetMap
  contributors") — that's a UI-layer concern (`source: "osm"` on the result is what a caller
  keys the attribution notice off of), not something this module renders itself.
* When Nominatim has no boundary for the query but does geocode it, fall back to bounding-box
  data for a rounded ellipse (never a raw rectangle) that the frontend seeds the draw tool
  with.
* When Nominatim finds nothing at all, `lookup` returns `None`.

Networking is behind an injectable transport, same pattern as `link_preview.py`, so tests
never touch Nominatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel

# --- constants -------------------------------------------------------------------------------

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"

#: Nominatim's usage policy (https://operations.osmfoundation.org/policies/nominatim/)
#: requires a valid identifying User-Agent or Referer. `httpx`'s default agent is explicitly
#: called out there as grounds for a block.
#:
#: The identifier has to be *real*. This was a hardcoded string ending in
#: `contact: admin@example.org`, and Nominatim answered every request with `403 Forbidden` —
#: a placeholder contact is treated the same as no contact at all. The whole feature failed
#: silently, because `BoundaryService.lookup` maps any transport error to "nothing found":
#: searching a county produced "no boundary" rather than an error anyone could act on.
#: Building the agent from the deployment's own `PUBLIC_BASE_URL` makes it identify a real
#:, reachable service, which is the entire point of the policy.
USER_AGENT_TEMPLATE = "Kindred/1.0 (+{base_url})"


def user_agent() -> str:
    """The identifying User-Agent for Nominatim, from this deployment's public URL.

    Read at call time rather than import time so a settings override applies without a
    module reload, and so tests can point it anywhere.
    """
    from app.core.config import settings

    override = settings.nominatim_user_agent.strip()
    if override:
        return override
    return USER_AGENT_TEMPLATE.format(base_url=settings.public_base_url.rstrip("/"))

FETCH_TIMEOUT_SECONDS = 8.0

#: `design.md`: "Douglas-Peucker to a sane vertex budget, target ≤ 500 points".
MAX_RING_POINTS = 500


# --- response shapes -------------------------------------------------------------------------


class LatLng(BaseModel):
    lat: float
    lng: float


class BoundingBox(BaseModel):
    south: float
    west: float
    north: float
    east: float


class BoundaryResult(BaseModel):
    """A real administrative boundary, ready to store as `suggestions.geometry_geojson`.

    `geojson` is a GeoJSON `Feature` with a `Polygon` geometry (single, simplified exterior
    ring — `design.md`'s region-geometry encoding takes one ring per region) and
    `properties = {"shape": "polygon", "boundary_source": "osm", "osm_relation_id": ...}`.
    """

    geojson: dict
    display_name: str
    osm_relation_id: int | None = None
    source: Literal["osm"] = "osm"


class EllipseFallback(BaseModel):
    """`design.md`'s fallback: "seed a rounded ellipse fitted inside the geocoded bounding
    box" when Nominatim geocodes the query but returns no boundary polygon.

    `center`/`bounds` are the raw data a caller fits an ellipse from. `ellipse_geojson` is
    provided as a convenience: a pre-built `Polygon` Feature (an ellipse inscribed in
    `bounds`), `properties.shape = "polygon"`, `properties.boundary_source =
    "fallback_ellipse"` — a caller can use it directly to seed the draw tool, per the design
    note that this must never be a raw bounding-box rectangle.
    """

    center: LatLng
    bounds: BoundingBox
    display_name: str | None = None
    ellipse_geojson: dict


LookupResult = BoundaryResult | EllipseFallback | None


# --- Douglas-Peucker (hand-implemented, unit-tested) ------------------------------------------


def _perpendicular_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    """Perpendicular distance from `point` to the line through `start`/`end`.

    Plain planar distance in coordinate space (lng/lat treated as x/y), not a great-circle
    distance. That is the standard, accepted approximation for boundary-simplification at
    town/county scale — the distortion is negligible at these coordinate spans, and using it
    keeps the algorithm a handful of lines instead of pulling in geodesic math for a purely
    visual simplification.
    """
    x, y = point
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    proj_x, proj_y = x1 + t * dx, y1 + t * dy
    return ((x - proj_x) ** 2 + (y - proj_y) ** 2) ** 0.5


def douglas_peucker(
    points: list[tuple[float, float]], epsilon: float
) -> list[tuple[float, float]]:
    """Classic recursive Douglas-Peucker line simplification.

    `points` is a list of `(x, y)` — here always `(lng, lat)` to match GeoJSON coordinate
    order. Endpoints are always kept. `epsilon` is in the same units as the coordinates
    (degrees), so callers pick it by trial against :data:`MAX_RING_POINTS` (see
    :func:`simplify_ring`) rather than a single fixed constant working for both a village and
    a county.
    """
    if len(points) < 3:
        return list(points)

    start, end = points[0], points[-1]
    max_dist = -1.0
    max_index = 0
    for i in range(1, len(points) - 1):
        dist = _perpendicular_distance(points[i], start, end)
        if dist > max_dist:
            max_dist = dist
            max_index = i

    if max_dist <= epsilon:
        return [start, end]

    left = douglas_peucker(points[: max_index + 1], epsilon)
    right = douglas_peucker(points[max_index:], epsilon)
    return left[:-1] + right


def simplify_ring(
    ring: list[tuple[float, float]], max_points: int = MAX_RING_POINTS
) -> list[tuple[float, float]]:
    """Simplify a closed ring to at most `max_points`, by widening `epsilon` until it fits.

    A ring (not an open polyline): first and last coordinates are equal. Douglas-Peucker
    always keeps both, so the ring stays closed through every iteration.

    Widening search rather than a closed-form epsilon: there's no simple formula from "vertex
    budget" to "epsilon in degrees" that holds across a boundary's actual shape, and this
    algorithm is run at most once per region creation, so a bounded loop of cheap
    re-simplifications is not a performance concern.
    """
    if len(ring) <= max_points:
        return list(ring)

    # A degree of longitude/latitude is a coarse but sufficient unit here: start tiny and
    # double until the ring is within budget, then binary-search the last interval for a
    # tighter fit rather than overshooting into a visibly blocky shape.
    lo, hi = 0.0, 1.0
    simplified = ring
    while len(simplified) > max_points:
        hi *= 2
        simplified = douglas_peucker(ring, hi)
        if hi > 360:  # pathological input guard; 360 degrees exceeds any real extent
            break

    for _ in range(20):
        mid = (lo + hi) / 2
        candidate = douglas_peucker(ring, mid)
        if len(candidate) > max_points:
            lo = mid
        else:
            hi = mid
            simplified = candidate

    return simplified


# --- HTTP transport ------------------------------------------------------------------------


class HttpTransportProtocol(Protocol):
    async def get_json(self, url: str, params: dict[str, str]) -> object:  # pragma: no cover
        """GET `url` with `params`, return the parsed JSON body. Raises on transport failure
        or a non-2xx status."""
        ...


class HttpxTransport:
    async def get_json(self, url: str, params: dict[str, str]) -> object:
        import httpx

        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_SECONDS, headers={"User-Agent": user_agent()}
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()


@dataclass
class FakeHttpTransport:
    """Test double: `(url, sorted params items)` -> canned JSON payload, or a configured
    exception. Records every call so a test can assert exactly one fetch happened."""

    responses: dict[str, object] = field(default_factory=dict)
    raises_for: dict[str, Exception] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def _key(self, url: str, params: dict[str, str]) -> str:
        return url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))

    async def get_json(self, url: str, params: dict[str, str]) -> object:
        self.calls.append((url, dict(params)))
        key = self._key(url, params)
        if key in self.raises_for:
            raise self.raises_for[key]
        if key not in self.responses:
            raise OSError(f"FakeHttpTransport: no response configured for {key!r}")
        return self.responses[key]


# --- Nominatim response -> our shapes -----------------------------------------------------


def _largest_polygon_ring(geojson_geom: dict) -> list[list[float]] | None:
    """The exterior ring of the largest polygon in a Nominatim `geojson` field.

    Nominatim returns `Polygon` or `MultiPolygon`. Holes (interior rings) are not represented
    in `suggestions.geometry_geojson` per `design.md`'s two supported shapes, so only the
    exterior ring is kept — losing interior holes (e.g. an enclave) is an accepted
    simplification for a visual region overlay, not a correctness requirement.
    """
    gtype = geojson_geom.get("type")
    coords = geojson_geom.get("coordinates")
    if gtype == "Polygon" and coords:
        return coords[0]
    if gtype == "MultiPolygon" and coords:
        # Largest by raw vertex count of its exterior ring — a cheap, adequate proxy for area
        # without pulling in a geometry library for a one-off "pick the main landmass" choice.
        rings = [poly[0] for poly in coords if poly]
        return max(rings, key=len) if rings else None
    return None


def _build_boundary_feature(
    ring: list[list[float]], osm_relation_id: int | None
) -> dict:
    simplified = simplify_ring([(pt[0], pt[1]) for pt in ring])
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[x, y] for x, y in simplified]],
        },
        "properties": {
            "shape": "polygon",
            "boundary_source": "osm",
            "osm_relation_id": osm_relation_id,
        },
    }


def _ellipse_polygon(bounds: BoundingBox, *, num_points: int = 48) -> dict:
    """A rounded ellipse inscribed in `bounds`, as a `Polygon` Feature.

    `design.md`: "seed a rounded ellipse fitted inside the geocoded bounding box... Never
    render a raw bounding-box rectangle." An inscribed ellipse (rather than the box itself)
    is the shape the design calls for.
    """
    import math

    cx = (bounds.west + bounds.east) / 2
    cy = (bounds.south + bounds.north) / 2
    rx = (bounds.east - bounds.west) / 2
    ry = (bounds.north - bounds.south) / 2
    ring = [
        [cx + rx * math.cos(theta), cy + ry * math.sin(theta)]
        for theta in (2 * math.pi * i / num_points for i in range(num_points))
    ]
    ring.append(ring[0])
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {"shape": "polygon", "boundary_source": "fallback_ellipse"},
    }


def _parse_bbox(raw: list[str]) -> BoundingBox:
    """Nominatim's `boundingbox` is `[south, north, west, east]`, all strings."""
    south, north, west, east = (float(v) for v in raw)
    return BoundingBox(south=south, west=west, north=north, east=east)


# --- the service ---------------------------------------------------------------------------


class BoundaryServiceProtocol(Protocol):
    async def lookup(self, query: str) -> LookupResult:  # pragma: no cover - protocol
        ...


class BoundaryService:
    def __init__(self, *, transport: HttpTransportProtocol | None = None) -> None:
        self._transport = transport or HttpxTransport()

    async def lookup(self, query: str) -> LookupResult:
        try:
            payload = await self._transport.get_json(
                NOMINATIM_SEARCH_URL,
                {
                    "q": query,
                    "format": "jsonv2",
                    "polygon_geojson": "1",
                    "limit": "1",
                    "addressdetails": "0",
                },
            )
        except Exception:  # noqa: BLE001 - transport failure / timeout -> nothing found
            return None

        if not isinstance(payload, list) or not payload:
            return None

        first = payload[0]
        if not isinstance(first, dict):
            return None

        display_name = str(first.get("display_name") or query)
        raw_bbox = first.get("boundingbox")
        raw_geojson = first.get("geojson")

        if isinstance(raw_geojson, dict):
            ring = _largest_polygon_ring(raw_geojson)
            if ring and len(ring) >= 4:
                osm_relation_id = (
                    int(first["osm_id"])
                    if first.get("osm_type") == "relation" and first.get("osm_id") is not None
                    else None
                )
                return BoundaryResult(
                    geojson=_build_boundary_feature(ring, osm_relation_id),
                    display_name=display_name,
                    osm_relation_id=osm_relation_id,
                )

        # No usable boundary polygon: fall back to the geocoded bounding box, if we have one.
        if isinstance(raw_bbox, list) and len(raw_bbox) == 4:
            try:
                bounds = _parse_bbox(raw_bbox)
            except (TypeError, ValueError):
                return None
            center = LatLng(
                lat=(bounds.south + bounds.north) / 2, lng=(bounds.west + bounds.east) / 2
            )
            return EllipseFallback(
                center=center,
                bounds=bounds,
                display_name=display_name,
                ellipse_geojson=_ellipse_polygon(bounds),
            )

        return None


def get_boundary_service() -> BoundaryServiceProtocol:
    """FastAPI dependency, for the M3 route to depend on. Overridden with a fake in tests."""
    return BoundaryService()
