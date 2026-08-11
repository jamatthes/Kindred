"""Phase 7 — the profile endpoints and the avatar pipeline.

The assertion that matters is the metadata strip, and it is made **on the decoded output**
rather than on the absence of an error: a pipeline that silently failed to strip would raise
nothing at all, so "the request succeeded" proves precisely nothing about it. The input here
is a real JPEG carrying real GPS EXIF, built in-process, and both renditions are re-opened and
inspected afterwards.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
import piexif
import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attachment, Family, Trip, User
from app.services import attachments as store
from app.services.images import AvatarProcessor, sniff_mime
from tests.conftest import login_as

ME = "/api/v1/me"
AVATAR = f"{ME}/avatar"


@pytest.fixture(autouse=True)
def attachments_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write uploads to a temp directory, never the configured volume."""
    monkeypatch.setattr(
        "app.core.config.settings.attachments_dir", str(tmp_path), raising=False
    )
    return tmp_path


# --- fixtures that build real images -------------------------------------------------------


def jpeg_with_gps(size: tuple[int, int] = (900, 600)) -> bytes:
    """A JPEG carrying GPS coordinates, an orientation tag, and a description.

    The GPS is 51°27'N 2°35'W — Bristol. If any of this survives into a rendition, the
    product has republished the location of the person who took the photo, which is the exact
    failure FM-14 exists to prevent.
    """
    image = Image.new("RGB", size, (200, 120, 90))
    exif = {
        "0th": {
            piexif.ImageIFD.Orientation: 6,  # rotated 90°, so the pixels must move
            piexif.ImageIFD.Make: b"Kindred Test Camera",
            piexif.ImageIFD.ImageDescription: b"taken at home",
        },
        "Exif": {},
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLatitude: ((51, 1), (27, 1), (0, 1)),
            piexif.GPSIFD.GPSLongitudeRef: b"W",
            piexif.GPSIFD.GPSLongitude: ((2, 1), (35, 1), (0, 1)),
        },
        "1st": {},
        "thumbnail": None,
    }
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=piexif.dump(exif))
    return buffer.getvalue()


def plain_png(size: tuple[int, int] = (300, 300)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (30, 90, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def zip_pretending_to_be_a_jpeg() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("payload.txt", "not an image")
    return buffer.getvalue()


def decompression_bomb() -> bytes:
    """A small PNG that declares an enormous canvas.

    A flat colour compresses to almost nothing, so this is a few kilobytes on the wire and
    would be gigabytes decoded. The pipeline must refuse it from the header, before it
    allocates.
    """
    buffer = io.BytesIO()
    Image.new("L", (20_000, 20_000), 0).save(buffer, format="PNG")
    return buffer.getvalue()


# --- the pipeline, directly ----------------------------------------------------------------


def test_every_scrap_of_metadata_is_dropped_including_gps() -> None:
    """The assertion this whole file exists for."""
    renditions = AvatarProcessor().process(jpeg_with_gps())

    for rendition in (renditions.full, renditions.thumb):
        with Image.open(io.BytesIO(rendition.data)) as out:
            assert out.format == "WEBP"
            # No EXIF block at all — not "an EXIF block with the GPS removed".
            assert not out.getexif()
            assert out.info.get("exif") in (None, b"")
            assert "icc_profile" not in out.info
            assert "xmp" not in out.info
        # And nothing recognisable survives in the bytes themselves.
        assert b"Kindred Test Camera" not in rendition.data
        assert b"taken at home" not in rendition.data


def test_the_exif_rotation_is_applied_to_the_pixels() -> None:
    """Dropping the orientation tag without moving the pixels would leave every phone photo
    on its side. The tag goes; the rotation it described stays."""
    tall = AvatarProcessor().process(jpeg_with_gps(size=(900, 300)))
    with Image.open(io.BytesIO(tall.full.data)) as out:
        assert out.size == (256, 256)  # square regardless of the input's shape


def test_both_renditions_are_square_webp_at_the_documented_sizes() -> None:
    renditions = AvatarProcessor().process(plain_png(size=(1200, 400)))
    with Image.open(io.BytesIO(renditions.full.data)) as full:
        assert full.size == (256, 256)
    with Image.open(io.BytesIO(renditions.thumb.data)) as thumb:
        assert thumb.size == (64, 64)
    assert renditions.mime == "image/webp"


def test_the_filename_is_a_hash_of_the_bytes() -> None:
    """Replacing an avatar changes the URL, so no cache anywhere has to be invalidated."""
    first = AvatarProcessor().process(plain_png())
    same = AvatarProcessor().process(plain_png())
    different = AvatarProcessor().process(jpeg_with_gps())
    assert first.full.filename == same.full.filename
    assert first.full.filename != different.full.filename


def test_a_zip_renamed_to_jpg_is_refused() -> None:
    """The type comes from magic bytes; the filename is the client's opinion."""
    with pytest.raises(Exception) as caught:
        AvatarProcessor().process(zip_pretending_to_be_a_jpeg())
    assert caught.value.detail["code"] == "unsupported_media_type"


def test_a_decompression_bomb_is_refused_without_decoding_it() -> None:
    payload = decompression_bomb()
    assert len(payload) < 1_000_000  # small on the wire, enormous decoded
    with pytest.raises(Exception) as caught:
        AvatarProcessor().process(payload)
    assert caught.value.detail["code"] == "image_unreadable"


def test_a_truncated_image_is_unreadable_not_a_crash() -> None:
    with pytest.raises(Exception) as caught:
        AvatarProcessor().process(plain_png()[:40])
    assert caught.value.detail["code"] == "image_unreadable"


def test_an_oversized_upload_is_refused_before_decoding() -> None:
    with pytest.raises(Exception) as caught:
        AvatarProcessor().process(b"\xff\xd8\xff" + b"\0" * (9 * 1024 * 1024))
    assert caught.value.detail["code"] == "file_too_large"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"\xff\xd8\xff\xe0rest", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"GIF89a", None),
        (b"PK\x03\x04", None),
        (b"", None),
    ],
)
def test_the_sniffer_knows_the_three_accepted_formats(payload: bytes, expected) -> None:
    assert sniff_mime(payload) == expected


