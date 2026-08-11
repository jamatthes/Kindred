"""`/api/v1/me` — the profile page's endpoints (F-7, and `families` FM-11 / FM-14).

Theme lives on `users.theme_pref`, not in `user_settings`, per `plan/architecture.md`. It
follows the user to any device, which is the whole point of storing it server-side rather
than in local storage.

**Nothing in this router carries a `require_stage` guard**, and that is deliberate rather
than an oversight. A name, a password, a theme and a face are account properties, not trip
data; freezing a trip must not freeze someone's face
(`plan/features/foundation/requirements.md` and `plan/features/families/requirements.md`
both list these as available in End). The avatar routes inherit the exemption for exactly
the reason the password endpoint has it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from app.deps import ActiveTrip, CurrentUser, DbDep, enforce_password_change, require_member
from app.models import Attachment
from app.routers.auth import build_user_out
from app.routers.families import broadcast_member_updated
from app.schemas.user import PreferencesIn, PreferencesOut, ProfilePatchIn, UserOut
from app.services import attachments as store
from app.services.images import (
    MAX_UPLOAD_BYTES,
    AvatarProcessorProtocol,
    file_too_large,
    get_avatar_processor,
)

router = APIRouter(
    prefix="/me",
    tags=["me"],
    dependencies=[Depends(enforce_password_change), Depends(require_member)],
)


@router.patch("", response_model=UserOut, summary="Update my own name")
async def update_profile(
    payload: ProfilePatchIn, db: DbDep, user: CurrentUser, trip: ActiveTrip
) -> UserOut:
    """FM-11. First name, last name and display name, editable at any time, in any stage.

    Changing a name changes the initials badge and the map label everywhere, live (FM-12) —
    which is why this emits `member.updated` through `families`' own helper rather than
    building a payload here. That helper owns the redaction the trip room requires.
    """
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(user, field, value.strip() if isinstance(value, str) else value)

    if not user.display_name.strip():
        # Emptying the display name would leave a person with no label anywhere. Fall back to
        # the derived form rather than refusing: they cleared a field, they did not ask for
        # an error.
        user.display_name = f"{user.first_name} {user.last_name}".strip()

    await db.commit()
    await db.refresh(user)
    # FM-12: "When someone changes their picture or name, their badge and map label update."
    # The payload is built by `families`, because that is where the redaction rule lives.
    await broadcast_member_updated(db, user.id, trip)
    return await build_user_out(db, user, trip)


@router.put("/avatar", response_model=UserOut, summary="Upload my profile picture")
async def upload_avatar(
    db: DbDep,
    user: CurrentUser,
    trip: ActiveTrip,
    file: UploadFile = File(..., description="JPEG, PNG or WebP, 8MB maximum"),
    processor: AvatarProcessorProtocol = Depends(get_avatar_processor),
) -> UserOut:
    """FM-14. Re-encoded server-side with **all metadata dropped, GPS included**.

    The old row and its files are deleted in the same transaction as the new ones are
    written, so a user has at most one avatar and the volume does not accumulate orphans.
    """
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise file_too_large()

    renditions = processor.process(raw)

    previous = (
        await db.get(Attachment, user.avatar_attachment_id)
        if user.avatar_attachment_id
        else None
    )

    full_path = f"{store.AVATAR_DIR}/{renditions.full.filename}"
    thumb_path = f"{store.AVATAR_DIR}/{renditions.thumb.filename}"
    store.write(full_path, renditions.full.data)
    store.write(thumb_path, renditions.thumb.data)

    attachment = Attachment(
        subject_type="user",
        subject_id=user.id,
        uploader_id=user.id,
        path=full_path,
        thumb_path=thumb_path,
        mime=renditions.mime,
        width=256,
        height=256,
        byte_size=renditions.full.size,
    )
    db.add(attachment)
    await db.flush()
    user.avatar_attachment_id = attachment.id

    if previous is not None:
        # Files first, row second: an orphaned row would keep serving a deleted file, whereas
        # a deleted file with its row already gone is simply absent.
        if previous.path != full_path:
            store.delete(previous.path)
        if previous.thumb_path != thumb_path:
            store.delete(previous.thumb_path)
        await db.delete(previous)

    await db.commit()
    await db.refresh(user)
    await broadcast_member_updated(db, user.id, trip)
    return await build_user_out(db, user, trip)


@router.delete("/avatar", response_model=UserOut, summary="Remove my profile picture")
async def delete_avatar(db: DbDep, user: CurrentUser, trip: ActiveTrip) -> UserOut:
    """Back to the initials badge. Reversible by uploading again, so the UI uses an undo
    toast rather than a confirm."""
    attachment = (
        await db.get(Attachment, user.avatar_attachment_id)
        if user.avatar_attachment_id
        else None
    )
    user.avatar_attachment_id = None
    if attachment is not None:
        store.delete(attachment.path)
        store.delete(attachment.thumb_path)
        await db.delete(attachment)
    await db.commit()
    await db.refresh(user)
    await broadcast_member_updated(db, user.id, trip)
    return await build_user_out(db, user, trip)


@router.get("/preferences", response_model=PreferencesOut, summary="My preferences")
async def read_preferences(user: CurrentUser) -> PreferencesOut:
    return PreferencesOut.model_validate(user)


@router.patch("/preferences", response_model=PreferencesOut, summary="Update my preferences")
async def update_preferences(
    payload: PreferencesIn, db: DbDep, user: CurrentUser
) -> PreferencesOut:
    # PATCH semantics: an omitted field is left alone, which is not the same as being set to
    # null. `exclude_unset` is what draws that distinction.
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return PreferencesOut.model_validate(user)
