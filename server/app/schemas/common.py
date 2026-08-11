"""The shared error envelope, used by every router in the project.

```
{"detail": {"code": "password_change_required", "message": "Change your password to continue."}}
```

The machine-readable `code` is the contract: the web client branches on it (route to the
password screen, retry once after `csrf_invalid`, show the archive banner on
`stage_forbidden`). `message` is for humans and may be reworded freely; `code` may not.
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str = Field(description="Stable machine-readable code. Clients branch on this.")
    message: str = Field(description="Human-readable message. Safe to show to a user.")


class ErrorOut(BaseModel):
    """The response body of every non-2xx response."""

    detail: ErrorDetail


class ApiError(HTTPException):
    """An ``HTTPException`` whose detail is already the envelope's inner object.

    Raise this rather than ``HTTPException`` so the code is explicit at the raise site.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail={"code": code, "message": message},
            headers=headers,
        )


# --- The codes introduced by foundation -------------------------------------------------
# Later features add their own; these are the ones every feature can rely on existing.

CODE_INVALID_CREDENTIALS = "invalid_credentials"  # 401
CODE_RATE_LIMITED = "rate_limited"  # 429
CODE_PASSWORD_CHANGE_REQUIRED = "password_change_required"  # 403
CODE_CSRF_INVALID = "csrf_invalid"  # 403
CODE_NOT_AUTHENTICATED = "not_authenticated"  # 401
CODE_FORBIDDEN = "forbidden"  # 403
CODE_STAGE_FORBIDDEN = "stage_forbidden"  # 409
CODE_VALIDATION_ERROR = "validation_error"  # 422
CODE_PASSWORD_UNCHANGED = "password_unchanged"  # 400
CODE_DB_UNAVAILABLE = "db_unavailable"  # 503

#: Reused so the wording of the login failure is identical for every cause (F-3): a wrong
#: password and a non-existent username must be indistinguishable.
INVALID_CREDENTIALS_MESSAGE = "Incorrect username or password"


def not_authenticated() -> ApiError:
    return ApiError(401, CODE_NOT_AUTHENTICATED, "Sign in to continue.")


def forbidden(message: str = "You do not have access to this.") -> ApiError:
    return ApiError(403, CODE_FORBIDDEN, message)


def invalid_credentials() -> ApiError:
    return ApiError(401, CODE_INVALID_CREDENTIALS, INVALID_CREDENTIALS_MESSAGE)