# --- through the API -------------------------------------------------------------------------


async def test_uploading_an_avatar_returns_both_urls(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, _ = family_admin
    await login_as(client, db, user)
    response = await client.put(
        AVATAR, files={"file": ("me.jpg", jpeg_with_gps(), "image/jpeg")}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["avatar_url"] and body["avatar_thumb_url"]
    assert body["avatar_url"] != body["avatar_thumb_url"]
    assert body["avatar_url"].startswith("/api/v1/attachments/")


async def test_the_served_file_carries_no_metadata_either(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    """End to end: what a browser actually receives is what the pipeline produced."""
    user, _ = family_admin
    await login_as(client, db, user)
    body = (
        await client.put(AVATAR, files={"file": ("me.jpg", jpeg_with_gps(), "image/jpeg")})
    ).json()

    fetched = await client.get(body["avatar_url"])
    assert fetched.status_code == 200
    assert fetched.headers["cache-control"].startswith("private, max-age=31536000")
    with Image.open(io.BytesIO(fetched.content)) as out:
        assert not out.getexif()
    assert b"Kindred Test Camera" not in fetched.content


async def test_an_attachment_is_not_public(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    """A profile picture is not public just because it is small."""
    user, _ = family_admin
    await login_as(client, db, user)
    url = (
        await client.put(AVATAR, files={"file": ("me.png", plain_png(), "image/png")})
    ).json()["avatar_url"]

    from app.main import app  # noqa: PLC0415

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as anon:
        assert (await anon.get(url)).status_code == 401


async def test_a_matching_etag_is_answered_304(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, _ = family_admin
    await login_as(client, db, user)
    url = (
        await client.put(AVATAR, files={"file": ("me.png", plain_png(), "image/png")})
    ).json()["avatar_url"]

    first = await client.get(url)
    again = await client.get(url, headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


async def test_replacing_an_avatar_leaves_one_row_and_no_orphan_file(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    attachments_dir: Path,
) -> None:
    user, _ = family_admin
    await login_as(client, db, user)

    first = (
        await client.put(AVATAR, files={"file": ("a.png", plain_png(), "image/png")})
    ).json()
    second = (
        await client.put(AVATAR, files={"file": ("b.jpg", jpeg_with_gps(), "image/jpeg")})
    ).json()

    assert first["avatar_url"] != second["avatar_url"]
    assert await db.scalar(select(func.count()).select_from(Attachment)) == 1
    # Two renditions of one avatar, and nothing left over from the first.
    assert len(list((attachments_dir / store.AVATAR_DIR).iterdir())) == 2


async def test_removing_an_avatar_goes_back_to_initials(
    client: httpx.AsyncClient,
    db: AsyncSession,
    family_admin: tuple[User, Family],
    attachments_dir: Path,
) -> None:
    user, _ = family_admin
    await login_as(client, db, user)
    await client.put(AVATAR, files={"file": ("a.png", plain_png(), "image/png")})

    removed = await client.delete(AVATAR)
    assert removed.status_code == 200
    assert removed.json()["avatar_url"] is None
    assert removed.json()["initials"] == "F"
    assert await db.scalar(select(func.count()).select_from(Attachment)) == 0
    assert not list((attachments_dir / store.AVATAR_DIR).iterdir())


async def test_a_zip_renamed_to_jpg_is_refused_over_the_wire(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, _ = family_admin
    await login_as(client, db, user)
    response = await client.put(
        AVATAR,
        files={"file": ("photo.jpg", zip_pretending_to_be_a_jpeg(), "image/jpeg")},
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_media_type"


async def test_a_nine_megabyte_upload_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, _ = family_admin
    await login_as(client, db, user)
    response = await client.put(
        AVATAR,
        files={"file": ("huge.jpg", b"\xff\xd8\xff" + b"\0" * (9 * 1024 * 1024), "image/jpeg")},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "file_too_large"


async def test_a_bomb_is_refused_over_the_wire(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, _ = family_admin
    await login_as(client, db, user)
    response = await client.put(
        AVATAR, files={"file": ("bomb.png", decompression_bomb(), "image/png")}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "image_unreadable"


# --- the profile itself -----------------------------------------------------------------------


async def test_changing_a_name_updates_the_badge(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    user, _ = family_admin
    await login_as(client, db, user)
    body = (
        await client.patch(ME, json={"first_name": "Ada", "last_name": "Lovelace"})
    ).json()
    assert body["initials"] == "AL"
    assert body["first_name"] == "Ada"


async def test_the_display_name_is_separately_editable(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    """FM-11: a member who goes by something other than their given name can say so without
    breaking their initials."""
    user, _ = family_admin
    await login_as(client, db, user)
    await client.patch(ME, json={"first_name": "Ada", "last_name": "Lovelace"})
    body = (await client.patch(ME, json={"display_name": "Ada L."})).json()
    assert body["display_name"] == "Ada L."
    assert body["initials"] == "AL"


async def test_clearing_the_display_name_falls_back_rather_than_erroring(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    """They cleared a field; they did not ask for an error, and nobody should end up with no
    label anywhere."""
    user, _ = family_admin
    await login_as(client, db, user)
    await client.patch(ME, json={"first_name": "Ada", "last_name": "Lovelace"})
    body = (await client.patch(ME, json={"display_name": "   "})).json()
    assert body["display_name"] == "Ada Lovelace"


async def test_the_username_cannot_be_changed_here(
    client: httpx.AsyncClient, db: AsyncSession, family_admin: tuple[User, Family]
) -> None:
    """Not editable in v1. Ignored rather than honoured — the field does not exist."""
    user, _ = family_admin
    await login_as(client, db, user)
    body = (await client.patch(ME, json={"username": "someoneelse"})).json()
    assert body["username"] == "familyadmin"


# --- the stage exemption ------------------------------------------------------------------------


async def test_the_profile_and_avatar_survive_the_end_stage(
    client: httpx.AsyncClient,
    db: AsyncSession,
    trip: Trip,
    family_admin: tuple[User, Family],
) -> None:
    """Freezing a trip must not freeze someone's face.

    The contrast is the point: the same session, in the same stage, is refused by a family
    route and allowed by these.
    """
    user, family = family_admin
    trip.stage = "end"
    await db.commit()
    await login_as(client, db, user)

    assert (await client.patch(ME, json={"first_name": "Ada"})).status_code == 200
    assert (
        await client.put(AVATAR, files={"file": ("a.png", plain_png(), "image/png")})
    ).status_code == 200
    assert (await client.delete(AVATAR)).status_code == 200
    assert (await client.patch(ME + "/preferences", json={"theme_pref": "dark"})).status_code == 200

    frozen = await client.patch(f"/api/v1/families/{family.id}", json={"name": "Nope"})
    assert frozen.status_code == 409
    assert frozen.json()["detail"]["code"] == "stage_forbidden"
