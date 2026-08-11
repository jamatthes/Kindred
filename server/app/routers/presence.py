"""`GET /api/v1/presence` — who is online right now.

Presence is ephemeral and never persisted (`plan/architecture.md`): the socket registry is
the only source of truth. This endpoint exists so a page can render the family avatar stack
on first paint, before any `presence.updated` event has had a reason to fire.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import ActiveTrip, enforce_password_change, require_member
from app.ws import registry

router = APIRouter(
    tags=["presence"],
    dependencies=[Depends(enforce_password_change), Depends(require_member)],
)


class PresenceOut(BaseModel):
    online_user_ids: list[str]


@router.get("/presence", response_model=PresenceOut, summary="User ids currently connected")
async def read_presence(trip: ActiveTrip) -> PresenceOut:
    trip_id = trip.id if trip else None
    return PresenceOut(
        online_user_ids=sorted(str(uid) for uid in registry.online_user_ids(trip_id))
    )
