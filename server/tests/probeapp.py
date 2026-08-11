"""A test-only app exposing one route per permission dependency.

Phase 5 shipped these as real `/_probe` routes in the served app; Phase 8 removed them, as
planned. The *coverage* must not go with them: `require_stage` and `require_family_admin`
have no feature route to exercise them until M1 features land, and a dependency with no
allow/deny test is exactly what F-9 forbids.

So the routes now live here instead. The app is built with the production `create_app()`, so
the CSRF middleware, the exception handlers and the router-level guards under test are the
real ones — only the four leaf routes are local to the suite, and nothing that ships can
reach them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI

from app.deps import (
    enforce_password_change,
    require_main_admin,
    require_member,
    require_stage,
)
from app.main import API_PREFIX, create_app

router = APIRouter(
    prefix="/_probe",
    tags=["_probe (tests only)"],
    # The same router-level guard every non-auth router carries, so these also prove the
    # must-change-password interceptor is inherited rather than remembered per route.
    dependencies=[Depends(enforce_password_change)],
)

MEMBER = f"{API_PREFIX}/_probe/member"
MAIN_ADMIN = f"{API_PREFIX}/_probe/main-admin"
STAGE = f"{API_PREFIX}/_probe/stage"
CSRF = f"{API_PREFIX}/_probe/csrf"


@router.get("/member", dependencies=[Depends(require_member)])
async def probe_member() -> dict[str, bool]:
    return {"ok": True}


@router.get("/main-admin", dependencies=[Depends(require_main_admin)])
async def probe_main_admin() -> dict[str, bool]:
    return {"ok": True}


@router.get("/stage", dependencies=[Depends(require_stage("planning", "holiday"))])
async def probe_stage() -> dict[str, bool]:
    return {"ok": True}


@router.post("/csrf")
async def probe_csrf() -> dict[str, bool]:
    """An unsafe method carrying no guard but the router's, to exercise CSRF middleware."""
    return {"ok": True}


def build_probe_app() -> FastAPI:
    """The production app plus the probe routes."""
    app = create_app()
    app.include_router(router, prefix=API_PREFIX)
    return app
