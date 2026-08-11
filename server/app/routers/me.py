"""`/api/v1/me/preferences` — the user's own theme and locale (F-7).

Theme lives on `users.theme_pref`, not in `user_settings`, per `plan/architecture.md`. It
follows the user to any device, which is the whole point of storing it server-side rather
than in local storage.

These are account operations, not trip data, so they carry **no** `require_stage` guard:
changing your theme must keep working after a trip is archived
(`plan/features/foundation/requirements.md` > Stage availability — the exemption is
deliberate and must be preserved).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import DbDep, CurrentUser, enforce_password_change, require_member
from app.schemas.user import PreferencesIn, PreferencesOut

router = APIRouter(
    prefix="/me",
    tags=["me"],
    dependencies=[Depends(enforce_password_change), Depends(require_member)],
)


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
