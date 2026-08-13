"""Suggestion wire shapes.

**NO GOOGLE-SOURCED DETAIL FIELD BELONGS IN THIS FILE, EVER.**
`plan/features/map-suggestions/design.md` > HARD INVARIANT. Google's Places Terms of Service
forbid persisting Place Details content, so the server persists exactly one Google-derived
value — `place_id` — plus user-authored fields. There is no photo, photo reference, rating,
review count or text, opening-hours, phone number, Google-sourced website, editorial summary,
price level or business-status field in any request or response model here, and adding one
would be a licensing violation rather than a feature. `place_snapshot` is the name and address
**as the user accepted or edited them in the create form** — a record of what a human typed.
Details flow browser → Google → browser; the server never proxies or stores them.

Four other rules are decided here rather than per endpoint, because each would otherwise be
re-implemented and drift:

1. **Geometry iff region.** A region without a shape is unrenderable, and a shape on an
   accommodation is a shape nothing would ever draw. Enforced at the edge *and* by a database
   check constraint, so neither a bad client nor a bad service call can write one.
2. **The API speaks GeoJSON coordinate order — `[lng, lat]` — throughout.** The conversion to
   Google's `LatLng` happens once, in the web map wrapper. `lat`/`lng` *fields* are named, and
   therefore unambiguous; only positions inside `geometry_geojson` are ordered.
3. **`status` is not patchable through `SuggestionUpdate`.** It has its own endpoint with its
   own permission (organiser) and its own transition table; leaving it out of the general patch
   model, with `extra="forbid"`, means a member who tries is told rather than silently ignored.
4. **Capability flags (`can_edit`, `can_delete`, `can_change_status`) are computed
   server-side** and shipped on the response, matching `schemas/poll.py`. The frontend renders
   them; it never derives permission.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.suggestion import SUGGESTION_STATUSES, SUGGESTION_TYPES
from app.schemas.comment import CommentOut
from app.schemas.distance import DistanceOut as _DistanceOut

SuggestionType = Literal["region", "accommodation", "activity", "meal", "other"]
SuggestionStatus = Literal["proposed", "shortlisted", "approved", "scheduled", "rejected"]
#: The subset `PATCH /{id}/status` accepts. `scheduled` is deliberately absent from the type —
#: only `itinerary-timeline` sets it — and is additionally rejected with a named `422` below,
#: so the client gets an explanation rather than a generic enum error.
SettableStatus = Literal["proposed", "shortlisted", "approved", "rejected"]

SortKey = Literal[
    "votes_asc",
    "votes_desc",
    "distance_asc",
    "distance_desc",
    "category_asc",
    "category_desc",
    "created_asc",
    "created_desc",
]

#: `design.md`: "`radius_m` must be positive and is clamped to a sane maximum (target 200 km)
#: to prevent a whole-globe circle".
MAX_RADIUS_M = 200_000.0

#: The vertex budget for a stored polygon ring.
#:
#: NOTE (deviation, recorded in `design.md`): the design document names two different caps —
#: "Douglas-Peucker to a sane vertex budget, target ≤ 500 points" for OSM boundaries, and "a
#: vertex-count cap (target 200)" in the edge-case table for a runaway hand-drawn shape. They
#: cannot both govern this validator: 200 would reject the very boundaries the same document
#: instructs the server to fetch and store, since `services/boundaries.py` simplifies to 500.
#: The larger number wins, and matches `boundaries.MAX_RING_POINTS`.
MAX_POLYGON_POINTS = 500

#: A closed ring needs at least a triangle: three distinct corners plus the repeated first.
MIN_POLYGON_POINTS = 4

SHAPE_CIRCLE = "circle"
SHAPE_POLYGON = "polygon"


# --- geometry ----------------------------------------------------------------------------------


def validate_region_geometry(value: Any) -> dict[str, Any]:
    """The region-geometry encoding from `design.md`, enforced in one place.

    Raises `ValueError` (which FastAPI renders as a field-level `422`) rather than returning a
    flag, so an invalid shape can never reach the database: the drawing stays on screen for
    correction, and the row is never half-written.
    """
    if not isinstance(value, dict):
        raise ValueError("geometry must be a GeoJSON Feature object")
    if value.get("type") != "Feature":
        raise ValueError("geometry must be a GeoJSON Feature")

    geometry = value.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError("geometry.geometry must be a GeoJSON geometry object")

    properties = value.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("geometry.properties is required")
    shape = properties.get("shape")
    if shape not in (SHAPE_CIRCLE, SHAPE_POLYGON):
        raise ValueError("geometry.properties.shape must be 'circle' or 'polygon'")

    if shape == SHAPE_CIRCLE:
        if geometry.get("type") != "Point":
            raise ValueError("a circle region is a GeoJSON Point carrying properties.radius_m")
        _require_position(geometry.get("coordinates"))
        radius = properties.get("radius_m")
        if not isinstance(radius, (int, float)) or isinstance(radius, bool):
            raise ValueError("geometry.properties.radius_m is required for a circle")
        if radius <= 0:
            raise ValueError("geometry.properties.radius_m must be greater than zero")
        if radius > MAX_RADIUS_M:
            raise ValueError(
                f"geometry.properties.radius_m must be at most {int(MAX_RADIUS_M)} metres"
            )
        return value

    if geometry.get("type") != "Polygon":
        raise ValueError("a polygon region is a GeoJSON Polygon")
    rings = geometry.get("coordinates")
    if not isinstance(rings, list) or not rings:
        raise ValueError("polygon coordinates must be a list of rings")
    ring = rings[0]
    if not isinstance(ring, list):
        raise ValueError("polygon coordinates must be a list of rings")
    if len(ring) < MIN_POLYGON_POINTS:
        raise ValueError(
            f"a polygon ring needs at least {MIN_POLYGON_POINTS} positions "
            "(a closed triangle is the smallest shape)"
        )
    if len(ring) > MAX_POLYGON_POINTS:
        raise ValueError(f"a polygon ring may have at most {MAX_POLYGON_POINTS} positions")
    for position in ring:
        _require_position(position)
    if list(ring[0][:2]) != list(ring[-1][:2]):
        raise ValueError("a polygon ring must be closed — the first and last positions match")
    return value


def _require_position(value: Any) -> None:
    """A GeoJSON position: `[lng, lat]`, in that order, in range."""
    if (
        not isinstance(value, (list, tuple))
        or len(value) < 2
        or any(isinstance(part, bool) or not isinstance(part, (int, float)) for part in value[:2])
    ):
        raise ValueError("each position must be a [lng, lat] pair of numbers")
    lng, lat = float(value[0]), float(value[1])
    if not -180.0 <= lng <= 180.0 or not -90.0 <= lat <= 90.0:
        raise ValueError("each position must be [lng, lat] — longitude first, both in range")


# --- nested shapes -----------------------------------------------------------------------------


class PlaceSnapshot(BaseModel):
    """The name and address **as the user accepted or edited them**. Not Google's response.

    `extra="forbid"`: a client that tries to smuggle a rating or an opening-hours blob in here
    gets a `422` rather than a silently stored ToS violation.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=500)


