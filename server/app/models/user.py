"""``users`` and ``user_settings``.

Columns follow `plan/architecture.md` > Identity. `user_settings` is created here but its
columns belong to `holiday-stage` (`live_location_enabled`) and `pwa-push` (`push_enabled`);
foundation only guarantees the row exists for every user. Theme preference lives on
``users.theme_pref``, not here.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: Allowed values for ``users.theme_pref`` (F-7).
THEME_PREFS = ("light", "dark", "system")


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    theme_pref: Mapped[str] = mapped_column(String(16), nullable=False, server_default="system")
    locale: Mapped[str] = mapped_column(String(16), nullable=False, server_default="en-GB")
    is_platform_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
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
        unique=True,
    )
    live_location_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
