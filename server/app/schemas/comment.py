"""Comment wire shapes, for the polymorphic `comments` table.

Polls was the first feature to render a thread, so it defined the shape; `voting-comments`
(M3) upgraded it in place with @mention parsing, mention notifications, and the soft-delete
that backs undo. The routes are shared: one implementation serves polls, suggestions and
itinerary items, which is why `subject_type` and `subject_id` are on the wire rather than
implied by a per-subject URL.

Two rules live here rather than in the router:

1. **`can_edit` / `can_delete` are computed server-side** and shipped on every comment. The
   frontend renders them; it never derives permission. `can_edit` is *author only, at every
   role including the trip's owner* — nobody edits another person's words under their name, so
   the permission does not exist rather than being withheld.
2. **`edited_at` is surfaced as well as `is_edited`.** The UI shows an "edited" marker, because
   an edit that left no trace would falsify the discussion record.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SubjectType = Literal["poll", "suggestion", "itinerary_item"]

#: `design.md`'s edge-case table: "Length cap enforced in the Pydantic schema (target 4000
#: chars) with a counter in the composer near the limit."
MAX_BODY_CHARS = 4000


class CommentOut(BaseModel):
    id: uuid.UUID
    subject_type: str
    subject_id: uuid.UUID
    #: Null when the author's account has been deleted. The comment survives attributed to
    #: nobody rather than vanishing and falsifying the thread.
    author_id: uuid.UUID | None = None
    author_name: str = "Someone who has left"
    family_id: uuid.UUID | None = None
    family_color: int | None = None
    family_color_custom: str | None = None
    body: str
    #: The uuids the body mentions **that are actually on this trip**. An off-trip or unknown
    #: uuid is absent here and renders as plain text, notifying nobody (V7).
    mentions: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime
    edited_at: datetime | None = None
    #: Computed per caller: the author, and nobody else, at any role.
    can_edit: bool = False
    #: Computed per caller: the author, the head or spouse of the author's family, or an
    #: organiser.
    can_delete: bool = False

    @property
    def is_edited(self) -> bool:
        return self.edited_at is not None


class CommentIn(BaseModel):
    """The body-only shape `polls` posts and patches with. Kept because a thread hung off a
    subject-specific URL already knows its subject."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=MAX_BODY_CHARS)


class CommentCreate(CommentIn):
    """The generic form: the subject travels in the body because one set of routes serves all
    three subject types.

    The pair is validated against the database on every path — `subject_id` has no foreign key,
    so "does this subject exist, and is it on a trip you belong to" is a mandatory check rather
    than a courtesy (`services/comments.py::verify_subject_access`).
    """

    model_config = ConfigDict(extra="forbid")

    subject_type: SubjectType
    subject_id: uuid.UUID


class CommentUpdate(CommentIn):
    """Body only. There is deliberately no `subject_type`/`subject_id`: a comment cannot be
    moved to another subject, and an edit that could would be a way to smuggle a thread from
    one trip into another."""


class CommentListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: SubjectType
    subject_id: uuid.UUID
