"""First-run seed. Idempotent — it runs on every boot.

Idempotency is defined by *emptiness*, not by "is there a user called admin": if any user
exists the admin is not created, and if any trip exists no trip is created. That is what
makes a restart harmless after the admin has renamed themselves or changed their password
(F-5: "restarting the stack does not reset an admin who has already changed their password").
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionFactory
from app.core.security import hash_password
from app.models import (
    DEFAULT_VOTING_MODES,
    SETTING_INSTANCE_NAME,
    SETTING_INVITE_ONLY,
    SETTING_REGISTRATION_OPEN,
    Setting,
    Trip,
    TripCategorySetting,
    User,
    UserSettings,
)

logger = logging.getLogger(__name__)

#: Seeded once, then owned by `admin-console`. Values are JSON.
DEFAULT_SETTINGS: dict[str, Any] = {
    SETTING_INSTANCE_NAME: "Kindred",
    SETTING_REGISTRATION_OPEN: False,
    SETTING_INVITE_ONLY: True,
}

DEFAULT_TRIP_NAME = "Our trip"


async def _seed_admin(db: AsyncSession) -> User | None:
    existing = await db.scalar(select(func.count()).select_from(User))
    if existing:
        return None
    name = settings.seed_admin_username.strip().title()
    user = User(
        username=settings.seed_admin_username.strip().lower(),
        password_hash=hash_password(settings.seed_admin_password),
        # A mononym, deliberately: the seeded account is "Admin", not a person, and the
        # initials rule (`families` FM-14) already covers an empty last name with a
        # one-letter badge. The real name is set on the profile page after first login.
        first_name=name,
        last_name="",
        display_name=name,
        is_platform_admin=True,
        # The seeded password is published in .env.example. The account is unusable for
        # anything else until it is changed.
        must_change_password=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserSettings(user_id=user.id))
    await db.flush()
    logger.info("Seeded platform admin %r (must_change_password=true).", user.username)
    return user


async def _seed_trip(db: AsyncSession, owner: User | None) -> Trip | None:
    existing = await db.scalar(select(func.count()).select_from(Trip))
    if existing:
        return None
    if owner is None:
        # No trip but users already exist: fall back to the first platform admin so the trip
        # has an owner, since `require_main_admin` accepts `trips.owner_user_id`.
        owner = await db.scalar(
            select(User).where(User.is_platform_admin.is_(True)).order_by(User.created_at).limit(1)
        )
    trip = Trip(
        name=DEFAULT_TRIP_NAME,
        stage="planning",
        owner_user_id=owner.id if owner else None,
        timezone=settings.tz,
    )
    db.add(trip)
    await db.flush()
    await seed_category_settings(db, trip)
    logger.info("Seeded trip %r in stage 'planning'.", trip.name)
    return trip


async def seed_category_settings(db: AsyncSession, trip: Trip) -> None:
    """Give a trip all five voting-mode rows.

    Called at trip creation so no read ever has to invent a default and no voting UI ever
    renders a blank control (`admin-console` AC-5). ``ON CONFLICT DO NOTHING`` makes it safe
    to call on a trip that already has some or all of them, which is what the console's
    self-healing read relies on.
    """
    for category, mode in DEFAULT_VOTING_MODES.items():
        await db.execute(
            pg_insert(TripCategorySetting)
            .values(trip_id=trip.id, category=category, voting_mode=mode)
            .on_conflict_do_nothing(
                index_elements=[TripCategorySetting.trip_id, TripCategorySetting.category]
            )
        )


async def _seed_settings(db: AsyncSession) -> None:
    """Insert the default rows, leaving any existing value alone.

    ``ON CONFLICT DO NOTHING`` rather than an upsert: these are defaults for a fresh install,
    and an admin who has renamed the instance must not have it renamed back on restart.
    """
    for key, value in DEFAULT_SETTINGS.items():
        await db.execute(
            pg_insert(Setting)
            .values(key=key, value=value)
            .on_conflict_do_nothing(index_elements=[Setting.key])
        )


async def run_seed() -> None:
    """Seed the database. Safe to call on every startup."""
    async with SessionFactory() as db:
        async with db.begin():
            admin = await _seed_admin(db)
            await _seed_trip(db, admin)
            await _seed_settings(db)
