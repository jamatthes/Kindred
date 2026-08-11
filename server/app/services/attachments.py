"""Where uploaded files live on disk.

`plan/architecture.md` bind-mounts `data/attachments` so the owner can see their own files in
a file browser. Paths stored in `attachments.path` are therefore **relative to
`ATTACHMENTS_DIR`**, never absolute: the same row is read by the API container (where the
directory is `/data/attachments`) and by host-side tooling (where it is not), and an absolute
path would be right in exactly one of those places.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Subdirectory for profile pictures, so an operator looking at the volume can tell what they
#: are looking at without consulting the database.
AVATAR_DIR = "avatars"


def root() -> Path:
    return Path(settings.attachments_dir)


def absolute(relative: str) -> Path:
    """Resolve a stored path, refusing anything that escapes the attachments root.

    The stored value is always written by this module, so traversal should be impossible —
    but this function is what a *serving* route calls with a value that has been round-tripped
    through the database, and "impossible" is a claim worth checking on the read side too.
    """
    base = root().resolve()
    candidate = (base / relative).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(f"attachment path escapes the attachments root: {relative!r}")
    return candidate


def write(relative: str, data: bytes) -> None:
    path = absolute(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def delete(relative: str | None) -> None:
    """Remove a file, tolerating one that is already gone.

    A missing file during cleanup is not worth failing a request over: the row is the record,
    the file is a cache of it, and refusing to delete an avatar because its old file had
    already been removed would leave the user stuck with a picture they asked to replace.
    """
    if not relative:
        return
    try:
        absolute(relative).unlink(missing_ok=True)
    except (OSError, ValueError):
        logger.warning("Could not delete attachment file %r", relative, exc_info=True)
