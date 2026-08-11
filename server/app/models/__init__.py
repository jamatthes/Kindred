"""SQLAlchemy models.

Importing this package imports every model, which is what makes Alembic autogenerate see
the full metadata (``alembic/env.py`` imports this module for exactly that reason).
"""

from app.models.attachment import ATTACHMENT_SUBJECT_TYPES, Attachment
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.family import (
    FAMILY_ROLES,
    GEOCODE_STATUSES,
    INVITE_EXPIRY_CHOICES,
    LOCATION_BLOCKED_CONSENT,
    LOCATION_BLOCKED_FAMILY,
    LOCATION_BLOCKED_MEMBER,
    MAX_COLOR_SLOTS,
    Family,
    FamilyMember,
    Invite,
    invite_status,
    is_invite_usable,
    location_block_reason,
    next_free_color,
)
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
    "ATTACHMENT_SUBJECT_TYPES",
    "FAMILY_ROLES",
    "GEOCODE_STATUSES",
    "INVITE_EXPIRY_CHOICES",
    "LOCATION_BLOCKED_CONSENT",
    "LOCATION_BLOCKED_FAMILY",
    "LOCATION_BLOCKED_MEMBER",
    "MAX_COLOR_SLOTS",
    "SETTING_INSTANCE_NAME",
    "SETTING_INVITE_ONLY",
    "SETTING_REGISTRATION_OPEN",
    "STAGES",
    "THEME_PREFS",
    "Attachment",
    "Base",
    "Family",
    "FamilyMember",
    "Invite",
    "LoginAttempt",
    "Session",
    "Setting",
    "TimestampMixin",
    "Trip",
    "UUIDPrimaryKeyMixin",
    "User",
    "UserSettings",
    "invite_status",
    "is_invite_usable",
    "location_block_reason",
    "next_free_color",
]
