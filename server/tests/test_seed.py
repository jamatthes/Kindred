"""Seed idempotency — F-5.

The seed runs on **every** boot, so "does not change anything the second time" is not a nice
property, it is the whole contract. The dangerous failure is not a duplicate row; it is
resetting an admin who has already chosen a password.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed import DEFAULT_SETTINGS, run_seed
from app.core.security import verify_password
from app.models import Setting, Trip, User, UserSettings


async def _counts(db: AsyncSession) -> tuple[int, int, int]:
    users = await db.scalar(select(func.count()).select_from(User))
    trips = await db.scalar(select(func.count()).select_from(Trip))
    settings_rows = await db.scalar(select(func.count()).select_from(Setting))
    return users, trips, settings_rows


async def test_first_run_creates_the_admin_the_trip_and_the_settings(
    db: AsyncSession,
) -> None:
    await run_seed()

    admin = await db.scalar(select(User))
    assert admin is not None
    assert admin.username == "admin"
    assert admin.is_platform_admin is True
    assert admin.must_change_password is True
    assert verify_password(admin.password_hash, "admin")

    trip = await db.scalar(select(Trip))
    assert trip is not None
    assert trip.stage == "planning"
    assert trip.owner_user_id == admin.id

    keys = set((await db.execute(select(Setting.key))).scalars().all())
    assert keys == set(DEFAULT_SETTINGS)

    # The seeded admin gets their settings row like any other user.
    assert await db.scalar(
        select(func.count()).select_from(UserSettings).where(UserSettings.user_id == admin.id)
    ) == 1


async def test_running_the_seed_repeatedly_changes_nothing(db: AsyncSession) -> None:
    await run_seed()
    before = await _counts(db)
    admin = await db.scalar(select(User))
    original_hash = admin.password_hash
    original_id = admin.id

    for _ in range(3):
        await run_seed()

    assert await _counts(db) == before

    await db.refresh(admin)
    assert admin.id == original_id
    assert admin.password_hash == original_hash


async def test_the_seed_does_not_undo_a_password_change(db: AsyncSession) -> None:
    """The failure this whole design exists to prevent (F-5)."""
    await run_seed()
    admin = await db.scalar(select(User))

    from app.core.security import hash_password

    admin.password_hash = hash_password("the-admins-own-password")
    admin.must_change_password = False
    await db.commit()

    await run_seed()

    await db.refresh(admin)
    assert admin.must_change_password is False
    assert verify_password(admin.password_hash, "the-admins-own-password")
    assert not verify_password(admin.password_hash, "admin")


async def test_the_seed_does_not_rename_a_renamed_instance(db: AsyncSession) -> None:
    await run_seed()

    row = await db.scalar(select(Setting).where(Setting.key == "instance_name"))
    row.value = "The Robinsons"
    await db.commit()

    await run_seed()

    await db.refresh(row)
    assert row.value == "The Robinsons"


async def test_no_admin_is_created_when_any_user_already_exists(db: AsyncSession) -> None:
    """Idempotency is defined by emptiness, so a renamed admin is not duplicated."""
    from tests.conftest import make_user

    await make_user(db, "someone-else", is_platform_admin=True)

    await run_seed()

    usernames = set((await db.execute(select(User.username))).scalars().all())
    assert usernames == {"someone-else"}
    # A trip is still created, and falls back to the existing platform admin as owner.
    trip = await db.scalar(select(Trip))
    assert trip is not None
    owner = await db.scalar(select(User).where(User.id == trip.owner_user_id))
    assert owner.username == "someone-else"


async def test_no_trip_is_created_when_one_already_exists(db: AsyncSession) -> None:
    from app.models import Trip as TripModel

    db.add(TripModel(name="Existing", stage="holiday", timezone="Europe/London"))
    await db.commit()

    await run_seed()

    trips = (await db.execute(select(TripModel))).scalars().all()
    assert len(trips) == 1
    assert trips[0].name == "Existing"
    # And the stage is left alone — the seed never touches an existing trip.
    assert trips[0].stage == "holiday"


async def test_the_seed_creates_no_family(db: AsyncSession) -> None:
    """`families` owns those tables; foundation leaves them empty on purpose."""
    from app.models import Family, FamilyMember

    await run_seed()

    assert await db.scalar(select(func.count()).select_from(Family)) == 0
    assert await db.scalar(select(func.count()).select_from(FamilyMember)) == 0