class SuggestionAuthorOut(BaseModel):
    """Who proposed it, and the family colour their pin is accented with."""

    user_id: uuid.UUID | None = None
    display_name: str
    family_id: uuid.UUID | None = None
    family_color: int | None = None
    family_color_custom: str | None = None


class VoteSummaryOut(BaseModel):
    """The tally as the list row and the popover card render it.

    Deliberately the *aggregate* only. The side panel — which also shows attribution and the
    outstanding list — asks `GET /suggestions/{id}/votes` for the full `TallyOut`; fetching
    every voter for every row of a list that displays none of them would be the same N+1 in
    aggregate form. The two are computed from the same rules (`services/votes.py`), so a row
    and a panel can never disagree about whether somebody voted.
    """

    #: The suggestion's category mode, derived from `trip_category_settings` — never stored.
    mode: Literal["score", "thumbs"] = "score"
    #: How many votes are usable in the **active** mode. Not how many rows exist: after a switch
    #: to score voting, a stored thumb counts for nothing here, because no honest number can be
    #: made from it.
    count: int = 0
    #: Null when nobody has voted. **Never 0.0** — the same honesty rule as `poll_stats`.
    average: float | None = None
    up: int = 0
    down: int = 0
    #: A stored 5 read in thumbs mode: neither camp, and rounding it into one would invent an
    #: opinion the voter did not express.
    unclear: int = 0
    #: True when any part of this summary was derived from votes cast in the other mode. The UI
    #: must label it, so a converted score is never passed off as a genuine thumbs vote.
    converted: bool = False
    my_vote: int | None = None
    my_thumb: Literal["up", "down"] | None = None


#: One family's home-to-here distance. **Imported, not redefined**: `distances` (M3) owns the
#: shape, and two classes with the same name and slightly different fields is how a chip in the
#: list and a chip in the panel end up disagreeing about what `is_estimate` means.
DistanceOut = _DistanceOut


# --- requests ---------------------------------------------------------------------------------


class SuggestionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: SuggestionType
    title: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    geometry_geojson: dict[str, Any] | None = None
    place_id: str | None = Field(default=None, max_length=255)
    place_snapshot: PlaceSnapshot | None = None
    external_url: str | None = Field(default=None, max_length=2000)
    #: A named locality to fetch a real administrative boundary for ("Cornwall"), instead of
    #: supplying a drawn `geometry_geojson`. Regions only. One server-side Nominatim call at
    #: creation (`design.md` > Named-locality regions); the result is stored forever and never
    #: re-fetched on render, per the API-cost rule.
    boundary_query: str | None = Field(default=None, max_length=200)

    @field_validator("geometry_geojson")
    @classmethod
    def _geometry_is_well_formed(cls, value: dict | None) -> dict | None:
        return validate_region_geometry(value) if value is not None else None

    @model_validator(mode="after")
    def _geometry_iff_region(self) -> SuggestionCreate:
        if self.type == "region":
            if self.geometry_geojson is None and not self.boundary_query:
                raise ValueError(
                    "a region needs a drawn geometry_geojson or a boundary_query to look up"
                )
        elif self.geometry_geojson is not None or self.boundary_query:
            raise ValueError("only a region carries a geometry")
        return self


