"""Phase 3 — the serialisers, and the two things they are allowed to say to whom.

These are the tests `plan/features/families/tasks.md` names for this phase. They matter more
than most schema tests, because the address rule and the consent rule are *privacy*
guarantees: a serialiser that leaks is not a cosmetic bug, and it is invisible in the UI of
the person it leaks to.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attachment, Family, Trip, User
from app.schemas.family import (
    FamilyDetailOut,
    MemberOut,
    Viewer,
    derive_display_name,
    family_detail_out,
    family_out,
    initials,
    member_out,
)
from app.schemas.invite import InviteAcceptIn, InvitePreviewOut
from tests.conftest import add_member, make_family, make_user


def _viewer(
    user: User,
    *,
    family: Family | None = None,
    role: str | None = None,
    main_admin: bool = False,
) -> Viewer:
    return Viewer(
        user_id=user.id,
        family_id=family.id if family else None,
        is_main_admin=main_admin,
        is_family_admin=role == "admin",
    )


def _person(first: str, last: str = "") -> User:
    return User(
        id=uuid.uuid4(),
        username="x",
        password_hash="x",
        first_name=first,
        last_name=last,
        display_name=f"{first} {last}".strip(),
    )


# --- initials ----------------------------------------------------------------------------


def test_initials_are_first_letter_of_each_name() -> None:
    assert initials(_person("Ada", "Lovelace")) == "AL"


def test_a_mononym_gets_one_letter_not_a_placeholder() -> None:
    """FM-14: "With a single name, one letter." Not an error state."""
    assert initials(_person("Mum")) == "M"


def test_initials_are_uppercased() -> None:
    assert initials(_person("ada", "lovelace")) == "AL"


def test_initials_take_a_grapheme_cluster_not_a_code_point() -> None:
    """A base letter plus its combining mark is one character to the person named.

    Decomposed "Ångström": U+0041 followed by U+030A. Taking one code point would give a
    bare "A" and silently drop the ring — the same class of bug as slicing a byte.
    """
    decomposed = _person("Ångström", "Österberg")
    assert initials(decomposed) == "ÅÖ".upper()


def test_initials_handle_a_non_latin_script() -> None:
    """Devanagari: the vowel sign belongs to the letter it follows."""
    assert initials(_person("किरण", "शर्म")) == (
        "किश"
    )


def test_a_whitespace_only_name_does_not_crash() -> None:
    assert initials(_person("  ", "  ")) == ""


# --- display name ------------------------------------------------------------------------


def test_display_name_is_derived_from_both_names() -> None:
    assert derive_display_name("Ada", "Lovelace") == "Ada Lovelace"


def test_display_name_of_a_mononym_has_no_trailing_space() -> None:
    assert derive_display_name("Mum", "") == "Mum"


# --- the address rule ---------------------------------------------------------------------


@pytest.fixture
async def placed_family(db: AsyncSession, trip: Trip) -> tuple[Family, User]:
    """A family with a fully geocoded home, and one member of it."""
    family = await make_family(db, trip, "Parkers", color=1)
    user = await make_user(db, "parker")
    await add_member(db, family, user, role="admin")
    family.home_address = "12 Elm Row, Bristol BS1 4AA"
    family.home_lat = 51.4545
    family.home_lng = -2.5879
    family.home_locality = "Bristol"
    family.home_geocoded_at = datetime.now(UTC)
    family.geocode_status = "ok"
    await db.commit()
    await db.refresh(family)
    return family, user


ADDRESS_KEYS = ("home_address", "home_lat", "home_lng", "home_geocoded_at")


def _keys(detail: FamilyDetailOut) -> set[str]:
    """What the client actually receives — `exclude_unset` is the whole mechanism."""
    return set(detail.model_dump(exclude_unset=True))


async def test_a_member_of_the_family_sees_the_full_address(
    db: AsyncSession, placed_family: tuple[Family, User]
) -> None:
    family, user = placed_family
    detail = family_detail_out(family, _viewer(user, family=family, role="admin"))
    assert ADDRESS_KEYS <= tuple(_keys(detail)) or set(ADDRESS_KEYS) <= _keys(detail)
    assert detail.home_address == "12 Elm Row, Bristol BS1 4AA"


async def test_the_main_admin_sees_any_familys_full_address(
    db: AsyncSession, placed_family: tuple[Family, User], main_admin: User
) -> None:
    family, _ = placed_family
    detail = family_detail_out(family, _viewer(main_admin, main_admin=True))
    assert set(ADDRESS_KEYS) <= _keys(detail)
    assert detail.home_lat == pytest.approx(51.4545)


async def test_another_familys_member_gets_no_address_key_at_all(
    db: AsyncSession, trip: Trip, placed_family: tuple[Family, User]
) -> None:
    """Absent, not null. A null would still say "there is an address and you cannot have it"."""
    family, _ = placed_family
    other_family = await make_family(db, trip, "Riveras", color=2)
    outsider = await make_user(db, "rivera")
    await add_member(db, other_family, outsider, role="admin")

    detail = family_detail_out(family, _viewer(outsider, family=other_family, role="admin"))
    assert _keys(detail).isdisjoint(ADDRESS_KEYS)


async def test_the_locality_is_still_shown_to_everyone(
    db: AsyncSession, trip: Trip, placed_family: tuple[Family, User]
) -> None:
    """FM-4: other members see the coarse town, never the street."""
    family, _ = placed_family
    other_family = await make_family(db, trip, "Riveras", color=2)
    outsider = await make_user(db, "rivera")
    await add_member(db, other_family, outsider)

    detail = family_detail_out(family, _viewer(outsider, family=other_family))
    assert detail.home_locality == "Bristol"
    assert detail.home_placed is True


async def test_the_coarse_family_shape_never_carries_an_address(
    db: AsyncSession, placed_family: tuple[Family, User]
) -> None:
    """`FamilyOut` is what the socket broadcasts to the whole trip room."""
    family, _ = placed_family
    payload = family_out(family).model_dump()
    assert set(payload).isdisjoint(ADDRESS_KEYS)
    assert payload["home_locality"] == "Bristol"


# --- the consent rule ---------------------------------------------------------------------


@pytest.fixture
async def sharing_family(db: AsyncSession, trip: Trip) -> tuple[Family, User, User]:
    """A family whose ordinary member has consented to share their location."""
    family = await make_family(db, trip, "Jiangs", color=3)
    admin = await make_user(db, "jiangadmin")
    sharer = await make_user(db, "jiangsharer")
    await add_member(db, family, admin, role="admin")
    await add_member(db, family, sharer, role="member")
    settings = sharer.settings
    settings.live_location_enabled = True
    await db.commit()
    await db.refresh(family)
    return family, admin, sharer


def _member_named(detail: FamilyDetailOut, username: str) -> MemberOut:
    return next(m for m in detail.members if m.username == username)


async def test_their_own_family_admin_sees_a_members_consent(
    sharing_family: tuple[Family, User, User],
) -> None:
    family, admin, _ = sharing_family
    detail = family_detail_out(family, _viewer(admin, family=family, role="admin"))
    assert _member_named(detail, "jiangsharer").location_sharing_enabled is True


async def test_a_member_sees_their_own_consent(
    sharing_family: tuple[Family, User, User],
) -> None:
    family, _, sharer = sharing_family
    detail = family_detail_out(family, _viewer(sharer, family=family, role="member"))
    assert _member_named(detail, "jiangsharer").location_sharing_enabled is True


async def test_a_plain_member_cannot_see_a_siblings_consent(
    sharing_family: tuple[Family, User, User],
) -> None:
    """Only the member, their family admin, and the main admin. Not the rest of the family."""
    family, admin, sharer = sharing_family
    detail = family_detail_out(family, _viewer(sharer, family=family, role="member"))
    assert _member_named(detail, "jiangadmin").location_sharing_enabled is None


async def test_another_familys_admin_sees_no_consent_at_all(
    db: AsyncSession, trip: Trip, sharing_family: tuple[Family, User, User]
) -> None:
    """A member of another family sees a marker or no marker, and cannot tell why."""
    family, _, _ = sharing_family
    other = await make_family(db, trip, "Riveras", color=4)
    stranger = await make_user(db, "stranger")
    await add_member(db, other, stranger, role="admin")

    detail = family_detail_out(family, _viewer(stranger, family=other, role="admin"))
    assert all(m.location_sharing_enabled is None for m in detail.members)


async def test_the_main_admin_sees_consent_in_any_family(
    sharing_family: tuple[Family, User, User], main_admin: User
) -> None:
    family, _, _ = sharing_family
    detail = family_detail_out(family, _viewer(main_admin, main_admin=True))
    assert _member_named(detail, "jiangsharer").location_sharing_enabled is True


async def test_the_family_admin_is_listed_first(
    sharing_family: tuple[Family, User, User],
) -> None:
    family, admin, _ = sharing_family
    detail = family_detail_out(family, _viewer(admin, family=family, role="admin"))
    assert detail.members[0].username == "jiangadmin"
    assert detail.member_count == 2


async def test_an_avatar_is_served_from_both_renditions(
    db: AsyncSession, trip: Trip
) -> None:
    family = await make_family(db, trip, "Withpics", color=5)
    user = await make_user(db, "haspic")
    await add_member(db, family, user, role="admin")
    attachment = Attachment(
        subject_type="user",
        subject_id=user.id,
        uploader_id=user.id,
        path="avatars/abc123.webp",
        thumb_path="avatars/abc123-64.webp",
        mime="image/webp",
    )
    db.add(attachment)
    await db.flush()
    user.avatar_attachment_id = attachment.id
    await db.commit()
    # Expire everything and re-read. The `User` already in the identity map has its `avatar`
    # relationship loaded as null from before the id was set, and an eager loader does not
    # overwrite what is already there. Ids are captured first because touching an expired
    # attribute would trigger a lazy refresh outside the async context.
    family_id, user_id = family.id, user.id
    db.expire_all()
    family = await db.get(Family, family_id)

    viewer = Viewer(
        user_id=user_id, family_id=family_id, is_main_admin=False, is_family_admin=True
    )
    detail = family_detail_out(family, viewer)
    member = detail.members[0]
    assert member.avatar_url.endswith("/abc123.webp")
    assert member.avatar_thumb_url.endswith("/abc123-64.webp")


async def test_no_avatar_leaves_both_urls_null_and_initials_standing(
    sharing_family: tuple[Family, User, User],
) -> None:
    """FM-14: the badge has no broken state — without a picture there are initials."""
    family, admin, _ = sharing_family
    detail = family_detail_out(family, _viewer(admin, family=family, role="admin"))
    member = detail.members[0]
    assert member.avatar_url is None and member.avatar_thumb_url is None
    assert member.initials == "J"


# --- the accept body ----------------------------------------------------------------------


def test_the_accept_body_refuses_a_family_name() -> None:
    """FM-13: the family is named on the setup screen, not on the join form.

    Rejected rather than ignored, so a client that sends one is told, instead of quietly
    creating an account whose family never gets the name its owner typed.
    """
    with pytest.raises(ValidationError) as caught:
        InviteAcceptIn(
            username="new",
            first_name="New",
            password="pw",
            password_confirm="pw",
            family_name="The Newtons",
        )
    assert "family_name" in str(caught.value)


def test_the_accept_body_refuses_a_display_name() -> None:
    with pytest.raises(ValidationError):
        InviteAcceptIn(
            username="new",
            first_name="New",
            password="pw",
            password_confirm="pw",
            display_name="Newt",
        )


def test_the_accept_body_requires_the_passwords_to_match() -> None:
    with pytest.raises(ValidationError):
        InviteAcceptIn(
            username="new", first_name="New", password="pw", password_confirm="typo"
        )


def test_last_name_is_optional_and_defaults_to_empty() -> None:
    body = InviteAcceptIn(
        username="new", first_name="Mum", password="pw", password_confirm="pw"
    )
    assert body.last_name == ""
    assert derive_display_name(body.first_name, body.last_name) == "Mum"


def test_a_short_password_is_accepted_because_foundation_sets_no_minimum() -> None:
    """F-5: no minimum length. This is foundation's rule, restated here so a future
    tightening has to change a test that says why."""
    InviteAcceptIn(username="new", first_name="New", password="a", password_confirm="a")


# --- the public preview -------------------------------------------------------------------


def test_an_invalid_preview_cannot_be_built_with_trip_details() -> None:
    """The guard rail described in `schemas/invite.py`: invalid reveals nothing but the
    instance name, which is already public on `GET /settings`."""
    with pytest.raises(ValidationError):
        InvitePreviewOut(
            instance_name="Kindred", valid=False, reason="used", trip_name="Cornwall"
        )


def test_an_invalid_preview_with_only_a_reason_is_fine() -> None:
    preview = InvitePreviewOut(instance_name="Kindred", valid=False, reason="unknown")
    assert preview.family_name is None and preview.trip_name is None
