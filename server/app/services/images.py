"""Avatar processing (FM-14).

**The rule this module exists for:** every uploaded image is decoded and re-encoded
server-side, and *all* metadata is dropped in the re-encode — **GPS tags included**. A product
whose headline privacy promise is about location must not accept a photo carrying coordinates
and serve it back to the whole trip. Nothing here copies an EXIF block forward, and
`tests/test_avatar.py` asserts that on the decoded output rather than on the absence of an
error.

Four other things are decided here rather than left to the caller:

* **The type comes from the file's magic bytes**, never from the filename or the client's
  `Content-Type`. Both of those are attacker-controlled, and `.jpg` on a ZIP is the oldest
  trick there is.
* **Decoding is bounded** by dimensions and pixel count, so a decompression bomb — a few
  kilobytes that expand to gigabytes — fails with `422` instead of exhausting the container.
  The bound is applied from the header, before any pixels are read.
* **Animation is flattened to its first frame.** A moving avatar on a map marker is a
  distraction and defeats `prefers-reduced-motion`.
* **The original is not retained.** It is strictly larger than anything the product renders,
  and keeping it would mean keeping the metadata-bearing file we just stripped.

Renditions are named by a hash of their own bytes, so replacing an avatar changes the URL and
no cache anywhere has to be invalidated (`plan/features/families/design.md` > Serving).
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Protocol

from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.Image import DecompressionBombError

from app.schemas.common import ApiError

#: `plan/features/families/design.md`: "Maximum upload 8MB → `413 file_too_large` above it.
#: The limit is stated on screen before the picker opens, not only on failure."
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

#: The 256px rendition is `avatar_url` (profile page); the 64px is `avatar_thumb_url`, which
#: is what map markers and member lists actually load.
AVATAR_SIZE = 256
THUMB_SIZE = 64

#: Decode bounds. Generous enough for any phone camera, small enough that the worst case is
#: bounded: 100 megapixels of RGBA is ~400MB, and we refuse before allocating it.
MAX_DIMENSION = 12_000
MAX_PIXELS = 100_000_000

OUTPUT_MIME = "image/webp"

#: Sniffed from the first bytes of the file. `plan/features/families/design.md` fixes the
#: accepted set; anything else is `415` naming these three.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


@dataclass(frozen=True)
class Rendition:
    """One encoded image, named by the hash of its own bytes."""

    filename: str
    data: bytes
    size: int


@dataclass(frozen=True)
class AvatarRenditions:
    full: Rendition
    thumb: Rendition
    mime: str = OUTPUT_MIME


def unsupported_media_type() -> ApiError:
    return ApiError(
        415,
        "unsupported_media_type",
        "Profile pictures must be a JPEG, PNG or WebP image.",
    )


def file_too_large() -> ApiError:
    return ApiError(413, "file_too_large", "Profile pictures must be 8MB or smaller.")


def image_unreadable() -> ApiError:
    return ApiError(422, "image_unreadable", "That image could not be read.")


def sniff_mime(data: bytes) -> str | None:
    """The real type of ``data``, from its leading bytes, or ``None``.

    Deliberately not `mimetypes.guess_type` on a filename and not the multipart part's
    declared `Content-Type`: both are supplied by the client, and this check exists precisely
    because the client may be lying.
    """
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            return mime
    # WebP is RIFF-framed: "RIFF" + 4 length bytes + "WEBP".
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _encode(image: Image.Image, size: int) -> Rendition:
    """Centre-crop to a square, resize, and encode to WebP with no metadata at all."""
    square = ImageOps.fit(image, (size, size), method=Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    # No `exif=`, no `icc_profile=`, no `xmp=`. Pillow writes only what it is given, so the
    # strip is achieved by *not passing anything* — which is why it cannot be half-done.
    square.save(buffer, format="WEBP", quality=88, method=4)
    data = buffer.getvalue()
    digest = hashlib.sha256(data).hexdigest()[:32]
    return Rendition(filename=f"{digest}-{size}.webp", data=data, size=len(data))


class AvatarProcessorProtocol(Protocol):
    def process(self, data: bytes) -> AvatarRenditions:  # pragma: no cover - protocol
        ...


class AvatarProcessor:
    """The real pipeline. Synchronous and CPU-bound; it runs in FastAPI's threadpool."""

    def process(self, data: bytes) -> AvatarRenditions:
        if len(data) > MAX_UPLOAD_BYTES:
            raise file_too_large()
        if sniff_mime(data) is None:
            raise unsupported_media_type()

        try:
            with Image.open(io.BytesIO(data)) as probe:
                # Read the *header* first and refuse on the declared size, before any pixel
                # data is decoded. Checking after `load()` would be checking after the
                # allocation the check is meant to prevent.
                width, height = probe.size
                if (
                    width > MAX_DIMENSION
                    or height > MAX_DIMENSION
                    or width * height > MAX_PIXELS
                ):
                    raise image_unreadable()

                # Animated inputs: `seek(0)` pins the first frame, and everything after this
                # operates on that one frame.
                if getattr(probe, "n_frames", 1) > 1:
                    probe.seek(0)

                # EXIF rotation is applied to the *pixels* here, which is the only way the
                # orientation survives dropping the tag that recorded it.
                upright = ImageOps.exif_transpose(probe)
                flattened = upright.convert("RGB")
        except ApiError:
            raise
        except (
            DecompressionBombError,
            UnidentifiedImageError,
            OSError,
            ValueError,
            MemoryError,
        ) as cause:
            # A truncated file, a corrupt one, or a bomb. Pillow raises its own
            # `DecompressionBombError` from inside `open()`, before our header check can run,
            # so it is caught here rather than left to surface as a 500 — the user gets the
            # documented `422` whichever guard fires first.
            raise image_unreadable() from cause

        return AvatarRenditions(
            full=_encode(flattened, AVATAR_SIZE),
            thumb=_encode(flattened, THUMB_SIZE),
        )


def get_avatar_processor() -> AvatarProcessorProtocol:
    """FastAPI dependency, so a test can substitute a cheaper processor where the image
    handling is not what is under test."""
    return AvatarProcessor()


# Pillow's own bomb guard, set to our bound so a warning does not become an exception at some
# other threshold. Ours is checked first and produces the documented 422; this is the backstop.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