class SuggestionUpdate(BaseModel):
    """No `status`. See the module docstring — it has its own endpoint and its own permission."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)
    type: SuggestionType | None = None
    external_url: str | None = Field(default=None, max_length=2000)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    geometry_geojson: dict[str, Any] | None = None
    place_id: str | None = Field(default=None, max_length=255)
    place_snapshot: PlaceSnapshot | None = None

    @field_validator("geometry_geojson")
    @classmethod
    def _geometry_is_well_formed(cls, value: dict | None) -> dict | None:
        return validate_region_geometry(value) if value is not None else None

    @model_validator(mode="after")
    def _coordinates_come_as_a_pair(self) -> SuggestionUpdate:
        """Half a coordinate is not a location — the same rule `OptionCreateIn` applies."""
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat and lng must be given together, or not at all")
        return self


class SuggestionStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SettableStatus
    #: Optimistic concurrency, for the case `voting-comments/design.md` names: "two admins act
    #: on status simultaneously — the server validates against the *current* status; the loser
    #: gets `409` with the current status, and the client re-renders from
    #: `suggestion.status_changed`". The admin controls send the status they were rendered
    #: against; when it no longer matches, the second organiser is told what happened instead of
    #: silently overwriting a decision they never saw. Optional, so a caller that does not care
    #: about the race (a script, a retry) simply omits it.
    expected_status: SuggestionStatus | None = None


class SuggestionListParams(BaseModel):
    """`GET /suggestions`' query string, as one object.

    Declared as a model even though FastAPI could take the parameters loose, because the map
    and the list share this filter state and a second reader (`voting-comments`' "needs my
    vote" view) should inherit the same defaults rather than re-deriving them.
    """

    model_config = ConfigDict(extra="forbid")

    type: list[SuggestionType] = Field(default_factory=list)
    status: list[SuggestionStatus] = Field(default_factory=list)
    family_id: list[uuid.UUID] = Field(default_factory=list)
    sort: SortKey = "created_desc"
    #: Nest activities and meals inside the accommodation they sit at. The map turns this off:
    #: every child still draws its own pin, offset so it stays clickable.
    group: bool = True
    #: Rejected suggestions stay in the record and out of the way — a rejection is not a
    #: deletion, and asking for them back is one filter chip.
    include_rejected: bool = False


class LinkPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2000)


class LinkPreviewOut(BaseModel):
    """`200` body of `POST /link-preview`. Every field is optional and `204` is the normal
    outcome for a site that blocks scraping — see `services/link_preview.py`.

    This is **not** a Places response and never carries one: the preview comes from the page
    the user pasted, not from Google.
    """

    title: str | None = None
    description: str | None = None
    image_url: str | None = None
    site_name: str | None = None
    #: Airbnb-aware bonus fields, best-effort — absent is normal, never an error.
    facts: str | None = None
    locality: str | None = None
    lat: float | None = None
    lng: float | None = None
    capacity: int | None = None


# --- responses ---------------------------------------------------------------------------------


class SuggestionOut(BaseModel):
    """The single item shape, used by the list, the map, and the detail read.

    One shape for both views on purpose: map and list are two renderers over one dataset
    (`requirements.md` S2), and two shapes would let them disagree about what a suggestion is.
    """

    id: uuid.UUID
    trip_id: uuid.UUID
    type: SuggestionType
    title: str
    notes: str | None = None
    status: SuggestionStatus
    created_by: SuggestionAuthorOut
    lat: float
    lng: float
    geometry_geojson: dict[str, Any] | None = None
    #: `"osm"` when the outline came from OpenStreetMap, which the UI must attribute (ODbL).
    boundary_source: str | None = None
    place_id: str | None = None
    place_snapshot: PlaceSnapshot | None = None
    external_url: str | None = None
    vote_summary: VoteSummaryOut = Field(default_factory=VoteSummaryOut)
    comment_count: int = 0
    distances: list[DistanceOut] = Field(default_factory=list)
    #: One level only. A child is an activity or meal at an accommodation; a child of a child
    #: is not a thing (`design.md` > Grouping).
    children: list[SuggestionOut] = Field(default_factory=list)
    can_edit: bool = False
    can_delete: bool = False
    can_change_status: bool = False
    created_at: datetime
    updated_at: datetime


SuggestionOut.model_rebuild()


class SuggestionDetailOut(SuggestionOut):
    """`GET /suggestions/{id}` — the list shape plus the thread.

    Still no Google details: the browser fetches photos, hours and ratings itself on card-open
    and never sends them back.
    """

    comments: list[CommentOut] = Field(default_factory=list)


# Kept last so a reader who skims to the bottom of the file still meets the invariant.
assert set(SUGGESTION_TYPES) == set(SuggestionType.__args__)  # type: ignore[attr-defined]
assert set(SUGGESTION_STATUSES) == set(SuggestionStatus.__args__)  # type: ignore[attr-defined]
