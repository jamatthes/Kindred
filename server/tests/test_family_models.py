"""Phase 2 — the two model helpers, and the constraints the migration promised.

`next_free_color` and `is_invite_usable` are small enough to look obviously correct and are
tested anyway, because both encode a rule stated in prose somewhere else: "lowest free slot,
eight maximum" (`plan/features/families/requirements.md` FM-1 and Out of scope) and "usable
when `used_by is null and revoked_at is null and expires_at > now()`"
(`plan/features/families/design.md`). A helper that drifts from its prose is exactly the bug
that survives review.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Family, FamilyMember, Invite, Trip, next_free_color
from app.models.family import MAX_COLOR_SLOTS, is_invite_usable, invite_status
from tests.conftest import add_member, make_family, make_user

NOW = datetime(2027, 1, 14, 12, 0, tzinfo=UTC)


def _invite(**overrides) -> Invite:
    """An unsaved, usable invite. Overrides make exactly one thing wrong at a time."""
    values = {
        "expires_at": NOW + timedelta(days=7),
        "used_by": None,
        "used_at": None,
        "revoked_at": None,
    }
    values.update(overrides)
    return Invite(**values)


# --- next_free_color ---------------------------------------------------------------------


async def test_first_family_on_a_trip_gets_slot_one(db: AsyncSession, trip: Trip) -> None:
    assert await next_free_color(db, trip.id) == 1


async def test_taken_slots_are_skipped(db: AsyncSession, trip: Trip) -> None:
    await make_family(db, trip, "Ones", color=1)
    await make_family(db, trip, "Twos", color=2)
    assert await next_free_color(db, trip.id) == 3


async def test_a_gap_is_reused_before_a_higher_slot(db: AsyncSession, trip: Trip) -> None:
    """Lowest-first, not next-highest: a family that leaves frees its colour again."""
    await make_family(db, trip, "Ones", color=1)
    await make_family(db, trip, "Threes", color=3)
    assert await next_free_color(db, trip.id) == 2


async def test_all_eight_taken_returns_none(db: AsyncSession, trip: Trip) -> None:
    for slot in range(1, MAX_COLOR_SLOTS + 1):
        await make_family(db, trip, f"Family {slot}", color=slot)
    assert await next_free_color(db, trip.id) is None


async def test_slots_are_counted_per_trip_not_globally(db: AsyncSession, trip: Trip) -> None:
    """`CLAUDE.md`: the schema is multi-trip. A second trip starts from slot 1 again."""
    await make_family(db, trip, "Ones", color=1)
    other = Trip(name="Another trip", stage="planning", timezone="Europe/London")
    db.add(other)
    await db.commit()
    assert await next_free_color(db, other.id) == 1


# --- is_invite_usable --------------------------------------------------------------------


def test_a_fresh_invite_is_usable() -> None:
    assert is_invite_usable(_invite(), now=NOW) is True


def test_a_used_invite_is_not_usable() -> None:
    assert is_invite_usable(_invite(used_by=uuid_sentinel(), used_at=NOW), now=NOW) is False


def test_a_revoked_invite_is_not_usable() -> None:
    assert is_invite_usable(_invite(revoked_at=NOW), now=NOW) is False


def test_an_expired_invite_is_not_usable() -> None:
    assert is_invite_usable(_invite(expires_at=NOW - timedelta(seconds=1)), now=NOW) is False


def test_expiry_is_exclusive_at_the_instant_it_lapses() -> None:
    assert is_invite_usable(_invite(expires_at=NOW), now=NOW) is False


def test_a_missing_invite_is_not_usable() -> None:
    """An unknown token resolves to ``None``; the caller must not have to special-case it."""
    assert is_invite_usable(None, now=NOW) is False


def test_a_naive_expiry_is_read_as_utc() -> None:
    """A raw driver round-trip can hand back a naive value; it must not raise."""
    naive = (NOW + timedelta(days=1)).replace(tzinfo=None)
    assert is_invite_usable(_invite(expires_at=naive), now=NOW) is True


# --- invite_status -----------------------------------------------------------------------


def test_status_reports_the_fact_the_admin_acted_on() -> None:
    """A revoked invite that has also expired reads as `revoked`, not `expired`."""
    stale_and_revoked = _invite(expires_at=NOW - timedelta(days=1), revoked_at=NOW)
    assert invite_status(stale_and_revoked, now=NOW) == "revoked"
    assert invite_status(_invite(), now=NOW) == "active"
    assert invite_status(_invite(used_by=uuid_sentinel()), now=NOW) == "used"
    assert invite_status(_invite(expires_at=NOW - timedelta(days=1)), now=NOW) == "expired"


# --- the constraints migration 0002 promised ---------------------------------------------


async def test_a_user_can_only_belong_to_one_family(db: AsyncSession, trip: Trip) -> None:
    """The unique index on `family_members.user_id`, exercised through the ORM.

    A second membership row would corrupt every permission check, so this is enforced in the
    database rather than only in application code (`plan/features/families/design.md`).
    """
    user = await make_user(db, "doubled")
    first = await make_family(db, trip, "First", color=1)
    second = await make_family(db, trip, "Second", color=2)
    await add_member(db, first, user)

    db.add(FamilyMember(family_id=second.id, user_id=user.id, role="member"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_two_families_cannot_share_a_colour_on_one_trip(
    db: AsyncSession, trip: Trip
) -> None:
    await make_family(db, trip, "Ones", color=1)
    db.add(Family(trip_id=trip.id, name="Also ones", color=1))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_family_defaults_match_the_documented_policy(
    db: AsyncSession, trip: Trip
) -> None:
    """A family that never opens its settings behaves as the product did before they existed.

    `plan/features/families/design.md`: allowed on the map, each member off until they say
    otherwise.
    """
    family = await make_family(db, trip, "Defaults", color=1)
    await db.refresh(family)
    assert family.location_sharing_allowed is True
    assert family.member_location_default is False
    assert family.geocode_status == "pending"
    assert family.home_placed is False


def uuid_sentinel():
    """A stand-in user id for the unsaved-invite cases above."""
    import uuid

    return uuid.uuid4()
