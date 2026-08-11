"""``settings`` — key/value platform config, singleton rows (F-12).

Foundation seeds `instance_name`, `registration_open`, `invite_only` and exposes the public
read. `admin-console` owns writing them and adds the `google_api_status` key, whose value is
a JSON object — hence ``JSONB`` rather than text.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: Keys seeded by foundation. `admin-console` owns editing them.
SETTING_INSTANCE_NAME = "instance_name"
SETTING_REGISTRATION_OPEN = "registration_open"
SETTING_INVITE_ONLY = "invite_only"


class Setting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    #: JSON so a value can be a string, a bool or a nested object (`google_api_status`).
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
