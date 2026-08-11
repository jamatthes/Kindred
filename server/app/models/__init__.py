"""SQLAlchemy models.

Importing this package imports every model, which is what makes Alembic autogenerate see
the full metadata (``alembic/env.py`` imports this module for exactly that reason).
"""

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.family import FAMILY_ROLES, Family, FamilyMember
from app.models.session import LoginAttempt, Session
from app.models.setting import (
    SETTING_INSTANCE_NAME,
    SETTING_INVITE_ONLY,
    SETTING_REGISTRATION_OPEN,
    Setting,
)
from app.models.trip import STAGES, Trip
from app.models.user import THEME_PREFS, User, UserSettings

__all__ = [
    "FAMILY_ROLES",
    "SETTING_INSTANCE_NAME",
    "SETTING_INVITE_ONLY",
    "SETTING_REGISTRATION_OPEN",
    "STAGES",
    "THEME_PREFS",
    "Base",
    "Family",
    "FamilyMember",
    "LoginAttempt",
    "Session",
    "Setting",
    "TimestampMixin",
    "Trip",
    "UUIDPrimaryKeyMixin",
    "User",
    "UserSettings",
]
