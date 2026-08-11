"""``users`` and ``user_settings``.

Columns follow `plan/architecture.md` > Identity. `user_settings` is created here but its
columns belong to `holiday-stage` (`live_location_enabled`) and `pwa-push` (`push_enabled`);
foundation only guarantees the row exists for every user. Theme preference lives on
``users.theme_pref``, not here.
"""

from __future__ import annotations

import uuid

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.attachment import Attachment

#: Allowed values for ``users.theme_pref`` (F-7).
THEME_PREFS = ("light", "dark", "system")


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Collected at registration (FM-7). The map badge is initials and its hover label is a
    #: full name; neither can be derived reliably from one free-text field, which is why the
    #: name is stored in parts as well as whole (`plan/features/families/design.md`).
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    #: **Not null, empty when absent.** Nullable-by-emptiness rather than nullable, so the
    #: initials rule is total: a mononym gets a one-letter badge, which is correct rather than
    #: a degraded case every call site has to handle.
    last_name: Mapped[str] = mapped_column(String(80), nullable=False, server_default="")
    #: Seeded to `"{first_name} {last_name}".strip()` at registration and separately editable
    #: thereafter, so someone who goes by a nickname can say so without breaking their badge.
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: The profile picture (FM-14). The image itself is an `attachments` row with
    #: `subject_type = 'user'`; this column makes resolving it a join the API already makes
    #: rather than a lookup by subject on every member row.
    avatar_attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # `users` and `attachments` reference each other (an attachment records its uploader),
        # so one side has to be added after both tables exist. `use_alter` with the migration's
        # own constraint name is what lets `create_all`/`drop_all` order them at all.
        ForeignKey(
            "attachments.id",
            ondelete="SET NULL",
            name="fk_users_avatar_attachment_id",
            use_alter=True,
        ),
        nullable=True,
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    theme_pref: Mapped[str] = mapped_column(String(16), nullable=False, server_default="system")
    locale: Mapped[str] = mapped_column(String(16), nullable=False, server_default="en-GB")
    is_platform_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    #: Null until the first successful login. `admin-console` AC-6 asks whether a person has
    #: ever got in, which `created_at` cannot answer: an invited account that was never used
    #: looks identical to one used daily. Written by foundation's login route.
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Eager, and with an explicit ``foreign_keys``: `attachments` points back at `users`
    #: through `uploader_id`, so there are two paths between the tables and SQLAlchemy cannot
    #: pick one for us. Loading it here means `MemberOut` can emit an avatar URL without a
    #: query per member row.
    avatar: Mapped[Attachment | None] = relationship(
        lazy="joined", foreign_keys=[avatar_attachment_id]
    )
    #: The user's own settings row, including `live_location_enabled` — their **consent** to
    #: share a location, which no admin may write (`plan/features/families/design.md`). Eager
    #: because `MemberOut` reports it to entitled callers and a lazy load on an
    #: `AsyncSession` would raise rather than fetch.
    settings: Mapped[UserSettings | None] = relationship(
        lazy="joined", uselist=False, back_populates="user"
    )

    __table_args__ = (
        # Usernames are compared case-insensitively; a functional unique index gives us that
        # without depending on the `citext` extension being installed.
        Index("ix_users_username_lower", func.lower(username), unique=True),
    )


class UserSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    user: Mapped[User] = relationship(back_populates="settings")
    #: **Consent**, written only by the member themselves. `families` reads it and never
    #: writes it for anyone else; the single exception is the one-time seed from
    #: `families.member_location_default` at the moment a membership row is created.
    live_location_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # Exactly one settings row per user, named so `create_all` and the migration agree.
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_settings_user_id"),)
