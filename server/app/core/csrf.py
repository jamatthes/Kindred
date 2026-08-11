"""CSRF middleware (F-10).

Double-submit: the CSRF token is issued with the session, delivered in a readable cookie, and
must come back in the `X-CSRF-Token` header on every unsafe method. A cross-site attacker can
cause the browser to send the cookies but cannot read them, so it cannot produce the header.

Registered as **global middleware, not a per-route dependency**, deliberately: a route that
forgets a dependency is unprotected and nothing notices, whereas middleware cannot be
forgotten by the author of a new feature router.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import settings
from app.core.db import SessionFactory
from app.core.sessions import load_session
from app.schemas.common import CODE_CSRF_INVALID

logger = logging.getLogger(__name__)

CSRF_HEADER = "X-CSRF-Token"

#: Methods that do not change state. `OPTIONS` is included so CORS preflight works.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

#: Login is exempt because it is what *issues* the token — requiring one to obtain one is a
#: deadlock. It carries no privilege to abuse: it is rate-limited and needs the password.
EXEMPT_PATHS = frozenset({"/api/v1/auth/login"})


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method in SAFE_METHODS or request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        token = request.cookies.get(settings.session_cookie_name)
        if not token:
            # No session at all: not a CSRF problem. Let the route's auth dependency answer
            # with 401, so an expired session does not masquerade as a CSRF failure.
            return await call_next(request)

        async with SessionFactory() as db:
            session = await load_session(db, token)

        if session is None:
            return await call_next(request)

        supplied = request.headers.get(CSRF_HEADER, "")
        # Constant-time: the token is a secret, and a comparison that short-circuits leaks it
        # a character at a time.
        if not supplied or not hmac.compare_digest(supplied, session.csrf_token):
            logger.warning(
                "CSRF rejection: %s %s (header %s)",
                request.method,
                request.url.path,
                "absent" if not supplied else "mismatched",
            )
            return JSONResponse(
                status_code=403,
                content={
                    "detail": {
                        "code": CODE_CSRF_INVALID,
                        "message": "Your session token was missing or stale. Try again.",
                    }
                },
            )

        return await call_next(request)
