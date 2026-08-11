"""TEMPORARY probe routes — Phase 5 of `plan/features/foundation/tasks.md`.

!!! DELETE THIS FILE AT THE END OF PHASE 8 !!!
(and its `include_router` line in `app/main.py`, and `tests/test_deps.py`'s use of it)

Each route is guarded by exactly one permission dependency and does nothing else, so
`tests/test_deps.py` can test the dependencies in isolation rather than through whichever
feature route happens to use them. Once real feature routers exist, they are the better
subject and these go away.

They are not a back door: each one is *more* restricted than the feature routes it stands in
for, and none of them reads or writes anything.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import (
    enforce_password_change,
    require_main_admin,
    require_member,
    require_stage,
)

router = APIRouter(
    prefix="/_probe",
    tags=["_probe (temporary)"],
    include_in_schema=False,
    # Same router-level guard every non-auth router carries, so the probes also verify that
    # the must-change-password interceptor is inherited rather than remembered.
    dependencies=[Depends(enforce_password_change)],
)


@router.get("/member", dependencies=[Depends(require_member)])
async def probe_member() -> dict[str, bool]:
    return {"ok": True}


@router.get("/main-admin", dependencies=[Depends(require_main_admin)])
async def probe_main_admin() -> dict[str, bool]:
    return {"ok": True}


@router.get(
    "/stage", dependencies=[Depends(require_stage("planning", "holiday"))]
)
async def probe_stage() -> dict[str, bool]:
    return {"ok": True}


@router.post("/csrf")
async def probe_csrf() -> dict[str, bool]:
    """An unsafe method with no guard but the router's, for exercising CSRF middleware."""
    return {"ok": True}
