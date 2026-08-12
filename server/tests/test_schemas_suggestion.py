"""The geometry validator's rejection paths, and the ToS invariant at the schema edge.

Every case here is a shape that must never reach the database. The validator is the first of
two defences — the second is the `ck_suggestions_geometry_iff_region` check constraint — and
this file is the one that names *why* each shape is wrong, in a message a user could act on.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.suggestion import (
    MAX_POLYGON_POINTS,
    MAX_RADIUS_M,
    PlaceSnapshot,
    SuggestionCreate,
    SuggestionUpdate,
    validate_region_geometry,
)


def circle(radius_m: float = 12_000, lng: float = -4.7, lat: float = 50.4) -> dict:
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


CLOSED_TRIANGLE = [[-4.8, 50.3], [-4.6, 50.3], [-4.6, 50.5], [-4.8, 50.3]]


# --- accepted --------------------------------------------------------------------------------


def test_a_circle_and_a_closed_triangle_are_both_accepted():
    assert validate_region_geometry(circle()) is not None
    assert validate_region_geometry(polygon(CLOSED_TRIANGLE)) is not None


def test_an_osm_boundary_keeps_its_provenance_properties():
    """`boundary_source` and the relation id ride along in `properties` — the validator must
    not strip what the ODbL attribution is keyed off."""
    feature = polygon(CLOSED_TRIANGLE)
    feature["properties"] |= {"boundary_source": "osm", "osm_relation_id": 148838}
    assert validate_region_geometry(feature)["properties"]["boundary_source"] == "osm"


# --- rejected --------------------------------------------------------------------------------


def test_a_missing_shape_discriminator_is_refused():
    feature = polygon(CLOSED_TRIANGLE)
    del feature["properties"]["shape"]
    with pytest.raises(ValueError, match="shape"):
        validate_region_geometry(feature)


def test_a_geometry_with_no_properties_at_all_is_refused():
    with pytest.raises(ValueError, match="properties"):
        validate_region_geometry(
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}}
        )


def test_a_negative_radius_is_refused():
    with pytest.raises(ValueError, match="greater than zero"):
        validate_region_geometry(circle(radius_m=-1))


def test_a_zero_radius_is_refused():
    """A circle of no size is not a region; it is a pin that has forgotten what it is."""
    with pytest.raises(ValueError, match="greater than zero"):
        validate_region_geometry(circle(radius_m=0))


def test_an_oversized_radius_is_refused():
    with pytest.raises(ValueError, match="at most"):
        validate_region_geometry(circle(radius_m=MAX_RADIUS_M + 1))


def test_a_circle_without_a_radius_is_refused():
    feature = circle()
    del feature["properties"]["radius_m"]
    with pytest.raises(ValueError, match="radius_m"):
        validate_region_geometry(feature)


def test_an_open_ring_is_refused():
    with pytest.raises(ValueError, match="closed"):
        validate_region_geometry(polygon([[-4.8, 50.3], [-4.6, 50.3], [-4.6, 50.5], [-4.7, 50.4]]))


def test_too_few_positions_are_refused():
    with pytest.raises(ValueError, match="at least"):
        validate_region_geometry(polygon([[0, 0], [1, 1], [0, 0]]))


def test_a_runaway_vertex_count_is_refused():
    ring = [[i / 1000, 50.0] for i in range(MAX_POLYGON_POINTS + 1)]
    ring.append(ring[0])
    with pytest.raises(ValueError, match="at most"):
        validate_region_geometry(polygon(ring))


def test_a_position_out_of_range_is_refused_as_a_swapped_pair():
    """`[50.4, -4.7]` is the Cornwall coordinate with its parts the wrong way round. Longitude
    50.4 is legal, so only the latitude check catches it — which is why the message names the
    order rather than the number."""
    with pytest.raises(ValueError, match="longitude first"):
        validate_region_geometry(circle(lng=200.0, lat=50.4))


def test_a_non_feature_is_refused():
    with pytest.raises(ValueError, match="Feature"):
        validate_region_geometry({"type": "Polygon", "coordinates": [CLOSED_TRIANGLE]})


# --- geometry iff region ------------------------------------------------------------------------


def test_a_region_needs_either_a_shape_or_a_boundary_query():
    with pytest.raises(ValidationError, match="boundary_query"):
        SuggestionCreate(type="region", title="Somewhere", lat=50.4, lng=-4.7)


def test_a_region_may_be_created_from_a_named_locality_alone():
    payload = SuggestionCreate(
        type="region", title="Cornwall", lat=50.4, lng=-4.7, boundary_query="Cornwall"
    )
    assert payload.geometry_geojson is None


def test_a_non_region_may_not_carry_a_geometry():
    with pytest.raises(ValidationError, match="only a region"):
        SuggestionCreate(
            type="accommodation",
            title="The Barn",
            lat=50.4,
            lng=-4.7,
            geometry_geojson=circle(),
        )


def test_coordinates_are_required_on_create():
    with pytest.raises(ValidationError):
        SuggestionCreate(type="activity", title="Surfing")


def test_a_patch_may_not_move_half_a_pin():
    with pytest.raises(ValidationError, match="together"):
        SuggestionUpdate(lat=50.4)


# --- the Places ToS, at the edge --------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "photos",
        "photo_reference",
        "rating",
        "user_ratings_total",
        "opening_hours",
        "formatted_phone_number",
        "website",
        "editorial_summary",
        "price_level",
        "business_status",
        "reviews",
    ],
)
def test_no_google_detail_field_can_be_sent_on_create(field):
    """`extra="forbid"` turns an inflated payload into a `422` rather than a stored licensing
    violation. The list is every field `design.md` > HARD INVARIANT names."""
    with pytest.raises(ValidationError):
        SuggestionCreate(
            type="accommodation",
            title="The Barn",
            lat=50.4,
            lng=-4.7,
            **{field: "anything at all"},
        )


@pytest.mark.parametrize("field", ["rating", "photos", "opening_hours", "website"])
def test_no_google_detail_field_can_hide_inside_the_place_snapshot(field):
    """The snapshot is the name and address *the user typed*. It is the most tempting place to
    smuggle Google's response into, which is why it forbids extras too."""
    with pytest.raises(ValidationError):
        PlaceSnapshot(name="The Barn", address="Dent", **{field: "anything at all"})


def test_the_suggestion_schemas_declare_no_google_detail_field():
    """A guard against the field being *added* rather than sent: if someone gives
    `SuggestionCreate` or `SuggestionOut` a `rating`, this fails on the next run."""
    from app.schemas.suggestion import SuggestionDetailOut, SuggestionOut

    forbidden = {
        "photos",
        "photo_reference",
        "rating",
        "user_ratings_total",
        "reviews",
        "opening_hours",
        "formatted_phone_number",
        "website",
        "editorial_summary",
        "price_level",
        "business_status",
    }
    for model in (SuggestionCreate, SuggestionUpdate, SuggestionOut, SuggestionDetailOut):
        assert not (set(model.model_fields) & forbidden), model.__name__
