"""`GET /api/v1/settings` — the public subset (F-12).

Readable before login, because the login screen shows the instance name as its heading so a
self-hoster sees their own name before authenticating. Only these three keys are exposed
here; every other key requires the main admin and belongs to `admin-console`.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.core.db import get_db
from app.deps import DbDep
from app.models import (
    SETTING_INSTANCE_NAME,
    SETTING_INVITE_ONLY,
    SETTING_REGISTRATION_OPEN,
    Setting,
)
from app.schemas.auth import SettingsOut

router = APIRouter(tags=["settings"])

#: The allowlist. A key not named here can never leak through this endpoint, however the
#: settings table grows.
PUBLIC_KEYS = (SETTING_INSTANCE_NAME, SETTING_REGISTRATION_OPEN, SETTING_INVITE_ONLY)

_FALLBACKS: dict[str, object] = {
    SETTING_INSTANCE_NAME: "Kindred",
    SETTING_REGISTRATION_OPEN: False,
    SETTING_INVITE_ONLY: True,
}


@router.get("/settings", response_model=SettingsOut, summary="Public platform settings")
async def read_settings(db: DbDep) -> SettingsOut:
    rows = (
        await db.execute(select(Setting).where(Setting.key.in_(PUBLIC_KEYS)))
    ).scalars().all()
    values = {**_FALLBACKS, **{row.key: row.value for row in rows}}
    return SettingsOut(
        instance_name=str(values[SETTING_INSTANCE_NAME]),
        registration_open=bool(values[SETTING_REGISTRATION_OPEN]),
        invite_only=bool(values[SETTING_INVITE_ONLY]),
    )
