"""`centroid()` and the haversine helpers — pure functions, no database.

The `[lng, lat]` assertion is the one that earns its keep: GeoJSON orders positions longitude
first and Google's `LatLng` orders them latitude first, and a system that gets it wrong puts
Cornwall in the Indian Ocean without raising anything.
"""

from __future__ import annotations

import pytest

from app.models.geo import haversine_m_py
from app.models.suggestion import centroid

CORNWALL_LNG, CORNWALL_LAT = -4.7, 50.4


def circle(lng: float, lat: float, radius_m: float = 12_000) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": {"shape": "circle", "radius_m": radius_m},
    }


def polygon(ring: list[list[float]]) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {"shape": "polygon"},
    }


# --- circles ---------------------------------------------------------------------------------


def test_a_circles_centroid_is_its_centre():
    assert centroid(circle(CORNWALL_LNG, CORNWALL_LAT)) == (CORNWALL_LAT, CORNWALL_LNG)


def test_the_centroid_is_returned_lat_first_from_a_lng_first_geometry():
    """The whole point of the helper. The input is `[lng, lat]`; the output is `(lat, lng)`,
    because that is the order every column, API field and Python caller in Kindred uses."""
    lat, lng = centroid(circle(2.3522, 48.8566))  # Paris, GeoJSON order
    assert (round(lat, 4), round(lng, 4)) == (48.8566, 2.3522)


# --- polygons --------------------------------------------------------------------------------


def test_a_closed_polygons_centroid_is_the_vertex_average_ignoring_the_repeat():
    """A square from (0,0) to (2,2): the average of its four corners is (1,1).

    If the duplicated closing coordinate were counted, the answer would drift towards (0,0) —
    which is why the helper drops it rather than averaging what it is handed.
    """
    square = polygon([[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]])
    lat, lng = centroid(square)
    assert (pytest.approx(lat), pytest.approx(lng)) == (1.0, 1.0)


def test_an_unclosed_ring_still_averages_every_vertex_it_has():
    lat, lng = centroid(polygon([[0, 0], [2, 0], [2, 2], [0, 2]]))
    assert (pytest.approx(lat), pytest.approx(lng)) == (1.0, 1.0)


def test_a_polygon_that_does_not_cross_the_meridian():
    """A Cornish triangle, entirely west of Greenwich: every longitude is negative and the
    centroid must be too."""
    lat, lng = centroid(polygon([[-4.8, 50.3], [-4.6, 50.3], [-4.6, 50.5], [-4.8, 50.3]]))
    assert lng < 0
    assert (round(lat, 4), round(lng, 4)) == (50.3667, -4.6667)


def test_a_polygon_that_does_cross_the_meridian():
    """One vertex east, two west. The average is a plain arithmetic mean — deliberately, since
    a region straddling Greenwich is an ordinary shape and not a wraparound case (that is the
    antimeridian, which no trip this product plans has ever needed)."""
    lat, lng = centroid(polygon([[-0.2, 51.5], [0.4, 51.5], [0.1, 51.8], [-0.2, 51.5]]))
    assert (round(lat, 4), round(lng, 4)) == (51.6, 0.1)


# --- refusals ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "geometry",
    [
        None,
        {},
        {"type": "Feature"},
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": ["a", "b"]}},
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
    ],
)
def test_an_unusable_geometry_returns_none_rather_than_guessing(geometry):
    """`None` rather than a raise: the caller decides whether that is a `422` (creating a
    region) or "leave the point alone" (patching an accommodation)."""
    assert centroid(geometry) is None


# --- haversine ---------------------------------------------------------------------------------


def test_haversine_is_zero_for_a_point_against_itself():
    assert haversine_m_py(50.4, -4.7, 50.4, -4.7) == pytest.approx(0.0)


def test_haversine_matches_a_known_distance():
    """London to Paris is about 344 km. Within a kilometre is plenty for a grouping threshold
    and a distance estimate."""
    metres = haversine_m_py(51.5074, -0.1278, 48.8566, 2.3522)
    assert metres == pytest.approx(343_500, abs=1_000)


def test_haversine_is_symmetric():
    there = haversine_m_py(51.5, -0.12, 50.4, -4.7)
    back = haversine_m_py(50.4, -4.7, 51.5, -0.12)
    assert there == pytest.approx(back)
