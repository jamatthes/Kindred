"""``attachments`` — every uploaded file the product serves.

`plan/architecture.md` lists this table under Platform: photos on suggestions, check-ins and
the archive, and **profile pictures** (`subject_type = 'user'`, referenced back from
`users.avatar_attachment_id`). `families` is the feature that first needs it, so migration
`0002` creates it — see the NOTE in `plan/features/families/design.md`.

Two columns beyond the set `architecture.md` names, both recorded there as additions:

* ``thumb_path`` — avatars emit two renditions (256px and 64px) and `MemberOut` exposes both,
  so the small one needs a home. Nullable: a subject that emits one file leaves it null.
* ``byte_size`` — what was actually written after re-encoding, which is not the size of the
  upload and is the only number worth reporting to an operator.

**Every file behind a row here has been re-encoded server-side with all metadata dropped,
GPS included** (`plan/architecture.md`; FM-14). That is a property of the write path in
`app/services/images.py`, not of this table — stated here because this is where a future
reader looks first.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: ``attachments.subject_type``. Only `user` is written in M1; the rest arrive with the
#: features that own them, and are listed so the column's domain is visible in one place.
ATTACHMENT_SUBJECT_TYPES = ("user", "suggestion", "checkin")


class Attachment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "attachments"

    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Nullable so a file can be written before the row it belongs to exists. For avatars it
    #: is the user's id and is always set.
    subject_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    uploader_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Path relative to ``ATTACHMENTS_DIR``. Never absolute: the volume moves between the
    #: container and the host, and an absolute path stored in the database would not survive.
    path: Mapped[str] = mapped_column(Text, nullable=False)
    #: The small rendition, when the subject emits one.
    thumb_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("ix_attachments_subject", "subject_type", "subject_id"),)
