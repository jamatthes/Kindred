"""Distance wire shapes.

**An estimate carries `distance_m` only and never a fabricated `duration_s`.** That is the
rule this file exists to make structural. A haversine straight line has a defensible length and
no defensible driving time — inventing one by dividing by an assumed speed would put a made-up
number on a card people plan around, and `plan/design-system.md`'s honesty rules apply to
numbers on cards exactly as they do to charts. So an estimate renders as "~48 km away, driving
time pending", and `duration_s` stays null until Google answers.

**`no_home` is a presentation state, not a stored one.** `distance_cache.status` has four
values — `pending` / `ok` / `no_route` / `failed` — and a family with no geocoded home has no
row in that table at all. The API reports such a family as `no_home` so the UI can offer that
family's head the address form, rather than dropping them from the list and leaving somebody to
wonder why their household is missing. **Do not add `no_home` to the check constraint**; see
`app/models/distance.py`, which says the same thing where a reader of the schema would look.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: The four stored statuses plus the one derived at read time.
DistanceStatus = Literal["pending", "ok", "no_route", "failed", "no_home"]


class DistanceOut(BaseModel):
    """One family's distance to one suggestion.

    `is_estimate` is the field every consumer must branch on: `true` means the number came from
    a straight line computed in SQL, not from Google, and the UI must mark it as approximate.
    """

    family_id: uuid.UUID
    family_name: str
    family_color: int | None = None
    family_color_custom: str | None = None
    status: DistanceStatus
    #: **Null whenever `is_estimate` is true.** Enforced below, not merely intended.
    duration_s: int | None = None
    #: Null only for `no_route` (there is no distance along a route that does not exist) and
    #: `no_home` (there is nowhere to measure from).
    distance_m: int | None = None
    is_estimate: bool = False
    #: When Google answered. Null for an estimate, and for a pair nobody has computed. Never
    #: used as a freshness check — a distance between two fixed points does not go stale.
    computed_at: datetime | None = None

    @model_validator(mode="after")
    def _an_estimate_never_carries_a_duration(self) -> DistanceOut:
        """The honesty rule, enforced at the edge.

        A `ValueError` here is a 500 rather than a 422, and deliberately so: this can only be
        tripped by server code, and the right outcome is a loud failure in tests rather than a
        plausible-looking fabricated duration reaching somebody's card.
        """
        if self.is_estimate and self.duration_s is not None:
            raise ValueError(
                "an estimate carries a distance only — there is no defensible driving time "
                "for a straight line"
            )
        return self


class SuggestionDistancesOut(BaseModel):
    """`GET /suggestions/{id}/distances`. Ordered with the caller's own family first."""

    suggestion_id: uuid.UUID
    distances: list[DistanceOut] = Field(default_factory=list)


class BulkDistancesParams(BaseModel):
    """`GET /distances`' query string.

    Exists so switching the list's sort perspective to another family refetches distances alone
    rather than re-requesting every suggestion (`design.md`'s NOTE under the endpoint).
    """

    model_config = ConfigDict(extra="forbid")

    suggestion_ids: list[uuid.UUID] = Field(default_factory=list)
    #: Restricts the response to one family's values for a lighter payload. Omitted means every
    #: family, which is what the side panel's expander needs.
    family_id: uuid.UUID | None = None


class BulkDistancesOut(BaseModel):
    """A map of `suggestion_id -> distances[]`, so rendering fifty rows costs one request."""

    distances: dict[uuid.UUID, list[DistanceOut]] = Field(default_factory=dict)


class RecomputeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Omit to recompute the whole trip.
    suggestion_id: uuid.UUID | None = None


class RecomputeOut(BaseModel):
    """Returned **before** the work runs, so the UI can state the cost.

    An organiser pressing "recompute" on a trip with sixty suggestions and six families should
    be told it is roughly six chunked calls and not three hundred and sixty — and should be told
    *before* the calls happen, which is why this is the response rather than a summary
    afterwards.
    """

    queued_pairs: int = 0
    estimated_api_calls: int = 0
