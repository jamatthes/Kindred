"""``suggestions`` — everything a family proposes for the trip, on the map and in the list.

**The Places Terms of Service invariant is a property of this table's column list.**
`plan/features/map-suggestions/design.md` > HARD INVARIANT: exactly one Google-derived value
is persisted, `place_id`. `place_snapshot_json` holds the name and address *as the user
accepted or edited them in the create form* — a record of what a human typed, not a copy of
Google's response — so that the card still renders something sensible when Places is
unavailable. There is deliberately **no** column here for a photo or photo reference, rating,
review count or text, opening hours, phone number, Google-sourced website, editorial summary,
price level or business status. Those are re-fetched live, in the browser, on card-open, and
never reach the server. Adding such a column is a licensing violation, not a schema change;
`tests/test_router_suggestions.py` asserts an inflated create payload lands none of them.

Two other rules are written down because they are invisible to a reader of the schema alone:

1. **`lat`/`lng` are NOT NULL, including for regions**, which store their centroid there — a
   circle's centre or a polygon's vertex average. That is what lets a region sort, select, and
   take a distance exactly like a pin, with no special-casing anywhere else in the system. The
   server recomputes the centroid on write rather than trusting the client, so the two can
   never disagree.
2. **Grouping is derived, never stored.** An activity or meal sitting at an accommodation is
   nested under it at query time (`app/services/suggestions.py`), on equal `place_id` or
   haversine proximity. No column, no join table: moving a pin re-groups automatically, which
   a stored parent link would not.

Every constraint below is mirrored from `alembic/versions/0001_schema.py`, per `CLAUDE.md`:
the suite builds its schema with ``create_all``, so a constraint declared in only one of the
two would be enforced in production and absent under pytest.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.comment import SUBJECT_SUGGESTION as _SUBJECT_SUGGESTION

if TYPE_CHECKING:
    from app.models.user import User

#: `suggestions.type`.
SUGGESTION_TYPES = ("region", "accommodation", "activity", "meal", "other")
TYPE_REGION = "region"
TYPE_ACCOMMODATION = "accommodation"
TYPE_ACTIVITY = "activity"
TYPE_MEAL = "meal"
#: Everything a trip actually contains that is none of the above — a shop, a viewpoint, a
#: friend's house, a place to park. Without it people file those under `activity` and the
#: type stops meaning anything; with it, "I don't know what this is" has an honest answer
#: rather than a wrong one.
TYPE_OTHER = "other"

#: The types that can be nested inside an accommodation's card (`design.md` > Grouping).
#: `other` groups too: a shop next to the cottage belongs on the cottage's card for the same
#: reason a restaurant does.
GROUPABLE_CHILD_TYPES = (TYPE_ACTIVITY, TYPE_MEAL, TYPE_OTHER)

#: `suggestions.status`.
SUGGESTION_STATUSES = ("proposed", "shortlisted", "approved", "scheduled", "rejected")
STATUS_PROPOSED = "proposed"
STATUS_SHORTLISTED = "shortlisted"
STATUS_APPROVED = "approved"
STATUS_SCHEDULED = "scheduled"
STATUS_REJECTED = "rejected"

#: The transition table from `design.md`, as data rather than as a chain of `if`s.
#:
#: `scheduled` appears as neither a source nor a target: `itinerary-timeline` sets it when a
#: suggestion is placed on a day, and `PATCH /{id}/status` rejects it with `422`. A scheduled
#: suggestion therefore has no status move available here at all, which is the point — the
#: itinerary is the only thing that may take it back out.
STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    STATUS_PROPOSED: (STATUS_SHORTLISTED, STATUS_APPROVED, STATUS_REJECTED),
    STATUS_SHORTLISTED: (STATUS_APPROVED, STATUS_REJECTED, STATUS_PROPOSED),
    STATUS_APPROVED: (STATUS_SHORTLISTED, STATUS_REJECTED, STATUS_PROPOSED),
    STATUS_REJECTED: (STATUS_PROPOSED,),
    STATUS_SCHEDULED: (),
}

#: `comments.subject_type` for a suggestion thread. Re-exported from `models/comment.py`, which
#: owns the polymorphic vocabulary, so the string is defined exactly once.
SUBJECT_SUGGESTION = _SUBJECT_SUGGESTION


def centroid(geometry: dict[str, Any] | None) -> tuple[float, float] | None:
    """The representative point of a region geometry, as `(lat, lng)`.

    Pure — no I/O, no database, no validation beyond what it needs to answer. Returns ``None``
    when the geometry is absent or unrecognisable, so the caller decides whether that is a
    `422` (creating a region) or simply "leave the point alone" (patching an accommodation).

    * **Circle** — a GeoJSON `Point` with `properties.radius_m`; the centroid is the point.
    * **Polygon** — the vertex average of the exterior ring, excluding the duplicated closing
      coordinate, which would otherwise weight one corner twice.

    GeoJSON stores coordinates as `[lng, lat]`, the reverse of Google's `LatLng`. This
    function is one of the two places in the server that knows that (the other is the schema
    validator); it returns `(lat, lng)` because that is the order every column, API field and
    Python caller in Kindred uses.
    """
    if not isinstance(geometry, dict):
        return None
    geom = geometry.get("geometry")
    if not isinstance(geom, dict):
        return None
    coordinates = geom.get("coordinates")

    if geom.get("type") == "Point":
        if not _is_position(coordinates):
            return None
        return float(coordinates[1]), float(coordinates[0])

    if geom.get("type") == "Polygon":
        if not isinstance(coordinates, list) or not coordinates:
            return None
        ring = coordinates[0]
        if not isinstance(ring, list) or len(ring) < 2:
            return None
        # Drop the closing coordinate when the ring is closed: averaging it would pull the
        # centroid towards whichever corner happens to be first.
        points = ring[:-1] if _same_position(ring[0], ring[-1]) else ring
        positions = [p for p in points if _is_position(p)]
        if not positions:
            return None
        lat = sum(float(p[1]) for p in positions) / len(positions)
        lng = sum(float(p[0]) for p in positions) / len(positions)
        return lat, lng

    return None


def _is_position(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and all(isinstance(part, (int, float)) and not isinstance(part, bool) for part in value[:2])
    )


def _same_position(a: object, b: object) -> bool:
    return _is_position(a) and _is_position(b) and a[0] == b[0] and a[1] == b[1]  # type: ignore[index]


class Suggestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "suggestions"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=STATUS_PROPOSED
    )
    #: Nullable so removing an account leaves the suggestion attributed to nobody rather than
    #: deleting a proposal the group may already have voted on — the same rule `comments` uses.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Always populated; for a region this is the centroid. See the module docstring.
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    #: ``none_as_null`` is load-bearing, not tidiness. Without it SQLAlchemy writes a Python
    #: ``None`` into a JSONB column as the JSON value ``null``, which is *not* SQL NULL — so
    #: `geometry_geojson IS NOT NULL` would be true for every accommodation, and
    #: `ck_suggestions_geometry_iff_region` would reject every non-region row ever inserted.
    #: Caught by `tests/test_service_suggestions.py` the first time a plain activity was saved.
    geometry_geojson: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    #: The **only** Google-derived value this table stores. Explicitly permitted to be cached
    #: indefinitely by the Places ToS; nothing else in the response is.
    place_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: User-authored name/address as entered. Never Google's details — see the module docstring.
    place_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Eager: every rendered suggestion needs its author's name, and a lazy load on an
    #: `AsyncSession` raises rather than fetching.
    author: Mapped[User | None] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_suggestions_trip_status", "trip_id", "status"),
        Index("ix_suggestions_trip_type", "trip_id", "type"),
        Index("ix_suggestions_place_id", "place_id"),
        CheckConstraint(f"type IN {SUGGESTION_TYPES}", name="ck_suggestions_type"),
        CheckConstraint(f"status IN {SUGGESTION_STATUSES}", name="ck_suggestions_status"),
        CheckConstraint(
            "(type = 'region') = (geometry_geojson IS NOT NULL)",
            name="ck_suggestions_geometry_iff_region",
        ),
    )

    @property
    def is_region(self) -> bool:
        return self.type == TYPE_REGION

    @property
    def boundary_source(self) -> str | None:
        """`"osm"` for a real administrative boundary, which the UI must attribute to
        OpenStreetMap contributors (ODbL). Null for a hand-drawn shape and for non-regions."""
        if not isinstance(self.geometry_geojson, dict):
            return None
        properties = self.geometry_geojson.get("properties")
        if not isinstance(properties, dict):
            return None
        source = properties.get("boundary_source")
        return source if isinstance(source, str) else None

    def centroid(self) -> tuple[float, float] | None:
        """This row's geometry reduced to a point. See the module-level :func:`centroid`."""
        return centroid(self.geometry_geojson)
