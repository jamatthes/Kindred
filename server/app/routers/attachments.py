"""Serving uploaded files (`families` FM-14; the table is `plan/architecture.md`'s).

**Avatars are readable by any member of the trip and by nobody else.** An unauthenticated
request is `401`, exactly like any other attachment — a profile picture is not public just
because it is small (`plan/features/families/design.md` > Serving).

The URL carries both the attachment id and the stored filename, and the filename is a hash of
the file's own bytes. Replacing an avatar therefore produces a different URL, so a long
`Cache-Control` is safe and nothing anywhere has to be invalidated. The filename in the path
is checked against the row rather than trusted, so it is an assertion about which rendition
is wanted, not a way to ask for a different file.
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response

from app.deps import DbDep, enforce_password_change, require_member
from app.models import Attachment
from app.schemas.common import ApiError

router = APIRouter(
    prefix="/attachments",
    tags=["attachments"],
    dependencies=[Depends(enforce_password_change), Depends(require_member)],
)

#: A year. Safe because the filename is a content hash: a changed file is a changed URL.
CACHE_CONTROL = "private, max-age=31536000, immutable"


@router.get("/{attachment_id}/{filename}", summary="Fetch an uploaded file")
async def read_attachment(
    attachment_id: uuid.UUID, filename: str, db: DbDep, request: Request
) -> Response:
    from app.services import attachments as store  # noqa: PLC0415 — settings read at call time

    attachment = await db.get(Attachment, attachment_id)
    if attachment is None:
        raise ApiError(404, "not_found", "That file does not exist.")

    # Which rendition, decided by matching the requested name against the row. An unmatched
    # name is a 404 rather than a silent fallback to the full size, so a stale URL fails
    # visibly instead of quietly serving the wrong image.
    for stored in (attachment.path, attachment.thumb_path):
        if stored and PurePosixPath(stored).name == filename:
            relative = stored
            break
    else:
        raise ApiError(404, "not_found", "That file does not exist.")

    try:
        path = store.absolute(relative)
    except ValueError:
        raise ApiError(404, "not_found", "That file does not exist.") from None
    if not path.is_file():
        raise ApiError(404, "not_found", "That file does not exist.")

    # The content hash *is* the ETag — there is no cheaper or more honest one available.
    etag = f'"{PurePosixPath(relative).stem}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": CACHE_CONTROL})

    return FileResponse(
        path,
        media_type=attachment.mime,
        headers={"Cache-Control": CACHE_CONTROL, "ETag": etag},
    )
