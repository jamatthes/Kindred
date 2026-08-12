"""Comment wire shapes, for the polymorphic `comments` table.

Polls is the first feature to render a thread, so it defines the shape; `voting-comments`
(M3) upgrades it in place with @mention parsing and mention notifications. **No @mention
handling here** — `plan/features/polls/requirements.md` PL-11 is explicit that polls ships a
plain thread and M3 upgrades it, and building half a mention parser now would be something
that feature then has to unpick.

`edited_at` is surfaced as `is_edited` as well as the timestamp: the UI shows an "edited"
marker, because an edit that left no trace would falsify the discussion record.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    created_at: datetime
    edited_at: datetime | None = None
    #: Computed per caller: their own, or an organiser's, who may delete anyone's.
    can_edit: bool = False
    can_delete: bool = False

    @property
    def is_edited(self) -> bool:
        return self.edited_at is not None


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4000)
